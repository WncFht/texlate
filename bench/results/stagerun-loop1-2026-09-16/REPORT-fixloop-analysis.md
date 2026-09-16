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

## 补记 5：loop2-delta 在飞期间的我侧落地（2026-09-16 晚）

**注意时点**：delta 批 `b4akkgal5`（543 fail + 540 misschar）点火早于下列三个 commit——跑的是 pre-chain 代码，rundiff 判读时要扣除对应层。

- **`6752bb0` TEXMFHOME 链**（1d 裁定落地）：`XelatexEngine._env` 写 `TEXMFHOME={usertree/home}:{ambient|~/texmf}` 冒号链——usertree 居首可写优先，宿主 ~/texmf 尾随保持可见（regress4 假退化根因修复）。**实测发现 tlmgr 把 env 值当字面路径**——链值会被建成名为 `texA:` 的目录且 tlpdb 判定全炸 → 新增 `_usertree_env()` 退链取首元素，`install_file`/`_filemap_tlmgr`/`rebuild_fontmaps` 全走它；`_bwrap_env_paths` 的 RW 值改走 `_kpathsea_list` 逐元素拆（链值原来会被当一个字面路径塞 --bind）。验证：`pst-plot97.tex`（仅 ~/texmf 有）经链解析命中，`_usertree_env` 输出单路径。签名未动。
- **`1e0e5c8` 67debb6 后同步**：`pdftex_prim_guard` 交替 13→75（全 PDFTEX_PRIMS，长名优先序）；`spotcolor_xetex_shadow` 的 `when` 改 `any:[undefined_cs, pdftex_prim]` + cs_set 加 `pdfobj`/`pdflastobj`（subclassify 现把宏体内 \pdfobj 炸点改判 `pdftex_prim:pdfobj`，单 undefined_cs gate 会死）。8 case 验证幂等 + cs 紧邻免疫。**技术债**：guard 交替是 yaml 内联字面值，PDFTEX_PRIMS 再扩时需手工同步——建议后续加 `prim_family` 键由 loader 生成（fixloop/engine.py 侧，1d 评估）。
- **`ea0c73e` 1e 两条兜底**：taxonomy 新增 `undefined_color`（`Package (?:x)?color Error: Undefined color 'X'`，payload=色名，实证 `undefined_color:这是译文`）；新规则 `undefined_color_fallback`(order 166) docclass 锚注 `\definecolor{X}{rgb}{0,0,0}`；`cs_targeted_fix` cs_table 加 `DeclareUnicodeCharacter` polyfill（lccode 惯用法，与 normalize c582736 同源 shim）。test_fixloop_yamlish 计数 37→38。
- **`.rtx` 边界裁定（我判，实现位在 1d 文件）**：1003.1717 的 `aps.rtx.tex`/`10pt.rtx.tex` 是 e-print 自带的 REVTeX 运行时转储（makeatletter 域纯宏数据），被 `rglob("*.tex")` 收进翻译集 → 407 超簇同款腐蚀。裁定 = **文件面排除 `*.rtx.tex`**（全语料 6 个文件全属此类，零 FP 面）；实现 = `e2e.py:_translate_tree` 与 `stagerun.py:_translate_tree` 两处 glob 加 `not f.name.endswith(".rtx.tex")`（或 1d 认为合适的共享 helper）。更深层的「纯宏数据 .tex」（tcilcomm 型无扩展名信号者）归 fixer-slots 的内容侧检测，不在本裁定内。

## 补记 6：loop2-delta 收官读数 + 残格归因（2026-09-16 深夜）

**批 `b4akkgal5` 终态**（每 cell 取末条 record，共 1310 格）：verdict 分布 acceptable_pdf 669 / best_effort 363 / clean 157（出 pdf 1189/1310 = 90.8%）/ unfixable 合计 112 / max_rounds 8 / no_errors_no_pdf 1。迁移：fail→clean 197、fail→partial 329、fail→fail 121、partial→clean 8、**partial→fail 仅 2**、partial→partial 653。对 loop1 基线：unfixable:missing_file **113→32**，nenp **15→1**（剩 1803.00012 即 SIGSEGV 格，ticket-only）。

### 残格逐簇归因

