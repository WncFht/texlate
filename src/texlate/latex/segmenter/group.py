r"""``latex/segmenter`` 子模块——god-class 机械拆分（行为零变）。"""

from __future__ import annotations

from bisect import (
    bisect_left,
)
from typing import TYPE_CHECKING, cast

import texlate.latex.tables as _tables
from texlate.latex.gullet import (
    _tok_eq,
)
from texlate.latex.model import (
    ArgSpec,
    PhType,
    env_opt_is_format,
)
from texlate.latex.tables import (
    ARG_TRANSPARENT_ENVS,
    ENV_MANDATORY_ARG,
    MATH_ENVS,
    PROTECTED_ENVS,
    VERBATIM_ENVS,
    looks_like_colspec,
)
from texlate.textutil import (
    DEAD_ENVS,
    dead_end_anchored,
)

from ._common import (
    _BSBS_SLOTS,
    _GRP_BSBS_CONTENT_RX,
    _GRP_SCAN_CAP,
    _GRP_TAIL_CAP,
    _KEYVAL_GROUP_RX,
    _PEND_PROBE,
    _aspec_elem,
    _call_slots,
    _chunk_spec_cached,
    _env_mand_count,
    _prose_arg_hit,
    _prose_word_hit,
    _scan_envtag,
    _slot_elem,
    _WalkRes,
    _WSpec,
)

if TYPE_CHECKING:
    import re

    from texlate.latex.model import ArgspecEntry
    from texlate.latex.mouth import (
        Tok,
    )
    from texlate.latex.segmenter import Segmenter

r"""``Segmenter`` 组内再生保护段（``_grp_*`` 单遍扫描器族）。"""


