r"""表族钳宽 v2 + legacy 整剥钉测试 (0930 TABLE_FITTING 拔除连锁)。

inject ``TABLE_FITTING`` (compile/layout.py 已拔) 与 fixloop v1
``TeXlateTabClamp`` 成对钩残块: ``env/E/before+after`` 钩法在 begin/end
配对不候场形 (cls ``\@tabular`` cs 形收尾/宏内 env/早退 ``\end{document}``)
崩成 ``ended by`` 失衡毁编——0930 vault 普查 ~1200 事件 (``TabClamp
ended by \end{TeXlateFitTable}`` 系 774 为最大单簇)。v2 换栈配对源级
跨度包 + ``legacy_clamp_purge`` 专职中和在席残块 + 数学域守卫
(``\ifmmode`` 臂静态等价)。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from _fixloopkit import mk_ctx_files, rule

from texlate.compile.fixloop.builtins import TRANSFORM_FNS

if TYPE_CHECKING:
    from pathlib import Path

# 席稿实形 (0806.4887/-@v1.1 vis_2.tex:275/359 双块并存):
_FIT_BLOCK = r"""% texlate: fit complete measured table containers v2
\RequirePackage{adjustbox}
\begingroup
\makeatletter
\AtBeginDocument{%
\newif\iftexlate@tablefit
\newenvironment{TeXlateFitTable}{%
\iftexlate@tablefit
\let\texlate@endtablefit\relax
\else\ifmmode
\let\texlate@endtablefit\relax
\else
\texlate@tablefittrue
\def\texlate@endtablefit{\end{adjustbox}}%
\begin{adjustbox}{max width=\linewidth,max totalheight=\textheight}%
\fi\fi\ignorespaces
}{\texlate@endtablefit}%
\AddToHook{env/tabular/before}{\begin{TeXlateFitTable}}%
\AddToHook{env/tabular/after}{\end{TeXlateFitTable}}%
}
\endgroup
"""

_CLAMP_BLOCK = r"""% texlate-fixloop: table width clamp v1
\usepackage{adjustbox}
\begingroup
\makeatletter
\AtBeginDocument{%
\newif\iftexlate@tabclampin
\newenvironment{TeXlateTabClamp}{%
\iftexlate@tabclampin
\let\texlate@endtabclamp\relax
\else
\texlate@tabclampintrue
\def\texlate@endtabclamp{\end{adjustbox}}%
\begin{adjustbox}{max width=\linewidth}%
\fi\ignorespaces
}{\texlate@endtabclamp}%
\AddToHook{env/tabular/before}{\begin{TeXlateTabClamp}}%
\AddToHook{env/tabular/after}{\end{TeXlateTabClamp}}%
\AddToHook{env/longtable/begin}{\footnotesize\setlength{\tabcolsep}{2pt}\relax}%
}
\endgroup
"""


def test_legacy_clamp_purge_strips_both_blocks(tmp_path: Path) -> None:
    """双块并存席稿整剥：钩行/env 定义清零，文档本体不动。"""
    doc = (
        "\\documentclass{article}\n"
        + _FIT_BLOCK
        + _CLAMP_BLOCK
        + "\\begin{document}\nx\n"
        "\\begin{tabular}{ll}\na&b\\\\\n\\end{tabular}\n"
        "\\end{document}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": doc})
    ok, note = TRANSFORM_FNS["legacy_clamp_purge"](ctx, None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "TeXlateFitTable" not in t
    assert "TeXlateTabClamp" not in t
    assert "AddToHook" not in t
    assert "\\begin{tabular}{ll}" in t
    assert "\\begin{document}" in t


def test_legacy_clamp_purge_stray_hook_lines(tmp_path: Path) -> None:
    """块边界失配形态：marker 块已截，散 ``\\AddToHook`` 行兜底单剥。"""
    doc = (
        "\\documentclass{article}\n"
        "\\AddToHook{env/tabular/before}{\\begin{TeXlateFitTable}}%\n"
        "\\AddToHook{env/tabularx/after}{\\end{TeXlateTabClamp}}%\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": doc})
    ok, note = TRANSFORM_FNS["legacy_clamp_purge"](ctx, None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "TeXlate" not in t
    assert "AddToHook" not in t


def test_legacy_clamp_purge_negative(tmp_path: Path) -> None:
    doc = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    ctx = mk_ctx_files(tmp_path, {"main.tex": doc})
    ok, note = TRANSFORM_FNS["legacy_clamp_purge"](ctx, None, None, {})
    assert not ok
    assert "no legacy" in note


def test_tabular_fit_wraps_box_and_strips_legacy(tmp_path: Path) -> None:
    """v2 主路径：legacy 块整剥 + 外层 tabular 文本级 adjustbox 包。"""
    doc = (
        "\\documentclass{article}\n" + _FIT_BLOCK + "\\begin{document}\n"
        "\\begin{tabular}{ll}\na&b\\\\\n\\end{tabular}\n"
        "\\end{document}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": doc})
    ok, note = TRANSFORM_FNS["tabular_fit"](ctx, None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "TeXlateFitTable" not in t
    assert "% texlate-fixloop: table width clamp v2" in t
    assert (
        "\\begin{adjustbox}{max width=\\linewidth,max totalheight=\\textheight}\n"
        "\\begin{tabular}{ll}"
    ) in t
    assert "\\end{tabular}\n\\end{adjustbox}" in t
    assert t.count("\\begin{adjustbox}") == 1


def test_tabular_fit_skips_math_region(tmp_path: Path) -> None:
    r"""``$\begin{tabular}$`` 内联形不包 (盒材料楔进数学模式即崩)。"""
    doc = (
        "\\documentclass{article}\n\\begin{document}\n"
        "inline $\\begin{tabular}{l}\nc\\end{tabular}$ math\n"
        "\\begin{tabular}{ll}\na&b\\\\\n\\end{tabular}\n"
        "\\end{document}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": doc})
    ok, note = TRANSFORM_FNS["tabular_fit"](ctx, None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert t.count("\\begin{adjustbox}") == 1
    math_tab = t.index("$\\begin{tabular}{l}")
    assert "\\begin{adjustbox}" not in t[math_tab - 100 : math_tab]


def test_tabular_fit_idempotent_second_pass(tmp_path: Path) -> None:
    """已包跨度前缀幂等跳过——二跑无新编辑。"""
    doc = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{tabular}{ll}\na&b\\\\\n\\end{tabular}\n"
        "\\end{document}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": doc})
    ok, _ = TRANSFORM_FNS["tabular_fit"](ctx, None, None, {})
    assert ok
    t1 = (tmp_path / "main.tex").read_text(encoding="utf-8")
    ok2, note2 = TRANSFORM_FNS["tabular_fit"](ctx, None, None, {})
    assert not ok2, note2
    t2 = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert t2.count("\\begin{adjustbox}") == 1
    assert t2 == t1


def test_tabular_fit_nested_only_outer_wrapped(tmp_path: Path) -> None:
    """嵌套表族只包最外层 (外层盒已罩内层)。"""
    doc = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\begin{tabular}{l}\n"
        "\\begin{tabular}{ll}\nx&y\\\\\n\\end{tabular}\n"
        "\\end{tabular}\n"
        "\\end{document}\n"
    )
    ctx = mk_ctx_files(tmp_path, {"main.tex": doc})
    ok, _ = TRANSFORM_FNS["tabular_fit"](ctx, None, None, {})
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert t.count("\\begin{adjustbox}") == 1


def test_legacy_clamp_purge_rule_registered() -> None:
    r = rule("legacy_clamp_purge")
    assert r.when["category"] == "env_mismatch"
    assert r.action["function"] == "legacy_clamp_purge"
    assert "legacy_clamp_purge" in TRANSFORM_FNS
