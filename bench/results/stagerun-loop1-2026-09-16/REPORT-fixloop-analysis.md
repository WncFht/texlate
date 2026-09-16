# loop1 fixloop 聚合分析（leader 补记）

数据：`records/fixloop.jsonl` 1310 格（--on fail 647 + --on misschar 663），跑于 engine audit-wave 修复（6b23435）**之前**。

## 结局分布

`fixloop_verdict`：acceptable_pdf 663（misschar 模式全数落此）/ best_effort_pdf 295 / clean 144 / unfixable:* 共 208 / no_errors_no_pdf 15 / stuck 1。
状态迁移（compile_status_before → fixloop 后 status）：fail→clean 181、fail→partial 273、fail→fail 193、partial→clean 8、partial→fail 17、partial→partial 638。

## no_errors_no_pdf ×15 —— 已实证为基建级杀伤，非规则问题

15 格中 13 格与 partial→fail 退化名单重合。修复后引擎直编 splice/ 树（sandbox=bwrap）：**12/15 出 pdf**；残留 3 格是真 bug 不是规则缺口：

- `1803.00012`：rc=139 SIGSEGV（包加载中途段错误）——独立崩溃类，judge 需能记 killed_signal=11。
- `1803.00054`：rc=1，`l.28 \usepackage{color}` 真错——需查 fixloop 末态编辑是否留残。
- `1706.02464`：`Unable to read an entire line---bufsize=200000`——单行超长的压缩/二进制源，需输入侧探测或 bufsize 参数路径。

含义：partial→fail 17 格里约 13 格是环境杀伤假象；真规则退化只剩 1003.1717 / 1306.0036 / 2410.00012 / astro-ph/0111575（4 格），供下轮规则回归排查。这 15 格应随下轮 fixloop 重跑重归类（records 不自动重试终态——`--rerun --ids` 定点）。

## unfixable:missing_file ×113 —— filemap 解不出的 legacy 包簇（下轮 fix 最大头）

payload 聚类（top）：pst-node 11、jheppub.sty 9、citesort.sty 7、diagrams.sty 7、axodraw.sty 5、pst-arrow 5、svjour3.cls 5、texsort.sty 4、epsf 4、emulateapj5.sty 4、setstack.sty 3、conm-p-l.cls 3、imsart.cls 3、jinstpub.sty 3、espcrc1.sty 3、emulateapj.sty 2、svjour2.cls 2、epl2.cls 2、undertilde.sty 2、default.sty 2。

注意点：pst-node/pst-arrow 属 pstricks 家族（路由层已知）；jheppub/jinstpub/svjour/imsart/espcrc 是期刊 legacy cls/sty——部分在 TL 但索引未覆盖，部分是 CTAN-only/闭源，候选处置 = shim_map 扩列 / filemap.overrides 扩列 / 真缺档承认。`emulateapj*` 与 `epsf` 有 shim 仍报 missing_file → vendored_shadow/install 通路未接住，值得查。

## 其余 unfixable 小簇

syntax 15 / other 14 / babel_opt 11 / illegal_unit 10 / pdftex_prim 7 / capacity 5 / undefined_cs 5 / expl3_backend 4 / option_clash 2 / already_def 2 / fontspec_missing 2 / pkg_order 1 / warn_utf8 1 / stuck 1。

## 与 engine 修复的交叠

本轮 fixloop 跑在修复前：bwrap 相对 bind、tectonic outdir 子目录、env 降级 escape、-Z 白名单、_TECTONIC_ATTEMPTS 重试预算、run_process OSError 均在 6b23435 落。下轮 fixloop 全量重跑前，可先定点重跑这 15+17 格看分类迁移。

## 待办输入（下轮）

1. missing_file 簇 → fix-rules 侧 shim_map/overrides 扩列评估（113 格 = fail 残留 59%）。
2. partial→fail 真退化 4 格 → 规则回归清单。
3. SIGSEGV / bufsize / \usepackage{color} 三格 → 各立 ticket。
4. misschar 模式 663 格全落 acceptable_pdf——该档语义是"有 pdf 即收"，如需更严口径另议。

## 补记 2（2026-09-16 晚，leader）

- **early_eof taxonomy 已落**（`efa1fa3`）：1706.00175 式「`\end occurred …` + `No pages of output`、全文无 `!`」此前判 clean；rules.yaml 尾段新增 `early_eof` 两条（guard=`No pages of output`，payload 抓冒犯 cs）。engine 侧待 taxonomy derive 落地后自动继承。重跑清单内 1706.00175 预期改判。
- **killed_signal 盲区**：`res.killed_signal` 只记 `rc<0`（POSIX 约定）；1803.00012 实测 `rc=139`（128+11 壳层约定）→ killed_signal=null 漏记。engine.py:1009/:1372 两处赋值点待加 `rc in 129..192 → rc-128` 归一（排进 loop2，避开在飞 rewrite）。
- **定点重跑清单**：`rerun-ids.txt`（15 nenp + 4 真退化，csv 可直接喂 `--ids`）。命令形：`stagerun.py fixloop --on fail --tag loop1 --rerun --ids $(tail -1 rerun-ids.txt)`。
- **环境坑**：`FORCE_COLOR` 会污染 CliRunner 输出致 help 断言假红；pytest 一律 `env -u FORCE_COLOR`。
- 1d 提案「不退化底板」（入口态 PDF 快照、末态判决不低于入口态）已立 ticket #20，loop2 全量前评估。

