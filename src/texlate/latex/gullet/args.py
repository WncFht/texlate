r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：spec 参数读取 + invoke 代入。"""

from __future__ import annotations

from texlate.latex.mouth import (
    Tok,
)

from .entries import (
    ArgMismatch,
    MacroDef,
)
from .tokutil import (
    _tok_eq,
    expand_def,
)


class _Args:
    # ------------------------------------------------------------ 参数读取
    # 全部走 read()（原始未展开流，TeX.py:704-714 同构）；消费计入 trace。

    def _rt(self, trace: list[Tok]) -> Tok | None:
        """``read()`` + 消费计入 ``trace``（回吐账户）。"""
        t = self.read()
        if t is not None:
            trace.append(t)
        return t

    def _rt_skip(self, trace: list[Tok]) -> Tok | None:
        """``_rt`` 跳过 space token（eol_par 不跳——不定界参不跨段）。"""
        while True:
            t = self._rt(trace)
            if t is None or t.kind != "space":
                return t

    def _pushback(self, trace: list[Tok], t: Tok) -> None:
        """已读 token 回吐流且销账（防 unread(trace) 双份）。"""
        trace.pop()
        self.unread([t])

    def _read_undelimited(self, trace: list[Tok]) -> list[Tok]:
        r"""不定界参（``readToken`` TeX.py:786-841）。

        跳前导空白后：``{`` → 平衡组（剥外层括号）；``$`` → 到下一 ``$`` 止
        （含两端）；``eol_par`` → 回吐 + mismatch；其余 → 单 token。
        """
        t = self._rt_skip(trace)
        if t is None:
            raise ArgMismatch
        if t.kind == "lbrace":
            return self._read_balanced(trace)
        if t.kind == "mathshift":
            out = [t]
            while True:
                t2 = self._rt(trace)
                if t2 is None:
                    return out
                out.append(t2)
                if t2.kind == "mathshift":
                    return out
        if t.kind == "eol_par":
            self._pushback(trace, t)
            raise ArgMismatch
        return [t]

    def _read_balanced(self, trace: list[Tok]) -> list[Tok]:
        """``{`` 已消费 → 收到配对 ``}`` 止（内层含括号，外层剥掉）。"""
        out: list[Tok] = []
        level = 1
        while True:
            t = self._rt(trace)
            if t is None:
                return out  # 流尽：容忍返回已收（调用方判 group 完整性）
            if t.kind == "lbrace":
                level += 1
            elif t.kind == "rbrace":
                level -= 1
                if level == 0:
                    return out
            out.append(t)

    def _read_grouping(  # noqa: C901 — 自定界组三类开符合一
        self, trace: list[Tok], open_c: str, close_c: str
    ) -> list[Tok] | None:
        r"""``[..]``/``<..>`` 可选参（``readGrouping`` TeX.py:863-908）。

        首非空白 token 非 opener → 回吐 + ``None``（缺席）；读到 close 止
        （配对计数；定界 token 消费不入参）。流尽 → ``ArgMismatch``。
        """
        t = self._rt_skip(trace)
        if t is None:
            return None
        if open_c == "{":
            if t.kind != "lbrace":
                self._pushback(trace, t)
                return None
        elif t.kind == "cs" or t.text != open_c:
            self._pushback(trace, t)
            return None
        out: list[Tok] = []
        level = 1
        depth = 0  # ``{…}`` 组内深度：``]``/``>`` 自定界参尊重平衡组屏蔽
        brace_form = close_c == "}"  # ``{…}`` 形由 level 自管，不走 depth
        while True:
            t2 = self._rt(trace)
            if t2 is None:
                raise ArgMismatch
            if t2.kind != "cs":
                if not brace_form and t2.kind == "lbrace":
                    depth += 1
                elif not brace_form and t2.kind == "rbrace" and depth > 0:
                    depth -= 1
                elif depth == 0 and (
                    t2.text == open_c and (open_c != "{" or t2.kind == "lbrace")
                ):
                    level += 1
                elif depth == 0 and (
                    t2.text == close_c or (brace_form and t2.kind == "rbrace")
                ):
                    level -= 1
                    if level == 0:
                        return out
            out.append(t2)

    def _read_delimited(self, trace: list[Tok], delim: list[Tok]) -> list[Tok]:
        r"""定界参（``__init__.py:1211-1219``）：读到后缀==``delim`` 止。

        定界 token 消费不入参；``{`` 起平衡组整组入参（**含括号**——组内
        定界符不匹配，比 plasTeX 逐 token 判定更贴 TeX）。流尽 → mismatch。
        """
        out: list[Tok] = []
        k = len(delim)
        while True:
            t = self._rt(trace)
            if t is None:
                raise ArgMismatch
            if t.kind == "lbrace":
                grp = self._read_balanced(trace)
                out.append(t)
                out.extend(grp)
                # 组闭合括号补回（grp 不含外层}）
                out.append(Tok("rbrace", "}", grp[-1].pos if grp else t.pos))
                continue
            out.append(t)
            if len(out) >= k and all(_tok_eq(out[-k + j], delim[j]) for j in range(k)):
                del out[-k:]
                return out

    def _read_until_lbrace(self, trace: list[Tok]) -> list[Tok]:
        r"""``#{`` 型：读到 ``lbrace`` 回吐不消费（``__init__.py:1196-1205``）。"""
        out: list[Tok] = []
        while True:
            t = self._rt(trace)
            if t is None:
                raise ArgMismatch
            if t.kind == "lbrace":
                self._pushback(trace, t)
                return out
            out.append(t)

    def _read_star(self, trace: list[Tok], char: str) -> list[Tok]:
        """``*``/``tX`` 可选修饰：命中 → ``[tok]``；否则回吐 + ``[]``。"""
        t = self._rt_skip(trace)
        if t is not None and t.kind != "cs" and t.text == char:
            return [t]
        if t is not None:
            self._pushback(trace, t)
        return []

    def _read_eq(self, trace: list[Tok]) -> None:
        r"""``\let\a=\b`` 的可选 ``=``：不占参数位。"""
        t = self._rt_skip(trace)
        if t is not None and (t.kind == "cs" or t.text != "="):
            self._pushback(trace, t)

    # ------------------------------------------------------------ invoke

    def _invoke(  # noqa: C901, PLR0912 — spec 参数型平铺即 §4.1 表
        self, trig: Tok, m: MacroDef
    ) -> list[Tok]:
        r"""按 ``spec`` 读参 + ``expand_def`` 代入（§5.3/§5.4 统一）。

        ``literal_match``/``eq`` 不占参数位；``o`` 缺席 → ``default``
        （None → 代入时该 ``#i`` 不产出）。``ArgMismatch`` 由调用方回吐。
        """
        if not m.spec:
            return self._stamp_call_origin(expand_def(m.body, {}, trig), trig)
        trace = self._trace
        params: dict[int, list[Tok] | None] = {}
        slot = 0
        for a in m.spec:
            k = a.kind
            if k == "literal_match":
                t = self._rt(trace)
                if t is None or not _tok_eq(t, a.delim[0]):
                    raise ArgMismatch
                continue
            if k == "eq":
                self._read_eq(trace)
                continue
            slot += 1
            if k == "m":
                params[slot] = self._read_undelimited(trace)
            elif k == "o":
                params[slot] = self._read_grouping(trace, a.open, a.close)
                if params[slot] is None:
                    params[slot] = a.default
            elif k == "star":
                params[slot] = self._read_star(trace, a.char)
            elif k == "delim":
                params[slot] = self._read_delimited(trace, a.delim)
                if a.brace_after:  # `#1 abc#{`：delim 后还需 `{`，读一回吐
                    t2 = self._rt(trace)
                    if t2 is not None:
                        self._pushback(trace, t2)
            elif k == "until_group":
                params[slot] = self._read_until_lbrace(trace)
            elif k == "e":
                # 修饰参 e{^_}：每字符至多一次、X{arg}/X<tok>——与分段器
                # _args_tok 'e' 分支同规（cs 不作参、缺席只留符）
                emb: list[Tok] = []
                rest = {t.text for t in a.delim}
                while rest:
                    t = self._rt_skip(trace)
                    if t is None or t.kind == "cs" or t.text not in rest:
                        if t is not None:
                            self._pushback(trace, t)
                        break
                    rest.discard(t.text)
                    emb.append(t)
                    z = self._rt_skip(trace)
                    if z is not None:
                        self._pushback(trace, z)
                        if z.kind != "cs":
                            emb.extend(self._read_undelimited(trace))
                params[slot] = emb
            else:
                raise ArgMismatch
        return self._stamp_call_origin(expand_def(m.body, params, trig), trig)

    def _stamp_call_origin(self, out: list[Tok], trig: Tok) -> list[Tok]:
        r"""产物 ``origin`` 补打为**整调用区间** ``(fid, trig.start, trace末.end)``。

        ``expand_def`` 只打 ``trig.pos``（cs 名区间）——``\sw{a}{b}`` 的
        args 字节会漏出 EXPAND/``ph_map[CHUNK]`` 的 identity 切片
        （segmenter-integration §4 表首行）。嵌套展开的产物已带最外层
        调用点 origin，不动；``gen=0`` 实参 token（pos 落在调用区间内的
        真源 token）也不动——它们靠 pos 归组、靠自身 pos 切 ident。
        """
        last = self._trace[-1] if self._trace else None
        if (
            trig.origin is not None
            or last is None
            or last.gen != 0  # 实参是上游展开产物 → 调用区间不连续，退回 cs 名
            or last.pos[0] != trig.pos[0]
            or last.pos[2] <= trig.pos[2]
        ):
            return out
        call = (trig.pos[0], trig.pos[1], last.pos[2])
        return [
            Tok(
                x.kind,
                x.text,
                x.pos,
                x.gen,
                call if x.origin == trig.pos else x.origin,
                x.xprotect,
            )
            for x in out
        ]
