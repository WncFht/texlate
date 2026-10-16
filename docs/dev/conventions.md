# 代码注释与命名规约

贡献者写注释、起新名、改旧名都先读这里。词汇登记表（冻结名/域词/撞名表）在 `../spec/glossary.md`——本文件管规则，那文件管名册。

## 1. 注释引用纪律

- **禁引 `tmp/` 路径作证据源**。`tmp/` 是 gitignored 临时区，清仓即断链——「见 `tmp/x/y.json`」式引用全是定时化石。持久证据指针用 `git show <sha>:<path>`（挂 commit）或已入库仓相对路径。
- **跨文件锚写「模块 + 符号名」**（`kernel.ledger.emit`、`Ctx.emit_case`），不写裸行号。`file:L###` 行号只在「当时取证」语境允许，且必须带 commit 锚（`foo.py@abc1234:L123`）——否则拆包即漂。
- 引用 spec 优先写文件与主题标题；使用数字节号时，移动或合并章节须同步修复全部引用，稳定文件名不保证节号稳定。
- 「当前/现行/现在」状态句带日期戳（`（2026-09 时点）`），不给读者猜时效。
- 战役/波次代号（`Wave-F`、`第N波`、`soak-N`）不进新注释——用日期或 run 名。史注（描述当日做过什么）保留原词无妨。

## 2. 命名纪律

- **新数据键 / epoch / run slug / 产物目录名一律日期戳**：`@YYYY-MM-DD`、`-YYYY-MM-DD` 后缀、`<date>/<slug>` run 形态。禁编号代号作新标识符。
- **版本语义用功能 slug**：名字自说明用途（`patchseams`/`in_env_args`/`armedId`），不靠代数后缀（`v5`/`l2`/`tier3` 承载语义即埋雷）。数字只在即协议号处合法（HTTP/2、LaTeX2e、Python 3.12 这类外部定名）。
- **同名新规**：跨包/跨域同名文件必须 (a) 两侧 docstring 互辨、(b) 登记 `spec/glossary.md` §3——2026-09 普查已存三缝组（`patchseams`/`worker/seams`/`_docseams`）与 `decls.py` 双件等实例。
- **域词不挪用**：`arm`/`格`/`波`/`缝`/`zone`/`tier`/`clean` 等已有约定义项的词（`glossary.md` §2）不另起新义；新语义起新名。
- **facade+ 叶一律收子包**：PEP-562 门面 `X.py` + `_X_*` 兄弟叶的平铺形态已全仓清零（2026-10-01）——形态为 `X/` 子包（门面 → `X/__init__.py`，叶 → `X/<stem>.py`）。新增/挪动叶时叶干名不得撞任一导出名：叶件 import 会把子模块绑上门面 `__dict__[stem]`，此后 `facade.<stem>` 恒 dict-hit 返回 module、`__getattr__` 永不触发——撞名叶取 `_` 前缀脱名（`cli/_main.py`、`lake/_evict.py`、`specs/*/_spec.py` 先例），导出面不变；各门面 `_export_drift` 已内置 stem∈exports 撞名闸。

## 3. 冻结面

改任何名前查 `glossary.md` §1：ledger/events 键、`payload` token（`sentry:` 等）、metrics 键、vault 拼写、数据目录名、`spec_hash`/`fp` 材料全部冻结——只能加读侧兼容别名。疑似落盘键先沿产出路径追到落盘点再动；测试断言到的键同样按冻结处理（断言跟着 wire 格式走）。

## 4. 注释写法基线

- docstring 写契约与 why：不变量、隐藏约束、绕过后果、跨件协作关系。不复述代码已自明的 what——好名字替代注释。
- 引用 wire 名（ledger 键/字段/token）用 `` `backtick` `` 包裹——表明是字面量而非比喻词。
- 退役系统名（`corpus_daily`/`daily_arxiv`/`errsweep`/`gwcap`）只许出现在退役注记语境；不得以现役口吻引用其路径/接口。
- `# noqa`/`# type: ignore` 豁免须同行注明理由（仓现行约定，`ruff select=ALL` 配套纪律）。
- 测试名/夹具名同属标识符面：自说明域语义（`test_dossier_selftest`），不带批次编号。

## 测试替换位置

测试对内部实现的 patch 面是有意维护的接缝，位置即契约。本文件约定三类接缝的 patch 点位置、改动时的两侧义务，以及新增接缝的顺序。背景：重构把若干模块改成 PEP 562 惰性门面/分组上下文后，`builtins.X` 这类门面平名仍可读，但 `setattr` 只遮蔽门面 `globals()`、不改叶子内部互引——patch 错层即静默失效（测试假绿）。

### 惰性门面：patch 叶子，不 patch 门面

`compile/fixloop/builtins/`（facade=`__init__.py`）、`compile/fixloop/__init__.py`、`textutil` 是 PEP 562 门面：平名经 `_LEAF_EXPORTS`/`_LAZY` 映射在 `__getattr__` 首访时 `importlib.import_module` 解析并缓存进 `globals()`。读 `facade.name` 总能拿到叶子对象，但叶子内部互引用的是叶子自己的模块命名空间——`monkeypatch.setattr(facade, "name", fake)` 只写进门面 `globals()`，叶子内部那条调用链仍走原实现。

