r"""specs._fixture_matrix.xw — xlat/W 系断言叶 (_fixture_matrix 拆分叶).

``assert_xlat`` (xlat-traps.tex ``@Xn`` 遮蔽形状 4 条，xlatbench SYNTHETIC
S1–S4 同源钉) / ``assert_w`` (tricky-w.tex ``@Wnn`` 野机制 11 条) /
``assert_w73`` (``\input{../}`` 路径逃逸两向) / ``assert_wenc`` (W72
混合编码字节件)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from specs import _bootstrap

_bootstrap.ensure()

from specs._fixture_matrix.base import _meta_row, chunks_blob
from texlate.latex.placeholder import PH_RX

if TYPE_CHECKING:
    from texlate.latex.model import Chunk, ScanResult


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

    out["_meta"] = _meta_row(res, recon_fake)
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
