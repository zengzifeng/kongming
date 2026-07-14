from sqlalchemy import inspect, text, func
from app import create_app
from app.extensions import db
from app.models import Policy

app = create_app("dev")
with app.app_context():
    insp = inspect(db.engine)
    cols = {c["name"] for c in insp.get_columns("policies")}
    if "scenario" not in cols:
        db.session.execute(text(
            "ALTER TABLE policies ADD COLUMN scenario VARCHAR(24) NOT NULL DEFAULT 'demand_evaluation'"
        ))
        db.session.commit()
        print("added scenario column")
    else:
        print("scenario column exists")

    n = 0
    for p in db.session.query(Policy).all():
        module = (p.summary_json or {}).get("module")
        if module in ("demand_evaluation", "idle", "busy"):
            sc = module
        elif p.algorithm == "demand_evaluation":
            sc = "demand_evaluation"
        elif p.algorithm == "time_period":
            sc = "busy"
        else:
            sc = "demand_evaluation"
        if p.scenario != sc:
            p.scenario = sc
            n += 1
    db.session.commit()
    print("backfilled", n)
    print("by scenario:", db.session.query(Policy.scenario, func.count()).group_by(Policy.scenario).all())
