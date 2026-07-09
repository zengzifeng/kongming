from datetime import datetime
from sqlalchemy import String, Numeric, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from .base import BaseModel


class ModelListPrice(BaseModel):
    """模型列表价（刊例价）主数据：三档计价 + 生效区间。

    一条记录表示某 model 在 [effective_from, effective_to) 时间段内的三档列表价。
    这是两个求解器 _unit_self_revenue（自建收入密度＝排序主键）的价格来源：
    按 input_ratio 与 cache_hit_rate 加权命中/未命中输入价与输出价，得到每 TPM 自建收入。
    """

    __tablename__ = "model_list_prices"
    __table_args__ = (
        UniqueConstraint("model_name", "effective_from",
                         name="uq_model_price_effective"),
    )

    model_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    input_cache_hit_price: Mapped[float] = mapped_column(Numeric(12, 6), default=0)   # 输入命中列表价
    input_cache_miss_price: Mapped[float] = mapped_column(Numeric(12, 6), default=0)  # 输入未命中列表价
    output_price: Mapped[float] = mapped_column(Numeric(12, 6), default=0)            # 输出列表价
    effective_from: Mapped[datetime] = mapped_column(nullable=False)
    effective_to: Mapped[datetime | None] = mapped_column()
