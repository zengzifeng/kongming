from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta

from ..algorithms import build_run_snapshot, get_solver
from ..algorithms.base import PolicyInputSnapshot, PolicyResult
from ..extensions import db
from ..models import (
    Demand,
    Policy,
    PolicyAction,
    PolicyAuditAction,
    PolicyAuditLog,
    PolicyRun,
    PolicyStatus,
)
from ..models.policy_run import PolicyRunStatus
from ..utils.errors import AlgorithmError, NotFound, StateConflict
from ..utils.time import utcnow


class PolicyService:
    def submit_run(self, algorithm: str, demand_ids: list[int] | None = None,
                   params: dict | None = None, triggered_by: str = "manual",
                   demand_id: int | None = None) -> PolicyRun:
        # 输入取数分路（demand_ids vs 实跑量）已下沉到 algorithms.build_run_snapshot，
        # 策略侧只负责：注入再平衡开关 → 建 snapshot → 落 run → 执行。
        # demand_id：需求评估触发的策略归属，写入 Policy.demand_id；NULL=人工/定时触发的全局策略。
        # 注入模型级再平衡开关（solver 从 snapshot.params 读，避免 solver 依赖 Flask config）。
        from flask import current_app

        params = dict(params or {})
        params.setdefault(
            "enable_model_rebalance",
            current_app.config.get("MODEL_REBALANCE_ENABLED", True),
        )
        snapshot = build_run_snapshot(algorithm=algorithm, demand_ids=demand_ids, params=params)

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

        self._execute(run, snapshot, demand_id=demand_id)
        return run

    def _execute(self, run: PolicyRun, snapshot: PolicyInputSnapshot, demand_id: int | None = None):
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

        self._persist_policy(run, result, demand_id=demand_id)
        run.status = PolicyRunStatus.SUCCESS
        run.finished_at = utcnow()
        run.duration_ms = int(
            (run.finished_at - run.started_at).total_seconds() * 1000)
        db.session.flush()

    def _persist_policy(self, run: PolicyRun, result: PolicyResult, demand_id: int | None = None):
        now = utcnow()
        policy = Policy(
            policy_run_id=run.id,
            demand_id=demand_id,
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

    def patch(self, policy_id: int, patch: dict, operator: str = "system") -> Policy:
        policy = self.get_policy(policy_id)
        # 仅 DRAFT 可改：已采纳/已取消的策略不允许静默改数（避免生效策略被无痕修改）。
        if policy.status != PolicyStatus.DRAFT:
            raise StateConflict("仅草稿状态策略可修改", details={"status": policy.status})
        allowed = {
            "summary_json",
            "constraints_json",
            "expected_revenue_gain",
            "expected_peak_shaving_gain",
            "expected_off_peak_gain",
            "effective_from",
            "effective_to",
        }
        before = {}
        after = {}
        for key, value in patch.items():
            if key in allowed:
                before[key] = self._jsonable(getattr(policy, key))
                setattr(policy, key, value)
                after[key] = self._jsonable(value)
        self._audit(policy.id, PolicyAuditAction.PATCH, operator,
                    before_json=before, after_json=after)
        db.session.flush()
        return policy

    def accept(self, policy_id: int, operator: str, effective_from: datetime | None = None,
               comment: str | None = None) -> Policy:
        policy = self.get_policy(policy_id)
        if policy.status != PolicyStatus.DRAFT:
            raise StateConflict("策略状态不可采纳", details={"status": policy.status})
        before = {"status": policy.status}
        policy.status = PolicyStatus.ACCEPTED
        policy.accepted_by = operator
        policy.accepted_at = utcnow()
        policy.effective_from = effective_from or utcnow()
        policy.effective_to = policy.effective_from + timedelta(hours=2)
        self._audit(policy.id, PolicyAuditAction.ACCEPT, operator, comment=comment,
                    before_json=before,
                    after_json={"status": policy.status,
                                "effective_from": self._jsonable(policy.effective_from)})
        db.session.flush()

        from .revenue_service import RevenueService
        RevenueService().schedule_before_snapshot(policy)
        return policy

    def recalculate(self, policy_id: int, params: dict | None = None,
                    operator: str = "system") -> PolicyRun:
        # 重算 = 用同一批需求重新取数跑一次，生成新的 run + DRAFT 策略。
        # 旧策略保持原状（DRAFT 不变），是否取消由人工另行触发。
        policy = self.get_policy(policy_id)
        if policy.status != PolicyStatus.DRAFT:
            raise StateConflict("仅草稿状态策略可重算", details={"status": policy.status})
        old_run = db.session.get(PolicyRun, policy.policy_run_id)
        demand_ids = self._demand_ids_from_snapshot(
            old_run.input_snapshot_json or {})
        run = self.submit_run(policy.algorithm, demand_ids=demand_ids, params=params,
                              triggered_by="recalculate", demand_id=policy.demand_id)
        self._audit(policy.id, PolicyAuditAction.RECALCULATE, operator,
                    after_json={"new_run_id": run.id, "new_run_no": run.run_no})
        db.session.flush()
        return run

    def cancel(self, policy_id: int, operator: str, reason: str) -> Policy:
        policy = self.get_policy(policy_id)
        if policy.status == PolicyStatus.CANCELLED:
            raise StateConflict("策略已取消", details={"status": policy.status})
        before = {"status": policy.status}
        policy.status = PolicyStatus.CANCELLED
        policy.cancel_reason = reason
        self._audit(policy.id, PolicyAuditAction.CANCEL, operator, comment=reason,
                    before_json=before, after_json={"status": policy.status})
        db.session.flush()
        return policy

    def _audit(self, policy_id: int, action: str, operator: str, *,
               comment: str | None = None, before_json: dict | None = None,
               after_json: dict | None = None) -> None:
        db.session.add(PolicyAuditLog(
            policy_id=policy_id,
            action=action,
            operator=operator or "system",
            comment=comment,
            before_json=before_json or {},
            after_json=after_json or {},
        ))

    @staticmethod
    def _jsonable(value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

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
