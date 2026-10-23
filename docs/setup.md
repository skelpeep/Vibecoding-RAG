# 安装与启动

此文适用于新克隆的仓库。开发机已有的地址、账号、数据库内容与演示会话不会随 GitHub 仓库分发。

## 环境要求

- Python 3.12 或 3.13、uv；基础安装不需要 GPU、PyTorch 或本地模型权重。
- Node.js 22.12+、npm，用于构建 Vue 前端。
- 可访问的 MySQL、MongoDB、Redis、MinIO 与 Milvus；Milvus 还依赖 etcd 和对象存储。
- 有效的聊天、Embedding、Rerank 远程模型接口及对应凭据。

可以在 Windows 运行应用，将存储放在 Linux 主机或虚拟机；也可以按环境自行部署。`deploy/vm/compose.yaml` 只补充 MongoDB、Redis，依赖已有的其他服务。根目录 `compose.yaml` 是另一套独立依赖模板，端口与版本不同，不能在已有环境中直接叠加运行。配置后在独立环境验证，不能把本机部署记录当作新环境已就绪。

## 首次安装

以下命令在仓库根目录的 PowerShell 中执行：

```powershell
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item .env.example .env }
```

编辑 `.env`，至少配置：

| 配置 | 用途 |
| --- | --- |
| `MYSQL_URL` | 已创建的 MySQL 数据库、应用用户与密码；用户需有迁移建表权限 |
| `MONGO_URL`、`MONGO_DB_NAME` | 对话历史数据库 |
| `REDIS_URL` | FAQ 缓存 |
| `MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`MINIO_BUCKET_NAME` | 可访问的私有桶和有权限的应用用户 |
| `MILVUS_URL`、`MILVUS_TOKEN` | 向量库地址与认证配置 |
| `OPENAI_API_BASE`、`OPENAI_API_KEY`、`LLM_DEFAULT_MODEL` | 聊天模型，OpenAI 兼容 API |
| `EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY`、`EMBEDDING_MODEL`、`EMBEDDING_DIMENSIONS` | 向量模型；模型或维度变化需使用新集合重新导入 |
| `RERANK_BASE_URL`、`RERANK_API_KEY`、`RERANK_MODEL` | 重排模型 |

连接字符串里的密码含特殊字符时需要 URL 编码。Embedding 地址和密钥留空时沿用 Rerank 配置。`JWT_SECRET` 可以留空，由初始化脚本生成并写入本机 `.env`。

存储就绪后执行：

```powershell
uv sync --locked
uv run python scripts/init_stage2.py
.\scripts\start-project.ps1
```

初始化脚本执行数据库迁移，并创建随机密码的示例身份；重复运行不重置已有用户或权限。启动脚本安装前端依赖并构建，随后在后台启动 API、导入 worker、知识沉淀 worker。

- 页面：http://127.0.0.1:8105
- API 文档：http://127.0.0.1:8105/docs
- 就绪检查：http://127.0.0.1:8105/ready；数据库应为 `0005`。

`/ready` 检查数据库迁移与认证配置，不代表所有外部模型/存储都通过。可运行 `uv run python scripts/doctor.py` 进行只读环境探测。

## 登录与第一篇知识

本机随机密码保存在 `var/setup/stage2-accounts.json`，此目录不进入 Git。

| 账号 | 用途 |
| --- | --- |
| `admin` | 用户、角色、部门、操作权限及数据看板 |
| `kb_admin` | 知识维护、导入、授权、FAQ 与缺口 |
| `alice`、`bob` | 普通阅读与问答，按知识授权生效 |

首次克隆没有开发机上的青梧/银桦等演示知识与历史记录。用 `kb_admin` 导入 `examples/stage4/` 的样例，等待构建完成，激活版本、设置阅读范围并发布，再用读者账号提问。操作权限与正文权限独立，管理员不自动得到所有正文访问权。

## 日常启动、停止与开发

已有依赖与前端构建时：

```powershell
.\scripts\start-project.ps1 -SkipBuild
.\scripts\stop-project.ps1
```

先启动存储主机/虚拟机，再启动本机应用。启动脚本只登记自身启动的三个进程；停止脚本核对路径、PID 与启动时间。日志和登记文件在 `var/logs/`。当前不是系统开机服务。

Windows PowerShell 5.1 与 PowerShell 7 均可使用。含中文的 `.ps1` 文件必须保存为 **UTF-8 with BOM**；项目 `.editorconfig` 已设置。仅执行 `chcp 65001` 不能修复脚本文件的读取编码。遇到乱码与 `UnexpectedToken` 时先核对文件编码，可运行 `powershell.exe -NoProfile -File .\scripts\check-powershell.ps1` 检查。

前端开发在另一终端执行：

```powershell
npm --prefix frontend ci
npm --prefix frontend run dev
```

开发页默认 `http://127.0.0.1:5186`，代理到 API `8105`；可通过 `KB_API_TARGET` 覆盖。Windows 运行 `npm ci` 前停止本项目旧 Vite/preview，避免 esbuild 文件占用。前端源码变更后重新 `npm --prefix frontend run build`，正式入口才能加载最新页面。

Linux/macOS 可手动分别运行三个进程；首次配置/初始化与前端构建步骤相同：

```bash
uv run python -m atguigu.cli platform --port 8105
uv run python -m atguigu.cli worker
uv run python -m atguigu.cli settlement-worker
```

## 检查

```powershell
uv run pytest -q
npm --prefix frontend run build
uv run python scripts/check_repository.py --history
```

默认 pytest 使用隔离数据库与替身外部依赖。真实集成脚本需另行配置服务，部分会创建、修改演示数据，执行前阅读对应阶段运行说明；GitHub CI 不使用开发机凭据或连接开发机存储。

支持 Markdown、TXT、DOCX、文字 PDF。扫描 PDF OCR、图片视觉摘要、外部搜索默认关闭，开启需单独配置。其他边界见 [最终交付说明](final-delivery.md)。
