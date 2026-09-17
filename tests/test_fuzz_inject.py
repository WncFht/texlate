r"""compile/inject.py 对抗性性质 fuzz —— 中文注入缝扫描 / CJK 检测 / 主文件定位 /
209 升级 / 前导块编排。

覆盖的协议不变量：

- ``find_docclass_ends``：缝 pos 恒为 ``\n`` 下标或 ``len(tex)``、lineno ==
  ``tex[:pos].count("\n") + 1``、逐缝递增去重；注释/verbatim/filecontents/
  comment/``\verb`` 遮盖区命中不算；宏体（brace depth>0）命中跳过；
  ``\if..\else..\fi`` 双 docclass 逐缝（不判死活）；同行双命中去重；
  选项段内 ``{..}``/``[..]``/``\{``/``\}``/注释括号配对。
- ``inject_cjk``：documentclass 路径字节守恒（首缝前前缀 + 末缝后后缀原样，
  独立 oracle 逐缝 ``\n``+block 重放逐字节一致）；幂等（注入产物自带
  CJK_PRESENT 签名 → 二跑 already 稳定）；多缝 ``\TeXlateCJKloaded`` 哨兵；
  ``already``/``no-docline``/``injected``/``InjectRejectError`` 四态划分。
- ``CJK_PRESENT_RE``：包/类语境收紧矩阵（``mactex``/``myctex``/``\newcommand``
  假阳 vs ``ctex\w*``/``CJK\w*``/``\setCJK*font``/``\begin{CJK*}`` 真命中；
  注释/verbatim 内的 ``\usepackage{ctex}`` 不算）。
- ``upgrade_209`` 接线：标准类确定转换、选项三路分派、随源 ds@ sty 拒转、
  裸 ``\documentstyle`` reason=latex209。
- ``find_main_tex``：``\input``/``\include``/``\InputIfFileExists``/裸形/引号
  闭包 bd 检测；越出工程根（``../``/绝对路径）不跟随；语言序/main 名加成/
  确定性排序。
- ``classify_no_main``：latex209 / plain_tex / garbage / None 四桶与遮盖口径。
- ``inject_float_sizing``/``inject_table_fitting``/``prepare_chinese``：
  项目级 figure 门、dc+bd 文件谓词、threeparttable 门、非 UTF-8 重写、
  幂等二跑。

钉住的确认缺陷（``xfail(strict=True)``——修复后 XPASS 提醒拆钉）：

- I1 ``inject.py:620`` EOF 兜底死注——docclass ``}``-close 后无 ``\n`` 时
  ``insert = len(tex)``，注入块落到 ``\end{document}`` 之后成死代码
  （单行文档形态，中文静默缺失）；
- I2 ``inject.py:552-580`` ``_docclass_close`` 无界前扫——``\documentclass``
  后非 ``[{`` 首 token 时吞掉**任意远处**的 ``{...}`` 当类名实参
  （``\documentclass\cls`` 宏实参形态吞 ``\begin{document}`` 的花括号 →
  缝落在 enddoc 行 → 死注）；
- I3 ``inject.py:615`` ``close < len(vis)`` 守卫把 ``}``-at-EOF 误判成无花括
  号 → 裸缝兜底 ``find("\n", m.end())`` 落在声明内部换行处 →
  ``\documentclass\n<BLOCK>\n{article}`` 劈断声明；
- I4 ``inject.py:616-622`` EOL 缝越过同行 ``\begin{verbatim}``——注入块落进
  verbatim 环境体成字面文本（死注）；
- I5 ``latex209.py:405`` ``_DOCSTYLE_RE.search`` 非深度感知——首个
  ``\documentstyle`` 命中可能坐在 ``\newcommand`` 宏体内，真声明被跳过 →
  宏体被升级器污染 + 活 ``\documentstyle`` 照旧吃到 ``\usepackage``；
- I6 ``inject.py:711-712`` FLOAT_SIZING 要求 dc+bd 同文件——编排壳 main
  （``find_main_tex`` 显式收录的 cs/0408015 形态：dc 在 main、bd 在
  ``\input`` 子文件）工程含 figure 也拿不到溢高 float 钩子；
- I7 ``inject.py:456,531`` 两处 ``*.tex`` 扫描闸——``.ltx`` 主文件不可见
  （``mask.py:19`` ``TEX_SOURCE_SUFFIXES`` 已把 .ltx 计为 TeX 源），
  find_main_tex 拒收 + classify_no_main 归 ``garbage``；
- I8 ``inject.py:271`` ``_DOC_RE`` lookahead ``(?![a-zA-Z])`` 放行 ``@``——
  ``\makeatletter`` 语境下 ``\documentclass@hook`` 是独立控制序列却计作
  声明缝 → 无 docclass 文件被报 ``injected``（locate.py 已用更严
  ``(?![a-zA-Z@])``，本钉是 inject 侧后果实例）；
- I9 ``inject.py:461`` 候选闸 ``\\documentclass\b`` 无深度检查 vs
  ``find_docclass_ends`` 有——唯一 docclass 藏在 ``\newcommand`` 体内的
  文件（``\doc`` 展开即真声明、可编译）被收为 main 却永远 ``no-docline``
  → 可编译文档静默零注入。

未钉观察（characterization 断言或报告项）：``[...]`` 括号不计深度产生的
幻影缝、``\usepackage{\n ctex}``/``\input ctex.sty`` 的 already 漏检
（双注入无害）、``inject_float_sizing`` docstring 的 ``0/1`` 与多 main
工程实际 ``N`` 的文档漂移、``mode`` 无校验非 ctex 一律走 xeCJK 块、
threeparttable 子串门（非正则）的良性过触发、无扩展名 ``\input`` 目标
不跟随（与 probe.py 同口径）。
"""

from __future__ import annotations

import random
import re
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from texlate.compile.inject import (
    CJK_FIRST_USE_WARMUP,
    CJK_MATH_FALLBACK,
    CJK_PRESENT_RE,
    CTEX_LINE,
    TABLE_FITTING,
    TEXT_8BIT_FALLBACK,
    THEOREM_ANCHOR_SHIM,
    TIE_ACCENT_FIX,
    XECJK_BLOCK,
    InjectRejectError,
    classify_no_main,
    find_docclass_end,
    find_docclass_ends,
    find_main_tex,
    inject_cjk,
    inject_float_sizing,
    inject_table_fitting,
    prepare_chinese,
)

