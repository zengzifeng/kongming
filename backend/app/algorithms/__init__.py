from __future__ import annotations

from ..utils.errors import ValidationFailed
from .base import (
    ConstraintHit,
    DemandSnapshotItem,
    PolicyActionDraft,
    PolicyInputSnapshot,
    PolicyResult,
    Solver,
)
from .snapshot import build_snapshot, build_run_snapshot
from .realtime_solver import RealtimeSolver
from .time_period_solver import TimePeriodSolver
from .demand_evaluation_solver import DemandEvaluationSolver


_SOLVERS: dict[str, Solver] = {
    "realtime": RealtimeSolver(),
    "time_period": TimePeriodSolver(),
    "demand_evaluation": DemandEvaluationSolver(),
}


def get_solver(name: str) -> Solver:
    solver = _SOLVERS.get(name)
    if solver is None:
        raise ValidationFailed(f"未知算法: {name}", details={"available": list(_SOLVERS)})
    return solver


__all__ = [
    "ConstraintHit",
    "DemandSnapshotItem",
    "PolicyActionDraft",
    "PolicyInputSnapshot",
    "PolicyResult",
    "Solver",
    "build_snapshot",
    "build_run_snapshot",
    "get_solver",
    "RealtimeSolver",
    "TimePeriodSolver",
    "DemandEvaluationSolver",
]
