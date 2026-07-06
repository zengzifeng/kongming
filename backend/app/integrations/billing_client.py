from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass
class BillingRow:
    stat_date: date
    revenue: float
    cost_self: float
    cost_vendor: float


@dataclass
class BillingSeries:
    customer_code: str
    rows: list[BillingRow] = field(default_factory=list)


class BillingClient:
    def __init__(self, mode: str = "mock"):
        self.mode = mode

    def usage(self, customer_code: str, days: int = 7) -> BillingSeries:
        today = date.today()
        base_revenue = 8_000 if customer_code == "C0002" else 3_000
        rows = []
        for i in range(days):
            d = today - timedelta(days=i)
            rev = base_revenue * (0.8 + 0.4 * ((i * 7) % 5) / 5)
            rows.append(BillingRow(d, rev, rev * 0.45, rev * 0.20))
        return BillingSeries(customer_code, rows)
