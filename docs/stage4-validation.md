# 阶段四验收记录

日期：2026-10-22。范围为知识维护、不可变版本、附件、四维授权、持久化批量导入、worker 与 Vue 知识工作区。统一 API 使用 8103，Vue 使用 5184，真实存储沿用已有虚拟机。MySQL 保持 20 张业务表，0003 只新增版本 `metadata_json` 快照；旧 MinIO 数据与阶段一 Milvus 集合不迁移或清空。

## 后端与真实服务结果

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 全量回归 | 102 passed / 4 skipped / 1 个现有 StarletteDeprecationWarning，22.85 秒 | `evidence/stage4/tests.txt` |
| 阶段二 + 阶段四 API 真实 MySQL | 44 passed，16.67 秒；使用事务隔离临时数据，API 外部对象/入队使用明确替身 | `evidence/stage4/api-mysql.txt` |
| 独立进程 MySQL worker | 3 passed，27.90 秒，真实锁、连接、租约与令牌检查 | `evidence/stage4/import-mysql.txt` |
| 真实 MySQL 迁移 | 隔离 20 表全新升级到 0003、已有版本 backfill、0003 降级/再升级保正文，临时表剩余 0，正式库仍 0003 | `evidence/stage4/migrations.json` |
| HTTP + MySQL + MinIO + Milvus + Qwen3 embedding | 13 组全部通过，六文件混合批次为 5 completed / 1 failed，cleanup=true | `evidence/stage4/http.json`、`http-worker.log` |
| 内嵌图片真实存储与鉴权 | 4 组全部通过，passed=true，cleanup=true | `evidence/stage4/images.json`、`image-worker.log` |
| 清理后重启 API 复核 | 3 组通过：临时知识软删除不可读、最终维护/任务/图片契约可用、仅保留默认拒绝读者的图片草稿 | `evidence/stage4/final-smoke.json` |

本轮 `alembic check` 通过 `No new upgrade operations detected.`，`uv sync --locked` 成功（170 resolved / 106 checked），未使用阶段二/三的历史检查替代当前结果。

全套的 4 个 skip 为 SQLite 下 MySQL 时区检查 1 个及需要显式开启的独立 MySQL worker 3 个；对应真实数据库检查已单独通过。警告来自 FastAPI/Starlette TestClient 与上游 httpx 兼容提示，未计为应用错误。

`test_stage4_api.py` 对象存储和入队服务使用内存替身；`test_stage4_import.py` 使用 SQLite、内存对象/索引和固定向量验证状态转换、重试幂等、令牌隔离与权限取消。MinerU 适配器测试使用受控归档/URL 输入，不代表真实外部 OCR 成功。这些针对性回归不用于证明真实模型或存储联调。

独立 MySQL worker 三项分别验证：

1. 一个连接持有最早任务的 FOR UPDATE，另一 OS 进程通过真实 SKIP LOCKED 领取第二任务；释放锁后再领取第一任务。
2. 两个 OS 进程并发领取不同任务，各任务 persisted attempts 为 1。子进程有限轮询处理瞬时无候选情况，符合 supervisor 行为。
3. 领取进程退出后，控制租约过期，由新进程使用新令牌回收同一任务、attempts=2；旧令牌 heartbeat/complete 均被 LeaseLost 拒绝，新令牌续租成功。

测试使用随机 owner 和精确临时记录，前移测试子进程时钟且只允许其领取该 owner 的任务，避免影响同时进行的 HTTP/UI 导入；完成后夹具定点清理。没有调用模型、MinIO、Milvus，没有模拟整机断电或真实网络分区，不将控制时钟等同于完整容灾验收。

## 13 组真实 HTTP 覆盖

1. `/ready` revision=0003、匿名知识访问被拒绝。
2. 浏览器目录元数据、同名文档 UUID 隔离、混合文件提交和幂等重放，六个文件不互相覆盖。
3. 跨用户批次拒绝；任务代查管理员仅见状态，不见文件/单元详情。
4. MD、TXT、DOCX、文字 PDF 使用真实解析、Qwen3 embedding、MinIO、Milvus 完成；旧 DOC 持久化明确失败，批次 partial_failed。
5. 激活与发布后，空 grants 仍默认拒绝。
6. 部门 OR 个人授权、部门无下级继承、私有附件访问。
7. MinIO 匿名请求 403；真实语义向量检索命中正确 unit/version/chunk 来源。
8. 仅损坏本轮替换版本源文件的故障注入：构建失败，旧已发布标题/正文/active 版本保持。
9. 真实重建、显式激活、继承附件；普通读者不能下载旧版本文件。
10. 撤权后正文和原有附件 ID 立即拒绝。
11. 角色与全局授权分别开放对应读者。
12. 撤销发布和停用立即从检索授权中排除，文件访问拒绝。
13. 文档、版本、权限等变化持久化 OutboxEvent；本阶段不宣称 FAQ 消费或缓存命中。

