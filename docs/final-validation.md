# 最终集成验收

验收日期：2026-10-22（Asia/Shanghai）。阶段一至七的本地可运行交付已完成；范围依据原需求 §2.9.11 及阶段七提示词。统一入口 http://127.0.0.1:8105，数据库 20 张业务表、Alembic 0005。运行方式见 [交付说明](final-delivery.md)。

2026-10-23 仓库整理：以下保留原开发环境验收结果；原始 `evidence/stage*/` 文件仅留本机，不随 Git 上传，链接在新克隆中不可用，见 [证据目录说明](evidence/README.md)。新环境安装见 [setup.md](setup.md)，不预置开发机数据库、演示知识或账号密码。

## 原需求八项映射

| 原验收项 | 页面 / 接口 | 用例与结果证据 |
| --- | --- | --- |
| 1. 登录、角色、部门、菜单与按钮授权 | /login、/org/users、/org/roles、/org/departments；/api/auth、组织管理 API | 最终真实浏览器 19 组通过，含账号启停、改密、角色权限即时撤销、移动操作及精确清理；[记录](evidence/stage7/org-ui/interactions.json)。真实 MySQL 组织/知识 API 44 项通过。 |
| 2. 单篇与批量导入、知识切分入库 | /knowledge/import；/api/import；独立导入 worker | 阶段六真实 Markdown/TXT 批量导入、MinIO 原文、切片和 Milvus 索引发布通过；[HTTP 记录](evidence/stage6/http.json)。最终独立 MySQL worker 3 项通过；阶段四还覆盖 DOCX/文字 PDF、逐文件失败重试与图片附件，见 stage4-validation.md（历史验收）。 |
| 3. 知识 CRUD 与四维混合配置 | /knowledge、/knowledge/new、详情/编辑/访问范围；/api/knowledge | 最终回归包含默认拒绝、CRUD、版本与授权；真实 MySQL API 44 项通过。阶段六真实创建、更新、版本切换和撤权链路通过；原阶段四 UI 23 组与三组注入状态见历史验收。 |
| 4. 单篇知识部门/角色/个人/全局任一匹配可读 | 详情授权预览及服务端统一 authorization | test_stage2、test_stage4_api、test_stage5_rag/chat 均进入最终全套回归；真实多账号验证全部有权/部分有权/无权。单篇四维 OR，多篇 FAQ 来源必须全部有权。 |
| 5. 登录问答、授权过滤与明确拒绝提示 | /chat；/api/ai/chat/stream、所属 sessions/messages/citations | 最终继承 RAG/会话/传输测试全通过；阶段六真实多源生成、部分授权拒绝缓存、撤权历史脱敏通过。阶段五真实 HTTP、断流、多轮和 HyDE 证据见 stage5-validation.md（历史独立实测）。 |
| 6. 访问、UV、知识量、问题榜、热度、Token、耗时趋势 | /dashboard；/api/dashboard/overview 等 | 阶段六真实日志重算与上海时区验证通过；最终页面有访问/Token/响应时间三趋势、耗时分布，零值与孤立观测点验收通过；[正式入口记录](evidence/stage7/production-smoke.json)。 |
| 7. 自动高频挖掘、推荐 FAQ、审核缓存 | /settlement 推荐/已发布；/api/settlement/mine、faqs；settlement-worker | 真实 embedding 语义分组、三次门槛、幂等频次、审核发布与 Redis 命中、撤回/版本/权限失效均通过；正式构建页面真实命中、落库且模型 Token=0。 |
| 8. 自动缺口与提问频次 | /settlement?tab=gaps；knowledge-gaps API | 未命中真实模型→挖掘缺口→创建关联草稿→实际索引→激活发布→原问题引用→确认解决；[手机闭环四组](evidence/stage6/ui/gap-draft.json)。受限/检索降级不误报缺口，草稿不直接关闭缺口。 |

