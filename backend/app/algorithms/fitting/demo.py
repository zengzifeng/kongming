"""demo 拟合算法：本阶段最简实现。

预测口径：把客户前一天相同时段的量原封不动搬到下一个时段作为预测数据。
增减量口径：需求增/减量在该时段所有点上均摊等量增减（每点 ± delta_tpm / 点数），负值按 0 兜底。
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .base import FittingInput


class DemoFittingAlgorithm:
    name = "demo"

    def fit(self, data: FittingInput) -> list[tuple[str, float]]:
        series = data.past_series
        if not series:
            return []

        # 均摊增/减量：每点等量增减 delta_tpm / 点数。
        per_slot = data.delta_tpm / len(series) if series else 0.0

        result: list[tuple[str, float]] = []
        for ts, tpm in series:
            next_ts = self._shift_one_day(ts)
            adjusted = float(tpm) + per_slot
            result.append((next_ts, max(0.0, adjusted)))  # 减量后不为负
        return result

    @staticmethod
    def _shift_one_day(ts_iso: str) -> str:
        """把时间戳平移到「下一个时段」——以自然日为周期，+1 天保持同一整点。

        解析失败（非 ISO）时原样返回，保证 demo 不因脏数据崩溃。
        """
        try:
            dt = datetime.fromisoformat(ts_iso)
        except (ValueError, TypeError):
            return ts_iso
        return (dt + timedelta(days=1)).isoformat()
