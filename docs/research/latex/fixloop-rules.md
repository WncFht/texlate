# fixloop 16 条规则 YAML 化 + tectonic 适配分析

**结论先行**: spike 的全部修复逻辑可以无损翻译成两层 YAML —— `taxonomy`(log→错误类别，18 个 regex) + `rules`(类别→动作，16 条)。四招 install 系 (`static_precheck`/`install_file`/`install_tfm`/`install_sysfont`) 占全部 86 次规则触发的 75 次 (87%), 是救回率主力; 11 条源码改写规则**天然引擎无关**, 可直接平移 tectonic; 真正需要降级的只有 5 条依赖 tlmgr/kpsewhich/updmap 的规则，降级路径核心是一个 **file→TeX Live 包离线索引** (texlive.tlpdb 解析产物) + tlnet archive 直接解包到工作目录 ("mini-tlmgr")。产出：`tmp/exp/fixrules/rules.yaml` (schema v1)。

源实现：`bench/py/fixloop.py`; 数据：`bench/results/fixloop-results.json` (22 格，16 原始失败 → 16 救回，15 clean); 报告：`bench/results/fixloop-spike-report.md`。

---

## 1. 规则全表 (16 条)

phase: `gate`=每轮分类后最先评估 / `precheck`=编译前一次性 / `loop`=每轮错误驱动。
同 phase 内按 order 升序，每轮只应用一条 (fixloop.py:549-565)。

| #   | id                   | phase/order | 触发 (category)                                        | 动作                                                                          | 实现位置                    |
| --- | -------------------- | ----------- | ------------------------------------------------------ | ----------------------------------------------------------------------------- | --------------------------- |
| 1   | `latex209_reject`    | gate/1      | `latex209` 或 `missing_file`+主文件含 `\documentstyle` | reject_route → latex+dvips                                                    | fixloop.py:508-520, 748-755 |
| 2   | `static_precheck`    | precheck/0  | always                                                 | 扫 `\usepackage/\RequirePackage/\documentclass` → 探测缺失 → filemap 批量装包 | fixloop.py:594-618          |
| 3   | `install_file`       | loop/10     | `missing_file`                                         | filemap 查包→安装→复核; 扩展名∈{tfm,pfb,vf,fd,map,enc} 时装后重建 map         | fixloop.py:301-311, 264-276 |
| 4   | `install_tfm`        | loop/20     | `missing_tfm`                                          | 装 `{pay}.tfm` 所在包 + updmap                                                | fixloop.py:314-321          |
| 5   | `install_sysfont`    | loop/30     | `fontspec_missing`                                     | 按 `{pay}.otf/.ttf/.ttc` 搜包装 + updmap                                      | fixloop.py:324-332          |
| 6   | `missing_pfb_updmap` | loop/40     | `missing_pfb`                                          | `updmap-user` 重建 map                                                        | fixloop.py:335-341          |
| 7   | `pdftex_prim_guard`  | loop/50     | `pdftex_prim`                                          | 13 个 `\pdf*` 原语套 `\ifdefined…\fi` (lookbehind 幂等)                       | fixloop.py:344-361, 284-298 |
| 8   | `px_to_bp`           | loop/60     | `illegal_unit`                                         | `N px` → `N*0.75 bp` (命名函数，算术非纯模板)                                 | fixloop.py:364-375          |
| 9   | `microtype_off`      | loop/70     | `xetexglyph_tfm`                                       | microtype 强制 `[protrusion=false,expansion=false]`                           | fixloop.py:378-393          |
| 10  | `times_to_newtx`     | loop/80     | `xetexglyph_tfm`                                       | `{mathptmx/mathptm}`→`{newtxtext,newtxmath}`, `{times}`→`{newtxtext}`         | fixloop.py:396-406          |
| 11  | `hyphenation_sane`   | loop/90     | `hyphenation`                                          | `\hyphenation{}` 只留 `[a-zA-Z-]` token (命名函数)                            | fixloop.py:409-426          |
| 12  | `soul_cjk_mbox`      | loop/100    | `soul_err`                                             | `\hl/\ul/\st/\so/\caps` 含 CJK 参数套 `\mbox`                                 | fixloop.py:429-445          |
| 13  | `thm_sibling_strip`  | loop/110    | `already_def`                                          | 剥 `sibling=\w+,?`                                                            | fixloop.py:448-456          |
| 14  | `option_clash_merge` | loop/120    | `option_clash`                                         | 同名包重复加载→合并选项到首处 + 注释后处 (算法型 builtin)                     | fixloop.py:459-494          |
| 15  | `minted_frozencache` | loop/130    | `minted_froz`                                          | 有 pygmentize 才剥 `frozencache` 选项 (需 -shell-escape)                      | fixloop.py:497-505          |
| 16  | `undefined_cs_guess` | loop/900    | `undefined_cs`                                         | escalate_llm (占位，spike 恒返回 False)                                       | fixloop.py:523-527          |

