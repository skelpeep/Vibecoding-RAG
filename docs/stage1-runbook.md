# 阶段一运行与依赖说明

> 更新：2026-10-21 已在 192.168.100.188 补齐并验证存储，根 .env 已填写。最新结果见 [虚拟机部署记录](vm-deployment.md) 与 [配置填写指南](env-guide.md)；下文缺存储记录属于首次本地基线。

日期：2026-10-21。支持入口为项目根目录的 `atguigu.cli` 和 `scripts/start.ps1`。本轮范围为原流程运行基线，新业务 API 和 Vue 前端未创建。

## 环境与安装

已实测 Windows 11、Python 3.12.8、uv 0.12.0、Node 24.19.0、Chrome 155。Python 范围限制为 3.12–3.13：原源码使用 Python 3.12 的 f-string 语法。Node 在阶段一不参与构建。

```powershell
uv sync --locked
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
```

基础安装包含 Web 服务、两条 LangGraph 的编译依赖、存储客户端及开发验证工具，实装 94 个包。`uv.lock` 固定实际解析版本，不需要全局 pip 安装。`uv sync --locked --no-dev` 可不安装 pytest 与 Playwright；需要截图时保留 dev 组。

基座原依赖直接强制 CUDA，且缺少启动和上传的直接依赖；本轮分拆后，基础 Web 服务无需下载模型即可启动。当前向量模型已改为远程 API，运行图不再依赖本地 BGE 推理。

## 模型运行方式

| 能力 | 配置 | 当前状态 |
| --- | --- | --- |
| 生成/商品识别/HyDE | OPENAI_API_BASE、OPENAI_API_KEY、LLM_DEFAULT_MODEL、ITEM_MODEL | 已配置，完整链路待验证 |
| 图片理解 | VL_BASE_URL / VL_API_KEY / VL_MODEL，独立 OpenAI 兼容视觉站点 | 地址已设为 https://ai.xmiaom.com/v1，待填该站点密钥 |
| PDF 解析 | MinerU API | 按需配置与验证 |
| 重排序 | EMRank `/v1/rerank`，Qwen/Qwen3-Reranker-8B | 真实请求已通过 |
| 向量 | EMRank `/v1/embeddings`，Qwen/Qwen3-Embedding-8B，4096 维 | 真实请求已通过；与 rerank 共用地址和密钥 |
| 联网 | 可选 MCP，默认关闭 | 未配置、未验证 |

模型通过远程 API 调用，无需本地 BGE-M3 权重、torch 或 CPU/CUDA extra。基础依赖安装 `uv sync --locked` 即可。具体环境变量见 [env-guide.md](env-guide.md)。

导入片段、主体索引、问题和 HyDE 全部使用同一远程 embedding 模型；主体与片段 Milvus 集合按实际维度创建，仅保留稠密向量，使用 COSINE 检索并保持主体过滤。旧 BGE 稀疏集合或不一致的维度会触发明确提示，需换新集合并重新导入，代码不会改动已有数据。

VL 使用独立 VL_BASE_URL 和 VL_API_KEY；它们不会回退到聊天凭据。无图片的 Markdown 不需要视觉配置。模型与维度在进程启动时加载，修改 `.env` 后重启两个 Python 服务。

## 存储条件

`doctor.py` 对配置地址执行只读 TCP 探测，不能将 TCP 可达解释为认证或协议成功。当前五个默认端口均不可达。项目开始没有 `.env`，相关进程环境变量未发现；现已从模板生成无真实密钥的 `.env`。

| 服务 | 默认地址/命名空间 | 用途 |
| --- | --- | --- |
| Milvus | 127.0.0.1:19530；kb_stage1_chunks、kb_stage1_items | 原商品与知识切片索引 |
| MinIO | 127.0.0.1:9000；kb-stage1 | 原文件和图片；凭据必填 |
| MongoDB | 127.0.0.1:27017；kb_stage1.chat_history | 原对话历史 |
| MySQL | 127.0.0.1:3306；kb_platform | 阶段二起组织/权限/任务业务表 |
| Redis | 127.0.0.1:6379/0 | 后续缓存；不是当前问答的必选依赖 |

