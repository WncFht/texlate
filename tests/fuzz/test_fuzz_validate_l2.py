"""validate l2 ``parse_log*``/``report.aggregate`` 对抗性性质 fuzz。

首波（``test_fuzz_validate.py``）打 l0 规则 + l1 传输层；本文件（原文件
波 2 切块）补 ``l2.parse_log_text``/``parse_log`` 与 ``report.aggregate``
面 + l1 schema 契约残余（``from_dict`` 只兜 coercion 异常、深层类型违例
静默穿透）+ l0 残余钉。对拍 oracle 全部独立实现：fileline 用
``split(":")``、warning 归类用子串/字符步进、nullfont 限界窗手写状态机
——不抄 l2/redlines 的 regex。

``_SOUP`` 通用汤表与首波共用——从 ``test_fuzz_validate`` 单向导入。
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import random

import pytest
from _fuzzkit import (
    assert_deterministic,
    fuzz_rng,
    short,
    soup_join,
    soup_pick,
)
from test_fuzz_validate import _SOUP

from texlate.redlines import L2_REDLINE_CLASSES
from texlate.textutil import is_cjk_cp
from texlate.validate.l0 import Issue, Severity, validate_pair
from texlate.validate.l1 import L1Error, TsResult
from texlate.validate.l2 import L2Verdict, parse_log, parse_log_text
from texlate.validate.report import aggregate

_LOGS_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "logs"

#: log 行 soup——引擎签名/文件栈括号/双格式错误/l.NNN/九类 warning 形态/
#: 边界形（空 msg、长扩展名、==> 复述、unicode 引擎名）混合。
_LOG_SOUP = [
    "This is XeTeX, Version 3.141592653 (TeX Live 2026)",
    "This is pdfTeX, Version 3.14159265",
    "This is 中文引擎, Version 9",
    "This is",
    "**main.tex",
    "(./main.tex",
    "(./sub/chap.tex",
    "(/usr/share/texmf-dist/tex/latex/base/article.cls",
    "(fig1.eps",
    "(fig,2.eps",
    "(draft",
    "(v2.0",
    "(52.00102pt",
    ")",
    ")))",
    "(a)(b.tex)",
    "text (paren) tail",
    "! Undefined control sequence.",
    "!",
    "! Missing character: There is no x in font y",
    "! File ended while scanning use of \\foo.",
    "! Emergency stop.",
    "!  ==> Fatal error occurred, no output PDF file produced!",
    "./main.tex:44: Undefined control sequence.",
    "./sub.tex:12: Missing $ inserted.",
    "x.tex:5: msg",
    "x.abcdefghijk:5: msg",  # 11 字符扩展名——超 {1,10} 不收
    "x.tex:5: ",  # 空 msg 不收
    "x.tex:5:==> x",  # `: ` 单空格硬约定不收
    "./fig/diag.pdf_t:7: Undefined control sequence.",
    "./main.bib:1: LaTeX Error: Missing \\begin{document}.",
    "./colt2020.cls:5:  ==> Fatal error occurred, no output PDF file produced!",
    "./x.tex:9: ==> Fatal error occurred, no output PDF file produced!",
    "./x.tex:12: LaTeX Warning: Reference `r' undefined on input line 12.",
    "./x.tex:3: Package foo Warning: bar",
    "l.44 \\foo{bar}",
    "l.5 \\x",
    "l.",
    "l.0",
    "LaTeX Warning: Citation `a' on page 1 undefined on input line 3.",
    "LaTeX Warning: Reference `r' undefined on input line 9.",
    "LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.",
    "LaTeX Warning: There were undefined references.",
    "LaTeX Warning: There were multiply-defined labels.",
    "Package hyperref Warning: Token not allowed",
    "Foo Warning: bar",
    "warning: lowercase bare",
    "random words Warning: mid-line",
    "Missing character: There is no 中 (U+4E2D) in font cmr10!",
    'Missing character: There is no ; ("3B) in font cmr10!',
    "Missing character: There is no (U+FFFD) in font cmr10!",
    'Missing character: There is no ("FFFD) in font cmr10!',
    "Missing character: There is no x (U+8FD9) in font nullfont!",
    "Missing character: There is no x",  # 无 in font——join 续行探测面
    "in font nullfont",
    "in font cmr10!",
    "Missing character: There is no y in font nullfont",
    "Invalid UTF-8 byte or sequence at line 11 replaced by U+FFFD.",
    "invalid utf-8 byte 9F at line 3",
    "Overfull \\hbox (12.0pt too wide) in paragraph at lines 1--2",
    "Underfull \\vbox (badness 10000) detected at line 7",
    "LaTeX Font Warning: Font shape `TU/ptm/m/n' undefined",
    "Some font shapes were substituted silently",
    "Package pdftex.def Warning: File `fig.pdf' not found on input line 9.",
    "LaTeX Warning: File `x.png' not found on input line 5.",
    "LaTeX Warning: cannot open file `data.dat' for reading.",
    "Package hyperref Warning: Could not locate file `x.out'.",
    "Could not locate file `x.out'.",  # 无 Warning: 标记——预筛不收
    "kpathsea: cannot open file for reading",
    "cannot find image x",
    "Package rerunfilecheck Info: File `x.out' has not changed.",
    "LaTeX Font Info:    Checking defaults",
    "",
    " ",
    "plain text line",
    "Output written on main.pdf (1 page).",
    "No pages of output.",
    "*** (cannot \\read from terminal in nonstop modes)",
    "<read *>",
    "\x00 nul line",
    "tab\there",
    "trailing space ",
    "ｆｕｌｌｗｉｄｔｈ",
    "entering extended mode",
    " %&-line parsing enabled.",
    "?",
    "Type X to quit or <RETURN> to proceed,",
    "Enter file name: ",
    "./x.tex:1: File ended while scanning use of \\foo.",
    "x.tex:٥: unicode digit line no",
]

_MISSCHAR_MARK = "missing character:"


def _o_fileline(ln: str) -> tuple[str, str, str] | None:
    """fileline 形独立解析（split 口径）；非错误形态行返回 ``(fname, lnum, msg)``。"""
    parts = ln.split(":", 2)
    if len(parts) < 3:  # noqa: PLR2004 -- split(":",2) 三段形
        return None
    fname, lnum, rest = parts
    if (
        not fname
        or re.search(r"[()\s]", fname)
        or not lnum.isdecimal()
        or not re.match(r" \S", rest)
    ):
        return None
    dot = fname.rfind(".")
    if dot <= 0 or not re.fullmatch(r"[A-Za-z0-9_-]{1,10}", fname[dot + 1 :]):
        return None
    return fname, lnum, rest[1:]


def _o_nonerr(msg: str) -> bool:
    """fileline 消息面非错误豁免：Warning 前缀行 / ``==>`` 复述行。"""
    if msg.startswith("==>"):
        return True
    return bool(
        re.match(r"(?:LaTeX|Package|Class)\b", msg) and re.search(r"\bWarning\b", msg)
    )


def _o_errs(lines: list[str]) -> list[tuple[int, str | None, int | None]]:
    """独立错误行扫描：``(行idx, tex_file, tex_line直取)``——bang 行 tex 位 None。"""
    out: list[tuple[int, str | None, int | None]] = []
    for i, ln in enumerate(lines):
        if ln.startswith("!"):
            out.append((i, None, None))
            continue
        fl = _o_fileline(ln)
        if fl is not None and not _o_nonerr(fl[2]):
            out.append((i, fl[0], int(fl[1])))
    return out


def _o_is_err(ln: str) -> bool:
    """独立错误行谓词：``!`` 行或非豁免 ``file:line:`` 行。"""
    if ln.startswith("!"):
        return True
    fl = _o_fileline(ln)
    return fl is not None and not _o_nonerr(fl[2])


def _o_err_ctx(lines: list[str], i: int) -> list[str]:
    """错误行 ctx 期望切片——截断于下一错误行（D5 修复口径）。"""
    out: list[str] = []
    for cln in lines[i + 1 : i + 9]:
        if _o_is_err(cln):
            break
        out.append(cln)
    return out


def _o_lnum_ctx(lines: list[str], i: int) -> int | None:
    """ctx 窗口内首个 ``l.NNN``（窗口即 ``_o_err_ctx`` 截断面）。"""
    for ln in _o_err_ctx(lines, i):
        m = re.match(r"l\.(\d+)", ln.strip())
        if m:
            return int(m.group(1))
    return None


def _o_file_btq(low: str) -> bool:
    """``File `x' not found`` 子串谓词——逐次 ``file ` `` 出现位扫描。"""
    pos = 0
    while True:
        i = low.find("file `", pos)
        if i < 0:
            return False
        j = low.find("'", i + 6)
        if j < 0:
            return False
        if j > i + 6 and low[j + 1 : j + 11] == " not found":
            return True
        pos = i + 1


def _o_warnish(ln: str) -> bool:
    """warning 预筛独立实现：``warning:`` 裸串或五类无标记硬 warning。"""
    low = ln.lower()
    return (
        "warning:" in low
        or _MISSCHAR_MARK in low
        or "invalid utf-8 byte" in low
        or "overfull \\hbox" in low
        or "overfull \\vbox" in low
        or "underfull \\hbox" in low
        or "underfull \\vbox" in low
        or _o_file_btq(low)
        or "cannot find" in low
        or "cannot open" in low
    )


def _o_nullfont(low: str) -> bool:
    """nullfont 限界窗状态机：任一 ``missing character:`` 后 ≤90 字符、
    至多跨一个 ``\\n`` 内出现 ``in font nullfont`` 边界即中。"""
    start = 0
    while True:
        i = low.find(_MISSCHAR_MARK, start)
        if i < 0:
            return False
        p = i + len(_MISSCHAR_MARK)
        nl = False
        seg = 0
        while p < len(low):
            if low.startswith("in font ", p):
                if low.startswith("in font nullfont", p):
                    return True
                break
            if low.startswith("missing character", p):
                break
            c = low[p]
            if c == "\n":
                if nl:
                    break
                nl = True
                seg = 0
            else:
                seg += 1
                if seg > 90:  # noqa: PLR2004 -- 窗口上限即实现 {0,90} 语义
                    break
            p += 1
        start = i + 1


def _o_glyph_cp(line: str) -> int | None:
    """``("HEX)``/``(U+HEX)`` 码点独立解析（4-6 位、大小写敏感字面锚）。"""
    anchor = "Missing character: There is no "
    start = 0
    while True:
        i = line.find(anchor, start)
        if i < 0:
            return None
        rest0 = line[i + len(anchor) :]
        cands = []
        sp = rest0.find(" ")
        tok = rest0[:sp] if sp > 0 else ""
        if tok and not any(c.isspace() for c in tok):
            cands.append(rest0[sp + 1 :])  # \S+ token 先行（regex 贪婪序）
        cands.append(rest0)
        for rest in cands:
            hexpart = (
                rest[2:]
                if rest.startswith('("')
                else rest[3:]
                if rest.startswith("(U+")
                else ""
            )
            if not hexpart:
                continue
            digits = []
            for c in hexpart:
                if c in "0123456789abcdefABCDEF":
                    digits.append(c)
                else:
                    break
            hexs = "".join(digits)
            n_dig = len(hexs)
            if not 4 <= n_dig <= 6 or hexpart[n_dig] != ")":  # noqa: PLR2004 -- {4,6} hex 窗即实现语义
                continue
            return int(hexs, 16)
        start = i + 1


def _o_cls(probe_low: str) -> str:  # noqa: PLR0911 -- 规则序即早退序，拍平伤读
    """warning 归类独立实现——规则序同实现，判据全部子串/字符级。"""
    low = probe_low
    if "invalid utf-8 byte" in low or "replaced by u+fffd" in low:
        return "invalid_utf8"
    if _o_nullfont(low):
        return "missing_glyph_nullfont"
    if _MISSCHAR_MARK in low:
        return "missing_glyph"
    if re.search(r"citation[^\n]*undefined", low) or "undefined citations" in low:
        return "citation"
    if (
        re.search(
            r"(?:reference|label|citation)[^\n]*(?:multiply[- ]defined|undefined)",
            low,
        )
        or "undefined references" in low
        or "multiply defined" in low
        or "multiply-defined" in low
    ):
        return "reference"
    if re.search(r"\brerun\b", low) or "may have changed" in low:
        return "rerun"
    if re.search(r"font shape[^\n]*undefined", low) or "some font shapes" in low:
        return "font_subst"
    if (
        _o_file_btq(low)
        or "cannot find" in low
        or "cannot open" in low
        or "could not locate" in low
    ):
        return "file_not_found"
    if (
        "overfull \\hbox" in low
        or "overfull \\vbox" in low
        or "underfull \\hbox" in low
        or "underfull \\vbox" in low
    ):
        return "overfull"
    return "generic"


def _o_warn_counts(
    lines: list[str], err_idx: set[int]
) -> tuple[int, dict[str, int], int]:
    """``(total, by_class, cjk_missing)`` 独立预测——错误行不参与归类。"""
    by_class: dict[str, int] = {}
    total = cjk = 0
    for i, ln in enumerate(lines):
        if i in err_idx or not _o_warnish(ln):
            continue
        nxt = (
            lines[i + 1]
            if "Missing character:" in ln
            and "in font " not in ln
            and i + 1 < len(lines)
            and "in font" in lines[i + 1]
            and not _o_warnish(lines[i + 1])  # 独立 warning 行不拼（D4 修复口径）
            else ""
        )
        probe = (ln + "\n" + nxt).lower() if nxt else ln.lower()
        cls = _o_cls(probe)
        if cls == "missing_glyph":
            cp = _o_glyph_cp(ln)
            if cp == 0xFFFD:  # noqa: PLR2004 -- U+FFFD 码点字面量
                cls = "fffd_glyph"
            elif cp is not None and is_cjk_cp(cp):
                cls = "missing_glyph_cjk"
                cjk += 1
        total += 1
        by_class[cls] = by_class.get(cls, 0) + 1
    return total, by_class, cjk


def _check_l2(text: str) -> L2Verdict:
    """l2 全量对拍：oracle 等值 + 结构不变量 + 序列化/确定性。"""
    assert_deterministic(lambda: parse_log_text(text).to_dict())
    v = parse_log_text(text)
    lines = text.splitlines()

    # —— 引擎签名：仅首行 ``This is (\w+)`` ——
    m = re.match(r"This is (\w+)", lines[0]) if lines else None
    assert v.engine == (m.group(1) if m else None), short(text)

    # —— 错误面 ——
    oerrs = _o_errs(lines)
    assert v.n_errors == len(oerrs), short(text)
    assert v.ok == (v.n_errors == 0)
    assert len(v.errors) == min(len(oerrs), 200), short(text)
    assert (v.first_error is None) == (v.n_errors == 0)
    if v.errors:
        assert v.first_error is v.errors[0]
    for e, (i, ofile, oline) in zip(
        v.errors, oerrs, strict=False
    ):  # 长度已钉 min(oerrs,200)
        assert e.line_no == i + 1
        assert e.head == lines[i].strip()
        assert e.tex_file == ofile
        assert e.tex_line == (oline if oline is not None else _o_lnum_ctx(lines, i)), (
            short(text)
        )
        assert len(e.ctx) <= 8  # noqa: PLR2004 -- CTX_LINES 窗口上限
        assert e.ctx == tuple(_o_err_ctx(lines, i))
        assert all(isinstance(s, str) and s for s in e.file_stack)
        if e.eof_file is not None:
            assert "File ended while scanning" in e.head

    # —— warning 面 ——
    ws = v.warnings
    o_total, o_by_class, o_cjk = _o_warn_counts(lines, {i for i, _, _ in oerrs})
    assert ws.total == o_total, short(text)
    assert ws.by_class == o_by_class, short(text)
    assert ws.cjk_missing == o_cjk, short(text)
    assert set(ws.samples) == set(ws.hits) == set(ws.by_class)
    for cls, cnt in ws.by_class.items():
        assert len(ws.samples[cls]) == min(cnt, 5) == len(ws.hits[cls])
        for h in ws.hits[cls]:
            assert set(h) == {"file", "line", "head", "log_line"}
            assert h["line"] is None
            assert isinstance(h["log_line"], int)
            assert h["head"] == lines[int(h["log_line"]) - 1].strip()
    assert len(ws.redlines) == len(set(ws.redlines))  # 去重
    for r in ws.redlines:
        cls, sep, head = r.partition(": ")
        assert sep
        assert cls in L2_REDLINE_CLASSES
        assert len(head) <= 120  # noqa: PLR2004 -- 截断上限
    assert all(s.startswith("invalid_utf8@") for s in ws.sys_hits)
    assert len(ws.sys_hits) == len(set(ws.sys_hits))

    # —— tail/序列化 ——
    assert v.tail == tuple(lines[-30:])
    json.dumps(v.to_dict())
    ad = v.attribution_dict()
    json.dumps(ad)
    assert ad["n_errors"] == v.n_errors
    assert ad["warn_by_class"] == ws.by_class
    hits = ad["hits"]
    assert [h["log_line"] for h in hits] == sorted(h["log_line"] for h in hits)
    assert sum(1 for h in hits if h["kind"] == "error") <= 50  # noqa: PLR2004
    return v


def test_l2_soup_oracle() -> None:
    """soup log 全量对拍：错误计数/归类/码点细分/归一化全部独立预测。"""
    rng = fuzz_rng(20261101)
    for _ in range(800):
        text = soup_join(rng, _LOG_SOUP, 1, 60, "\n")
        _check_l2(text)


def _load_fixture_logs() -> list[tuple[str, str]]:
    return [
        (p.name, p.read_text("utf-8", errors="replace"))
        for p in sorted(_LOGS_DIR.glob("*.log"))
    ]


def _mutate_lines(  # noqa: PLR0911 -- 算子派发即早退表
    rng: random.Random, lines: list[str]
) -> tuple[list[str], str]:
    """log 行级变异算子；返回 ``(新行表, 算子名)``。"""
    op = soup_pick(
        rng, ["trunc", "drop", "bang+1", "fl+1", "warn+1", "dup", "shuffle", "inject"]
    )
    if op == "trunc" and lines:
        return lines[: rng.randrange(len(lines) + 1)], "trunc"
    if op == "drop" and lines:
        a = rng.randrange(len(lines))
        b = min(len(lines), a + rng.randrange(1, 40))
        return [*lines[:a], *lines[b:]], "drop"
    if op == "bang+1":
        i = rng.randrange(len(lines) + 1)
        return [*lines[:i], "! fuzz injected error", *lines[i:]], "bang+1"
    if op == "fl+1":
        i = rng.randrange(len(lines) + 1)
        return [*lines[:i], "./fuzz.tex:7: injected fileline error", *lines[i:]], "fl+1"
    if op == "warn+1":
        i = rng.randrange(len(lines) + 1)
        return [
            *lines[:i],
            "LaTeX Warning: Citation `fz' undefined on input line 3.",
            *lines[i:],
        ], "warn+1"
    if op == "dup" and lines:
        a = rng.randrange(len(lines))
        b = min(len(lines), a + rng.randrange(1, 20))
        i = rng.randrange(len(lines) + 1)
        return [*lines[:i], *lines[a:b], *lines[i:]], "dup"
    if op == "shuffle" and len(lines) > 2:  # noqa: PLR2004 -- 乱序最小片段长
        a = rng.randrange(len(lines) - 1)
        b = min(len(lines), a + rng.randrange(1, 12))
        seg = lines[a:b]
        rng.shuffle(seg)
        return [*lines[:a], *seg, *lines[b:]], "shuffle"
    i = rng.randrange(len(lines) + 1)
    return [*lines[:i], soup_pick(rng, _LOG_SOUP), *lines[i:]], "inject"


def test_l2_fixture_mutation() -> None:
    """真 fixture log 变异 fuzz：每次变异后全量 oracle + 算子级变质断言。"""
    rng = fuzz_rng(20261102)
    fixtures = _load_fixture_logs()
    assert fixtures, "tests/fixtures/logs 为空"
    for name, text in fixtures:
        base = _check_l2(text)
        lines = text.splitlines()
        for _ in range(40):
            mlines, op = _mutate_lines(rng, lines)
            mv = _check_l2("\n".join(mlines))
            if op in {"bang+1", "fl+1"}:
                assert mv.n_errors == base.n_errors + 1, (name, op)
            elif op == "warn+1":
                assert mv.warnings.total == base.warnings.total + 1, name
                assert (
                    mv.warnings.by_class.get("citation", 0)
                    == base.warnings.by_class.get("citation", 0) + 1
                ), name


def test_l2_fixture_splice_additivity() -> None:
    """两 log 拼接：错误数/warning 总数可加；engine/first_error 随前半。"""
    rng = fuzz_rng(20261103)
    fixtures = _load_fixture_logs()
    for _ in range(60):
        (na, ta), (nb, tb) = rng.choice(fixtures), rng.choice(fixtures)
        va, vb = parse_log_text(ta), parse_log_text(tb)
        vc = _check_l2(ta + "\n" + tb)
        assert vc.n_errors == va.n_errors + vb.n_errors, (na, nb)
        assert vc.warnings.total == va.warnings.total + vb.warnings.total, (na, nb)
        assert vc.engine == va.engine
        if va.first_error is not None:
            assert vc.first_error is not None
            assert vc.first_error.line_no == va.first_error.line_no
        elif vb.first_error is not None:
            off = len((ta + "\n").splitlines())
            assert vc.first_error is not None
            assert vc.first_error.line_no == vb.first_error.line_no + off


def test_l2_parse_log_path(tmp_path: Path) -> None:
    """路径入口一致性 + 缺席/目录/坏字节降级为 log_missing 或 replace 解码。"""
    rng = fuzz_rng(20261104)
    text = soup_join(rng, _LOG_SOUP, 5, 40, "\n")
    p = tmp_path / "x.log"
    p.write_bytes(text.encode("utf-8") + b"\xff\xfe trailing")
    decoded = p.read_bytes().decode("utf-8", "replace")
    assert parse_log(p).to_dict() == parse_log_text(decoded).to_dict()
    assert parse_log(tmp_path / "absent.log").log_missing is True
    assert parse_log(tmp_path).log_missing is True  # 目录 → is_file 闸
    assert parse_log("\x00nul").log_missing is True  # NUL 路径不抛


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="os.mkfifo 缺席平台")
def test_p3_parse_log_fifo_is_missing(tmp_path: Path) -> None:
    """P3 回归：fifo/特殊文件先吃 ``is_file`` 闸——``exists()`` 对 fifo 为真，
    无闸时 ``read_text`` 阻塞至有 writer。"""
    fifo = tmp_path / "x.log"
    os.mkfifo(fifo)
    assert parse_log(fifo).log_missing is True


