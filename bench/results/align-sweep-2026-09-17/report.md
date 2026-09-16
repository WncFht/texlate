# align-sweep — src/texlate/align.py 残余审计+小修

> 2026-09-17。scope：align.py + test_align.py。52 测试绿、ruff 净，未 commit。

## 调用契约（先核实）

`build_alignment(en_pdf, zh_pdf)` 唯一产品调用方是 `server/worker.py:2948`（`_build_dual`，`asyncio.to_thread` 内）；**cli.py 实际不引用 align**。`extract_landmarks` 是 `__all__` 公开调试入口，产品侧无调用但 `test_inject_theorem_anchor.py` 在用——非死代码，保留。web 侧 `alignment.ts` 契约：`heights/pairs/regions` 全 optional，`kind:"pages"` 无 heights 合法。

## 修复（4 项，均在 align.py）

1. **`_order_key` 无 /Top 锚排序错误**（确凿 bug）：`yfrac=None` 默认 0.0 按页底排，但 `_pos` 输出 fraction 0.0=页顶——同页 fraction 序列非单调，污染前端插值；且与移植源 `bench/py/alignbench.py:144`（`else 1.0`）分歧。改 1.0=页顶。
2. **畸形 `/Top` 杀整侧**：`float(top)` 对 NullObject/文本/indirect 抛 TypeError/ValueError 向上传播 → 整侧 anchors 全丢。抽 `_dest_yfrac` helper：解析失败→None（按页顶锚，粒度对齐 `_dest_page`），并钳到 [0,1] + isfinite 守卫（越界/NaN yfrac 不再泄漏到 fraction）。
3. **畸形 mediabox 杀整侧**：`float(p.mediabox.height)` 单页崩→侧丢；且 `or 792.0` 拦不住 nan（truthy）。抽 `_page_height`：异常/nan/非正值→792 回退，页序不动。
4. **`_graphic_regions` 三处**：(a) `page.get("/Resources")` 不解继承——`/Resources` 是 PDF 可继承页属性，pypdf 自家 `_get_page_resources` 走 `get_inherited`，改同款；(b) `int(page.get("/Rotate",0))` 遇 indirect /Rotate 抛 TypeError→整页丢，改 `page.rotation`（pypdf ≥3.4 有，自动解 indirect）；(c) signature 窄捕获 `(PyPdfError, NotImplementedError)` 覆盖不了 `resources[x].get_object()` 悬空引用、非流对象 `.get` AttributeError、畸形 `/BBox` IndexError——整块 Do 处理并入 `except Exception`，单块畸形图只丢该图不拖整页。

## 测试（+5 条，tests/test_align.py 13→18）

- `test_no_top_anchor_sorts_as_page_top`：/Fit 整页锚与 FitH 锚同页，钉死新排序+fraction 非降（旧代码必挂）。
- `test_malformed_top_falls_back_to_page_top` + `test_mediabox_garbage_page_falls_back`：duck-type `_StubReader`/`_StubPage`——**writer 会把 /Top 强转 FloatObject、把 parent /Resources 拍平进页对象**（探测证实），畸形/继承形态只能 stub 或 reader 侧手术构造。
- `test_regions_inherited_resources`：读回后把页级 /Resources 挪到 `/Parent` 模拟继承形态，`get_inherited` 命中出 region（旧代码 []）。
- `test_regions_broken_art_sibling_survives`：同页 Do 指向非流 XObject，正常图 region 仍产出（旧代码整页 []）。

## 验证

- `uv run pytest tests/test_align.py tests/test_inject_theorem_anchor.py tests/test_worker_audit_fixes.py` → **52 绿**
- `ruff format --check` + `ruff check` 两文件 → **净**
- vulture 未装；人工数：无死代码（`fit`/`npages` 是 landmarks 视图的诊断字段，alignbench 同口径保留）。

## 观察（未改）

- `/MediaBox`/`/CropBox`/`/Rotate`/`/Contents` 继承：pypdf 自家读取属性也不解继承（仅 `_get_page_resources` 特例），LaTeX 产出物这些都直写页对象，保持一致不改。
- `cm` 算子参数非数值/`stream.operations` 崩→页粒度丢（调用方 broad except）——content stream 真坏到这步，页粒度合理。
- 跨锚点同 signature artwork 重叠区间：两个 figure 锚可各产出覆盖同一图形的 region，前端取首个命中，texglot 原语义。
- `dests[*]["fit"]`/`npages` 仅诊断用途无下游消费，属公开视图一部分，不删。

## 无关发现（别的 teammate 领地，不动）

`tests/test_fixloop_aux_eof.py` 收集期 ERROR：`texlate.compile.fixloop._yamlish` yaml 转义错（`sciii: "{\sc iii}"` 的 `\s`），疑似 fixloop 相关会话在飞改动，全量 `pytest tests/` 会被它卡在收集。
→ **leader 复核：交付时已不可复现（8 tests collected fine）——在飞方已自修。**