## 补记 3：定点 rerun 两轮结果（2026-09-16）

**Round 1**（post-`6b23435` 引擎 + `efa1fa3` early_eof + `5d195c2` derive）：nenp 15 → 2 真残留（1803.00012 rc=-11 `killed_signal=11` SIGSEGV、1706.02464 bufsize）；**12 格 misschar 池 nenp 全改判 `unfixable:early_eof`**，1803.00054 同归；astro-ph/0111575 → **acceptable_pdf 痊愈**（epsf 通路链修复起效）；1003.1717 仍 syntax、1306.0036/2410.00012 改判 undefined_cs（subclassify 收窄正确）。

**机理**：13 格 early_eof 同根因——稿自带 aastex61/62.cls 的 `\IfFileExists{revtex4-1.cls}{…}{…\stop}`，revtex4-1 不在 TL → `\stop` 夹条件内 → `\end occurred incomplete` + 零页、rc=0、无 `!`。对策 `18ff106`：tail plea 规则（`include|download … X.cls` + guard `No pages of output` → missing_file 抓档名）+ `revtex4-1.cls`→revtex4-2 shim。

**Round 2**（13 格重跑）：**全数落 pdf** —— 11 acceptable_pdf + 2 best_effort_pdf（2304.05202、2211.04482）。

**19 格终态**：14 格出 pdf；残 5 —— 1803.00012（SIGSEGV）、1706.02464（bufsize）、1003.1717（syntax）、1306.0036/2410.00012（undefined_cs）。pst-node/pst-arrow 可解仍败疑点在本批未复现（不在这 19 格内），归 loop2 全量观察。

## 补记 4：残 5 格归因终版（2026-09-16，loop2 点火前）

逐格机理查明，3 格已修入 loop2 数据集：

- **1306.0036 → 规则互踩（已修 `88d0ab9`）**：`pdftex_prim_polyfill` 注入 `\ifdefined\pdfoutput\else\chardef\pdfoutput=1\fi`，下一轮 `pdftex_prim_guard` 的旧 lookbehind `(?<!ifdefined)` 仍放行 `\chardef\` 紧邻的 `\pdfoutput=1` → 套娃改写成 `\chardef\ifdefined\pdfoutput\pdfoutput=1\fi`（复现逐字节吻合）；同理对自输出不幂等、连 `\ifnum\pdfoutput=1` 比较式也误裹。lookbehind 改 `(?<![\\a-zA-Z])`（cs 名紧邻一律不动）后三种语境全免疫且幂等。
- **2410.00012 → spotcolor 是 pdfTeX-only（已修 `88d0ab9`）**：bundled ieeeaccess.cls `\RequirePackage{spotcolor}`；spotcolor 内部 `\AddSpotColor→\pdfobj/\pdflastobj` 是 pdfTeX 原语，xelatex/tectonic 必炸 undefined_cs（payload=SpotSpace）。TL 有真包 → missing_file 打不到；xespotcolor（TL 有）同 API 面 → 新规则 `spotcolor_xetex_shadow`（order 156）wdir 注 stub 桥接，gate=source_contains{spotcolor}+cs_set。
- **1706.02464 → bufsize 硬死（已修 `26b760e`）**：bundled TCI 宏转储 `tcilcomm.tex` 单行 3MB，顶穿 web2c buf_size=200000 → `Unable to read an entire line` 无 `!` 收尸。`XelatexEngine._env` setdefault `buf_size=8000000`（kpathsea cnf 经 env 覆盖，实跑验证过线）。过线后暴露第二层伤：该巨行内亦有 `这是译文` 腐蚀 → 属下条超簇，等 segmenter 修后重翻。
- **1003.1717 → 译文腐蚀超簇成员（fixer-slots 属地）**：bundled `aps.rtx`/`10pt.rtx`（REVTeX 运行时数据文件，makeatletter 域）被当正文翻——`-.25in`→`-.25这是译文`（illegal_unit）、`\let\frontmatter@footnote@produce...`→`\let\frontmatter@ 这是译文`（csname 断裂）。与 1d scout 超簇同机理；补注：.rtx 这类文件 `@` 是字母，segmenter 按普通 .tex tokenize 会错切 cs 名。
- **1803.00012 → 确定性 xelatex SIGSEGV（ticket-only）**：revtex4 shim 树内 hyperref 初始化段（log 止于 `Plain pages OFF` 后）崩 rc=-11；stack/save/nest_size 放宽无效、`unicode=false` 无效（文档自开 unicode=true）→ 非资源耗尽、非选项门控的真引擎 bug，无规则面可修。

另发现并移交 1d：`shim_known` 条件（engine.py:611）实际不可达（shim_map 键带扩展名 vs `\usepackage{裸名}`）；payload 口径在宏内炸场景偏到展开点行末（真冒犯 cs 在上文 macro-expansion 行末）；`PDFTEX_PRIMS` 缺 pdfobj/pdflastobj 族（wdir 内直用型稿件要靠它 guard/polyfill）。

**pst-node/pst-arrow 疑点核销**：0707.1954 动作链显示 round5 `missing_file: pst-node` 仅记 `no package provides pst-node`——裸名候选 `pst-node.tex` 变体补位是 `3c5aae2`（17:19）才落的，loop1 跑于 15:49 之前。机理无谜：`\input pst-node`（pstricks-add 内裸 input）→ 裸 payload → filemap 查文件名表必 miss。loop2 已含该修复，22 格 pst-* 预期转 installed。