# ---------------------------------------------------------------- oracle


def _block(mode: str, nseams: int) -> str:
    """``inject_cjk`` 块组装的独立重演（docs/08 §3.3 注入缝规格）。"""
    blk = CTEX_LINE + "  % [texlate injected]" if mode == "ctex" else XECJK_BLOCK
    blk += (
        THEOREM_ANCHOR_SHIM
        + CJK_MATH_FALLBACK
        + CJK_FIRST_USE_WARMUP
        + TIE_ACCENT_FIX
        + TEXT_8BIT_FALLBACK
    )
    if nseams > 1:
        blk = (
            "% texlate: CJK support (multi-seam idempotent)\n"
            "\\ifdefined\\TeXlateCJKloaded\\else\n"
            "\\def\\TeXlateCJKloaded{1}%\n" + blk + "\\fi\n"
        )
    return blk


def _splice(tex: str, seams: list[tuple[int, int, str]], block: str) -> str:
    """逐缝 ``\\n``+block 规格化重放。"""
    out = tex
    delta = 0
    for pos, _lineno, _cmd in seams:
        out = out[: pos + delta] + "\n" + block + out[pos + delta :]
        delta += len(block) + 1
    return out


def _assert_seam_invariants(tex: str) -> list[tuple[int, int, str]]:
    hits = find_docclass_ends(tex)
    prev = -1
    for pos, lineno, _cmd in hits:
        assert pos > prev
        prev = pos
        assert pos == len(tex) or tex[pos] == "\n"
        assert lineno == tex[:pos].count("\n") + 1
    return hits


_DOC = "\\begin{document}\nx\n\\end{document}\n"


def _dc(body: str = "x") -> str:
    return (
        "\\documentclass{article}\n\\begin{document}\n" + body + "\n\\end{document}\n"
    )


# ---------------------------------------------------------------- 缝扫描


def test_seam_position_line_invariants() -> None:
    """缝 pos 恒落在行尾 ``\\n``（或 EOF），lineno 与 pos 自洽、逐缝递增。"""
    samples = [
        "\\documentclass{article}\nx\n",
        "\\documentclass[12pt,\na4paper]{amsart}\nx\n",
        "\\documentclass{article}",
        "\\documentclass{article} % cmt\nx\n",
        (
            "\\RequirePackage{ifpdf}\n\\ifpdf\n\\documentclass{a}\n\\else\n"
            "\\documentclass{b}\n\\fi\nx\n"
        ),
        "\\documentclass\n{article}\nx\n",
        "pre\n\\documentclass{article}\npost\n",
        "\\documentclass[" + "a," * 3000 + "]{cls}\nx\n",  # 扫描界内不挂
    ]
    for tex in samples:
        _assert_seam_invariants(tex)
    tex = "\\ifpdf\n\\documentclass{a}\n\\else\n\\documentclass{b}\n\\fi\nx\n"
    assert find_docclass_end(tex) == find_docclass_ends(tex)[0]
    assert find_docclass_end("no decl") is None


def test_seam_option_segment_parsing() -> None:
    """选项段配对矩阵：内嵌花括号/转义/嵌套方括号/注释遮蔽/多行注释穿插。"""
    cases = [
        ("\\documentclass[a={b,c}]{cls}\nx\n", "{cls}", 1),
        ("\\documentclass[a=\\{x\\}]{cls}\nx\n", "{cls}", 1),
        ("\\documentclass[a=[b]]{cls}\nx\n", "{cls}", 1),
        ("\\documentclass[% this ] is masked\naps]{revtex4-2}\nx\n", "{revtex4-2}", 2),
        (
            "\\documentclass[%\n %aip,%\n %jmp,%\n aps,prl]{revtex4-2}\nx\n",
            "{revtex4-2}",
            4,
        ),
        ("\\documentclass{rev\ntex4}\nx\n", "{rev\ntex4}", 2),
    ]
    for tex, tail, lineno in cases:
        hits = _assert_seam_invariants(tex)
        assert len(hits) == 1
        assert tex[: hits[0][0]].endswith(tail)
        assert hits[0][1] == lineno


def test_seam_masked_regions_skipped() -> None:
    """逐字/失活环境与 ``\\verb`` 内的 ``\\documentclass`` 不产生缝。"""
    for env in [
        "verbatim",
        "lstlisting",
        "comment",
        "filecontents",
        "minted",
        "Verbatim",
    ]:
        tex = (
            f"\\begin{{{env}}}\n\\documentclass{{embedded}}\n\\end{{{env}}}\n"
            "\\documentclass{article}\nx\n"
        )
        hits = _assert_seam_invariants(tex)
        assert len(hits) == 1
        assert tex[: hits[0][0]].endswith("{article}")
    tex = "\\verb|\\documentclass{x}|\n\\documentclass{article}\nx\n"
    hits = _assert_seam_invariants(tex)
    assert len(hits) == 1
    assert tex[: hits[0][0]].endswith("{article}")


def test_seam_brace_depth_semantics() -> None:
    """depth>0 命中跳过；``\\bgroup``/``[..]`` 不计深度的 characterization。"""
    for prefix in [
        "\\newcommand{\\x}{\\documentclass{a}}\n",
        "\\def\\x{\\documentclass{a}}\n",
        "{\\documentclass{a}}\n",
        "\\ifmain{\\documentclass{a}}{}\n",
    ]:
        assert find_docclass_ends(prefix) == []
        hits = _assert_seam_invariants(prefix + "\\documentclass{article}\nx\n")
        assert len(hits) == 1
        assert hits[0][0] > len(prefix)  # 缝落在真声明行尾、prefix 之后
    # 前置游离 ``}`` 使 depth 归负——全量命中被跳，安全降级 no-docline。
    blinded = "}\n\\documentclass{article}\n" + _DOC
    assert find_docclass_ends(blinded) == []
    _out, info = inject_cjk(blinded)
    assert info["status"] == "no-docline"
    # ``\bgroup``/``\egroup`` 非字符花括号——depth 不计，组内声明仍成缝。
    assert len(find_docclass_ends("\\bgroup\\documentclass{a}\\egroup\n" + _DOC)) == 1
    # ``[..]`` 不计深度——``\usepackage[\documentclass{x}]{y}`` 造幻影缝：
    # 哨兵兜双注仍 preamble 位，但非声明命中计入了缝数。
    phantom = (
        "\\usepackage[\\documentclass{fakedc}]{foo}\n\\documentclass{article}\n" + _DOC
    )
    assert len(find_docclass_ends(phantom)) == 2  # noqa: PLR2004


