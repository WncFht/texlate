# Pi agent 多 agent 能力对照调研

> **结论**：Pi 能配出 Claude Code 五项多 agent 功能中的 4/5（subagents、Workflow 编排、skills 原生、hooks 以事件替代）；配不出的是跨会话信箱/共享任务表，agent teams 只有 tmux+fleet-view 近似。Pi 的多 agent 是扩展生态而非内核功能。
> **状态**：时点证据（2026-09-14 口径）
> **日期**：2026-09-14

问题：pi（`earendil-works/pi`）能否配置出 Claude Code 的五项多 agent 功能（subagents / agent teams / 跨会话消息 / Workflow 编排 / skills→subagent）？方法：pi 0.85.1 实查（自带 docs/ + examples/）+ 网络调研（GitHub/npm/官方博客）。

## 0. Pi 是什么、现状

- 身份：**Pi** = "minimal terminal coding harness"，站 pi.dev；仓库 `github.com/earendil-works/pi`（原 `badlogic/pi-mono` 重定向至此），**105k★**，日更。维护者含 `badlogic`（Mario Zechner）与 `mitsuhiko`（Armin Ronacher）[^pi]。
- npm：`@mariozechner/pi-coding-agent` 已弃于 0.73.1；现行 **`@earendil-works/pi-coding-agent`**（调研时点最新 0.85.1，2026-09-05 发布）。
- monorepo 包：`pi-ai`（统一 provider API，~30 provider）、`pi-agent-core`（agent loop）、`pi-tui`、`pi-coding-agent`（CLI）、`chord`（组合运行时）、`pi-telemetry`。
- **核心哲学：极简内核，一切靠扩展**。原生**没有** subagent、MCP、plan mode、权限系统、todo、后台 bash——全是扩展的活。Mario 博客甚至把隐藏子 agent 叫「black box within a black box」，他本人用 `/`命令 + `pi --print` 子进程的模式。
- 配置目录：`$HOME/.pi/agent/`（settings.json/models.json/auth.json/sessions/）；`pi list` 列已装扩展。

## 1. 架构速览

- **模式**：交互 TUI / `pi -p` headless / `--mode json`（JSONL 事件流）/ `--mode rpc`（stdio JSONL 命令）/ SDK 嵌入。
- **扩展**：TS 模块，jiti 加载，来自 `$HOME/.pi/agent/extensions/`、`.pi/extensions/`（项目信任后）、`pi install npm:/git:` 包。工厂函数拿 `ExtensionAPI`：`registerTool` / `registerCommand` / `registerFlag` / `registerProvider` / `sendMessage(deliverAs: steer|followUp|nextTurn)` / `appendEntry` / `setActiveTools` + ~30 事件（`session_start`/`before_agent_start`/`tool_call` 可 block/`project_trust`/…）。`ctx.ui` 提供 TUI 组件；`ctx.newSession()/fork()`；`modelRegistry.streamSimple()` 可做嵌套 LLM 调用。`/reload` 热重载。
- **会话**：JSONL 树（`id`/`parentId`），`/tree` 原地分支、`/fork`、`--fork`、`-c/-r`、自动 compaction。`docs/session-format.md`。
- **上下文文件**：`AGENTS.md`/`CLAUDE.md`（全局 + 祖先+cwd）、`AGENTS.override.md`、`SYSTEM.md`/`APPEND_SYSTEM.md`。
- **RPC**：`pi --mode rpc`，stdio 上严格 LF 分隔 JSONL；命令面很全（`prompt`/`steer`/`follow_up`/`new_session`/`switch_session`/`fork`/`clone`/`get_entries(since 游标)`/`get_state`/`bash`…）——但**一个 spawned 进程一条管道**，无会话寻址。

## 2. 逐项对照：CC 五功能 → Pi

