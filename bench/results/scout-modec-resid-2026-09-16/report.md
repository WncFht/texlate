# scout-modec-resid — modec-postfix 残余失败归因（11 格全覆盖）

> 2026-09-16。对象：`bench/results/modec-postfix-2026-09-16/`（n=80 mock 四臂）残余面。

## 一、Mode-C clean→partial 6 格：同一机理——PH 被挪进 cs 名中段

`e2e_mock_bench.py:166-195` `_apply_c` 把标记 `[[PH]]` 挪到段内任意字符边界（只排除其他 PH span）。落点切进 `\foo` 中段时 zh 成 `\fo[[PH]]o`，splice 逐字节替换后 `\fo<payload>o` → undefined cs。6 格全中：

| 格 | pipeC first_error | 被切的 cs / 挪入 payload |
| --- | --- | --- |
| 1206.0197 | :263 | `\textit` 被 `\cite{sato81}` 切开 |
| 1306.0067 | main.tex:409 | `\noindent` 被 `$\mathrm{\Omega_{M1}}$` 切开 |
| 2211.04436 | :307 | `\textbf` 被 `$X$` 切开 |
| 2308.12593 | :314 | `\noindent` 被 `\Cref{def:composition}` 切开 |
| 2410.17957 | :396 | `\method` 被 `\ref{…}` 切开 |
| hep-th/0408064 | :1230 | `\displaystyle` 被 `\refb{e14}` 切开 |

**变种 1206.0358**（partial=missing_character×2）：同款切分但切 `\bf`→`\b`+f——`\b` 是合法 TU accent（bar-below U+0332），展开产物在 cmmi10 缺字。fixloop `\newunicodechar` 兜底**盖不住**：字符不在文件里，是 accent 展开产物（与 astro-ph/9901044/hep-th/0408064 同一防线盲区）。

**判定**：harness 挪位是设计内压力档，真 LLM 也可能把 PH 落进留在 chunk 文本的 cs 名中段——真实风险面。**修复建议（已转 1d）**：splice 前 zh 文本加「PH 嵌 cs 名」检查（`\\[a-zA-Z]*\[\[PH` 形态）→ violation 走 retry/回退原文，或 PH 顺延到 cs 名尾。不进 fixloop——编译期才炸时只剩半边 cs，payload 不可复原。

## 二、upgrade209 partial 三格：209 惯用语面缺口，非转换逻辑 bug

- **hep-ph/0104029**（undefined_cs:abstract ×71）：转换正确；败因是 209 时代 `\abstract…\endabstract` 裸命令对——revtex4-2 的 abstract 只在 frontmatter 机器内绑定，`\maketitle` 后裸调必 undefined。**修复层（fixloop rules）**：upgrade209 产物 + undefined_cs:abstract → shim 命令对 `\providecommand\abstract{\begin{quotation}\noindent\textbf{Abstract.}}` + `\endabstract{\end{quotation}}`。
- **astro-ph/9901044**（missing_character×51）：mnras+psfig 转换正确出 pdf；51 缺字全 Å(U+00C5) in cmr10——源 `$\rm\AA$`/`{\rm\AA}` 把埃写进数学模式，TU 下 `\AA`→字面 Å 落 classic cmr10 无字形。**修复层**：math 内 `\AA`→`\text{\AA}` 改写或 `\renewcommand\AA{\text{\r A}}`。
- **hep-th/0408064**（missing_char×1）：article+COMPAT_SHIM 正确；`{\i.e.}` 在 `\be…\ee` 里——compat 下 `\i`=chardef 有字形，升级后 TU accent 展开 U+0131 cmmi12 缺字。同类 209 文本 accent 进数学。

## 三、1404.0527 `latex209_ds_at`：terminal 判定正确

jaa 是 ds@ **root style**（整体替换 article.sty 非包），全文依赖 ~32 个 209 内核残留（`\@maxsep`/`\@dblmaxsep`/`\@ptsize`/`\@pubyear`/`\@journal`…）；`\@options`+`\ds@<opt>` 分发只在 compat 流内存在。要活只有 (a) compat 模式 CJK 注入通路（工程量大）或 (b) 209-internals shim 层。**当前 reject 是正确终态**。

## 四、1306.0302 JINST.cls：实测验证的 shim 草案（宏面版）

SISSA 站外分发（CTAN 只有 jinstpub.sty——article 用包非替身）。稿面宏面：`\email`/`\keywords`/`\abstract{}`/`\acknowledgments`/`\arxiv`/`\href`。**实测**：stub 落 wdir 后 xelatex 一次过 16 页 0 错 0 缺字。要点：JINST 语义是 `\begin{document}` 自动出标题块（稿内无 `\maketitle`）→ abstract/keywords stash + `\AtBeginDocument` 释放，`\maketitle` 同钩补打（`\ifx\@title\@empty` 守卫）。注意仓内 shim_map 已有裸 `JINST.cls: {loads: article}`（`768c528`）——本草案是宏面升级版，已转项目体验方式合入。yaml 草案在 `bench/results/scout-modec-resid-2026-09-16/jinst-shim.yaml`。

## 汇总

| 格 | 机理 | 建议层/属主 |
| --- | --- | --- |
| 6+1 格 pipeC | PH 嵌 cs 名中段断 cs | 1d：validate/pipeline 加检查 → 回退原文 |
| hep-ph/0104029 | 209 `\abstract` 命令对 | fixloop rules shim |
| astro-ph/9901044 | math 内 `\AA` | fixloop rules |
| hep-th/0408064 | math 内 `\i` accent | fixloop rules |
| 1404.0527 | jaa root style 死墙 | terminal 正确 |
| 1306.0302 | JINST.cls 缺席 | shim_map 宏面升级（草案实测） |

**跨格签名**：accent 展开产物缺字（U+0332/U+00C5/U+0131）是 `\newunicodechar` 防线的结构性盲区——三格同型，值得一条签名级规则面（已转项目体验方式）。

工作现场：`tmp/exp/ds_at_1404/`、`tmp/exp/jinst_1306/`。
