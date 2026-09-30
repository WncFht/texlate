r"""shipwrap 车道 (2026-09-19): ``shipped_sty_input_wrap`` 规则钉。

shipclscen census: 随源 ``.cls``/``.sty`` 内部裸 ``\input X.sty`` 站 ——
``\input`` 以宿主当前 @ catcode 读件, 宿主经裸 ``\input``/2.09 option
链载入 (@=other) 时载入件内 @-cs 全裂 → Missing ``\begin{document}``
级联 (aipproc.cls:10 ``\input{aipproc.sty}`` 型)。包裹取 svglov3.clo
exact-restore idiom: ``\edef`` 存 ``\catcode 64`` 现值 → ``=11`` 读件
→ 复元 —— @=letter 宿主下恒等, 裸 ``\makeatletter/\makeatother`` 对
会把 letter 宿主尾段强翻回 12 (1608.06693 ``15\p@`` 实证)。
"""

from pathlib import Path

from _fixloopkit import apply, mk_ctx, rule

from texlate.compile.fixloop._builtins_pkgload import (
    _SHIP_STY_INPUT_RE,
    _SHIP_WRAP_POST,
    _SHIP_WRAP_PRE,
    _sty_input_sites,
    _wrap_shipped_sty_inputs,
)

_RULE_ID = "shipped_sty_input_wrap"


def _apply(tmp_path: Path) -> tuple[bool, str]:
    return apply(_RULE_ID, mk_ctx(tmp_path), None)


def test_shipwrap_rule_registered() -> None:
    rl = rule(_RULE_ID)
    assert rl.phase == "precheck"
    assert rl.order == -0.5  # noqa: PLR2004 - schema 断言值
    assert rl.action["kind"] == "builtin_transform"
    assert rl.action["function"] == "shipped_sty_input_wrap"
    assert "input" in rl.condition["source_contains"]


def test_wrap_braced_site() -> None:
    """aipproc.cls:10 形: 顶层 ``\\input{X.sty}`` 补存复对。"""
    src = "\\ProvidesClass{foo}\n\\input{macros.sty}\n\\def\\x@y{1}\n"
    out, n = _wrap_shipped_sty_inputs(src)
    assert n == 1
    assert (_SHIP_WRAP_PRE + "\\input{macros.sty}" + _SHIP_WRAP_POST) in out
    # restore cs 名纯字母 —— 宿主 @=other 下带 @ 的名自断签名
    assert "@" not in _SHIP_WRAP_PRE
    assert "@" not in _SHIP_WRAP_POST
    assert "\\catcode 64=11" in out


def test_wrap_bare_site() -> None:
    """裸 ``\\input foo.sty`` (无花括号) 同裹, post 前导空格断文件名。"""
    src = "\\input apjfonts.sty\n\\relax\n"
    out, n = _wrap_shipped_sty_inputs(src)
    assert n == 1
    assert "\\input apjfonts.sty \\TeXlateStyInRestore" in out


def test_skip_at_letter_region() -> None:
    """显式 ``\\makeatletter`` 区内站点不重包 (at_letter=True 跳过)。"""
    src = "\\makeatletter\n\\input{inner.sty}\n\\makeatother\n\\input{outer.sty}\n"
    out, n = _wrap_shipped_sty_inputs(src)
    assert n == 1
    assert "\\makeatletter\n\\input{inner.sty}\n\\makeatother\n" in out
    assert _SHIP_WRAP_PRE + "\\input{outer.sty}" + _SHIP_WRAP_POST in out


def test_skip_nested_group() -> None:
    """``{}`` 组内站点 (延迟/局部执行) 不裹。"""
    src = "\\AtEndOfClass{\\input{late.sty}}\n\\input{top.sty}\n"
    out, n = _wrap_shipped_sty_inputs(src)
    assert n == 1
    assert "\\AtEndOfClass{\\input{late.sty}}\n" in out
    assert _SHIP_WRAP_PRE + "\\input{top.sty}" in out


def test_skip_commented_site() -> None:
    """``%`` 注释内假装载点不裹 (mask_tex 遮盖)。"""
    src = "% \\input{dead.sty}\n\\input{live.sty}\n"
    out, n = _wrap_shipped_sty_inputs(src)
    assert n == 1
    assert "% \\input{dead.sty}\n" in out
    assert _SHIP_WRAP_PRE + "\\input{live.sty}" in out


def test_no_site_returns_unchanged() -> None:
    src = "\\documentclass{article}\n\\begin{document}\nx\n"
    out, n = _wrap_shipped_sty_inputs(src)
    assert n == 0
    assert out == src


def test_209_option_file_shape() -> None:
    """thp.sty:54 形: ``\\@ifundefined`` 守卫旁的 ``\\input{theorem.sty}`` 站。

    守卫 cs 本身在 ``{}`` 组内不算顶层站, 但 2.09-era option 件常是
    深度 0 裸 ``\\input`` —— 裹上后载入件 @-cs 不再断名。
    """
    src = (
        "\\ProvidesPackage{thp}\n"
        "\\@ifundefined{theorem@style}{\\input{theorem.sty}}{}\n"
        "\\input{theold.sty}\n"
    )
    out, n = _wrap_shipped_sty_inputs(src)
    assert n == 1
    assert _SHIP_WRAP_PRE + "\\input{theold.sty}" + _SHIP_WRAP_POST in out


def test_builtin_wraps_shipped_cls(tmp_path: Path) -> None:
    """actions._apply 全链: 随源 .cls 内站点落盘改写。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{aipproc}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "aipproc.cls").write_text(
        "\\ProvidesClass{aipproc}\n\\input{aipproc.sty}\n\\def\\x@y{1}\n",
        encoding="utf-8",
    )
    (tmp_path / "aipproc.sty").write_text(
        "\\ProvidesPackage{aipproc}\n\\@maxsep 20pt\n", encoding="utf-8"
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "aipproc.cls").read_text()
    assert _SHIP_WRAP_PRE + "\\input{aipproc.sty}" + _SHIP_WRAP_POST in t
    assert (tmp_path / "aipproc.sty").read_text() == (
        "\\ProvidesPackage{aipproc}\n\\@maxsep 20pt\n"
    )


def test_builtin_wraps_fragment_tex(tmp_path: Path) -> None:
    """``\\begin{document}`` 缺席的 fragment .tex —— input_sty 两臂前瞻闸
    够不着的站点由本规则收网。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "frag.tex").write_text(
        "\\input{localdefs.sty}\ntext\n", encoding="utf-8"
    )
    ok, _note = _apply(tmp_path)
    assert ok
    t = (tmp_path / "frag.tex").read_text()
    assert _SHIP_WRAP_PRE + "\\input{localdefs.sty}" + _SHIP_WRAP_POST in t


def test_builtin_no_site_false(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "plain.sty").write_text(
        "\\ProvidesPackage{plain}\n\\input{macros.tex}\n", encoding="utf-8"
    )
    ok, _note = _apply(tmp_path)
    assert not ok


def test_sites_walker_param() -> None:
    """``_sty_input_sites`` 通用形: 任意 ``.sty`` 目标站尽收。"""
    src = "\\input{a.sty}\n\\input{b.sty}\n"
    sites = _sty_input_sites(src, _SHIP_STY_INPUT_RE)
    assert len(sites) == 2  # noqa: PLR2004 - 两站断言值
    assert src[sites[0][0] : sites[0][1]] == "\\input{a.sty}"
    assert src[sites[1][0] : sites[1][1]] == "\\input{b.sty}"
