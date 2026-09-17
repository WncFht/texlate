# scout-l2fixtures — L2 真 log fixtures 可行性 + 实现 spec（只读）

> 2026-09-17 收口。**结论：完全可行且廉价。** 本机 .log 池 7139 个（全在 gitignored `bench/work_*/` + `bench/results/stagerun-loop1-2026-09-16/work/`，后者 5086 个/224MB），所有 L2 关心的真实失败形态都有 ≤30KB 可裁切实例，其中 6 个 ≤7.5KB 可近乎原样入库。脱敏 = 机械前缀替换（6233 个含 `/home/` 路径）。探针现场 `tmp/scout-l2fixtures/scan.py`（gitignored，全量普查可重跑）。

## 1. 需求枚举（L2 消费面 × 覆盖现状）

L2 消费面（`src/texlate/validate/l2.py`）：engine 首行签名、双格式错误计数（`^!` + `file:line:`）、first_error ctx/`l.N`/`file_stack`、`eof_file`（runaway 归因）、9 类 warning、红线归因（project vs sys_hits/dos-eps）、tail 30、`log_missing`、存储上限。

| 形态 | 合成覆盖 | 现有真 log | 真 log 增量 |
|---|---|---|---|
| `^!` 错误计数/file_stack/l.N | 有 | gated err21（53KB/21错，skipif） | 中——小体积替代已在池内 |
| `file:line:` 格式 | 合成 2 例 | fixture×1（fileline-syntax） | 低 |
| **fileline-only（零 `!` 全 fileline）** | 无 | 无 | **高——1526 个真例，假干净杀手锏形态** |
| **`==>` fatal 复述剔除** | 无 | 无 | **高——colt2020 `==> Fatal error` fileline 行真例在池** |
| **`eof_file` runaway 归因** | **L2 层零覆盖**（仅 texlog 原语 + logparse 层测） | 无 | **高——53 个真例，plb-rev 弹出距 3<16 窗口实证** |
| **tectonic 形态**（engine=None/裸名栈/`(main.tex`） | 无 | gated _WARN_LOG 21KB | **高——753 个真例，裸名栈驱动 `is_project_file` 分支** |
| missing_glyph_cjk（U+ 形） | 合成 | gated 70KB | 中——27KB 可裁真例 |
| invalid_utf8 工程件红线 | 合成（tmp_path 构造栈） | gated 876KB 巨兽 | **高——wprime_cdf 1.7KB 工程内 lineno.sty 真例** |
| invalid_utf8 texmf→sys_hits | 合成 | — | 中——1012.1124 9.3KB texmf 栈真例 |
| `file:line:` 非 tex 扩展名 | 合成 1 例（.pdf_t） | 无 | 低——真例在池（.bbx/.lbx/.bib）但 134KB 需裁；.bib 已在白名单 |
| Warning 行带 fileline 前缀剔除 | 合成（logparse 侧） | **池内 0 例——本机拿不到真例** | 无（保持合成） |
| 79 列 mid-token 折行→None 帧 | fuzz 隐含 | 无 | 低——118 例在池，texlog 层已强测，可选 |
| 缺字括弧字形 `no ) in font` | 合成全型 | 无 | 低——6 例真例在池，可选 |
| `! ==> Fatal error`（老 pdfTeX 尾行） | 无 | 无 | 中——texput.log 684B 原样可用，兼送 engine=pdfTeX 多样性 |
| `>200` errors 存储上限 | 无 | 1528 错真例但 876KB | 无——纯计数性质，合成即可 |
| clean log + warning 分类 | 合成 | gated 26KB | 低——裁切版替代 |

出处对齐：本项即 audit wave2-findings #7「L2 真 log/spikereplay 干净 clone 永跳」（`docs/research/audit-2026-09-16/`），tests.md L52「真实 log 半全灭于陈旧路径」。已落 2 fixture 后本 spec 是把剩余 5 个 gated + 新发现形态一并收编。

## 2. 素材可行性（实测）

