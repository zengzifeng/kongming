from datetime import datetime
from sqlalchemy.orm import Mapped, mapped_column

from ..extensions import db
from ..utils.time import utcnow


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow, nullable=False)


class BaseModel(db.Model, TimestampMixin):
    __abstract__ = True
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