**动作原语** 共 7 种 (rules.yaml `action.kind`): `scan_install`(1)、`install_file`(3-5 共用，参数不同)、`run_tool`(6)、`regex_rewrite`(7-13,15)、`builtin_transform`(14)、`reject_route`(1)、`escalate_llm`(16)。
**命名函数注册表** (算法型改写，无法纯 regex 表达，保留为代码): `px_to_bp`、`keep_latin_tokens`、`option_clash_merge` —— 只有 3 个，其余改写全是 pattern+repl 模板。社区贡献新规则时多数只需写 regex; 新函数才需要 PR 代码。

## 2. 覆盖统计 (fixloop-results.json 实测)

| 规则                                                                                                                                     | 触发次数 | 所在格终出 pdf | 状态                       |
| ---------------------------------------------------------------------------------------------------------------------------------------- | -------- | -------------- | -------------------------- |
| static_precheck                                                                                                                          | 22       | 22             | 实战验证                   |
| install_file                                                                                                                             | 26       | 17             | 实战验证                   |
| install_sysfont                                                                                                                          | 14       | 14             | 实战验证                   |
| install_tfm                                                                                                                              | 13       | 13             | 实战验证                   |
| microtype_off                                                                                                                            | 4        | 4              | 实战验证                   |
| pdftex_prim_guard                                                                                                                        | 3        | 3              | 实战验证                   |
| px_to_bp                                                                                                                                 | 3        | 3              | 实战验证                   |
| hyphenation_sane                                                                                                                         | 1        | 1              | 实战验证                   |
| soul_cjk_mbox                                                                                                                            | 0¹       | 0              | **已知缺口**               |
| missing_pfb_updmap / times_to_newtx / thm_sibling_strip / option_clash_merge / minted_frozencache / latex209_reject / undefined_cs_guess | 0        | 0              | proposed (防御性/经验移植) |

¹ 2005.11401/zh 触发 `soul_err` 但 regex 0 文件命中 → skip → 全场唯一 dirty_pdf (6 errs)。

- install 系 4 招 = 75/86 次触发 (**87%**, 即任务书"90%"口径)。
- 首错类别分布：`missing_sty` 16 格 (救回 16/16), `missing_tfm` 4 (4/4), `pdftex_prim` 1 (1/1), none 1。
- 注意分布偏差：`missing_sty` 里 14 格是 `zhnumber.sty` —— ctex/zh 条件注入产物，换语料分布会变; 规则库要靠沉淀机制持续长。

## 3. 匹配顺序与防干扰

spike 的 `RULES` 列表序 (fixloop.py:530-546) 翻译成 order 后保留了四个关键不变量：

