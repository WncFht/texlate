# Agent 维护体系

本目录保存随仓分发的维护技能、共享参考、模板和 Agent Notes。来源与适配范围见[来源与取舍](来源与取舍.md)，MIT 许可见 [AGENT-MAINTENANCE-LICENSE](AGENT-MAINTENANCE-LICENSE)。

## 入口

- [maintain-docs](skills/maintain-docs/SKILL.md)：文档归属、事实核验与示例验证。
- [maintain-prose](skills/maintain-prose/SKILL.md)：正文、注释和诊断的语义完整性。
- [maintain-decision-notes](skills/maintain-decision-notes/SKILL.md)：长期理由与[记录生命周期](notes/README.md)。
- [维护检查](references/automation.md)：暂存快照、调度和可信历史比较的边界。

## 本地接线与验证

在仓库根执行 `uv sync`、`npm ci`，按根 `AGENTS.md` 安装既有格式化工具，然后运行：

```sh
bash scripts/agent-links.sh
pre-commit install --hook-type pre-commit --hook-type pre-push
uv run --no-sync python scripts/run_checks.py --config scripts/checks.json --mode ci
```

`docs` 模式检查技能、当前文档链接、Notes 与封存历史；`test` 模式运行维护工具的行为测试；`ci` 模式合并两者。此处的 `ci` 只代表维护检查集合，产品测试、类型检查和构建仍使用现有 CI。提交钩子导出完整 index 快照，防止未暂存修复掩盖待提交的断链；推送钩子运行维护检查，不强制本地重跑整个产品矩阵。

文档链接检查覆盖根入口、隐藏规则目录和全部研究报告，仅跳过依赖、本机目录、临时实验及 Notes 的 `archived/`。`tools/docs_linkcheck.py` 检查完整 `docs/` 的本地文件链接，并验证各页面能从统一 README 导航到达；不要求每个子目录再设索引。封存 Notes 的字节与历史由专用检查器保护，普通研究报告没有整目录冻结豁免。

封存保护包括当前哈希检查和可信历史比较。CI 在 PR 上从目标分支读取检查器；首次接入时目标分支尚无检查器，明确跳过这一额外检查，合入工具链基线后才具备该保护。远端是否将此 job 设为 required check 需在 GitHub 分支规则中另行核验。
