# 来源与第三方组件

## 上游基座

本项目基于 [ly03171629/kb_0515](https://gitee.com/ly03171629/kb_0515)，接入提交为 `3af2ccdc91baca389f24feb60ecbd82f3ff5710c`。现有 Git 历史与 `upstream` remote 保留，具体改造记录见 [基座来源](docs/source-baseline.md)。

接入的上游版本未附 LICENSE。本次整理不为上游代码或整个仓库补授新的开源许可；上传源码不等于授予使用、修改和再分发许可。

## 前端资源

- `frontend/src/vendor/taste-charts.js` 来源于项目开发时使用的 design-taste-frontend 技能图表代码，保留来源注释，并包含本项目对孤立观测点的调整。其来源记录不代替许可授权。
- IBM Plex Sans 与 Noto Sans SC 通过对应 `@fontsource` npm 包加载。各包的许可文件随 npm 安装保留。
- Vue、Vite、Element Plus、Lucide、DOMPurify、marked 及其他依赖按各自发行包的许可使用，准确版本见 `frontend/package-lock.json`。
- Python 依赖及准确版本见 `pyproject.toml`、`uv.lock`，各组件按其自身许可使用。

`examples/` 与 `docs/assets/` 中的业务内容是本项目的虚构演示材料，不包含实际企业制度或用户密码。
