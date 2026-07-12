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

    def dashboard(self) -> dict:
        policies = db.session.execute(
            select(Policy)
            .where(Policy.status == PolicyStatus.ACCEPTED, Policy.algorithm == "time_period")
            .order_by(Policy.id.desc())
        ).scalars().all()

        idle: list[dict] = []
        busy: list[dict] = []
        peak_shaving: list[dict] = []
        for policy in policies:
            period_rows = self._time_period_dashboard_rows(policy)
            if self._time_period_kind(policy) == "idle":
                idle.extend(period_rows)
            else:
                busy.extend(period_rows)
            peak_shaving.extend(self._peak_shaving_dashboard_rows(policy))

        return {
            "generated_at": utcnow().isoformat(),
            "idle": idle,
            "busy": busy,
            "peak_shaving": peak_shaving,
        }

    def _time_period_kind(self, policy: Policy) -> str:
        summary = policy.summary_json or {}
        module = summary.get("module")
        template = summary.get("template")
        text = str(summary)
        if module == "idle" or template in {"闲时策略", "闲忙时策略"} or "闲时" in text:
            return "idle"
        if float(policy.expected_off_peak_gain or 0) > 0:
            return "idle"
        return "busy"

    def _time_period_dashboard_rows(self, policy: Policy) -> list[dict]:
        summary = policy.summary_json or {}
        customers = self._dict_list(summary.get("accepted_customers"))
        if not customers:
            customers = [{"report_id": policy.policy_no, "customer_code": policy.policy_no, "model": policy.algorithm}]
        total_gain = float(policy.expected_off_peak_gain or policy.expected_revenue_gain or 0)
        per_gain = total_gain / max(len(customers), 1)
        rows = []
        for index, customer in enumerate(customers, start=1):
            unit_self_revenue = self._number(customer.get("unit_self_revenue"))
            rows.append({
                "id": policy.id * 1000 + index,
                "date": self._policy_date(policy),
                "customer_name": customer.get("customer_code") or customer.get("report_id") or policy.policy_no,
                "model_name": customer.get("model") or customer.get("model_name") or policy.algorithm,
                "sale_discount": 0,
                "purchase_discount": 0,
                "self_incremental_revenue": per_gain,
                "vendor_cost_reduction": 0,
                "total_revenue": per_gain,
                "price_per_million_tokens": unit_self_revenue * 1_000_000,
            })
        return rows

    def _peak_shaving_dashboard_rows(self, policy: Policy) -> list[dict]:
        summary = policy.summary_json or {}
        rebalance = summary.get("model_rebalance") if isinstance(summary.get("model_rebalance"), dict) else {}
        moves = self._dict_list(summary.get("node_moves")) + self._dict_list(rebalance.get("moves"))
        total_gain = float(policy.expected_peak_shaving_gain or 0)
        if not moves and total_gain <= 0:
            return []
        if not moves:
            moves = [{"from_cluster": policy.policy_no, "to_cluster": policy.policy_no, "model": policy.algorithm}]
        per_gain = total_gain / max(len(moves), 1)
        machines_before = summary.get("machines_before") if isinstance(summary.get("machines_before"), dict) else {}
        machines_after = summary.get("machines_after") if isinstance(summary.get("machines_after"), dict) else {}
        rows = []
        for index, move in enumerate(moves, start=1):
            source = str(move.get("from_cluster") or policy.policy_no)
            target = str(move.get("to_cluster") or "-")
            removed_tpm = self._number(move.get("removed_tpm"))
            added_tpm = self._number(move.get("added_tpm"))
            before_tpm = max(removed_tpm, added_tpm)
            gain = self._number(move.get("gain_yuan_day"), self._number(move.get("gain"), per_gain))
            rows.append({
                "id": policy.id * 1000 + index,
                "date": self._policy_date(policy),
                "customer_name": move.get("reason") or f"{source}->{target}",
                "model_name": move.get("model") or policy.algorithm,
                "peak_tpm_before": before_tpm,
                "peak_watermark": (added_tpm / before_tpm) if before_tpm else 0,
                "saved_tpm": max(removed_tpm - added_tpm, 0),
                "machines_before": self._number(machines_before.get(source)),
                "machines_after": self._number(machines_after.get(source)),
                "self_cost_reduction": 0,
                "vendor_cost_increase": 0,
                "directed_shift_revenue": gain,
            })
        return rows

    def _policy_date(self, policy: Policy) -> str:
        value = policy.effective_from or policy.accepted_at or getattr(policy, "created_at", None) or utcnow()
        return value.date().isoformat() if hasattr(value, "date") else str(value)

    def _dict_list(self, value) -> list[dict]:
        return [item for item in (value or []) if isinstance(item, dict)] if isinstance(value, list) else []

    def _number(self, value, fallback: float = 0.0) -> float:
        try:
            return float(value if value is not None else fallback)
        except (TypeError, ValueError):
            return fallback

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
