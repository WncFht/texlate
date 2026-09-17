# 08 · 翻译 / 校验 / 编译管线规格

> 最终技术方案 · `src/texlate/xlat/` + `src/texlate/validate/` + `src/texlate/compile/` 全规格。
> 证据基础：`docs/research/latex/prompt-glossary-spec.md`（prompt/术语表）、`texglot-patterns.md`（归一化层/缓存键/重试阶梯/沙箱）、`validator-rules.md`（L0）、`validator-ts.md`（L1）、`fixloop-rules.md`（规则库）、`engine-matrix.md`（引擎路由）、`pstricks-route.md`、`ctanfetch-probe.md`。
> 实现按本文执行。

## 0. 总览

```
chunks[] ──► 术语表物化（三级 + ph 恒等 + doc 级过滤）
        ──► 按 kind 选 system prompt（C1–C10 + kind 条款 + glossary 尾块）
        ──► 批量/单翻 + 重试阶梯 ──► L0 规则校验（每块即时）
        ──► （可选 L1 CST）──► splice 回写（docs/07 §9）
        ──► normalize 归一化手术 ──► 注入块（ctex/xeCJK + 兼容前导块）
        ──► Engine 沙箱编译 ──► fixloop（yaml 规则）──► clean 判定 ──► zh.pdf
```

铁律：**"出 PDF ≠ 成功"**——校验必须独立于编译（E10 实测：56 处丢占位符产生 0 编译错误静默删内容；hep-th 出 8 页 PDF 但 0 中文字节）。

## 1. 翻译编排（`xlat/`）

### 1.1 chunk 类型与 system prompt 套件

六种 chunk kind → 六份 system prompt，**公共条款块 C1–C8 逐字共享**（维护性 + 前缀缓存）：

```
system_prompt(kind) = TASK_SENTENCE[kind]
                    + C1..C8（公共块，逐字固定）
                    + KIND_CLAUSES[kind]     # 0~2 条
                    + C9 PLACEHOLDER_CLAUSE  # 压轴，条款列表末位
                    + C10 NAME_CLAUSE        # 仅 para/abstract
                    + GLOSSARY_BLOCK         # 最末（§1.4）
```

公共块要点（英文成稿，init 期填 `{SRC}/{TGT}`）：C1 只翻自然语言；C2 不翻清单（控制命令/数学/含 LaTeX 尺寸单位 em…sp 的参数原样枚举）；C3 转义特殊字符 `\% \# \&`；C4 已知与 CJK 冲突的宏（`\hl/\ctext`/soul/xcolor 系）参数保原语；C5 特殊符号两侧垫空格（中文换行痛点）；C6 输出可编译；C7 学术术语一致；C8 只输出译文无解释无围栏。

**C9 占位符条款（逐字，列表末位）**：

```text
C9. [[TYPE_n]] tokens (e.g. [[MATH_12]], [[CITE_3]], [[REF_7]], [[ENV_4]],
    [[AUTHOR_1]], [[SL]], [[PL]], [[SP]]) are placeholders for protected LaTeX
    fragments or structural markers. Do not translate, modify, reorder,
    split, merge, add, or remove any of them, and do not let them influence
    the surrounding translation. Every placeholder in the input must appear
    verbatim in your output.
```

（勘误 2026-09-17：成稿列举补 `[[SP]]`——post-spec 新 token，保护 `\ ` 强制空格，`placeholders.py:62`；条款文本与 `prompts.py` `PLACEHOLDER_CLAUSE` 逐字同步。勘误 2026-09-17 复核：`PLACEHOLDER_CLAUSE`（prompts.py:176-183）实列 5 枚裸标记 `[[SL]]/[[PL]]/[[SP]]/[[NBSP]]/[[THINSP]]`；保护族全量为 **8 成员**——再加 `[[MEDSP]]/[[THICKSP]]/[[NEGSP]]`（`\:`/`\;`/`\!`，各带 `_RAW` 变体+sentinel，`placeholders.py:64-95`），prompt 措辞不提后三枚。另 spec 公式未记档的 impl 子句：`_FUSION_CLAUSE`(C8a)、`_HEADER`、`_BATCH_CLAUSE`。）

**C10 人名保原语**（para/abstract 末条）：`always keep person names in their original {SRC} form. Never translate, transliterate, or reorder them.`

| kind            | 专属条款                                                                                                   |
| --------------- | ---------------------------------------------------------------------------------------------------------- |
| `para`          | +C10                                                                                                       |
| `caption`       | 无（短文本）                                                                                               |
| `section_title` | 只翻 `\section` 花括号内文本；命令/`[opt]`/`\label` 不动                                                   |
| `abstract`      | +C10；单段流畅、保留 `\keywords` 结构                                                                      |
| `table_text`    | `&`/`\\`/`\hline`/`\multicolumn`/`\cline`/列 spec 不动；行列数不变（**v0 先不翻表格内文本，prompt 备好**） |
| `env_text`      | `\begin/\end` 与结构命令不动，只翻人读句子                                                                 |

### 1.2 带错重翻（corrector）

专用 corrector system prompt（不改共享块）+ user 三段式：

```text
[Original]
<original {SRC} LaTeX>
[Translation]
<current {TGT} LaTeX>
[Error]
<missing/extra placeholders, command mismatches, bracket errors, ...>
```

温度 0.2；上限 3 轮；仍败 → 回退原文 + `fault` 标记。**反馈字段化优先**：校验异常字符串塞 `previous_validation_error`/`slot_validation_failures` 字段（texglot 结构化方案）比对话式更稳。

### 1.3 批量协议

- 分桶：`content < 300 字符 → short`（打包编号批量），否则 long（逐条单翻）。
- 打包：short 桶贪心装箱 ≤2000 字符/批（**按 token 控可放宽 ~2000–4000 tok ≈ ≤8000 字符**——成本实测：prompt 摊销占输入 68%，批阈值是最大杠杆）；编号 `[1]…[n]` 协议，`@@` 兜底，响应按 `\[(\d+)\]` 解析。
- 回退：数量不符/序号越界/解析失败 → **整批退化逐条单翻**（复用并发额度）；超大原子 chunk 先切分再入批。
- 跳过：纯占位符 chunk（`^[[TYPE_n]]$`）不发请求，translation=source 直落盘。
- 换行编码：段内 `\n` 编码为 `[[SL]]` 送翻、回来解码；分段边界在 chunk 层管理（勘误 2026-09-17：impl 另有两枚防御 token——`[[PL]]` 编码 `\n\n+` 空段保底、`[[SP]]` 保护 `\ ` 强制空格，`placeholders.py:51-64/95-149`）。