- **池**：7139 log。has_bang 1051、file:line 1775、fileline-only 1526、clean 5120、tectonic 753、eof-runaway 53、missing_char 563（U+ 160/引号 121）、fffd 316、missing_file 942、citation 461、ref 1017、rerun 3009、overfull 4084。
- **体积**：p50 8–34KB；extractable 目标 ≤20KB/件，6 件 ≤7.5KB 原样可用。
- **隐私/路径**：6233 含 `/home/` 或 `/Users/`——全部是工作目录绝对路径（`**` 行、`(…` 栈项、file:line 错误头），无凭证类内容。脱敏 = 单一 `--strip-prefix` 把 run-root 前缀换 `./`；`/usr/share/texmf-dist/…` 等系统路径**保留不动**——公开路径且是 `sys_hits` 归因的承重输入（`_SYS_TREE_RX` 认 `texmf` 段）；Tectonic 缓存路径若有则改写 `/Tectonic/` 保 `_SYS_TREE_RX` 大写段。抽取器硬门槛：产物含 `/home/|/Users/` 即 fail。
- **裁切正确性**：elide 只允许删**无括弧行**（字体/宏转储大头），保 engine 头 + `**` 行 + 全部含 `(`/`)` 行 + 错误行±8 ctx + tail 30。验证器重放 kept 行集，断言 per-error named-stack 与 last-pop 与源一致（runaway 的 eof_file 依赖 popped 史，`)` 行不可删是硬约束）。marker 用现有惯例 `[... elided N lines ...]`（纯文本无括弧）。

## 3. 实现 spec

### 布局

- `tests/fixtures/logs/` 新子目录（现有 2 件 `tests/fixtures/xelatex-*.log` 建议迁入保持一致）；`.gitignore` 加一行 `!tests/fixtures/logs/*.log`（现 `!tests/fixtures/*.log` 只盖直系子级）。
- `tests/fixtures/logs/manifest.json`——每 fixture 一行期望 verdict，非 .log 不受 ignore 影响。
- 抽取器 `bench/py/extract_l2_fixture.py`（bench 侧惯例：消费 gitignored work 目录，`uv run python` 跑；进 bench 档 per-file-ignores 即可）。参数：`SRC --name NAME --strip-prefix PFX [--project-root-for-attribution DIR]`；自动做：strip→按规则裁切→写 fixture→**对裁后文本跑 parse_log 生成 manifest 行**（断言值永远以裁后件为准，行号不漂移）→`-verify` 重放栈对拍源件。

### manifest schema

```json
{"file":"xelatex-runaway-eof.log","source":"bench/work_e2ereal/pipe-xel/hep-ph--9910403/plb-rev.log",
 "engine":"XeTeX","n_errors":2,"ok":false,
 "first_error":{"head_contains":"File ended while scanning","tex_file":null,"tex_line":null,
                "eof_file":"./plb-rev.tex","stack_suffix":null},
 "warnings":{"by_class_min":{},"redline_contains":[],"sys_hits_contains":[],"cjk_missing_min":0},
 "tail_last":"No pages of output.",
 "fixloop":{"category":"syntax","payload":null},
 "notes":"runaway: ) pop dist 3 < _EOF_POP_WINDOW=16"}
```

`fixloop` 段沿用 `test_fixloop_spikereplay.py` 现有 (n_bang, category, payload) 表惯例——fixture 天然双消费端（L2 verdict + taxonomy）。

### 测试侧挂法

`test_validate_l2.py` 加一个 manifest-parametrize 测试：`@pytest.mark.parametrize("row", manifest)` 断言每个声明字段；`eof_file`/`==>` 剔除/非 tex 扩展名各加一条 dedicated test（语义重，不塞 manifest）。`test_fixloop_spikereplay.py` 的 FIXTURES 表改从 manifest 读。现有 5 个 `NEED_LOGS` gated 用例的断言全部被 fixture 收编后**建议整块删除**（大 log 回归由 bench harness 承担，单测层不留 dead gate）；若保留作本机回归，至少把 876KB utf8 巨兽换成小件。

### 逐 fixture 映射表（源→清洗→断言，verdict 已实测）

