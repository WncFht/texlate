r"""``latex/segmenter`` 子模块——god-class 机械拆分（行为零变）。"""

from __future__ import annotations

import texlate.latex.segmenter as _seg
from texlate.latex.model import (
    PhType,
    ScanWarning,
    Span,
)
from texlate.latex.mouth import (
    Tok,
)
from texlate.latex.tables import (
    ACCENT_CHARS,
    BOUNDARY_NAMES,
    BOUNDARY_TAIL,
    COND_RX,
    DIMEN_TAIL_KIND,
    FILENAME_CHARS,
    INPUT_SCAN_CMDS,
    PROTECT_NAMES,
    TRANSPARENT_HEAD_SPEC,
)

from ._common import (
    _GRP_BSBS_CONTENT_RX,
    _GRP_SCAN_CAP,
    _KEYARG_TAIL_DEPTH,
    _KEYARG_TAIL_RX,
    _PEND_CALL1,
    _PEND_CALL2,
    _PEND_PROBE,
    _PROTECT_TYP,
    _SLOT_PAIR_LEN,
    _SLOT_TEST_LEN,
    _TAIL_RX,
    TokenSource,
    _chunk_spec_cached,
    _cite_ref_type,
    _env_ph_type,
    _pend_call_slots,
    _pend_slot_of,
)

r"""``Segmenter`` 跨边界待绑参与组 surface 收拢。"""

_VERB_LIKE = ("verb", "verb*", "lstinline")
_ENV_CS = ("begin", "end")
_MATH_DELIM_CS = ("[", "(", "]", ")")
_MATH_OPEN_CS = ("[", "(")
_IMPORT2 = ("import", "subimport")


def _accent_cs(name: str) -> bool:
    r"""Accent 族行谓词（``_dispatch``/``_pend_spec_of``/``_group_surface`` 同判据）。"""
    return len(name) == 1 and name in ACCENT_CHARS


# ``_group_surface`` 行序的名级投影——``mainloop._DISPATCH_FAMS`` 的镜像钉
# （``tests/test_dispatch_mirror.py`` 逐名裁决两表族序）。行 =
# ``(族 tag, 名集 | 谓词 | None)``；``None`` = env 宏/argspec/探针动态行。
# 行序即 ``_group_surface`` 分派序，改动须同步投影。
_GRP_SURFACE_FAMS: tuple[tuple[str, object], ...] = (
    ("verb", _VERB_LIKE),
    ("env", _ENV_CS),
    ("math-open", _MATH_OPEN_CS),
    ("cite-ref", _cite_ref_type),
    ("protect", PROTECT_NAMES),
    ("href", "href"),
    ("hyperref", "hyperref"),
    ("cond", COND_RX.match),
    ("input-scan", INPUT_SCAN_CMDS),
    ("env-macro", None),  # _grp_env_macro：env_begin/env_end 宏端点
    ("boundary", BOUNDARY_NAMES),  # BOUNDARY_TAIL/DIMEN_TAIL 尾参内嵌本行
    ("bsbs", "\\"),
    ("transparent-head", TRANSPARENT_HEAD_SPEC),
    ("tail", DIMEN_TAIL_KIND),  # 非 BOUNDARY 的 dimen/assign 尾参兜收
    ("accent", _accent_cs),
    ("argspec", None),
    ("probe", None),  # _grp_probe_end → 逐字
)

# ``_pend_spec_of`` 行序投影（同表第三镜像——跨界待绑参槽形分派）。
_PEND_SPEC_FAMS: tuple[tuple[str, object], ...] = (
    ("verb", _VERB_LIKE),
    ("env", _ENV_CS),
    ("math-delim", _MATH_DELIM_CS),
    ("cite-ref", _cite_ref_type),
    ("protect", PROTECT_NAMES),
    ("href", "href"),
    ("hyperref", "hyperref"),
    ("cond", COND_RX.match),
    ("input-scan", INPUT_SCAN_CMDS),
    ("env-macro", None),
    ("boundary", BOUNDARY_NAMES),  # BOUNDARY_TAIL 位序槽内嵌本行
    ("bsbs", "\\"),
    ("transparent-head", TRANSPARENT_HEAD_SPEC),
    ("accent", _accent_cs),
    ("argspec", None),
    ("keyarg", None),  # _keyarg_tail 宏体尾 key-arg
    ("probe", None),  # _PEND_PROBE 槽
)


