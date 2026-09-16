# fixloop tickets F3+F4 — verdict 语义 + missing_char CJK 规则 (2026-09-16)

spec: `docs/research/product/2026-09-16-batch-hardening-design.md` §9 F3/F4。ticket #85。

## F3 — reject verdict 语义

### 决定: 合成层消灭 `reject`，一律 `partial` + `reject_at` 审计字段

`judge()` 的 verdict.status 定义域本来就是 `{clean, partial, fail}`（`compile/judge.py` docstring 已钉）；`reject` 只在 `e2e.py` 的 3 处合成点冒出来：

1. fixloop 末格 `reject:<rid>` cell verdict（`e2e.py` fixloop 汇总段）；
2. `InjectRejectError`（`\documentstyle`/化石 cls 拒绝注入 ctex）；
3. `route.reject` / `find_main_tex` None（路由拒绝 / 无主文件）。

三处统一改为 `status="partial"`，同时给报告加 `reject_at ∈ {"fixloop","inject","route"}` + reject token 进 `verdict.reasons`（如 `["latex209"]`、`["reject:<rid>"]`）保留审计面。`cli.py` 退出码改从 `reject_at` 出 2（原 `status=="reject"` 出 2），fail 仍出 1，clean/partial 出 0。

理由：spec 的 verdict 三态语义里 partial=「出了 PDF 或出了交付物但降级」；route/inject 拒绝实际产出了 zh-src 树（翻译完成、仅注入/编译段拒绝），属降级交付而非编译失败——fail 留给「编译链走尽仍无 PDF」。fixloop 引擎内部 cell verdict `reject:<rid>` 不变（引擎内部分诊枚举，非合成状态）。

### 下游一致性

- `e2e.py` `_VERDICT_RANK` 保留 `reject:0` 位（旧报告回放兼容）。
- `worker.py`（属 #80/#81 文件，未动）→ `bench/results/f3-patch-notes.md`。
- `bench/py/e2e_real_bench.py`、`bench/py/fixloop_bench.py`（bench harness，未动）→ 同上 patch notes。

## F4 — missing_char 分诊规则（数据驱动）

### 结构

- `rules.yaml` taxonomy 增 `warn_missing_char`（scope `warnings`，`warn_id: missing_char`）——警告段「Missing character: There is no …」在零 `!` 错误时以伪类别驱动修复轮（3-scope 评估：head→tail→warnings）。
- 新规则 `missing_char_fix`（phase loop, order 25, `when.category=warn_missing_char`, kind `builtin_transform`, risk low, xelatex+tectonic 同参），builtin `missing_char_fix` 注册进 `TRANSFORM_FNS`。
- builtin 表驱动：`_MC_TABLE` 每条目 `{id, cps|ranges, font|font_not(正则), action:"cjk_warmup"|replace:"<TeX串>"}`；`params.char_table` 同形条目按 id 覆盖/扩列——新增缺字签名只改数据不改代码。

### 0307508 根因（/tmp/mc-repro 实证）

elsart.cls `\proc@elem` 把每个 frontmatter 元素排进 `\setbox\@tempboxa\hbox{#2}` 测量，组内 `\no@harm` 含 `\def\protect{\noexpand\protect\noexpand}`——这把 `\DeclareRobustCommand` 的 `\fontencoding/\fontfamily/\selectfont` 全变 no-op，xeCJK 首用初始化 `\__xeCJK_family_use:n` 里 `\xeCJK_font_gset_to_current:N` 把 `xeCJK/FandolSong-Regular(0)/m/n/10.53937` 这个 (family,series,shape,size) csname **全局**绑到当时字体现况（lmroman），之后所有同型 CJK 字符全部丢字。单 culprit 是 `\protect` 重定义一条（v_protect 探针：仅该 def 即 79 drops）。

修复 = 类无关：干净上下文预热绑定——`\AtBeginDocument{\setbox0=\hbox{{\normalsize 中}{\small 中}…}}`，7 个 (size,series,shape) 组合先把 csname 绑到真 CJK 字体，测量盒后续命中既有绑定不再污染。t12 实证 `\phantom{中}` 预热 → 0 drops。

### n100 种子签名

| 签名 | 论文 | 次数 | 处置 |
| --- | --- | --- | --- |
| CJK 码位 in lmroman/cmr | 0307508, 0707.3950, 0905.4907 | ×4379/60/92 | `cjk_warmup`（ranges 2E80–2FA1F, font_not=CJK 字体正则） |
| ≠ U+2260 in cmr7 | 0806.1079 | ×3 | `\ensuremath{\neq}` |
| − U+2212 in cmr10 | 1608.02516 | ×1 | `\ensuremath{-}` |
| § U+A7 in cmr10 | 2403.15096 | ×1 | `\S` |
| ø U+F8 in cmmi8 | 1003.1464 | ×1 | `\mbox{\o}` |
| è U+E8 in cmex10 | 0707.3950 | ×1 | `\mbox{\`{e}}` |

字体排除面：CJK 码位落在真 CJK 字体名（fandol/noto-cjk/source-han/uming/ukai/wqy/ipa/sim\*/ms gothic·mincho/含 cjk）→ 真缺字形，warmup 救不了，不匹配。无 ctex/xeCJK/CJKutf8 机制的源 → warmup 跳过不谎报 applied。pdftex 端 `^^xx`/`^^^xxxx` 记法解析到码位。

### 测试

`tests/test_fixloop_missing_char.py` 7 例：warn 类别驱动整轮（注入位置 documentclass 后/begin{document}前）、符号替换、无机制跳过、CJK-字体排除、char_table 扩列、pdftex `^^e8`、无 log 边界。F3 侧 `test_e2e.py`×3 + `test_cli.py` reject→partial+reject_at 断言更新。

### 验证

`uv run pytest tests/ -x -q` 1450 passed, 4 skipped；`uv run ruff check`（本 ticket 文件）clean。
