# spec · 编译引擎与 fixloop

> 范围：`compile/` 全目录——引擎路由与双引擎、沙箱/进程、注入、判定/探测、LaTeX 2.09 升级、fixloop 修复引擎。归一化层（`compile/normalize.py`）归 `translate.md`；翻译编排归 `translate.md`；解析归 `latex-pipeline.md`。
> 口径：现行实现描述，符号引用为「模块 + `::符号`」粒度；实测证据引 `research/` 档。

## 0. 总览

```
splice 树 ──► normalize 归一化（translate.md）──► route_project 静态路由
         ──► prepare_chinese 注入（ctex/xeCJK + 兼容块 + layout 手术）
         ──► 沙箱编译（engine.compile）──► judge verdict
         ──► fixloop（yaml 规则循环）──► clean/partial ──► cjkmap ToUnicode ──► zh.pdf
```

判词口径：编译判决三值 `clean`（无错有 pdf）/ `partial`（有 pdf 有错或缺字）/ `fail`（无 pdf），**无 `reject` 终态**——route/inject/fixloop 三处策略拒绝统一归 `partial` + `reject_at ∈ {route, inject, fixloop, share_verify}` 审计字段（拒绝是降级交付不是 fault）[^f3-note]。铁律「出 PDF ≠ 成功」见 translate.md §0。

## 1. 引擎层（`compile/engine/`）

### 1.1 Engine 协议（`engine/_base.py`）

`Engine` 是 `@runtime_checkable Protocol`，9 名成员：属性 `name: str`、`caps: frozenset[str]`；方法 `detect()`、`compile()`、`probe_file(fname, *, cwd)`、`install_file(fname, *, font_related)`、`rebuild_fontmaps() -> bool`、`filemap(fname)`、`parse_log(res) -> LogInfo`。

`compile(wdir, main, *, passes=None, timeout=DEFAULT_TIMEOUT=240s, outdir=None, sandbox=True, env_extra=None, best_effort=False, flags=None, should_cancel=None) -> CompRes`：`passes=None` 为自适应口径（按 rerun 提示续跑、上限 `MAX_PASSES`），显式 int 为无条件 ≤N 遍；`best_effort` 让 xelatex 摘 `-halt-on-error`、tectonic 强制 `continue-on-errors`；`flags` 是 fixloop 规则请求的追加 CLI flag（拒放者落 `flags_dropped`）；`should_cancel` 轮询钩抛 `CancelledError`。`CompRes` 字段含 engine/ok/pdf/log_path/log(LogInfo)/log_text/timed_out/sentry_reason/passes/rc/killed_signal/bib_ran/stdout_tail/deps/sandbox_mode/flags_applied/flags_dropped + `has_pdf` 属性。共享件 `_collect_compile_outputs`（stdout_tail 截 4000）、`_driver_fatal`（stdout `*: fatal:` + 失败相才采信）、`_salvage_driver_fatal`、`_checked_main`（NUL/`..` 逃逸拒）。`parse_log` 契约：log_text→log_path→stdout_tail 兜底 + salvage。

caps 语义：xelatex=`{"kpsewhich","tlmgr","updmap","recorder"}`，tectonic=`{"bundle"}`——fixloop 据此裁剪可跑规则（`cap_available` 门）。

### 1.2 静态路由（`engine/_route.py`）

`route_project(root, *, prefer="tectonic") -> RouteDecision{engines, reject, reasons, non_utf8, latex209_suspect}`——`reject` 槽位保留但**恒 None**（LaTeX 2.09 无条件拒已移 fixloop `latex209_reject` gate）。流程：扫全部 .tex → `decode_tex`（非 UTF-8 记 `non_utf8`）→ `visible_tex` 遮盖 blob 上跑签名集。

| 签名               | 检测                                                                                                                          | 路由效果                                      |
| ------------------ | ----------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| eps/pstricks       | `*.eps` 文件、`@pstricks` 签名（`PSTRICKS_SIG_ALTS` 单源：pstricks/pstricks-_/pst-_ 包名元素级 + `pspicture` env + `\psset`） | **xelatex 置首**（xdvipdfmx 硬墙）[^pstricks] |
| minted+frozencache | `_MINTED_FROZEN_RE` 且 minted 同现                                                                                            | tectonic 置首（bundle v2.6 吃 v2 缓存）       |
| bitmap fonts       | `bbm/bbmfonts/dsfont/bbold/yfonts/wasy/wasysym`、`*.mf`                                                                       | reasons（tectonic 高风险提示，不改序）        |
| `\special{psfile}` | dvips 原语插图探测（`_PSFILE_SPECIAL_RE`）                                                                                    | reasons（双引擎均不渲染，注记不改序）         |
| 非 UTF-8           | `decode_tex` 分档                                                                                                             | reasons                                       |
| `\documentstyle`   | LaTeX 2.09 嫌疑                                                                                                               | `latex209_suspect` 标记 + reasons             |

决策默认 `prefer="tectonic"`（便携无 tlmgr 依赖、初始 clean 率更高），命中 xelatex 签名即重排[^engine-matrix]。消费方：`e2e.py` 与 `server/worker`（经 `worker/seams.route_project`）；probe 的 `prefer_engine` 是 advisory 不改本决策。biber/biblatex 版本错配不在本层——归 fixloop `builtins.bib.biber_biblatex_skew_route`（`rules/80-bib.yaml`，order 8）。

### 1.3 XelatexEngine（`engine/_xelatex.py`）

