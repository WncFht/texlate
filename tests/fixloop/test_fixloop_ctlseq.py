r"""chineseclear 车道 (task #93): ``ctlseq_already_def_undefine`` 规则 +
``ctlseq_undefine`` builtin。

2403.00013 (kaist-ucs.cls) 形: ``\documentclass`` 内 cls 链
(``\RequirePackage[nonfrench]{dhucs}`` → xetexko.sty ``\let\chinese\Schinese``)
先定义 ``\chinese``; 我们注入的 ctex 行 ctex.sty:500 ``\cs_new:Npn \chinese``
expl3 ``\cs_if_exist`` 恒拒 → ``Control sequence \chinese already defined``
(无 Command 关键字 → category=other payload=None, already_def_* 三家够不到)。

修 = docclass 缝顶 (注入 ctex 行**之前**) csname-let 清位 —— cls 先定义
已跑、注入块后定义未跑的序位由 file 门 (错误文件 ∈ CJK 块装载树) + texlate
注入标记双闸保证。
"""

from pathlib import Path

from _fixloopkit import EngStub, apply, mk_ctx, rule
from test_fixloop_csfix2 import _proj

from texlate.compile.fixloop import actions, load_ruleset

_RID = "ctlseq_already_def_undefine"

_ERR = (
    "/usr/share/texmf-dist/tex/latex/ctex/ctex.sty:500: LaTeX Error: "
    "Control sequence \\chinese already defined."
)

_MAIN = (
    "\\documentclass{kaist-ucs}\n"
    "\\usepackage[fontset=fandol,UTF8,zihao=false]{ctex}  % [texlate injected]\n"
    "\\usepackage{amsmath}\n"
    "\\begin{document}\nx\n\\end{document}\n"
)


def _apply(tmp_path: Path, err_head: str = _ERR) -> tuple[bool, str]:
    return apply(_RID, mk_ctx(tmp_path, err_head=err_head), None)


def _cond(tmp_path: Path, err_head: str = _ERR) -> tuple[bool, str]:
    r = rule(_RID)
    return actions._cond_ok(  # noqa: SLF001
        r.condition, r, mk_ctx(tmp_path, err_head=err_head), EngStub(), None
    )


def _write_main(tmp_path: Path, text: str = _MAIN) -> None:
    _proj(tmp_path, {"main.tex": text})


def test_ctlseq_rule_registered() -> None:
    r = rule(_RID)
    assert r.order == 110.8  # noqa: PLR2004 - schema 断言值
    assert r.action["kind"] == "builtin_transform"
    assert r.action["function"] == "ctlseq_undefine"


def test_ctlseq_cond_passes_signature() -> None:
    ok, why = _cond(Path("/nonexistent"))
    assert ok, why


def test_ctlseq_cond_declines_command_form(tmp_path: Path) -> None:
    """``Command \\X already defined`` 是 already_def 面, 本格不接。"""
    ok, _ = _cond(
        tmp_path, "foo.sty:10: LaTeX Error: Command \\chinese already defined"
    )
    assert not ok


def test_ctlseq_cond_declines_expl3_internal(tmp_path: Path) -> None:
    r"""``\c__fontspec_*`` 内码名: ``_`` 破邻接, 字母类不捕 → 闸拒。"""
    ok, _ = _cond(
        tmp_path,
        "fontspec-xetex.sty:4166: LaTeX Error: Control sequence "
        "\\c__fontspec_shape_it_sc_tl already defined",
    )
    assert not ok


def test_ctlseq_apply_injects_before_ctex(tmp_path: Path) -> None:
    r"""csname-let 清位串落在 \documentclass 后、注入 ctex 行前。"""
    _write_main(tmp_path)
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\csname chinese\\endcsname\\TeXlateUndefCs" in t
    i_let = t.index("\\csname chinese\\endcsname")
    i_ctex = t.index("{ctex}")
    i_docclass = t.index("\\documentclass")
    assert i_docclass < i_let < i_ctex
    assert "\\makeatletter" not in t
    assert "\\makeatother" not in t


def test_ctlseq_apply_declines_foreign_file(tmp_path: Path) -> None:
    """错误文件不在 CJK 块装载树 (hyperref.sty) → 拒。"""
    _write_main(tmp_path)
    ok, _ = _apply(
        tmp_path,
        "/usr/share/texmf-dist/tex/latex/hyperref/hyperref.sty:4000: "
        "LaTeX Error: Control sequence \\chinese already defined.",
    )
    assert not ok
    assert "\\csname chinese\\endcsname" not in (tmp_path / "main.tex").read_text()


def test_ctlseq_apply_declines_cls_file(tmp_path: Path) -> None:
    """``.cls`` 错误 (缝前 docclass 内执行) → 拒, 缝顶 \\let 鞭长莫及。"""
    _write_main(tmp_path)
    ok, _ = _apply(
        tmp_path,
        "ctexart.cls:100: LaTeX Error: Control sequence \\chinese already defined.",
    )
    assert not ok