1. **gate 先于一切**: `latex209_reject` 在 spike 里不靠规则序，而是主循环硬编码短路 (L748-755) —— 对 `missing_file`+`\documentstyle` 必须在 `install_file` 之前拦，否则会给 2.09 文档白装包。YAML 用 `phase: gate` 显式建模这个"每轮最先评估"语义。
2. **install 先于 rewrite** (order 10-40 < 50-130): 环境缺包时不许动源码 —— 避免把"没装包"误诊成"源码错"留下脏改写。
3. **同 trigger 内"保守→激进"梯度**: `microtype_off`(70) 先于 `times_to_newtx`(80), 两者都吃 `xetexglyph_tfm`; dedup key `(rule_id, payload)` (L552,561) 保证第一轮先试关特性，同签名再现时才轮到换字体族。
4. **兜底恒最后**: `undefined_cs_guess` order 900, 所有具体规则放弃后才 escalate。

其余防干扰机制：每轮一条规则 (便于归因); `(rid,pay)` dedup 防重复; 同 `cat:pay` 签名连续 3 轮 → `stuck` (L756-761); rewrite 幂等性逐条审过 —— `pdftex_prim_guard` 靠 `(?<!ifdefined)` lookbehind, `px_to_bp`/`microtype_off`/`option_clash_merge` 重入结果为同值或 hits<2 短路，`thm_sibling_strip`/`minted_frozencache`/`soul_cjk_mbox` 剥除式替换天然幂等。

## 4. tectonic 降级矩阵

tectonic = XeTeX 内核 + TeX Live bundle 按需拉取; **无 tlmgr / 无 kpsewhich / 无 updmap**。taxonomy 层全部可复用 (log 格式同源)。规则层：

| 规则               | 依赖能力                | tectonic 可行性 | 降级方案                                                                                                                                                                                 |
| ------------------ | ----------------------- | --------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| static_precheck    | kpsewhich+tlmgr         | 可省            | `skip` —— bundle 按需拉包使预检多余; 可选轻量版：仅查本地存在性，缺 → ctan_fetch                                                                                                         |
| install_file       | tlmgr search/install    | **核心降级**    | `ctan_fetch`: filemap 离线索引 (解析 texlive.tlpdb) 得包名 → 拉 `tlnet/archive/<pkg>.tar.xz` → 解包到工作目录 (tectonic 本地文件优先于 bundle); 索引查不到 → `advisory` (报错附候选包名) |
| install_tfm        | 同上+updmap             | 同上            | `ctan_fetch` (tfm 落工作目录直读可用); 后端若要 pfb map → escalate (无 updmap)                                                                                                           |
| install_sysfont    | 同上+updmap             | partial         | `ctan_fetch_font` 拉到字体文件后 fontspec 按名查找仍不可见 → 需配套源改写注入 `Path=./` 或注册 fontconfig; 否则 advisory (建议换 bundle 内字体)                                          |
| missing_pfb_updmap | updmap                  | **不支持**      | escalate_llm / 路由回 xelatex                                                                                                                                                            |
| pdftex_prim_guard  | — (源改写)              | same            | 无需降级; 守卫在 XeTeX 核语义一致                                                                                                                                                        |
| px_to_bp           | —                       | same            | —                                                                                                                                                                                        |
| microtype_off      | —                       | same            | —                                                                                                                                                                                        |
| times_to_newtx     | —                       | same            | newtx 在 bundle 内                                                                                                                                                                       |
| hyphenation_sane   | —                       | same            | —                                                                                                                                                                                        |
| soul_cjk_mbox      | —                       | same            | —                                                                                                                                                                                        |
| thm_sibling_strip  | —                       | same            | —                                                                                                                                                                                        |
| option_clash_merge | —                       | same            | —                                                                                                                                                                                        |
| minted_frozencache | pygmentize+shell-escape | partial         | shell-escape 受限 → 剥选项后未必能跑; 备选改写 listings 或 advisory                                                                                                                      |
| latex209_reject    | — (路由策略)            | same            | —                                                                                                                                                                                        |
| undefined_cs_guess | — (LLM)                 | same            | —                                                                                                                                                                                        |

**降级架构要点**: 5 条降级里有 4 条汇到同一个原语 `ctan_fetch` —— 所以真正要建的资产是 **file→TL 包索引** (xelatex 下由 `tlmgr search --file` 充当，fixloop.py:176-208; tectonic 下用 texlive.tlpdb 离线解析生成，随规则库分发 + `overrides` 手工表兜底)。这一个索引同时喂 static_precheck 与 install_* 三招。updmap 无替代物 —— TFM 直读不需要它，需要 pfb map 的场景直接 escalate。

