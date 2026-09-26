# Subagents / Multi-Agent 生态调研

> **结论**：Claude Code 2026 年已把多 agent 原语（subagent→teams→workflow→跨会话消息）补成第一方能力，「要不要装第三方」的答案多数变成「先用内置的」；社区层 superpowers 一家独大，编排框架赛道洗牌很狠。对 TeXlate：开发期用原生 subagent+worktree，运行期翻译管线本质是 asyncio fan-out + evaluator-optimizer，不需要重型框架。
> **状态**：时点证据（2026-09-14 口径；版本号/star 数均为当日近似值）
> **日期**：2026-09-14

调研范围：subagents / multi-agent 相关的 **skill、插件、工具、框架**。分四层：① Claude Code 第一方能力；② 社区 skill/插件/集合；③ 外部编排工具（TUI/GUI/云端）；④ 跨 CLI 与编程框架。文末附对 TeXlate 两层（开发期 / 运行期）的建议。方法：4 个研究 agent 并行调研（官方文档 + GitHub API 核实 star/更新时间）+ 生态摸排；标注「未核实」的条目未能在 GitHub 找到对应仓库。

## 0. TL;DR

- **第一方已经很强**：Claude Code 2026 年密集补齐了多 agent 原语——subagent（v1.0.60）→ agent teams（v2.1.32，实验）→ background agents（v2.1.139）→ **Workflow 脚本编排**（v2.1.150）→ 跨会话 SendMessage（v2.1.224）→ fork 默认化（v2.1.233）。多数「要不要装第三方工具」的问题，答案现在是「先试试内置的」[^cc-docs]。
- **社区 skill 层一家独大**：`obra/superpowers`（~286k★）的 `subagent-driven-development` + `dispatching-parallel-agents` 是事实标准，且已进入官方插件市场[^superpowers]。
- **subagent 定义集合**：`wshobson/agents`（202 agents + 16 orchestrator agents，94 个插件）、`VoltAgent/awesome-claude-code-subagents`（161 个，按目录分类）。
- **编排框架**：`claude-flow` 已更名 **`ruflo`** v3（swarm/MCP 元 harness）；`spec-kit` 达 1.0；`compound-engineering` 在升；`vibe-kanban`/`Crystal`/`Terragon`/`agentapi` 已死或弃用——**这个赛道 2026 年洗牌很狠，选型要看维护状态不看 star**。
- **外部并行会话工具**：Electron「ADE」称霸（Orca 68k★、Superset、Conductor 商业版）；终端党用 `claude-squad`/`ccmanager`；手机监控用 `Happy`。
- **跨 CLI 趋同**：`.xxx/agents/*.md`（md+frontmatter）成事实格式，Cursor 甚至直接读 `.claude/agents/`；Codex 用 TOML 是异类。Agent Skills 开放规范 ~50 个客户端采用；**A2A 协议**赢得 agent↔agent 互操作层（Linux Foundation 托管，v1.0）[^a2a]。
- **对 TeXlate**：开发期推荐 superpowers + 原生 subagent/worktree 隔离；运行期翻译管线本质是 asyncio fan-out + evaluator-optimizer，**不需要重型框架**，真要上选 LangGraph 或 Pydantic AI+Temporal，prompt 优化用 DSPy/GEPA。

## 1. 第一方能力（Claude Code v2.1.270 / Anthropic API）

文档：`code.claude.com/docs/en/sub-agents`、`/agent-teams`、`/cross-session-messaging`、`/workflows`、`/skills`、`/agent-sdk/*`；`platform.claude.com/docs/en/managed-agents/*`[^cc-docs]。

### 1.1 Subagents（`.claude/agents/*.md` + Agent 工具）

**定义**：md + YAML frontmatter，`name`/`description` 必填，body 即 system prompt（不继承主会话 prompt）。发现路径优先级：managed settings → `--agents` CLI JSON → 项目 `.claude/agents/` → 用户级 `.claude/agents/` → 插件 `agents/`（插件子目录产生作用域 ID：`plugin:dir:name`）。文件热加载。

**frontmatter 全字段**（v2.1.270 时点）：

```yaml
name: code-reviewer # 必填；小写 + 连字符；':' 保留给插件作用域
description: 何时用我 # 必填
tools: Read, Grep # allowlist；省略=继承完整池
disallowedTools: Write # denylist，先于 tools 应用
model: sonnet # sonnet|opus|haiku|fable|完整 ID|inherit
permissionMode: default # default|acceptEdits|auto|dontAsk|bypassPermissions|plan
maxTurns: 20 # 超限给部分输出，可 resume
skills: [api-conventions] # 启动时注入 skill 全文
memory: project # user|project|local → .claude/agent-memory/<name>/
background: true # 强制后台
effort: high # low|medium|high|xhigh|max
isolation: worktree # 临时 git worktree，从默认分支拉
color: cyan
initialPrompt: "..." # --agent 整会话模式的首轮输入
experimental: { cacheTtl: 1h }
mcpServers: [...] # 需 folder trust
hooks: { PreToolUse: [...] }
```

**内建**：`Explore`、`Plan`（只读）、`general-purpose`（默认）、`claude`（兜底）、`statusline-setup`、`claude-code-guide`。

