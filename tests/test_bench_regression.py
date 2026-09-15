r"""B2 fixtures 陷阱断言回归（docs/10 §B2）——spike ``miniscanner_test`` 断言矩阵移植到 ``texlate.latex``。

底材 ``bench/fixtures/*.tex``（入库，逐字节即语义——永不格式化/润色）：

- ``tricky.tex``：T01–T29 单点陷阱 26 条断言 + ``_meta`` 残留计数 info 行；
- ``tricky-209.tex``：LaTeX 2.09 旧式组合 3 条（``\beq/\eeq``、``\documentstyle``、``\def``）+ parse_ok；
- ``tricky-multi/``：T14 ``\input/\include`` 展平 4 条。

断言函数 ``assert_tricky`` / ``assert_209`` / ``assert_multi`` 与 bench 跑分器
``bench/py/fixture_assert.py`` 共享（该脚本直接 import 本模块）。门槛（docs/10
§B2）：33 条 dict 断言全 ``pass``——``partial`` 在 spike 里是容忍档，但产品
现状全 pass，退化到 partial 即回归，这里按 ``== "pass"`` 严判。
"""

from __future__ import annotations

import difflib
import re
import signal
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from texlate.latex import flatten_inputs, parse_file, reconstruct, validate_result
from texlate.latex.placeholder import CHUNK_RX, PH_RX

if TYPE_CHECKING:
    from types import FrameType

    from texlate.latex.model import Chunk, ScanResult

FIXTURES = Path(__file__).resolve().parent.parent / "bench" / "fixtures"

FIXTURE_FILES = [
    ("tricky.tex", FIXTURES / "tricky.tex"),
    ("tricky-209.tex", FIXTURES / "tricky-209.tex"),
    ("tricky-multi/main.tex", FIXTURES / "tricky-multi" / "main.tex"),
]

# 泄漏扫描口径（spike 同表）：可译 chunk 内不得出现这些构造
LEAK_PATTERNS = {
    "dollar": re.compile(r"\$"),
    "cite_family": re.compile(r"\\cite[a-zA-Z]*"),
    "ref_family": re.compile(r"\\(?:eq|auto|c|page|name|sub)?ref(?![a-zA-Z])"),
    "begin_env": re.compile(r"\\begin\{"),
    "conditional": re.compile(r"\\(?:if[a-zA-Z]+|else|fi)(?![a-zA-Z])"),
    "input_include": re.compile(r"\\(?:input|include)\{"),
}


class ParseTimeoutError(Exception):
    """parse 超时（spike 同款 30s SIGALRM 护栏——挂死型回归也按失败算）。"""


def _alarm(_signum: int, _frame: FrameType | None) -> None:
    raise ParseTimeoutError


# ---------------------------------------------------------------- 测量包


def chunks_blob(res: ScanResult) -> str:
    """全部可译 chunk 的 content 拼一块——泄漏断言的扫描面。"""
    return "\n".join(c.content for c in res.chunks)


def fake_translation(chunk: Chunk, idx: int) -> str:
    """假译文：CJK 前缀 + 原样保留的内嵌占位符（契约压力形）。"""
    keep = PH_RX.findall(chunk.content)
    return f"【假译文{idx}】" + "".join(keep)


def scan_chunks(res: ScanResult) -> dict:
    """泄漏扫描（spike 同口径）：可译 chunk 内命中受保护构造的计数。"""
    hits = dict.fromkeys(LEAK_PATTERNS, 0)
    leaked = 0
    examples = []
    for c in res.chunks:
        found = [name for name, rx in LEAK_PATTERNS.items() if rx.search(c.content)]
        if found:
            leaked += 1
            for f in found:
                hits[f] += 1
            examples.append(
                {"context": c.context, "leaks": found, "snippet": c.content[:120]}
            )
    return {
        "n_translatable_chunks": len(res.chunks),
        "n_leaked": leaked,
        "hits": hits,
        "examples": examples[:5],
    }


def classify_recon(orig: str, recon: str) -> tuple[str, float, int]:
    """重建分级：identical / normalized / diverged（spike 同口径）。"""
    if orig == recon:
        return "identical", 1.0, -1

    def norm(s: str) -> str:
        return re.sub(r"\s+", " ", s).strip()

    if norm(orig) == norm(recon):
        return "normalized", 1.0, -1
    i = 0
    n = min(len(orig), len(recon))
    while i < n and orig[i] == recon[i]:
        i += 1
    ratio = difflib.SequenceMatcher(None, orig, recon).quick_ratio()
    return "diverged", round(ratio, 4), i


