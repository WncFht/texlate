# latex-audit-core — gullet/scanner/mouth/model/macro_table/placeholder 只读审计

> 2026-09-17 收口。只读任务，零产品文件改动（latex/ 归 texlate-1d lane，发现全部外路由）。探针 `tmp/latex-audit-core/probe*.py` + notes.txt 台账（gitignored）。~5800 行全读。

## 确认缺陷 → 已路由 texlate-1d

### C1 [SECURITY] `_resolve_input` 任意路径读 — gullet.py:2152/2208-2237

`Path(d)/c`：c 为绝对路径时 pathlib 绝对分量胜出；`../` 无约束。probe E 实证 `\input{/tmp/sec_abs_probe.tex}` 与 `\input{../x}` 均解析并 tokenize root_dir 之外文件。无 root_dir/top_dir 包含性检查（spec §7 只定查找序未禁 abs/`..`；TeX 由 `openin_any` 限制）。不可信 e-print 可借此把本机文件注入 token 流 → chunks → LLM 网关 = **本地文件外泄面**。

### C2 [v1-only] `\newcommand[n][d]` spec off-by-one — macro_table.py:375

`spec = [o]*has_opt + [m]*nargs`，但 LaTeX n **含**可选参 → `[2][d]` 应 `[o,m]` 实为 `[o,m,m]`。`\foo{a} Text` → `[[MACRO_1]]` 覆盖 `\foo{a} T`——幻影第 3 m 吃正文 token（probe3 实证）。`[d]` 默认值亦丢（has_opt bare bool）。v2 `_do_newcmd`（`n=max(n-1,0)`）正确——v1 臂独有。

### C3 [v1-only] `\newenvironment` 同族 off-by-one — macro_table.py:319-344

`[2][d]` → EnvEntry.nargs=2（应 1）→ `_eat_env_args` 多吃一 mandatory 组。probe4：`\begin{ee}{a}{b} TEXT` 两组全并入 ENVTAG（TeX 只取 `{a}`，`{b}` 是体）。较轻——字节保留在 literal 内，召回损失非损坏。

### C4 `_read_grouping` `]`/`>` 闭合不看 `{}` 屏蔽 — gullet.py:1203-1234

line 1230 `t2.text == close_c` 对任何 `]` token 触发，brace 深度不计。`[o]` 参 `\foo[{]}]X` → 实际 arg=`{`（内层 `}` 前的 `]` 处闭合），`}]X` 滞留流。probe D' 实证输出 `A { Z } ] X`。TeX/xparse 定界可选参尊重平衡组屏蔽；`_read_delimited`（1236+）有 lbrace→`_read_balanced` 整组跳——`_read_grouping` 缺同款。

### C5 `protected_param_positions` 保护位跨 `}` 泄漏 — macro_table.py:75-91

`cur_protect` 在 `\cite{` 打开后只由下一个 cs token 重置，`}` 边界不复位。`("See \\cite{#1} and #2", 2)` → `(True, True)`——`#2` 纯文本位被标 KEY → 调用点该参数永不进 chunk（召回损失）。反向序 `(False, True)` 正确。

## 存疑/装饰（实证过，供裁决）

- gullet.py:2608-2614 `process_if`：registered if* 有 guard，**未注册** if* 名（etoolbox `\ifdef`/`\ifcsdef` 族包宏）仍 nesting+=1 → probe F：`\iftrue KEEP \ifdef{X}{Y} DROP \fi` → 真 `\fi` 被当内层吃掉 → `if_unterminated` + 裸 `\fi` cs 泄漏；`\iffalse` 变体选支空 → consumed marker 盖到 EOF → 文档尾部整段 literalize。v1 scanner.py:1548-1556 同型残留。
- scanner.py:1461-1467 v1 `_read_number`：`'`（八进制）与 `` ` ``（字符码）混一谈——`'77` → ord('7')=55 且留 stray `7`（TeX '77=63）。both-branch 保守方向。
- gullet csname 合成 token pos 只盖内首 token，`\csname`/`\endcsname` 字节成 gap——大概率 segmenter gap-fill 兜住。
- `skip_past` straddle abort 时 resync 已推 mouth.i（partial mutation）。
- `_read_delimited` 合成 rbrace pos 借 `grp[-1].pos`；`delim=[]` 时 `del out[-0:]` 清表——今天 `_spec_to_args` 不产空 delim，landmine。
- `_spec_to_args` D/R 默认值丢弃（只 O 保留）；gullet `_parse_xparse` 保留——双臂不对称，同 C2 族。
- `e{^^}` embellishment `rest` 是 set → 重复修饰符不可达（双臂同）。
- mouth/model 小项群：`\<space>` 留 state=M；eol_par 跨注释行去重；`\r`=CC_SPACE；`_WS` 无 `\f`；`read_cmd_name` isalpha 收 Unicode；`env_opt_is_format` isdigit Unicode；`skip_verb_at` `\lstinline[` 未闭 `[` 成定界符；`env_kind_of` 子串 'figure' in 'Configure' 命中；`classify_body` `\begin {X}` 带空格漏 ENV_BEGIN；`_scan_def_params` 收 `#0`/Unicode 数字；`register_newif` `\newif\if` 退化登记 `\true`/`\false`；`\ifcase` 负数 both-branch；`ifcat` isalpha 近似；MAX_INPUTS `>`vs`>=` 边界；v1 `_args` 'm' 接受 `[`-开参（保守覆盖）。

## 排除项（核实非缺陷）

- 终止性：`\def\x{\x}` → gen≥32 `gen_overflow` warning + cs 原样产出，probe H steps=33 终止；steps/BUDGET/inputs 三闸均在。
- `\let` 快照语义：链在 let 时塌缩，resolve 一层 deref 正确。
- `_seen` 祖先栈：同路径堆叠阻，spec W12 已记修复 5811f83。
- catcode 组作用域：segmenter `_scope_push/_pop` 接线 `cats.push/pop` 无泄漏。
- `_dispatch_cmd` 19 行全返 j>i——主循环前进保证；所有 arg reader EOF→ArgMismatch 或消费≥1。
- v2 `\newcommand{\foo}[2][d]` probe K：`\foo` 判 opaque（体无≥2字母文本）→ 不展开原样过——正确。
- `expand_all` 仅 gullet_bench.py 调用 + `ArgspecEntry.guessed` 零读者——crosscut 已报，复核属实。

spec 对照：docs/07 §7 查找序与 MAX_INPUTS=8+_seen 防护均一致；C1 路径逃逸是 spec 未覆盖空白面（openin_any 等价物缺失）；C2/C3 与 §5.2 的 `[n][d]` n 语义偏离 LaTeX。
