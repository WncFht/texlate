r"""engine.run.comp — ``_FixRun`` 编译相 mixin (二级拆叶)。

``eng.compile`` 原语 + 出货前解析趟 + 轮次分类编译四法
(``_compile``/``_aux_seeded``/``_resolve_tail``/``_round_compile``)——
主轮与尾段 (reverify/salvage) 共用的「编译+读 log 分类」机制面。
``_UNRESOLVED_MARKS_RX`` 判据常数随 ``_resolve_tail`` 同迁。
patch 注意: 方法体内名解析走本叶命名空间 (seams.md §5)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, cast

from texlate.compile.fixloop.builtins.common import _mc_parse_log
from texlate.compile.fixloop.engine.auxiliary import _VOLATILE_EXTS
from texlate.compile.fixloop.engine.proto import (
    _note_dropped_flags,
    _report_of,
    _res_died,
    _res_has_pdf,
    _round_cat,
)

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine.proto import CompResLike
    from texlate.compile.fixloop.engine.run import _FixRun
    from texlate.compile.logparse import ErrReport

__all__ = [
    "_UNRESOLVED_MARKS_RX",
    "_RunComp",
]


#: 出货前解析趟判据——编译 log 里仍存活的 rerun/undefined-ref/cite 请
#: 求面。xelatex ``_RERUN_HINT_RX`` 的超集：加 ``(citation|reference)..
#: undefined`` (0806.3788 型 Rerun 尾标被 bib brace 错吞后 citation
#: undefined 是唯一存活标记) 与 ``Please (re)run`` (biber/bibtex 请求行)。
_UNRESOLVED_MARKS_RX = re.compile(
    r"rerun to get|label\(s\) may have changed|there were undefined|"
    r"(?:citation|reference)s?\b[^\n]*?undefined|please \(re\)run",
    re.IGNORECASE,
)


class _RunComp:
    """``_FixRun`` 编译相——``eng.compile`` 包装与分类趟原语集。"""

    def _compile(
        self: _FixRun, *, passes: int | None = 1, best_effort: bool = False
    ) -> CompResLike:
        """``eng.compile`` + 编译后惯例两件套 (失效挥发性缓存 + 丢旗记账)。

        ``_VOLATILE_EXTS`` 头注的「循环内每个 ``eng.compile`` 后必失效此集」
        不变量收敛为结构——走本方法即不可能漏失效 (含探针与兜底臂，幂等)。
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

    def _aux_seeded(self: _FixRun) -> bool:
        r"""工程任一 ``.aux`` 已产标签/引用记录——解析趟要解的目标在 aux 面。

        ``\newlabel``/``\bibcite`` (natbib/plain 系) 与 ``\citation``/
        ``\abx@aux@cite`` (bibtex/biblatex 系) 四标记任一在场即播种;
        未播种格的 undefined 纯属首轮 aux 空转 (常规 rerun-hint 升遍
        自足, 不走本臂)。文件面有界 (≤32 件) 防巨型工程扫盘。
        """
        marks = ("\\newlabel", "\\bibcite", "\\citation", "\\abx@aux@cite")
        for f in sorted(self.ctx.io.wdir.rglob("*.aux"), key=lambda p: p.as_posix())[
            :32
        ]:
            t = self.ctx.read(f)
            if t and any(k in t for k in marks):
                return True
        return False

    def _resolve_tail(
        self: _FixRun,
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

    def _round_compile(
        self: _FixRun,
    ) -> tuple[CompResLike, ErrReport, str | None, str | None, float]:
        r"""本轮分类编译 → (res, rep, cat, pay, 秒数)。

        pass-1 读 log 分类; pass-1 判收敛则同轮全遍终编定稿 (rungen_stub
        类机制靠第二遍 ``\\write`` 填实成品), 复编重分类回流同一决策面。
        """
        ctx, rs, rnd = self.ctx, self.rs, self.rnd
        if ctx.ledger.needs_pass:
            # 上轮 apply 请求解析趟 (yaml ``action.params.needs_pass`` 或
            # builtin 直写——bbl 再生/citekey 改写类动了 aux/cite 记录面，
            # 单趟 log 分类不足以吸收) → 本轮分类编译直接走引擎自适应遍数，
            # ``\newlabel``/``\bibcite`` 同轮解齐。一次性闸，消费即清。
            ctx.ledger.needs_pass = False
            res = self._compile(passes=None)
            ctx.ledger.events.append(f"r{rnd} resolve-pass (needs_pass requested)")
        else:
            res = self._compile(passes=1)  # 分类轮只读 pass-1 log——第二遍不产新分类信号
        rep = _report_of(res, rs.warn_patterns, ctx.io.wdir)
        cat, pay = _round_cat(rs, rep, res)
        round_sec = float(getattr(res, "seconds", getattr(res, "sec", 0.0)))
        if (  # pass-1 判收敛 → 同轮全遍终编定稿：rungen_stub 类机制靠
            # 第二遍 \write 填实成品; 复编重分类回流下方同一决策面，
            # pass-2-emergent 错照常进 gate/修复路径。tectonic 自定遍数
            # (impl del passes)、死编译轮不升遍——超时重跑大概率再超时;
            # 信号死 (xdvipdfmx SIGPIPE 截杀等) 产出未证且 aux 可正被截
            # 在半行，同轮重编即吃毒件造 aux_scan_eof 幻影 (2403.05523
            # 实证，与 ``_round_verdict`` clean 门同一 _res_died 否决语义)。
            self.passes > 1
            and self.ctx.deps.engine_name != "tectonic"
            and not _res_died(res)
            and _res_has_pdf(res)
            and rep.n_bang == 0
            and cat not in rs.taxonomy.warn_cats
        ):
            res = self._compile(
                # yaml ``compile_passes`` 权威依旧：>1 才进本臂; 值 ≤2 时传
                # ``None`` 走引擎自适应门 (rerun-hint 才升遍，起步
                # MAX_PASSES=2, 提示仍在自延至 _ADAPTIVE_PASS_CAP),
                # >2 是钉死趟数诉求，原样透传无条件执行。
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
