# 数据看板与知识沉淀接口

所有接口使用 `Authorization: Bearer <token>`。操作权限和知识正文权限独立；系统管理员不绕过来源授权。完整 OpenAPI 位于运行服务的 `/docs` 与 `/openapi.json`。

## 数据看板

`dashboard:read` 访问。日期参数为 `start=YYYY-MM-DD&end=YYYY-MM-DD&timezone=Asia/Shanghai`，结束日期包含当天，服务端转换成 UTC 左闭右开区间。默认最近七天，最长 366 天；`bucket=day|week`，周从周一开始。

| 方法和路径 | 返回 |
| --- | --- |
| GET `/api/dashboard/overview` | 同一批日志计算的 metrics、trends、questions、units、latency、range、definitions |
| GET `/api/dashboard/metrics` | 访问、UV、当前知识总量、已知 Token、平均耗时、各终态与缓存命中 |
| GET `/api/dashboard/rankings/questions` | 有当前全部来源访问权的问题榜，`limit` 1–100 |
| GET `/api/dashboard/rankings/units` | 当前可访问知识引用热度，一轮一篇计一次 |
| GET `/api/dashboard/stats/tokens` | 按日/周访问、Token、平均耗时及耗时区间计数 |

访问包含已接纳的失败、取消、受限、处理中请求；认证前拒绝不入日志。平均耗时仅使用有耗时的终态记录。Token 是供应商实际已知用量之和，`unknown_usage` 与 `partial_usage` 单列；全部未知返回 null，空范围为 0，缓存命中为 0。知识总量是当前未删除量，含草稿。榜单正文依当前来源权限过滤，因此管理员可能看到访问总量但没有私有标题和问题文本。

## FAQ

| 方法和路径 | 权限与参数 |
| --- | --- |
| POST `/api/settlement/mine` | `settlement:faq:review` + `settlement:gap:manage`；返回实际挖掘模式、窗口、阈值、截断情况和新增量 |
| GET `/api/settlement/faqs/recommendations` | `settlement:faq:read`；待审核列表 |
| GET `/api/settlement/faqs` | `settlement:faq:read`；status=pending_review/published/rejected/withdrawn；page/page_size |
| POST `/api/settlement/faqs/{id}/review` | `settlement:faq:review`；`{action: approve或reject, revision, edited_answer?}`；approve 另需 publish |
| PUT `/api/settlement/faqs/{id}` | review；`{revision, answer}`；已发布还需 publish，修改后重新待审核 |
| POST `/api/settlement/faqs/{id}/withdraw` | publish；`{revision}`；来源失效时原审核人仍可撤回 |

并发 revision 不一致返回 409。空白答案 422。来源不完整、当前版本不同或缺权限返回 404。列表不泄漏受限答案；原审核人可看到脱敏后的失效记录。FAQ 保存全部生成依赖，而不只保存最终展示引用；所有来源须同时有权。

挖掘默认最近 30 天、最多 5000 条，频次至少 3 次、embedding cosine 阈值 0.92。不同 unit/version 集合硬隔离；源于缓存、不完整持久化或外部搜索的答案不成为候选。语义服务失败显示 `exact_fallback`，不会冒充语义成功。窗口内频次重算不累加。周期服务命令为 `python -m atguigu.cli settlement-worker`，默认每 300 秒运行，可用 `--once` 单轮执行。

Redis key 为 `kb-platform:faq:v1:{faq_id}`，TTL 默认 3600 秒。返回前核对 MySQL 当前 FAQ revision/status/answer、全依赖版本、授权及缓存签名；每次 SSE 输出与完成时复核。Outbox 消费者持久化失效进度，Redis 不可用时保留待处理事件。缓存不可用安全退回正常 RAG。仅首轮问题使用标准化精确匹配，保留负号、小数点和运算符；有多轮上下文时正常检索，不用孤立问题缓存。

SSE 仍兼容阶段五协议，meta.cache_status=pending，end.cache_status=hit/miss/unavailable。hit 的实际模型 Token 为 0，界面标记“FAQ 缓存回答”。撤权或 FAQ 修订后旧缓存回答历史和引用同样重新鉴权。

## 知识缺口

均需 `settlement:gap:manage`。

| 方法和路径 | 参数与行为 |
| --- | --- |
| GET `/api/settlement/knowledge-gaps` | status=unresolved/resolved/ignored；page/page_size |
| POST `/api/settlement/knowledge-gaps/{id}/draft` | title/content/summary/category/tags/grants；另需 knowledge:create，创建真实入队草稿并关联；重复关联 409 |
| POST `/api/settlement/knowledge-gaps/{id}/status` | `{status, request_id?}`；解决时必须提供本人的成功原问题验证 |

仅无命中/低置信度且没有拒绝来源或检索降级的日志进入缺口。解决时验证原问题、成功持久化、本人的回答、当前发布版本、全部来源权限以及实际引用补全知识；草稿、旧版本、其他问题、其他用户回答均不能关闭缺口。手机与桌面可从“验证原问题”进入问答，再点击“用此回答确认补全”。
