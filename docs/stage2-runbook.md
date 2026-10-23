# 阶段二运行与验证

阶段二使用阶段一配置的 MySQL 专用项目库。Windows PowerShell 在项目根目录执行：

先确保存储虚拟机 `192.168.100.188` 已开机，MySQL 3306 可达；虚拟机关闭时 API 进程仍可启动，但 `/ready` 和登录返回 503。

```powershell
uv sync --locked
$env:PYTHONUTF8 = '1'
.venv\Scripts\python.exe scripts/init_stage2.py
.\scripts\start.ps1 platform
```

首次初始化：生成随机 JWT_SECRET 写入被忽略的 `.env`，执行 Alembic 到 0002，新增 7 个示例用户、5 个角色、4 个部门和菜单/操作目录。随机账号密码保存在 `var/setup/stage2-accounts.json`，不输出到日志。当前已完成这些步骤，服务运行在 [http://127.0.0.1:8102/docs](http://127.0.0.1:8102/docs)。

初始化可以重复执行，已有账号的密码、启停、部门、角色关联及已撤销权限不会恢复或覆盖。同名示例编码若属于其他记录则整个种子事务拒绝；权限目录仅补充缺失编码。若本机密码文件丢失，生成的新值不会重置数据库已有账号，请由有权限的管理员重置密码。

| 账号 | 部门 | 示例职责 |
| --- | --- | --- |
| admin | 示例组织 | 系统管理员；组织/角色/菜单、看板操作、独立代查权限 |
| kb_admin | 技术部 | 知识授权管理与后续导入/沉淀操作 |
| alice | 技术部 | 普通用户 + 技术角色 |
| bob | 销售部 | 普通用户 |
| carol | 研发组（技术部下级） | 普通用户；不继承技术部数据授权 |
| disabled_demo | 销售部 | 停用账号，不能登录 |
| no_op_demo | 销售部 | 可登录，无操作权限 |

Swagger 操作：调用 `POST /api/auth/login`，从本机密码文件读取对应密码；将返回 access_token 填入 Authorize。可用 admin 管理组织，以 alice 观察普通用户的 403，或检查未授权知识 ID 得到拒绝列表。本阶段不初始化假知识、向量或运营数据。

迁移和初始化分开使用：

```powershell
.venv\Scripts\python.exe -m alembic upgrade head
.venv\Scripts\python.exe -m alembic check
```

迁移 0001 建立主体结构，0002 增加任务与文件同一所有者约束。MySQL DDL 不具备整批事务回滚；中断时保留现场并检查已执行语句，不在非空库盲目 stamp 或重建。`downgrade base` 会删除业务表，仅供已隔离的验证环境使用，当前项目库未执行降级。验证脚本会在本项目库创建随机前缀的临时表，执行同一迁移 SQL 的升级/降级并只清理这些表。

## 验证命令

```powershell
# 快速回归：SQLite 权限测试 + 原基座替身/协议测试
.venv\Scripts\python.exe -m pytest -q

# 相同权限用例在真实 MySQL 上运行；每例回滚独立测试记录
$env:KB_TEST_MYSQL = '1'
.venv\Scripts\python.exe -m pytest tests/test_stage2.py -q
Remove-Item Env:KB_TEST_MYSQL

# 新库迁移 SQL 验证：仅使用随机前缀的临时表
.venv\Scripts\python.exe scripts/verify_stage2_migrations.py

# 需要本地 platform/import/query 服务已加载新代码
.venv\Scripts\python.exe scripts/verify_stage2_http.py
```

HTTP 验证会以示例账号真实登录，创建一条验证会话，检查所有权后软删除；不改示例密码或授权。测试账号如已被用户修改，应按真实状态调整验证，不能重新初始化覆盖。

本轮三个服务为本地后台开发进程，启动 PID 记录在 `var/logs/server-pids.json`，日志在同目录 `*-stage2.*.log`。终端启动服务可 Ctrl+C 停止。已有 8100/8101 服务已重启，旧数据路由关闭。后续开发入口统一 8102，前端端口计划 5173；需要在 `.env` 的 CORS_ORIGINS 中允许实际前端来源。

## 范围

本阶段未生成新 UI；阶段三接入组织管理前端。知识 CRUD、导入执行器、文件下载、RAG 鉴权、历史/SSE 和 FAQ/看板业务仍在后续阶段。阶段一完整 RAG 尚未验收，独立的远程 embedding/rerank/向量查询通过情况保留原证据。新增任务表不代表持久化 worker 已实现。
