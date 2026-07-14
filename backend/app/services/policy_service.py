from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from decimal import Decimal


from sqlalchemy import select

from ..algorithms import build_run_snapshot, get_solver
from ..algorithms.base import PolicyInputSnapshot, PolicyResult
from ..extensions import db
from ..models import (
    Demand,
    DemandStatus,
    Evaluation,
    EvaluationStatus,
    Policy,
    PolicyAction,
    PolicyAuditAction,
    PolicyAuditLog,
    PolicyRun,
    PolicyStatus,
)

from ..models.policy_run import PolicyRunStatus
from ..utils.errors import AlgorithmError, NotFound, StateConflict, ValidationFailed
from ..utils.time import utcnow


class PolicyService:
    def submit_run(self, algorithm: str, demand_ids: list[int] | None = None,
                   params: dict | None = None, triggered_by: str = "manual",
                   demand_id: int | None = None) -> PolicyRun:
        # 输入取数分路（demand_ids vs 实跑量）已下沉到 algorithms.build_run_snapshot，
        # 策略侧只负责：注入再平衡开关 → (需求评估额外注入评估参数) → 建 snapshot → 落 run → 执行。
        # demand_id：需求评估触发的策略归属，写入 Policy.demand_id；NULL=人工/定时触发的全局策略。
        # 注入模型级再平衡开关（solver 从 snapshot.params 读，避免 solver 依赖 Flask config）。
        from flask import current_app

        params = dict(params or {})
        params.setdefault(
            "enable_model_rebalance",
            current_app.config.get("MODEL_REBALANCE_ENABLED", True),
        )

        # 需求评估算法：solver 需要 evaluations / demand_id_by_report_id 参数，
        # build_run_snapshot 不感知评估语义，因此在这里先加载评估需求并注入参数。
        if algorithm == "demand_evaluation":
            demands = self._load_demands(demand_ids) if demand_ids else self._load_demand_evaluation_demands()
            if not demands:
                raise ValidationFailed("指定的需求不存在或不可用")
            demand_ids = [d.id for d in demands]
            self._inject_evaluation_params(params, demands)

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

        self._execute(run, snapshot, demand_id=demand_id,
                      scenario=self._resolve_scenario(algorithm, params))
        return run

    @staticmethod
    def _resolve_scenario(algorithm: str, params: dict | None) -> str:
        """策略场景标记：demand_evaluation / idle / busy。优先取前端传入的 module。"""
        module = (params or {}).get("module")
        if module in ("demand_evaluation", "idle", "busy"):
            return module
        if algorithm == "time_period":
            return "busy"  # time_period 未指定时段时默认归忙时
        return "demand_evaluation"

    def _load_demands(self, demand_ids: list[int]) -> list[Demand]:
        # 手动/报备路径：仅按显式 id 取 demands 表（不再默认扫全表已审批需求）。
        stmt = select(Demand).where(Demand.id.in_(demand_ids))
        return list(db.session.execute(stmt).scalars())

    def _load_demand_evaluation_demands(self) -> list[Demand]:
        stmt = (
            select(Demand)
            .join(Evaluation, Evaluation.demand_id == Demand.id)
            .where(Demand.status.in_([
                DemandStatus.EVALUATING,
                DemandStatus.AWAITING_APPROVAL,
            ]))
            .distinct()
        )
        return list(db.session.execute(stmt).scalars())

    def _inject_evaluation_params(self, params: dict, demands: list[Demand]):
        demand_ids = [d.id for d in demands]
        params["demand_id_by_report_id"] = {d.report_id: d.id for d in demands}
        latest_ids = (
            select(db.func.max(Evaluation.id).label("id"))
            .where(Evaluation.demand_id.in_(demand_ids))
            .group_by(Evaluation.demand_id)
            .subquery()
        )
        rows = db.session.execute(
            select(Evaluation).join(latest_ids, Evaluation.id == latest_ids.c.id)
        ).scalars().all()
        params["evaluations"] = [
            {
                "id": row.id,
                "demand_id": row.demand_id,
                "feasibility_score": float(row.feasibility_score or 0),
                "customer_value_score": float(row.customer_value_score or 0),
                "expected_revenue": float(row.expected_revenue or 0),
                "expected_cost": float(row.expected_cost or 0),
                "expected_margin": float(row.expected_margin or 0),
                "recommendation": row.recommendation,
                "status": row.status,
            }
            for row in rows
        ]

    def _execute(self, run: PolicyRun, snapshot: PolicyInputSnapshot, demand_id: int | None = None,
                 scenario: str = "demand_evaluation"):
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

        self._persist_policy(run, result, demand_id=demand_id, scenario=scenario)
        run.status = PolicyRunStatus.SUCCESS
        run.finished_at = utcnow()
        run.duration_ms = int(
            (run.finished_at - run.started_at).total_seconds() * 1000)
        db.session.flush()

    def _persist_policy(self, run: PolicyRun, result: PolicyResult, demand_id: int | None = None,
                        scenario: str = "demand_evaluation"):
        now = utcnow()
        policy = Policy(
            policy_run_id=run.id,
            demand_id=demand_id,
            policy_no="P" + now.strftime("%Y%m%d%H%M%S%f")[:-3],
            algorithm=run.algorithm,
            scenario=scenario,
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
        if policy.algorithm == "demand_evaluation":
            self._sync_demand_evaluation_decision(
                policy, accepted=True, operator=operator, reason=comment)
        db.session.flush()

        if policy.algorithm != "demand_evaluation":
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
        if policy.algorithm == "demand_evaluation":
            self._sync_demand_evaluation_decision(
                policy, accepted=False, operator=operator, reason=reason)
        db.session.flush()
        return policy

    def _sync_demand_evaluation_decision(self, policy: Policy, accepted: bool,
                                         operator: str, reason: str | None = None):
        summary = dict(policy.summary_json or {})
        demand_id = summary.get("demand_id")
        evaluation_id = summary.get("evaluation_id")
        demand = db.session.get(Demand, int(demand_id)) if demand_id else None
        evaluation = db.session.get(Evaluation, int(evaluation_id)) if evaluation_id else None
        if demand:
            demand.status = DemandStatus.APPROVED if accepted else DemandStatus.REJECTED
        if evaluation:
            evaluation.status = EvaluationStatus.APPROVED if accepted else EvaluationStatus.REJECTED
            evaluation.decided_by = operator
            evaluation.decided_at = utcnow()
            evaluation.decided_reason = reason or ("需求评估方案确认" if accepted else "需求评估方案驳回")
        summary.update({
            "demand_status": DemandStatus.APPROVED if accepted else DemandStatus.REJECTED,
            "decided_by": operator,
            "decided_reason": reason,
        })
        policy.summary_json = summary

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
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, dict):
            return {k: PolicyService._jsonable(v) for k, v in value.items()}
        if isinstance(value, list):
            return [PolicyService._jsonable(v) for v in value]
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value


    @staticmethod
    def _demand_ids_from_snapshot(snapshot_dict: dict) -> list[int]:
        report_ids = [d["report_id"] for d in snapshot_dict.get("demands", [])]
        if not report_ids:
            return []
        rows = db.session.execute(
            select(Demand.id).where(Demand.report_id.in_(report_ids))
        ).all()
        return [r[0] for r in rows]
