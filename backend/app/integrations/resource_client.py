from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClusterResourceItem:
    cluster_name: str
    deployed_model: str            # 与 cluster_name 等同（大小写不敏感匹配）
    provider: str | None
    machine_count: int             # 来自监控 node_count
    tpm_per_machine: float         # 来自 cluster_capacities（前端录入）
    total_capacity_tpm: float      # = machine_count × tpm_per_machine
    current_tpm: float             # 来自监控最新时点 tpm
    current_redundant_tpm: float
    current_redundant_machines: int = 0
    raw_json: dict[str, Any] = field(default_factory=dict)


@dataclass
class ResourceSnapshot:
    captured_at: str
    clusters: list[ClusterResourceItem] = field(default_factory=list)

    @property
    def total_capacity_tpm(self) -> float:
        return sum(c.total_capacity_tpm for c in self.clusters)

    @property
    def total_current_redundant_tpm(self) -> float:
        return sum(c.current_redundant_tpm for c in self.clusters)


def _mock_clusters() -> list[ClusterResourceItem]:
    """无监控数据时的合成集群（仅 mock 模式，dev/测试用）。cluster_name=部署模型名。"""
    seed = [
        ("qwen2.5-72b", 16, 37_500, 410_000, "ksyun-qwen"),
        ("gpt-4o-mini", 8, 37_500, 190_000, "ksyun-gpt"),
        ("deepseek-v3", 10, 40_000, 210_000, "ksyun-dsv3"),
    ]
    out: list[ClusterResourceItem] = []
    for name, machines, rate, current, provider in seed:
        total = machines * rate
        redundant = max(total - current, 0.0)
        out.append(ClusterResourceItem(
            cluster_name=name, deployed_model=name, provider=provider,
            machine_count=machines, tpm_per_machine=rate, total_capacity_tpm=total,
            current_tpm=current, current_redundant_tpm=redundant,
            current_redundant_machines=int(redundant // rate) if rate > 0 else 0,
        ))
    return out


class ResourceClient:
    """自建集群资源快照。

    cluster_resources 表已废弃：快照改由「监控实跑（cluster_model_tpm 最新批次）
    + 单机承接能力（cluster_capacities，前端录入）+ provider（provider_mappings）」组装。
    total_capacity_tpm = 台数 × 单机承接能力；当前冗余 = 容量 − 实跑。
    无监控数据且 mode==mock 时回退合成集群（dev/测试）。
    """

    def __init__(self, mode: str = "mock"):
        self.mode = mode

    def snapshot(self) -> ResourceSnapshot:
        from ..extensions import db
        from ..models import ClusterCapacity, ClusterModelTpm, ProviderMapping
        from ..utils.model_name import normalize_model_name
        from ..utils.time import utcnow

        now = utcnow()
        batch_id = db.session.execute(
            db.select(db.func.max(ClusterModelTpm.batch_id))
        ).scalar()
        if batch_id is None:
            clusters = _mock_clusters() if self.mode == "mock" else []
            return ResourceSnapshot(captured_at=now.isoformat(), clusters=clusters)

        rows = db.session.execute(
            db.select(ClusterModelTpm)
            .where(ClusterModelTpm.batch_id == batch_id)
            .order_by(ClusterModelTpm.cluster_name.asc(), ClusterModelTpm.data_time.asc())
        ).scalars().all()
        latest: dict[str, ClusterModelTpm] = {}
        for r in rows:
            latest[r.cluster_name] = r  # 升序遍历，保留最后一个时点

        cap = {
            (c.cluster_name or "").lower(): float(c.tpm_per_machine or 0)
            for c in db.session.execute(db.select(ClusterCapacity)).scalars()
        }
        prov: dict[str, str] = {}
        for m in db.session.execute(db.select(ProviderMapping)).scalars():
            if m.cluster_name:
                prov.setdefault(m.cluster_name.lower(), m.provider)

        clusters: list[ClusterResourceItem] = []
        for name, r in latest.items():
            machine_count = int(r.node_count or 0)
            rate = cap.get(name.lower(), 0.0)
            total_cap = machine_count * rate
            current = float(r.tpm or 0)
            redundant = max(total_cap - current, 0.0)
            clusters.append(ClusterResourceItem(
                cluster_name=name,
                deployed_model=normalize_model_name(name),  # 与需求 model 同为小写规范形，供按模型匹配/聚合
                provider=prov.get(name.lower()),
                machine_count=machine_count,
                tpm_per_machine=rate,
                total_capacity_tpm=total_cap,
                current_tpm=current,
                current_redundant_tpm=redundant,
                current_redundant_machines=int(redundant // rate) if rate > 0 else 0,
                raw_json={},
            ))
        return ResourceSnapshot(captured_at=now.isoformat(), clusters=clusters)
