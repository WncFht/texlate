# fixloop 规则库 YAML 化 + tectonic 适配分析

> **结论**：spike 全部修复逻辑可无损翻译为两层 YAML——`taxonomy`（log→错误类别，18 regex）+ `rules`（类别→动作，16 条）；install 系四招占 86 次规则触发的 75 次（87%），是救回率主力；11 条源码改写天然引擎无关可直接平移 tectonic，真正要降级的只有 5 条依赖 tlmgr/kpsewhich/updmap 的规则——降级路径汇到同一原语 `ctan_fetch`（file→TeX Live 包离线索引 + tlnet archive 直接解包到工作目录的「mini-tlmgr」）。
> **状态**：现行（已落地为 `compile/fixloop/`——engine/actions/ruleset 三件套 + `rules/` 分片目录 + `_builtins_*` 叶 + `llm_hook`（`ctan.py` 已上提为 `compile/ctan.py`，2026-09-20）；规范见 `spec/compile.md`）
> **日期**：2026-09-15

fixloop spike（bench 原型，已随产品化退役）的 YAML 化设计稿兼 tectonic 适配分析；22 格语料实测（16 原始失败 → 16 救回、15 clean）来自开发机 bench 现场。spike 产物 rules.yaml（schema v1）其后演化为现行 `compile/fixloop/rules/` 分片目录，条目数以代码为准。

## 1. 规则全表（16 条）

phase：`gate`=每轮分类后最先评估 / `precheck`=编译前一次性 / `loop`=每轮错误驱动；同 phase 内按 order 升序，每轮只应用一条。

| #   | id                   | phase/order | 触发 (category)                                        | 动作                                                                          |
| --- | -------------------- | ----------- | ------------------------------------------------------ | ----------------------------------------------------------------------------- |
| 1   | `latex209_reject`    | gate/1      | `latex209` 或 `missing_file`+主文件含 `\documentstyle` | reject_route → latex+dvips                                                    |
| 2   | `static_precheck`    | precheck/0  | always                                                 | 扫 `\usepackage/\RequirePackage/\documentclass` → 探测缺失 → filemap 批量装包 |
| 3   | `install_file`       | loop/10     | `missing_file`                                         | filemap 查包→安装→复核；扩展名∈{tfm,pfb,vf,fd,map,enc} 时装后重建 map         |
| 4   | `install_tfm`        | loop/20     | `missing_tfm`                                          | 装 `{pay}.tfm` 所在包 + updmap                                                |
| 5   | `install_sysfont`    | loop/30     | `fontspec_missing`                                     | 按 `{pay}.otf/.ttf/.ttc` 搜包装 + updmap                                      |
| 6   | `missing_pfb_updmap` | loop/40     | `missing_pfb`                                          | `updmap-user` 重建 map                                                        |
| 7   | `pdftex_prim_guard`  | loop/50     | `pdftex_prim`                                          | 13 个 `\pdf*` 原语套 `\ifdefined…\fi`（lookbehind 幂等）                      |
| 8   | `px_to_bp`           | loop/60     | `illegal_unit`                                         | `N px` → `N*0.75 bp`（命名函数，算术非纯模板）                                |
| 9   | `microtype_off`      | loop/70     | `xetexglyph_tfm`                                       | microtype 强制 `[protrusion=false,expansion=false]`                           |
| 10  | `times_to_newtx`     | loop/80     | `xetexglyph_tfm`                                       | `{mathptmx/mathptm}`→`{newtxtext,newtxmath}`，`{times}`→`{newtxtext}`         |
| 11  | `hyphenation_sane`   | loop/90     | `hyphenation`                                          | `\hyphenation{}` 只留 `[a-zA-Z-]` token（命名函数）                           |
| 12  | `soul_cjk_mbox`      | loop/100    | `soul_err`                                             | `\hl/\ul/\st/\so/\caps` 含 CJK 参数套 `\mbox`                                 |
| 13  | `thm_sibling_strip`  | loop/110    | `already_def`                                          | 剥 `sibling=\w+,?`                                                            |
| 14  | `option_clash_merge` | loop/120    | `option_clash`                                         | 同名包重复加载→合并选项到首处 + 注释后处（算法型 builtin）                    |
| 15  | `minted_frozencache` | loop/130    | `minted_froz`                                          | 有 pygmentize 才剥 `frozencache` 选项（需 shell-escape）                      |
| 16  | `undefined_cs_guess` | loop/900    | `undefined_cs`                                         | escalate_llm（spike 期占位）                                                  |

**动作原语** 7 种（`action.kind`）：`scan_install`(1)、`install_file`(3-5 共用参数不同)、`run_tool`(6)、`regex_rewrite`(7-13,15)、`builtin_transform`(14)、`reject_route`(1)、`escalate_llm`(16)。**命名函数注册表**只有 3 个算法型改写——`px_to_bp`、`keep_latin_tokens`、`option_clash_merge`——其余全是 pattern+repl 模板；社区贡献新规则多数只需写 regex，新函数才需要 PR 代码。

