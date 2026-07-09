from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from sqlalchemy import select

from ..algorithms import build_snapshot, get_solver
from ..algorithms.base import PolicyInputSnapshot, PolicyResult
from ..algorithms.usage_demand_source import build_usage_demand_items
from ..extensions import db
from ..models import (
    Demand,
    Policy,
    PolicyAction,
    PolicyRun,
    PolicyStatus,
)
from ..models.policy_run import PolicyRunStatus
from ..utils.errors import AlgorithmError, NotFound, StateConflict, ValidationFailed
from ..utils.time import utcnow


class PolicyService:
    def submit_run(self, algorithm: str, demand_ids: list[int] | None = None,
                   params: dict | None = None, triggered_by: str = "manual") -> PolicyRun:
        # 默认（无 demand_ids）：从实跑量 + 平台定价主数据实时构建需求。
        # demand_ids 有值：手动/报备路径，从 demands 表按 id 取（前端指定新增客户需求评估时用）。
        if demand_ids:
            demands = self._load_demands(demand_ids)
            if not demands:
                raise ValidationFailed("指定的需求不存在或不可用")
            snapshot = build_snapshot(algorithm=algorithm, demands=demands, params=params)
        else:
            demand_items = build_usage_demand_items()
            if not demand_items:
                raise ValidationFailed("没有可用的实跑量需求用于测算")
            snapshot = build_snapshot(
                algorithm=algorithm, demand_items=demand_items, params=params,
                enrich_cluster_redundancy=True,
            )

        snapshot_dict = snapshot.to_dict()
        input_hash = hashlib.sha256(
            json.dumps(snapshot_dict, sort_keys=True,
                       ensure_ascii=False).encode()
        ).hexdigest()

        now = utcnow()
        run = PolicyRun(
            run_no="PR" + now.strftime("%Y%m%d%H%M%S%f")[:-3],
            triggered_by=triggered_by,
            algorithm=algorithm,
            input_snapshot_json=snapshot_dict,
            input_hash=input_hash,
            status=PolicyRunStatus.QUEUED,
        )
        db.session.add(run)
        db.session.flush()

        self._execute(run, snapshot)
        return run

    def _load_demands(self, demand_ids: list[int]) -> list[Demand]:
        # 手动/报备路径：仅按显式 id 取 demands 表（不再默认扫全表已审批需求）。
        stmt = select(Demand).where(Demand.id.in_(demand_ids))
        return list(db.session.execute(stmt).scalars())

    def _execute(self, run: PolicyRun, snapshot: PolicyInputSnapshot):
        solver = get_solver(snapshot.algorithm)
        run.status = PolicyRunStatus.RUNNING
        run.started_at = utcnow()
        try:
            result = solver.solve(snapshot)
        except AlgorithmError as exc:
            run.status = PolicyRunStatus.FAILED
            run.finished_at = utcnow()
            run.error_message = str(exc)
            run.duration_ms = int(
                (run.finished_at - run.started_at).total_seconds() * 1000
            )
            db.session.flush()
            return
        except Exception as exc:  # 兜底
            run.status = PolicyRunStatus.FAILED
            run.finished_at = utcnow()
            run.error_message = f"未知算法错误: {exc}"
            db.session.flush()
            raise

        self._persist_policy(run, result)
        run.status = PolicyRunStatus.SUCCESS
        run.finished_at = utcnow()
        run.duration_ms = int(
            (run.finished_at - run.started_at).total_seconds() * 1000)
        db.session.flush()

    def _persist_policy(self, run: PolicyRun, result: PolicyResult):
        now = utcnow()
        policy = Policy(
            policy_run_id=run.id,
            policy_no="P" + now.strftime("%Y%m%d%H%M%S%f")[:-3],
            algorithm=run.algorithm,
            summary_json=result.summary,
            expected_revenue_gain=result.expected_revenue_gain,
            expected_peak_shaving_gain=result.expected_peak_shaving_gain,
            expected_off_peak_gain=result.expected_off_peak_gain,
            constraints_json={
                "items": [c.__dict__ for c in result.constraints]},
            status=PolicyStatus.DRAFT,
        )
        db.session.add(policy)
        db.session.flush()
        for action in result.actions:
            db.session.add(PolicyAction(
                policy_id=policy.id,
                action_type=action.action_type,
                payload_json=action.payload,
                expected_gain=action.expected_gain,
            ))
        db.session.flush()

    def get_run(self, run_id: int) -> PolicyRun:
        run = db.session.get(PolicyRun, run_id)
        if not run:
            raise NotFound("策略测算任务不存在", details={"id": run_id})
        return run

    def get_policy(self, policy_id: int) -> Policy:
        policy = db.session.get(Policy, policy_id)
        if not policy:
            raise NotFound("策略不存在", details={"id": policy_id})
        return policy

    def patch(self, policy_id: int, patch: dict) -> Policy:
        policy = self.get_policy(policy_id)
        if policy.status in (PolicyStatus.CANCELLED, PolicyStatus.EXPIRED):
            raise StateConflict("策略状态不可修改", details={"status": policy.status})
        allowed = {
            "summary_json",
            "constraints_json",
            "expected_revenue_gain",
            "expected_peak_shaving_gain",
            "expected_off_peak_gain",
            "effective_from",
            "effective_to",
        }
        for key, value in patch.items():
            if key in allowed:
                setattr(policy, key, value)
        db.session.flush()
        return policy

    def accept(self, policy_id: int, operator: str, effective_from: datetime | None = None,
               comment: str | None = None) -> Policy:
        policy = self.get_policy(policy_id)
        if policy.status != PolicyStatus.DRAFT:
            raise StateConflict("策略状态不可采纳", details={"status": policy.status})
        policy.status = PolicyStatus.ACCEPTED
        policy.accepted_by = operator
        policy.accepted_at = utcnow()
        policy.effective_from = effective_from or utcnow()
        policy.effective_to = policy.effective_from + timedelta(hours=2)
        db.session.flush()

        from .revenue_service import RevenueService
        RevenueService().schedule_before_snapshot(policy)
        return policy

    def recalculate(self, policy_id: int, params: dict | None = None) -> PolicyRun:
        policy = self.get_policy(policy_id)
        if policy.status not in (PolicyStatus.DRAFT, PolicyStatus.RECALCULATING):
            raise StateConflict("策略状态不可重算", details={"status": policy.status})
        policy.status = PolicyStatus.RECALCULATING
        db.session.flush()
        old_run = db.session.get(PolicyRun, policy.policy_run_id)
        demand_ids = self._demand_ids_from_snapshot(
            old_run.input_snapshot_json or {})
        return self.submit_run(policy.algorithm, demand_ids=demand_ids, params=params,
                               triggered_by="recalculate")

    def cancel(self, policy_id: int, operator: str, reason: str) -> Policy:
        policy = self.get_policy(policy_id)
        if policy.status in (PolicyStatus.CANCELLED, PolicyStatus.EXPIRED):
            raise StateConflict("策略已结束", details={"status": policy.status})
        policy.status = PolicyStatus.CANCELLED
        policy.cancel_reason = reason
        db.session.flush()
        return policy

    @staticmethod
    def _demand_ids_from_snapshot(snapshot_dict: dict) -> list[int]:
        report_ids = [d["report_id"] for d in snapshot_dict.get("demands", [])]
        if not report_ids:
            return []
        from sqlalchemy import select
        rows = db.session.execute(
            select(Demand.id).where(Demand.report_id.in_(report_ids))
        ).all()
        return [r[0] for r in rows]
