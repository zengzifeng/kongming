from flask import Flask
from sqlalchemy import inspect, text

from . import extensions
from .config import CONFIG_MAP
from .utils import errors as errors_module
from .utils import logger as logger_module
from .utils import request_id as request_id_module


def create_app(config_name: str = "dev") -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.from_object(CONFIG_MAP[config_name])

    extensions.init_app(app)
    request_id_module.install(app)
    logger_module.install(app)
    errors_module.register_handlers(app)

    from .api import register_blueprints
    register_blueprints(app)

    with app.app_context():
        extensions.db.create_all()
        _apply_sqlite_compatibility_migrations()
        from .services.watched_cluster_service import ensure_default_watched_clusters
        ensure_default_watched_clusters(app)
        if app.config.get("SCHEDULER_ENABLED", True):
            from .jobs import start_scheduler
            start_scheduler(app)

    return app


def _apply_sqlite_compatibility_migrations() -> None:
    """补齐 create_all 无法加入既有 SQLite 表的新列。"""
    engine = extensions.db.engine
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    demand_columns = {column["name"] for column in inspector.get_columns("demands")}
    policy_columns = {column["name"] for column in inspector.get_columns("policies")}

    with engine.begin() as connection:
        if "extra" not in demand_columns:
            connection.execute(text("ALTER TABLE demands ADD COLUMN extra JSON"))
        if "demand_id" not in policy_columns:
            connection.execute(text("ALTER TABLE policies ADD COLUMN demand_id INTEGER REFERENCES demands(id)"))
        connection.execute(text("CREATE INDEX IF NOT EXISTS ix_policies_demand_id ON policies(demand_id)"))
