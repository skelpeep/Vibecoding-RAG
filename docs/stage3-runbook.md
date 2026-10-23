# 阶段三前端运行说明

当前可用：Vue 管理框架、真实登录/退出、个人资料/密码、用户管理、角色权限、部门管理。知识维护、AI 问答、数据看板与知识沉淀只有按授权显示的未开放入口，业务留阶段四至六。

## 启动

需要 Node.js 22.12+、npm、已初始化的阶段二后端和可连接的 MySQL。当前使用 Windows Node 24、Chrome；后端数据位于既有 VMware 虚拟机，需先开机。无需重新初始化已有账号。

在项目根目录的两个 PowerShell 终端分别执行：

```powershell
.\scripts\start.ps1 platform
```

```powershell
.\scripts\start-frontend.ps1
```

前端脚本在缺少 node_modules 时执行 `npm ci`。也可执行 `npm --prefix frontend ci`、`npm --prefix frontend run dev`。

- 前端：[http://127.0.0.1:5183](http://127.0.0.1:5183)
- 后端：[http://127.0.0.1:8102/docs](http://127.0.0.1:8102/docs)，就绪探针 `/ready`。
- 5183 用于避开本机已有项目的 5173；strictPort 防止启动时静默跳端口。
- 开发请求 `/api` 由 Vite 同源代理至 8102。浏览器不持有数据库或模型密钥。
- 本轮保留前后端开发进程；日志/PID 位于 `var/logs/`。它们不是开机自启或生产服务。

系统管理员为 `admin`，密码在本机被 Git 忽略的 `var/setup/stage2-accounts.json`。其他示例账号沿用阶段二；前端没有写入固定密码或免登录入口。菜单来自当前权限，系统管理员也不会隐式获得所有知识正文访问权。

## 构建与部署边界

```powershell
.\scripts\start-frontend.ps1 build
.\scripts\start-frontend.ps1 preview
```

build 执行 TypeScript/Vue 类型检查和 Vite 构建，产物 `frontend/dist/`；preview 位于 4173，同样代理 `/api`。预览仅用于本地检查。本阶段未部署公网或配置生产反向代理。

生产托管需将 `/api` 转发至统一后端，并将其他前端路径回退到 `index.html`，保证 `/org/users` 等直达路由可用。使用 HTTPS 和组织自己的账号数据。字体包随产物自托管；中文字体按 unicode-range 分片请求，不依赖 Google Fonts 在线服务。

## 工程组织

| 位置 | 作用 |
| --- | --- |
| `frontend/src/api.ts` | 类型化请求、15 秒超时、401/403 与可读错误、日期与数据辅助 |
| `frontend/src/stores/auth.ts` | Pinia 身份、权限定向导航、登录/退出；JWT 存当前标签页 sessionStorage |
| `frontend/src/router.ts` | 懒加载路由、菜单与操作双重检查、失效/拒绝/不可用页面 |
| `frontend/src/components/` | 应用框架、DataTable、FilterBar、MasterDetail、PageHeader、AsyncState、FieldInput、FormDialog、PermissionPicker、头像和标识 |
| `frontend/src/views/` | Login、Profile、Users、Roles、Departments 与共用状态/未开放页面 |
| `frontend/src/style.css` | 单一 token、桌面/平板/手机布局、组件状态 |
| `.taste-skill/` | 方向、seed、设计决策、技能报告、三种宽度截图与评审拼图 |

Element Plus 按需用于对话框、确认及消息；表格、导航、表单字段和权限分组遵循项目视觉。权限选择是菜单/操作配置组件，知识四维授权编辑器尚未实现。

权限在路由进入、窗口重新聚焦/可见及 60 秒周期刷新；每次实际请求仍由后端即时鉴权。按钮隐藏只改善交互，不承担安全边界。资料刷新保留当前未保存编辑；角色权限离开路由或关闭页面有未保存提醒。

## 验证命令

```powershell
$env:PYTHONUTF8 = '1'
.venv\Scripts\python.exe scripts/verify_stage3.py
.venv\Scripts\python.exe scripts/verify_stage3_states.py
.venv\Scripts\python.exe scripts/capture_stage3.py
node C:\Users\fi4h\.codex\skills\design-taste-frontend\scripts\lint.mjs --app frontend/src
node scripts/inspect_stage3.mjs http://127.0.0.1:5183/org/users --out .taste-skill/users
```

浏览器脚本需要 Python Playwright 和已安装 Chrome（本机已具备）。`verify_stage3.py` 会创建带随机 `stage3_qa_` 编码的临时成员、角色、部门，执行真实写入后清理；用户无删除 API，因此仅使用本轮返回的 UUID 和再次核验的随机用户名做定点 SQL 清理，不清空表。测试账号密码随机生成且不记录。现有示例账号的显式退出会按后端规则更新凭证版本。

`verify_stage3_states.py` 不修改组织业务数据；网络故障/延迟仅在验收浏览器中注入。inspect 包装脚本先通过真实登录取得短期 token，再运行原技能 inspector，不修改产品鉴权。可设置 `TASTE_SKILL_PATH` 指向技能目录，`STAGE3_QA_USER` 选择示例账号，`STAGE3_QA_DETAIL=1` 打开角色或部门详情。

验证结果和剩余边界见 [阶段三验收与设计评审](stage3-validation.md)。