- **unfixable:pdftex_prim ×6 —— axessibility（已修 `7037301`）**：六格全是 `\usepackage[accsupp]{axessibility}`。axessibility 在 TL texmf-dist 内（missing_file 打不到），包体 `\pdfcompresslevel/\pdfoptionpdfminorversion/\pdfglyphtounicode` 在 XeTeX 内核必炸 pdftex_prim；包无用户命令面（纯 ActualText 标注补丁）→ 新规则 `axessibility_xetex_shadow`（order 157，spotcolor 同档）wdir 注空 stub 吞选项。cs_set 含包体全部六个 pdf 原语。
- **unfixable:missing_file ×32 —— axodraw2 类已修（`9f08bf3`），余为期刊 legacy**：axodraw2 ×5 的机理是 `tlmgr --usermode` 对 postaction 类包整体拒装（`package axodraw2 is not relocatable`，**rc=0 假成功**）→ `install_file` 新增 CTAN `archive/<pkg>.tar.xz` overlay=tree 落 usertree home 兜底（probe 复核，已实测 axodraw2.sty 落 `tex/latex/axodraw2/`）。其余 payload 为期刊/legacy 类（svmult/cimento/eptcs/JINST/PoS/nature2/llncsdoc/aa501/sw20lart/kapproc/appolb/pasj00/acm_proc_article-sp/emulateapj-rtx4/amsart2000 + multind/numcompress/widetext/umlaut/isolatin1/xetex-inputenc/docs/ol2/ams/thmsupp.tex/feynman）——filemap 无解者居多，归 shim_map/overrides 扩列评估或承认真缺。
- **max_rounds ×8 —— pst-all 家族扇出（机理查明，修法待 1d 侧）**：八格全是 `\usepackage{pst-all}`。pst-all.sty 在 `pstricks` 包内，`\RequirePackage` 连发 11 个成员（pst-tree/pst-grad/pst-3d/…各为独立 TL 包）。现有 `_install_dep_closure` 扫**被装文件**的依赖行——看不到"要求方" pst-all → 每轮只补一个成员，8 轮 < 11 成员耗尽预算。建议（fixloop engine 侧）：missing_file 收尾行的 `file:line` 带要求方（实证 `pst-all.sty:25: Emergency stop`），若该文件可解析则扫其 `\RequirePackage` 全表批量装——对一切 meta-wrapper 家族通杀。我侧备选钝器是抬 `meta.loop.max_rounds`（全局代价大，不推荐首选）。
- **partial→fail ×2 —— 一格是真超簇，一格是脏树残留**：1003.1717 = .rtx 腐蚀超簇（fixer-slots 属地，不变）。1306.0036 的 `unfixable:undefined_cs:relax` 查明为 **88d0ab9 之前轮次留下的套娃残留**——splice tex 第 30 行实存 `\chardef\ifdefined\pdfoutput\pdfoutput=1\fi` 烤进文件；现行 lookbehind 已免疫此类改写（cs 紧邻全拦），但 `--rerun` 复用 work dir 不洗源 → 旧伤永存。**方法论旗标**：rerun 继承脏树，曾被已修 bug 写坏的格需 pristine-tree 重跑才见真值。
- **floor_restored 指标（ticket #20）**：键已在 records 落地，本轮全格 False——与「近零退化」一致（底板从未被触发，非失效）。

### 裁定落地（我的队列清零）

- **bug-E**（0905.4907 caption 裸 `\alpha`→Missing $）：**不立规则**，归 llm_hook 候选——caption 作用域正则爆炸半径大，单格量不值。
- **prim-guard 注释行命中**（IEEEtran.cls:552）：**接受不改**——match 与 repl 同落 `%` 之后，全行仍是注释，语义零效应；收紧需行首锚定+前缀捕获，为 cosmetic 伤加复杂度不值。
- **latex209 终拒**：确认 `latex209_reject` phase:gate order:1 已 terminal——upgrade_209 后仍命中者（`\documentstyle` 行首条件复核）走 reject_route，无需再加东西。
- **elsart 旁系 shim 名表**（1e gtrap-scout §a 请求）：`elsart3/elsart3-1/elsart1/autart/personal` 五个 `.cls` 键已入 `legacy_pkg_shim` shim_map → elsarticle（`7037301`）。ship 真载体的 misschar 毒化由 `CJK_FIRST_USE_WARMUP` 覆盖（cmrepro elsart/elsart3 10/10 → 0 miss 实证；autart `\proc@elem` 逐字节同源、personal 为 elsart 克隆 → 同机理预期同治，待 real-postfix 复扫确认）。

### 定点重跑建议清单（post-delta）

