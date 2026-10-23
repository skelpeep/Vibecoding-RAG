# GitHub 上传说明

当前目录保留了上游 Git 历史，`upstream` 指向原 Gitee 基座。GitHub 仓库为 [skelpeep/Vibecoding-RAG](https://github.com/skelpeep/Vibecoding-RAG)，本地分支为 `main`，`origin` 指向该仓库。首次整理仅准备文件，随后按用户明确要求配置 GitHub 远程并提交上传。

## 提交范围

| 保留在仓库 | 仅保留本机 |
| --- | --- |
| `atguigu/`、`frontend/src/`、`migrations/`、`tests/`、`scripts/` | `.venv/`、`node_modules/`、Python/测试缓存 |
| `uv.lock`、`frontend/package-lock.json`、构建配置 | `frontend/dist/`、`dist/` 构建产物 |
| `.env.example`、部署模板 | `.env`、账号密码、实际 Redis 配置、私钥 |
| 需求、接口、安装、验收及设计决定文字 | `var/` 上传文件、数据、日志、PID 与本地报告 |
| `docs/assets/` 的两张虚构演示预览 | `docs/evidence/stage*/`、生成的设计截图与检查报告 |

已从索引移除上游 IDE 配置，本机 `.idea/` 仍保留；已有 Python 字节码移除保持不变。原 `src/` 只有两个空 `__init__.py`，打包实际使用 `atguigu`，因此移除了空占位。`atguigu/test/` 是上游教学示例，保留来源；正式回归在根 `tests/`。

## 上传前检查与源码包

```powershell
uv run python scripts/check_repository.py --history
uv run python scripts/check_repository.py --history --archive dist/github-source.zip
```

检查当前 Git 将收录的文件、已知本机凭据值、常见密钥格式、带认证 URL、大文件和历史对象。报告默认写入 `var/reports/github-readiness.json`，只记录文件路径和规则，不输出密码。

`dist/github-source.zip` 是通过检查的纯源码快照，不含 `.git`、运行数据、依赖目录或历史证据；解压后可单独创建仓库。它不是已打包的前端成品，新环境仍需安装和构建。不要把整个工作区直接拖入 GitHub，以免绕开 `.gitignore` 上传本地凭据。

## 当前仓库后续更新

本机已配置 `origin` 与 `main`，后续更新使用：

```powershell
uv run python scripts/check_repository.py --history
git add -A
git diff --cached --stat
git commit -m "Describe the update"
git push origin main
```

## 首次上传到其他仓库

先在 GitHub 创建一个空仓库，不预置 README、LICENSE 或 .gitignore。将下方 `OWNER`、`REPOSITORY` 替换为自己的名称，在本项目根目录运行：

```powershell
git status --short
git add -A
git diff --cached --stat
uv run python scripts/check_repository.py --history
git commit -m "Prepare knowledge platform for GitHub"
git remote add origin https://github.com/OWNER/REPOSITORY.git
git push -u origin HEAD:main
```

上面是其他新仓库的通用示例；本项目当前已有 `origin`，不要重复添加。先用 `git remote -v` 核对目标地址。`upstream` 用于追溯原仓库，保留即可。首次 push 会同时上传当前分支可达的历史，检查脚本的 `--history` 会检查本地所有引用下的历史对象。

GitHub Actions 会执行隔离后端测试和前端构建；真实模型/虚拟机集成验收不在 CI 自动运行，也不需要把 `.env` 放进仓库。本机检查不等于远端 CI 已通过，远端状态以仓库 Actions 页面为准。

含中文的 PowerShell 脚本使用 UTF-8 BOM，兼容 Windows PowerShell 5.1；`.editorconfig`、仓库扫描以及 Windows CI 共同检查编码和解析。不要以“UTF-8 无 BOM”重新保存这些脚本。

## 本次整理验证（2026-10-23）

- Git 将收录的源码约 3.5 MB；依赖、日志、原始证据和生成截图均排除，本机原文件保留。
- 当前文件及 233 个历史 blob 的已知本机密钥/常见密钥格式检查通过；没有 GitHub 单文件大小超限。
- 源码发行包解压到隔离目录，不含 `.env`、账号文件、依赖、原始验收证据；使用已安装的 Python 依赖运行回归，171 passed、4 skipped。
- `npm --prefix frontend run build` 的类型检查和生产构建通过；`uv lock --check`、`uv build` 与发行内容核对通过。
- 新增安装、索引和上传文档的相对链接检查通过。完整清单和检查时间在本机 `var/reports/github-readiness.json`，回归/构建输出在 `var/reports/`。

这些本机验证没有在新的操作系统上重新部署存储或调用模型。首次推送触发的 GitHub Actions 中，前端构建和 Windows 脚本检查通过；后端在安装依赖时发现本机默认镜像与远端官方 PyPI 不一致，触发 `--locked` 检查失败，尚未运行测试。项目现已显式声明官方 PyPI 并重新生成锁文件，后续运行结果以 Actions 页面为准。

## 来源与许可

上游接入版本没有附 LICENSE；没有擅自为整个项目选择 MIT 等许可。来源及前端图表/字体记录见 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)。上传保存源码与决定公开开源许可是两个独立事项。
