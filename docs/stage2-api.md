# 阶段二接口与数据约定

统一入口：`http://127.0.0.1:8102`；交互文档：[/docs](http://127.0.0.1:8102/docs)。
请求使用 JSON，登录之外的 `/api/*` 接口均要求 `Authorization: Bearer <access_token>`。字段和完整请求结构以 OpenAPI 为准，保存的接口快照为 `docs/evidence/stage2/openapi.json`。

## 认证与个人中心

| 方法与路径 | 用途 | 授权 |
| --- | --- | --- |
| POST /api/auth/login | username、password 登录；返回 access_token、user_info、permissions、expires_in | 无 |
| GET /api/auth/me | 当前用户、部门、角色、当前权限 | 登录 |
| PUT /api/auth/profile | 修改 display_name、email | 本人 |
| POST /api/auth/password | current_password、new_password；修改后全部旧 Token 失效 | 本人 |
| POST /api/auth/logout | 退出此账号全部登录会话 | 本人 |
| GET /api/auth/menus | 当前授权菜单的 code、name、path | 登录 |

新密码 12–128 字符，Argon2id 哈希；JWT 固定 HS256、校验签名/发行者/受众/有效期，默认 60 分钟。Token 只承载用户 ID 和凭证版本，角色与部门以请求时数据库结果为准。账号停用/重新启用、改密/重置密码、退出均使旧 Token 永久失效；角色、部门和权限变化在下一请求生效。无 refresh token，过期后重新登录。

用户名、部门编码、角色编码为 1–64 位小写字母/数字及 `_.-`，首位须为字母或数字。不接受额外 JSON 字段，校验错误不会回显密码。

## 组织管理

| 方法与路径 | 关键字段 | 操作权限 |
| --- | --- | --- |
| GET /api/org/users | page、page_size≤100、search、department_id、status | org:user:read |
| POST /api/org/users | username、password、display_name、email、department_id、role_ids | org:user:create；指定角色另需 org:user:assign-roles |
| PUT /api/org/users/{id} | display_name、email、department_id | org:user:update |
| POST /api/org/users/{id}/roles | role_ids，全量替换 | org:user:assign-roles |
| POST /api/org/users/{id}/status | status: active / disabled | org:user:status |
| POST /api/org/users/{id}/reset-password | password | org:user:reset-password |
| GET /api/org/roles | 返回角色及 permission_codes | org:role:read |
| POST /api/org/roles | role_name、role_code、description | org:role:create |
| PUT /api/org/roles/{id} | 同新增 | org:role:update |
| DELETE /api/org/roles/{id} | 有成员或知识授权时拒绝 | org:role:delete |
| POST /api/org/roles/{id}/permissions | permission_codes，全量替换 | org:role:permissions |
| GET /api/org/permissions | 菜单/操作目录与 parent_code | org:role:read |
| GET /api/org/departments | 树、leader_id、直属 member_count | org:department:read |
| POST /api/org/departments | code、name、parent_id、leader_id、sort_order | org:department:create |
| PUT /api/org/departments/{id} | 同新增；拒绝自环和祖先循环 | org:department:update |
| DELETE /api/org/departments/{id} | 有下级、成员或知识授权时拒绝 | org:department:delete |

用户的部门归属通过用户新增/编辑维护；一个用户一个直属部门、多个角色。负责人必须是存在且启用的用户，允许跨部门兼任。部门树编辑按 ID 顺序锁定部门记录，防止并发编辑形成循环。用户采用启停而非删除，保留审计和资源归属。

菜单只控制导航，不能替代操作权限；每个受保护操作单独检查对应编码。角色权限配置和用户角色分配属于高权限操作，拥有这些授权的账号可以明确授予相应角色能力。所有角色均没有硬编码超级用户分支。

## 四维知识权限

| 方法与路径 | 用途 | 操作权限 |
| --- | --- | --- |
| POST /api/knowledge/check-permissions | 检查自己的 unit_ids（1–500 项） | knowledge:check |
| POST /api/knowledge/preview-permissions | 管理端指定 user_id、unit_ids 代查，写入审计 | knowledge:preview |
| GET /api/knowledge/units/{id}/permissions | 读取授权元数据，不返回标题或正文 | knowledge:permissions |
| POST /api/knowledge/units/{id}/permissions | grants 全量替换，空数组即全部撤销 | knowledge:permissions |

普通鉴权请求不接受 `user_id`、角色或部门字段；原需求示例中的 user_id 已按流程记忆的身份安全约定拆到独立代查接口。查询字符串中伪造身份也不能改变登录用户。

```json
{"unit_ids":["<unit_id_1>","<unit_id_2>"]}
```

返回 `authorized_unit_ids` 和 `unauthorized_unit_ids`，按首次出现顺序去重；无权、不存在或未发布统一归入拒绝列表，不返回标题、正文或拒绝原因细节。

```json
{"grants":[
  {"target_type":"department","target_id":"<department_id>"},
  {"target_type":"role","target_id":"<role_id>"},
  {"target_type":"user","target_id":"<user_id>"}
]}
```

全局授权使用 `{"target_type":"global","target_id":"*"}`。同一知识单元内任意实体匹配即通过；部门严格匹配直属部门，不向下继承。无配置默认拒绝，系统管理员、知识管理员和创建者也不例外。普通鉴权还要求知识为 published、active_version_id 指向本单元 ready 版本；停用、删除、草稿、无有效版本均拒绝。

`knowledge:permissions` 明确授予全库授权元数据的管理权，可配置、撤销或给自己显式授权；它本身不授予正文。变更事务增加 permission_revision 并写入 outbox_events，当前权限引擎无缓存，立即按库判断。Outbox 消费者与 FAQ 缓存失效在后续阶段实现。

## 资源归属

| 方法与路径 | 范围 | 操作权限 |
| --- | --- | --- |
| POST /api/ai/sessions | 创建 title，owner_id 后端填写 | ai:chat |
| GET /api/ai/sessions | 本人会话，page/page_size | ai:chat |
| GET /api/ai/sessions/{id} | 本人有效会话元数据 | ai:chat |
| DELETE /api/ai/sessions/{id} | 本人软删除 | ai:chat |
| GET /api/knowledge/files/{id} | 受控文件元数据，无对象存储地址 | knowledge:file:read |
| GET /api/knowledge/tasks/{id} | 自己的状态、阶段、尝试次数 | knowledge:task:read |
| GET /api/knowledge/batches/{id} | 自己的状态与文件数 | knowledge:task:read |

`knowledge:task:read-any` 可显式代查任务/批次状态元数据，不授权文件、正文、错误详情或会话。没有会话管理员绕过。未关联知识的暂存文件仅上传者可访问；已关联文件要求当前知识正文权限，并校验关联版本为当前版本，上传者也须满足。无权资源统一 404。

本阶段只实现会话登记与上述元数据访问：文件字节下载、上传/任务执行、MongoDB 历史读取及模型 SSE 未接入。旧 8100/8101 的 `/upload`、`/status/*`、`/query`、`/history/*`、`/stream/*` 匿名请求返回 401，登录后返回 410，防止旧无权限链路绕过新体系。旧 HTML 仍保留作为基线，不能继续执行数据操作。

## 数据模型与错误约定

20 张业务表及 Alembic 版本表已部署。组织：users、departments、roles、user_roles、permissions、role_permissions；知识：knowledge_units、knowledge_versions、knowledge_chunks、unit_permissions、stored_files；任务：import_batches、import_tasks；会话/日志：chat_sessions、qa_access_logs；沉淀：faqs、faq_sources、knowledge_gaps；审计/事件：audit_events、outbox_events。

所有业务 ID 为字符串 UUID，单元/版本/切片各自稳定。复合外键保证激活版本和切片所属单元一致、文件版本一致、任务与批次/原文件同一所有者、问答日志与会话同一用户。FAQ 多来源表保留 unit_id/version_id；后续答案必须具备全部来源权限，不能把单篇 OR 套到多来源之间。faqs.related_unit_id 仅保留兼容字段，不作为唯一来源依据。

MySQL 每个连接设会话时区 +00:00，不修改共享实例全局时区；应用写入 UTC，接口时间使用 Z。迁移不会在 API 启动时自动执行。

HTTP 401：登录无效；403：缺少操作权限；404：资源不存在/不可访问；409：重复编码或关联冲突；422：字段/实体/循环非法；503：数据库不可用或迁移未完成。`/health` 为进程存活，`/ready` 检查数据库迁移版本和 JWT 配置。
