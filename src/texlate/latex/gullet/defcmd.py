r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：\def 族。"""

from __future__ import annotations

from itertools import (
    pairwise,
)

from texlate.latex.mouth import (
    Tok,
)

from .entries import (
    Arg,
    MacroDef,
)


class _DefCmd:
    # ------------------------------------------------------------ \def 族

    def _do_def(
        self,
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
        if nt is None or nt.kind not in ("cs", "active"):
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
        body = self._read_balanced(trace)
        if not trace or trace[-1].kind != "rbrace":
            return self._def_fail(trig, trace, "def body unterminated")
        spec = self._compile_param_text(ptext, has_brace=True)
        if spec is None:
            return self._def_fail(trig, trace, "param text illegal")
        if self._has_double_hash(ptext):
            # `##` 在**参数文本**（非体）出现 → 该 def 写深了一层，ptext+体同折
            # （Primitives.py:146-160 的判定域是 args；体里的 ## 归 expand_def 管）
            ptext = self._fold_hashes(ptext)
            body = self._fold_hashes(body)
            spec = self._compile_param_text(ptext, has_brace=True)
            if spec is None:
                return self._def_fail(trig, trace, "param text illegal")
        if eager:
            body = self._expand_eager(body)
        kind, target, protect = self._classify(body, self._param_count(spec))
        self.macros.set(
            mname,
            MacroDef(
                name=mname,
                spec=spec,
                body=body,
                kind=kind,
                target_env=target,
                protect_args=protect,
                scope="global" if global_ else "local",
                src=(
                    (head or trig).pos[0],
                    (head or trig).pos[1],
                    self._trace_end(trace),
                ),
            ),
            "global" if global_ else "local",
        )
        return self._consumed(f"{trig.text}:{mname}", trig, trace, head)

    def _expand_eager(self, body: list[Tok]) -> list[Tok]:
        r"""``\edef/\xdef`` 体即时展开：体 + 哨兵推回，抽展开流到哨兵止。

        哨兵 kind 非 cs、不在任何分派面 → 必然原样浮出；``\noexpand`` 打标
        的 token 带 ``xprotect`` 存进体（调用点再展开时见标跳一次）。
        """
        sentinel = Tok("_edef_end", "", (-1, -1, -1))
        self.unread([*body, sentinel])
        out: list[Tok] = []
        while True:
            t = self.next_expanded()
            if t is None or t is sentinel:
                return out
            out.append(t)

    @staticmethod
    def _trace_end(trace: list[Tok]) -> int:
        """Trace 末 token 的 end（def 登记 src 用）。"""
        return trace[-1].pos[2] if trace else -1

    def _def_fail(self, trig: Tok, trace: list[Tok], why: str) -> Tok:
        r"""定义解析失败（§3.5）：不登记 + 全部回吐 + ``\def`` 本体交出。"""
        self._warn("def_parse_fail", trig, why)
        self.unread(trace)
        return trig

    def _do_prefix(self, trig: Tok, name: str) -> Tok | None:
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
        return out

    @staticmethod
    def _param_count(spec: list[Arg]) -> int:
        """参数位数（``literal_match``/``eq`` 不占位）。"""
        return sum(1 for a in spec if a.kind not in ("literal_match", "eq"))

    def _compile_param_text(  # noqa: C901, PLR0912 — 参数文本文法平铺即 §8.4 表
        self, ptext: list[Tok], *, has_brace: bool
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