## 本轮执行结果

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 全套后端回归 | 171 passed，4 skipped | evidence/stage7/tests.txt |
| 真实 MySQL 组织/知识 API | 44 passed | evidence/stage7/api-mysql.txt |
| 真实 MySQL 独立导入 worker | 3 passed | evidence/stage7/import-mysql.txt |
| 真实 MySQL 新建及升级/回滚再升级 | 通过，临时表无残留，正式 head=0005 | evidence/stage6/migrations.json |
| 真实 HTTP、模型与七种服务能力 | 11 组通过（MySQL/Redis/Mongo/MinIO/Milvus、embedding/rerank/chat） | evidence/stage6/http.json |
| 阶段六浏览器操作与状态 | 8 组、27 张三宽度截图、0 页面错误；网络故障组明确为注入 | evidence/stage6/ui/interactions.json |
| 手机缺口补全 | 4 组、0 页面错误 | evidence/stage6/ui/gap-draft.json |
| 组织 UI 最终回归 | 19 组、0 页面错误、精确清理成功 | evidence/stage7/org-ui/interactions.json |
| 正式构建同址浏览器 | 5 组、9 张三宽度截图、0 页面错误 | evidence/stage7/production-smoke.json |
| 前端依赖、类型检查与生产构建 | npm ci 成功，0 vulnerabilities；vue-tsc + vite build 成功 | evidence/stage7/npm-ci.txt、build.txt |
| UI 技能 | 14 个路由状态 × 三宽度，全部 0 FAIL；源码 0 FAIL / 5 WARN | evidence/stage7/inspect-summary.json、lint.txt |
| Python 打包与交付文件核对 | 源码、锁文件、迁移、脚本与说明齐全；无本机配置/凭据 | evidence/stage7/package-build.txt、packaging.json |
| 最终运行态 | 同址 API 与两个 worker 存活，0005、Outbox 与周期挖掘记录核对 | evidence/stage7/runtime.json |

4 个跳过项是 SQLite 无法覆盖的 MySQL 时区用例与三个需显式启用的真实 worker 用例；后者已在独立真实 MySQL 测试中通过。现有 Starlette TestClient 对 httpx 的弃用警告保留。替身 Redis/embedding 仅用于可控故障、安全和边界测试，不能替代上述真实服务结果。

所有界面截图均为 Chrome 的 1440/768/390 模拟视口；原版检查器没有修改或放行参数。设计方向、数值一致性和逐项 WARN 理由见 [七项视觉评审](../.taste-skill/final-review.md)。

## 实现口径与最终修复

- 看板范围含结束日，UTC 存储、上海日/周聚合。访问含失败/取消/受限/处理中；耗时只计终态；Token 为已知用量之和，未知/部分单列。知识量为当前未删除量，含草稿；榜单标题和问题继续校验正文权限。
- FAQ 默认 30 天/5000 条、3 次门槛、cosine 0.92；不同完整来源版本集合不合并。无历史首轮只做标准化精确缓存，负号、小数点与运算符保留。语义服务故障标记 exact_fallback。
- 缓存读取、SSE 输出、完成及历史引用均校验当前全依赖。Redis 失效事件持久化重试；非对象 JSON 缓存不会导致问答异常。停用、撤权、版本变化或 FAQ 撤回可立即阻止旧答案，即使物理缓存删除尚未执行。
- 最终前端修正了状态过滤标签、缺口原问题一键确认补全、三趋势图、孤立耗时点与缺失说明。正式同址 SPA 在 Windows 的路径分隔符已规范化，未知 /api 路径返回 JSON 404。
- 最终启动/停止脚本只管理登记且路径/启动时间匹配的进程。npm ci 遇到本项目 esbuild 文件锁时明确提示，处理锁后重新安装构建成功；首次失败保存在 npm-ci-initial-file-lock.txt。
- 首次批量 HTTP 验收脚本误把返回顺序当上传顺序，造成测试资料授权颠倒。按实际标题建立映射后重跑通过，首轮精确 UUID 已软删除；失败保存在 http-initial-fixture-order-failure.json。这不是产品绕过正确授权。

## 交付边界

交付本地源码工程、构建成果、迁移/初始化/启动脚本、演示与验收说明。没有对外发布或改成操作系统服务。已有账号和用户数据保留；示例密码仅在忽略的 var/setup/stage2-accounts.json。演示日志参与当前统计，不宣称真实业务量。

OCR、外部搜索和图片视觉摘要的外部服务默认关闭且未最终实测；旧 DOC 需转换。未验证实体手机/Safari、长期压测、整机断电恢复或公网 TLS。检索、看板和挖掘有文档所列窗口/候选限制，大规模场景需进一步评估。软删除对象/旧向量的自动物理垃圾回收未实现。这些边界不属于原八项本地核心验收的通过范围。
