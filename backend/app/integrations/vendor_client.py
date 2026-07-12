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
    actual_tpm: float = 0.0
    actual_redundant_tpm: float = 0.0
    purchase_discount: float = 0.0


# 兼容旧导入名：算法层与 snapshot.py 早期引用 VendorQuota
VendorQuota = VendorQuotaDTO


_SEED = [
    ("百度", "thirdparty-baidu-ofb", "glm-5.2", 12_000_000, 0.75, "供应量级 1200 万 TPM"),
    ("鼎鼎方游", "thirdparty-ddfy-openai", "glm-5.2", 50_000_000, 0.73, "供应量级 5000 万 TPM"),
    ("香港锦望", "thirdparty-hkjw-openai", "glm-5.2", 10_000_000, 0.55, "供应量级 1000 万 TPM"),
    ("月暗原厂", "thirdparty-kimi-fc", "kimi-k2.5", 60_000_000, 0.80, "供应量级 6000 万 TPM"),
    ("月暗原厂", "thirdparty-kimi-fc", "kimi-k2.6", 100_000_000, 0.80, "供应量级 10000 万 TPM"),
    ("百度", "thirdparty-baidu-ofb", "deepseek-v32", 12_000_000, 0.40, "供应量级 1200 万 TPM"),
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
                actual_tpm=float(getattr(r, "actual_tpm", 0) or 0),
                actual_redundant_tpm=float(getattr(r, "actual_redundant_tpm", 0) or 0),
                purchase_discount=float(getattr(r, "purchase_discount", 0) or 0),
            )
            for r in rows
        ]

    @staticmethod
    def _seed(now: datetime):
        from ..extensions import db
        from ..models import VendorQuota as VendorQuotaModel

        created = []
        for vendor, provider, model, quota, discount, notes in _SEED:
            row = VendorQuotaModel(
                vendor=vendor,
                model=model,
                quota_tpm=quota,
                actual_tpm=0,
                actual_redundant_tpm=quota,
                unit_cost=0,
                unit_price=0,
                purchase_discount=discount,
                effective_from=now - timedelta(days=1),
                notes=notes,
                raw_json={"source": "manual-image", "provider": provider, "quota_w": quota / 10000},
            )

            db.session.add(row)
            created.append(row)
        db.session.flush()
        return created