**派发方式**：自然语言、`@name` 提及、`claude --agent <name>`（整会话扮演该 agent）、`Agent` 工具。交互会话默认后台运行（fork mode 默认开）；`-p`/SDK 由模型决定除非 `background: true`。后台 subagent 的权限请求会浮到主会话（v2.1.186+），完成时通知。

**fork 语义**：`subagent_type:"fork"` 或 `/subtask` 继承一切（system prompt、工具、模型、全部历史），只回传最终结果。

**恢复**：完成的 subagent 返回 `agentId`；`SendMessage{to:<name|id>}` 后台恢复，保留工具/缓存/历史。transcript 在 `$HOME/.claude/projects/{proj}/{sessionId}/subagents/agent-{id}.jsonl`。

**限制**：嵌套深度 3（`CLAUDE_CODE_MAX_SUBAGENT_SPAWN_DEPTH`）；并发 20（`CLAUDE_CODE_MAX_CONCURRENT_SUBAGENTS`，ultracode 豁免）；描述合计 15k token；模型选择链 invocation → frontmatter → `CLAUDE_CODE_SUBAGENT_MODEL` → 主模型；`CLAUDE_CODE_SUBAGENT_MODEL_FORCE=1` 可强制。subagent 输出会做指令形态净化（v2.1.210+）。

### 1.2 Agent Teams（实验）+ 跨会话消息

**Agent teams**：`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` 开启。一个 lead + N 个 teammate（各自完整 Claude Code 实例、独立上下文窗口）。机制：JSON 信箱 `$HOME/.claude/teams/{team}/inboxes/{agent}.json` + 共享任务表 `$HOME/.claude/tasks/{team}/`（文件锁认领 + 依赖跟踪）。显示：`in-process`（默认 agent 面板）或 tmux/iterm2 分屏（`teammateMode`）。hooks：`TeammateIdle`/`TaskCreated`/`TaskCompleted`（exit 2 = 否决）。subagent 定义可复用为 teammate 类型。限制：单 team、不嵌套、lead 固定、in-process teammate 不可 resume。首版 v2.1.32（2026-02）。

**跨会话消息**（已 GA）：`ListAgents` 发现可达 agent——自己的 subagent、teammate、**本机其他 Claude 会话**（Unix socket + token）、以及 Remote Control 连接时的其他机器/云端会话。`SendMessage` 按名字寻址（`/rename`、`--name`），`notify_when_idle:true` 一次性闲时通知（本机限定）。入站控制 `crossSessionInbound: accept|hold|refuse`；**权限 laundering 被显式封锁**（消息不能批准 prompt、改配置、跑命令）。限速：~1M 字符/条、队列 50、burst 限流。

### 1.3 Workflow / ultracode（脚本化多 agent 编排）

`Workflow` 工具执行 JS 脚本，**确定性**编排几十~几百个 subagent——计划写在脚本里而不是模型脑子里。付费计划 + API + Bedrock 可用，v2.1.150 首版（2026-05）。

```js
export const meta = {
    name: "audit",
    description: "...",
    phases: [{ title: "Scan" }, { title: "Fix" }],
};
phase("Scan");
const files = await agent("list files", { schema: FILES_SCHEMA }); // 结构化输出
const results = await pipeline(files, (f) =>
    agent(`audit ${f}`, { label: f, phase: "Fix" }),
);
return results.filter(Boolean);
```

- `agent(prompt,{label,phase,schema,effort,isolation:'worktree',agentType})` — schema 强制 StructuredOutput（≤5 重试）；失败返回 `null`。
- `pipeline(items,...stages)` 逐项流水线无 barrier（默认）；`parallel(thunks)` 有 barrier；单次 ≤4096 项。
- `phase/log/args/budget/workflow(name,args)`（可嵌套一层）。
- 约束：纯 JS 无 import；`Date.now()/Math.random()` 抛错（resume 安全）；脚本本身不能碰 fs/shell，只有 agent 能干活；并发 `min(16, CPUs-2)`（`CLAUDE_CODE_WORKFLOW_MAX_CONCURRENT_AGENTS` 1–256）；每次 run 上限 1000 agents。
- **Resume**：`resumeFromRunId` 按 journal.jsonl 重放最长未变前缀，失败点之后重跑；fan-out 有 prompt-cache stagger 优化。
- 管理：`/workflows` 查看器（phase 树、per-agent token、暂停/停止/重启/保存）；存 `.claude/workflows/` 或用户级 workflows 目录变 `/name`；插件 `workflows/` 目录分发。规模指引 `workflowSizeGuideline`（默认 medium<15 agents）。
- 触发：`ultracode` 关键词（仅交互输入）、口头要求「用 workflow」、`/effort ultracode`（每个任务都走 workflow）、内置/已存 workflow 名。

### 1.4 Skills 系统的多 agent 通道