| fixture 名 | 源（相对 repo） | 原大小 | 清洗 | 关键断言（裁后由 extractor 重算） |
|---|---|---|---|---|
| `xelatex-missing-file.log` | 已有 | 1.8KB | — | 现有测试不动 |
| `xelatex-fileline-syntax.log` | 已有 | 2.1KB | — | 现有测试不动 |
| `xelatex-missing-cls-min.log` | `bench/work_compile_v2/2109.12648/baseline/main.log` | 966B | **原样**（零私路径） | engine=XeTeX、n=2、first `File 'revtex4-1.cls' not found`、tail `No pages of output.`；fixloop=missing_file:revtex4-1.cls |
| `pdftex-emergency-fatal.log` | `bench/results/…/work/1502.06003/src/texput.log` | 684B | **原样** | engine=pdfTeX、n=2（`! Emergency stop` + `! ==> Fatal error` 双 bang 形态） |
| `xelatex-fileline-only-bib.log` | `bench/results/…/work/2112.00020/src/main.log` | 1308B | **原样** | n=2 且全文无 `^!`——fileline-only 假干净杀手；first `./main.bib:1:`、tex_file=`./main.bib`；尾行 `./main.bib:1: ==> Fatal error`（==> 剔除一并实证） |
| `tectonic-bare-stack.log` | `bench/work_compile_v4/hep-ph/9910443/baseline/_tect_out/hep99.log` | 2864B | **原样** | engine=None（无 `This is` 行）、n=0、missing_glyph redline（`£ ("A3)` 引号形非 CJK）、裸名栈 `(main.tex` 形态 |
| `tectonic-citation-warn.log` | `bench/work_compile_v4/1803.08846/baseline/_tect_out/gwbpre.log` | 6135B | **原样** | engine=None、ok、by_class citation=5/reference=1——替代 gated _WARN_LOG |
| `xelatex-utf8-redline-project.log` | `bench/work_compile_v4/1012.5145/baseline/wprime_cdf.log` | 1742B | strip `…/baseline/`→`./` | 工程件 invalid_utf8 真红线（lineno.sty 在工程树）+ missing cls + estop fileline——一份三形态 |
| `xelatex-inputenc-fffd.log` | `bench/work_compile_v4/1012.1124/baseline/main.log` | 9267B | strip→`./` | inputenc.sty:164 fileline 真错 + invalid_utf8×6 + fffd_glyph×6 红线；栈含 texmf 绝对路径（sys 归因上下文实证） |
| `xelatex-cjk-missing-glyph.log` | `bench/work_e2emock/corpus_v3/pipe-xel/2003.10723/SS_October.log` | 27247B | strip→`./`+裁 | by_class missing_glyph_cjk≥1、cjk_missing≥1、`这 (U+8FD9)` U+ 形真例——替代 gated 70KB |
| `xelatex-runaway-eof.log` | `bench/work_e2ereal/pipe-xel/hep-ph--9910403/plb-rev.log` | 26282B | strip→`./`+裁（**`)` 行全保**） | first `File ended while scanning use of \@iiiparbox`、eof_file=`./plb-rev.tex`（弹出距 3<16 实证 #78） |
| `xelatex-multierror-stack.log` | `bench/work_e2emock/corpus_v3/base-xel/1306.0302/manuscript.log` | 2221B | strip→`./` | n=4、fileline+abs 路径栈归一后 `./manuscript.tex`、nullfont 缺字 redline×2 |
| `tectonic-fatal-summary.log` | `bench/work_compile_v2/2002.05660/baseline/_tect_out/main.log` | 32873B | 裁 | `./colt2020.cls:5: ==> Fatal error…` 行**不计错**——`_NONERR_FILELINE_RX` `^\s*==>` 分支唯一真例；n 精确值裁后算 |
| `xelatex-fileline-nontex-ext.log`（可选） | `bench/results/…/work/1907.00257/splice/graph-transport.log` | 134KB | strip+重裁（113 错只保首错邻域+目标 .bbx/.lbx 行，n_errors 会变小——manifest 记裁后值） | first `/usr/share/texmf-dist/…/standard.bbx:10:`——非白名单扩展名 fileline 真例 |
| `xelatex-clean-warnings.log`（可选） | `bench/work_compile/1512.03385/baseline/residual_v1_arxiv_release.log` | 26KB | 裁 | ok、n=0、overfull/font_subst 分类——替代 gated clean |

合计入库 ~13 件，预计总体积 ≤60KB（裁切后），其中 6 件原样零裁。

## 4. 池内拿不到的形态（诚实缺口）

- **`file:line:` 前缀 Warning 行**：7139 全扫 0 例（`_NONERR_FILELINE_RX` Warning 分支来自 fixloop 别的语料坑）——保持合成，在 manifest/fixture 注释记「本池无真例」。
- **`>200` 错误上限**：唯一真例 876KB 不合算——合成 201 条 `!` 行即可（纯计数性质）。
- **dos_eps + graphic 帧归因真例**：`Conversion_BTF.log` 只命中 `.eps` 字样非真 graphic-open+utf8 组合——现有 tmp_path 合成已盖好，不强求。

## 5. 建议落地顺序

1. extractor + manifest 骨架 + 6 件原样件（半天内）→ 立省 5 个 gated 用例的全部断言。
2. 裁切件 4 个（utf8/cjk/runaway/fatal-summary）+ verify 对拍。
3. 可选 2 件 + gated 块退役决定。
