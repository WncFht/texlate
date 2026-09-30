r"""engine._engine_run — ``_FixRun`` 主循环状态机 + ``fixloop`` 入口 (C5 拆叶)。

次级派发阈值 (``_SEC_PROBE_MAX``/``_SEC_CAND_MAX``) 与出货前解析趟判据
``_UNRESOLVED_MARKS_RX`` 常数面; ``_FixRun`` 收 cell/ctx/loop 账的
单格运行态 (主轮/次级/尾段四相方法); ``fixloop`` = 装配面 + 主档解析
+ ``_FixRun`` 驱相机; ``_record_case`` cases 沉淀缝。
``inject.classify_no_main`` 经本叶回引 (``engine.X`` 兼容面)。
"""

from __future__ import annotations

import asyncio
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from texlate.compile.fixloop._engine_aux import _VOLATILE_EXTS, _sweep_bad_aux
from texlate.compile.fixloop._engine_disp import (
    _commit_reject,
    _gate_eval,
    _gate_fired_of,
    _match_apply_landing,
    _precheck_phase,
    _rule_needs_pass,
    _warn_preempt,
    find_main_tex,
)
from texlate.compile.fixloop._engine_proto import (
    _note_dropped_flags,
    _report_of,
    _res_died,
    _res_driver_fatal,
    _res_has_pdf,
    _round_cat,
)
from texlate.compile.fixloop._engine_wire import _setup_ctx, _wire_engine
from texlate.compile.fixloop.actions import _REJECT_PREFIX
from texlate.compile.fixloop.builtins.common import _mc_parse_log
from texlate.compile.inject import classify_no_main as _classify_no_main
from texlate.compile.logparse import ErrReport

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Any

    from texlate.compile.fixloop._engine_ctx import LoopCtx
    from texlate.compile.fixloop._engine_proto import (
        CompResLike,
        Engine,
        LlmHook,
        RunFn,
    )
    from texlate.compile.fixloop.cases import CaseSink
    from texlate.compile.fixloop.ruleset import Rule, Ruleset

__all__ = [
    "_SEC_CAND_MAX",
    "_SEC_PROBE_MAX",
    "_UNRESOLVED_MARKS_RX",
    "_FixRun",
    "_classify_no_main",
    "_record_case",
    "fixloop",
]


#: 次级错误派发 (twinhead) 每格 best_effort 探针编译上限——xelatex
#: halt_on_error 单错 log 看不见孪生错, 规则 miss 时跑一发 nonstop
#: 探针取全错误面 (与 salvage 同参, 结果直接留给兜底复用, 净零编译)。
_SEC_PROBE_MAX = 2
#: 单次 miss 最多尝试的次级候选数——dedupe 后保错误序截前 4。
_SEC_CAND_MAX = 4


#: 出货前解析趟判据——编译 log 里仍存活的 rerun/undefined-ref/cite 请
#: 求面。xelatex ``_RERUN_HINT_RX`` 的超集: 加 ``(citation|reference)..
#: undefined`` (0806.3788 型 Rerun 尾标被 bib brace 错吞后 citation
#: undefined 是唯一存活签名) 与 ``Please (re)run`` (biber/bibtex 请求行)。
_UNRESOLVED_MARKS_RX = re.compile(
    r"rerun to get|label\(s\) may have changed|there were undefined|"
    r"(?:citation|reference)s?\b[^\n]*?undefined|please \(re\)run",
    re.IGNORECASE,
)


