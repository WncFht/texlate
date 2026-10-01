# spec · 校验层

> 范围：`validate/`（L0 规则 / L1 tree-sitter / L2 log 回灌 / 聚合报告）+ `redlines.py`（红线概念注册表）+ `repair_l2.py`（L2 归因 - 重译簇 / env judge）+ `repair.py`（修复衔接低层）+ scan 层内建校验指针。翻译编排归 `translate.md`；编译引擎与 fixloop 归 `compile.md`；chunk 产出与层内校验规则语义归 `latex-pipeline.md`。
> 口径：现行实现描述，符号引用为「模块 + `::符号`」粒度；实测证据引 `research/` 档。

## 0. 总则

校验链的根本立场：**出 PDF ≠ 成功**——占位符大面积丢失可产生零编译错误而静默删内容，亦有出 8 页 PDF 但零中文字节的实测案例[^texglot]，故校验必须独立于编译存在。

三条共同原则：

- **全部 src↔zh 相对判定**——「译文不得比原文更坏」：src 自带不平衡继承容忍，只报新增损伤（baseline 相对判定在 L0/L1/L2 三层同构）。
- **异构校验**——L0 用 stdlib 正则、L1 用 tree-sitter CST、L2 用编译 log 三种不同实现互为正交证据，不共享解析器防同源盲区[^l1-ts]。
- **缺层不罚**——`report.py::ValidationReport.ok` = 所有在场层过；缺层（无 node 的 L1、`log_missing` 的 L2）不计负。

## 1. scan 层内建校验（指针）

chunk 产出层自带两件校验器（`latex/reconstruct/validate.py`），属上游解析域、完整语义见 `latex-pipeline.md` §9：

- `validate_result(res)`——结构校验：pieces 无缝平铺（`pieces_gap`）、protected_tex→ph/chunk 递归可达性（`dangling_ph`/`dangling_chunk_ref`/`orphan_chunk`/`dead_ph`），`ph_reserved` 字面豁免。
- `validate_translation(chunk, text)`——译文契约：`chunk.placeholders` 多重集逐枚在译文出现（`missing`/`extra` 差集）。

下游消费：pipeline `_INTERCEPT_NETS` 的 `leftover_ph` 网与 L0 `placeholder` 规则是同概念在不同层的复判（§2 的 `CACHE_VETO_RULES` 镜像面）。

## 2. L0 规则层（`validate/l0/`，stdlib always-on）

`validate_pair(src, zh) -> L0Report` 跑 **15 项顶层 `_check_*`**（`_check_ph_anchor` 内嵌于 `_check_placeholder` 调用，合计 16 个定义；函数 docstring「13 组」已滞后）。`report.ok` 为 True 即可送 L1/拼回；False 时 `feedback()` 文本直接进 corrector `previous_validation_error` 字段。

