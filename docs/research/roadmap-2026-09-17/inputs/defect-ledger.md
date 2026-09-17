# 缺陷总账侦察输入（roadmap-2026-09-17）

> 只读侦察，2026-09-17。口径：**pinned-but-unfixed**——已发现、已留证（fuzz pin / scout 报告 / 代码注释 / fix: commit 残余注记）、当前 HEAD 上仍未修的缺陷。每条带 位置|现象|复现证据|严重度|预估修价|归属面；严重度 P0=阻塞或静默错产出 / P1=降级路径或边界失守 / P2=妆面或潜伏。末尾 P0/P1/P2 分级表 + 已清零族核销记录。

## 1. 代码面钉账（tests/ pin + 代码注记 + fix: 反查）

### 1.1 活跃缺陷钉

- **位置**：`src/texlate/xlat/batch.py:36` `_NUM_RX` + `:102` 非锚定退路（钉于 `tests/test_fuzz_xlat_batch.py:335,:857`）
  **现象**：模型整批挤一行 + 译文自带 `[n]` 引用号凑齐多重集 → 成员静默错配。
  **复现证据**：`parse_batch_response("[1] 结果如文献 [2] 所示成立", 2)` → 各分半句；e2e ok/batched 直通 diff 校验落 PDF（1500-iter oracle 证锚定路径免疫）。
  **严重度**：**P0**（CONFIRMED 静默错产出进成品）·**修价**：M（单文件——错配检测或批协议硬化）·**归属**：xlat
  **备注**：65392d4 登记的 3 CONFIRMED 之首；修复时断言应翻转。

- **位置**：`src/texlate/xlat/batch.py:106-110` `@@` 兜底段
  **现象**：编号解析失败后 `@@` 段不剥 `[n]` 序号字面 → 标记原文进译文。
  **复现证据**：characterization 钉（`@@` 行本身在编号路径也按字面留段内）。
  **严重度**：P1（译文腐蚀字面可见）·**修价**：S·**归属**：xlat

- **位置**：`src/texlate/xlat/batch.py` n=1 行内标记
  **现象**：`"x [1] y"` → `["y"]`——标记前文本静默丢弃。
  **复现证据**：`test_inline_marker_drops_prior_text` 现状钉。
  **严重度**：P1（内容丢失）·**修价**：S·**归属**：xlat

- **位置**：`src/texlate/xlat/batch.py:36`（PLAUSIBLE）
  **现象**：`[[n]]` 字面——行首锚定不吃 `[[`、非锚定吃内层 `[n]` → 产 `]` 残渣段。
  **复现证据**：`test_fuzz_xlat_batch.py:352` observed。
  **严重度**：P1·**修价**：S·**归属**：xlat

- **位置**：`src/texlate/xlat/retry.py:44` `SLOT_NAME_RX` vs `:214` `_valid_slot_text`（PLAUSIBLE）
  **现象**：`⟪S1⟫`（<4位）/`⟪s0000⟫`（小写）/`⟪S0000`（未闭合）畸形槽 token 全放行 → 原文可进装配译文。
  **复现证据**：`test_fuzz_xlat_batch.py:443`。
  **严重度**：P1·**修价**：S·**归属**：xlat

- **位置**：`src/texlate/share.py:453-458` unpack_share 发布段（钉于 `tests/test_fuzz_share.py:734`）
  **现象**：多文件 rename 非事务——预检收敛确定性冲突后，环境级中段故障仍部分发布（docstring 自承「无回滚承诺」）。
  **复现证据**：现状钉 `zh-src.zip == STALE`（仅因成员序位幸存；先 rename 的成员无保护）。
  **严重度**：P1（环境级理论窗，share 导入完整性）·**修价**：M-L（回滚日志或单件发布化）·**归属**：server/share