@dataclass
class _FixRun:
    """fixloop 单格运行态——cell/ctx/loop 账一本持, 各相方法共享。

    ``fixloop()`` 状态机的相切承载体: 构造期字段 = 配置快照 (ruleset/
    引擎/阈值/回调), 运行期字段 = 跨相账簿 (floor 快照/sig streak/
    次级探针计数与复用槽/last_rep/B6 基线)。``_round`` 返 ``"break"``
    表本轮已定局 (verdict 写进 cell), ``None`` 表轮末正常结束;
    ``_secondary`` 的 flow 多一态 ``"continue"`` (warn-preempt 落件续轮)。
    经验调谐注释随块原样迁移——每处分支的实证依据不丢。
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
    #: 不退化底板: 入口态 PDF 快照路径 + 字节数 (Guard B baseline 分量)。
    floor_snap: Path | None = None
    floor_bytes: int = 0
    prev_sig: str = ""
    sig_n: int = 0
    last_rep: ErrReport | None = None
    sec_probes: int = 0  # 次级派发探针计数 (≤_SEC_PROBE_MAX/格)
    #: 上次探针时的 actions 计数——树无 apply 变化不重探 (重探=同 log 同候选)
    sec_probe_mark: int = -1
    #: 探针编译留给 salvage 兜底复用的槽——只在「探针同轮、无 apply、走向
    #: 裁决」时填入 (miss 块内探针→候选全灭→break 是原子序, 天然新鲜)。
    salvage_res: CompResLike | None = None
    salvage_rep: ErrReport | None = None
    #: 末次迭代编译前的 actions 账顶 (None = loop 未跑)——B6 写后复验门
    #: 的基线: 出口时账顶增长 = 末次编译后仍有 apply 落件。
    acts_mark: int | None = None
    rnd: int = 0
    #: 自动解析趟 once-per-cell 闸——pagerange 类永不解析标签格的
    #: rerun-hint 恒存, 无闸会逐轮回环 (fp resolve-pass dedup)。
    resolve_done: bool = False

    def _floor_snapshot(self) -> None:
        """快照入口态 PDF。

        先于 precheck/loop 一切编辑: 规则若把能出 pdf 的树打死,
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
            except OSError as e:  # 快照失败仅失底板, 不阻塞修复
                ctx.ledger.advisories.append(f"floor snapshot: {e}")

    # ------------------------------------------------------------ 主轮循环

    def _compile(
        self, *, passes: int | None = 1, best_effort: bool = False
    ) -> CompResLike:
        """``eng.compile`` + 编译后惯例两件套 (失效挥发性缓存 + 丢旗记账)。

        ``_VOLATILE_EXTS`` 头注的「循环内每个 ``eng.compile`` 后必失效此集」
        不变量收敛为结构——走本方法即不可能漏失效 (含探针与兜底臂, 幂等)。
        ``passes=None`` 透传引擎自适应遍数门。
        """
        ctx = self.ctx
        res = self.eng.compile(
            ctx.io.wdir,
            cast("str", ctx.io.main_rel),  # 循环期 main_rel 必已置位 (_setup_ctx 落值)
            passes=cast(
                "int", passes
            ),  # None 透传 impl 自适应趟 (impl 面 int|None, 本协议面 int)
            best_effort=best_effort,
            flags=list(ctx.ledger.engine_flags),
            **self.compile_kw,
        )
        ctx.invalidate_suffixes(_VOLATILE_EXTS)
        _note_dropped_flags(ctx, res)
        return res

    def _aux_seeded(self) -> bool:
        r"""工程任一 ``.aux`` 已产标签/引用记录——解析趟要解的目标在 aux 面。

        ``\newlabel``/``\bibcite`` (natbib/plain 系) 与 ``\citation``/
        ``\abx@aux@cite`` (bibtex/biblatex 系) 四签名任一在场即播种;
        未播种格的 undefined 纯属首轮 aux 空转 (常规 rerun-hint 升遍
        自足, 不走本臂)。文件面有界 (≤32 件) 防巨型工程扫盘。
        """
        marks = ("\\newlabel", "\\bibcite", "\\citation", "\\abx@aux@cite")
        for f in sorted(self.ctx.io.wdir.rglob("*.aux"))[:32]:
            t = self.ctx.read(f)
            if t and any(k in t for k in marks):
                return True
        return False

    def _resolve_tail(
        self,
        res: CompResLike,
        rep: ErrReport,
        *,
        best_effort: bool = False,
    ) -> tuple[CompResLike, ErrReport, float]:
        r"""出货前解析趟: log 残存 rerun/undefined 标 → 补发自适应趟。

        fp resolve-pass——``passes=None`` 续趟。
        判据三合: 本轮出 pdf (有产品才有"解齐引用"价值) ∧ 编译未死 ∧
        ``_UNRESOLVED_MARKS_RX`` 命中 rep.raw ∧ aux 已播种 (要解的
        ``\newlabel``/``\bibcite`` 记录确实在盘)。命中即补一发引擎自适
        应趟并以其 res/rep 覆盖调用面——undef-ref 残存的 PDF 不再带
        ``??`` 出货 (qc xlat_broken_refs 桶 17 格实证)。``resolve_done``
        once-per-cell 闸防 pagerange 类永不解析签的回环; tectonic 自定
        遍数天然豁免 (impl del passes, 本臂判据直接短路)。返
        ``(res, rep, 补趟秒数)``——未命中 ``sec=0`` 原样回传。
        """
        ctx = self.ctx
        if (
            self.resolve_done
            or ctx.deps.engine_name == "tectonic"
            or not _res_has_pdf(res)
            or _res_died(res)
            or not _UNRESOLVED_MARKS_RX.search(rep.raw or "")
            or not self._aux_seeded()
        ):
            return res, rep, 0.0
        self.resolve_done = True
        res2 = self._compile(passes=None, best_effort=best_effort)
        rep2 = _report_of(res2, self.rs.warn_patterns, ctx.io.wdir)
        sec = float(getattr(res2, "seconds", getattr(res2, "sec", 0.0)))
        ctx.ledger.events.append(
            "resolve pass: unresolved marks + seeded aux → adaptive compile "
            f"(pdf={_res_has_pdf(res2)} err={rep2.n_bang})"
        )
        return res2, rep2, sec

    def rounds(self) -> None:
        """主轮循环: 每轮 aux-sweep→分类编译→终止判→派发落账; 穷尽 → ``max_rounds``。"""
        for rnd in range(1, self.max_rounds + 1):
            if self.should_cancel is not None and self.should_cancel():
                raise asyncio.CancelledError
            self.rnd = rnd
            if self._round() == "break":
                break
        else:
            self.cell["verdict"] = "max_rounds"

    def _round(self) -> str | None:
        """单轮: 清毒件 → 分类编译 → entry → 终止判 → 派发 → 落账。

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
        # sig_n = 同签连续 streak——只记账不判负: stuck verdict 移到下方
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

    def _round_compile(
        self,
    ) -> tuple[CompResLike, ErrReport, str | None, str | None, float]:
        r"""本轮分类编译 → (res, rep, cat, pay, 秒数)。

        pass-1 读 log 分类; pass-1 判收敛则同轮全遍终编定稿 (rungen_stub
        类机制靠第二遍 ``\\write`` 填实成品), 复编重分类回流同一决策面。
        """
        ctx, rs, rnd = self.ctx, self.rs, self.rnd
        if ctx.ledger.needs_pass:
            # 上轮 apply 请求解析趟 (yaml ``action.params.needs_pass`` 或
            # builtin 直写——bbl 再生/citekey 改写类动了 aux/cite 记录面,
            # 单趟 log 分类不足以吸收) → 本轮分类编译直接走引擎自适应遍数,
            # ``\newlabel``/``\bibcite`` 同轮解齐。一次性闸, 消费即清。
            ctx.ledger.needs_pass = False
            res = self._compile(passes=None)
            ctx.ledger.events.append(f"r{rnd} resolve-pass (needs_pass requested)")
        else:
            res = self._compile(passes=1)  # 分类轮只读 pass-1 log——第二遍不产新分类信号
        rep = _report_of(res, rs.warn_patterns, ctx.io.wdir)
        cat, pay = _round_cat(rs, rep, res)
        round_sec = float(getattr(res, "seconds", getattr(res, "sec", 0.0)))
        if (  # pass-1 判收敛 → 同轮全遍终编定稿: rungen_stub 类机制靠
            # 第二遍 \write 填实成品; 复编重分类回流下方同一决策面,
            # pass-2-emergent 错照常进 gate/修复路径。tectonic 自定遍数
            # (impl del passes)、死编译轮不升遍——超时重跑大概率再超时;
            # 信号死 (xdvipdfmx SIGPIPE 截杀等) 产出未证且 aux 可正被截
            # 在半行, 同轮重编即吃毒件造 aux_scan_eof 幻影 (2403.05523
            # 实证, 与 ``_round_verdict`` clean 门同一 _res_died 否决语义)。
            self.passes > 1
            and self.ctx.deps.engine_name != "tectonic"
            and not _res_died(res)
            and _res_has_pdf(res)
            and rep.n_bang == 0
            and cat not in rs.taxonomy.warn_cats
        ):
            res = self._compile(
                # yaml ``compile_passes`` 权威依旧: >1 才进本臂; 值 ≤2 时传
                # ``None`` 走引擎自适应门 (rerun-hint 才升遍, 起步
                # MAX_PASSES=2, 提示仍在自延至 _ADAPTIVE_PASS_CAP),
                # >2 是钉死趟数诉求, 原样透传无条件执行。
                passes=None if self.passes <= 2 else self.passes,  # noqa: PLR2004 - 2 = compile/engine.py MAX_PASSES 自适应起步
            )
            rep = _report_of(res, rs.warn_patterns, ctx.io.wdir)
            cat, pay = _round_cat(rs, rep, res)
            round_sec += float(getattr(res, "seconds", getattr(res, "sec", 0.0)))
            ctx.ledger.events.append(
                f"r{rnd} finalize: pass-1 clean → {self.passes}-pass "
                f"(pdf={_res_has_pdf(res)} err={rep.n_bang} cat={cat})"
            )
        elif (  # 出货前解析趟 (qc-impl fp resolve-pass): 不判 n_bang==0——
            # 残错格同值得 "pdf 出货前把引用解齐" (17 格实证面), warn_cat
            # 轮亦收; aux 未播种/marks 缺席/已跑过由 _resolve_tail 自闸。
            self.passes > 1
            and self.ctx.deps.engine_name != "tectonic"
            and not _res_died(res)
            and _res_has_pdf(res)
        ):
            res, rep, rsec = self._resolve_tail(res, rep)
            if rsec:
                cat, pay = _round_cat(rs, rep, res)
                round_sec += rsec
        self.last_rep = rep
        ctx.round.point(cat, pay, rep)
        # 本轮 missing-char 码位面 (error-cat 轮同记)——缺字族 dedup
        # 增量豁免与 warn-preempt 勤勉闸的判据底账。
        ctx.round.mc_cps = (
            frozenset(_mc_parse_log(rep.raw or ""))
            if "missing_char" in rep.warnings
            else frozenset()
        )
        return res, rep, cat, pay, round_sec

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
        都收在此 (旧三抄里 salvage 臂两处皆漂: stat 兜底缺 + ``sec`` legacy
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
            # 口径给——best_effort (nonstopmode) 全程 log 不截, 恒 False。
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
        # 截在首错——n_bang 是下界非测量值, 证不了 errors≤clean_err_max。
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

        首错无规则可修时, 同 log 后续错误行可能才载可修根因
        (1206.0291: syntax 首错遮蔽 option_clash 孪生, geometry_hoist
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
        # 兜底 pass 复用, 净零编译。
        probe_res: CompResLike | None = None
        probe_rep: ErrReport | None = None
        cand_rep = rep
        if (
            rep.n_bang < 2  # noqa: PLR2004 - 2=单错→多错阈; log 已有全错误面 → 免费候选, 不烧探针
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
                continue  # 主错刚 miss 过, 不再重扫
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
        # 候选耗尽仍未命中——ctx.round 回指主错, 走原裁决路径;
        # 探针结果入兜底槽 (同轮无 apply, 状态未变, 复用安全)。
        ctx.round.point(cat, pay, rep)
        self.salvage_res, self.salvage_rep = probe_res, probe_rep
        # warn-preempt (missdisp #189): error-cat 轮把轮次烧完、裁决落
        # dirty/unfixable/stuck 前——残存 missing-char 码位若有族臂未见,
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
        # stuck 结算点移到派发耗尽后: 同签 streak ≥ stuck_sig_repeat 且
        # 本轮主+次级均无 apply → stuck。旧制在第 stuck_n 个同签轮派发前
        # 预判——产出轮 (apply 发生) 同样计入 sig_n, 会把只在第 N+1 轮才
        # 够得到的规则 (凭据门 if_phantom_protect 类) 永久抢死在窗口外
        # (1206.0701/1306.0364: r1/r2 各有 apply, r3 未派发即断)。新制下
        # 同签轮只有「本轮无产出」才结算 stuck——apply 轮次只续窗口,
        # 真耗尽格烧轮止于派发枯竭。
        cell["verdict"] = (
            "stuck"
            if self.sig_n >= self.stuck_n
            else f"unfixable:{cat}"
            if not pdf
            else "dirty_pdf"
        )
        return "break", None, "", None

    # ------------------------------------------------------------ 尾段

    def tail(self) -> None:
        """尾段: warn-preempt 补位 → B6 写后复验 → salvage 兜底 → 汇总定稿。"""
        self._post_warn_preempt()
        self._reverify()
        self._salvage()
        self._finalize()

    def _warn_preempt_hit(self, wrule: Rule, wnote: str, rnd: int | str) -> None:
        """warn-preempt 命中落账: action 条目 + event 行 + 兜底槽弃用。

        ``rnd`` = ``"round"`` 字段原值 (轮号或 ``"post"``)——event 行前缀
        分别派生 ``r<N>``/``post``。轮内补发与退出点补位两 site 共用。
        """
        ctx, cell = self.ctx, self.cell
        cell["actions"].append(
            {
                "round": rnd,
                "rule": wrule.id,
                "detail": wnote,
                "via": "warn_preempt",
            }
        )
        if _rule_needs_pass(wrule):  # 补发规则同可请求解析趟
            ctx.ledger.needs_pass = True
        label = rnd if isinstance(rnd, str) else f"r{rnd}"
        ctx.ledger.events.append(f"{label} warn-preempt -> {wrule.id} ({wnote})")
        # apply 已落地——探针编译瞬间陈旧, 兜底槽必须弃用
        self.salvage_res = self.salvage_rep = None

    def _post_warn_preempt(self) -> None:
        """warn-preempt 退出点补位 (missdisp #189)。

        loop 以 max_rounds/非拒绝 verdict 收场且末轮残存 missing-char 码位
        有族臂未见 → 补一轮派发再走 salvage/汇总。无 pdf 格的兜底编译天然
        充当验证编; max_rounds+pdf 格的 apply 落地后由下方 B6 写后复验
        补编取证。
        """
        ctx, cell = self.ctx, self.cell
        if str(cell["verdict"] or "").startswith("reject:"):
            return
        wrule, wnote = _warn_preempt(
            self.rs, ctx, self.eng, self.last_rep or ErrReport()
        )
        if wrule is None:
            return
        if wnote.startswith(_REJECT_PREFIX):
            _commit_reject(cell, wrule, wnote)
            return
        self._warn_preempt_hit(wrule, wnote, "post")

    def _reverify(self) -> None:
        """B6 写后复验。

        末次编译后仍有 apply 落件 (末轮派发/gate/post
        warn-preempt 统一经 ledger.actions 入账) → ``rounds[-1]`` 证的是
        写前证据, 汇总段 floor/Guard-A/B/acceptable_pdf 公式全吃残证
        (2503.10148/2606.19622: stub 落在末编 ~0.7s 后, max_rounds 格被压
        dirty/acceptable 失真)。补一发常参 pass-1 编译——非 best_effort:
        halt 口径与轮编译同标, Guard A 的 log_truncated 判据才同义——
        entry 按轮形落让下游公式零改消费, ``proxy.last`` 同被刷新 (bench
        post 复判吃 fixloop_last 亦得新证)。门 = actions 账顶增长 ∧
        末轮出 pdf: 无 pdf 出路的写后取证由 salvage best_effort 兜底天然
        承担 (其 sentry entry 即新证), reject/定败 unfixable 复验无义;
        clean 出路在派发段前 break 写不存在, 天然零开销 (构造保证)。≤1 次/格。
        """
        ctx, cell = self.ctx, self.cell
        if not (
            self.acts_mark is not None
            and cell["rounds"]
            and cell["rounds"][-1].get("pdf")
            and len(ctx.ledger.actions) > self.acts_mark
        ):
            return
        res = self._compile(passes=1)
        rep = _report_of(res, self.rs.warn_patterns, ctx.io.wdir)
        # 解析趟后处理同套——写后复验的 pass-1 产物若仍带 undef 标且 aux
        # 已播种, 补一发自适应趟再落 entry (fp resolve-pass 尾段复用)。
        res, rep, _rsec = self._resolve_tail(res, rep)
        cat, pay = _round_cat(self.rs, rep, res)
        self.last_rep = rep  # log_excerpt 消费终态报告
        # 与轮 entry 同式 (adjudication #10 Guard A): halt + n_bang>0
        # ⇒ 截断下界证不了 errors≤max——best_effort 才恒 False 豁免。
        entry = self._append_round(
            res,
            rep,
            rnd=len(cell["rounds"]) + 1,
            cat=cat,
            pay=pay,
            log_truncated=bool(
                getattr(self.eng, "halt_on_error", False) and rep.n_bang > 0
            ),
            marker={"reverify": True},
        )
        ctx.ledger.events.append(
            f"post-write reverify: pdf={entry['pdf']} err={rep.n_bang} cat={cat}"
        )

    def _salvage(self) -> None:
        r"""best-effort 兜底 pass。

        规则耗尽且末轮无 pdf → 去 halt-on-error 让 TeX 错误恢复跑到底救
        残页 (astro-ph/0306068 型真回归: 首错即停 vs nonstopmode 续跑出
        partial pdf)。reject:* 是语义拒绝不救; clean/dirty/acceptable 已有
        pdf 不救; timeout 重跑大概率再超时, 不救; runaway_output 是
        ``\output`` 死循环暴走, 非定败重跑必然再暴走, 不救; 驱动 fatal 是
        驱动层确定败 (同输入同 fatal), nonstopmode 改不了 shipout 后管道,
        不救——主面走末轮 ``driver_fatal`` 证据字段 (category 借 "other"
        面供修复规则派发, verdict 词看不出驱动死), ``unfixable:driver_fatal``
        兜 _round_cat clean/None 边路径。``unfixable:input_stack`` 同为
        定败——该 cat 只由 capacity 重路由产出, 全属上游执行宏递归帧,
        nonstopmode 重跑同炸, 不救。
        """
        ctx, cell = self.ctx, self.cell
        v_now = str(cell["verdict"] or "")
        if not (
            v_now
            and not v_now.startswith("reject:")
            and v_now
            not in (
                "clean",
                "acceptable_pdf",
                "dirty_pdf",
                "unfixable:timeout",
                "unfixable:runaway_output",
                "unfixable:driver_fatal",
                "unfixable:input_stack",
            )
            and not (cell["rounds"] and cell["rounds"][-1]["pdf"])
            and not (cell["rounds"] and cell["rounds"][-1].get("driver_fatal"))
        ):
            return
        swept = _sweep_bad_aux(ctx.io.wdir)
        if swept:
            ctx.ledger.events.append(f"salvage aux-sweep: {', '.join(swept)}")
        # 次级派发探针复用: miss 轮已跑过同参 best_effort 编译且其间无
        # apply (状态未变)——直接取回, 不二次烧编译 (twinhead 净零成本)。
        sres = (
            self.salvage_res
            if self.salvage_res is not None
            else self._compile(passes=1, best_effort=True)
        )
        ctx.invalidate_suffixes(_VOLATILE_EXTS)
        _note_dropped_flags(ctx, sres)  # 复用探针已记录过——flags_dropped 去重幂等
        srep = (
            self.salvage_rep
            if self.salvage_rep is not None
            else _report_of(sres, self.rs.warn_patterns, ctx.io.wdir)
        )
        # 解析趟后处理同套 (best_effort 档续传 nonstopmode)——兜底产物
        # 若仍带 undef 标且 aux 已播种, 补一发自适应趟再落 sentry entry。
        sres, srep, _rsec = self._resolve_tail(sres, srep, best_effort=True)
        # best_effort (nonstopmode) 全程 log 不截——Guard A 豁免 (adjudication #10)。
        sentry = self._append_round(
            sres,
            srep,
            rnd=len(cell["rounds"]) + 1,
            cat=None,
            pay=None,
            log_truncated=False,
            marker={"salvage": True},
        )
        spdf = bool(sentry["pdf"])
        cell["actions"].append(
            {
                "round": "salvage",
                "rule": "_best_effort_pass",
                "detail": f"nonstopmode 兜底: pdf={spdf} err={srep.n_bang}",
            }
        )
        ctx.ledger.events.append(f"salvage best_effort: pdf={spdf} err={srep.n_bang}")
        if spdf:
            cell["verdict"] = "best_effort_pdf"

    def _finalize(self) -> None:
        """汇总最终态 (原型)。

        floor 兜回 → final 字段 → verdict 公式 (Guard A/B) → acceptable
        升档 → 末态清场 → gate_fired。
        """
        ctx, cell, rs = self.ctx, self.cell, self.rs
        last = cell["rounds"][-1] if cell["rounds"] else {}
        cell["final_pdf"] = bool(last.get("pdf"))
        # —— 底板兜回: 入口有 pdf 而末态无 → 拷回快照, verdict 置 None 让下方
        # 既有公式自然落成 dirty_pdf/clean; floor_from 记兜底前 verdict 供
        # triage/cases 观测 (不新增 verdict 词, 保持 docs/spec/compile.md 词表封闭)。
        v_end = str(cell["verdict"] or "")
        if (
            not cell["final_pdf"]
            and self.floor_snap is not None
            and not v_end.startswith("reject:")
        ):
            main_pdf = ctx.io.wdir / Path(cast("str", ctx.io.main_rel)).with_suffix(
                ".pdf"
            )
            main_pdf.unlink(missing_ok=True)  # 末态同名碎片先清再拷, 防半截混语义
            shutil.copy2(self.floor_snap, main_pdf)
            cell["floor_from"] = v_end
            cell["floor_restored"] = True
            cell["final_pdf"] = True
            cell["verdict"] = None
            ctx.ledger.events.append(
                f"floor: entry pdf restored (was {v_end or 'none'})"
            )
        cell["final_errors"] = last.get("n_errors")
        cell["final_cat"] = last.get("category")
        cell["installed"] = ctx.ledger.installed
        # 「看见/拒修」物化: rules_fired (actions 列) 的互补面 —— when 命中
        # 但 cond/applied 败阵的规则 id 去重列 + 带因注记 (去重同条目)。
        cell["rules_declined"] = list(
            dict.fromkeys(d.split(":", 1)[0] for d in ctx.ledger.declined)
        )
        cell["decline_notes"] = ctx.ledger.declined
        cell["advisories"] = ctx.ledger.advisories
        cell["engine_flags"] = ctx.ledger.engine_flags
        cell["engine_flags_dropped"] = ctx.ledger.flags_dropped
        cell["log"] = ctx.ledger.events
        if (
            self.last_rep is not None
        ):  # triage 原料: 终态错误上下文 (docs/spec/compile.md §6.8 log_excerpt)
            head = "\n".join(x for x in (self.last_rep.first, self.last_rep.ctx) if x)
            cell["log_excerpt"] = (head or self.last_rep.tail)[:2000]
        cell["started_fail"] = not (cell["rounds"] and cell["rounds"][0]["pdf"])
        if cell["verdict"] in (None, "max_rounds", "stuck") and cell["final_pdf"]:
            # 末轮死编译（超时/信号杀）产出 pdf 未证 clean——压成 dirty 且禁升;
            # halt 截断轮同理 (n_bang 下界证不了 0 错, Guard A adjudication #10)。
            # clean 式与 ``_round_verdict`` 收敛门同面 (spec compile.md:201): pdf ∧
            # n_bang==0 ∧ cat∉warn_cats ∧ ¬died——warn 残类照样压 dirty。
            # 旧 ``or 9`` 把 n_errors=0 也吞成 9 (缺字段保守语义误伤真 0)——
            # B6 写后复验让 0 错 entry 在 max_rounds/stuck 出口可达, clean 臂
            # 由死码复活; 0-err warn-cat 末轮 (旧可达) 由 warn_cats 子句等价
            # 接管, 无行为回退。
            n_err_last = last.get("n_errors")
            cell["verdict"] = (
                "dirty_pdf"
                if (9 if n_err_last is None else n_err_last) > 0
                or last.get("died")
                or last.get("log_truncated")
                or last.get("category") in rs.taxonomy.warn_cats
                else "clean"
            )
        # Guard B (adjudication #10) 内容腰斩闸: 终产物字节相对本 run 最强 pdf
        # (floor 快照 ∪ 逐轮峰值) 跌过 50% ⇒ 中段截断/内容回归——nonstopmode
        # 定败残页是 log_truncated 够不到的补位面; 阈值外诚实 zh 重排不动。
        # floor 兜回格终产物即快照本体, final_bytes 取 floor 而非末轮的 0。
        baseline_bytes = max(
            self.floor_bytes, *(int(r.get("pdf_bytes") or 0) for r in cell["rounds"])
        )
        final_bytes = (
            self.floor_bytes
            if cell["floor_restored"]
            else int(last.get("pdf_bytes") or 0)
        )
        shrunk = bool(
            cell["final_pdf"]
            and baseline_bytes > 0
            and final_bytes < baseline_bytes * 0.5
        )
        if shrunk:
            cell["content_regressed"] = round(final_bytes / baseline_bytes, 3)
            if cell["verdict"] == "clean":
                # 0 错编译同样可腰斩 (修复误删附录类真内容丢失)——clean 不豁免。
                cell["verdict"] = "dirty_pdf"
        if (
            cell["final_pdf"]
            and (cell["final_errors"] or 0) <= self.clean_err_max
            and cell["verdict"] == "dirty_pdf"
            and not last.get("died")  # 死编译末轮的 dirty 不升 acceptable
            and not last.get("log_truncated")  # 截断 log 证不了 errors≤max (Guard A)
            and not shrunk  # 腰斩残页不升 (Guard B)
        ):
            cell["verdict"] = "acceptable_pdf"
        # 末态清场: 末轮/兜底被杀的截断 aux 不驻留毒化格后 post 复判
        swept = _sweep_bad_aux(ctx.io.wdir)
        if swept:
            ctx.ledger.events.append(f"final aux-sweep: {', '.join(swept)}")
            cell["log"] = (
                ctx.ledger.events
            )  # 上方已赋值的同一 list 引用, 显式重挂防漂移
        cell["gate_fired"] = _gate_fired_of(cell)


def fixloop(  # noqa: PLR0913 -- 注入面穿透
    proj: Path | str,
    eng: Engine,
    *,
    ruleset: Ruleset | None = None,
    engine_name: str | None = None,
    main_rel: str | None = None,
    corpus_id: str | None = None,
    cond: str | None = None,
    llm_hook: LlmHook | None = None,
    runner: RunFn | None = None,
    case_sink: CaseSink | None = None,
    compile_timeout: float | None = None,
    should_cancel: Callable[[], bool] | None = None,
    on_round: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """跑一格修复循环 → cell dict (字段与原型 fixloop-results.json 兼容)。

    verdict ∈ clean / acceptable_pdf / dirty_pdf / best_effort_pdf /
    unfixable:<cat> / stuck / max_rounds / reject:<rid> /
    no_errors_no_pdf / no_main_tex[:<sub>]（``classify_no_main`` 细分）

    装配面: setup (ruleset/引擎名/cfg/ctx/cell) → 主档解析与 no_main 早退
    → ``_FixRun`` 相机 (_floor_snapshot → precheck 早退 → rounds 主循环
    → tail 尾段)。相内状态机分支各归其方法, 经验调谐注释逐块随迁。

    ``main_rel`` 缺省时 ``find_main_tex`` 双档推导；调用方持有正确主档
    时显式传入（译后 splice 树的语种重排会让 ``language_rank`` 把
    CJK 主档输给 standalone 英文档——ds209diag #191 实证 4 格误选）。
    指定档缺件/指树外则回退自动探测，落 ``cell["main_fallback"]`` 留痕；
    ``cell["main"]`` 恒记实效主档。

    ``on_round`` 可选逐轮回调：每轮 ``cell["rounds"]`` 落新 entry 即同步
    调用（含 salvage 兜底轮），entry 与 cell 内同对象——server worker
    借此发 SSE 实况帧；None 时零开销，e2e/bench 直调臂行为不变。
    """
    rs, engine_name, wdir, ctx = _setup_ctx(
        proj,
        eng,
        ruleset=ruleset,
        engine_name=engine_name,
        runner=runner,
        llm_hook=llm_hook,
    )
    cfg = rs.loop_cfg
    max_rounds = int(cfg.get("max_rounds", 8))
    clean_err_max = int(cfg.get("clean_err_max", 3))
    passes = int(cfg.get("compile_passes", 2))
    stuck_n = int(cfg.get("stuck_sig_repeat", 3))
    # 重编超时: 参数 > meta.loop.timeout_sec > 引擎缺省 (None = 不透传)
    if compile_timeout is not None:
        timeout = float(compile_timeout)
    elif cfg.get("timeout_sec") is not None:
        timeout = float(cfg["timeout_sec"])
    else:
        timeout = None
    compile_kw: dict[str, Any] = {}
    if timeout is not None:
        compile_kw["timeout"] = timeout

    cell: dict[str, Any] = {
        "project": corpus_id or wdir.name,
        "cond": cond,
        "main": None,
        "engine": engine_name,
        "rounds": [],
        "actions": [],
        "verdict": None,
        # reject 决策名单: gate/loop 相 REJECT 不经 actions 列 (precheck 相
        # append 在先判 REJECT 在后, 双栖) —— 单列物化, 不混 rules_fired
        # 的修复语义, verdict ``reject:<rid>`` 的结构化面。
        "gate_fired": [],
        "floor_restored": False,
        # 调用方指定主档缺件/树外时的回退留痕——None = 无回退发生
        "main_fallback": None,
    }
    main: Path | None = None
    if main_rel is not None:
        cand = wdir / main_rel
        # 树外引用 (绝对路径/.. 逃逸) 与缺件同档处理——主档必须在工程树内
        if cand.is_file() and cand.resolve().is_relative_to(wdir.resolve()):
            main = cand
        else:
            cell["main_fallback"] = main_rel
            ctx.ledger.advisories.append(
                f"main_rel {main_rel} not in tree; fell back to find_main_tex"
            )
    if main is None:
        main = find_main_tex(wdir)
    if main is None:
        sub = _classify_no_main(wdir)
        cell["verdict"] = f"no_main_tex:{sub}" if sub else "no_main_tex"
        _record_case(
            case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
        )
        return cell
    ctx.io.main_rel = str(main.relative_to(wdir))
    cell["main"] = ctx.io.main_rel
    cell["actions"] = ctx.ledger.actions  # 同一 list: precheck/gate/loop 动作汇入一处
    _wire_engine(eng, rs, wdir, ctx)

    run = _FixRun(
        rs=rs,
        eng=eng,
        ctx=ctx,
        cell=cell,
        compile_kw=compile_kw,
        max_rounds=max_rounds,
        clean_err_max=clean_err_max,
        passes=passes,
        stuck_n=stuck_n,
        should_cancel=should_cancel,
        on_round=on_round,
    )
    run._floor_snapshot()  # noqa: SLF001 -- 装配臂驱相内方法

    # —— precheck phase (第 0 招; 静态路由也在这里) ——
    p_verdict, p_route = _precheck_phase(rs, ctx, eng)
    if p_verdict is not None:
        cell["verdict"] = p_verdict
        cell["gate_fired"] = _gate_fired_of(cell)
        if p_route:
            cell["reject_route"] = p_route
        _record_case(
            case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
        )
        return cell

    run.rounds()
    run.tail()
    _record_case(
        case_sink, cell, corpus_id=corpus_id, cond=cond, engine_name=engine_name
    )
    return cell


def _record_case(
    sink: CaseSink | None,
    cell: dict[str, Any],
    *,
    corpus_id: str | None,
    cond: str | None,
    engine_name: str,
) -> None:
    """沉淀 cases.jsonl (docs/spec/compile.md); sink 缺省即不写。"""
    if sink is None:
        return
    sink.record(cell, corpus_id=corpus_id, cond=cond, engine=engine_name)
