from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from ..extensions import db
from ..models import (
    Alert,
    ClusterCapacity,
    MonitorConsumer,
    CustomerUsageDaily,
    Demand,
    DemandStatus,
    Evaluation,
    EvaluationStatus,
    Policy,
    PolicyStatus,
    RevenueAttribution,
    WatchedCluster,
)
from ..models.alert import AlertStatus
from ..utils.errors import NotFound, ValidationFailed
from ..utils.time import utcnow


class DashboardService:
    def operations(self) -> dict:
        now = utcnow()
        since = now - timedelta(hours=24)
        pending = db.session.execute(
            select(func.count(Demand.id)).where(
                Demand.status == DemandStatus.PENDING)
        ).scalar_one()
        evaluating = db.session.execute(
            select(func.count(Evaluation.id)).where(
                Evaluation.status == EvaluationStatus.PENDING)
        ).scalar_one()
        draft_policies = db.session.execute(
            select(func.count(Policy.id)).where(
                Policy.status == PolicyStatus.DRAFT)
        ).scalar_one()
        recent_revenue = db.session.execute(
            select(func.coalesce(func.sum(RevenueAttribution.revenue_delta), 0))
            .where(RevenueAttribution.computed_at >= since)
        ).scalar_one()
        open_alerts = db.session.execute(
            select(func.count(Alert.id)).where(
                Alert.status == AlertStatus.OPEN)
        ).scalar_one()
        return {
            "pending_demands": pending,
            "pending_evaluations": evaluating,
            "draft_policies": draft_policies,
            "revenue_last_24h": float(recent_revenue or 0),
            "open_alerts": open_alerts,
        }

    def customers(self, customer_id: int | None = None) -> dict:
        stmt = select(MonitorConsumer)
        demand_stmt = select(Demand)
        if customer_id:
            stmt = stmt.where(MonitorConsumer.id == customer_id)
            demand_stmt = demand_stmt.where(Demand.customer_id == customer_id)
        customers = db.session.execute(stmt).scalars().all()
        demands = db.session.execute(demand_stmt.order_by(
            Demand.created_at.desc())).scalars().all()
        demand_ids = [d.id for d in demands]
        expected_revenue = 0
        if demand_ids:
            expected_revenue = db.session.execute(
                select(func.coalesce(func.sum(Evaluation.expected_revenue), 0))
                .where(Evaluation.demand_id.in_(demand_ids))
            ).scalar_one()
        result = []
        for c in customers:
            usage_rows = db.session.execute(
                select(CustomerUsageDaily).where(
                    CustomerUsageDaily.customer_id == c.id)
                .order_by(CustomerUsageDaily.stat_date.desc()).limit(7)
            ).scalars().all()
            achievement = (
                sum(float(r.achievement_rate)
                    for r in usage_rows) / len(usage_rows)
                if usage_rows else 0
            )
            result.append({
                "customer_id": c.id,
                "customer_code": c.customer_code,
                "name": c.customer_name,
                "level": c.level,
                "avg_achievement_rate_7d": round(achievement, 4),
                "revenue_7d": sum(float(r.revenue) for r in usage_rows),
            })
        return {
            "customer_id": customer_id or "all",
            "demand_count": len(demands),
            "active_models": sorted({d.model_name for d in demands}),
            "expected_tpm": sum(float(d.expected_tpm or 0) for d in demands),
            "expected_revenue": float(expected_revenue or 0),
            "fulfillment": {
                "live": sum(1 for d in demands if d.status == DemandStatus.LIVE),
                "approved": sum(1 for d in demands if d.status == DemandStatus.APPROVED),
                "pending": sum(1 for d in demands if d.status == DemandStatus.PENDING),
            },
            "recent_demands": [
                {
                    "id": d.id,
                    "report_id": d.report_id,
                    "customer_id": d.customer_id,
                    "model_name": d.model_name,
                    "expected_tpm": float(d.expected_tpm or 0),
                    "expected_rpm": float(d.expected_rpm or 0),
                    "discount_rate": float(d.discount_rate or 0),
                    "expected_start_at": d.expected_start_at.isoformat() if d.expected_start_at else None,
                    "expected_end_at": d.expected_end_at.isoformat() if d.expected_end_at else None,
                    "status": d.status,
                    "source_batch_id": d.source_batch_id,
                    "source_payload_hash": d.source_payload_hash,
                    "field_completeness_score": float(d.field_completeness_score or 0),
                    "created_at": d.created_at.isoformat() if d.created_at else None,
                    "updated_at": d.updated_at.isoformat() if d.updated_at else None,
                }
                for d in demands[:5]
            ],
            "items": result,
        }

    def management(self, range: str = "7d") -> dict:
        days = 7 if range == "7d" else 30
        now = utcnow()
        since = now - timedelta(days=days)
        previous_since = since - timedelta(days=days)
        total_revenue = db.session.execute(
            select(func.coalesce(func.sum(RevenueAttribution.revenue_delta), 0))
            .where(RevenueAttribution.computed_at >= since)
        ).scalar_one()
        previous_revenue = db.session.execute(
            select(func.coalesce(func.sum(RevenueAttribution.revenue_delta), 0))
            .where(RevenueAttribution.computed_at >= previous_since)
            .where(RevenueAttribution.computed_at < since)
        ).scalar_one()
        adoption_total = db.session.execute(
            select(func.count(Policy.id))).scalar_one()
        adoption_accepted = db.session.execute(
            select(func.count(Policy.id)).where(
                Policy.status == PolicyStatus.ACCEPTED)
        ).scalar_one()
        adoption_rate = (adoption_accepted /
                         adoption_total) if adoption_total else 0
        current_revenue = float(total_revenue or 0)
        previous_revenue_value = float(previous_revenue or 0)
        revenue_growth = ((current_revenue - previous_revenue_value) /
                          previous_revenue_value) if previous_revenue_value else 0
        policies = db.session.execute(select(Policy).order_by(
            Policy.created_at.desc()).limit(20)).scalars().all()
        strategy_contribution = [
            {
                "policy_no": policy.policy_no,
                "algorithm": policy.algorithm,
                "gain": float(policy.expected_revenue_gain or 0),
            }
            for policy in policies
        ]
        trend_rows = db.session.execute(
            select(
                func.date(RevenueAttribution.computed_at),
                func.coalesce(func.sum(RevenueAttribution.revenue_delta), 0),
                func.coalesce(func.sum(RevenueAttribution.cost_delta), 0),
            )
            .where(RevenueAttribution.computed_at >= since)
            .group_by(func.date(RevenueAttribution.computed_at))
            .order_by(func.date(RevenueAttribution.computed_at))
        ).all()
        trend = [
            {
                "date": str(row[0])[5:] if row[0] else "",
                "revenue": float(row[1] or 0),
                "cost": float(row[2] or 0),
            }
            for row in trend_rows
        ]
        current_cost = sum(item["cost"] for item in trend)
        current_margin = current_revenue - current_cost
        return {
            "platform_revenue_delta": current_revenue,
            "policy_adoption_rate": round(adoption_rate, 4),
            "range": range,
            "generated_at": now.isoformat(),
            "revenue": {
                "current": current_revenue,
                "previous": previous_revenue_value,
                "growth": revenue_growth,
            },
            "cost": {
                "current": current_cost,
                "previous": 0,
                "growth": 0,
            },
            "margin": {
                "current": current_margin,
                "rate": (current_margin / current_revenue) if current_revenue else 0,
            },
            "strategy_contribution": strategy_contribution,
            "trend": trend,
        }

    def resources(
        self,
        cluster_name: str | None = None,
        deployed_model: str | None = None,
        gpu_model: str | None = None,
        datacenter: str | None = None,
    ) -> dict:
        from ..integrations import resource_client
        snapshot = resource_client().snapshot()
        clusters = snapshot.clusters
        watched_names = {n.lower() for n in self._watched_cluster_names()}
        if watched_names:
            clusters = [c for c in clusters if (c.cluster_name or "").lower() in watched_names]
        if cluster_name:
            clusters = [c for c in clusters if c.cluster_name == cluster_name]
        if deployed_model:
            clusters = [
                c for c in clusters if c.deployed_model == deployed_model]
        if gpu_model:
            clusters = [
                c for c in clusters
                if gpu_model.lower() in c.deployed_model.lower()
                or gpu_model.lower() in c.cluster_name.lower()
            ]
        if datacenter:
            clusters = [c for c in clusters if datacenter.lower()
                        in c.cluster_name.lower()]

        total_capacity = sum(c.total_capacity_tpm for c in clusters)
        total_current = sum(c.current_tpm for c in clusters)
        total_current_redundant = sum(
            c.current_redundant_tpm for c in clusters)
        avg_utilization = (
            total_current / total_capacity) if total_capacity else 0

        clusters_payload = [
            self._cluster_payload(c)
            for c in clusters
        ]
        nodes = [
            {
                "node_id": c.cluster_name,
                "gpu_model": c.deployed_model,
                "datacenter": c.cluster_name,
                "az": c.cluster_name,
                "capacity_tpm": c.total_capacity_tpm,
                "available_tpm": c.current_redundant_tpm,
                "utilization": (c.current_tpm / c.total_capacity_tpm) if c.total_capacity_tpm else 0,
                "cluster_name": c.cluster_name,
                "deployed_model": c.deployed_model,
                "provider": c.provider,
            }
            for c in clusters
        ]
        return {
            "captured_at": snapshot.captured_at,
            "total_capacity_tpm": total_capacity,
            "total_available_tpm": total_current_redundant,
            "avg_utilization": avg_utilization,
            "nodes": nodes,
            "total_current_tpm": total_current,
            "total_current_redundant_tpm": total_current_redundant,
            "clusters": clusters_payload,
        }

    def _watched_cluster_names(self) -> set[str]:
        return {
            item.cluster_name
            for item in db.session.execute(
                select(WatchedCluster).where(WatchedCluster.enabled.is_(True))
            ).scalars()
        }

    def update_cluster_tpm_per_machine(
        self,
        cluster_name: str,
        deployed_model: str | None = None,
        tpm_per_machine_w: float = 0,
        machine_count: int | None = None,
        current_tpm_w: float | None = None,
        provider: str | None = None,
    ) -> dict:
        """前端录入自建集群单机承接能力（万 TPM）。写入 cluster_capacities（大小写不敏感）。

        台数/实跑/provider 均来自监控与 provider_mappings，此处只维护 tpm_per_machine；
        返回该集群按最新监控组装后的资源快照 payload。
        """
        cluster_name = (cluster_name or "").strip()
        if not cluster_name:
            raise ValidationFailed("集群名称不能为空")
        if tpm_per_machine_w < 0:
            raise ValidationFailed("单机承载能力不能小于 0")

        tpm_per_machine = Decimal(str(tpm_per_machine_w)) * Decimal("10000")
        row = db.session.execute(
            select(ClusterCapacity).where(
                func.lower(ClusterCapacity.cluster_name) == cluster_name.lower()
            )
        ).scalar_one_or_none()
        if row is None:
            row = ClusterCapacity(cluster_name=cluster_name, tpm_per_machine=tpm_per_machine)
            db.session.add(row)
        else:
            row.tpm_per_machine = tpm_per_machine
        db.session.commit()

        from ..integrations import resource_client
        snap = resource_client().snapshot()
        item = next(
            (c for c in snap.clusters if c.cluster_name.lower() == cluster_name.lower()),
            None,
        )
        if item is not None:
            return self._cluster_payload(item)
        # 监控暂无该集群实跑数据：返回仅含容量的最小 payload。
        return {
            "cluster_name": cluster_name,
            "tpm_per_machine": float(tpm_per_machine),
            "tpm_per_machine_w": self._to_wtpm(tpm_per_machine),
            "machine_count": 0,
            "total_capacity_tpm": 0.0,
            "total_capacity_w": 0.0,
            "current_tpm": 0.0,
            "current_redundant_tpm": 0.0,
            "current_redundant_machines": 0,
        }

    def _cluster_payload(self, c) -> dict:
        total_capacity = self._to_number(c.total_capacity_tpm)
        current_tpm = self._to_number(c.current_tpm)
        return {
            "cluster_name": c.cluster_name,
            "deployed_model": c.deployed_model,
            "provider": c.provider or c.cluster_name,
            "machine_count": int(c.machine_count or 0),
            "tpm_per_machine": self._to_number(c.tpm_per_machine),
            "tpm_per_machine_w": self._to_wtpm(c.tpm_per_machine),
            "total_capacity_tpm": total_capacity,
            "total_capacity_w": self._to_wtpm(c.total_capacity_tpm),
            "current_tpm": current_tpm,
            "current_tpm_w": self._to_wtpm(c.current_tpm),
            "current_redundant_tpm": self._to_number(c.current_redundant_tpm),
            "current_redundant_w": self._to_wtpm(c.current_redundant_tpm),
            "current_redundant_machines": int(c.current_redundant_machines or 0),
            "cluster_utilization": (current_tpm / total_capacity) if total_capacity else 0,
        }

    @staticmethod
    def _to_number(value) -> float:
        return float(value or 0)

    @staticmethod
    def _to_wtpm(value) -> float:
        return round(float(value or 0) / 10000, 4)
