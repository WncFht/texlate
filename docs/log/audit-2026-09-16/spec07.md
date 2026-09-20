# spec07 逐节覆盖审计 — docs/07-latex-pipeline.md vs src/texlate/latex/

> **结论**：spec07 逐节审计：v1 面近全覆盖、v2 主体落地且 §12 留档数字全对；INLINE_MAX 死常量为唯一实质缺口。
> **状态**：时点证据（2026-09-16 口径）
> **日期**：2026-09-16（2026-09-20 迁入重编）

审计点：HEAD f461683（v2 产品面切换后）。口径：spec 每条规范性要求逐一对照 `src/texlate/latex/`（api/flatten/mouth/gullet/segmenter/model/scanner/tables/macro_table/placeholder/reconstruct）与 `tests/test_latex_*.py`（247 用例，全绿）。判例：✅ 落地 / ⚠️ 偏离（实现与 spec 文字不一致，含 spec 滞后与未记录偏离两方向）/ ❌ 缺失。

总体结论：**v1 面（§0-§7、§9-§11）覆盖近乎完全；v2 面（§8、§12）主体落地且 §12 留档数字全部与 bench 实物核对一致**。最大实质缺口只有一处：§3.8 末句"宏参数内联上限"对应的 `INLINE_MAX=8000` 是死常量，零消费方。其余分歧集中在 spec 文本滞后（模块清单、数据结构字段、`_seen` 语义段）与少量未记录的实现扩展（`unicode_math_fix`、`_DEBT_EXEMPT`、`\endinput` 行、top_dir/.TEX 兜底）。

## §0 设计哲学与不变式

区间替换模型与五条铁律均落地：

- `pieces` 无缝平铺 `[0,n)`：v1 `Scanner` emit/flush_run 链（scanner.py:257+）；v2 由 `_Vtex` 覆盖台账保证（segmenter.py `_cover_to`/`_slice_items`），`_emit`/`_ph` 零宽保护防止重复覆盖产生 dead_ph（§12.1 决策）。✅
- 铁律 1 单遍不回退不抛异常：`latex/` 全目录无 `raise`/`assert` 逃出路径；Gullet 用 unread 回吐而非异常（`_can_expand`/ArgMismatch 路径）。✅
- 铁律 3 `%` 构造先于 `%` 分支消费：v1 dispatch 行 1 verb/`\lstinline`、行 8 url verbatim 括号（scanner.py）；v2 `_dispatch` 同序移植。✅
- 铁律 4 splice 只用调用点/原始字节：v2 双轨 `_RunItem(surface/ident/vspan)` + `res.vtex` 设计即此（segmenter.py `_RunItem`）。✅
- 铁律 5 降级 splice-safe：§8.3 表全部路径输出 literal/`[[MACRO]]` 包原始字节。✅

## §1 模块布局

⚠️ spec 滞后。模块清单仍只列 9 文件，缺 v2 三主体 `mouth.py`/`gullet.py`/`segmenter.py`（合计 ~5800 行，是产品默认路径）。依赖方向"api/flatten 是唯一可碰文件系统处"已不成立：`gullet.py:_do_input`（~1866-1944）直接做文件系统 I/O 内联 `\input`。`__init__.py` re-export 清单无 v2 类型（`parse_tex_v2`/`scan_v2` 不导出，产品入口 `parse_tex` 本身已是 v2，影响小）。api.py 另有未记录的 `TEXLATE_NO_EXPAND` 环境变量回退与 `parse_file(top_dir=)` 参数。

## §2 核心数据结构

全部 dataclass 存在且 `slots=True`（model.py）。Spec 滞后项：

- `PhType` 多出 `EXPAND`（展开组占位符，§12.1 已追认）。⚠️
- `ScanResult` 多出 `vtex` 字段（v2 identity 面基准）。⚠️
- `ScanState` 多出 `ifflags`/`steps`/`ph_reserved`；`PlaceholderIssuer.new` 有 `reserved` 参数（placeholder.py）。⚠️
- `Chunk.context` spec 写 `"paragraph"`，实现统一为 `"para"`（model.py:82-84 注释注明 "paragraph" 专指 `\paragraph` 节题——有意改名，spec 未同步）。⚠️
- `env_opt_is_format` 惰性 import tables 打破纯数据层约束（model.py，docstring 已注明偏离）。⚠️
- `PH_RX` 实现为无分组版，spec 伪码为分组版（placeholder.py；`CHUNK_RX` 与 spec 一致）。⚠️ 微差。

