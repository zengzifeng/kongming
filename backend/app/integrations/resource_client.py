from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClusterResourceItem:
    cluster_name: str
    deployed_model: str
    primary_customer: str | None
    machine_count: int
    tpm_per_machine: float
    total_capacity_tpm: float
    peak_tpm_d1_23_24: float
    peak_tpm_d2_23_24: float
    peak_tpm_d3_23_24: float
    peak_tpm_idle: float
    idle_redundant_tpm: float
    idle_redundant_machines: int
    peak_tpm_busy: float
    busy_redundant_tpm: float
    busy_redundant_machines: int
    current_tpm: float
    current_redundant_tpm: float
    current_redundant_machines: int = 0  # 可供出机器数（录入「冗余台数」），求解器 _donatable_machines 的正典键
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

    @property
    def total_idle_redundant_tpm(self) -> float:
        return sum(c.idle_redundant_tpm for c in self.clusters)

    @property
    def total_busy_redundant_tpm(self) -> float:
        return sum(c.busy_redundant_tpm for c in self.clusters)


# mock 种子：空库时（mode==mock）写入 cluster_resources 并返回，保证 dev/测试可跑。
# current_redundant_machines 取 = idle_redundant_machines（当前可供出台数）。
_MOCK_CLUSTERS: list[dict] = [
    dict(cluster_name="bj-h100-cluster-01", deployed_model="qwen2.5-72b", primary_customer="星海智算",
         machine_count=16, tpm_per_machine=37_500, total_capacity_tpm=600_000,
         peak_tpm_d1_23_24=520_000, peak_tpm_d2_23_24=505_000, peak_tpm_d3_23_24=498_000,
         peak_tpm_idle=180_000, idle_redundant_tpm=420_000, idle_redundant_machines=11,
         peak_tpm_busy=540_000, busy_redundant_tpm=60_000, busy_redundant_machines=1,
         current_tpm=410_000, current_redundant_tpm=190_000, current_redundant_machines=11),
    dict(cluster_name="sh-a100-cluster-01", deployed_model="gpt-4o-mini", primary_customer="光合传媒",
         machine_count=8, tpm_per_machine=37_500, total_capacity_tpm=300_000,
         peak_tpm_d1_23_24=250_000, peak_tpm_d2_23_24=245_000, peak_tpm_d3_23_24=260_000,
         peak_tpm_idle=80_000, idle_redundant_tpm=220_000, idle_redundant_machines=5,
         peak_tpm_busy=270_000, busy_redundant_tpm=30_000, busy_redundant_machines=1,
         current_tpm=190_000, current_redundant_tpm=110_000, current_redundant_machines=5),
    dict(cluster_name="sz-a800-cluster-01", deployed_model="deepseek-v3", primary_customer="墨方科技",
         machine_count=10, tpm_per_machine=40_000, total_capacity_tpm=400_000,
         peak_tpm_d1_23_24=300_000, peak_tpm_d2_23_24=280_000, peak_tpm_d3_23_24=315_000,
         peak_tpm_idle=120_000, idle_redundant_tpm=280_000, idle_redundant_machines=7,
         peak_tpm_busy=340_000, busy_redundant_tpm=60_000, busy_redundant_machines=1,
         current_tpm=210_000, current_redundant_tpm=190_000, current_redundant_machines=7),
]

# ClusterResourceItem 的字段名与 ClusterResource 模型列名一一对应，用于逐行映射。
_ITEM_FIELDS = [f for f in ClusterResourceItem.__dataclass_fields__]
_STR_FIELDS = {"cluster_name", "deployed_model", "primary_customer"}
_INT_FIELDS = {"machine_count", "idle_redundant_machines", "busy_redundant_machines", "current_redundant_machines"}


def _to_item(row) -> ClusterResourceItem:
    kwargs = {}
    for f in _ITEM_FIELDS:
        v = getattr(row, f, None)
        if f == "raw_json":
            kwargs[f] = dict(v or {})
        elif f == "primary_customer":
            kwargs[f] = v  # 可空字符串，原样保留
        elif f in _STR_FIELDS:
            kwargs[f] = str(v) if v is not None else ""
        elif f in _INT_FIELDS:
            kwargs[f] = int(v or 0)
        else:
            kwargs[f] = float(v or 0)
    return ClusterResourceItem(**kwargs)


class ResourceClient:
    def __init__(self, mode: str = "mock"):
        self.mode = mode

    def snapshot(self) -> ResourceSnapshot:
        from sqlalchemy import func

        from ..extensions import db
        from ..models import ClusterResource
        from ..utils.time import utcnow

        now = utcnow()
        # 取最新 snapshot_date 的所有集群行，避免多天快照叠加。
        latest = db.session.execute(
            db.select(func.max(ClusterResource.snapshot_date))
        ).scalar()
        rows = []
        if latest is not None:
            rows = db.session.execute(
                db.select(ClusterResource).where(ClusterResource.snapshot_date == latest)
            ).scalars().all()

        if not rows and self.mode == "mock":
            rows = self._seed(now.date())

        return ResourceSnapshot(
            captured_at=now.isoformat(),
            clusters=[_to_item(r) for r in rows],
        )

    @staticmethod
    def _seed(snapshot_date):
        from ..extensions import db
        from ..models import ClusterResource

        created = []
        for c in _MOCK_CLUSTERS:
            row = ClusterResource(snapshot_date=snapshot_date, **c)
            db.session.add(row)
            created.append(row)
        db.session.flush()
        return created
