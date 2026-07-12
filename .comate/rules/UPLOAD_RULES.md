# 代码上传规则（UPLOAD_RULES）

本仓库遵循「**只上传项目源码**」原则。以下类别的文件**不纳入 Git 版本库**，具体匹配规则见 [`.gitignore`](.gitignore)。

## 不上传的内容

| 类别 | 说明 | 典型匹配 |
|---|---|---|
| **Claude 运行生成文件** | 会话中为跑数据、产出策略而生成的适配脚本与中间产物 | `run_*_on_testdata.py`、`run_realtime_v2.py`、`export_*.py`、`_*.json`、`_*.txt`、`*-导出.xlsx` |
| **测试数据** | 输入测试用的表格数据 | `kongming-测试数据*.xlsx`、`*.xlsx`、`*.csv` |
| **Python 编译与环境** | 虚拟环境、字节码、构建缓存 | `.venv/`、`__pycache__/`、`*.pyc`、`*.egg-info/`、`.pytest_cache/`、`.ruff_cache/` |
| **实例数据 / 本地库** | 运行期生成的数据库与实例目录 | `backend/instance/`、`*.db`、`*.sqlite*` |
| **前端依赖与构建产物** | 依赖、缓存、编译输出 | `node_modules/`、`.npm-cache/`、`dist/`、`*.tsbuildinfo`、`vite.config.js`（由 `.ts` 编译） |
| **系统 / 编辑器元数据** | macOS/编辑器杂项 | `._*`、`.DS_Store`、`.idea/`、`.vscode/` |

## 上传的内容（项目源码）

- 后端：`backend/app/`、`backend/tests/`、`backend/pyproject.toml`、`backend/run.py`、`backend/README.md`
- 前端：`frontend/src/`、`frontend/index.html`、`frontend/package.json`、`frontend/package-lock.json`、`frontend/tsconfig*.json`、`frontend/vite.config.ts`
- 根目录运维脚本：`*-windows.bat`
- 本文件与 `.gitignore`

## 变更约定

调整上传范围时，**同步更新 `.gitignore` 与本文件**，保持二者一致。新增会导出结果/中间产物的脚本，请确保其输出命名落在 `_*`、`*-导出.*` 等已忽略模式内，或补充到 `.gitignore`。

## 远端

`origin` = https://github.com/zengzifeng/kongming.git