- SKILL.md 的 `context: fork` + `agent:` + `background:` 字段可**把 skill 直接派进 subagent**（body 成为该 subagent 的 prompt）——skill 本身就是轻量 subagent 分发器。
- `allowed-tools` 给 turn 级授权（注意：repo 提交的 skill 要审计）。
- Agent Skills 是开放规范（agentskills.io，~50 客户端：Codex/ChatGPT、Cursor、Copilot、Gemini CLI、Goose…）；spec 合法字段只有 name/description/license/compatibility/metadata/allowed-tools——Claude 的 `context`/`hooks`/`argument-hint` 等是**第一方扩展不可移植**[^agentskills]。
- `agents/openai.yaml` 是 **OpenAI Codex 约定**（非规范）：interface/policy/dependencies.tools 元数据。Codex 扫 `.agents/skills/`——TeXlate 仓的 `.agents/skills/` 唯一事实源 + `.claude/skills/` 软链布局正与此兼容。

### 1.5 Claude Agent SDK / Managed Agents / tool_runner

- **Agent SDK**（`@anthropic-ai/claude-agent-sdk` TS、`claude-agent-sdk` Py）：`query()` 异步迭代 SDKMessage；`agents:{name:AgentDefinition{description,prompt,tools,model,skills,memory,mcpServers,maxTurns,background,effort,permissionMode}}` 编程式定义 subagent（覆盖同名文件）；`agentId` 可 resume；`maxBudgetUsd` 预算帽；TS SDK ≥0.3.149 可用 Workflow 工具[^agent-sdk]。
- **tool_runner**（beta）：`client.beta.messages.tool_runner()` 服务端驱动 agentic loop、客户端跑工具——比手写 loop 省事。
- **Managed Agents API**（beta `managed-agents-2026-04-01`）：Anthropic 托管的 REST API——`POST /v1/agents` 定义 agent、environments（云或自托管沙箱）、stateful sessions + SSE 事件流、预算、定时部署、memory stores、vaults、webhooks、MCP tunnels。**多 agent 编排**：`multiagent:{type:"coordinator", agents:[roster]}`——coordinator 派任务给花名册 agent，每个跑在独立 **session thread**（隔离上下文、共享沙箱/文件系统/vaults），上限 25 并发线程，另有 `anthropic.advisor` 咨询线程不占额度。thread 可 list/interrupt/archive；tool 权限请求会跨贴到 primary thread 等你回 `user.tool_confirmation`。定位：SDK=自己跑进程；Managed=Anthropic 托管 agent+ 沙箱（不支持 ZDR/HIPAA）[^managed-agents]。

### 1.6 云端/远程/后台

- **claude.ai/code**（research preview）：`claude --cloud "task"` 起 Anthropic VM 会话（多次调用并行）；`claude -p "msg" --cloud <id>` 向云端会话排队追加；`claude --teleport` 把云会话 + 分支拉回本地终端；`/autofix-pr` 盯 CI/评审评论自动修；routines 定时任务；**Ultrareview**（`/code-review ultra`）= 云端多 agent 评审舰队，独立验证发现，3 次免费后 ~$5–25/次。
- **Remote Control**：`claude remote-control`/`--rc`/`/rc` 把本地会话镜像到 web/手机，全计划可用；ListAgents 借此看到其他机器会话。
- **Background agents**：`claude --bg "prompt"`、`/background`、`/fork`（复制会话到后台）、`claude agents` TUI 管理（attach/logs/stop/respawn）；supervisor daemon 自动 worktree 隔离（`.claude/worktrees/`）、自动 commit/push 不碰 main、~1h 闲置回收。
- **headless** `claude -p`：`--output-format stream-json` + `--json-schema`、`--forward-subagent-text`、`--bare`（CI 推荐，跳过 hooks/skills/CLAUDE.md）、`--agents <json>`、`--permission-mode auto`；`-p` 会话绑信箱 socket（能收跨会话消息）。
- **GitHub Action**：`anthropics/claude-code-action@v1`——`@claude` mention / issue 指派 / cron prompt，跑自己的 runner，API/Bedrock/Vertex/Foundry[^cc-action]。

### 1.7 时间线（首版版本号）

| 功能                                                            | 版本              | 时间       |
| --------------------------------------------------------------- | ----------------- | ---------- |
| 自定义 subagents                                                | v1.0.60           | 2025-07    |
| Agent SDK 更名                                                  | —                 | 2025-09    |
| 插件 / Skills                                                   | v2.0.12 / v2.0.20 | 2025-10    |
| web→CLI teleport、bg agents                                     | v2.0.24/60        | 2025 末    |
| `context:fork` skills、Ctrl+B、`/teleport`                      | v2.1.0            | 2026 初    |
| **Agent teams**（实验）                                         | v2.1.32           | 2026-02    |
| `isolation:worktree`                                            | v2.1.49           | 2026-02    |
| Remote Control                                                  | v2.1.51           | 2026-02    |
| Routines 定时                                                   | v2.1.105          | 2026-04    |
| Ultrareview                                                     | v2.1.114          | 2026-04    |
| `claude agents` + `--bg` 生态                                   | v2.1.139          | 2026-05    |
| **Workflow 编排**                                               | v2.1.150          | 2026-05    |
| 嵌套深度 5→3、bg 权限浮窗、subagent 默认后台                    | v2.1.166–201      | 2026-06/07 |
| `/subtask` fork、ultracode effort                               | v2.1.212/203      | 2026-07    |
| **跨会话消息**、fork 默认、`@` 提及                             | v2.1.224–233      | 2026-08    |
| `SUBAGENT_MODEL_FORCE`、workflow 并发 env、`claude plugin eval` | v2.1.257/269      | 2026-09    |

