# 阶段五验收记录

日期：2026-10-22。范围为权限感知的通用 RAG、所属多轮会话、SSE、来源、日志与 Vue 问答工作台。统一 API 8104，前端 5185，生产构建预览 4175。所有实现子代理使用用户指定的 gpt-6.1-sol。

## 实际结果

| 验证 | 结果 | 证据 |
| --- | --- | --- |
| 全套回归 | 159 passed / 4 skipped / 1 现有上游兼容 warning，44.95 秒 | `evidence/stage5/tests.txt` |
| 真实 MySQL 组织/知识 API 回归 | 44 passed，18.03 秒，随机事务夹具回滚；模型/对象存储使用明确替身 | `evidence/stage5/api-mysql.txt` |
| 真实独立 MySQL 导入 worker 回归 | 3 passed，26.79 秒，真实锁/租约/进程；不代表整机故障 | `evidence/stage5/import-mysql.txt` |
| 真实 HTTP 问答 | 11 组全部通过，实际 MySQL/Mongo/Milvus/embedding/rerank/chat，无模拟回答 | `evidence/stage5/http.json` |
| 真实 SSE 控制 | 3 组通过：同会话 409、显式取消、首个真实模型 delta 后撤权；授权精确恢复 | `evidence/stage5/stream-controls.json` |
| 可选真实 HyDE | 4 组通过，真实假设模型、两次 embedding、重排和生成；只引用当前 MySQL 切片 | `evidence/stage5/hyde.json` |
| 语义受限探测 | 无词法交集的问题仍检出受限向量；无重排/生成，无正文或标题输出 | `evidence/stage5/semantic-denied.json` |
| 独立进程会话租约 | 4 组通过，两进程竞争、精确过期回收、旧完成令牌隔离、终态释放；随机所属会话清理 | `evidence/stage5/leases.json` |
| 真实 MySQL 迁移 | 新库 0001→0004、降级/再升级保留问答、有效租约拒绝降级，临时表剩余 0，正式库 0004 | `evidence/stage5/migrations.json` |
| 真实 UI | 12 组、21 张截图、0 页面错误；3 组真实撤权交互，原授权恢复 | `evidence/stage5/ui/interactions.json`、`ui/visual-fixtures.json` |
| 注入 UI 状态 | 14 组、18 张三宽度截图，另有390×700输入可见检查；0 页面错误 | `evidence/stage5/ui/states.json` |
| Vue 类型检查与构建 | 最终 build 包含 vue-tsc，通过 | `evidence/stage5/ui/build.txt` |
| 技能 lint / inspector | lint 0 FAIL / 5 继承 WARN；history/empty/answer/citation 四组各 0 FAIL / 1 WARN | `evidence/stage5/ui/lint.txt`、`.taste-skill/stage5-*/report.json` |
| 时间显示 | 数据库无后缀 UTC 与 ISO Z 都显示上海14:59，实际浏览器检查通过 | `evidence/stage5/ui/timezone.json` |
| 生产预览 | 未登录深链跳登录、真实登录与所属历史、确无命中 no_match、最终示例引用；4 组通过 | `evidence/stage5/production-smoke.json` |

`alembic check` 为 No new upgrade operations detected，`uv sync --locked` 成功，git diff --check 无空白错误。4 个 skip 是 SQLite 不适用的 MySQL UTC 检查和未默认启用的3个独立 MySQL worker 检查；其对应真实检查已经单独执行通过。warning 为现有 FastAPI/Starlette TestClient 的上游 httpx 兼容提示。

阶段五新增回归分为 48 个 RAG/模型传输场景和 9 个会话场景，使用随机隔离 SQLite、明确内存历史/模型及受控 HTTP Transport 验证权限、伪造向量、取消、partial EOF、usage 与跨存储失败，不冒充真实模型。真实调用另列 HTTP、HyDE、语义探测。

## 权限和依据

两份 UUID 隔离的验收资料索引使用真实 MinIO、MySQL、Milvus 和 Qwen3 4096 维向量。同一个复合问题分别由 alice 全部有权、bob 仅有公开流程、carol 和 admin 全部无权；后端使用当前四维 OR 授权，创建者维护和系统管理员例外不进入检索正文授权。

最终 HTTP 记录 alice completed、bob completed 且仅一份来源、carol/admin restricted。受限校验编号、受限单元 ID 和敏感标题不出现在 bob 的 SSE。全有权真实 dense_recalled_count=2、invalid_vector_count=0；关键词与向量确实共同参与，来源使用稳定 unit/version/chunk ID，引用切片与当前 MySQL 内容一致。

不相关问题在有权用户下实际为 low_confidence，无事实答案、无来源；单独真实 carol 同题没有任一相关召回，返回 no_match 且无权限提示。两种安全拒答按实际状态记录，不将 low_confidence 宣称为 no_match。语义探测问题“材料应在完工之前多早递交？”没有词法候选，但检出受限当前向量，仍未调用重排和生成。