- 命令：`xelatex -no-shell-escape -interaction=nonstopmode -file-line-error -recorder -output-directory=out`；`halt_on_error ∧ ¬best_effort` 时插 `-halt-on-error`（ctor 旋钮；e2e/repair best-effort 口径置 False 对齐产出，fixloop 内部引擎用默认 True）；fixloop `flags` 经 `_split_flags` 过滤——`-output-directory/-aux-directory/-jobname` 等 output-rekey 前缀丢 `flags_dropped`，sandbox_mode=="env" 时剥 `-shell-escape` 系。
- pass 循环：`MAX_PASSES=2`；`per_pass=max(10, timeout/eff_passes)`；停则：超时/执行失败/无 pdf 恒停；rc>0 非信号停，**除非 `passes=None` 且有 rerun hint**（`_RERUN_HINT_RX`：rerun to get|labels may have changed|undefined references|table widths changed；裸 rerun 与 biber 请求排除）——rerun hint 可覆盖 rc≠0 续跑；负 rc（信号死）保续跑通道。
- **bibliography 中 pass**（`_bib_pass`）：p<eff_passes ∧ ¬bib_ran ∧ 非死相时——`<stem>.bcf` 存在且无 peer `.bbl` → 跑 `biber <stem>`；否则逐 aux 查 `\citation+\bibdata` 缺 `.bbl` → bibtex（`_BIB_AUX_SCAN_MAX=8`、工具超时 60s、BIBINPUTS/BSTINPUTS 前缀 `wdir:out`）。`_bbl_complete`（尾 4096B 见 `\end{thebibliography}|\endinput`，biber 另要 rc==0）才采纳，`bib_ran` 记 `biber:stem`/`bibtex:rel`，`passes=None`+采纳→eff_passes+1。
- env：`buf_size=8000000`、FONTCONFIG_FILE 生成 conf、TEXMFHOME 链（usertree 首）；tlmgr 调用走 `_usertree_env` 去链防自引用。
- `probe_file`：cwd 先 + kpsewhich memo(4096)。`filemap`：`ctan.TlpdbIndex.ensure` 离线索引优先 → `tlmgr search --global --file` 兜底，`_cache.py` 落盘缓存（`TEXLATE_TLMGR_CACHE`；负条目不持久）。`install_file`：probe→filemap→`tlmgr --usermode install`（flock 串行）→`_post_install_verify`→CTAN 覆盖兜底→`_relocate_doc_only`。`rebuild_fontmaps`=updmap-user。res.ok=¬timed_out∧rc≥0；`deps`=`compiled_dependencies`（§3.2）。

### 1.4 TectonicEngine（`engine/_tectonic.py`）

- 命令：`tectonic --color never -X compile --untrusted --keep-logs --keep-intermediates --makefile-rules out/dependencies.mk --outdir out`；`continue_on_errors ∨ best_effort` → `-Z continue-on-errors`；+ bundle flag + `--hide` + 映射 flags + main。`_TECTONIC_FLAG_MAP` 仅 `-synctex`→`--synctex`；`_TECTONIC_Z_OK` 白名单 `{continue-on-errors, minify-bundle, keep-intermediates, keep-logs, deterministic-output, synctex, paper-size, trace, hide}`——`-Z shell-escape` 与 output-rekey 系全丢（安全面）。
- bundle 三源：ctor `bundle=` > `TEXLATE_TEX_BUNDLE` env > `TECTONIC_BUNDLE_PIN`（`tlextras-2022.0r0` 钉版）；低版本用 `--web-bundle` 名。冷拉 bundle 需网——sandbox `allow_net=True`。
- 双尝试 `_TECTONIC_ATTEMPTS=2`：`(timeout, min(timeout,120))`——超时后重试一次，timed_out 只记末次；`del passes`（引擎自决 pass 数，记 passes=1）；`_mirror_source_dirs` 预建镜像子目录。
- `probe_file` 仅 cwd 内含解析；`install_file`→注入的 `ctan_fetch` callable（fixloop `CtanFetcher`，§6.5）；`rebuild_fontmaps`→False；log 缺席时 `^error:` 扫 stdout_tail。
- 三大硬墙（换引擎信号）：EPS/PS 图（xdvipdfmx 不支持）、bundle 缺物理字体（`.vf or physical font`）、bundle 包版本旧语义错（不可选版只能换引擎）[^engine-matrix]。

## 2. 沙箱与进程（`compile/sandbox.py` + `compile/proc.py`）

