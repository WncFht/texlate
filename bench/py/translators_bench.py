#!/usr/bin/env python3
r"""translators_bench.py — stagerun ``xlat --arm`` 的 translator 适配层。

臂名 → translator 工厂（``make_translator``）+ 破坏台账面（``.ledger`` /
``.finalize(results)``）。Sabotage/Perturb 的 **注入实现继承自**
``e2e_mock_bench``（Mode B/C 扰动逻辑的唯一事实源——子类只叠台账面，
逐字节一致由构造保证而非拷贝；e2e_mock 自身的 ``pipe_mode_condition``
仍用原类，两不相扰）。

接线契约（stagerun 与回归测试共用）：

- translator 协议 = ``texlate.xlat.pipeline.Translator``：
  ``async translate(*, system, user, temperature, max_tokens,
  response_format=None) -> str``。
- 工厂：``make_translator(arm, **kw)``，arm ∈ ``{mock, sabotage-b,
  sabotage-c, perturb}``（``perturb`` 是 ``sabotage-c`` 别名——Mode C
  位置扰动）。``kw`` 透传底层 ctor（全线 MockTranslator 血统，如
  ``zh=`` 换固定译文串）。``real`` 臂不在此表：GatewayTranslator 要
  ChatClient 生命周期，由 stagerun 现场装配。
- 台账：sabotage/perturb 实例带 ``.ledger`` dict 与 ``.events`` 明细
  list（``ledger["events"]`` 即同一 list 对象，translate 期间逐次
  append ``{seg, kind, detail}`` / ``{seg, moved}``）。pipeline 跑完后
  调 ``.finalize(results)`` 做逐块归因（``e2e_mock_bench._seg_of`` 同
  口径：段可能是 encoded 全段/行切片/原文），就地填计数器并返回
  ``ledger``——stagerun 落 ``rec["metrics"]["sabotage"]``。幂等：
  重复 finalize 先清零重数。
- mock 臂返回裸 ``pipeline.MockTranslator``（无台账面）；
  ``hasattr(tr, "finalize")`` / ``getattr(tr, "finalize", None)`` 是
  探测点（stagerun ``_SemTranslator`` 经 ``__getattr__`` 透传）。

ledger schema（``sabotaged`` = 命中事件的块数；``moved`` = C 模式挪位总数）::

    events    list[dict]  注入事件明细（与 .events 同对象）
    n_events  int         len(events)，finalize 时刷新
    sabotaged moved       int
    sabotage-b 另含: caught / recovered / escaped / escaped_ids
    sabotage-c·perturb 另含: spliced / dropped

``uv run python bench/py/translators_bench.py`` 自检：60 段合成 tex 走
parse → XlatPipeline(sabotage-b) → finalize，断言台账记到注入事件
（模块级 import texlate.xlat.pipeline → httpx，需 uv venv）。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # bench/py 同目录 import

import e2e_mock_bench as _emb  # Mode B/C 注入实现唯一事实源

from texlate.latex.placeholder import PH_RX
from texlate.xlat.pipeline import ChunkResult, MockTranslator, Translator


def _finalize(ledger: dict, results: list[ChunkResult], mode: str) -> dict:
    """逐块归因填计数器——e2e_mock ``pipe_mode_condition`` 台账同构，幂等。"""
    src_ph = lambda s: sorted(PH_RX.findall(s))  # noqa: E731
    events = ledger["events"]
    ledger["n_events"] = len(events)
    ledger["sabotaged"] = 0
    ledger["moved"] = 0
    if mode == "B":
        ledger.update(caught=0, recovered=0, escaped=0, escaped_ids=[])
    else:
        ledger.update(spliced=0, dropped=0)
    for r in results:
        evs = [e for e in events if _emb._seg_of(r.source, e["seg"])]
        if not evs:
            continue
        ledger["sabotaged"] += 1
        ledger["moved"] += sum(e.get("moved", 0) for e in evs)
        if mode == "B":
            if r.status != "ok":
                ledger["caught"] += 1  # fault/skipped → 原文回退
            elif src_ph(r.translation) != src_ph(r.source):
                ledger["escaped"] += 1  # 校验放行且译文带破坏残留——真逃逸
                ledger["escaped_ids"].append(r.chunk_id)
            else:
                ledger["recovered"] += 1
        elif r.status == "ok":
            ledger["spliced"] += 1  # 挪位译文进了文档 → 编译判存活
        else:
            ledger["dropped"] += 1
    return ledger


class _Ledgered:
    """台账 mixin：``.ledger`` dict + ``.finalize(results)``；``_MODE`` 子类给 B/C。"""

    _MODE = ""

    def _init_ledger(self) -> None:
        # events 键直接引用 self.events——注入侧 append 自动入账
        self.ledger: dict = {
            "events": self.events,
            "n_events": 0,
            "sabotaged": 0,
            "moved": 0,
        }

    def finalize(self, results: list[ChunkResult]) -> dict:
        """pipeline 结果 → 结局计数器（caught/recovered/escaped 或 spliced/dropped）。"""
        return _finalize(self.ledger, results, self._MODE)


class SabotageTranslator(_Ledgered, _emb.SabotageTranslator):
    """Mode B 幻觉破坏臂（丢/造占位符）+ 台账。"""

    _MODE = "B"

    def __init__(self, **kw: object) -> None:
        super().__init__(**kw)
        self._init_ledger()


class PerturbTranslator(_Ledgered, _emb.PerturbTranslator):
    """Mode C 占位符挪位臂（multiset 保持 → 过 L0 后 splice 错位）+ 台账。"""

    _MODE = "C"

    def __init__(self, **kw: object) -> None:
        super().__init__(**kw)
        self._init_ledger()


#: arm → translator 类。``perturb`` = ``sabotage-c`` 别名（Mode C 位扰）。
_ARMS: dict[str, type] = {
    "mock": MockTranslator,
    "sabotage-b": SabotageTranslator,
    "sabotage-c": PerturbTranslator,
    "perturb": PerturbTranslator,
}


def make_translator(arm: str, **kw: object) -> Translator:
    """stagerun ``xlat --arm`` 插件点：臂名 → translator 实例。

    ``kw`` 透传底层 ctor（``zh=`` 等）。``real`` 需 ChatClient 生命周期，
    不在此表——stagerun 自装 GatewayTranslator。
    """
    try:
        cls = _ARMS[arm]
    except KeyError:
        msg = (
            f"unknown xlat arm {arm!r} — expect one of {sorted(_ARMS)} "
            "(real 由 stagerun 经 ChatClient 装配)"
        )
        raise ValueError(msg) from None
    return cls(**kw)


def _selfcheck() -> None:
    """冒烟：合成 60 段 tex → parse → XlatPipeline(sabotage-b) → finalize 台账断言。"""
    import asyncio
    import tempfile

    from texlate.latex.api import parse_file
    from texlate.validate.l0 import validate_pair
    from texlate.xlat.pipeline import XlatPipeline, chunk_to_in

    # 破坏决策 = f(段内容哈希) 确定性——60 段 ~30% 命中，无随机源
    paras = "\n\n".join(
        f"Sabotage smoke paragraph {i} carries $x_{i}$ inline math." for i in range(60)
    )
    tex = (
        "\\documentclass{article}\n\\begin{document}\n" + paras + "\n\\end{document}\n"
    )
    with tempfile.TemporaryDirectory() as td:
        f = Path(td) / "main.tex"
        f.write_text(tex, encoding="utf-8")
        res = parse_file(f, flatten=False)
        chunks = [
            chunk_to_in(c, chunk_id=str(c.id), ph_map=res.ph_map) for c in res.chunks
        ]
        tr = make_translator("sabotage-b")
        pipe = XlatPipeline(tr, validator=lambda s, z: validate_pair(s, z).feedback())
        results = asyncio.run(pipe.run(chunks))
        ledger = tr.finalize(results)
    head = {k: v for k, v in ledger.items() if k != "events"}
    print(f"chunks={len(chunks)} ledger={head}")
    print(f"first events: {ledger['events'][:3]}")
    assert ledger["n_events"] > 0, "no sabotage events injected"
    assert ledger["n_events"] == len(tr.events)
    assert ledger["sabotaged"] > 0
    assert ledger["escaped"] == 0, "Mode B 逃逸——校验链洞"
    # C 臂同面自检（挪位天然过 L0：spliced+dropped == sabotaged）
    tr_c = make_translator("perturb")
    pipe_c = XlatPipeline(tr_c, validator=lambda s, z: validate_pair(s, z).feedback())
    results_c = asyncio.run(pipe_c.run(chunks))
    ledger_c = tr_c.finalize(results_c)
    print(f"perturb ledger={ {k: v for k, v in ledger_c.items() if k != 'events'} }")
    assert ledger_c["spliced"] + ledger_c["dropped"] == ledger_c["sabotaged"]
    print("selfcheck ok")


if __name__ == "__main__":
    _selfcheck()
