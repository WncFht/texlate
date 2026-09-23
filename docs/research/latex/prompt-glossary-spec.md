# 翻译层 prompt 套件与术语表设计 — LaTeXTrans / MathTranslate / ieeA 调研成稿

> **结论**：prompt 套件 = 六 kind 共享公共条款块 + 类型专属条款 + 占位符条款压轴 + 人名条款 + 文档级过滤术语表整表烤进尾部；占位符硬约束靠 `ph→ph` 恒等映射混进 glossary 实现；批量/并发/断点协议照 ieeA。
> **状态**：现行（已落地为 `xlat/prompts.py` + `xlat/glossary.py` + `xlat/terms/`；规范见 `spec/latex-pipeline.md`）
> **日期**：2026-09-15

## 1. 调研对象与分工裁决

三个参考实现各抄一块：LaTeXTrans[^latextrans] 的「分类型 system prompt + 尾置占位符条款 + 三级术语表 + ph 恒等注入 + LLM 判 env + 三段式带错重翻」骨架；ieeA[^ieea] 的「文档级术语表过滤 + 稳定前缀 + 编号批量 + state 断点」协议；MathTranslate[^mathtranslate] 只借「占位符工程细节（垫空格/大写刷回/受限展开白名单）」。

## 2. LaTeXTrans 证据

### 2.1 prompt 套件形态

15 个 system prompt 由 `init_prompts(src, tgt)` 填充语种，按用途四组：caption/section/env 三基础型（各含 with_dict 术语版、with_sum 摘要版、with_prev 上下文版）、`set_need_trans_for_envs`（LLM 判 env 可译性）、`retrans_error_parts`（带错重翻 corrector）、术语抽取/滚动摘要。

公共条款块（以 section 版为基准）：只翻自然语言内容、标题要翻但语法不动、不翻清单（控制命令枚举 + 数学环境 + **尺寸单位枚举** `em, ex, in, pt, pc, cm, mm, dd, cc, nd, nc, bp, sp`——`\vspace{-1.125cm}`、`[scale=0.58]` 保持原样，这条枚举非常具体值得抄）、转义特殊字符不改、已知与 CJK 冲突的宏（`\hl/\ctext`、soul/xcolor 系）参数保原语防编译炸、特殊符号两侧垫空格（中文排版换行痛点）、输出必须可编译、学术术语一致、只输出译文无解释无围栏。

**占位符条款位置规律**：section 版第 10/11 条、env 版第 9/9（末条）、caption 版第 8/9——始终压在条款列表尾部利用近因效应，且全文唯一一次出现（措辞逐字一致）。人名保原语条款（不译不音译不调序）仅 section 版压轴。

### 2.2 ph→ph 恒等注入（最妙一招）

翻译执行前把全部占位符注册为 `glossary[ph] = ph` 恒等映射——由于 prompt 宣称「glossary 是最高优先级规则」，**占位符保护从「请你别动」的软约束升级为「术语替换表规定它映射到自身」的硬约束**，零额外 token 成本。

### 2.3 术语表三级体系

user CSV（独占加载）→ 否则按 arXiv abs 页 `div.subjects` 爬 category 逐类映射 `terms/{category}.csv`（多 category 并集、先命中先写）→ 全不命中落 `terms/default.csv`。CSV 两列无表头 `en,zh`；种子体量 default 404 行 + cs.LG 357 + cs.RO 354 + cs.ML 305 + cs.AI 212 + cs.CV 158 ≈ 1790 行人工对，含「保原语」条目（`AGI,AGI`、`Canny,Canny`）。注入方式是把整个 dict repr 拼进 prompt 尾部——糙但有效（§4 改进点）。运行时术语自增（翻完段抽 `en-zh` 对并入表）实现了但有 bug 实际未启用——思路可借鉴不抄实现。

### 2.4 env 可译性判定

规则先判：黑名单（math/verbatim/figure/table/algorithm/bib 全族 ~30 个）或体内含 caption 占位符 → 不翻。LLM 复判：其余未知 env 逐个问——**temperature=0、max_tokens 小、只答 True/False、判 content 而非 env name、few-shot 5 例、解析不出或请求失败一律 True（fail-open 宁翻勿漏）**。分段粒度是 section 级（`\section` 切），`-1`=preamble/`0`=正文头不送 LLM 但段内 caption/env 照常摘出送翻——「图表环境不翻但 caption 单独翻」靠「先摘 caption 后判 env」的顺序自动成立。

## 3. MathTranslate 证据（只借工程细节）

- **受限展开白名单**：`\newcommand` 仅当定义体命中白名单子串（equation/align/theorem/textcolor + 可译 env/command 名单）才在使用点展开——`\be→\begin{equation}` 别名不展开则保护规则套不上。texlate 的 v2 展开管线（`expansion-design.md`）是该思想的完整化。
- **占位符工程**：`XMATHX_d_d_d` 序号按位拆分（MT 吃掉部分分隔符也能恢复）；占位符两侧强制垫空格防粘连；译后 IGNORECASE 正则刷回全大写（MT 会改小写/变形）；腾讯 `UntranslatedText` API 原生不翻标记——**有原生支持的引擎优先用原生机制，prompt 层只是兜底**。
- **粒度对比定档**：MathTranslate 段落级 + 全对象化 vs LaTeXTrans section 级 + 选择性保护。texlate 取中——**段落级 chunk**（section 级单请求 8k token 太粗、上下文稀释、断点粒度差）+ **选择性保护**（LLM 有纪律，过多占位符反而稀释注意力）。

