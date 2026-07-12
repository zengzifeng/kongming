from flask import Flask

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

    # 定时任务配置 seed（幂等）：即使调度线程未启用，前端仍可通过 /api/v1/jobs 管理。
    from .jobs.scheduler import ensure_default_schedules
    ensure_default_schedules(app)

    # 拟合算法目录 seed（幂等）：有哪些算法可选管理在库，API 只读。
    from .services.wave_fitting_service import ensure_default_fitting_algorithms
    ensure_default_fitting_algorithms(app)

    if app.config.get("SCHEDULER_ENABLED") and not app.config.get("TESTING"):
        from .jobs.scheduler import start_scheduler
        start_scheduler(app)

    return app
