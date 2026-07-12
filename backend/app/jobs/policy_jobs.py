from ..extensions import db
from ..services import PolicyService
from .decorators import with_job_log


@with_job_log("policy_auto_run")
def policy_auto_run(app, algorithm: str = "time_period"):
    """后台定时测算：用实跑量 + 平台定价重新取数跑一次，产出 DRAFT 策略待人工采纳。

    算法与频率由 job_schedules 表配置（默认 time_period / 每天），args_json.algorithm 可覆盖算法。
    """
    run = PolicyService().submit_run(algorithm=algorithm, triggered_by="scheduled")
    db.session.commit()
    return f"run={run.run_no} status={run.status}"
