from __future__ import annotations

from dataclasses import asdict

from ..integrations import (
    resource_client,
    monitoring_client,
    vendor_client,
)
from ..models import Demand
from ..utils.time import utcnow
from .base import DemandSnapshotItem, PolicyInputSnapshot
from .cluster_redundancy import apply_current_redundancy


def _load_model_prices() -> dict:
    """从 model_list_prices 表读取当前生效的三档列表价，组装成 {model: {三档}} 供求解器消费。

    表为空时返回 {}，由调用方回退到 params.model_prices（向后兼容）。
    """
    from ..extensions import db
    from ..models import ModelListPrice

    now = utcnow()
    rows = db.session.execute(
        db.select(ModelListPrice).where(
            ModelListPrice.effective_from <= now,
            db.or_(
                ModelListPrice.effective_to.is_(None),
                ModelListPrice.effective_to > now,
            ),
        )
    ).scalars().all()
    return {
        r.model_name: {
            "input_cache_hit_price": float(r.input_cache_hit_price or 0),
            "input_cache_miss_price": float(r.input_cache_miss_price or 0),
            "output_price": float(r.output_price or 0),
        }
        for r in rows
    }


def _item_from_orm(d: Demand, demand_params: dict, default_input_ratio: float, params: dict) -> DemandSnapshotItem:
    """把一条 Demand（报备单）ORM 转成 DemandSnapshotItem（手动/报备路径用）。

    实跑量4字段：优先取 params.demands[report_id] 覆盖（显式覆盖/测试），否则取 DB 列，最后取默认。
    """
    overrides = demand_params.get(d.report_id, {})
    return DemandSnapshotItem(
        report_id=d.report_id,
        customer_code=str(d.customer_id) if d.customer_id else "unknown",
        model_name=d.model_name,
        expected_tpm=float(d.expected_tpm or 0),
        expected_rpm=float(d.expected_rpm or 0),
        discount_rate=float(d.discount_rate or 1.0),
        input_ratio=float(overrides.get(
            "input_ratio", d.input_ratio if d.input_ratio is not None else default_input_ratio)),
        cache_hit_rate=float(overrides.get(
            "cache_hit_rate",
            d.cache_hit_rate if d.cache_hit_rate is not None
            else params.get("default_cache_hit_rate", 0.0))),
        current_self_ratio=float(overrides.get(
            "current_self_ratio", d.current_self_ratio if d.current_self_ratio is not None else 0.0)),
        current_vendor_ratios=dict(overrides.get(
            "current_vendor_ratios", d.current_vendor_ratios or {})),
        quality_score=float(overrides.get("quality_score", 0.0)),
    )