**2026 原语收敛**：一个 `SendMessage` 通吃 subagent-resume/teammate/跨会话；`Agent` 工具 + `name` + teams flag 决定 subagent vs teammate；subagent 定义可当 teammate 类型；workflow 复用同一套 subagent 注册表/权限/worktree/cache 语义。

## 2. 社区生态（skill / 插件 / 集合）

### 2.1 目录与 awesome 清单

| 仓库                                          | ★     | 状态        | 说明                                                                                         |
| --------------------------------------------- | ----- | ----------- | -------------------------------------------------------------------------------------------- |
| `hesreallyhim/awesome-claude-code`            | 54k   | 当日活跃    | 旗舰目录：skill/subagent/命令/hook/statusline/插件，CSV 驱动 + 脚本生成 README，**首选索引** |
| `ComposioHQ/awesome-claude-skills`            | 75k   | 2026-08     | 「1000+ skills」，含自家 Composio 引流子树——广而不精                                         |
| `travisvn/awesome-claude-skills`              | 15.1k | ~4.5 月未动 | 编辑质量好（有 Skills vs Subagents vs MCP 对比表），但在变陈                                 |
| `VoltAgent/awesome-claude-code-subagents`     | 25.1k | 当日活跃    | ~161 个 subagent 定义，10 个分类目录含「Meta & Orchestration」；每类是可装插件               |
| `davila7/claude-code-templates`（aitmpl.com） | 30.7k | 当日活跃    | `npx claude-code-templates`，100+ 组件（agents/commands/MCPs/hooks/skills），聚合器          |
| `ccplugins/awesome-claude-code-plugins`       | 0.9k  | 2026-08     | 清单 + 市场二合一，claudecodeplugins.dev                                                     |
| `anthropics/claude-plugins-official`          | 36.3k | 当日活跃    | 官方市场（276 插件），另有 `claude-community` 市场[^plugins]                                 |

### 2.2 Subagent 定义集合

| 仓库                                                  | ★     | 更新           | 规模                                                                                                                                         | 判定                                                  |
| ----------------------------------------------------- | ----- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------- |
| `wshobson/agents`                                     | 39.6k | 当日           | **202 agents + 183 skills + 105 commands + 16 orchestrator agents**，94 个插件，多 harness（CC/Codex/Cursor/OpenCode/Copilot），分层模型路由 | 事实标准库，`/plugin marketplace add wshobson/agents` |
| `VoltAgent/awesome-claude-code-subagents`             | 25.1k | 当日           | 161 agents/10 类                                                                                                                             | 组织最好的纯 subagent 集                              |
| `contains-studio/agents`                              | 12.4k | **停更 1 年+** | 37 agents 按「公司部门」组织，500 词 persona                                                                                                 | 理念有启发，别当依赖                                  |
| `davepoon/buildwithclaude`（原 subagents-collection） | 3.4k  | 当日           | 117 agents/51 插件                                                                                                                           | 活跃聚合站                                            |
| `0xfurai/claude-code-subagents`                       | 1.0k  | 停更 ~11 月    | 100+                                                                                                                                         | 休眠                                                  |
| `Dlaby23/claude-agents-ultimate-collection`           | 5     | —              | 798 个（12 库去重合并）                                                                                                                      | 大而糙，未审                                          |

### 2.3 编排框架（跑在 Claude Code 上/里）

| 项目                                              | ★          | 更新             | 形态                                                                                                                                              | 判定                                                                             |
| ------------------------------------------------- | ---------- | ---------------- | ------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------- |
| `obra/superpowers`                                | **286.5k** | 2 天前           | skill 框架 + 方法论：brainstorm→worktree→plan→**subagent-driven-development**（每任务一个新 subagent+ 两阶段评审）→TDD→评审；「强制工作流非建议」 | **事实标准**，官方市场可装 `/plugin install superpowers@claude-plugins-official` |
| `ruvnet/ruflo`（原 claude-flow）                  | 72.4k      | 当日             | agent 元 harness：swarm 拓扑（hierarchical/mesh/queen-led）、~210–314 MCP 工具、AgentDB 向量记忆、跨机 federation、35 插件（含 ruflo-sparc）      | 最激进；README 性能数字是厂商自报，审慎评估                                      |
| `bmad-code-org/BMAD-METHOD`                       | 53k        | 当日             | 敏捷方法论 + 角色 agent（PO/架构/UX/dev/test）结构化流程 + 质量门                                                                                 | 流程重的成熟方案                                                                 |
| `github/spec-kit`                                 | 136.6k     | 2 天前，**v1.0** | spec 驱动：`specify` CLI 生成 constitution→specify→plan→tasks→implement 斜杠命令，30+ harness                                                     | 不是 subagent 框架，但是编排器上游的主流 spec 管线                               |
| `EveryInc/compound-engineering-plugin`            | 25.1k      | 当日             | 35 skills 复利循环：`/ce-brainstorm→plan→work→simplify→review→compound`，经验沉淀 `docs/solutions/`                                               | 理念最新颖（让下次开发更省），上升期                                             |
| `eyaltoledano/claude-task-master`                 | 28.1k      | ~4.5 月          | PRD→依赖任务图 MCP，`task-master next` 驱动                                                                                                       | 验证过但维护放缓                                                                 |
| `buildermethods/agent-os`                         | 5.4k       | 2026-08          | 代码库「标准」提取+spec 塑形                                                                                                                      | 小众 spec-craft                                                                  |
| `BeehiveInnovations/pal-mcp-server`（原 zen-mcp） | 11.7k      | **停更 9 月**    | MCP server 起 `claude`/`codex`/`gemini` CLI 当 subagent（隔离上下文、只回结果）、多模型共识                                                       | 跨 CLI 编排的成熟实现，但没人维护了                                              |

