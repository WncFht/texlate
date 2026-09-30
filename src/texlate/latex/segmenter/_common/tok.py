r"""``latex.segmenter._common.tok`` — token 源抽象（``_common`` god-file 机械拆分叶）。

``TokenSource`` 拉取契约 + 能力面 Protocol（展开源独有 live 栈/宏表/前瞻
展开，回放源恒定缺省作答）+ ``_ListSource`` in_arg 子扫 deque 源 +
``_pull_cursor`` 流侧拉参游标 ``(unpull, peek)`` 闭包对。
"""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.latex.gullet import ScopeMacroTable
    from texlate.latex.mouth import Mouth, Tok

# ------------------------------------------------------------------ token 源

# 可发起文本 run 的 token kind——gen==0 源 token 专属（展开产物 gen>0 走组路）。
_TEXT_RUN_HEADS = frozenset({"letter", "other", "param", "active"})


class TokenSource(Protocol):
    r"""分段器输入抽象——``Gullet``（顶层展开源）或 ``_ListSource``（in_arg 子扫）。

    拉取契约外还有一层**能力面**：展开源独有 live 栈/宏表/前瞻展开，
    固定回放源以 ``None``/``False``/``(False, None)`` 作答——消费侧按
    本表编程，不做 ``isinstance`` 类型特判。
    """

    # ---- 展开源能力面（_ListSource 恒定缺省） ----
    @property
    def macros(self) -> ScopeMacroTable | None:
        """宏表（ListSource=None——查名回落 state.macros）。"""
        ...

    pop_seq: int  # 栈弹事件钟（ListSource 恒 0）
    push_seq: int  # 栈压事件钟（ListSource 恒 0）
    unmatched_open: set[tuple[tuple[int, int, int], int]] | None
    """``_collect_group`` 无配对 memo；展开流无界不可 memo → Gullet 恒 ``None``。"""
    eof_pops: bool
    """``read()`` 耗尽是否已弹栈——``True`` 时 ``unread`` 会建 file_id<0 合成源。"""

    # ---- 拉取契约 ----

    def next_expanded(self) -> Tok | None:
        """拉下一枚展开后 token；耗尽 ``None``。"""
        ...

    def read(self) -> Tok | None:
        """原始（不展开）拉取——前瞻/收集用。"""
        ...

    def unread(self, toks: list[Tok]) -> None:
        """回吐前端。"""
        ...

    def skip_past(self, fid: int, end: int, /) -> bool:
        """``fid`` 源对齐到 ``end``——raw 消费段内 token 残骸剔除；成功 ``True``。"""
        ...

    # ---- scope 回报（§4：分段器驱动宏表/catcode 推弹；回放源无展开态 = no-op）----

    def scope_push(self) -> None:
        """组开回报。"""
        ...

    def scope_pop(self) -> None:
        """组闭回报。"""
        ...

    # ---- 展开源能力面（_ListSource 各臂缺省实现） ----

    def live_inputs(self) -> list[Mouth] | None:
        """Live 输入栈快照（弹栈尾盖/ph 懒采样用）；``None`` = 非展开源。"""
        ...

    def env_sig(self, target: str) -> frozenset:
        """Target env 端点宏签名（墓标作废键）；回放源签名恒空集。"""
        ...

    def input_expand(self, t: Tok, /) -> tuple[bool, Tok | None]:
        r"""前瞻臂 ``\input`` 族展开 → ``(handled, hit)``；无能力 → ``(False, None)``。"""
        ...

    def text_run_end(self, t: Tok, files: list[str]) -> int | None:
        """gen=0 文本头起的连续 run 末位快扫；不可批 → ``None``。"""
        ...