@dataclass
class FixtureScan:
    """单个 fixture 的解析 + 双重重建测量包（断言函数的输入）。"""

    name: str
    ok: bool
    wall_ms: float
    res: ScanResult | None = None
    recon: str = ""  # identity 重建（对比基准是展平后原文）
    recon_fake: str = ""  # 假译文重建
    flat: str = ""  # flatten_inputs 后的原文
    error: str = ""
    residue_chunk_ph: int = -1
    residue_protect_ph: int = -1


def run_fixture(name: str, path: Path, timeout_s: int = 30) -> FixtureScan:
    """parse + identity/假译文重建一次（spike ``parse_one``+``rebuild_metrics`` 合体）。"""
    t0 = time.perf_counter()
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout_s)
    try:
        res = parse_file(path, flatten=True)
    except ParseTimeoutError:
        return FixtureScan(
            name=name, ok=False, wall_ms=timeout_s * 1000.0, error="Timeout(>30s)"
        )
    except Exception as e:  # noqa: BLE001 — 断言跑分语义：解析失败记为 fail 行而非抛出
        ms = round((time.perf_counter() - t0) * 1000, 1)
        return FixtureScan(
            name=name, ok=False, wall_ms=ms, error=f"{type(e).__name__}: {e}"
        )
    finally:
        signal.alarm(0)
    ms = round((time.perf_counter() - t0) * 1000, 1)
    recon = reconstruct(res)
    translated = {c.id: fake_translation(c, i) for i, c in enumerate(res.chunks)}
    recon_fake = reconstruct(res, translated)
    flat = flatten_inputs(
        path.read_text(encoding="utf-8", errors="replace"),
        str(path.parent),
        str(path.parent),
    )
    return FixtureScan(
        name=name,
        ok=True,
        wall_ms=ms,
        res=res,
        recon=recon,
        recon_fake=recon_fake,
        flat=flat,
        residue_chunk_ph=len(CHUNK_RX.findall(recon_fake)),
        residue_protect_ph=len(PH_RX.findall(recon_fake)),
    )


# ---------------------------------------------------------------- tricky.tex 断言矩阵