## §3 扫描状态机（v1）

§3.1 主循环五分支顺序原样落地（scanner.py 主循环）；§3.4 注释、§3.5 `_handle_env` 星号归一+in_arg 未知 env、§3.6 `_handle_chunk_arg`（含 `\captionof` ("mom",2) 特例，tables.py CHUNK_ARG_SPEC）、§3.7 `_handle_macro`、§3.8 flush_run（CHUNK_MIN=20、force_chunk 一次性、`_split_core` CHUNK_MAX=4000 切分 scanner.py:287-361）均 ✅。

§3.2 分派表 19 行逐行核对一致。**多出第 14b 行 `\endinput`**（scanner.py:908）——spec 分派表未记，但 §8.2 原语集含 endinput，属 v1 对齐补漏未回写。⚠️

§3.3 math-debt：`_ph_into_run` 唯一入口 + 奇数 `$` 记账 + flush_run 清空均落地；另有 **`_DEBT_EXEMPT` 豁免集**（scanner.py:108，VERB/COMMENT/URL/HREF 不记账）——spec 未记录的扩展，语义正确（verbatim/注释体内的 `$` 本来不开启数学）。⚠️

§3.8 末句两个要求拆分判定：CHUNK_MAX 二次切分 ✅（v1 `_split_core` + v2 `_split_bounds`）；**"宏参数内联上限" ❌**——`INLINE_MAX=8000`（tables.py:20）全仓零消费方，是唯一实质未实施项（109K `\version` 内联场景仅靠 CHUNK_MAX 兜底）。

## §4 Scanner 对象模型

`Scanner.__init__/spawn` 签名与字段一致；`ScanState` 共享容器 ✅。`_args(allow_single_token=False)` 唯一调用点在分派 19（scanner.py:957）✅；单 token 不跨 `\`（W1/E10 补丁）✅。平铺不变式测试断言存在 ✅。

## §5 宏表

六类定义命令 + 三分类判定 + `parse_argspec` 全落地（macro_table.py）。偏离：

- §5 表"`\def` delimited 参数记 def_parse_fail 不登记"：v1 一致（macro_table.py:315-321）；§10 附表写"v1 opaque 降级"——行为上是"不登记→调用点走未知命令 `[[CMD]]`"，措辞不同但语义兼容。⚠️ 措辞。
- §5 副表 `\let`/`\newtheorem`：**v1 `DEF_NAMES` 不含**，仅 v2 gullet 实现（`_do_let`/`_do_newtheorem`）。spec 标 "P2 hook" 属预留，v2 侧已落地，v1 侧无——现状可接受但 spec 未说清两臂差异。⚠️
- §5.2 "空白/未知 → skip+warning"：实现 skip 但**无 warning**（macro_table.py:~191 未知字符静默跳过）。❌ 微缺。
- `\newenvironment[n][d]` 双 bracket（F3）✅。

## §6 占位符方案

`[[TYPE_n]]` 双命名空间、单 `PlaceholderIssuer` 全局单调、嵌套 DAG 均 ✅。"构造上无环，assert 兜底"：实现无 assert——`reconstruct` 用 `active` 集检测环并**原样返回字面 token**（reconstruct.py），外加 `dangling` 集 + `log.warning`。行为更保守，但 spec 的 assert 承诺未兑现也未改述。⚠️

## §7 展平

v1 `flatten.py`：8 触发形 + 裸文件名形 ✅；`\subfile` 展开 + `\end{document}` 仅顶层截停（`strip_doc_shell`）✅；MAX_INPUTS=8 ✅；注释内 `\input` 不触发 ✅。

- **内部矛盾**：§7 正文仍写"`_seen` 绝对路径集断环（留档偏差：合法重复包含被跳过一次）"，而 §10 W12 已记"已修（祖先栈语义，5811f83）"——现为祖先栈语义，合法重复包含不再被拦。§7 文字滞后自相矛盾。⚠️
- `_resolve` 查找序多出 **top_dir 第三级 + `.TEX` 大写扩展名**两档兜底（flatten.py；gullet `_do_input` 同步实现）——spec 四级序未含，属未记录增强（orphan 修复任务产物）。⚠️
- v2 侧：展平在 gullet `_do_input`（扫描中展平，符合 §7 首句设计意图）✅；动态文件名拒收（`"\" in fname` → 非 input，gullet.py:~1917）✅ 且 §12.1 已留档。

## §8 展开层（Mouth/Gullet/Segmenter）

主体全部落地。