规则：patch 点 = 绑定所有者模块。要替换 `builtins.graphics._run_convert`，patch `texlate.compile.fixloop.builtins.graphics._run_convert`；engine 已拆 `engine/` 子包——patch `texlate.compile.fixloop.engine.<叶>.X` 而非 `engine.X`（facade setattr 不反传叶内 `from` 绑定）。断言「函数被调用/被换」时 patch 调用方所在模块的那个名字（`from x import y` 的 patch 点是消费方命名空间的 `y`，这是 Python 通用规则，门面只是让它更不直观）。

新增导出三处同步：`_LEAF_EXPORTS` 值表、字面 `__all__`（ruff F401 re-export 判定要静态列表）、`TYPE_CHECKING` import 块（静态分析器面）。`TRANSFORM_FNS`/`REWRITE_FNS` 这类注册表键集变化时同步对应键表常量。

### 注册表 dict：setitem，不整表替换

`builtins.TRANSFORM_FNS`、`builtins.REWRITE_FNS`、`builtins.csfix._CS_FIX_TABLE` 等是运行期构建的真 dict，dispatch 每轮按键取函数。测试用 `monkeypatch.setitem(registry, "rule_fn_name", fake)` 注入伪实现——这条消费面语义不能破：注册表必须保持可变 dict，不得换成 MappingProxy/frozenset 式只读面。`setattr` 整表换掉不影响已按名取出的引用，但查表发生在派发时点、无缓存别名，整表替换也安全——两种 patch 形皆可用，优先 setitem（只动一键，不牵全表）。

### LoopCtx 平铺字段：facade 转写，patch 平名即达

`engine.LoopCtx` 字段分 io/deps/round/ledger 四组存储，旧平铺名经 `_CTX_FIELD_GROUP` + `__getattr__`/`__setattr__` 转发。`monkeypatch.setattr(ctx, "wdir", p)` 与 `ctx.wdir = p` 一样落到 `ctx.io.wdir`——平名 patch 依旧有效，测试不用改。组子对象（`ctx.io`、`ctx.ledger` 等）是真实属性，也可直 patch 组内字段。例外：facade 只兜 `_CTX_FIELD_GROUP` 收录的字段名——新增字段必须先进组映射，否则 `setattr` 直挂实例（silent divergence：读写走到两处）。

### 改动时的两侧义务

实现侧：移动/改名/拆包函数前先 `rg "monkeypatch.*<name>|patch.*<name>" tests/` 盘点 patch 点；拆叶子的同时把受影响 patch 点改到叶子（同一个提交，facade 与叶子同步入库，否则中间态 patch 错层假绿）。私名转公开保持旧名可用期 = 零——直接改全部引用，不留 alias。

测试侧：写新 patch 时按「绑定所有者」定位——惰性门面下的名一律进叶子模块 patch；注册表一律 setitem；LoopCtx 平名字段照常 patch。怀疑 patch 没生效时先验证「拿到的是不是同一个模块对象」——`facade.name is leaf.name` 在首次解析后恒真，但 `facade.name = fake` 不反向传播。

### 已登记接缝

- `texlate.compile.fixloop.builtins.graphics._run_convert` — 图形/PS 转换子进程缝（case/EPS/SVG 转换测试注入点）。
- `texlate.compile.fixloop.builtins.TRANSFORM_FNS` — `builtin_transform` 注册表，setitem 缝。
- `texlate.compile.fixloop.engine.run` 内 `_match_apply_landing`/`_gate_eval`/`_warn_preempt` — 实体在 `engine/disp.py`，`_FixRun`（`engine/run/__init__.py`）经 `from engine.disp import` 绑定进自己命名空间，patch 点 = 消费方 `engine.run.<name>`（patch 门面 `engine.X` 或属主 `engine.disp.X` 都拦不到 `_FixRun` 内调用）。`engine/run/` 二级拆叶后 `_warn_preempt` 劈成两消费点：轮内 `_secondary` 的调用仍走 `engine.run._warn_preempt`，退出点 `_post_warn_preempt` 的调用走 `engine.run.tail._warn_preempt`——patch 哪个拦哪段。
- `LoopCtx` 平铺字段全集 — `_CTX_FIELD_GROUP` 收录名。
- `xlat/pipeline/` 对 `_intercept_*`/`AuthGate` 的 patch 点 —— `_intercept_*` 包装函与注册表实体在 `xlat/intercept.py`/`xlat/authgate.py`，门面 `pipeline/__init__.py` 经 `from texlate.xlat.intercept import _intercept_*` eager 回绑进本包 globals；账本/裸形两消费点（`pipeline/ledger.py::_ledger_intercepts`、`pipeline/single.py::retranslate_chunk`）经驻留门面的 `_net_apply_fn` 以 `globals()` 晚绑定取件——`setattr(pl, "_intercept_bare_cs", ...)`/`pl.AuthGate.record` 照旧触达真调用。新增一网只动 `_INTERCEPT_NETS` 条目 + intercept.py 同名包装函。
