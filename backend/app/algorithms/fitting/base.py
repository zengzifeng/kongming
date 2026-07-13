"""波形拟合算法框架的输入契约与协议。

拟合算法按「客户+模型+时段」粒度调用：读入过去同时段跑量序列 + 已确定的需求增/减量，
产出目标时段的波形（[(timestamp_iso, tpm), ...]）。集群级波形由服务层叠加客户波形得到，
不在单个算法内处理。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class FittingInput:
    """单次拟合（客户+模型+某时段）的输入。

    past_series   : 过去该时段的历史跑量 [(timestamp_iso, tpm), ...]，按时间升序。
    period        : "idle" / "busy"。
    period_hours  : 该时段覆盖的整点小时集合（0-23），来自全局 config。
    delta_tpm     : 已确定的需求增/减量（正为增、负为减），人工配置。
    params        : 算法其余入参（关联配置 params_json 与算法 default_params 合并）。
    """

    ai_consumer: str
    model_name: str
    period: str
    period_hours: frozenset[int]
    past_series: list[tuple[str, float]]
    delta_tpm: float = 0.0
    params: dict = field(default_factory=dict)


class FittingAlgorithm(Protocol):
    name: str

    def fit(self, data: FittingInput) -> list[tuple[str, float]]:
        """产出目标时段波形 [(timestamp_iso, tpm), ...]。"""
        ...
