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

    if app.config.get("SCHEDULER_ENABLED") and not app.config.get("TESTING"):
        from .jobs.scheduler import start_scheduler
        start_scheduler(app)

    return app
