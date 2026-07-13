"""基于当前拟合数据跑一版 time_period 策略测算（含闲时策略）。

WAVE_FIT_ENABLED 开启时，build_run_snapshot 会用最新的客户级拟合波形（闲时+忙时合并）
覆盖各需求的 tpm_series，故本次测算即"基于拟合数据"。time_period 求解器在各时段水位上
重新分配自建/三方与跨簇腾挪，闲时(0-8)的自建占比抬升即闲时策略。

用法（backend 目录下）：
    python scripts/run_time_period_policy.py
"""
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app import create_app  # noqa: E402
from app.extensions import db  # noqa: E402
from app.services import PolicyService  # noqa: E402
from app.services.wave_fitting_service import WaveFittingService  # noqa: E402
from app.models import Policy  # noqa: E402

IDLE_HOURS = None  # 运行时从 config 取


def main():
    app = create_app("dev")
    with app.app_context():
        idle_hours = WaveFittingService.period_hours("idle")
        print(f"WAVE_FIT_ENABLED={app.config.get('WAVE_FIT_ENABLED')} 闲时小时={sorted(idle_hours)}")

        run = PolicyService().submit_run(algorithm="time_period", triggered_by="manual")
        db.session.commit()
        print(f"[run] {run.run_no} status={run.status} algo={run.algorithm} duration={run.duration_ms}ms")
        if run.error_message:
            print(f"[error] {run.error_message}")
            return

        policy = db.session.execute(
            db.select(Policy).where(Policy.policy_run_id == run.id)
        ).scalar_one_or_none()
        if policy is None:
            print("[policy] 本次未产出策略")
            return
        s = policy.summary_json or {}
        print(f"[policy] {policy.policy_no} status={policy.status}")
        print(f"  预期收益增益={float(policy.expected_revenue_gain or 0):.2f} "
              f"削峰增益={float(policy.expected_peak_shaving_gain or 0):.2f} "
              f"闲时增益={float(policy.expected_off_peak_gain or 0):.2f}")
        accepted = s.get("accepted_customers", [])
        moves = s.get("node_moves", [])
        print(f"  accepted_customers={len(accepted)} node_moves={len(moves)}")

        # 闲时水位样例：取一条 watermark_changes，打印落在闲时的 slot 自建占比
        wms = s.get("watermark_changes", [])
        if wms:
            wm = wms[0]
            idle_slots = [sl for sl in wm.get("slots", [])
                          if _hour_of(sl.get("time") or sl.get("hour")) in idle_hours]
            print(f"  样例集群/需求 watermark，闲时 slot {len(idle_slots)} 个，前 3:")
            for sl in idle_slots[:3]:
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
