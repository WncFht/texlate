r"""mouth token 层 fuzz——pos 三元组 / tokbuf 回放 / catcode 切换 / EOF 契约钉。

与 ``test_latex_expansion.py``（三态/cs/注释逐例单测）的分工：本文件钉
**性质级**不变量——逐例钉不到的跨位置关系。

不变量清单（``Mouth``/``CatTable``/``Tok``）：

- pos 良构：纯源流每枚 token ``pos=(fid,s,e)`` 满足 ``0<=s<e<=len(src)``、
  产出序单调非重叠（``s >= prev_end``）、``src[s:e] == str(t)`` 指回源字节。
  两个归一例外：space 的 text 恒 ``" "``（切片为空白字符或 ``\<EOL>`` 段）；
  cs/space 的转义读会吞下 IGNORED 字符进 token 区间（切片含 ``\x00``）。
- kind 域：只产 ``_ALL_KINDS``（``consumed`` 是 gullet 事件不进 mouth）；
  ``gen==0``/``origin is None``/``xprotect==False``；相邻 eol_par 不出现
  （``_prev_kind`` 去重）。
- 回放等价：``push_tokens`` 推回 → 缓冲先出先出完、跨 push 后推先出、
  推内保序、源流不受污染；``from_tokens`` 逐字回复读；读出前 k 枚推回
  续读 ≡ 原流（缓冲 pop 不更新 ``state``/``_prev_kind`` 是成立根因）。
- catcode 中stream 改写：已产 token 不受 ``cats.set`` 影响（快照等值）；
  改写后读到的单字符 token 按新 code 归类（直产 kind 族）。
- ``CatTable`` 组作用域：快照 oracle——``push`` 记帧、``set`` 即写即生效、
  ``pop`` 复原帧前观测值、底帧写永存、空 ``pop`` 幂等。
- EOF：枯竭 ``next() → None`` 幂等且 ``i==len(src)``；枯竭后 ``push_tokens``
  仍被服务（EOF 不粘）；``iter(m) is m``；``next(m)`` 耗尽 ``StopIteration``。
- ``resync``：``i`` 只前进；``state=M`` + ``_prev_kind`` 清空（``\n\n``
  仍产 ``eol_par`` 且先产 space）；``tokbuf`` 整体置换为 ``keep``；
  keep 逐字先出，后续源 token ``pos.start >= resync 后 i``。
- 铁规：任意 ``str`` 入参 ``list(Mouth(s))`` 不抛契约外异常。

观察钉（pin observed——当前行为留档，定性留裁决）：

- sequence 入参不炸——无类型闸：bytes 逐字节产 ``("other", <int>)``、
  list 元素原样当字符分类、空 dict 直接枯竭；标量是 ``TypeError``。
- ``a\n\n%x\n\nb`` → 单 ``eol_par``：注释不改 ``_prev_kind``，第二段空行
  被「相邻去重」吃掉（plasTeX 移植语义，非显然）。
- ``\``+EOF → 空名 cs；``^^X`` 不实现（``^``^``A`` 三枚独立 token）。
- 相邻 space 合法：``\<EOL>`` 产 space 不经 M 态空白闸（``a\<EOL> b``
  可产相连 space）。
- ``\global`` 前缀的 catcode 写仍落本帧 undo（保守方向，docstring 留档）。

台账：``tmp/mouth-fuzz/findings.txt``（本文件 ``test_write_findings_ledger``
写出，2026-09-18 全绿）。
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _fuzzkit import (
    assert_deterministic,
    fuzz_rng,
    short,
    soup_join,
    soup_pick,
    write_findings,
)

from texlate.latex.mouth import (
    CC_ACTIVE,
    CC_ALIGNMENT,
    CC_BGROUP,
    CC_EGROUP,
    CC_LETTER,
    CC_MATHSHIFT,
    CC_OTHER,
    CC_PARAMETER,
    CC_SUB,
    CC_SUPER,
    CatTable,
    Mouth,
    Tok,
)

if TYPE_CHECKING:
    import random

# ---------------------------------------------------------------- 常量与 soup

_FUZZ_ITERS = 500
_FUZZ_ITERS_MED = 250
_SEED_SOUP = 2026091801
_SEED_PUSH = 2026091802
_SEED_CATCODE = 2026091803
_SEED_CATTAB = 2026091804
_SEED_RESYNC = 2026091805

#: 敌意字符汤——mouth 是 char→token 机，汤料按触发面选：各 catcode 代表
#: 字符、三态驱动符（空白/EOL/注释）、escape 各形态、CJK/控制字符、
#: ``^^X`` 序列、``\<EOL>``/``\ ``/``\%`` 控制符号、段尾孤立 ``\``/``%``。
_MOUTH_SOUP = [
    "a",
    "Z",
    "q",
    "0",
    "9",
    " ",
    "  ",
    "\t",
    "\r",
    "\x0c",
    "\n",
    "\n\n",
    "\n\n\n",
    "%",
    "%cmt\n",
    "%cmt",
    "{",
    "}",
    "$",
    "$$",
    "&",
    "#",
    "#1",
    "^",
    "_",
    "~",
    "@",
    "\\",
    "\\a",
    "\\foo",
    "\\foo ",
    "\\ ",
    "\\%",
    "\\\\",
    "\\{",
    "\\}",
    "\\$",
    "\\\n",
    "\\@x",
    "\\catcode",
    "中",
    "文",
    "é",
    "ß",
    "\x00",
    "\x01",
    "\x7f",
    "^^A",
    "'",
    "`",
    "-",
    "--",
    "[",
    "]",
    "(",
    ")",
    "|",
    "/",
    "*",
    "+",
    "=",
    "<",
    ">",
    ":",
    ";",
    "!",
    "?",
    ".",
    ",",
]

#: CatTable fuzz 探测字符——默认表内外、各 catcode 族、非 ASCII。
_CATS_CHARS = [
    "a",
    "q",
    "@",
    "%",
    " ",
    "\t",
    "\n",
    "{",
    "}",
    "\\",
    "$",
    "#",
    "^",
    "_",
    "~",
    "&",
    "0",
    "=",
    "中",
    "é",
    "ß",
]

#: 直产 kind 的 catcode 目标集——SPACE/EOL/COMMENT/ESCAPE/IGNORED/INVALID
#: 走专门路径不进此表（改写为这些会破切片断言的字符域前提）。
_TARGET_CODES = [
    CC_BGROUP,
    CC_EGROUP,
    CC_MATHSHIFT,
    CC_PARAMETER,
    CC_LETTER,
    CC_OTHER,
    CC_ACTIVE,
    CC_SUPER,
    CC_SUB,
    CC_ALIGNMENT,
]

_EXPECTED_KIND = {
    CC_BGROUP: "lbrace",
    CC_EGROUP: "rbrace",
    CC_MATHSHIFT: "mathshift",
    CC_PARAMETER: "param",
    CC_LETTER: "letter",
    CC_ACTIVE: "active",
    CC_OTHER: "other",
    CC_SUPER: "other",
    CC_SUB: "other",
    CC_ALIGNMENT: "other",
}

#: catcode 改写探测字符——含默认表内各族 + 空白 + ``\`` 本身 + 非 ASCII。
_PROBE_CHARS = [
    "q",
    "@",
    "Z",
    "1",
    "=",
    "~",
    "-",
    "{",
    "}",
    "$",
    "#",
    "^",
    "_",
    "&",
    "中",
    "é",
    "%",
    " ",
    "\t",
    "\n",
    "\\",
    ".",
]

#: 直产 kind 集合——这些 kind 的单字符 token ``text`` 即源字符本体。
_STRAIGHT_KINDS = frozenset(
    {"lbrace", "rbrace", "mathshift", "param", "letter", "other", "active"}
)

#: mouth 全部可产 kind（``consumed`` 是 gullet 事件——绝不出现在此）。
_ALL_KINDS = _STRAIGHT_KINDS | {"cs", "space", "eol_par"}

#: 推回合成 token 的 kind/text 池——任意 token 都应逐字穿透。
_SYNTH_KINDS = ["cs", "letter", "other", "space", "eol_par", "consumed", "active"]


# ---------------------------------------------------------------- 小件


def _sig(t: Tok) -> tuple:
    """token 投影——逐字段比较面（kind/text/pos/gen/origin/xprotect）。"""
    return (t.kind, t.text, t.pos, t.gen, t.origin, t.xprotect)


def _check_stream(src: str, toks: list[Tok], fid: int) -> None:
    r"""纯源流良构断言：pos 三元组合法 + 单调非重叠 + 指回源字节。

    ``src[s:e] == str(t)`` 是核心——pos 真指 token 的源字节区间。归一例
    外两族：space 的 text 恒 ``" "``（切片为空白或 ``\<EOL>`` 段）；cs 的
    转义读把 ``\\`` 与名之间的 IGNORED 字符（默认表唯 ``\\x00``）吞进 token
    区间——切片 = ``\\`` + 被吞字符 + 名。
    """
    prev_end = 0
    prev_kind = ""
    for t in toks:
        f, s, e = t.pos
        assert f == fid, (short(src), t.pos)
        assert 0 <= s < e <= len(src), (short(src), t.pos)
        assert s >= prev_end, (short(src), t.pos, prev_end)
        prev_end = e
        assert t.kind in _ALL_KINDS, (short(src), t.kind)
        assert t.gen == 0
        assert t.origin is None
        assert not t.xprotect
        if t.kind == "space":
            assert t.text == " "
            # 切片 = 空白字符 | '\' + 被吞 ignored* + EOL 字符（\<EOL> 路径）
            assert src[s:e].strip("\\\t\r\f\n\x00 ") == "", (short(src), t.pos)
        elif t.kind == "cs":
            # 转义读会吞掉 '\'-名 之间的 IGNORED 字符（默认表唯 \x00）——
            # pos 盖整个被消费区间：切片 = '\' + 被吞字符 + 名/单字符
            assert src[s:e].startswith("\\"), (short(src), t.pos)
            assert src[s:e][1:].lstrip("\x00") == t.text, (short(src), t.pos)
        else:
            assert src[s:e] == str(t), (short(src), t.pos, src[s:e])
        assert not (t.kind == prev_kind == "eol_par"), (short(src), t.pos)
        prev_kind = t.kind


def _synth_tok(rng: random.Random) -> Tok:
    """合成推回 token——kind/text/pos 任意（回放语义不校验字段）。"""
    return Tok(
        soup_pick(rng, _SYNTH_KINDS),
        soup_pick(rng, _MOUTH_SOUP),
        (soup_pick(rng, (-2, -1, 9)), rng.randrange(3), rng.randrange(3, 9)),
    )


# ---------------------------------------------------------------- 源流良构 + 铁规


def test_fuzz_stream_wellformed() -> None:
    """soup 源流：pos 指回源切片 + 单调非重叠 + kind 域 + eol_par 不相邻。

    ``list(Mouth(src))`` 不抛即过铁规；枯竭后 ``i==len(src)``、``next()``
    幂等 ``None``。
    """
    rng = fuzz_rng(_SEED_SOUP)
    for _ in range(_FUZZ_ITERS):
        src = soup_join(rng, _MOUTH_SOUP, 0, 40)
        fid = soup_pick(rng, (-1, 0, 3))
        m = Mouth(src, file_id=fid)
        toks = list(m)
        _check_stream(src, toks, fid)
        assert m.i == len(src)
        assert m.next() is None
        assert m.next() is None  # 枯竭幂等


def test_fuzz_deterministic() -> None:
    """同输入连跑两回 tokenize——逐字段投影恒等。"""
    rng = fuzz_rng(_SEED_SOUP + 1)
    for _ in range(_FUZZ_ITERS_MED):
        src = soup_join(rng, _MOUTH_SOUP, 0, 24)
        assert_deterministic(
            lambda: list(Mouth(src)),  # noqa: B023 -- 闭包当轮消费无延迟绑定
            key=lambda ts: [_sig(t) for t in ts],
        )


# ---------------------------------------------------------------- tokbuf 回放等价


def test_fuzz_pushback_oracle() -> None:
    """回放等价主 oracle：影子队列复刻「缓冲先出、跨 push 后推先出、推内保序」。

    每步随机读/推：推回时 ``pending`` 前插整块（后推先出）；读时 pending 非
    空则必须逐字弹出同对象（缓冲 pop 不吃源流），空则对 baseline 源流逐字段
    等。收尾排空后 baseline 游标与 pending 必须同时见底。
    """
    rng = fuzz_rng(_SEED_PUSH)
    fid = 5
    for _ in range(_FUZZ_ITERS_MED):
        src = soup_join(rng, _MOUTH_SOUP, 0, 24)
        baseline = list(Mouth(src, file_id=fid))
        m = Mouth(src, file_id=fid)
        pending: list[Tok] = []  # tokbuf 影子队列（队首 = 下次产出）
        bi = 0
        for _ in range(rng.randint(1, 14)):
            if rng.random() < 0.45:  # noqa: PLR2004 -- 推/读概率档即 soup 权重
                pushed = [_synth_tok(rng) for _ in range(rng.randint(0, 4))]
                m.push_tokens(pushed)
                pending[:0] = pushed
                continue
            t = m.next()
            if pending:
                assert t is pending.pop(0)
            elif bi < len(baseline):
                assert t is not None
                assert _sig(t) == _sig(baseline[bi]), short(src)
                bi += 1
            else:
                assert t is None
        while True:
            t = m.next()
            if t is None:
                break
            if pending:
                assert t is pending.pop(0)
            else:
                assert bi < len(baseline)
                assert _sig(t) == _sig(baseline[bi]), short(src)
                bi += 1
        assert bi == len(baseline)
        assert not pending


def test_fuzz_prefix_pushback_replays() -> None:
    """读出前 k 枚原样推回 → 续读全流 ≡ 原流（缓冲 pop 不碰 state/_prev_kind）。"""
    rng = fuzz_rng(_SEED_PUSH + 1)
    fid = 2
    for _ in range(_FUZZ_ITERS_MED):
        src = soup_join(rng, _MOUTH_SOUP, 0, 30)
        baseline = list(Mouth(src, file_id=fid))
        if not baseline:
            continue
        k = rng.randrange(len(baseline) + 1)
        m = Mouth(src, file_id=fid)
        head = []
        for _ in range(k):
            t = m.next()
            assert t is not None
            head.append(t)
        m.push_tokens(head)
        assert [_sig(t) for t in m] == [_sig(t) for t in baseline], short(src)


def test_fuzz_from_tokens_roundtrip() -> None:
    """回放等价（``from_tokens`` 臂）：产出流原样喂回 → 逐字段一致。"""
    rng = fuzz_rng(_SEED_PUSH + 2)
    for _ in range(_FUZZ_ITERS_MED):
        src = soup_join(rng, _MOUTH_SOUP, 0, 30)
        toks = list(Mouth(src, file_id=6))
        back = list(Mouth.from_tokens(toks))
        assert [_sig(t) for t in back] == [_sig(t) for t in toks]


# ---------------------------------------------------------------- catcode 中 stream 改写


def test_fuzz_catcode_mutation_midstream() -> None:
    """``cats.set`` 中 stream 生效：已产 token 快照不动；新读按新 code 归类。

    头 k 枚与 baseline（默认表全程）逐字段等——改写不回溯；k 之后每枚
    ``text == ch`` 的直产 kind token 必须等于 ``_EXPECTED_KIND[code]``
    （``cs``/``space``/``eol_par`` 排除——``\\<ch>`` 控制符号与空白归一
    不受 ch 自身 catcode 约束）。pos 良构贯穿改写点不断。
    """
    rng = fuzz_rng(_SEED_CATCODE)
    fid = 3
    for _ in range(_FUZZ_ITERS_MED):
        src = soup_join(rng, _MOUTH_SOUP, 1, 30)
        baseline = list(Mouth(src, file_id=fid))
        cats = CatTable()
        m = Mouth(src, file_id=fid, cats=cats)
        k = rng.randrange(len(baseline) + 1)
        head = []
        for _ in range(k):
            t = m.next()
            assert t is not None
            head.append(t)
        assert [_sig(t) for t in head] == [_sig(t) for t in baseline[:k]], short(src)
        ch = soup_pick(rng, _PROBE_CHARS)
        code = soup_pick(rng, _TARGET_CODES)
        cats.set(ch, code)
        tail = list(m)
        _check_stream(src, head + tail, fid)
        for t in tail:
            if t.kind in _STRAIGHT_KINDS and t.text == ch:
                assert t.kind == _EXPECTED_KIND[code], (
                    short(src),
                    ch,
                    code,
                    t.kind,
                )


# ---------------------------------------------------------------- CatTable 组作用域


def test_fuzz_cattable_undo_oracle() -> None:
    """快照 oracle：``push`` 记全帧观测、``set`` 即写即生效、``pop`` 复原。

    与 undo-log 实现非同构（快照 vs 首写增量）——钉的是「组局部化」语义本
    身：帧内任意改写序列在 ``pop`` 后回到帧前观测；底帧写（无帧时）永存；
    空 ``pop`` 幂等。收尾逐帧排空后表态与 oracle 全等。
    """
    rng = fuzz_rng(_SEED_CATTAB)
    for _ in range(_FUZZ_ITERS_MED):
        cats = CatTable()
        probe = rng.sample(_CATS_CHARS, rng.randint(2, 6))
        oracle = {ch: cats.code(ch) for ch in probe}
        saved: list[dict[str, int]] = []
        for _ in range(rng.randint(1, 40)):
            r = rng.random()
            if r < 0.4:  # noqa: PLR2004 -- set/push/pop 概率档
                ch = soup_pick(rng, probe)
                code = rng.randrange(16)
                cats.set(ch, code)
                oracle[ch] = code
            elif r < 0.7:  # noqa: PLR2004 -- 同上
                cats.push()
                saved.append(dict(oracle))
            else:
                cats.pop()
                if saved:
                    oracle = saved.pop()
            for ch in probe:
                assert cats.code(ch) == oracle[ch], (ch, cats.code(ch), oracle[ch])
        while saved:
            cats.pop()
            oracle = saved.pop()
            for ch in probe:
                assert cats.code(ch) == oracle[ch], (ch, cats.code(ch), oracle[ch])


class TestCatTablePins:
    """CatTable 逐点钉——快照 oracle 之外的定点语义。"""

    def test_first_write_wins(self) -> None:
        """帧内重复写只记首写旧值：``set;set;pop`` → 回到帧前，非中间值。"""
        cats = CatTable()
        assert cats.code("a") == CC_LETTER
        cats.push()
        cats.set("a", CC_OTHER)
        cats.set("a", CC_PARAMETER)
        cats.pop()
        assert cats.code("a") == CC_LETTER

    def test_bottom_write_persists(self) -> None:
        """底帧不记 undo——顶层写穿组弹永存。"""
        cats = CatTable()
        cats.set("a", CC_OTHER)
        cats.push()
        cats.pop()
        assert cats.code("a") == CC_OTHER

    def test_pop_empty_noop(self) -> None:
        """空栈 ``pop`` 幂等不抛。"""
        cats = CatTable()
        cats.pop()
        cats.pop()
        assert cats.code("a") == CC_LETTER

    def test_unregistered_char_default_other(self) -> None:
        """未登记字符恒 ``CC_OTHER``（plasTeX whichCode 同义）。"""
        cats = CatTable()
        for ch in ("中", "ß", "€", "①"):
            assert cats.code(ch) == CC_OTHER


# ---------------------------------------------------------------- resync 契约


def test_fuzz_resync_contract() -> None:
    """``resync(pos, keep)``：``i`` 只前进 + keep 逐字先出 + 后续 pos 不回溯。"""
    rng = fuzz_rng(_SEED_RESYNC)
    fid = 4
    for _ in range(_FUZZ_ITERS_MED):
        src = soup_join(rng, _MOUTH_SOUP, 0, 24)
        m = Mouth(src, file_id=fid)
        for _ in range(rng.randint(0, 6)):
            if m.next() is None:
                break
        i_before = m.i
        pos = rng.randrange(len(src) + 1) if src else 0
        keep = [Tok("letter", "K", (-9, 0, 1)) for _ in range(rng.randint(0, 3))]
        m.resync(pos, keep)
        assert m.i == max(i_before, pos)
        i_resync = m.i
        for k_tok in keep:
            assert m.next() is k_tok
        while (t := m.next()) is not None:
            assert t.pos[0] == fid
            assert t.pos[1] >= i_resync, (short(src), t.pos, i_resync)


class TestResyncPins:
    """``resync`` 状态面定点钉（gullet ``skip_past`` 的唯一入口）。"""

    def test_resync_state_m_and_prev_cleared(self) -> None:
        r"""``state=M`` + ``_prev_kind`` 清空：``\n\n`` 仍产 ``[space, eol_par]``。

        无 resync 续读同位置两 ``\n`` 全被去重吃掉只剩 ``b``——本钉同时证
        明 M 态（首 ``\n`` 产 space 而非跳过）与 prev 清空（次 ``\n`` 产
        eol_par 而非去重）。
        """
        m = Mouth("a\n\n\n\nb")
        for _ in range(3):
            m.next()  # a, space, eol_par；i=3、prev=eol_par
        m.resync(3, [])
        assert [t.kind for t in m] == ["space", "eol_par", "letter"]

    def test_resync_forward_only(self) -> None:
        """``pos < i`` 不倒车——``i`` 原地不动，续读位不变。"""
        m = Mouth("abcdef")
        m.next()
        m.next()  # i=2
        m.resync(0, [])
        assert m.i == 2  # noqa: PLR2004 -- 定点断言的坐标即语义
        t = m.next()
        assert t is not None
        assert t.text == "c"  # 续读位不变——没倒车回 'a'

    def test_resync_replaces_tokbuf(self) -> None:
        """旧 tokbuf 被 ``keep`` 整体置换——先推的 token 被丢弃。"""
        m = Mouth("xy")
        m.push_tokens([Tok("letter", "P", (-1, 0, 1))])
        m.resync(0, [Tok("letter", "K", (-1, 0, 1))])
        t = m.next()
        assert t is not None
        assert t.text == "K"
        t = m.next()
        assert t is not None
        assert t.text == "x"  # P 被丢弃而非排在 keep 后


# ---------------------------------------------------------------- EOF / 入口边角


class TestEntryEdges:
    """入口边角钉——EOF 契约、类型闸、移植差异面。"""

    def test_empty_source_idempotent_none(self) -> None:
        """空源：``next() → None`` 幂等；``list`` 空。"""
        m = Mouth("")
        assert m.next() is None
        assert m.next() is None
        assert list(m) == []
        assert m.i == 0

    def test_iter_returns_self(self) -> None:
        """迭代协议：``iter(m) is m``。"""
        m = Mouth("x")
        assert iter(m) is m

    def test_stopiteration_protocol(self) -> None:
        """内置 ``next()`` 耗尽 → ``StopIteration``。"""
        m = Mouth("")
        with pytest.raises(StopIteration):
            next(m)

    def test_eof_not_sticky_push_revives(self) -> None:
        """OBSERVED：EOF 不粘——枯竭 ``None`` 后 ``push_tokens`` 仍被服务
        （``tokbuf`` 检查先于枯竭判定；展开层在文件尾推回依赖此）。"""
        m = Mouth("x")
        assert list(m)
        assert m.next() is None
        m.push_tokens([Tok("letter", "Z", (-1, 0, 1))])
        t = m.next()
        assert t is not None
        assert t.text == "Z"
        assert m.next() is None

    @pytest.mark.parametrize("bad", [None, 42, 3.5])
    def test_non_str_typeerror(self, bad: object) -> None:
        """无 ``len`` 的标量入参 → ``TypeError``（``len(buf)`` 炸点）。"""
        with pytest.raises(TypeError):
            list(Mouth(bad))  # type: ignore[arg-type]

    def test_sequence_input_quirk_observed(self) -> None:
        """OBSERVED：sequence 入参不炸——无类型闸，逐元素穿透。

        bytes 逐位取下标得 int → ``("other", <int>)``；list 元素原样当
        「字符」分类（``"xy"`` 未登记 → other、``"z"`` → letter）；空 dict
        ``len==0`` 直接枯竭。与标量的 ``TypeError`` 不对称——pin 现行行为。
        """
        ts = list(Mouth(b"ab"))  # type: ignore[arg-type]
        assert [(t.kind, t.text) for t in ts] == [("other", 97), ("other", 98)]
        ts = list(Mouth(["xy", "z"]))  # type: ignore[arg-type]
        assert [(t.kind, t.text) for t in ts] == [("other", "xy"), ("letter", "z")]
        assert list(Mouth({})) == []  # type: ignore[arg-type]

    def test_backslash_eof_empty_cs(self) -> None:
        r"""``\``+EOF → 空名 cs（``text=""``，pos 盖反斜杠）。"""
        ts = list(Mouth("a\\"))
        assert [(t.kind, t.text) for t in ts] == [("letter", "a"), ("cs", "")]
        assert ts[-1].pos == (0, 1, 2)

    def test_caret_caret_not_implemented(self) -> None:
        r"""OBSERVED：``^^X`` 序列不实现（语料≈0，docstring 留档）——
        ``^^A`` 是三枚独立 token（``^`` ``^`` ``A``）。"""
        ts = list(Mouth("^^A"))
        assert [(t.kind, t.text) for t in ts] == [
            ("other", "^"),
            ("other", "^"),
            ("letter", "A"),
        ]

    def test_comment_between_blank_runs_single_eol_par(self) -> None:
        r"""OBSERVED：``a\n\n%x\n\nb`` → 单 ``eol_par``。

        注释吞行不改 ``_prev_kind``——第二段 ``\n\n`` 被「相邻去重」整段吃
        掉（去重看的是上一枚**流产出** token，注释对它透明）。pin 现行行为。
        """
        ts = list(Mouth("a\n\n%x\n\nb"))
        assert [(t.kind, t.text) for t in ts] == [
            ("letter", "a"),
            ("space", " "),
            ("eol_par", "\n"),
            ("letter", "b"),
        ]

    def test_adjacent_space_legal_via_escape_eol(self) -> None:
        r"""OBSERVED：``\<EOL>`` 产 space 不经 M 态空白闸——相邻 space 合法。"""
        ts = list(Mouth("a \\\nb"))
        assert [(t.kind, t.text) for t in ts] == [
            ("letter", "a"),
            ("space", " "),
            ("space", " "),
            ("letter", "b"),
        ]


# ---------------------------------------------------------------- Tok 字段语义


class TestTokSemantics:
    """``Tok`` 本体钉——``src``/``__str__``/``from_tokens`` 回放。"""

    def test_str_cs_adds_backslash(self) -> None:
        """``\\foo`` → ``\\\\foo``；其余 kind → text 本体。"""
        assert str(Tok("cs", "foo", (0, 0, 4))) == "\\foo"
        assert str(Tok("letter", "a", (0, 0, 1))) == "a"
        assert str(Tok("eol_par", "\n", (0, 0, 1))) == "\n"

    def test_src_prefers_origin(self) -> None:
        """``src`` = ``origin or pos``——展开产物取最外层调用点。"""
        t = Tok("letter", "x", (0, 5, 6), gen=1, origin=(0, 1, 2))
        assert t.src == (0, 1, 2)
        assert Tok("letter", "x", (0, 5, 6)).src == (0, 5, 6)

    def test_from_tokens_replays_verbatim(self) -> None:
        """``from_tokens``：逐字回复读同对象序，耗尽 ``None``。"""
        toks = [Tok("cs", "a", (-1, 0, 1)), Tok("letter", "b", (-1, 1, 2))]
        m = Mouth.from_tokens(toks)
        out = list(m)
        assert out == toks
        for o, t in zip(out, toks, strict=True):
            assert o is t
        assert m.next() is None


# ---------------------------------------------------------------- findings 台账落盘


def test_write_findings_ledger() -> None:
    """台账写出——``tmp/mouth-fuzz/findings.txt``。"""
    write_findings(
        Path("tmp/mouth-fuzz/findings.txt"),
        title="mouth-fuzz — D2c token 层不变量台账",
        scope=(
            "Mouth 三态 tokenize 的 pos 三元组良构/单调/指回源切片、tokbuf "
            "回放等价（push_tokens/from_tokens/prefix-pushback）、catcode "
            "中stream 改写归类、CatTable 组作用域 undo、EOF/resync 契约、"
            "Tok src/str 字段语义"
        ),
        test_file="tests/fuzz/test_fuzz_mouth.py",
        status="0 CONFIRMED / 0 PLAUSIBLE / 观察钉一簇（全绿 2026-09-18）",
        observed=[
            (
                "sequence 入参不炸——无类型闸：bytes 逐字节产 (other, <int>)、"
                "list 元素原样当字符分类、空 dict len==0 直接枯竭；标量 "
                "TypeError（注解即文档，无运行时闸）"
            ),
            (
                "a\\n\\n%x\\n\\nb → 单 eol_par：注释不改 _prev_kind，第二段空行 "
                "被相邻去重整段吃掉（去重看上一枚流产出 token）"
            ),
            (
                "\\<EOL> 产 space token 不经 M 态空白闸——相邻 space 合法；"
                "其 pos 盖反斜杠+换行两字符、text 归一为 ' '"
            ),
            (
                "\\ + EOF → 空名 cs（text='' pos 盖反斜杠）；^^X 序列不实现——"
                "^^A 产 (^,^,A) 三枚独立 token（语料≈0，docstring 留档）"
            ),
            (
                "EOF 不粘：枯竭 None 后 push_tokens 仍被服务（tokbuf 检查先于 "
                "枯竭判定）——展开层文件尾推回依赖此"
            ),
            (
                "\\global 前缀的 catcode 写仍落本帧 undo 随组回滚（保守方向，"
                "write-through 未实现，set docstring 留档）"
            ),
        ],
        notes=[
            (
                "回放等价成立根因：缓冲 pop 在 prev/state 更新之前返回（plasTeX "
                "Tokenizer.py:319-331 同）——prefix-pushback 测试即钉此机制；"
                "若未来缓冲 pop 改为更新 _prev_kind，eol_par 去重基线会漂移。"
            ),
            (
                "catcode 断言只盖直产 kind 族：\\<ch> 控制符号与 space/eol_par "
                "的 text 归一不受 ch 自身 catcode 约束，排除在归类断言外。"
            ),
        ],
        scratch="tmp/mouth-fuzz/",
    )
