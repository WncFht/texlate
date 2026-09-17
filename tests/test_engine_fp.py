"""engine.py 误报回归：latex209 tail 签名收紧 + pstricks 路由高置信化。

证据：docs/research/product/2026-09-16-signature-mining.md §2.4 +
bench/results/fixloop-replay-baseline-2026-09-16/SUMMARY.md
（aastex 横幅 15+ 篇 latex209 误报、1803.08846 注释 pstricks 误杀）。
"""

from pathlib import Path

from texlate.compile.engine import route_project
from texlate.compile.loginfo import classify_error

#: aastex61/62/63x cls 的 \typeout 横幅在 .log 里的实落形态（\protect 使
#: \LaTeX/\LaTeXe 逐字输出）——1803.08927 proj/apjl_jets.log 实测段。
_AASTEX_BANNER_TAIL = (
    "Document Class: aastex61 2016/04/16 Version 6.1/AAS markup document class\n"
    "Class aastex Info: \n"
    " \n"
    " Original \\LaTeX2.09 style by Chris Biemesderfer (chris@seagoat.com). \n"
    " Adapted to \\LaTeXe by A. Ogawa (ogawa@teleport.com)\n"
    "  on input line 106.\n"
    "\\bibbaselineskip=\\skip49\n"
    "\n"
    "\n"
    " Please update your system to include revtex4-1.cls\n"
    "\n"
    "\n"
    " ) )\n"
    "(\\end occurred when \\ifx on line 26 was incomplete) \n"
    "No pages of output.\n"
)


# ---------------------------------------------------------------- latex209 tail
def test_tail_aastex_banner_not_latex209() -> None:
    """aastex 横幅落 tail（零 '!' 行静默死 → err=None 走 tail 扫描）
    不得归 latex209——这些全是 \\documentclass 的 LaTeX2e 稿。tail 实携
    "Please update your system to include revtex4-1.cls" 求档文 → 归
    missing_file（cls-plea tail 规则有意排在 early_eof 之前——plea 提出
    的文件名是 actionable payload，install/shim 链接手；18ff106）。"""
    cat, _ = classify_error(None, None, _AASTEX_BANNER_TAIL, timed_out=False)
    assert cat == "missing_file"


def test_tail_banner_plus_unmatched_error_not_latex209() -> None:
    """首错存在但不中 head 规则时 tail 回扫：banner 同样不得顶包。"""
    tail = "Original \\LaTeX2.09 style\nNo pages of output.\n"
    cat, _ = classify_error("! Weird unclassified failure", None, tail, timed_out=False)
    assert cat == "other"


def test_tail_documentstyle_still_latex209() -> None:
    """真 2.09：`\\documentstyle` cs 现身 tail 错上下文（l.N 行）→ 判。"""
    tail = "l.5 \\documentstyle{article}\nNo pages of output.\n"
    cat, _ = classify_error(None, None, tail, timed_out=False)
    assert cat == "latex209"


def test_tail_compat_mode_banner_still_latex209() -> None:
    """真 2.09：内核 compat-mode 横幅 + 逐行 Compatibility mode 注记。"""
    tail = (
        "Entering LaTeX 2.09 COMPATIBILITY MODE\n"
        "This mode attempts to provide an emulation of the LaTeX 2.09\n"
        "No pages of output.\n"
    )
    cat, _ = classify_error(None, None, tail, timed_out=False)
    assert cat == "latex209"


def test_tail_compat_mode_notes_still_latex209() -> None:
    """compat 注记行（'Compatibility mode: definition of \\rm ignored.'）。"""
    tail = (
        "Compatibility mode: definition of \\rm ignored.\n"
        "Compatibility mode: definition of \\sf ignored.\n"
        "No pages of output.\n"
    )
    cat, _ = classify_error(None, None, tail, timed_out=False)
    assert cat == "latex209"


def test_tail_latex2e_in_209_still_latex209() -> None:
    """内核错 'LaTeX2e command \\ensuremath in LaTeX 2.09 document'
    （hep-th/0104130 实证签名）落 tail 仍判。"""
    tail = "! LaTeX Error: LaTeX2e command \\ensuremath in LaTeX 2.09 document.\n"
    cat, _ = classify_error(None, None, tail, timed_out=False)
    assert cat == "latex209"