多轮验证对当前所属会话改写指代；伪造 user_id、跨用户历史/请求/取消/删除/引用都被拒绝。撤权后旧引用 404，整轮问题、答案和来源脱敏，下一轮不带入校验编号。所有生成上下文和安全历史依赖单独保存，实际引用子集不替代完整授权依赖。

真实 SSE 控制在收到第一个模型 delta 后撤权，后续为 permission clear_answer 和 end restricted，清理事件后无后续 delta，历史问题和答案均空，actual cited=[]。主动取消和客户端断开均有持久化 cancelled 终态。取消过程服务商未报告 usage 时 unknown，模型可能已处理部分请求，不能把未报告当作零账单。

## 修复及历史证据

初轮真实浏览器断开后请求仍 processing，定位为 AnyIO 取消作用域打断终态存储；已采用 shielded cleanup 修复，最终 HTTP 和真实控制通过。`http-initial-disconnect-failure.json` 保留历史失败，不算通过。

真实 pymilvus 返回顶层 `vector_id`，初版仅接受 `id` 导致合法向量被拒、关键词召回兜底。已兼容具名主键并仍逐项校验实体身份、正文、当前版本和赢得租约的 vector_id；最终 HTTP 和 HyDE 明确检查真实向量贡献。`http-before-dense-fix.json` 和 `hyde-initial-lexical-fallback.json` 为修复前记录，不用作最终混合检索证明。HyDE 中短答案可能只产生一个真实 delta，不把 delta 数量当作服务端模拟流的依据；传输检查验证实时模型流，最终 concat 与完整答案一致。

可选 MCP 网页搜索默认关闭。已实现原问题调用、链接白名单、独立外部来源事件/历史，以及不可用降级；不发送企业正文、改写后的私有历史或 HyDE 假设给网页搜索，不把外部摘要作为内部制度生成依据。仅受控模型/协议与 UI 注入验证，未宣称真实 MCP 搜索服务成功。

## 视觉与交互

沿用 design-taste-frontend framed-sheet / seed 993422931，IBM Plex Sans + Noto Sans SC，不重抽。技能 inspector 的每组1个 no-data-hue WARN 将品牌/导航 SVG 误判成图表；工作台没有运营图表，不增加虚构数据消除警告。5个 lint WARN 为继承的浮层、组织分组标签和缺失值短横，chat 无新增 warning。

真实 UI 包含新建、IME/Shift Enter、无商品名称提问、无知识菜单的普通读者查看来源、刷新历史、多轮、低置信度、手机返回、停止、部分/全部无权和删除。单独注入验证逐字节 UTF8/CRLF、缺少 end、恶意 Markdown、外部链接、失败、授权改变、加载/重试、迟到 meta/delta/end、会话切换、卸载、草稿守卫和短手机视口。

全部三宽度全页/折页及联系表已打开复核；修正了停止重复提示、未发送草稿丢失、截图加载/动画时机、Markdown 多个h1、Element Plus 过重阴影和部分授权提示刷新丢失。最终截图没有整页横溢，手机输入/发送可见。UTC 显示最后修复在实际浏览器验证，已有部分历史截图保留修复前时间，不混淆为后台时间记录错误。详见 `.taste-skill/stage5-review.md`。

## 当前边界

召回有配置上限：授权/未授权各自词法和当前向量池最多2000切片，截断标记进日志；未做大库全量完备召回或压力评估。默认阈值在本轮资料验证，不代表全行业准确率；重排失败可按召回阈值降级。无引用或引用编号非法时清空错误结果，模型事实逐句一致性仍需使用者结合原文核对。

Mongo 历史一次读取最近100轮、模型使用最多20条安全消息；会话列表分页，不提供全部历史归档导出。租约崩溃回收需要后续请求，不提供原 SSE 重放或自动恢复生成。跨 MySQL/Mongo 不具备分布式原子事务，采用预检、权威终态、证据一致性和失败关闭，不宣称整机断电/网络分区容灾通过。

FAQ 缓存、看板、运营聚合、知识缺口、FAQ 失效消费者和孤儿对象/向量 GC 留后续阶段；缓存日志明确 not_implemented。保留原 OCR/视觉边界。未验生产 TLS/公网、长期运行、实体手机/Safari 或辅助技术人工体验。

## 最终数据状态

精确记录的验收会话已关闭，Mongo 对应历史清理；原阶段四图片草稿保留。内部校验验收资料软删除，公开流程经真实 worker 重建为“项目资料归档流程（示例）”，仅 kb_admin/alice/bob 明确个人授权。kb_admin 保留一段真实“资料归档问答（示例）”，最终生产预览可打开答案与来源。账号8、角色5、部门4、非删除知识2，abc123未改动，详见 `evidence/stage5/final-state.json`。

三个初轮取消故障/服务重启时中断的精确 QA 请求曾停留 processing，所属会话已关闭，最后仅对这些记录手动结算为 cancelled/lease_expired，保留 `interrupted-qa-cleanup.json`。该人工修复不宣称为自动崩溃恢复；最终新请求的真实断流/取消已经独立验证。最终无 processing 请求，软删除资料的物理对象/向量仍按后续 GC 边界保留。
