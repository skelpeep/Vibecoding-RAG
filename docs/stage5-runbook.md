# 阶段五运行与使用

阶段五提供通用权限问答、混合检索、流式回答、所属会话历史和可重新鉴权的来源。沿用已有虚拟机 MySQL、MongoDB、MinIO、Milvus，以及本地 `.env` 的聊天、embedding 和 rerank 服务，不重建或清空旧存储。

## 启动

在项目根升级并检查：

```powershell
uv sync --locked
.venv\Scripts\python.exe -m alembic upgrade head
npm --prefix frontend ci
```

当前 Alembic 为 0004，仍有 20 张业务表。0004 给 chat_sessions 加入 active_request_id、lease_until，给 qa_access_logs 加入 cancel_requested、finished_at、details_json。降级前必须停止有效聊天请求；不应在活动 SSE 期间变更结构。

三个终端分别运行：

```powershell
.venv\Scripts\python.exe -m atguigu.cli platform --port 8104
```

```powershell
.venv\Scripts\python.exe -m atguigu.cli worker
```

```powershell
Set-Location -LiteralPath 'frontend'
$env:KB_API_TARGET = 'http://127.0.0.1:8104'
npm run dev -- --port 5185
```

| 入口 | 用途 |
| --- | --- |
| [问答工作台](http://127.0.0.1:5185/chat) | 登录后新建会话、提问、停止与引用核对 |
| [知识维护](http://127.0.0.1:5185/knowledge) | kb_admin 创建、构建、授权、激活和发布 |
| [API 文档](http://127.0.0.1:8104/docs) | 组织、知识、导入和 AI 统一接口 |
| [ready](http://127.0.0.1:8104/ready) | MySQL 迁移为 0004；不是所有模型/存储的综合健康检查 |

旧 8102/8103 进程加载历史 readiness 版本，升级后可能报告迁移不匹配；使用本轮 8104/5185。本地开发进程没有注册 Windows 服务或开机启动。历史 8100/8101 数据入口继续关闭。

账号密码在被忽略的 `var/setup/stage2-accounts.json`，不要重新初始化现有账号。`kb_admin` 可维护知识并问答，普通 `alice/bob/carol` 可问答；`admin` 不自动获得正文访问权。用户自行建立的 `abc123` 保留。

## 提问与来源

1. 知识必须索引 ready、显式激活、状态 published，并向当前用户匹配 global/department/role/user 任一授权。菜单、知识创建者维护例外或系统管理员身份不授予 RAG 正文访问权。
2. 打开 AI 问答，直接输入制度、流程或技术问题，不需要商品名称。资料不够时输出“未找到依据”或“依据不足”；只有受限资料时提示申请权限。
3. 回答流式显示，来源保留原引用编号。生成完成后可打开来源，后端重新校验所属请求和全部授权依赖。
4. 在同一会话继续问“那应该什么时候提交”等指代问题；不同用户和会话隔离。默认标题为“新会话”，不会自动复制受限历史内容到列表。
5. 停止生成、切换会话或离开页面会请求取消并关闭连接；迟到事件不写入其他会话。未发送的问题在切换或离开时有丢弃提示。
6. 撤权、撤销发布、停用或切换版本后，旧引用不再可读，重新加载历史会整轮脱敏；新一轮改写不会再携带其问题、答案和来源。

Markdown 经 marked + DOMPurify 处理，原始 HTML、图片和危险协议不会执行。知识图片/附件仍走阶段四独立鉴权接口，模型答案不自动加载文件或远程跟踪图片。

## 检索配置

| 配置 | 默认 / 含义 |
| --- | --- |
| `RAG_REWRITE_ENABLED` | true，有安全已完成历史时改写指代 |
| `RAG_HYDE_ENABLED` | false，单独真实验证通过，可启用；假设只用于向量检索 |
| `RAG_DENSE_LIMIT/MAX_LIMIT/BATCH_SIZE` | 24 / 96 / 200，授权当前向量池内检索与补充窗口 |
| `RAG_LEXICAL_LIMIT/SCAN_LIMIT` | 40 / 2000，独立授权/受限词法候选扫描上限；向量池每侧也有 2000 条上限 |
| `RAG_RRF_K/RERANK_LIMIT/FINAL_LIMIT` | 60 / 12 / 6，稳定切片 ID 融合与选入上下文 |
| `RAG_DENSE_MIN_SCORE/RERANK_MIN_SCORE/LEXICAL_MIN_SCORE` | 0.35 / 0.2 / 0.1，可按真实资料评估调节，不代表通用准确率 |
| `RAG_CONTEXT_MAX_CHARS/HISTORY_MAX_CHARS` | 14000 / 6000，限定资料和安全历史长度 |
| `RAG_QUESTION_MAX_CHARS/GENERATION_MAX_TOKENS` | 2000 / 1600 |
| `WEB_SEARCH_ENABLED` | false；开启需配置已有 MCP，补充结果单列为外部来源，不作为内部制度答案依据 |

关键词召回为 MySQL 匹配后的 BM25 算法，向量召回为真实 Qwen3 + Milvus COSINE，两路融合后重排。没有迁移为 Milvus sparse/fulltext。语义受限探测使用独立当前未授权向量池，只记录安全提示和内部审计，不向模型提交正文。模型、某路召回或可选节点失败有明确降级；无法形成可信结果时拒绝回答。

当前窗口是有界实现，不承诺超过 2000 候选切片的全库完备召回。details.metrics 保存 dense_scope_truncated、denied_dense_scope_truncated、lexical_truncated；大库应调整上限、引入服务端可检索授权索引或正式全文服务后压测。

## 验证

```powershell
$env:PYTHONUTF8 = '1'
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe -m alembic check
npm --prefix frontend run build
```

真实验收需要先创建精确隔离资料，脚本会调用实际模型和存储并生成证据：

```powershell
$env:STAGE5_FIXTURE_API='http://127.0.0.1:8104'
.venv\Scripts\python.exe scripts/prepare_stage5_fixtures.py
.venv\Scripts\python.exe scripts/verify_stage5_http.py
.venv\Scripts\python.exe scripts/verify_stage5_stream_controls.py
.venv\Scripts\python.exe scripts/verify_stage5_hyde.py
.venv\Scripts\python.exe scripts/verify_stage5_hyde.py --semantic-only
.venv\Scripts\python.exe scripts/verify_stage5_leases.py
.venv\Scripts\python.exe scripts/verify_stage5_migrations.py
```

HTTP/流式控制/UI 撤权脚本会暂时修改本轮隔离资料授权并恢复；应顺序运行，不并行修改同一 fixture。迁移与租约验证只操作随机前缀表或精确会话，既有资料和账号不清空。验收与边界见 [阶段五验证记录](stage5-validation.md)，SSE 与日志口径见 [接口契约](stage5-api-contract.md)。

FAQ 缓存、运营看板、知识缺口和后台 FAQ 失效消费者属于阶段六。可选 MCP 外部搜索未做真实服务成功验收；OCR/视觉保留阶段四边界。长期运行、生产 TLS、实体手机/Safari、全库规模性能与整机断电未宣称已验证。
