from __future__ import annotations

from dataclasses import dataclass, field


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


class ResourceClient:
    def __init__(self, mode: str = "mock"):
        self.mode = mode

    def snapshot(self) -> ResourceSnapshot:
        from ..utils.time import utcnow

        clusters = [
            ClusterResourceItem(
                cluster_name="bj-h100-cluster-01",
                deployed_model="qwen2.5-72b",
                primary_customer="星海智算",
                machine_count=16,
                tpm_per_machine=37_500,
                total_capacity_tpm=600_000,
                peak_tpm_d1_23_24=520_000,
                peak_tpm_d2_23_24=505_000,
                peak_tpm_d3_23_24=498_000,
                peak_tpm_idle=180_000,
                idle_redundant_tpm=420_000,
                idle_redundant_machines=11,
                peak_tpm_busy=540_000,
                busy_redundant_tpm=60_000,
                busy_redundant_machines=1,
                current_tpm=410_000,
                current_redundant_tpm=190_000,
            ),
            ClusterResourceItem(
                cluster_name="sh-a100-cluster-01",
                deployed_model="gpt-4o-mini",
                primary_customer="光合传媒",
                machine_count=8,
                tpm_per_machine=37_500,
                total_capacity_tpm=300_000,
                peak_tpm_d1_23_24=250_000,
                peak_tpm_d2_23_24=245_000,
                peak_tpm_d3_23_24=260_000,
                peak_tpm_idle=80_000,
                idle_redundant_tpm=220_000,
                idle_redundant_machines=5,
                peak_tpm_busy=270_000,
                busy_redundant_tpm=30_000,
                busy_redundant_machines=1,
                current_tpm=190_000,
                current_redundant_tpm=110_000,
            ),
            ClusterResourceItem(
                cluster_name="sz-a800-cluster-01",
                deployed_model="deepseek-v3",
                primary_customer="墨方科技",
                machine_count=10,
                tpm_per_machine=40_000,
                total_capacity_tpm=400_000,
                peak_tpm_d1_23_24=300_000,
                peak_tpm_d2_23_24=280_000,
                peak_tpm_d3_23_24=315_000,
                peak_tpm_idle=120_000,
                idle_redundant_tpm=280_000,
                idle_redundant_machines=7,
                peak_tpm_busy=340_000,
                busy_redundant_tpm=60_000,
                busy_redundant_machines=1,
                current_tpm=210_000,
                current_redundant_tpm=190_000,
            ),
        ]
        return ResourceSnapshot(captured_at=utcnow().isoformat(), clusters=clusters)
