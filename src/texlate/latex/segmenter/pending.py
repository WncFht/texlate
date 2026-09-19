r"""``latex/segmenter`` 子模块——god-class 机械拆分（行为零变）。"""

from __future__ import annotations

from typing import (
    NamedTuple,
)

import texlate.latex.tables as _tables
from texlate.latex.gullet import (
    Arg,
    MacroDef,
    _tok_eq,
)
from texlate.latex.model import (
    PhType,
    ScanWarning,
    Span,
)
from texlate.latex.mouth import (
    Tok,
)
from texlate.latex.tables import (
    BOUNDARY_NAMES,
    BOUNDARY_TAIL,
    CHUNK_ARG_NAMES,
    CHUNK_ARG_SPEC,
    COND_RX,
    DIMEN_TAIL_KIND,
    FILENAME_CHARS,
    INPUT_SCAN_CMDS,
    MAX_GEN,
    PAIR_BLOCK_ALL,
    PAIR_BLOCK_CMDS,
    PROTECT_BLOCK_NAMES,
    PROTECT_NAMES,
    TRANSPARENT_HEAD_SPEC,
)

from ._common import (
    _ENV_CS,
    _GRP_BSBS_CONTENT_RX,
    _GRP_SCAN_CAP,
    _KEYARG_TAIL_DEPTH,
    _KEYARG_TAIL_RX,
    _MATH_DELIM_CS,
    _MATH_OPEN_CS,
    _PEND_CALL1,
    _PEND_CALL2,
    _PEND_PROBE,
    _PROTECT_TYP,
    _SLOT_PAIR_LEN,
    _SLOT_TEST_LEN,
    _TAIL_RX,
    _VERB_LIKE,
    TokenSource,
    _accent_cs,
    _chunk_spec_cached,
    _cite_ref_type,
    _env_ph_type,
    _fams,
    _gspec_elem,
    _inline_lit_cs,
    _ListSource,
    _pend_call_slots,
    _pend_slot_of,
    _slot_elem,
    _WSpec,
)
from .args import (
    _COMMA_LIST_RX,
    _COND_GROUP_ARGS,
    _DEAD_ARG_NAMES,
    _DEAD_TAIL_NAMES,
    _KEYVAL_GROUP_RX,
    _SWALLOW_ARG_NAMES,
)

r"""``Segmenter`` 跨边界待绑参与组 surface 收拢。"""

_IMPORT2 = ("import", "subimport")


# ``_group_surface`` 行序投影——名→判据绑定单源 ``_common._FAM_BIND``
# （``tests/test_dispatch_mirror.py`` 逐名裁决三面族序）；``None`` 动态行 =
# env 宏/opaque 宏/argspec/探针。行序即 ``_group_surface`` 分派序。
_GRP_SURFACE_FAMS: tuple[tuple[str, object], ...] = _fams(
    "verb",
    "env",
    "math-open",
    "cite-ref",
    "protect",
    "href",
    "hyperref",
    "cond",
    "input-scan",
    "env-macro",  # _grp_env_macro：env_begin/env_end 宏端点
    "chunk-arg",  # 头参进 CMD、可译 {arg} 留 surface
    "protect-block",  # \author 族整块 → AUTHOR
    "boundary",  # BOUNDARY_TAIL/DIMEN_TAIL 尾参内嵌本行
    "bsbs",
    "transparent-head",
    "tail",  # 非 BOUNDARY 的 dimen/assign 尾参兜收
    "accent",
    "inline-literal",  # 无参行内字面——argspec/探针前截
    "opaque",  # opaque/math 宏 spec 走参（主流 row18 对价）
    "pair-block",  # cs 对界块组内整段 ENV ph（W29）
    "argspec",
    "probe",  # _grp_probe_end → CMD（散文参挖掘）/逐字
)

# ``_pend_spec_of`` 行序投影（第三面——跨界待绑参槽形分派）。
_PEND_SPEC_FAMS: tuple[tuple[str, object], ...] = _fams(
    "verb",
    "env",
    "math-delim",
    "cite-ref",
    "protect",
    "href",
    "hyperref",
    "cond",
    "input-scan",
    "env-macro",
    "chunk-arg",  # 头参槽（*?+[opt] 等非文本位）
    "protect-block",  # [opt]{m} 槽
    "boundary",  # BOUNDARY_TAIL 位序槽内嵌本行
    "bsbs",
    "transparent-head",
    "accent",
    "inline-literal",  # 无参——不吸界外 token
    "opaque",  # opaque/math 宏 spec 走参（_grp_spec_walk 余量臂）
    "pair-block",  # 对界 cs 无槽形——不吸界外 token
    "argspec",
    "keyarg",  # _keyarg_tail 宏体尾 key-arg
    "probe",  # _PEND_PROBE 槽
)


class _PendRem(NamedTuple):
    r"""``_grp_spec_walk`` 组末余量——跨界待绑位描述（``_absorb_spec`` 消费）。

    ``spec``/``cont`` = 未走 gullet ``Arg`` 尾段与首参续扫态
    （``("delim",滑窗尾列)``/``("e-arg",)``/``("grp",定界族,残深)``）；
    ``ka_slots``/``ka_cont``/``ka`` = 体尾 key-arg 剩余槽、首槽 ``[`` 组
    续收态与告警名（``""`` = 无）。
    """

    spec: list
    cont: tuple | None
    ka_slots: list[str]
    ka_cont: tuple | None
    ka: str