| CC 功能       | Pi 等价物                                                                                                  | 状态            |
| ------------- | ---------------------------------------------------------------------------------------------------------- | --------------- |
| Subagents     | 官方示例扩展 `examples/extensions/subagent/` + 社区 `@tintinweb/pi-subagents` / `pi-subagents`(nicobailon) | ✅ 可配，非原生 |
| Agent teams   | 无原语；tmux 多 pane + `pi-chat` 文件快照模式                                                              | ⚠️ 近似         |
| 跨会话消息    | 无 SendMessage；RPC 每进程一管；`chord` 对称 peer 未发布                                                   | ❌ 需自建       |
| Workflow 编排 | `SubagentWorkflow`（跑 CC workflow 脚本）/ SDK 自建                                                        | ✅ 可配         |
| Skills        | **原生** Agent Skills，已扫 `$HOME/.agents/skills/` + `.agents/skills/`                                    | ✅ 原生         |

### 2.1 Subagents —— 三条路

**(a) 官方示例扩展**（发行包自带源码，未启用）：`$PIPKG/examples/extensions/subagent/`

- `index.ts`(1038 行) 注册一个 subagent 工具，每个子 agent = **独立 `pi` 子进程**（隔离上下文窗口）
- 三种模式：`{agent, task}` 单发 / `{tasks:[…]}` 并行（≤8 任务、4 并发）/ `{chain:[…]}` 链式（`{previous}` 占位符）
- agent 定义 = **和 CC 同构的 md+frontmatter**（`name`/`description`/`tools`/`model`；model 省略则继承派发会话模型 + 思考级别）
- 位置：`$HOME/.pi/agent/agents/*.md`（用户级，默认加载）+ `.pi/agents/*.md`（项目级，需 `agentScope:"both"|"project"`，不受信项目会弹确认；`confirmProjectAgents` 可控）
- 附带 workflow prompt 模板：`/implement`（scout→planner→worker）、`/scout-and-plan`、`/implement-and-review`
- 特性：并行流式输出、每 agent turns/tokens/cost/ctx 统计、Ctrl+C 传播杀子进程、每次调用重新发现 agent（可中途改定义）
- 启用方式 = 把发行包内 `examples/extensions/subagent/` 与 `agents/*.md`、`prompts/*.md` 软链/拷进 `$HOME/.pi/agent/` 对应目录（README 给的软链法）。

**(b) `@tintinweb/pi-subagents`**（0.19.0，56 个版本——最贴近 CC 语义）[^tintinweb]：
`pi install npm:@tintinweb/pi-subagents`（需 pi ≥0.84）。提供 **`Agent` 工具** + `get_subagent_result` + `steer_subagent`（**运行中改派！**）+ `SubagentWorkflow`；fleet view（编辑器下方可导航的 agent 列表）、`@agent-<type>` 提及、后台并发池（`maxConcurrent` 10）、嵌套委派（`allowed_subagents`）、**`isolation: worktree` frontmatter**（git worktree 隔离，同 CC）、`persist_session`/`output_transcript`、per-agent `memory`。发现顺序：`.pi/agents/` > `.agents/agents/` > `$HOME/.pi/agent/agents/`——**显式不读 `.claude/agents/`**。

**(c) `pi-subagents`（nicobailon，0.67.0）**：前台子 agent 进程内 + **后台子 agent 走 detached runner 进程**；内建 scout/researcher/worker/reviewer/oracle/delegate；`/subagents-fleet` 检查器（浏览/看 transcript/steer/stop）；missions（持久周期任务）；watchdog reviewer；`maxSubagentSpawnsPerRun` 默认 64；发现 `$HOME/.pi/agent/agents/**/*.md`、`.pi/agents/**/*.md`、`.agents/**/*.md`；per-agent `MEMORY.md`。

**(d) SDK DIY**：`createAgentSession({sessionManager: SessionManager.inMemory(), tools:[…]})` 起独立 in-process session 注册成工具即可，~15 行（`docs/sdk.md` 把「spawn sub-agents」列为官方用例）。

### 2.2 Agent teams —— 无原语

- 官方答案 = tmux 多 pane 跑多个 pi；`pi-chat`（earendil-works 自家）是参考实现：每个 chat channel 一个 pi 会话跑 detached tmux 进程，worker 每 15s 写状态快照到 `$HOME/.pi/agent/chat/worker-status/`，supervisor pi 用 `chat_workers` 工具读——**文件快照，不是真消息**。
- 两个 subagent 扩展的 fleet view + steer 约等于「会话内的 team 面板」，但没有共享任务表原语；pi 惯例是 `TODO.md` 文件或 `pi.appendEntry()` 共享态。

