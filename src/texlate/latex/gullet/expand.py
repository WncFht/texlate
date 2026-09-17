r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：expandafter/csname/ifundefined。"""

from __future__ import annotations

from texlate.latex.mouth import (
    Tok,
)

from .entries import (
    ArgMismatch,
    MacroDef,
)
from .tables import (
    _BUILTINS,
    _EXPAND_KINDS,
    _PRIMS,
)


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

    def _expand_once(self, t: Tok) -> list[Tok]:  # noqa: PLR0911 — 表项/原语各态一分支
        r"""单步展开（``\expandafter`` 用）：宏 → 读参代入；其余 → ``[t]``。"""
        if t.kind != "cs":
            return [t]
        e = self.macros.lookup(t.text)
        r = self.macros.resolve(e)
        if isinstance(r, MacroDef):
            if r.kind not in _EXPAND_KINDS or not self._can_expand(t):
                return [t]
            self._trace = []
            try:
                return self._invoke(t, r)
            except ArgMismatch:
                self.unread(self._trace)
                return [t]
        if isinstance(r, str):
            return self._expand_once(Tok("cs", r, t.pos, t.gen, t.origin))
        if r is None and t.text == "csname":
            return [self._read_csname()]
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
