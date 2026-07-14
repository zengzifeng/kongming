"""给 watched_clusters 增加 dedicated 列，并按 provider_mappings「只绑定单一客户」的集群初始化标记。

dedicated=True 的集群只服务它自己的客户，产能不并入共享模型池（详见 time_period 求解器）。
初始化用「单客户」启发式点亮，后续可在 watched_clusters 上手动增删。

用法（backend 目录下）：
    python scripts/migrate_watched_dedicated.py
"""
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import func

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.config import INSTANCE_DIR  # noqa: E402


def _ensure_column() -> None:
    """先用原生 sqlite 补列，避免 create_app 触发 ORM 查询时列尚不存在而报错。"""
    db_path = INSTANCE_DIR / "kongming.db"
    if not db_path.exists():
        print(f"db not found, skip pre-add: {db_path}")
        return
    conn = sqlite3.connect(str(db_path))
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(watched_clusters)")}
        if "dedicated" not in cols:
            conn.execute("ALTER TABLE watched_clusters ADD COLUMN dedicated BOOLEAN NOT NULL DEFAULT 0")
            conn.commit()
            print("added dedicated column")
        else:
            print("dedicated column exists")
    finally:
        conn.close()


def main():
    _ensure_column()

    from app import create_app
    from app.extensions import db
    from app.models import ProviderMapping, WatchedCluster

    app = create_app("dev")
    with app.app_context():
        # provider_mappings 里映射到单一客户的集群 → 视为专属集群；同时取其唯一模型名做 deployed_model 回填。
        rows = db.session.execute(
            db.select(ProviderMapping.cluster_name, func.count(func.distinct(ProviderMapping.customer_name)))
            .group_by(ProviderMapping.cluster_name)
        ).all()
        single_customer = {name for name, n in rows if name and n == 1}
        model_of = {}
        for m in db.session.execute(db.select(ProviderMapping)).scalars():
            if m.cluster_name:
                model_of.setdefault(m.cluster_name.lower(), (m.model_name or "").strip().lower() or None)

        # 大小写不敏感匹配已存在的 watched 行，避免仅因大小写差异重复插入。
        watched = {w.cluster_name.lower(): w for w in db.session.execute(db.select(WatchedCluster)).scalars()}
        flagged = []
        for name in single_customer:
            w = watched.get(name.lower())
            if w is None:
                w = WatchedCluster(cluster_name=name, enabled=True, dedicated=True,
                                   deployed_model=model_of.get(name.lower()))
                db.session.add(w)
                watched[name.lower()] = w
                flagged.append(name)
                continue
            changed = False
            if not w.dedicated:
                w.dedicated = True
                changed = True
            if not w.deployed_model and model_of.get(name.lower()):
                w.deployed_model = model_of[name.lower()]  # 回填部署模型，保证专属集群能匹配到其模型需求
                changed = True
            if changed:
                flagged.append(w.cluster_name)


        db.session.commit()
        print(f"flagged dedicated ({len(flagged)}): {sorted(flagged)}")
        print("all dedicated:", sorted(
            w.cluster_name for w in db.session.execute(
                db.select(WatchedCluster).where(WatchedCluster.dedicated.is_(True))
            ).scalars()
        ))



if __name__ == "__main__":
    main()
