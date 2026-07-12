from __future__ import annotations

from sqlalchemy import func, select

from ..extensions import db
from ..models import WatchedCluster
from ..utils.errors import NotFound, StateConflict, ValidationFailed


DEFAULT_WATCHED_CLUSTERS = [
    "DeepSeek-V3.2",
    "GLM-5.1-FP8",
    "GLM-5.1-KSCC",
    "GLM-5.1-XISHANJU",
    "GLM-5.2",
    "GLM-5.2-Tencent",
    "jl-test",
    "Kimi-K2.5-NVFP4-MIHAYOU",
    "KSCC-TEST",
    "llc-test1",
    "wd-test",
    "weilai-test",
]


class WatchedClusterService:
    def list(self, include_disabled: bool = False) -> list[WatchedCluster]:
        stmt = select(WatchedCluster)
        if not include_disabled:
            stmt = stmt.where(WatchedCluster.enabled.is_(True))
        stmt = stmt.order_by(WatchedCluster.sort_order.asc(), WatchedCluster.cluster_name.asc())
        return list(db.session.execute(stmt).scalars())

    def get(self, cluster_id: int) -> WatchedCluster:
        cluster = db.session.get(WatchedCluster, cluster_id)
        if not cluster:
            raise NotFound("关注集群不存在", details={"id": cluster_id})
        return cluster

    def create(self, payload: dict) -> WatchedCluster:
        name = self._normalize_name(payload.get("cluster_name"))
        self._ensure_unique_name(name)
        cluster = WatchedCluster(
            cluster_name=name,
            enabled=bool(payload.get("enabled", True)),
            sort_order=self._normalize_order(payload.get("sort_order"), self._next_order()),
        )
        db.session.add(cluster)
        db.session.commit()
        return cluster

    def update(self, cluster_id: int, patch: dict) -> WatchedCluster:
        cluster = self.get(cluster_id)
        if "cluster_name" in patch and patch["cluster_name"] is not None:
            name = self._normalize_name(patch["cluster_name"])
            self._ensure_unique_name(name, exclude_id=cluster.id)
            cluster.cluster_name = name
        if "enabled" in patch and patch["enabled"] is not None:
            cluster.enabled = bool(patch["enabled"])
        if "sort_order" in patch and patch["sort_order"] is not None:
            cluster.sort_order = self._normalize_order(patch["sort_order"], cluster.sort_order)
        db.session.commit()
        return cluster

    def delete(self, cluster_id: int) -> None:
        cluster = self.get(cluster_id)
        db.session.delete(cluster)
        db.session.commit()

    def _ensure_unique_name(self, name: str, exclude_id: int | None = None) -> None:
        stmt = select(WatchedCluster).where(WatchedCluster.cluster_name == name)
        if exclude_id is not None:
            stmt = stmt.where(WatchedCluster.id != exclude_id)
        exists = db.session.execute(stmt).scalar_one_or_none()
        if exists:
            raise StateConflict("关注集群名称已存在", details={"cluster_name": name})

    @staticmethod
    def _normalize_name(value) -> str:
        name = str(value or "").strip()
        if not name:
            raise ValidationFailed("关注集群名称不能为空")
        if len(name) > 128:
            raise ValidationFailed("关注集群名称不能超过 128 个字符")
        return name

    @staticmethod
    def _normalize_order(value, fallback: int) -> int:
        try:
            order = int(value if value is not None else fallback)
        except (TypeError, ValueError) as exc:
            raise ValidationFailed("排序值必须是整数") from exc
        if order < 0:
            raise ValidationFailed("排序值不能小于 0")
        return order

    @staticmethod
    def _next_order() -> int:
        current = db.session.execute(select(func.max(WatchedCluster.sort_order))).scalar()
        return int(current or 0) + 1


def ensure_default_watched_clusters(app) -> None:
    with app.app_context():
        existing = {
            item.cluster_name
            for item in db.session.execute(select(WatchedCluster)).scalars()
        }
        added = False
        for index, name in enumerate(DEFAULT_WATCHED_CLUSTERS, start=1):
            if name in existing:
                continue
            db.session.add(WatchedCluster(cluster_name=name, enabled=True, sort_order=index))
            added = True
        if added:
            db.session.commit()