def test_l2_eof_attribution() -> None:
    """eof_file 归因：``)`` 弹出后 ≤16 行内的 File-ended 错回填弹出件。"""
    v = parse_log_text("(./a.tex\n)\n! File ended while scanning use of \\x.\n")
    assert v.errors[0].eof_file == "./a.tex"
    v = parse_log_text("(./a.tex\n! File ended while scanning use of \\x.\n")
    assert v.errors[0].eof_file is None  # 无弹出 → 不归因
    pad = "\n".join(f"pad{i}" for i in range(20))
    v = parse_log_text(f"(./a.tex\n)\n{pad}\n! File ended while scanning use of \\x.\n")
    assert v.errors[0].eof_file is None  # 弹窗 >16 → 不归因
    v = parse_log_text("(./a.tex\n)\n! Undefined control sequence.\n")
    assert v.errors[0].eof_file is None  # 非 File-ended 错不套用


def test_l2_warn_oracle_directed() -> None:
    """归类 oracle 定向锚——oracle 自身的正确性证据（失配即实现 bug 非 oracle bug）。"""
    cases = {
        "Invalid UTF-8 byte or sequence": "invalid_utf8",
        "invalid utf-8 byte 9F": "invalid_utf8",
        "Warning: replaced by U+FFFD.": "invalid_utf8",
        "Missing character: There is no x in font nullfont": "missing_glyph_nullfont",
        "Missing character: There is no x in font cmr10": "missing_glyph",
        "Missing character: There is no 中 (U+4E2D) in font cmr10!": "missing_glyph_cjk",
        "Missing character: There is no (U+FFFD) in font cmr10!": "fffd_glyph",
        "LaTeX Warning: Citation `a' undefined on input line 3.": "citation",
        "LaTeX Warning: Reference `r' undefined on input line 9.": "reference",
        "LaTeX Warning: Label(s) may have changed. Rerun to get cross-references right.": "rerun",
        "LaTeX Font Warning: Font shape `TU/x' undefined": "font_subst",
        "Package pdftex.def Warning: File `fig.pdf' not found on input line 9.": "file_not_found",
        "LaTeX Warning: cannot open file `d.dat' for reading.": "file_not_found",
        "Overfull \\hbox (12.0pt too wide) in paragraph": "overfull",
        "Underfull \\vbox (badness 10000)": "overfull",
        "Foo Warning: something odd": "generic",
        "plain text": "NONE",
        "Missing character:": "missing_glyph",
    }
    for ln, want in cases.items():
        v = parse_log_text(ln + "\n")
        got = next(iter(v.warnings.by_class), "NONE")
        assert got == want, (ln, v.warnings.by_class)


