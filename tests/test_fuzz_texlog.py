"""texlog 文件栈性质 fuzz——随机括弧/token 序列重放的结构不变量。

独立 oracle（不计名的裸括弧记账，floor-0）钉三条不变量：

- 栈深 == 非豁免 ``(`` 数 − 有效 ``)`` 数——``None`` 占位语义下具名/匿名
  帧一票一格，深度只由括弧配对决定，与 token 是否文件名无关；
- ``popped`` 长度 == 有效 ``)`` 数（栈空时的 ``)`` 被丢弃不计）；
- ``file_stack_at(lines, i, popped)`` 与逐行 ``update_file_stack`` 重放
  同口径（增量 == 批量），返回值只含具名帧、保持栈序。

豁免位置用独立实现的 missing-char 判定（按 docstring 语义重写 regex——
不复用 ``_MISS_CHAR_RX``，oracle 必须独立于被测实现）。
"""

from __future__ import annotations

import random
import re

from texlate.texlog import file_stack_at, looks_like_input_file, update_file_stack

#: 独立 missing-char 字形豁免（与 _MISS_CHAR_RX 同语义的平行实现）。
_ORACLE_MISS_RX = re.compile(r"Missing character: There is no ([()])(?=[ (]|$)")

#: token 汤 alphabet——文件形/非文件形/裸括弧/折行碎片/missing-char 模板混排。
_TOKENS = [
    "(",
    ")",
    "(./main.tex",
    "(./sub/chap.tex",
    "(x.sty",
    "(/usr/share/texmf/tex/latex/base/article.cls",
    "(fig1.eps",
    "(a(b).tex",
    "(draft",
    "(v2.0",
    "(52.00102pt",
    "(Fig.11a",
    "(see)",
    "(user@host.tex",
    "(http://x.y/a.tex",
    "(a,b.tex",
    "(x.pygtex",
    "text ",
    " output written on x.pdf (1 page, 3k).",
    "\t",
    "{",
    "}",
    "[",
    "]",
    "Missing character: There is no ) in font nullfont!",
    "Missing character: There is no ( in font nullfont!",
    "Missing character: There is no ) (U+0029) in font cmr10!",
    "Missing character: There is no 字 (U+5B57) in font nullfont!",
    "Missing character: There is no )x in font nullfont!",
    "! File ended while scanning use of \\foo.",
    "Runaway argument? )",
]


def _oracle(lines: list[str]) -> tuple[int, int]:
    """裸括弧记账 oracle → ``(深度, 有效闭括弧数)``。

    豁免：missing-char 字形位（ lookahead ``[ (]|$`` ）不参与配对；
    无括弧行整体短路——与实现同一条文义规则、独立代码路径。
    """
    depth = pops = 0
    for ln in lines:
        if "(" not in ln and ")" not in ln:
            continue
        skip = (
            {m.start(1) for m in _ORACLE_MISS_RX.finditer(ln)}
            if "Missing character" in ln
            else set()
        )
        for j, c in enumerate(ln):
            if j in skip:
                continue
            if c == "(":
                depth += 1
            elif c == ")" and depth > 0:
                depth -= 1
                pops += 1
    return depth, pops


def _replay(lines: list[str]) -> tuple[list[str | None], list[str | None]]:
    """逐行重放 → ``(stack, popped)``。"""
    stack: list[str | None] = []
    popped: list[str | None] = []
    for ln in lines:
        update_file_stack(ln, stack, popped)
    return stack, popped


def _gen_lines(rng: random.Random) -> list[str]:
    """随机行集：1–8 行，每行 1–12 个 soup token。"""
    return [
        "".join(rng.choice(_TOKENS) for _ in range(rng.randint(1, 12)))
        for _ in range(rng.randint(1, 8))
    ]


def test_fuzz_stack_depth_eq_paren_balance() -> None:
    """铁律：``len(stack)`` 恒等于豁免后括弧配对余额——栈永不负、幻影帧零。"""
    rng = random.Random(20260917)  # noqa: S311 -- 确定性种子复现，非加密用途
    for _ in range(3000):
        lines = _gen_lines(rng)
        stack, _ = _replay(lines)
        depth, _ = _oracle(lines)
        assert len(stack) == depth, f"depth drift: {lines!r} -> {len(stack)} vs {depth}"