可以配置已有服务；不要把基线验证指向正式集合。`MINIO_PUBLIC_BASE_URL` 控制旧图片引用地址，但客户端不会修改已有桶策略，私有桶的直接图片 URL 可能不可访问；受控附件/图片接口留阶段四。

提供 `compose.yaml` 可启动隔离的开发依赖，数据保存在项目名下独立 Docker volumes。先在 `.env` 设置自己的 MINIO_ACCESS_KEY、MINIO_SECRET_KEY、MYSQL_ROOT_PASSWORD、MYSQL_PASSWORD，再执行：

```powershell
docker info
docker compose --env-file .env config --quiet
docker compose --env-file .env up -d
docker compose ps
.venv\Scripts\python.exe scripts/doctor.py
```

Compose 内 MySQL 用户为 `kb_app`，后续将 MYSQL_URL 改为该用户连接串（含密码时注意 URL 编码）。Milvus 等容器仅用于本地基线，未完成生产配置。

本次 Docker Desktop 客户端 29.2.1 存在；尝试隐藏启动后引擎曾短暂响应版本，随后 LinuxEngine 命名管道消失，com.docker.service 为 Stopped。**Compose 语法已检查，容器拉取、启动、健康状态与 Milvus 2.6.3 / pymilvus 3.0.1 实际兼容性均未验证**。需恢复 Docker/WSL2 引擎或提供外部服务后重测。没有删除、清空或迁移任何已有数据库/向量集合。

## 目录、端口与接口

| 位置 | 职责 |
| --- | --- |
| atguigu/import_process、query_process | 原 LangGraph 流程及节点 |
| atguigu/web/api | 原协议 FastAPI 入口 |
| atguigu/web/page | 原始 HTML 行为参考 |
| atguigu/config、tool | 环境配置、客户端与共用工具 |
| var/data | 按 UTC 日期和 UUID 隔离的本地文件；被 Git 忽略 |
| var/logs | 本轮临时运行日志与进程号；被 Git 忽略 |
| docs/evidence/stage1 | 环境、真实流程、测试及截图证据 |

| 服务 | 启动 | 接口 |
| --- | --- | --- |
| 导入 8100 | scripts/start.ps1 import | GET /、/health、/docs；POST /upload；GET /status/{task_id} |
| 问答 8101 | scripts/start.ps1 query | GET /、/health、/docs；POST /query；GET /stream/{task_id}；GET/DELETE /history/{session_id} |
| 新管理前端 | 未创建，后续默认考虑 5173 | 阶段三 |

服务绑定 127.0.0.1。原接口还没有登录、四维权限和归属控制，仅用作本地基线。不得以此当作阶段二或五的已完成接口。

原 SSE：先 POST `/query`，再 GET `/stream/{task_id}`；事件包含 progress、delta、final，额外提供 done / error 终态。`final` 是原答案/图片消息，`done` 表示任务完成；断开清理队列，后续节点不再等待消失队列。尚未实现取消模型计算、重连回放、队列容量上限及长期任务状态清理；每个服务单进程运行。

## 可复现验证与真实边界

使用 `examples/KB-DEMO-180.md`。浏览器可直接上传后查看状态，在问答页问“KB-DEMO-180 演示设备应如何停机？”。`scripts/verify_baseline.py` 每次复制独立名称和会话 ID，执行原入口识别、无图片 Markdown 读取和切分，再尝试真实上传、导入、历史和问答。

当前预期结果：两页 200、上传 200、本地解析 5 个非空片段；文件备份阶段因 MinIO 凭据缺失失败；历史返回 503；查询接收 200，SSE 返回失败终态。它们只证明可启动和正确暴露缺项，不能证明向量检索与答案生成成功。

补齐服务后再次执行验证，并核对导入 `completed`、Milvus 中独立示例数据、真实 delta 文本、最终来源及 MongoDB 历史后再标为通过。脚本未删除测试数据；请保留独立测试命名空间。PDF 还需 MinerU、图片还需视觉模型与可访问引用配置，Word/TXT 格式扩展属于阶段四。

## 后台任务决策

后续采用 MySQL 持久化任务和独立 Python worker，使用租约与 SKIP LOCKED 领取任务；见 [background-jobs.md](background-jobs.md)。本轮只完成方案，当前进程内状态重启会丢失，不能按持久化导入验收。
