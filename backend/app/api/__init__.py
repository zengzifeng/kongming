from flask import Flask

from .health import bp as health_bp
from .sync import bp as sync_bp
from .demands import bp as demands_bp
from .evaluations import bp as evaluations_bp
from .policies import bp as policies_bp
from .revenues import bp as revenues_bp
from .dashboards import bp as dashboards_bp
from .vendors import bp as vendors_bp


V1_PREFIX = "/api/v1"


def register_blueprints(app: Flask):
    app.register_blueprint(health_bp)
    app.register_blueprint(sync_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(demands_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(evaluations_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(policies_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(revenues_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(dashboards_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(vendors_bp, url_prefix=V1_PREFIX)


__all__ = ["register_blueprints"]
