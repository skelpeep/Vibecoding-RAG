# 知识库管理平台交付说明

2026-10-22，本地交付版本。当前统一入口为 http://127.0.0.1:8105，接口文档为 http://127.0.0.1:8105/docs。Vue 开发模式可用 5186 并代理同一 API；日常演示使用统一入口。

此文记录原开发机交付。新克隆仓库按 [安装与启动](setup.md) 配置；下方现有账号、具体演示问题和原始证据只在原开发环境保留，不随 Git 分发。

## 启动与登录

已有环境先启动保存数据的 VMware 虚拟机，确认 MySQL、MinIO、Milvus、MongoDB、Redis 可达。项目根目录运行：

```powershell
.\scripts\start-project.ps1 -SkipBuild
```

该命令校验 Python 依赖、执行 Alembic 升级，并隐藏启动统一 API、导入 worker、沉淀 worker。前端 `frontend/dist` 由 API 同址托管，深层路由可直接刷新；`/api` 不会回退成 HTML。进程信息和日志写在忽略的 `var/logs` 中。已在本机实测启动、停止、再次启动。端口占用时脚本明确退出，不结束其他项目进程。

```powershell
.\scripts\stop-project.ps1
```

停止脚本核对登记 PID、Python 绝对路径与进程启动时间，仅停止本脚本启动的进程。当前方式是本地后台运行，并非系统开机服务。

示例密码保存在本机 `var/setup/stage2-accounts.json`，不写在源码和文档里。`admin` 负责组织与数据看板；`kb_admin` 负责知识、导入、授权、FAQ 和缺口；`alice`/`bob` 演示不同正文权限。登录按钮和菜单取当前服务端授权。已有账号无需重新初始化，不重置用户密码。用户之前创建的 `abc123` 保留。

新机器需要 Python 3.12/3.13、uv、Node.js 22.12+、上述五种存储和有效远程模型配置：

```powershell
# 仅在 .env 不存在时复制，并填写真实连接配置
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item .env.example .env }
uv sync --locked
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe scripts/init_stage2.py
npm --prefix frontend ci
npm --prefix frontend run build
.\scripts\start-project.ps1 -SkipBuild
```

数据库为 20 张业务表，迁移 head 为 0005。全新建库及已有迁移的真实 MySQL 隔离验证见 `docs/evidence/stage6/migrations.json`。存储虚拟机部署步骤见 `vm-deployment.md`，各配置含义见 `env-guide.md` 与 `.env.example`。扫描 PDF OCR、视觉摘要为可选增强；默认使用文字 PDF、DOCX、Markdown、TXT。旧 DOC 请先转换。

开发前端时，在另一个终端执行：

```powershell
$env:KB_API_TARGET='http://127.0.0.1:8105'
npm --prefix frontend run dev -- --port 5186
```

在 Windows 上运行 `npm ci` 前，应停止本项目 Vite/preview 开发进程，以免它锁住 esbuild.exe。脚本已加入这一检查。日常使用已构建文件时无需 npm ci。源码分发包包含前端源码/锁文件、迁移、初始化与启动脚本，不包含本机 .env、账号密码或 node_modules；单独 wheel 仅是 Python 包，完整部署使用源码工程。

## 可复现演示

1. 用 admin 登录，打开用户、角色、部门页，维护组织并分配菜单/操作权限；这些权限不自动授予知识正文访问权。
2. 用 kb_admin 登录导入中心，上传 `examples/stage4` 的文档。观察逐文件进度、失败说明与可重试状态。知识默认关闭阅读，完成索引后在版本历史激活，配置全局/部门/角色/个人任一匹配的范围，再发布。
3. 分别用 alice、bob 提问。当前交付演示问题是“青梧0793158a交接需要提前几天申请、由谁复核，专用确认码是什么？”。alice 拥有申请流程和确认规范，首轮命中已审核 FAQ；bob 只有申请流程，不能取得另一份确认规范的缓存答案。可核对来源后撤权，再重问并打开旧历史。
4. admin 打开数据看板，检查日期、日/周访问、Token、耗时趋势与分布。指标来自当前真实日志，包括本机明确标注的开发验收请求；不是虚构运营量。问题和知识标题仍按当前来源权限过滤。
5. kb_admin 打开知识沉淀，查看已发布 FAQ；编辑会回到待审核，审核通过后可命中 Redis。可撤回，再观察问答安全返回普通 RAG。旧版本来源变化的 FAQ 会脱敏且不返回缓存。
6. 在缺口列表查看已解决的“银桦0793158a月面标本…”及“苍鹭…轨道微藻…”演示项。可以重新打开，点击验证原问题，在成功回答后点击“用此回答确认补全”。新缺口可创建关联草稿，完成构建、激活发布后验证。演示资料均明确为虚构业务规范，不应作为实际制度使用。

所有演示 ID、问题和实际请求见 `docs/evidence/stage6/http.json` 与 `ui/gap-draft.json`。首轮批量脚本错误授予的测试资料已按精确 UUID 软删除，失败证据保留；没有清空正式表、桶或向量集合。

## 验收与边界

必要功能和核心权限闭环已交付，验收映射见 `final-validation.md`。真实模型/存储与替身测试分别记录。前端三宽度为桌面 Chrome 的 1440、768、390 模拟；未宣称实体手机或 Safari 验收。

外部搜索、扫描 PDF OCR、图片视觉摘要默认关闭，其外部服务不在此次最终实测范围。未进行公网/TLS 发布、整机灾难恢复、长期压测或大规模语料性能验收。当前检索有配置上限；看板按选中窗口读取日志，语义挖掘按最近 5000 条窗口工作，适合当前规模，超大规模应改用数据库预聚合与向量聚类。FAQ 精确缓存只用于无历史首轮，语义聚类只推荐、不会自动发布。

软删除保留审计、旧对象及向量，尚未提供自动物理垃圾回收。Redis 中失效内容即便尚未由 Outbox 删除，也必须通过当前 MySQL 授权和签名才能返回；Redis 故障回退 RAG。当前需持续运行两个 worker 才能自动处理导入和知识沉淀。