### 2.4 专门教 multi-agent 的 skill

- **`superpowers` 的 `dispatching-parallel-agents` + `subagent-driven-development`**——orchestrator-worker 模式的参考实现，已核实存在于其 `skills/`。
- **`shinpr/sub-agents-skills`**（86★，MIT）——把**跨 LLM** 派发打包成 Agent Skills：Claude Code → Codex/Grok/GLM/Kimi/Gemini。
- **wshobson/agents 的 16 个 orchestrator agents**——普通 `.claude/agents/*.md` 形式编排其他 agent。
- 独立的「swarm skill」很少——该模式主要活在框架里（ruflo/superpowers/compound-engineering）。

## 3. 外部编排工具

### 3.1 终端 TUI（tmux/PTY + worktree）

| 工具                           | ★          | 机制                | 说明                                                                                                                                     |
| ------------------------------ | ---------- | ------------------- | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `smtg-ai/claude-squad`（`cs`） | 8.5k, AGPL | tmux+worktree+TUI   | 元老级并行会话面板：attach/diff 审阅/checkout/pause/yolo 模式；支持 CC/Codex/Gemini/Aider/OpenCode/Amp/任意 CLI                          |
| `kbwo/ccmanager`               | 1.2k, MIT  | **PTY 不依赖 tmux** | Ink TUI；per-CLI 状态检测（idle/busy/waiting）；支持 Kimi/MiniMax；worktree include、崩溃恢复、devcontainer                              |
| `Jedward23/Tmux-Orchestrator`  | 1.8k       | tmux send-keys 脚本 | Orchestrator→PM→Engineer 三级 + `send-claude-message.sh`；本质是 README+ 脚本，轻维护但影响大                                            |
| `amantus-ai/vibetunnel`        | 4.7k       | node-pty→浏览器     | 把终端代理进浏览器，任何设备监控/接管；Tailscale 远程；不是编排器但是好搭档                                                              |
| 其他                           | —          | —                   | `yohey-w/multi-agent-shogun`(1.4k 分层)、`claude_code_agent_farm`(917★ 20+agent 锁协调)、`mixpeek/amux`(Rust)、`agent-deck`(883★ 多 CLI) |

### 3.2 桌面 GUI / ADE（Agentic Development Environment）

| 工具                                   | ★/价格                 | 说明                                                                                                                                                     |
| -------------------------------------- | ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `stablyai/orca`                        | **68.3k**, MIT         | 品类第一：Electron ADE，一 prompt fan-out 多 agent 各居 worktree；SSH 远程 worktree；移动伴侣 app；~20 具名 agent+ 任意 CLI；`orca serve` headless；日更 |
| `winfunc/opcode`（原 claudia）         | 22.4k, AGPL            | Tauri GUI **专为 CC**：会话/项目浏览、自定义 CC Agents、用量成本分析、MCP 管理、checkpoint fork+diff                                                     |
| `superset-sh/superset`                 | 14.2k, Elastic License | 「并行编排 100+ agent」IDE：worktree/agent、diff 查看、端口检测、定时 automations、CLI+TS SDK+MCP server（agent 可以自己开 workspace）                   |
| Conductor（conductor.build）           | 免费/$50/$60 每席      | Melty Labs 商业版，macOS；并行 CC/Codex/Cursor + diff 审阅合并；Pro 有云时长/多人协作/API                                                                |
| `BloopAI/vibe-kanban`                  | 28.1k                  | **公司 2026-04 倒闭**，转社区维护纯本地版；Rust+web 看板编排 10+ CLI agent，worktree+diff 评论回喂 agent                                                 |
| `stravu/crystal`→`Nimbalyst/nimbalyst` | 3.1k→1.7k              | Crystal 2026-02 弃用；Nimbalyst：CC/Codex/OpenCode 工作区 + 富文本编辑器+iOS 伴侣                                                                        |
| 其他                                   | —                      | `cc-haha`(14.4k)、`openchamber`(9.9k 围 OpenCode)、`supacode`、`dmux`、`parallel-code`(1k，「AI Arena」双 agent 对跑+QR 手机监控)                        |

### 3.3 云端 / 远程 runner