- §8.1 Tok：`kind/text/pos/gen` 在；**pos 实现为 `(fid,start,end)` 三元组**而非 spec 的 `(file_id,offset)`——mouth.py docstring 已注明偏离，功能超集。另有 `origin`/`xprotect`/`consumed` kind 扩展（consumed 用于 gullet 静默区 `\def/\if/\input` 占位，§12.1 已追认）。Mouth 行为清单（tokbuf/push_tokens/三态折叠/注释整行吞/cs 空白吸收/cats 共享可变）逐条 ✅。⚠️ pos 字段定义滞后。
- §8.2 Gullet：`next_expanded` 宏表优先→`_PRIMS` 原语、读参读未展开 token、代入后 unread 不动点、`\if` 只推回选中支均 ✅。原语集覆盖 spec 全列（含 `let/newtheorem/endinput/ifundefined/catcode/expandafter/csname/noexpand/long/outer`）✅。
- §8.3 降级：BUDGET=100_000/MAX_GEN=32/MAX_INPUTS=8 ✅；超限 warning 实现为 `expansion_overflow`（steps，gullet.py:922）+ `gen_overflow`（gen，:917）双 kind——spec 只提 `expansion_overflow`，gen 侧是细分补充（§12.2 warn_kinds 已含 gen_overflow=1）。ArgMismatch 回吐、`宏体畸形不登记`、`\input` 不存在 warning+literal 均 ✅。
- §8.4 `\def` 定界参编译：`_compile_param_text`（gullet.py:1453-1508）实现 literal_match/delim/until_group/brace_after 全规则，`invoke_def` 调用点语义（定界 token 消费不入参、until_group 回吐、尾随 undelimited 补读、1 基）✅。
- §8.5 作用域：`MacroTable.scopes` 链 + segmenter 驱动 push/pop + `\let` 快照（Alias）+ `\newif` IfCond/IfSetter ✅；参数内组不推 scope 的保守退化一致 ✅。
- §8.6 `\if` 两档：`process_if` 界标夹心（gullet.py:2340-2437）+ `_eval_if` 覆盖 spec 可求值族全列（`\newif` 旗标/`\ifmmode`/`\ifnum\ifodd\ifdim` 字面量/`\ifdefined`/`\if\ifcat`/`\ifx` literal/`\ifcsname`/恒 False 族/`\ifhmode\ifvmode` 常量）✅；判定前置查宏表 ✅。**代码遗留陈旧注释**：gullet.py:16 称 tables.IF_CONST"写反了"，而 tables.py 现值 `{ifhmode:True, ifvmode:False}` 已正确——注释误导，应删。⚠️
- §8.7 `\makeatletter` 区 ✅；`\csname/\expandafter` ✅。

## §9 splice 重建