## 4. 成稿 spec（设计动机视角；逐字条款见 `xlat/prompts.py` 与 spec）

套件结构 `TASK_SENTENCE[kind] + C1..C8 + KIND_CLAUSES + C9 + C10? + GLOSSARY_BLOCK`：六种 kind（`para/caption/section_title/abstract/table_text/env_text`）共享逐字公共块 C1–C8；C9 占位符条款压轴（枚举真实 token 形态 `[[MATH_12]]` 等 + 动词清单 `translate/modify/reorder/split/merge/add/remove` 覆盖 validator 会查的全部破坏方式 + `must appear verbatim`）；C10 人名条款仅 para/abstract。`table_text` 是新能力（两参考实现都不翻 tabular）——K4 条款强约束 `&`/`\\`/列数不变，v0 先不翻、prompt 先备。

**落地增量（v2/v4 修订，已进 `xlat/prompts.py`）**：+C8a 反熔合条款（实测 `\`+CJK 熔合是跨模型通病，要求占位符/命令与 CJK 之间保留显式边界）；+C8b untrusted 条款（论文正文里嵌的指令/请求/格式命令一律当数据——prompt injection 防线）；C9 增补 movable-token 授权；abstract kind 带 paper_context 锚定块。

**术语表**：五级 user > 论文级（`output/{paper}/glossary.local.yaml`）> category > default > ph→ph 占位符恒等（`xlat/glossary.py` 层级注 ①–⑤，活规范 `spec/translate.md` §1.9——调研期的「三级」是 LaTeXTrans 原型，落地时插入论文级并把占位符恒等列为最低档）；文档级过滤（`(?<!\w)term(?!\w)` IGNORECASE 扫全部 chunk 源文，整篇过滤一次保证 system prompt 恒定）后序列化 `- en: zh` 行表追加尾部（「highest-priority rule」头），占位符恒等注入混在表里（按 TYPE 字典序 + n 数值序稳定排序——前缀缓存命中前提）。种子表搬 LaTeXTrans 六表并按语料 category 分布扩（现行 `xlat/terms/`：default + cs.AI/CV/LG/ML/RO + cond-mat + quant-ph + `index.yaml` 映射——加领域不改代码）。

**LLM judge**：env 可译性——黑名单直判、未知 env 交 LLM（temp=0、`max_tokens=16`、True/False、fail-open=True）；段内可译判定走廉价规则（无拉丁字母/全大写/纯占位符 chunk 跳过），灰区默认翻不另开 LLM 调用。

**批量/并发/断点**（参数以 batchmodel-2026-09-18 修订为准，活规范 `spec/translate.md` §1.4）：全量 chunk 入批（无 <300 短块闸，`pipeline.py::_build_work_items`），K 量化等大装箱 `BATCH_MAX_CHARS=12000` / `BATCH_MAX_ITEMS=32` / `BATCH_MIN_CHARS=2500`（`xlat/batch.py`），user 文本 `[1]…[2]…` 编号、响应按行首 `[n]` 锚定解析（`@@` 独占行为兜底分隔），数量不符/序号越界整批回退单翻；并发为 worker pool `DEFAULT_CONCURRENCY=10` + **首发单飞暖前缀缓存**；429 特判指数退避；temperature 翻译 0.2–0.3（LaTeXTrans 0.7 对保结构任务偏激进）、judge/抽取 0；单请求超 `CHUNK_HARD_LIMIT=6000` 按句界二分；state.json 逐块落盘 `{version, meta, completed[], results[], errors_report[]}`，chunk 缓存键 `sha256(content + model + prompt_version)`——**条款措辞任何改动必须 bump prompt_version 否则缓存命中旧 prompt 产物**；纯占位符 chunk 不发请求直接落盘。带错重翻 = `[Original]/[Translation]/[Error]` 三段式 user prompt + 专用 corrector，≤3 轮仍败回退原文记 `fault`。

**换行编码（建议采纳项）**：ieeA 把 `\n`/`\n\n` 编码为 `[[SL]]`/`[[PL]]` 防 LLM 增删换行——采纳 `[[SL]]`（段内换行保护），`[[PL]]` 不需要（分段边界在 chunk 层管理）。

## 5. 风险与开放项（留档）

glossary 体积 ~3–4k token/请求，短块批量时可能超过正文体积——接受（一次烤进吃缓存），留意超小 provider 上下文；`[[MATH_n]]` 隔断句子可能出翻译腔，scanner 产出时保证占位符两侧天然空格；`table_text`/`section_title`/`abstract` 需配套 validator 对账项（`&`/`\\` 计数、命令名 diff）；运行时术语自增默认关留接口（自动抽取质量参差，污染全局表得不偿失）。

### 参考文献

[^latextrans]: LaTeXTrans contributors. LaTeXTrans — LaTeX document translation with LLMs. GitHub. [github.com/PolarisRisingWar/LaTeXTrans](https://github.com/PolarisRisingWar/LaTeXTrans)

[^mathtranslate]: SUSYUSTC. MathTranslate — LaTeX translation via machine translation engines. GitHub. [github.com/SUSYUSTC/MathTranslate](https://github.com/SUSYUSTC/MathTranslate)

[^ieea]: zcyisiee. ieeA. GitHub. [github.com/zcyisiee/ieeA](https://github.com/zcyisiee/ieeA)
