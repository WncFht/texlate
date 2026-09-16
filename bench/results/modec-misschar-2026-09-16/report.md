# modec-misschar 归因报告 — 4 格 missing_char 全部定到机理

> 2026-09-16。对象：modec-expand n=80 的 5 格 misschar 引入中已交 4 格（0806.1984 / 0806.3144 / 0905.0795 / 1003.0112；1706.00265 后补入簇）。
> 共享形状：**数学内容以散文身份到达翻译器**（占位符契约本身没破：leftover_ph=0、ph multiset 完好；也不是「合法译文撞上未覆盖字槽」——CJK 落在 TeX 数学态里，cmr 数学字当然没字形）。但 4 格是 **3 个不同的上游保护洞 + 1 个 accent 参 + 1 个独立分页病理**。全部已在 stagerun-loop1（pre-f5da4bf）标记 missing_char → **非今日 segmenter 改动回归**；F2 group-literal 与 \text-skip 都不在这些路径上。

## 0806.1984 — missing×12 (cmr10) — `_on_math` 只认 `$`→`$`，不识 `\)` 闭符

源 L257: `\item $\act(g_1, \act(g_2, \p))=\act(g_1\, g_2 , \p)\), for all $\p \in S$ and\n$g_1,g_2\in  G$.` — 作者混排定界符：`$` 开、`\)` 闭。TeX 实测（最小 repro 已编译验证）：`\)` 在数学态内 = mathshift 闭符 → `, for all ` 是正文、`$\p \in S$`、`$g_1,g_2\in G$` 是数学。

segmenter `_on_math`（segmenter.py:1682-1712）拉 token 只找 mathshift：math1=`$\act...\), for all $`（把 "for all" 吞进数学→保住英文）、`\p \in S` 落散文→`S` 被译、math2=`$ and\n$`（"and" 吞掉）、`g_1,g_2\in G` 落散文→`g_1,g`→这是译文+`_2` 留、`G`→这是译文、尾 `$` 孤字面。逐字节对上 zh 输出：`for all $\p \in 这是译文$ and\n$这是译文_2\in 这是译文$.` 12=3×这是译文，与 log 精确吻合。

机理字：**混合定界符 `$...\)` 导致 $-奇偶错位**。修复归属 segmenter `_on_math`：体内遇 cs `\)`（及 disp 时 `\]`）应作闭符——与今日 `\text`-skip 修复（0806.3472 内层 `$` 截断外层）是同一函数的镜像洞。repro:

```tex
\item $\alpha(x)\), for all $p \in S$ and $g_1\in G$.
```

parse_tex 应产出 1 个 MATH ph（`$\alpha(x)\)`）+ prose + 2 个 MATH ph；现产出 2 个 ph（含 "for all"/"and"）+ prose。

## 0905.0795 — missing×100 (cmr10/8/6) — `\nc` 别名分类 opaque → `\be/\en` 未定义 → equation 体被译

源 preamble: `\newcommand{\nc}{\newcommand}` 然后 `\nc{\be}{\begin{equation}}` `\nc{\en}{\end{equation}}`（+`\ben/\enn`）。gullet `_classify`（gullet.py:2564）：`\nc` 体=裸 cs `\newcommand` → `body_has_text` false → **opaque** → `next_expanded` 命中 `return t`（:976）不展开 → `\be` 永不注册 → 使用时 `\be...\en` 当未知 cs + 散文体 → 整段 equation 进 chunk 被译。zh 实证 L539: `\be \tau(这是译文)=\sum_{\alpha\in 这是译文} \tau_\alpha(这是译文) 这是译文^{\alpha}= \sigma(这是译文|0\ket), \en`（下标→cmr8、嵌套→cmr6、正文级→cmr10，×25 处 ≈100 精确吻合）。

对照实测（最小 repro 已跑）：直接 `\newcommand{\be}{\begin{equation}}` → `\be...\en` 正确成 `[[MATH_1]]`（ph 体保原字节）；走 `\nc` → 整体落 CHUNK。**洞在 gullet 分类**：体=单枚可展开/def-原语 cs 的宏不该 opaque——应 transparent_expand（或沿目标 cs 继承展开性），让 `\nc{\be}{..}` 展开回吐 `\newcommand` 后正常执行定义。TeX 语义上别名定义是合法的。归属 gullet/macro_table。repro 文件在 /tmp/t_be.tex（`\nc` 版）与 /tmp/t_be2.tex（直写版，对照）。