def build_snapshot(
    algorithm: str,
    demands: list[Demand] | None = None,
    params: dict | None = None,
    *,
    demand_items: list[DemandSnapshotItem] | None = None,
    enrich_cluster_redundancy: bool = False,
) -> PolicyInputSnapshot:
    """组装求解器输入快照。

    需求来源二选一：
    - ``demand_items`` 直接给定（实跑量路径，默认由 usage_demand_source 构建）；
    - 否则从 ``demands``（Demand ORM，报备/手动路径）逐条转换（向后兼容）。
    resources / vendors / model_prices 已分别来自 DB 表，monitoring 仍走监控客户端。

    ``enrich_cluster_redundancy``：实跑量路径下置 True，策略运行前按最新负载实时计算
    各集群当前冗余（current_redundant_tpm/机器数），覆盖静态录入值。
    """
    resources = resource_client().snapshot()
    monitoring = monitoring_client().tpm_series()
    vendors = vendor_client().quotas()

    params = dict(params or {})
    demand_params = params.get("demands", {})
    default_input_ratio = float(params.get("default_input_ratio", 1.0))

    # 列表价：优先取 DB（model_list_prices 表），空表回退 params.model_prices（向后兼容/测试注入）。
    db_prices = _load_model_prices()
    model_prices = {**params.get("model_prices", {}), **db_prices}
    params["model_prices"] = model_prices

    if demand_items is None:
        demand_items = [
            _item_from_orm(d, demand_params, default_input_ratio, params)
            for d in (demands or [])
        ]

    cluster_dicts = [asdict(c) for c in resources.clusters]
    if enrich_cluster_redundancy:
        # 策略运行前：按最新实跑负载实时计算各集群当前冗余，覆盖静态录入值。
        apply_current_redundancy(cluster_dicts)

    snapshot = PolicyInputSnapshot(
        captured_at=utcnow(),
        algorithm=algorithm,
        demands=demand_items,
        resources={
            "captured_at": resources.captured_at,
            "clusters": cluster_dicts,
            # 总量从（可能已被冗余计算覆盖的）集群 dict 求和，保证与 clusters 一致。
            "total_capacity_tpm": sum(c.get("total_capacity_tpm", 0) or 0 for c in cluster_dicts),
            "total_current_redundant_tpm": sum(c.get("current_redundant_tpm", 0) or 0 for c in cluster_dicts),
            "total_idle_redundant_tpm": sum(c.get("idle_redundant_tpm", 0) or 0 for c in cluster_dicts),
            "total_busy_redundant_tpm": sum(c.get("busy_redundant_tpm", 0) or 0 for c in cluster_dicts),
        },
        monitoring={
            "captured_at": monitoring.captured_at,
            "window_minutes": len(monitoring.points),
            "avg_tpm_self": (
                sum(p.tpm_self for p in monitoring.points) / max(len(monitoring.points), 1)
            ),
            "avg_tpm_vendor": (
                sum(p.tpm_vendor for p in monitoring.points) / max(len(monitoring.points), 1)
            ),
            "avg_cache_hit_rate": (
                sum(p.cache_hit_rate for p in monitoring.points) / max(len(monitoring.points), 1)
            ),
        },
        vendors=[asdict(v) for v in vendors],
        params=params,
    )
    return snapshot


def build_run_snapshot(
    algorithm: str,
    demand_ids: list[int] | None = None,
    params: dict | None = None,
) -> PolicyInputSnapshot:
    """策略测算的统一输入构建：由「触发时是否给定 demand_ids」决定取数逻辑，
    策略侧(policy_service)不再关心分路。

    - 无 ``demand_ids``（默认/后台定时）：从实跑量 + 平台定价主数据实时构建，
      并按最新负载富化各集群当前冗余。
    - 有 ``demand_ids``（前端手动指定新增某客户需求评估）：按显式 id 从 demands 表取。
    """
    from ..models import Demand
    from ..utils.errors import ValidationFailed
    from .usage_demand_source import build_usage_demand_items
    from ..extensions import db

    params = dict(params or {})
    if demand_ids:
        demands = list(
            db.session.execute(db.select(Demand).where(Demand.id.in_(demand_ids))).scalars()
        )
        if not demands:
            raise ValidationFailed("指定的需求不存在或不可用")
        return build_snapshot(algorithm=algorithm, demands=demands, params=params)

    demand_items = build_usage_demand_items()
    if not demand_items:
        raise ValidationFailed("没有可用的实跑量需求用于测算")
    _apply_fitted_series(demand_items)
    return build_snapshot(
        algorithm=algorithm,
        demand_items=demand_items,
        params=params,
        enrich_cluster_redundancy=True,
    )


def _apply_fitted_series(demand_items) -> None:
    """WAVE_FIT_ENABLED 时，用波形拟合结果覆盖各需求的 tpm_series（time_period 消费）。

    每个 (客户, 模型) 取最新的 闲时+忙时 客户级拟合波形合并为整段序列；无拟合结果的项
    保留 usage_demand_source 直接搬来的原始序列（回退，行为与关闭开关时一致）。
    """
    from flask import current_app

    if not current_app.config.get("WAVE_FIT_ENABLED", False):
        return
    from ..services.wave_fitting_service import WaveFittingService

    svc = WaveFittingService()
    for item in demand_items:
        fitted = svc.build_fitted_series(item.customer_code, item.model_name)
        if fitted:
            item.tpm_series = fitted
            item.expected_tpm = max(tpm for _, tpm in fitted)  # 峰值基准同步为拟合序列峰值
