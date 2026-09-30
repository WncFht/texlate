"""字体门 ``\\IfFileExists{*.otf}`` → ``\\IfFontExistsTF`` 修复回归（fontgate）。

旧门 ``\\IfFileExists`` 走 ``\\openin``/TEXINPUTS（texmf/tex/）——otf 住
texmf/fonts/ 恒查不到，两个 fallback 臂是永久 FALSE 的死代码：Libertinus
数学后备（``\\Umathcode`` 带）+ CMU 文本后备（``\\XeTeXinterchartoks`` 换族）。
fontspec ``\\IfFontExistsTF`` 走 kpathsea 字体树才查得到；fontspec 由
ctex/xeCJK 块携带加载，``\\ifdefined`` 兜底裸贴场景视为缺席（跳过不报错）。

形状约束（两个实证陷阱）：
- 判定必须先收进 ``\\chardef`` flag 再用原语 ``\\ifnum`` 门本体——
  ``\\IfFontExistsTF{font}{体}{}`` 的实参在读取时即 tokenize，体内
  ``\\makeatletter``/``\\catcode`\\"`` 守护来不及生效（Missing number 实证）。
- flag 用 ``\\chardef`` 而非 ``\\let..\\iftrue``——被跳过分支文本里的裸
  ``\\iftrue``/``\\iffalse`` token 会被条件扫描误计成开臂，``\\fi`` 配对
  全崩（Incomplete \\ifdefined 实证）。

连带修复：0..31 接线循环把 (CMUclass→CMUclass) 自环配成 cmuOff——同类
相邻字符每对都复位字体，一串西里尔只剩首字换族；接线后清掉这对自环。
"""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from texlate.compile.inject import CJK_MATH_FALLBACK, TEXT_8BIT_FALLBACK, inject_cjk

_CMU_GATE = (
    r"\IfFontExistsTF{cmunrm.otf}"
    r"{\chardef\TeXlateCMUok=1\relax}{\chardef\TeXlateCMUok=0\relax}"
)
_SELF_PAIR_CLEAR = r"\XeTeXinterchartoks\TeXlateCMUclass\TeXlateCMUclass={}"


def _strip_comments(tex: str) -> str:
    """剥掉 ``%`` 注释——条件扫描看到的是 token 流，注释文本不计。"""
    return re.sub(r"%[^\n]*", "", tex)


def test_no_iffileexists_otf_gate() -> None:
    """死门根除：两块内不再用 ``\\IfFileExists`` 查任何 .otf。"""
    for block in (CJK_MATH_FALLBACK, TEXT_8BIT_FALLBACK):
        assert not re.search(r"\\IfFileExists\{[^}]*\.otf\}", block)


def test_math_gate_resolves_into_chardef_flag() -> None:
    r"""Libertinus 臂：``\IfFontExistsTF`` → ``\chardef\TeXlateFBok`` →
    原语 ``\ifnum`` 门本体（门体不是宏实参——tokenize 陷阱规避）。"""
    body = CJK_MATH_FALLBACK
    assert r"\ifdefined\IfFontExistsTF" in body
    assert r"\IfFontExistsTF{LibertinusSerif-Regular.otf}{%" in body
    assert r"\chardef\TeXlateFBok=1\relax" in body
    assert r"\chardef\TeXlateFBok=0\relax" in body
    assert body.index(r"\ifnum\TeXlateFBok=1\relax") > body.index(
        r"\IfFontExistsTF{LibertinusSerif-Regular.otf}"
    )


def test_text_gate_resolves_into_chardef_flag() -> None:
    r"""CMU 臂同形：``\IfFontExistsTF`` → ``\chardef\TeXlateCMUok`` → ``\ifnum``。"""
    body = TEXT_8BIT_FALLBACK
    assert r"\ifdefined\IfFontExistsTF" in body
    assert _CMU_GATE in body
    assert body.index(r"\ifnum\TeXlateCMUok=1\relax") > body.index(_CMU_GATE)


