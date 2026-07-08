from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol


@dataclass
class DemandSnapshotItem:
    report_id: str
    customer_code: str
    model_name: str
    expected_tpm: float
    expected_rpm: float
    discount_rate: float
    input_ratio: float = 1.0  # 输入:输出 token 比值，如 3 表示 3:1；输出基准恒为 1
    cache_hit_rate: float = 0.0
    current_self_ratio: float = 0.0
    current_vendor_ratios: dict[str, float] = field(default_factory=dict)
    quality_score: float = 0.0
    # 时段拟合业务量序列 [(timestamp_iso, tpm), ...]。为空时退化为用 expected_tpm 的平序列，
    # 供 time_period 算法做整段收入积分；realtime 不使用此字段，向后兼容。
    tpm_series: list[tuple[str, float]] = field(default_factory=list)


@dataclass
class ConstraintHit:
    name: str
    hit: bool
    threshold: float | None = None
    actual: float | None = None
    description: str | None = None


@dataclass
class PolicyActionDraft:
    action_type: str
    payload: dict
    expected_gain: float = 0.0


@dataclass
class PolicyInputSnapshot:
    captured_at: datetime
    algorithm: str
    demands: list[DemandSnapshotItem]
    resources: dict
    monitoring: dict
    vendors: list[dict]
    params: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "captured_at": self.captured_at.isoformat(),
            "algorithm": self.algorithm,
            "demands": [d.__dict__ for d in self.demands],
            "resources": self.resources,
            "monitoring": self.monitoring,
            "vendors": self.vendors,
            "params": self.params,
        }


@dataclass
class PolicyResult:
    expected_revenue_gain: float
    expected_peak_shaving_gain: float
    expected_off_peak_gain: float
    constraints: list[ConstraintHit]
    actions: list[PolicyActionDraft]
    diagnostics: dict = field(default_factory=dict)
    summary: dict = field(default_factory=dict)


class Solver(Protocol):
    name: str

    def solve(self, snapshot: PolicyInputSnapshot) -> PolicyResult: ...