### 1.4 术语表（三级 + 恒等注入 + 文档级烤进）

```
① 用户表  ~/.texlate/glossary.yaml | --glossary user.csv  → 最高优先，独占覆盖
② category 表  terms/{primary_cat}.csv（+ 次 category 并集，先命中先写）
③ 内建默认表  terms/default.csv                           → 兜底
```

- 格式：CSV 两列无表头 `en,zh`；"保原语"条目一等公民（`AGI,AGI`/`LLM,LLM`）。
- **ph→ph 恒等注入**：文档全部占位符 `glossary[ph]=ph` 混入表（优先级最低不覆盖真术语）——占位符保护从"请你别动"软约束升级为术语表硬约束，零额外 token。
- **文档级过滤 + 整表烤进**：启动时扫全部 chunk 源文本，`(?<!\w)term(?!\w)`（IGNORECASE|ASCII）筛出本文实际出现的术语 → `doc_glossary` 序列化为 `- en: zh` 行表追加 system prompt 末尾——整篇翻译期间 system prompt **逐字节不变**（前缀缓存：Anthropic `cache_control`，OpenAI/DeepSeek 自然前缀命中）。排序稳定（TYPE 字典序+n 数值序）是缓存命中前提。
- 论文级覆盖：`output/{paper}/glossary.local.yaml`（优先级介于 user 与 category 之间）；产物落盘 `term_dict.json`。
- 运行时术语自增：可选开关**默认关**（自动抽取质量参差，污染全局表得不偿失）。
- 种子表：LaTeXTrans `terms/` 六表（default 404 + cs.LG/RO/ML/AI/CV）；category→file 映射 `terms/index.yaml`；缺口领域（hep/math/cond-mat/eess）后续众包。

### 1.5 判定分工与 LLM-judge

| 判定             | 首选手段                                                                                     | LLM 时机                  |
| ---------------- | -------------------------------------------------------------------------------------------- | ------------------------- |
| env 可译性       | 黑名单（math/verbatim/figure/table/algorithm/bib 全族）+ 白名单（proof/itemize/abstract 等） | 未知 env → judge          |
| 段内可译自然语言 | 规则：无拉丁字母跳过/全大写跳过/纯占位符跳过                                                 | 灰区默认翻（fail-open）   |
| 宏透明性         | 宏表静态分析（docs/07 §5.1）                                                                 | v0 不做                   |
| 编译修复         | fixloop 规则表                                                                               | 未命中 → LLM 修复器（§5） |

env judge 参数：**temperature=0、max_tokens=16、3 次重试、解析 `true/false` 小写、其余一律 True（fail-open 宁翻勿漏）**（勘误 2026-09-17：impl `ENV_JUDGE_TEMPERATURE=0.01`，`prompts.py:347`——本网关 temperature=0 直接 502，0.01 即近确定性且通行）；判 content 非 env name；6 few-shot 成稿（含 `\caption` 内嵌→True、纯公式/绘图→False 灰区）。判 False → 整体 `[[ENV_n]]`；判 True → `env_text` chunk 送翻。

### 1.6 并发 / 重试 / 断点

- `asyncio.Semaphore(10)`（按 provider 限额 10~50 可调）；**首发单飞暖前缀缓存**，其余并发。
- 退避：指数 `retry_delay·2^attempt`（429 用 `3^attempt` 下限 5s；timeout 下限 10s；`Retry-After` 从其值）；3~5 试；失败回退原文 + `skipped`+`skip_reason` 不阻塞整批。（勘误 2026-09-15 B4a 实测：本网关 429 的 retry_after 在 **body `error.retry_after`（秒）** 而非 HTTP header——解析序 body→header→默认退避；429 系多租户共享流量触发，与本地并发宽度无关。）
- 温度：翻译 0.2~0.3；judge/抽取 0。
- **重试阶梯**：整段×2（字段化反馈）→ 行级修复（闭合 scope 边界按句号切）→ slots JSON 兜底（`⟪S0000⟫` 槽位、`response_format json_object`、8 槽/批、**失败槽只重问失败批**）→ 三振 `fallback_orig` + warning → `partial` 终态（勘误 2026-09-17：`fallback_orig` 在 impl 块级落 `status=fault`+`skipped` 标记，`partial` 是论文级终态语义；块级 `partial` 另有出处=阶梯 recovered，见 §6）。
- `recover_copied_tokens`：模型把受保护原文抄回时，**唯一出现**才换回 token（exact+unique 才修，不瞎猜）。
- HTTP 层：状态码分类表（401/403 认证、402 余额、404 地址、408/409/425/429/5xx 重试 ≤2、余 4xx 拒、`finish_reason==length` 截断错）；`redact()` provider 无关脱敏。
- **断点**：`state.json` 逐块原子落盘 `{version, meta{model,pipeline_version,total_chunks}, completed[], results[], errors_report[]}`；中间产物五表 `chunks_map/placeholders_map/glossary/state/errors_report`——重建器只读 map 表。
- **段级缓存键**：`sha256(source + role + 失效标签 + masked/protected 快照)`——失效 tag 按需追加（accent/声明/数量级命中才加），masked/protected 快照使 token 布局变则 key 变；文件级键 `sha256(prompt_version+base_url+model+lang+glossary+context)`。**prompt 措辞任何改动必须 bump `prompt_version`**。
- `atomic_json`：tmp+rename+0600；缓存读入逐条再校验，损坏文件隔离不删。

### 1.7 本地默认后端（实测定案）

`http://127.0.0.1:3003/v1/chat/completions` + **`swe-2-medium`**（free tier：大样本硬契约 100%(80/80)、reasoning p50=98 字符、5.9s/chunk）；备选 `swe-2-high`；`swe-2-max` 留修复器；禁用 `swe-1-7*`。免费集运行时动态筛（`/panel/api/models` `cost_tier==free` ∧ promo.active + `/v1/models` 求交 + 探活）。硬约束：每请求 ~160–566 隐藏 prompt token（网关注入 agent 系统提示，批内摊不掉）；reasoning 档 effort=模型名后缀；清单≠可用须实测白名单。付费对照 `glm-5-3-low`/`claude-sonnet-5-medium`。外部 BYOK 走 `provider_for_url` host→provider 预设表。（勘误 2026-09-17：默认后端 impl 实为 tailscale `http://100.105.212.52:3003`——`settings.py:40`/`cli.py:672` 同款，`127.0.0.1` 仅 `client.py` docstring 残留；禁用表 impl 精确两枚 `{"swe-1-7","swe-1-7-medium"}` 非 `swe-1-7*` 通配，`client.py:53`——新 `swe-1-7-*` 变体会逃逸；付费对照 impl 偏好表第 4 位是 `glm-5-2` 非 `glm-5-3-low`，`client.py:51`；`claude-sonnet-5-medium` 付费对照全代码无踪迹——impl 偏好表共 4 枚全免费模型+denylist 两枚，若属有意取消 spec 已追记。）

