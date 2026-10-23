# 各阶段历史入口

以下为开发阶段的原运行记录，旧端口与未完成项只反映当时状态。当前启动方式见仓库根 README.md 和 docs/setup.md。文中 docs/ 路径以仓库根目录为基准。

## 阶段五历史记录

```powershell
uv sync --locked
.venv\Scripts\python.exe -m alembic upgrade head
npm --prefix frontend ci
```

三个终端分别启动：

```powershell
.venv\Scripts\python.exe -m atguigu.cli platform --port 8104
```

```powershell
.venv\Scripts\python.exe -m atguigu.cli worker
```

```powershell
Set-Location -LiteralPath 'frontend'
$env:KB_API_TARGET='http://127.0.0.1:8104'
npm run dev -- --port 5185
```

使用现有账号登录，密码在被忽略的 `var/setup/stage2-accounts.json`。`kb_admin` 已有“资料归档问答（示例）”会话，可核对真实生成与来源。发布的“项目资料归档流程（示例）”向 kb_admin、alice、bob 开放；carol/admin 不自动得到正文权。原阶段四图片草稿保留，验收会话和内部校验测试资料已精确清理，用户账号未重置。

最终 159 项回归通过、4 项跳过；真实 HTTP 11 组、流式控制 3 组、HyDE 与语义受限探测、独立租约和迁移验证通过。前端真实交互12组、撤权3组、注入状态14组通过；构建和四组三宽度技能检查无 FAIL。详见 [运行手册](../../docs/stage5-runbook.md)、[接口与 SSE 契约](../../docs/stage5-api-contract.md) 和 [验收记录](../../docs/stage5-validation.md)。

未有当前授权的正文不会进入重排与生成；撤权后整轮历史脱敏，包含所有参与生成的资料依赖。默认关闭 HyDE 与网页搜索：HyDE 已真实验证，网页补充的实际服务尚未验收。召回每侧有2000候选切片上限，FAQ 缓存明确 `not_implemented`。旧 8102/8103 API 进程的历史迁移探针可能在升级后返回不匹配，使用当前 8104/5185。

## 阶段四历史记录

先保证既有虚拟机的 MySQL、MinIO、Milvus 可连接；真实 embedding 配置沿用已忽略的 `.env`。首次安装或升级在项目根执行：

```powershell
uv sync --locked
.venv\Scripts\python.exe -m alembic upgrade head
npm --prefix frontend ci
```

在三个 PowerShell 终端分别启动统一 API、独立 worker 和前端：

```powershell
.venv\Scripts\python.exe -m atguigu.cli platform --port 8103
```

```powershell
.venv\Scripts\python.exe -m atguigu.cli worker
```

```powershell
Set-Location -LiteralPath 'frontend'
$env:KB_API_TARGET = 'http://127.0.0.1:8103'
npm run dev -- --port 5184
```

知识维护请使用 `kb_admin`；随机密码在本机 `var/setup/stage2-accounts.json`。`admin` 用于组织管理，不自动获得全部知识正文。导入或编辑先生成待构建版本，worker 成功后只标记“已就绪”；用户还需显式激活并发布，空访问范围默认拒绝读者。

详见 [运行与演示说明](../../docs/stage4-runbook.md)、[接口契约](../../docs/stage4-api-contract.md)、[验收证据](../../docs/stage4-validation.md) 和 [后台任务实现](../../docs/background-jobs.md)。支持 MD、TXT、DOCX、文字 PDF；旧 DOC 需转换为 DOCX。扫描 PDF 的 MinerU OCR、图片视觉摘要默认关闭，外部调用尚未真实验收。FAQ 失效消费者和孤儿对象/向量自动清理尚未实现。

验收：全套 102 项通过，真实 MySQL API 44 项、独立 worker 3 项、HTTP 13 组、图片 4 组通过；Vue 构建成功，8 组页面/状态三宽度技能检查无 FAIL。UI 23 组真实交互与 3 组注入状态分别报告，保留警告和证据见验收文档。

阶段三的 8102/5183 入口保留；本轮使用 8103/5184 验收，避免影响旧入口。现有账号无需重新初始化。

