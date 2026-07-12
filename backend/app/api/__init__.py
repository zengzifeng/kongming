from flask import Flask

from .health import bp as health_bp
from .sync import bp as sync_bp
from .demands import bp as demands_bp
from .evaluations import bp as evaluations_bp
from .policies import bp as policies_bp
from .revenues import bp as revenues_bp
from .dashboards import bp as dashboards_bp
from .vendors import bp as vendors_bp
from .jobs import bp as jobs_bp
from .monitor import bp as monitor_bp
from .fittings import bp as fittings_bp
from .watched_clusters import bp as watched_clusters_bp
from .docs import bp as api_docs_bp, OPENAPI_SPEC_ROUTE


V1_PREFIX = "/api/v1"

# Swagger UI 挂载点与它拉取规范的路径（供 create_app / 前端参照）。
SWAGGER_UI_URL = "/apidocs"


def register_blueprints(app: Flask):
    app.register_blueprint(health_bp)
    app.register_blueprint(sync_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(demands_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(evaluations_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(policies_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(revenues_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(dashboards_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(vendors_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(jobs_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(monitor_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(fittings_bp, url_prefix=V1_PREFIX)
    app.register_blueprint(watched_clusters_bp, url_prefix=V1_PREFIX)

    # API 文档：规范原文（根路径 /openapi.yaml）+ Swagger UI（/apidocs）。
    app.register_blueprint(api_docs_bp)
    _register_swagger_ui(app)


def _register_swagger_ui(app: Flask):
    """挂载 Swagger UI 到 /apidocs，指向 /openapi.yaml。

    依赖 flask-swagger-ui；未安装时仅记录告警，不影响其余 API（规范原文仍可访问）。
    """
    try:
        from flask_swagger_ui import get_swaggerui_blueprint
    except ImportError:
        app.logger.warning(
            "flask-swagger-ui 未安装，跳过 %s 挂载（pip install -e . 可获取）；"
            "规范原文仍可从 %s 获取。", SWAGGER_UI_URL, OPENAPI_SPEC_ROUTE)
        return

    swagger_bp = get_swaggerui_blueprint(
        SWAGGER_UI_URL,
        OPENAPI_SPEC_ROUTE,
        config={"app_name": "空明 Kongming API"},
    )
    app.register_blueprint(swagger_bp, url_prefix=SWAGGER_UI_URL)


__all__ = ["register_blueprints", "SWAGGER_UI_URL", "OPENAPI_SPEC_ROUTE"]
