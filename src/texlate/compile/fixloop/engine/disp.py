r"""engine.disp — 主档定位 + gate/precheck/次级派发面 (C5 拆叶)。

reject 记账原语 (``_REJECT_ROUTE_RE``/``_note_route``/``_commit_reject``/
``_rule_needs_pass``), 主文件双档定位 ``find_main_tex``, loop 相派发
缝 ``_match_apply_landing``/``_gate_eval``/``_warn_family_due``/
``_warn_preempt``, precheck 相 ``_precheck_phase`` 与独立入口
``precheck_pass``, verdict→名单 ``_gate_fired_of``。actions 叶动作
原语集与 ``_mc_parse_log``/``_inject_find_main_tex``/``DOCCLASS_RX``/
``decode_tex`` 经本叶回引 (``engine.X`` 兼容面)。
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path
from typing import TYPE_CHECKING

from texlate.compile.fixloop.actions import (
    _REJECT_PREFIX,
    _apply,
    _apply_landed,
    _apply_scan_install,
    _apply_window,
    _cond_ok,
    _dep_stems,
    _is_misschar_rule,
    _landing_sync,
    _match_apply,
    _probe,
    _substitute,
    _when_ok,
)
from texlate.compile.fixloop.builtins.common import _mc_parse_log
from texlate.compile.fixloop.engine.wire import _setup_ctx, _wire_engine
from texlate.compile.inject import find_main_tex as _inject_find_main_tex
from texlate.compile.logparse import parse_log
from texlate.textutil import DOCCLASS_RX, decode_tex

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from texlate.compile.fixloop.engine.ctx import LoopCtx
    from texlate.compile.fixloop.engine.proto import Engine, RunFn
    from texlate.compile.fixloop.ruleset import Rule, Ruleset
    from texlate.compile.logparse import ErrReport

__all__ = [
    "DOCCLASS_RX",
    "_REJECT_PREFIX",
    "_REJECT_ROUTE_RE",
    "_apply",
    "_apply_landed",
    "_apply_scan_install",
    "_apply_window",
    "_commit_reject",
    "_cond_ok",
    "_dep_stems",
    "_gate_eval",
    "_gate_fired_of",
    "_inject_find_main_tex",
    "_is_misschar_rule",
    "_landing_sync",
    "_match_apply",
    "_match_apply_landing",
    "_mc_parse_log",
    "_note_route",
    "_precheck_phase",
    "_probe",
    "_rule_needs_pass",
    "_substitute",
    "_warn_family_due",
    "_warn_preempt",
    "_when_ok",
    "decode_tex",
    "find_main_tex",
    "precheck_pass",
]


#: REJECT note 里的 ``route=<name>`` 令牌——``reject_route``/route 语义型
#: builtin (plain_format_detect/biber_biblatex_skew_route) 同一拼写约定；
#: 提出后落 ``cell["reject_route"]`` 供跨引擎臂消费（repair.consume_engine_flags）。
_REJECT_ROUTE_RE = re.compile(r"\broute=(\S+)")


def _note_route(note: str) -> str | None:
    """REJECT note → 目标路由名；无 route 令牌 → None。"""
    m = _REJECT_ROUTE_RE.search(note)
    return m.group(1) if m else None


def _commit_reject(cell: dict[str, Any], rule: Rule, note: str) -> None:
    """REJECT 裁决落账：``reject:<rid>`` verdict + route 令牌 (有则)。

    主轮/gate/次级 warn 臂/post warn-preempt 各决策点的同一写点——
    route 令牌即取即落 ``cell["reject_route"]``, 供跨引擎臂消费。
    """
    cell["verdict"] = f"reject:{rule.id}"
    if r := _note_route(note):
        cell["reject_route"] = r


def _rule_needs_pass(rule: Rule) -> bool:
    """规则 yaml 解析趟请求：``action.params.needs_pass: true`` → True。

    ``builtin_transform`` 的 params 面不受 ``_ACTION_PARAM_KEYS`` 白名单
    约束 (ruleset.validate 未列该 kind)——yaml 作者对动了 aux/cite
    记录面的修复规标 ``needs_pass: true`` 即挂引擎能力; builtin 直写
    ``ctx.needs_pass`` 同义 (facade 转落 ``ctx.ledger.needs_pass``)。
    """
    action = rule.action or {}
    params = action.get("params") or {}
    return bool(params.get("needs_pass"))


def find_main_tex(proj: Path) -> Path | None:
    r"""主文件定位：先严格档后宽松档。

    严格档 = ``inject.find_main_tex``（注释遮盖 + 语种排序）；无命中退
    宽松档——``\documentclass|style`` 在即可（fixloop 的职责是修坏论文，
    ``\begin{document}`` 缺失正是要修的对象；原型口径保留）。
    """
    strict = _inject_find_main_tex(proj)
    if strict is not None:
        return strict
    cands = []
    for f in sorted(f for f in proj.rglob("*") if f.suffix.lower() == ".tex"):
        with contextlib.suppress(OSError):
            head = decode_tex(f.read_bytes())[:60000]
            if DOCCLASS_RX.search(head):
                has_body = "\\begin{document}" in head
                depth = len(f.relative_to(proj).parts)
                cands.append((depth, 0 if has_body else 1, str(f)))
    if not cands:
        return None
    cands.sort()
    return Path(cands[0][2])


def _match_apply_landing(  # noqa: PLR0913, PLR0917  # 与 _match_apply 同签名面
    rs: Ruleset,
    ctx: LoopCtx,
    eng: Engine,
    cat: str | None,
    pay: str | None,
    rep: ErrReport,
    only: Callable[[Rule], bool] | None = None,
) -> tuple[Rule | None, str]:
    """``_match_apply`` + 落件同步——loop 相两处派发点共用。"""
    with _apply_window(ctx):
        rule, note = _match_apply(rs, ctx, eng, cat, pay, rep, only=only)
    return rule, note


def _gate_eval(  # noqa: PLR0913, PLR0917  # 与 _match_apply 同签名面
    rs: Ruleset,
    ctx: LoopCtx,
    eng: Engine,
    cat: str | None,
    pay: str | None,
    rep: ErrReport,
) -> tuple[str | None, str | None]:
    """Gate phase 规则逐条评估; REJECT note → ``(reject:<rid>, route)``。

    route 令牌在持有 note 的决策点即取即返 (``_precheck_phase`` 同一返回
    通道)——不再经 ``ctx.round`` 过桥 (旧 ``reject_route`` 字段是
    verdict-only 返回值时代的影子通道，已删)。
    """
    for rule in rs.phase("gate"):
        key = f"{rule.id}:{pay}"
        if key in ctx.ledger.applied:  # 非 REJECT 型 gate 已应用过 → 不重发不重记账
            continue
        if not _when_ok(rule.when, cat, pay, ctx):
            continue
        spec = rule.engine_spec(ctx.deps.engine_name)
        if spec.get("mode") == "skip":
            continue
        ok, why = _cond_ok(rule.condition, rule, ctx, eng, pay)
        if not ok:
            ctx.ledger.events.append(f"gate {rule.id}: cond skip ({why})")
            continue
        applied, note = _apply_landed(rule, ctx, eng, pay, rep, label="gate")
        if applied and note.startswith(_REJECT_PREFIX):
            return f"reject:{rule.id}", _note_route(note)
        if applied:
            ctx.ledger.applied.add(key)
            ctx.ledger.actions.append({"round": -1, "rule": rule.id, "detail": note})
            if _rule_needs_pass(rule):  # gate 相规则同可请求解析趟
                ctx.ledger.needs_pass = True
    return None, None


def _warn_family_due(
    rs: Ruleset, ctx: LoopCtx, cat: str | None, pay: str | None
) -> bool:
    """接受裁决前的缺字族勤勉检：本轮残存 missing-char 码位有臂未见。

    「未见」双判缺一不可——``when`` 不匹配本轮 cat 的臂本轮根本没被
    评估 (error-cat 轮全族皆然，``invalid_in_math`` 轮只
    macro_glyph_fix 评估过); 残存码位落在臂 ``mc_seen`` 消费账外
    (never-fired ⇒ 账空 ⇒ 全集皆增量)。两条件同假的臂重扫同一
    rep 必同判，不算 due。``(cat, pay)`` 取调用方快照——派发窗内
    ``ctx.round`` 已被强指 ``warn_missing_char``, 原 cat 须外传入。
    """
    cps = ctx.round.mc_cps
    if not cps:
        return False
    for rule in rs.phase("loop"):
        if not _is_misschar_rule(rule):
            continue
        if _when_ok(rule.when, cat, pay, ctx):
            continue  # 本轮已在该 cat 下评估过此臂——同 rep 重扫是空转
        if cps - ctx.ledger.mc_seen.get(rule.id, frozenset()):
            return True
    return False


def _warn_preempt(
    rs: Ruleset, ctx: LoopCtx, eng: Engine, rep: ErrReport
) -> tuple[Rule | None, str]:
    """Warn 家族补发一轮派发 (error-cat 轮裁决点/loop 退出点两 site 共用)。

    ``ctx.round`` 暂指 ``warn_missing_char`` 让族臂 ``when`` 命中——与
    次级错误派发的 twin 重指同机制，返回后复元。``(None, "")`` =
    残存缺字各臂均见过 (或本无缺字), 直走原裁决; REJECT note 经
    ``note`` 原样冒泡由调用方落 ``reject:<rid>``。码位面 = 轮记
    ``mc_cps`` ∪ 派发 rep 实解——次级探针编译后盘上 .log 是探针全
    错误面，族臂 apply 读的是它，勤勉判据须同面 (``mc_seen`` 起火
    记账亦落此并集)。
    """
    eff = ctx.round.mc_cps | frozenset(_mc_parse_log(rep.raw or ""))
    if not eff:
        return None, ""
    cat, pay = ctx.round.err_cat, ctx.round.err_pay
    # ``pointed`` 走 point() 接缝重指——err_head 同写同复元 (旧分点手写
    # 留 stale head, 族臂 ctx_suggests 会读到重指前 rep 的 head)。
    with ctx.round.pointed("warn_missing_char", None, rep, mc_cps=eff):
        if not _warn_family_due(rs, ctx, cat, pay):
            return None, ""
        rule, note = _match_apply_landing(
            rs, ctx, eng, "warn_missing_char", None, rep, only=_is_misschar_rule
        )
    if rule is None:
        ctx.ledger.events.append(
            f"warn-preempt: {len(eff)} residual cps, no arm applied"
        )
    return rule, note


def _precheck_phase(
    rs: Ruleset, ctx: LoopCtx, eng: Engine
) -> tuple[str | None, str | None]:
    """Precheck 相逐规则评估 (第 0 招装包 + 静态路由)。

    全程不编译——规则面是 scan_install/builtin_transform 等增量件，
    对 resplice 安全 (改件不碰 .tex 源)。REJECT note →
    ``(reject:<rid>, route)``；跑完无拒绝 → ``(None, None)``。
    """
    dummy_rep = parse_log(None, rs.warn_patterns)
    for rule in rs.phase("precheck"):
        if not _when_ok(rule.when, None, None, ctx):
            continue
        spec = rule.engine_spec(ctx.deps.engine_name)
        mode = spec.get("mode")
        if mode in ("skip", "unsupported") or (
            mode == "degrade" and spec.get("degrade") == "skip"
        ):
            ctx.ledger.events.append(
                f"precheck {rule.id}: {mode} on {ctx.deps.engine_name}"
            )
            continue
        ok, why = _cond_ok(rule.condition, rule, ctx, eng, None)
        if not ok:
            ctx.ledger.events.append(f"precheck {rule.id}: cond skip ({why})")
            continue
        applied, note = _apply_landed(rule, ctx, eng, None, dummy_rep, label="precheck")
        ctx.ledger.actions.append(
            {"round": 0, "rule": rule.id, "detail": note, "applied": applied}
        )
        if applied and note.startswith(_REJECT_PREFIX):
            return f"reject:{rule.id}", _note_route(note)
        if applied and _rule_needs_pass(rule):  # precheck 规则同可请求解析趟
            ctx.ledger.needs_pass = True
    return None, None


def precheck_pass(  # noqa: PLR0913 -- 与 fixloop 同契约的注入面
    proj: Path | str,
    eng: Engine,
    *,
    ruleset: Ruleset | None = None,
    engine_name: str | None = None,
    main_rel: str | None = None,
    runner: RunFn | None = None,
) -> dict[str, Any]:
    """编译链前的静态预检——fixloop precheck 相的独立入口。

    与 ``fixloop()`` 内嵌预检同一 ``_precheck_phase``：装缺包/解嵌套
    tar/收割构建指令，不修 .tex 源，对 L2 resplice 安全。e2e/worker
    两臂在 L2 回灌前调它——缺件类失败在归因前就消掉 (algpseudocodex
    型 missing_file 不再进 L2 兜底面)。

    ``main_rel`` 缺省时 ``find_main_tex`` 宽松档推导；无主档置空串
    （预检的 source_contains/扫描原语只读工程树，不依赖主档存在）。
    """
    rs, engine_name, wdir, ctx = _setup_ctx(
        proj, eng, ruleset=ruleset, engine_name=engine_name, runner=runner
    )
    if main_rel is None:
        main = find_main_tex(wdir)
        main_rel = str(main.relative_to(wdir)) if main is not None else ""
    ctx.io.main_rel = main_rel
    _wire_engine(eng, rs, wdir, ctx)
    verdict, route = _precheck_phase(rs, ctx, eng)
    pre = {
        "actions": ctx.ledger.actions,
        "installed": ctx.ledger.installed,
        "engine_flags": [str(f) for f in ctx.ledger.engine_flags],
        "flags_dropped": ctx.ledger.flags_dropped,
        "advisories": ctx.ledger.advisories,
        "events": ctx.ledger.events,
        "verdict": verdict,
        "reject_route": route,
    }
    pre["gate_fired"] = _gate_fired_of(pre)
    return pre


def _gate_fired_of(cell: dict[str, Any]) -> list[str]:
    """``reject:<rid>`` verdict → 拒绝规则名单; 其余 verdict → ``[]``。"""
    v = str(cell.get("verdict") or "")
    return [v.split(":", 1)[1]] if v.startswith("reject:") else []
