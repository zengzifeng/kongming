from __future__ import annotations

from sqlalchemy import select

from ..extensions import db
from ..models import MonitorConsumer, Demand, RawFiling
from ..models.demand import DemandStatus, VALID_TRANSITIONS
from ..utils.errors import NotFound, StateConflict, ValidationFailed
from ..utils.time import utcnow


CORE_FIELDS = ("report_id", "customer_code", "model", "expected_tpm", "expected_rpm")


class DemandService:
    def upsert_from_raw(self, raw: RawFiling) -> str:
        payload = raw.payload_json or {}
        report_id = payload.get("report_id") or raw.report_id
        customer = self._ensure_customer(payload)
        completeness = self._completeness(payload)

        demand = db.session.execute(
            select(Demand).where(Demand.report_id == report_id)
        ).scalar_one_or_none()

        if demand is None:
            demand = Demand(
                report_id=report_id,
                customer_id=customer.id if customer else None,
                model_name=payload.get("model", "unknown"),
                expected_tpm=payload.get("expected_tpm", 0) or 0,
                expected_rpm=payload.get("expected_rpm", 0) or 0,
                discount_rate=payload.get("discount_rate", 1.0) or 1.0,
                expected_start_at=self._parse_dt(payload.get("expected_start_at")),
                expected_end_at=self._parse_dt(payload.get("expected_end_at")),
                status=DemandStatus.PENDING,
                source_batch_id=raw.batch_id,
                source_payload_hash=raw.hash,
                field_completeness_score=completeness,
            )
            db.session.add(demand)
            db.session.flush()
            return "inserted"

        if demand.source_payload_hash == raw.hash:
            return "skipped"

        demand.customer_id = customer.id if customer else demand.customer_id
        demand.model_name = payload.get("model", demand.model_name)
        demand.expected_tpm = payload.get("expected_tpm", demand.expected_tpm)
        demand.expected_rpm = payload.get("expected_rpm", demand.expected_rpm)
        demand.discount_rate = payload.get("discount_rate", demand.discount_rate)
        demand.source_payload_hash = raw.hash
        demand.field_completeness_score = completeness
        return "updated"

    def _ensure_customer(self, payload: dict) -> MonitorConsumer | None:
        code = payload.get("customer_code")
        if not code:
            return None
        customer = db.session.execute(
            select(MonitorConsumer).where(MonitorConsumer.customer_code == code)
        ).scalar_one_or_none()
        if customer:
            return customer
        name = payload.get("customer_name", code)
        customer = MonitorConsumer(
            ai_consumer=name,
            customer_code=code,
            customer_name=name,
            level=payload.get("customer_level", "B"),
        )
        db.session.add(customer)
        db.session.flush()
        return customer

    @staticmethod
    def _completeness(payload: dict) -> float:
        filled = sum(1 for f in CORE_FIELDS if payload.get(f) not in (None, "", 0))
        return round(filled / len(CORE_FIELDS), 4)

    @staticmethod
    def _parse_dt(value):
        if not value:
            return None
        from datetime import datetime
        try:
            return datetime.fromisoformat(value)
        except (TypeError, ValueError):
            return None

    def get(self, demand_id: int) -> Demand:
        demand = db.session.get(Demand, demand_id)
        if not demand:
            raise NotFound("需求不存在", details={"id": demand_id})
        return demand

    def transition(self, demand_id: int, target_status: str, operator: str | None = None,
                   reason: str | None = None) -> Demand:
        demand = self.get(demand_id)
        if target_status not in DemandStatus.ALL:
            raise ValidationFailed("非法状态", details={"target": target_status})
        allowed = VALID_TRANSITIONS.get(demand.status, set())
        if target_status not in allowed:
            raise StateConflict(
                "需求状态流转非法",
                details={"from": demand.status, "to": target_status, "allowed": list(allowed)},
            )
        demand.status = target_status
        db.session.flush()
        return demand

    def patch(self, demand_id: int, patch: dict) -> Demand:
        demand = self.get(demand_id)
        if "status" in patch and patch["status"]:
            self.transition(demand_id, patch["status"])
        for field in ("expected_start_at", "expected_end_at"):
            if field in patch and patch[field]:
                setattr(demand, field, patch[field])
        if "extra" in patch and patch["extra"] is not None:
            demand.extra = patch["extra"]
        db.session.flush()
        return demand