def assert_tricky(  # noqa: PLR0915 — 逐条断言平铺即清单（spike 同构）
    res: ScanResult, recon: str, recon_fake: str
) -> dict[str, dict[str, str]]:
    """tricky.tex 逐条陷阱断言（spike 移植；``_meta`` 是 info 行非断言）。"""
    chunks = chunks_blob(res)
    ph_vals = "\n".join(res.ph_map.values())
    out: dict[str, dict[str, str]] = {}

    def leak(rx: str) -> str | None:
        m = re.search(rx, chunks)
        return m.group(0) if m else None

    # T01 \be..\ee 宏展开数学环境整体保护
    hit = leak(r"\\be\b|\\ee\b|\\wt\{A\}")
    out["T01"] = {
        "status": "fail" if hit else "pass",
        "detail": f"macro-env math leaked: {hit!r}"
        if hit
        else "\\be..\\ee -> [[MATH_n]]",
    }

    # T02 \dR 自定义数学宏
    hit = leak(r"\\dR")
    out["T02"] = {
        "status": "fail" if hit else "pass",
        "detail": f"custom macro raw in chunk: {hit!r}"
        if hit
        else "\\dR -> [[MACRO_n]]",
    }

    # T03 \def 宏定义不译
    hit = leak(r"\\def\\wt|\\def\\Tr")
    ok = "\\def\\wt{\\widetilde}" in recon
    out["T03"] = {
        "status": "pass" if (ok and not hit) else "fail",
        "detail": "def in preamble, verbatim"
        if ok and not hit
        else f"def lost/leaked: {hit!r} in_recon={ok}",
    }

    # T04 natbib 全族 + ref 族
    fam = [
        "citep",
        "citet",
        "citealp",
        "citeauthor",
        "citeyear",
        "autoref",
        "cref",
        "pageref",
        "nameref",
    ]
    leaked_cmds = [c for c in fam if re.search(r"\\" + c + r"(?![a-zA-Z])", chunks)]
    leaked_keys = [
        k for k in ["vaswani2017", "kingma2015", "he2016", "devlin2019"] if k in chunks
    ]
    leaked_refs = [
        r for r in ["ref", "eqref", "label"] if re.search(r"\\" + r + r"\{", chunks)
    ]
    out["T04"] = {
        "status": "fail" if (leaked_cmds or leaked_keys or leaked_refs) else "pass",
        "detail": f"cmds={leaked_cmds} keys={leaked_keys} core={leaked_refs}",
    }

    # T05 \section[opt]{long}
    out["T05"] = {
        "status": "pass" if "A Very Long Section Title" in chunks else "fail",
        "detail": "long title chunked"
        if "A Very Long Section Title" in chunks
        else "optional arg unsupported -> title lost",
    }

    # T06 verbatim/lstlisting 内 % 原样
    verb_ok = "100% real data" in recon and "\\end{verbatim}" in recon
    lst_ok = "code%with%percent" in recon
    out["T06"] = {
        "status": "pass" if (verb_ok and lst_ok) else "fail",
        "detail": f"verbatim intact={verb_ok} lstlisting={lst_ok}",
    }

    # T07 \url{..%20..} \verb|a%b|
    url_ok = "a%20b%20c.pdf" in recon
    verb_ok2 = "a%b" in recon
    out["T07"] = {
        "status": "pass" if (url_ok and verb_ok2) else "fail",
        "detail": f"url %20={url_ok} verb={verb_ok2}",
    }

    # T08 注释边界
    cmt_in_chunks = "a comment with" in chunks or "unbalanced brace" in chunks
    comment_text_leak = "followed by real comment" in chunks
    pct_kept = "\\%" in recon
    if cmt_in_chunks:
        st = "fail"
    elif comment_text_leak or not pct_kept:
        st = "partial"
    else:
        st = "pass"
    out["T08"] = {
        "status": st,
        "detail": f"comment-in-chunk={cmt_in_chunks} "
        f"\\\\%-trail={comment_text_leak} "
        f"\\% kept={pct_kept}",
    }

    # T09 author 保护
    out["T09"] = {
        "status": "pass" if "Alice Smith" not in chunks else "fail",
        "detail": "author -> [[AUTHOR_n]]",
    }

    # T10 subequations/align/flalign
    fl_leak = leak(r"x\s*&=\s*y") or leak(r"a\s*&=\s*b")
    subeq_ph = any("subequations" in v or "flalign" in v for v in res.ph_map.values())
    out["T10"] = {
        "status": "pass"
        if (not fl_leak and subeq_ph)
        else ("partial" if not fl_leak else "fail"),
        "detail": "all -> [[MATH_n]]"
        if subeq_ph and not fl_leak
        else f"leak={fl_leak!r}",
    }

    # T11 theorem 可选名 + 正文可译
    out["T11"] = {
        "status": "pass"
        if ("the statement holds" in chunks and "\\begin{theorem}" in recon)
        else "fail",
        "detail": "theorem body chunked, env literal",
    }

    # T12 caption 内 footnote
    out["T12"] = {
        "status": "pass" if "computed by hand" in chunks else "fail",
        "detail": "footnote text rides in caption chunk",
    }

    # T13 \ifdraft..\else..\fi
    cond_leak = re.findall(r"\\ifdraft|\\else|\\fi|\\drafttrue", chunks)
    out["T13"] = {
        "status": "partial" if cond_leak else "pass",
        "detail": "conditional tokens as boundary literals"
        + (f" LEAKED {sorted(set(cond_leak))}" if cond_leak else ""),
    }

    # T16 \NewDocumentCommand
    out["T16"] = {
        "status": "pass"
        if ("\\NewDocumentCommand" in recon and "\\NewDocumentCommand" not in chunks)
        else "fail",
        "detail": "xparse def kept verbatim",
    }

    # T17 数学内 \text{}
    out["T17"] = {
        "status": "pass" if "if and only if" not in chunks else "fail",
        "detail": "\\text{} inside [[MATH]]",
    }

    # T18 figure 内 caption
    out["T18"] = {
        "status": "pass"
        if ("A figure with" in chunks and "\\begin{figure}" in recon)
        else "fail",
        "detail": "caption mined from [[ENV]] body",
    }

    # T19 abstract
    out["T19"] = {
        "status": "pass" if "We study tricky" in chunks else "fail",
        "detail": "abstract text chunked",
    }

    # T20 列表
    has_items = (
        "First item" in chunks
        and "Numbered one" in chunks
        and "Its definition" in chunks
    )
    out["T20"] = {
        "status": "pass" if has_items else "fail",
        "detail": "item texts chunked",
    }

    # T21 includegraphics
    gfx = "figs/plot.pdf" in ph_vals and "figs/plot.pdf" not in chunks
    out["T21"] = {"status": "pass" if gfx else "fail", "detail": "-> [[GRAPHICS_n]]"}

    # T22 \href
    out["T22"] = {
        "status": "pass"
        if ("the documentation" in chunks and "https://example.com" in ph_vals)
        else "fail",
        "detail": "url->[[HREF_n]], text translatable",
    }

    # T23 \emph\textbf\textit
    out["T23"] = {
        "status": "pass"
        if all(s in chunks for s in ["very important", "bold claim", "italic"])
        else "fail",
        "detail": "inline formatting text merged into chunk",
    }

    # T24 \bibliography
    out["T24"] = {
        "status": "pass" if "\\bibliography{refs}" in recon else "fail",
        "detail": "-> [[BIB_n]], survives",
    }

    # T25 \makeatletter
    out["T25"] = {
        "status": "pass" if "\\makeatletter" in recon else "fail",
        "detail": "kept literal",
    }

    # T26 \[ \] \( \)
    out["T26"] = {
        "status": "pass"
        if ("\\int_0^1" not in chunks and "e^{i\\pi}" not in chunks)
        else "fail",
        "detail": "display/inline delims -> [[MATH_n]]",
    }

    # T27 重音
    out["T27"] = {
        "status": "pass"
        if ("\\'e" in recon or "caf\\'e" in recon) and 'M\\"uller' in recon
        else "fail",
        "detail": "accent commands preserved",
    }

    # T29 独立 footnote
    out["T29"] = {
        "status": "pass"
        if "This footnote text should be translated" in chunks
        else "fail",
        "detail": "footnote arg -> own chunk",
    }

    res_chunk = len(CHUNK_RX.findall(recon_fake))
    res_prot = len(PH_RX.findall(recon_fake))
    out["_meta"] = {
        "status": "info",
        "detail": f"chunks={len(res.chunks)} ph={len(res.ph_map)} "
        f"residue_chunk={res_chunk} residue_prot={res_prot}",
    }
    return out


