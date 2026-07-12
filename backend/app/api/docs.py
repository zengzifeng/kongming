"""API 文档：对外提供 OpenAPI 规范原文 + 挂载 Swagger UI。

规范文件是仓库根 docs/openapi.yaml（单一事实来源，手工维护）。
本蓝图只负责把它作为静态内容吐出来，Swagger UI 蓝图在 create_app 中注册并指向它。
"""
from __future__ import annotations

from pathlib import Path

from flask import Blueprint, Response

from ..utils.errors import NotFound


bp = Blueprint("api_docs", __name__)

# backend/app/api/docs.py -> 仓库根/docs/openapi.yaml
_SPEC_PATH = Path(__file__).resolve().parents[3] / "docs" / "openapi.yaml"

# Swagger UI 通过该路径拉取规范；create_app 里把它配给 swagger blueprint。
OPENAPI_SPEC_ROUTE = "/openapi.yaml"


@bp.get(OPENAPI_SPEC_ROUTE)
def openapi_spec():
    if not _SPEC_PATH.exists():
        raise NotFound("OpenAPI 规范文件不存在", details={"path": str(_SPEC_PATH)})
    text = _SPEC_PATH.read_text(encoding="utf-8")
    return Response(text, mimetype="application/yaml")
