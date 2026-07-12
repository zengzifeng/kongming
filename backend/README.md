# 孔明后端 (Kongming Backend)

V1 Flask 单体应用，详见 `../.plans/backend.md`。

## 快速开始

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
python run.py
```

默认在 `http://localhost:5001` 启动，使用 `instance/kongming.db` (SQLite)，所有外部 client 默认 mock 模式。

## 运行测试

```bash
pytest -q
```

## API 文档 (Swagger / OpenAPI)

启动后端后，浏览器直接打开 **<http://localhost:5001/apidocs>** 即为在线 Swagger UI（由
`flask-swagger-ui` 挂载，`pip install -e .` 已含该依赖）。规范原文由后端在
**<http://localhost:5001/openapi.yaml>** 提供，源文件是 [`../docs/openapi.yaml`](../docs/openapi.yaml)（OpenAPI 3.0，覆盖全部蓝图）。

离线查看规范文件（不启动后端）任选：

- 在线：把 `../docs/openapi.yaml` 内容贴到 <https://editor.swagger.io>
- VS Code：安装 “OpenAPI (Swagger) Editor” 插件后直接预览

## 目录结构

见 `.plans/backend.md` §2。
