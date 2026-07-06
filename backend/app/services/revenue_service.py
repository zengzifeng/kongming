from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import select

from ..extensions import db
from ..integrations import monitoring_client
from ..models import (
    MetricSnapshot,
    Policy,
    PolicyAction,
    PolicyStatus,
    RevenueAttribution,
)
from ..models.metric_snapshot import SnapshotPhase
from ..models.revenue_attribution import RevenueMechanism
from ..utils.errors import NotFound
from ..utils.time import utcnow


WINDOW_MINUTES = 30


class RevenueService:
    def schedule_before_snapshot(self, policy: Policy) -> MetricSnapshot:
        return self.collect_snapshot(policy.id, phase=SnapshotPhase.BEFORE)

    def collect_snapshot(self, policy_id: int, phase: str) -> MetricSnapshot:
        policy = db.session.get(Policy, policy_id)
        if not policy:
            raise NotFound("策略不存在", details={"id": policy_id})
        now = utcnow()
        snapshot = monitoring_client().tpm_series(window_minutes=WINDOW_MINUTES)
        tpm_self = sum(p.tpm_self for p in snapshot.points) / max(len(snapshot.points), 1)
        tpm_vendor = sum(p.tpm_vendor for p in snapshot.points) / max(len(snapshot.points), 1)
        cache = sum(p.cache_hit_rate for p in snapshot.points) / max(len(snapshot.points), 1)
        utilization = sum(p.gpu_utilization for p in snapshot.points) / max(len(snapshot.points), 1)

        unit_revenue = 0.0014
        unit_cost_self = 0.0007
        unit_cost_vendor = 0.0009

        record = MetricSnapshot(
            policy_id=policy.id,
            phase=phase,
            window_start=now - timedelta(minutes=WINDOW_MINUTES),
            window_end=now,
            tpm_self=tpm_self,
            tpm_vendor=tpm_vendor,
            revenue=(tpm_self + tpm_vendor) * unit_revenue * WINDOW_MINUTES,
            cost_self=tpm_self * unit_cost_self * WINDOW_MINUTES,
            cost_vendor=tpm_vendor * unit_cost_vendor * WINDOW_MINUTES,
            cache_hit_rate=cache,
            gpu_utilization=utilization,
            raw_json={"window_minutes": WINDOW_MINUTES},
        )
        db.session.add(record)
        db.session.flush()
        return record

    def compute_attribution(self, policy_id: int) -> list[RevenueAttribution]:
        policy = db.session.get(Policy, policy_id)
        if not policy:
            raise NotFound("策略不存在", details={"id": policy_id})

        before = db.session.execute(
            select(MetricSnapshot).where(
                MetricSnapshot.policy_id == policy_id,
                MetricSnapshot.phase == SnapshotPhase.BEFORE,
            ).order_by(MetricSnapshot.id.desc()).limit(1)
        ).scalar_one_or_none()
        after = db.session.execute(
            select(MetricSnapshot).where(
                MetricSnapshot.policy_id == policy_id,
                MetricSnapshot.phase == SnapshotPhase.AFTER,
            ).order_by(MetricSnapshot.id.desc()).limit(1)
        ).scalar_one_or_none()

        if not before or not after:
            return []

        mechanism = (
            RevenueMechanism.PEAK_SHAVING
            if policy.algorithm == "realtime"
            else RevenueMechanism.OFF_PEAK_ADJUST
        )

        revenue_delta = float(after.revenue) - float(before.revenue)
        cost_delta = (
            float(after.cost_self) + float(after.cost_vendor)
            - float(before.cost_self) - float(before.cost_vendor)
        )

        node_move_cost = sum(
            float(a.expected_gain) for a in db.session.execute(
                select(PolicyAction).where(
                    PolicyAction.policy_id == policy_id,
                    PolicyAction.action_type == "node_move",
                )
            ).scalars()
        )
        margin_delta = revenue_delta - cost_delta - node_move_cost

        projects = self._project_split(policy)
        rows: list[RevenueAttribution] = []
        for code, ratio, name in projects:
            row = RevenueAttribution(
                policy_id=policy.id,
                mechanism=mechanism,
                project_code=code,
                project_name=name,
                revenue_delta=revenue_delta * ratio,
                cost_delta=cost_delta * ratio,
                margin_delta=margin_delta * ratio,
                allocation_ratio=ratio,
                computed_at=utcnow(),
            )
            db.session.add(row)
            rows.append(row)
        db.session.flush()
        return rows

    def _project_split(self, policy: Policy) -> list[tuple[str, float, str]]:
        actions = db.session.execute(
            select(PolicyAction).where(PolicyAction.policy_id == policy.id,
                                       PolicyAction.action_type == "model_assign")
        ).scalars().all()
        if not actions:
            return [("DEFAULT", 1.0, "默认项目")]
        weight = 1.0 / len(actions)
        return [
            (
                a.payload_json.get("report_id", f"P{a.id}"),
                weight,
                a.payload_json.get("project_name", a.payload_json.get("model", "未命名")),
            )
            for a in actions
        ]

    def process_due_after_snapshots(self) -> int:
        now = utcnow()
        due_policies = db.session.execute(
            select(Policy).where(
                Policy.status == PolicyStatus.ACCEPTED,
                Policy.effective_from.isnot(None),
                Policy.effective_from <= now - timedelta(minutes=WINDOW_MINUTES),
            )
        ).scalars().all()

        processed = 0
        for policy in due_policies:
            has_after = db.session.execute(
                select(MetricSnapshot).where(
                    MetricSnapshot.policy_id == policy.id,
                    MetricSnapshot.phase == SnapshotPhase.AFTER,
                ).limit(1)
            ).scalar_one_or_none()
            if has_after:
                continue
            self.collect_snapshot(policy.id, SnapshotPhase.AFTER)
            self.compute_attribution(policy.id)
            processed += 1
        if processed:
            db.session.commit()
        return processed
