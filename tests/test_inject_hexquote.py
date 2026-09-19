"""注入块 ``"``-hex catcode 守护回归（dimcen A3）。

``"`` 只有 catcode-12 时是合法十六进制前缀。CJK_MATH_FALLBACK 锚在
``\\begin{document}`` 前（全部 ``\\usepackage`` 之后），读到时 ``"`` 可能
已被宏包改写：quotes.sty ``\\global\\catcode`\\"\\active``（1012.1303
spidersweb:208，``<to be read again> \\let``——active ``"`` 在数字扫描中
展开）、fundus-cyr 链置 catcode-11（1206.1631 gamma_d:186-194，
``<to be read again> "``）——``\\count@="4E00`` 全体 Missing number +
Missing \\begin{document}（22 hits/2 cells）。

修复形状：守护区间——块首 ``\\chardef\\TeXlate@dqcat=\\the\\catcode`\\"``
存值 + ``\\catcode`\\"=12``，块尾 ``\\catcode`\\"=\\TeXlate@dqcat`` 精确
还原；区间内 ``\\def`` 体、调用点实参与字体名引号全按 12 读入。
TIE_ACCENT_FIX 的 ``"0361`` 直接改十进制 ``865``（下游 ``\\char`` 数字
扫描语义恒等，彻底脱敏）。真编译臂人为 ``\\catcode`\\"=11``/``=\\active``
投毒验证注入产物零 Missing number、数学内 CJK 零缺字。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.compile.inject import (
    CJK_MATH_FALLBACK,
    TEXT_8BIT_FALLBACK,
    TIE_ACCENT_FIX,
    inject_cjk,
)

_GUARD_SET = r"\catcode`\"=12"
_GUARD_SAVE = r"\chardef\TeXlate@dqcat=\the\catcode`\""
_GUARD_RESTORE = r"\catcode`\"=\TeXlate@dqcat"


def _guard_span(block: str) -> tuple[int, int]:
    """守护区间 offset：``\\catcode`\\"=12`` 起 → 还原行止。"""
    return block.index(_GUARD_SET), block.index(_GUARD_RESTORE)


def test_mathmap_catcode_guard() -> None:
    r"""mathmap 块在 ``\makeatletter`` 后立 guard，``\makeatother`` 前还原。"""
    body = CJK_MATH_FALLBACK
    assert _GUARD_SAVE in body
    start, end = _guard_span(body)
    assert body.index(r"\makeatletter") < start
    assert body.index(r"\def\TeXlate@mathmap") > start
    assert end < body.index(r"\makeatother")


def test_mathmap_guard_covers_all_hex_sites() -> None:
    r"""所有 ``"``-hex 操作数与调用点都落在守护区间内（区间外无裸 ``"``）。

    ``"`` 字符在块内出现处 = 守护行自身（``\catcode`\"`` 形态，`` ` `` 转义
    不受 ``"`` catcode 影响）+ 区间内的 ``\def`` 体/调用实参/字体名引号。
    """
    body = CJK_MATH_FALLBACK
    start, end = _guard_span(body)
    for site in (
        r"\def\TeXlate@mathmap",
        r"\DeclareSymbolFont{texlatecjk}",
        r"\TeXlate@mathmap\symtexlatecjk 4E00-9FFF;",
        r"\TeXlate@mathmap\symtexlatefb 00F8-017F;",
        '"[FandolSong-Regular.otf]"',
        '"[LibertinusSerif-Regular.otf]"',
    ):
        assert start < body.index(site) < end, f"{site} 不在守护区间内"


def test_clsmap_catcode_guard() -> None:
    r"""clsmap 同款守护——docclass 缝防类文件级 ``"`` 投毒（同 A3 机理）。"""
    body = TEXT_8BIT_FALLBACK
    assert _GUARD_SAVE in body
    start, end = _guard_span(body)
    assert body.index(r"\makeatletter") < start
    for site in (
        r"\def\TeXlate@clsmap",
        r"\TeXlate@clsmap 0400-0530;",
        r"\TeXlate@clsmap FB00-FB50;",
        '"[cmunrm.otf]"',
    ):
        assert start < body.index(site) < end, f"{site} 不在守护区间内"
    assert end < body.index(r"\makeatother")


def test_guard_save_restore_symmetric() -> None:
    """每块恰好一条存值、一条置位、一条还原——漏还原会把 catcode 改写给用户。"""
    for body in (CJK_MATH_FALLBACK, TEXT_8BIT_FALLBACK):
        assert body.count(_GUARD_SAVE) == 1
        assert body.count(_GUARD_SET) == 1
        assert body.count(_GUARD_RESTORE) == 1


def test_tie_accent_decimal_operand() -> None:
    r"""``\t`` 码位实参十进制化——``"0361`` 消失，``865`` 恒等上档。"""
    assert r"\DeclareUnicodeAccent{\t}{865}" in TIE_ACCENT_FIX
    assert '"0361' not in TIE_ACCENT_FIX


