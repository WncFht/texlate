r"""impl2 pack-24 回归钉 —— 遮盖视图站点纪律 / 元素级包名判 / 路径安全 / 缝序判。

六族各钉一条旧实现的真实误伤面:

- ``_drop_pkg_loads``: ``\b<pkg>\b`` 子串形把 ``{physics-tools}`` 连字符
  兄弟名撕残 —— 元素级 ``_load_elems`` 判后兄弟名原样保留。
- ``pdfstring_cs_disarm``: ``\@x`` 族肇事名注入位宿主 @=12, 裸
  ``\def\@x{}`` 断名 —— ``\expandafter\def\csname`` 形任意 catcode 同读。
- ``premature_cs_guard`` seam 臂: 「供方任意位已装即跳」把供方**晚于**
  调用点的序颠倒稿误当已供 —— ``_seam_prov_covered`` 按执行序判
  (main 直查 / ``\input`` 件查引用站位)。
- ``bbl_stub_rewrite``: ``\input`` 目标按编译 cwd (``main.parent``) 落
  relpath + 只认含 ``thebibliography`` 的真 bbl + 遮盖视图全量改写
  (注释内假装载点不动)。
- ``font_sub_shim``: 装载点与 cs 改写皆遮盖视图定位 —— 注释内假
  装载点/假调用不改写。
- ``llm_hook._banned``: ``\openout\w=x``/``\read\w to\x`` 的流号/目标
  cs 先吃掉 (旧尾哨兵把 ``\w=x`` 误当绝对路径); ``arg``/``arg2`` 实参
  逐组件判 ``.``/``..``/绝对位 —— 中位 ``sub/../x`` 不再直通。
"""

from pathlib import Path

from _fixloopkit import mk_ctx
from test_fixloop_loop import MockEngine

from texlate.compile.fixloop._builtins_bib import bbl_stub_rewrite
from texlate.compile.fixloop._builtins_common import _drop_pkg_loads
from texlate.compile.fixloop._builtins_docfix import (
    pdfstring_cs_disarm,
    premature_cs_guard,
)
from texlate.compile.fixloop._builtins_pkgload import font_sub_shim
from texlate.compile.fixloop.llm_hook import _banned


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ═══════════ _drop_pkg_loads 元素级判 ═══════════


def test_drop_pkg_loads_hyphenated_sibling_untouched() -> None:
    """``{physics-tools}`` 剥 ``physics`` —— 旧 ``\\b`` 子串撕残 ``-tools``,
    元素级判后零摘除、文本原样。"""
    t = "\\documentclass{article}\n\\usepackage{physics-tools}\n"
    nt, n = _drop_pkg_loads(t, "physics")
    assert n == 0
    assert nt == t


def test_drop_pkg_loads_list_element() -> None:
    """逗号列 ``{a,physics,b}`` 只摘 ``physics`` 元素 → ``{a,b}``。"""
    nt, n = _drop_pkg_loads("\\usepackage{a,physics,b}\n", "physics")
    assert n == 1
    assert nt == "\\usepackage{a,b}\n"


def test_drop_pkg_loads_sole_element_comments_line() -> None:
    """独载行整行注释 (旧行为保留) —— 摘除数 1, 包名不再 live。"""
    nt, n = _drop_pkg_loads("x\n\\usepackage{physics}\ny\n", "physics")
    assert n == 1
    assert "% fixloop: stripped \\usepackage{physics}" in nt
    assert "\\usepackage{a" not in nt


# ═══════════ pdfstring_cs_disarm csname 形 ═══════════