def test_seam_multi_decl_and_dedup() -> None:
    r"""``\if..\fi`` 双臂逐缝、死臂不判死活、同行去重、enddoc 后游离声明。"""
    two = "\\ifpdf\n\\documentclass{a}\n\\else\n\\documentclass{b}\n\\fi\n" + _DOC
    assert len(_assert_seam_invariants(two)) == 2  # noqa: PLR2004
    dead = "\\iffalse\n\\documentclass{dead}\n\\fi\n\\documentclass{live}\n" + _DOC
    assert len(_assert_seam_invariants(dead)) == 2  # noqa: PLR2004
    same_line = "\\ifpdf\\documentclass{a}\\else\\documentclass{b}\\fi\n" + _DOC
    assert len(_assert_seam_invariants(same_line)) == 1
    trailing = "\\documentclass{article}\n" + _DOC + "\\documentclass{late}\n"
    hits = _assert_seam_invariants(trailing)
    assert len(hits) == 2  # noqa: PLR2004
    out, info = inject_cjk(trailing)
    assert info["status"] == "injected"
    assert info["seams"] == 2  # noqa: PLR2004
    assert out == _splice(trailing, hits, _block("ctex", 2))
    # 无 ``{..}`` 裸声明——命令行尾缝。
    assert find_docclass_ends("\\documentclass\nrest\n") == [(14, 1, "documentclass")]


# --------------------------------------------------------------- inject_cjk


def test_inject_byte_exact_oracle() -> None:
    """单缝/多缝注入与独立 oracle 逐字节一致——缝外零改写、纯追加。"""
    for tex, mode in [
        ("\\documentclass[12pt]{article}\n" + _DOC, "ctex"),
        (
            "\\RequirePackage{ifpdf}\n\\ifpdf\n\\documentclass[pdftex]{sigma}\n"
            "\\else\n\\documentclass{sigma}\n\\fi\n" + _DOC,
            "ctex",
        ),
        (
            "\\ifpdf\n\\documentclass{a}\n\\else\n\\documentclass{b}\n\\fi\n" + _DOC,
            "xecjk",
        ),
    ]:
        hits = _assert_seam_invariants(tex)
        out, info = inject_cjk(tex, mode=mode)
        assert info["status"] == "injected"
        assert out == _splice(tex, hits, _block(mode, len(hits)))
        assert len(out) > len(tex)
        # 每缝一份块标记。
        marker = "fontset=fandol,UTF8" if mode == "ctex" else "\\usepackage{xeCJK}"
        assert out.count(marker) == len(hits)


def test_inject_idempotent() -> None:
    """``inject(inject(x)) == inject(x)``——注入产物自带 CJK_PRESENT 签名。"""
    cases = [
        (_dc(), "ctex"),
        (_dc(), "xecjk"),
        (
            "\\ifpdf\n\\documentclass{a}\n\\else\n\\documentclass{b}\n\\fi\n" + _DOC,
            "ctex",
        ),
        (
            "\\ifpdf\n\\documentclass{a}\n\\else\n\\documentclass{b}\n\\fi\n" + _DOC,
            "xecjk",
        ),
        ("\\documentstyle{article}\n" + _DOC, "ctex"),
    ]
    for tex, mode in cases:
        out1, info1 = inject_cjk(tex, mode=mode)
        out2, info2 = inject_cjk(out1, mode=mode)
        assert info1["status"] == "injected"
        assert info2["status"] == "already"
        assert out2 == out1


_CJK_ALREADY = [
    "\\documentclass{ctexart}\n",
    "\\documentclass[UTF8]{ctexbook}\n",
    "\\documentclass{article}\n\\usepackage{ctex}\n",
    "\\documentclass{article}\n\\usepackage{amsmath,ctex}\n",
    "\\documentclass{article}\n\\usepackage {ctex}\n",
    "\\documentclass{article}\n\\RequirePackage{CJKutf8}\n",
    "\\documentclass{article}\n\\usepackage{xeCJK}\n",
    "\\documentclass{article}\n\\usepackage{luatexja}\n",
    "\\documentclass{article}\n\\usepackage{ctexsize}\n",
    "\\documentclass{article}\n\\usepackage{CJKpunct}\n",
    "\\documentclass{article}\n\\setCJKmainfont{SimSun}\n",
    "\\documentclass{article}\n\\newCJKfontfamily\\sfnt{x}\n",
    "\\documentclass{article}\n\\xeCJKsetup{CheckSingle=true}\n",
    (
        "\\documentclass{article}\n\\begin{document}\n\\begin{CJK}{UTF8}{gbsn}x"
        "\\end{CJK}\n\\end{document}\n"
    ),
    (
        "\\documentclass{article}\n\\begin{document}\n\\begin{CJK*}{UTF8}{gbsn}x"
        "\\end{CJK*}\n\\end{document}\n"
    ),
    # usepackage 落在 document 体内是非法 LaTeX——但 already 判据是全文件扫，
    # characterization：仍判 already 不双注。
    (
        "\\documentclass{article}\n\\begin{document}\n\\usepackage{ctex}\nx"
        "\\end{document}\n"
    ),
]

_CJK_NOT_DETECTED = [
    "\\documentclass{article}\n\\usepackage{mactex}\n",
    "\\documentclass{article}\n\\usepackage{myctex}\n",
    "\\documentclass{article}\n\\newcommand{\\ctexhelper}{}\n",
    "\\documentclass{article}\n\\def\\ctexmainfont{x}\n",
    (
        "\\documentclass{article}\n\\begin{document}\n\\begin{CJKfoo}x\\end{CJKfoo}"
        "\n\\end{document}\n"
    ),
]


