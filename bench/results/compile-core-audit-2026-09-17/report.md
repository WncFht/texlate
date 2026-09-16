# compile-core-audit — compile 核心（engine/sandbox/inject）+ l2 交付

> 2026-09-17 收口。落地分三笔：`2ed90e9`（l2.py `_MISSING_CHAR_RX` 双格式 + `fffd_glyph` 类 + `_classify_warning` 分支——随 validate-audit 交错先落）、`24007d1`（peer 会话 commit 扫入 engine.py + test_compile_engine_judge.py 全部在飞 hunks + dos_eps 消费侧——双归因）、`054cafc`（inject.py + sandbox.py + 两测试文件）。自验 `-k "compile or inject or sandbox or l2"` 353+ 绿、ruff 双净。探针 tmp/compile-core-audit/engine_probes.py 5/5。

## 修复清单（16 项）

### l2.py（已随 2ed90e9 落地）

1. `_FILE_LINE_RX` 扩展名字符集 `[A-Za-z0-9]`→`[A-Za-z0-9_-]`（.pdf_t 的 _）；`_match_error_line` 删 `looks_like_tex_file` 白名单门——loop1 语料 7814 log 全扫实证：白名单漏 586 行真错/13 log（.eps/.pdf_t/.fgx/.lbx/.tikz/.end/.lof/.abs），3 例整体翻转 ok=True 假干净。
2. `_MISSING_CHAR_RX` 双格式 `("8FD9)`/`(U+8FD9)`——老/新 TL 码点形态并存，单认引号形漏新工具链约 1/3 CJK 缺字红线。
3. 新增 `fffd_glyph` 红线类（cp==0xFFFD 分流，engine WARNING_RED_LINES 同名对齐），missing_glyph_cjk 保留。

### engine.py（已随 peer 24007d1 落地，含 peer 补强的 graphic-token 栈回填）

4. `res.ok` → `not res.timed_out and res.rc is not None and res.rc >= 0`——exec 失败（rc=None）与末 pass 信号杀不再报 ok=True。
5. `_split_flags` 裸 rekey flag 吃下一个非 `-` token 进 dropped——两 token `-output-directory /x` 的值此前漏进 argv 被 xelatex 当第二输入文件。
6. `_map_flags` 改 3 元组 `(toks, dropped, applied)`；`flags_applied` 取源 token 记账——dropped 合体串 `-Z shell-escape` 按 flist 差集会把两 token 误记已放行。
7. `_fetch_into_usertree` 加 `dest: Path` 参——texmfhome=None + ambient TEXMFHOME 场景 `Path(None)` TypeError 崩。
8. install_file init-usertree 结果入 `rc_i/to_i`，`_usertree_inited` 仅成功时钉——失败不再假装就绪。
9. route_project `p.read_bytes()` 包 try/except OSError→continue——竞态删除/权限位不炸整格。
10. log 读取四处补 `encoding="utf-8"`+OSError 容错；两个 `parse_log(res)` 统一 `text or res.stdout_tail`（存在但空的 .log 退 stdout_tail，旧码直返 0 错）；tectonic 版补 `error:` 扫描兜底。
11. fffd_glyph `U\+FFFD`→`\((?:"|U\+)FFFD\)`——`("FFFD)` 老 TL 形也命中。
12. `_apply_sandbox` 向 `sandbox_wrap` 转发 `allow_net`——此前 xelatex allow_net=False 在 darwin 被吞。

### dos_eps 消费侧（24007d1 内，peer 机制 + 本审计探针/测试）

13. `_DOS_EPS_MAGIC`/`_is_dos_eps`/`_scan_error_lines` 降级——normalize `dos_eps_skipped` 台账件（DOS 魔数二进制 EPS，字节原样保留）的 invalid_utf8 残余降 `warnings_sys` 标 `(dos-eps)`。**关键依赖**：`update_file_stack` 对 `(./fig.eps` 入 None 配对帧（TEX_FILE_EXTS 无 graphic 扩展名），peer 的修法是 `_last_open_graphic_token` 把行尾未配对 graphic token 补回栈顶——engine 局部解决，texlog 谓词面未动（l2 同款在飞补丁见下）。

