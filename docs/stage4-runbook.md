# 阶段四运行与演示说明

日期：2026-10-22。当前知识管理入口为 Vue `5184`、统一 API `8103`，耗时导入使用独立 Python worker。阶段三的 `5183/8102` 入口保留，本轮新端口承载阶段四验收。完整通用鉴权问答未在本阶段实现。

## 安装与升级

需要 Python 3.12、uv、Node.js 22.12+ 和 npm。当前 Windows 使用 Node 24；MySQL、MinIO、Milvus 位于已有 VMware 虚拟机，先保证虚拟机开机、现有服务可连接。不要运行根目录全量 Compose 替换已有实例；部署记录见 [虚拟机部署](vm-deployment.md)。

在项目根执行：

```powershell
uv sync --locked
.venv\Scripts\python.exe -m alembic upgrade head
npm --prefix frontend ci
```

当前项目库 `kb_platform` 保持 20 张业务表，迁移从 0002 到 0003，仅新增 `knowledge_versions.metadata_json` 版本元数据快照。迁移不清空现有知识、账号或组织。已有环境无需再次初始化；新环境若尚无账号可运行 `scripts/init_stage2.py`，它会增量初始化，不重置既有账号密码与授权。

`.env` 保存实际连接和模型凭据，不把它复制进证据。示例账号密码在已忽略的 `var/setup/stage2-accounts.json`。知识创建/编辑/导入使用 `kb_admin`，`admin` 用于组织管理；系统管理员不自动得到全部正文、旧版本或附件读取权。

## 三个终端启动

终端一，在项目根：

```powershell
.venv\Scripts\python.exe -m atguigu.cli platform --port 8103
```

终端二，在项目根：

```powershell
.venv\Scripts\python.exe -m atguigu.cli worker
```

终端三，在项目根进入前端：

```powershell
Set-Location -LiteralPath 'frontend'
$env:KB_API_TARGET = 'http://127.0.0.1:8103'
npm run dev -- --port 5184
```

