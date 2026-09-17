# logpipe-fuzz — 编译日志三层管线口径对抗测试

> 2026-09-17 收口。交付 `tests/test_fuzz_logpipe.py`（554 行，commit `8289521`）：**14 passed + 15 xfailed(strict, 0 xpass)**，ruff check/format 双净。真实语料面 = 13 fixture + 427 bench 抽样（共 440 log），三层 n_errors 零分歧——全部分叉均为对抗构造。

## 覆盖面

gate+nullfont 逐点划分（3k 随机交错含折行）、续行豁免、邻接不互污、90 字硬边界、l2 by_class 四类 census（2.5k 生成）、sys_hits 仅 invalid_utf8@、三层错误计数/首错/栈一致（真 log + 合成 + 注入变异）、l2 结构不变量（cap200/ctx≤8/tail30/序）、update_file_stack 裸括弧 oracle（含 misschar 字形括弧豁免）、judge 面（nullfont→clean+notes、warn:→reasons、sys_warn:→notes）。

## 缺陷台账（6 族，15 strict xfail 钉）

| # | 缺陷 | 位置 | 影响 | 修法 |
|---|------|------|------|------|
| 1 | `WARNING_RED_LINES[fffd_glyph]` 缺 nullfont 豁免 | engine.py:185 | `Missing character: There is no ("FFFD) in font nullfont!` → warnings_hit=['fffd_glyph'] → judge partial，而 missing_chars 闸+l2 missing_glyph_nullfont 同案判良性——**nullfont 裁决层内自相矛盾** | fffd_glyph 前置同款 tempered lookahead |
| 2 | 90 字 tempered 窗可越过非 misschar 行 | judge.py:96（engine missing_chars / rules.yaml missing_char 同纹） | 真字体 misschar 后 ≤90 字内任何 `in font nullfont` 字样即误豁免真缺字（实测 gate=0）；真实可达性≈0（该字样仅 misschar 消息产生），latent | 窗至多跨一个换行且续行内限长 |
| 3 | `_FILE_LINE_RX` vs `_ERR_FILELINE_RE` 三层口径分叉 | l2.py:48 vs engine.py:168（fixloop 借用） | 9 条 repro 全钉：l2 独收 `./f.tex:5:`/`f.tex:5:!x`/tab 系；engine+fx 独收 `Makefile:5:`/`C:\x.tex:5:`/`(x.tex:5:` 系；l2 `_NONERR_FILELINE_RX` Warning 排除未锚定致 `./f.tex:5: See LaTeX Warning:`/`! LaTeX Warning`/`! ==>` 漏真错（1/0/1） | 双正则取严侧并单源化 |
| 4 | misschar 三闸认裸 `Missing character`（无冒号） | judge/engine/yaml 三处 | `Missing characters ...` 行文误计缺字；l2 census 要冒号才是真形态。0 真实命中，latent | 三处 pattern 加 `:` |
| 5 | invalid_utf8 大小写/措辞口径分叉 | l2 IGNORECASE+`replaced by U+FFFD` 变体 vs engine `_UTF8_WARN_RE` 仅大写 | `invalid utf-8 byte C3`/`Char replaced by U+FFFD` 两形 l2 红线 engine 零命中；真实行两短语同现故 latent | 两端 pattern 对齐 |
| 6 | `file_stack_at` 无 graphic 补丁 | texlog.py:143（fixloop 栈重放） | `(fig,1.eps` 形状拒收帧在 engine(`_last_open_graphic_token`)/l2(`_patch_graphic_top`) 补真名、fixloop 丢帧：eng/l2=['./main.tex','fig,1.eps'] vs fx=['./main.tex'] | texlog 栈重放补同款 graphic 补丁 |

## ps_image 裁决：原假设证伪

xdvipdfmx TL2026 + tectonic 0.15.0 二进串实证 `for "%s"` 引号已入格式串——`for "my file.eps"` 正常命中 `('ps_image','my file.eps')`，裸名形态不发出。探到两个真实邻接缺口（未钉，供裁决）：(a) `caused by:` 行被 xdvipdfmx `====` dump 块推出 ctx8 窗口 → 'other'；(b) `Image inclusion failed. Could not find file: %s` 无引号变体逃逸全部签名 → 'other'。

## 未钉观察项

- engine.error_line write-only 字段与 l2.tex_line 口径不一。
- wrapped-nullfont 实际不可达（`in font` 恒在 79 列内，mid-word 折行 nullfont 才漏）。

探针脚本在 `tmp/logpipe-fuzz/`。