class _Pending:
    def _slots_walk_toks(
        self, toks: list[Tok], j: int, slots: list[str] | tuple[str, ...]
    ) -> list[str] | None:
        r"""槽形在组内 token 列上的推行 → 剩余槽列 / ``None``。

        走参本体 = ``_walk_spec_toks``（槽字母经 ``_slot_elem`` 归一）。
        ``toks`` 耗尽而槽未尽 → 返回剩余槽列（调用点界外有待绑参——
        ``_absorb_slots`` 从流里拉回）；中途失配/``eol_par``/组未闭 →
        调用已完结，``None``。可选槽（s/o/b/d/t）失配过给下一槽；强制
        槽（m/e/a）失配 = 终止。
        """
        res = self._walk_spec_toks(toks, j, [_slot_elem(s) for s in slots])
        return list(slots[res.rem :]) if res.rem is not None else None

    def _absorb_slots(  # noqa: C901, PLR0912, PLR0915 — 槽字母各一分支，平铺即流侧列扫对价
        self, src: TokenSource, fid: int, slots: list[str]
    ) -> list[Tok]:
        r"""槽形从 ``read()`` 流吸参 → 已消费 token 列（拉取序，可空）。

        ``_slots_walk_toks``（``_walk_spec_toks`` 列扫投影）的源侧对价——
        拉取契约不同构不入归一：失配 token 与其前的 ws 全量 ``unread``
        回放（``_protect_cs`` ``pulled`` 约定同款）；``eol_par``/异
        fid/``gen>0`` token 是参扫边界（回放、不消费）。
        """
        pulled: list[Tok] = []
        committed = 0

        def unpull(x: Tok | None = None) -> None:
            tail = pulled[committed:]
            if x is not None:
                tail = [*tail, x]
            if tail:
                src.unread(tail)
            del pulled[committed:]

        def peek() -> Tok | None:
            while True:
                x = src.read()
                if x is None:
                    return None
                if x.kind == "space":
                    pulled.append(x)
                    continue
                if x.kind == "eol_par" or x.gen > 0 or x.pos[0] != fid:
                    src.unread([x])
                    return None
                return x

        for s in slots:
            if s == "s":
                x = src.read()  # ``*`` 槽不跳 ws（call_end 同规）
                if (
                    x is not None
                    and x.kind == "other"
                    and x.text == "*"
                    and x.gen == 0
                    and x.pos[0] == fid
                ):
                    pulled.append(x)
                    committed = len(pulled)
                elif x is not None:
                    src.unread([x])
                continue
            x = peek()
            if x is None:
                unpull()
                break
            if s == "o":
                if x.kind == "other" and x.text == "[":
                    hit = self._collect_group(src, x, brace=False)
                    if hit is None:
                        unpull()
                        break
                    inner, closer = hit
                    pulled.extend((x, *inner, closer))
                    committed = len(pulled)
                else:
                    unpull(x)
                continue
            if s == "b":
                if x.kind == "other" and x.text == "[":
                    hit = self._collect_group(src, x, brace=False)
                    if hit is None:
                        unpull()
                        break
                    inner, closer = hit
                    if not _GRP_BSBS_CONTENT_RX.fullmatch(self._grp_surfs(inner)):
                        src.unread([x, *inner, closer])
                        unpull()
                        break
                    pulled.extend((x, *inner, closer))
                    committed = len(pulled)
                else:
                    unpull(x)
                continue
            if s == "m":
                if x.kind != "lbrace":
                    unpull(x)
                    break
                hit = self._collect_group(src, x, brace=True)
                if hit is None:
                    unpull()
                    break
                inner, closer = hit
                pulled.extend((x, *inner, closer))
                committed = len(pulled)
                continue
            if s == "n":
                # 裸名参（``\setlength\parskip``）：cs 单 token 或 {..}/[..] 组
                if x.kind == "cs":
                    pulled.append(x)
                    committed = len(pulled)
                    continue
                if x.kind != "lbrace" and not (x.kind == "other" and x.text == "["):
                    unpull(x)
                    break
                hit = self._collect_group(src, x, brace=x.kind == "lbrace")
                if hit is None:
                    unpull()
                    break
                inner, closer = hit
                pulled.extend((x, *inner, closer))
                committed = len(pulled)
                continue
            if s == "e":
                if x.kind != "lbrace" and not (x.kind == "other" and x.text == "["):
                    unpull(x)
                    break
                hit = self._collect_group(src, x, brace=x.kind == "lbrace")
                if hit is None:
                    unpull()
                    break
                inner, closer = hit
                pulled.extend((x, *inner, closer))
                committed = len(pulled)
                continue
            if s == "a":
                if x.kind == "lbrace":
                    hit = self._collect_group(src, x, brace=True)
                    if hit is None:
                        unpull()
                        break
                    inner, closer = hit
                    pulled.extend((x, *inner, closer))
                    committed = len(pulled)
                elif x.kind in ("letter", "other") or (
                    x.kind == "cs" and len(x.text) == 1
                ):
                    pulled.append(x)
                    committed = len(pulled)
                else:
                    unpull(x)
                    break
                continue
            if s.startswith("d") and len(s) == _SLOT_PAIR_LEN:
                if x.text == s[1]:
                    seq = [x]
                    while True:
                        y = src.read()
                        if (
                            y is None
                            or y.kind == "eol_par"
                            or y.gen > 0
                            or y.pos[0] != fid
                        ):
                            src.unread([*seq, *([y] if y is not None else [])])
                            seq = []
                            break
                        seq.append(y)
                        if y.text == s[2]:
                            break
                    if not seq:
                        unpull()
                        break
                    pulled.extend(seq)
                    committed = len(pulled)
                else:
                    unpull(x)
                continue
            if s.startswith("t") and len(s) == _SLOT_TEST_LEN:
                if x.kind != "cs" and x.text == s[1]:
                    pulled.append(x)
                    committed = len(pulled)
                else:
                    unpull(x)
                continue
        return pulled[:committed]

    @staticmethod
    def _absorb_grp_tail(
        src: TokenSource, fid: int, *, brace: bool, depth: int
    ) -> list[Tok] | None:
        r"""跨界已开 ``{``/``[`` 组的流侧续收 → 新拉 token 列 / ``None``。

        ``_collect_group`` 的续段对价：``eol_par`` 是组内容物不判界；
        ``gen>0``/异 fid/EOF 先至 → 已读全量回吐、``None``（组未闭即参
        失配）。``depth`` 承 ``_grp_open_tail`` 组末残深从此续计。
        """
        seq: list[Tok] = []
        while True:
            y = src.read()
            if y is None or y.gen > 0 or y.pos[0] != fid:
                if y is not None:
                    src.unread([y])
                src.unread(seq)
                return None
            seq.append(y)
            if brace:
                is_open = y.kind == "lbrace"
                is_close = y.kind == "rbrace"
            else:
                is_open = y.kind == "other" and y.text == "["
                is_close = y.kind == "other" and y.text == "]"
            if is_open:
                depth += 1
            elif is_close:
                depth -= 1
            if depth == 0:
                return seq

    def _absorb_spec(  # noqa: C901, PLR0912, PLR0915 — spec 字母各一分支，平铺即流侧 _grp_spec_walk 对价
        self, src: TokenSource, fid: int, spec: list, cont: tuple | None = None
    ) -> list[Tok]:
        r"""Gullet ``Arg`` spec 从 ``read()`` 流吸参 → 已消费 token 列（可空）。

        ``_grp_spec_walk``（``_walk_spec_toks`` 列扫投影）的源侧对价
        （``_absorb_slots`` 同款拉取规——拉取契约不同构不入归一）：
        ``cont`` 承 ``_PendRem.cont`` 首参续扫态（``("grp",族,残深)`` 已开
        组续收/``("delim",尾列)`` 滑窗续扫/``("e-arg",)`` 已吃 ``X`` 的尾
        位续决）；界 token（``eol_par``/``gen>0``/异 fid）与未提交 ws 全量
        ``unread`` 回放。``m``/``o`` 组参走 ``_collect_group``（``eol_par``
        组内是内容物）、``delim`` 滑窗 ``_tok_eq``（runaway = 整调用止）、
        ``until_group`` 读到 ``lbrace`` 回吐不消费、其余 kind 零宽位。
        """
        pulled: list[Tok] = []
        committed = 0

        def unpull(x: Tok | None = None) -> None:
            tail = pulled[committed:]
            if x is not None:
                tail = [*tail, x]
            if tail:
                src.unread(tail)
            del pulled[committed:]

        def peek() -> Tok | None:
            while True:
                x = src.read()
                if x is None:
                    return None
                if x.kind == "space":
                    pulled.append(x)
                    continue
                if x.kind == "eol_par" or x.gen > 0 or x.pos[0] != fid:
                    src.unread([x])
                    return None
                return x

        def e_arg_tail() -> None:
            # ``e`` 参已吃 ``X`` 的 ``{arg}``/``<tok>`` 尾位（可缺省——
            # cs/界 token/缺席只留符，不算失配）
            nonlocal committed
            z = peek()
            if z is None:
                unpull()
            elif z.kind == "lbrace":
                hit = self._collect_group(src, z, brace=True)
                if hit is None:
                    unpull()
                else:
                    inner, closer = hit
                    pulled.extend((z, *inner, closer))
                    committed = len(pulled)
            elif z.kind != "cs":
                pulled.append(z)
                committed = len(pulled)
            else:
                src.unread([z])

        for ai, a in enumerate(spec):
            kind = a.kind
            if kind in ("m", "o"):
                if ai == 0 and cont is not None and cont[0] == "grp":
                    hit0 = self._absorb_grp_tail(src, fid, brace=cont[1], depth=cont[2])
                    if hit0 is None:
                        unpull()
                        break
                    pulled.extend(hit0)
                    committed = len(pulled)
                    continue
                x = peek()
                if x is None:
                    unpull()
                    break
                if kind == "m":
                    if x.kind == "lbrace" or (x.kind == "other" and x.text == "["):
                        hit = self._collect_group(src, x, brace=x.kind == "lbrace")
                        if hit is None:
                            unpull()
                            break
                        inner, closer = hit
                        pulled.extend((x, *inner, closer))
                        committed = len(pulled)
                    elif x.kind == "cs":
                        unpull(x)
                        break  # 单 token 参不跨 '\'
                    else:
                        pulled.append(x)
                        committed = len(pulled)
                    continue
                if x.kind == "other" and x.text == "[":
                    hit = self._collect_group(src, x, brace=False)
                    if hit is None:
                        unpull()
                        break
                    inner, closer = hit
                    pulled.extend((x, *inner, closer))
                    committed = len(pulled)
                else:
                    unpull(x)
                continue
            if kind == "star":
                x = peek()
                if x is None:
                    unpull()
                    break
                if x.kind == "other" and x.text == "*":
                    pulled.append(x)
                    committed = len(pulled)
                else:
                    unpull(x)
                continue
            if kind == "e" and a.delim:
                rest = list(dict.fromkeys(d.text for d in a.delim))
                if ai == 0 and cont is not None and cont[0] == "e-arg":
                    e_arg_tail()
                while rest:
                    x = peek()
                    if x is None:
                        unpull()
                        break
                    if x.kind == "cs" or x.text not in rest:
                        unpull(x)
                        break
                    rest.remove(x.text)
                    pulled.append(x)
                    committed = len(pulled)
                    e_arg_tail()
                continue
            if kind == "delim" and a.delim:
                kk = len(a.delim)
                # 滑窗续扫态：ctx = 组内已吃尾列（比对用，不在 pulled——
                # 已属组内 toks）；新拉 token 同进 seq（窗比对）与 pulled
                seq: list[Tok] = (
                    list(cont[1])
                    if ai == 0 and cont is not None and cont[0] == "delim"
                    else []
                )
                runaway = False
                if not seq:
                    x = peek()
                    if x is None:
                        unpull()
                        break
                    if x.kind == "lbrace":
                        hit = self._collect_group(src, x, brace=True)
                        if hit is None:
                            unpull()
                            break
                        inner, closer = hit
                        seq.extend((x, *inner, closer))
                        pulled.extend((x, *inner, closer))
                    else:
                        seq.append(x)
                        pulled.append(x)
                matched = False
                while not runaway and not matched:
                    if len(seq) >= kk and all(
                        _tok_eq(seq[len(seq) - kk + j2], a.delim[j2])
                        for j2 in range(kk)
                    ):
                        matched = True
                        continue
                    y = src.read()
                    if y is None or y.kind == "eol_par" or y.gen > 0 or y.pos[0] != fid:
                        if y is not None:
                            src.unread([y])
                        runaway = True
                    elif y.kind == "lbrace":
                        hit = self._collect_group(src, y, brace=True)
                        if hit is None:
                            runaway = True
                        else:
                            inner, closer = hit
                            seq.extend((y, *inner, closer))
                            pulled.extend((y, *inner, closer))
                    else:
                        seq.append(y)
                        pulled.append(y)
                if not matched:
                    unpull()
                    break
                committed = len(pulled)
                continue
            if kind == "until_group":
                x = peek()
                if x is None:
                    unpull()
                    break
                if x.kind == "lbrace":
                    src.unread([x])  # ``{`` 不消费——零宽位成立、组留主流
                    committed = len(pulled)
                    continue
                pulled.append(x)
                found = False
                while True:
                    y = src.read()
                    if y is None or y.kind == "eol_par" or y.gen > 0 or y.pos[0] != fid:
                        if y is not None:
                            src.unread([y])
                        break
                    if y.kind == "lbrace":
                        src.unread([y])
                        found = True
                        break
                    pulled.append(y)
                if not found:
                    unpull()
                    break
                committed = len(pulled)
                continue
            # 其余（literal_match/eq/空 delim/brace_after 形）→ 零宽位不消费
        return pulled[:committed]

    def _keyarg_tail(  # noqa: C901, PLR0912 — 体形态分派 + key-arg 判定，平铺即规则
        self, m: object, src: TokenSource, depth: int = 0
    ) -> str | None:
        r"""宏体尾 cs 解析到 key-arg 名（``\def\x{..\label}`` 形）→ 名 / ``None``。

        ``MacroDef.body`` = token 列（尾 cs = 最后非空白 token——``{..}``
        结尾即体尾是组不是 cs，不算待绑）；``body: str`` 登记体 = 字符串
        （``_KEYARG_TAIL_RX``）；``\\let`` 快照 ``Tok``/原语名 ``str`` 直取。
        尾 cs 再登记成宏 → 递归一层（``\\a``→``\\b``→``\\ref`` 别名链，
        深 ≤4 防环）。
        """
        if depth >= _KEYARG_TAIL_DEPTH or m is None:
            return None
        name: str | None = None
        body = getattr(m, "body", None)
        if isinstance(body, list):
            for x in reversed(body):
                if x.kind in ("space", "eol_par"):
                    continue
                if x.kind == "cs":
                    name = x.text
                break
        elif isinstance(body, str):
            mm = _KEYARG_TAIL_RX.search(body)
            if mm is not None:
                name = mm.group(1)
        elif isinstance(m, Tok):
            if m.kind == "cs":
                name = m.text
        elif isinstance(m, str):
            name = m
        if name is None:
            return None
        if _cite_ref_type(name) is not None or name in PROTECT_NAMES:
            return name
        m2 = self._resolve_macro(src, name)
        if m2 is None or m2 is m:
            return None
        return self._keyarg_tail(m2, src, depth + 1)

    def _cite_ref_mand(self, name: str) -> int:
        r"""cite/ref 名的强制参数目——argspec 签名优先，无条目回落 1。

        ``\joref{a}{j}{v}{p}{y}``/``\crefrange{a}{b}`` 这类多参书目宏：
        硬编 ``mand=1`` 只保首参、尾参 ``{b}``/``{y}`` 漏进 chunk——签名
        里 ``m``/``v``/``n`` 位计数目即真参目（``o``/``s`` 由 ``_protect_cs``
        自身的星/可选步覆盖）。``\cite`` ``o m`` → 1，行为不变。
        """
        e = _tables.argspec_lookup(name, self.state.pkgs)
        if e is None or not e.signature:
            return 1
        spec = _chunk_spec_cached(e.signature)
        return max(1, sum(1 for s in spec if s.kind in ("m", "v", "n")))

    def _pend_spec_of(  # noqa: C901, PLR0911, PLR0912 — _group_surface 分派行序镜像，平铺即语义
        self, name: str, src: TokenSource
    ) -> tuple[list[str] | MacroDef | None, str]:
        r"""组内 cs → 待绑参槽形/登记 opaque 宏 + key-arg 名（``_group_surface`` 各行镜像）。

        ``(None, "")`` = 该 cs 无跨界待绑形（verb 定界体/``\\if`` 族/
        数学定界/env 端点宏/env 尾参另一机制）。``MacroDef`` 首元 =
        opaque/math 宏——探针槽形表达不了 spec fidelity（``m`` 可吃单
        token/``[`` 组、``delim``/``e``/``until_group`` 无槽字母），交
        ``_grp_spec_walk`` 余量臂。key-arg 名非空 = cite/ref/PROTECT/
        宏体尾 key-arg——吸纳后仍未绑到 ``{key}`` 时 ``keyarg_unbound``
        告警。
        """
        if name in _VERB_LIKE:
            return None, ""  # 定界体无法 token 配对回吸
        if name in _ENV_CS:
            return ["m"], ""
        if name in _MATH_DELIM_CS:
            return None, ""
        if _cite_ref_type(name) is not None:
            return [
                "s",
                "o",
                "o",
                "o",
                *(["m"] * self._cite_ref_mand(name)),
            ], name
        if name in PROTECT_NAMES:
            return _pend_call_slots(name), name
        if name == "href":
            return ["m"], ""  # {url} 参；{text} 可译留主流
        if name == "hyperref":
            return ["s", "e"], ""
        if COND_RX.match(name):
            # ``\iftoggle`` 族名/表达式槽是强制 ``{..}`` 参——组尾未绑时
            # 跨界吸回（主流 ``_handle_cond`` 的 ``_COND_GROUP_ARGS`` 白名单
            # 对价）；表外 ``\ifx``/``\else``/``\fi``/``\newif`` 旗标无花括号
            # 名参，``{..}`` 是分支散文非名槽——维持无槽形。
            nslots = _COND_GROUP_ARGS.get(name, 0)
            return (["m"] * nslots if nslots else None), ""
        if name in INPUT_SCAN_CMDS:
            return (list(_PEND_CALL2) if name in _IMPORT2 else list(_PEND_CALL1)), ""
        m = self._resolve_macro(src, name)
        if getattr(m, "kind", "") in ("env_begin", "env_end"):
            return None, ""  # env 尾参走 ``_grp_env_args_end`` 另一机制
        if name in CHUNK_ARG_NAMES:
            # 头参槽（``*``? + 可译位前的非文本位——``[opt]``/类型名）；
            # 可译 ``{arg}`` 本身不吸——须留主流（主流字面前缀同位）
            spec_s, tidx = CHUNK_ARG_SPEC.get(name, ("om", 1))
            slots = ["s"]
            for s2 in _chunk_spec_cached(spec_s)[:tidx]:
                sl = _pend_slot_of(s2)
                if sl is None:
                    break
                slots.append(sl)
            return slots, ""
        if name in PROTECT_BLOCK_NAMES:
            return ["o", "m"], ""  # ``[opt]``?``{arg}``——keyval 续组仅组内消费
        if name in BOUNDARY_NAMES:
            spec = BOUNDARY_TAIL.get(name)
            if spec is None:
                return None, ""
            # 强制参位按位映射槽字母（``n``→``"n"`` 裸名槽——``m`` 不跨 ``\``）
            mslots = [
                "n" if a.kind == "n" else "m" for a in spec if a.kind in ("m", "v", "n")
            ]
            return ["s", "o", "o", "o", *mslots], ""
        if name == "\\":
            return ["s", "b"], ""
        if name in TRANSPARENT_HEAD_SPEC:
            return ["o", "m"], ""  # {red} 头参非文本；{text} 留主流
        if _accent_cs(name):
            return ["a"], ""
        if _inline_lit_cs(name):
            # 行内字面无参——零槽形防误吸（``\5``/``\_``/字体开关名下
            # argspec 假条目不得领槽把界外散文拉进组）
            return None, ""
        if getattr(m, "kind", "") in ("opaque", "math"):
            # 登记 opaque/math 宏（``_grp_scan`` opaque 行同位）：``m.spec``
            # 位序走参决定真待绑尾——探针 ``o m×6`` 槽把 spec 外 ``{..}``
            # 误吸进组尾（登记宏 nargs 越界过吸）
            return m, ""
        if name in PAIR_BLOCK_ALL:
            # 对界块开/闭 cs 无槽形——``\pinlabel{tex}`` 等体 token
            # 留主流（探针槽会误吸界外 pinlabel 参进组）
            return None, ""
        # 宏表登记名不吃 argspec（主流 ``_handle_unknown_cs`` ``m is None``
        # 闸同规——登记名走下方 keyarg/探针，包签名不得领槽）
        e = _tables.argspec_lookup(name, self.state.pkgs) if m is None else None
        if e is not None:
            if e.policy in ("literal", "transparent"):
                return None, ""
            spec2 = _chunk_spec_cached(e.signature)
            if e.policy == "chunk-arg":
                slots: list[str] = []
                for si, s2 in enumerate(spec2):
                    role = e.arg_roles[si] if si < len(e.arg_roles) else "skip"
                    if role in ("text", "opt-text"):
                        break  # 可译参位起不吸——文本须留主流
                    sl = _pend_slot_of(s2)
                    if sl is None:
                        break
                    slots.append(sl)
                return slots or None, ""
            # protect/key/verbatim/boundary → 整调用 _grp_call_end 形
            # 强制位按位映射（``n`` 裸名参槽——``m`` 槽不跨 ``\``）
            mslots = [
                "n" if s2.kind == "n" else "m"
                for s2 in spec2
                if s2.kind in ("m", "v", "n")
            ]
            return ["s", "o", "o", "o", *mslots], ""
        ka = self._keyarg_tail(m, src)
        if ka is not None:
            return _pend_call_slots(ka), ka
        return list(_PEND_PROBE), ""

    def _grp_pending(self, src: TokenSource) -> tuple[list[str] | _PendRem, str] | None:
        r"""组尾待绑参检测 → ``(剩余槽列/_PendRem, keyarg 名)`` / ``None``。

        右起扫 ``_open_toks`` 首个有槽形/登记 opaque 宏的 cs，其参扫须吃
        到 toks 末才算 pending（中途被 token 终止 = 调用已完结）。命中即
        返——更早的 cs 不可能 pending：其参扫必经本 cs token 而强制槽遇
        cs 即止。opaque/math 宏走 ``_grp_spec_walk``——``_PendRem`` 余量
        描述未完 spec 尾段与续扫态（槽形表达不了的 fidelity 位）。
        """
        toks = self._open_toks
        for i in range(len(toks) - 1, -1, -1):
            x = toks[i]
            if x.kind != "cs":
                continue
            pend, ka = self._pend_spec_of(x.text, src)
            if pend is None:
                continue
            if isinstance(pend, list):
                rem = self._slots_walk_toks(toks, i + 1, pend)
                return (rem, ka) if rem else None
            rem2 = self._grp_spec_walk(toks, i, pend)[2]
            return (rem2, rem2.ka) if rem2 is not None else None
        return None

    def _absorb_pending(  # noqa: C901 — 槽列/spec 双臂各一序，平铺即规则
        self, t: Tok, src: TokenSource
    ) -> bool:
        r"""组尾待绑参吸纳：``t``（界外首 token）回流作首候选，拉参入组。

        成功 → token 并入 ``_open_toks``、``_open_vspan``/``_open_origin``
        延到吸纳末位（``[[EXPAND]]`` 体覆盖 ``\\r{key}`` 全调用点）、
        返 ``True``（t 已入组不再主流分派）；未吸到 → 流复原、``False``。
        ``_PendRem`` 命中 = opaque/math 宏 spec 走参余量——``_absorb_spec``
        续 spec 尾段后 ``_absorb_slots`` 续体尾 key-arg 槽（``_grp_opaque_
        args`` 的流侧对价；``ka_cont`` 记 ``[`` 组跨界续收）。key-arg 族待
        绑而无 ``{``/``[`` 参落位 → ``keyarg_unbound`` 告警（含空 got——
        收组后将产 cs-only 保护面，同属漏参信号）。
        """
        o = self._open_origin
        hit = self._grp_pending(src)
        if hit is None:
            return False
        pend, ka = hit
        src.unread([t])  # t 回流作首候选——槽列完整后统一拉取
        if isinstance(pend, _PendRem):
            got = self._absorb_spec(src, o[0], pend.spec, pend.cont)
            ka_got: list[Tok] = []
            ks = pend.ka_slots
            if pend.ka_cont is not None:
                # key-arg 首槽 ``[`` 组跨界续收——``]`` 落位后余槽照走
                tail = self._absorb_grp_tail(
                    src, o[0], brace=pend.ka_cont[1], depth=pend.ka_cont[2]
                )
                if tail is None:
                    ks = []
                else:
                    ka_got.extend(tail)
                    ks = ks[1:]
            if ks:
                ka_got.extend(self._absorb_slots(src, o[0], ks))
            got += ka_got
            warn_pool = ka_got  # spec 参非 key 本体——告警只看 keyarg 落位
        else:
            got = self._absorb_slots(src, o[0], pend)
            warn_pool = got
        if ka and not any(
            x.kind == "lbrace" or (x.kind == "other" and x.text == "[")
            for x in warn_pool
        ):
            # key-arg 参没绑到（``*``/``[opt]`` 不算 key 本体；空 got =
            # 紧邻 token 全非参——收组走 cs-only 保护）——告警留痕
            self.state.warnings.append(
                ScanWarning("keyarg_unbound", len(self.vt), f"\\{ka} 尾参缺席")
            )
        if not got:
            x = src.read()  # 回吐复原后队首即 t——取回交主流分派
            if x is not None and x is not t:
                src.unread([x])
            return False
        self._open_toks.extend(got)
        end_pos = max(x.pos[2] for x in got)
        if end_pos > self._cons(o[0]):
            vext = self._cover_to(o[0], end_pos)
            if self._open_vspan is not None:
                self._open_vspan = Span(self._open_vspan.start, vext.end)
            self._open_origin = (o[0], o[1], end_pos)
        return True

    def _grp_delim_body_end(self, toks: list[Tok], i: int, j: int) -> int | None:
        r"""``toks[j]`` = 定界 token 的逐字闭界扫描 → j_end；未闭 → None。

        ``_handle_verb``/``_protect_cs`` 定界支的组内镜像：cs 定界
        （``\\``）由下一 cs token 闭合，其余按 ``kind+text`` 同符配对；
        ``eol_par`` 与盖了源换行的 space token 是 EOL 上限（W9 同义——
        定界搜索不过行）。
        """
        d = toks[j]
        n = len(toks)
        k = j + 1
        while k < n and k - i < _GRP_SCAN_CAP:
            x = toks[k]
            if x.kind == "eol_par" or (
                x.kind == "space"
                and "\n" in self.file_texts[x.pos[0]][x.pos[1] : x.pos[2]]
            ):
                return None
            if d.kind == "cs":
                if x.kind == "cs":
                    return k + 1
            elif x.kind == d.kind and x.text == d.text:
                return k + 1
            k += 1
        return None

    def _grp_verb_end(self, toks: list[Tok], i: int) -> int | None:
        r"""组内 ``\verb|..|``/``\verb*``/``\lstinline[opt]|..|``/``{..}`` → j_end。

        ``_handle_verb`` 的组内镜像（组内无文件字节可扫——定界/配对全在
        token 列上）：``verb*`` 星与 ``lstinline`` 的 ws+``[opt]`` 前缀先吃；
        定界 token 为 space/eol_par/EOF → ``None``（逐字回落）。``{..}``
        配对形走 ``_grp_bal``——``\\}``/``\\{`` 是 cs token 不计深，
        ``%`` 不成 token，配对语义与字节版 verbatim 一致。
        """
        n = len(toks)
        name = toks[i].text
        j = i + 1
        if name.startswith("verb") and j < n and toks[j].text == "*":
            j += 1
        if name == "lstinline":
            j = self._grp_skip_ws(toks, j)
            if j < n and toks[j].kind == "other" and toks[j].text == "[":
                e = self._grp_bal(toks, j, brace=False)
                if e is not None:
                    j = self._grp_skip_ws(toks, e)
        if j >= n or toks[j].kind in ("space", "eol_par"):
            return None
        if toks[j].kind == "lbrace":
            return self._grp_bal(toks, j, brace=True)
        return self._grp_delim_body_end(toks, i, j)

    @staticmethod
    def _grp_open_tail(
        toks: list[Tok], i: int, *, brace: bool
    ) -> tuple[str, bool, int] | None:
        r"""``_grp_bal`` 否决的细分 → 跨界续扫态 / ``None``（失配终止）。

        同口径重数深度：``eol_par`` 穿组 → ``None``（参扫终界同规）；
        深度未归零走到列尾 = 组真跨界 → ``("grp", 定界族, 残深)`` 交
        ``_absorb_grp_tail`` 流侧续收（``[..]`` 版式组在 def 体内不需
        配平——``\vv{pre \foo[ww}`` 实形，``{`` 组同理备齐）。
        """
        depth = 0
        for x in toks[i:]:
            if x.kind == "eol_par":
                return None
            if brace:
                if x.kind == "lbrace":
                    depth += 1
                elif x.kind == "rbrace":
                    depth -= 1
            elif x.kind == "other":
                if x.text == "[":
                    depth += 1
                elif x.text == "]":
                    depth -= 1
            if depth == 0:
                return None
        return ("grp", brace, depth) if depth else None

    def _grp_spec_walk(
        self, toks: list[Tok], i: int, m: object
    ) -> tuple[int, list[tuple[int, int, int]], _PendRem | None]:
        r"""Opaque/math 宏 ``m.spec`` + 体尾 key-arg 槽的组内位序走参。

        → ``(参末位, 散文候选界列, 跨界余量)``。``_handle_opaque_macro``+
        ``_args_tok`` 的组内 toks 对价。走参本体 = ``_walk_spec_toks``
        （gullet ``Arg`` 经 ``_gspec_elem`` 归一）——``m``/``o`` 组未闭
        承 ``_grp_open_tail`` 跨界续扫态（``cont_ok``）。体尾 key-arg cs
        （``\def\r{\ref}`` 形）续按 ``_pend_call_slots`` 槽形吸调用点
        ``{key}``——同机第二段走参（ka-``o`` 未闭承续收态、``s``/``m``
        失配即终止不追）。

        余量 ``None`` = 调用在组内完结/失配终止；``_PendRem`` = toks 走尽
        而调用未竟（``_grp_pending`` 臂消费）：``spec`` 未走 ``Arg`` 尾段
        （``e`` 残件只剩未吃定界符）、``cont`` 首参续扫态、``ka_slots``/
        ``ka_cont``/``ka`` = key-arg 剩余槽、``[`` 组续收态与告警名——
        流侧对价 = ``_absorb_spec`` + ``_absorb_slots``。
        """
        ka = self._keyarg_tail(m, _ListSource([]))
        ka_slots = _pend_call_slots(ka) if ka is not None else []
        spec = list(getattr(m, "spec", []))
        res = self._walk_spec_toks(toks, i + 1, [_gspec_elem(a) for a in spec])
        end, cand = res.end, res.cand
        rem: _PendRem | None = None
        if res.rem is not None:
            if res.e_rest is not None:
                resid = Arg(
                    "e", delim=[Tok("other", c, (-1, -1, -1)) for c in res.e_rest]
                )
                rem = _PendRem(
                    [resid, *spec[res.rem + 1 :]],
                    res.cont,
                    ka_slots,
                    None,
                    ka or "",
                )
            else:
                rem = _PendRem(spec[res.rem :], res.cont, ka_slots, None, ka or "")
        elif ka is not None:
            kres = self._walk_spec_toks(
                toks,
                end,
                [_slot_elem(s, cont_ok=s == "o") for s in ka_slots],
            )
            end = kres.end
            if kres.rem is not None:
                rem = _PendRem([], None, ka_slots[kres.rem :], kres.cont, ka)
        return end, cand, rem

    def _grp_opaque_args(
        self, toks: list[Tok], i: int, name: str, m: object
    ) -> tuple[int, list[tuple[int, int]]]:
        r"""Opaque/math 宏 ``m.spec`` 的组内位序走参 → ``(参末位, 散文参界列)``。

        走参本体 = ``_grp_spec_walk``（跨界余量归 ``_grp_pending`` 臂，组内
        surface 只见完结调用——``_grp_scan`` 在收组后对完整 toks 重走）。
        散文参界 = 实消费 ``{``/``[``-open 组参过判据的 ``(开位, 闭后位)``
        列——``_opaque_arg_prose`` 判据的 token 级对价：``_SWALLOW/_DEAD``
        名闸 + ``_DEAD_TAIL`` 首参限 + keyval/逗号名单形状门 +
        ``_grp_arg_prose`` 词链判据；``e``/``u``/单 token 参无散文槽位
        （主流 ``a.fs``/``a.cs`` 门同界）。
        """
        end, cand, _rem = self._grp_spec_walk(toks, i, m)
        if name in _SWALLOW_ARG_NAMES or name in _DEAD_ARG_NAMES:
            return end, []
        tail_dead = name in _DEAD_TAIL_NAMES
        spans = [
            (a0, a1)
            for nth2, a0, a1 in cand
            if (not tail_dead or nth2 == 0)
            and _KEYVAL_GROUP_RX.match(self._grp_surfs(toks[a0 + 1 : a1 - 1])) is None
            and not _COMMA_LIST_RX.fullmatch(self._grp_surfs(toks[a0 + 1 : a1 - 1]))
            and self._grp_arg_prose(toks[a0 + 1 : a1 - 1])
        ]
        return end, spans

    def _group_surface(self) -> list[str] | None:
        r"""组成员 token → surface 段：结构命令再生保护段产 ph。

        展开表面里的 ``\\begin/\\end{env}``（math/verb/protected 整段、
        其余 tag）、``$…$``/``\\[…\\]``/``\\(…\\)``、cite/ref/PROTECT 族整
        调用、``\\if`` 族——ph 体 = 展开表面切片（vtex 无对应字节，
        identity 由本组 ``[[EXPAND]]``/``ph_map[CHUNK]`` 兜底）。
        ``eol_par`` = 虚拟分段符：切段边界、自身不产字节（§3）。
        返回 ``list[str]``——段界在 ``_close_group`` 重拼为同一 run 的
        ``\\n\\n`` 段内分隔（全或无发射：逐段冲刷会把空 ident 尾段交给
        literal 路径丢字节——``\\parbox`` 参内 ``\\par`` 切断的
        ``}``/``\\end{env}`` 蒸发，hep-ph/9910403 ``\\@iiiparbox``
        runaway 族）。

        返回 ``None`` = 整组 bail（``_close_group`` 转 literal 兜底）：
        组内 ``\\begin{保护族 env}``/env_begin 宏端点找不到配对
        ``\\end``——物质化一个永无配对的开 tag 会把后续主流
        ``\\end`` 变 stray、译文面留未闭环境（R7/J3，``\\bea``=
        ``\\begin{eqnarray}\\relax`` 形）。
        """
        return self._grp_scan(self._open_toks)

    def _grp_scan(  # noqa: C901, PLR0912, PLR0915 — 组内保护段分派平铺（§3 再生保护段）
        self, toks: list[Tok], depth: int = 0
    ) -> list[str] | None:
        r"""``_group_surface`` 的 toks 参数化引擎——探针散文参子扫复用。

        ``depth`` = 散文参递归代数：``MAX_GEN`` 触底即停挖、参维持
        ``[[CMD]]`` 并记 ``gen_overflow``（字节臂 ``self.gen`` 回压同义——
        宁可不译也不超代数）。
        """
        segs: list[str] = []
        out: list[str] = []
        i, n = 0, len(toks)
        while i < n:
            t = toks[i]
            if t.kind == "eol_par":
                segs.append("".join(out))
                out = []
                i += 1
                continue
            if t.kind == "mathshift":
                j = self._grp_math_end(toks, i)
                if j is None:
                    self._cat_surf(out, self._tok_surface(t))
                    i += 1
                    continue
                self._cat_surf(
                    out, self._grp_ph(PhType.MATH, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            if t.kind != "cs":
                self._cat_surf(out, self._tok_surface(t))
                i += 1
                continue
            name = t.text
            # 分派行序镜像 _dispatch：verb 定界形（row1）→ env tag → 定界
            # 数学 → cite/ref（共享谓词）→ PROTECT → href/hyperref →
            # input 族 → \if 族 → env 宏端点 → 默认逐字
            if name in _VERB_LIKE:
                j = self._grp_verb_end(toks, i)
                if j is None:
                    self._cat_surf(out, self._tok_surface(t))
                    i += 1
                    continue
                self._cat_surf(
                    out, self._grp_ph(PhType.VERB, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            if name in _ENV_CS:
                hit = self._grp_envtag(toks, i)
                if hit is None:
                    self._cat_surf(
                        out, self._grp_ph(PhType.ENVTAG, self._tok_surface(t))
                    )
                    i += 1
                    continue
                env, j = hit
                if name == "begin":
                    reg = self.state.macros.lookup_env(env)
                    ae = self._argspec_env(env, reg)
                    typ = _env_ph_type(env, ae, reg)
                    if typ is not None:
                        e = self._grp_find_env_end(toks, j, env)
                        if e is not None:
                            self._cat_surf(
                                out, self._grp_ph(typ, self._grp_surfs(toks[i:e]))
                            )
                            i = e
                            continue
                        # 保护族 env 开 tag 无配对 \end——整组回 literal
                        # （R7/J3：\bea=\begin{eqnarray}\relax 形）
                        return None
                    # ENVTAG 界延到环境尾参（主流 _eat_env_args 同规）——
                    # preamble {lRLc}/版式 [opt] 不裸进 surface
                    j = self._grp_env_args_end(toks, j, env, reg, ae)
                self._cat_surf(
                    out, self._grp_ph(PhType.ENVTAG, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            if name in _MATH_OPEN_CS:
                j = self._grp_delim_end(toks, i, "]" if name == "[" else ")")
                if j is not None:
                    self._cat_surf(
                        out, self._grp_ph(PhType.MATH, self._grp_surfs(toks[i:j]))
                    )
                    i = j
                    continue
                self._cat_surf(out, self._tok_surface(t))
                i += 1
                continue
            fam = _cite_ref_type(name)
            if fam is not None:
                j = self._grp_call_end(toks, i, self._cite_ref_mand(name))
                self._cat_surf(out, self._grp_ph(fam, self._grp_surfs(toks[i:j])))
                i = j
                continue
            if name in PROTECT_NAMES:
                j = self._grp_call_end(toks, i, 2 if name == "inputminted" else 1)
                if name in ("url", "path"):
                    # \url<delim>…<delim> 定界形兜底（主版 verbatim 支同判据）
                    k2 = i + 1
                    if k2 < n and toks[k2].kind == "other" and toks[k2].text == "*":
                        k2 += 1
                    if j == k2 and k2 < n:
                        d = toks[k2]
                        dt = "\\" if d.kind == "cs" else d.text
                        if (
                            len(dt) == 1
                            and not dt.isalnum()
                            and dt not in " \t\n\r%{}[]"
                        ):
                            e2 = self._grp_delim_body_end(toks, i, k2)
                            if e2 is not None:
                                j = e2
                self._cat_surf(
                    out,
                    self._grp_ph(
                        _PROTECT_TYP.get(name, PhType.CMD),
                        self._grp_surfs(toks[i:j]),
                    ),
                )
                i = j
                continue
            if name == "href":
                # \href{url}{text}：命令名+间隙留 surface，{url} 组 →
                # [[HREF]]；{text} 组 token 留 surface 续扫（主版 _handle_href
                # 同形——花括号随文本进 surface）
                k = i + 1
                while k < n and toks[k].kind == "space":
                    k += 1
                e = (
                    self._grp_bal(toks, k, brace=True)
                    if k < n and toks[k].kind == "lbrace"
                    else None
                )
                if e is None:
                    self._cat_surf(out, self._tok_surface(t))
                    i += 1
                    continue
                self._cat_surf(out, self._grp_surfs(toks[i:k]))
                self._cat_surf(
                    out, self._grp_ph(PhType.HREF, self._grp_surfs(toks[k:e]))
                )
                i = e
                continue
            if name == "hyperref":
                # argspec m m（key,text）的组内对价：首个参组（{key} 或
                # [label]）随命令进 [[CMD]]，{text} 余参留 surface 续扫——
                # 走参 = ``["s","e"]`` 槽列（``_pend_spec_of`` hyperref 行同形）
                j = self._walk_spec_toks(
                    toks, i + 1, [_slot_elem("s"), _slot_elem("e")]
                ).end
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            if COND_RX.match(name):
                # 名/表达式槽 ``{..}`` 并入 [[COND]]（主流 ``_handle_cond``
                # 的 ``_COND_GROUP_ARGS`` 组内对价）——``\iftoggle{tag}`` 的
                # ``{tag}`` 机器槽留 surface 被译；``{T}{F}`` 支不在吸收数
                # 内，留 surface 续扫照译。表外名无槽形（``{`` 是分支散文）。
                # 走参 = ``["m"]×nslots`` 槽列（``_pend_spec_of`` COND 行同形）
                j = self._walk_spec_toks(
                    toks, i + 1, [_slot_elem("m")] * _COND_GROUP_ARGS.get(name, 0)
                ).end
                self._cat_surf(
                    out, self._grp_ph(PhType.COND, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            if name in INPUT_SCAN_CMDS:
                # \input 族漏网（主版 row10）：{file}/import 双参/裸名三形
                k = i + 1
                while k < n and toks[k].kind == "space":
                    k += 1
                if (
                    k < n
                    and toks[k].kind in ("letter", "other")
                    and all(c in FILENAME_CHARS for c in toks[k].text)
                ):
                    j = k + 1  # 裸文件名形：连吃 FILENAME_CHARS 文本 token
                    while (
                        j < n
                        and toks[j].kind in ("letter", "other")
                        and all(c in FILENAME_CHARS for c in toks[j].text)
                    ):
                        j += 1
                elif (
                    k < n
                    and toks[k].kind in ("letter", "other")
                    and toks[k].text == '"'
                ):
                    # 引号裸名 \input"a b.tex" —— 含闭引号整吞进 [[CMD]]，
                    # 缺席吞到流尾（否则文件名漏成散文）
                    j = k + 1
                    while j < n and not (
                        toks[j].kind in ("letter", "other") and toks[j].text == '"'
                    ):
                        j += 1
                    if j < n:
                        j += 1
                elif k < n and toks[k].kind == "cs":
                    # ``\input \cs`` 动态文件名——cs 随命令进 [[CMD]]
                    # （主流 else 臂同规，R4）
                    j = k + 1
                else:
                    j = self._grp_call_end(toks, i, 2 if name in _IMPORT2 else 1)
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            em = self._grp_env_macro(t)
            if em is not None:
                ek, eenv = em
                reg2 = self.state.macros.lookup_env(eenv)
                ae2 = self._argspec_env(eenv, reg2) if ek == "env_begin" else None
                typ = _env_ph_type(eenv, ae2, reg2) if ek == "env_begin" else None
                e = (
                    self._grp_find_env_end(toks, i + 1, eenv)
                    if typ is not None
                    else None
                )
                if e is not None:
                    self._cat_surf(out, self._grp_ph(typ, self._grp_surfs(toks[i:e])))
                    i = e
                    continue
                if ek == "env_begin" and typ is not None:
                    # 同上：保护族 env 开端点无配对——整组回 literal（R7/J3）
                    return None
                j2 = i + 1
                if ek == "env_begin":
                    # 宏端点同吃环境尾参（\bea{c} 的 preamble 不裸进 surface）
                    j2 = self._grp_env_args_end(toks, j2, eenv, reg2, ae2)
                self._cat_surf(
                    out, self._grp_ph(PhType.ENVTAG, self._grp_surfs(toks[i:j2]))
                )
                i = j2
                continue
            if name in CHUNK_ARG_NAMES:
                # ``\section[opt]{arg}`` 组内对价（``_handle_chunk_arg`` 镜像）：
                # ``*``?+可译位前头参随名进 ``[[CMD]]``，``{arg}`` 组整体留
                # surface 续扫（B 臂无独立 chunk piece——参留主流即可见同义，
                # 名不再裸落译文面）。可译槽缺席/非 ``{..}`` 组 → 名逐字回落
                # （主流 bail→``_rappend_tok`` 同规）；空参 → 整调用逐字。
                spec_s, tidx = CHUNK_ARG_SPEC.get(name, ("om", 1))
                # ``*``? 前缀 = ``star`` 走参元（ws 前跳——组面 ``*`` 可隔空，
                # 与槽 ``s`` 的 ws=False 原位判不同，原判保留）
                k = self._walk_spec_toks(toks, i + 1, [_WSpec("star")]).end
                j2 = self._grp_spec_args_end(
                    toks, k, _chunk_spec_cached(spec_s)[:tidx], (), None
                )
                k = j2
                while k < n and toks[k].kind == "space":
                    k += 1
                e2 = (
                    self._grp_bal(toks, k, brace=True)
                    if k < n and toks[k].kind == "lbrace"
                    else None
                )
                if e2 is None:
                    self._cat_surf(out, self._tok_surface(t))
                    i += 1
                    continue
                if not self._grp_surfs(toks[k + 1 : e2 - 1]).strip():
                    self._cat_surf(out, self._grp_surfs(toks[i:e2]))
                    i = e2
                    continue
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:k]))
                )
                i = k
                continue
            if name in PROTECT_BLOCK_NAMES:
                # ``\author[opt]{..}`` 整块 → ``[[AUTHOR]]``——abort（``{`` 未
                # 随只护 cs 本体）与 keyval 续组语义在 ``_grp_protect_block_end``
                e = self._grp_protect_block_end(toks, i)
                self._cat_surf(
                    out, self._grp_ph(PhType.AUTHOR, self._grp_surfs(toks[i:e]))
                )
                i = e
                continue
            if name in BOUNDARY_NAMES:
                # 组内 BOUNDARY_TAIL/dimen 尾参（顶层 _handle_boundary 对价，
                # in_arg=COMMAND 整调用保护）：结构尾参 ``{2mm}``/``[o]``、裸
                # 操作数 ``\vskip 3pt`` 随命令进 [[CMD]]——裸落 surface 会被
                # 翻译 ``mm``/``pt``（illegal_unit，loop1 slots①）。
                # spec 缺席不预吃 ``[opt]``——``\item[label]`` 的 label 是
                # 可译文本须留 surface（主流同规）。
                spec = BOUNDARY_TAIL.get(name)
                j = i + 1
                kind = DIMEN_TAIL_KIND.get(name)
                if kind is not None:
                    e2 = self._grp_tail_end(toks, j, _TAIL_RX[kind])
                    if e2 is not None:
                        j = e2
                elif spec is not None:
                    # 位序走参——``n`` 槽认裸 cs token（``\setlength\parskip``
                    # 组内形）；旧 ``_grp_call_end`` 只数 ``{..}`` 组，裸名形
                    # 漏 ``{4pt}`` 进 surface（illegal_unit 波实证：
                    # 1608.02270 ``\setlength\arraycolsep{2pt}`` 34 处残留）
                    j = self._grp_spec_args_end(toks, i + 1, spec, (), None)
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            # —— 以下各行镜像 _dispatch 行 13–19 的组内对价（非文本槽位不
            #    裸进 surface——loop1 slots 修复的组内侧）——
            if name == "\\":
                j2 = self._grp_bsbs(toks, i)
                if j2 is not None:
                    self._cat_surf(
                        out,
                        self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j2])),
                    )
                    i = j2
                    continue
                self._cat_surf(out, self._tok_surface(t))
                i += 1
                continue
            if name in TRANSPARENT_HEAD_SPEC:
                # \textcolor{red}{text}：头参进 [[CMD]]，{text} 留 surface
                j2 = self._grp_spec_args_end(
                    toks,
                    i + 1,
                    TRANSPARENT_HEAD_SPEC[name],
                    (),
                    None,
                    allow_single_token=False,
                )
                if j2 > i + 1:
                    self._cat_surf(
                        out,
                        self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j2])),
                    )
                    i = j2
                    continue
                self._cat_surf(out, self._tok_surface(t))
                i += 1
                continue
            kind2 = DIMEN_TAIL_KIND.get(name)
            j2 = self._grp_tail_end(
                toks, i + 1, _TAIL_RX[kind2 if kind2 is not None else "assign"]
            )
            if j2 is not None:
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j2]))
                )
                i = j2
                continue
            if _accent_cs(name):
                # accent 单参保护（主流 _handle_accent 对价）：{x} 组或
                # 单 token 参随 cs 进 [[CMD]]——参字母裸落 surface 会被
                # 翻译（0806.3144 同族，花括号形前由探针兜底、裸参形是洞）。
                # 走参 = ``["a"]`` 槽列（``_pend_spec_of`` accent 行同形）
                j = self._walk_spec_toks(toks, i + 1, [_slot_elem("a")]).end
                if j > i + 1:
                    self._cat_surf(
                        out,
                        self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j])),
                    )
                    i = j
                    continue
                self._cat_surf(out, self._tok_surface(t))
                i += 1
                continue
            if _inline_lit_cs(name):
                # 行内字面（主流 row19 对价）：符号/品牌/字体开关/单字符
                # 非字母命令零参逐字——``\5``/``\_`` 不得被下游 argspec
                # 假条目/探针吃参（参留 surface = 主流可见同义）
                if name == "$":
                    # ``\$`` 组内同规：surface ph 化防裸 ``$`` 漏进可译面
                    self._cat_surf(out, self._grp_ph(PhType.CMD, self._tok_surface(t)))
                else:
                    self._cat_surf(out, self._tok_surface(t))
                i += 1
                continue
            # 宏表登记名决议（env-macro 行只截 env_begin/env_end 后此处
            # 再查同表）：opaque/math 宏行走参、其余登记名落探针——
            # ``m is None`` 才进 argspec（主流闸同规）
            m2 = self.state.macros.resolve(self.state.macros.lookup(name))
            if getattr(m2, "kind", "") in ("opaque", "math"):
                # opaque/math 宏（主流 row18 ``_handle_opaque_macro`` 对价）：
                # ``m.spec`` 位序走参整调用罩 ``[[CMD]]``——探针 ``[o]+{m}×6``
                # 形把 spec 外 ``{..}`` 组误吸进保护面（登记宏 nargs 越界
                # 过吸）。``{``/``[``-open 组参过散文门抠出子扫渲 surface
                # （主流散文挖掘同型）；体尾 key-arg 调用点 ``{key}`` 同罩。
                # 宏行在 pair-block 行之前与主流行序同位。
                j2, spans = self._grp_opaque_args(toks, i, name, m2)
                if spans and depth >= MAX_GEN:
                    self.state.warnings.append(
                        ScanWarning("gen_overflow", len(self.vt), f"grp-opaque:{name}")
                    )
                    spans = []
                cur = i
                for a0, a1 in spans:
                    sub = self._grp_scan(toks[a0 + 1 : a1 - 1], depth + 1)
                    if sub is None:
                        continue  # 参内保护族 env 无配对——该参维持 opaque
                    self._cat_surf(
                        out,
                        self._grp_ph(PhType.CMD, self._grp_surfs(toks[cur : a0 + 1])),
                    )
                    self._cat_surf(out, "\n\n".join(sub))
                    cur = a1 - 1  # ``}``/``]`` 随下段结构进 CMD（主流同位）
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[cur:j2]))
                )
                i = j2
                continue
            if name in PAIR_BLOCK_ALL:
                # cs 对界块（主流 row18b 对价）：组内有配对闭 cs → 整段
                # [[ENV]]（B 臂无独立 chunk piece——体表面随 ph 保护即同
                # 义）；孤闭 cs → [[CMD]]；开 cs 组内无配对 → 不落本行、
                # 续走 argspec/探针（未闭合按未知 cs 保守处理，主流
                # unclosed→unknown 同规）
                if name not in PAIR_BLOCK_CMDS:
                    self._cat_surf(out, self._grp_ph(PhType.CMD, self._tok_surface(t)))
                    i += 1
                    continue
                e3 = self._grp_pair_end(toks, i + 1, name, PAIR_BLOCK_CMDS[name])
                if e3 is not None:
                    self._cat_surf(
                        out,
                        self._grp_ph(PhType.ENV, self._grp_surfs(toks[i:e3])),
                    )
                    i = e3
                    continue
            # 宏表登记名不吃 argspec（主流 ``m is None`` 闸的组内对价——
            # env-macro 行只截 env_begin/env_end，opaque/math 宏上行已兜，
            # 其余登记名落探针同规）
            e2 = _tables.argspec_lookup(name, self.state.pkgs) if m2 is None else None
            if e2 is not None:
                policy = e2.policy
                if policy in ("literal", "transparent"):
                    self._cat_surf(out, self._tok_surface(t))
                    i += 1
                    continue
                spec2 = _chunk_spec_cached(e2.signature)
                if policy == "chunk-arg":
                    j2 = self._grp_spec_args_end(toks, i + 1, spec2, e2.arg_roles, None)
                    if j2 > i + 1:
                        self._cat_surf(
                            out,
                            self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j2])),
                        )
                        i = j2
                        continue
                    self._cat_surf(out, self._tok_surface(t))
                    i += 1
                    continue
                # protect/key/verbatim/boundary → 整调用 [[CMD]]
                if name == "tikz" and policy in ("protect", "key"):
                    # 裸 ``\tikz <path>;`` 的组内对价（R8）——签名
                    # ``o o m`` 同主流一样够不着路径形
                    j3 = self._grp_tikz_end(toks, i)
                    if j3 is not None:
                        self._cat_surf(
                            out,
                            self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j3])),
                        )
                        i = j3
                        continue
                mand = sum(1 for s in spec2 if s.kind in ("m", "v", "n"))
                j2 = self._grp_call_end(toks, i, mand)
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j2]))
                )
                i = j2
                continue
            # 未知探针（主流 row19 对价）：``[opt]``? + ``{m}``×6 → [[CMD]]；
            # 散文 ``{..}`` 参抠出 CMD 覆盖、``_grp_scan`` 递归子扫渲进
            # surface（``_handle_unknown_cs`` 散文挖掘的组内同型——宏名/
            # 非散文参/散文参两侧花括号所在结构段仍 CMD 原文，嵌套 cs 经
            # 子扫分派照常保护）。
            j2 = self._grp_probe_end(toks, i)
            if j2 is not None:
                spans = self._grp_probe_prose_args(toks, i, j2, name)
                if spans and depth >= MAX_GEN:
                    self.state.warnings.append(
                        ScanWarning("gen_overflow", len(self.vt), f"grp-probe:{name}")
                    )
                    spans = []
                cur = i
                for a0, a1 in spans:
                    sub = self._grp_scan(toks[a0 + 1 : a1 - 1], depth + 1)
                    if sub is None:
                        continue  # 参内保护族 env 无配对——该参维持 opaque
                    self._cat_surf(
                        out,
                        self._grp_ph(PhType.CMD, self._grp_surfs(toks[cur : a0 + 1])),
                    )
                    self._cat_surf(out, "\n\n".join(sub))
                    cur = a1 - 1  # ``}`` 随下段结构进 CMD（字节臂 a.ce 起盖同位）
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[cur:j2]))
                )
                i = j2
                continue
            self._cat_surf(out, self._tok_surface(t))
            i += 1
        segs.append("".join(out))
        return segs
