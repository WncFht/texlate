# Agent Notes

Agent Note 保存代码、测试和现有文档不能充分表达的长期理由、真实替代方案、代价及验证要求。相同决策更新原记录，局部机械修改不创建记录。

产品与架构理由按主题合并到 `implemented/architecture/`，维护流程决定在 `implemented/process/`。创建前检索 active 目录，优先更新已有主题；当前契约和操作入口见 [项目文档](../../docs/README.md)。旧 ADR 已归并，来源映射见 [迁移清单](../doc-migration-2026-10-16.json)。

生命周期、分类、中文章节、合并和冻结约束见[记录规范](../references/decision-notes.md)。模板见 [proposed](../templates/proposed.md) 和 [implemented](../templates/implemented.md)。检查命令为仓库根执行 python3 scripts/notes_guard.py --root .；冻结保护还需可信基线。

## 主题入口

- [技术栈与格式边界](implemented/architecture/2026-09-15-技术栈与格式边界.md)
- [解析与校验](implemented/architecture/2026-09-15-解析与校验.md)
- [编译与修复](implemented/architecture/2026-09-15-编译与修复.md)
- [获取与语料](implemented/architecture/2026-09-15-获取与语料.md)
- [翻译协议](implemented/architecture/2026-09-15-翻译协议.md)
- [服务与共享](implemented/architecture/2026-09-15-服务与共享.md)
- [阅读器](implemented/architecture/2026-09-21-阅读器.md)
- [评测账本与资产](implemented/architecture/2026-09-21-评测账本与资产.md)
- [维护体系接入](implemented/process/2026-10-16-维护体系接入.md)与[文档归并](implemented/process/2026-10-16-文档归并.md)