| 工具                            | 状态                | 说明                                                                                         |
| ------------------------------- | ------------------- | -------------------------------------------------------------------------------------------- |
| **claude.ai/code**（第一方）    | research preview    | 见 §1.6——`--cloud`/`--teleport`/auto-fix/routines 已吃掉大半第三方云 runner 的地盘           |
| `slopus/happy`                  | 23.8k，活跃         | 手机/web 控制 CC+Codex：E2E 加密 relay、权限请求推送、实时语音；iOS/Android/macOS/web        |
| `coder/agentapi`                | **2026-09-13 归档** | HTTP API 包任意 agent CLI（PTY 模拟）；已转去 Coder Agents                                   |
| Terragon                        | **已关停**          | YC 云 agent 服务，官网只剩 shutdown 页                                                       |
| `anthropics/claude-code-action` | 8.9k，v1.0          | 官方 GitHub Action：`@claude` mention/issue 指派/cron                                        |
| `OpenHands/openhands`           | 87.9k               | 自托管控制中心 + 商业云，agent-agnostic（ACP 接 CC/Codex/Gemini）；claude.ai/code 的开源对位 |
| `alexei-led/ccgram`             | 265★                | Telegram↔tmux 桥，手机遥控                                                                   |

### 3.4 元 harness / agent-agnostic

| 工具                                           | ★         | 说明                                                                                                                                                                                          |
| ---------------------------------------------- | --------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `ruvnet/ruflo`                                 | 72.4k     | 见 §2.3——MCP+hook+ 插件跑在 CC/Codex **内部**                                                                                                                                                 |
| `Yeachan-Heo/oh-my-claudecode`                 | 39.2k     | 插件+`omc` CLI：`/team` 管线直接架在 CC 原生 agent teams（`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`）上 + tmux 窗格 worker（codex/gemini/grok/cursor-agent），19 专家 agent、通知、限流 daemon |
| `musistudio/claude-code-router`                | 37.2k     | 模型网关/控制面（多 provider 路由、failover、配额），**不是会话编排器**，常垫在下面                                                                                                           |
| `Untrivial-ai/agent-orchestrator`              | 12k       | 桌面 app+daemon 监督 27 种 agent 从 plan 到 merge；worktree、看板、PR/CI 反馈回喂                                                                                                             |
| `automazeio/ccpm`                              | 8.4k      | GitHub Issues+worktree 并行执行的项目管理 skill 体系                                                                                                                                          |
| `max-sixty/worktrunk`、`kunchenguid/treehouse` | 7.6k/1.7k | 纯 worktree 管理 CLI——并行 agent 流的 plumbing                                                                                                                                                |

## 4. 跨 CLI subagent 支持 + 编程框架

### 4.1 其他 coding CLI 的 subagent 能力

格式趋同：md+frontmatter 在 `.xxx/agents/`；Codex 独走 TOML。

| CLI                                   | subagent             | 格式                                                                                                                        | 内建                                             | 互操作                                                                                                  |
| ------------------------------------- | -------------------- | --------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------ | ------------------------------------------------------------------------------------------------------- |
| **Codex CLI**（124k★）                | ✅ 2026 新功能       | TOML `.codex/agents/`（`name`/`description`/`developer_instructions`/`model`/`sandbox_mode`/`mcp_servers`/`skills.config`） | default/worker/explorer                          | 显式设计并行 spawn-合并；`codex exec` 非交互 + Python SDK；AGENTS.md 原生；支持 Agent Skills            |
| **Gemini CLI**（107k★）               | ✅ 最像 CC           | md `.gemini/agents/`（`kind:local\|remote`、`tools`通配、`max_turns`、`timeout_mins`）                                      | codebase_investigator/generalist/browser_agent   | **`kind:remote` 走 A2A Agent Card——唯一原生外派 agent 的 CLI**；`/agents` 管理、`@name` 强派            |
| **opencode**                          | ✅                   | md `.opencode/agents/` + `opencode.json`（`mode:primary\|subagent\|all`）                                                   | build/plan/general/explore/scout                 | `permission.task` 可白名单允许调哪些 subagent；读 `CLAUDE.md`+用户级 skills，**不读 `.claude/agents/`** |
| **Cursor**                            | ✅                   | md `.cursor/agents/`                                                                                                        | Explore/Bash/Browser                             | **直接读 `.claude/agents/` 和 `.codex/agents/`**——最兼容的消费者；Task fan-out + worktree/云 VM 隔离    |
| **Amp**                               | ✅                   | 插件定义                                                                                                                    | Search/Oracle/Librarian/ReadThread + Puck 协调器 | 子 agent 互相隔离只回最终摘要                                                                           |
| **Kimi Code**（7.4k★，替代 kimi-cli） | ✅ 内建              | —                                                                                                                           | coder/explore/plan                               | 自定义 subagent 支持**未核实**；ACP 支持                                                                |
| **Crush**（28k★）                     | ❌ 无文档化 subagent | —                                                                                                                           | —                                                | 多会话 + 共享 workspace（`crush serve`）                                                                |
| **Aider**                             | ❌ 无通用 subagent   | CLI flags                                                                                                                   | architect→editor 两段式                          | planner/executor 固定双角色                                                                             |

**两个跨工具标准**：