- **位置**：`src/texlate/compile/engine.py` `_ERR_FILELINE_RE`（钉于 `tests/test_fuzz_logpipe.py:464`，全仓唯一存活 strict-xfail）
  **现象**：文件名面过宽——收无扩展名/含冒号/含括号文件名（`Makefile:5:` 系）。
  **复现证据**：`test_xfail_error_line_filename_width` 参数化 5 行；fixloop.logparse 借同一 regex，三层不一致。
  **严重度**：P1（错计错误行归属，下游归因面偏）·**修价**：S-M（收紧 regex + fixloop 侧同步）·**归属**：compile/fixloop
  **备注**：e12aecb commit body 明记「defect #3, engine-side remain」——同族 #1/#2（redlines/misschar）已修。

### 1.2 未钉观察（文档化 latent）

- `tests/test_fuzz_inject.py:59-66` 六件：`[...]` 深度幻影缝 / already 漏检（双注入无害）/ float_sizing docstring 0/1↔N 漂移 / mode 无校验非 ctex 一律 xeCJK / threeparttable 子串门过触发 / 无扩展名 `\input` 不跟随——P2。
- `src/texlate/latex/mouth.py:150` + `gullet.py:1592`：write-through 前缀链透传未实现（`\write`/`\catcode` 族展开盲区）——P2 latent。
- `tests/test_fuzz_store.py:373` 静默归零钉——自注「非 defect」，不计。

### 1.3 陈旧 pin 文档（P2 文档债，单批可清）

`tests/test_fuzz_inject.py:28-57` I1-I9 仍称「钉住的确认缺陷」（0d93d66 已全修+全拆钉）；`tests/test_fuzz_xlat.py:991` 注「非 UTF-8 分支由独立 xfail 钉」（已修，:1004 普通断言）；`tests/test_app_endpoints.py:5` 头注 +:182「下条 xfail」（400/500 分裂已修）；`tests/test_fuzz_mask.py:353`「缺陷以 xfail 钉在末段」（bfd1d17 已修幂等）；`tests/test_fuzz_logpipe.py` 头注 +:416/:428/:481/:496「原 strict-xfail」注脚（fffd_glyph/redlines/misschar colon 均已修）。

skipif 余量全部为环境守卫（euid/platform/gitignored-data），无缺陷伪装。

## 2. scout/audit 面钉账（bench/results + docs/research）

覆盖：13 份主 scout 报告 + 11 个 scout-* 目录 + 20 份 audit 报告 + still-manual-audit/m3smoke/wave 复核 + roadmap inputs 三份 sibling；闭项逐一对 HEAD 核码验证。**scout 面 open P0 = 0**（今日 P0 级全灭：bare_cs/ph_in_cs/cache 毒化/dispatcher/security 闸全落）。

### 2.1 P1 —— 降级路径/真实语料影响（16 条）