## 2. 校验链（`validate/`）

三层分工，**全部 src↔zh 相对判定**（"译文不得比原文更坏"——src 自带不平衡继承容忍，只报新增损伤）。

### 2.1 L0 规则层（stdlib，always-on，0.57ms/对）

| rule          | 检查                                                                                                     | error                                                                  | warn                      |
| ------------- | -------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------- | ------------------------- |
| `placeholder` | `[[A-Z_]+_\d+]` multiset diff + 模糊候选 lev≤2 配对（`[[..]`/`[X_1]`/`【..】`）                          | 缺失/多余/拼错（附修复建议）                                           | —                         |
| `brace`       | `{}` 平衡（`\{\}` 转义、`%` 注释豁免）                                                                   | zh 前缀深度 < src 或净余额 ≠ src                                       | 计数不同但净额一致        |
| `env`         | `\begin/\end` 栈配对 + env 名 multiset diff                                                              | 多余 end/不匹配/未闭合/新增或丢失 env 名                               | end 名偏多                |
| `key`         | `\cite*/\*ref/\label/\bibitem/\bibliography` key multiset（逗号拆分、`[..]` 豁免）                       | src−zh 漏 key                                                          | zh−src 新增（幻觉引用）   |
| `math`        | 未转义 `$` 计数 + `\(\)\[\]` 成对                                                                        | 任一计数 ≠ src                                                         | `$` 奇数（继承自 src）    |
| `length`      | zh/src 长度比 + 剥占位符后 CJK 占比                                                                      | —                                                                      | 比出 [0.25,2.50]；CJK<30% |
| `macro`       | zh 控制序列集合 − src 集合（**+ src 命令多重集 ⊆ zh 方向检查**：`\`/`\,`/`\;`/`~` 脆弱间距命令防丢失型） | 命中结构族（`begin/end/documentclass/newcommand/usepackage` 等 31 个） | 其余新 cs                 |

实测：10 类破坏 100% 检出（1323 例）、313 干净对 0 error-FP、135/138 拼错给 lev≤2 修复建议。**大样本再修**：占位符严格序守恒降软信号（`of X`→`X 的` 合法换序 ~95%）；`cs_dropped`（脆弱命令计数差）升硬判据（抓到 `\`+中文熔成 `\和` 未定义 cs 全部真炸弹）。（勘误 2026-09-17：impl `l0.py` 共 12 项 `_check_*`——上表 7 行外另有 `_check_ph_anchor`/`_check_item_glue`/`_check_ph_in_cs`/`_check_bare_cs`/`_check_protocol_echo` 未入表。）

### 2.2 L1 tree-sitter CST 层（可选组件 `texlate[ts-validator]`）

- **必须 baseline 相对模式**（`ok_relative`）：73.7%（42/57）真实主文件自带 grammar 空隙 baseline ERROR——绝对判定在真实语料上不可用；相对模式按计数比对，位移不影响。
- 检查项：ERROR/MISSING 节点（startByte/row/snippet）、env 配对（Query 抓 begin/end/generic_command/裸 begin/end 叶）、unclosed_math（CST 叶计数——verbatim/comment 内 `{}`/`$` 天然免疫）、brace_balance、placeholders 契约 diff（同 L0）。
- 独有能查：node 级定位（破坏点 ±1B / 容器区域级）、`\end` 改名（语法上合法 generic_environment，必须自做名字比对）、ERROR 区内退化形态恢复。
- 工程：JSONL 批处理 stdin/stdout 常驻进程（逐块 spawn 50ms 不可行，批处理摊薄 <1ms/块；chunk 级进程内 0.7–2ms）；分发 = validator.js + 两 npm 依赖随包作 data，`shutil.which("node")` 探测、无 node 优雅降级 L0。
- 已知 grammar 坑四个已覆盖（`\end` 改名不报 ERROR 等）。

### 2.3 L2 编译 log 回灌

- 错误计数**双格式**：`^!` + `file:line:`（只数 `!` 漏全部引擎级错误）。（勘误 2026-09-17：`_FILE_LINE_RX` 扩展名字符集放宽到任意 `[A-Za-z0-9_-]{1,10}`——file:line: 报任何被当输入读的文件（`.eps`/`.pdf_t`/`.lbx`/`.tikz`/`.end` 实测全真错，loop1 7814 log 全扫、扩展名白名单漏 586 行真错含 3 例整体 ok=True 假干净）；行首 `(`/`!` 与 `:`/空白内嵌仍排除。`_NONERR_FILELINE_RX` 反向剔除非错误形——`{LaTeX,Package,Class} … Warning` 行（部分引擎/包给 warning 也打 file:line: 前缀，不排则 `n_errors==0` 干净门永不通）与 `==> Fatal error` 汇总尾行（同一失败复述多计，corpus_v2 2002.05660 实测）。）
- `parse_log`：首个 `^!` 行 + 其后 8 行 ctx + `!` 总数 + tail 30 行；ctx 内 `l.(\d+)` 行号 + `(` 开括号文件栈追踪（file_stack 定位出错 .tex/.sty，供 rewrite 规则缩小作用域）。（勘误 2026-09-17：runaway 扫描错 `File ended while scanning` 单列 `eof_file` 字段——`)` 弹出已把肇事文件退栈、错误行报的是父文件 `\input` 续行位，取错误行前 `_EOF_POP_WINDOW=16` 行内最后弹出文件；存储面 `errors ≤200` 条（`n_errors` 仍精确计数）、每类 warning 样例 ≤5 条。）
- 注意：tectonic 有时**不写 .log**——监控不能假设 log 存在。
- 不过 → 重译该块（错误描述进反馈字段）→ 再不过 → fallback 原文。（勘误 2026-09-17：L2 回落原文并重 splice 后**未再编**——`e2e.py:746`/`worker.py:3046` 置 `fallback_unverified=True`，终判 verdict 对应回落前源树（PDF 产物为 stale），由后续 fixloop 代验；裁断维持现状——verdict 名如实标记即诚实面，对已败格再烧一轮编译不值。）

## 3. 归一化层（`compile/normalize.py`）

### 3.1 方法论：visible_tex 遮蔽视图 + 逆序 span 回放

- 所有正则定位打在 `visible_tex()` 上：verbatim/Verbatim/lstlisting/minted/filecontents/comment 环境 + `\verb` + 行内 `%` 注释**等长空格遮盖**（`\n` 保留 → 行号不变、offset 保持）；编辑列表 `(start,end,replacement)` **逆序**应用到原文。
- 定位视图 ≠ 改写目标：绝不能把 masked view 拷回去（注释行变空行、断跨行参数）。
- 所有删除保持行号稳定（`replacement += "\n" * count` 补回换行）——错误可回溯源文件行号。

### 3.2 无条件手术清单（顺序执行）

1. `normalize_comment_terminators`：`\end{comment}` 行尾空白剥掉。
2. `normalize_float_positions`：float 位置参数非法字符剥掉。
3. `normalize_pdftex_features`（tectonic/xelatex 时）：`\pdf{compresslevel,objcompresslevel,minorversion,majorversion,gentounicode}` 系赋值整段删 + `\input glyphtounicode` 删；microtype `expansion/spacing/kerning`（tectonic 再+`tracking`）选项 → `=false`。
4. `normalize_pixel_dimensions`：尺寸语境 `Npx` → `N\pdfpxdimen`（**语境受限**，非全局 sed）。
5. 兼容前导块按需前插（注入点 = `\begin{document}` 前——勘误 2026-09-17：impl 三兼容块插**文件顶**，`text = BLOCK + text`，`\PassOptionsToClass` 语义所迫）：PIXEL_COMPATIBILITY（`\pdfpxdimen` polyfill）、XETEX_COMPATIBILITY（microtype TU 限定 + breakurl `\ifpdf` 暂存 + quantumarticle PassOptions + pstricks typeout 探针）、TECTONIC_FONT（bbm→dsrom/dsss 向量字体 shim）。
6. `\PassOptionsToPackage{no-math}{fontspec}` 前插。
7. **剥 inputenc/fontenc**：解析 `\usepackage{..}` 名字列表只剔 `{inputenc,fontenc}`，其余保留。
8. 删 `\pdfinfo{...}`、删 `\pdfoutput=1`；驱动选项 `pdftex→xetex`（只改 hyperref/graphicx/graphics/color/xcolor 可选参内的独立 token）。
9. OT1/T1/LY1 → TU 字体族：`ptm→texgyretermes` 等映射表 + `\usefont/\fontfamily` 改写 + `\newfontfamily` 定义块插 `\documentclass{}` **后**（自定义 NFSS 族跳过；不改作者默认字体，只给显式 Type1 选择提供 Unicode 等价物）。
10. `normalize_legacy_cjk`：`CJK/CJKutf8` → xeCJK+Fandol（lualatex→luatexja）。
11. `use_bundled_bibliography`：`.bib` 缺失但有 `.bbl` → `\bibliography{x}` → `\input{x.bbl}`。（勘误 2026-09-17：改写目标非 `x.bbl` 而是**声明文件词干** `.bbl`（`path.with_suffix(".bbl")`）相对编译 cwd 的 posix 路径——`main.tex`→`\input{main.bbl}`、`chaps/one.tex`→`\input{chaps/one.bbl}`；前置：该 .bbl 存在且含 `\begin{thebibliography}`、relpath 不越 `..`（`openin_any=p` 拒 `../` 引用）；多只 `\bibliography` 只换首个有缺库者（.bib 存在性以编译 cwd 为基准）；visible 已含 `\input{<target>}` 即整体不改——工程级幂等防逐跑累加重排书目。）
12. `rebase_project_paths`：`\input/../foo.tex` 越界引用重写为包内正确相对路径。
13. `_transcode_support_files`（树级，非文本 span；勘误 2026-09-17：spec 原名 `_transcode_aux_bib`，impl `normalize.py:981`）：`.bib/.bbl/.bst` + `.aux` 系可再生中间产物非 UTF-8 → UTF-8 转码写回；中间产物另加 8192B 截尾整形（`_trim_intermediate_tail`——XeTeX 写缓冲在边界劈断多字节字符，`\@newl@bel` 扫过 EOF 比非法字节更致命；立项 `research/latex/2026-09-16-aux-cjk-truncation.md`，`4a8d5ce`/`b6ba25a` 系）。（勘误 2026-09-17：impl 另有 3 项未记档手术——`_neutralize_junk_files`/`_shadow_broken_system_packages`/`_sanitize_ps_comments`。）（勘误 2026-09-17：树级手术/审计面统一豁免隐藏路径——任一路径段以 `.` 前缀即整体跳过（`_hidden_path`；`_normalize_tex_files`/`_tex_sources`/`rebase_project_paths`/`source_path_violations`/`_neutralize_junk_files`/`_transcode_support_files`/`_collect_pending_refs` 同口径）；单件读/写 OSError 不中断整树——跳过保持原样，debug 落日志不进 rewritten 台账。）

**分工铁律**：归一化层做无条件手术；条件性手术（microtype/times→newtx 等）留 fixloop——两边不得重复改同一处。

### 3.3 中文注入

- 默认 **ctex `[fontset=fandol,UTF8]`**（hjfy 同款、双引擎实测可编译、白拿节名汉化）；**xeCJK+fontspec 为降级路径**（ctex 冲突签名→fixloop 或探测编译切换）。两路径共用注入缝：兼容块 → **文件顶**（勘误 2026-09-17：非 `\begin{document}` 前，PassOptions 语义要求）；字体系块 → `\documentclass{}` 后。
- `\documentstyle` → **禁止注入**（inject 层兜底拒，账本记 `inject_reject:latex209`——勘误 2026-09-17：`inject.py:576` 先走 `upgrade_209` 转换器，仅不可转（ds@ 类/no_target）才抛拒，「禁止注入」是兜底语义）；路由侧改判 `latex209_suspect` **先试编**、真 2.09 签名（tail 侧 `\documentstyle`/`LaTeX 2.09 COMPATIBILITY MODE`）由 fixloop gate `latex209_reject` 拒绝 → 降级链（改判 `38cc0a7`，推翻 05 裁决 13 的"无条件 reject"——05 已加注）。
- FLOAT_SIZING 仅在有 figure/table 时注入（`\resizebox*` 缩超高 float + typeout 回读）；TABLE_FITTING hook threeparttable（`adjustbox{max width=\linewidth}`）。（勘误 2026-09-17：TABLE_FITTING 判定在 `prepare_chinese` 末段对 `visible_tex(new_text)` 无条件扫 `threeparttable`——status=already 工程再进亦生效（出分支统一判，非仅新注入路径）；`\begin{document}` 锚 `_BEGIN_DOC_RE`=`\\begin\s*\{document\}` 空白容忍，`.search` 与 `.split(maxsplit=1)` 切正文同正则；`_closure_has_document` 允许 bd 落在 `\input` 闭包内——主文件不含但 include 图可达即放行。）
- `embed_cjk_mappings`：编译后给 Identity-H/Adobe-GB1 无 ToUnicode 字体注 `Adobe-GB1-UCS2` cmap——中文 PDF 可复制可搜索。

### 3.4 target_probe 与 compiled_dependencies

- **target_probe**：翻译前先以"译文桩"替换英文词编译一遍（免费），暴露字体/模板问题再花钱；探针失败直接进 fixloop。落地注记（2026-09-16）：`compile/probe.py` 已落（`54e1c4b`，声明依赖预扫 + `.fls` deps diff + `latex209_suspect` 标记）；worker 接线为 **best-effort 旁路**（`worker.py::_probe_target`——依赖计数/`tl_pkg` 可装清单/`prefer_engine` 分歧只进 log 播报，探针崩溃不阻塞编译，装包仍归 fixloop/tlmgr）。（勘误 2026-09-17：译文桩预编译原形态未建——按落地注记口径为静态探针旁路合规；「探针失败直接进 fixloop」语义不存在，prefer_engine 分歧只进 log。）
- **compiled_dependencies 为翻译文件集权威**：`.fls` INPUT 行 / tectonic `--makefile-rules` 决定翻哪些 .tex；静态 `\input` 图只作编译失败时降级。落地注记：`dep_seen`/`deps_diff` 已随 probe 一并接入 worker（`54e1c4b`）。

## 4. 引擎层（`compile/engine.py`）

### 4.1 Engine 协议

```python
class Engine(Protocol):
    caps: set[str]                    # {kpsewhich,tlmgr,updmap,shell_escape,bundle}
    def compile(wdir, main, passes=2) -> CompRes    # pdf?, log_path, timed_out
    def probe_file(fname) -> str | None             # kpsewhich | 本地+bundle 探测
    def install_file(fname, font_related) -> bool   # tlmgr | ctan_fetch 降级
    def rebuild_fontmaps() -> None                  # updmap-user | noop
    def filemap(fname) -> list[str]                 # file→pkg 索引
```

（勘误 2026-09-17：impl 实为 9 成员——`name: str`、`caps: frozenset[str]`、`detect()`、`compile()`、`probe_file(fname, *, cwd)`、`install_file(fname, *, font_related)`、`rebuild_fontmaps() -> bool`、`filemap()`、`parse_log(res) -> LogInfo`，`engine.py:822-894`；`shell_escape` cap 全代码无踪迹——`XelatexEngine.caps={kpsewhich,tlmgr,updmap,recorder}`。）

- xelatex：`-no-shell-escape -interaction=nonstopmode -halt-on-error -file-line-error -recorder`，≤2 pass，timeout 240s（勘误 2026-09-17：消费方均传 `halt_on_error=False` 对齐 bench 产出——worker.py/e2e.py 刻意参数，fixloop 内部引擎才用默认 True）。
- tectonic：`-X compile --untrusted --keep-logs --keep-intermediates --makefile-rules <deps.mk> --hide secrets` + `-Z continue-on-errors`（post-spec 加注对齐 nonstopmode）；`TEXINPUTS` 不认——等价物 `-Z search-path`（勘误 2026-09-17：被 `_TECTONIC_Z_OK` 白名单安全面封锁，`engine.py:77`）；bundle pin `tlextras-2022.0r0`。

### 4.2 路由与兜底

**静态预检路由表**（编译前即可决策）：

| 检测                                            | 路由                                                                                         |
| ----------------------------------------------- | -------------------------------------------------------------------------------------------- |
| `\documentstyle`                                | **`latex209_suspect` 试编**（inject 拒注入；真 2.09 签名由 fixloop gate 拒，`38cc0a7` 改判） |
| `*.eps` / `\usepackage{pstricks}` / `pspicture` | **跳过 tectonic 直走 xelatex**（硬墙）                                                       |
| `frozencache` + minted                          | tectonic 优先（bundle v2.6 兼容 v2 缓存）                                                    |
| bbm/dsfont 类位图字体包                         | tectonic 高风险 → 失败后换 xelatex                                                           |
| 非 UTF-8 源（latin-5 等）                       | iconv 转码预处理 或 latex 路注 inputenc                                                      |

- **M0 开发默认 xelatex**（fixloop 地面真值、tlmgr 可修性实测最高：7 FAIL → 7 可推进、链深 1–5 轮）。
- **分发默认 tectonic 优先 + xelatex 兜底**：便携无 tlmgr 依赖、初始 clean 率更高（7/12 vs 4/12）、热缓存 ≤22s；失败集几乎互补（联合 clean 9/12，全灭仅 hep-th）。
- tectonic 三大硬墙（换引擎信号）：EPS/PS 图（xdvipdfmx 不支持）、bundle 缺物理字体（`.vf or physical font`）、bundle 包版本旧语义错（不可选版只能换引擎）。

### 4.3 clean 判定三件套（判据，非修复）

`clean` = ① 有 pdf ② `!`≤3 且首错非 missing_*/undefined_cs ③ **log warning 扫描**：`Invalid UTF-8 byte` / `Missing character`（勘误 2026-09-17：impl 红线为全 `missing_glyph` 族——CJK/U+FFFD/码点不可解三类，`l2.py _REDLINE_CLASSES`，不限 U+FFFD 一形）/ tectonic `File.*not found` 降级行 / missing_graphic 红线——任一命中即 dirty。另加**中文实际渲染检查**（`Missing character` 计数==0 或 PDF 字体表含 CJK——hep-th 0 中文字节是全线最坏静默失败）。`partial` = 有 pdf 但 dirty。

> 勘误（2026-09-16，F3 改判 `87e6a40`）：**策略拒绝不再单列 `reject` 终态**——route/inject/fixloop 三处拒绝统一归 `partial` + `reject_at ∈ {route, inject, fixloop}` 审计字段（语义：拒绝是降级交付不是 fault；worker `_reject` 与 e2e `run()` 同形，`cli.py` 对 `reject_at` 保持 exit 2）。§5 verdict 词汇表同此口径。

> 复核（2026-09-17，红线类集两层各一份、命名不同构）：`engine.py WARNING_RED_LINES` = `[invalid_utf8, fffd_glyph, missing_chars, missing_graphic, degraded_file]`（warning 扫描/judge 面；`degraded_file` 即 tectonic 缺包静默降级行 `^!.*(File|package).*not found`——continue-on-errors 跳包出残页 pdf 的暗雷）；`l2.py _REDLINE_CLASSES` = `{invalid_utf8, missing_glyph, missing_glyph_cjk, fffd_glyph, file_not_found}`（log 回灌面）——按层查名勿求字面全等。`Missing character` 码点形态随引擎代际分叉：老 TL 打 `("8FD9)`、新 TL 打 `(U+8FD9)`（`_MISSING_CHAR_RX` 双形态并收，corpus log 并存、U+ 形约 1/3）。系统 texmf/bundle 件与 dos-eps（魔数 `\xc5\xd0\xd3\xc6`，normalize `dos_eps_skipped` 原样保留的二进制件）的红线命中**降级进 `sys_hits`/`warnings_sys` 观察项**、命中串尾挂 `(dos-eps)` 标（l2 `_mark_redline` 与 engine `_scan_error_lines` 同口径）——老 CTAN 包自带坏字节非工程红线（invalid_utf8 系统件 loop1 归因占 96%）；文件栈 None 帧由 `_patch_graphic_top` 按 graphic 引用 token 补位归因。

### 4.4 编译沙箱

`--untrusted`（tectonic）/ `-no-shell-escape`（xelatex）+ **env 白名单**（非黑名单；加 `TECTONIC_UNTRUSTED_MODE=1 openin_any=p openout_any=p shell_escape=f`）+ macOS sandbox-exec profile（deny `$HOME` 读 + 全写，白名单放行工程/输出/缓存/字体目录——settings.json/浏览器 profile/SSH key 编译期不可读）+ `killpg` 进程树超时杀。（勘误 2026-09-17：impl `sandbox_wrap(allow_net=…)` 分档——`allow_net=False` 追加 `(deny network*)`（sandbox-exec profile 尾）/`--unshare-net`（bwrap），xelatex 工具链全本地走 False、tectonic True（bundle 拉取要网）；`start_new_session` 独立进程组 + `killpg` 杀整树，触发面不只超时——`run_process` 在 TimeoutExpired **与一切 BaseException**（KeyboardInterrupt/GeneratorExit）路径都 `_kill_tree` 防孤儿，killpg 失败退 `proc.kill` 单杀；setsid/双 fork 逃逸的孙进程仍握 stdout 写端，二段 wait 超时由调用点兜。）

> 落地注记（2026-09-16）：Linux 侧 bwrap 包装已落 `compile/sandbox.py`（`b260378`；darwin 走 sandbox-exec，`TEXLATE_NO_BWRAP=1` 逃逸开关）+ `tests/test_compile_sandbox.py`。（勘误 2026-09-17：bwrap 三件套实在 `compile/engine.py`——`_bwrap_capable/_bwrap_mounts/_bwrap_wrap`；sandbox.py 只有 env 白名单+sandbox-exec+killpg。）

## 5. fixloop（`compile/fixloop/` 包）

### 5.1 两层 YAML：`taxonomy`（log→类别）+ `rules`（类别→动作）

> **勘误（2026-09-16）**：实现为 `compile/fixloop/` 包（engine/cases/ctan/logparse/\_yamlish/rules.yaml）；
> taxonomy 段现为 37 个 pattern 条目、rules 段 **36** 条（v3 整改 + 后续扩表：pstricks_dvips_preflight/eps_route/eps_to_pdf/legacy_pkg_shim/font_sub_shim/aux_scan_eof/split_glued_cs 等，HANDOFF-2026-09-16 §2.2/§6——勘误标注：此列名混层，`aux_scan_eof` 实为 category（消费规则 `aux_purge_regen`）、`split_glued_cs` 实为 builtins 内部 helper `_split_glued_cs`（builtins.py:1013），余者才是规则 id）。（勘误 2026-09-17：实 **42** taxonomy/**52** rules——计数持续滞后，以 rules.yaml 为准。勘误 2026-09-17 复核：**39** taxonomy 条目/**32** category/**59** rules——`ff1a811` 一波 +4：ntheorem_style_undefine/already_def_undefine/acro_v3_key_rename/restore_support_from_src，另 detector 扩 already_def 双签 + cs_table 扩期刊宏与字体熔合族。）（勘误 2026-09-17 三复核：**46** taxonomy 条目/**36** category/**62** rules（2 gate+2 precheck+58 loop）——`9d9ebe5` 新增 category `cannot_patch_macro`/`runaway_scan`（消费规则 biblatex_bbx_rename:161/detab_end_scanlines:164）；`env_mismatch`/`float_opt` 有 taxonomy 条目尚无消费规则（实消 34 cat）。另：文件实为**三层**——顶层 `warnings:` 段（4 warn_id：invalid_utf8/missing_char/missing_graphic/tectonic_degrade）载 warn-driven fix 的签名面， taxonomy/rules 之外独立；rules.yaml 头部自注释"36 条:2+2+32"自身已陈旧。）

phase：`gate`=每轮分类后最先评估 / `precheck`=编译前一次性 / `loop`=每轮错误驱动；同 phase 按 order 升序、**每轮只应用一条**（便于归因）。

| #   | id                   | phase/order | 触发                                         | 动作                                                             |
| --- | -------------------- | ----------- | -------------------------------------------- | ---------------------------------------------------------------- |
| 1   | `latex209_reject`    | gate/1      | `latex209` ∨ `missing_file`+`\documentstyle` | reject_route                                                     |
| 2   | `static_precheck`    | precheck/0  | always                                       | 扫 `\usepackage/\RequirePackage/\documentclass`→filemap 批量装包 |
| 3   | `install_file`       | loop/10     | `missing_file`                               | filemap 查包→安装→复核；字体扩展名装后重建 map                   |
| 4   | `install_tfm`        | loop/20     | `missing_tfm`                                | 装 `{pay}.tfm` 所在包 + updmap                                   |
| 5   | `install_sysfont`    | loop/30     | `fontspec_missing`                           | `{pay}.otf/.ttf/.ttc` 搜包装 + updmap                            |
| 6   | `missing_pfb_updmap` | loop/40     | `missing_pfb`                                | `updmap-user` 重建 map                                           |
| 7   | `pdftex_prim_guard`  | loop/50     | `pdftex_prim`                                | 13 个 `\pdf*` 原语套 `\ifdefined…\fi`（lookbehind 幂等）         |
| 8   | `px_to_bp`           | loop/60     | `illegal_unit`                               | `N px`→`N*0.75 bp`（算术函数）                                   |
| 9   | `microtype_off`      | loop/70     | `xetexglyph_tfm`                             | microtype 强制 `[protrusion=false,expansion=false]`              |
| 10  | `times_to_newtx`     | loop/80     | `xetexglyph_tfm`                             | `{mathptmx/mathptm}`→`{newtxtext,newtxmath}`                     |
| 11  | `hyphenation_sane`   | loop/90     | `hyphenation`                                | `\hyphenation{}` 只留 `[a-zA-Z-]` token                          |
| 12  | `soul_cjk_mbox`      | loop/100    | `soul_err`                                   | `\hl/\ul/\st/\so/\caps` 含 CJK 参数套 `\mbox`                    |
| 13  | `thm_sibling_strip`  | loop/110    | `already_def`                                | 剥 `sibling=\w+,?`                                               |
| 14  | `option_clash_merge` | loop/120    | `option_clash`                               | 同名包重复加载→合并选项到首处 + 注释后处（builtin）              |
| 15  | `minted_frozencache` | loop/130    | `minted_froz`                                | `{minted}`→`{minted2}` 一行替换（v3 吃 v2 缓存报 50 错实测）     |
| 16  | `undefined_cs_guess` | loop/900    | `undefined_cs`                               | escalate_llm（恒最后兜底）                                       |

动作原语 7 种：`scan_install / install_file / run_tool / regex_rewrite / builtin_transform / reject_route / escalate_llm`。命名函数注册表仅 3 个（`px_to_bp`/`keep_latin_tokens`/`option_clash_merge`）——社区新规则多数只写 regex，新函数才需 PR 代码。（勘误 2026-09-17：impl `TRANSFORM_FNS` **21** + `REWRITE_FNS` **2**，`builtins.py:142/1844`。再勘误同日：**22**+2，`builtins.py:144/2147`——`827674d` 增 `accent_mark_fix`。）

**顺序不变量**：gate 先于一切（`missing_file`+`\documentstyle` 必须先拦，否则给 2.09 白装包）；install 先于 rewrite（缺包时不许动源码）；同 trigger 保守→激进（microtype_off 70 < times_to_newtx 80 + `(rule_id,payload)` dedup）；兜底恒最后（order 900）。防干扰：同 `(cat,pay)` 签名连续 3 轮 → `stuck`；rewrite 幂等逐条审过。

### 5.2 新增规则（实证缺口回填）

| id                            | 触发/检测                                        | 动作                                                                                          |
| ----------------------------- | ------------------------------------------------ | --------------------------------------------------------------------------------------------- |
| `pdftex_prim_polyfill`        | 读取型 `\ifnum\pdfoutput`（现 guard 只管赋值型） | `\ifdefined\pdfoutput\else\chardef\pdfoutput=1\fi`                                            |
| `vendored_sty_shadow`         | 工程自带旧 .sty 遮蔽已装新版                     | **按 ProvidesPackage 日期比较 + 错误触发** rename 隔离（盲删必死——同目录 cls 可能是唯一来源） |
| `minted_v3_rewrite`           | xelatex minted v3 × v2 frozencache               | `{minted}`→`{minted2}`                                                                        |
| `eps_route`                   | 静态扫 `*.eps`/pstricks                          | 不进 fixloop 直接路由 xelatex                                                                 |
| `non_utf8_source`             | xelatex 静默 U+FFFD                              | 上游 iconv 转码或 inputenc 注入                                                               |
| `pstricks_dvips_fallback`     | dvips 兜底                                       | `.pro` preflight（pst-tools.pro）（勘误 2026-09-17：impl id 为 `pstricks_dvips_preflight`——gate/0 相位语义超前于 loop fallback 命名） |
| `bbl_stub_shadow`（tectonic） | 有 .bbl 无 .bib                                  | `\bibliography{x}`→`\input{main.bbl}`，阻断自动 bibtex stub 遮蔽真 bbl                        |
| `font_sub_shim`（tectonic）   | MF-only 字体包（bbm 等）                         | Type1 近亲（dsfont/dsrom）shim——物理字体投放是死路                                            |
| `ctan_fetch` 版本前置         | 命中包先比 expl3/LaTeX2e 版本要求                | 新版过新跳过（tlnet 只发最新，钉版需 historic tlnet/自建 pin cache）                          |

### 5.3 tectonic 降级与 ctan_fetch 原语

16 条中 11 条源改写天然引擎无关；5 条依赖 tlmgr/kpsewhich/updmap 需降级，其中 **4 条汇到同一原语 `ctan_fetch`**：

```
ctan_fetch = file→TeX Live 包离线索引（解析 texlive.tlpdb：
             8148 包 / 138K basename，0.14s 构建，随规则库分发 + overrides 手工表）
           → tlnet/archive/<pkg>.tar.xz 拉取 → 解包到工作目录
           （cwd 平铺遮蔽 bundle 实测成立：ctex 2.5.10 遮蔽 bundle 2.5.8 → 0 错）
           → 索引查不到 → advisory（附候选包名）
```

**仅限 TeX 输入层文件**（.sty/.cls/.tfm）；物理字体/xdvipdfmx 层须改写规则兜底；`install_sysfont` 拉到字体后需配套 `Path=./` 或 fontconfig 注册否则 advisory；`missing_pfb_updmap` 无替代物 → escalate 或路由回 xelatex。xelatex 侧 `tlmgr search --global --file` → `tlmgr --usermode install`（21 种实测装入 `~/Library/texmf`；`not relocatable` 落 `.ins` 兜底/放弃标记；搜索缓存落盘）。

### 5.4 主循环

```
fixloop(proj, eng, ruleset):
    ctx = {applied:set, actions:[], installed:[]}
    for r in ruleset.phase("precheck"): apply(r)          # 第 0 招
    main = find_main_tex(proj)
    for rnd in 1..max_rounds:
        res = eng.compile(wdir, main, passes=2)
        cat, pay = classify(parse_log(res.log))
        v = verdict_gate(res, cat, pay, ruleset.phase("gate"), ctx)
        if v: return finish(v)                           # clean / reject
        if (cat,pay) == prev_sig ×3: return finish("stuck")
        r = match(ruleset, cat, pay, ctx, eng)           # order 序+dedup+cond+caps
        if r is None: return finish("unfixable:"+cat | "dirty_pdf")
        apply(r); ctx.applied.add((r.id,pay))
    return finish("max_rounds")
    # finish(): final_pdf/errors 汇总 + case → cases.jsonl（沉淀原料）
```

终止判据：pdf+0 错→clean；cat clean/None→判 pdf；gate 命中→reject；sig×3→stuck。

> 落地勘误（2026-09-17，对照 `fixloop/engine.py`）：伪代码未画的已提交机制——**warn-driven fix rounds**（`meta.warn_driven_fixes` + `scope: warnings` 条目 warn_utf8/warn_missing_char + engine.py:1371 `warn_cats` 豁免——编译过但带红线 warning 也进修复轮）；**best-effort salvage**（engine.py:1402-1451 → `best_effort_pdf` verdict）；**floor_snap** 入场 PDF 回退 + `floor_from` 字段（engine.py:1273-1284/1456-1471——修复轮产出比入场更差时回退）；per-round `_sweep_bad_aux`。另超时分层：`meta.loop.timeout_sec=120` 是 fixloop 内部单轮编译预算（`fixloop(compile_timeout=)` 可覆盖），§4.1 的 240s 是引擎层墙钟——两层独立，非矛盾。

### 5.5 沉淀机制（"新失败 → 新规则"）

```
每格跑完 → cases.jsonl {corpus, cond, engine, rounds[cat/pay/rule/result],
                        verdict, log_excerpt}
    verdict ∈ {unfixable, stuck, dirty_pdf} → triage queue
        LLM/人工读 log_excerpt → 三类补丁之一：
          a) taxonomy 新行（新错误形态 regex→category）
          b) rules 新条目（已有类别修法：多为 regex_rewrite，少数新 function）
          c) filemap.overrides 行（索引查不到的 file→pkg）
    ▼ 回放验证（入库门槛）
      ① 本格重跑：新规则必须把 fail 修到 pdf
      ② 全语料回归：不得把任何 clean 格改脏（no-regression gate）
      ③ status: proposed → active；fires/rescues 计数回填 stats
```

要点：~80% 新失败落"已知类别变体"→纯 yaml PR；规则带 `stats.fires/rescued_cells` + `status: stub|proposed|active|retired`；`provenance` 必填（`corpus_id + error` 原文可回溯失败现场——hjfy 人肉库的开源等价物）；可选 **shadow 模式**（proposed 排 active 后试运行只记录"若应用会怎样"防抢位回归）。当前沉淀队列头号 case：`soul_cjk_mbox`（soul_err 不在现有 CJK-参数 pattern 内）；`undefined_cs_guess` 需 cs→pkg 知识库（fdsymbol/stix/unicode-math 符号包映射）。

实测覆盖：install 系 4 招 = 75/86 次触发（87%）；spike 22 格 16 原始失败 → 16 救回、15 clean。

## 6. 状态词表（各层 status/verdict 枚举对照）

四套枚举并存于不同层，字段名相近但语义域不同——读 records/cases 时按下表对号（audit-2026-09-16 wave2 deferred-4 收口）。

| 域 | 字段位置 | 取值 | 产出处 |
| --- | --- | --- | --- |
| 编译判决 verdict | `metrics.verdict.status` / `post.verdict.status` | `clean`（无错有 pdf）/ `partial`（有 pdf 有错或缺字）/ `fail`（无 pdf） | `compile/judge.py` |
| 记录态 status | stagerun records `status` | verdict 三值 + `reject`（inject 层拒绝，如 latex209）+ `skip`（上游门控豁免）（勘误 2026-09-17：与 §4.3 F3 口径并存分裂——stagerun 仍写裸 `reject`，e2e/worker 已落 `partial`+`reject_at` 字段；两写法并存待收口） | `bench/py/stagerun.py` |
| 块态 | chunk/segment `status` | `ok` / `partial`（阶梯 recovered）/ `fault`（翻译或校验错；`fallback_orig` 回退原文亦落 fault+skipped 标记）/ `skipped`（门控跳过）（勘误 2026-09-17：原表漏 `partial` 第四值，impl `pipeline.py:107/614-630`） | `xlat/pipeline.py` |
| 注入态 | inject `status` | `injected` / `already`（已有 CJK 支持）/ `no-docline`（无 documentclass 锚） | `compile/inject.py` |
| fixloop 判决 | cases `verdict` / `fixloop_verdict` | `clean` / `acceptable_pdf`（有 pdf 即收，misschar 档）/ `best_effort_pdf`（有 pdf 残留错）/ `dirty_pdf` / `unfixable:{cat}` / `stuck`（轮内无进展）/ `no_errors_no_pdf`（干净日志零页面）/ `reject:<rid>`（gate 直通）/ `no_main_tex` / `max_rounds`（勘误 2026-09-17：原表缺后三值） | `fixloop/engine.py`、`fixloop/cases.py` |
| 规则态 | rules.yaml `status` | `stub` / `proposed` / `active` / `retired` / `validated`（裁定 2026-09-17：**审计元数据非门控**——全部状态同序同权上场，排序/触发由 `order`+`when` 驱动；proposed→active 升迁走回放门 ③ 写 `stats`/复核，不拦 firing。bench 语义要"全手上场"，retired 例外=规则条目删除前位。勘误同日：impl 实际在用值为 stub×1/proposed×29/validated×5/**verified×4**（biblatex_bbx_rename/acro_v3_key_rename/ntheorem_style_undefine/already_def_undefine——表内枚举原缺 verified）；active/retired 零使用；另有规则仅 stats.fires 无 status 键） | `fixloop/rules.yaml` |
| 任务态 | job `status`（11 态机） | active：`queued`/`fetching`/`parsing`/`translating`/`compiling`；terminal：`done`/`partial`/`fault`/`cancelled`/`interrupted`/`needs_auth` | `server/store.py:150` |

跨段退化口径：终态 `fixloop.status` 不得低于上游 `compile.status`（clean>partial>fail>reject）；loop1 实证 17 格中 13 格为基建杀伤假象（修复后引擎直编出 pdf），真退化判定须直编复验。