## 5. 规则执行引擎接口 (~100 行 spec)

```python
# ─── 引擎适配层：xelatex / tectonic 各一实现 ───
class Engine(Protocol):
    caps: set[str]                    # {kpsewhich,tlmgr,updmap,shell_escape,bundle}
    def compile(wdir, main, passes=2) -> CompRes      # pdf?, log_path, timed_out
    def probe_file(fname) -> str|None  # kpsewhich | 本地+bundle 探测
    def install_file(fname, font_related) -> bool     # tlmgr | ctan_fetch 降级
    def rebuild_fontmaps() -> None     # updmap-user | noop
    def filemap(fname) -> list[str]    # file→pkg 索引 (tlmgr search | tlpdb 表)

# ─── log 解析 ───
def parse_log(log_path) -> ErrReport:
    # 首个 '^!' 行 + 其后 8 行 ctx + '!' 总数 + tail 30 行   (spike L48-64)
    # v1 增强：ctx 内 /l\.(\d+)/ → 出错行号;
    #          '(' 开括号文件栈追踪 → file_stack (定位出错 .tex/.sty,
    #          供 rewrite 规则缩小作用域，spike 是全文件树盲改)
def classify(rep, taxonomy) -> (cat, payload):
    # 有 '!' → head 段按序首命中; 0 个 '!' → tail 段     (L67-125)
    # undefined_cs 命中后 subclassify: \pdf* → pdftex_prim (L110-114)

# ─── 规则匹配 ───
def match(rules, cat, pay, ctx, eng) -> Rule|None:
    for r in sorted(rules.of_phase("loop"), key=order):
        if (r.id, pay) in ctx.applied:        continue   # dedup
        if r.when.category != cat:            continue
        if r.when.payload_required and !pay:  continue
        if !cond_ok(r.condition, ctx, eng):   continue   # tool_available / main_head_contains
        if !eng.can_run(r.action):            continue   # 能力位 → native/degrade/skip
        return r

# ─── 动作分派 ───
def apply(rule, ctx, eng) -> (applied, note):
    match rule.action.kind:
        case scan_install:   # 扫包→probe→filemap→eng.install_file(batch)
        case install_file:   # probe→filemap→install_file→复核; font_related→rebuild_fontmaps
        case run_tool:       # subprocess argv
        case regex_rewrite:  # 遍历 tex_files(exts 过滤): pattern+repl | function(payload)
        case builtin_transform: BUILTINS[function](ctx, **params)  # option_clash_merge
        case reject_route:   return True, "REJECT: ..."
        case escalate_llm:   return llm_fallback(ctx)      # 外部注入，规则只定义上下文

# ─── 主循环 ───
def fixloop(proj, eng, ruleset) -> Cell:
    ctx = Ctx(proj)                       # applied=set, actions=[], installed=[]
    for r in ruleset.phase("precheck"): apply(r, ctx, eng)          # 第 0 招
    main = find_main_tex(proj)            # 深度 + 有无\begin{document} 启发式 (L575-587)
    prev_sig, sig_n = None, 0
    for rnd in 1..ruleset.max_rounds:
        res = eng.compile(ctx.wdir, main, passes=2)
        rep = parse_log(res.log); cat, pay = classify(rep)
        # 终止判据 (L742-761): pdf+0 错→clean; cat clean/None→判 pdf;
        #   gate 规则命中→reject; sig 重复×3→stuck
        v = verdict_gate(res, cat, pay, ruleset.phase("gate"), ctx)
        if v: return finish(ctx, v)
        sig_n = sig_n+1 if (cat,pay)==prev_sig else 1; prev_sig=(cat,pay)
        if sig_n >= 3: return finish(ctx, "stuck")
        r = match(ruleset, cat, pay, ctx, eng)
        if r is None: return finish(ctx, "unfixable:"+cat if !res.pdf else "dirty_pdf")
        applied, note = apply(r, ctx, eng)
        if applied: ctx.applied.add((r.id,pay)); ctx.actions.append(rnd, r.id, note)
        if note.startswith("REJECT"): return finish(ctx, "reject:"+r.id)
    return finish(ctx, "max_rounds")
    # finish(): final_pdf/errors 汇总 + case 持久化 → cases.jsonl (沉淀原料)
```

