r"""specs._fixture_matrix.dm — dollar/mask 系断言叶 (_fixture_matrix 拆分叶).

``assert_dollar`` (tricky-dollar.tex ``@Dnn`` ``$``-leak 归因亚型 10 条) /
``assert_mask`` (tricky-mask.tex ``@Mnn`` ↔ W07/W11/W84/W92 机制钉 11 条)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from specs import _bootstrap

_bootstrap.ensure()

from specs._fixture_matrix.base import (
    _all_re,
    _meta_row,
    _ph_roundtrip,
    chunks_blob,
)
from texlate.textutil import DOCCLASS_DECL_RX, mask_tex

if TYPE_CHECKING:
    from texlate.latex.model import ScanResult


def assert_dollar(
    res: ScanResult | None, recon: str, recon_fake: str
) -> dict[str, dict[str, str]]:
    """tricky-dollar.tex D 系列逐条断言（corpus ``$``-leak 归因亚型钉）。"""
    if res is None:
        return {"_meta": {"status": "info", "detail": "parse failed"}}
    chunks = chunks_blob(res)
    out: dict[str, dict[str, str]] = {}

    # D01 散文内 \$ → CMD ph（corpus 主族：\$25 / `\$AAPL' / US\$240B）
    out["D01"] = _all_re(
        chunks,
        (
            r"\[\[CMD_\d+\]\]25 ",
            r"`\[\[CMD_\d+\]\]AAPL'",
            r"US\[\[CMD_\d+\]\]240B",
        ),
        "prose \\$ escapes -> [[CMD_n]]",
    )
    # D02 \section{} 组参内 \$ → group surface CMD ph
    out["D02"] = _all_re(
        chunks,
        (r"The \[\[CMD_\d+\]\]5 problem and its \[\[CMD_\d+\]\]10 variants",),
        "section-arg \\$ -> CMD ph",
    )
    # D03 \textit 组参内 \$（corpus \textit{\$KEEP} 形）
    out["D03"] = _all_re(
        chunks,
        (r"\\textit\{\[\[CMD_\d+\]\]KEEP\}", r"\\textit\{\[\[CMD_\d+\]\]DELETE\}"),
        "textit-arg \\$ -> CMD ph",
    )
    # D04 \item 文本内 \$（corpus 2009.10990 pmpm 形）
    out["D04"] = _all_re(
        chunks,
        (r"equals \[\[CMD_\d+\]\]1 million", r"cost \[\[CMD_\d+\]\]100,000"),
        "item-text \\$ -> CMD ph",
    )
    # D05 footnote 内 \href 文本参 \$（corpus 2211.04509 形）
    out["D05"] = _all_re(
        chunks,
        (r"the US \[\[CMD_\d+\]\]326 Billion",),
        "footnote href-arg \\$ -> CMD ph",
    )
    # D06 $$..\begin{array} 区内空行..$$：env 容忍 → 单条 MATH ph 照常配对
    out["D06"] = _ph_roundtrip(
        chunks,
        recon,
        r"We obtain \[\[MATH_\d+\]\] as well as",
        "$$\n   M =",
        "$$..array(blank-lines)..$$ paired -> [[MATH_n]]",
    )
    # D07 $$..<未展开宏闭符 \ek>+\par → 孤 $$ -> CMD ph + unpaired_dollar
    out["D07"] = _ph_roundtrip(
        chunks,
        recon,
        r"Weaker condition\n?\s*\[\[CMD_\d+\]\]",
        "$$\n\\nabla",
        "stranded $$ -> CMD ph, $$ survives in recon",
    )
    # D08 散文裸单 $ 不配对 → CMD ph
    out["D08"] = _ph_roundtrip(
        chunks,
        recon,
        r"25 \[\[CMD_\d+\]\] per unit",
        "25 $ per unit",
        "bare $ -> CMD ph, literal $ in recon",
    )
    # D09 散文裸 $$ 不配对 → CMD ph
    out["D09"] = _ph_roundtrip(
        chunks,
        recon,
        r"before\. \[\[CMD_\d+\]\] broken",
        "$$ broken math",
        "bare $$ -> CMD ph, literal $$ in recon",
    )
    # D10 \$ 与 $x$ 同行混排 → CMD + MATH 两路并行
    out["D10"] = _all_re(
        chunks,
        (
            r"Paid \[\[CMD_\d+\]\]5 for \[\[MATH_\d+\]\] tokens and \[\[CMD_\d+\]\]10 more",
        ),
        "mixed \\$ + $x$ -> CMD+MATH dual track",
    )

    out["_meta"] = _meta_row(res, recon_fake)
    return out


def assert_mask(
    res: ScanResult | None, recon: str, recon_fake: str
) -> dict[str, dict[str, str]]:
    """tricky-mask.tex M 系列逐条断言（W07/W11/W84/W92 机制钉）。"""
    if res is None:
        return {"_meta": {"status": "info", "detail": "parse failed"}}
    chunks = chunks_blob(res)
    out: dict[str, dict[str, str]] = {}

    # M01 W92 注释尾孤立 $ 不参配对（hep-ph/9910434 %$ 形）——footnote 参内
    # $^{\dag}$ 正常配对，尾随 %$ 的 $ 不抢不泄
    out["M01"] = _ph_roundtrip(
        chunks,
        recon,
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
    out["M03"] = _ph_roundtrip(
        chunks,
        recon,
        r"The shell \[\[MATH_\d+\]\] orbitals",
        "$%\n(N) $",
        "$..%<NL>..$ joined into one MATH",
    )
    # M04 W84 \overline{%<NL>\chi} 参内注释拼接——arg 边界跳注释
    out["M04"] = _ph_roundtrip(
        chunks,
        recon,
        r"We write \[\[MATH_\d+\]\] for the averaged",
        "$\\overline{%\n\\chi }$",
        "\\overline{%<NL>\\chi} arg-intact MATH",
    )
    # M05 W84 文本组内注释拼接：Mouth 吃注释 → 参数一体单 chunk
    out["M05"] = _all_re(
        chunks,
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
    out["M11"] = _all_re(
        chunks,
        (r"Live tail \[\[MATH_\d+\]\] closes the file body\.",),
        "full-line comment $ ignored",
    )

    out["_meta"] = _meta_row(res, recon_fake)
    return out