### 2.3 跨会话消息 —— 需自建

- 进程内：`pi.events` 总线、`sendMessage(steer|followUp|nextTurn)`；RPC 侧 `steer`/`follow_up` 命令。
- 进程间：RPC 模式一进程一管道、无多客户端寻址；`chord` 有 remote services/复制状态抽象但对称 peer 只是「planned」。**想要 SendMessage 得自己写编排器**（spawn N 个 `pi --mode rpc` 子进程，自己做信箱路由）——SDK/RPC 命令面足够，缺的是现成品。

### 2.4 Workflow 编排 —— 两条路

- `@tintinweb/pi-subagents` 的 **`SubagentWorkflow`**：`node:vm` 沙箱跑确定性 JS（`agent()`/`parallel()`/`pipeline()`/`phase()`/`export const meta`），**宣称可原样跑 CC 的 Workflow 脚本**；存 `.pi/workflows/`、`--subagents-workflow-file`。
- SDK 自建：`createAgentSession()` 每次调用都是独立 AgentSession（无单例），配 `SessionManager`/`defineTool`/`InlineExtension` 就是进程内编排器；`@agwab/pi-workflow`(0.13.8) 存在但细节未核实。

### 2.5 Skills —— 原生

- 扫描位置：`$HOME/.pi/agent/skills/`、**`$HOME/.agents/skills/`**、`.pi/skills/`、**`.agents/skills/`**（cwd+ 祖先至 git root，需项目信任）、package `skills/`、settings `skills[]`、`--skill`。
- **TeXlate 仓的 `.agents/skills/` 布局 pi 原生支持**；`$HOME/.claude/skills` 不在扫描表，可 settings 里 `{"skills": ["$HOME/.claude/skills"]}` 引入。
- 渐进披露同规范；`/skill:name [args]` 强触发；`allowed-tools`/`disable-model-invocation` 支持。

### 2.6 顺带：其他缺口与对应

- **hooks**：无 hooks 系统，等价物 = 扩展事件（`tool_call` 可 block/`bash-spawn-hook`/`file-trigger`/`confirm-destructive` 示例）。
- **MCP**：非原生（哲学：CLI+README > MCP）；社区 `pi-mcp-adapter`（v2.34 活跃）/`pi-mcp-extension`/`@geohar/pi-mcp-combiner`。
- **provider**：`$HOME/.pi/agent/models.json` 自定义 OpenAI/Anthropic 兼容端点（`$ENV`/`!cmd` 插值）或 `pi.registerProvider()`。
- **其他**：project-trust 系统、`pi-acp`（ACP 协议）、`@ai-sdk/harness-pi`（跑在 Vercel AI-SDK 沙箱里）、社区发行版 `@oh-my-pi/*`、`senpi`。

## 3. 结论

**能配出 4/5**：subagent（官方示例/两个社区扩展，且 agent 定义格式与 CC 同构、支持 worktree 隔离）、workflow（SubagentWorkflow 甚至兼容 CC 脚本语法）、skills（原生）、hooks（事件替代）。
**配不出的**：跨会话信箱/共享任务表（要自建 RPC 编排器或走文件约定）；agent teams 只有 tmux+fleet-view 近似。
**注意**：pi 的多 agent 是「扩展生态」而非内核功能——稳定性、维护、升级兼容性取决于扩展作者（`@tintinweb/pi-subagents` 56 个版本、nicobailon 67 个版本，都算活跃）。若要在 pi 里复刻 CC 体验，`pi install npm:@tintinweb/pi-subagents` 一步到位是最短路径。

### 参考文献

[^pi]: earendil-works. pi — minimal terminal coding harness. GitHub 2026. [github.com/earendil-works/pi](https://github.com/earendil-works/pi)

[^tintinweb]: tintinweb. pi-subagents — Claude Code 语义对齐的 subagent 扩展. npm 2026. [npmjs.com/@tintinweb/pi-subagents](https://www.npmjs.com/package/@tintinweb/pi-subagents)
