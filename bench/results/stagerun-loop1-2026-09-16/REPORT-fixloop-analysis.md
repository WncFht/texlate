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