def test_fuzz_popped_eq_effective_closes() -> None:
    """``popped`` 恰收有效 ``)`` 弹出的栈顶——空栈 ``)`` 丢弃不入账。"""
    rng = random.Random(20260918)  # noqa: S311 -- 确定性种子
    for _ in range(3000):
        lines = _gen_lines(rng)
        _, popped = _replay(lines)
        _, pops = _oracle(lines)
        assert len(popped) == pops, f"popped drift: {lines!r}"
        # 弹出的具名帧必须是曾入栈的字面 token（形状由 looks_like_input_file 判）
        for p in popped:
            assert p is None or looks_like_input_file(p)


def test_fuzz_file_stack_at_eq_incremental() -> None:
    """``file_stack_at(lines, i, popped)`` == 前缀逐行重放——任意 stop 位。"""
    rng = random.Random(20260919)  # noqa: S311 -- 确定性种子
    for _ in range(800):
        lines = _gen_lines(rng)
        for stop in range(len(lines) + 1):
            stack, popped = _replay(lines[:stop])
            popped2: list[str | None] = []
            named = file_stack_at(lines, stop, popped2)
            assert named == [s for s in stack if s]
            assert popped2 == popped


def test_fuzz_missing_char_lines_are_neutral() -> None:
    """规范 missing-char 行对栈净零；``popped`` 只多收该行自带配对帧的弹出。

    码位形态 ``(U+XXXX)`` 行内含平衡括弧对——推 ``None`` 占位于自身
    即弹（栈零净效应），但 ``popped`` 历史如实多收这一条 ``None``。
    """
    rng = random.Random(20260920)  # noqa: S311 -- 确定性种子
    templates = [
        "Missing character: There is no ) in font nullfont!",
        "Missing character: There is no ( in font nullfont!",
        "Missing character: There is no ) (U+0029) in font cmr10!",
        "Missing character: There is no ( (U+0028) in font cmr10!",
        "Missing character: There is no 字 (U+5B57) in font nullfont!",
        'Missing character: There is no 字 ("5B57) in font nullfont!',
    ]
    for _ in range(1500):
        lines = _gen_lines(rng)
        pos = rng.randint(0, len(lines))
        extra = rng.choice(templates)
        lines2 = [*lines[:pos], extra, *lines[pos:]]
        stack1, popped1 = _replay(lines)
        stack2, popped2 = _replay(lines2)
        assert stack1 == stack2, f"missing-char line moved stack: {extra!r}"
        k = _oracle(lines[:pos])[1]  # 插入点之前已发生的弹次数
        n = _oracle([extra])[1]  # 该行自带配对弹次（弹出的全是自身 None 帧）
        assert popped2 == popped1[:k] + [None] * n + popped1[k:]


def test_fuzz_never_raises_on_dirty_input() -> None:
    """脏字符汤（控制字符/代理区/巨型行）不炸——log 是不可信输入面。"""
    rng = random.Random(20260921)  # noqa: S311 -- 确定性种子
    alpha = "(){}[]<>| \t\x00\x01\x7f\udce9\ud800字\\/@:.,-abcTEX.sty"
    for _ in range(1500):
        lines = [
            "".join(rng.choice(alpha) for _ in range(rng.randint(0, 300)))
            for _ in range(rng.randint(1, 5))
        ]
        stack, popped = _replay(lines)
        depth, pops = _oracle(lines)
        assert len(stack) == depth
        assert len(popped) == pops


def test_fuzz_named_frames_are_token_literals() -> None:
    """具名帧集合 ⊆ 行内 ``(`` 后 token——栈不发明文件名。"""
    rng = random.Random(20260922)  # noqa: S311 -- 确定性种子
    token_rx = re.compile(r"\(([^\s(){}]+)")
    for _ in range(2000):
        lines = _gen_lines(rng)
        stack, _ = _replay(lines)
        seen_tokens = {m.group(1) for ln in lines for m in token_rx.finditer(ln)}
        for s in stack:
            if s is not None:
                assert s in seen_tokens, f"phantom frame {s!r} from {lines!r}"


def test_stack_linear_on_huge_line() -> None:
    """单行 60k 括弧交替——线性扫描无爆栈/无超时（压塌为 0 深）。"""
    ln = "(x.tex)" * 20000
    stack, popped = _replay([ln])
    assert stack == []
    assert len(popped) == 20000  # noqa: PLR2004 -- 钉字面配对数


def test_file_stack_at_bounds() -> None:
    """stop 边界：0 → 空栈；超 len → 全量重放。"""
    lines = ["(./a.tex", "(./b.tex", ")x"]
    assert file_stack_at(lines, 0) == []
    assert file_stack_at(lines, 99) == ["./a.tex"]
    assert file_stack_at([], 0) == []
