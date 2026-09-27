r"""``latex/segmenter`` 子模块——god-class 机械拆分（行为零变）。"""

from __future__ import annotations

import texlate.latex.tables as _tables
from texlate.latex.gullet import (
    MacroDef,
    _tok_eq,
)
from texlate.latex.model import (
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
    INPUT_SCAN_CMDS,
    PAIR_BLOCK_ALL,
    PROTECT_BLOCK_NAMES,
    PROTECT_NAMES,
    TRANSPARENT_HEAD_SPEC,
)

from ._common import (
    _ACCENT_SLOTS,
    _BSBS_SLOTS,
    _ENV_CS,
    _GRP_BSBS_CONTENT_RX,
    _HYPERREF_SLOTS,
    _KEYARG_TAIL_DEPTH,
    _KEYARG_TAIL_RX,
    _MATH_DELIM_CS,
    _PEND_CALL1,
    _PEND_CALL2,
    _PEND_PROBE,
    _SLOT_PAIR_LEN,
    _SLOT_TEST_LEN,
    _VERB_LIKE,
    TokenSource,
    _accent_cs,
    _call_slots,
    _chunk_spec_cached,
    _cite_ref_type,
    _cond_slots,
    _fams,
    _inline_lit_cs,
    _pend_call_slots,
    _pend_slot_of,
    _pull_cursor,
    _slot_elem,
)
from .grpscan import (
    _IMPORT2,
    _GrpScan,
    _PendRem,
)

r"""``Segmenter`` 跨边界待绑参——流侧 pend/absorb 机械。组内 ``_grp_*``
surface 引擎在 ``grpscan.py``，经 ``_Pending(_GrpScan)`` 并入同一 MRO。"""


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


# ---- ``_pend_spec_of`` 槽列 ↔ ``_grp_scan``/``_grp_bsbs`` 走参元的同形单源 ----
# 名→槽形改动只改一处（``_slot_elem`` 逐位归一投影进 ``_walk_spec_toks``）；
# ``_HYPERREF_SLOTS``/``_BSBS_SLOTS``/``_ACCENT_SLOTS``/``_cond_slots``/
# ``_call_slots`` 已收 ``_common``（``_PEND_CALL*``/``_PEND_PROBE`` 同族）。


def _pull_boundary(x: Tok | None, fid: int, *, par: bool = True) -> bool:
    r"""参扫界 token 判据：``None``(EOF)/``eol_par``/``gen>0``/异 fid。

    ``_absorb_slots``/``_absorb_spec``/``_absorb_grp_tail`` 拉参扫的统一界
    判（各 docstring 的「界 token」契约）；``par=False`` = ``eol_par`` 不作
    界——``_absorb_grp_tail`` 组内续收里 par 是组内容物。
    """
    return x is None or (par and x.kind == "eol_par") or x.gen > 0 or x.pos[0] != fid