# ---------------------------------------------------------------- l1 schema 残余


def test_d1_ok_relative_must_be_bool() -> None:
    """D1 回归：``ok_relative`` 非 bool/None → ``L1Error``（真值串 ``"no"``
    曾穿透进 ``verdict_ok`` 使聚合 fail-open）。"""
    with pytest.raises(L1Error):
        TsResult.from_dict({"ok": False, "ok_relative": "no"})


@pytest.mark.parametrize(
    "payload",
    [
        {"ok": False, "parse_errors": ["oops"]},
        {"ok": False, "env_mismatches": [42]},
        {"ok": False, "placeholders": {"typos": ["x"]}},
    ],
)
def test_d2_detail_items_must_be_dicts(payload: dict[str, Any]) -> None:
    """D2 回归：明细列表项非 dict → ``L1Error``（曾在 ``report.feedback``
    消费侧泄 ``AttributeError``）。"""
    with pytest.raises(L1Error):
        TsResult.from_dict(payload)


@pytest.mark.parametrize(
    "ph",
    [
        {"missing": None},
        {"missing": "MATH_1"},
        {"unexpected": 7},
        {"typos": None},
    ],
)
def test_d3_placeholder_values_must_be_lists(ph: dict[str, Any]) -> None:
    """D3 回归：``placeholders`` 三键值非 list → ``L1Error``（``missing=None``
    曾炸 ``len(None)``、``missing=str`` 曾产逐字符垃圾反馈）。"""
    with pytest.raises(L1Error):
        TsResult.from_dict({"ok": False, "placeholders": ph})