`child_env` env 白名单三层（非黑名单）：`_ENV_PASS_EXACT`（HOME/PATH/TMP*/LANG/LC__/USER/LOGNAME/SOURCE_DATE_EPOCH/TEXLATE_TEX_BUNDLE）+ `_ENV_PASS_PREFIX`（TEXMF_/TEXINPUTS/BIBINPUTS/BSTINPUTS/*FONTS/TEXFONTMAPS/ENCFONTS）+ `_ENV_FORCED`{`TECTONIC_UNTRUSTED_MODE=1, openin_any=p, openout_any=p, shell_escape=f, max_print_line=10000`}——env_extra 压不过 forced。

`_apply_sandbox` 四态 `off/sandbox-exec/bwrap/env`：

- darwin `sandbox-exec` SBPL profile：deny `$HOME` 读 + 全写，白名单放行工程/输出/缓存/字体目录；`allow_net=False` 追加 `(deny network*)`。
- linux `bwrap`：`_bwrap_capable` lru 探针（`TEXLATE_NO_BWRAP` 真值即否）→ `--die-with-parent --unshare-pid/ipc/uts [--unshare-net] --cap-drop ALL --dev --proc --tmpfs <私有临时目录> --dir $HOME`，系统目录 ro-bind-try、kpathsea 目录按 W_OK 升 rw、`$HOME` 不挂（rw 白名单 texmf/缓存 + extra_rw）。xelatex 工具链全本地 `allow_net=False`，tectonic True（bundle 拉取）。
- `env` 态只剩 env 白名单（无文件系统隔离）。
- `_rc_to_signal`：负 rc→`-rc`；sandbox 包装下 128<rc≤192→`rc-128`。

`proc.py::run_process`：`Popen`（stdin=DEVNULL、stderr→STDOUT、`start_new_session` POSIX、preexec rlimits AS=4GiB/NOFILE=1024/CPU=max(2×timeout,600)）→ `_drain_bounded` 排干环（monotonic deadline + poll 终态 + should_cancel 0.5s 分片 + headroom=4×out_cap 尾截 + `_RunawaySentry` 活哨：`page_flood` 单调 `[N]` 页面包络 ≥10000、`vbox_flood` 密度签名）→ 超时/哨兵→`timed_out=sentry.reason|True` + `_kill_tree`（killpg 整树→`proc.kill` 兜底）+ 30s 续收。`except BaseException`（KeyboardInterrupt/GeneratorExit 等）同样杀树再抛——setsid/双 fork 逃逸的孙进程仍握 stdout 写端，二段 wait 由调用点兜。返回尾部 `out_cap=8MB`。

## 3. 判定、探测与 log 层

### 3.1 judge（`compile/judge.py`）

`judge(res, *, expect_cjk, log_text) -> Verdict{status, reasons, notes, n_errors, category, payload, error_cats, error_pay, cjk_chars, missing_chars, warnings_hit}`，`status ∈ {clean, partial, fail}`。

判定序：timed_out→fail（sentry_reason/str timed_out→category=`runaway_output`+错误构成保留；否则 classify 后 `cat=="timeout"` 再 `_is_runaway_output` 全文复核）；killed_signal/rc<0→reason+note（有 pdf 也 dirty）；`_driver_fatal`→reason（category 空/other 时夺为 driver_fatal）；无 pdf→fail+`no_pdf`+category+error_cats 早退。有 pdf：classify 首错→category/payload + `_error_composition` 逐行裸分类聚 `error_cats/error_pay`；`n_errors>CLEAN_ERR_MAX(3)`→reason；首错 cat∈`DIRTY_FIRST_CATEGORIES`{missing_file, missing_tfm, missing_pfb, missing_graphic, fontspec_missing, undefined_cs, ps_image, latex209}→reason；`warnings_hit`→reasons、`warnings_sys`→notes。终态 `clean if not reasons else partial`。

探针三件：`_missing_char_check`（门控缺字计数=nullfont 豁免−sweep 豁免；`expect_cjk` 时计数入 reasons，良性命中入 notes）、`_thm_restate_probe`、`_machine_slot_probe`（`\newcommand` 机位实参非 ASCII→note，cap 20）。`expect_cjk` → `_cjk_render_check`（pdftotext 计 CJK 字符：`0`→reason `cjk_chars=0` + `tofu_veto`→**status fail**；`<20`→reason；`-1` 未测→missing_chars>0 落 reason 否则 note）——零中文字节的 PDF 是最坏静默失败，fail 级判死。另出 `machine_slot_audit`/`paired_slot_diff`（src/zh 占位符机位多重集 diff→`slot_arg_missing/extra`）。

### 3.2 probe 与 deps 权威

`probe.py::target_probe(work_dir, main_rel, deps_index) -> ProbeReport{deps[DepProbe], inputs, missing, tl_packages, prefer_engine, flags, notes, index_available}`——静态探针：`_PKG_RE`/`_CLS_RE` 只扫 preamble（`\begin{document}` 前 + 死尾截断），`\PreventPackageFromLoading` 抑制；documentstyle→latex209 ctx + `docstyle_opts` 按包 deps 扫；`_SWP_RE`/`_INTERACTIVE_RE`/`_PSFILE_SPECIAL_RE` 指纹。`_dep_signal`：`.eps`→xelatex、minted→shell_escape（frozencache→tectonic pref）、pstricks 系→xelatex、bitmap fonts→tectonic_risky。**worker 接线为 best-effort 旁路**：依赖计数/`tl_pkg` 可装清单/`prefer_engine` 分歧只进 log 播报，探针崩溃不阻塞编译，装包仍归 fixloop/tlmgr——「译文桩预编译」形态未落地。

`deps.py::compiled_dependencies(root, main, out, engine)` 是**翻译文件集权威**：xelatex 读 `{stem}.fls` INPUT 行；tectonic 读 `dependencies.mk`（`_makefile_inputs` Make 转义首规则 + `_tectonic_unescaped_inputs`）；名字限 root 内 ∧ suffix∈{.tex,.sty,.cls,.cfg,.def,.clo,.fd,.ltx}，main 必须在集否则 None。probe 的 inputs/missing 是静态预计，fls/mk 是实测权威——静态 `\input` 图只作编译失败时降级。`deps_diff(expected, recorded)`→`DepsDiff.saw(fname)→bool|None`，`dep_seen` basename 兜底。

### 3.3 log 层分层

- `texlog.py`（顶层）：`file:line:` 文件栈词法原语单源（`match_error_line`/`iter_log_events`）——engine/L2/fixloop 三处收敛于此。
- `compile/loginfo.py`：`.log`→`LogInfo` + `WARNING_RED_LINES=[invalid_utf8, fffd_glyph, missing_chars, missing_graphic, degraded_file]`（warning 扫描/judge 面；`degraded_file` 即 tectonic `^!.*(File|package).*not found` 跳包降级行——continue-on-errors 跳包出残页 pdf 的暗雷）。与 L2 面 `_REDLINE_CLASSES` 按层查名、经 `redlines.py` 单源注册。
- `compile/logparse.py`：parse + taxonomy 分类（compile 层共享地基，fixloop 消费）：`ErrReport`(first/ctx/pre/post/n_bang/tail/line_no/file_stack/popped_files/warnings/warnings_sys/raw/errs≤32)、`Taxonomy`（head/tail/warnings 三 scope 评估序 + `_tail_preempt` preempts 抢占 + subclassify 收窄 + `payload_scan{capacity, undefined_cs}` + `_cap_verdict_cat` input_stack 重路由）、`_is_runaway_output`+`_RUNAWAY_*` 阈值（与 proc 活哨同语义双臂）。

## 4. 注入、版式与主文件

### 4.1 中文注入（`compile/inject.py`）

`inject_cjk(tex, *, mode="ctex", root, _defer_math_fallback) -> (text, info)`；`InjectRejectError(ValueError)` 带 `.reason`（msg=`inject_reject:<reason>`）。`\documentstyle` 先走 `latex209.upgrade_209`（§4.4）——不可转才抛拒，「禁止注入」是兜底语义。status ∈ `injected` / `already`（已有 CJK 支持）/ `no-docline`（无 documentclass 锚）。seam 定位 `find_docclass_ends`（visible_tex depth-0 docclass seam 表 + `_macro_proxy_seams` 宏体兜底）、`_splice_before_document`（`\begin{document}` 锚，空白容忍；允许 bd 落 `\input` 闭包内）。注入块 = `CTEX_LINE`(`\usepackage[fontset=fandol,UTF8,zihao=false]{ctex}`；非 ctex 模式给 XECJK_BLOCK) + ACM_BASELINESTRETCH_GUARD + THEOREM_ANCHOR_SHIM + CJK_FIRST_USE_WARMUP + TIE_ACCENT_FIX + TEXT_8BIT_FALLBACK + OVERFLOW_MITIGATION；`CJK_MATH_FALLBACK` 沉 pre-bd（mathgroup 编号）；多 seam 加 `\ifdefined\TeXlateCJKloaded` 幂等壳。`_input_hop_inject` 一跳 `\input` 载具注入（cap 64）。

`prepare_chinese(root, main, *, mode, float_sizing=True, demote_wrap=True)`：tar 伪装→reject("nontex")；no-docline→hop；`demote_wrapfloats`+`inject_float_sizing` 入 info。**ctex 默认路径**（双引擎实测可编译、白拿节名汉化）；xeCJK+fontspec 为降级路径（ctex 冲突签名→fixloop 或探测切换）。

### 4.2 版式手术（`compile/layout.py`）

- `FLOAT_SIZING`（有 figure/table 才注入）：@endfloatbox patch，ht+dp>`\textheight`→`\resizebox*` 缩 + `\typeout{TeXlate-Float-Fit}` 回读。
- `demote_wrapfloats`：wrap*→figure/table[!htb]+centering+minipage 原宽，负 vspace 删。
- ~~`TABLE_FITTING`~~（0930 拔除）：表族 env/before+after 成对钩套 adjustbox 在配对不候场形（cls cs 形收尾/宏内 env/`\end{document}` 早退）及与 fixloop v1 注块并挂时崩 `ended by` 毁编（vault ~1200 事件）；表族钳宽归 fixloop `tabular_fit` v2 源级跨度包（warn_overfull 驱动，97-layout.yaml）。

### 4.3 cmap 注入（`compile/cjkmap.py`）

`embed_cjk_mappings(pdf)`：pypdf 克隆，/Resources 链（含 XObject 递归）找无 ToUnicode ∧ Identity-H/V ∧ CIDSystemInfo Adobe-GB1 的 CID 字体，共享一份 `cmaps/Adobe-GB1-UCS2`（221KB，与 poppler 同字节）flate 流补 `/ToUnicode`，`.mapped.pdf` 原子替换——中文 PDF 可复制可搜索。

### 4.4 主文件与 LaTeX 2.09

`mainfile.py::find_main_tex`：depth-0 docclass + bd 在自身或 input 闭包（filecontents 虚拟成员）；排序 aux 降权 → basename main/paper/ms → 语言秩 → tpl → 深度 → body mass → size。`classify_no_main`→latex209/plain_tex/garbage/None。

`latex209.py::upgrade_209(tex, *, root)` 受限升级器（`\documentstyle`→`\documentclass`）：status∈converted/reject/no-docstyle；reject 三因 `latex209_no_decl`/`latex209_ds_at`(ds@ 类)/`latex209_no_target`（映射目标工程 rglob+kpsewhich 双路不可解，kpsewhich 缺席 fail-open）。`_CLASS_MAP`：revtex→revtex4-2（选项 rename）、mn→mnras、jpsj→jpsj3、elsart→elsarticle、aipproc→aipproc、amsart→amsart；`_route_opts` 序：rename→`_INCOMPAT_PKGS` 剥→`_KERNEL_OPTS`/类内建→`_PKG_OPTS` 或 shipped `<opt>.sty`→usepackage，余归类 opts。输出=`_PRE_CLASS_SHIM`+`\documentclass`+COMPAT_SHIM(latexsym/vruleheight/nfss ifs/DeclareOldFontCommand/plain 字体族/theorem-body/plain-TeX 残渣/multicol)+`_REVTEX209_SHIM`+`_MULTICOLS_SHIM`+`\usepackage{pkg_opts}`；`_fix_math_209`：math/text 模态，`{<switch> X}` 组→`\mathit/\mathbf` 参数形；`_MATH_CITE_CS_209` 17 名 cite 族数学内裸调→`\mbox{}` 包（独立出口 `wrap_math_cites`，fixloop `cite_in_math_mbox` 消费）。调用点：`inject.inject_cjk`（自动升级）+ fixloop precheck `latex209_upgrade`（order -0.5）；`latex209_reject` gate（order 1）兜底拒不可转形态[^fixloop-rules]。

## 5. 支撑件

| 件                     | 职责                                                                                                                                                                                                                                                                                                                                                          |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `toolchain.py`         | tectonic 便携引擎分发：`TECTONIC_VERSION=0.17.0`、五平台 sha256 钉死 `ASSETS`、`install_tectonic`（sha256 校验 + 原子换名）/`ensure_tectonic`/`resolve_tool`；`TEXLATE_NO_DOWNLOAD`>CI 默认关[^tectonic]                                                                                                                                                      |
| `ctan.py`              | `ctan_fetch` 原语全模块：`TlpdbIndex`（texlive.tlpdb 解析→filemap.json 缓存，`TEXLATE_CACHE`>数据目录下 cache）、`fetch_package`（INDEX/OVERLAY_EXTS，flat 平铺\|tree 前缀剥，成员名穿越拒收 + 撤回，`FetchCaps` 五上限）、`check_version_compat`（`_NEEDFMT`/`_PKGLATER` 双 date 族 vs epoch）、`CtanFetcher`（tectonic 注入适配，索引首访惰建）[^ctanprobe] |
| `sandbox.py`/`proc.py` | §2                                                                                                                                                                                                                                                                                                                                                            |
| `mask.py`              | `TEX_SOURCE_SUFFIXES` + `visible_tex`/`without_comments`/`group_end`/`apply_edits`——normalize/inject 所有正则定位共用遮蔽契约                                                                                                                                                                                                                                 |
| `shadow.py`            | `_shadow_broken_system_packages`（§3.4 translate.md 同族——xelatex/lualatex 坏字节系统包遮影）                                                                                                                                                                                                                                                                 |
| `transcode.py`         | 支持件字节卫生（§3.4 translate.md 同族——aux/bib/intermediate/ps 转码 + `(atend)` bbox 回溯 ledgers）                                                                                                                                                                                                                                                          |
| `patchseams.py`        | compile 层 monkeypatch 面收口（`_SOURCES` 惰性 `__getattr__`；worker 层同名收口 `server/worker/seams.py`，注入缝几何件 `_docseams.py` 名近义异勿混）                                                                                                                                                                                                          |
| `_docseams.py`         | docclass/bd 注入缝原语（inject C4 拆出，原 `_seams.py` 改名防与上件撞名）：`find_docclass_ends`/`_splice_after_seams`/`_splice_before_document`——inject/layout/normalize/fixloop builtins 单向取用，仅依赖 textutil/mask                                                                                                                                      |
| `_yamlish.py`          | `load_yaml`（目录分片合并装载薄封装）+ `loads` + `YamlishError`——PyYAML `safe_load` 正式依赖化后，自定义子集解析器已退役                                                                                                                                                                                                                                      |
| `__init__.py`          | 惰性 facade（PEP 562 `__getattr__` 平名映射回子模块，不 eager 拉全链）                                                                                                                                                                                                                                                                                        |

## 6. fixloop（`compile/fixloop/`）

yaml 规则驱动的编译自动修复循环：log→taxonomy 分类→规则匹配→动作应用→重编，逐轮收敛[^fixloop-rules]。

### 6.1 架构三件套与共享地基

- `engine.py`：主循环 + `LoopCtx`（io/deps/round/ledger 四组 dataclass + `_CTX_FIELD_GROUP` facade）+ `_wire_engine`（filemap overrides 实例遮蔽 `eng.filemap`；texmfhome 缺省 → `wdir/_texmf` 隔离；tectonic 注入 `CtanFetcher`）。
- `actions.py`：`when`/`condition` 评估 + 7 种 action 分派。
- `ruleset.py`：`Ruleset.load(tolerant=True)`——`rules/` 目录按文件名序逐件 safe_load、顶层段合并（list 段按文件序 extend、map 段递归、标量异值即 `YamlishError` 冲突）；rule 级问题弃条记 `skipped_rules`、file 级 raise；`_RULESET_CACHE` 按分片 `(name,mtime_ns,size)` 指纹缓存、返回 deepcopy。
- **共享地基**：`compile/logparse.py`/`compile/ctan.py`/`compile/_yamlish.py` 是 compile 层共享件（log 解析/taxonomy、CTAN 拉包、yaml 装载——C3/F2 归位自 fixloop，fixloop 向下消费）；`fixloop/__init__.py` 是 PEP 562 惰性门面（17 平名映射回两叶 cases/engine）。

### 6.2 规则 schema

必填 `id`/`phase`/`when`/`action`；可选 `order`（float，缺省 0）、`condition`、`engines`（per-engine `{mode,degrade,fallback,via,note}`）、`mechanisms`（`[BTW]\d+`）、`description`、`risk`、`known_gap`、`provenance`（`[{corpus,error}]` 表——人肉修复库的开源等价物，必填可回溯失败现场）、`stats`（`fires`/`rescued_cells`/`status`/`note`/`status_suggested`）、`source_ref`。

- `phase ∈ {gate, precheck, loop}`：gate=每轮分类后最先评估；precheck=编译前一次性；loop=每轮错误驱动。同 phase 按 order 升序。
- `when` 键：`always`/`any[]`/`category`(str)/`payload_required`/`main_head_contains`。
- `condition` 15 键白名单：`any, tool_available, cap_available, engine_in, main_head_contains, source_contains, ctx_suggests, fileset{has_ext,lacks_ext,sibling_exts}, cache_dir_glob, vendored_shadow, package_version_ge, prim_read_form, payload_pattern, err_outside_fileset, shim_known`——未知键 fail-closed，装载期拦 typo。
- `action` 键：`kind`/`function`/`params`；`{payload}`/`{main_dir}` 占位由 `_substitute` 递归展开。
- taxonomy 行：`id`/`scope`(head|tail|warnings)/`pattern`/`payload_group`/`guard`/`preempts[]`/`use_pre`/`use_post`/`subclassify`/`payload_scan`/`warn_id`。
- warnings 行：`{id, pattern}` 两键。

### 6.3 `rules/` 分片图谱（17 分片，文件名序合并）

| 分片             | 内容                                                                                                       | rules | phase                |
| ---------------- | ---------------------------------------------------------------------------------------------------------- | ----- | -------------------- |
| `00-base`        | version/meta/capabilities/filemap（非列表段）                                                              | 0     | —                    |
| `10-taxonomy`    | taxonomy 全段：118 行 / 89 unique id（head 108 / tail 6 / warnings 4）；首命中序即语义                     | 0     | —                    |
| `20-warnings`    | warnings 段 6 条：invalid_utf8/missing_char/missing_graphic/tectonic_degrade/overfull_hbox/float_too_large | 0     | —                    |
| `30-route`       | gate 拒路 + precheck 预检                                                                                  | 10    | gate 3 / precheck 7  |
| `40-install`     | missing_file/tfm → install/fetch + babel 选项                                                              | 31    | loop                 |
| `45-graphics`    | ps_image/missing_graphic eps 链 + input_sty_to_usepackage                                                  | 16    | loop 15 / precheck 1 |
| `50-font`        | fontspec/missing_pfb 字体族                                                                                | 10    | loop                 |
| `55-prim`        | pdftex_prim/expl3 后端/glyphtounicode                                                                      | 7     | loop                 |
| `60-misschar`    | warn_missing_char/warn_utf8 缺字族                                                                         | 11    | loop                 |
| `65-encoding`    | inputenc/非 UTF-8/aux 腐蚀                                                                                 | 9     | loop                 |
| `70-pkgopt`      | option_clash/pkg_order/minted/hyperref                                                                     | 21    | loop                 |
| `75-syntax`      | syntax/already_def/散件 + `undefined_cs_guess` 兜底                                                        | 50    | loop                 |
| `80-bib`         | bbl stub/regen/citekey/bbx/biber-biblatex skew                                                             | 9     | loop                 |
| `85-shim`        | vendored 隔离/bundle 遮蔽/polyfill                                                                         | 13    | loop 11 / precheck 2 |
| `90-shim-legacy` | `legacy_pkg_shim` shim_map 大表 + input_sty_209_requirepkg                                                 | 4     | loop 3 / precheck 1  |
| `95-targeted`    | `cs_targeted_fix` 定点表独占片                                                                             | 20    | loop                 |
| `97-layout`      | 版面缺陷（qc_wanted 补票格驱动）：warn_overfull→`para_loosen`、warn_float_big→`float_h_demote`             | 2     | loop                 |

合计 **213 条规则**（gate 3 / precheck 11 / loop 199）；action 分布 builtin_transform 101 / regex_rewrite 86 / run_tool 13 / install_file 7 / reject_route 4 / scan_install 1 / escalate_llm 1。`00-base` 的 `meta.loop` 全键：`max_rounds=8, one_rule_per_round, dedup_key, stuck_sig_repeat=3, clean_err_max=3, compile_passes=2, timeout_sec=120, warn_demote=false, warn_driven_fixes=true`；`filemap.overrides`=105 钉（babel .ldf 大表 + 噪声 null 项）；`version_guard` epoch 2022-07-14；`capabilities` 段为审计文档不参与 dispatch。

### 6.4 主循环（`engine.fixloop`）

```
precheck 一次性（_precheck_phase，无编译，REJECT → reject:<rid>+reject_route）
for rnd in 1..max_rounds(8):
    res = eng.compile(...)                       # 单次预算 timeout_sec=120
    cat, pay = _round_cat(classify(parse_log))   # +timeout/runaway/killed/driver_fatal 附加类
    v = _gate_eval(gate 相逐条)                  # REJECT 即终止
    if v: return v
    sig = "{cat}:{pay}"；连 ≥stuck_sig_repeat(3) 且本轮派发零 apply → stuck
    r = _match_apply(loop 相 order 升序，首条 when+cond+mode 过且 apply 成功)
    if r is None: → unfixable:{cat}（无 pdf）| dirty_pdf（有 pdf）
```

- **每轮只应用一条**（`one_rule_per_round`，便于归因）；dedup 键 `{rule_id}:{payload}` 入 `ctx.ledger.applied`；misschar 族 `_mc_delta` 增量豁免（残存码位账外可再火）。`_landing_sync` 检测窗内外部落件（绕 `ctx.write` 的 install/run_tool/vendor 写）→ 失效缓存 + 落件前烧键过期（新站点引进后同签可重派）。
- **stuck 结算**：同签 streak≥3 **且本轮主 + 次级派发均无 apply** 才判——产出轮只续窗口不判负。
- **次级派发（twinhead）**：首错 miss 时 `err_candidates`（≤4）补派；xelatex halt_on_error 单错 log 且未出 pdf 且探针 <2 → best_effort 探针编译取全错误面，探针结果留 salvage 复用。
- **warn-preempt**（warn-driven fixes）：编译过但带红线 warning 也进修复轮——两 site：error-cat 轮派发耗尽点 + loop 退出点；`_warn_family_due` 勤勉判（族臂未评估过本 cat ∧ 残存码位在 mc_seen 账外）→ `only=_is_misschar_rule` 专场派发。
- **salvage**：verdict 非 reject 且末轮无 pdf 且无 driver_fatal → nonstopmode 兜底编译（exclusion 表：clean/acceptable_pdf/dirty_pdf/unfixable:{timeout,runaway_output,driver_fatal,input_stack}）→ 出 pdf 即 `best_effort_pdf`。
- **floor_snap**：precheck 前快照入口现存 pdf → `.fixloop-entry.pdf`；末态无 pdf 且非 reject → 拷回，`floor_from`=兜前 verdict、`floor_restored`=True——修复轮产出比入场更差时回退。
- **aux sweep**：每轮首、salvage 前、finalize 三处 `_sweep_bad_aux`——删 `_AUX_WRITE_EXTS` 截断件（无尾换行或花括号不闭合）；`_VOLATILE_EXTS`(+log) 每轮 compile 后 `invalidate_suffixes`。
- **pass-1 判收敛**：rep 干净且 passes>1 且非 tectonic 且未死 → 同轮全遍终编（≤2 传 None 走引擎自适应 rerun-hint）。
- **超时**：无引擎 wall-clock——`meta.loop.timeout_sec=120` 是单次 `eng.compile` 预算（`compile_timeout` 参数可覆盖）；`run_tool` 默认 120s；regex 单次 `pat.sub` 20s（`_bounded_sub`）；llm 60s+10s grace。取消经 `should_cancel`→`CancelledError`。
- **escalate_llm 位置**：`undefined_cs_guess` order=900 恒 loop 末位（唯一 escalate_llm kind 规则）；另有 `engines.*.mode:unsupported + fallback:escalate_llm` 两规则——`_match_apply` 不就地点火，记 `pending_esc` 待同 cat 廉价规则耗尽后才调 hook。
- `precheck_pass()`：precheck 相独立入口——e2e/worker 在 L2 resplice 前调用。

**verdict 全集**：`clean`（pdf ∧ n_bang==0 ∧ cat∉warn_cats ∧ ¬_res_died——被杀/超时/驱动 fatal 产 pdf 不证 clean）/ `acceptable_pdf`（dirty_pdf 且末轮非 died 且 final_errors≤`clean_err_max`(3) 升级）/ `dirty_pdf` / `best_effort_pdf` / `unfixable:<cat>` / `stuck` / `max_rounds` / `reject:<rid>` / `no_errors_no_pdf` / `no_main_tex[:<sub>]`。

顺序不变量：gate 先于一切（`pstricks_dvips_preflight` 0 / `latex209_reject` 1 / `plain_format_route` 2；`missing_file`+`\documentstyle` 必须先拦否则给 2.09 白装包）；装件臂居 loop order 低位（biber_biblatex_skew_route 8.0 → install_file 10 → … → 900 兜底），前有 relocate/shadow/stub 臂；同 trigger 保守→激进 + `(rule_id,payload)` dedup；rewrite 幂等逐条审过。

### 6.5 action 原语（`actions._apply` 分派）

| kind                | 语义                                                                                                                                                                                             |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `scan_install`      | 静态扫 `\usepackage/\RequirePackage/\documentclass/\input` → probe → `eng.install_file` 批量装；`vendored:true` 时 install 败件走 `_scan_vendored` repo 兜底落盘 + `_dep_fanout` 深度 2 依赖闭包 |
| `install_file`      | file/try_exts/font_related/file_aliases/already_present_ok；`.fd` 大小写双变体；先 `_requester_paths` 要求方 fanout；probe(cwd=wdir)→install→复核→`rebuild_fontmaps`                             |
| `run_tool`          | `argv` 直跑（`ctx.runner` 注入点）；实证多为 `tool_available:python3` 门控的内嵌 `python3 -c` 脚本                                                                                               |
| `regex_rewrite`     | `rewrites[]{pattern, repl\|function, flags, match_surface:masked}`+ exts +`engine_flags`（仅 n>0 时注 flag）                                                                                     |
| `builtin_transform` | `TRANSFORM_FNS[name](ctx, eng, pay, params)`                                                                                                                                                     |
| `reject_route`      | `REJECT: route=<r> <reason>`                                                                                                                                                                     |
| `escalate_llm`      | `ctx.llm_hook(ctx, rep)`，无 hook→False stub                                                                                                                                                     |

`cap_available`/`tool_available` 即引擎 caps 门——tlmgr/kpsewhich/updmap 依赖规则在 tectonic 侧自动降级或汇到 `ctan_fetch`/`vendored_fetch` 臂[^ctanprobe]。

### 6.6 builtins：facade + 22 叶

`builtins/__init__.py` 门面 = 全量 re-export + `REWRITE_FNS`（3：`px_to_bp`/`keep_latin_tokens`/`graphics_kv_strip_obsolete`）+ `TRANSFORM_FNS`（**83**）。yaml 引用：`action.function`→TRANSFORM_FNS 键、`rewrites[].function`→REWRITE_FNS 键、`@pdftex_prims`/`@pstricks` 占位符 yaml 全树展开（`_FAMILY_TOKENS` 双支：`@pdftex_prims` 112 词表 + `@pstricks` 4 签名支——后者单源 `engine/_route.PSTRICKS_SIG_ALTS`，route 静态签名与规则条件同口径）。社区新规则多数只写 regex，新函数才需 PR 代码。

| 叶 | 主题 | |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | |
| `builtins.common` | 跨域原语：mask_tex/live_matches/`_resolve_site`/`_inject_write` 指纹闸/`_safe_rel` payload 名卫/`_mc_*` 缺字读侧/`_MC_TABLE`/PDFTEX_PRIMS/`_drop_pkg_loads` | |
| `builtins.assetfix` | 随稿资产改形补缺（misc C3 再拆叶）：`pfa_to_pfb`（pdftex.map `.pfa`→usertree `.pfb`+map 同位遮蔽）/`eps_converted_alias`（`X-eps-converted-to.pdf`→`<stem>.pdf` 别名+eps 引用剥名） | |
| `builtins.bib` | bbl stub 改写/bbl_regen/`biber_biblatex_skew_route`/`cite_in_math_mbox`/`citekey_sanitize` | |
| `builtins.csbind` | 上古/产出 cs 守卫重绑（shim C3 再拆叶）：`font_cs_shim`（AMS 上古字体 cs→`\font` 绑 CM）/`cs_rebind`（TFM 缺字→回退字体）/`bm_mathchar_wrap`（`\bm` 撞 XeTeX 15-bit mathchar 墙） | |
| `builtins.csfix` | undefined_cs/already_def cs 名打靶（`cs_targeted_fix`/`ctlseq_undefine`/`undefine_for_redef` 等） | |
| `builtins.docfix` | 文档结构打靶：`pdfstring_cs_disarm`/`if_phantom_protect`/`premature_cs_guard`/`cs_delim_tail_fix`/`spacefactor_atdef_wrap`（at-def 包裹） | |
| `builtins.envpoly` | `undefined_env_polyfill`（shim C3 再拆叶）：`Environment X undefined` proven+ 批扩面 `\ifcsname` 守卫 noop（pkg_map 命中装真包/`\renewenvironment` 站点守卫/ companion 对偶） | |
| `builtins.filefix` | payload 文件归位/占位（shim C3 再拆叶）：`fileset_relocate`（+顶层目录整树镜像）/`driver_tfm_hoist`/`generated_stub`/`doc_absent_stub` | |
| `builtins.graphics` | pstricks/dvips 预检/eps→pdf/svg_prepare/pdf_asset_sanitize/xbb_pregen + 共享原语（`_iter_project_files`/`_try_gs_redistill` 等单源） | |
| `builtins.gfx_missing` | missing_graphic 缺图域（graphics C3 再拆叶）：`graphic_case_link`/`graphic_repair`/`includepdf_missing_stub`/`graphic_missing_placeholder`/`raster_pdf_rename`/`driver_missing_image_stub` | |
| `builtins.inputfix` | input 族引用图外科（misc C3 再拆叶）：`subfile_docclass_strip`/`main_wrapper_promote`/`graphics_include_strip` + `_input_targets`/`_closure_scan` 引用闭包原语 | |
| `builtins.layoutfix` | qc-wanted 版面/字符面：`tabular_fit`/`math_run_break`/`display_math_shrink`/`gfx_width_clamp`/`section_skip_floor`/`fffd_context_fix`/`legacy_clamp_purge` | |
| `builtins.misschar` | missing_char 族修复（missing_char_fix/accent_mark_fix/font_fallback/nfss_* 六件） | |
| `builtins.misc` | 编码转码/中间件清场/support 复原/格式门：`non_utf8_recode`/`cjk_env_relax`/`purge_corrupt_intermediates`/`aux_seed_undefined_refs`/`restore_support_from_src`/`plain_format_detect`/`latex209_upgrade`/`harvest_build_directives`/`docstrip_generate` | |
| `builtins.optfix` | env 选项组与排版参数外科（misc C3 再拆叶）：`tcolorbox_breakable_inject`/`float_h_demote`/`float_opt_cs_expand`/`para_loosen`（前二者是 runaway_output 修复臂） | |
| `builtins.paralong` | para_longize——非 long 宏撞 `\par` | |
| `builtins.pdfprim` | `pdftex_prim_polyfill`（shim C3 再拆叶）：xelatex 下 pdfTeX 原语按签名分臂（寄存器族/取参族/余项 chardef）`\ifdefined` 守卫注入 | |
| `builtins.pkgload` | 装载点外科：option_clash_merge/strip_inputenc/physics_stub_detach/font_sub_shim/xy_option_load 等 | |
| `builtins.shim` | shim_map stub/遮蔽注入：legacy_pkg_shim/svjour_clo_stub/journal_cs_polyfill/bundled_class_shadow/shim_pkgs_in_use/revtex209_surface_polyfill | |
| `builtins.slotrev` | slot_arg_revert——zh 机位实参 revert（segmenter 侧病灶） | |
| `builtins.tarblob` | `extract_tar_blobs`（misc C3 再拆叶）：tar 伪装件检测（ustar 窗 + 头校验）/regular-file 成员补缺/blob 改名 `*.tarblob` 退役 | |
| `builtins.vendored` | `find_vendored_shadows`（\ProvidesX 日期面 ld<sd 确证；tectonic 走 filemap 索引 advisory 级）/vendored_shadow_isolate/`vendored_fetch`(+multi)/amsmath_family_retire/revtex_era_retire | |

### 6.7 `vendor/` 离线资产三层

| 层       | 件数                                                                                                                      | 角色                                                                                            |
| -------- | ------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| `files/` | 183 件真档（.sty 80/.tex 47/.cls 13/.def 9/.rtx 8/.tfm 5/.mf 5/.ldf 2/.clo 2/.con 1 + 无扩展名 11 件 pst-*/multido/epsf） | 许可逐件核过的真身——missing_file 臂 off-CTAN 绝版件零网络平铺（`vendored_fetch`）               |
| `stubs/` | 26 件                                                                                                                     | 许可禁分发件的最小宏面 stub——签名按 corpus 真件参数形状逐条对齐（吞参形状错位即吃调用点 token） |
| `shims/` | 9 件 .cls 替身（aipproc/imsart/JHEP3/JHEP/mn2e/mn/revtex/svjour3/svjour）                                                 | 受限 cls 重写替身                                                                               |