以上真实向量来自 Qwen/Qwen3-Embedding-8B（4096 维），写入独立 `kb_platform_chunks_v1` 的 version/chunk/attempt schema；没有以固定向量冒充真实 embedding。语义检索验证只证明导入后向量与来源可用，通用问答、重排序前鉴权和流式会话仍留阶段五。

首次 `http-initial-proxy-timeout.json` 记录客户端代理超时，保留为排查历史；最终 `http.json` 是关闭环境代理影响后的完整成功结果。它不属于额外通过用例。

## 4 组真实图片覆盖

内嵌 PNG 被解析后存入私有 MinIO，正文替换为鉴权图片 ID；发布后授权账号取回与原 PNG 相同的字节；编辑后新版本拥有独立图片文件 ID/对象，普通读者被拒绝访问上一版本图片；撤权后当前图片也立即 404。图片测试知识已软删除，证据为 `images.json`。

本阶段真实验证了存储与预览，未调用外部视觉模型生成摘要。扫描 PDF 默认 `PDF_OCR_REQUIRED`，可选 `IMPORT_PDF_OCR=true` 的 MinerU 适配器已实现但真实 OCR 未验收；`IMPORT_IMAGE_SUMMARIES=false` 为默认，视觉调用也未验收。旧 DOC 明确要求转换成 DOCX；Markdown 外链和相对图片不抓取，data URI/文档内嵌图片可保存。

## Vue 交互与视觉证据

沿用 `design-taste-frontend` 的 framed-sheet / seed 993422931、IBM Plex Sans + Noto Sans SC 和既有 token，无重新抽取。知识页数据、总数、权限、版本及任务进度来自真实 API，无硬编码业务样例。方向和问题清单见 `.taste-skill/stage4-decisions.md`。

| 检查 | 实际结果 | 证据 |
| --- | --- | --- |
| 初轮真实浏览器交互 | 8 组通过，0 页面错误 | `evidence/stage4/ui/report.json` |
| 补充真实交互 | 8 组通过，0 页面错误 | `evidence/stage4/ui/states.json` |
| 注入状态检查 | 404 权限响应后清除旧正文/版本，通过；恢复后使用真实 API | `evidence/stage4/ui/states.json` 的 injected_state_checks |
| 批量删除 | 1 组真实 API 删除精确临时知识，删除后搜索为空 | `evidence/stage4/ui/bulk-delete.json` |
| 手机与网络状态补验 | 2 组真实手机交互 + 2 组注入延迟/503 状态，通过 | `evidence/stage4/ui/loading-error.json` |
| 图片与重试补验 | 3 组通过：Bearer 图片、blob URL 回收、原任务重试按钮；超时起因明确为注入 | `evidence/stage4/ui/media-retry.json` |
| 正文内嵌图片 | 1 组真实白名单图片渲染，保留 alt 图注且无原始文件地址 | `evidence/stage4/ui/inline-image.json` |
| Vue/TypeScript/Vite 最终构建 | vue-tsc + Vite build 成功，10.48 秒 | `evidence/stage4/ui/build.txt` |
| 生产构建预览 | 4174→8103，受保护深层路由/真实登录/详情图片/列表读取通过，0 页面错误、无整页横溢 | `evidence/stage4/production-smoke.json`、`production-desktop.png` |
| 技能源码 lint | 0 FAIL / 5 WARN，理由见下 | `evidence/stage4/ui/lint.txt` |
| 技能 inspect | 8 个页面/状态 × 1440/768/390，全部 0 FAIL、无整页横向溢出；6 组 0 WARN，detail 1 WARN，versions 2 WARN | `evidence/stage4/ui/inspect-summary.json`、`.taste-skill/stage4-*/report.json` |
| 初轮三宽度截图 | 8 个页面/状态 × 3 宽度 = 24 张；首轮 list/import 图为迭代前记录 | `evidence/stage4/ui/report.json` 与同目录 PNG |

UI 合计 26 组：23 组真实 API/UI 交互及 3 组注入状态。media-retry 的重试请求使用真实持久化任务，超时通过真实 worker 的失败转换注入；后来常驻 worker 完成 attempt 2，未把注入起因当作供应商真实超时。各组与后端 HTTP/worker/图片验收分别计数。

初轮覆盖列表读取、新建草稿/默认拒绝、四维授权和未发布预览、版本正文溯源、真实附件 FormData 上传/Bearer blob 下载、未保存离开提示/编辑提交、搜索与三宽度列表、混合批次和目录入口。

