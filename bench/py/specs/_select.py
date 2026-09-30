"""``Spec(select=...)`` run 期收窄原语 + 标准管道（§3.4 selector knobs）。

``select(item, resolved_params) -> bool`` 是 plan-filter 通道：kernel
``_enumerate_cells`` 在 canon **之前**逐格调它——被排的格不付 registry
查价，``ids=`` 等 raw-id 窄化按作者拼写直接命中。各 spec 曾人手一份
``_select`` 拷贝（ids 双拼写 want 集 + layers/only/n/seed 门），本模块
是十几份拷贝差分后的单源。

原语（可脱离管道单用）：

- ``canon_res``  各 spec 的 ``_canon`` 同款——``idnorm.canon_id(str(raw))``
- ``idc_of``     canon 可解析取 idc，否则原样——item/needle 双侧归一
- ``csv_set``    ``'a, b ,c' -> {'a','b','c'}``（空/未给 → 空集）
- ``want_set``   ``ids=`` 逗列 → want 集：token 原样 + 可解析者的 canon idc
- ``seeded``     ``Random(seed).sample(pool, min(n, len))``——池序调用方定
                 （文件序/sorted-set 抽样语义不同，本函数不替池排序）

``select()`` 标准管道（多数 spec 原式即此序；除 decisive ids 外全是纯合取，
门槛先后不影响结果）：

    bypass 直放 → pre 前置门 → ids → layers → only → post → n/seed 抽样

- ``bypass(ctx)``   True → 直选（"永远进 plan"的驱动格一类）
- ``pre(ctx)``      False → 拒（spec 自有维度门：condition/engines/lane/
                    run/frames/judges 都挂这里）
- ``ids``           ``'gate'``（未中即拒、中了续查）| ``'decisive'``
                    （命中即选、bypass 后续门）| ``'off'``。``ids=`` 参数
                    非空才激活；want 集双侧 canon 归一由 ``canon`` 控
- ``item_canon``    item 侧 id 归一：``'canon'``=``idc_of``、
                    ``'safe'``=``idc_from_safe``（safe 拼写解码不验形）、
                    ``'off'``=raw 直比。``canon=False`` 时强取 ``'off'``
- ``layers``        None=不看 ``layers=``；否则作缺省 csv（``""``=空集
                    即不滤）。标量 membership 查 ``item["layer"]``；
                    ``layers_any=True`` 时查 ``item["layers"]``-or-
                    ``[item["layer"]]`` 集合交
- ``only``          ``'canon'``（needle canon 归一 ∈ idc）| ``'raw'``
                    （only 原样子串 ∈ raw）| ``'either'``（双拼宽容：
                    canon∈idc 或 only∈raw）| ``'off'``
- ``post(ctx)``     False → 拒（only 之后、n 之前的次门）
- ``sample(ctx)``   n/seed 抽样判定——``ctx.n>0`` 才调；池构造/湖态谓词
                    都是 spec 自有口径
"""

from __future__ import annotations

import functools
import random
from dataclasses import dataclass, field

from kernel import idnorm
from kernel.spec import SpecError


@functools.cache
def canon_res(raw) -> idnorm.CanonResult:
    """各 spec 的 ``_canon`` 同款——cache 过的 ``idnorm.canon_id(str(raw))``
    （select 逐格逐 token 调 canon，缓存口径同旧件）。"""
    return idnorm.canon_id(str(raw))


def idc_of(raw) -> str:
    """canon 可解析取 idc，否则原样返回——双拼写归一。"""
    r = canon_res(raw)
    return r.idc if r.ok and r.idc else str(raw)


def csv_set(v) -> set[str]:
    """逗列 → strip 后非空项集（None/空串 → 空集）。"""
    return {s.strip() for s in str(v or "").split(",") if s.strip()}


def want_set(ids_param) -> set[str]:
    """``ids=`` 逗列 → want 集：token 原样 + 可解析者的 canon idc（双拼写）。"""
    want = set()
    for tok in csv_set(ids_param):
        want.add(tok)
        r = canon_res(tok)
        if r.ok and r.idc:
            want.add(r.idc)
    return want