- **AGENTS.md**——Linux Foundation Agentic AI Foundation 托管，60k+ 项目；**不含 subagent 语义**（纯上下文文件，就近原则）。
- **Agent Skills**（agentskills.io）——`SKILL.md` 跨工具标准，~50 客户端；TeXlate 仓 `.agents/skills/`+`agents/openai.yaml` 布局正确（Codex 约定）[^agentskills]。

**CC 互操**：CC 经 Bash 驱动 `codex exec`/`gemini -p`/`kimi`（通用 CLI 组合）；反向消费靠 MCP 或 A2A 桥。文件级复用朝 CC 约定收敛（Cursor 读 `.claude/agents/`）。

### 4.2 编程式多 agent 框架（跑在自己代码里）

对照场景：**批量文档翻译管线**——段落 fan-out、map-reduce、评审 loop。

| 框架                          | 语言             | ★/成熟度           | 模型                                                                           | 翻译管线适配                                                                    |
| ----------------------------- | ---------------- | ------------------ | ------------------------------------------------------------------------------ | ------------------------------------------------------------------------------- |
| **LangGraph**                 | Py/JS            | 41.6k 生产级       | StateGraph 节点/边；Subagents(supervisor)/Handoffs/Router；Deep Agents harness | **综合最强**：持久执行、checkpoint/resume、HITL——段落并行节点 + 评审条件环      |
| **CrewAI**                    | Py               | 58.5k              | Flows（事件驱动）编排 Crews（角色 agent）                                      | Flow 循环文档；translator+terminologist+reviewer crew                           |
| **Microsoft Agent Framework** | Py/.NET/Go       | 13.5k              | Agent + graph Workflows + checkpoint + YAML 声明式                             | **取代 AutoGen+SK**；.NET/Azure 店选                                            |
| **AutoGen**                   | Py/.NET          | 61k 但**维护模式** | v0.4 分层                                                                      | 新项目别用，迁 MAF                                                              |
| **AG2**                       | Py               | 4.9k               | AutoGen fork；v1.0 protocol-driven Network                                     | 小众                                                                            |
| **OpenAI Agents SDK**         | Py/JS            | 29.4k              | agents+handoffs+agents-as-tools+guardrails+sessions+tracing                    | **最轻够用**：translator→reviewer handoff、guardrails 做术语/长度校验；100+ LLM |
| **Google ADK**                | Py/TS/Go/Java/Kt | 2.0 GA             | Sequential/Parallel/Loop agents + A2A expose/consume                           | ParallelAgent 天然段落 fan-out；GCP 部署选                                      |
| **Pydantic AI**               | Py               | 成熟               | 类型化 Agent+graph+SubAgents+**Temporal/DBOS/Prefect/Restate durable**         | 长批量任务首选之一：结构化输出 schema + 崩溃恢复                                |
| **smolagents**                | Py               | 29.3k              | CodeAgent（LLM 写代码当动作）/ToolCallingAgent；managed agents 层级            | 轻量可 hack；要写代码得配沙箱                                                   |
| **DSPy**                      | Py               | 38k                | 不是 agent 框架——声明式 LM 程序 + 优化器（GEPA/MIPRO）                         | **互补品**：离线优化翻译/评审 prompt，编译后嵌进任何框架                        |
| `llm` CLI（simonw）           | Py/CLI           | 成熟               | 单节点 + 插件+schema+SQLite 日志                                               | Unix 式组合，脚本化小管线                                                       |
| Vercel AI SDK                 | TS               | —                  | 多步 agent+tool calling                                                        | TS 管线默认选（2026 细节未核实）                                                |

**Anthropic 原生模式**：Agent SDK `agents` 参数本身就是编程式多 agent 底座（background 默认、并发 20、深度 3、`maxBudgetUsd`、SendMessage 互发、可嵌套）；大批量用 Workflow 工具。设计词汇表仍是 _Building effective agents_ 五式：**prompt chaining / routing / parallelization(sectioning|voting) / orchestrator-workers / evaluator-optimizer**——后两式正好对应翻译→评审结构[^building-agents]。

**协议层**：MCP 赢 agent↔tool（无争议）；**A2A 赢 agent↔agent**——Google 捐给 LF Agentic AI Foundation，2026-08 v1.0，Py/JS/Java/Go/.NET/Rust SDK，steering committee 含 AWS/MS/Salesforce/SAP/Cisco/IBM；Gemini CLI remote subagent、ADK expose/consume、Amp、AG2 v1.0 都指向它。ANP 未成主流[^a2a]。

## 5. 对 TeXlate 的建议

### 5.1 开发期（写代码时的多 agent）