补充覆盖 ready 激活/发布、四维混合保存和发布后预览、撤销发布/停用/恢复草稿、真实重建保持旧 active、请求恢复、目录递归/拖拽/移除文件、手机任务优先展示、搜索空结果。注入 404 只验证浏览器接收到权限失败后的旧内容清理，不能称为真实服务故障；撤权和文件拒绝另有真实 HTTP 用例。

最终视觉以 `.taste-skill/stage4-list`、`stage4-editor`、`stage4-detail`、`stage4-permissions`、`stage4-versions`、`stage4-import`、`stage4-image`、`stage4-attachments` 的 inspector 图，以及 `ui/image-*.png` 和补验状态图为准。八组的折页/全页图与首轮 PNG 均由 UI 执行代理打开或通过带文件名联系表复核，联系表在 `.taste-skill/stage4-review/`；完整评审见 `.taste-skill/stage4-review.md`。

## 三轮内设计修正与七项评审

手机导入中心将批次历史改为原生选择框，把逐文件任务提前；任务/总量字号提高到 13px。列表补齐稳定编号、格式和四维范围摘要，手机保留全部业务字段。修正保存成功后被未保存守卫挡住、FormData content-type、blob 下载、失权/迟到响应回填和标签长度校验。最终 list/import 均无 WARN。

| 评审项 | 最终结论 |
| --- | --- |
| 主问题与阅读顺序 | 知识身份与状态为列表主内容，编辑正文最大；详情先显示当前/最新版本关系，导入先呈现结果和下一动作 |
| 网格、边缘与留白 | 同一桌面 24px/手机 16px 边界，正文与 280px 资料栏对齐，短侧栏按内容收缩 |
| 色彩与辨识 | 蓝灰纸夹、书页品牌、近黑主动作、青色真实状态/进度；没有装饰性指标 |
| 数字与对齐 | API 返回筛选总数、批次 counts、percent、版本号和切片数；日期右对齐，数字等宽 |
| 零与缺失 | 0 篇、0%、0 失败显示真实值；未分类与未开放阅读明确，缺失元数据用短横占位 |
| 状态与标记 | 版本/任务状态有文字，当前版本独立标记；进度条与百分比一致，不依赖图例猜测 |
| 手机 | 导航折叠、权限组折叠、单栏编辑/资料、完整知识字段，批次选择后优先文件任务；390px 无整页横溢 |

保留 WARN 未用 allow 绕过：lint 的 1 个阴影用于真实下拉浮层、3 个 section-label 命中属于既有组织页语义分组、1 个 em-dash 规则命中是多个字段缺失占位，共 5 WARN。inspect 的短正文 detail 在 1440 有 1 个 hero-void；三条记录的 versions 在 1440 有 hero-void/panel-void 共 2 个。它们测量的是全产品稳定白色工作页的最小窗口高度和自然收缩内容后的留白，保留真实数据，未填造正文或记录；其他六组均 0 WARN。

## 权限、一致性与清理边界

读者仅能访问 published + 当前 ready 版本 + 四维 OR 授权，列表计数、标题搜索、分类、正文与附件同时过滤。创建者持对应操作权限时可维护自己的草稿/旧版本，此例外不进入自查或检索授权。系统管理员和任务状态代查均无隐式正文绕过。

未发布编辑的标题/摘要/分类/标签与原文件元数据保存在版本快照，激活后再复制到当前发布视图。worker 成功只 ready，用户激活、初次发布均显式执行。失败保旧；租约令牌隔离 MySQL、外部图片及向量写入，阶段五检索还须以当前 MySQL version/chunk/vector_id 为准。

HTTP/图片及其余 QA 知识按本轮 UUID 软删除，不清空正式表、桶或旧集合。最终仅保留一篇明确“阶段四示例”的图片草稿，默认拒绝读者；任务/单元 ID 见 `evidence/stage4/demo.json`。timeout 重试起因是故障注入，随后常驻 worker 使用真实源文件、embedding 和存储完成同一任务，completed、attempts=2；重试知识也已软删除。

清理后重启 API 的 `final-smoke.json` 通过。组织当前为 8 用户/5 角色/4 部门；新增 `abc123` 创建时间早于本轮工具执行，属于用户先前操作，已保留，没有把组织“恢复为 7 用户”。数据库仍为 20 张业务表、0003。失败尝试遗留对象/向量和软删除知识的物理数据没有自动 GC，FAQ outbox 消费者没有实现。

本阶段止于知识维护与导入。通用 RAG、SSE、多轮鉴权会话与回答引用为阶段五；FAQ 缓存和日志统计为阶段六。本轮未做实体手机/Safari、大规模负载、整机故障恢复、生产 TLS 或公网部署，不扩大验收范围。
