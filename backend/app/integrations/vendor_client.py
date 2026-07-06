from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta


@dataclass
class VendorQuotaDTO:
    vendor: str
    model: str
    quota_tpm: float
    unit_cost: float
    unit_price: float


# 兼容旧导入名：算法层与 snapshot.py 早期引用 VendorQuota
VendorQuota = VendorQuotaDTO


_SEED = [
    ("openai", "gpt-4o-mini", 400_000, 0.0008, 0.0015, "OpenAI 官方"),
    ("aliyun", "qwen2.5-72b", 800_000, 0.0004, 0.0010, "阿里云百炼"),
    ("volc", "deepseek-v3", 1_200_000, 0.0003, 0.0009, "火山方舟"),
]


class VendorClient:
    def __init__(self, mode: str = "mock"):
        self.mode = mode

    def quotas(self) -> list[VendorQuotaDTO]:
        from ..extensions import db
        from ..models import VendorQuota as VendorQuotaModel
        from ..models.vendor import VendorStatus
        from ..utils.time import utcnow

        now = utcnow()
        rows = db.session.execute(
            db.select(VendorQuotaModel).where(
                VendorQuotaModel.status == VendorStatus.ACTIVE,
                VendorQuotaModel.effective_from <= now,
                db.or_(
                    VendorQuotaModel.effective_to.is_(None),
                    VendorQuotaModel.effective_to > now,
                ),
            )
        ).scalars().all()

        if not rows and self.mode == "mock":
            rows = self._seed(now)

        return [
            VendorQuotaDTO(
                vendor=r.vendor,
                model=r.model,
                quota_tpm=float(r.quota_tpm),
                unit_cost=float(r.unit_cost),
                unit_price=float(r.unit_price),
            )
            for r in rows
        ]

    @staticmethod
    def _seed(now: datetime):
        from ..extensions import db
        from ..models import VendorQuota as VendorQuotaModel

        created = []
        for vendor, model, quota, cost, price, notes in _SEED:
            row = VendorQuotaModel(
                vendor=vendor,
                model=model,
                quota_tpm=quota,
                unit_cost=cost,
                unit_price=price,
                effective_from=now - timedelta(days=1),
                notes=notes,
            )
            db.session.add(row)
            created.append(row)
        db.session.flush()
        return created
