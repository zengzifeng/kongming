from __future__ import annotations

from typing import Generic, Type, TypeVar

from sqlalchemy import select, func

from ..extensions import db


T = TypeVar("T")


class BaseRepository(Generic[T]):
    model: Type[T]

    def __init__(self, model: Type[T] | None = None):
        if model is not None:
            self.model = model

    @property
    def session(self):
        return db.session

    def get(self, id: int) -> T | None:
        return self.session.get(self.model, id)

    def add(self, obj: T) -> T:
        self.session.add(obj)
        self.session.flush()
        return obj

    def delete(self, obj: T):
        self.session.delete(obj)

    def commit(self):
        self.session.commit()

    def list_paginated(self, filters: list | None = None, order_by=None, page: int = 1, page_size: int = 20):
        stmt = select(self.model)
        if filters:
            stmt = stmt.where(*filters)
        if order_by is not None:
            stmt = stmt.order_by(order_by)
        else:
            stmt = stmt.order_by(self.model.id.desc())
        total = self.session.execute(
            select(func.count()).select_from(stmt.subquery())
        ).scalar_one()
        items = self.session.execute(
            stmt.limit(page_size).offset((page - 1) * page_size)
        ).scalars().all()
        return items, total
