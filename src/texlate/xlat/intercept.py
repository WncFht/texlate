"""升格拦截网注册表（自 ``pipeline`` 出叶）：zh 毒译签名 → fault + 回退原文。

``_INTERCEPT_NETS`` 是唯一枚举面——``_interceptable`` bool 形（段级缓存
写入/命中否决）、``pipeline._ledger_intercepts`` 账本形、
``pipeline.retranslate_chunk`` 裸形三处消费点同迭代本表；新增一网只动
「本表一条目 + 同名 ``_intercept_<name>`` 包装函」。

monkeypatch 钉点面守恒：``_intercept_<name>`` 包装函经 pipeline 顶部
import 回挂其模块命名空间，``pipeline._net_apply_fn`` 以 ``globals()``
晚绑定取件——tests ``monkeypatch.setattr(pl, "_intercept_*")`` 的
补丁对账本形/裸形两消费点照常触达。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from texlate.textutil import (
    bare_cs_net,
    dangerous_cs_net,
    ph_in_cs_net,
    residual_en_net,
)

from . import placeholders

if TYPE_CHECKING:
    from collections import Counter
    from collections.abc import Callable

    from .pipeline import ChunkResult


def _leftover_ph_tokens(src: str, zh: str) -> list[str]:
    """``zh`` 中 ∉ ``src`` 占位符集合的 token（按出现序列，重复保留）。

    splice 按 ph_map 成员解析 ``[[X_n]]``：zh 侧 token 不在 src 集合 → 查无
    实体留字面（reconstruct ``dangling``）；在集合内则每处出现都正常展开——
    故取集合差而非多重集差，合法重复引用与 src 字面 ``[[..]]`` 回显不误伤。
    """
    src_set = set(placeholders.ANY_PH_RX.findall(src))
    return [t for t in placeholders.ANY_PH_RX.findall(zh) if t not in src_set]


def _intercept_guard(r: ChunkResult) -> bool:
    """升格拦截网共用守门——只扫 ok/partial（skipped/fault 的 translation 已是 source）。"""
    return r.status in ("ok", "partial")


def _intercept_apply(r: ChunkResult, *, warn: str, reason: str) -> None:
    """升格拦截网共用落形：fallback_orig 同形（fault + skipped + 回退原文）。

    ``attempts>0`` 才记 ``error_kind=validate``——缓存命中没发请求，
    不充当 auth 闸的非-auth 证据。warning 仍按族名落 ``<net>:N`` 供计量。
    """
    r.warnings.append(warn)
    r.status = "fault"
    r.translation = r.source
    r.skip_reason = reason
    if r.attempts > 0:
        r.error_kind = r.error_kind or "validate"


# ---------------------------------------------------------------- 升格拦截网注册表


@dataclass(frozen=True, slots=True)
class _InterceptNet[H]:
    """升格拦截网注册条目——``_INTERCEPT_NETS`` 是唯一枚举面。

    三处消费形共享同一张表，新增一网只动「本表一条目 + 同名
    ``_intercept_<name>`` 包装函」——包装函缺席 ``_net_apply_fn`` 取件
    即 KeyError 不静默漏网，条目缺席则包装函 ``_NET_BY_NAME`` 查无同炸。

    - ``name``：网 id——账本调用名 ``f"{name} intercept"``、warn 前缀、
      包装函名 ``_intercept_{name}`` 同一词根；
    - ``detect``：``(src, zh) → 命中载荷``（falsy=未中）——``_interceptable``
      缓存否决 bool 形直迭代本字段；
    - ``fmt``：``命中载荷 → (warn, reason)``——``_intercept_apply`` 两件簿记；
    - ``l0_rule``：镜像的 l0 规则 id——缓存命中/续跑装载旁路 ``validate_pair``
      时本网是该签名的唯一闸；成员集钉 ``l0.CACHE_VETO_RULES``。
    """

    name: str
    detect: Callable[[str, str], H]
    fmt: Callable[[H], tuple[str, str]]
    l0_rule: str


def _fmt_leftover_ph(hits: list[str]) -> tuple[str, str]:
    """``leftover_ph`` 载荷 → (warn, reason)：集合差 token 去重展 8 枚。"""
    shown = ", ".join(sorted(set(hits))[:8])
    return (
        f"leftover_ph:{len(hits)}",
        f"leftover placeholder(s) unresolvable in splice: {shown}",
    )


def _fmt_cs_bomb(name: str, verb: str, hits: Counter[str]) -> tuple[str, str]:
    """多重集载荷 → (warn ``{name}:{n}``, reason ``{verb} x{n}: {shown}``) 共用形。"""
    n = sum(hits.values())
    shown = ", ".join(sorted(hits)[:8])
    return f"{name}:{n}", f"{verb} x{n}: {shown}"


def _fmt_ph_in_cs(hits: Counter[str]) -> tuple[str, str]:
    """``ph_in_cs`` 载荷 → (warn, reason)。"""
    return _fmt_cs_bomb("ph_in_cs", "placeholder fused into cs name", hits)


def _fmt_bare_cs(hits: Counter[str]) -> tuple[str, str]:
    """``bare_cs`` 载荷 → (warn, reason)。"""
    return _fmt_cs_bomb("bare_cs", "bare cs injected", hits)


def _fmt_residual_en(hits: list[str]) -> tuple[str, str]:
    """``residual_en`` 载荷 → (warn, reason)：run 截 40 字符展 3 条。"""
    shown = ", ".join(run[:40] for run in hits[:3])
    return (
        f"residual_en:{len(hits)}",
        f"untranslated english run(s) in zh x{len(hits)}: {shown}",
    )


def _fmt_dangerous_cs(hits: Counter[str]) -> tuple[str, str]:
    """``dangerous_cs`` 载荷 → (warn, reason)。"""
    return _fmt_cs_bomb("dangerous_cs", "dangerous cs injected", hits)


#: 升格拦截网注册表（唯一枚举面）——``_interceptable`` bool 形、
#: ``_ledger_intercepts`` 账本形、``retranslate_chunk`` 裸形三处消费点
#: 同迭代本表，新增网不再三处各点名。
_INTERCEPT_NETS: tuple[_InterceptNet, ...] = (
    _InterceptNet(
        name="leftover_ph",
        detect=_leftover_ph_tokens,
        fmt=_fmt_leftover_ph,
        l0_rule="placeholder",
    ),
    _InterceptNet(
        name="ph_in_cs",
        detect=ph_in_cs_net,
        fmt=_fmt_ph_in_cs,
        l0_rule="ph_in_cs",
    ),
    _InterceptNet(
        name="bare_cs",
        detect=bare_cs_net,
        fmt=_fmt_bare_cs,
        l0_rule="bare_cs",
    ),
    _InterceptNet(
        name="residual_en",
        detect=residual_en_net,
        fmt=_fmt_residual_en,
        l0_rule="residual_en",
    ),
    _InterceptNet(
        name="dangerous_cs",
        detect=dangerous_cs_net,
        fmt=_fmt_dangerous_cs,
        l0_rule="dangerous_cs",
    ),
)

#: ``name → 条目`` 派生查表（唯一枚举面仍是 ``_INTERCEPT_NETS`` 元组）。
_NET_BY_NAME: dict[str, _InterceptNet] = {n.name: n for n in _INTERCEPT_NETS}


def _net_apply[H](net: _InterceptNet[H], r: ChunkResult) -> None:
    """升格拦截网统一执行体：守门 → detect → 命中落 ``_intercept_apply``。

    原各网 guard→detect→apply 同构序列的执行核——``_intercept_<name>``
    包装函经本件落地，注册表只携带 detect/fmt 元数据。
    """
    if not _intercept_guard(r):
        return
    hits = net.detect(r.source, r.translation)
    if not hits:
        return
    warn, reason = net.fmt(hits)
    _intercept_apply(r, warn=warn, reason=reason)


def _interceptable(src: str, zh: str) -> bool:
    """升格拦截网注册表的合并判定——``zh`` 命中任一网即会被 ``_collect`` 降 fault。

    ``_cache_store``/缓存命中路共用此口径：过不了拦截的译文既不入缓存、
    命中旧毒条目也清除重翻。迭代 ``_INTERCEPT_NETS`` 各 ``detect``——
    新增网自动并入否决面。
    """
    return any(net.detect(src, zh) for net in _INTERCEPT_NETS)


def _intercept_leftover_ph(r: ChunkResult) -> None:
    """``leftover_ph`` 升格拦截：zh 带 splice 不可解析 token → fault + 回退原文。

    B7 归因：模型幻觉 ``[[MATH_n]]`` 穿透 ladder/校验留字面，splice 后
    ``[[MATH_966]]`` 进文档是用户可见污染（sabotage 1012.5411 实测）——
    回退英文原文是更体面的降级。命中即落 fallback_orig 同形：不再 splice、
    续跑重试、落库 ``failed`` → 论文级 ``partial`` 而非静默 ok。
    """
    _net_apply(_NET_BY_NAME["leftover_ph"], r)


def _intercept_ph_in_cs(r: ChunkResult) -> None:
    r"""``ph_in_cs`` 升格拦截：zh 把占位符嵌进 cs 名中段 → fault + 回退原文。

    ``_intercept_leftover_ph`` 同构副层——续跑 state/段级缓存命中旁路
    validator，此层是拦 stale 脏译的唯一闸（l0 ``_check_ph_in_cs`` 的
    缓存旁路姊妹，判定口径 = ``textutil.ph_in_cs_net`` 逐字节一致）。
    splice ``expand`` 逐字节替换后 ``\\fo[[PH]]o`` → ``\\fo<payload>o``
    断名成未定义 cs 且载荷不可复原（scout-spliceguard 14/14 实证）。
    """
    _net_apply(_NET_BY_NAME["ph_in_cs"], r)


def _intercept_bare_cs(r: ChunkResult) -> None:
    r"""``bare_cs`` 升格拦截：zh 文本域新增裸 cs → fault + 回退原文。

    ``_intercept_ph_in_cs`` 同构副层——判定口径 = ``textutil.bare_cs_net``
    （与 l0 ``_check_bare_cs`` 逐字节一致），缓存/续跑旁路 validator
    时此层是唯一闸。两类编译炸弹：数学域外 ``MATH_CS`` 表名
    （``\alpha 发射体`` → ``Missing $``，realpostfix2 0905.4907 实证）
    与粘合 cs（``\itemOC``/``\csnamebibitemNoStop`` → undefined cs）。
    """
    _net_apply(_NET_BY_NAME["bare_cs"], r)


def _intercept_residual_en(r: ChunkResult) -> None:
    r"""``residual_en`` 升格拦截：zh 段内夹未翻译英文 run → fault + 回退原文。

    ``_intercept_bare_cs`` 同构副层——判定口径 = ``textutil.residual_en_net``
    （与 l0 ``_check_residual_en`` 逐字节一致）。seq-49/51 实证：行级修复
    把 audit 失败的行按 ``src_l`` 原文装回，装配 candidate 过 validator
    时 same_source 只拦整段回显、CJK 占比 warn 不闸——``recovered`` 落
    DB ``ok`` 静默出货。缓存命中/续跑旁路 validator 时本层是唯一闸。
    """
    _net_apply(_NET_BY_NAME["residual_en"], r)


def _intercept_dangerous_cs(r: ChunkResult) -> None:
    r"""``dangerous_cs`` 升格拦截：zh 新增 ``DANGEROUS_CS`` 表名 → fault + 回退原文。

    ``_intercept_bare_cs`` 同构副层——判定口径 = ``textutil.dangerous_cs_net``
    （与 l0 ``_check_dangerous_cs`` 逐字节一致），缓存/续跑旁路 validator
    时此层是唯一闸。面覆盖 ``bare_cs`` 未管的良形非数学危险 cs：
    ``\input{/etc/passwd}``/``\write18``（词法 ``write``+``18``）/
    ``\def``/``\catcode``/``\csname`` 逃逸族——数学域不豁免
    （``$\input$`` 照样执行）。
    """
    _net_apply(_NET_BY_NAME["dangerous_cs"], r)