- **位置**：`latex209.py:385-389` + `inject.py:465-466`。**现象**：spec 改名目标类不解析即放行 → zh 臂 missing_file fail（jpsj3 实证，期刊站分发非 CTAN 无救）。**证据**：scout-coreleak-2026-09-16。**修价**：M。**归属**：latex/1d——reject:latex209_no_target 两级校验（rglob+kpsewhich fail-open）。
- **位置**：`worker/compile.py:946 _build_dual`（zh 字段 :980）。**现象**：fallback_orig 行 translation=en 原文写进 dual.json zh 位 → `_share_apply` matched=ok 英「译」+ reader zh 槽英文。**证据**：share-texlog-audit 外部#1（validate_pair(en,en)=ok 实证）。**修价**：S-M。**归属**：worker/share——pack 侧非 ok 行 zh="" 或剔；消费端 zh==en/zh=="" 判 miss。
- **位置**：`worker.py:181 COMPILE_TIMEOUT` + ctor:1139 vs `app.py:432-441`。**现象**：compile_timeout 旋钮断头路——settings/env/flag 全无，恒 240s。**证据**：capacity-scout-2026-09-17 表。**修价**：S。**归属**：server/settings。
- **位置**：`sandbox.py:191-250 run_process`。**现象**：无 rlimits（内存/CPU/nofile）——仅 killpg 墙钟+8MB stdout cap，TeX 失控进程可吃光宿主。**证据**：capacity-scout-2026-09-17。**修价**：M。**归属**：compile/sandbox。
- **位置**：`e2e.py:772` vs worker fixloop 引擎。**现象**：halt_on_error 两侧相反（e2e True/worker False）→ fixloop 每轮错误面不同，分类输入分叉。**证据**：e2e-resid-audit F4——需裁决哪侧权威。**修价**：S（裁决）+S。**归属**：e2e+worker。
- **位置**：`bench/py/e2e_real_bench.py:899` + `_code_stamp:510`。**现象**：(a) --date 跨日重启劈目录全重跑；(b) 印章钉 live repo 不钉快照 → 无关 dirty 触发全量 stale。**证据**：scout-e2ereal-2026-09-17 风险清单 #1#2。**修价**：M。**归属**：bench/e2e_real（1e）。
- **位置**：fixloop rules `graphic_repair` + `missing_char_fix` + `shim_map`。**现象**：三缺口——多 eps 缺图不触发 repair（1404.5720×5）；数学字体域 misschar（ø cmmi8/ĳ txmi）无规则；aa.cls stub natbib 失配/aipproc theacknowledgments 缺/aastex63 `_` catcode 未复刻。**证据**：scout-pf2fails/pf2final-2026-09-17。**修价**：M each。**归属**：peer1 fixloop。
- **位置**：fixloop missing_character 动作路由。**现象**：CJK（U+4E00-9FFF）缺字走 install（kotex 错配实证×2）——应走 binding/font_fallback。**证据**：fbucket-scout F-font 型。**修价**：S。**归属**：peer1。
- **位置**：fixloop 救援物自身 `aa.cls` legacy shim + `graphicx.tex`（miniltx）。**现象**：shim 三格同炸 `\section`→Missing \endcsname×100；graphicx.tex `\zap@space` xelatex 无限递归爆栈。**证据**：fbucket-scout F-stub 型 4 格。**修价**：M。**归属**：peer1。
- **位置**：`latex/tables.py` DIMEN_TAIL_KIND/TRANSPARENT_HEAD_SPEC。**现象**：illegal_unit 4 簇残余 ~25 格（逗号小数/组参·可选参/`\\[dimen]`/散文区寄存器尾参）。**证据**：illegal-unit-scout + scout-triage（62/90 已随在飞转 clean）。**修价**：M-L。**归属**：1d（在飞线延续）。
- **位置**：accent 展开缺字 U+0332/00C5/0131。**现象**：数学域 accent 展开产物缺字无签名级规则（`\newunicodechar` 结构性盲区）——3 格同型。**证据**：scout-modec-resid。**修价**：M。**归属**：peer1。
- **位置**：`stagerun.py` compile resume 键 + `fixloop_bench.py:406-814`。**现象**：resume 键不核树内容（rerun 换树旧 zh 仍判 done 归因错）+ `_ON_PRED[all]` 含 error 格 + `shutdown(wait=False)` race；fixloop_bench `json.loads` 裸 ×4。**证据**：bench-harness-audit 飞区清单。**修价**：M。**归属**：peer1/bench。
- **位置**：`tests/` l2 合成边界 11 件（scout-l2edges）。**现象**：file:line Warning 豁免每编译必走却零断言——生产 `-file-line-error` log 回归即全判 dirty 无报警。**证据**：l2edges-scout（loop1 186 warning 命中实证）。**修价**：S each。**归属**：1e/validate（已派工）。**备注**：首件 P1，余 P2。
- ~~**位置**：`share_pack` 端点 `app.py:~1080`。**现象**：index_lookup 实抛 OSError/UnicodeDecodeError 但只捕 ShareError → 非 UTF-8 索引/路径 500；flat 检查漏 NUL → `.stat()` ValueError 500。**证据**：share-texlog-audit 外部#2（实证）。**修价**：S。**归属**：app/share。~~ **已核销**（2026-09-17 复核：1d1ad8d+9325aa1 当日已修，TestIndexDegraded 钉在；残余 worker/share.py `_share_lookup` 扁平检查漂移由 `9acced6` 补齐）
- **位置**：worker splice 失效后 files 表 + app main-change retry。**现象**：失效重编失败 → 旧 zh_pdf/zh_src_zip/dual_json 行与磁盘件照发 partial；换 main 后 en.pdf/md.zip 陈旧照发（`delete_file` store.py:772 已存在，接线面未核）。**证据**：worker-audit 未修清单。**修价**：M。**归属**：worker/store。
- **位置**：hep-ph/9910403 splice macro-body 回放截断。**现象**：pf2final fail 格——macro body 回放进 zh 截断。**证据**：scout-pf2final 路由结论。**修价**：M。**归属**：1d。