def test_ifdefined_fallback_means_absent() -> None:
    r"""``\ifdefined\IfFontExistsTF`` 的 ``\else`` 臂把 flag 置 0——裸贴场景
    fontspec 不在 ≡ 字体缺席，跳过而非 undefined-cs 硬错。"""
    for block, flag in (
        (CJK_MATH_FALLBACK, "FBok"),
        (TEXT_8BIT_FALLBACK, "CMUok"),
    ):
        seg = block.split(r"\ifdefined\IfFontExistsTF", 1)[1]
        else_arm = seg.split(r"\else", 1)[1].split(r"\fi", 1)[0]
        assert rf"\chardef\TeXlate{flag}=0\relax" in else_arm


def test_no_bare_iftrue_iffalse_in_code() -> None:
    r"""块内不得出现裸 ``\iftrue``/``\iffalse`` token——被跳过分支文本里的
    裸 token 会被条件扫描误计成开臂（flag 必须用 ``\chardef``+``\ifnum``）。"""
    for block in (CJK_MATH_FALLBACK, TEXT_8BIT_FALLBACK):
        code = _strip_comments(block)
        assert "\\iftrue" not in code
        assert "\\iffalse" not in code


def test_self_interchartoks_pair_cleared() -> None:
    """0..31 接线循环把 (CMUclass→CMUclass) 自环配成 cmuOff——同类相邻
    字符每对都复位字体，一串西里尔只剩首字换族；循环后必须清零。"""
    body = TEXT_8BIT_FALLBACK
    assert _SELF_PAIR_CLEAR in body
    assert body.index(_SELF_PAIR_CLEAR) > body.index(r"\@whilenum\count@<32")


def test_flags_namespaced_per_block() -> None:
    """两 flag 分块命名不串。"""
    assert "TeXlateFBok" not in TEXT_8BIT_FALLBACK
    assert "TeXlateCMUok" not in CJK_MATH_FALLBACK


def test_inject_output_carries_live_gates() -> None:
    """端到端：``inject_cjk`` 产物里两个 ``\\IfFontExistsTF`` 门都落盘。"""
    tex = "\\documentclass{article}\n\\begin{document}\nx\\end{document}\n"
    out, info = inject_cjk(tex, mode="ctex")
    assert info["status"] == "injected"
    assert r"\IfFontExistsTF{cmunrm.otf}" in out
    assert r"\IfFontExistsTF{LibertinusSerif-Regular.otf}" in out


def _compile(tmp_path: Path, name: str, tex: str) -> str:
    xelatex = shutil.which("xelatex")
    assert xelatex is not None
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


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex not installed")
def test_text_arm_adjacent_cluster_renders(tmp_path: Path) -> None:
    r"""活臂验证：同类相邻簇 ``ДШЛ`` 全字符换族、``中Д中`` CJK 相邻不串、
    数学 ``ł`` 走 Libertinus 后备——零缺字零硬错（自环 Off 修复实证）。"""
    doc = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "aДШЛb 中Д中 $łŁ$\n"
        "\\end{document}\n"
    )
    out, info = inject_cjk(doc, mode="ctex")
    assert info["status"] == "injected"
    log = _compile(tmp_path, "cluster", out)
    assert "Missing character" not in log
    assert not re.search(r"^! ", log, re.MULTILINE)
    assert "Incomplete \\if" not in log


@pytest.mark.integration
@pytest.mark.skipif(shutil.which("xelatex") is None, reason="xelatex not installed")
def test_absent_font_skips_cleanly(tmp_path: Path) -> None:
    """缺席语义：门指到不存在字体 → 臂整体跳过——西里尔降级为缺字警告，
    零硬错（与原 ``\\IfFileExists`` 缺席语义对齐，不升级成字体加载错误）。"""
    doc = "\\documentclass{article}\n\\begin{document}\naДb\n\\end{document}\n"
    out, info = inject_cjk(doc, mode="ctex")
    assert info["status"] == "injected"
    dead = out.replace(
        r"\IfFontExistsTF{cmunrm.otf}",
        r"\IfFontExistsTF{NoSuchFontXYZ-12345.otf}",
    )
    assert dead != out
    log = _compile(tmp_path, "absent", dead)
    assert "Missing character" in log
    assert not re.search(r"^! ", log, re.MULTILINE)
    assert "Emergency stop" not in log