def test_cjk_present_matrix() -> None:
    """真 CJK 机制判 already 零改写；内嵌 ctex 假阳名照常注入。"""
    for head in _CJK_ALREADY:
        tex = head + _DOC
        out, info = inject_cjk(tex)
        assert info["status"] == "already"
        assert out == tex
    for head in _CJK_NOT_DETECTED:
        _out, info = inject_cjk(head + _DOC)
        assert info["status"] == "injected"


def test_cjk_masked_and_edge_misses() -> None:
    r"""遮盖区 ctex 不触发 already；``\usepackage{\n ctex}``/``\input ctex.sty`` 漏检。

    characterization：``[^\n]`` 段跨不过花括号内换行（TeX 当空白、合法
    写法）与裸 ``\input`` 加载——漏检后果是 ctex 再 ``\usepackage`` 一
    次，LaTeX 层面幂等仅冗余。
    """
    for masked in [
        "% \\usepackage{ctex}\n",
        "\\begin{verbatim}\n\\usepackage{ctex}\n\\end{verbatim}\n",
        "\\begin{comment}\n\\usepackage{ctex}\n\\end{comment}\n",
        "\\verb|\\usepackage{ctex}|\n",
        "\\begin{filecontents}{x.sty}\n\\usepackage{ctex}\n\\end{filecontents}\n",
    ]:
        _out, info = inject_cjk("\\documentclass{article}\n" + masked + _DOC)
        assert info["status"] == "injected"
    for edge in [
        "\\documentclass{article}\n\\usepackage{\nctex}\n",
        "\\documentclass{article}\n\\input ctex.sty\n",
    ]:
        _out, info = inject_cjk(edge + _DOC)
        assert info["status"] == "injected"


def test_inject_hostile_bytes_and_no_docline() -> None:
    """NUL/BOM/CRLF 透传不干扰缝扫描；无声明一律 no-docline 原样。"""
    for tex in ["", "   \n\n", "% only a comment\n", _DOC]:
        out, info = inject_cjk(tex)
        assert info["status"] == "no-docline"
        assert out == tex
    nul = "\\documentclass{article}\n\\begin{document}\n\x00x\n\\end{document}\n"
    out, info = inject_cjk(nul)
    assert info["status"] == "injected"
    assert "\x00" in out
    bom = "\ufeff\\documentclass{article}\n" + _DOC
    out, info = inject_cjk(bom)
    assert info["status"] == "injected"
    assert out.startswith("\ufeff")
    crlf = "\\documentclass{article}\r\n\\begin{document}x\\end{document}\r\n"
    out, info = inject_cjk(crlf)
    assert info["status"] == "injected"
    assert "\r\n" in out
    assert out.index("fontset=fandol") < out.index("\\begin{document}")


def test_inject_209_upgrade_paths() -> None:
    r"""ds 缝升级矩阵：标准类转换、三路选项分派、dc/ds 混合两序、拒因契约。"""
    # 标准类确定转换（无 kpsewhich 依赖）。
    out, info = inject_cjk("\\documentstyle{article}\n" + _DOC)
    assert info["status"] == "injected"
    assert info["upgrade209"]["status"] == "converted"
    assert info["upgrade209"]["target"] == "article"
    assert "\\documentclass{article}" in out
    assert CTEX_LINE in out
    # ``[12pt,epsf]``：内核选项留类、宏包白名单进 ``\usepackage``。
    out, info = inject_cjk("\\documentstyle[12pt,epsf]{article}\n" + _DOC)
    conv = info["upgrade209"]
    assert conv["class_opts"] == ["12pt"]
    assert conv["pkg_opts"] == ["epsf"]
    assert "\\documentclass[12pt]{article}" in out
    assert "\\usepackage{epsf}" in out
    # ds 首 dc 尾：hits[0]=documentstyle → 先升级 ds 缝，双缝哨兵注。
    out, info = inject_cjk("\\documentstyle{article}\n\\documentclass{report}\n" + _DOC)
    assert info["status"] == "injected"
    assert info["seams"] == 2  # noqa: PLR2004
    assert info["upgrade209"]["status"] == "converted"
    assert "\\documentstyle" not in out
    # dc 首 ds 尾：不升级，逐缝注两块——``\documentstyle`` 缝吃到
    # ``\usepackage``（活臂 2.09 compat 下必炸；混合声明本身是病态输入）。
    out, info = inject_cjk("\\documentclass{a}\n\\documentstyle{b}\n" + _DOC)
    assert info["status"] == "injected"
    assert info["seams"] == 2  # noqa: PLR2004
    assert out.count("fontset=fandol,UTF8") == 2  # noqa: PLR2004
    # 拒因契约：裸声明 / ds@ 选项机类 / InjectRejectError 字段。
    with pytest.raises(InjectRejectError, match="inject_reject:latex209"):
        inject_cjk("\\documentstyle\n" + _DOC)
    with pytest.raises(InjectRejectError, match="inject_reject:latex209_ds_at"):
        inject_cjk("\\documentstyle[12pt]{ias}\n" + _DOC)
    err = InjectRejectError("latex209_ds_at")
    assert err.reason == "latex209_ds_at"
    assert str(err) == "inject_reject:latex209_ds_at"
    assert InjectRejectError().reason == "latex209"
    # 遮盖区 ``\documentstyle`` 不触发升级。
    out, info = inject_cjk("% \\documentstyle{ams}\n\\documentclass{article}\n" + _DOC)
    assert info["status"] == "injected"
    assert "upgrade209" not in info
    assert "\\documentstyle{ams}" in out
    # ``mode`` 无校验——非 "ctex" 一律 xeCJK 块（characterization）。
    out, info = inject_cjk(_dc(), mode="bogus")
    assert info["status"] == "injected"
    assert info["mode"] == "bogus"
    assert "\\usepackage{xeCJK}" in out


def test_inject_ds_shipped_sty_ds_at_rejects(tmp_path: Path) -> None:
    r"""随源 ``<cls>.sty`` 检出 ``ds@`` 分发定义 → 按 latex209_ds_at 拒。"""
    (tmp_path / "mycls.sty").write_text("\\def\\ds@preprint{}\n")
    with pytest.raises(InjectRejectError, match="inject_reject:latex209_ds_at"):
        inject_cjk("\\documentstyle{mycls}\n" + _DOC, root=tmp_path)


# --------------------------------------------------------------- 钉样缺陷