## 2. 覆盖统计（22 格实测）

| 规则                                                                                                                                     | 触发次数 | 所在格终出 pdf | 状态                        |
| ---------------------------------------------------------------------------------------------------------------------------------------- | -------- | -------------- | --------------------------- |
| static_precheck                                                                                                                          | 22       | 22             | 实战验证                    |
| install_file                                                                                                                             | 26       | 17             | 实战验证                    |
| install_sysfont                                                                                                                          | 14       | 14             | 实战验证                    |
| install_tfm                                                                                                                              | 13       | 13             | 实战验证                    |
| microtype_off                                                                                                                            | 4        | 4              | 实战验证                    |
| pdftex_prim_guard                                                                                                                        | 3        | 3              | 实战验证                    |
| px_to_bp                                                                                                                                 | 3        | 3              | 实战验证                    |
| hyphenation_sane                                                                                                                         | 1        | 1              | 实战验证                    |
| soul_cjk_mbox                                                                                                                            | 0¹       | 0              | **已知缺口**                |
| missing_pfb_updmap / times_to_newtx / thm_sibling_strip / option_clash_merge / minted_frozencache / latex209_reject / undefined_cs_guess | 0        | 0              | proposed（防御性/经验移植） |

¹ 2005.11401/zh 触发 `soul_err` 但 regex 0 文件命中 → skip → 全场唯一 dirty_pdf（6 errs）。

- install 系 4 招 = 75/86 次触发（**87%**）。
- 首错类别分布：`missing_sty` 16 格（救回 16/16）、`missing_tfm` 4（4/4）、`pdftex_prim` 1（1/1）、none 1。
- 分布偏差提醒：`missing_sty` 里 14 格是 `zhnumber.sty`——ctex/zh 条件注入产物，换语料分布会变；规则库要靠沉淀机制持续增长。

## 3. 匹配顺序与防干扰（四个不变量）

1. **gate 先于一切**：对 `missing_file`+`\documentstyle` 必须在 `install_file` 之前拦，否则给 2.09 文档误装包——YAML 用 `phase: gate` 显式建模 spike 主循环的硬编码短路。
2. **install 先于 rewrite**（order 10-40 < 50-130）：环境缺包时不许动源码，避免把「没装包」误诊成「源码错」留下脏改写。
3. **同 trigger 内保守→激进梯度**：`microtype_off`(70) 先于 `times_to_newtx`(80)，两者都命中 `xetexglyph_tfm`；dedup key `(rule_id, payload)` 保证第一轮先试关特性，同签名再现才轮到换字体族。
4. **兜底恒最后**：`undefined_cs_guess` order 900，所有具体规则放弃后才 escalate。

其余机制：每轮一条规则便于归因；`(rid,pay)` dedup 防重复；同 `cat:pay` 签名连续 3 轮判 `stuck`；rewrite 幂等性逐条审过——`pdftex_prim_guard` 靠 `(?<!ifdefined)` lookbehind，`px_to_bp`/`microtype_off`/`option_clash_merge` 重入同值或 hits<2 短路，`thm_sibling_strip`/`minted_frozencache`/`soul_cjk_mbox` 剥除式替换天然幂等。

## 4. tectonic 降级矩阵

tectonic = XeTeX 内核 + TeX Live bundle 按需拉取；**无 tlmgr / 无 kpsewhich / 无 updmap**。taxonomy 层全部可复用（log 格式同源）。规则层：

| 规则                                                                                                                                      | 依赖能力                | tectonic 可行性 | 降级方案                                                                                                                                                    |
| ----------------------------------------------------------------------------------------------------------------------------------------- | ----------------------- | --------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------- |
| static_precheck                                                                                                                           | kpsewhich+tlmgr         | 可省            | `skip`——bundle 按需拉包使预检多余；可选轻量版仅查本地存在性，缺→ctan_fetch                                                                                  |
| install_file                                                                                                                              | tlmgr search/install    | **核心降级**    | `ctan_fetch`：filemap 离线索引（解析 texlive.tlpdb）得包名 → 拉 `tlnet/archive/<pkg>.tar.xz` → 解包到工作目录（本地文件优先于 bundle）；查不到 → `advisory` |
| install_tfm                                                                                                                               | 同上+updmap             | 同上            | `ctan_fetch`（tfm 落工作目录直读可用）；要 pfb map → escalate（无 updmap）                                                                                  |
| install_sysfont                                                                                                                           | 同上+updmap             | partial         | `ctan_fetch_font` 拉到字体后 fontspec 按名查找仍不可见 → 需配套源改写注入 `Path=./` 或注册 fontconfig；否则 advisory                                        |
| missing_pfb_updmap                                                                                                                        | updmap                  | **不支持**      | escalate_llm / 路由回 xelatex                                                                                                                               |
| pdftex_prim_guard / px_to_bp / microtype_off / times_to_newtx / hyphenation_sane / soul_cjk_mbox / thm_sibling_strip / option_clash_merge | —（源改写）             | same            | 无需降级；newtx 在 bundle 内                                                                                                                                |
| minted_frozencache                                                                                                                        | pygmentize+shell-escape | partial         | shell-escape 受限 → 剥选项后跑通无保证；备选改写 listings 或 advisory                                                                                       |
| latex209_reject                                                                                                                           | —（路由策略）           | same            | —                                                                                                                                                           |
| undefined_cs_guess                                                                                                                        | —（LLM）                | same            | —                                                                                                                                                           |

