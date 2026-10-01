r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：\def 族。"""

from __future__ import annotations

from itertools import (
    pairwise,
)
from typing import (
    TYPE_CHECKING,
)

from texlate.latex.mouth import (
    Tok,
)

from .entries import (
    Arg,
    ArgMismatch,
    IfCond,
    IfSetter,
)
from .expand import (
    _BLOCKED,
    _MISMATCH,
)

if TYPE_CHECKING:
    from texlate.latex.gullet import (
        Gullet,
    )

# ``\edef`` 扫参期可展原语名集（``_exec_prim`` 分派面的无副作用子集）——
# ``\def/\let/\input/\catcode/\newif`` 族与 ``makeat*``/组原语不可展，
# ``\edef`` 体内原样留存（调用点再执行）；``if*`` 另由 startswith 兜。
_EAGER_PRIMS = frozenset(
    {
        "expandafter",
        "csname",
        "noexpand",
        "ifundefined",
        "@ifundefined",
        "@ifxundefined",
        "romannumeral",
        "uppercase",
        "lowercase",
        "par",
    }
)


def _group_closed(trace: list[Tok], bi: int) -> bool:
    r"""``trace[bi]`` 起的 ``{`` 组是否在 trace 内真闭合。

    ``_read_balanced`` 流尽容忍返回已收段——``trace[-1].kind=="rbrace"``
    可能只是**内层**组的右括号（``\def\x{{a}``+EOF 时 outer ``}`` 缺席
    而 trace 末枚恰是内层 ``}``）。从开括号重放 level，level-0 ``}``
    恰为 trace 末枚才算闭合。
    """
    level = 0
    for t in trace[bi:]:
        if t.kind == "lbrace":
            level += 1
        elif t.kind == "rbrace":
            level -= 1
            if level == 0:
                return t is trace[-1]
    return False


class _DefCmd:
    # ------------------------------------------------------------ \def 族

    def _do_def(
        self: Gullet,
        trig: Tok,
        *,
        global_: bool,
        eager: bool = False,
        head: Tok | None = None,
    ) -> Tok | None:
        r"""``\def\name<参数文本>{体}``（``DefCommand`` Primitives.py:127-168）。

        参数文本 = ``\name`` 与首个 ``{`` 间全部 token，定义时编译为 spec；
        ``##`` 检出后体/参数文本同折叠一层（Primitives.py:146-160）。
        ``\edef/\xdef``（``eager``）先对体跑一遍展开再登记（哨兵界标法）。
        ``head`` = ``\long/\outer/\global`` 前缀链首 token（marker span
        从它起算；缺省 = ``trig``）。
        """
        trace = self._trace = []
        nt = self._rt_skip(trace)
        # ``active`` 目标不登记：active token 永不查 macros，写进去只会毒同名 cs
        if nt is None or nt.kind != "cs":
            # 名非 cs = 正文谈 \def 的笔法（v1 _read_def_name None → 静默不记）
            self.unread(trace)
            return trig
        mname = nt.text
        # 参数文本：到首个 lbrace 止（brace 入账不归参数文本）
        ptext: list[Tok] = []
        brace: Tok | None = None
        while True:
            a = self._rt(trace)
            if a is None or a.kind == "lbrace":
                brace = a
                break
            ptext.append(a)
        if brace is None:
            return self._def_fail(trig, trace, "param text unterminated")
        bi = len(trace) - 1  # 开 ``{`` 在 trace 的索引（_rt 刚入账）
        body = self._read_balanced(trace)
        if not _group_closed(trace, bi):
            return self._def_fail(trig, trace, "def body unterminated")
        spec = self._compile_param_text(ptext, has_brace=True)
        if spec is None:
            return self._def_fail(trig, trace, "param text illegal")
        if self._has_double_hash(ptext):
            # `##` 在**参数文本**（非体）出现 → 该 def 写深了一层，ptext+ 体同折
            # （Primitives.py:146-160 的判定域是 args；体里的 ## 归 expand_def 管）
            ptext = self._fold_hashes(ptext)
            body = self._fold_hashes(body)
            spec = self._compile_param_text(ptext, has_brace=True)
            if spec is None:
                return self._def_fail(trig, trace, "param text illegal")
        if eager:
            body = self._expand_eager(body)
        return self._register_cmd(
            trig.text, mname, spec, body, trig, trace, global_=global_, head=head
        )

    def _expand_eager(self: Gullet, body: list[Tok]) -> list[Tok]:
        r"""``\edef/\xdef`` 体即时展开：体 + 哨兵推回，抽展开流到哨兵止。

        哨兵 kind 非 cs、不在任何分派面 → 必然原样浮出；``\noexpand`` 打标
        的 token 带 ``xprotect`` 存进体（调用点再展开时见标跳一次）。
        drain 走 ``_eager_step``——TeX ``\edef`` 只展开可展 token，副作用
        原语（``\def/\let/\input/\catcode`` 族）扫参期**不执行**、原样留体
        （``\edef\x{\def\y{a}}`` 的 ``\y`` 登记属调用时语义，不在此触发）。
        """
        sentinel = Tok("_edef_end", "", (-1, -1, -1))
        self.unread([*body, sentinel])
        out: list[Tok] = []
        while True:
            t = self._eager_step()
            if t is None or t is sentinel:
                return out
            out.append(t)

    def _eager_step(self: Gullet) -> Tok | None:  # noqa: C901, PLR0911, PLR0912 — next_expanded 的可展子集分派
        r"""``\edef`` drain 单步——``next_expanded`` 的可展开子集同构。

        宏表侧同径（可展 ``MacroDef`` 代入 / ``IfCond`` 求值 / 别名换名），
        原语侧收窄到 ``_EAGER_PRIMS`` + ``if*``：副作用原语与 ``IfSetter``
        直交字面——``\edef`` 扫参期不执行，随体留存到调用点。
        """
        while True:
            t = self.read()
            if t is None:
                return None
            if t.kind != "cs":
                return t
            if t.xprotect:
                t.xprotect = False  # \noexpand 打标：见标跳过一次展开
                return t
            name = t.text
            entry = self.macros.lookup(name)
            if entry is not None:
                r = self.macros.resolve(entry)
                out = self._try_expand_macro(t, r, count_step=True)
                if isinstance(out, list):
                    self.unread(out)
                    continue
                if out is _BLOCKED or out is _MISMATCH:
                    return t
                if isinstance(r, IfCond):
                    if not self._can_expand(t):
                        return t
                    self.steps += 1
                    # 界标夹心同主流（process_if 契约见 cond.py）
                    end = self.process_if(
                        self.ifflags.get(r.flag, False), trig=t, tail_tag=f"fi:{name}"
                    )
                    return self._consumed(
                        f"if:{name}", t, None, end=end if end is not None else t.pos[2]
                    )
                if isinstance(r, IfSetter):
                    return t  # 写 ifflags 是副作用——扫参期留字面
                if isinstance(r, Tok):  # \let 字面别名 → 以触发位交出
                    return Tok(r.kind, r.text, t.pos, t.gen, t.origin)
                if isinstance(r, str):  # \let 到原语名 → 换名走原语分派
                    t = Tok("cs", r, t.pos, t.gen, t.origin)
                    name = r
                else:
                    return t  # Alias(None)：定义时未解析 → 未知命令
            if name in _EAGER_PRIMS or name.startswith("if"):
                if not self._can_expand(t):
                    return t
                self.steps += 1
                self._trace = []
                try:
                    out = self._exec_prim(t)
                except ArgMismatch:
                    self.unread(self._trace)
                    return t  # §3.5：回吐已读 + 本体交出
                if out is None:
                    continue
                return out
            return t

    @staticmethod
    def _trace_end(trace: list[Tok]) -> int:
        """Trace 末 token 的 end（def 登记 src 用）。"""
        return trace[-1].pos[2] if trace else -1

    def _def_fail(self: Gullet, trig: Tok, trace: list[Tok], why: str) -> Tok:
        r"""定义解析失败（§3.5）：不登记 + 全部回吐 + ``\def`` 本体交出。"""
        self._warn("def_parse_fail", trig, why)
        self.unread(trace)
        return trig

    def _do_prefix(self: Gullet, trig: Tok, name: str) -> Tok | None:
        r"""``\long/\outer/\global/\protected`` 前缀：链到定义族才生效。

        链目标 = ``\def`` 族 + ``\let`` + ``\newif``（任意序前缀均可叠）；
        ``\global`` 传 scope（``\global\let`` 组内写底帧），
        ``\long/\outer/\protected`` 消费不传递（语义未建模——吞掉字节防
        前缀泄 literal）。链外目标 → 回吐 + 本体交出（保守：``\global``
        续 ``\catcode`` 这类写透未实现，见 ``CatTable.set`` 注）。
        """
        trace = self._trace = []
        seen_global = name == "global"
        while True:
            t = self._rt_skip(trace)
            if t is None:
                self.unread(trace)
                return trig
            if t.kind == "cs" and t.text in (
                "long",
                "outer",
                "global",
                "protected",
            ):
                seen_global = seen_global or t.text == "global"
                continue
            if t.kind == "cs" and t.text in ("def", "edef", "gdef", "xdef"):
                return self._do_def(
                    t,
                    global_=seen_global or t.text in ("gdef", "xdef"),
                    eager=t.text in ("edef", "xdef"),
                    head=trig,  # marker/src 从首个前缀 token 起算
                )
            if t.kind == "cs" and t.text == "let":
                return self._do_let(t, global_=seen_global, head=trig)
            if t.kind == "cs" and t.text == "newif":
                return self._do_newif(t, global_=seen_global, head=trig)
            self.unread(trace)
            return trig

    @staticmethod
    def _has_double_hash(toks: list[Tok]) -> bool:
        """检测相邻 ``##``（嵌套定义标记）。"""
        return any(a.kind == "param" and b.kind == "param" for a, b in pairwise(toks))

    @staticmethod
    def _fold_hashes(toks: list[Tok]) -> list[Tok]:
        r"""``##`` 折叠一层（Primitives.py:146-160）：每段 ``#`` 连跑去一。

        k 个连续 ``#`` + 非 ``#`` → k−1 个 ``#`` 留下。
        """
        out: list[Tok] = []
        run = 0
        for t in toks:
            if t.kind == "param":
                run += 1
                out.append(t)
            else:
                if run > 1:
                    out.pop()
                run = 0
                out.append(t)
        if run > 1:
            out.pop()  # 尾端 ``#`` 连跑同折一层（``##``→``#``）
        return out

    @staticmethod
    def _param_count(spec: list[Arg]) -> int:
        """参数位数（``literal_match``/``eq`` 不占位）。"""
        return sum(1 for a in spec if a.kind not in ("literal_match", "eq"))

    def _compile_param_text(  # noqa: C901, PLR0912 — 参数文本文法平铺即 §8.4 表
        self: Gullet, ptext: list[Tok], *, has_brace: bool
    ) -> list[Arg] | None:
        r"""``\def`` 参数文本 → ``list[Arg]``（§8.4/§5.2 编译表）。

        ``#``+数字 → 新参数槽；``#``+``#`` → 跳过；``#``+流末（且参数文本
        止于 ``{``）→ 前一槽 ``until_group``；非 ``#`` 有槽 → 追加 delim；
        非 ``#`` 无槽 → ``literal_match``；尾随槽 → ``'m'``。
        """
        spec: list[Arg] = []
        pending: Arg | None = None
        i, n = 0, len(ptext)
        while i < n:
            a = ptext[i]
            if a.kind != "param":
                if pending is not None:
                    pending.kind = "delim"
                    pending.delim.append(a)
                else:
                    spec.append(Arg("literal_match", delim=[a]))
                i += 1
                continue
            nxt = ptext[i + 1] if i + 1 < n else None
            if nxt is None:
                # 尾随裸 '#'（参数文本止于 '{'）：TeX `#{` 语义——
                # pending 无 delim → until_group；有 delim → 保留 +
                # brace_after（`#1 abc#{` 的 abc 定界不丢）
                if has_brace:
                    if pending is None:
                        spec.append(Arg("until_group"))
                    elif pending.kind == "delim" and pending.delim:
                        pending.brace_after = True
                    else:
                        pending.kind = "until_group"
                    i += 1
                    continue
                return None
            if nxt.kind == "param":  # '##' → 跳过（折叠残留容忍）
                i += 2
                continue
            if nxt.kind == "lbrace":  # '#{' 同尾随形（防御：正常不可达）
                if pending is None:
                    spec.append(Arg("until_group"))
                elif pending.kind == "delim" and pending.delim:
                    pending.brace_after = True
                else:
                    pending.kind = "until_group"
                i += 2
                continue
            if nxt.kind != "cs" and len(nxt.text) == 1 and nxt.text.isdigit():
                pending = Arg("m")
                spec.append(pending)
                i += 2
                continue
            return None  # '#' + 其他 → 参数文本非法
        return spec
