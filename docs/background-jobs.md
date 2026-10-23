# 持久化导入与独立 worker

阶段一选择 MySQL 持久化任务和数据库租约方案，阶段二建立业务表，阶段四已实现执行器并完成真实存储联调。当前知识业务使用 `atguigu/business/import_service.py`、`import_worker.py` 与 `/api/knowledge`；原 `task_utils.py`/FastAPI `BackgroundTasks` 属于历史入口，不能用于持久化任务验收，旧数据 API 继续封闭。

MySQL 是任务、版本和有效切片的事实源；worker 是独立 Python 进程，在 Windows 使用 spawn 子进程执行耗时解析与模型调用。Redis 不承担当前任务队列，FAQ 缓存消费者留后续阶段。

## 已实现的数据与执行约定

1. `import_batches` 保存提交者、幂等键、文件数和汇总；`import_tasks` 保存单元/版本/原文件关联、任务状态、阶段、尝试次数、错误、进度、重试时间、租约和尝试令牌。数据库复合外键约束批次、任务、文件与提交者归属。
2. 上传先在私有 MinIO 保存源文件，并在同一业务事务内创建 unit、version、file、batch、task；提交后返回 HTTP 202。相同提交者、幂等键和文件摘要/相对路径重放返回原批次，内容冲突返回 409。重名文件分别拥有 UUID，不以文件名覆盖知识。
3. worker 用短事务 `SELECT ... FOR UPDATE SKIP LOCKED` 领取到期任务，提交租约后在事务外运行。每个任务由受控子进程执行，独立心跳续租；硬超时、子进程异常或停止会进入受控失败/重试路径。
4. 任务状态为 `pending → processing → completed / failed / cancelled`，阶段与错误持久化。网络、429、5xx 等可重试错误按指数退避等待；格式错误、旧 DOC、未启用 OCR 等不可重试。手动重试沿用 task/version ID 和累计 attempts，不新增重复知识。
5. 默认并发 1 个槽、租约 90 秒、心跳 15 秒、任务硬超时 900 秒、最多 3 次总尝试、退避基数 15 秒、轮询 2 秒。并发可配置为 1–8；当前验收使用低并发和远程 embedding，不加载本地 BGE-M3。
6. 过期租约可以重新领取，每次生成新令牌。心跳和完成写入都核对当前令牌与租期；迟到进程不能提交正文、切片或覆盖成功内容。图片对象和向量也按尝试令牌隔离。
7. `chunk_id` 由 version_id 与 chunk_index 稳定派生；Milvus 主键 `vector_id=chunk_id:attempt_token`。独立集合 `kb_platform_chunks_v1` 保存 unit/version/chunk/attempt、正文与位置，拒绝复用阶段一集合或不兼容维度/schema。MySQL 只登记成功尝试的切片及 vector_id。
8. 全部解析、embedding、向量写入/读回完成后，worker 只将版本标记 `ready`，不自动激活或发布。用户显式激活 ready 版本后才切换 active_version_id 和发布元数据；初次激活还需发布。失败的新版本保留旧 active 内容、标题、分类、标签及附件。
9. 列表、正文、附件、图片和任务 API 在每次请求重新检查身份、归属、版本、状态与四维授权。创建者维护自己的草稿需要对应操作权限，此例外不进入读者或检索授权；任务状态代查也不授权正文或文件。

MinIO 默认复用现有私有 `kb-stage1` 桶，以 `units/{unit_id}/versions/{version_id}/...` 隔离，服务不修改桶策略。专用账号不能读取策略时仍执行每个对象的匿名 GET 探测，仅 AccessDenied 允许继续。对外只返回 API 文件 ID，由 Bearer 鉴权代理下载或图片预览。

## 启动与重启

```powershell
.venv\Scripts\python.exe -m atguigu.cli worker
# 仅处理当前到期队列；没有执行槽和到期任务时退出
.venv\Scripts\python.exe -m atguigu.cli worker --once
```

也可用 `scripts/start.ps1 worker`。API 进程不代替 worker；只有 API 运行时任务仍会持久化为 pending。`--once` 不等待未来的 retry_at，自动退避应由常驻 worker 继续。配置修改后重新启动 API 和 worker，任务状态从 MySQL 读取。

## 已验证与边界

真实 MySQL 独立进程/连接测试 3 passed：持锁连接旁路领取（SKIP LOCKED）、两个进程领取不同任务、进程退出后租约回收及旧令牌心跳/完成被拒绝。测试任务仅属于随机专用 owner，排到一小时后且只前移测试子进程时钟，避免争抢同时运行的真实导入。它们没有调用模型或外部对象/向量存储，也没有模拟完整主机断电或网络分区。证据：`evidence/stage4/import-mysql.txt`。

HTTP 13 组真实联调通过，覆盖同名/幂等/混合失败、MD/TXT/DOCX/文字 PDF、Qwen3 embedding、MinIO/Milvus、版本重建/失败保旧、四维授权及撤权/下线后的读取拒绝；图片另有 4 组真实检查。内存存储/向量替身只用于针对性回归，独立标明，详见 [阶段四验收](stage4-validation.md)。

文档、授权、版本、状态与附件变化已写入 OutboxEvent，作为后续 FAQ 失效接口；尚无 FAQ 消费者或缓存命中验收。失败尝试遗留对象/向量以及软删除知识的物理数据尚无自动 GC。后续检索必须以 MySQL 的当前可读版本、chunk_id、vector_id 为准，不能把 Milvus 中旧版本或旧尝试直接加入问答上下文。

## 阶段五会话租约

问答实时SSE不使用导入任务队列。`chat_sessions`通过CAS reservation持有active_request_id和30秒lease_until，每轮短事务续租；同会话并发409，新请求可回收已过期租约并标旧请求cancelled/lease_expired。旧请求完成先校验租约，再以session→log一致锁序提交权威终态，不能覆盖胜出请求或释放其租约。

会话历史使用Mongo专用所属集合，MySQL记录请求/来源/终态。网络断开与主动停止会关闭真实模型流并用AnyIO shield保护终态清理；进程直接退出后依赖后续请求回收，不提供SSE重放或原模型恢复。真实独立进程竞争、精确过期回收、旧完成隔离和双存储终态4组通过，见`evidence/stage5/leases.json`；真实浏览器断开/显式取消/生成中撤权见阶段五HTTP与stream-controls证据。详细协议和日志口径见[阶段五接口契约](stage5-api-contract.md)。
