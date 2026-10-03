r"""engine.run.tail — ``_FixRun`` 尾段 mixin (二级拆叶)。

warn-preempt 退出点补位 + B6 写后复验 + best-effort 兜底 + 汇总定稿
(``tail``/``_warn_preempt_hit``/``_post_warn_preempt``/``_reverify``/
``_salvage``/``_finalize``)——主轮穷尽或定局后跑的后处理相。
patch 注意: 方法体内名解析走本叶命名空间——``_warn_preempt`` 在
本叶的 patch 点是 ``engine.run.tail._warn_preempt`` (轮内
``_secondary`` 的同名调用点仍在 ``engine.run``, seams.md §5)。
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING, cast

from texlate.compile.fixloop.actions import _REJECT_PREFIX
from texlate.compile.fixloop.engine.auxiliary import _VOLATILE_EXTS, _sweep_bad_aux
from texlate.compile.fixloop.engine.disp import (
    _commit_reject,
    _gate_fired_of,
    _rule_needs_pass,
    _warn_preempt,
)
from texlate.compile.fixloop.engine.proto import (
    _note_dropped_flags,
    _report_of,
    _round_cat,
)
from texlate.compile.logparse import ErrReport

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine.run import _FixRun
    from texlate.compile.fixloop.ruleset import Rule

__all__ = [
    "_RunTail",
]


class _RunTail:
    """``_FixRun`` 尾段——warn-preempt 补位/复验/兜底/汇总四相。"""

    def tail(self: _FixRun) -> None:
        """尾段：warn-preempt 补位 → B6 写后复验 → salvage 兜底 → 汇总定稿。"""
        self._post_warn_preempt()
        self._reverify()
        self._salvage()
        self._finalize()

    def _warn_preempt_hit(
        self: _FixRun, wrule: Rule, wnote: str, rnd: int | str
    ) -> None:
        """warn-preempt 命中落账：action 条目 + event 行 + 兜底槽弃用。

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
        # apply 已落地——探针编译瞬间陈旧，兜底槽必须弃用
        self.salvage_res = self.salvage_rep = None

    def _post_warn_preempt(self: _FixRun) -> None:
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

    def _reverify(self: _FixRun) -> None:
        """B6 写后复验。

        末次编译后仍有 apply 落件 (末轮派发/gate/post
        warn-preempt 统一经 ledger.actions 入账) → ``rounds[-1]`` 证的是
        写前证据，汇总段 floor/Guard-A/B/acceptable_pdf 公式全吃残证
        (2503.10148/2606.19622: stub 落在末编 ~0.7s 后，max_rounds 格被压
        dirty/acceptable 失真)。补一发常参 pass-1 编译——非 best_effort:
        halt 口径与轮编译同标，Guard A 的 log_truncated 判据才同义——
        entry 按轮形落让下游公式零改消费，``proxy.last`` 同被刷新 (bench
        post 复判吃 fixloop_last 亦得新证)。门 = actions 账顶增长 ∧
        末轮出 pdf: 无 pdf 出路的写后取证由 salvage best_effort 兜底天然
        承担 (其 sentry entry 即新证), reject/定败 unfixable 复验无义;
        clean 出路在派发段前 break 写不存在，天然零开销 (构造保证)。≤1 次/格。
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
        # 已播种，补一发自适应趟再落 entry (fp resolve-pass 尾段复用)。
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

    def _salvage(self: _FixRun) -> None:
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
        # 次级派发探针复用：miss 轮已跑过同参 best_effort 编译且其间无
        # apply (状态未变)——直接取回，不二次烧编译 (twinhead 净零成本)。
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
        # 若仍带 undef 标且 aux 已播种，补一发自适应趟再落 sentry entry。
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

    def _finalize(self: _FixRun) -> None:
        """汇总最终态 (原型)。

        floor 兜回 → final 字段 → verdict 公式 (Guard A/B) → acceptable
        升档 → 末态清场 → gate_fired。
        """
        ctx, cell, rs = self.ctx, self.cell, self.rs
        last = cell["rounds"][-1] if cell["rounds"] else {}
        cell["final_pdf"] = bool(last.get("pdf"))
        # —— 底板兜回：入口有 pdf 而末态无 → 拷回快照，verdict 置 None 让下方
        # 既有公式自然落成 dirty_pdf/clean; floor_from 记兜底前 verdict 供
        # triage/cases 观测 (不新增 verdict 词，保持 docs/spec/compile.md 词表封闭)。
        v_end = str(cell["verdict"] or "")
        if (
            not cell["final_pdf"]
            and self.floor_snap is not None
            and not v_end.startswith("reject:")
        ):
            main_pdf = ctx.io.wdir / Path(cast("str", ctx.io.main_rel)).with_suffix(
                ".pdf"
            )
            main_pdf.unlink(missing_ok=True)  # 末态同名碎片先清再拷，防半截混语义
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
        # 「看见/拒修」物化：rules_fired (actions 列) 的互补面 —— when 命中
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
        ):  # triage 原料：终态错误上下文 (docs/spec/compile.md §6.8 log_excerpt)
            head = "\n".join(x for x in (self.last_rep.first, self.last_rep.ctx) if x)
            cell["log_excerpt"] = (head or self.last_rep.tail)[:2000]
        cell["started_fail"] = not (cell["rounds"] and cell["rounds"][0]["pdf"])
        if cell["verdict"] in (None, "max_rounds", "stuck") and cell["final_pdf"]:
            # 末轮死编译（超时/信号杀）产出 pdf 未证 clean——压成 dirty 且禁升;
            # halt 截断轮同理 (n_bang 下界证不了 0 错，Guard A adjudication #10)。
            # clean 式与 ``_round_verdict`` 收敛门同面 (spec compile.md:201): pdf ∧
            # n_bang==0 ∧ cat∉warn_cats ∧ ¬died——warn 残类照样压 dirty。
            # 旧 ``or 9`` 把 n_errors=0 也吞成 9 (缺字段保守语义误伤真 0)——
            # B6 写后复验让 0 错 entry 在 max_rounds/stuck 出口可达，clean 臂
            # 由死码复活; 0-err warn-cat 末轮 (旧可达) 由 warn_cats 子句等价
            # 接管，无行为回退。
            n_err_last = last.get("n_errors")
            cell["verdict"] = (
                "dirty_pdf"
                if (9 if n_err_last is None else n_err_last) > 0
                or last.get("died")
                or last.get("log_truncated")
                or last.get("category") in rs.taxonomy.warn_cats
                else "clean"
            )
        # Guard B (adjudication #10) 内容腰斩闸：终产物字节相对本 run 最强 pdf
        # (floor 快照 ∪ 逐轮峰值) 跌过 50% ⇒ 中段截断/内容回归——nonstopmode
        # 定败残页是 log_truncated 够不到的补位面; 阈值外诚实 zh 重排不动。
        # floor 兜回格终产物即快照本体，final_bytes 取 floor 而非末轮的 0。
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
        # 末态清场：末轮/兜底被杀的截断 aux 不驻留毒化格后 post 复判
        swept = _sweep_bad_aux(ctx.io.wdir)
        if swept:
            ctx.ledger.events.append(f"final aux-sweep: {', '.join(swept)}")
            cell["log"] = (
                ctx.ledger.events
            )  # 上方已赋值的同一 list 引用，显式重挂防漂移
        cell["gate_fired"] = _gate_fired_of(cell)