def assert_209(res: ScanResult | None, recon: str) -> dict[str, object]:
    """tricky-209.tex 断言（LaTeX 2.09 旧式组合；``parse_ok`` 是 bool 行）。"""
    chunks = chunks_blob(res) if res else ""
    beq_leak = re.search(r"\\beq\b|\\eeq\b", chunks)
    return {
        "parse_ok": res is not None,
        "beq_eeq_trap": {
            "status": "fail" if beq_leak else "pass",
            "detail": f"\\beq..\\eeq leaked: {beq_leak.group(0) if beq_leak else None}",
        },
        "documentstyle": {
            "status": "pass"
            if res is not None and "\\documentstyle" in recon
            else "fail",
            "detail": "2.09 preamble survives",
        },
        "def_macros": {
            "status": "pass" if res is not None and "\\def\\Im" in recon else "fail",
            "detail": "\\def kept verbatim",
        },
    }


def assert_multi(recon_multi: str) -> dict[str, dict[str, str]]:
    """T14: tricky-multi ``\\input/\\include`` 展平断言。"""
    return {
        "T14_input_expanded": {
            "status": "pass" if "Intro paragraph" in recon_multi else "fail",
            "detail": "sub/intro.tex inlined",
        },
        "T14_include_expanded": {
            "status": "pass" if "Methods paragraph" in recon_multi else "fail",
            "detail": "sub/methods.tex inlined",
        },
        "T14_nested_input": {
            "status": "pass" if "Nested paragraph content" in recon_multi else "fail",
            "detail": "nested \\input resolved vs main dir",
        },
        "T14_commented_input": {
            "status": "pass"
            if "THIS FILE MUST NOT APPEAR" not in recon_multi
            else "fail",
            "detail": "commented \\input not expanded",
        },
    }


# ---------------------------------------------------------------- 模块级测量（3 个小文件，ms 级）

_PARSED = {name: run_fixture(name, path) for name, path in FIXTURE_FILES}
_t = _PARSED["tricky.tex"]
_209 = _PARSED["tricky-209.tex"]
_m = _PARSED["tricky-multi/main.tex"]