def test_inject_output_carries_guard() -> None:
    """端到端：``inject_cjk`` 产物里守护行确实落盘（bd 锚路径）。"""
    tex = "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    out, info = inject_cjk(tex, mode="ctex")
    assert info["status"] == "injected"
    assert _GUARD_SET in out
    assert _GUARD_RESTORE in out
    assert out.index(_GUARD_SET) < out.index(r"\def\TeXlate@mathmap")


_DOC_TEMPLATE = (
    "\\documentclass{article}\n%s\n\\begin{document}\nText $中$.\n\\end{document}\n"
)


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex not installed")
def test_mathmap_real_compile_poisoned_quote(tmp_path: Path) -> None:
    r"""真编译双投毒臂：``"``=catcode-11（cyr 态）与 ``"``=active（quotes 态）

    下注入产物零 Missing number、数学内 CJK 零缺字。对照臂（未守护的
    旧块形状）在 ``"``=11 下复现 census 签名。
    """
    xelatex = shutil.which("xelatex")
    assert xelatex is not None

    def _compile(name: str, tex: str) -> str:
        p = tmp_path / f"{name}.tex"
        p.write_text(tex, encoding="utf-8")
        subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
            [xelatex, "-interaction=nonstopmode", p.name],
            cwd=tmp_path,
            capture_output=True,
            timeout=120,
            check=False,
        )
        return (tmp_path / f"{name}.log").read_text(encoding="utf-8", errors="replace")

    for tag, poison in (
        ("cat11", '\\catcode`\\"=11'),
        ("active", '\\catcode`\\"=\\active'),
    ):
        doc = _DOC_TEMPLATE % poison
        out, info = inject_cjk(doc, mode="ctex")
        assert info["status"] == "injected"
        log = _compile(f"poison_{tag}", out)
        n_missing_num = len(re.findall(r"Missing number", log))
        assert n_missing_num == 0, f"{tag}: {n_missing_num} 个 Missing number"
        n_missing_chr = len(re.findall(r"Missing character", log))
        assert n_missing_chr == 0, f"{tag}: {n_missing_chr} 个缺字"

    # 对照臂：剥掉守护行恢复旧形状，catcode-11 下必复现 census 签名。
    ctl_doc = _DOC_TEMPLATE % '\\catcode`\\"=11'
    out, _info = inject_cjk(ctl_doc, mode="ctex")
    ctl = out.replace(_GUARD_SAVE + _GUARD_SET, "")
    ctl = ctl.replace(_GUARD_RESTORE, "")
    assert _GUARD_SET not in ctl
    ctl_log = _compile("ctl_cat11", ctl)
    assert len(re.findall(r"Missing number", ctl_log)) > 0


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex not installed")
def test_clsmap_real_compile_poisoned_quote(tmp_path: Path) -> None:
    r"""TEXT_8BIT_FALLBACK 裸块贴进 ``"``=11 前导区——守护后 clsmap 正常执行。

    门已从 ``\\IfFileExists``（TEXINPUTS 死门）换成 ``\\IfFontExistsTF``
    （kpathsea 字体树）——裸贴场景补 ``\\usepackage{fontspec}`` 令门真开，
    才能实测到 ``\\TeXlate@clsmap`` 的 ``"``-hex 路径。
    """
    xelatex = shutil.which("xelatex")
    assert xelatex is not None
    doc = (
        "\\documentclass{article}\n"
        "\\usepackage{fontspec}\n"
        '\\catcode`\\"=11\n'
        + TEXT_8BIT_FALLBACK
        + "\\begin{document}\nx\\end{document}\n"
    )
    p = tmp_path / "clsmap_cat11.tex"
    p.write_text(doc, encoding="utf-8")
    subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [xelatex, "-interaction=nonstopmode", p.name],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    log = (tmp_path / "clsmap_cat11.log").read_text(encoding="utf-8", errors="replace")
    n_missing = len(re.findall(r"Missing number", log))
    assert n_missing == 0, f"{n_missing} 个 Missing number"
    # 对照：剥守护行后同投毒必崩。
    ctl = doc.replace(_GUARD_SAVE + _GUARD_SET, "").replace(_GUARD_RESTORE, "")
    p2 = tmp_path / "clsmap_ctl.tex"
    p2.write_text(ctl, encoding="utf-8")
    subprocess.run(  # noqa: S603 -- argv[0] 来自 shutil.which 绝对路径
        [xelatex, "-interaction=nonstopmode", p2.name],
        cwd=tmp_path,
        capture_output=True,
        timeout=120,
        check=False,
    )
    ctl_log = (tmp_path / "clsmap_ctl.log").read_text(
        encoding="utf-8", errors="replace"
    )
    assert len(re.findall(r"Missing number", ctl_log)) > 0