| 入口 | 用途 |
| --- | --- |
| [http://127.0.0.1:5184](http://127.0.0.1:5184) | 登录与组织管理 |
| [知识维护](http://127.0.0.1:5184/knowledge) | 分页、搜索、分类/状态、批量删除 |
| [导入中心](http://127.0.0.1:5184/knowledge/import) | 文件/目录选择、批次、单文件进度、失败重试 |
| [http://127.0.0.1:8103/docs](http://127.0.0.1:8103/docs) | 真实知识与组织 API |
| [http://127.0.0.1:8103/ready](http://127.0.0.1:8103/ready) | 检查数据库迁移和认证配置，当前 revision 应为 0003 |

`/health` 仅为存活探针。API 可以接收并持久化任务，但必须有 worker 才会解析/索引。单次运行 `python -m atguigu.cli worker --once` 清空当前到期队列后退出，不等待将来的自动重试。常驻模式才会持续处理 `retry_at` 到期任务。

本轮 API、Vue 与 worker 为本地开发进程，未注册开机启动服务。旧 8100/8101 上传、查询、历史和 SSE 数据 API 仍封闭，匿名 401、登录后 410；当前知识流程只使用统一 `/api/knowledge`。

## 真实格式与配置边界

| 输入 | 当前行为 |
| --- | --- |
| `.md` / `.markdown` | 读取正文和 data URI 内嵌图片；外链及本地相对图片不抓取，任务 warnings 提示 |
| `.txt` | UTF-8、带 BOM 的 UTF-16、GB18030 |
| `.docx` | 解析正文、表格与内嵌图片；图片写入受控 MinIO |
| `.doc` | 明确失败 `LEGACY_DOC_UNSUPPORTED`，请先另存为 DOCX，不自动转换 |
| 文字 PDF | 读取可提取文字，内嵌图片保存并替换为受控图片 ID |
| 扫描 PDF | 默认失败 `PDF_OCR_REQUIRED`；可配置 MinerU OCR，但外部 OCR 尚未真实验收 |
| 图片摘要 | 默认保留图片，不调用视觉摘要；开启后需要独立视觉模型配置，真实视觉调用尚未验收 |

查询 `/api/knowledge/import/capabilities` 可取得实际限制和开关。默认最多 100 文件/批、50 MiB/文件、200 MiB/批；解析展开 200 MiB、500 页、100 张图片、200 万字符。超过上传限制返回 413/422；单文件无效格式作为持久化 failed 记录，不让整批成功文件消失。目录上传仅保存浏览器提供的相对路径元数据，worker 不接受客户端指定的本地文件路径。

主要配置均已列在 `.env.example`，修改后重新启动 API 与 worker：

| 配置 | 默认与用途 |
| --- | --- |
| `KNOWLEDGE_BUCKET` | 留空复用已有私有 MinIO 桶，当前 `kb-stage1`；对象按 `units/{UUID}/versions/{UUID}/...` 隔离 |
| `KNOWLEDGE_CHUNKS_COLLECTION` | `kb_platform_chunks_v1`；专用 version/chunk/attempt schema，旧阶段集合不变 |
| `IMPORT_CONCURRENCY` | 1 个子进程槽，可配置 1–8 |
| `IMPORT_LEASE_SECONDS` / `IMPORT_HEARTBEAT_SECONDS` | 90 秒 / 15 秒 |
| `IMPORT_TASK_TIMEOUT_SECONDS` / `IMPORT_MAX_ATTEMPTS` | 900 秒 / 3 次总尝试 |
| `IMPORT_RETRY_BASE_SECONDS` / `IMPORT_POLL_SECONDS` | 指数退避基数 15 秒 / 轮询 2 秒 |
| `IMPORT_PDF_OCR` | `false`；启用时需要现有 MinerU 配置和 `MINERU_TOKEN` |
| `IMPORT_IMAGE_SUMMARIES` | `false`；启用时需要独立 `VL_BASE_URL`、`VL_API_KEY`、`VL_MODEL` |

embedding 沿用已验证的远程 Qwen/Qwen3-Embedding-8B，4096 维；空 `EMBEDDING_BASE_URL/API_KEY` 复用重排站点配置，可单独覆盖。不会加载本地 BGE-M3。数据库结构、对象和向量协议详见 [接口契约](stage4-api-contract.md) 与 [worker 实现](background-jobs.md)。

服务不会将 MinIO 桶改公开。无法读取桶策略的专用账号仍对每个对象执行匿名 GET 探测，匿名可读对象不能进入 ready 版本；浏览器得到的是鉴权 API 文件 ID，没有公开对象地址。改变桶或 embedding 维度前须提供私有桶或新的独立兼容集合，不能复用旧阶段集合。

## 发布与版本演示

1. 用 `kb_admin` 登录，打开知识维护并新建正文，或在导入中心同时上传 `examples/stage4/` 的 MD、TXT、DOCX、文字 PDF 四份明确标注的示例。可用 `scripts/create_stage4_examples.py` 重建这些输入，目录 README 不属于四份业务文档。
2. 查看批次和逐文件阶段。导入完成表示版本索引已就绪，不会自动变成对外发布内容。不同目录的同名文件分别生成稳定 unit_id，重试沿用原 task/version ID。
3. 在详情的访问范围配置 global、department、role、user 任意组合。空 grants 默认拒绝读者；直属部门严格匹配，不继承下级部门。管理预览检查当前真实发布状态，草稿即使已授权仍显示拒绝。
4. 在版本历史显式激活 ready 版本，再发布知识。新建/编辑时的标题、分类、摘要和标签保存在版本快照；只有激活才更新当前发布视图，未激活草稿不会泄露到读者列表与搜索。
5. 以 `alice`、`bob`、`carol` 等账号核对正文和附件。读者需同时满足 published、当前 ready 版本和四维 OR 授权。创建者维护自己的未删除知识需有创建/更新/导入任一操作权限；编辑、版本和附件操作还需更新权限，该例外不进入问答检索授权。
6. 编辑创建新 pending 版本，旧发布版本继续可读。worker 成功后可以手动激活；构建失败时旧 active_version_id 和标题/正文保留。版本重建也生成新版本和任务，不原地改写已发布版本。
7. 下载和图片每次请求重新鉴权。编辑/重建克隆普通附件和图片的独立文件记录/对象并重写正文图片引用；旧版本文件只允许创建者维护访问。撤权、撤销发布、停用或软删除后，读者的既有文件 ID 请求也会被拒绝。

`knowledge:permissions` 是全库授权元数据管理能力，不开放正文；`knowledge:task:read-any` 只允许任务状态代查，不开放文件名、错误详情或文档内容。界面隐藏按钮不替代后端校验。

## 构建与验证命令

在项目根构建：

```powershell
npm --prefix frontend run build
.venv\Scripts\python.exe -m alembic check
```

build 含 vue-tsc 和 Vite，产物在 `frontend/dist/`。本轮生产构建预览使用 4174→8103，已验证受保护深层路由、真实登录、正文图片和列表。可在前端终端执行：

```powershell
$env:KB_API_TARGET = 'http://127.0.0.1:8103'
npm run preview -- --port 4174
```

预览只用于本地检查。生产托管需将 `/api` 转发至统一后端，前端深层路由回退到 `index.html`；本阶段未做公网或 TLS 部署。

以下验收会创建明确标识的临时知识；HTTP/图片脚本通过真实 API 软删除本轮生成的 UUID，物理对象和向量不做全库清理。UI 状态脚本依赖 UI 主脚本生成的 `ui/report.json`，应依次运行。脚本可能调用真实 embedding 服务。

```powershell
$env:PYTHONUTF8 = '1'
.venv\Scripts\python.exe -m pytest -q
$env:KB_TEST_MYSQL = '1'
.venv\Scripts\python.exe -m pytest tests/test_stage2.py tests/test_stage4_api.py -q
Remove-Item Env:KB_TEST_MYSQL
$env:KB_TEST_IMPORT_MYSQL = '1'
.venv\Scripts\python.exe -m pytest tests/test_stage4_import_mysql.py -q
Remove-Item Env:KB_TEST_IMPORT_MYSQL
.venv\Scripts\python.exe scripts/verify_stage4_migrations.py
.venv\Scripts\python.exe scripts/verify_stage4_http.py
.venv\Scripts\python.exe scripts/verify_stage4_images.py
.venv\Scripts\python.exe scripts/verify_stage4_ui.py
.venv\Scripts\python.exe scripts/verify_stage4_ui_states.py
node C:\Users\fi4h\.codex\skills\design-taste-frontend\scripts\lint.mjs --app frontend/src
node scripts/inspect_stage4.mjs http://127.0.0.1:5184/knowledge --out .taste-skill/stage4-list
```

浏览器验收需 Playwright 和本机 Chrome。HTTP/图片默认使用 8103（可设 `STAGE4_API_BASE`）；UI 主脚本可设 `STAGE4_API_ORIGIN` / `STAGE4_WEB_ORIGIN`。inspect 包装脚本通过真实登录取得短期 token，沿用原技能 inspector，无产品免鉴权入口；可设置 `STAGE4_QA_USER`、`STAGE4_QA_TAB` 和 `TASTE_SKILL_PATH`。

验收结果、替身测试范围及视觉证据见 [阶段四验收](stage4-validation.md)。文档/授权/版本/状态/附件变化已写 OutboxEvent，FAQ 消费者和孤儿文件/向量自动清理留后续；下一阶段只接入通用 RAG 与鉴权问答。
