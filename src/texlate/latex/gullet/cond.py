r"""``latex/gullet`` 子模块——god-class 机械拆分（行为零变）：\if 族 + process_if。"""

from __future__ import annotations

from texlate.latex.mouth import (
    Tok,
)

from .entries import (
    IfCond,
)
from .names import (
    _BUILTINS,
    _DIGITS,
    _PRIMS,
    _REL_CHARS,
)
from .tokutil import (
    _surface,
    _tok_eq,
)


class _Cond:
    # ------------------------------------------------------------ \if 族

    def _do_if(self, t: Tok) -> Tok | None:
        r"""``\if`` 两档（§8.6/§7.1）。

        可求值 → ``process_if(which)`` 只推回选中支；不可求值 → 条件已按
        语法消费（→ gap literal）+ ``\ifX`` 本体作界标直交分段器，两分支
        照常进流（召回优先，编译端 TeX 自决）。
        """
        which = self._eval_if(t.text)
        if which is None:
            return t
        # 条件段端点在 process_if 前锚定（其后 _last_read 已被 \fi 顶掉）
        lr = self._last_read
        cond_end = (
            lr.pos[2]
            if lr is not None and lr.gen == 0 and lr.pos[0] == t.pos[0]
            else t.pos[2]
        )
        end = self.process_if(which, trig=t, tail_tag=f"fi:{t.text}")
        # 界标夹心：end = 选支首 token 起点（None = 跨 fid 退回条件段端点）
        return self._consumed(
            f"if:{t.text}", t, None, end=end if end is not None else cond_end
        )

    def _eval_if(self, name: str) -> bool | int | None:  # noqa: C901, PLR0911, PLR0912 — 可求值族平铺即 §8.6 表
        r"""``\if`` 条件求值：``None`` → 界标档。条件 token 无条件消费。"""
        if name == "iftrue":
            return True
        if name == "iffalse":
            return False
        if name == "ifmmode":
            # 恒 False——数学区由分段器 raw 拉取成 [[MATH]]，数学体内的
            # \ifmmode 不经本求值（测试已钉：test_latex_cond.py）
            return False
        if name == "ifhmode":
            return True  # plasTeX 常量（Primitives.py:253-257），tables.IF_CONST 同值
        if name == "ifvmode":
            return False  # 同上（Primitives.py:247-251）
        if name == "ifinner":
            return False
        if name in ("ifeof", "ifvoid", "ifhbox", "ifvbox"):
            self._read_number()  # 寄存器号吃掉（\ifeof0）
            return False
        if name in ("ifnum", "ifdim"):
            v1 = self._read_number()
            rel = self._read_relation()
            v2 = self._read_number()
            if v1 is None or v2 is None or rel is None:
                return None
            if rel == "<":
                return v1 < v2
            if rel == ">":
                return v1 > v2
            return v1 == v2
        if name == "ifodd":
            v = self._read_number()
            return (int(v) % 2 == 1) if v is not None else None
        if name == "ifcase":
            v = self._read_number()
            # process_if 的 int 槽要真 int——_read_number 为 ifdim 统一返回 float
            return int(v) if v is not None and v >= 0 else None
        if name in ("if", "ifcat"):
            t1 = self._read_if_tok()
            t2 = self._read_if_tok()
            if t1 is None or t2 is None or t1.kind == "cs" or t2.kind == "cs":
                return None
            if name == "if":
                return _tok_eq(t1, t2)
            return t1.text.isalpha() == t2.text.isalpha()  # ifcat：字母类粗粒度
        if name == "ifx":
            t1 = self._read_if_tok()
            t2 = self._read_if_tok()
            if t1 is None or t2 is None:
                return None
            if t1.kind == "cs" or t2.kind == "cs":
                if t1.kind == "cs" and t2.kind == "cs" and t1.text == t2.text:
                    return True
                return None  # 宏比较 → 界标（召回优先）
            return _tok_eq(t1, t2)
        if name == "ifdefined":
            t = self._read_if_tok()
            if t is None or t.kind != "cs":
                return None
            return (
                True
                if self.macros.lookup(t.text) is not None
                or t.text in _PRIMS
                or t.text in _BUILTINS
                else None
            )
        if name == "ifcsname":
            toks: list[Tok] = []
            while True:
                x = self.read()
                if x is None:
                    return None
                if x.kind == "cs" and x.text == "endcsname":
                    break
                toks.append(x)
            cname = _surface(toks).strip()
            return (
                True
                if self.macros.lookup(cname) is not None or cname in _BUILTINS
                else None
            )
        return None  # 未知 if* → 界标

    def _read_if_tok(self) -> Tok | None:
        r"""``\if/\ifx`` 的一个比较 token（跳过空白）。"""
        while True:
            t = self.read()
            if t is None or t.kind != "space":
                return t

    def _read_relation(self) -> str | None:
        """``<``/``>``/``=`` 关系符（非符 → 回吐）。"""
        t = self._read_if_tok()
        if t is not None and t.kind != "cs" and t.text in _REL_CHARS:
            return t.text
        if t is not None:
            self.unread([t])
        return None

    def _read_number(self) -> float | None:  # noqa: C901, PLR0911, PLR0912, PLR0915 — TeX <number> 各形态一分支
        r"""读 TeX 数（``readInteger`` TeX.py:1592-1643 砍半）。

        可选符号 + 数字串 / ``'77`` 八进制 / ``"ff`` 十六进制 / ``` `` `x`` 字符码 /
        ``\cs`` 寄存器（消费但不求值）/ ``{..}`` 组（同）。不可求值 → ``None``。
        """
        sign = 1.0
        while True:
            t = self.read()
            if t is None:
                return None
            if t.kind == "space":
                continue
            if t.kind != "cs" and t.text == "+":
                continue
            if t.kind != "cs" and t.text == "-":
                sign = -sign
                continue
            break
        if t.kind != "cs" and t.text and t.text in _DIGITS:
            digits = [t.text]
            while True:
                t2 = self.read()
                if t2 is None:
                    break
                if t2.kind != "cs" and t2.text in _DIGITS:
                    digits.append(t2.text)
                    continue
                self.unread([t2])
                break
            return sign * int("".join(digits))
        if t.kind != "cs" and t.text == "'":  # 八进制
            digits = []
            while True:
                t2 = self.read()
                if t2 is None:
                    break
                if t2.kind != "cs" and t2.text in "01234567":
                    digits.append(t2.text)
                    continue
                self.unread([t2])
                break
            return sign * int("".join(digits) or "0", 8)
        if t.kind != "cs" and t.text == '"':  # 十六进制
            digits = []
            while True:
                t2 = self.read()
                if t2 is None:
                    break
                if t2.kind != "cs" and t2.text.lower() in "0123456789abcdef":
                    digits.append(t2.text)
                    continue
                self.unread([t2])
                break
            return sign * int("".join(digits) or "0", 16)
        if t.kind != "cs" and t.text == "`":  # 字符码
            t2 = self.read()
            if t2 is None:
                return None
            return sign * ord(t2.text[0] if t2.text else "\x00")
        if t.kind == "lbrace":
            trace: list[Tok] = [t]
            self._read_balanced(trace)  # 组：消费不求值
            return None
        if t.kind == "cs":
            # 寄存器/内部量：消费下标数/`x/{group}，不求值
            t2 = self.read()
            if t2 is None:
                return None
            if t2.kind != "cs" and t2.text in _DIGITS:
                while True:
                    t3 = self.read()
                    if t3 is None:
                        break
                    if t3.kind != "cs" and t3.text in _DIGITS:
                        continue
                    self.unread([t3])
                    break
                return None
            if t2.kind != "cs" and t2.text == "`":
                self.read()
                return None
            if t2.kind == "lbrace":
                trace = [t2]
                self._read_balanced(trace)
                return None
            self.unread([t2])
            return None
        self.unread([t])
        return None

    def process_if(  # noqa: C901, PLR0912, PLR0915 — 案例收集循环分支平铺即 TeX.py:531-585
        self,
        which: bool | int,  # noqa: FBT001 — \ifcase 值与 True/False 同槽（plasTeX which 同形）
        *,
        trig: Tok,
        tail_tag: str = "",
    ) -> int | None:
        r"""``processIfContent`` 移植（TeX.py:531-585）+ 界标夹心。

        原始流收集 case 到 ``\fi``（``\else/\or`` 分案例；只计**真条件**
        嵌套——``\newif`` 注册的 ``IfCond``、``\let`` 到 if 原语的别名、
        未重定义的原语 if；宏表里的 ``if*`` MacroDef/IfSetter 与未注册
        名不计，``\newif\ifX`` 整对保留）；收尾 ``\fi`` 不推回，
        ``unread`` = 选中支 + 尾部 ``fi:`` marker。

        返回 ``lead_end`` = 选支首 token 文件起点（空选支 = ``\fi``/末读
        token 末）：调用方 ``if:`` marker 盖 ``[trig.start, lead_end)``
        = 条件 + 前置死支 + 分案符；尾 marker 盖 ``[选支末, fi_end)`` =
        后置死支 + ``\fi``——死支字节全成 LITERAL，与 v1 ``_process_if``
        逐 piece 等价（此前死支折 gap 进 chunk gspan，译文面被整段替换
        丢失）。边界 token 跨 fid → ``None``，调用方退回旧端点。
        """
        cases: list[list[Tok]] = [[]]
        else_idx: int | None = None  # \else 支索引（\ifcase 超界回落地）
        nesting = 0
        terminated = False
        fi_tok: Tok | None = None  # depth-0 收尾 \fi（界标夹心右端）
        while True:
            t = self.read()
            if t is None:
                break
            name = t.text if t.kind == "cs" else ""
            if name == "newif":
                cases[-1].append(t)
                nxt = self.read()
                if nxt is not None:
                    cases[-1].append(nxt)
                continue
            if name.startswith("if"):
                r = self.macros.resolve(self.macros.lookup(name))
                # 只有真 TeX 条件计嵌套：\newif 注册的 IfCond、\let 到 if
                # 原语的别名、未被重定义的原语 if。MacroDef/IfSetter/Tok/
                # 未注册名不计——\newif\ififx 的 \ifxtrue（IfSetter）名带
                # if 前缀，etoolbox \ifdef 族包宏形似——二者计入都会把外层
                # \fi 配错 → if_unterminated 吞文尾（audit F5/probe F）。
                if (
                    isinstance(r, IfCond)
                    or (isinstance(r, str) and r.startswith("if"))
                    or (r is None and name in _PRIMS)
                ):
                    cases[-1].append(t)
                    nesting += 1
                    continue
                cases[-1].append(t)
                continue
            if name == "fi":
                if not nesting:
                    terminated = True
                    fi_tok = t
                    break
                cases[-1].append(t)
                nesting -= 1
                continue
            if not nesting and name in ("else", "or"):
                if name == "else":
                    else_idx = len(cases)
                cases.append([])
                continue
            cases[-1].append(t)
        if not terminated:
            self._warn("if_unterminated", None, "if")
        cases.append([])  # 无 else 支的默认（TeX.py:582）
        idx = (
            which
            if isinstance(which, int) and not isinstance(which, bool)
            else (0 if which else 1)
        )
        if idx >= len(cases):
            # \ifcase 超界 → \else 支；无 \else → 追加的空支
            # （plasTeX 此处 IndexError 裸奔；TeX 语义 = else 支）
            idx = else_idx if else_idx is not None else len(cases) - 1
        sel = cases[idx]
        # 界标端点：边界 token（选支首尾、\fi/末读）须同 fid——跨文件
        # \if 退回 None（旧行为：marker 只盖条件段，死支折 gap）
        fid = trig.pos[0]
        edge = fi_tok if fi_tok is not None else self._last_read
        bounds_ok = (
            edge is not None
            and edge.pos[0] == fid
            and (not sel or (sel[0].pos[0] == fid and sel[-1].pos[0] == fid))
        )
        tail: Tok | None = None
        lead_end: int | None = None
        if bounds_ok and edge is not None:
            if sel:
                lead_end = sel[0].pos[1]
                if edge.pos[2] > sel[-1].pos[2]:
                    tail = Tok(
                        "consumed",
                        tail_tag or "fi:",
                        (fid, sel[-1].pos[2], edge.pos[2]),
                        trig.gen,
                        trig.origin,
                    )
            else:
                lead_end = edge.pos[2]  # 空选支：单 marker 盖到 \fi 末
        self.unread([*sel, *([tail] if tail is not None else [])])
        return lead_end