**降级架构要点**：5 条降级里 4 条汇到同一原语 `ctan_fetch`——真正要建的资产是 **file→TL 包索引**（xelatex 下由 `tlmgr search --file` 充当；tectonic 下用 texlive.tlpdb 离线解析生成，随规则库分发 + `overrides` 手工表兜底）。这一个索引同时喂 static_precheck 与 install_* 三招。updmap 无替代物——TFM 直读不需要它，需要 pfb map 的场景直接 escalate。→ 落地即 `compile/ctan.py`（实测见 `ctanfetch-probe.md`）。

## 5. 规则执行引擎接口（设计稿，落地以 `compile/fixloop/engine.py` 为准）

引擎适配层 `Engine` Protocol：`caps` 能力位（kpsewhich/tlmgr/updmap/shell_escape/bundle）+ `compile/probe_file/install_file/rebuild_fontmaps/filemap` 五方法，xelatex 与 tectonic 各一实现。主循环：precheck 规则先行 → 找主文件 → 每轮 `compile` → `parse_log`（首个 `^!` 行 + 8 行 ctx + `!` 总数 + tail；v1 增强 `l.N` 行号与 `(` 开括号文件栈，供 rewrite 收窄作用域）→ `classify`（有 `!` 按序首命中、无 `!` 走 tail；`undefined_cs` 命中后 subclassify `\pdf*`→`pdftex_prim`）→ gate 判终局（pdf+0 错→clean / gate 命中→reject / sig×3→stuck）→ `match`（dedup + category + payload_required + condition + `eng.can_run` 能力位）→ `apply` 分派七种动作 → `finish` 汇总 + case 持久化进 `cases.jsonl`（沉淀原料）。

与 spike 的两处刻意差异：① gate 从主循环硬编码改为规则条目（语义等价、可配置）；② `parse_log` 增加行号与文件栈输出，为 rewrite 规则作用域收窄留口（spike 全树盲改靠 regex 精确度兜底，无副作用记录）。

## 6. 「新失败 → 新规则」沉淀机制

每格跑完产 `cases.jsonl` `{corpus, cond, engine, rounds[cat/pay/rule/result], verdict, log_excerpt}`；verdict ∈ {unfixable, stuck, dirty_pdf} 进 triage 队列，LLM/人工读 log_excerpt 产出三类补丁之一：a) taxonomy 新行（新错误形态 regex→category）；b) rules 新条目（已有类别的修法，多为 regex_rewrite）；c) filemap.overrides 行（索引查不到的 file→pkg）。入库门槛 = 回放验证：本格重跑必须把它从 fail 修到 pdf；全语料回归不得把任何 clean 格改脏（no-regression gate）；status `proposed → active`，fires/rescues 计数回填 stats。

设计要点：**低门槛贡献面**——估算新失败约 80% 落在「已知类别的变体」（新 regex 行或新 rewrite 参数），纯 yaml PR；只有新算法型修复要写 `builtin_transform` 函数。**置信度追踪**——每条规则带 `stats.fires/rescued_cells` + `status: stub|proposed|active|retired`，fires=0 的防御性规则全标 proposed，实战首次救回才转 active。**provenance 必填**——`corpus_id + error` 原文使每条规则可回溯到具体失败现场（hjfy 人工维护库 → 开源知识的等价物）。**shadow 模式**（可选）——proposed 规则排在 active 之后试运行，只记录假想应用结果，积累证据再转正，防新规则抢占老规则触发位引入回归。沉淀队列头号 case：`soul_cjk_mbox`——2005.11401/zh 的 soul_err 不在现有 CJK-参数 pattern 覆盖内，需要新 taxonomy 细分或第二条 rewrite。

## 7. 已知缺口（spike 遗留，随 yaml 显式登记）

1. `soul_cjk_mbox` regex 覆盖不足（上节）——唯一 dirty_pdf 的直接原因。
2. `already_def` 泛化 newtheorem 去重未实现。
3. `undefined_cs_guess` 是 stub——cs→pkg 知识库是 filemap 之外的第二张待建索引（现行 `llm_hook` 是其落地形）。
4. `static_precheck` 误捕非包名 token（实测 `\\@tempb.sty`）——yaml 加 `noise_filter` 参数，无害但噪声。
5. `install_file` 的 `already-present` 分支会把「非本规则解决的缺文件」记为 applied——归因噪音，应单独统计。
6. `hyphenation` 的 `Not a letter` pattern 存在误命中其他语境面——yaml 加 `ctx_suggests: \hyphenation` 条件位。
