# fixloop v2 规则库整改 — 交接留痕 (rules-v2, 2026-09-15)

任务: M2 规则库整改,基准 `bench/results/fixloop-corpusv2-2026-09-15/`(40 篇 corpus_v2 无偏样本),验收本目录。

## 完成度: 100%,全部实测验证,未 commit(leader 统一入库)

| 整改点 | 状态 |
| --- | --- |
| eps_route 过度拒 (tectonic fileset 静态拒) | 已改 log 确证兜底拒,11 格旧拒全救回 |
| legacy 包 shim (xelatex missing_file 残余) | 已落 revtex/psfig/aastex stub + aastex_bundle_shadow + journal_cs_polyfill |
| missing_tfm after install (0903.0543) | 查无此判决——见下"根因对账" |

数字 (旧 → 新): xelatex 21/9/0/4/6 → 22/9/0/4/5;tectonic 8/8/3/6/15 → 19/8/4/4/5(FAIL→pdf 1/16→12/16);union pdf 32→34/40。13 格升,0 格退。

## 文件归属与改动面

- 我的: `src/texlate/compile/fixloop/{rules.yaml,builtins.py}`、`bench/py/fixloop_bench.py`、本结果目录、`tests/` 里 4 条 v1 契约断言(lead 后批的,见下)。
- 未动: `fixloop/engine.py`、`fixloop/logparse.py`(约束: 先报根因)。
- `git status` 里 `src/texlate/compile/sandbox.py` 的 M 是别人的在飞改动,别当我的一起合。

## 关键决策 (为什么这么改)

1. **eps_route 拒法**: v1 见 fileset 有 .eps 就在 precheck 拒 tectonic —— 误杀全部 pdf~-capable 工程。v2: 新增 `ps_image` taxonomy(xdvipdfmx "image inclusion failed for X.eps" 签名),loop 层 `eps_to_pdf`(order 15, epstopdf/gs 转换 + 引用改写 + PS-driver 选项剥离)先救,`eps_route`(order 16)兜底拒。实测 eps_to_pdf 救回全部 11 格,eps_route 零点火(兜底留着防工具缺席环境)。
2. **`[dvips]{graphicx}` 坑**: 扩展名省略引用在 dvips 全局选项下 .eps 优先 → xelatex 靠 xdvipdfmx 运行时 gs 转换能活,tectonic 死。eps_to_pdf 会剥 graphics 家族的 PS-driver 选项(`_PS_DRIVERS` 表),否则转完 pdf 仍按 .eps 解析。
3. **`\ProvidesClass[ver]` 必须以日期开头**: `\@ifl@t@r` 在 `\documentclass` 时解析 ver@*.cls,非日期串触发 `\ifnum` "Missing = inserted" —— 无 halt-on-error 时静默恢复(产出"假成功"pdf),halt-on-error 下致命。stub 模板统一 `[2026/09/15 fixloop legacy shim]`。
4. **tectonic bundle 的 aastex 是 5.0rc3 (1999)**: 缺 `\actaa` + deluxetable 全家。修法 = wdir 同名 stub 遮蔽 bundle(`aastex_bundle_shadow`, stub 内 `\LoadClassWithOptions{emulateapj}` + `\providecommand{\rotate}{}` —— emulateapj 缺 `\rotate`);非 aastex 工程走 `journal_cs_polyfill`(注入 ~55 条期刊缩写宏,表从 emulateapj.cls 抄)。undefined_cs payload 改抓 l.N 行末 cs 名就是为了给这两条喂 cs 名。
5. **missing_tfm 对账**: 全语料 8 格 missing_tfm 命中全部经 `install_tfm` 修复,零 `unfixable:missing_tfm`。0903.0543 两轮均 `rsfs10` → 装好 → clean。lead 看到的"unfixable:missing_tfm"实系 astro-ph/0306068 混淆。
6. **astro-ph/0306068 xelatex `unfixable:other` 是正确裁决**: wdir 自带化石类 caps.cls/cupbook.cls (1997 CUP) 的 `\@authortable` 手工重实现 tabular 内核(`\hbox\bgroup$`+`\@tabarray`+`\ifnum0=`}` 数括号),与 LaTeX2e≥2024 内核不兼容 —— `\chapter{X}` 即炸 "Extra }, or forgotten $."。无 halt-on-error 可恢复出 211KB pdf(手测);bench xelatex halt_on_error=True → 致命 → other → 无规则 → unfixable。tectonic bundle LaTeX2e 2021-11-15 内部件还是旧版 → 零错 clean(14 页)。修它要改写对方 cls 内核,无可泛化规则,不加。

## tests/ 4 条红 → 已修(lead 2026-09-15 授权归我)

全是 v1 契约 stale 断言,按 v2 语义改写,`uv run pytest tests/` 全绿(1020 pass):

- `test_fixloop_yamlish.py::test_shipped_rules_yaml_loads`: 24→29(30 条对账 = 29 rules + version_guard)
- `test_fixloop_logparse.py::test_head_categories`: undefined_cs payload `None`→`"foo"`
- `test_fixloop_rules.py::test_phase_ordering`: precheck `["eps_route",...]`→`["pstricks_route","static_precheck"]`
- `test_fixloop_loop.py::test_eps_route_rejects_on_tectonic`: 改喂 ps_image log(`tail` 字段走 stdout_tail `error:`→`! ` 归一真路径),断 `rounds[0].category=="ps_image"`;另加 `test_eps_route_fileset_only_clean_on_tectonic` 钉死"fileset 含 eps 但编译干净不拒"回归

## 复现

```sh
uv run python bench/py/fixloop_bench.py --out bench/results/fixloop-v2-rules-2026-09-15   # resume 支持
uv run python bench/py/fixloop_bench.py --only 0903.0543,1806.06690                      # 子集
uv run pytest tests/test_fixloop_*.py tests/test_fixloop_yamlish.py
```

## 已知遗留 (非阻塞)

- astro-ph/0306068 xelatex: `unfixable:other`(正确裁决,见上)。
- `journal_cs_polyfill` 实测零点火 —— 唯一命中格被 order-155 aastex_bundle_shadow 先接住,规则留作非 aastex 工程的兜底。
- xelatex `acceptable_pdf` 3 格尾因 warn_utf8(1609.01652/2104.02882/2506.07410),latin-1 源残余,属 non_utf8 链非本整改面。