def test_d4_misschar_join_steals_class() -> None:
    """D4 回归：misschar 续行拼接在次行是独立 warning 行时不拼——
    ``in font nullfont`` 属次行自身锚点，不得窃走本行 CJK 归类。"""
    v = parse_log_text(
        "Missing character: There is no 中 (U+4E2D)\n"
        "Missing character: There is no y in font nullfont\n"
    )
    assert v.warnings.by_class.get("missing_glyph_cjk") == 1
    assert v.warnings.by_class.get("missing_glyph_nullfont") == 1
    assert v.warnings.cjk_missing == 1
    assert any("missing_glyph_cjk" in r for r in v.warnings.redlines)


def test_d4_misschar_join_wrap_still_works() -> None:
    """D4 回归补：真折行续行（裸 ``in font nullfont`` 碎片非 warning 形态）
    仍拼接——nullfont 豁免面不回退。"""
    v = parse_log_text("Missing character: There is no 中\nin font nullfont\n")
    assert v.warnings.by_class.get("missing_glyph_nullfont") == 1
    assert v.warnings.cjk_missing == 0


def test_d5_bang_ctx_borrows_next_error_lnum() -> None:
    """D5 回归：``!`` 错 ctx 截断于下一错误行——``l.NNN`` 属邻错定位，
    errA 不得借用 errB 行号。"""
    v = parse_log_text("! errA\n! errB\nl.9 \\y\n")
    assert v.errors[0].tex_line is None
    assert v.errors[0].ctx == ()
    assert v.errors[1].tex_line == 9  # noqa: PLR2004 -- 字面行号即输入语料