`_vendored_source` basename 按 `files→stubs→shims` 序查件（basename 跨层唯一）；`_resolve_site` 保 payload 相对径落位；`_inject_write` 指纹闸（外来件永不覆写，旧代注入件可刷新）。`doc_absent_stub`：版本缀 sibling 搬真件否则空 stub；`fileset_relocate`：稿自带件归位 `<main_dir>/`；`find_vendored_shadows`：工程自带旧 .sty 遮蔽已装新版——按 `\ProvidesPackage` 日期面确证（ld<sd）才 rename 隔离，盲删必死（同目录 cls 可能是唯一来源）。

### 6.8 cases 沉淀（`cases.py`）

`CaseSink.record` → `cases.jsonl`：`{ts, corpus, cond, engine, main, verdict, final_pdf, final_errors, started_fail, rounds[{round,cat,pay,pdf,n_errors,warnings}], actions[{round,rule,result}], installed, rules_declined, gate_fired, decline_notes, advisories, log_excerpt}`；线程锁+flock 追加。triage verdict 前缀集：`unfixable:/stuck/dirty_pdf/max_rounds/no_errors_no_pdf`。

「新失败→新规则」回放三门（入库门槛）：① `replay_case` 本格重跑——新规则必须把 fail 修到 pdf；② `replay_all` 全语料回归——曾 clean 不得改脏（`floor_restored` 算退化）；③ `stats_backfill` 回填 fires/rescued_cells，`proposed`+有 fires+ 有 rescued→`status_suggested:"active"` 建议（不自动转正）。

