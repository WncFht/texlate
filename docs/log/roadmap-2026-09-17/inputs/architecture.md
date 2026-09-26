# 架构面侦察输入（roadmap-2026-09-17）

> **结论**：架构侦察：残余巨件三块与 compile↔fixloop 模块级 2-环为结构脆弱点；rules.yaml 4797 行增速第一；R1–R3 演进建议。
> **状态**：时点证据（2026-09-17 口径）
> **日期**：2026-09-17（2026-09-20 迁入重编）
>
> 只读侦察，2026-09-17。基线：`docs/research/refactor-audit-2026-09-17/report.md`（Top6 已落地：repair.py 单源化、redlines registry、stagerun 拆包、segmenter 拆包、worker.py→server/worker/ 包、benchlib 读层）。本文只答五问：模块图现状、残余结构债、增长热点、一致性机制健康度、演进建议。所有断言带 file:line。

## 1. 重构后模块图现状

### 1.1 包体量（Python 行数，含子包；数据文件另列）

| 包          | 行数                              | 备注                                                                                                 |
| ----------- | --------------------------------- | ---------------------------------------------------------------------------------------------------- |
| `latex/`    | 7861 + segmenter 5683 = **13544** | 最大轴；另 `latex/data/argspec.json` 16851 行数据                                                    |
| `compile/`  | 6209 + fixloop 5667 = **11876**   | 另 `fixloop/rules.yaml` 4797 行数据                                                                  |
| `server/`   | 4729 + worker 4418 = **9147**     | 另 `static/` 8.9MB vendored pdf.js                                                                   |
| 根模块      | **5483**                          | cli 1642 / textutil 1149 / e2e 1037 / share 553 / align 451 / texlog 247 / redlines 203 / repair 198 |
| `xlat/`     | **4145**                          | 另 `terms/*.csv` 术语表种子数据                                                                      |
| `arxiv/`    | **3010**                          |                                                                                                      |
| `export/`   | **2489**                          |                                                                                                      |
| `validate/` | **2150**                          | 另 `ts/validator.js` L1 tree-sitter sidecar（package data 分发）                                     |

合计 98 个 py 文件 ≈ 51.8k 行。

### 1.2 依赖方向（`from texlate.*` import 语句统计）

层序自底向上：`textutil`/`texlog`/`redlines`/`share`/`align` 为叶子层（零 texlate 出边或仅互叶）；`latex`→textutil（11+3）、`arxiv`→textutil（3）、`validate`→redlines/texlog/textutil、`xlat`→latex(2)/textutil(2) 为领域层；`compile`→redlines/texlog/textutil/latex(fixloop.builtins:25-27)/xlat(llm_hook:38)；`export`→xlat(14)；`e2e`/`repair`/`cli`/`server(+worker)` 为编排顶层。无 src→bench、src→tests 反向边（实测零命中）。

环与倒挂只有一处真张力：**compile ↔ compile.fixloop 模块级 2-环**——`fixloop/logparse.py:20` 顶层 `from texlate.compile.engine import _ERR_FILELINE_RE`（私有名跨界），反向 `compile/engine.py:303-329,1242,1376` 与 `probe.py:118` 全部走函数内延迟 import 并自注「防循环」。环目前被 lazy import 中和，但它是结构性脆弱点：两包 `__init__` 都是 eager facade（`compile/__init__.py:17` 顶层拉 engine、`fixloop/__init__.py:10-36` 顶层拉 engine/cases/ctan/logparse），任何一次把延迟 import 提回模块顶层的顺手改动都会引爆真环。另 `server.worker`→`server` 父包 29 条 import（store/settings/upload/events/babeldoc 共享基建在父层）+ `server/app.py:77`→worker 包，父子互依是子包化的正常形态；`server/events.py`（EventBus）与 `server/worker/events.py`（_Events mixin）同名邻居多义是小噪音。

一个值得注意的反向依赖：`server.worker` → `texlate.e2e` 私有名 ×12（`translate.py:16-21` 拉 `_ENV_ENV_JUDGE/_KNOWN_ENVS/_env_flag/_env_judge_all`，`compile.py:27-35` 拉 `_ENV_NO_L2/L2_MAX_CHUNKS/_env_flag/_l2_localize/_resplice/_retranslate_hits/_split_cid/_TreeRun`），cli.py:49 拉 `_env_flag`、bench `stage_xlat.py:28` 拉 `_scan_tree`、tests 拉 `_L2Attr/_TreeRun/_chunk_spans`——e2e.py 事实已是两臂共享件库，但公共面仍是下划线私有名，编排器名字挂着库的实际职责。