## 阶段三前端历史记录

先确保虚拟机/MySQL 与统一后端运行，再在项目根目录执行：

```powershell
.\scripts\start-frontend.ps1
```

脚本在缺少依赖时执行 npm ci，使用 Node.js 22.12+。构建命令为 `.\scripts\start-frontend.ps1 build`。设计采用 framed-sheet（seed 993422931），中英文字体本地加载，适配 1440/768/390。

详见 [前端运行说明](../../docs/stage3-runbook.md)、[验收与设计评审](../../docs/stage3-validation.md)。真实交互 19 组、补充状态 9 组通过，三宽度无整页横溢，技能检查无 FAIL。

## 阶段二历史记录

```powershell
uv sync --locked
.venv\Scripts\python.exe scripts/init_stage2.py
.\scripts\start.ps1 platform
```

随机账号密码见本机 `var/setup/stage2-accounts.json`，系统管理员账号为 `admin`。初始化重复运行不会重置已有账号或恢复撤销权限。

详见 [运行说明](../../docs/stage2-runbook.md)、[接口与数据约定](../../docs/stage2-api.md)、[验证记录](../../docs/stage2-validation.md)。阶段一原 HTML 保留，旧数据接口已关闭：匿名 401、登录后 410，导入与 RAG 后续接入统一鉴权链路。

## 原基座启动参考（Windows PowerShell）

在项目根目录执行，需要 Python 3.12 和 uv：

```powershell
uv sync --locked
# 仅当 .env 不存在时复制，避免覆盖自己的配置
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

分别打开两个终端执行：

```powershell
.\scripts\start.ps1 import
```

```powershell
.\scripts\start.ps1 query
```

- 原导入页：[http://127.0.0.1:8100/](http://127.0.0.1:8100/)
- 原问答页：[http://127.0.0.1:8101/](http://127.0.0.1:8101/)
- 接口文档：对应端口的 `/docs`；`/health` 只表示 Web 进程可用。
- 可用 `.venv\Scripts\python.exe -m atguigu.cli import` / `query` 直接启动，无需激活虚拟环境。每个服务保持一个进程，按 Ctrl+C 停止。

默认端口避开本机已经占用的 8000。可通过 `.env` 的 `IMPORT_PORT`、`QUERY_PORT` 修改；页面使用同源 API，修改端口不需改 HTML。这两个历史 HTML 入口无需 Node；当前管理前端使用上面的 Vue 构建流程。

## 阶段一历史验证命令

下面的旧上传/问答脚本面向阶段一基线，阶段二关闭旧数据接口后不再作为当前验收命令。当前知识业务验证请使用阶段四运行说明中的命令。

```powershell
$env:PYTHONUTF8 = '1'
.venv\Scripts\python.exe scripts/doctor.py
.venv\Scripts\python.exe -m pytest -q
# 先启动两个服务；下面会上传独立示例、尝试真实导入和问答
.venv\Scripts\python.exe scripts/verify_baseline.py
.venv\Scripts\python.exe scripts/capture_baseline.py
```

`verify_baseline.py` 在完整链路未通过时返回非零退出码，报告中的 `full_chain_verified` 保持 `false`，不会以模拟模型填补缺项。截图脚本针对当前「缺少依赖」基线，需要已安装 Chrome；服务补齐后应按真实成功行为调整验证。

## 虚拟机部署与 .env

见 [填写指南](../../docs/env-guide.md) 和 [虚拟机部署记录](../../docs/vm-deployment.md)。已有 Milvus/MinIO/MySQL 复用，新增 MongoDB 与独立 Redis；本虚拟机使用 deploy/vm 配置，不运行根目录全量 Compose。

## 进一步配置

详见 [阶段一运行说明](../../docs/stage1-runbook.md)、[阶段一验证记录](../../docs/stage1-validation.md)、[后台任务方案](../../docs/background-jobs.md) 和 [来源记录](../../docs/source-baseline.md)。

实际密钥只填入已忽略的 `.env`。全部核心业务已交付，旧 8100/8101 数据接口继续封闭；当前运行方式和验收以本文开头及最终交付文档为准。