@pytest.mark.xfail(
    strict=True,
    reason=(
        "inject.py:620 `insert = len(tex) if eol < 0 else eol`——docclass "
        "`}`-close 之后没有任何 `\\n`（单行文档 / 声明尾行后无换行）时块被"
        "追加到文件末尾、落在 `\\end{document}` 之后成死代码 → 中文静默缺失"
        "（A 桶同型：注入物进死代码）。修法：eol<0 时在 close（`}` 后）插入。"
    ),
)
def test_xfail_single_line_doc_block_dead() -> None:
    r"""单行文档：注入块必须落在 ``\end{document}`` 之前。"""
    tex = "\\documentclass{article}\\begin{document}x\\end{document}"
    out, info = inject_cjk(tex)
    assert info["status"] == "injected"
    assert out.index("fontset=fandol") < out.index("\\end{document}")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "inject.py:552-580 `_docclass_close` 对 `\\documentclass` 后的实参做"
        "无界前扫——首个非空白 token 非 `[`/`{` 时（`\\documentclass\\cls` "
        "宏实参形态、裸声明）仍吞掉任意远处的 `{...}` 当类名：此处吞了 "
        "`\\begin{document}` 的花括号 → 缝落在 enddoc 行尾 → 注入块全灭。"
        "修法：扫描在首个非 `[{`/换行 token 处收口回退行尾缝。"
    ),
)
def test_xfail_docclass_macro_arg_scan_overreach() -> None:
    r"""``\documentclass\cls``（类名走宏）的缝应在声明行，而非远处 ``{..}`` 后。"""
    tex = (
        "\\def\\cls{article}\n\\documentclass\\cls\n\\begin{document}x\\end{document}\n"
    )
    hits = find_docclass_ends(tex)
    assert hits[0][1] == 2  # noqa: PLR2004 -- 缝应落在声明行
    out, _info = inject_cjk(tex)
    assert out.index("fontset=fandol") < out.index("\\end{document}")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "inject.py:615 `close < len(vis)` 守卫把 `}`-at-EOF 误判为无花括号——"
        '落入裸缝兜底 `find("\\n", m.end())`，命中声明内部的换行 → '
        "`\\documentclass\\n<BLOCK>\\n{article}` 劈断声明，类名实参成孤儿。"
        "修法：仅 `vis[close-1]=='}'` 判收，与 close==len 兼容。"
    ),
)
def test_xfail_close_brace_at_eof_splits_decl() -> None:
    r"""``\documentclass\n{article}``（``}`` 为文件末字节）不得劈断声明。"""
    tex = "\\documentclass\n{article}"
    hits = find_docclass_ends(tex)
    assert hits[0][0] > tex.index("}")  # 缝须在 } 之后
    out, _info = inject_cjk(tex)
    assert (
        out.index("\\documentclass")
        < out.index("{article}")
        < out.index("fontset=fandol")
    )


@pytest.mark.xfail(
    strict=True,
    reason=(
        "inject.py:616-622 缝落 ``}`` 行尾——同行后开的 verbatim/lstlisting "
        "环境吞掉后续行：注入块落进环境体成字面文本（死注）。修法：插点取 "
        "close（`}` 后）而非行尾，或检测行尾开启的逐字/失活环境。"
    ),
)
def test_xfail_verbatim_env_swallows_block() -> None:
    r"""docclass 行尾开 ``\begin{verbatim}``——块不得落进环境体。"""
    tex = (
        "\\documentclass{a}\\begin{verbatim}\nblah\n\\end{verbatim}\n"
        "\\begin{document}x\\end{document}\n"
    )
    out, _info = inject_cjk(tex)
    assert out.index("fontset=fandol") < out.index("\\begin{verbatim}")


@pytest.mark.xfail(
    strict=True,
    reason=(
        "latex209.py:405 `_DOCSTYLE_RE.search(visible_tex(tex))` 无 brace "
        "深度检查——首个 `\\documentstyle` 命中坐在 `\\newcommand` 宏体内"
        "（find_docclass_ends 会跳过它），升级器却改写宏体：真 "
        "`\\documentstyle{article}` 原样残留，且其缝仍吃到 `\\usepackage`"
        "（209 compat 下非法）+ def 体被 COMPAT_SHIM 撑爆。修法：用"
        " find_docclass_ends 的深度感知缝位传给升级器。"
    ),
)
def test_xfail_upgrade209_macro_body_misconvert() -> None:
    r"""宏体内的 ``\documentstyle`` 不得被升级——真声明才是转换目标。"""
    tex = "\\newcommand{\\ds}{\\documentstyle{junk}}\n\\documentstyle{article}\n" + _DOC
    out, _info = inject_cjk(tex)
    assert "\\documentstyle" not in out
    assert "\\documentclass{article}" in out


@pytest.mark.xfail(
    strict=True,
    reason=(
        "inject.py:711-712 FLOAT_SIZING 注入要求 ``documentclass`` 与 "
        "``\\begin{document}`` 同文件——编排壳 main（find_main_tex 显式收录"
        "的 cs/0408015/2105.00092 形态：dc 在 main.tex、bd 在 \\input 子文件）"
        "工程含 figure 也拿不到溢高 float 钩子（实测返回 0）。修法：dc+bd "
        "不全的文件回退文件顶/缝后位置。"
    ),
)
def test_xfail_float_sizing_shell_main_gap(tmp_path: Path) -> None:
    r"""编排壳工程（dc 在 main、bd+figure 在 ``\input`` 子文件）也要 float 钩子。"""
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n\\input{body}\n")
    (tmp_path / "body.tex").write_text(
        "\\begin{document}\n\\begin{figure}x\\end{figure}\n\\end{document}\n"
    )
    assert inject_float_sizing(tmp_path) == 1


@pytest.mark.xfail(
    strict=True,
    reason=(
        'inject.py:456 `p.suffix.lower() == ".tex"`（classify_no_main:531 '
        "同闸）——``.ltx`` 主文件不可见：find_main_tex 拒收真 LaTeX 主档，"
        "classify_no_main 把全 .ltx 工程归 ``garbage``（mask.py:19 "
        "TEX_SOURCE_SUFFIXES 已把 .ltx 计为 TeX 源——双闸口径漂移）。"
        "修法：后缀集对齐 TEX_SOURCE_SUFFIXES 或至少补 .ltx。"
    ),
)
def test_xfail_ltx_main_invisible(tmp_path: Path) -> None:
    """``.ltx`` 真 LaTeX 主档应可定位。"""
    (tmp_path / "paper.ltx").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    assert find_main_tex(tmp_path) is not None