## 2. Top6 之后仍存的结构债

### 2.1 >1500 行文件/巨类清单

| 文件                          | 行数 | 内部形态                                                                                                                                                                   |
| ----------------------------- | ---- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `latex/gullet.py`             | 2794 | `Gullet` 单类 859→2795 ≈ 1936 行（宏展开器本质多分支，内聚尚可）                                                                                                           |
| `compile/fixloop/builtins.py` | 2535 | 24+ TRANSFORM_FNS + REWRITE_FNS 平铺（审计时 2401，仍在胀）                                                                                                                |
| `compile/engine.py`           | 1835 | ≥4 关注点：log 模型+parse_log+taxonomy 适配（106-353）、依赖发现（354-544）、bwrap 沙箱机械（545-860，与 sandbox.py 同层分居）、Engine Protocol+ 双引擎+router（861-1835） |
| `latex/scanner.py`            | 1748 | v1 臂 `Scanner` 单类 156→1740 ≈ 1584 行；存废裁决未落地（v1 仍是 parsebench 对拍 oracle）                                                                                  |
| `cli.py`                      | 1642 | 10+ 命令 + share_app + tools_app 单文件（审计时 1526，在胀）                                                                                                               |
| `server/app.py`               | 1604 | `create_app` 工厂 473→1605 ≈ 1132 行、~24 路由闭包（审计裁决「端点面即规格表」有意平直，增长时再拆）                                                                       |
| `compile/fixloop/engine.py`   | 1513 | Ruleset 装载/校验 + Rule 视图 + LoopCtx + _cond_ok 分派 + 主循环 5 关注点                                                                                                  |

阈值下沿：normalize.py 1463（13 个编号 normalize 关注点）、segmenter/args.py 1371（拆包后最大件）、export/epub.py 1317。

### 2.2 重复实现残留（registry 没收编的部分）

- `\\begin{document}` 正则：`textutil.BEGIN_DOC_RX:65` 已是正源（sniff/locate/inject 消费），但 `api.py:30`、`flatten.py:35`、`segmenter/_common.py:478` 仍各持一份逐字 `_DOC_BEGIN_RX`。
- `\documentclass|documentstyle` 探测 6+ 站 3 方言：`(?![a-zA-Z])`（api.py:29、segmenter/_common.py:477、fixloop/engine.py:55）vs `(?![a-zA-Z@])`（locate.py:37、latex209.py:52、inject.py:278）vs `\b`/带参变体（inject.py:486,563、normalize.py:593,619、builtins.py:625 `_DOCCLASS_OPTS_RE`）——审计点名的 `@` 分歧只修了一半（inject 已带 @，fixloop/engine.py:55 仍无 @）。
- `\input` 族正则近逐字双份：probe.py:49-50 vs inject.py:298-299（inject 多 `_INPUT_NAME_RE:300`）。
- env-flag truthy 表两份：e2e._env_flag:106-111（`{"1","true","yes","on"}`）vs engine.py:539 `_TRUE_VALUES`。
- 扫描分流策略双实现：worker/parse.py:115-140 自有 rglob+`.rtx.tex`/`.code.tex`/`file_has_prose` 三级分流环，与 e2e._scan_tree:199 同策略不同码（_common.py:212 注释自认「同 e2e._scan_tree 三级分流」）；bench 侧三 runner 已收敛（commit 1c55602+407fc38 钉闸契约），产品侧这条没并。
- 清理残留：`compile/engine.py.orig`（1833 行重构快照，与现文件仅差 IGNORECASE 一处）在树内；仓根 `emulateapj.sty`/`eqsecnum.sty`/`ims/` 散落 vendored 件。

### 2.3 分层状态

fixloop→xlat（llm_hook:38,371 经 Protocol/延迟）、export→xlat（14）、worker→e2e（私有名）三条跨层边都在；真正需要修的是 §1.2 的 compile↔fixloop 环与 e2e 私有面。bench→tests 反向 import 仍在：`fixture_assert.py:25-27` sys.path 插入 tests/ 当断言库。

