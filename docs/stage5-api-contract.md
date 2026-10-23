# 阶段五问答接口契约

统一前缀 `/api/ai/chat`，所有接口使用 Bearer 登录，当前真实账号必须 active 且拥有 `menu:ai`、`ai:chat`。会话、请求、引用只允许所属用户访问；系统管理员不绕过知识正文授权。时间使用 UTC，前端按 Asia/Shanghai 展示。

## REST

| 方法 | 路径 | 输入 / 返回 |
| --- | --- | --- |
| GET | `/sessions` | `page=1,page_size=50`，返回 items、total、page、page_size |
| POST | `/sessions` | `{title?: "新会话"}`，201 返回会话 |
| GET | `/sessions/{id}/messages` | 最近 100 轮，按时间正序；每轮包含 request_id、status、user、assistant、permission_hint、external_sources |
| DELETE | `/sessions/{id}` | 204；关闭会话、请求取消并删除所属 Mongo 历史，MySQL 审计日志保留 |
| GET | `/requests/{id}` | 归属自己的状态、是否取消、是否持久化、终止时间和耗时；不返回内部拒绝来源集合 |
| POST | `/requests/{id}/cancel` | 请求持久化取消；已结束请求不会重新启动 |
| GET | `/requests/{id}/citations/{chunk_id}` | 完成的所属请求、全部生成依赖仍有权时，返回当前切片的 title、content、position 和稳定 ID |
| POST | `/stream` | `{question,session_id?}`，返回 SSE；没有 session_id 时创建所属会话 |

`question` 去除首尾空白，默认上限 2000 字，受 `RAG_QUESTION_MAX_CHARS` 限制。多余输入字段如 `user_id` 返回 422。归属或正文不可访问统一 404；未登录 401、缺操作权限 403、同会话并发 409、历史存储或初始化失败 503。

默认标题固定为“新会话”，避免自动使用可能包含受限历史的问题作为会话列表标题。会话记录保存于 MySQL；Mongo 专用集合 `kb_platform_chat_turns_v1` 保存所属逐轮内容，原 `chat_history` 不读取、不迁移。读取历史和引用设置 `Cache-Control: no-store`。

## SSE v1

每个事件包含递增 `seq`、`request_id`、`session_id`。`id` 为 `{request_id}:{seq}`，事件数据是 JSON。服务端不支持 Last-Event-ID 重放；网络中断后查所属请求状态或重载历史，不自行重发原问题。

```text
id: <request-id>:1
event: meta
data: {"seq":1,"request_id":"...","session_id":"...","protocol_version":1,"status":"processing","cache_status":"not_implemented"}

```

| 事件 | 数据与语义 |
| --- | --- |
| `meta` | 首事件；此时 MySQL 请求与 Mongo 占位均已确认写入 |
| `progress` | 安全的 stage/status/message，不含候选标题或受限正文 |
| `sources` | `{sources:[...],final?}`；初次为授权生成上下文，`final:true` 为答案实际引用的子集，客户端以最新集合替换，不追加 |
| `delta` | `{text}`；直接转发模型流式内容，非完整回答后的模拟分片；无依据时可为后端固定说明 |
| `permission` | `{code,message,clear_answer}`；相关知识受限、授权变化或停止。clear_answer=true 时清除该轮问题、回答与来源 |
| `external_sources` | `{sources:[{source_type:"external",label,title,snippet,url}]}`；可选联网补充，独立于内部引用和生成依据 |
| `error` | `{code,message,clear_answer:true}`；不回显模型、数据库、存储错误详情或凭据 |
| `end` | `{status,persisted,reason,duration_ms,first_token_ms,usage,cache_status,external_sources}`，连接仍可写时必须有结束事件 |

5 秒心跳为 SSE 注释 `: heartbeat`，不消耗 seq。前端处理分段 UTF-8、CRLF 和 JSON 帧；未收到 end 视为连接中断。真实浏览器断开无法再接收 end，服务端仍执行受 AnyIO 取消屏蔽保护的终态写入。

终态为 `completed`、`restricted`、`no_match`、`low_confidence`、`error`、`cancelled`。模型流中断、来源引用缺失或编号无效会清除结果并结束为 error。客户端停止、账号/操作/授权/版本改变都有明确终态，未授权正文不会交给重排或生成。

## 来源和历史脱敏

来源使用 `unit_id/version_id/chunk_id`，同时保留 citation 编号、title、position、snippet 和鉴权 citation_url。真实 Milvus 主键可能为顶层 `vector_id`，兼容旧客户端 `id`；顶层主键、entity ID、赢得租约的 MySQL vector_id 和正文须一致。模型只使用重新读取的当前 MySQL 内容。

实际引用与授权依赖分开保存。全部生成上下文、问题改写和历史依赖都进入 `authorization_dependencies`；撤权或版本变化时整轮问题、回答和引用脱敏，不能把未引用但参与生成的资料重新放入下一轮上下文。MySQL 是终态权威，只有两存储已确认、answer/来源/依赖一致的回答才进入多轮上下文。来源拒绝提示仅公开安全说明，不公开受限 ID、标题、正文或对象地址。

会话使用 MySQL CAS、30 秒租约、约 0.2 秒检查/续租。总请求超时为 `MODEL_TIMEOUT_SECONDS * 5`，限制在 30–600 秒。新请求可回收过期会话，并将旧 processing 请求标为 cancelled/lease_expired；旧进程不能覆盖有效终态或释放新租约。这不是可重放队列，进程崩溃后不自动继续原模型输出。

## 日志和 usage

`qa_access_logs` 分别保存 recalled、authorized、unauthorized、实际 cited，生成依赖和截断/降级详情放入 details_json；内部集合不作为公开 SSE 内容。取消、错误和受限终态 actual cited 为空，保留必要的内部观察记录。断流尚未收到 provider usage 时为 unknown，不伪造 Token。

每个阶段保存调用列表，包括 status、duration_ms、known 和服务商实际 usage。聚合字段只累加已报告值；`usage_completeness` 为 complete/partial/unknown，partial 不能当作全部账单 Token。first_token_ms 从服务端 SSE 工作开始计算，response_time_ms 包括解析、检索、模型和终态持久化；不包括登录及请求接受前的存储预检。

FAQ 入口预留但返回 miss，不宣称缓存命中；本阶段所有请求 `cache_status=not_implemented`。
