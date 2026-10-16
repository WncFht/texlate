# 贡献指南

环境、测试与格式化操作统一见[开发与验证](docs/dev/development.md)，职责关系见[架构](docs/spec/architecture.md)，命名、注释和测试替换位置见[代码约定](docs/dev/conventions.md)。

修改用户行为时更新 `docs/guide/`，修改跨模块契约时更新 `docs/spec/`；独有的长期理由进入 Agent Notes，实验说明条件与证据。全部材料采用[文档维护契约](docs/MAINTENANCE.md)，不另建 ADR 或波次日志。评测载荷和运行产物在仓外，不提交大文件与凭据。

## 提交与 PR

提交使用英文 Conventional Commits，一个提交聚焦一个逻辑变更，格式产出不混入无关改动。提交前运行所属验证与维护检查；PR 说明触发条件、最终行为、验证结果及未覆盖边界。

CI 覆盖格式、密钥、Python、类型、Shell、跨平台 pytest、fuzz、Web、Zotero 和引擎冒烟。Windows 文件名避开系统保留名；进程、信号和文件锁差异须按平台处理，并由对应测试验证。

发行版本由维护者在发版时同步 `pyproject.toml`、`zotero/package.json` 和 tag，发布工作流检查一致性。Bug 与需求使用 issue 模板；安全问题按 [SECURITY.md](SECURITY.md)报告。