`status` 实际值分布（213 条）：**active 118 / proposed 83 / validated 6 / verified 4 / proven 1 / stub 1**（无 retired/none）——`Rule.status` 只读 `stats.status` 缺省 active，engine/actions 零消费点：纯审计元数据不门控，全状态同序同权上场，排序/触发由 `order`+`when` 驱动。

### 6.9 llm_hook（`llm_hook.py`）

`escalate_llm` 唯一出口 `LlmFixer.__call__(ctx, rep)`：全空 rep 拒烧 → `_prompt` 装配（system 硬契约 + user = ERROR CATEGORY/PAYLOAD + log 摘要≤4KB + file_stack + 出错文件 `l.N`±25 行≤4KB + 已试动作史≤12 条）→ 网关并发闸（4）内专用线程 `asyncio.run`（60s+10s 宽限）→ `_parse_patches`（剥 fence/loads/首尾{}兜底，patches≤8）→ `_apply_patches` 四闸：**路径闸**（拒绝对/`..`，safe_resolve 限 wdir）+ **扩展名闸**（.tex/.sty/.cls）+ **banned 构造闸**（`\write18`/`\pdfsystem`/`\directlua`/`\input|管道`/装载宏内绝对 - 穿越径）+ `old` **精确一次**匹配 → `ctx.write`。note 以 `llm_hook[model](pay):` 打头。env 与网关同单源（`TEXLATE_BASE_URL`/`TEXLATE_API_KEY`/`TEXLATE_MODEL`/`TEXLATE_DIALECT`）。

