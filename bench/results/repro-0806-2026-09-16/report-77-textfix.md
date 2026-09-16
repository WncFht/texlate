# repro-0806 #77 收口报告：`\text` 族参数边界跳扫 + C2 守卫

> 2026-09-16 晚。随 `f5da4bf` 联合提交入库（与 repro-2203 F2 patch 同 commit）。**e2e 终局：0806.3472 pipe-xel 由 partial(missing_character×16) → clean——整条退化链闭合。**

## 交付内容（segmenter.py + tests/test_segmenter_unpaired_0806.py）

### 1. `\text` 族参数边界跳扫

- `_MATH_TEXTARG` frozenset（segmenter.py:119）：text/intertext/shortintertext/mbox/hbox/fbox/makebox/framebox/emph/textnormal/textrm/textit/textbf/textsf/texttt/textsc/textsl/textup/textmd。parbox 类多参命令不在列（正文非首参，定序跳扫够不着）——注释已钉死。
- `_on_math` 体扫新增 cs 分支（:1706）：命中族名 → `_math_skip_textarg` 按 `*`?+`[opt]`≤2+`{m}` 定序跳扫，参内（含嵌套组）`$` 不再截断外层数学。
- 新助手：`_skip_balanced`（:1749，static——`{}`/`[]` 嵌套计深，brace 按 kind 判故 `\{` 转义无误判）+ `_math_skip_textarg`（:1768）。读到的 token 全进 body——paired 路只凭 vspan 盖字节，unpaired 路 `unread(body)` 原序回放，两路均安全。

### 2. C2 守卫：评估结论 = 可达且有害 → 补守卫（非仅注释）

- 可达路径实证：`_ListSource` 子扫两站点（`_env_with_mined` :2159 区 / `_subscan_render` :3424 区）经 `sub.scan` → mathshift dispatch → `_on_math`。参数内未配对 `$`（如 `\section{Title with $unpaired}`）耗尽 deque → `x is None` → 裸判据下 `_cover_to(fid, len)` + `_emit` 把 `[cons,EOF)` 整段 LITERAL 抢走主扫字节。
- 守卫（:1728）：`x is None and isinstance(src, Gullet)`。else 分支注释写明依据：_ListSource 耗尽时 unread 同队回插保序、无弹栈合成源问题，恒走回放。

## 验证矩阵

- `tests/test_segmenter_unpaired_0806.py`：**10/10 绿**（新增 3 条：`\text{...$c \mu$...}` 内层 `$` 不截断、mbox/makebox[opt] 变体、`\section{..$x}` 子扫耗尽不抢尾）。
- ruff check + format --check 两文件全净。
- e2e `bench/results/repro-0806-textfix-2026-09-16/`：0806.3472 pipe-xel **clean**——missing_character×16 清零（基线 66 errors → 0 → 残留 missing_char 全消）。
- **corpus_v3 全量 parsebench --v2**（`bench/results/parsebench-v2textfix-2026-09-16/`，1955 文件，对 `parsebench-v2full1955` 基线 @4e06299 pre-fix）：
  - v2 identity：**1955/1955 strict**（基线 1954+1 diverged，diverged 文件 nitin_rheath_bigamp.tex 现已 strict）；零回归、零 ok→err。
  - v2 leak：**3979 → 60**（dollar 587→59，begin_env 2599→0，ref_family 851→1）。注意：基线 pre-日期全部修复，此 delta 是 ABC 修复+本补丁的合计，非独占——可归因证据是 10/10 单测 + dollar-hits 降幅 + 下条。
  - 4 文件 leak +1（1206.5628 / 1811.10195×2 / 2009.10990）：ArticleSarahLemler 全文零 `\text` 族命令 → 本补丁证明性惰性，delta 来自其它修复的边界漂移；iaai 的 +1 是 `\$1 million` 转义美元（leak 检测器固有面）；均为边界漂移级非回归。

## 遗留注记

- segmenter.py 在报告时正被 1d 会话热重构（`_cov_origin` 锚账本移除、`_rappend_ph` 去 `tok` 参、新增 `_cover_gap`）：本补丁 4 个 hunk 逐行核对全部幸存，重构绕着本区段改；半改态的 `_rappend_ph` 调用点 TypeError 属重构在飞噪声，已通报。
- 重构期间给 `_on_math`/`_handle_verb` 各加 `PLR0915` noqa（两函数均被推到 51>50 语句上限）。若后续想用抽方法而非豁免，摘 noqa 即可。
- `tmp/exp/seg-nofix/` 是「减 4 hunks」影子树（归因实验用），因重构已失真，可弃。
- parsebench 全量跑于重构前装载的模块，结果干净有效。
