# 当前 .env 填写指南

本文为原开发环境配置记录，IP、模型站点与“已填写”均不代表新克隆可直接使用。新安装以 [setup.md](setup.md) 为准；当前统一应用启动使用 `scripts/start-project.ps1`，文末旧 import/query 命令仅为历史参考。

适用部署：Windows 运行 Python API，模型通过远程接口调用，192.168.100.188 虚拟机运行存储服务。实际密钥只填写项目根目录 `.env`，不要写进 `.env.example` 或流程记忆。

## 已经自动填写的存储配置

| 配置项 | 当前内容/用途 |
| --- | --- |
| MILVUS_URL | http://192.168.100.188:19530 |
| MILVUS_TOKEN | 留空；当前已有 Milvus 实例未启用认证，没有改动其全局配置 |
| CHUNKS_COLLECTION / ITEM_NAME_COLLECTION | kb_stage1_chunks / kb_stage1_items，独立项目集合名 |
| MINIO_ENDPOINT / MINIO_PUBLIC_BASE_URL | 192.168.100.188:9000 / http://192.168.100.188:9000 |
| MINIO_ACCESS_KEY / MINIO_SECRET_KEY | 已生成专用账号，限定 kb-stage1 桶，已填入本地 .env |
| MINIO_BUCKET_NAME | kb-stage1，已创建，保留私有访问 |
| MONGO_URL / MONGO_DB_NAME | 已填写专用 kb_app 账号连接串；192.168.100.188:27017 / kb_stage1 |
| MYSQL_URL / MYSQL_PASSWORD | 已填写 kb_platform_app 专用账号；192.168.100.188:3306 / kb_platform |
| MYSQL_ROOT_PASSWORD | 此次复用已有 MySQL 时留空；应用不需要管理员密码 |
| REDIS_URL | 已填写带认证的独立 Redis 连接串，192.168.100.188:6380/0；不占用原业务的 6379 |

应用连接串中的密码已经按安全字符生成，不需要手动拼接。虚拟机 SSH 的账号密码与各数据库应用账号无关，不要将 SSH 密码填进上述字段。

根目录 `compose.yaml` 是从零创建全部依赖的另一套方案；**本虚拟机使用 `deploy/vm/compose.yaml` 补充 MongoDB/Redis，勿在已有服务端口上执行根目录 Compose**。虚拟机执行目录为 `/opt/kb-platform`，部署管理员凭据保存在该目录权限 600 的 `.env`；本地根 `.env` 仅用于应用连接。

## 需要你填写的模型配置

### 必填：聊天、主体识别、HyDE、生成

```dotenv
# 服务商提供的 OpenAI 兼容接口根地址，通常以 /v1 结尾；不是 /chat/completions 完整路径
OPENAI_API_BASE=
OPENAI_API_KEY=
# 服务商实际支持的模型 ID
LLM_DEFAULT_MODEL=
# 可留空，回退到 LLM_DEFAULT_MODEL；也可指定同一服务商的另一模型
ITEM_MODEL=
```

主体识别、问题改写、HyDE 和答案生成主要使用 ITEM_MODEL。LLM_DEFAULT_MODEL 是默认模型；这些文本模型须属于同一个 OPENAI_API_BASE/API_KEY 可调用的服务。图片摘要使用下面独立配置的视觉服务。

### 图片摘要：独立视觉站点

```dotenv
VL_BASE_URL=https://ai.xmiaom.com/v1
VL_API_KEY=
VL_MODEL=deepseek-v4-flash-vision-exp
```

VL_BASE_URL 填 OpenAI 兼容接口根地址，不包含 `/chat/completions`。VL_API_KEY 填此站点的密钥；不会回退到聊天站点的密钥。VL_MODEL 需为该站点实际支持的视觉模型，当前保留已有模型名。含图片的导入若缺少视觉地址、密钥或模型，会明确提示缺项；无图片 Markdown 不需要视觉配置。

### 必填：远程重排与向量模型

```dotenv
RERANK_BASE_URL=https://emrank.tech/v1
RERANK_API_KEY=
RERANK_MODEL=Qwen/Qwen3-Reranker-8B

EMBEDDING_MODEL=Qwen/Qwen3-Embedding-8B
# 留空即复用 RERANK_BASE_URL 和 RERANK_API_KEY
EMBEDDING_BASE_URL=
EMBEDDING_API_KEY=
EMBEDDING_DIMENSIONS=4096
```

两个模型共用 EMRank 站点及网关密钥。向量调用 `/v1/embeddings`，重排调用 `/v1/rerank`，使用 Bearer 认证和 JSON；不再使用 DashScope TextReRank 协议。本地 `.env` 已有的 RERANK_API_KEY 保留，embedding 默认直接复用，无需重复填写。仅在需要单独覆盖时填写 EMBEDDING_BASE_URL/API_KEY。

导入片段、主体名称、问题和 HyDE 均使用远程 Qwen3 Embedding；无需下载 BGE-M3、安装 torch 或 cpu/cuda extra。Qwen3 API 仅返回稠密向量，Milvus 主体与片段集合均按实际返回维度创建，采用 COSINE 稠密向量检索，仍保留主体过滤和后续 rerank。当前使用默认 4096 维；如调整维度，入库与检索必须保持一致。

更换 embedding 模型或维度需在新集合重新导入。已有 BGE 稀疏集合或维度不匹配时，代码明确拒绝复用，不会删除或迁移已有数据。可修改 CHUNKS_COLLECTION 和 ITEM_NAME_COLLECTION 指向新集合；调整 rerank 通常无需重建向量。

### 按使用范围填写

| 配置 | 何时需要 |
| --- | --- |
| VL_BASE_URL / VL_API_KEY / VL_MODEL | 文档含图片且要生成图片摘要时；填写独立视觉站点及其支持的模型 |
| MINERU_TOKEN | 导入 PDF 时必需；无图片 Markdown 基线不需要 |
| MINERU_BASE_URL | 通常保留 https://mineru.net/api/v4，除非使用兼容部署 |
| WEB_SEARCH_ENABLED | 默认 false，可保持 |
| MCP_DASHSCOPE_BASE_URL / MCP_API_KEY | 只有主动开启联网搜索时才填写，并安装 web-search extra |

最小真实 Markdown 问答链路需要：存储已通、聊天接口/模型已填、EMRank embedding 与 rerank 可调用。PDF 和图片验证额外需要相应配置。

## 可以保留的本地设置

APP_HOST=127.0.0.1、IMPORT_PORT=8100、QUERY_PORT=8101、DATA_DIR、上传大小、超时和集合名可以先保留。本地 API 和浏览器仍在 Windows，不要把 APP_HOST 改成虚拟机 IP。

编辑后重启两个 Python 服务，配置在进程启动时加载：

```powershell
.\scripts\start.ps1 import
# 另一个终端
.\scripts\start.ps1 query
```

检查命令：

```powershell
.venv\Scripts\python.exe scripts/doctor.py
.venv\Scripts\python.exe scripts/verify_storage.py
.venv\Scripts\python.exe scripts/verify_baseline.py
```

`verify_storage.py` 验证真实存储协议与项目数据读写；其中 MongoDB 的两条标记记录仅为存储探针，绝不是模型生成答案。完整 RAG 成功仍以 verify_baseline 的真实结果为准。
