"""texlog 文件栈性质 fuzz——随机括弧/token 序列重放的结构不变量。

独立 oracle（不计名的裸括弧记账，floor-0）钉三条不变量：

- 栈深 == 非豁免 ``(`` 数 − 有效 ``)`` 数——``None`` 占位语义下具名/匿名
  帧一票一格，深度只由括弧配对决定，与 token 是否文件名无关；
- ``popped`` 长度 == 有效 ``)`` 数（栈空时的 ``)`` 被丢弃不计）；
- ``file_stack_at(lines, i, popped)`` 与逐行 ``update_file_stack`` 重放
  同口径（增量 == 批量），返回值只含具名帧、保持栈序。

豁免位置用独立实现的 missing-char 判定（按 docstring 语义重写 regex——
不复用 ``_MISS_CHAR_RX``，oracle 必须独立于被测实现）。

缺陷台账（tmp/fuzz-texlog/ 实证，2026-09-17）：

- D1 ``is_project_file`` 裸名分支 ``(root/token).is_file()`` 漏
  OSError——单段 >255 字节 token ENAMETOOLONG 逃逸（绝对路径分支显式
  catch OSError/ValueError，裸名支不对称）；docstring「判不出归属保守
  归工程」契约破，l2.py:353/loginfo.py:102 逐帧调用一遇即整轮死。
  **已修**（裸名支 ``try (OSError, ValueError)`` → True），钉转回归断言。
- D2 ``is_dos_eps`` NUL token 漏 ValueError（"embedded null byte" 非
  OSError 子类）——NUL 具名帧真实可达：``(a\x00b.tex`` 行推 ``.tex``
  白名单帧；消费端 loginfo.py:97/l2.py:348 的 ``is_dos_eps`` 先于
  ``is_project_file`` 的 NUL 豁免执行，invalid_utf8 命中即炸整轮归因。
  **已修**（先 ``is_file`` 正规文件闸 + ``except (OSError, ValueError)``
  ——fifo 开口阻塞 P2 面同消），钉转回归断言。

观察钉（pin 当前契约，非缺陷——裁决留负责人）：

- ``file_stack_at`` 负 stop 按 ``lines[:stop]`` 切片丢尾部（stop 语义是
  行号索引）；非 int stop/非 str 行 ``TypeError`` 裸逃。
- ``is_project_file`` 空裸名 token → False（实际不可达——token ≥1 字符）。
- ``is_dos_eps`` 按 token 缓存判定、文件后改不回读（per-scan 语义）。
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _fuzzkit import fuzz_rng, short, soup_join, soup_pick

import texlate.texlog as texlog_mod
from texlate.texlog import (
    DOS_EPS_MAGIC,
    file_stack_at,
    is_dos_eps,
    is_project_file,
    looks_like_input_file,
    patch_graphic_top,
    update_file_stack,
)

if TYPE_CHECKING:
    import random

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
    rng = fuzz_rng(20260917)
    for _ in range(3000):
        lines = _gen_lines(rng)
        stack, _ = _replay(lines)
        depth, _ = _oracle(lines)
        assert len(stack) == depth, f"depth drift: {lines!r} -> {len(stack)} vs {depth}"


def test_fuzz_popped_eq_effective_closes() -> None:
    """``popped`` 恰收有效 ``)`` 弹出的栈顶——空栈 ``)`` 丢弃不入账。"""
    rng = fuzz_rng(20260918)
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
    rng = fuzz_rng(20260919)
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
    rng = fuzz_rng(20260920)
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
    rng = fuzz_rng(20260921)
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
    rng = fuzz_rng(20260922)
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


# ---------------------------------------------------------------- patch 回放臂
# 消费端正典是逐行 ``update``+``patch``（l2.py:473/loginfo.py:93）——上面的
# oracle 重放只吃 update；patch 不改栈深但会把栈顶 None 补成 graphic 名，
# 故本节独立钉 patch 回放面的不变量。

_GRAPHIC_EXTS = texlog_mod._PS_GRAPHIC_EXTS  # noqa: SLF001 -- patch 补名合法性判定
_ERR_RES = (
    texlog_mod.ERR_FILELINE_RE,
    texlog_mod.NONERR_FILELINE_RE,
    texlog_mod.ERR_BANG_RE,
    texlog_mod.L_NUM_RE,
)

#: 归因原语 token 汤——绝对/相对/裸名/texmf 标记/逃逸/dot 段/NUL/超长/非文件形。
_TOK_SOUP = [
    "main.tex",
    "sub/x.sty",
    "./a.tex",
    "../up.tex",
    "a/../../b.tex",
    "/abs/x.tex",
    "/usr/share/texmf-dist/y.sty",
    "/home/u/texmf/z.tex",
    "/cache/Tectonic/b/x.sty",
    "/w/tectonic/y.tex",
    "/_texmf/u.sty",
    "",
    ".",
    "..",
    "/",
    "//h/x.tex",
    "x.",
    ".tex",
    "a.TEX",
    "mailto:a@b.tex",
    "x://y",
    "a,b.tex",
    "锚.tex",
    "\x7f.tex",
    "a\x00b.tex",
    "/a\x00b/c.tex",
    "x" * 260 + ".tex",
    "nodot",
    "v2.0",
    "52.00102pt",
    "(",
    ")",
    " ",
    "fig\n.tex",
]

#: patch 面行汤——graphic token 全形态（逗号截断形落 None 帧才是补名对象）。
_PATCH_SOUP = [
    "(fig.eps",
    "(fig,1.eps",
    "(x.EPS",
    "(a.epsf",
    "(b.epsi",
    "(c.ps",
    "(d.mps",
    "(e.png",
    "(f.tex",
    "(",
    ")",
    "(draft",
    "Missing character: There is no ) in font nullfont!",
    "Missing character: There is no ( in font nullfont!",
    " text ",
    "(fig.eps)",
    "(x.eps tail",
    "a" * 300,
    "\x00",
]


def _replay_patched(lines: list[str]) -> tuple[list[str | None], list[str | None]]:
    """消费端正典逐行 ``update``+``patch`` 回放。"""
    stack: list[str | None] = []
    popped: list[str | None] = []
    for ln in lines:
        update_file_stack(ln, stack, popped)
        patch_graphic_top(ln, stack)
    return stack, popped


def _frame_legal(frame: str) -> bool:
    """具名帧合法性——``looks_like_input_file`` 或 graphic 后缀补名。"""
    return looks_like_input_file(frame) or Path(frame).suffix.lower() in _GRAPHIC_EXTS


def test_fuzz_patched_replay_invariant() -> None:
    """patch 回放臂：栈深/popped 数仍恒等于 oracle；具名帧恒合法。"""
    rng = fuzz_rng(2026091730)
    for _ in range(2000):
        lines = [
            "".join(
                rng.choice(_PATCH_SOUP + _TOKENS) for _ in range(rng.randint(1, 10))
            )
            for _ in range(rng.randint(1, 8))
        ]
        stack, popped = _replay_patched(lines)
        depth, pops = _oracle(lines)
        assert len(stack) == depth, short(lines)
        assert len(popped) == pops, short(lines)
        for frame in (*stack, *popped):
            assert frame is None or _frame_legal(frame), short((frame, lines))


def test_fuzz_patched_replay_deterministic() -> None:
    """patch 臂确定性：同输入重放 stack/popped 全等。"""
    rng = fuzz_rng(2026091731)
    for _ in range(500):
        lines = [
            "".join(rng.choice(_PATCH_SOUP) for _ in range(rng.randint(1, 8)))
            for _ in range(rng.randint(1, 6))
        ]
        first = _replay_patched(lines)
        assert _replay_patched(lines) == first


def test_fuzz_patch_graphic_top_direct() -> None:
    """patch 只许改栈顶 None→graphic 名——长度与其余帧不动。"""
    rng = fuzz_rng(2026091732)
    for _ in range(2000):
        ln = soup_join(rng, _PATCH_SOUP, 1, 8)
        stack: list[str | None] = [
            soup_pick(rng, [None, "./a.tex", "x.sty", "f.lbx"])
            for _ in range(rng.randint(0, 5))
        ]
        before = list(stack)
        patch_graphic_top(ln, stack)
        assert len(stack) == len(before), short((ln, before))
        assert stack[:-1] == before[:-1], short((ln, before))
        if stack and stack[-1] != before[-1]:
            assert before[-1] is None, short((ln, before))
            assert Path(str(stack[-1])).suffix.lower() in _GRAPHIC_EXTS, short(
                (ln, before)
            )


# ---------------------------------------------------------------- 入口边角


class TestFileStackAtEdges:
    """入口边角观察钉——pin 当前契约（非缺陷，定性留裁决）。"""

    def test_negative_stop_is_slice(self) -> None:
        """观察钉：负 stop 按 ``lines[:stop]`` 切片——尾部行被静默丢。

        stop 的调用方契约是行号索引（logparse 传 ``first_i``≥0）；负值
        不 clamp/raise，按 Python 切片语义漏掉尾部。PLAUSIBLE——见台账。
        """
        lines = ["(./a.tex", "(./b.tex", ")x"]
        assert file_stack_at(lines, -1) == ["./a.tex", "./b.tex"]

    def test_none_stop_is_full_replay(self) -> None:
        """观察钉：``stop=None`` 按 ``lines[:None]`` 全量重放——不校验类型。"""
        lines = ["(./a.tex", "(./b.tex", ")x"]
        assert file_stack_at(lines, None) == ["./a.tex"]  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [1.5, "1"])
    def test_non_int_stop_typeerror(self, bad: object) -> None:
        with pytest.raises(TypeError):
            file_stack_at(["(./a.tex"], bad)  # type: ignore[arg-type]

    @pytest.mark.parametrize("bad", [b"(./a.tex", None, 5])
    def test_non_str_line_typeerror(self, bad: object) -> None:
        with pytest.raises(TypeError):
            file_stack_at([bad], 1)  # type: ignore[list-item]


# ---------------------------------------------------------------- 错误行原语


def test_fuzz_err_res_never_raise() -> None:
    """四条错误行 regex 对 soup 行恒返回 Match|None——不抛。"""
    rng = fuzz_rng(2026091733)
    for _ in range(2000):
        ln = soup_join(rng, _TOKENS + _TOK_SOUP, 1, 10)
        for rx in _ERR_RES:
            m = rx.match(ln)
            assert m is None or isinstance(m, re.Match), short(ln)


def test_err_res_semantics() -> None:
    """语义钉：file:line: 口径（ext 必带/数字行号）与 Warning/==> 排除。"""
    assert texlog_mod.ERR_FILELINE_RE.match("./main.tex:12: x")
    assert not texlog_mod.ERR_FILELINE_RE.match("Makefile:5: x")
    assert not texlog_mod.ERR_FILELINE_RE.match("./x.tex:abc: x")
    assert texlog_mod.NONERR_FILELINE_RE.match("./x.tex:9: Package f Warning: b")
    assert texlog_mod.NONERR_FILELINE_RE.match("./x.tex:9: ==> Fatal error")
    assert not texlog_mod.NONERR_FILELINE_RE.match("./x.tex:9: Undefined")
    m = texlog_mod.L_NUM_RE.match("l.42 \\foo")
    assert m is not None
    assert m.group(1) == "42"
    assert not texlog_mod.L_NUM_RE.match("l.x")
    assert texlog_mod.ERR_BANG_RE.match("! boom")
    assert not texlog_mod.ERR_BANG_RE.match(" ! boom")  # 行首锚


# ---------------------------------------------------------------- 归因原语


def test_fuzz_looks_like_never_raises() -> None:
    """``looks_like_input_file`` 对任意 str 恒返回 bool。"""
    rng = fuzz_rng(2026091734)
    for _ in range(2000):
        tok = soup_join(rng, _TOK_SOUP + _TOKENS, 1, 4)
        assert isinstance(looks_like_input_file(tok), bool), short(tok)


def test_looks_like_no_dot_never_file() -> None:
    """基名无 ``.`` → 恒 False（形状判定的先决）。"""
    rng = fuzz_rng(2026091735)
    for _ in range(500):
        tok = soup_join(rng, _TOK_SOUP, 1, 3)
        if "." not in tok.rsplit("/", 1)[-1]:
            assert not looks_like_input_file(tok), short(tok)


def test_fuzz_is_project_file_never_raises(tmp_path: Path) -> None:
    """token 汤 + 两种 root——恒返回 bool（D1 修复后超长裸名回归汤内）。"""
    rng = fuzz_rng(2026091736)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.sty").write_text("x", encoding="utf-8")
    (tmp_path / "main.tex").write_text("x", encoding="utf-8")
    for _ in range(2000):
        tok = soup_pick(rng, _TOK_SOUP)
        for root in (tmp_path, None):
            assert isinstance(is_project_file(tok, root), bool), short(tok)


def test_is_project_file_long_bare_name(tmp_path: Path) -> None:
    """D1 回归：单段 300 字符 token——ENAMETOOLONG 保守归工程 True。"""
    assert is_project_file("a" * 300 + ".tex", tmp_path) is True


def test_is_project_file_empty_bare_name(tmp_path: Path) -> None:
    """观察钉：空裸名 → ``root/""`` 是目录 → False（不可达，token≥1 字符）。"""
    assert not is_project_file("", tmp_path)
    assert is_project_file("", None)  # root 缺席 → 保守 True


class TestDosEps:
    """``is_dos_eps`` 面——真文件/目录/缺失/缓存/NUL（D2）。"""

    def test_fuzz_never_raises_and_bool(self, tmp_path: Path) -> None:
        (tmp_path / "magic.eps").write_bytes(DOS_EPS_MAGIC + b"junk")
        (tmp_path / "plain.eps").write_bytes(b"%!PS-Adobe-3.0")
        (tmp_path / "dir.eps").mkdir()
        cache: dict[str, bool] = {}
        toks = [
            "magic.eps",
            "plain.eps",
            "dir.eps",
            "missing.eps",
            str(tmp_path / "magic.eps"),
            "",
            ".",
            "..",
            "x" * 400 + ".eps",  # 超长名 OSError 走 except 面
            "/",
            "../magic.eps",
        ]
        for tok in toks:
            assert isinstance(is_dos_eps(tok, tmp_path, cache), bool), short(tok)
        assert is_dos_eps("magic.eps", tmp_path, {}) is True
        assert is_dos_eps("plain.eps", tmp_path, {}) is False
        assert is_dos_eps(None, tmp_path, {}) is False
        assert is_dos_eps("magic.eps", None, {}) is False  # root 缺席

    def test_nul_token_valueerror(self, tmp_path: Path) -> None:
        """D2 回归：NUL token → is_file 闸 ValueError 兜住判 False。"""
        assert is_dos_eps("a\x00b.tex", tmp_path, {}) is False

    def test_fifo_not_blocking(self, tmp_path: Path) -> None:
        """P2 回归：fifo 走 is_file 闸即拒——不 open 故无开口阻塞。"""
        os.mkfifo(tmp_path / "f.eps")
        assert is_dos_eps("f.eps", tmp_path, {}) is False

    def test_nul_token_reaches_stack(self) -> None:
        """D2 可达性钉：``(a\\x00b.tex`` 行推 NUL 具名帧（``.tex`` 白名单）。

        消费端 ``is_dos_eps(inner, ...)`` 先于 ``is_project_file`` 的 NUL
        豁免执行（loginfo.py:97/l2.py:348）——D2 不是死路径。
        """
        st: list[str | None] = []
        update_file_stack("(a\x00b.tex", st)
        assert st == ["a\x00b.tex"]
        assert looks_like_input_file("a\x00b.tex") is True

    def test_cache_is_per_scan(self, tmp_path: Path) -> None:
        """观察钉：判定按 token 缓存——文件后改不回读（per-scan 语义）。"""
        f = tmp_path / "x.eps"
        f.write_bytes(DOS_EPS_MAGIC + b"z")
        cache: dict[str, bool] = {}
        assert is_dos_eps("x.eps", tmp_path, cache) is True
        f.write_bytes(b"plain")
        assert is_dos_eps("x.eps", tmp_path, cache) is True  # 缓存陈旧但契约内