def seeded(pool, n: int, seed: int) -> set:
    """``Random(seed).sample(pool, min(n, len))``——池序由调用方定。"""
    pool = list(pool)
    return set(random.Random(seed).sample(pool, min(n, len(pool))))


@dataclass(frozen=True)
class Ctx:
    """一次 select 调用的解析上下文——``pre``/``post``/``bypass``/``sample``
    钩子的统一入参。

    raw     ``item["id"]`` 原样
    idc     item 侧归一 id（``item_canon`` 模式解析；``'off'`` 时同 raw）
    want    ``ids=`` want 集（未激活 = 空）
    needle  ``only=`` canon 归一针（未给 = ""）
    only_raw ``only=`` 去空白原样（未给 = ""）
    layers  ``layers=`` 有效集（未启用/解析空 = 空）
    n/seed  int(rp["n"] or 0) / int(rp["seed"] or seed_default)
    """

    item: dict
    rp: dict
    raw: str
    idc: str
    want: frozenset = field(default_factory=frozenset)
    needle: str = ""
    only_raw: str = ""
    layers: frozenset = field(default_factory=frozenset)
    n: int = 0
    seed: int = 0


def _item_idc(raw: str, item_canon: str) -> str:
    if item_canon == "canon":
        return idc_of(raw)
    if item_canon == "safe":
        return idnorm.idc_from_safe(raw)
    return raw


def select(
    item: dict,
    rp: dict,
    *,
    bypass=None,
    pre=None,
    ids: str = "off",
    canon: bool = True,
    item_canon: str = "canon",
    layers: str | None = None,
    layers_any: bool = False,
    only: str = "off",
    post=None,
    sample=None,
    seed_default: int = 0,
) -> bool:
    """标准 ``spec.select`` 管道——各 knob 语义见模块 docstring。"""
    if ids not in ("off", "gate", "decisive"):
        raise SpecError([f"select: ids mode {ids!r} not in off/gate/decisive"])
    if only not in ("off", "canon", "raw", "either"):
        raise SpecError([f"select: only mode {only!r} not in off/canon/raw/either"])
    if item_canon not in ("canon", "safe", "off"):
        raise SpecError([f"select: item_canon {item_canon!r} not in canon/safe/off"])
    if not canon:
        item_canon = "off"
    raw = str(item.get("id") or "")
    idc = _item_idc(raw, item_canon)
    ids_p = str(rp.get("ids") or "").strip()
    only_raw = str(rp.get("only") or "").strip()
    want = (
        frozenset(want_set(ids_p) if canon else csv_set(ids_p))
        if ids_p
        else frozenset()
    )
    lset = (
        frozenset(csv_set(rp.get("layers") or layers))
        if layers is not None
        else frozenset()
    )
    ctx = Ctx(
        item=item,
        rp=rp,
        raw=raw,
        idc=idc,
        want=want,
        needle=idc_of(only_raw) if only_raw else "",
        only_raw=only_raw,
        layers=lset,
        n=int(rp.get("n") or 0),
        seed=int(rp.get("seed") or seed_default),
    )
    if bypass is not None and bypass(ctx):
        return True
    if pre is not None and not pre(ctx):
        return False
    if ids_p and ids != "off":
        hit = raw in want or idc in want
        if ids == "decisive":
            return hit
        if not hit:
            return False
    if lset:
        if layers_any:
            vals = item.get("layers") or [item.get("layer")]
            if not set(vals) & lset:
                return False
        elif str(item.get("layer") or "") not in lset:
            return False
    if only_raw and only != "off":
        if only == "canon":
            if ctx.needle not in idc:
                return False
        elif only == "raw":
            if only_raw not in raw:
                return False
        elif ctx.needle not in idc and only_raw not in raw:
            return False
    if post is not None and not post(ctx):
        return False
    if ctx.n > 0 and sample is not None:
        return bool(sample(ctx))
    return True