与 spike 的两处刻意差异：① gate 从主循环硬编码改为规则条目 (语义等价，可配置); ② `parse_log` 增加 `l.N` 行号与 paren 文件栈输出，为 rewrite 规则的作用域收窄留口 (spike 全树盲改靠 regex 精确度兜着，目前无副作用记录)。

## 6. "新失败 → 新规则" 沉淀机制

```
每格跑完 → cases.jsonl {corpus, cond, engine, rounds[cat/pay/rule/result], verdict, log_excerpt}
     │
     ├─ verdict ∈ {unfixable, stuck, dirty_pdf} ─→ triage queue
     │     LLM/人工读 log_excerpt → 产出三类补丁之一:
     │       a) taxonomy 新行   (新错误形态: regex→category)
     │       b) rules 新条目    (已有类别的修法: 多为 regex_rewrite, 少数新 function)
     │       c) filemap.overrides 行 (索引查不到的 file→pkg)
     │
     ▼ 回放验证 (入库门槛)
   ① 本格重跑: 新规则必须把它从 fail 修到 pdf
   ② 全语料回归: 不得把任何 clean 格改脏 (no-regression gate)
   ③ status: proposed → active; fires/rescues 计数回填 stats
```

设计要点：

- **低门槛贡献面**: 估算新失败里 ~80% 落在"已知类别的变体" (新 regex 行或新 rewrite 参数), 纯 yaml PR; 只有新算法型修复要写 `builtin_transform` 函数。
- **置信度追踪**: 每条规则带 `stats.fires/rescued_cells` + `status: stub|proposed|active|retired`; fires=0 的 8 条防御性规则全部标 `proposed`, 实战首次救回才转 `active`。
- **provenance 必填**: `corpus_id + error` 原文，使每条规则可回溯到具体失败现场 (hjfy 人肉库 → 开源知识的等价物)。
- **shadow 模式** (可选): proposed 规则排在 active 规则之后试运行，只记录"若应用会怎样", 攒证据再转正 —— 防新规则抢老规则的触发位引入回归。
- **当前沉淀队列头号 case**: `soul_cjk_mbox` —— 2005.11401/zh 的 soul_err 不在现有 CJK-参数 pattern 覆盖内，需要新 taxonomy 细分或第二条 rewrite。

## 7. 已知缺口 (spike 遗留，随 yaml 显式登记)

1. `soul_cjk_mbox` regex 覆盖不足 (上节) —— 唯一 dirty_pdf 的直接原因。
2. `already_def` 泛化 newtheorem 去重未实现 (fixloop.py:453-455)。
3. `undefined_cs_guess` 是 stub —— cs→pkg 知识库是 filemap 之外的第二张待建索引。
4. `static_precheck` 误捕非包名 token (实测 `'\\\\@tempb.sty'`) —— 已在 yaml 加 `noise_filter` 参数，无害但噪声。
5. `install_file` 的 `already-present` 分支 (L268-269) 会把"非本规则解决的缺文件"记为 applied —— 归因噪音，建议改记 `applied=True, note=already-present` 单独统计。
6. `hyphenation` 的 `Not a letter` pattern 可能误中其他语境 —— yaml 已加 `ctx_suggests: \hyphenation` 条件位。

## 交付物

- `tmp/exp/fixrules/rules.yaml` —— schema v1 全量规则表 (meta/capabilities/filemap/taxonomy 23 行/rules 16 条)
- 本文件 —— 规则全表、覆盖统计、顺序设计、tectonic 降级矩阵、引擎 spec、沉淀机制