def test_l1_schema_positive_shapes() -> None:
    """反向钉：合法形态不得被误收 L1Error——防修 D1-D3 时过度收紧。"""
    r = TsResult.from_dict(
        {
            "id": "c1",
            "ok": True,
            "ok_relative": None,
            "parse_errors": [{"type": "ERROR", "row": 1, "snippet": "s"}],
            "env_mismatches": [
                {"kind": "end_name", "begin_env": "a", "end_env": "b", "line": 3}
            ],
            "unclosed_math": 0,
            "brace_balance": 0,
            "placeholders": {"missing": [], "unexpected": [], "typos": []},
            "parse_ms": 1.5,
        }
    )
    assert r.ok
    assert r.verdict_ok
    assert r.parse_errors[0]["row"] == 1
    r2 = TsResult.from_dict({"ok": True, "ok_relative": False})
    assert r2.verdict_ok is False


# ---------------------------------------------------------------- report 聚合面


def _rand_ts(rng: random.Random) -> TsResult:
    """合法形态 TsResult 生成器（坏形态归 D1-D3 钉，不进绿路径）。"""
    return TsResult(
        ok=rng.random() < 0.5,  # noqa: PLR2004 -- 概率阈值字面量
        ok_relative=rng.choice([None, None, True, False]),
        parse_errors=[
            {"type": "ERROR", "row": i, "snippet": f"s{i}"}
            for i in range(rng.randint(0, 8))
        ],
        env_mismatches=[
            {"kind": "end_name", "begin_env": f"b{i}", "end_env": f"e{i}", "line": i}
            for i in range(rng.randint(0, 6))
        ],
        unclosed_math=rng.randint(-2, 4),
        brace_balance=rng.randint(-4, 4),
        placeholders={
            "missing": [f"M{i}" for i in range(rng.randint(0, 4))],
            "unexpected": [f"U{i}" for i in range(rng.randint(0, 4))],
            "typos": [
                {"found": f"f{i}", "expected": f"e{i}"}
                for i in range(rng.randint(0, 4))
            ],
        },
        parse_ms=rng.random() * 10,
        error=rng.choice([None, "boom"]),
    )


