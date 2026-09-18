r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：\newcommand 族 + \let/\newif/\catcode。"""

from __future__ import annotations

from texlate.latex.mouth import (
    Mouth,
    Tok,
)
from texlate.latex.tables import (
    MATH_ENVS,
)

from .entries import (
    Alias,
    Arg,
    EnvDef,
    IfCond,
    IfSetter,
    MacroDef,
)
from .tables import (
    _BUILTINS,
    _MATH_CS,
    _MATH_OPEN_CS,
    _PRIMS,
)
from .tokutil import (
    _surface,
)


class _Decls:
    # ------------------------------------------------------------ \newcommand 族

    def _eat_star(self, trace: list[Tok]) -> None:
        r"""``\newcommand*`` 等的可选 ``*``：吃掉或回吐（仅占位不产参数）。"""
        t = self._rt_skip(trace)
        if t is not None and (t.kind == "cs" or t.text != "*"):
            self._pushback(trace, t)

    def _read_def_name(self, trace: list[Tok]) -> str | None:
        r"""``{\cmd}`` 或 ``\cmd`` 读宏名（``name:cs``）。"""
        t = self._rt_skip(trace)
        if t is None:
            return None
        if t.kind == "cs":
            return t.text
        if t.kind == "lbrace":
            inner = self._read_balanced(trace)
            for x in inner:
                if x.kind == "cs":
                    return x.text
            return ""
        return None

    def _read_opt_int(self, trace: list[Tok]) -> tuple[int | None, list[Tok] | None]:
        """可选 ``[n]``：返回 ``(int 值, 原始 token 列)``；缺席 ``(None, None)``。"""
        grp = self._read_grouping(trace, "[", "]")
        if grp is None:
            return None, None
        txt = _surface(grp).strip()
        try:
            return int(txt or 0), grp
        except ValueError:
            return 0, grp

    def _do_newcmd(self, trig: Tok, name: str) -> Tok | None:
        r"""``\newcommand[*]{\n}[N][d]{B}``（``Definitions.py:15-24``）。

        ``*`` 只吃 token；``[N][d]`` 同在 → ``spec=[o(d)]+m×(N-1)``——
        N **含**可选位（plasTeX ``nargs-1`` ``__init__.py:1145-1147``）。
        """
        trace = self._trace = []
        self._eat_star(trace)
        mname = self._read_def_name(trace)
        if mname is None:
            return self._def_fail(trig, trace, "newcommand name")
        nargs, _ = self._read_opt_int(trace)
        default = self._read_grouping(trace, "[", "]")  # 缺省值是 token 列非 int
        n = nargs or 0
        brace = self._rt_skip(trace)
        if brace is None or brace.kind != "lbrace":
            return self._def_fail(trig, trace, "newcommand body")
        body = self._read_balanced(trace)
        spec: list[Arg] = []
        if default is not None:
            spec.append(Arg("o", default=default))
            n = max(n - 1, 0)
        spec.extend(Arg("m") for _ in range(n))
        kind, target, protect = self._classify(body, self._param_count(spec))
        entry = MacroDef(
            name=mname,
            spec=spec,
            body=body,
            kind=kind,
            target_env=target,
            protect_args=protect,
            src=(trig.pos[0], trig.pos[1], self._trace_end(trace)),
        )
        if name == "providecommand":
            self.macros.setdefault(mname, entry)
        else:
            self.macros.set(mname, entry)
        return self._consumed(f"{name}:{mname}", trig, trace)

    def _do_newenv(self, trig: Tok) -> Tok | None:
        r"""``\newenvironment[*]{env}[N][d]{before}{after}``（Definitions.py:42-51）。"""
        trace = self._trace = []
        self._eat_star(trace)
        envname = self._read_env_name(trace)
        if envname is None:
            return self._def_fail(trig, trace, "newenvironment name")
        nargs, _ = self._read_opt_int(trace)
        default = self._read_grouping(trace, "[", "]")
        before = self._read_grouping(trace, "{", "}")
        if before is None:
            return self._def_fail(trig, trace, "newenvironment before")
        after = self._read_grouping(trace, "{", "}")
        if after is None:
            return self._def_fail(trig, trace, "newenvironment after")
        spec: list[Arg] = []
        n = nargs or 0
        if default is not None:
            spec.append(Arg("o", default=default))
            n = max(n - 1, 0)
        spec.extend(Arg("m") for _ in range(n))
        kind = "transparent"  # env 保护性归分段器按 ENV 表裁决（v1 一律 transparent）
        self.macros.set_env(
            EnvDef(
                name=envname,
                spec=spec,
                before=before,
                after=after,
                kind=kind,
                body_role=self._env_body_role(before),
            )
        )
        return self._consumed(f"newenv:{envname}", trig, trace)

    def _env_is_math(self, env: str) -> bool:
        r"""Env 名判数学：内建 ``MATH_ENVS`` / 已注册 ``body_role=math`` 用户 env。"""
        if env in MATH_ENVS or env.rstrip("*") in MATH_ENVS:
            return True
        reg = self.macros.lookup_env(env)
        return reg is not None and reg.body_role == "math"

    def _env_body_role(self, before: list[Tok]) -> str:
        r"""``\newenvironment`` before 体尾开数学 → ``"math"``（否则 ``""``）。

        1003.0112（miss×180）：before 尾 ``\eqnarray`` 的 env 体实为数学，
        无名表可追——尾部推断覆盖 ``$``/``$$``、``\eqnarray`` 族内核名、
        ``\(`/``\[``、``\begin{math-env}``、env_begin→math-env 宏端点与
        ``body_role=math`` 用户 env 套娃；其余一律 ``""``。
        """
        i = len(before) - 1
        while i >= 0 and before[i].kind in ("space", "eol_par"):
            i -= 1
        if i < 0:
            return ""
        t = before[i]
        if t.kind == "mathshift":
            return "math"
        if t.kind == "rbrace":
            return self._env_tail_begin_role(before, i)
        if t.kind != "cs":
            return ""
        if t.text in _MATH_OPEN_CS:
            return "math"
        r = self.macros.resolve(self.macros.lookup(t.text))
        math = (
            isinstance(r, MacroDef)
            and r.kind == "env_begin"
            and self._env_is_math(r.target_env)
        )
        return "math" if math else ""

    def _env_tail_begin_role(self, before: list[Tok], i: int) -> str:
        r"""``\begin{env}`` 收尾尾形：回找配对 ``{``，前驱 cs 为 ``\begin`` 才取 env 名。"""
        depth, j = 1, i - 1
        while j >= 0:
            if before[j].kind == "rbrace":
                depth += 1
            elif before[j].kind == "lbrace":
                depth -= 1
                if depth == 0:
                    break
            j -= 1
        if j < 0:
            return ""
        k = j - 1
        while k >= 0 and before[k].kind in ("space", "eol_par"):
            k -= 1
        if k < 0 or before[k].kind != "cs" or before[k].text != "begin":
            return ""
        env = _surface(before[j + 1 : i]).strip()
        return "math" if self._env_is_math(env) else ""

    def _read_env_name(self, trace: list[Tok]) -> str | None:
        """``{env}`` 读环境名（``name:str``）。"""
        grp = self._read_grouping(trace, "{", "}")
        if grp is None:
            return None
        return _surface(grp).strip()

    def _do_newtheorem(self, trig: Tok) -> Tok | None:
        r"""``\newtheorem{n}[c]{cap}[w]``（Definitions.py:61-90）→ 定理类 env。"""
        trace = self._trace = []
        self._eat_star(trace)
        envname = self._read_env_name(trace)
        if envname is None:
            return self._def_fail(trig, trace, "newtheorem name")
        self._read_grouping(trace, "[", "]")  # [counter] 吃掉不用
        cap = self._read_grouping(trace, "{", "}")
        if cap is None:
            return self._def_fail(trig, trace, "newtheorem caption")
        self._read_grouping(trace, "[", "]")  # [within]
        self.macros.set_env(
            EnvDef(name=envname, spec=[Arg("o")], caption=cap, kind="theorem")
        )
        return self._consumed(f"newtheorem:{envname}", trig, trace)

    def _do_mathop(self, trig: Tok) -> Tok | None:
        r"""``\DeclareMathOperator[*]{\n}{B}`` → 体包 ``\operatorname{B}``（amsmath.py:111-123）。"""
        trace = self._trace = []
        self._eat_star(trace)
        mname = self._read_def_name(trace)
        if mname is None:
            return self._def_fail(trig, trace, "DeclareMathOperator name")
        grp = self._read_grouping(trace, "{", "}")
        if grp is None:
            return self._def_fail(trig, trace, "DeclareMathOperator body")
        body = [
            Tok("cs", "operatorname", trig.pos),
            Tok("lbrace", "{", trig.pos),
            *grp,
            Tok("rbrace", "}", trig.pos),
        ]
        self.macros.set(
            mname,
            MacroDef(
                name=mname,
                spec=[],
                body=body,
                kind="math",
                src=(trig.pos[0], trig.pos[1], self._trace_end(trace)),
            ),
        )
        return self._consumed(f"mathop:{mname}", trig, trace)

    def _do_xparse(self, trig: Tok, name: str) -> Tok | None:
        r"""``\NewDocumentCommand{\n}{spec}{B}``（§4.3 xparse 子集）。

        spec 含 ``v/b/e/E/x`` → 整条不登记（体原样回吐走字面）。
        """
        trace = self._trace = []
        mname = self._read_def_name(trace)
        if mname is None:
            return self._def_fail(trig, trace, "xparse name")
        spec_grp = self._read_grouping(trace, "{", "}")
        if spec_grp is None:
            return self._def_fail(trig, trace, "xparse spec")
        spec = self._parse_xparse(_surface(spec_grp))
        if spec is None:
            return self._def_fail(trig, trace, "xparse unsupported spec")
        body = self._read_grouping(trace, "{", "}")
        if body is None:
            return self._def_fail(trig, trace, "xparse body")
        kind, target, protect = self._classify(body, self._param_count(spec))
        entry = MacroDef(
            name=mname,
            spec=spec,
            body=body,
            kind=kind,
            target_env=target,
            protect_args=protect,
            src=(trig.pos[0], trig.pos[1], self._trace_end(trace)),
        )
        if name == "ProvideDocumentCommand":
            self.macros.setdefault(mname, entry)
        else:
            self.macros.set(mname, entry)
        return self._consumed(f"xparse:{mname}", trig, trace)

    def _parse_xparse(self, s: str) -> list[Arg] | None:  # noqa: C901, PLR0912, PLR0915 — spec 字母平铺即 §4.3 表
        """Xparse spec 串 → ``list[Arg]``；不支持字母 → ``None``。"""
        out: list[Arg] = []
        i, n = 0, len(s)

        def _braced(j: int) -> tuple[str | None, int]:
            """``{..}`` 取内容（不配对括号）。"""
            if j < n and s[j] == "{":
                e = s.find("}", j + 1)
                if e >= 0:
                    return s[j + 1 : e], e + 1
            return None, j

        while i < n:
            ch = s[i]
            i += 1
            if ch in " \t\n+":
                continue
            if ch == "m":
                out.append(Arg("m"))
            elif ch == "o":
                out.append(Arg("o"))
            elif ch == "O":
                d, i = _braced(i)
                out.append(Arg("o", default=self._lex(d or "")))
            elif ch == "s":
                out.append(Arg("star", char="*"))
            elif ch == "t":
                if i < n:
                    out.append(Arg("star", char=s[i]))
                    i += 1
                else:
                    out.append(Arg("star"))
            elif ch in "dD":
                if i + 1 < n:
                    a = Arg("o", open=s[i], close=s[i + 1])
                    i += 2
                    if ch == "D":
                        d, i = _braced(i)
                        a.default = self._lex(d or "")
                    out.append(a)
                else:
                    return None
            elif ch in "rR":
                if i + 1 < n:
                    open_c, close_c = s[i], s[i + 1]
                    i += 2
                    if ch == "r":
                        # r<> 必填：literal_match 开符 + delim 收内容（只占一槽）
                        out.append(
                            Arg(
                                "literal_match",
                                delim=[Tok("other", open_c, (-1, -1, -1))],
                            )
                        )
                        out.append(
                            Arg(
                                "delim",
                                delim=[Tok("other", close_c, (-1, -1, -1))],
                            )
                        )
                    else:
                        # R<> 带缺省 → 等价 'o' 自定界
                        a = Arg("o", open=open_c, close=close_c)
                        d, i = _braced(i)
                        a.default = self._lex(d or "")
                        out.append(a)
                else:
                    return None
            elif ch == "u":
                d, i = _braced(i)
                if d is None:
                    return None
                out.append(Arg("delim", delim=self._lex(d)))
            elif ch == "g":
                out.append(Arg("o", open="{", close="}"))
            elif ch == "l":
                out.append(Arg("until_group"))
            elif ch == "e":
                d, i = _braced(i)
                if d is None:
                    return None
                out.append(Arg("e", delim=self._lex(d)))
            elif ch in "vbEx":
                return None  # 不支持的参数型 → 整条不登记
            else:
                continue  # 未知字母跳过（容错）
        return out

    def _lex(self, s: str) -> list[Tok]:
        """字面串 → token 列（xparse 默认值/``u{}`` 定界用；共享 cats）。"""
        return list(Mouth(s, -1, self.cats))

    # ------------------------------------------------------------ \let/\newif/\catcode

    def _do_let(
        self, trig: Tok, *, global_: bool = False, head: Tok | None = None
    ) -> Tok | None:
        r"""``\let\a[=]\b``（Primitives.py:369-374 + Context.py:1175-1193）。

        cs 目标 → 当时表项**快照**（MacroDef/IfCond/IfSetter/原语名 str /
        None）；非 cs → 字面 token 别名。``global_``/``head`` 由
        ``_do_prefix`` 链透传（``\global\let`` 写底帧、marker 从前缀起算）。
        """
        trace = self._trace = []
        scope = "global" if global_ else "local"
        nt = self._rt_skip(trace)
        if nt is None or nt.kind not in ("cs", "active"):
            self.unread(trace)
            return trig
        self._read_eq(trace)
        src = self._rt_skip(trace)
        if src is None:
            self.unread(trace)
            return trig
        if src.kind == "cs":
            e = self.macros.lookup(src.text)
            if e is not None:
                tgt = self.macros.resolve(e)
            elif (
                src.text in _PRIMS
                or src.text.startswith("if")
                or src.text in _BUILTINS
                or src.text in _MATH_CS
            ):
                # 原语/内建/数学命令名引用：\let\mycite\cite、\let\ra\rangle
                # 换名后调用点按绑定名出流（W46——下游按名分派拿到真身）
                tgt = src.text
            else:
                tgt = None
            self.macros.set(nt.text, Alias(tgt), scope)
        else:
            self.macros.set(nt.text, Alias(src), scope)
        return self._consumed(f"let:{nt.text}", trig, trace, head)

    def _do_newif(
        self, trig: Tok, *, global_: bool = False, head: Tok | None = None
    ) -> Tok | None:
        r"""``\newif\ifX`` 三项登记（Context.newif Context.py:1008-1041）。

        ``\ifX`` → ``IfCond`` 求值项；``\Xtrue``/``\Xfalse`` → ``IfSetter``
        写 ``ifflags[flag]``，token 本体原样交分段器。``global_``/``head``
        由 ``_do_prefix`` 链透传（``\global\newif`` 三项写底帧）。
        """
        trace = self._trace = []
        scope = "global" if global_ else "local"
        nt = self._rt_skip(trace)
        if nt is None or nt.kind != "cs" or not nt.text.startswith("if"):
            self.unread(trace)
            self._warn("def_parse_fail", trig, "newif name")
            return trig
        flag = nt.text[2:]
        self.ifflags[flag] = False
        self.macros.set(nt.text, IfCond(flag), scope)
        self.macros.set(flag + "true", IfSetter(flag, value=True), scope)
        self.macros.set(flag + "false", IfSetter(flag, value=False), scope)
        return self._consumed(f"newif:{flag}", trig, trace, head)

    def _do_catcode(self, trig: Tok) -> Tok | None:
        r"""``\catcode`<ch>=<num>``（Primitives.py:401-411）。"""
        trace = self._trace = []
        t = self._rt_skip(trace)
        if t is None or t.text != "`":
            self.unread(trace)
            return trig
        ct = self._rt(trace)
        if ct is None:
            self.unread(trace)
            return trig
        ch = ct.text[0] if ct.text else "\x00"
        eq = self._rt_skip(trace)
        if eq is not None and eq.text != "=":
            self._pushback(trace, eq)  # '=' 可选
        v = self._read_number()
        if v is None:
            self.unread(trace)
            return trig
        self.cats.set(ch, int(v) & 15)
        return self._consumed("catcode", trig, trace)