| check                                                                               | 语义                                                                                                                                                                                                                                                                                                                                                               | error / warn                                                                                                                     |
| ----------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------- |
| `_check_placeholder`（含 `_check_ph_anchor` 子检查：BIBITEM 行锚 + COMMENT 行纯度） | `[[A-Z_]+_\d+]` 多重集 diff + lev≤2 Kuhn 模糊配对（`[[..]`/`[X_1]`/`【..】` 变体）；注释区多余                                                                                                                                                                                                                                                                     | 缺失/多余/拼错/锚定→error（附修复建议）；序乱→warn                                                                               |
| `_check_brace`                                                                      | `{}` 平衡（`\{\}` 转义、`%` 注释豁免）：zh 前缀深度 < src 或净余额 ≠ src                                                                                                                                                                                                                                                                                           | error；计数不同但净额一致→warn                                                                                                   |
| `_check_env`                                                                        | `\begin/\end` 栈配对 + env 名 multiset diff                                                                                                                                                                                                                                                                                                                        | 多余 end/不匹配/未闭合/新增 env→error；end 名偏多→warn（cap 50）                                                                 |
| `_check_key`                                                                        | `\cite*/\*ref/\label/\bibitem/\bibliography` key multiset（逗号拆分、`[..]` 豁免）                                                                                                                                                                                                                                                                                 | src−zh 漏 key→error；zh−src 新增（幻觉引用）→warn                                                                                |
| `_check_math`                                                                       | 未转义 `$` 计数 + `\(\)\[\]` 成对                                                                                                                                                                                                                                                                                                                                  | 计数≠→error；`$` 奇数（继承自 src）→warn                                                                                         |
| `_check_same_source`                                                                | 归一化后 zh≈src 回声（BIB/<10tok/人名专名列豁免）                                                                                                                                                                                                                                                                                                                  | error                                                                                                                            |
| `_check_length`                                                                     | zh/src token 比 + CJK 占比                                                                                                                                                                                                                                                                                                                                         | 比出 [0.30,3.00]→error（名单列 src 上界 4.00）；CJK<0.30→warn                                                                    |
| `_check_residual_en`                                                                | 英文残段净量（残句未翻漏网）                                                                                                                                                                                                                                                                                                                                       | error                                                                                                                            |
| `_check_macro`                                                                      | zh 控制序列集合 − src 集合 + src cs 多重集 ⊆ zh 方向                                                                                                                                                                                                                                                                                                               | 新增 cs（含非 ASCII 融合、STRUCT_CMDS 结构族）→error；脆弱间距命令（`\`/`\,`/`\;`/`~` 等）丢失 `cs_dropped`→error；其余丢失→warn |
| `_check_item_glue`                                                                  | `\item` 与后文粘连形态                                                                                                                                                                                                                                                                                                                                             | warn                                                                                                                             |
| `_check_ph_in_cs`                                                                   | 占位符落进控制序列内（`\foo[[MATH_1]]` 融合）                                                                                                                                                                                                                                                                                                                      | error                                                                                                                            |
| `_check_bare_cs`                                                                    | 数学 cs 入文本 / 粘连 cs                                                                                                                                                                                                                                                                                                                                           | error                                                                                                                            |
| `_check_dangerous_cs`                                                               | `DANGEROUS_CS` 表名净差（IO/定义覆写/catcode/装包逃逸族；数学域不豁免；env 名写文件如 `\begin{filecontents}` 属盲区另网）                                                                                                                                                                                                                                          | error                                                                                                                            |
| `_check_protocol_echo`                                                              | 协议回显守卫（`_ECHO_SIGS`：corrector 三段式节标 `[Original]`/`[Translation]`/`[Error]` + L0 反馈行话 `占位符缺失:`/`占位符疑似拼错`/`多余/未识别占位符:`/`结构占位符`/`注释区内臆造占位符` + 重试协议字面 `previous_validation_error`/`slot_validation_failures`/`[compile_error]`；`[n]`/`@@`/`placeholder_values` 批协议残渣由 `xlat/batch.py` 剥除，不经本查） | error                                                                                                                            |
| `_check_comment_eof`                                                                | 注释/EOF 边界形态                                                                                                                                                                                                                                                                                                                                                  | error                                                                                                                            |

`CACHE_VETO_RULES = {placeholder, ph_in_cs, bare_cs, residual_en, dangerous_cs}`（`l0/main.py`）——缓存写入/命中否决面，与 `xlat/intercept.py::_INTERCEPT_NETS` 五张升格拦截网镜像同源（`leftover_ph`/`ph_in_cs`/`bare_cs`/`residual_en`/`dangerous_cs`）；`placeholder` 网只镜像 zh−src 净多出臂，缺失/锚定臂归阶梯修复管辖。漂移由 `tests/compile/test_redlines.py` 系 pin 拦截。实测 10 类破坏全检出、干净对零 error-FP、拼错高比例给出 lev≤2 修复建议[^l0-rules]。

`pair_feedback(src, zh)` = `validate_pair(...).feedback()`——pipeline.validator 签名对齐版，e2e/pipecore/worker 四臂共用。

## 3. L1 tree-sitter CST 层（可选，`validate/l1.py` + `validate/ts/`）

`TsValidator` + node 子进程 `ts/validator.js`（`@pfoerster/tree-sitter-latex` + `tree-sitter` npm 依赖，均有 prebuilt；`ts-validator` extra 是 python 侧空占位）[^l1-ts]。

- **必须 baseline 相对判定**：`sign()` 产 `TsBaseline{parse_errors, env_mismatches, unclosed_math, brace_balance}`，`validate(tex, baseline, expect)`→`ok_relative` = 四项计数 ≤ baseline ∧ 无 placeholder_bad——约七成真实主文件 baseline 自带 grammar ERROR，绝对判定不可用；生产裁决经 `verdict_ok`。
- 检查项：ERROR/MISSING 节点（含位置/snippet）、env 配对（Query 抓 begin/end/generic_command/裸叶）、定界符叶计数、占位符契约 diff（expect↔found 差集 + lev≤2 typo 配对）。verbatim/comment 内 `{}`/`$` 经 CST 叶天然免疫；`\end` 改名属语法合法 generic_environment，靠名字比对抓。
- IPC 双模：spawn-per-batch（~37ms 摊薄）与 `--repl` 常驻（`open()` + pump 线程）；`_BATCH_TIMEOUT_S=30`。
- 降级：`available()` 需 node+validator.js+node_modules 三件，缺席优雅降级 L0；`TEXLATE_NODE`/`TEXLATE_TS_WORKER`/`TEXLATE_TS_NODE_PATH` env 覆盖。env 白名单 `_ENV_PASS_EXACT`+`LC_*`+注入 NODE_PATH（不继承 secrets）。协议/schema 违例抛 `L1Error`。

## 4. L2 编译 log 回灌（`validate/l2.py`）

`parse_log`/`parse_log_text` → `L2Verdict{n_errors, first_error, errors, warnings, tail, engine, log_missing}`；`ok` = `n_errors==0`。

- 错误计数**双格式**：`^!` + `file:line:`（只数 `!` 漏全部引擎级错误）；判定单源在 `texlog.match_error_line`——`file:line:` 扩展名字符集放宽到任意短字母数字串（`.eps`/`.pdf_t`/`.lbx`/`.tikz`/`.end` 实测全真错），反向剔除非错误形（`{LaTeX,Package,Class} … Warning` 行与 `==> Fatal error` 汇总尾行）。
- `LogError{line_no, head, tex_file, tex_line, ctx, file_stack, eof_file}`：首个 `^!` + 其后 ctx（截于下一错）；`l.N` 行号 + `(` 开括号文件栈追踪定位肇事文件；`File ended while scanning` 单列 `eof_file`——`)` 弹栈已把肇事文件退栈，取错误行前 ≤16 行内最后弹出文件当真凶。
- 红线分类经 `redlines.py` 单源注册（`L2_REDLINE_CLASSES`：`invalid_utf8`、`fffd_glyph`、`missing_glyph`、`missing_glyph_cjk`、`file_not_found`；`missing_glyph_nullfont` 良性试排吞字**不入**红线，见 §5）。`Missing character` 码点形态双收：老 TL `("8FD9)`、新 TL `(U+8FD9)`（`_MISSING_CHAR_RX`）。系统 texmf/bundle 件与 DOS-EPS（魔数 `\xc5\xd0\xd3\xc6`）红线命中降级进 `sys_hits`/`warnings_sys` 观察项——老 CTAN 包自带坏字节非工程红线。
- 存储面：`errors ≤ _MAX_STORED_ERRORS=200` 条（`n_errors` 仍精确计数）、每类 warning 样例 ≤5、归因 hits ≤50；`attribution_dict()` 产 records 紧凑 hits。
- tectonic 有时**不写 .log**——`log_missing=True` 非异常，监控不能假设 log 存在。

`WarningSummary` 分类序：invalid_utf8、missing_glyph_nullfont、missing_glyph（码点细分 fffd/cjk）、citation、reference、rerun、font_subst、file_not_found、overfull、generic。

## 5. 红线概念注册表（`redlines.py`）

同一红线概念在多层（engine warning 扫描 / fixloop `warnings:` 段 / l2 行级类 / judge 门控探针）**有真分歧**而非纯拼写问题——注册表按 concept 行登记各层 `(发射名, pattern)` 切片，消费者各取本层、分歧并列可见防再漂（`tests/compile/test_redlines.py` pin 住 rules yaml 镜像）。导出切片：`ENGINE_RED_LINES`（登记序）、`RULES_WARNINGS`（镜像期望）、`L2_REDLINE_CLASSES`（红线集）、`L2_WARNING_RULES`（行级 pattern 托管）、`REDLINES_BY_ID`（归因面引 id）。

| concept id                   | engine            | rules(warnings:)                   | l2                                                    | judge                      | 备注                                                                                               |
| ---------------------------- | ----------------- | ---------------------------------- | ----------------------------------------------------- | -------------------------- | -------------------------------------------------------------------------------------------------- |
| `invalid_utf8`               | invalid_utf8      | invalid_utf8（折叠 FFFD misschar） | invalid_utf8，红线                                    | —                          | 裸串 + `replaced by U+FFFD` 变体                                                                   |
| `fffd_glyph`                 | fffd_glyph        | （并入 invalid_utf8）              | fffd_glyph（missing_glyph 码点=0xFFFD 派生），红线    | —                          | engine 独占 gate 窗 pattern                                                                        |
| `missing_char`               | missing_chars     | missing_char                       | missing_glyph，红线                                   | missing_character          | 三层同 `_MISSCHAR_GATE` tempered 窗：排除 `in font nullfont`，至多跨一个 79 列折行                 |
| `missing_char_nullfont`      | —（负向前瞻内嵌） | —                                  | missing_glyph_nullfont，**非红线**                    | missing_character_nullfont | 良性试排吞字：judge/l2 只记观察项                                                                  |
| `missing_char_sweep`         | —                 | —                                  | —                                                     | missing_character_sweep    | C0 测量扫掠豁免是算法签名（同字体 ≥25 条严格升序链），无行级 pattern                               |
| `missing_glyph_cjk`          | —                 | —                                  | missing_glyph_cjk，红线                               | —                          | l2 派生类：码点 `is_cjk_cp` 细分，中文静默丢失信号                                                 |
| `missing_graphic`            | missing_graphic   | missing_graphic                    | file_not_found（本行 + degraded_file 粒度并集），红线 | —                          | l2 行级不分 graphic/包文件                                                                         |
| `degraded_file`              | degraded_file     | tectonic_degrade                   | —（`^!` 行在 l2 计错误）                              | —                          | tectonic 跳包降级暗雷：continue-on-errors 出残页 pdf                                               |
| `restatable_loss`            | —                 | —                                  | —                                                     | thm_restate_loaded         | thm-restate env-name 参被译→`\csname` 零消息静默丢定理；唯一可检信号=包加载痕迹，只记 notes 观察项 |
| `upstream_asset_absent`      | —                 | —                                  | —                                                     | —                          | concept_only 锚点：e-print 未 ship 的图档，log 面与可修 missing_graphic 同形不可切，判据在清单核对 |
| `perpage_fnsymbol_firstpass` | —                 | —                                  | —                                                     | —                          | concept_only 锚点：perpage+fnsymbol 首遍计数器溢出（warm aux 次遍自愈），判据在 .aux 新鲜度        |
| `latex209_class_absent`      | —                 | —                                  | —                                                     | —                          | concept_only 锚点：`\documentstyle` 类缺席类表属能力边界正确 reject，判据在类表核对                |

## 6. L2 归因 - 重译簇（`repair_l2.py`）

编译不过时把 log 错误定位回 chunk 点名重译：`L2Attr.attribute`（tex_line→offset→chunk）、`_l2_localize`→hits、`retranslate_hits`（每块限 1 次：ok→adopt，否则 revert→原文）、`_resplice` 重建 + `prepare_chinese` 再注入。

归因豁免与窗口：`L2_MAX_CHUNKS=10`、`_L2_ATTR_WINDOW=4000`、`_L2_MAX_ERRORS=50`（宏展开现经共享 `_Expander`（`latex/reconstruct/core.py`）token 入口，memo + `active` 环检取代旧 `_EXPAND_MAX_DEPTH` 深度保险丝）；`_INFRA_ERR_RX` 永不归因（基建错不归罪译文）、`_STRUCT_ERR_RX` 严格 in-span、`_FILELEVEL_ERR_RX` 文件级兜底白名单、`_UNDEF_CS_*` culprit 提取 + `_cs_source_carried` 豁免（src 自带错不罚 zh）、`err_signature` en-baseline 豁免。

回退后**补一次裸编**：L2 回落原文并重 splice 后双臂对回落交付树再编译判定，`rep["fallback_verdict"]` 记三态 verdict（clean/partial/fail）——回落态即交付树，不再有代验兜底。env：`TEXLATE_NO_L2`（回灌总闸）、`TEXLATE_ENV_JUDGE`。

### 6.1 env judge（可译性判定）

未知 env（不在 MATH|VERBATIM|PROTECTED|ARG_TRANSPARENT 已知集）是否含可译散文由 LLM 判定：`repair_l2.unknown_env_of` → `_env_judge_one`（content 送判非 env name，`_ENV_JUDGE_MAX_CHARS=2000`）→ `env_judge_all` 顺序判定。判 False → 整体 `[[ENV_n]]`；判 True → `env_text` chunk 送翻。

参数（`xlat/prompts.py`）：`ENV_JUDGE_TEMPERATURE=0.01`（本意 0，本网关 temp=0 返回 502，0.01 近确定性且通行）、`ENV_JUDGE_MAX_TOKENS=16`、`ENV_JUDGE_RETRIES=3`；`_ENV_JUDGE_SYSTEM` 6 组 few-shot（含 `\caption` 内嵌→True、纯公式/绘图→False 灰区）；`parse_env_judge_answer` **fail-open**——精确 `false` 才判 False，其余一律 True（宁翻勿漏）。

## 7. 修复衔接（`repair.py`）

e2e 与 server worker 双编排器共享的低层件；链序 = **precheck → L2 回灌 → fixloop**（`e2e._repair_chain`）——L2 先跑因 fixloop 的 regex_rewrite 会被 L2 resplice 冲掉。

- `log_text_of`：.log 非空优先、stdout_tail 兜底。
- `run_fixloop`/`run_precheck`/`ruleset_with_baseline`：fixloop 双臂调用面（ruleset 装载缓存 + baseline 注入）。
- `cross_engine_retry`/`consume_engine_flags`：tectonic→xelatex 换引擎重试；`VERDICT_RANK={clean:3, partial:2, fail:1, reject:0}` 跨臂退化闸——终态不得低于上游。
- `embed_tounicode_quiet`/`resolve_glossary_path`/`ResProxy`。
- env 开关：`TEXLATE_NO_FIXLOOP`（默认开）、`TEXLATE_FIXLOOP_LLM`（e2e 默认关 opt-in；worker 默认开但 BYOK 计费面门控，见 compile.md §6.9）、`TEXLATE_NO_L2`、`TEXLATE_ENV_JUDGE`。

## 8. 聚合与状态词表

`report.py::ValidationReport`：`ok`=所有在场层过（缺层不罚；`l2.log_missing` 豁免）；`feedback()`/`hard_failures()`/`summary()` 供 pipeline validator 与修复链消费。

| 域       | 字段                             | 取值                                                                        | 产出                    |
| -------- | -------------------------------- | --------------------------------------------------------------------------- | ----------------------- |
| L0       | `L0Report.ok` / Issue `severity` | `error` / `warn`（§2 表逐条定级）                                           | `validate/l0/report.py` |
| L1       | `ok_relative`                    | 四项计数 ≤ baseline ∧ 无 placeholder_bad                                    | `validate/l1.py`        |
| L2       | `L2Verdict.ok`                   | `n_errors==0`；`log_missing` 单列                                           | `validate/l2.py`        |
| 聚合     | `ValidationReport.ok`            | 所有在场层过                                                                | `validate/report.py`    |
| 回灌     | `fallback_verdict`               | `clean` / `partial` / `fail`                                                | `repair_l2.py`          |
| 编译判决 | `Verdict.status`                 | `clean` / `partial` / `fail`（拒绝统一 partial+`reject_at`，见 compile.md） | `compile/judge.py`      |

### 参考文献

[^texglot]: TeXlate 调研档案：texglot 模式实录——归一化层/缓存键/重试阶梯/沙箱与网关实测。[research/latex/texglot-patterns.md](../research/latex/texglot-patterns.md)

[^l0-rules]: TeXlate 调研档案：L0 校验规则设计与对抗实测。[research/latex/validator-rules.md](../research/latex/validator-rules.md)

[^l1-ts]: TeXlate 调研档案：tree-sitter 校验层与 baseline 相对判定。[research/latex/validator-ts.md](../research/latex/validator-ts.md)
