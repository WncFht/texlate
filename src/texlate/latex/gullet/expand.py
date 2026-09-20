r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：expandafter/csname/ifundefined。"""

from __future__ import annotations

from texlate.latex.mouth import (
    Tok,
)

from .entries import (
    ArgMismatch,
    MacroDef,
)
from .names import (
    _BUILTINS,
    _EXPAND_KINDS,
    _PRIMS,
)

# \romannumeral 减记表（TeX 产出小写罗马；n>3999 走 consumed 兜底不展开）
_ROMAN_TAB = (
    (1000, "m"),
    (900, "cm"),
    (500, "d"),
    (400, "cd"),
    (100, "c"),
    (90, "xc"),
    (50, "l"),
    (40, "xl"),
    (10, "x"),
    (9, "ix"),
    (5, "v"),
    (4, "iv"),
    (1, "i"),
)

#: ``\romannumeral`` 上界——TeX 语义 0< n ≤3999（超界不产 token）。
_ROMAN_MAX = 3999

# ``_try_expand_macro`` 三态哨兵——共用门命中与否由各分派点自映返回形。
#: ``r`` 非 ``MacroDef``——调用点续走 str 别名 / 原语名分派。
_NOT_MACRO = object()
#: ``MacroDef`` 但不可展（kind 非 ``_EXPAND_KINDS`` / 三级限制拒）。
_BLOCKED = object()
#: 读参 ``ArgMismatch``——已消费 token 助手侧已回吐，调用点只映返回形。
_MISMATCH = object()


def _to_roman(n: int) -> str:
    r"""整数 → 小写罗马数字串（``\romannumeral`` 语义）。"""
    out: list[str] = []
    for v, s in _ROMAN_TAB:
        q, n = divmod(n, v)
        out.append(s * q)
    return "".join(out)


class _Expand:
    # ------------------------------------------------------------ expandafter/csname/ifundefined

    def _do_expandafter(self, _trig: Tok) -> Tok | None:
        r"""``\expandafter\t1\t2``：``t2`` 展开一次再推回（Primitives.py:495-512）。

        推回序为 ``[t1]+展开结果``；触发 token 本体已消费不回吐（gap literal）。
        """
        t1 = self.read()
        t2 = self.read()
        if t1 is None:
            self.unread([t2] if t2 is not None else [])
            return None
        if t2 is None:
            self.unread([t1])
            return None
        expanded = self._expand_once(t2)
        self.unread([t1, *expanded])
        return None

    def _try_expand_macro(
        self,
        t: Tok,
        r: object,
        *,
        keep_trace: bool = False,
        count_step: bool = False,
    ) -> list[Tok] | object:
        r"""``MacroDef`` 可展门 + ``_invoke`` + ``ArgMismatch`` 回吐的共用骨架。

        ``_expand_once``/``_case_expand_cs``/``next_expanded`` 三处单步分派
        平铺同一段 ``isinstance(r, MacroDef)`` → ``_EXPAND_KINDS`` /
        ``_can_expand`` 门 → ``_invoke``（§3.5 失配回吐）——仅投影面不同，
        归一为小结果由各点自映：

        - ``list[Tok]``：代入产物——``_expand_once`` 直返；``_case_expand_cs``
          ``unread`` 后 ``True``；``next_expanded`` ``unread`` 后不动点续圈；
        - ``_NOT_MACRO``：``r`` 非 ``MacroDef``——调用点续走 str 别名/原语名；
        - ``_BLOCKED``/``_MISMATCH``：调用点映 ``[t]``/``False``/交出 ``t``。

        ``keep_trace``：``_invoke`` 复用 ``self._trace`` 账。``False``
        （``_expand_once``/``next_expanded``）恒开新账不还（败账留待下次
        置新覆盖，与平铺旧码等价）；``True``（``_case_expand_cs``）外层
        扫 ``{`` 的回吐账先挂起、成败皆还。

        ``count_step``：``next_expanded`` 专属的 ``steps`` 预算记账
        （``_invoke`` 前 +1）；两处单步点刻意**不**计——``\expandafter``
        链与 ``{`` 扫描走有界单步，不占主流预算账（旧平铺即有此漂移，
        归一后差异收敛到本参数显式表达）。
        """
        if not isinstance(r, MacroDef):
            return _NOT_MACRO
        if r.kind not in _EXPAND_KINDS or not self._can_expand(t):
            return _BLOCKED
        if count_step:
            self.steps += 1
        saved = self._trace
        self._trace = []
        try:
            out = self._invoke(t, r)
        except ArgMismatch:
            self.unread(self._trace)
            if keep_trace:
                self._trace = saved
            return _MISMATCH
        if keep_trace:
            self._trace = saved
        return out

    def _expand_once(self, t: Tok) -> list[Tok]:  # noqa: PLR0911 — 表项/原语各态一分支
        r"""单步展开（``\expandafter`` 用）：可展宏/可展原语就地一步；其余 ``[t]``。"""
        if t.kind != "cs":
            return [t]
        e = self.macros.lookup(t.text)
        r = self.macros.resolve(e)
        out = self._try_expand_macro(t, r)
        if isinstance(out, list):
            return out
        if out is _BLOCKED or out is _MISMATCH:
            return [t]
        if isinstance(r, str):
            return self._expand_once(Tok("cs", r, t.pos, t.gen, t.origin))
        if r is None and t.text == "expandafter":
            # ``\expandafter`` 链（``\expandafter\expandafter``）：递归单步——
            # 同 ``_do_expandafter`` 语义，产物入返回列而非 unread。
            t1 = self.read()
            t2 = self.read()
            return ([t1] if t1 is not None else []) + (
                self._expand_once(t2) if t2 is not None else []
            )
        if r is None and t.text == "csname":
            return [self._read_csname()]
        if r is None and t.text == "noexpand":
            t2 = self.read()
            if t2 is not None:
                t2.xprotect = True
            return [t2] if t2 is not None else []
        if r is None and t.text == "romannumeral":
            return self._roman_expand(t)
        return [t]

    def _do_csname(self, _trig: Tok) -> Tok | None:
        r"""``\csname..\endcsname`` → 合成 cs token 推回（Primitives.py:413-424）。"""
        self.unread([self._read_csname()])
        return None

    def _read_csname(self) -> Tok:
        r"""读到 ``\endcsname`` 合成 cs；流尽 → 空名 cs（容忍）。"""
        name: list[str] = []
        start: tuple[int, int, int] | None = None
        while True:
            t = self.read()
            if t is None:
                break
            if start is None:
                start = t.pos
            if t.kind == "cs" and t.text == "endcsname":
                break
            name.append(str(t))
        pos = start if start is not None else (-1, -1, -1)
        return Tok("cs", "".join(name), pos)

    def _do_ifundefined(self, trig: Tok) -> Tok | None:
        r"""``\@ifundefined{name}{T}{F}`` 选支推回（Base/LaTeX ``__init__.py:36-45``）。

        ``name`` 已定义（宏表/原语/内建名集）→ 推 ``F``；否则推 ``T``。
        """
        trace = self._trace = []
        name = self._read_env_name(trace)
        if name is None:
            t = self._rt_skip(trace)
            name = t.text if t is not None and t.kind == "cs" else ""
        if name is None:
            name = ""
        t_arg = self._read_grouping(trace, "{", "}")
        f_arg = self._read_grouping(trace, "{", "}")
        t_arg = t_arg or []
        f_arg = f_arg or []
        defined = (
            self.macros.lookup(name) is not None or name in _PRIMS or name in _BUILTINS
        )
        sel = f_arg if defined else t_arg
        # 界标夹心（同 process_if）：lead marker 盖到选支首 token，
        # 尾 marker 随选支 unread 盖 [选支末, 调用末)——否则整调用
        # literal 后选支 surface 再进 chunk → 译文面 literal 原文 +
        # chunk 译文双发。
        fid = trig.pos[0]
        end = -1
        tail: Tok | None = None
        if trace and trace[-1].pos[0] == fid:
            if sel and sel[0].pos[0] == fid and sel[-1].pos[0] == fid:
                end = sel[0].pos[1]
                call_end = trace[-1].pos[2]
                if call_end > sel[-1].pos[2]:
                    tail = Tok(
                        "consumed",
                        f"ifundefined-end:{name}",
                        (fid, sel[-1].pos[2], call_end),
                        trig.gen,
                        trig.origin,
                    )
            elif not sel:
                end = trace[-1].pos[2]
        self.unread([*sel, *([tail] if tail is not None else [])])
        return self._consumed(f"ifundefined:{name}", trig, trace, end=end)

    # ------------------------------------------------------------ romannumeral/uppercase

    def _do_romannumeral(self, trig: Tok) -> Tok | None:
        r"""``\romannumeral<num>`` → 罗马字母推回（W28 idiom 的展开臂）。

        产物恒经 ``unread`` 回主流：``n>0`` → 小写罗马 letter token
        （``gen+1``/``origin=调用区间``——与宏代入同构，覆盖由 origin 兜）；
        ``n<=0``/不可求值/``n>3999`` → ``consumed`` marker（``\romannumeral0``
        扩张触发 idiom 与笔误同态：不产 token、调用段字节 literal 保住）。
        """
        self.unread(self._roman_expand(trig))
        return None

    def _roman_expand(self, trig: Tok) -> list[Tok]:
        r"""``\romannumeral`` 单步展开产物（``\expandafter``/原语分派共用）。"""
        n = self._read_number()
        lr = self._last_read
        end = (
            lr.pos[2]
            if lr is not None and lr.pos[0] == trig.pos[0] and lr.pos[2] > trig.pos[2]
            else trig.pos[2]
        )
        call = (trig.pos[0], trig.pos[1], end)
        if n is None or not 0 < int(n) <= _ROMAN_MAX:
            return [Tok("consumed", "romannumeral", call, trig.gen, trig.origin)]
        return [
            Tok("letter", ch, trig.pos, trig.gen + 1, call) for ch in _to_roman(int(n))
        ]

    def _do_case(self, trig: Tok, *, upper: bool) -> Tok | None:
        r"""``\uppercase``/``\lowercase{..}``（W28 idiom 的壳臂）。

        ``<general text>`` 扫 ``{`` 走 get_x_token 语义——途中可展开 token
        （``\expandafter``/``\csname``/``\romannumeral``/可展宏）就地展开，
        ``\relax``/空白作 filler；组内 letter/other 文本换大小写、gen+1/
        origin=整调用区间推回（产物文本 ``I`` 对源字节 ``i`` 不 reconcilable，
        gen 抬升即标识）。扫不到开组（非可展 cs/括号/流尽）→ 全回吐 +
        本体交出——``\uppercase`` 落 literal 比插 ``{`` 纠错安全。
        """
        trace = self._trace = []
        while True:
            t = self._rt_skip(trace)
            if t is None:
                self.unread(trace)
                return trig
            if t.kind == "lbrace":
                break
            if t.xprotect:
                t.xprotect = False
                self.unread(trace)
                return trig
            if t.kind == "cs" and t.text == "relax":
                continue
            if t.kind == "cs" and self._case_expand_cs(t):
                trace.pop()  # 已展开消费——回吐名单剔除（字节由调用 origin 兜）
                continue
            self.unread(trace)
            return trig
        inner = self._read_balanced(trace)
        last = trace[-1] if trace else None
        end = (
            last.pos[2]
            if last is not None and last.pos[0] == trig.pos[0]
            else trig.pos[2]
        )
        call = (trig.pos[0], trig.pos[1], end)
        gen = trig.gen + 1
        self.unread(
            [
                Tok(
                    t.kind,
                    t.text.upper() if upper else t.text.lower(),
                    t.pos,
                    gen,
                    call,
                    t.xprotect,
                )
                if t.kind in ("letter", "other")
                else Tok(t.kind, t.text, t.pos, gen, call, t.xprotect)
                for t in inner
            ]
        )
        return None

    def _case_expand_cs(self, t: Tok) -> bool:  # noqa: PLR0911 — 可展原语逐名分派平铺
        r"""``\uppercase`` 扫 ``{`` 途中的单枚 cs：可展开 → 展开推回 ``True``。"""
        name = t.text
        r = self.macros.resolve(self.macros.lookup(name))
        # _invoke 复用 _trace——扫 { 的回吐账挂起（keep_trace），成败皆还
        out = self._try_expand_macro(t, r, keep_trace=True)
        if isinstance(out, list):
            self.unread(out)
            return True
        if out is _BLOCKED or out is _MISMATCH:
            return False
        if isinstance(r, str):
            name = r
        if name == "expandafter":
            self._do_expandafter(t)
            return True
        if name == "csname":
            self._do_csname(t)
            return True
        if name == "noexpand":
            t2 = self.read()
            if t2 is not None:
                t2.xprotect = True
                self.unread([t2])
            return True
        if name == "romannumeral":
            self.unread(self._roman_expand(t))
            return True
        return False
