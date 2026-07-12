from __future__ import annotations

from datetime import date, timedelta

from flask import current_app
from sqlalchemy import select

from ..extensions import db
from ..integrations import billing_client, monitoring_client
from ..models import MonitorConsumer, CustomerUsageDaily, Demand
from ..utils.errors import NotFound
from ..utils.time import utcnow
from .alert_service import AlertService


class CustomerTrackingService:
    def __init__(self):
        self.alert_service = AlertService()

    def aggregate_daily(self, stat_date: date | None = None) -> int:
        stat_date = stat_date or (utcnow().date() - timedelta(days=1))
        demands = db.session.execute(
            select(Demand).where(Demand.customer_id.isnot(None))
        ).scalars().all()
        count = 0
        for demand in demands:
            customer = db.session.get(MonitorConsumer, demand.customer_id)
            if not customer:
                continue
            actual = monitoring_client().aggregate_for_report(demand.report_id).get("avg_actual_tpm", 0)
            billing = billing_client().usage(customer.customer_code, days=1)
            revenue = sum(r.revenue for r in billing.rows)
            cost_self = sum(r.cost_self for r in billing.rows)
            cost_vendor = sum(r.cost_vendor for r in billing.rows)

            existing = db.session.execute(
                select(CustomerUsageDaily).where(
                    CustomerUsageDaily.customer_id == customer.id,
                    CustomerUsageDaily.report_id == demand.report_id,
                    CustomerUsageDaily.stat_date == stat_date,
                )
            ).scalar_one_or_none()

            achievement = (actual / float(demand.expected_tpm)) if demand.expected_tpm else 0
            row = existing or CustomerUsageDaily(
                customer_id=customer.id,
                report_id=demand.report_id,
                stat_date=stat_date,
            )
            row.expected_tpm = float(demand.expected_tpm or 0)
            row.actual_tpm = actual
            row.achievement_rate = round(achievement, 4)
            row.revenue = revenue
            row.cost_self = cost_self
            row.cost_vendor = cost_vendor
            row.margin = revenue - cost_self - cost_vendor
            if existing is None:
                db.session.add(row)
            count += 1

            self._maybe_alert(customer, demand.report_id, achievement)
        db.session.commit()
        return count

    def _maybe_alert(self, customer: MonitorConsumer, report_id: str, achievement: float):
        low = current_app.config["ALERT_THRESHOLD_LOW"]
        high = current_app.config["ALERT_THRESHOLD_HIGH"]
        if achievement < low:
            self.alert_service.create(
                alert_type="achievement_low",
                severity="warn",
                subject_type="report",
                subject_id=report_id,
                message=f"客户 {customer.customer_code} 报备 {report_id} 达成率 {achievement:.2%} 低于阈值",
                payload={"achievement_rate": achievement, "threshold": low},
            )
        elif achievement > high:
            self.alert_service.create(
                alert_type="achievement_high",
                severity="info",
                subject_type="report",
                subject_id=report_id,
                message=f"客户 {customer.customer_code} 报备 {report_id} 达成率 {achievement:.2%} 超出阈值",
                payload={"achievement_rate": achievement, "threshold": high},
            )

    def tracking_for_report(self, report_id: str) -> dict:
        demand = db.session.execute(
            select(Demand).where(Demand.report_id == report_id)
        ).scalar_one_or_none()
        if not demand:
            raise NotFound("报备不存在", details={"report_id": report_id})
        rows = db.session.execute(
            select(CustomerUsageDaily).where(CustomerUsageDaily.report_id == report_id)
            .order_by(CustomerUsageDaily.stat_date.desc())
        ).scalars().all()
        return {
            "report_id": report_id,
            "expected_tpm": float(demand.expected_tpm or 0),
            "history": [
                {
                    "stat_date": r.stat_date.isoformat(),
                    "actual_tpm": float(r.actual_tpm),
                    "achievement_rate": float(r.achievement_rate),
                    "revenue": float(r.revenue),
                    "margin": float(r.margin),
                }
                for r in rows
            ],
        }