## 3. 增长热点预测

- **rules.yaml（4797 行）是全仓增速第一**：头部注释还写「36 条:2+2+32」（:500，已陈旧近 2 倍），实测 taxonomy 48 条 + rules 69 条（gate 2/precheck 2/loop 65）+ warnings 4；docs/08:251 一串「勘误/再勘误/三复核」（36→52→59→62→…）证明计数追不上增长。文件自声明「社区贡献入口 = 新增/修改本文件条目」——按 corpus 驱动节奏它只会更胀。自然拆分缝：taxonomy: 段（:173-508，两个消费装载点——Ruleset.load 与 engine._taxonomy 惰性各解析一遍）独立成 taxonomy.yaml 零风险；rules: 段（:509-4797 ≈ 4290 行）按 phase 或修复域（fonts/graphics/packages/bbl）切 rules.d/；warnings: 段已被 redlines.RULES_WARNINGS pin 住镜像，远期可反过来由 registry 生成。capabilities: 段（:69-91）是纯文档镜像、不参与 dispatch，宜先处置（见 §4）。
- **builtins.py（2535 行）随规则域增长**：TRANSFORM_FNS 每条新修复域落一簇函数（fonts 域 `_mc_*`/`_fb_*` ~1644-2200、graphics 域 `_graphic_*`/`eps_to_pdf`/`_run_convert` ~811-929、包 shim 域 `legacy_pkg_shim`/`shim_pkgs_in_use` ~929-1051,1556+）。自然缝 = 审计建议的 `builtins/` 包按域拆 + `_common.py` 收 LoopCtx helper；两个 registry dict（TRANSFORM_FNS/REWRITE_FNS）已是装配点，拆分是机械活。
- **segmenter/ 包（5683 行）**：args.py 1371 是 argspec policy 分派增长面（每类新 policy/族表遮蔽在此落 handler），pending.py 966 次之；mixin 缝已开好，文件内按 policy 族再分子模块即可。
- **argspec.json（16851 行）**：随宏/环境覆盖率单调胀的纯数据表；自然缝是按 CTAN 包分片或保持单表（一次装载的查表数据，胀到 MB 级再议）。
- **app.py create_app / cli.py**：随 API/命令面线性胀；app.py 的缝是 APIRouter 分域 + deps dataclass，cli.py 的缝是 share/doctor 子块切出（审计已点名）。
- **engine.py bwrap 段 + normalize.py 编号段**：按引擎/语料新坑持续回填的中速面。

## 4. 跨层一致性机制健康度

### 4.1 已收编（registry/单源/pin 覆盖良好）

`redlines.py:93-168` 六概念×四层（engine/rules 镜像/l2/judge）注册表 + `tests/test_redlines.py` 冻结发射名/pattern/序位/yaml 镜像——范式样板；`repair.py` 收 e2e/worker 修复臂五件；`textutil` 持 BEGIN_DOC_RX:65/PH_FUZZY_RX:81/_INPUTENC_RX:519 等正源；`store.py:150-153` 状态词表单源；worker/_common 持 PROGRESS:46/PIPELINE_VERSION:54/KIND_URL:79/_SENTINELS:106/_DB_TO_PIPE:340 单源；fixloop DSL 词表 `_WHEN_KEYS:316`/`_COND_KEYS:321`/`_ACTION_KINDS:302`/`_PHASES`/`_MODES` 白名单 load 期校验 fail-closed；PROMPT_VERSION 单源 xlat/prompts.py:24；argspec 分派有 test_argspec_dispatch + test_latex_argspec 双钉；_scan_tree 闸契约跨三 runner 有 test_bench_harness pin。

### 4.2 同源多处声明、未被 registry 收编