axessibility 6 格 + axodraw2 5 格 + pst-all 8 格（待 sibling-closure 或配合抬 max_rounds 验证收敛）+ 脏树嫌疑 1306.0036（pristine-tree）+ 1003.1717（随 .rtx 排除落地后）+ early_eof 13 格归因待看。`rerun-ids-loop2delta.txt` 已有底单，可按此簇化筛。

## 补记 7：定点重跑结果（2026-09-16 深夜，post-`8e6d442`/`9f08bf3`/`7037301`）

**方法**：全部 34 格先 `compile --arm zh --rerun` 重建 pristine splice（洗掉在飞轮次的写坏残留——1306.0036 实证此步必要）；1003.1717 额外先 `parse+xlat --rerun` 重建 zh/（吃 .rtx 排除）。再按原 mode 分两批 `fixloop --rerun`（fail×32 + misschar×2）。

- **axessibility ×6 → 6/6 出 pdf**（clean 2 / acceptable 3 / best_effort 1）：`axessibility_xetex_shadow` 空 stub 实证生效。
- **axodraw2 ×5 → 5/5 出 pdf**（clean 2 / acceptable 1 / best_effort 2，含 real 臂 hep-ph/0501163）：`install_file` 的 CTAN overlay=tree 兜底实证生效。
- **pst-all ×8 → 7/8 出 pdf**（clean 3 / acceptable 2 / best_effort 2）：1d 的请求方扇出（`_requester_paths`+`_dep_fanout`，`8e6d442`）一轮补全 11 成员包。唯一未愈格 2105.11398 **越过 missing_file 改判 illegal_unit**——fanout 已通，前进到下一个错误类（稿自身新问题，非退化）。
- **misschar ×2 → 2/2 出 pdf**：1306.0036 best_effort_pdf（pristine 树证实 `undefined_cs:relax` 确系 88d0ab9 前套娃残留，现行规则不再复现）；1003.1717 acceptable_pdf（.rtx 排除 + `revtex4_array_swap_guard` 合流生效）。**delta 唯二 partial→fail 格清零。**
- **early_eof ×13 → 3/13 转 pdf，签名归因完成（全 13 格逐格查 tail）**：
  - **`Cannot find the file` 缺档 ×3 → 全愈（`3010310`）**：1706.02694/2308.00072/2410.06051 同墙——textgreek.sty:39 `\PackageError` 报 `Cannot find the file lgrenc.def`（无反引号对）逃出两条 missing_file head 签名；进程 halt 后 tail 落 `cannot \read`+`No pages` → 误路由 early_eof 从未进 install。新增 head 签名第三条 → `missing_file:lgrenc.def` → greek-fontenc 一包同时覆盖 hyperref puenc.def:612 要的 `puenc-greek.def`（TL 真身，tlpdb 索引本就有，从未到装包步）。重跑 3/3 → best_effort_pdf。
  - **`\read` 交互档 ×1**：hep-ph/0111248 — bundled `aipcheck.tex:259` 做终端 `\read`（"Type <return> to continue"），nonstop 模式必死。稿自带交互检查文件，候选处置 = wdir 覆写 aipcheck.tex stub（bundled_class_shadow 同机理，target 不限 cls/sty）。
  - **`no legal \end found` ×4**：1206.0136（^^M 缺字刷屏后截断）/ 1706.07911（`{` 未闭合 runaway 吞掉 `\end{document}`）/ 1907.00131（`\if` 缺 `\fi`，file ended while skipping conditional）/ 2403.00139（command ignored 后 Emergency）。同签名不同根——每格是独立 doc-level 伤（含疑似译文腐蚀侧枝），无一刀切规则面，逐格归因或归 llm_hook。
  - **错误帽 100 终止 ×2**：1608.06693（`\firstchoice@false` 系 undefined_cs 连发到 "(That makes 100 errors)"）、2308.12612（pgfsys.sty:17 `Missing \endcsname` 级联）。fatal 表象是 early_eof 零页，真根在上游错——值一条「错误帽」taxonomy 注记，修不修看上游个案。
  - **svjour 期刊选项 errmessage ×1**：0905.0193 — `\documentclass[epj]{svjour}` 但 svjour 不认 `epj` 选项（class 找 `svj<opt>` 子档失败 → `\errmessage{No valid journal specified}` → `\ifx` 未闭合陪葬）。类选项 shim 候选，单格量。
  - **译文腐蚀 ×1**：1404.0519 — `\c{S}` 系口音命令参数被译文改写（`-\c3这是译文2\`）→ `Use of \c doesn't match its definition` Emergency。归腐蚀超簇，非规则面。
  - **SIGKILL 超时 ×1**：2211.13028 — rc=-9 timed_out，log 截断在 citation warning 半途（无 stats 尾）。真挂起/infra 类，非规则缺口。

