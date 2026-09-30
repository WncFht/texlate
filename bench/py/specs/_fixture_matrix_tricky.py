r"""specs._fixture_matrix_tricky — tricky 系断言叶 (_fixture_matrix 拆分叶).

``assert_tricky`` (tricky.tex T01–T29 单点陷阱 26 条 + ``_meta`` info 行) /
``assert_209`` (tricky-209.tex LaTeX 2.09 旧式组合 3 条 + parse_ok) /
``assert_multi`` (tricky-multi ``\input/\include`` 展平 T14 四条)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from specs import _bootstrap

_bootstrap.ensure()

from specs._fixture_matrix_base import _meta_row, chunks_blob

if TYPE_CHECKING:
    from texlate.latex.model import ScanResult


def assert_tricky(  # 逐条断言平铺即清单（原型同构）
    res: ScanResult, recon: str, recon_fake: str
) -> dict[str, dict[str, str]]:
    """tricky.tex 逐条陷阱断言（原型移植；``_meta`` 是 info 行非断言）。"""
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

    out["_meta"] = _meta_row(res, recon_fake)
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