class _ListSource:
    """in_arg 子扫的 token 列表源（token 已展开，read==next_expanded）。

    ``deque`` 而非 list：大体 env/arg 子扫下 ``pop(0)`` 是 O(n)
    memmove——2410.17998 实测 2.4M 次出队吃掉 22s。
    """

    # ---- ``TokenSource`` 能力面缺省值：固定回放源无展开态 ----
    macros: ScopeMacroTable | None = None
    pop_seq = 0
    push_seq = 0
    eof_pops = False  # 耗尽即真 EOF——``unread`` 回插队首、无合成源问题

    def __init__(self, toks: list[Tok]) -> None:
        """持有待发 token 队列。"""
        self._q = deque(toks)
        # ``_collect_group`` 扫到队尾未配对的 open 位 (pos, gen)：token 列
        # 构造即定（unread 只回放已见 token、skip_past 只删），「无配对」
        # 判终身成立——同 open 的后续探针 O(1) fast-fail，不再 O(尾长) 重扫
        # （2410.17998 实测 145 次失败重扫 = 18.6M/19M token 拉取）。
        self.unmatched_open: set[tuple[tuple[int, int, int], int]] = set()

    def next_expanded(self) -> Tok | None:
        """队首出队。"""
        return self._q.popleft() if self._q else None

    def read(self) -> Tok | None:
        """同 next_expanded（子扫内不再有展开副作用）。"""
        return self.next_expanded()

    def unread(self, toks: list[Tok]) -> None:
        """回插队首（保序）。"""
        self._q.extendleft(reversed(toks))

    def skip_past(self, fid: int, end: int) -> bool:
        r"""丢弃 ``pos`` 完全落在 ``end`` 前的队首 token（raw 消费对齐）。

        ``\verb`` 定界体/verbatim env 体在文件字节上找闭合，其间的
        token 早已展开入队——不剔除会被二次分派（体内 ``\end`` 假命中）。
        对齐总能达成（失配 token 丢弃即齐），恒 ``True``。
        """
        while self._q and self._q[0].pos[0] == fid and self._q[0].pos[2] <= end:
            self._q.popleft()
        return True

    def scope_push(self) -> None:
        """no-op：子扫回放已展开 token，组界不进宏表/catcode。"""

    def scope_pop(self) -> None:
        """no-op：同上。"""

    def live_inputs(self) -> list[Mouth] | None:
        """``None``：回放源无 Mouth 栈（弹栈尾盖/ph 懒采样主扫专属）。"""
        return None

    def env_sig(self, target: str) -> frozenset:
        r"""空集：子扫 token 列固定、宏表在重放内不突变，墓标签名恒自洽。"""
        del target
        return frozenset()

    def input_expand(self, t: Tok) -> tuple[bool, Tok | None]:
        r"""无展开能力：恒 ``(False, None)``——``\input`` cs 按普通体 token 收。"""
        del t
        return False, None

    def text_run_end(self, t: Tok, files: list[str]) -> int | None:
        r"""Deque 队首 gen==0、``pos`` 严格相接的文本 token 出队合并 → run 末位。

        space 仅作夹心项——原字节须恒 ``" "``（``\t`` 等的 surface 渲染不同）
        且后继须为相接文本头（run 以 ws 收尾会破 ``_slice_items`` lead/trail
        strip——item 粒度剥不进内部）。无后继可并 → ``None``。
        """
        fid, _a, end = t.pos
        q = self._q
        kinds = _TEXT_RUN_HEADS | {"space"}
        i, n = 0, len(q)
        while i < n:
            nxt = q[i]
            if (
                nxt.gen != 0
                or nxt.kind not in kinds
                or nxt.pos[0] != fid
                or nxt.pos[1] != end
            ):
                break
            if nxt.kind == "space":
                n2 = q[i + 1] if i + 1 < n else None
                if (
                    files[fid][nxt.pos[1] : nxt.pos[2]] != " "
                    or n2 is None
                    or n2.gen != 0
                    or n2.kind not in _TEXT_RUN_HEADS
                    or n2.pos[0] != fid
                    or n2.pos[1] != nxt.pos[2]
                ):
                    break
            end = nxt.pos[2]
            i += 1
        for _ in range(i):
            q.popleft()
        return end if end > t.pos[2] else None


class _Unpull(Protocol):
    """``_pull_cursor`` ``unpull`` 闭包形——可选 ``x`` 附尾回吐（``Callable`` 表达不了缺省参）。"""

    def __call__(self, x: Tok | None = None) -> None: ...


def _pull_cursor(
    src: TokenSource, fid: int, pulled: list[Tok], committed: Callable[[], int]
) -> tuple[_Unpull, Callable[[], Tok | None]]:
    r"""流侧拉参游标 ``(unpull, peek)`` 闭包对——``_absorb_slots``/``_absorb_spec`` 共享。

    ``pulled`` = 已拉 token 全列，``committed()`` 取当前提交水位（调用方传
    ``lambda: committed`` 活引用——水位随消费推进须逐次取新值，快照即
    死数）。``unpull`` 把未提交尾段（可选 ``x`` 附尾）``unread`` 回放并
    截断；``peek`` 跳 space 入账，界 token（``eol_par``/``gen>0``/异 fid）
    与 EOF 回放不消费、返 ``None``。
    """

    def unpull(x: Tok | None = None) -> None:
        tail = pulled[committed() :]
        if x is not None:
            tail = [*tail, x]
        if tail:
            src.unread(tail)
        del pulled[committed() :]

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

    return unpull, peek
