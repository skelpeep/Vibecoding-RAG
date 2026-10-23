# 阶段四前后端接口契约

所有路径前缀为 `/api/knowledge`，使用现有 Bearer 登录。错误统一为 `detail`，未授权的数据返回 404。时间为 UTC ISO 字符串。

## 数据与访问

- 读者仅能看到 published + 当前 ready 版本 + 四维 OR 授权的知识。列表总数、分类、标题和附件同样过滤。默认拒绝。
- 创建者同时具有 `knowledge:create`、`knowledge:update`、`knowledge:import` 任一个操作权限时可在管理页面读取自己未删除的知识；编辑/版本/附件操作还必须有 `knowledge:update`，删除必须有 `knowledge:delete`。此例外不进入 check-permissions 或检索授权。
- 系统管理员没有正文绕过。`knowledge:permissions` 保留既有全库授权元数据管理能力，但不自动开放标题、正文、旧版本或文件。
- version 内容不可变；编辑生成 pending 版本。worker 构建成功只改为 ready，用户显式激活 ready 版本；初次激活后仍需发布。失败时旧 active_version_id 不变。

## 知识

| 方法 | 路径 | 参数 |
|---|---|---|
| GET | `/units` | `page=1,page_size=20,search,category,status` |
| POST | `/units` | JSON `{title,content,summary?,category?,tags?,grants?}` |
| GET | `/units/{id}` | 无 |
| PUT | `/units/{id}` | JSON `{title,content,summary?,category?,tags?,grants?}` |
| DELETE | `/units` | JSON `{unit_ids:[...]}`，原子批量软删除 |
| POST | `/units/{id}/status` | JSON `{status:"draft"|"published"|"disabled"}` |
| GET | `/units/{id}/versions` | 创建者管理能力必需 |
| GET | `/units/{id}/versions/{version_id}` | 创建者管理能力必需，含 content/chunks |
| POST | `/units/{id}/versions/{version_id}/rebuild` | 无，创建内容相同的新 pending 版本及任务 |
| POST | `/units/{id}/versions/{version_id}/activate` | 无，仅 ready 版本 |
| GET | `/categories` | 返回 `{items:[string...]}`，仅可见知识分类 |

列表响应 `{items,total,page,page_size}`。item 为 `{id,unit_id,unit_code,title,summary,category,tags,status,creator_id,creator_name,active_version_id,source_file_name,file_type,file_size,created_at,updated_at,permission_summary,can_edit,can_delete,can_manage_permissions,can_manage_versions,can_attach}`。

详情在 item 基础上增加 `{content,active_version,latest_version,attachments,grants,is_maintenance_view}`；无权限管理者的 grants 为空数组。管理者 content 是最新版本供编辑，读者 content 是当前 active 内容。version 为 `{id,version_id,unit_id,version_number,status,created_at,activated_at,is_active,content_hash,metadata}`；管理视图额外带 `task_id,batch_id`，普通读者不返回任务归属信息。版本列表 `{items:[version...]}`。创建/更新/重建返回详情并额外 `{task_id,batch_id}`。

`metadata_json` 保存版本标题、摘要、分类、标签及原文件元数据；激活时才复制到单元的当前发布视图，避免未发布编辑泄露到标题搜索、分类和列表。编辑和重建会克隆来源版本普通附件的独立文件记录与存储对象，正文对应图片引用同步重写；旧版文件仍仅限创建者维护访问。

## 权限

- GET `/permission-options?search=`：`{departments:[{id,name}],roles:[{id,role_name}],users:[{id,username,display_name,department_id}]}`。需 `knowledge:permissions` 或 `knowledge:preview`。
- GET/POST `/units/{id}/permissions`：保持阶段二 `{grants:[{target_type,target_id}]}`。global 的 target_id 必须为 `*`，空 grants 默认拒绝。
- POST `/preview-permissions`：保持 `{user_id,unit_ids}`，响应 `{authorized_unit_ids,unauthorized_unit_ids}`。仅检查当前真实状态并写审计，不暴露正文。

## 附件

- POST `/units/{id}/attachments`：multipart `file`，可选 `version_id`；默认绑定最新版本。响应附件元数据。
- DELETE `/units/{id}/attachments/{file_id}`：删除附件关联；仅附件类型，不删除导入源文件。
- GET `/files/{file_id}`：现有元数据接口。
- GET `/files/{file_id}/download`：鉴权后二进制代理返回，无公开 MinIO URL。
- GET `/files/{file_id}/image`：仅 PNG/JPEG/GIF/WebP 图片，鉴权返回，其他类型 415。
- 附件元数据 `{id,file_name,file_size,content_type,purpose,unit_id,version_id,download_url,image_url}`。旧版本附件仅创建者管理能力可读取。每次请求重校验权限；撤权、下线、删除后读者不可读取。

