"""基于当前拟合数据重产出 time_period 闲时/忙时策略。

用法（backend 目录下）：
    python scripts/run_time_period_policy.py
"""
import json
import sys
from pathlib import Path

from sqlalchemy import delete

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.models import Policy, PolicyAction, PolicyAuditLog, PolicyRun  # noqa: E402
from app.services import PolicyService  # noqa: E402
from app.services.wave_fitting_service import WaveFittingService  # noqa: E402


MODULES = ("idle", "busy")


def main():
    app = create_app("dev")
    with app.app_context():
        print(f"WAVE_FIT_ENABLED={app.config.get('WAVE_FIT_ENABLED')}")
        for module in MODULES:
            hours = WaveFittingService.period_hours(module)
            print(f"{module} 小时={sorted(hours)}")

        removed = clear_time_period_policies()
        db.session.commit()
        print(f"[cleanup] removed_time_period_policies={removed['policies']} runs={removed['runs']}")

        for module in MODULES:
            run_policy(module)


def clear_time_period_policies() -> dict[str, int]:
    policy_ids = list(db.session.scalars(
        db.select(Policy.id).where(Policy.algorithm == "time_period")
    ))
    run_ids = list(db.session.scalars(
        db.select(PolicyRun.id).where(PolicyRun.algorithm == "time_period")
    ))

    if policy_ids:
        db.session.execute(delete(PolicyAuditLog).where(PolicyAuditLog.policy_id.in_(policy_ids)))
        db.session.execute(delete(PolicyAction).where(PolicyAction.policy_id.in_(policy_ids)))
        db.session.execute(delete(Policy).where(Policy.id.in_(policy_ids)))
    if run_ids:
        db.session.execute(delete(PolicyRun).where(PolicyRun.id.in_(run_ids)))
    return {"policies": len(policy_ids), "runs": len(run_ids)}


def run_policy(module: str) -> None:
    run = PolicyService().submit_run(
        algorithm="time_period",
        triggered_by="manual",
        params={"module": module},
    )
    db.session.commit()
    print(f"[run:{module}] {run.run_no} status={run.status} algo={run.algorithm} duration={run.duration_ms}ms")
    if run.error_message:
        print(f"[error:{module}] {run.error_message}")
        return

    policy = db.session.execute(
        db.select(Policy).where(Policy.policy_run_id == run.id)
    ).scalar_one_or_none()
    if policy is None:
        print(f"[policy:{module}] 本次未产出策略")
        return

    summary = policy.summary_json or {}
    accepted = summary.get("accepted_customers", [])
    moves = summary.get("node_moves", [])
    print(f"[policy:{module}] {policy.policy_no} scenario={policy.scenario} status={policy.status}")
    print(
        f"  预期收益增益={float(policy.expected_revenue_gain or 0):.2f} "
        f"削峰增益={float(policy.expected_peak_shaving_gain or 0):.2f} "
        f"闲时增益={float(policy.expected_off_peak_gain or 0):.2f}"
    )
    print(f"  accepted_customers={len(accepted)} node_moves={len(moves)}")

    wms = summary.get("watermark_changes", [])
    if wms:
        hours = WaveFittingService.period_hours(module)
        wm = wms[0]
        slots = [sl for sl in wm.get("slots", [])
                 if _hour_of(sl.get("ts") or sl.get("time") or sl.get("hour")) in hours]
        print(f"  样例集群/需求 watermark，{module} slot {len(slots)} 个，前 3:")
        for sl in slots[:3]:
            print("    ", json.dumps(sl, ensure_ascii=False))


def _hour_of(v):
    if v is None:
        return -1
    if isinstance(v, int):
        return v
    from datetime import datetime
    try:
        return datetime.fromisoformat(str(v)).hour
    except ValueError:
        try:
            return int(v)
        except (TypeError, ValueError):
            return -1


if __name__ == "__main__":
    main()