1. **subagent 隔离干活**：`.claude/agents/` 定义项目专属 agent（如 `latex-parser`、`fixloop-tester`、`bench-runner`），配 `isolation: worktree` 并行改不同模块互不打架；`memory: project` 让 fixloop 规则沉淀跨会话累积。
2. **superpowers 插件**：`subagent-driven-development` + `dispatching-parallel-agents` 直接对应「模块多、相互独立」的实施期；已进官方市场：`/plugin install superpowers@claude-plugins-official`。
3. **大批量 bench 重跑**：语料端到端验证适合 Workflow——`pipeline(corpus, p => agent(translate-and-validate p, {schema: RESULT}))`，结构化收结果、journal resume 断点续跑、prompt-cache stagger 省前缀。
4. **跨 CLI 复用**：若要 Codex/Kimi 也能用，agent 定义放 `.claude/agents/` 会被 Cursor 读到、但 Codex 要 TOML `.codex/agents/`、opencode 不读——TeXlate 仓三 CLI 共用层只有 `.agents/skills/` + AGENTS.md；**subagent 定义暂无跨 CLI 标准**，按 Claude 专属对待即可。
5. **代码评审**：`/code-review`（内置，多 agent fan-out 评审）或 Ultrareview 云评审（按次付费）；pr-review-toolkit 插件给了 6 个评审 agent 可抄。
6. **避坑**：vibe-kanban/Crystal/agentapi/Terragon/parruda-claude-swarm/AutoGen 已死或弃——别引进；ruflo 的 README 性能声明未经审计；contains-studio/0xfurai 停更。

### 5.2 运行期（产品管线里的「agent」）

`texlate/xlat/` 翻译编排本质是 **asyncio fan-out + 结构化输出 + 评审回环**。评估结论：

- **不需要重框架**：段落级翻译 = 并发 LLM 调用 + JSON schema + 重试，`asyncio.Semaphore` + `response_format json_object` 就够；上 LangGraph 是杀鸡用牛刀。
- 若将来要**长任务可恢复/人工介入**（大书 900 页批量、审核队列），候选：LangGraph（checkpoint 生态最厚）或 Pydantic AI + Temporal/DBOS（类型化+崩溃恢复）。
- **evaluator-optimizer 已内嵌**：LLM-judge 判可译性、LLM 修复器 undefined_cs 兜底——就是 Anthropic 五式里的 evaluator-optimizer，无需框架背书。
- **DSPy/GEPA 值得看一眼**：可拿语料离线优化翻译/评审 prompt（替代手调 few-shot），编译产物嵌进现有管线。
- **别用 coding-agent 框架跑生产**：subagent/agent-teams/workflow 是开发期工具，生产管线要自己握 HTTP client——Managed Agents API 若以后做云端翻译服务可再看（coordinator+roster 结构对得上「翻译 agent+ 评审 agent」）。

### 5.3 值得跟踪的信号

- Agent teams 何时摘 experimental（目前 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`）。
- A2A 进 Claude Code 原生 remote subagent 的时间（Gemini 已有，CC 目前走 MCP 桥）。
- `.agents/skills/` 生态会不会长出「subagent 定义」的跨工具规范（现在各家格式趋同但目录不同）。
- superpowers 是否继续吞并编排层（已 286k★，碾压级）。

## 附录：未核实/已死清单

- **未核实**：claudepluginhub.com（403）、「supersquad」更名（404）、claude-fleet/agentfleet、chamberlain、snowrt/poly-ai、Kimi 自定义 subagent、opencode 读 `.claude/agents`（文档说 no）、Windsurf/Devin subagent、Vercel AI SDK 2026 细节。
- **已死/弃用**：Terragon（关停）、Vibe Kanban 公司（2026-04，转社区纯本地）、Crystal（→Nimbalyst）、agentapi（2026-09-13 归档）、parruda/claude-swarm（404）、AutoGen（维护模式→MAF）、travisvn 清单（~4.5 月未动）、pal-mcp-server（9 月未动）、contains-studio（1 年+）。

### 参考文献

[^cc-docs]: Anthropic. Claude Code 文档（sub-agents / agent-teams / cross-session-messaging / workflows / skills）. code.claude.com 2026. [code.claude.com/docs](https://code.claude.com/docs)

[^superpowers]: obra. superpowers — agentic skills 框架与方法论（subagent-driven-development / dispatching-parallel-agents）. GitHub 2026. [github.com/obra/superpowers](https://github.com/obra/superpowers)

[^agentskills]: Agent Skills 开放规范（~50 客户端采用）. agentskills.io 2026. [agentskills.io](https://agentskills.io)

[^agent-sdk]: Anthropic. Claude Agent SDK（`@anthropic-ai/claude-agent-sdk` / `claude-agent-sdk`）. 2026. [platform.claude.com/docs](https://platform.claude.com/docs)

[^managed-agents]: Anthropic. Managed Agents API 文档（beta `managed-agents-2026-04-01`）. platform.claude.com 2026. [platform.claude.com/docs/en/managed-agents](https://platform.claude.com/docs)

[^cc-action]: anthropics. claude-code-action — 官方 GitHub Action. GitHub 2026. [github.com/anthropics/claude-code-action](https://github.com/anthropics/claude-code-action)

[^plugins]: anthropics. claude-plugins-official 官方插件市场。GitHub 2026. [github.com/anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official)

[^a2a]: Linux Foundation Agentic AI Foundation. A2A Protocol v1.0（agent↔agent 互操作）. 2026. [a2a-protocol.org](https://a2a-protocol.org)

[^building-agents]: Anthropic. Building effective agents（prompt chaining / routing / parallelization / orchestrator-workers / evaluator-optimizer 五式）. anthropic.com 2024. [anthropic.com/engineering/building-effective-agents](https://www.anthropic.com/engineering/building-effective-agents)