class _Group:
    def _grp_ph(self: Segmenter, typ: PhType, body: str) -> str:
        r"""组内 surface ph：先挂 ``_run_pending``。

        run 转 chunk 才入 ``ph_map``——literal 冲刷只渲染 ident，surface
        ph 若直登记必成 dead_ph。
        """
        return self.state.issuer.new(
            typ, body, self._run_pending, self.state.ph_reserved
        )

    @staticmethod
    def _cat_surf(out: list[str], s: str) -> None:
        r"""Surface 段追加。

        ``\``-引导且字母结尾的元素（控制词渲染）后随字母开头元素时插
        ``" "``——TeX 控制词吞空格的 detokenize 对价。展开组 token pos
        指调用点、无 gap 字节可恢复（``_gap_surface`` 只救 gen=0），不补
        则 ``{\bf X}`` 展开成 ``\bfX``（未定义控制词 + 逃逸翻译）。
        """
        if (
            out
            and s[:1].isalpha()
            and out[-1].startswith("\\")
            and out[-1][-1:].isalpha()
        ):
            out.append(" ")
        out.append(s)

    def _grp_surfs(self: Segmenter, toks: list[Tok]) -> str:
        out: list[str] = []
        for t in toks:
            self._cat_surf(out, self._tok_surface(t))
        return "".join(out)

    def _grp_envtag(self: Segmenter, toks: list[Tok], i: int) -> tuple[str, int] | None:
        r"""``\\begin``/``\\end`` + ws + ``{name}`` → ``(name, j_end)``；失配 None。

        主流对价：``_env_name``——扫描本体 = ``_common._scan_envtag``
        单源（前扫跨 space 与 ``eol_par``，名内 ``eol_par`` 即失败，
        R6 主流同规）。
        """
        n = len(toks)
        j = i + 1

        def pull() -> Tok | None:
            nonlocal j
            if j >= n:
                return None
            x = toks[j]
            j += 1
            return x

        hit = _scan_envtag(pull, self._tok_surface)
        return (hit[0], j) if hit is not None else None

    def _grp_env_macro(self: Segmenter, t: Tok) -> tuple[str, str] | None:
        r"""组内 env_begin/env_end 宏端点 → ``(kind, target_env)``；非宏 None。"""
        m = self.state.macros.resolve(self.state.macros.lookup(t.text))
        kind = getattr(m, "kind", "")
        if kind in ("env_begin", "env_end"):
            return kind, getattr(m, "target_env", "")
        return None

    def _grp_find_env_end(  # noqa: C901 — begin/end/cs-end/宏端点四臂单遍深度扫描平铺
        self: Segmenter, toks: list[Tok], i: int, env: str
    ) -> int | None:
        r"""``i`` 起找配对 ``\\end{env}``（同名 begin/宏端点计深度）→ j_end。

        comment 族体不嵌套、仅行锚 ``\\end{env}`` 终结（``_env_stop`` dead
        臂同式）——行中 ``\\end{comment}``/``\\end<env>`` 字面/宏端点全不算。
        """
        target = env.rstrip("*")
        dead = env in DEAD_ENVS
        depth = 1
        j = i
        while j < len(toks) and j - i < _GRP_SCAN_CAP:
            x = toks[j]
            if x.kind == "cs" and x.text in ("begin", "end"):
                hit = self._grp_envtag(toks, j)
                if hit is not None:
                    n2, e = hit
                    if dead:
                        if (
                            x.text == "end"
                            and n2 == env
                            and x.pos[0] == toks[e - 1].pos[0]
                            and dead_end_anchored(
                                self.file_texts[x.pos[0]],
                                env,
                                x.pos[1],
                                toks[e - 1].pos[2],
                            )
                        ):
                            return e
                        j = e
                        continue
                    if n2.rstrip("*") == target:
                        depth += 1 if x.text == "begin" else -1
                        if depth == 0:
                            return e
                    j = e
                    continue
            elif x.kind == "cs" and not dead:
                # ``\end<env>`` 字面端点（csname 合成/旧式）——主流
                # ``_find_env_end`` 同名判据的组内镜像（R1）
                if x.text == "end" + target:
                    depth -= 1
                    if depth == 0:
                        return j + 1
                    j += 1
                    continue
                em = self._grp_env_macro(x)
                if em is not None and em[1].rstrip("*") == target:
                    depth += 1 if em[0] == "env_begin" else -1
                    if depth == 0:
                        return j + 1
            j += 1
        return None

    def _grp_math_end(self: Segmenter, toks: list[Tok], i: int) -> int | None:
        r"""Mathshift 配对（``$$`` 双 token 形）→ 闭界 j（含）；未中 None。"""
        dbl = i + 1 < len(toks) and toks[i + 1].kind == "mathshift"
        j = i + 2 if dbl else i + 1
        n = len(toks)
        while j < n and j - i < _GRP_SCAN_CAP:
            if toks[j].kind == "mathshift":
                if dbl:
                    if j + 1 < n and toks[j + 1].kind == "mathshift":
                        return j + 2
                    j += 1
                    continue
                return j + 1
            j += 1
        return None

    def _grp_delim_end(
        self: Segmenter, toks: list[Tok], i: int, want: str
    ) -> int | None:
        r"""``\\[``/``\\(`` 配对 ``\\]``/``\\)`` → j_end；未中 None。"""
        j = i + 1
        n = len(toks)
        while j < n and j - i < _GRP_SCAN_CAP:
            x = toks[j]
            if x.kind == "cs" and x.text == want:
                return j + 1
            j += 1
        return None

    def _grp_pair_end(
        self: Segmenter, toks: list[Tok], i: int, open_: str, close: str
    ) -> int | None:
        r"""``cs`` 对界块组内配对（``_find_pair_end`` 的 toks 版）→ j_end（含）。

        闭名 cs 或 ``\end{open}`` env 闭形首命中即闭合（块不嵌套——
        ``\end{labellist}`` 混搭形是 ``\end{X}``→``\endX`` 的对价）。
        未中 ``None``（调用方续走 argspec/探针保守路径）。
        """
        n = len(toks)
        j = i
        while j < n and j - i < _GRP_SCAN_CAP:
            x = toks[j]
            if x.kind == "cs" and x.text == close:
                return j + 1
            if x.kind == "cs" and x.text == "end":
                hit = self._grp_envtag(toks, j)
                if hit is not None:
                    if hit[0] == open_:
                        return hit[1]
                    j = hit[1]
                    continue
            j += 1
        return None

    @staticmethod
    def _grp_bal(  # noqa: C901 — 两定界族各一段，平铺即规则
        toks: list[Tok], i: int, *, brace: bool
    ) -> int | None:
        """``{…}``/``[…]`` 平衡组 → 闭界 j（含）；``eol_par``/EOF 止 None。

        主流对价：``_collect_group``（源侧拉取版，``eol_par`` 当内容不判
        段界——两侧 par 规则刻意不同，改一侧前先核对另一侧调用语境）。
        """
        depth = 0
        for j in range(i, len(toks)):
            x = toks[j]
            if x.kind == "eol_par":
                return None
            if brace:
                if x.kind == "lbrace":
                    depth += 1
                elif x.kind == "rbrace":
                    depth -= 1
                    if depth == 0:
                        return j + 1
            elif x.kind == "other":
                if x.text == "[":
                    depth += 1
                elif x.text == "]":
                    depth -= 1
                    if depth == 0:
                        return j + 1
        return None

    def _walk_spec_toks(  # noqa: C901, PLR0911, PLR0912, PLR0915 — 归一槽型各一分支，平铺即三字母表语义并集
        self: Segmenter,
        toks: list[Tok],
        pos: int,
        elems: list[_WSpec] | tuple[_WSpec, ...],
    ) -> _WalkRes:
        r"""物化 token 列上的归一 spec 走参 → ``_WalkRes``。

        列扫走参的单源：``_slots_walk_toks``/``_grp_call_end``/
        ``_grp_probe_end``/``_grp_spec_args_end``/``_grp_spec_walk``（+体尾
        key-arg 槽段）与 ``_grp_bsbs``/``_grp_env_args_end``/``_grp_scan``
        内嵌臂（hyperref ``s+e``/COND ``m``×N/chunk-arg ``*``/accent ``a``）
        全部投影本机——``_WSpec`` 把 slot 字母（``_common``
        槽形表）、argspec ``ArgSpec``、gullet ``Arg`` 三字母表归一到公共
        槽型（归一投影 = ``_slot_elem``/``_aspec_elem``/``_gspec_elem``）。

        语义轴（各面原判一律保留）：``eol_par`` 即参扫终界；``ws``=False
        唯 slot ``s``/``_grp_call_end`` 的 ``*`` 不跳前置 space；可选位
        （``star``/``opt``/``test``/``dpair``-``req``=False）失配过给下
        一元，强制位（``mand``/``egrp``/``name``/``marg``/``dpair``-rR）
        失配整走终止；``role``=``text``/``opt-text`` 不消费停界；
        ``env`` 非空时 ``opt``/``dpair`` 过 ``env_opt_is_format`` 闸
        （``d<>`` 恒版式豁免在归一侧）；``cont_ok`` 的组未闭承
        ``_grp_open_tail`` 跨界续扫态；``no_cs`` 罩 ``test``/``dpair``
        定界符的 cs 禁配（投影侧按原判面定）。

        结果投影：``end`` 各面通用；``cand`` 仅 ``opt``/``mand``/``marg``/
        ``bsbs`` 组参记录（``_grp_spec_walk``/``_grp_probe_end`` 的散文候
        选界、``_grp_bsbs`` 的中/未中区分）；``rem``=toks 走尽/真跨界
        时未完元下标（``_slots_walk_toks`` 的剩余槽列、``_PendRem`` 的
        ``spec``/``ka_slots`` 切片料）；``cont``/``e_rest`` 是跨界续扫态
        与 ``e`` 残件料。流侧拉取对价（``_absorb_slots``/``_absorb_spec``/
        ``_args_tok`` 的 read/unread 账本）不同构，不走本机。
        """
        n = len(toks)
        end = pos
        cand: list[tuple[int, int, int]] = []
        nth = 0
        for ei, el in enumerate(elems):
            k = end
            if el.ws:
                while k < n and toks[k].kind == "space":
                    k += 1
            if k >= n:
                return _WalkRes(end, cand, ei, None, None)  # toks 走尽而参未竟
            x = toks[k]
            if x.kind == "eol_par":
                break  # 参扫终界——不定界参数不跨 \par
            start = end
            kind = el.kind
            if kind == "star":  # ``*`` 可选修饰
                if x.kind == "other" and x.text == "*":
                    end = k + 1
            elif kind == "opt":  # ``[..]`` 可选组
                if x.kind == "other" and x.text == "[":
                    e = self._grp_bal(toks, k, brace=False)
                    if e is None:
                        if el.cont_ok:
                            hit = self._grp_open_tail(toks, k, brace=False)
                            if hit is not None:
                                return _WalkRes(end, cand, ei, hit, None)
                        break
                    if el.role in ("text", "opt-text"):
                        break
                    if el.env is not None and not env_opt_is_format(
                        el.env, self._grp_surfs(toks[k + 1 : e - 1])
                    ):
                        break  # 定理标题正文不收——回吐随主流（F6 同规）
                    cand.append((nth, k, e))
                    end = e
            elif kind == "mand":  # ``{..}`` 强制组（slot ``m``/call/probe 同形）
                if x.kind != "lbrace":
                    break
                e = self._grp_bal(toks, k, brace=True)
                if e is None:
                    if el.cont_ok:
                        hit = self._grp_open_tail(toks, k, brace=True)
                        if hit is not None:
                            return _WalkRes(end, cand, ei, hit, None)
                    break
                cand.append((nth, k, e))  # 记 cand——``_grp_probe_end`` 散文候选界
                end = e
            elif kind == "egrp":  # ``{..}``|``[..]`` 任选强制组（slot ``e``）
                if x.kind != "lbrace" and not (x.kind == "other" and x.text == "["):
                    break
                e = self._grp_bal(toks, k, brace=x.kind == "lbrace")
                if e is None:
                    if el.cont_ok:
                        hit = self._grp_open_tail(toks, k, brace=x.kind == "lbrace")
                        if hit is not None:
                            return _WalkRes(end, cand, ei, hit, None)
                    break
                end = e
            elif kind == "name":  # ``n`` 裸名参：cs 单 token 或 ``{..}``/``[..]`` 组
                if x.kind == "cs":
                    end = k + 1
                elif x.kind == "lbrace" or (x.kind == "other" and x.text == "["):
                    e = self._grp_bal(toks, k, brace=x.kind == "lbrace")
                    if e is None or el.role in ("text", "opt-text"):
                        break
                    end = e
                else:
                    break
            elif kind == "marg":  # ``m``/``v``：组或单 token（cs 止）
                if x.kind == "lbrace" or (x.kind == "other" and x.text == "["):
                    e = self._grp_bal(toks, k, brace=x.kind == "lbrace")
                    if e is None:
                        if el.cont_ok:
                            hit = self._grp_open_tail(toks, k, brace=x.kind == "lbrace")
                            if hit is not None:
                                return _WalkRes(end, cand, ei, hit, None)
                        break
                    if el.role in ("text", "opt-text"):
                        break
                    cand.append((nth, k, e))
                    end = e
                elif x.kind == "cs":
                    break  # 单 token 参不跨 '\'（BUG1 同规）
                elif not el.single_ok or el.role in ("text", "opt-text"):
                    break
                else:
                    end = k + 1
            elif kind == "bsbs":  # ``\\`` 的 ``[dimen]``（``_grp_bsbs`` 内容闸同判据）
                if x.kind == "other" and x.text == "[":
                    e = self._grp_bal(toks, k, brace=False)
                    if e is None or not _GRP_BSBS_CONTENT_RX.fullmatch(
                        self._grp_surfs(toks[k + 1 : e - 1])
                    ):
                        break
                    cand.append((nth, k, e))  # 记 cand——``_grp_bsbs`` 取中/未中区分
                    end = e
            elif kind == "accent":  # ``\c{c}``/``\~n`` 单参
                if x.kind == "lbrace":
                    e = self._grp_bal(toks, k, brace=True)
                    if e is None:
                        break
                    end = e
                elif x.kind in ("letter", "other") or (
                    x.kind == "cs" and len(x.text) == 1
                ):
                    end = k + 1
                else:
                    break
            elif kind == "test":  # ``t`` 测试字符（``no_cs`` 承字母表原判差）
                if x.text == el.test_c and not (el.no_cs and x.kind == "cs"):
                    end = k + 1
            elif (
                kind == "dpair"
            ):  # ``d``/``D``/``r``/``R`` 定界对（``no_cs`` 承字母表原判差——开/闭符 cs 不配）
                if x.text != el.open_c or (el.no_cs and x.kind == "cs"):
                    if el.req:
                        break
                else:
                    k2 = k + 1
                    while (
                        k2 < n
                        and toks[k2].kind != "eol_par"
                        and (
                            toks[k2].text != el.close_c
                            or (el.no_cs and toks[k2].kind == "cs")
                        )
                    ):
                        k2 += 1
                    if k2 >= n:
                        return _WalkRes(end, cand, ei, None, None)
                    if toks[k2].kind == "eol_par":
                        break
                    if el.role in ("text", "opt-text"):
                        break
                    if el.env is not None and not env_opt_is_format(
                        el.env, self._grp_surfs(toks[k + 1 : k2])
                    ):
                        break
                    end = k2 + 1
            elif kind == "embell":  # ``e``：逐枚 ``X{arg}``/``X<tok>``（xparse 修饰参）
                rest = list(el.e_chars)
                tail_pend = False  # 已吃 ``X``、``{arg}``/``<tok>`` 尾位未决
                stop = False
                while rest:
                    k2 = end
                    while k2 < n and toks[k2].kind == "space":
                        k2 += 1
                    if k2 >= n:
                        stop = True
                        break
                    if toks[k2].kind in ("cs", "eol_par") or toks[k2].text not in rest:
                        break
                    rest.remove(toks[k2].text)
                    end = k2 + 1
                    tail_pend = True
                    k2 = end
                    while k2 < n and toks[k2].kind == "space":
                        k2 += 1
                    if k2 >= n:
                        continue  # 尾位未决——下轮符扫统一出 pending
                    tail_pend = False
                    if toks[k2].kind == "lbrace":
                        e = self._grp_bal(toks, k2, brace=True)
                        if e is not None:
                            end = e
                    elif toks[k2].kind not in ("cs", "eol_par"):
                        end = k2 + 1
                if stop:
                    return _WalkRes(
                        end, cand, ei, ("e-arg",) if tail_pend else None, tuple(rest)
                    )
            elif kind == "dseq":  # ``#1<seq>`` 定界参：滑窗 ``_tok_eq`` 比对
                kk = len(el.delim_toks)
                seq: list[int] = []
                k2 = k
                runaway = False
                if x.kind == "lbrace":
                    e = self._grp_bal(toks, k2, brace=True)
                    if e is None:
                        runaway = True
                    else:
                        seq.extend(range(k2, e))
                        k2 = e
                else:
                    seq.append(k2)
                    k2 += 1
                matched = False
                pend_mid = False
                while not runaway and not matched and not pend_mid:
                    if len(seq) >= kk and all(
                        _tok_eq(toks[seq[len(seq) - kk + j2]], el.delim_toks[j2])
                        for j2 in range(kk)
                    ):
                        matched = True
                    elif k2 >= n:
                        pend_mid = True
                    elif toks[k2].kind == "eol_par":
                        runaway = True
                    elif toks[k2].kind == "lbrace":
                        e = self._grp_bal(toks, k2, brace=True)
                        if e is None:
                            runaway = True
                        else:
                            seq.extend(range(k2, e))
                            k2 = e
                    else:
                        seq.append(k2)
                        k2 += 1
                if pend_mid:
                    ctx = [toks[j] for j in seq[max(0, len(seq) - (kk - 1)) :]]
                    return _WalkRes(end, cand, ei, ("delim", ctx), None)
                if not matched:
                    break  # runaway = 整调用止
                end = k2
            elif kind == "ugroup":  # ``#{`` 形：读到 ``lbrace`` 不消费
                k2 = k
                while (
                    k2 < n and toks[k2].kind != "lbrace" and toks[k2].kind != "eol_par"
                ):
                    k2 += 1
                if k2 >= n:
                    return _WalkRes(end, cand, ei, None, None)
                if toks[k2].kind == "eol_par":
                    break
                end = k2
            # ``zero`` 及其余 → 零宽位不消费
            if end > start:
                nth += 1  # 实消费参占序——``_prose_args_of`` 序数同口径
        return _WalkRes(end, cand, None, None, None)

    def _grp_call_end(self: Segmenter, toks: list[Tok], i: int, mand: int) -> int:
        r"""Cs + ``*``? + ``[opt]``≤3 + ``{arg}``≤mand → j_end（``_protect_cs`` 镜像）。

        走参本体 = ``_walk_spec_toks``——``_call_slots(["m"]*mand)``
        槽列（``_PEND_CALL1``/``_PEND_CALL2`` 同形）。
        """
        elems = [_slot_elem(s) for s in _call_slots(["m"] * mand)]
        return self._walk_spec_toks(toks, i + 1, elems).end

    def _grp_keyval_tail_end(self: Segmenter, toks: list[Tok], j: int) -> int:
        r"""``_keyval_tail_end`` 的组内对价——keyval 形 ``{..}`` 组续吃。

        形状门同 ``_KEYVAL_GROUP_RX``：组内 surface join 判 ``key=`` 起头，
        不中即停（组 token 留 surface 主流，同主流回放语义）。``eol_par``
        不跨——space 前跳遇之即非 lbrace 停。
        """
        n = len(toks)
        while True:
            k = j
            while k < n and toks[k].kind == "space":
                k += 1
            if k >= n or toks[k].kind != "lbrace":
                return j
            e = self._grp_bal(toks, k, brace=True)
            if (
                e is None
                or _KEYVAL_GROUP_RX.match(self._grp_surfs(toks[k + 1 : e - 1])) is None
            ):
                return j
            j = e

    def _grp_protect_block_end(self: Segmenter, toks: list[Tok], i: int) -> int:
        r"""``\author[opt]{..}`` 整块保护的组内对价（``_handle_protect_block``）。

        ``{arg}`` 未跟随时 abort——``[opt]`` 段不进覆盖（主流只护 cs 本体
        同规）；命中首 ``{m}`` 后续吃 keyval 形组（aipproc 第二参同护）。
        """
        n = len(toks)
        end = i + 1
        k = i + 1
        while k < n and toks[k].kind == "space":
            k += 1
        if k < n and toks[k].kind == "other" and toks[k].text == "[":
            e = self._grp_bal(toks, k, brace=False)
            if e is not None:
                k = e
                while k < n and toks[k].kind == "space":
                    k += 1
        if k < n and toks[k].kind == "lbrace":
            e = self._grp_bal(toks, k, brace=True)
            if e is not None:
                end = e
        if end > i + 1:
            end = self._grp_keyval_tail_end(toks, end)
        return end

    @staticmethod
    def _grp_skip_ws(toks: list[Tok], j: int) -> int:
        r"""space/eol_par 前跳（``_read_skipws`` 的组内对价）。"""
        while j < len(toks) and toks[j].kind in ("space", "eol_par"):
            j += 1
        return j

    def _grp_tail_end(
        self: Segmenter, toks: list[Tok], i: int, rx: re.Pattern[str]
    ) -> int | None:
        r"""``toks[i:]`` 非文本尾参扫 → j_end；形不合 → None。

        主版 ``_tail_scan_end``（字节正则）的组内对价：surface join 后
        ``_GRP_TAIL_CAP`` 字符窗内匹配，匹配界必须恰在 token 界（切进
        token 内部 → 不匹配）；``eol_par`` 止扫（par 边界不跨）。
        """
        n = len(toks)
        parts: list[str] = []
        bounds = [0]
        j = i
        total = 0
        while j < n and total < _GRP_TAIL_CAP:
            x = toks[j]
            if x.kind == "eol_par":
                break
            s = self._tok_surface(x)
            parts.append(s)
            total += len(s)
            bounds.append(total)
            j += 1
        m = rx.match("".join(parts))
        if m is None or m.end() == 0:
            return None
        e = m.end()
        k = bisect_left(bounds, e)
        if k >= len(bounds) or bounds[k] != e:
            return None  # 匹配界落 token 内（cs 名被尾参切断）——不吃半截
        return i + k

    def _grp_tikz_end(self: Segmenter, toks: list[Tok], i: int) -> int | None:
        r"""组内裸 ``\tikz <path>;`` 的 ``;`` 定界扫描 → j_end；非路径形 → None。

        ``_tikz_tail_end``（字节版）的 token 对价：首非空 token 须是
        cs/``(``/``[``（path 起点族）；``{..}``/``[..]`` 深度内 ``;``
        不算界；``eol_par``/深度外闭括/``\end`` cs 即中止（R8）。
        """
        n = len(toks)
        j = i + 1
        while j < n and toks[j].kind == "space":
            j += 1
        if j >= n or not (
            toks[j].kind == "cs" or (toks[j].kind == "other" and toks[j].text in "([")
        ):
            return None
        depth = 0
        while j < n and j - i < _GRP_SCAN_CAP:
            x = toks[j]
            if x.kind == "eol_par" or (x.kind == "cs" and x.text == "end"):
                return None
            if x.kind == "lbrace" or (x.kind == "other" and x.text == "["):
                depth += 1
            elif x.kind == "rbrace" or (x.kind == "other" and x.text == "]"):
                if depth == 0:
                    return None  # 越过所在组界
                depth -= 1
            elif x.kind == "other" and x.text == ";" and depth == 0:
                return j + 1
            j += 1
        return None

    def _grp_bsbs(self: Segmenter, toks: list[Tok], i: int) -> int | None:
        r"""组内 ``\\`` 的可选 dimen 参 → j_end；``\\[5pt]``/``\\*[2em]`` 命中。

        ``_BSBS_OPT_RX`` 的 token 版：``*``? + ``[atom]``——内容非 dimen
        （``\\[x]`` 形）→ None 回落逐字。走参本体 = ``_walk_spec_toks``
        （``_BSBS_SLOTS`` 槽列同 ``_pend_spec_of`` ``\\`` 行）；cand 命中 =
        ``[dimen]`` 实消费（单 ``*`` 不算）。
        """
        res = self._walk_spec_toks(toks, i + 1, [_slot_elem(s) for s in _BSBS_SLOTS])
        return res.end if res.cand else None

    def _grp_spec_args_end(  # noqa: PLR0913 — 组内走参面（toks/起点/spec/角色/env/开关）原位
        self: Segmenter,
        toks: list[Tok],
        j: int,
        spec: list[ArgSpec],
        roles: tuple[str, ...],
        env: str | None,
        *,
        allow_single_token: bool = True,
    ) -> int:
        r"""Argspec 位序走参的组内 token 版（``_eat_env_args_spec`` 镜像）。

        走参本体 = ``_walk_spec_toks``（``_aspec_elem`` 逐位归一）。返回连
        续消费的非文本参后界——``text``/``opt-text`` 角色或参数缺席处停
        （其后 token 留 surface 主流，同 ``_unread_args`` 语义）。``env``
        非空时可选位过 ``env_opt_is_format`` 闸（定理标题不收——F6 同
        规）；None 则可选位照常消费（命令可选参无标题歧义）。
        ``allow_single_token=False``（探针/thead 路同主流
        ``_args_tok`` 同参）：``m``/``v`` 位不吃裸单 token——
        ``\textcolor red`` 的 ``red`` 是散文不是参。text 位单 token
        恒停（主流 ``_emit_argspec_chunks`` 截停回吐的对价）——
        ``\emph p`` 吃掉 ``p`` 会让 ``ost`` 落 surface 而 ``p`` 隐入
        [[CMD]]（签名面看不见的散字母偷吃）。``e``/``b``/``u``/``g``
        位组内不消费（原判保留——``_args_tok`` 流侧才有对价）。
        """
        elems = [
            _aspec_elem(
                s,
                roles[si] if si < len(roles) else "skip",
                env,
                single_ok=allow_single_token,
            )
            for si, s in enumerate(spec)
        ]
        return self._walk_spec_toks(toks, j, elems).end

    def _argspec_env(
        self: Segmenter, env: str, reg: object | None
    ) -> ArgspecEntry | None:
        r"""Argspec env 条目查询——``_handle_env_begin`` 族表门控同集。"""
        if (
            reg is not None
            or env in VERBATIM_ENVS
            or env in MATH_ENVS
            or env in PROTECTED_ENVS
            or env in ARG_TRANSPARENT_ENVS
            or env in ENV_MANDATORY_ARG
        ):
            return None
        return _tables.argspec_lookup_env(env, cast("set[str]", self.state.pkgs))

    def _grp_env_args_end(
        self: Segmenter,
        toks: list[Tok],
        j: int,
        env: str,
        reg: object | None,
        ae: ArgspecEntry | None,
    ) -> int:
        r"""``\begin{env}``/env_begin 宏端点尾参的组内对价（``_eat_env_args``）。

        ``ae`` 带签名 → ``_grp_spec_args_end`` 位序走参；否则版式 ``[opt]``
        （``env_opt_is_format`` 闸）+ ``ENV_MANDATORY_ARG``/``reg.spec``
        的 ``{m}`` 数吃进 ENVTAG 界——否则 preamble ``{lRLc}`` 这类非文本
        参裸进 surface 被翻译（``Illegal pream-token``，loop1 slots⑤）。
        """
        if ae is not None and ae.signature:
            return self._grp_spec_args_end(
                toks, j, _chunk_spec_cached(ae.signature), ae.arg_roles, env
            )
        mand = _env_mand_count(env, reg)
        # 版式 ``[opt]``（``env_opt_is_format`` 闸）+ ``{m}``×mand——归一走
        # 参元列（``[opt]`` 未闭/闸败即停：mand 位从原位同判 ``[`` 失配）
        j = self._walk_spec_toks(
            toks, j, [_WSpec("opt", env=env), *([_WSpec("mand")] * mand)]
        ).end
        if mand == 0:
            # 列型前导 peek 的组内镜像（R3）——首 ``{..}`` 形似列参即吃进
            n = len(toks)
            k = j
            while k < n and toks[k].kind == "space":
                k += 1
            if k < n and toks[k].kind == "lbrace":
                e = self._grp_bal(toks, k, brace=True)
                if e is not None and looks_like_colspec(
                    self._grp_surfs(toks[k + 1 : e - 1])
                ):
                    j = e
        return j

    def _grp_probe_end(self: Segmenter, toks: list[Tok], i: int) -> _WalkRes | None:
        r"""未知命令探针的组内版（``_handle_unknown_cs``：``[opt]``? + ``{m}``×6、禁单 token 参）。

        任一参数命中 → ``_WalkRes``（``end`` 调用界、``cand`` 逐参界——
        ``_grp_probe_prose_args`` 散文挖掘直取 cand，免同形复扫）；全缺席
        → None。走参本体 = ``_walk_spec_toks``——``_PEND_PROBE`` 槽列同形。
        """
        res = self._walk_spec_toks(toks, i + 1, [_slot_elem(s) for s in _PEND_PROBE])
        return res if res.end > i + 1 else None

    def _grp_arg_prose(self: Segmenter, inner: list[Tok]) -> bool:
        r"""组内 ``{..}`` 参内容的散文判据——``_opaque_arg_prose`` 的 token 级对价。

        组内 token 的 ``pos`` 指调用点/定义体（gen>0 无本段字节），不能
        ``file_texts`` 切片——token 级重建文本：cs token 剔为空白（等价
        字节版 ``\\`` 剥除分支；注释在 token 流本无），其余 ``_tok_surface``
        拼接后过同款 ≥4 连词、非全大写判据。
        """
        text = "".join(" " if t.kind == "cs" else self._tok_surface(t) for t in inner)
        return _prose_word_hit(text)

    def _grp_probe_prose_args(
        self: Segmenter, toks: list[Tok], probe: _WalkRes, name: str
    ) -> list[tuple[int, int]]:
        r"""探针调用 ``toks[i:probe.end]`` 内的散文 ``{..}`` 参 → ``(``{`` 位, ``}`` 后位)`` 列。

        ``_handle_unknown_cs`` 散文挖掘的组内对价：参界直取 ``_grp_probe_end``
        走参记录的 ``cand``（同形复扫已并）——``[o]`` 组非散文槽位不挖
        （``lbrace`` 开位滤除）；``_prose_arg_hit`` 名闸 + keyval/逗号名单/
        裸键列形状门 + 词链判据与流侧 ``_opaque_arg_prose``、组内
        ``_grp_opaque_args`` 同口径（``\\comment`` 吞块 W50、``\\deleted``
        死文本、``\\replaced`` 尾参死文本同罩）。散文参内层由调用方
        ``_grp_scan`` 子扫渲 surface。
        """
        return [
            (a0, a1)
            for nth, a0, a1 in probe.cand
            if toks[a0].kind == "lbrace"
            and _prose_arg_hit(name, nth, self._grp_surfs(toks[a0 + 1 : a1 - 1]))
        ]
