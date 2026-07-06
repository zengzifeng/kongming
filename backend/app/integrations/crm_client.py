from dataclasses import dataclass


@dataclass
class CustomerProfile:
    customer_code: str
    name: str
    level: str
    paid_amount_total: float
    strategic_tag: str | None
    historical_achievement_rate: float


class CRMClient:
    def __init__(self, mode: str = "mock"):
        self.mode = mode

    def profile(self, customer_code: str) -> CustomerProfile:
        bank = {
            "C0001": CustomerProfile("C0001", "光合传媒", "A", 1_200_000, "media", 0.92),
            "C0002": CustomerProfile("C0002", "星海智算", "S", 3_800_000, "strategic", 1.05),
            "C0003": CustomerProfile("C0003", "墨方科技", "B", 250_000, None, 0.74),
        }
        return bank.get(
            customer_code,
            CustomerProfile(customer_code, customer_code, "C", 0, None, 0.6),
        )
