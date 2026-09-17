# l2fixtures-impl — L2 真 compile-log fixtures 抽取落地交付

> 2026-09-17 收口。按 scout-l2fixtures spec 全量落地：13 件入库（含 2 件可选件），extractor 全件 `--verify` 通过，`pytest tests/test_l2_real_fixtures.py` 18 绿，ruff 净。

## 产物

- `bench/py/extract_l2_fixture.py`（可执行；strip→裁切→写件→manifest 行→verify 全链）
- `tests/fixtures/logs/`：13×.log + manifest.json（JSON 数组，13 行），共 ~114KB
- `tests/test_l2_real_fixtures.py`：manifest-parametrize（逐声明字段断言 L2 verdict + fixloop n_bang/category/payload）+ 5 dedicated（eof_file runaway / ==> 剔除 / fileline-only 零 bang / tectonic engine=None / 私路径硬门槛）
- `.gitignore` +`!tests/fixtures/logs/*.log`（现 `!tests/fixtures/*.log` 只盖直系子级）

## 入库件 verdict 一览

- xelatex-missing-cls-min.log 966B 原样：n=2 missing_file:revtex4-1.cls
- pdftex-emergency-fatal.log 684B 原样：n=2 双 bang（! Emergency stop + ! ==> Fatal error）emergency
- pdftex-fileline-only-bib.log 1.3KB 原样：全文零 ^!、n=2 纯 fileline、尾行 ==> 复述不计错，syntax
- tectonic-bare-stack.log 2.9KB 原样：engine=None、missing_glyph £("A3) 红线、warn_missing_char
- tectonic-citation-warn.log 6.1KB 原样：engine=None、citation=5/reference=1、clean
- xelatex-utf8-redline-project.log 1.5KB strip：invalid_utf8 工程件真红线（lineno.sty→./lineno.sty）missing_file:revtex4.cls
- xelatex-inputenc-fffd.log 9.0KB strip：n=1 inputenc.sty:164 fileline + invalid_utf8×6/fffd_glyph×6 红线、inputenc_unicode
- xelatex-multierror-stack.log 1.9KB strip：n=4、missing_file:JINST.cls、missing_glyph×2
- pdftex-fatal-summary.log 1.3KB 原样：./colt2020.cls:5: ==> fileline 复述剔除实证、emergency
- xelatex-cjk-missing-glyph.log 27→19.7KB strip+裁：missing_glyph_cjk=1（U+8FD9 新形）、warn_missing_char
- xelatex-runaway-eof.log 26→19.6KB strip+裁：n=2、eof_file=./plb-rev.tex、runaway_scan:\@iiiparbox
- xelatex-fileline-nontex-ext.log 134→31.5KB strip+first-error-only：standard.bbx:10 非白名单扩展名真错、undefined_cs:DeclareBiblatexOption
- xelatex-clean-warnings.log 26→17.8KB strip+裁：n=0 overfull=23/font_subst=6、clean

## extractor 用法

`uv run python bench/py/extract_l2_fixture.py SRC --name NAME [--strip-prefix PFX[=REPL]]... [--no-cut|--first-error-only] [--verify] [--manifest PATH] [--no-manifest] [--notes TEXT] [--project-root-for-attribution DIR]` —— manifest 默认 upsert 到 tests/fixtures/logs/manifest.json（按 file 去重排序）。

## 与 spec 的差异点（均按代码真相落地）

1. **spec 的 `tectonic-fatal-summary` 源指错**：`work_compile_v2/2002.05660/baseline/_tect_out/main.log` 全文无 `==>`（已 grep 实证）。真 ==> 载体是 `bench/corpus_v2/2002.05660/extracted/colt2020.log`（1.3KB pdfTeX 原样件）→ 入库名 `pdftex-fatal-summary.log`。
2. **命名修正**：`xelatex-fileline-only-bib` 源实为 pdfTeX/TL2019 → `pdftex-fileline-only-bib.log`。
3. manifest schema：JSON 数组承载（.json 后缀名义）；`fixloop` 段加 `n_bang`（对齐 spikereplay 三元组）；加 `project_root` 字段（null 未用，测试按 repo 相对解析）；`head_contains` 存完整 head（最强子串）。
4. `xelatex-inputenc-fffd`：spec 预期的 texmf sys 归因上下文实为单位——invalid_utf8/fffd_glyph 实际落 **redlines**（warning 时刻栈顶是 ./main.tex 工程件）；texmf abs 路径只见于 first_error stack_suffix。manifest 按实算记录。
5. 裁切 keep 集比 spec 字面略宽：额外保全部 warning 形态行 + 裸 `==>` 行——by_class 计数与源件精确一致（普通裁切模式 verify 断言 warnings.* 全等）。
6. `--first-error-only` 模式自加 horizon 规则：首错 ctx 后至 tail 前整段可裁（含括弧行）——首错栈重放只依赖其前历史；verify 相应豁免 n_errors/errors/warnings，stack/last_pop 仍逐保留错误精确对拍。

## 留给 leader 的决策（scope 外未动）

- test_validate_l2.py 的 5 个 NEED_LOGS gated 块收编退役；spikereplay `_FIXTURE_CATS` 可改读 manifest。
- 现有 `tests/fixtures/xelatex-*.log` 两件未迁动（在飞引用保护）。
- 池内拿不到 `file:line:` 前缀 Warning 行真例（7139 全扫 0 例）与 >200 错上限真例——保持合成，与 spec §4 一致。
