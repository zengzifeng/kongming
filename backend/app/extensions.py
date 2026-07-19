import sqlite3

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from sqlalchemy import event
from sqlalchemy.engine import Engine


db = SQLAlchemy()
migrate = Migrate()


@event.listens_for(Engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    """SQLite 连接级调优：开 WAL 让读写不互斥，设 busy_timeout 让写冲突等待而非直接
    抛 "database is locked"（后端多实例/调度器与 API 并发访问同一库时尤其必要）。
    非 sqlite 连接不受影响。
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


def init_app(app):
    db.init_app(app)
    migrate.init_app(app, db)
