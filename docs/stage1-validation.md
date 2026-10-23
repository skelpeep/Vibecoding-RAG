# 阶段一实际验证记录

> 更新：2026-10-21 已在 192.168.100.188 补齐并验证存储，根 .env 已填写。最新结果见 [虚拟机部署记录](vm-deployment.md) 与 [配置填写指南](env-guide.md)；下文缺存储记录属于首次本地基线。

日期：2026-10-21（Asia/Shanghai）。状态：**基座、配置和本地运行基线已交付；真实 RAG 全链路受外部条件阻塞，阶段一未全部通过**。

## 环境

Python 3.12.8、uv 0.12.0、Node 24.19.0、Chrome 155.0.8059.82 可用。RTX 4070 Laptop GPU 可见；torch、FlagEmbedding、BGE-M3 权重未安装。Milvus、MinIO、MongoDB、MySQL、Redis 默认端口均不可达，模型和存储凭据未配置。Docker 引擎启动未持续成功。

证据：[environment.json](evidence/stage1/environment.json)。探测仅执行读取、版本检查与 TCP 连接，未执行破坏性存储操作。

## 已执行检查

| 检查 | 结果与边界 |
| --- | --- |
| uv lock / uv sync --locked | 成功锁定并安装基础环境 94 个包；GPU/CPU extras 未实装 |
| uv pip check | 所有已装依赖兼容 |
| 两个 ASGI app 导入、两条 LangGraph 编译 | 成功，不等同节点运行或模型验证 |
| compileall | 支持的源码与脚本语法检查通过 |
| pytest | 11 项通过；两个上游弃用警告，见 tests.txt |
| Web /health、原 HTML 页面 | 8100 和 8101 均 200；health 明示依赖未检查 |
| 示例 Markdown 真实解析 | 原入口、Markdown 读取、切分节点实际运行，5 个有效非空切片 |
| POST /upload | 200，真实文件写入独立 UUID 目录 |
| 文件备份/完整导入 | failed；MinIO 凭据缺失，在 backup_file 阶段停止 |
| 历史会话 | 503；MongoDB 不可连接，读写成功链路未验证 |
| POST /query 与 SSE | 200；原 LangGraph 开始执行，在历史节点失败，发出 progress/error 并关闭连接 |
| 模型、向量入库、真实检索、流式答案 | 未验证；没有伪模型、伪向量或虚构的成功答案 |
| Compose 配置 | 仅 config --quiet 语法检查；未运行容器 |
| wheel 打包 | 见 checks.txt；原 HTML 与 atguigu.cli 必须包含在 wheel 中 |

真实 HTTP/节点证据：[verification.json](evidence/stage1/verification.json)，`models_mocked=false`、`full_chain_verified=false`。验证脚本故意在未通过完整链路时返回非零状态。

pytest 范围：非法路径、非支持格式、空文件、大小限制及残留清理、同名上传隔离和真实缺配置失败、未知任务、SSE 终止/清理、已有向量不被删除、图编译。SSE 的成功终态和已有向量保护使用局部合成事件/客户端替身，只用于回归检查，不能当真实存储或模型联调。

## 原页面行为与截图

已在真实 Chrome、1440×1000 视口操作文件选择和提问，两个页面没有未捕获 JavaScript 异常。四张截图均已打开人工检查；这是旧页面基线采集，不是阶段三技能设计或跨设备视觉验收。

- [导入初始态](evidence/stage1/import-initial.png)：点击/拖拽区，声明 PDF/MD。
- [导入失败态](evidence/stage1/import-dependency-failure.png)：文件名、大小、节点进度、失败徽标；当前仍显示已开始的节点，错误详情较粗略。
- [问答初始态](evidence/stage1/chat-initial.png)：欢迎语、会话 localStorage、发送和清空对话；health 成功只显示 API 已连接。
- [问答依赖失败态](evidence/stage1/chat-dependency-failure.png)：真实错误可见，输入恢复，SSE 不再无限挂起。

行为与浏览器版本：[browser.json](evidence/stage1/browser.json)。原问答页仍保留“可查询知识库与联网信息”的固定文案，即使联网搜索配置关闭；后续新 UI 应按真实能力显示。原导入页按节点计数估算进度，并不是实际字节/工作量百分比。品牌、布局、代码节点名和这些交互限制均作为回归参考记录。

## 运行中发现并解决的问题

8000 端口被其他程序占用，首轮访问收到其他服务 404；未终止该程序，改为 8100/8101。验证脚本新增 service 身份检查，在发送文件前验证目标确为本项目；本地 HTTP 检查禁用继承代理，避免误走系统代理。本文引用的 JSON 均为改端口后的结果。

原配置空值导致启动异常、缺少启动依赖、固定上传目录、同名文件覆盖、自动公开 MinIO 桶与删除公共图片目录、先删旧向量、MongoClient 布尔判断/索引、PDF 紧循环和固定结果 URL、SSE 永不结束等已做阶段一必要修复。没有创建业务表、没有新增登录权限或 Vue 管理页。

## 下一步

补齐可用的存储地址/凭据、BGE-M3 权重和匹配设备的依赖、聊天/视觉/重排及 MinerU 配置后，重跑 doctor 和真实链路验证；成功证据齐全前保持阶段一“未全部通过”。本轮止于阶段一，不自动启动阶段二。
