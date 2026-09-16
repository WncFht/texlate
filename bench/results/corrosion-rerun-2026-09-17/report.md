# corrosion×28 mock 臂重译回收（texlate-2f）

> 链：`xlat --arm mock --rerun` → `compile --arm zh --rerun` →
> `fixloop --rerun --on fail`（28 格 = scout-fail59.md corrosion+plaus 行）。
> 时点：post-`a6b58d4`（gap bytes 独立 literal run）。

## 0. 结果

**10/28 出 pdf**（compile clean 6 + partial 3 + fixloop acceptable_pdf 1），
18 格仍 fail——**但 CJK 指纹全消**，末条 first_error 零 `这是译文` 命中：
腐蚀签名已清除，残留为真错暴露 + 结构性残损两桶。

| 结局 | 格数 | id |
|---|---|---|
| compile clean | 6 | 1706.02464 1907.00027 1907.10528 2308.12593 2403.05454 cond-mat/0501221 |
| compile partial | 3 | 1306.0516 2104.00116（cat=clean 仅 warn）· 2203.00092（soul_err） |
| fixloop acceptable_pdf | 1 | 2105.11398（pst 族扇出后 har2nat 装包通） |
| unfixable 残 | 18 | 见 §1 |

注：口径以末条 compile record 为准（compile 段会写多条 record——首编
verdict 与 salvage 后 verdict 分列），console 逐格 `-> fail` 是首编输出。

## 1. 残 18 格归因（重译后）

| 桶 | 格数 | 机理 |
|---|---|---|
| 真错暴露（upstream/规则面） | ~11 | `Illegal parameter number`×4（1012.1830/1109.2144/1109.2205/1109.5313——dpf2011/hcp2010 模板 `#` 真错）；capacity×2（1404.0037/1706.00076）；`\@citex` 失配（1907.00131）；`\c` 口音误用（1404.0519）；`Missing \begin{document}`（1206.2111 schulze——原 `[12pt]` 孤儿判腐蚀，重译后仍缺 documentclass 行，真错/上游待复核）；undefined_cs×2（0707.4206 pstricks.tex 内部 cs、astro-ph/0605222 `\hb`——aastex shim 宏面缺口，已在 fixable-data 提案） |
| 结构性残损（非 CJK 指纹） | ~5 | `Incomplete \iffalse`×2（1206.0701 净 ifx-depth +4、1306.0364）；`\@iiiparbox` EOF 扫描×3（hep-ph/0408067/0501170/9910403——`\parbox{\absize}{...` 的 `}`/`\fi` 不在任何 chunk 内，重译无法回补——**残损在 segmenter chunk 边界层，fixer-slots 属地**） |
| harness_crash:YamlishError | 2 格间发 | 2105.11398/hep-ph/0605134 各一条 crash record 后自恢复跑完——**fixloop 引擎 yaml 解析偶发崩溃，infra bug 报 owner** |

## 2. 判读

- `a6b58d4` + mock 重译实证：**`这是译文` 型 CJK 腐蚀确已断根**（28 格 first_error
  与冒犯行零 CJK）。realpostfix2 全量重翻可放心跑，不会再产新 CJK 蚀格。
- 残 18 格里 ~5 格的 `\fi`/`}` 结构性丢失是**另一类腐蚀**——损失的是结构字节
  而非文本，CJK 指纹照不到；属 segmenter chunk 边界 + strip 残余面，
  需 fixer-slots 逐格核（样本：hep-ph/0408067 splice:234/253 的
  `\parbox{\absize}{#1` def 与调用点闭包错位）。
- 净增 pdf **+10**（fail 池 56→~46 路径上）；fixable-data 18 格 +
  no_main_tex 12 格落地后 gate 算术仍成立。

## 3. 复验记录

- xlat mock 28/28 ok，ph=0；source-drift 触发全量重译（chunk 全数再生）。
- compile zh：console 逐格 `-> fail` 是首编 verdict；末条 record 6 clean /
  3 partial（salvage/复判写多条 record，末条为准——同 §7.1 口径差节）。
- fixloop 19 格：2105.11398 acceptable_pdf（45s），1608.06714 跑满 362s
  未愈，其余 unfixable:* 类目如 §1。
- YamlishError 两条 crash record（2105.11398 后转 acceptable、
  hep-ph/0605134 终 unfixable:syntax）——payload 空，现场在 fixloop.jsonl。
