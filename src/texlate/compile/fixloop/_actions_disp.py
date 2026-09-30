"""actions._actions_disp — ``action.kind`` 分派 + 规则匹配 + 派发窗 (C5 拆叶)。

``_apply`` 七种 ``action.kind`` 分派 (``reject_route`` 产出
``_REJECT_PREFIX`` note 供主循环判读), ``_match_apply`` order 序
when+condition+mode 匹配 (原型 ``pick_and_apply``), 缺字族判据
``_is_misschar_rule``/``_mc_delta``, 与派发窗落件同步
``_apply_window``/``_landing_sync``/``_apply_landed``
(loop/gate/precheck 三相共用，C2 自 engine 归位; ``engine`` 门面回引
保 ``engine.X`` import 面)。
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

from texlate.compile.fixloop import builtins
from texlate.compile.fixloop._actions_cond import (
    _cond_ok,
    _cond_snap_reset,
    _substitute,
    _when_ok,
)
from texlate.compile.fixloop._actions_install import (
    _apply_install_file,
    _apply_scan_install,
)
from texlate.compile.fixloop._actions_rewrite import _compile_rewrites, _patch_files
from texlate.compile.fixloop.builtins.common import _advise, _fp_diff, _wdir_fingerprint

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator
    from pathlib import Path

    from texlate.compile.fixloop.engine import Engine, LoopCtx
    from texlate.compile.fixloop.ruleset import Rule, Ruleset
    from texlate.compile.logparse import ErrReport

_REJECT_PREFIX = "REJECT:"


def _apply(  # noqa: C901, PLR0911  # action.kind 分派表，每种一处
    rule: Rule, ctx: LoopCtx, eng: Engine, pay: str | None, rep: ErrReport
) -> tuple[bool, str]:
    """按 action.kind 分派执行一条规则 → (applied, note)。"""
    _cond_snap_reset(ctx)  # 任何动作尝试皆可改盘面——后续 _cond_ok 重建快照
    action = rule.action
    kind = action.get("kind")
    params = _substitute(action.get("params") or {}, pay, ctx)
    if kind == "scan_install":
        return _apply_scan_install(ctx, eng, params)
    if kind == "install_file":
        return _apply_install_file(ctx, eng, params, rep)
    if kind == "run_tool":
        rc, out, to = ctx.run_tool(
            list(params.get("argv") or []), int(params.get("timeout", 120))
        )
        ctx.events.append(
            f"run {' '.join(params.get('argv') or [])} -> rc={rc}{' TIMEOUT' if to else ''}"
        )
        return True, f"rc={rc}{' TIMEOUT' if to else ''} {out[-200:].strip()}"
    if kind == "regex_rewrite":
        subs = _compile_rewrites(params.get("rewrites") or [])
        n = _patch_files(ctx, params.get("exts") or (".tex", ".sty"), subs, rule.id)
        if n > 0:  # 0 命中不落 engine_flags——空转规则不该给后续编译注 flag
            for fl in params.get("engine_flags") or []:
                if fl not in ctx.engine_flags:
                    ctx.engine_flags.append(fl)
        return (n > 0), f"rewrite in {n} files"
    if kind == "builtin_transform":
        fn = builtins.TRANSFORM_FNS[action["function"]]
        return fn(ctx, eng, pay, params)
    if kind == "reject_route":
        route = params.get("route", "")
        reason = params.get("reason", "")
        return True, f"{_REJECT_PREFIX} route={route} {reason}".strip()
    if kind == "escalate_llm":
        if ctx.llm_hook is None:
            return False, "no llm hook; stub (spike L523-527 parity)"
        return ctx.llm_hook(ctx, rep)
    return False, f"unknown action kind {kind!r}"


# ════════════════════════════════════════════════════════════════
# 规则匹配 (原型 pick_and_apply + mode/condition/fallback)
# ════════════════════════════════════════════════════════════════


def _is_misschar_rule(rule: Rule) -> bool:
    """``when`` 覆盖 ``warn_missing_char`` = 缺字修复族成员判据。

    缺字族 (missing_char_fix/accent/cs_rebind/macro_glyph/caret_utf8/
    三类 font_fallback) 全臂 when 均含此类别; warn_utf8-only 的
    non_utf8_source 不在族内。
    """
    when = rule.when or {}
    return any(
        isinstance(c, dict) and c.get("category") == "warn_missing_char"
        for c in (when.get("any") or [when])
    )


def _mc_delta(rule: Rule, ctx: LoopCtx) -> bool:
    r"""缺字族 dedup 豁免: 本轮 missing-char 码位含该臂未消费的新码位。

    missdisp #189 (fired_late_surface): ``\\bibitem`` 细空格/.bbl 字形/
    cs_rebind 重音等后浪缺字在臂起火**之后**才浮出——``applied`` 键只
    记「此臂对此码位集消费过」, ``mc_cps - mc_seen[rid]`` 非空即放行
    再派发。增量空 → 照常 dedup (同码位集不重火, 终止性靠此)。
    """
    if not _is_misschar_rule(rule):
        return False
    return bool(ctx.mc_cps - ctx.mc_seen.get(rule.id, frozenset()))


def _match_apply(  # noqa: C901, PLR0912, PLR0913, PLR0915, PLR0917  # 原型 pick_and_apply 签名面
    rs: Ruleset,
    ctx: LoopCtx,
    eng: Engine,
    cat: str | None,
    pay: str | None,
    rep: ErrReport,
    only: Callable[[Rule], bool] | None = None,
) -> tuple[Rule | None, str]:
    """Order 序找第一条 when+condition 过、mode 可行且应用成功的规则。

    ``unsupported`` + ``fallback: escalate_llm`` 不就地烧 LLM——记下首个
    待 escalate 规则继续扫描，同 category 的廉价规则全耗尽后才调 hook
    (missing_pfb_updmap 原位评估会把后置的 font_sub_shim 饿死在 LLM 后面)。

    ``only`` 可选族过滤器 (warn-preempt 的缺字族专场): 非 None 时只评
    谓词为真的规则——``when: always`` 的域外规则不抢家族派发窗。
    """
    _cond_snap_reset(ctx)  # 派发窗入口整槽作废——窗间编译产物 (aux/log 落删) 不入快照
    pending_esc: tuple[Rule, str] | None = None
    for rule in rs.phase("loop"):
        if only is not None and not only(rule):
            continue
        key = f"{rule.id}:{pay}"
        if key in ctx.applied and not _mc_delta(rule, ctx):
            continue
        if not _when_ok(rule.when, cat, pay, ctx):
            continue
        spec = rule.engine_spec(ctx.engine_name)
        mode = spec.get("mode", "native")
        if mode == "skip" or (mode == "degrade" and spec.get("degrade") == "skip"):
            continue
        if mode == "unsupported":
            if spec.get("fallback") == "escalate_llm" and pending_esc is None:
                pending_esc = (rule, key)
            _advise(ctx, f"{rule.id} unsupported on {ctx.engine_name}")
            continue
        ok, why = _cond_ok(rule.condition, rule, ctx, eng, pay, rep)
        if not ok:
            ctx.events.append(f"rule {rule.id}: cond skip ({why})")
            d = f"{rule.id}: cond skip ({why})"
            if d not in ctx.declined:
                ctx.declined.append(d)
            continue
        try:
            applied, note = _apply(rule, ctx, eng, pay, rep)
        except Exception as e:  # noqa: BLE001  # 规则崩溃=放弃该条，试下一条 (原型口径)
            applied, note = False, f"rule crashed: {type(e).__name__}: {e}"
        if applied:
            ctx.applied.add(key)
            if _is_misschar_rule(rule):
                # 起火轮看见的码位集记消费账——后浪新码位不在账内，
                # _mc_delta 增量豁免据此放行再派发 (missdisp #189)。
                ctx.mc_seen.setdefault(rule.id, set()).update(ctx.mc_cps)
            return rule, note
        if note:
            ctx.events.append(f"rule {rule.id}: skip ({note})")
            d = f"{rule.id}: {note}"
            if d not in ctx.declined:
                ctx.declined.append(d)
        fb = spec.get("fallback")
        if fb == "advisory":
            _advise(ctx, f"{rule.id}: {note}")
    if pending_esc is not None and ctx.llm_hook is not None:
        rule, key = pending_esc
        applied, note = ctx.llm_hook(ctx, rep)
        _cond_snap_reset(ctx)  # hook 直写 (ctx.write 不过 _apply)——快照作废
        if applied:
            ctx.applied.add(key)
            return rule, f"escalated: {note}"
        if note:
            ctx.events.append(f"rule {rule.id}: escalate skip ({note})")
            d = f"{rule.id}: escalate skip ({note})"
            if d not in ctx.declined:
                ctx.declined.append(d)
    return None, ""


# ════════════════════════════════════════════════════════════════
# 派发窗落件同步 —— loop/gate/precheck 三相共用 (C2 自 engine 归位;
# ``engine`` 门面回引保 ``engine.X`` import 面)
# ════════════════════════════════════════════════════════════════


def _landing_sync(
    ctx: LoopCtx,
    before: dict[Path, tuple[int, int]],
    pre_applied: set[str],
) -> int:
    """动作落件同步：外部落件指纹 diff → ``_texts`` 失效 + 落件前烧键过期。

    规则动作可改写盘面 (``scan_install``/``install_file``/vendored 落件、
    ``run_tool``/docstrip 产物、builtin 直写)。``written`` 在派发窗开始
    时清空，窗内经 ``ctx.write`` 落账的写件即本窗自产编辑; ``before``
    基线后的变化件分两档：

      - **规则自改** —— ``written`` 在账的 ``ctx.write`` 改写/新建
        (regex_rewrite/站点前置/shim 新建件): 写件已在 ``_texts`` 同步，
        键面不动——派发链的自产编辑不该稀释 dedup (stucksem 实证：无
        差别过期会让先火规则非幂等重派，抢走凭据门后位规则的派发窗)。
      - **外部落件** —— 绕 ``ctx.write`` 的新件/改写/删除 (install/
        vendor/run_tool 裸写): 全 invalidate (覆盖写与 miss→None 毒化
        条目同 logcache 病族，下轮 ``ctx.read``/site-map 读新文), 并把
        ``pre_applied`` 基线前烧录的 ``{rule}:{pay}`` dedup 键整体过
        期——落件把新站点引进 fileset 后，同签轮应允许同规则重派
        (defcensus E-route 病族：mid-loop install 后 already_def 臂
        按旧烧键跳过，残签滞留)。基线后新烧键 (``applied - pre_applied``)
        保留——刚派发的规则不因自身落件立刻重派。

    返回外部落件数 (0 = 无外部落件，键面不动)。
    """
    after = _wdir_fingerprint(ctx.io.wdir)
    external = _fp_diff(before, after, exclude=ctx.io.written)
    for p in external:
        ctx.invalidate(p)
    if not external:
        return 0
    ctx.ledger.applied.intersection_update(ctx.ledger.applied - pre_applied)
    ctx.ledger.events.append(
        f"landing sync: {len(external)} external landing(s) — "
        "pre-landing dedup keys expired"
    )
    return len(external)


@contextlib.contextmanager
def _apply_window(ctx: LoopCtx) -> Iterator[None]:
    """派发窗：指纹基线 + applied 快照 + ``written`` 清零 → 退出 ``_landing_sync``。

    loop/gate/precheck 三相派发共用同一落件同步不变量——窗内经
    ``ctx.write`` 的写按自产编辑计账，窗外裸写按外部落件失效 +
    烧键过期 (口径见 ``_landing_sync``)。
    """
    before = _wdir_fingerprint(ctx.io.wdir)
    pre = set(ctx.ledger.applied)
    ctx.io.written.clear()  # 本窗自产写从零计账
    try:
        yield
    finally:
        _landing_sync(ctx, before, pre)


def _apply_landed(  # noqa: PLR0913  # 与 _apply/_match_apply 同签名面
    rule: Rule,
    ctx: LoopCtx,
    eng: Engine,
    pay: str | None,
    rep: ErrReport,
    *,
    label: str,
) -> tuple[bool, str]:
    """单规则落件派发：``_apply_window`` 内 guarded ``_apply``。

    crash note 统一 ``{label} crashed: <type>: <e>`` —— gate/precheck
    相逐条评估共用 (loop 相的逐条 crash 兜底在 ``_match_apply`` 内部)。
    """
    with _apply_window(ctx):
        try:
            applied, note = _apply(rule, ctx, eng, pay, rep)
        except Exception as e:  # noqa: BLE001
            applied, note = False, f"{label} crashed: {type(e).__name__}: {e}"
    return applied, note