## 1003.0112 — missing×180 (cmr7/10) + Output-loop 死循环 — 两个独立问题

**(a) missing×180**：`\sba`/`\sea` = `\newcommand` 直写 `\begin/\end{subeqnarray}`。`subeqnarray` 是**文档内 `\newenvironment` 定义的** env（L70：before 体尾部 `\eqnarray`）。MATH_ENVS 无此名；`_do_newenv`（gullet.py:1709）硬编码 `kind="transparent"`，无从 before-体推 body_role="math" → 体按散文 → `\varphi^这是译文_\Omega`（上标→cmr7）、`\varphi_{这是译文}^这是译文`、`\int...\!\!这是译文` → ×45 处=180。zh L424-430 实证。**归属 env 角色推断**：`_do_newenv` 可检 before-体末尾是否数学开环境 cs（`\eqnarray`/`\math`/`\[`/`\begin{eqnarray}`）→ 标 math；或最窄补丁 MATH_ENVS+=subeqnarray。对照：同文档 `\ba`（→`\begin{eqnarray}`）工作正常，`\ba...\ea` 内无 CJK。

**(b) Output loop—100 dead cycles** @UnruhHawking6.tex:1423 `\ba`（widetext 内巨型 eqnarray w_0/w_1/w_2）：revtex4 `twocolumn` 的 `widetext` 走输出例程 grid-snap 摆位，译文缩短散文→块落点移位→无法收敛。**positional 病理，非内容污染**：该 widetext 块内纯数学（与 base 同字节）；pipeB 臂在 1454 行另一 widetext 复现死循环、pipeC 臂无——随分页漂移。与 missing_char 无因果。倾向 known-issue/疑难杂诊（fixloop 已 acceptable_pdf 放行）；要确诊需对 zh/base 两版做页级 diff。归属 compile/inject 侧（可顺手排查 float_sizing 注入是否加剧）。

## 0806.3144 — missing×1 (lmroman12-italic, U+0327) — accent 参字母被译

bibitem[6] `{\it Le\c{c}ons sur la th$\acute{e}$orie...}` → `\c{c}` 的参 `c` 被 mock 译 → `\c{这是译文}`：cedilla accent 对 CJK 无法预组→走组合符 U+0327→lmroman-italic 无该槽。base 里 `\c{c}`→ç（U+00E7 预组）故 clean。**归属 segmenter 参保护表**：accent cs 族（`\c \v \' \` \" \H \r \u \~ \= \. \b \d \k \t`）参须保护——accent+CJK 语义上恒无意义；真 LLM 保 `\c{c}` 壳但翻参也会产生同款。严重度微（×1），但机理真实。同 bibitem 还有 `\"{这是译文}`（Gürses）——`\"` 走 U+0308，该 italic 字有槽故未报。

## 判定汇总

- 4 格全部是**既有保护洞**被 expand 层语料首次照亮（expand 层正是宏/env 重灾区），非今日提交回归。三条 CJK-in-math 共享「数学体进翻译器」形状但根因各异：`_on_math` 混排闭符（0806.1984）/ 别名定义不展开（0905.0795）/ 用户 env 无 math 角色推断（1003.0112）。0806.3144 是 accent 参洞，量级最小。
- 修复归属：**segmenter**（`_on_math` `\)`/`\]` 闭符 + accent 参表）与 **gullet/macro_table**（`_classify` 裸-cs 体别 opaque 化 + `_do_newenv` body_role 推断）；1003.0112 死循环独立，归 compile 侧或记 known-issue。
- Mode B/C 与本批无因果（pipe 纯臂同样炸；pipeB/C 仅计数因 L2 路径漂移而不同）。
- 真 LLM 下危害仍存在但减轻：数学体内 `\mbox`/连接词会被译成 CJK 落 cmr——mock 把洞放到最大可见，结构性 bug 相同。

现场：workdir `bench/work_e2emock/corpus_v3/{pipe,pipeB,pipeC}-xel/{id}/`；最小 repro /tmp/t_be.tex、/tmp/t_be2.tex、/tmp/t_mj2.tex（`\)` 混排实证）；zh 证据行 0806.1984:L221-222、0905.0795:L539/L930、1003.0112:L424-430、0806.3144:L1734。