class _Pending(_GrpScan):
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

    def _pull_group(
        self, src: TokenSource, x: Tok, *, brace: bool, fid: int
    ) -> list[Tok] | None:
        r"""``_collect_group`` 拉取打包 → ``[x, *inner, closer]`` / ``None``。

        ``_absorb_slots``/``_absorb_spec`` 的组参拉取半（``_pull_cursor``
        是回放/前瞻半）：``x`` = 已读开界 token（``{``/``[``）；``fid`` 逐
        枚界检——组内混进异 fid token 即整组回吐。组未闭/异 fid → ``None``
        （``_collect_group`` 已全量回吐——调用方 ``unpull`` 收未提交尾即可）。
        """
        hit = self._collect_group(src, x, brace=brace, fid=fid)
        if hit is None:
            return None
        inner, closer = hit
        return [x, *inner, closer]

    def _absorb_slots(  # noqa: C901, PLR0912, PLR0915 — 槽字母各一分支，平铺即流侧 _slots_walk_toks 对价
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
        unpull, peek = _pull_cursor(src, fid, pulled, lambda: committed)

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
                    grp = self._pull_group(src, x, brace=False, fid=fid)
                    if grp is None:
                        unpull()
                        break
                    pulled.extend(grp)
                    committed = len(pulled)
                else:
                    unpull(x)
                continue
            if s == "b":
                if x.kind == "other" and x.text == "[":
                    grp = self._pull_group(src, x, brace=False, fid=fid)
                    if grp is None:
                        unpull()
                        break
                    if not _GRP_BSBS_CONTENT_RX.fullmatch(self._grp_surfs(grp[1:-1])):
                        src.unread(grp)
                        unpull()
                        break
                    pulled.extend(grp)
                    committed = len(pulled)
                else:
                    unpull(x)
                continue
            if s == "m":
                if x.kind != "lbrace":
                    unpull(x)
                    break
                grp = self._pull_group(src, x, brace=True, fid=fid)
                if grp is None:
                    unpull()
                    break
                pulled.extend(grp)
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
                grp = self._pull_group(src, x, brace=x.kind == "lbrace", fid=fid)
                if grp is None:
                    unpull()
                    break
                pulled.extend(grp)
                committed = len(pulled)
                continue
            if s == "e":
                if x.kind != "lbrace" and not (x.kind == "other" and x.text == "["):
                    unpull(x)
                    break
                grp = self._pull_group(src, x, brace=x.kind == "lbrace", fid=fid)
                if grp is None:
                    unpull()
                    break
                pulled.extend(grp)
                committed = len(pulled)
                continue
            if s == "a":
                if x.kind == "lbrace":
                    grp = self._pull_group(src, x, brace=True, fid=fid)
                    if grp is None:
                        unpull()
                        break
                    pulled.extend(grp)
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
                if x.kind != "cs" and x.text == s[1]:
                    seq = [x]
                    while True:
                        y = src.read()
                        if _pull_boundary(y, fid):
                            src.unread([*seq, *([y] if y is not None else [])])
                            seq = []
                            break
                        seq.append(y)
                        if y.kind != "cs" and y.text == s[2]:
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
            if _pull_boundary(y, fid, par=False):
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
        unpull, peek = _pull_cursor(src, fid, pulled, lambda: committed)

        def e_arg_tail() -> None:
            # ``e`` 参已吃 ``X`` 的 ``{arg}``/``<tok>`` 尾位（可缺省——
            # cs/界 token/缺席只留符，不算失配）
            nonlocal committed
            z = peek()
            if z is None:
                unpull()
            elif z.kind == "lbrace":
                grp = self._pull_group(src, z, brace=True, fid=fid)
                if grp is None:
                    unpull()
                else:
                    pulled.extend(grp)
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
                        grp = self._pull_group(
                            src, x, brace=x.kind == "lbrace", fid=fid
                        )
                        if grp is None:
                            unpull()
                            break
                        pulled.extend(grp)
                        committed = len(pulled)
                    elif x.kind == "cs":
                        unpull(x)
                        break  # 单 token 参不跨 '\'
                    else:
                        pulled.append(x)
                        committed = len(pulled)
                    continue
                if x.kind == "other" and x.text == "[":
                    grp = self._pull_group(src, x, brace=False, fid=fid)
                    if grp is None:
                        unpull()
                        break
                    pulled.extend(grp)
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
                        grp = self._pull_group(src, x, brace=True, fid=fid)
                        if grp is None:
                            unpull()
                            break
                        seq.extend(grp)
                        pulled.extend(grp)
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
                    if _pull_boundary(y, fid):
                        if y is not None:
                            src.unread([y])
                        runaway = True
                    elif y.kind == "lbrace":
                        grp = self._pull_group(src, y, brace=True, fid=fid)
                        if grp is None:
                            runaway = True
                        else:
                            seq.extend(grp)
                            pulled.extend(grp)
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
                    if _pull_boundary(y, fid):
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
        self, m: object, src: TokenSource | None = None, depth: int = 0
    ) -> str | None:
        r"""宏体尾 cs 解析到 key-arg 名（``\def\x{..\label}`` 形）→ 名 / ``None``。

        ``MacroDef.body`` = token 列（尾 cs = 最后非空白 token——``{..}``
        结尾即体尾是组不是 cs，不算待绑）；``body: str`` 登记体 = 字符串
        （``_KEYARG_TAIL_RX``）；``\\let`` 快照 ``Tok``/原语名 ``str`` 直取。
        尾 cs 再登记成宏 → 递归一层（``\\a``→``\\b``→``\\ref`` 别名链，
        深 ≤4 防环）。``src=None``（``_grp_spec_walk`` 组内扫无流源）→ 直查
        共享 ``state.macros``——``_resolve_macro`` ``src.macros or`` 回落同款。
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
        tab = getattr(src, "macros", None) or self.state.macros
        m2 = tab.resolve(tab.lookup(name))
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
            return _call_slots(["m"] * self._cite_ref_mand(name)), name
        if name in PROTECT_NAMES:
            return _pend_call_slots(name), name
        if name == "href":
            return ["m"], ""  # {url} 参；{text} 可译留主流
        if name == "hyperref":
            return list(_HYPERREF_SLOTS), ""
        if COND_RX.match(name):
            # ``\iftoggle`` 族名/表达式槽是强制 ``{..}`` 参——组尾未绑时
            # 跨界吸回（主流 ``_handle_cond`` 的 ``_COND_GROUP_ARGS`` 白名单
            # 对价）；表外 ``\ifx``/``\else``/``\fi``/``\newif`` 旗标无花括号
            # 名参，``{..}`` 是分支散文非名槽——维持无槽形。
            slots = _cond_slots(name)
            return (slots or None), ""
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
            return _call_slots(mslots), ""
        if name == "\\":
            return list(_BSBS_SLOTS), ""
        if name in TRANSPARENT_HEAD_SPEC:
            return ["o", "m"], ""  # {red} 头参非文本；{text} 留主流
        if _accent_cs(name):
            return list(_ACCENT_SLOTS), ""
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
            return _call_slots(mslots), ""
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
        if ka and not any(x.kind == "lbrace" for x in warn_pool):
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