`reconstruct` 优先级链 trans→ph_map→chunk_content 与 spec 伪码一致；memo 化 O(规模） ✅；`validate_translation` Counter 多重集校验 ✅；`validate_result` 覆盖 pieces_gap/orphan_chunk/dead_ph 且**多出 `dangling_*` 诊断**（未记录）⚠️；`cjk_glue_fix` ✅；**`unicode_math_fix` 是 spec §9 未记的额外 post-reconstruct 修正**（reconstruct.py）⚠️；环处理为字面返回非 assert（见 §6）。⚠️

## §10 弱点清单

W1-W14 与 F1-F12 全部"已修"声明逐条对代码核实成立：W1 `allow_single_token=False`（scanner.py:957）、W2 `rstrip('*')`、W3-W5 in_arg 三分支、W6 `envs` 接入、W7 ScanState 容器、W9 verb EOL 上限、W10 `\lstinline` 走 verb、W11 mask_tex（textutil，593da2d）、W12 祖先栈（5811f83）、F1 迭代化、F2 ("om",1)、F3 双 bracket、F4 `ws_skip_arg`、F5 `_find_math_close` 对齐、F6 `_env_opt_is_format`（90f9f09）、F7 全 core PH_RX 扫描、F9 三字符 ord、F10 e 支消费 + 零宽占位、F11 `\url` 定界分支、F12 `_EnvDead`/`_EnvDeadTok` 墓标（v1 scanner + v2 segmenter `_replay_dead` 双实现）。W14/F8 留档项状态准确。✅

## §11 验收门 + 测试面

§11 表是 spike/259 语料时代基线，现被 §12.2 corpus_v3 数字取代（spec 自身结构如此，不算矛盾）。测试面：spec 写 `tests/latex/`，实际为 `tests/test_latex_*.py`（路径滞后 ⚠️）；列出的矩阵项（match_brace/match_bracket/read_cmd_name/find_env_end 星号归一/_args/parse_argspec/math-debt/in_arg 四变体/宏分类/chunk 化/正文内 \def/flatten_inputs/reconstruct 嵌套）在 247 个 latex 测试函数中均有对应，本轮 `uv run pytest tests/test_latex_*.py` = **247 passed**。✅

## §12 v2 切换落地记录

§12.1 八个切换面决策全部在代码中定位到实现（`_EXPAND_KINDS` 只留 transparent_expand、verb 宏端点 token 级 `_find_env_end`、`_grp_env_macro` 经 `state.macros`、`_resolve_macro` 回落 v1 平表 segmenter.py:1832、`_ListSource` deque、零宽 `_cover_to` 不签发、动态文件名拒绝、xparse e 支+ArgMismatch 回压）。✅

§12.2 验收数字逐项对 `bench/results/parsebench-v2prod-final-2026-09-15/` 实物核实：

| spec 声明                                            | 实物核对                                                                                                                              | 判定 |
| ---------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- | ---- |
| parse ok 1955/1955、0 错 0 超时                      | summary.md + files.jsonl 1955 行全 ok                                                                                                 | ✅   |
| identity strict 1955/1955                            | summary.md identity strict 1955                                                                                                       | ✅   |
| leak 58/124772=0.046%（v1 57/135170）                | summary.md v1↔v2 表一致                                                                                                               | ✅   |
| unresolved_inputs 111                                | files.jsonl v2.unresolved_inputs 计数=111（注意与 149 条 missing_input warning 是两个口径，spec 两数都写对了）                        | ✅   |
| dead_ph/orphan 0/0                                   | summary.md fake-translation 行                                                                                                        | ✅   |
| vtex_vs_src 1906/17/32                               | summary.md 一致                                                                                                                       | ✅   |
| p50 43ms/p95 428ms/max 8.4s(2403.15096)/>500ms 85 个 | files.jsonl 重算：max=8393.2ms 正是 2403.15096，>500ms 恰 85                                                                          | ✅   |
| pytest 1090 passed/16 skipped                        | 现 `tests/` 收集 1106 = 1090+16，latex 247 全绿                                                                                       | ✅   |
| e2e_mock 冒烟三段干净、编译挂为环境缺包              | `e2emock-v2prod-smoke-2026-09-15/results.json`：fault_chunks=0、leftover_ph=0、ctex 注入 ok；compile fail=缺 pstricks.tex/revtex4.cls | ✅   |
| warn_kinds 对照（v2 vs v1 九项）                     | 与 summary.md v2 warn_kinds/v1 scan warnings 逐项一致                                                                                 | ✅   |

§12.3 遗留三条（`res.macros` 消费点未适配、性能尾 85 文件、e2e 编译环境性）与代码现状一致。✅

## 缺口汇总（按严重度）

1. ❌ **`INLINE_MAX=8000` 死常量**——§3.8"宏参数内联上限"未实施，tables.py:20 唯一定义无消费方（超大内联仅靠 CHUNK_MAX 兜底，spec 示例场景未验证过上限语义）。
2. ⚠️ **§1 结构性滞后**——模块清单缺 mouth/gullet/segmenter；"api/flatten 唯一碰文件系统"已被 gullet `_do_input` 打破。
3. ⚠️ **§7 `_seen` 段与 §10 W12 自相矛盾**——祖先栈修复后正文仍描述旧的 once-set 语义。
4. ⚠️ **数据结构字段滞后一批**——`vtex`/`EXPAND`/`ifflags`/`steps`/`ph_reserved`/`reserved`/pos 三元组/`"para"` 均未回写 §2/§8.1。
5. ⚠️ **未记录的实现扩展**——`unicode_math_fix`、`_DEBT_EXEMPT`、`\endinput` 分派行、top_dir+`.TEX` 兜底、reconstruct 环→字面返回+`dangling` 诊断、`gen_overflow` warning kind、`TEXLATE_NO_EXPAND`/`top_dir` API 参数。
6. ❌ 微缺：`parse_argspec` 未知字符无 warning（§5.2 承诺 skip+warning）；spec §6 承诺的环 assert 不存在（实现更保守，字面返回）。
7. ⚠️ 代码侧：`gullet.py:16` 陈旧注释称 IF_CONST 写反（实际已正）；§5 副表 `\let/\newtheorem` 在 v1 永久缺席但 spec 未注明两臂差异。
