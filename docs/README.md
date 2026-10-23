# 文档索引

## 使用与维护

| 文档 | 内容 |
| --- | --- |
| [安装与启动](setup.md) | 新机器配置、初始化、登录、日常启动、开发与测试 |
| [GitHub 上传说明](github-upload.md) | 提交范围、检查、源码包与上传命令 |
| [最终交付说明](final-delivery.md) | 原开发环境交付、演示步骤与实际限制 |
| [最终验收](final-validation.md) | 八项需求映射、2026-10-22 验证记录 |
| [后台任务](background-jobs.md) | 持久化任务、租约、重试与独立 worker |
| [基座来源](source-baseline.md) | 上游仓库、接入提交和改造范围 |

## 接口契约

- [认证与组织权限](stage2-api.md)
- [知识维护、版本、导入和授权](stage4-api-contract.md)
- [鉴权问答、会话与 SSE](stage5-api-contract.md)
- [数据看板、FAQ 与知识缺口](stage6-api-contract.md)

## 开发与部署历史

`stage*-runbook.md`、`stage*-validation.md`、`vm-deployment.md`、`env-guide.md` 记录原开发过程及当时环境，涉及历史端口或本机地址。新安装以 [setup.md](setup.md) 为准。

- [各阶段旧入口](history/stage-entries.md)
- [本地验收记录说明](evidence/README.md)：原始截图与探针默认不上传。
- 根目录 `知识库管理平台.md` 是原需求；`流程记忆.md`、`阶段提示词.md` 保存完整开发接续记录。
- `.taste-skill/` 仅保留设计决定与最终评审文字；生成截图、原始测量报告留在本机。