双臂默认有意不同（登记裁决不修）：e2e/pipecore 是 `TEXLATE_FIXLOOP_LLM=1` opt-in（default=False）；server worker 默认开（`env_flag(default=True)`）但 BYOK 计费面门控——share-sourced 任务/`options.llm_hook=false`/env=0/无 api_key/`TEXLATE_TRANSLATOR=mock` 均置 None。

## 7. 状态词表（编译侧）

| 域           | 字段             | 取值                                                                                                                                                                    | 产出                                    |
| ------------ | ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------- |
| 编译判决     | `Verdict.status` | `clean` / `partial` / `fail`（无 reject——三处拒绝统一 partial + `reject_at`）                                                                                           | `compile/judge.py`                      |
| 注入态       | inject `status`  | `injected` / `already` / `no-docline`                                                                                                                                   | `compile/inject.py`                     |
| fixloop 判决 | cases `verdict`  | `clean` / `acceptable_pdf` / `best_effort_pdf` / `dirty_pdf` / `unfixable:<cat>` / `stuck` / `max_rounds` / `reject:<rid>` / `no_errors_no_pdf` / `no_main_tex[:<sub>]` | `fixloop/engine.py`、`fixloop/cases.py` |
| 规则态       | `stats.status`   | `active` / `proposed` / `validated` / `verified` / `proven` / `stub`（审计元数据非门控）                                                                                | `fixloop/rules/`                        |
| 跨臂退化     | `VERDICT_RANK`   | `clean:3 > partial:2 > fail:1 > reject:0`——终态不得低于上游                                                                                                             | `repair.py`                             |

### 参考文献

[^pstricks]: TeXlate 调研档案：pstricks/EPS 路由与 dvips 兜底链。[research/latex/pstricks-route.md](../research/latex/pstricks-route.md)

[^engine-matrix]: TeXlate 调研档案：tectonic/xelatex 引擎矩阵实测。[research/latex/engine-matrix.md](../research/latex/engine-matrix.md)

[^ctanprobe]: TeXlate 调研档案：ctan_fetch 原语与 tlpdb 离线索引实测。[research/latex/ctanfetch-probe.md](../research/latex/ctanfetch-probe.md)

[^fixloop-rules]: TeXlate 调研档案：fixloop 规则库设计与沉淀机制。[research/latex/fixloop-rules.md](../research/latex/fixloop-rules.md)

[^f3-note]: TeXlate ADR-0006：引擎路由裁决（2026-09-16 更新：策略拒绝归一 `partial`+`reject_at`）. [decisions/adr/0006-engine-routing.md](../decisions/adr/0006-engine-routing.md)

[^tectonic]: Tectonic Typesetting. Tectonic 编译引擎（五平台 sha256 钉死二进制分发）. [github.com/tectonic-typesetting/tectonic](https://github.com/tectonic-typesetting/tectonic)
