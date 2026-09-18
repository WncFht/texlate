r"""B2 fixtures 陷阱断言回归（docs/10 §B2）——spike ``miniscanner_test`` 断言矩阵移植到 ``texlate.latex``。

底材 ``bench/fixtures/*.tex``（入库，逐字节即语义——永不格式化/润色）：

- ``tricky.tex``：T01–T29 单点陷阱 26 条断言 + ``_meta`` 残留计数 info 行；
- ``tricky-209.tex``：LaTeX 2.09 旧式组合 3 条（``\beq/\eeq``、``\documentstyle``、``\def``）+ parse_ok；
- ``tricky-multi/``：T14 ``\input/\include`` 展平 4 条；
- ``xlat-traps.tex``：xlat 契约压力形 4 条（``@Xn``——产品遮蔽口径
  ``[[BIB_n]]``/``\href[[HREF_n]]``/``[[URL_n]]``，与 xlatbench SYNTHETIC S1–S4 同源）；
- ``tricky-w.tex``：W 系列野机制 11 条（``@Wnn`` ↔ corpus_v3 mechanisms.jsonl 台账行，
  infix-over/unbraced-args/arg-next-line/eol-pct-join/range-cite/discretionary/
  pct-comment/comment-macro/spaced-env/enddoc-tail/usepackage-comment）；
- ``tricky-w73/``：``\input{../...}`` 路径逃逸两向断言（gullet C1 openin_any 等价闸）——
  出 main/ 进 shared/（paper 根内，``top_dir=tricky-w73``）照常 resolved inline；
  出 paper 根进 fixtures/（根外）被拒 → ``missing_input``，逃逸句不进 chunks；
- ``tricky-wenc.tex``：W72 混合编码字节件（合法 UTF-8 序列 + 孤立 latin1 字节共存），
  走 ``decode_tex`` 单码选定路径——identity 基准同源改用 ``decode_tex`` 而非
  ``errors="replace"``，断言只锁 latin1 侧 ``café``（单码不可救的 utf8 侧形态留给
  normalize 分档层演进）；
- ``tricky-dollar.tex``：D 系列 dollar 族 10 条（``@Dnn`` ↔ corpus_v3 ``$``-leak
  归因亚型——散文 ``\$`` 转义、``\section``/``\textit``/``\item``/footnote 组参内 ``\$``、
  ``$$..env..`` 区内空行照常配对、孤 ``$$``/孤 ``$`` → CMD ph + ``unpaired_dollar``、
  ``\$`` 与 ``$x$`` 同行混排 CMD+MATH 双路）；
- ``tricky-mask.tex``：M 系列 MASK 族 11 条（``@Mnn`` ↔ W07/W11/W84/W92 机制钉——
  comment env 死块三态行锚、docclass/usepackage 跨行夹注释参、行尾 ``%`` 拼接、
  注释内孤立 ``$`` 不参配对；``env_name_at``/``unescaped_dollar_odd`` 修复面）。

断言函数 ``assert_tricky`` / ``assert_209`` / ``assert_multi`` / ``assert_xlat``
与 bench 跑分器 ``bench/py/fixture_assert.py`` 共享（该脚本直接 import 本模块）。
门槛（docs/10 §B2）：72 条 dict 断言全 ``pass``——``partial`` 在 spike 里是容忍档，
但产品现状全 pass，退化到 partial 即回归，这里按 ``== "pass"`` 严判。
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
from texlate.textutil import DOCCLASS_DECL_RX, decode_tex, mask_tex

if TYPE_CHECKING:
    from types import FrameType

    from texlate.latex.model import Chunk, ScanResult

FIXTURES = Path(__file__).resolve().parent.parent / "bench" / "fixtures"

FIXTURE_FILES = [
    ("tricky.tex", FIXTURES / "tricky.tex"),
    ("tricky-209.tex", FIXTURES / "tricky-209.tex"),
    ("tricky-multi/main.tex", FIXTURES / "tricky-multi" / "main.tex"),
    ("xlat-traps.tex", FIXTURES / "xlat-traps.tex"),
    ("tricky-w.tex", FIXTURES / "tricky-w.tex"),
    ("tricky-w73/main/main.tex", FIXTURES / "tricky-w73" / "main" / "main.tex"),
    ("tricky-wenc.tex", FIXTURES / "tricky-wenc.tex"),
    ("tricky-dollar.tex", FIXTURES / "tricky-dollar.tex"),
    ("tricky-mask.tex", FIXTURES / "tricky-mask.tex"),
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


def run_fixture(
    name: str, path: Path, timeout_s: int = 30, top_dir: Path | None = None
) -> FixtureScan:
    """parse + identity/假译文重建一次（spike ``parse_one``+``rebuild_metrics`` 合体）。"""
    t0 = time.perf_counter()
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout_s)
    try:
        res = parse_file(path, flatten=True, top_dir=top_dir)
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
        decode_tex(path.read_bytes()),
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


def assert_xlat(res: ScanResult | None) -> dict[str, dict[str, str]]:
    """xlat-traps.tex 逐条遮蔽形状断言（``@Xn`` ↔ xlatbench SYNTHETIC S1–S4 同源）。

    钉产品占位符口径：``\\bibitem`` 段首 ``[[BIB_n]]``、``\\href``/``\\url``
    命令本体可见而 url 遮蔽成 ``[[HREF_n]]``/``[[URL_n]]``、url 内 ``%20``
    不当注释吞尾、占位符全局跨类编号。匹配键是占位符种类序列——编号随
    文档顺序漂不算回归，种类/可见构造变了才是。
    """
    if res is None:
        return {"_parse": {"status": "fail", "detail": "parse failed"}}
    out: dict[str, dict[str, str]] = {}

    def kinds(c: Chunk) -> list[str]:
        return [p[2:-2].rsplit("_", 1)[0] for p in PH_RX.findall(c.content)]

    def chk(tid: str, seq: list[str], must: list[str], note: str) -> None:
        c = next((c for c in res.chunks if kinds(c) == seq), None)
        missing = [s for s in must if c is None or s not in c.content]
        if c is not None and not missing:
            out[tid] = {"status": "pass", "detail": note}
        else:
            detail = (
                f"missing={missing} chunk={c.content[:120]!r}"
                if c
                else f"no chunk with kinds={seq}"
            )
            out[tid] = {"status": "fail", "detail": detail}

    chk(
        "@X1-bibitem-lead",
        ["BIB", "HREF", "MATH", "CITE", "CITE"],
        ["\\href[[HREF_", "{introduced the Transformer}", "al.\\ "],
        "\\bibitem 段 -> [[BIB_n]] 引导; \\href url 遮蔽、命令本体与可见文本保留",
    )
    chk(
        "@X2-multikey-cite",
        ["CITE", "MATH", "CITE", "MATH"],
        ["Subsequent analyses"],
        "多 \\cite 与行内公式交错遮蔽",
    )
    chk(
        "@X3-verbatim-pct",
        ["URL", "CITE", "MATH", "REF"],
        ["estimator described in"],
        "\\url -> [[URL_n]]; %20 之后文本存活（未当注释吞掉）",
    )
    chk(
        "@X4-dense-math",
        ["MATH", "MATH", "MATH", "MATH", "MATH", "CITE"],
        ["contraction"],
        "高密度行内公式全遮蔽",
    )
    return out


def assert_w(
    res: ScanResult | None, recon: str, recon_fake: str
) -> dict[str, dict[str, str]]:
    """tricky-w.tex W 系列野机制逐条断言（``@Wnn`` ↔ mechanisms.jsonl 台账行）。"""
    if res is None:
        return {"_meta": {"status": "info", "detail": "parse failed"}}
    chunks = chunks_blob(res)
    out: dict[str, dict[str, str]] = {}

    def no_leak(tid: str, rx: str, note: str) -> None:
        m = re.search(rx, chunks)
        out[tid] = {
            "status": "fail" if m else "pass",
            "detail": f"leaked {m.group(0)!r}" if m else note,
        }

    def absent(tid: str, needle: str, note: str) -> None:
        out[tid] = {
            "status": "pass" if needle not in chunks else "fail",
            "detail": note if needle not in chunks else f"{needle!r} in chunks",
        }

    def present(tid: str, needle: str, note: str) -> None:
        out[tid] = {
            "status": "pass" if needle in chunks else "fail",
            "detail": note if needle in chunks else f"{needle!r} missing",
        }

    # W11 \usepackage 参数跨行夹注释 → preamble literal，包名不进 chunk
    absent("W11", "graphicx", "usepackage 跨行参数仍落 preamble literal")
    # W15 \end{document} 之后真实正文/通信文本 → 不译但 identity 保留
    out["W15"] = {
        "status": "pass"
        if ("referee" not in chunks and "Dear referee" in recon)
        else "fail",
        "detail": "post-\\end{document} prose literal in recon, absent from chunks",
    }
    # W50 \comment{...} 空宏吞块 → 内容不进译文
    absent("W50", "author-todo", "\\comment{...} block swallowed from translation")
    # W67 \begin {env} 标签与括号间插空格
    present("W67", "Spaced env-tag body", "\\begin {abstract} spaced tag parsed")
    # W75 plain-TeX 中缀分式 → 数学 ph 不透明
    no_leak("W75", r"\\over\b|\\buildrel\b", "infix \\over/\\buildrel opaque in math")
    # W82 无花括号单记号参数 → 数学 ph 不透明
    no_leak("W82", r"\\frac|\\sqrt", "unbraced args inside math ph")
    # W83 cs 与必选参数换行分隔 → cite 照常保护
    absent("W83", "vaswani2017", "\\cite<NL>{key} -> [[CITE_n]]")
    # W84 行尾 % 在数学参数内拼接记号 → identity 不破 + ph 完整
    no_leak("W84", r"\\overline|\\chi", "%-join inside math arg keeps ph whole")
    # W90 \cite{a-b} 区间当键 → key 不透出
    absent("W90", "a-b", "range-as-key cite stays in ph")
    # W91 可译文本内 \- 手工断词 → 原样透传
    present("W91", "dis\\-cretionary", "\\- literal passthrough in translatable text")
    # W92 注释内 $ \cite{ghost} \begin{equation} → 注释不可见
    absent("W92", "ghost", "comment body invisible to scanner")

    res_chunk = len(CHUNK_RX.findall(recon_fake))
    res_prot = len(PH_RX.findall(recon_fake))
    out["_meta"] = {
        "status": "info",
        "detail": f"chunks={len(res.chunks)} ph={len(res.ph_map)} "
        f"residue_chunk={res_chunk} residue_prot={res_prot}",
    }
    return out


def assert_w73(res: ScanResult | None) -> dict[str, dict[str, str]]:
    """tricky-w73 ``\\input{../}`` 路径逃逸两向断言（C1 根内约束闸）。"""
    chunks = chunks_blob(res) if res else ""
    warns = {w.kind for w in res.warnings} if res else set()
    denied = "missing_input" in warns and "Outside-root sentence" not in chunks
    return {
        "W73_within_paper_escape": {
            "status": "pass" if "Shared-file sentence" in chunks else "fail",
            "detail": "../shared/defs.tex（出 main/ 未出 paper 根）resolved inline",
        },
        "W73_beyond_root_escape": {
            "status": "pass" if denied else "fail",
            "detail": "../../escape-outside.tex（出 paper 根）→ missing_input 拒读",
        },
    }


def assert_wenc(res: ScanResult | None) -> dict[str, dict[str, str]]:
    """tricky-wenc 混合编码断言（只锁 latin1 侧——单码选定下 utf8 侧 mojibake 留档）。"""
    chunks = chunks_blob(res) if res else ""
    return {
        "W72_mixed_decoded": {
            "status": "pass" if "café" in chunks else "fail",
            "detail": "decode_tex 单码选定 latin1 → café 存活（mixed 分档归 normalize 层）",
        }
    }


def assert_dollar(
    res: ScanResult | None, recon: str, recon_fake: str
) -> dict[str, dict[str, str]]:
    """tricky-dollar.tex D 系列逐条断言（corpus_v3 ``$``-leak 归因亚型钉）。"""
    if res is None:
        return {"_meta": {"status": "info", "detail": "parse failed"}}
    chunks = chunks_blob(res)
    out: dict[str, dict[str, str]] = {}

    def all_re(tid: str, rxs: tuple[str, ...], note: str) -> None:
        missing = [rx for rx in rxs if not re.search(rx, chunks)]
        out[tid] = {
            "status": "fail" if missing else "pass",
            "detail": f"missing {missing} in chunks" if missing else note,
        }

    def ph_roundtrip(tid: str, rx: str, needle: str, note: str) -> None:
        ok = re.search(rx, chunks) and needle in recon
        out[tid] = {
            "status": "pass" if ok else "fail",
            "detail": note
            if ok
            else f"rx={rx!r} in chunks / {needle!r} in recon: false",
        }

    # D01 散文内 \$ → CMD ph（corpus 主族：\$25 / `\$AAPL' / US\$240B）
    all_re(
        "D01",
        (
            r"\[\[CMD_\d+\]\]25 ",
            r"`\[\[CMD_\d+\]\]AAPL'",
            r"US\[\[CMD_\d+\]\]240B",
        ),
        "prose \\$ escapes -> [[CMD_n]]",
    )
    # D02 \section{} 组参内 \$ → group surface CMD ph
    all_re(
        "D02",
        (r"The \[\[CMD_\d+\]\]5 problem and its \[\[CMD_\d+\]\]10 variants",),
        "section-arg \\$ -> CMD ph",
    )
    # D03 \textit 组参内 \$（corpus \textit{\$KEEP} 形）
    all_re(
        "D03",
        (r"\\textit\{\[\[CMD_\d+\]\]KEEP\}", r"\\textit\{\[\[CMD_\d+\]\]DELETE\}"),
        "textit-arg \\$ -> CMD ph",
    )
    # D04 \item 文本内 \$（corpus 2009.10990 pmpm 形）
    all_re(
        "D04",
        (r"equals \[\[CMD_\d+\]\]1 million", r"cost \[\[CMD_\d+\]\]100,000"),
        "item-text \\$ -> CMD ph",
    )
    # D05 footnote 内 \href 文本参 \$（corpus 2211.04509 形）
    all_re(
        "D05",
        (r"the US \[\[CMD_\d+\]\]326 Billion",),
        "footnote href-arg \\$ -> CMD ph",
    )
    # D06 $$..\begin{array} 区内空行..$$：env 容忍 → 单条 MATH ph 照常配对
    ph_roundtrip(
        "D06",
        r"We obtain \[\[MATH_\d+\]\] as well as",
        "$$\n   M =",
        "$$..array(blank-lines)..$$ paired -> [[MATH_n]]",
    )
    # D07 $$..<未展开宏闭符 \ek>+\par → 孤 $$ -> CMD ph + unpaired_dollar
    ph_roundtrip(
        "D07",
        r"Weaker condition\n?\s*\[\[CMD_\d+\]\]",
        "$$\n\\nabla",
        "stranded $$ -> CMD ph, $$ survives in recon",
    )
    # D08 散文裸单 $ 不配对 → CMD ph
    ph_roundtrip(
        "D08",
        r"25 \[\[CMD_\d+\]\] per unit",
        "25 $ per unit",
        "bare $ -> CMD ph, literal $ in recon",
    )
    # D09 散文裸 $$ 不配对 → CMD ph
    ph_roundtrip(
        "D09",
        r"before\. \[\[CMD_\d+\]\] broken",
        "$$ broken math",
        "bare $$ -> CMD ph, literal $$ in recon",
    )
    # D10 \$ 与 $x$ 同行混排 → CMD + MATH 两路并行
    all_re(
        "D10",
        (
            r"Paid \[\[CMD_\d+\]\]5 for \[\[MATH_\d+\]\] tokens and \[\[CMD_\d+\]\]10 more",
        ),
        "mixed \\$ + $x$ -> CMD+MATH dual track",
    )

    res_chunk = len(CHUNK_RX.findall(recon_fake))
    res_prot = len(PH_RX.findall(recon_fake))
    out["_meta"] = {
        "status": "info",
        "detail": f"chunks={len(res.chunks)} ph={len(res.ph_map)} "
        f"residue_chunk={res_chunk} residue_prot={res_prot}",
    }
    return out


def assert_mask(
    res: ScanResult | None, recon: str, recon_fake: str
) -> dict[str, dict[str, str]]:
    """tricky-mask.tex M 系列逐条断言（W07/W11/W84/W92 机制钉）。"""
    if res is None:
        return {"_meta": {"status": "info", "detail": "parse failed"}}
    chunks = chunks_blob(res)
    out: dict[str, dict[str, str]] = {}

    def all_re(tid: str, rxs: tuple[str, ...], note: str) -> None:
        missing = [rx for rx in rxs if not re.search(rx, chunks)]
        out[tid] = {
            "status": "fail" if missing else "pass",
            "detail": f"missing {missing} in chunks" if missing else note,
        }

    def ph_roundtrip(tid: str, rx: str, needle: str, note: str) -> None:
        ok = re.search(rx, chunks) and needle in recon
        out[tid] = {
            "status": "pass" if ok else "fail",
            "detail": note
            if ok
            else f"rx={rx!r} in chunks / {needle!r} in recon: false",
        }

    # M01 W92 注释尾孤立 $ 不参配对（hep-ph/9910434 %$ 形）——footnote 参内
    # $^{\dag}$ 正常配对，尾随 %$ 的 $ 不抢不泄
    ph_roundtrip(
        "M01",
        r"Published version\.\[\[MATH_\d+\]\]",
        r"$^{\dag}$",
        "comment-trailing isolated $ ignored, dagger math paired",
    )
    # M02 W92+W84 数学体内注释 $ 不计债——两枚 MATH 各自配对、零 debt_repair
    ok = re.search(
        r"Before \[\[MATH_\d+\]\] middle After \[\[MATH_\d+\]\] tail\.", chunks
    ) and not any(w.kind == "debt_repair" for w in res.warnings)
    out["M02"] = {
        "status": "pass" if ok else "fail",
        "detail": "math-body comment $ excluded from debt (unescaped_dollar_odd)"
        if ok
        else "debt_repair fired or math pairing broken",
    }
    # M03 W84 $%$ 跨行拼接（nucl-th/9703052）——单条 MATH 跨注释闭合
    ph_roundtrip(
        "M03",
        r"The shell \[\[MATH_\d+\]\] orbitals",
        "$%\n(N) $",
        "$..%<NL>..$ joined into one MATH",
    )
    # M04 W84 \overline{%<NL>\chi} 参内注释拼接——arg 边界跳注释
    ph_roundtrip(
        "M04",
        r"We write \[\[MATH_\d+\]\] for the averaged",
        "$\\overline{%\n\\chi }$",
        "\\overline{%<NL>\\chi} arg-intact MATH",
    )
    # M05 W84 文本组内注释拼接：Mouth 吃注释 → 参数一体单 chunk
    all_re(
        "M05",
        (r"A braced \\textbf\{grouped  word\} stays one argument\.",),
        "comment-joined textbf arg stays one chunk",
    )
    # M06 W07 comment env 死块——死块内 section/math 不进 chunk
    ok = re.search(r"Live paragraph resumes here\.", chunks) and not re.search(
        r"Dead Section|Dead body", chunks
    )
    out["M06"] = {
        "status": "pass" if ok else "fail",
        "detail": "comment env body fully dead"
        if ok
        else "dead body leaked into chunks",
    }
    # M07 W07 行内 x\end{comment} 不终结（comment.sty 行锚比对）
    ok = re.search(r"Live after the dead block\.", chunks) and not re.search(
        r"dead alpha|dead beta", chunks
    )
    out["M07"] = {
        "status": "pass" if ok else "fail",
        "detail": "mid-line \\end{comment} rejected"
        if ok
        else "mid-line end closed env",
    }
    # M08 W07 \end{comment}% 尾随不终结
    ok = re.search(r"Live after the tricky close\.", chunks) and not re.search(
        r"dead one|dead two", chunks
    )
    out["M08"] = {
        "status": "pass" if ok else "fail",
        "detail": "trailing-comment \\end{comment} rejected"
        if ok
        else "trailing-comment end closed env",
    }
    # M09 W11 docclass/usepackage 跨行夹注释参——DECL_TAIL 在遮盖视图整表
    # 捕获（recon == 原文字节，mask 后 %preprint 成空白项被 clean_decl_name 拒）
    dc = DOCCLASS_DECL_RX.search(mask_tex(recon))
    opts = (dc.group(2) or "") if dc else ""
    opt_names = [o.strip() for o in opts.split(",") if o.strip()]
    ok = (
        dc is not None
        and dc.group(3).strip() == "article"
        and {"a4paper", "12pt"} <= set(opt_names)
        and "preprint" not in opt_names
        and "\\usepackage{amsmath, % math tools\n comment}" in recon
    )
    out["M09"] = {
        "status": "pass" if ok else "fail",
        "detail": f"decl tail captures multi-line opts {opt_names}"
        if ok
        else f"dc={dc and dc.groups()} opts={opt_names}",
    }
    # M10 W11 泛化 \begin{%<NL>comment}——env_name_at 剔注释得名 comment
    # → 死块 [[VERB]] 整段保护，两臂收敛同形
    ok = re.search(r"Live after commented env name\.", chunks) and not re.search(
        r"dead gamma|still dead delta", chunks
    )
    out["M10"] = {
        "status": "pass" if ok else "fail",
        "detail": "commented env name -> DEAD_ENVS hit, body protected"
        if ok
        else "dead body leaked or live tail lost",
    }
    # M11 W92 整行注释内孤立 $ 不参配对——$z$ 正常配对
    all_re(
        "M11",
        (r"Live tail \[\[MATH_\d+\]\] closes the file body\.",),
        "full-line comment $ ignored",
    )

    res_chunk = len(CHUNK_RX.findall(recon_fake))
    res_prot = len(PH_RX.findall(recon_fake))
    out["_meta"] = {
        "status": "info",
        "detail": f"chunks={len(res.chunks)} ph={len(res.ph_map)} "
        f"residue_chunk={res_chunk} residue_prot={res_prot}",
    }
    return out


# ---------------------------------------------------------------- 模块级测量（7 个小文件，ms 级）

#: 需要非缺省 ``top_dir`` 的 fixture（w73：paper 根 = tricky-w73/，``../shared``
#: 在根内可解析、``../../escape-outside`` 出根被 C1 闸拒）。
_FIXTURE_TOPDIR: dict[str, Path] = {
    "tricky-w73/main/main.tex": FIXTURES / "tricky-w73",
}

_PARSED = {
    name: run_fixture(name, path, top_dir=_FIXTURE_TOPDIR.get(name))
    for name, path in FIXTURE_FILES
}
_t = _PARSED["tricky.tex"]
_209 = _PARSED["tricky-209.tex"]
_m = _PARSED["tricky-multi/main.tex"]
_x = _PARSED["xlat-traps.tex"]
_w = _PARSED["tricky-w.tex"]
_w73 = _PARSED["tricky-w73/main/main.tex"]
_wenc = _PARSED["tricky-wenc.tex"]
_d = _PARSED["tricky-dollar.tex"]
_mk = _PARSED["tricky-mask.tex"]

TRICKY_ASSERTS = assert_tricky(_t.res, _t.recon, _t.recon_fake) if _t.res else {}
ASSERTS_209 = assert_209(_209.res, _209.recon)
MULTI_ASSERTS = assert_multi(_m.recon) if _m.res else {}
XLAT_ASSERTS = assert_xlat(_x.res)
W_ASSERTS = assert_w(_w.res, _w.recon, _w.recon_fake) if _w.res else {}
W73_ASSERTS = assert_w73(_w73.res) if _w73.res else {}
WENC_ASSERTS = assert_wenc(_wenc.res) if _wenc.res else {}
DOLLAR_ASSERTS = assert_dollar(_d.res, _d.recon, _d.recon_fake) if _d.res else {}
MASK_ASSERTS = assert_mask(_mk.res, _mk.recon, _mk.recon_fake) if _mk.res else {}

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
XLAT_IDS = [
    "@X1-bibitem-lead",
    "@X2-multikey-cite",
    "@X3-verbatim-pct",
    "@X4-dense-math",
]
# tricky-w.tex 的断言全集（Wnn ↔ bench/corpus_v3/mechanisms.jsonl 台账行）
W_IDS = [
    "W11",
    "W15",
    "W50",
    "W67",
    "W75",
    "W82",
    "W83",
    "W84",
    "W90",
    "W91",
    "W92",
]
W73_IDS = [
    "W73_within_paper_escape",
    "W73_beyond_root_escape",
]
WENC_IDS = ["W72_mixed_decoded"]
# tricky-dollar.tex 的断言全集（@Dnn ↔ corpus_v3 $-leak 归因亚型钉）
D_IDS = [f"D{n:02d}" for n in range(1, 11)]
# tricky-mask.tex 的断言全集（@Mnn ↔ W07/W11/W84/W92 机制钉）
M_IDS = [f"M{n:02d}" for n in range(1, 12)]
ALL_FIXTURE_NAMES = [n for n, _ in FIXTURE_FILES]


# ---------------------------------------------------------------- 逐 fixture 结构断言


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_parse_ok(name: str) -> None:
    """解析零异常（含 30s 超时护栏）。"""
    p = _PARSED[name]
    assert p.ok, p.error


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_identity_reconstruct(name: str) -> None:
    """identity 重建 == ``res.vtex``（逐字节）。

    v2 的 identity 基准是 vtex（展开机产出文本），不是 flatten 输出——
    cs 后空白被 tokenizer 吞、``\\if`` 死支不落地等差异属产品语义。
    """
    p = _PARSED[name]
    assert p.ok, p.error
    assert p.res is not None
    status, _ratio, _first = classify_recon(p.res.vtex, p.recon)
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


#: 各 fixture 期望的 warning kind 集（缺省 = 零 warning）。w73 的
#: ``missing_input`` 是 C1 闸拒根外逃逸的断言面本身，由 ``test_w73`` 两向锁定。
#: 多重集口径（sorted 精确比对）——tricky-dollar 的 D07/D08/D09 三个孤 ``$$``/``$``
#: 各产一条 ``unpaired_dollar``，期望值必须列足 3 条。
_EXPECTED_WARN_KINDS: dict[str, set[str] | list[str]] = {
    "tricky-w73/main/main.tex": {"missing_input"},
    "tricky-dollar.tex": [
        "unpaired_dollar",
        "unpaired_dollar",
        "unpaired_dollar",
    ],
}


@pytest.mark.parametrize("name", ALL_FIXTURE_NAMES)
def test_no_parse_warnings(name: str) -> None:
    """解析 ``ScanWarning`` 精确匹配期望集（缺省零——unclosed_env 等任一即回归）。"""
    p = _PARSED[name]
    assert p.ok, p.error
    assert p.res is not None
    kinds = [w.kind for w in p.res.warnings]
    assert sorted(kinds) == sorted(_EXPECTED_WARN_KINDS.get(name, set()))


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


# ---------------------------------------------------------------- xlat-traps 逐条


@pytest.mark.parametrize("aid", XLAT_IDS)
def test_xlat(aid: str) -> None:
    """xlat-traps.tex 逐条遮蔽形状断言（断言体在 ``assert_xlat``）。"""
    a = XLAT_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


def test_xlat_matrix_complete() -> None:
    """断言矩阵只增不减：新增 ``@Xn`` 断言必须登记进 ``XLAT_IDS``。"""
    assert set(XLAT_ASSERTS) == set(XLAT_IDS)


# ---------------------------------------------------------------- tricky-w / w73 / wenc 逐条


@pytest.mark.parametrize("aid", W_IDS)
def test_w(aid: str) -> None:
    """tricky-w.tex W 系列野机制逐条断言（断言体在 ``assert_w``）。"""
    a = W_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


def test_w_matrix_complete() -> None:
    """``@Wnn`` 断言与 ``W_IDS`` 登记一致（只增不减口径同 tricky）。"""
    assert set(W_ASSERTS) == set(W_IDS) | {"_meta"}


@pytest.mark.parametrize("aid", W73_IDS)
def test_w73(aid: str) -> None:
    """tricky-w73 ``\\input{../}`` 路径逃逸断言。"""
    a = W73_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


@pytest.mark.parametrize("aid", WENC_IDS)
def test_wenc(aid: str) -> None:
    """tricky-wenc 混合编码字节件断言。"""
    a = WENC_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


# ---------------------------------------------------------------- tricky-dollar 逐条


@pytest.mark.parametrize("aid", D_IDS)
def test_dollar(aid: str) -> None:
    """tricky-dollar.tex D 系列 ``$``-leak 亚型逐条断言（断言体在 ``assert_dollar``）。"""
    a = DOLLAR_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


def test_dollar_matrix_complete() -> None:
    """``@Dnn`` 断言与 ``D_IDS`` 登记一致（只增不减口径同 tricky/w）。"""
    assert set(DOLLAR_ASSERTS) == set(D_IDS) | {"_meta"}


# ---------------------------------------------------------------- tricky-mask 逐条


@pytest.mark.parametrize("aid", M_IDS)
def test_mask(aid: str) -> None:
    """tricky-mask.tex M 系列 MASK 族逐条断言（断言体在 ``assert_mask``）。"""
    a = MASK_ASSERTS.get(aid)
    assert a is not None, f"missing assertion {aid} (parse failed?)"
    assert a["status"] == "pass", f"{aid} {a['status']}: {a['detail']}"


def test_mask_matrix_complete() -> None:
    """``@Mnn`` 断言与 ``M_IDS`` 登记一致（只增不减口径同 tricky/w/dollar）。"""
    assert set(MASK_ASSERTS) == set(M_IDS) | {"_meta"}
