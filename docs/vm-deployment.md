# 虚拟机存储部署记录

日期：2026-10-21（Asia/Shanghai）。目标：192.168.100.188，用户授权通过 SSH 部署所需容器。SSH 密码不记录在本文件或仓库。

## 实际拓扑

虚拟机 CentOS 7 / x86_64，4 vCPU，约 3.7 GiB RAM，部署后根卷约 28 GiB 可用。Docker 26.1.4、Compose 2.27.1。Windows 保留 API、原 HTML 和后续 BGE-M3 本地推理，虚拟机只运行存储。

| 服务 | 处理 | 项目连接 |
| --- | --- | --- |
| Milvus 2.5.5 | 复用 milvus-standalone；原 etcd、MinIO 不重建 | 19530；独立 kb_stage1_* 集合，当前无集合数据 |
| MinIO 2024-12-18 | 复用 milvus-minio，新增限定桶的项目账号和私有桶 | 9000；kb-stage1 |
| MySQL 8.0.40 | 复用 sentiment-mysql，新增 kb_platform 数据库与 kb_platform_app 用户，授权仅此库 | 3306；未创建业务表 |
| MongoDB 7.0.18 | 新部署 kb-platform-mongodb-1，已 healthy；独立卷及 readWrite 应用用户 | 27017；kb_stage1，kb_app |
| Redis 7.4 | 新部署 kb-platform-redis-1，已 healthy；认证、AOF、独立卷 | 6380/0，保留其他项目 6379 |

已有电商、PostgreSQL、Redis、Attu 等容器继续运行，未重启或升级已有服务。未清空任何库、桶或集合。MinIO 原全局策略保留，新账号只能访问 kb-stage1 桶。Milvus 复用现有未鉴权配置，本次没有修改其全局认证或网络。

新容器绑定虚拟机 192.168.100.188，限制 MongoDB 768 MiB、Redis 192 MiB，MongoDB 缓存 0.25 GiB；Redis maxmemory 96 MiB。已验证 Windows 能访问，无需修改防火墙。部署后虚拟机可用内存约 1.8 GiB，未使用 swap；正式批量向量工作量仍需压测或增加资源。

## 文件与运行维护

- 仓库配置：`deploy/vm/compose.yaml`、`mongo-init.js`、`.env.example`、`redis.conf.example`。
- 虚拟机实际目录：`/opt/kb-platform`，目录权限 700。
- 虚拟机 `.env` 权限 600，保存新 MongoDB 管理员/应用与 Redis 密码。
- 实际 `redis.conf` 含密码，仅在受保护虚拟机目录下保存。
- 本地应用连接串与专用 MinIO/MySQL 密钥已填入根 `.env`，不输出到日志与仓库。
- 本地 SSH known_hosts 和部署凭据暂存于已忽略的 `var/deploy/`，未记录 SSH 密码。

```sh
cd /opt/kb-platform
docker compose ps
docker compose logs --tail=50 mongodb redis
docker compose up -d
```

本 Compose 只管理两个新增容器；不要在此虚拟机运行仓库根目录的“全量依赖”Compose，以免争用现有端口。不使用 `down -v`，持久化卷需保留。

MySQL 现有服务器全局时区为 +08:00，未修改共享实例。后续 SQLAlchemy 连接应显式设置 session time_zone='+00:00'，保证既定 UTC 存储约定。

## 镜像拉取问题与处理

虚拟机 Docker 的全局代理指向未监听的 127.0.0.1:7897。通过临时 SSH 反向隧道将该端口接入 Windows 现有代理，Docker Hub token 端点仍异常，最终从 `docker.m.daocloud.io/library/mongo:7.0.18` 拉取后本地标记为 `mongo:7.0.18`。

记录的镜像仓库摘要：`sha256:549107a75d6e6fbaad98edaee35df5c80be6c442c01b6676b22fe0d16223214f`。摘要为实际拉取记录，未另作上游签名校验。临时隧道已关闭，没有改写全局 Docker 代理，也没有为拉取重启 Docker；未来新镜像拉取仍需可用代理。

## 验证结果

`scripts/verify_storage.py` 已全部通过：

- Milvus：真实客户端连接、读取服务端版本和集合目录；无假向量，模型向量写入/检索尚未验证。
- MinIO：专用账号将唯一标记文件写入项目桶，再读回逐字节比对。
- MongoDB：应用账号 ping、使用原历史工具插入两条明确标记的非模型测试记录并读取。
- MySQL：应用账号连接目标库，用连接级临时表验证读写，连接关闭后表自动消失。
- Redis：认证 ping，唯一键写入读回，60 秒自动过期。

证据：`docs/evidence/stage1/vm-storage.json`（all_passed=true）、`vm-containers.txt`（健康及资源）、`vm-environment.json`（客户端侧探测）。现有 `environment.json`、`verification.json` 与原页面截图保留为首次无服务基线，不代表部署后的最新状态。

本地 API 已重启加载新 `.env`。`vm-verification.json` 显示真实上传、MinIO 原文件备份、Markdown 读取/切分全部完成；历史接口从 503 恢复 200，可持久化用户提问。流程随后在缺少模型配置的主体识别/问题确认处失败。完整向量入库、召回与模型答案仍保持 full_chain_verified=false。

填写模型配置详见 [env-guide.md](env-guide.md)。本轮完成存储部署，不进入阶段二业务开发。