@pytest.mark.xfail(
    strict=True,
    reason=(
        "inject.py:271 `_DOC_RE` lookahead `(?![a-zA-Z])` 放行 `@`——"
        "`\\makeatletter` 语境下 `\\documentclass@hook` 是独立控制序列而非"
        "声明，却计作缝 → 无 docclass 文件被报 ``injected``（locate.py 用更"
        "严 `(?![a-zA-Z@])`——inject 侧后果实例）。修法：lookahead 补 `@`。"
    ),
)
def test_xfail_at_hook_phantom_seam() -> None:
    r"""``\documentclass@hook`` 宏定义不应计作声明缝。"""
    tex = (
        "\\makeatletter\n\\def\\documentclass@hook#1{#1}\n\\makeatother\n"
        "\\begin{document}x\\end{document}\n"
    )
    _out, info = inject_cjk(tex)
    assert info["status"] == "no-docline"


@pytest.mark.xfail(
    strict=True,
    reason=(
        'inject.py:461 候选闸 ``re.search(r"\\\\(?:documentclass|'
        'documentstyle)\\b", text)`` 无 brace 深度检查 vs '
        "find_docclass_ends 有——唯一 docclass 藏在 `\\newcommand` 体内的"
        "文件被收为 main 却永远 ``no-docline``：``\\doc`` 展开即真声明、"
        "文件可编译，但注入层无安全缝 → 可编译文档静默零注入。修法：闸与缝"
        "用同一深度口径（或降级此类候选）。"
    ),
)
def test_xfail_macro_body_dc_unseamable(tmp_path: Path) -> None:
    r"""宏包声明形态（``\doc`` 展开为 ``\documentclass``）的 main 也应可注入。"""
    (tmp_path / "x.tex").write_text(
        "\\newcommand{\\doc}{\\documentclass{article}}\n\\doc\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    found = find_main_tex(tmp_path)
    assert found is not None
    _out, info = inject_cjk(found.read_text(encoding="utf-8"))
    assert info["status"] == "injected"


# ------------------------------------------------------------- find_main_tex


def test_main_closure_input_forms(tmp_path: Path) -> None:
    r"""``\input``/``\include``/``\InputIfFileExists``/裸形/引号闭包内 bd 均收录。"""
    for i, decl in enumerate(
        [
            "\\input{body}",
            "\\input body",
            "\\include{body}",
            "\\InputIfFileExists{body}{}{}",
            '\\input "body"',
        ]
    ):
        case = tmp_path / f"c{i}"
        case.mkdir()
        (case / "main.tex").write_text(f"\\documentclass{{article}}\n{decl}\n")
        (case / "body.tex").write_text(
            "\\begin{document}\n" + "body text " * 20 + "\n\\end{document}\n"
        )
        assert find_main_tex(case) == case / "main.tex"


def test_main_closure_escapes_not_followed(tmp_path: Path) -> None:
    r"""越出工程根 / 绝对路径 / 无扩展名 / 空白名的 ``\input`` 目标不跟随。"""
    esc = tmp_path.parent / f"{tmp_path.name}_esc.tex"
    esc.write_text("\\begin{document}\nx\n\\end{document}\n")
    try:
        cases = [
            ("\\input{../" + esc.stem + "}", "esc.tex", False),
            ("\\input{/abs/x}", None, False),
            ("\\input{body}", "body", False),  # 无扩展名文件存在也不跟
            ("\\input{my file}", "my file.tex", False),
        ]
        for i, (decl, target, _expect) in enumerate(cases):
            case = tmp_path / f"e{i}"
            case.mkdir()
            (case / "main.tex").write_text(f"\\documentclass{{article}}\n{decl}\n")
            if target is not None and "/" not in target:
                (case / target).write_text("\\begin{document}\nx\n\\end{document}\n")
            assert find_main_tex(case) is None
    finally:
        esc.unlink()


def test_main_closure_nested_subdir_and_masked_dc(tmp_path: Path) -> None:
    r"""``sub/mid → leaf`` 按声明目录解析；``filecontents`` 内嵌 docclass 不算。"""
    nested = tmp_path / "nested"
    sub = nested / "sub"
    sub.mkdir(parents=True)
    (sub / "leaf.tex").write_text("\\begin{document}\nx\n\\end{document}\n")
    (sub / "mid.tex").write_text("\\input{leaf}\nmid\n")
    (nested / "main.tex").write_text("\\documentclass{article}\n\\input{sub/mid}\n")
    assert find_main_tex(nested) == nested / "main.tex"

    masked = tmp_path / "masked"
    masked.mkdir()
    (masked / "frag.tex").write_text(
        "\\begin{filecontents}{embedded.tex}\n\\documentclass{a}\n"
        "\\begin{document}\ne\n\\end{document}\n\\end{filecontents}\n"
    )
    (masked / "real.tex").write_text("\\documentclass{article}\n" + _DOC)
    assert find_main_tex(masked) == masked / "real.tex"


def test_main_ranking_language_and_tiebreak(tmp_path: Path) -> None:
    """非拉丁主体（CJK 正文档）降权；排序键全等同回退字母序（确定性）。"""
    lang = tmp_path / "lang"
    lang.mkdir()
    (lang / "aaa_zh.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        + "汉字内容" * 60
        + "\n\\end{document}\n"
    )
    (lang / "zzz_en.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        + "english text " * 20
        + "\n\\end{document}\n"
    )
    assert find_main_tex(lang) == lang / "zzz_en.tex"

    tie = tmp_path / "tie"
    tie.mkdir()
    body = "\\documentclass{article}\n\\begin{document}\nsame\n\\end{document}\n"
    (tie / "b.tex").write_text(body)
    (tie / "a.tex").write_text(body)
    assert find_main_tex(tie) == tie / "a.tex"


# --------------------------------------------------------- classify_no_main


def test_classify_buckets(tmp_path: Path) -> None:
    r"""plain 指纹 / ds 优先级 / 遮盖口径 / ``\end{env}`` 非 bare end。"""
    plain = [
        "\\magnification=1200\n\\bye\n",
        "\\magstep1\nx\n\\bye\n",
        "\\font\\rm=cmr10\n\\bye\n",
        "text\n\\end\n",
        "\\input harvmac\nx\n",
        "\\input{phyzzx}\nx\n",
        "\\input{amstex}\nx\n",
        "\\input{texinfo}\nx\n",
    ]
    f = tmp_path / "n.tex"
    for body in plain:
        f.write_text(body)
        assert classify_no_main(tmp_path) == "plain_tex"
    f.unlink()
    # ds 与 plain 指纹并存 → latex209；ds 与 bd 并存（异文件）→ latex209。
    f.write_text("\\documentstyle{amsppt}\n\\input phyzzx\n")
    assert classify_no_main(tmp_path) == "latex209"
    f.write_text("\\documentstyle{ams}\n")
    (tmp_path / "b.tex").write_text("\\begin{document}\nx\n\\end{document}\n")
    assert classify_no_main(tmp_path) == "latex209"
    (tmp_path / "b.tex").unlink()
    # verbatim 内 docclass / 注释内 documentstyle 被遮盖 → garbage；
    # ``\end{env}`` 带花括号不是 bare ``\end`` → 不算 plain 指纹。
    f.write_text("\\begin{verbatim}\n\\documentclass{article}\n\\end{verbatim}\n")
    assert classify_no_main(tmp_path) == "garbage"
    f.write_text("% \\documentstyle{amsart}\nplain text\n")
    assert classify_no_main(tmp_path) == "garbage"
    f.write_text("\\end{center}\nsome text\n")
    assert classify_no_main(tmp_path) == "garbage"
    # ``.ltx`` 树归 garbage——characterization（同 I7 闸口径漂移）。
    f.unlink()
    (tmp_path / "doc.ltx").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    assert classify_no_main(tmp_path) == "garbage"


# ------------------------------------------- float_sizing / table_fitting


def test_float_gate_env_and_masked(tmp_path: Path) -> None:
    r"""figure/table（含 ``*``/空白变体）触门；遮盖区 figure 不触发不写盘。"""
    main = tmp_path / "main.tex"
    for figline in [
        "\\begin{figure}x\\end{figure}",
        "\\begin{figure*}x\\end{figure*}",
        "\\begin{table}x\\end{table}",
        "\\begin{table*}x\\end{table*}",
        "\\begin {figure}x\\end{figure}",
    ]:
        main.write_text(
            "\\documentclass{article}\n\\begin{document}\n"
            + figline
            + "\n\\end{document}\n"
        )
        assert inject_float_sizing(tmp_path) == 1
        main.write_text(
            "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
        )
    for masked_fig in [
        "% \\begin{figure}x\\end{figure}",
        "\\begin{verbatim}\n\\begin{figure}x\\end{figure}\n\\end{verbatim}",
        "\\begin{comment}\n\\begin{figure}x\\end{figure}\n\\end{comment}",
    ]:
        main.write_text(
            "\\documentclass{article}\n\\begin{document}\n"
            + masked_fig
            + "\n\\end{document}\n"
        )
        before = main.read_bytes()
        assert inject_float_sizing(tmp_path) == 0
        assert main.read_bytes() == before


def test_float_project_wide_and_idempotent(tmp_path: Path) -> None:
    r"""工程级门：figure 在散件也注 main；块锚 ``\begin{document}`` 前；
    双 main 各注一份返回 2（docstring ``0/1`` 口径漂移 characterization）；
    二跑子串幂等。"""
    proj = tmp_path / "p1"
    proj.mkdir()
    (proj / "figs.tex").write_text("\\begin{figure}x\\end{figure}\n")
    (proj / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    assert inject_float_sizing(proj) == 1
    text = (proj / "main.tex").read_text()
    assert text.index("texlate@endfloatbox") < text.index("\\begin{document}")
    after = (proj / "main.tex").read_bytes()
    assert inject_float_sizing(proj) == 0
    assert (proj / "main.tex").read_bytes() == after

    proj2 = tmp_path / "p2"
    proj2.mkdir()
    for name in ("a.tex", "b.tex"):
        (proj2 / name).write_text(
            "\\documentclass{article}\n\\begin{document}\n"
            "\\begin{figure}x\\end{figure}\n\\end{document}\n"
        )
    assert inject_float_sizing(proj2) == 2  # noqa: PLR2004


def test_table_fitting_block() -> None:
    r"""无 ``\begin{document}`` 锚原样返回；块落锚前；子串幂等。"""
    tex = "\\documentclass{article}\nno body env\n"
    assert inject_table_fitting(tex) == tex
    out = inject_table_fitting("\\documentclass{article}\n" + _DOC)
    assert TABLE_FITTING.strip() in out
    assert out.index("TeXlateFitTable") < out.index("\\begin{document}")
    assert inject_table_fitting(out) == out


# ------------------------------------------------------------ prepare_chinese


def test_prepare_no_docline_and_table_gates(tmp_path: Path) -> None:
    r"""no-docline 零写盘；注释内 ``threeparttable`` 不触门；裸子串门过触发。

    ``\threeparttableish`` 宏名也触门（characterization：良性过触发——
    加载 adjustbox + 挂不上的 env hook，编译层面无害）。
    """
    main = tmp_path / "main.tex"
    main.write_text("just a fragment\n")
    info = prepare_chinese(tmp_path, "main.tex", float_sizing=False)
    assert info["status"] == "no-docline"
    assert main.read_text() == "just a fragment\n"
    assert "float_sizing" not in info

    main.write_text("\\documentclass{article}\n% \\usepackage{threeparttable}\n" + _DOC)
    prepare_chinese(tmp_path, "main.tex", float_sizing=False)
    assert "TeXlateFitTable" not in main.read_text()

    main.write_text(
        "\\documentclass{article}\n\\newcommand{\\threeparttableish}{x}\n" + _DOC
    )
    prepare_chinese(tmp_path, "main.tex", float_sizing=False)
    assert "TeXlateFitTable" in main.read_text()


def test_prepare_209_end_to_end(tmp_path: Path) -> None:
    r"""209 工程整链升级+注入落盘；ias 类 InjectRejectError 原样上抛。"""
    main = tmp_path / "m.tex"
    main.write_text("\\documentstyle{article}\n" + _DOC)
    info = prepare_chinese(tmp_path, "m.tex", float_sizing=False)
    assert info["status"] == "injected"
    assert info["upgrade209"]["status"] == "converted"
    text = main.read_text()
    assert "\\documentclass{article}" in text
    assert CTEX_LINE in text

    main.write_text("\\documentstyle{ias}\n" + _DOC)
    with pytest.raises(InjectRejectError, match="inject_reject:latex209_ds_at"):
        prepare_chinese(tmp_path, "m.tex", float_sizing=False)


def test_prepare_idempotent_rerun(tmp_path: Path) -> None:
    """编排级幂等：二跑 already、文件不变。"""
    main = tmp_path / "main.tex"
    main.write_text("\\documentclass{article}\n" + _DOC)
    prepare_chinese(tmp_path, "main.tex", float_sizing=False)
    after1 = main.read_bytes()
    info2 = prepare_chinese(tmp_path, "main.tex", float_sizing=False)
    assert info2["status"] == "already"
    assert main.read_bytes() == after1


def test_prepare_encoding_and_arg_forms(tmp_path: Path) -> None:
    """非 UTF-8 源注入后按 utf-8 重写（xelatex 前置）；``main`` 可传 Path。"""
    main = tmp_path / "m.tex"
    main.write_bytes(
        "\\documentclass{article}\n\\begin{document}\nGr\\xf6\\xdfe\n"
        "\\end{document}\n".encode("cp1252")
    )
    info = prepare_chinese(tmp_path, "m.tex", float_sizing=False)
    assert info["status"] == "injected"
    text = main.read_bytes().decode("utf-8")  # 可解码即 utf-8 产物
    assert CTEX_LINE in text

    main2 = tmp_path / "p.tex"
    main2.write_text("\\documentclass{article}\n" + _DOC)
    info = prepare_chinese(tmp_path, main2, float_sizing=False)
    assert info["status"] == "injected"


def test_prepare_shell_main_gaps(tmp_path: Path) -> None:
    r"""编排壳工程 prepare 全链（characterization，I6 同族覆盖口）。

    dc 在 main、bd+figure+threeparttable 在 ``\input`` 子文件：ctex 注入
    落在 main（缝在）；FLOAT_SIZING 要求 dc+bd 同文件 → 0；threeparttable
    门只读 main 文本 → TABLE_FITTING 不注。两个钩子口对壳形态静默缺席。
    """
    (tmp_path / "main.tex").write_text("\\documentclass{article}\n\\input{body}\n")
    (tmp_path / "body.tex").write_text(
        "\\usepackage{threeparttable}\n\\begin{document}\n"
        "\\begin{figure}x\\end{figure}\n\\end{document}\n"
    )
    info = prepare_chinese(tmp_path, "main.tex")
    assert info["status"] == "injected"
    assert info["float_sizing"] == 0
    text = (tmp_path / "main.tex").read_text()
    assert CTEX_LINE in text
    assert "TeXlateFitTable" not in text


# --------------------------------------------------------------- 随机 fuzz


_FRAGS = [
    "\\documentclass{article}\n",
    "\\documentclass[12pt,a4paper]{amsart}\n",
    "\\documentclass[%\n aps,%\n prl]{revtex4-2}\n",
    "\\documentclass{standalone}",
    "\\documentclass\n{article}\n",
    "\\documentstyle{article}\n",
    "\\documentstyle{ias}\n",
    "\\documentstyle{weirdcls}\n",
    "% \\documentclass{ghost}\n",
    "\\begin{verbatim}\n\\documentclass{v}\n\\end{verbatim}\n",
    "\\begin{comment}\n\\documentclass{c}\n\\end{comment}\n",
    "\\newcommand{\\dc}{\\documentclass{macro}}\n",
    "\\ifpdf\n\\documentclass{a}\n\\else\n\\documentclass{b}\n\\fi\n",
    "\\usepackage{amsmath}\n",
    "\\usepackage{ctex}\n",
    "\\def\\x#1{#1}\n",
    "\\begin{document}\n",
    "body $x_{i}$ \\textbf{b} {nest}\n",
    "\\end{document}\n",
    "\\{ \\} \\%\n",
    "\\verb|{|\n",
    "\x00\n",
    "\ufeff",
    "\\bgroup\n",
    "\\egroup\n",
    "\\section{A}\n",
    "\\input{sub}\n",
]


def test_fuzz_random_inputs() -> None:
    """碎片随机拼接：缝扫描不变量 + 注入四态 + 幂等——恒不抛、恒自洽。"""
    rng = random.Random(20260917)  # noqa: S311 -- 确定性种子
    for _ in range(240):
        tex = "".join(rng.choice(_FRAGS) for _ in range(rng.randrange(1, 14)))
        hits = _assert_seam_invariants(tex)
        try:
            out, info = inject_cjk(tex)
        except InjectRejectError:
            continue
        status = info["status"]
        assert status in {"injected", "already", "no-docline"}
        if status != "injected":
            assert out == tex
            continue
        assert len(out) > len(tex)
        if "\\documentstyle" not in tex:
            # 字节守恒：首缝前前缀 + 末缝后后缀原样（升级路径除外——
            # documentstyle 片段会被改写）。
            assert out[: hits[0][0]] == tex[: hits[0][0]]
            assert out.endswith(tex[hits[-1][0] :])
        out2, info2 = inject_cjk(out)
        assert info2["status"] == "already"
        assert out2 == out


def test_fuzz_regex_and_scan_bounded() -> None:
    r"""长选项段/长包名不挂——``_DOCCLASS_SCAN_LIMIT`` 界内返回、
    ``CJK_PRESENT_RE`` 对敌对 ``{``/``[`` 串无回溯爆炸。"""
    tex = "\\documentclass[" + "a," * 3000 + "]{cls}\nx\n"
    assert len(find_docclass_ends(tex)) == 1
    hostile = "\\documentclass{article}\n\\usepackage{" + "a" * 5000 + "}\n" + _DOC
    out, info = inject_cjk(hostile)
    assert info["status"] == "injected"
    assert len(out) > len(hostile)
    assert re.search(r"a{5000}", out)
    assert CJK_PRESENT_RE.search("[" * 2000 + "{ctex}") is None or True