def test_report_aggregate_fuzz() -> None:
    """``aggregate`` 三级组合 fuzz：ok/n_error/n_warn/hard_failures/feedback/
    summary 全 oracle；to_dict JSON 可落盘。"""
    rng = fuzz_rng(20261105)
    for _ in range(400):
        l0 = (
            validate_pair(soup_join(rng, _SOUP, 0, 12), soup_join(rng, _SOUP, 0, 12))
            if rng.random() < 0.7  # noqa: PLR2004 -- 在场层概率阈值
            else None
        )
        l1 = _rand_ts(rng) if rng.random() < 0.7 else None  # noqa: PLR2004
        l2 = (
            parse_log_text(soup_join(rng, _LOG_SOUP, 0, 40, "\n"))
            if rng.random() < 0.5  # noqa: PLR2004
            else (
                L2Verdict(log_missing=True) if rng.random() < 0.3 else None  # noqa: PLR2004
            )
        )
        rep = aggregate(chunk_id=f"c{rng.randint(0, 9)}", l0=l0, l1=l1, l2=l2)

        exp_ok = (
            (l0 is None or l0.ok)
            and (l1 is None or bool(l1.verdict_ok))
            and (l2 is None or l2.log_missing or l2.ok)
        )
        assert rep.ok == exp_ok
        exp_err = (
            (l0.n_error if l0 else 0)
            + (0 if l1 is None or l1.verdict_ok else 1)
            + (0 if l2 is None or l2.log_missing else l2.n_errors)
        )
        assert rep.n_error == exp_err
        assert rep.ok == (rep.n_error == 0)
        exp_warn = (l0.n_warn if l0 else 0) + (
            0 if l2 is None or l2.log_missing else l2.warnings.total
        )
        assert rep.n_warn == exp_warn

        hf = rep.hard_failures()
        exp_hf = (
            (l0.n_error if l0 else 0)
            + (0 if l1 is None or l1.verdict_ok else 1)
            + (0 if l2 is None or l2.log_missing or l2.ok else 1)
        )
        assert len(hf) == exp_hf
        assert all(h.startswith(("l0:", "l1:", "l2:")) for h in hf)
        fb = rep.feedback()  # 合法形态恒不抛
        if rep.ok:
            assert fb == ""
            assert hf == []

        s = rep.summary()
        parts = s.rsplit(" ", 5)
        exp_marks = [
            "L0-" if l0 is None else ("L0✓" if l0.ok else "L0✗"),
            "L1-" if l1 is None else ("L1✓" if l1.verdict_ok else "L1✗"),
            "L2-"
            if l2 is None
            else ("L2?" if l2.log_missing else ("L2✓" if l2.ok else "L2✗")),
        ]
        assert parts[-5:-2] == exp_marks, short(s)
        assert parts[-2] == f"err={rep.n_error}"
        assert parts[-1] == f"warn={rep.n_warn}"
        json.dumps(rep.to_dict())


