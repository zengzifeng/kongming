"""拟合算法注册中心：entry_ref -> 算法实例。

fitting_algorithms 表存的是「可选算法目录」（主数据）；本注册表存的是每个 entry_ref
对应的代码实现。二者通过 entry_ref 关联：表里登记一条算法必须有一个已注册的 entry_ref。
"""
from __future__ import annotations

from ...utils.errors import ValidationFailed
from .base import FittingAlgorithm, FittingInput
from .demo import DemoFittingAlgorithm


_ALGORITHMS: dict[str, FittingAlgorithm] = {
    "demo": DemoFittingAlgorithm(),
}


def get_fitting_algorithm(entry_ref: str) -> FittingAlgorithm:
    algo = _ALGORITHMS.get(entry_ref)
    if algo is None:
        raise ValidationFailed(
            f"未知拟合算法入口: {entry_ref}",
            details={"available": list(_ALGORITHMS)},
        )
    return algo


__all__ = ["FittingAlgorithm", "FittingInput", "get_fitting_algorithm"]