### 2.2 P2 —— 妆面/潜伏/待裁决（~30 条）

- G3 retry{model} API 分叉（spec 写 retry{model}，实装=换 model 建新任务）——裁决 A 改规格 <0.5d | m3gap-scout
- G2 Redis 形态裁决 pending | m3gap-scout
- `cache_key_for` 排除 glossary/options（§4.3 故意但产物错命中 reuse）——spec 决策 | server-persist/worker-audit
- 三份并行 parse_log 口径漂移（engine/logparse/l2）——对照表已产，五件三点重复维持 | compile-core/validate/share-texlog audits → peer1
- ScanWarning kind 19 字面散落无注册表，docs/07 写 13（audit C3）| architecture.md/latex
- 1404.5720 rc=141 SIGPIPE killed_signal 未解码（`judge._signal_attribution` 不认正 rc≥128）| scout-e2ereal#4/pf2final → peer1
- `e2e.py:398 _l2_parse` 空 log 直返不退 stdout_tail | compile-core-audit → 1d
- e2e `_tail_dict` verdict 缺 payload 键 vs benchlib.judge_dict | bench-harness-audit → 1d
- e2e_mock translate_tree 漂移副本（大小写/4门/Glossary/cache 缺）+ `stagerun.py:644` .RTX.TEX 未 lower | e2e-resid-audit → bench/peer1
- `probe_file` cwd 隐式前提（`engine.py:1224` 裸 kpsewhich 依赖 cwd∉workdir）| apj-bib-scout → peer1
- thmtwin 通用规则未立（bespoke stub 已修个案）| scout-thmtwin → peer1
- modec-resid 4 格：209 `\abstract` 命令对/math `\AA`/math `\i` accent/JINST shim_map | scout-modec-resid → peer1
- fixloop clean 不查 CJK（1706.00217 russian clean vs post partial 口径缝）| scout-triage → e2e 记档
- `verdict.category` 首错遮 bulk（quant-ph/9703040 110 错 108 missing_number）| scout-triage → 1e 口径
- B2 settings 存不可用 model 持续毒化后续任务——UX 注记 | m3smoke
- F-echo MockTranslator 西里尔/希腊源恒等（bench 盲区登记或 `_PROSE_RUN_RX` 扩 Unicode）| fbucket → 1e
- docs/05 §5.x LaTeXML 规格改写成 arXiv HTML DOM | latexml-spike → docs
- realpostfix2 残余：浅合并残键/cases.jsonl 无去重/results.json 撕写窗/空 records 种子/抽样漂移/auth 死亡不停车（6 低）| scout-e2ereal
- DomPane `pages()` 用 `el.offsetTop`——相对 offsetParent 非 pane 根；当前 sanitize 剥光样式无 positioned 祖先故无恙，未来放行 CSS position 即锚错位（PLAUSIBLE latent）| wave8-review → web
- worker `dur_s` 口径瑕疵：`stage_xlat.py:186` t0 打在 paper_sem 外→xlat dur 99.6% 是跨论文排队——度量件缺陷非产品缺陷 | perf.md §1（在修）
- worker 残余低危：`_run_doc` cancel 孤儿 export 线程（结构限）；`_materialize_reuse` 删除命中→done 零产物窄窗；enqueue 先于 start secrets 残留；share_pack index_append 失败孤儿 bundle | worker-resid-audit
- server-persist 记档：append_event open tx 自愈窗；upload plain-retry 残留产物 | server-persist-audit
- cli backlog：Fetcher 无 close() 门面；unpack_share 中途败留部分成员；parse_file OSError TOCTOU；settings raw()/has_key 面 | cli-audit
- arxiv 记档：RateLimiter/Fetcher 无锁（单写者）；_resolve_bib x.bbl 探测歧义；Retry-After 保守偏离 | arxiv-texlog-audit
- sidecar 残余：_STAGE_ROW_RE 误吃 stage 行（SSE 展示面）；harvest_outputs dual-only 边例；spa_dir() 无 resolve | server-sidecar-audit
- textutil 记档：cyrillic-veto 语料标注；decode_tex_with 双幂等 nit；_CJK_DECLARED cp54936 死项 | textutil-e2e-audit
- bench 小项：qualbench first-seen model 错标；cells.json 非原子；verify_chunk 2×GB RAM；build_corpus_expand Range-忽略整 tar RAM；e2e_mock 无 resume-skip；triage 读时点不原子 | bench-harness-audit
- ci/dep 观察：defusedxml 上游停滞；eslint 三套 pins 手工同步；gitleaks 钉 v8.30.1 vs brew 浮装；xelatex apt 未钉；autocorrect ci 门缺席 | dep/scripts-ci audits
- xelatex 每 pass `max(10,timeout/passes)` 稀释语义——产品裁决 backlog | compile-core-audit
- `route_project` reject 分支 dead-ish（engine 恒非空）| textutil-e2e-audit
- dist/ 陈旧 wheel（2026-09-16 09:32，缺 compile/cmaps）——发版前 `uv build` | server-sidecar-audit
- `texput.log` + `tests/test_group_surface_depth.py` 未跟踪散件 | scripts-ci-audit
- 0916 余账：corpus_v2 manifest 数字；INLINE_MAX 已除；B3/B7/Mode-B/C 臂（波次后大概率已跑，未逐项核）