def test_ctlseq_apply_declines_no_inject_mark(tmp_path: Path) -> None:
    """ctex 撞名但无 texlate 注入块 (用户自备 ctex) → 拒。"""
    _write_main(
        tmp_path,
        "\\documentclass{article}\n\\usepackage{ctex}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, _ = _apply(tmp_path)
    assert not ok


def test_ctlseq_apply_declines_no_docclass(tmp_path: Path) -> None:
    """无 docclass 缝 → 退文件头是 cls 前错序, 拒。"""
    _write_main(
        tmp_path,
        "\\usepackage[fontset=fandol,UTF8,zihao=false]{ctex}  "
        "% [texlate injected]\nx\n",
    )
    ok, _ = _apply(tmp_path)
    assert not ok


def test_ctlseq_apply_declines_reserved_name(tmp_path: Path) -> None:
    r"""原语名 ``\par`` 撞名 → 拒 (清位即全局灾难)。"""
    _write_main(tmp_path)
    ok, _ = _apply(
        tmp_path,
        "/usr/share/texmf-dist/tex/latex/ctex/ctex.sty:500: LaTeX Error: "
        "Control sequence \\par already defined.",
    )
    assert not ok


def test_ctlseq_apply_batch_multi_names(tmp_path: Path) -> None:
    """log 内同文件簇多撞名一轮批清 (xecjk+zhnumber 各一)。"""
    _write_main(tmp_path)
    err = (
        "/usr/share/texmf-dist/tex/latex/ctex/ctex.sty:500: LaTeX Error: "
        "Control sequence \\chinese already defined.\n"
        "/usr/share/texmf-dist/tex/xelatex/xecjk/xeCJK.sty:80: LaTeX Error: "
        "Control sequence \\CJKfontspec already defined."
    )
    ok, note = _apply(tmp_path, err)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\csname chinese\\endcsname\\TeXlateUndefCs" in t
    assert "\\csname CJKfontspec\\endcsname\\TeXlateUndefCs" in t


def test_ctlseq_apply_skips_nonfamily_names_in_blob(tmp_path: Path) -> None:
    """blob 内非族文件撞名不连坐: 只清 ctex 名, hyperref 名留下。"""
    _write_main(tmp_path)
    err = (
        "/usr/share/texmf-dist/tex/latex/ctex/ctex.sty:500: LaTeX Error: "
        "Control sequence \\chinese already defined.\n"
        "/usr/share/texmf-dist/tex/latex/hyperref/hyperref.sty:4000: "
        "LaTeX Error: Control sequence \\pdfname already defined."
    )
    ok, _ = _apply(tmp_path, err)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert "\\csname chinese\\endcsname\\TeXlateUndefCs" in t
    assert "\\csname pdfname\\endcsname" not in t


def test_ctlseq_apply_idempotent_second_round(tmp_path: Path) -> None:
    """二轮复跑: \\let 已落 → applied=False 不再复写。"""
    _write_main(tmp_path)
    ok1, _ = _apply(tmp_path)
    assert ok1
    ok2, note2 = _apply(tmp_path)
    assert not ok2
    assert "already cleared" in note2


def test_ctlseq_apply_multi_seam(tmp_path: Path) -> None:
    """\\ifpdf 双 docclass 形态: 两缝各注 \\let, 均在各自 ctex 行前。"""
    _write_main(
        tmp_path,
        "\\ifpdf\n\\documentclass{kaist-ucs}\n"
        "\\usepackage[fontset=fandol,UTF8,zihao=false]{ctex}  "
        "% [texlate injected]\n"
        "\\else\n\\documentclass{article}\n"
        "\\usepackage[fontset=fandol,UTF8,zihao=false]{ctex}  "
        "% [texlate injected]\n\\fi\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    ok, _ = _apply(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text()
    assert t.count("\\csname chinese\\endcsname\\TeXlateUndefCs") == 2  # noqa: PLR2004 - 双缝各一


def test_ctlseq_apply_at_name_internal_declined(tmp_path: Path) -> None:
    r"""``@`` 内码名 ``\ctex@fontsize``: 字母类在 ``@`` 处断 → 不捕 → 拒。"""
    _write_main(tmp_path)
    ok, _ = _apply(
        tmp_path,
        "/usr/share/texmf-dist/tex/latex/ctex/ctex.sty:500: LaTeX Error: "
        "Control sequence \\ctex@fontsize already defined.",
    )
    assert not ok


def test_ctlseq_apply_no_fileline_prefix_declined(tmp_path: Path) -> None:
    """非 file-line-error 形 (无 ``file:N:`` 前缀) → 不定界拒。"""
    _write_main(tmp_path)
    ok, _ = _apply(
        tmp_path, "! LaTeX Error: Control sequence \\chinese already defined."
    )
    assert not ok


def test_ctlseq_ruleset_loads() -> None:
    rs = load_ruleset()
    assert len(rs.rules) >= 114  # noqa: PLR2004 - 库规模断言