## 导入/worker 约定

POST `/import` 使用 multipart：重复字段 `files`、必填 `idempotency_key`（1–100 字符，建议 UUID）、可选 `relative_paths`（与 files 顺序一致的 JSON 字符串数组）、可选 `category`。返回 HTTP 202 和 batch。相同提交者的相同幂等键与文件摘要/相对路径重放返回原批次，冲突返回 409；重名文件使用不同 unit/version/source/chunk IDs。

GET `/batches?page=1&page_size=20` 返回 `{items,total,page,page_size}`，列表 item 不含 tasks。GET `/batches/{id}` 含完整 tasks；GET `/tasks` 支持 `page,page_size,batch_id`；GET `/tasks/{id}` 返回单任务；POST `/tasks/{id}/retry` 无 body，返回原任务，保留 task/version ID 与累计 attempts。只有可重试错误且未达上限才能重试，网络/429/5xx 自动指数退避；无效格式、旧 DOC、OCR 未开启等不重试。

batch：`{id,batch_id,status,file_count,counts:{pending,processing,completed,failed,cancelled},created_at,updated_at,tasks?}`。batch status 可为 `pending,processing,completed,partial_failed,failed,cancelled`。

task：`{id,batch_id,status,stage,attempts,max_attempts,created_at,updated_at,unit_id,version_id,file_name,file_size,relative_path,error_code,error_message,retry_at,progress:{percent,chunk_count?,image_count?,warnings?},can_retry}`。status 为 `pending,processing,completed,failed,cancelled`；stage 为 `uploaded,parsing,images,chunking,embedding,indexing,ready,retry_wait,failed,cancelled`。只有任务本人且关联知识仍可管理或当前版本已授权时展示文件/错误/单元信息；read-any 仅提供状态元数据。

GET `/import/capabilities` 返回 `{extensions,max_files,max_file_bytes,max_batch_bytes,pdf_ocr,image_summaries,boundaries}`。默认限制 100 文件/批、50 MiB/文件、200 MiB/批；上传超出限额返回 413/422。文件格式错误作为单文件 failed 持久化，与成功文件组成部分失败批次。支持 UTF-8、BOM UTF-16、GB18030 TXT，MD/Markdown，DOCX，文字 PDF；旧 DOC 须转换 DOCX。扫描图片页默认 `PDF_OCR_REQUIRED`，配置 `IMPORT_PDF_OCR=true` 后调用真实 MinerU。DOCX/PDF 和 Markdown data URI 的图片写入受控 MinIO 并替换成 API `/files/{id}/image`；外链/本地相对图片不读取并返回 warning。可选 `IMPORT_IMAGE_SUMMARIES=true` 调用真实独立视觉模型；默认保留原图不生成摘要。

worker：`python -m atguigu.cli worker`，或 PowerShell `scripts/start.ps1 worker`；`--once` 在当前到期队列清空后退出，未到期自动重试由常驻模式继续。短事务 SKIP LOCKED 领取，默认 1 个子进程槽、90 秒租约、15 秒心跳、900 秒硬超时、3 次总尝试。过期租约可回收，每次令牌不同；MySQL 完成写入核对令牌/租期，外部图片和向量使用尝试令牌隔离，迟到进程不能覆盖已成功内容。chunk_id 由 version_id + chunk_index 稳定派生，vector_id 为 chunk_id:attempt_token，后续检索必须按 MySQL 当前可读 version/chunk/vector_id 过滤，不能直接信任集合里的旧尝试。未引用的失败尝试对象/向量保留为待清理孤儿，当前未实施自动 GC。

API 创建 unit/version 后调用 `import_service.enqueue_version(db,owner_id,unit,version,upload=None,idempotency_key=None)`，同步返回 ImportTask；不提交调用方事务。worker 只索引到 ready，不自动激活或发布。

附件存储：`get_storage().put_bytes(object_key,data,content_type,bucket=None)` / `get_bytes(object_key,bucket=None)` / `delete_object(object_key,bucket=None)`；StoredFile.bucket 使用 storage.bucket。

`KNOWLEDGE_BUCKET` 留空复用当前私有 MinIO 桶，以 `units/{unit_id}/versions/{version_id}/...` 隔离旧阶段数据；不修改桶策略。若专用账号无权限读取桶策略，服务仍对每个对象执行无认证 GET 探测，只有 AccessDenied 才允许继续，匿名可读对象不会成为 ready 版本。Milvus 使用独立 `KNOWLEDGE_CHUNKS_COLLECTION=kb_platform_chunks_v1`，禁止配置成阶段一集合。

文档、授权、版本、状态、附件变化写入 OutboxEvent。FAQ 缓存消费者尚未实现，事件是明确的后续失效接口，不宣称缓存命中验证完成。