def test_tail_209_missing_file_precedence() -> None:
    """真 2.09 稿死 missing file：missing_file 先于 latex209——astro-ph/
    9703134 实落路径（aaspp4.sty + Enter file name + Emergency）。"""
    tail = (
        "Entering LaTeX 2.09 COMPATIBILITY MODE\n"
        "! LaTeX Error: File `aaspp4.sty' not found.\n"
        "Enter file name: \n! Emergency stop.\n"
        "*** (cannot \\read from terminal in nonstop modes)\n"
    )
    cat, pay = classify_error(None, None, tail, timed_out=False)
    assert cat == "missing_file"
    assert pay == "aaspp4.sty"


# ---------------------------------------------------------------- pstricks 路由
def test_route_pstricks_comments_not_routed(tmp_path: Path) -> None:
    """1803.08846 实证：注释掉的 pstricks/pstricks-add/pspicture 行
    （visible_tex 已盖）不改路由——保持 tectonic 优先。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\usepackage{amsmath,amssymb,theorem}\n"
        "% \\usepackage{pstricks-add}\n"
        "%\\usepackage{pstricks}\n"
        "% \\begin{pspicture}(0,0)(1,1)\\end{pspicture}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    d = route_project(tmp_path)
    assert d.engines == ["tectonic", "xelatex"]
    assert not any("pstricks" in r for r in d.reasons)


def test_route_ps_macro_shadows_not_routed(tmp_path: Path) -> None:
    """宏定义里的 \\psline/\\psframe 残影（无包声明/环境/\\psset）不命中——
    裸 \\ps* 族已从识别面移除（corpus_v3 全扫零独立命中）。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\newcommand{\\fakeps}{\\psline(0,0)(1,1)\\psframe(2,2)(3,3)}\n"
        "\\def\\pscurvealias{\\pscurve}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    d = route_project(tmp_path)
    assert d.engines == ["tectonic", "xelatex"]


def test_route_pstricks_substring_pkg_not_routed(tmp_path: Path) -> None:
    """包名元素边界：{notpstricks}/{pstricksfoo} 类子串不得命中。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{notpstricks}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    d = route_project(tmp_path)
    assert d.engines == ["tectonic", "xelatex"]


def test_route_usepackage_pstricks_still_xelatex(tmp_path: Path) -> None:
    """真 pstricks：显式 usepackage 声明 → xelatex 优先。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{pstricks}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    assert route_project(tmp_path).engines[0] == "xelatex"


def test_route_pstricks_pkg_list_nonfirst(tmp_path: Path) -> None:
    """非首元素声明 {amsmath,pstricks}（旧 pattern 漏收形态）→ xelatex。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{amsmath,pstricks}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    assert route_project(tmp_path).engines[0] == "xelatex"


def test_route_pstricks_family_pkgs(tmp_path: Path) -> None:
    """pst-* 家族与 pstricks-add（选项形式）→ xelatex。"""
    (tmp_path / "a.tex").write_text(
        "\\documentclass{article}\n\\usepackage[dvips]{pstricks-add}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    assert route_project(tmp_path).engines[0] == "xelatex"
    (tmp_path / "a.tex").write_text(
        "\\documentclass{article}\n\\usepackage{pst-plot}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    assert route_project(tmp_path).engines[0] == "xelatex"


def test_route_pspicture_env_still_xelatex(tmp_path: Path) -> None:
    """无包声明但有 pspicture 环境（传递装载形态）→ xelatex。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{pspicture}(0,0)(1,1)x\\end{pspicture}\n\\end{document}\n"
    )
    assert route_project(tmp_path).engines[0] == "xelatex"


def test_route_psset_still_xelatex(tmp_path: Path) -> None:
    """\\psset 兜底信号：vendored/传递装载 pstricks 的文档证据
    （0905.2435/0905.4369：vendored pstricks.tex 唯此命中）。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\psset{unit=1cm}x\\end{document}\n"
    )
    assert route_project(tmp_path).engines[0] == "xelatex"


def test_route_pstricks_uppercase_ext(tmp_path: Path) -> None:
    r"""``.TEX`` 文件同样进路由扫描——pstricks 不因大写扩展名漏检。"""
    (tmp_path / "PAPER.TEX").write_text(
        "\\documentclass{article}\n\\usepackage{pstricks}\n"
        "\\begin{document}\nx\\end{document}\n"
    )
    assert route_project(tmp_path).engines[0] == "xelatex"
