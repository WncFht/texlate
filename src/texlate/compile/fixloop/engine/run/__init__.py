r"""engine.run — ``_FixRun`` 主循环状态机 (C5 拆叶 + 二级拆叶)。

次级派发阈值 (``_SEC_PROBE_MAX``/``_SEC_CAND_MAX``) 常数面; ``_FixRun``
收 cell/ctx/loop 账的单格运行态——本叶持字段与主轮/次级相方法,
编译相 (``_compile``/``_round_compile``/``_resolve_tail``/``_aux_seeded``)
与尾段相 (``tail``/``_reverify``/``_salvage``/``_finalize`` 系) 拆作
``engine.run.comp``/``engine.run.tail`` 两 mixin 叶, ``_FixRun``
多重继承组装 (``segmenter`` god-class 拆分同形); ``fixloop`` 入口与
``_record_case``/``_classify_no_main`` 回引拆进 ``engine.run.fixloop``。
patch 注意: 方法体内名解析走属主叶命名空间 (seams.md §5)。
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from texlate.compile.fixloop.actions import _REJECT_PREFIX
from texlate.compile.fixloop.engine.aux import _sweep_bad_aux
from texlate.compile.fixloop.engine.disp import (
    _commit_reject,
    _gate_eval,
    _match_apply_landing,
    _rule_needs_pass,
    _warn_preempt,
)
from texlate.compile.fixloop.engine.proto import (
    _report_of,
    _res_died,
    _res_driver_fatal,
    _res_has_pdf,
)
from texlate.compile.fixloop.engine.run.comp import _RunComp
from texlate.compile.fixloop.engine.run.tail import _RunTail
from texlate.compile.logparse import ErrReport

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from texlate.compile.fixloop.engine.ctx import LoopCtx
    from texlate.compile.fixloop.engine.proto import CompResLike, Engine
    from texlate.compile.fixloop.ruleset import Rule, Ruleset

__all__ = [
    "_SEC_CAND_MAX",
    "_SEC_PROBE_MAX",
    "_FixRun",
]


#: 次级错误派发 (twinhead) 每格 best_effort 探针编译上限——xelatex
#: halt_on_error 单错 log 看不见孪生错，规则 miss 时跑一发 nonstop
#: 探针取全错误面 (与 salvage 同参，结果直接留给兜底复用，净零编译)。
_SEC_PROBE_MAX = 2
#: 单次 miss 最多尝试的次级候选数——dedupe 后保错误序截前 4。
_SEC_CAND_MAX = 4


@dataclass
class _FixRun(_RunComp, _RunTail):
    """fixloop 单格运行态——cell/ctx/loop 账一本持，各相方法共享。

    ``fixloop()`` 状态机的相切承载体：构造期字段 = 配置快照 (ruleset/
    引擎/阈值/回调), 运行期字段 = 跨相账簿 (floor 快照/sig streak/
    次级探针计数与复用槽/last_rep/B6 基线)。``_round`` 返 ``"break"``
    表本轮已定局 (verdict 写进 cell), ``None`` 表轮末正常结束;
    ``_secondary`` 的 flow 多一态 ``"continue"`` (warn-preempt 落件续轮)。
    方法按相拆叶——编译相/尾段相分别在 ``_RunComp``/``_RunTail`` mixin
    (同名文件 ``engine.run.comp``/``engine.run.tail``), 本类持字段
    与主轮/次级相; 经验调谐注释随块原样迁移——每处分支的实证依据不丢。
    """

    rs: Ruleset
    eng: Engine
    ctx: LoopCtx
    cell: dict[str, Any]
    compile_kw: dict[str, Any]
    max_rounds: int
    clean_err_max: int
    passes: int
    stuck_n: int
    should_cancel: Callable[[], bool] | None
    on_round: Callable[[dict[str, Any]], None] | None
    #: 不退化底板：入口态 PDF 快照路径 + 字节数 (Guard B baseline 分量)。
    floor_snap: Path | None = None
    floor_bytes: int = 0
    prev_sig: str = ""
    sig_n: int = 0
    last_rep: ErrReport | None = None
    sec_probes: int = 0  # 次级派发探针计数 (≤_SEC_PROBE_MAX/格)
    #: 上次探针时的 actions 计数——树无 apply 变化不重探 (重探=同 log 同候选)
    sec_probe_mark: int = -1
    #: 探针编译留给 salvage 兜底复用的槽——只在「探针同轮、无 apply、走向
    #: 裁决」时填入 (miss 块内探针→候选全灭→break 是原子序，天然新鲜)。
    salvage_res: CompResLike | None = None
    salvage_rep: ErrReport | None = None
    #: 末次迭代编译前的 actions 账顶 (None = loop 未跑)——B6 写后复验门
    #: 的基线：出口时账顶增长 = 末次编译后仍有 apply 落件。
    acts_mark: int | None = None
    rnd: int = 0
    #: 自动解析趟 once-per-cell 闸——pagerange 类永不解析标签格的
    #: rerun-hint 恒存，无闸会逐轮回环 (fp resolve-pass dedup)。
    resolve_done: bool = False

    def _floor_snapshot(self) -> None:
        """快照入口态 PDF。

        先于 precheck/loop 一切编辑：规则若把能出 pdf 的树打死，
        finalize 拷回入口产物兜底 (loop1 实证 partial→fail 真退化 4 格)。
        reject:* 不救。
        """
        ctx = self.ctx
        main_pdf = ctx.io.wdir / Path(cast("str", ctx.io.main_rel)).with_suffix(".pdf")
        if main_pdf.is_file() and main_pdf.stat().st_size > 0:
            snap = ctx.io.wdir / ".fixloop-entry.pdf"
            try:
                shutil.copy2(main_pdf, snap)
                self.floor_snap = snap
                self.floor_bytes = main_pdf.stat().st_size
            except OSError as e:  # 快照失败仅失底板，不阻塞修复
                ctx.ledger.advisories.append(f"floor snapshot: {e}")

    # ------------------------------------------------------------ 主轮循环

    def rounds(self) -> None:
        """主轮循环：每轮 aux-sweep→分类编译→终止判→派发落账; 穷尽 → ``max_rounds``。"""
        for rnd in range(1, self.max_rounds + 1):
            if self.should_cancel is not None and self.should_cancel():
                raise asyncio.CancelledError
            self.rnd = rnd
            if self._round() == "break":
                break
        else:
            self.cell["verdict"] = "max_rounds"

    def _round(self) -> str | None:
        """单轮：清毒件 → 分类编译 → entry → 终止判 → 派发 → 落账。

        返 ``"break"`` 本轮定出局 (verdict 已写 cell); ``None`` 轮末正常
        结束 (次级派发的 ``"continue"`` 在内层消化——续轮与轮末对
        ``rounds()`` 同义)。
        """
        ctx, cell, rnd = self.ctx, self.cell, self.rnd
        swept = _sweep_bad_aux(ctx.io.wdir)
        if swept:
            ctx.ledger.events.append(f"r{rnd} aux-sweep: {', '.join(swept)}")
        self.acts_mark = len(ctx.ledger.actions)
        res, rep, cat, pay, round_sec = self._round_compile()
        pdf = self._round_entry(res, rep, cat, pay, round_sec)
        if self._round_verdict(res, rep, cat, pay, pdf=pdf):
            return "break"
        sig = f"{cat}:{pay}"
        self.sig_n = self.sig_n + 1 if sig == self.prev_sig else 1
        self.prev_sig = sig
        # sig_n = 同签连续 streak——只记账不判负：stuck verdict 移到下方
        # 派发耗尽点结算 (streak≥stuck_n 且本轮无 apply), 同签后位规则
        # 不再被「第 N 轮先判 stuck」抢掉派发窗口。
        # —— loop 规则匹配 + 应用 ——
        rule, note = _match_apply_landing(self.rs, ctx, self.eng, cat, pay, rep)
        sec_via: str | None = None
        if rule is None:
            flow, rule, note, sec_via = self._secondary(rep, cat, pay, pdf=pdf)
            if flow == "break":
                return "break"
            if flow == "continue":
                return None
        rule = cast("Rule", rule)  # flow=None ⇒ _secondary 契约携 Rule (rule None 不返)
        if note.startswith(_REJECT_PREFIX):
            _commit_reject(cell, rule, note)
            return "break"
        if _rule_needs_pass(rule):  # yaml ``action.params.needs_pass`` 解析趟请求
            ctx.ledger.needs_pass = True
        action_entry: dict[str, Any] = {"round": rnd, "rule": rule.id, "detail": note}
        if sec_via is not None:
            action_entry["via"] = sec_via
        cell["actions"].append(action_entry)
        ctx.ledger.events.append(f"apply {rule.id}: {note}")
        return None

    def _append_round(  # noqa: PLR0913 -- entry 字段面即参数列 (三 site 同构共用)
        self,
        res: CompResLike,
        rep: ErrReport,
        *,
        rnd: int,
        cat: str | None,
        pay: str | None,
        log_truncated: bool,
        sec: float | None = None,
        marker: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """物化一条 rounds entry: 字段装配 → ``cell["rounds"]`` 落账 → ``on_round``。

        主轮/reverify/salvage 三 site 的 entry 骨架单源——``pdf_bytes`` 缺载
        时的 ``Path(pdf).stat()`` 兜底与 ``sec`` 旧名 (``res.sec``) 兼容读法
        都收在此 (旧三抄里 salvage 臂两处皆漂：stat 兜底缺 + ``sec`` legacy
        名丢)。``sec=None`` 时按 res 取秒 (reverify/salvage 单编译轮); 主轮
        传两轮累计 ``round_sec``。``marker`` = 轮次标记位
        (``{"reverify": True}``/``{"salvage": True}``), 落 ``round`` 键后。
        """
        cell = self.cell
        pdf = _res_has_pdf(res)
        pdf_bytes = getattr(res, "pdf_bytes", None)
        if pdf and pdf_bytes is None:
            pdf_attr = getattr(res, "pdf", None)
            try:
                pdf_bytes = Path(pdf_attr).stat().st_size if pdf_attr else 0
            except (OSError, TypeError):
                pdf_bytes = 0
        if sec is None:
            sec = float(getattr(res, "seconds", getattr(res, "sec", 0.0)))
        entry = {
            "round": rnd,
            **(marker or {}),
            "pdf": pdf,
            "pdf_bytes": int(pdf_bytes or 0),
            # 超时/被杀轮——死编译产出未证，汇总段 clean/acceptable 判据须查。
            "died": _res_died(res),
            # Guard A (adjudication #10) 判据值由调用方按 halt/best_effort
            # 口径给——best_effort (nonstopmode) 全程 log 不截，恒 False。
            "log_truncated": log_truncated,
            # 驱动 fatal 证据行（无则 None）——category 仍押 classify 的
            # "other" 面（pdf_asset_sanitize 等 ``when: category: other``
            # 规则靠它派发），本字段载精确归因 + salvage 定败排除闸。
            "driver_fatal": _res_driver_fatal(res),
            "n_errors": rep.n_bang,
            "category": cat,
            "payload": pay,
            "warnings": list(rep.warnings),
            # 系统源输入侧警告 (``<warn_id>@<file>``)——不驱 warn_* 但留
            # 归因证据供 census 对账 (loginfo warnings_sys 同形)。
            "warnings_sys": list(rep.warnings_sys),
            "line_no": rep.line_no,
            "file_stack": rep.file_stack,
            "sec": round(sec, 1),
        }
        cell["rounds"].append(entry)
        if self.on_round is not None:
            self.on_round(entry)
        return entry

    def _round_entry(
        self,
        res: CompResLike,
        rep: ErrReport,
        cat: str | None,
        pay: str | None,
        round_sec: float,
    ) -> bool:
        """物化本轮 rounds entry + events 出口 + 首轮 pdf 迟快照 → pdf。"""
        ctx, eng, rnd = self.ctx, self.eng, self.rnd
        # Guard A (adjudication #10): halt_on_error 编译 n_bang>0 ⇒ log
        # 截在首错——n_bang 是下界非测量值，证不了 errors≤clean_err_max。
        # 本轮两轮候选编 (pass-1/finalize) 均非 best_effort; 探针/salvage
        # 的 best_effort 轮不走本 entry。无 halt 面引擎 (tectonic/Mock)
        # getattr 落 False 不置位。
        entry = self._append_round(
            res,
            rep,
            rnd=rnd,
            cat=cat,
            pay=pay,
            log_truncated=bool(getattr(eng, "halt_on_error", False) and rep.n_bang > 0),
            sec=round_sec,
        )
        pdf = bool(entry["pdf"])
        ctx.ledger.events.append(
            f"r{rnd}: pdf={pdf} err={rep.n_bang} cat={cat} pay={pay} ({entry['sec']}s)"
        )
        if self.floor_snap is None and pdf:  # 入口无现存产物 → 快照首轮 pdf
            src = getattr(res, "pdf", None)
            if isinstance(src, Path):
                snap = ctx.io.wdir / ".fixloop-entry.pdf"
                try:
                    shutil.copy2(src, snap)
                    self.floor_snap = snap
                    self.floor_bytes = src.stat().st_size
                except OSError as e:
                    ctx.ledger.advisories.append(f"floor snapshot: {e}")
        return pdf

    def _round_verdict(
        self,
        res: CompResLike,
        rep: ErrReport,
        cat: str | None,
        pay: str | None,
        *,
        pdf: bool,
    ) -> bool:
        """终止判据 (原型 + docs/spec/compile.md §6.4) → True 表本轮定局。"""
        cell, rs, eng = self.cell, self.rs, self.eng
        if (
            pdf
            and rep.n_bang == 0
            and cat not in rs.taxonomy.warn_cats
            and not _res_died(res)  # 被杀/超时编译产 pdf 也不证 clean
        ):
            # 原型首门 `pdf and nerr==0 → clean`; v1.1 放行 warn_* 伪类别
            # 让 warning 驱动的修复轮有机会跑 (non_utf8_source)
            cell["verdict"] = "clean"
            return True
        if cat in (None, "clean"):
            cell["verdict"] = "clean" if pdf else "no_errors_no_pdf"
            return True
        v, route = _gate_eval(rs, self.ctx, eng, cat, pay, rep)
        if v:
            cell["verdict"] = v
            if route:
                cell["reject_route"] = route
            return True
        return False

    def _secondary(
        self,
        rep: ErrReport,
        cat: str | None,
        pay: str | None,
        *,
        pdf: bool,
    ) -> tuple[str | None, Rule | None, str, str | None]:
        """次级错误派发 (twinhead) + warn-preempt + stuck 结算。

        首错无规则可修时，同 log 后续错误行可能才载可修根因
        (1206.0291: syntax 首错遮蔽 option_clash 孪生，geometry_hoist
        永远够不到)。返回 ``(flow, rule, note, sec_via)``: flow
        ``"break"``/``"continue"`` 表主循环直退/续轮; ``None`` 表次级
        命中携 rule 回落共享 reject/action 尾段 (rule None 不返——
        miss 全灭必走 warn-preempt/stuck 结算)。
        """
        ctx, rs, eng, cell, rnd = self.ctx, self.rs, self.eng, self.cell, self.rnd
        # 候选源 ``rep.errs`` 全错误表 (n_bang≥2, tectonic
        # continue_on_errors 下免费); xelatex halt_on_error 单错 log
        # 无孪生——未产 pdf 且探针预算未尽时跑一发 best_effort 探针
        # 编译 (与 salvage 同参), 在其全错误面上取候选; 探针结果留给
        # 兜底 pass 复用，净零编译。
        probe_res: CompResLike | None = None
        probe_rep: ErrReport | None = None
        cand_rep = rep
        if (
            rep.n_bang < 2  # noqa: PLR2004 - 2=单错→多错阈; log 已有全错误面 → 免费候选，不烧探针
            and getattr(eng, "halt_on_error", False)
            and not pdf  # dirty-pdf miss 只给免费候选 (探针闸)
            and self.sec_probes < _SEC_PROBE_MAX
            and len(ctx.ledger.actions) != self.sec_probe_mark
        ):
            probe_res = self._compile(passes=1, best_effort=True)
            self.sec_probes += 1
            self.sec_probe_mark = len(ctx.ledger.actions)
            probe_rep = _report_of(probe_res, rs.warn_patterns, ctx.io.wdir)
            cand_rep = probe_rep
            ctx.ledger.events.append(f"r{rnd} secondary probe: err={probe_rep.n_bang}")
        rule: Rule | None = None
        note = ""
        sec_via: str | None = None
        n_sec = 0
        for c2, p2, eline, eblob in rs.taxonomy.err_candidates(cand_rep):
            if (c2, p2) == (cat, pay):
                continue  # 主错刚 miss 过，不再重扫
            if n_sec >= _SEC_CAND_MAX:
                break
            n_sec += 1
            # ctx.round 重指孪生 (when/ctx_suggests/llm_hook 均见此面),
            # dispatch rep 携孪生行位 (requester 锚/cases excerpt 用)。
            twin_rep = ErrReport(first=eline, ctx=eblob, raw=cand_rep.raw)
            ctx.round.point(c2, p2, twin_rep)
            rule, note = _match_apply_landing(rs, ctx, eng, c2, p2, twin_rep)
            if rule is not None:
                sec_via = f"secondary:{c2}"
                ctx.ledger.events.append(
                    f"r{rnd} secondary dispatch -> {c2}:{p2} ({rule.id})"
                )
                break
        if rule is not None:
            return None, rule, note, sec_via
        # 候选耗尽仍未命中——ctx.round 回指主错，走原裁决路径;
        # 探针结果入兜底槽 (同轮无 apply, 状态未变，复用安全)。
        ctx.round.point(cat, pay, rep)
        self.salvage_res, self.salvage_rep = probe_res, probe_rep
        # warn-preempt (missdisp #189): error-cat 轮把轮次烧完、裁决落
        # dirty/unfixable/stuck 前——残存 missing-char 码位若有族臂未见，
        # 补发一轮 warn_missing_char 派发再言败 (family_not_dispatched:
        # 60/77 覆盖格从未拿到 warn 轮)。派发送 cand_rep: 探针跑过时其
        # 全错误面才是族臂 apply 实读的盘上 .log。
        wrule, wnote = _warn_preempt(rs, ctx, eng, cand_rep)
        if wrule is not None:
            if wnote.startswith(_REJECT_PREFIX):
                _commit_reject(cell, wrule, wnote)
                return "break", None, "", None
            self._warn_preempt_hit(wrule, wnote, rnd)
            return "continue", None, "", None
        # stuck 结算点移到派发耗尽后：同签 streak ≥ stuck_sig_repeat 且
        # 本轮主 + 次级均无 apply → stuck。旧制在第 stuck_n 个同签轮派发前
        # 预判——产出轮 (apply 发生) 同样计入 sig_n, 会把只在第 N+1 轮才
        # 够得到的规则 (凭据门 if_phantom_protect 类) 永久抢死在窗口外
        # (1206.0701/1306.0364: r1/r2 各有 apply, r3 未派发即断)。新制下
        # 同签轮只有「本轮无产出」才结算 stuck——apply 轮次只续窗口，
        # 真耗尽格烧轮止于派发枯竭。
        cell["verdict"] = (
            "stuck"
            if self.sig_n >= self.stuck_n
            else f"unfixable:{cat}"
            if not pdf
            else "dirty_pdf"
        )
        return "break", None, "", None
