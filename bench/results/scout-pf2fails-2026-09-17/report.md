# scout-pf2fails — realpostfix2 真臂早期归因

> 2026-09-17。**口径**：读数时 records.jsonl=64/100（00:47，arm 仍在跑），cases.jsonl=13；pipe-xel 分布 clean 51 / fail 6 / partial 7。翻译侧全绿：chunks 4815/4818 ok，leftover ph:0 全格，skip 1 格系 HTTP 502 网关瞬时（0905.4439），另 1 格 partial chunk 走 slots fallback rescued（1511.02820）。**splice 残留占位符 0 —— gate PASS**。

## 逐格归因表（13 格非 clean）

| id | verdict | 签名 | 簇归属 | fixloop 终态 | 证据 |
|---|---|---|---|---|---|
| 0707.4465 | fail | `elsart.cls` 缺席 | missing_file·shim可解 | clean（stub→elsarticle） | base 同错，非管线 |
| 0905.4439 | fail | `aa.cls` 缺席→stub→natbib author-year mismatch @aux:67 | missing_file→**shim保真** | acceptable_pdf（1残错） | 12023.aux:67 `Bibliography not compatible with author-year citations` |
| 0905.4907 | partial | **译文注入裸 `\alpha`**（"alpha emitters"→`\alpha 发射体`）→Missing $×4 | **新签名·翻译裸cs** | acceptable_pdf（1残错） | tex:194 caption；base clean=唯一管线引入格 |
| 1003.1464 | partial | ø(U+00F8) in cmmi8 ×1 | misschar·**数学字体域** | acceptable（未修） | base 同签名，源级 |
| 0806.1079 | partial | ≠(U+2260) in cmr5/7 ×3 | misschar（normalize揭罩，见下） | clean（missing_char_fix） | base 是 invalid_utf8+FFFD×2，mac_roman 源 |
| 1206.5921 | partial | `figure1.pdf` 源缺 | missing_graphic | clean（fbox stub） | base 同错 |
| 1306.2177 | fail | `aipcheck.tex`+`aipproc.cls` 缺席→stub→`theacknowledgments` env undefined | missing_file→**shim保真** | acceptable_pdf（1残错） | tex:320 |
| 1306.5813 | fail | `iopart12.clo` 缺席 | missing_file·shim可解 | clean | base 同错 |
| 1404.5720 | partial | 5×.eps 源缺级联 9 err→salvage 5KB pdf | missing_graphic+**graphic_repair缺口** | best_effort_pdf | feedforward/ip_overview/cskicker/rawwaveforms/apwaveforms |
| 1511.02820 | partial | ĳ(U+0133) in txmi ×1 | misschar·**数学字体域** | acceptable（font_fallback未达） | base 另有 float_opt`d`错，被管线 float_sizing **治愈** |
| 1511.06879 | fail | revtex4 `\Ref` already_def→作者 \newcommand 失败→每处 \Ref 用报 Illegal parameter number（1+20级联=no_pdf） | already_def·源级 | clean（renew规则） | base@line12 同错 |
| 1608.02516 | partial | −(U+2212) in cmr10 ×1 | misschar | clean（missing_char_fix） | base 同签名 |
| 2105.03750 | fail | `aastex63.cls` 缺席→emulateapj stub→`\footnote{\url{.._..}}` Missing $ | missing_file→**shim保真** | acceptable_pdf（1残错） | tex:509；aastex63 真身 `_` catcode-12 未被 stub 复刻（推断，见下） |

管线引入格仅 **0905.4907** 一例（pipe partial / base clean）。pipeline **治愈**一格（1511.02820 base float_opt`d` 被 normalize float_sizing 吸收）。1404.5720 rc=141（SIGPIPE 样返回码）但 harness 记 ok:true，仅注记。

## 新签名清单

1. **翻译注入裸 LaTeX cs（翻译侧伤害，非 splice/PH）** —— 0905.4907：LLM 把英文 "alpha emitters" 译成 `\alpha 发射体`、`\alpha 以外事件`，caption 内两处裸 cs → Missing $×4，fixloop 修不掉（残留 1 err → acceptable）。同族疑似在 mock 臂 pending 里还有 `undefined_cs:itemOC/itemSPELL/linebreakGF`（2211.04495/2410.06025/math·0605301）——译文中出现臆造控制序列。**这是真实臂确认的第一类翻译→编译伤害，建议 L2/规则侧补"译文裸 cs 检测"（源无此 cs、数学域外出现 `\word` 即告警/修复）。**
2. **shim 保真度残余（3 子型）** —— 均不出 PDF 级 fail，收敛 acceptable_pdf 但带 1 残错：aa.cls stub→natbib author-year 失配（aux 内 bbl 形态不符）；aipproc.cls stub→`theacknowledgments` env 缺；aastex63→emulateapj stub→`_` catcode 未复刻使 `\footnote{\url{..._...}}` 爆 Missing $（经典 \url-in-脚注 catcode 陷阱；真身 aastex63 按惯例 `_` 在文本为 catcode12 故源稿可编——此为机理推断，证据=源 line579 同构 `\footnote{\url{}}` 且作者原文可出刊）。可考虑给 aastex63 stub 加 `\catcode`\_=12` 或 footnote-url 重写规则。
3. **misschar·数学字体域无规则接手** —— ø in cmmi8（1003.1464）、ĳ in txmi（1511.02820）：missing_char_fix 只cover文本字体（≠/−已治愈），font_fallback→Libertinus Serif 够不到数学域，两格挂 acceptable。
4. **graphic_repair 覆盖缺口** —— 1404.5720 五连 eps 源缺**未触发** graphic_repair（1206.5921 单 figure1.pdf 有触发），直接走 _best_effort_pass salvage → 5KB 残 pdf。疑似规则只对单文件/特定引用形态生效，值得查规则触发条件。
5. **normalize 揭罩效应** —— 0806.1079：normalize 把 mac_roman→utf8 修对后，base 侧的 FFFD×2 变成真 ≠×3（cmr5/7 无此字）——pipe miss 数表观大于 base 非回归，且 missing_char_fix 已治愈 clean。

## mock 臂同 id 对照（postfix-2026-09-16）

12 格可比：9 格 real≈mock 同签名（elsart/aa/aipcheck/iopart12/aastex63 缺席、figure1.pdf、feedforward.eps、misschar ø/ĳ/−/≠）。差异：real 更好 —— 0806.1079 mock留partial real clean；1206.5921 mock未跑fix real clean；1511.06879 mock判clean(1err) real fail→fix clean。0905.4907 mock 同族 syntax err4 但 miss=92（mock 译文伪影）。**同簇结论：无 real-only 新炸点，0905.4907 翻译裸cs在 mock 也是同族签名。**

## 90% 门进度预判

当前 64 格：pipe-xel 出 PDF 率（clean+partial）58/64=**90.6% 骑线**；fixloop 已救回 clean 7 + acceptable 6 /13。pending 36 格 mock 投影 17 clean/15 partial/4 fail——尾部 old-era 批集中已知族：espcrc2.sty 缺席×2（hep-lat/0111009、hep-ph/0111218）、hyperxmp pkg_order（2308.12712）、expl3_backend（hep-ph/9910403）、若干 invalid_utf8 系老档（astro-ph/97x、cond-mat/9x、math/0x 等 mock 侧 verdict 空字段格）。hep-ph/9703228（bug-E 已知格）仍在 pending。**预判：出 PDF 率大概率贴线或略破，fail 上限 ~8-10；90% 门若按「pipe-xel clean」计则当前 79.7% 有缺口，关键看 fixloop 救回率与门定义口径。**
