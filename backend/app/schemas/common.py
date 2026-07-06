from __future__ import annotations

from datetime import datetime
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict


T = TypeVar("T")


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PageMeta(BaseModel):
    page: int
    page_size: int
    total: int


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.isoformat()


def model_to_dict(obj: Any, exclude: set[str] | None = None) -> dict:
    if obj is None:
        return None
    columns = obj.__table__.columns.keys()
    result = {}
    for col in columns:
        if exclude and col in exclude:
            continue
        value = getattr(obj, col)
        if isinstance(value, datetime):
            value = value.isoformat()
        elif hasattr(value, "isoformat"):
            value = value.isoformat()
        result[col] = value
    return result
