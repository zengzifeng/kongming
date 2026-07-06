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

## 目录结构

见 `.plans/backend.md` §2。
