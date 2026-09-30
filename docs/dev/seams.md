# 测试补丁缝（monkeypatch seam）纪律

测试对内部实现的 patch 面是有意维护的接缝，不是随手可移的实现细节。本文件约定三类接缝的 patch 点位置、改动时的两侧义务，以及新增接缝的顺序。背景：重构把若干模块改成 PEP 562 惰性门面/分组上下文后，`builtins.X` 这类门面平名仍可读，但 `setattr` 只遮蔽门面 `globals()`、不改叶子内部互引——patch 错层即静默失效（测试假绿）。

## 1. 惰性门面：patch 叶子，不 patch 门面

`compile/fixloop/builtins/`（facade=`__init__.py`）、`compile/fixloop/__init__.py`、`textutil` 是 PEP 562 门面：平名经 `_LEAF_EXPORTS`/`_LAZY` 映射在 `__getattr__` 首访时 `importlib.import_module` 解析并缓存进 `globals()`。读 `facade.name` 总能拿到叶子对象，但叶子内部互引用的是叶子自己的模块命名空间——`monkeypatch.setattr(facade, "name", fake)` 只写进门面 `globals()`，叶子内部那条调用链仍走原实现。

规则：patch 点 = 绑定所有者模块。要替换 `builtins.graphics._run_convert`，patch `texlate.compile.fixloop.builtins.graphics._run_convert`；`fixloop.fixloop` 内部分支同理——patch `texlate.compile.fixloop.engine.X` 而非 `fixloop.X`。断言「函数被调用/被换」时 patch 调用方所在模块的那个名字（`from x import y` 的 patch 点是消费方命名空间的 `y`，这是 Python 通用规则，门面只是让它更不直观）。

新增导出三处同步：`_LEAF_EXPORTS` 值表、字面 `__all__`（ruff F401 re-export 判定要静态列表）、`TYPE_CHECKING` import 块（静态分析器面）。`TRANSFORM_FNS`/`REWRITE_FNS` 这类注册表键集变化时同步对应键表常量。

## 2. 注册表 dict：setitem，不整表替换

`builtins.TRANSFORM_FNS`、`builtins.REWRITE_FNS`、`builtins.csfix._CS_FIX_TABLE` 等是运行期构建的真 dict，dispatch 每轮按键取函数。测试用 `monkeypatch.setitem(registry, "rule_fn_name", fake)` 注入伪实现——这条消费面语义不能破：注册表必须保持可变 dict，不得换成 MappingProxy/frozenset 式只读面。`setattr` 整表换掉不影响已按名取出的引用，但查表发生在派发时点、无缓存别名，整表替换也安全——两种 patch 形皆可用，优先 setitem（只动一键，不牵全表）。

## 3. LoopCtx 平铺字段：facade 转写，patch 平名即达

`engine.LoopCtx` 字段分 io/deps/round/ledger 四组存储，旧平铺名经 `_CTX_FIELD_GROUP` + `__getattr__`/`__setattr__` 转发。`monkeypatch.setattr(ctx, "wdir", p)` 与 `ctx.wdir = p` 一样落到 `ctx.io.wdir`——平名 patch 依旧有效，测试不用改。组子对象（`ctx.io`、`ctx.ledger` 等）是真实属性，也可直 patch 组内字段。例外：facade 只兜 `_CTX_FIELD_GROUP` 收录的字段名——新增字段必须先进组映射，否则 `setattr` 直挂实例（silent divergence：读写走到两处）。

## 4. 改动时的两侧义务

实现侧：移动/改名/拆包函数前先 `grep -rn "monkeypatch.*<name>\|patch.*<name>" tests/` 盘点 patch 点；拆叶子的同时把受影响 patch 点改到叶子（同一个提交，facade 与叶子同步入库，否则中间态 patch 错层假绿）。私名转公开保持旧名可用期 = 零——直接改全部引用，不留 alias。

测试侧：写新 patch 时按「绑定所有者」定位——惰性门面下的名一律进叶子模块 patch；注册表一律 setitem；LoopCtx 平名字段照常 patch。怀疑 patch 没生效时先验证「拿到的是不是同一个模块对象」——`facade.name is leaf.name` 在首次解析后恒真，但 `facade.name = fake` 不反向传播。

## 5. 已登记接缝

- `texlate.compile.fixloop.builtins.graphics._run_convert` — 图形/PS 转换子进程缝（case/EPS/SVG 转换测试注入点）。
- `texlate.compile.fixloop.builtins.TRANSFORM_FNS` — `builtin_transform` 注册表，setitem 缝。
- `texlate.compile.fixloop.engine` 内 `_match_apply_landing`/`_gate_eval`/`_warn_preempt` 等模块级名 — `fixloop()`/`_FixRun` 各相直引模块名，patch engine 模块属性即可拦截（`_FixRun` 方法体内同样直引，无自引用别名）。
- `LoopCtx` 平铺字段全集 — `_CTX_FIELD_GROUP` 收录名。
- `xlat/pipeline.py` 对 `_intercept_*`/`AuthGate` 的 patch 点 —— 出叶到 `intercept.py`/`authgate.py` 后以 `from .intercept import _intercept_*` 保持名字在本模块命名空间，测试照旧 `monkeypatch.setattr(pl, "_intercept_bare_cs", ...)`/`pl.AuthGate.record`，patch 点 = 消费方命名空间（非叶子同名）。
