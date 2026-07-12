"""API 文档：OpenAPI 规范原文可取；Swagger UI 已安装时挂载在 /apidocs。"""


def test_openapi_spec_served(client):
    res = client.get("/openapi.yaml")
    assert res.status_code == 200, res.status_code
    assert "application/yaml" in res.content_type
    body = res.get_data(as_text=True)
    assert body.lstrip().startswith("openapi:")
    assert "/api/v1/fittings/algorithms" in body  # 覆盖到拟合模块


def test_apidocs_mounted_when_available(client):
    """flask-swagger-ui 已安装则 /apidocs/ 返回 UI 页面；未安装则跳过（规范原文不受影响）。"""
    try:
        import flask_swagger_ui  # noqa: F401
    except ImportError:
        import pytest

        pytest.skip("flask-swagger-ui 未安装")
    res = client.get("/apidocs/")
    assert res.status_code == 200, res.status_code
    assert b"swagger" in res.data.lower()