def test_pdfstring_cs_disarm_at_cs_uses_csname(tmp_path: Path) -> None:
    r"""``\@x`` 肇事 → ``\expandafter\def\csname @x\endcsname{}`` 空降格
    (注入位宿主 @=12 时裸 ``\def\@x{}`` 断名成 ``\@``+裸字母)。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
    )
    err = (
        "! Improper alphabetic constant.\n"
        "<to be read again> \n"
        "                   \\@x\n"
        "l.302 \\maketitle\n"
    )
    ok, note = pdfstring_cs_disarm(mk_ctx(tmp_path, err_head=err), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\expandafter\\def\\csname @x\\endcsname{}" in t
    assert "\\def\\@x{}" not in t


# ═══════════ premature_cs_guard seam 臂执行序判 ═══════════


def test_premature_seam_injects_when_provider_after_call(tmp_path: Path) -> None:
    r"""main 内 ``\numberwithin`` 先于 ``\usepackage{amsmath}`` —— 序颠倒
    不豁免, docclass 缝仍注供方。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "\\numberwithin{equation}{section}\n"
        "\\usepackage{amsmath}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    err = (
        "./main.tex:2: LaTeX Error: Missing \\begin{document}.\nl.2 \\numberwithin{e\n"
    )
    ctx = mk_ctx(tmp_path, err_head=err)
    eng = MockEngine([], available={"amsmath.sty"})
    ok, note = premature_cs_guard(ctx, eng, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\RequirePackage{amsmath} % fixloop: premature provider" in t


def test_premature_seam_abstains_when_provider_before_call(tmp_path: Path) -> None:
    r"""``\usepackage{amsmath}`` 先于 ``\numberwithin`` 调用点 —— 执行序
    已供, seam 臂豁免 (旧「任意位已装即跳」面下此处亦跳, 钉的是判据换位
    后真覆盖仍跳、不重复注)。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "\\usepackage{amsmath}\n"
        "\\numberwithin{equation}{section}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    err = (
        "./main.tex:3: LaTeX Error: Missing \\begin{document}.\nl.3 \\numberwithin{e\n"
    )
    ctx = mk_ctx(tmp_path, err_head=err)
    eng = MockEngine([], available={"amsmath.sty"})
    ok, _note = premature_cs_guard(ctx, eng, None, {})
    assert not ok
    t = (tmp_path / "main.tex").read_text()
    assert "fixloop: premature provider" not in t


def test_premature_seam_input_offender_covered(tmp_path: Path) -> None:
    r"""``\input{sub}`` 件内肇事 —— includer 内供方装载先于引用站位 →
    执行序已供, 豁免。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "\\usepackage{amsmath}\n"
        "\\input{sub}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    _write(tmp_path, "sub.tex", "\\numberwithin{equation}{section}\n")
    err = "./sub.tex:1: LaTeX Error: Missing \\begin{document}.\nl.1 \\numberwithin{e\n"
    ctx = mk_ctx(tmp_path, err_head=err)
    eng = MockEngine([], available={"amsmath.sty"})
    ok, _note = premature_cs_guard(ctx, eng, None, {})
    assert not ok
    t = (tmp_path / "main.tex").read_text()
    assert "fixloop: premature provider" not in t


def test_premature_seam_input_offender_late_provider(tmp_path: Path) -> None:
    r"""``\input{sub}`` 先于 ``\usepackage{amsmath}`` —— 引用站位执行时
    供方未装, 序颠倒不豁免 → 缝注。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "\\input{sub}\n"
        "\\usepackage{amsmath}\n"
        "\\begin{document}\nx\n\\end{document}\n",
    )
    _write(tmp_path, "sub.tex", "\\numberwithin{equation}{section}\n")
    err = "./sub.tex:1: LaTeX Error: Missing \\begin{document}.\nl.1 \\numberwithin{e\n"
    ctx = mk_ctx(tmp_path, err_head=err)
    eng = MockEngine([], available={"amsmath.sty"})
    ok, note = premature_cs_guard(ctx, eng, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\RequirePackage{amsmath} % fixloop: premature provider" in t


# ═══════════ bbl_stub_rewrite relpath + usable 门 + 遮盖站点 ═══════════

_BBL = "\\begin{thebibliography}{9}\\end{thebibliography}\n"


def test_bbl_stub_rewrite_skips_commented_site(tmp_path: Path) -> None:
    r"""注释内 ``% \bibliography`` 不改写 —— 遮盖视图只收 live 站。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n"
        "% \\bibliography{old}\n\\bibliography{refs}\n\\end{document}\n",
    )
    _write(tmp_path, "main.bbl", _BBL)
    ok, note = bbl_stub_rewrite(mk_ctx(tmp_path), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert t.count("\\input{main.bbl}") == 1
    assert "% \\bibliography{old}" in t


def test_bbl_stub_rewrite_subdir_bbl_relpath(tmp_path: Path) -> None:
    r"""bbl 在 ``sub/`` —— ``\input{sub/main.bbl}`` 相对编译 cwd (wdir),
    非裸 basename (kpathsea 按 cwd 解析, 嵌套稿裸名会断)。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n"
        "\\bibliography{refs}\n\\end{document}\n",
    )
    _write(tmp_path, "sub/main.bbl", _BBL)
    ok, note = bbl_stub_rewrite(mk_ctx(tmp_path), None, None, {})
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\input{sub/main.bbl}" in t


def test_bbl_stub_rewrite_declines_stub_bbl(tmp_path: Path) -> None:
    r"""无 ``thebibliography`` 的 24 行 stub bbl 不接 —— decline, 源不动。"""
    main = _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n"
        "\\bibliography{refs}\n\\end{document}\n",
    )
    _write(tmp_path, "main.bbl", "% tectonic stub\n\\relax\n")
    before = main.read_text()
    ok, note = bbl_stub_rewrite(mk_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no usable .bbl" in note
    assert main.read_text() == before


def test_bbl_stub_rewrite_declines_cwd_escape(tmp_path: Path) -> None:
    r"""main 在 ``sub/``、bbl 在上一级 —— relpath ``../main.bbl`` 越出编译
    cwd → decline (kpathsea ``..`` 不可达 + 不写逃逸目标)。"""
    main = _write(
        tmp_path,
        "sub/main.tex",
        "\\documentclass{article}\n\\begin{document}\nx\n"
        "\\bibliography{refs}\n\\end{document}\n",
    )
    _write(tmp_path, "main.bbl", _BBL)
    before = main.read_text()
    ctx = mk_ctx(tmp_path, main_rel="sub/main.tex")
    ok, note = bbl_stub_rewrite(ctx, None, None, {})
    assert not ok
    assert "escapes compile cwd" in note
    assert main.read_text() == before


# ═══════════ font_sub_shim 遮盖站点 ═══════════


def test_font_sub_shim_skips_commented_sites(tmp_path: Path) -> None:
    r"""注释内 ``% \usepackage{bbm}``/``% \mathbbm`` 不改写; live 装载点
    换 ``dsfont`` + live cs 换 ``\mathds``。"""
    _write(
        tmp_path,
        "main.tex",
        "\\documentclass{article}\n"
        "% \\usepackage{bbm}\n"
        "\\usepackage{bbm}\n"
        "\\begin{document}\n"
        "% $\\mathbbm{x}$\n"
        "$\\mathbbm{x}$\n"
        "\\end{document}\n",
    )
    params = {
        "shim_map": {"bbm": {"usepackage": "dsfont", "cs_map": {"mathbbm": "mathds"}}}
    }
    ok, note = font_sub_shim(mk_ctx(tmp_path), None, None, params)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\usepackage{dsfont}" in t
    assert "$\\mathds{x}$" in t
    assert "% \\usepackage{bbm}" in t
    assert "% $\\mathbbm{x}$" in t


# ═══════════ llm_hook._banned 装载宏实参判 ═══════════


def test_banned_openout_stream_cs_safe() -> None:
    r"""``\openout\w=x`` —— 流号 cs ``\w`` + ``=`` 先吃掉, 文件名 ``x``
    非路径 → 不拒 (旧尾哨兵把 ``\w=x`` 的 ``\`` 当分隔误判绝对路径)。"""
    assert _banned("\\openout\\w=x") is None


def test_banned_read_to_cs_safe() -> None:
    r"""``\read\w to\x`` —— ``to`` 臂吃掉目标 cs, 无实参 → 不拒。"""
    assert _banned("\\read\\w to\\x") is None


def test_banned_plain_input_safe() -> None:
    r"""``\input{ok}`` 相对裸名 → 不拒。"""
    assert _banned("\\input{ok}") is None


def test_banned_midpath_dotdot_rejected() -> None:
    r"""``\input{sub/../x}`` —— 中位 ``..`` 组件逐段判出 (旧行首前哨直通)。"""
    assert _banned("\\input{sub/../x}") == "absolute/.. path in file-loading macro"


def test_banned_dot_component_rejected() -> None:
    r"""``\input{./x}`` —— ``.`` 组件维持旧禁。"""
    assert _banned("\\input{./x}") == "absolute/.. path in file-loading macro"


def test_banned_import_second_arg_rejected() -> None:
    r"""``\import{../d}{f}`` —— ``arg2`` 双参形的 ``{f}`` 之外, 首参
    ``{../d}`` 逐组件判出。"""
    assert _banned("\\import{../d}{f}") == "absolute/.. path in file-loading macro"


def test_banned_absolute_path_rejected() -> None:
    r"""``\verbatiminput{/etc/passwd}`` —— 绝对路径拒。"""
    why = "absolute/.. path in file-loading macro"
    assert _banned("\\verbatiminput{/etc/passwd}") == why


def test_banned_windows_drive_rejected() -> None:
    r"""``\input{C:/x}`` —— 盘符绝对形拒。"""
    why = "absolute/.. path in file-loading macro"
    assert _banned("\\input{C:/x}") == why