- §2.2 全部：documentclass 6 站 3 方言、_DOC_BEGIN_RX ×3、_INPUT_* ×2、env-flag ×2、scan 分流 ×2。
- **rules.yaml `capabilities:` 段 ↔ `Engine.caps` frozenset（engine.py:952/1429）零钉且形已分歧**：yaml 键集 {kpsewhich,tlmgr,updmap,shell_escape,bundle} vs 代码 frozenset {"kpsewhich","tlmgr","updmap","recorder"}/{"bundle"}——`recorder` 在 yaml 缺席、`shell_escape:partial` 在 caps 无对应。该段自称「审计文档」但无机制保证不漂。
- **ScanWarning kind 无注册表**：19 种字面 kind 散落 latex/* 模块发射点，docs/07 还写 13——warning 消费者无法分辨契约面（审计 C3 已记，未修）。
- **rules.yaml 头注计数、docs/08:251 计数、CLAUDE.md 头「36 规则」三处计数同漂**——属「生成即可消灭」的漂移类。
- worker/**init**.py ~30 名 `# noqa: F401 -- test monkeypatch 面` 再导出 facade——是刻意的测试缝但属脆弱约定（改名断 patch）。
- `share.py` share_key vs worker `cache_key_for`（_common.py:245）是文档化的有意独立（share.py:9-15），export/docx.py:80 与 epub.py:206 各自 `_PIPELINE_VERSION` 同理——这两条不算债。

## 5. 架构级演进建议（按还债收益排序）

### R1（收益最高）：拆 compile/engine.py 四关注点 + 掐断 fixloop↔engine 环边

把 `_ERR_FILELINE_RE`/`_NONERR_FILELINE_RE` 等 log 行原语下移 `texlog.py`（log 格式件本就住那），fixloop/logparse.py:20 改指叶子层后，`engine.py:303-329` 等五处 lazy import 可全部提回顶层、环消失；同期把 106-353 log 模型+parse_log+taxonomy 适配切 `compile/loginfo.py`、545-860 `_bwrap_*`/`_apply_sandbox`/`_kpathsea_*` 并入 `sandbox.py`（同关注点现分居两文件）、354-544 依赖发现并入 probe.py 或 deps.py。残余 ~900 行（Protocol+ 双引擎+router）可选再按引擎拆。风险：低 - 中——纯代码位移，行为有 judge/engine 测试矩阵钉；唯一行为面是 import 次序。工作量：约 0.5-1 天含验证。

### R2（收益高）：e2e.py 共享件扶正，消灭私有名跨包 import

worker/translate+compile/cli/bench/tests 现合计 import e2e 私有名 ≥15 个（§1.2 清单）。两条走法择一：(a) 把被消费的件搬正层——`_scan_tree`/env 表归 latex 邻层、`_l2_*`/`_resplice`/`_retranslate_hits`/`_TreeRun` 归 repair.py 或新 `treepipe.py`、`env_flag` 归 textutil（顺手灭 engine.py:539 双份）——e2e 只剩 mock/CLI 编排面；(b) 零位移版：被消费名去下划线转公开 + docstring 声明「e2e = 两臂共享管线件库」。建议 (a) 里 env_flag/扫描分流（顺手并掉 worker/parse.py:115-140 双实现）先落，其余按触碰节奏迁。风险：低；私有名改名面会触 tests/bench import 点（机械）。工作量：(a) 全量 ~0.5-1 天，(b) ~1 小时。

### R3（收益中、防整类漂移）：TeX 词法常量层 + 计数类文档生成化

新建 `latex/lexicon.py`（或并入 textutil）：DOCCLASS_RX 一处裁决 `@` 分歧（六站统一）、删 `_DOC_BEGIN_RX` ×3、`_INPUT_*` 三件套 probe/inject 共享、_DOCCLASS_OPTS_RE builtins/normalize 共享；ScanWarning 19 kind 建 WARNING_KINDS 注册表 + 测试 pin（docs/07:96 的 13 从此自动可见新旧）；rules.yaml capabilities 段二选一——加测试 pin `yaml caps ↔ Engine.caps` 或直接删段（现纯文档且已分歧）；rules.yaml 头注/CLAUDE.md/docs/08 三处规则计数改生成或删数。风险：极低。工作量：~0.5 天。收益是消灭已付过两次代价的漂移类（PH_FUZZY_RX、documentclass @）。

### 附：即刻可清的小事

`compile/engine.py.orig` 删除；仓根 emulateapj.sty/eqsecnum.sty/ims/ 归位或删；`fixture_assert.py:25-27` bench→tests 反向 import 翻正（断言函数进 bench/py 模块由测试 import）。rules.yaml 的 taxonomy/rules 文件级拆分建议等 ~100 规则再付（维持审计裁决），但 capabilities 段处置与计数生成化属 R3 现在就值。
