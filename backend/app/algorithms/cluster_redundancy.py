"""策略运行前计算自建集群的当前冗余（从实跑量推导，而非静态录入）。

集群承接能力（machine_count / tpm_per_machine / total_capacity_tpm）是录入的静态主数据；
但「当前冗余」= 承接能力 − 当前负载，其中当前负载来自实跑量里**该集群 provider** 的自建跑量。
故在每次组装快照、跑策略之前实时计算，保证冗余反映最新负载。

当前负载口径：取最新一个整点（max data_time）该 provider 的自建 Σio/60（与需求 expected_tpm
的「当前负载」口径一致）。集群与实跑量通过 provider（ksyun-*）关联。
"""
from __future__ import annotations

from ..extensions import db
from ..models import ClusterResource, MonitorConsumer, CustomerUsageHourly

SELF_SOURCE = "自建"


def _cfg(key: str, default):
    try:
        from flask import current_app

        return current_app.config.get(key, default)
    except Exception:
        return default


def _provider_by_cluster_name() -> dict[str, str]:
    """取最新 snapshot_date 各集群的 provider（存于 raw_json.provider）。"""
    from sqlalchemy import func

    latest = db.session.execute(db.select(func.max(ClusterResource.snapshot_date))).scalar()
    if latest is None:
        return {}
    rows = db.session.execute(
        db.select(ClusterResource).where(ClusterResource.snapshot_date == latest)
    ).scalars().all()
    return {r.cluster_name: (r.raw_json or {}).get("provider") for r in rows}


def _current_self_tpm_by_provider(exclude_customer_ids: set[int] | None = None) -> dict[str, float]:
    """最新整点各 provider 的自建负载 TPM = Σinput_output/60（排除指定客户，与 demand 口径一致）。"""
    latest_dt = db.session.execute(db.select(db.func.max(CustomerUsageHourly.data_time))).scalar()
    if latest_dt is None:
        return {}
    stmt = (
        db.select(
            CustomerUsageHourly.provider,
            db.func.sum(CustomerUsageHourly.input_output),
        )
        .where(
            CustomerUsageHourly.model_source == SELF_SOURCE,
            CustomerUsageHourly.data_time == latest_dt,
        )
        .group_by(CustomerUsageHourly.provider)
    )
    if exclude_customer_ids:
        stmt = stmt.where(CustomerUsageHourly.customer_id.notin_(exclude_customer_ids))
    rows = db.session.execute(stmt).all()
    return {prov: float(io or 0) / 60.0 for prov, io in rows}


def apply_current_redundancy(clusters: list[dict], exclude_customer_codes=None) -> None:
    """就地为集群 dict 计算并写入当前负载/冗余字段。

    设置：current_tpm、current_redundant_tpm、current_redundant_machines。
    provider 无对应实跑量则当前负载记 0（整集群空闲）。
    exclude_customer_codes（默认取 config）：整户剔除的客户，其量不计入自建负载，与 demand 口径一致。
    """
    if exclude_customer_codes is None:
        exclude_customer_codes = _cfg("EXCLUDE_CUSTOMER_CODES", ())
    exclude_codes = set(exclude_customer_codes or ())
    excluded_ids: set[int] = set()
    if exclude_codes:
        excluded_ids = {
            c.id for c in db.session.execute(db.select(MonitorConsumer)).scalars()
            if c.customer_code in exclude_codes
        }

    provider_map = _provider_by_cluster_name()
    load_by_provider = _current_self_tpm_by_provider(excluded_ids)

    for c in clusters:
        provider = provider_map.get(c.get("cluster_name"))
        current_tpm = load_by_provider.get(provider, 0.0) if provider else 0.0
        total_cap = float(c.get("total_capacity_tpm", 0) or 0)
        rate = float(c.get("tpm_per_machine", 0) or 0)
        redundant_tpm = max(total_cap - current_tpm, 0.0)
        c["current_tpm"] = current_tpm
        c["current_redundant_tpm"] = redundant_tpm
        c["current_redundant_machines"] = int(redundant_tpm // rate) if rate > 0 else 0