class _Pending:
    def _slots_walk_toks(  # noqa: C901, PLR0911, PLR0912, PLR0915 — 槽字母各一分支，平铺即 _grp_call_end 通用化
        self, toks: list[Tok], j: int, slots: list[str] | tuple[str, ...]
    ) -> list[str] | None:
        r"""槽形在组内 token 列上的推行 → 剩余槽列 / ``None``。

        ``toks`` 耗尽而槽未尽 → 返回剩余槽列（调用点界外有待绑参——
        ``_absorb_slots`` 从流里拉回）；中途失配/``eol_par``/组未闭 →
        调用已完结，``None``。可选槽（s/o/b/d/t）失配过给下一槽；强制
        槽（m/e/a）失配 = 终止。
        """
        n = len(toks)
        si = 0
        while si < len(slots):
            s = slots[si]
            k = j
            if s != "s":  # ``*`` 槽不跳 ws（``\ref *{k}`` 的星非星参）
                while k < n and toks[k].kind == "space":
                    k += 1
            if k >= n:
                return list(slots[si:])
            x = toks[k]
            if x.kind == "eol_par":
                return None  # 段界即终止——不定界参数不跨 \par
            if s == "s":
                if x.kind == "other" and x.text == "*":
                    j = k + 1
                si += 1
                continue
            if s == "o":
                if x.kind == "other" and x.text == "[":
                    e = self._grp_bal(toks, k, brace=False)
                    if e is None:
                        return None
                    j = e
                si += 1
                continue
            if s == "b":
                if x.kind == "other" and x.text == "[":
                    e = self._grp_bal(toks, k, brace=False)
                    if e is None or not _GRP_BSBS_CONTENT_RX.fullmatch(
                        self._grp_surfs(toks[k + 1 : e - 1])
                    ):
                        return None
                    j = e
                si += 1
                continue
            if s == "m":
                if x.kind != "lbrace":
                    return None
                e = self._grp_bal(toks, k, brace=True)
                if e is None:
                    return None
                j = e
                si += 1
                continue
            if s == "n":
                # 裸名参：cs 单 token 或 {..}/[..] 组（强制——失配终止）
                if x.kind == "cs":
                    j = k + 1
                elif x.kind == "lbrace" or (x.kind == "other" and x.text == "["):
                    e = self._grp_bal(toks, k, brace=x.kind == "lbrace")
                    if e is None:
                        return None
                    j = e
                else:
                    return None
                si += 1
                continue
            if s == "e":
                if x.kind != "lbrace" and not (x.kind == "other" and x.text == "["):
                    return None
                e = self._grp_bal(toks, k, brace=x.kind == "lbrace")
                if e is None:
                    return None
                j = e
                si += 1
                continue
            if s == "a":
                if x.kind == "lbrace":
                    e = self._grp_bal(toks, k, brace=True)
                    if e is None:
                        return None
                    j = e
                elif x.kind in ("letter", "other") or (
                    x.kind == "cs" and len(x.text) == 1
                ):
                    j = k + 1
                else:
                    return None
                si += 1
                continue
            if s.startswith("d") and len(s) == _SLOT_PAIR_LEN:
                if x.text == s[1]:
                    k2 = k + 1
                    while (
                        k2 < n and toks[k2].text != s[2] and toks[k2].kind != "eol_par"
                    ):
                        k2 += 1
                    if k2 >= n:
                        return list(slots[si:])  # 定界闭符在界外——同槽待绑
                    if toks[k2].kind == "eol_par":
                        return None
                    j = k2 + 1
                si += 1
                continue
            if s.startswith("t") and len(s) == _SLOT_TEST_LEN:
                if x.kind != "cs" and x.text == s[1]:
                    j = k + 1
                si += 1
                continue
            si += 1  # 未识槽字母——保守跳过（不产生消费）
        return None

    def _absorb_slots(  # noqa: C901, PLR0912, PLR0915 — 槽字母各一分支，平铺即流侧 _slots_walk_toks 对价
        self, src: TokenSource, fid: int, slots: list[str]
    ) -> list[Tok]:
        r"""槽形从 ``read()`` 流吸参 → 已消费 token 列（拉取序，可空）。

        ``_slots_walk_toks`` 的源侧对价。失配 token 与其前的 ws 全量
        ``unread`` 回放（``_protect_cs`` ``pulled`` 约定同款）；
        ``eol_par``/异 fid/``gen>0`` token 是参扫边界（回放、不消费）。
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

    def _keyarg_tail(  # noqa: C901, PLR0912 — 体形态分派 + key-arg 判定，平铺即规则
        self, m: object, src: TokenSource, depth: int = 0
    ) -> str | None:
        r"""宏体尾 cs 解析到 key-arg 名（``\def\x{..\label}`` 形）→ 名 / ``None``。

        ``MacroDef.body`` = token 列（尾 cs = 最后非空白 token——``{..}``
        结尾即体尾是组不是 cs，不算待绑）；``MacroEntry.body`` = 字符串
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
        e = _seg.argspec_lookup(name, self.state.pkgs)
        if e is None or not e.signature:
            return 1
        spec = _chunk_spec_cached(e.signature)
        return max(1, sum(1 for s in spec if s.kind in ("m", "v", "n")))

    def _pend_spec_of(  # noqa: C901, PLR0911, PLR0912 — _group_surface 分派行序镜像，平铺即语义
        self, name: str, src: TokenSource
    ) -> tuple[list[str] | None, str]:
        r"""组内 cs → 待绑参槽形 + key-arg 名（``_group_surface`` 各行镜像）。

        ``(None, "")`` = 该 cs 无跨界待绑形（verb 定界体/``\\if`` 族/
        数学定界/env 端点宏/env 尾参另一机制）。key-arg 名非空 =
        cite/ref/PROTECT/宏体尾 key-arg——吸纳后仍未绑到 ``{key}``
        时 ``keyarg_unbound`` 告警。
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
            return None, ""
        if name in INPUT_SCAN_CMDS:
            return (list(_PEND_CALL2) if name in _IMPORT2 else list(_PEND_CALL1)), ""
        m = self._resolve_macro(src, name)
        if getattr(m, "kind", "") in ("env_begin", "env_end"):
            return None, ""  # env 尾参走 ``_grp_env_args_end`` 另一机制
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
        e = _seg.argspec_lookup(name, self.state.pkgs)
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

    def _grp_pending(self, src: TokenSource) -> tuple[list[str], str] | None:
        r"""组尾待绑参检测 → ``(剩余槽列, keyarg 名)`` / ``None``。

        右起扫 ``_open_toks`` 首个有槽形的 cs，其参扫须吃到 toks 末才
        算 pending（中途被 token 终止 = 调用已完结）。命中即返——更早
        的 cs 不可能 pending：其参扫必经本 cs token 而强制槽遇 cs 即止。
        """
        toks = self._open_toks
        for i in range(len(toks) - 1, -1, -1):
            x = toks[i]
            if x.kind != "cs":
                continue
            slots, ka = self._pend_spec_of(x.text, src)
            if slots is None:
                continue
            rem = self._slots_walk_toks(toks, i + 1, slots)
            return (rem, ka) if rem else None
        return None

    def _absorb_pending(self, t: Tok, src: TokenSource) -> bool:
        r"""组尾待绑参吸纳：``t``（界外首 token）回流作首候选，拉参入组。

        成功 → token 并入 ``_open_toks``、``_open_vspan``/``_open_origin``
        延到吸纳末位（``[[EXPAND]]`` 体覆盖 ``\\r{key}`` 全调用点）、
        返 ``True``（t 已入组不再主流分派）；未吸到 → 流复原、``False``。
        key-arg 族待绑而无 ``{``/``[`` 参落位 → ``keyarg_unbound`` 告警
        （含空 got——收组后将产 cs-only 保护面，同属漏参信号）。
        """
        o = self._open_origin
        hit = self._grp_pending(src)
        if hit is None:
            return False
        slots, ka = hit
        src.unread([t])  # t 回流作首候选——槽列完整后统一拉取
        got = self._absorb_slots(src, o[0], slots)
        if ka and not any(
            x.kind == "lbrace" or (x.kind == "other" and x.text == "[") for x in got
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

    def _group_surface(self) -> list[str] | None:  # noqa: C901, PLR0912, PLR0915 — 组内保护段分派平铺（§3 再生保护段）
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
        toks = self._open_toks
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
                # [label]）随命令进 [[CMD]]，{text} 余参留 surface 续扫
                j = i + 1
                if j < n and toks[j].kind == "other" and toks[j].text == "*":
                    j += 1
                k = j
                while k < n and toks[k].kind == "space":
                    k += 1
                if k < n and (
                    toks[k].kind == "lbrace"
                    or (toks[k].kind == "other" and toks[k].text == "[")
                ):
                    e = self._grp_bal(toks, k, brace=toks[k].kind == "lbrace")
                    if e is not None:
                        j = e
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j]))
                )
                i = j
                continue
            if COND_RX.match(name):
                self._cat_surf(out, self._grp_ph(PhType.COND, self._tok_surface(t)))
                i += 1
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
                    toks, i + 1, TRANSPARENT_HEAD_SPEC[name], (), None
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
                # 翻译（0806.3144 同族，花括号形前由探针兜底、裸参形是洞）
                j = i + 1
                while j < n and toks[j].kind == "space":
                    j += 1
                if j < n and toks[j].kind == "lbrace":
                    e2 = self._grp_bal(toks, j, brace=True)
                    j = e2 if e2 is not None else i + 1
                elif j < n and (
                    toks[j].kind in ("letter", "other")
                    or (toks[j].kind == "cs" and len(toks[j].text) == 1)
                ):
                    j += 1
                else:
                    j = i + 1
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
            e2 = _seg.argspec_lookup(name, self.state.pkgs)
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
            # 未知探针（主流 row19 对价）：``[opt]``? + ``{m}``×6 → [[CMD]]
            j2 = self._grp_probe_end(toks, i)
            if j2 is not None:
                self._cat_surf(
                    out, self._grp_ph(PhType.CMD, self._grp_surfs(toks[i:j2]))
                )
                i = j2
                continue
            self._cat_surf(out, self._tok_surface(t))
            i += 1
        segs.append("".join(out))
        return segs