def test_obs_log_missing_overrides_nerrors() -> None:
    """OBSERVED 钉：手造 ``log_missing=True, n_errors=3`` 的不一致 verdict，
    aggregate 只信 log_missing——pin 当前行为防静默改语义。"""
    rep = aggregate(l2=L2Verdict(log_missing=True, n_errors=3))
    assert rep.ok is True
    assert rep.n_error == 0


def test_obs_tsresult_error_field_unread() -> None:
    """OBSERVED 钉：``error`` 字段只被 sign() 读——validate/aggregate 不看，
    ``ok=True, error='boom'`` 照常过。"""
    rep = aggregate(l1=TsResult(ok=True, error="boom"))
    assert rep.ok is True
    assert rep.n_error == 0


# ---------------------------------------------------------------- l0 残余钉


def test_l0_env_tail_cap() -> None:
    """``_ENV_CHECK_TAIL_LIMIT=50``：60 个互异多余 ``\\end{X}`` → 1 error + 50 warn。"""
    zh = "".join(f"\\end{{env{i}}}" for i in range(60))
    rep = validate_pair("", zh)
    envs = [i for i in rep.issues if i.rule == "env"]
    # 60 互异 end 名：orphan 签名 1 error + tail-diff warn 截断 50（其余规则
    # 如 macro 结构命令计数另算，不钉死 n_error 总数）
    assert sum(i.severity is Severity.WARN for i in envs) == 50  # noqa: PLR2004
    assert any(i.severity is Severity.ERROR and "多余" in i.message for i in envs)


def test_l0_issue_to_dict_pos_edge() -> None:
    """``Issue.to_dict`` pos=-1 省略键、pos≥0 写入——边界 pin。"""
    assert "pos" not in Issue("env", Severity.ERROR, "m").to_dict()
    assert Issue("env", Severity.ERROR, "m", pos=0).to_dict()["pos"] == 0