### inject.py / sandbox.py（054cafc）

14. inject `find_main_tex` bodies 切分改 `_BEGIN_DOC_RE.split(maxsplit=1)`——`\begin {document}`（空白合法）与检测正则同口径，前导区不再虚抬 body 量挤掉真 main。
15. inject `prepare_chinese` TABLE_FITTING 判据移出 `status=="injected"` 分支——已带 CJK 的工程同样补 threeparttable 溢宽钩子；`new_text != text` 写闸门保幂等。
16. sandbox `sandbox_wrap(allow_net=)` False 追加 `(deny network*)`（与 bwrap `--unshare-net` 对齐）；`run_process` 超时后二次 `communicate(timeout=30)` 有界回收（逃逸孙进程握 stdout 写端不再无限等）+ `except BaseException`→kill_tree+raise（KeyboardInterrupt 不孤儿化进程树）。

## 新测试（+16 跨三笔）

l2 ×2（FFFD 引号形、非 tex 扩展名 file:line 计数）；engine_judge ×9+改 2（fffd 引号形红线、exec 失败/信号杀 ok=False、parse_log(res) 空 log 退 stdout_tail + tectonic error: 扫描、route 不可读跳过、init-usertree 失败不钉、ambient TEXMFHOME fetch dest、`-Z` 两 token 不漏记 applied、split_flags 两 token、map_flags 3 元组）+ dos_eps 降级 1；sandbox ×3（darwin deny network 开关、KeyboardInterrupt 杀整组、二次回收有界）；inject ×2（spaced begin-document、already-CJK 补 TABLE_FITTING 幂等）。

## 未修（理由）

- texlog 栈消费纪律审讫：update_file_stack 无状态逐行推/弹、解析循环无异常逃逸路径——无泄漏。
- `% texlate` marker 覆盖审讫：全部注入块带 marker，fixloop restore 的 deliberate-write 判定有靠。
- killed_signal last-wins/docstring 有意语义；LogInfo.errors 无界=契约；child_env extra 覆盖=调用方契约；代理 env 剥离=防凭据透传；ambient TEXMFOUTPUT=kpathsea 配置面。
- engine error_ctx(+8) vs l2 ctx(8 行后) 口径微差：消费方不同各自文档化。

## 外部路由

- e2e.py:398 `_l2_parse` 同「空 .log 直返 0 错不退 stdout_tail」口径差——与 engine.parse_log(res) 已修项同源 → 1d。
- texlog `looks_like_tex_file` 白名单使非 tex 帧落 None → share-texlog-audit（在飞，已收编为 scope 追加：谓词放宽评估 + l2/graphic 帧归因）。
- xelatex 每 pass `max(10,timeout/passes)` 拆分语义（单 pass 稀释 vs 全程预算）——产品裁决项，backlog。

## 归因注记

- l2.py 在飞 hunks 分两次落：`_REDLINE_CLASSES`+missing_glyph 与 compile-core 的 `_MISSING_CHAR_RX`/`fffd_glyph`/`_classify_warning` 随 2ed90e9 双归因落地；`_FILE_LINE_RX`/`_match_error_line` 同在该提交（当时已在树内）。
- engine.py + test_compile_engine_judge.py 的在飞 hunks 被 peer 会话 `24007d1`（05:03）pathspec commit 扫入——内容与报告逐条吻合 + peer 补 `_last_open_graphic_token` 栈回填使 dos_eps 消费侧真生效（我侧复跑 dos_eps 测试绿）。
- l2.py 残存 +39 dos_eps 移植补丁（`_is_dos_eps`/`_last_open_graphic_token`/`_mark_redline` 降级段）在 tree 中，作者核实中——疑为 peer 对 l2 侧的同机制移植或本审计追加，无配套测试暂不提交。
