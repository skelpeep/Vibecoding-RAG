# 基座来源与变更范围

- 来源：https://gitee.com/ly03171629/kb_0515.git
- 来源分支：`master`
- 接入提交：`3af2ccdc91baca389f24feb60ecbd82f3ff5710c`
- 接入日期：2026-10-21（Asia/Shanghai）
- 本地分支：`stage-1`，来源 remote 为 `upstream`。
- 与准备阶段只读分析提交完全相同，没有采用较新代码。
- 开始时目录只有 `知识库管理平台.md`、`流程记忆.md`、`阶段提示词.md`，无 Git 仓库。初始化 Git、fetch 后切换到基座分支，三份文件均保留。
- 已检查项目与 D:、agent_create、vibecoding 父目录，未发现适用的 AGENTS.md；上游源码内也没有 AGENTS.md。

原代码仍可从 `upstream/master` 与完整 Git 历史追溯。阶段一未提交修改，可用 `git diff HEAD` 审阅。上游跟踪的 38 个 Python 缓存文件已从索引移除，缓存目录被忽略；源文件不受影响，历史保留。

## 阶段一必要修复

| 位置 | 修改原因 |
| --- | --- |
| `pyproject.toml` / `uv.lock` | 补充 uvicorn、multipart、requests 等直接依赖；基础环境不强制安装 CUDA、torchvision/torchaudio；CPU/CUDA/MCP extras 按需；修正 CLI 与打包入口 |
| `atguigu/config/config.py` / `.env.example` | 空环境可启动，固定上传/模型路径和服务地址配置化，环境变量优先于 .env |
| `atguigu/web/api/` | 原页面同源托管，独立上传目录、格式/大小/路径检查、明确失败状态与 404、SSE 终态与断开清理；未更换 RAG 核心 |
| `atguigu/web/page/` | 仅将固定 API 地址改为同源；保留原布局、品牌与交互，作为后续 UI 参考 |
| `atguigu/tool/` | BGE 延迟加载、服务超时、MongoClient 布尔判断与索引修复、MinIO 不再自动开放公共读、日志不再启用全局 DEBUG |
| `atguigu/import_process/nodes/` | 同名向量拒绝覆盖；图片按次隔离且不删除旧图片；PDF API/轮询/超时配置化、解压不删除旧目录、校验解压路径；过滤空切片 |
| `atguigu/query_process/nodes/` | 模型调用超时、模型配置生效、联网搜索默认关闭并按需加载依赖；商品识别、HyDE、混合召回、RRF、重排与生成结构仍保留 |
| `scripts/` / `tests/` / `examples/` / `docs/` | 安装启动、环境探测、真实流程检查、截图、针对性回归和交付文档 |

教学 `atguigu/test/`、历史备用节点与 `__main__` 示例中的演示路径保留在源码内，不是支持的服务入口；不要将这些教学示例当作项目启动命令运行。源码中的旧演示图片 URL 也不是本地服务配置。

## 2026-10-23 GitHub 整理

保留上游历史与 `upstream`，不创建提交或推送。上游跟踪的七个 `.idea` 配置从索引移除，本机文件保留。实际包使用 `atguigu`，移除了 `src/` 中两个没有内容和引用的空初始化文件。原 README 阶段入口归档到 `docs/history/stage-entries.md`，新首页和 `docs/setup.md` 描述当前安装方式。

本地密钥、运行数据、依赖、构建及原始验收截图/报告由忽略规则排除；保留设计决定文字和两张虚构演示预览。新增 GitHub CI、仓库扫描与源码快照工具。上游未附 LICENSE，不补授新的项目许可，来源细节见根目录 `THIRD_PARTY_NOTICES.md`。