**小结**：本轮命名簇 21/22 格转 pdf（axessibility+axodraw2+pst 7+misschar 2），1 格前进换类（illegal_unit），early_eof 13 格留作下轮签名归因。

## 补记 8：wave-2 规则批收官（2026-09-16，commit `3010310`/`768c528` 等）

wave-2 全批落地验证完毕。**方法同补记 7**：每格先 `compile --arm zh --rerun` 重建 pristine splice 再 `fixloop --rerun`。

- **shim_map 第二波 ×26 格 → 25 转 pdf**（clean 5 / acceptable 4 / best_effort ~16）：emulateapj-rtx4→emulateapj、amsart2000→amsart、nature2→nature、acm_proc_article-sp→acmart 桥接 + svmult/cimento/eptcs/JINST/PoS/appolb/pasj00/aa501/kapproc→article + multind/ams/widetext/amscd2000 功能 stub + numcompress/ol2/docs/sw20lart/xetex-inputenc/umlaut/isolatin1/llncsdoc noop + thmsupp/feynman/diagrams tex 空桩。唯一未愈 1306.0281 前进到 already_def（稿在 acmart-shim 的 amsthm 之上再载 ntheorem，"Theorem style plain already defined"——drop-loads 候选）。
- **missing_file 第三 head 签名**（`Cannot find the file X`，3010310）：early_eof 误路由的 lgrenc.def×3 格全愈（补记 7 已记）。
- **babel_lang_ldf_install**（order 11，`try_exts:[.ldf,b.ldf]` + overrides 语言→包钉表）**：14 格 → 13 愈**，唯一残留 polutonikogreek——语言无对应 .ldf 文件，需选项改写非安装，单格量。
- **expl3_driver_opt_strip**（order 35，剥 documentclass 驱动选项）：4 格 → 1 愈 + 3 前进换类（other/illegal_unit/undefined_cs），非退化。
- **already_def_newcmd_renew**（order 111）：`\newcommand{\X}` 撞包先定义 → `\renewcommand`，作者书写面胜出。1003.0344/cond-mat-0501638 `\Ref` 两格 → **2/2 clean**。
- **option_clash 跨文件两规则**（merge 只合单文件双载，cls↔doc 分裂够不到）：`option_clash_loadopt_strip`（121，doc 侧含驱动词整括号剥除）愈 0905.0081（elsart 先载 graphicx[] vs doc [dvips]）；`option_clash_passopts`（122，非驱动选项 `\PassOptionsToPackage` 挂 documentclass 前 + doc 括号剥除）愈 astro-ph/0501556（aa.cls shim natbib[] vs doc [authoryear]，**意图零损失**）→ **2/2 出 pdf**（acceptable）。
- **pkg_order_hyperxmp_relocate**（order 123）：hyperxmp 整行下沉到 hyperref 载点后（非互换——`\@footnotemark@nolink` \let 三明治须保持 pre-hyperref）。bundled 老 acmart.cls vs 新 hyperxmp v5+ 硬检 → 2308.12712 → **best_effort_pdf**。pkg_order 类目首个消费规则。

**当前残盘**（fixloop.jsonl 每格末条，n=1310）：unfixable 合计 **57** = syntax 15 / illegal_unit 12 / early_eof 11 / undefined_cs 7 / capacity 5 / other 3 / fontspec_missing 2 / babel_opt 1（polutonikogreek）/ missing_file 1；no_errors_no_pdf 1（1803.00012 SIGSEGV，ticket-only）。出 pdf 1247/1310 = 95.2%。already_def/option_clash/pkg_order 三个命名簇清零。

**wave-3 候选**：syntax/illegal_unit 超簇大头即译文腐蚀（fixer-slots 属地）+ 错帽终止下游；early_eof 残 11 = 补记 7 归因的 \read 交互/no-legal-\end/错帽/svjour-option/SIGKILL 各型；undefined_cs 7 残 payload 散（sortlist/maketitle/hb/emFrenkel/eqntopsep/LARGEFun）。