### 2.3 侦察覆盖附记

fuzz 报告目录（app-boundary-fuzz/cli-fuzz/arxiv-fuzz 等）未逐读——pin 归代码面覆盖；fixer-*/verifier-batch8 是修复现场非新票；冒烟类（armed/dist/docker/live/server/cli-smoke）过即无票；m1b-criteria/envarg 为口径评估非缺陷源；e2esmoke matrix 是格结果非票单。

## 3. 分级表

| 级 | 条数 | 内容 |
|---|---|---|
| **P0** | **1** | xlat batch 非锚定退路成员静默错配进成品（`batch.py:36`+`:102`，已转 1e） |
| **P1** | **22** | 代码面 6（xlat batch 族 4 + share 非事务窗 + _ERR_FILELINE_RE 文件名面）+ scout 面 16（见 §2.1：latex209 spec 校验 / dual zh 位英文 / compile_timeout 断头 / sandbox 无 rlimits / halt_on_error 分叉 / e2e_real 印章 / fixloop 三缺口 / CJK 缺字路由 / 救援物自炸 / illegal_unit 残余 / accent 缺字 / stagerun resume 键 / l2 warning 断言 / share_pack 500 / splice 失效产物照发 / splice macro 截断） |
| **P2** | **~43** | latent 8 + 陈旧 pin 文档 5（代码面）+ scout 面 ~30（见 §2.2，含裁决 pending 项） |

**形态结论**：xlat batch 协议是唯一成族缺陷窝（1 P0 + 4 P1 同文件）；fixloop 规则面是 scout 面 P1 最密归属（peer1 占 6/16）；已清零族运转良好（今日核销 27+ 项，pin 机制健康）。

## 4. 已清零族（台账闭环证据）

inject I1-I9（0d93d66）、worker W1-W7（4de2360）、mask 5 族+lstinline（bfd1d17）、logpipe 姊妹钉（e12aecb）、xlat 非 UTF-8 漏 catch（df86f05）、app 400/500 分裂、fallback_unverified 三态分歧（3db4a08）、G1 arxiv_html emit 链（ebf462a+6914391）、vendored_fetch 件库（a90978a）、l2 chunk 归因落账（09fcafa）——pin 清零机制运转良好。