TRICKY_ASSERTS = assert_tricky(_t.res, _t.recon, _t.recon_fake) if _t.res else {}
ASSERTS_209 = assert_209(_209.res, _209.recon)
MULTI_ASSERTS = assert_multi(_m.recon) if _m.res else {}

# tricky.tex 的断言全集（docs/10：新增断言只增不减——T14 在 multi，T15/T28 不存在）
TRICKY_IDS = [
    f"T{n:02d}"
    for n in (
        1,
        2,
        3,
        4,
        5,
        6,
        7,
        8,
        9,
        10,
        11,
        12,
        13,
        16,
        17,
        18,
        19,
        20,
        21,
        22,
        23,
        24,
        25,
        26,
        27,
        29,
    )
]
IDS_209 = ["beq_eeq_trap", "documentstyle", "def_macros"]
MULTI_IDS = [
    "T14_input_expanded",
    "T14_include_expanded",
    "T14_nested_input",
    "T14_commented_input",
]
ALL_FIXTURE_NAMES = [n for n, _ in FIXTURE_FILES]


# ---------------------------------------------------------------- 逐 fixture 结构断言


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_parse_ok(name: str) -> None:
    """解析零异常（含 30s 超时护栏）。"""
    p = _PARSED[name]
    assert p.ok, p.error


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_identity_reconstruct(name: str) -> None:
    """identity 重建 == 展平后原文（逐字节）。"""
    p = _PARSED[name]
    assert p.ok, p.error
    status, _ratio, _first = classify_recon(p.flat, p.recon)
    assert status == "identical", f"{status} first_diff_at={_first}"


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_no_placeholder_residue(name: str) -> None:
    """假译文重建后无 ``[[CHUNK_n]]``/``[[TYPE_n]]`` 残留。"""
    p = _PARSED[name]
    assert p.ok, p.error
    assert p.residue_chunk_ph == 0
    assert p.residue_protect_ph == 0


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_validate_result_clean(name: str) -> None:
    """``validate_result`` 结构校验零告警（孤儿 chunk/死 ph/平铺/悬空引用全覆盖）。"""
    p = _PARSED[name]
    assert p.ok, p.error
    assert p.res is not None
    assert validate_result(p.res) == []


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_no_parse_warnings(name: str) -> None:
    """解析零 ``ScanWarning``（unclosed_env/unpaired_dollar 等任一出现即回归）。"""
    p = _PARSED[name]
    assert p.ok, p.error
    assert p.res is not None
    assert p.res.warnings == []


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_no_chunk_leaks(name: str) -> None:
    """可译 chunk 内零泄漏（LEAK_PATTERNS 六类受保护构造）。"""
    p = _PARSED[name]
    assert p.ok, p.error
    assert p.res is not None
    lk = scan_chunks(p.res)
    assert lk["n_leaked"] == 0, lk["examples"]


# ---------------------------------------------------------------- tricky.tex 逐条


@pytest.mark.parametrize("tid", TRICKY_IDS)
def test_tricky(tid: str) -> None:
    """tricky.tex 逐条陷阱断言（断言体在 ``assert_tricky``）。"""
    a = TRICKY_ASSERTS.get(tid)
    assert a is not None, f"missing assertion {tid} (parse failed?)"
    assert a["status"] == "pass", f"{tid} {a['status']}: {a['detail']}"


def test_tricky_matrix_complete() -> None:
    """断言矩阵只增不减：新增 ``@Tnn`` 断言必须登记进 ``TRICKY_IDS``。"""
    assert set(TRICKY_ASSERTS) == set(TRICKY_IDS) | {"_meta"}


def test_tricky_meta_info() -> None:
    """``_meta`` info 行在（残留计数由 ``test_no_placeholder_residue`` 严判）。"""
    assert TRICKY_ASSERTS["_meta"]["status"] == "info"


# ---------------------------------------------------------------- tricky-209 / tricky-multi


def test_209_parse_ok() -> None:
    assert ASSERTS_209["parse_ok"] is True


@pytest.mark.parametrize("aid", IDS_209)
def test_209(aid: str) -> None:
    a = ASSERTS_209[aid]
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


@pytest.mark.parametrize("aid", MULTI_IDS)
def test_multi(aid: str) -> None:
    a = MULTI_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"
