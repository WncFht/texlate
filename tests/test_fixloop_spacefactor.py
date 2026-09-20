r"""spacefactor lane (2026-09-19): ``spacefactor_atdef_wrap`` 规则钉 + 走查单元。

``\@`` = ``\spacefactor\@m`` 间距宏; ``@``=catcode-12 下 ``\@cs`` 断名成
``\@``+裸字母 → 展开点 ``\@`` 执行 → "You can't use `\spacefactor' in
vertical mode" / "in math mode" / "Improper \spacefactor" / "Package calc
Error" 四头 (皆落 other 类)。doc-latent def 站 (``\renewcommand*\l@section``
/``\newcommand\makepapertitle`` 族, 2.09-era cls 内码抄稿) 无
``\makeatletter`` → 修 = def 域 exact-restore @=11 包裹 (svglov3.clo
idiom, 宿主 ambient 不可测时恒等)。
"""

from pathlib import Path

from texlate.compile.fixloop import actions, load_ruleset
from texlate.compile.fixloop._builtins_common import (
    _AT_LETTER_POST,
    _AT_LETTER_PRE,
    _let_cs,
    _undefine_cs,
)
from texlate.compile.fixloop._builtins_docfix import (
    _AT_TOKEN_RE,
    _atdef_sites,
)
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport
from texlate.textutil import mask_tex

_ERR_VMODE = "You can't use `\\spacefactor' in vertical mode."


class _Eng:
    """builtin_transform 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _ctx(tmp_path: Path, err_head: str = _ERR_VMODE) -> LoopCtx:
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")
    ctx.err_head = err_head
    return ctx


def _rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == "spacefactor_atdef_wrap")


def _apply(tmp_path: Path, err_head: str = _ERR_VMODE) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _rule(), _ctx(tmp_path, err_head), _Eng(), None, ErrReport()
    )


def _flagged(src: str) -> list[tuple[int, int]]:
    """``_atdef_sites`` + ``@`` token 判定的完整站点面 (builtin 内部同款)。"""
    vis = mask_tex(src)
    return [
        (s, e)
        for s, e, al in _atdef_sites(vis)
        if not al and _AT_TOKEN_RE.search(vis[s:e])
    ]


def test_rule_registered() -> None:
    rule = _rule()
    assert rule.phase == "loop"
    assert rule.order == 198.5  # noqa: PLR2004 - schema 断言值
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "spacefactor_atdef_wrap"
    assert rule.when["category"] == "other"
    assert "spacefactor" in rule.condition["ctx_suggests"]


def test_wrap_renewcommand_lsection() -> None:
    """1206.0445 形: ``\\renewcommand*\\l@section[2]{...\\@secpenalty...}``
    整域包裹, 域内 ``\\@`` 与 ``\\hb@xt@`` 一并罩住。"""
    src = (
        "\\documentclass{article}\n"
        "\\renewcommand*\\l@section[2]{%\n"
        "  \\addpenalty\\@secpenalty\\addvspace{1.0em}%\n"
        "  \\hb@xt@1.4em{\\noindent#1}#2}\n"
        "\\begin{document}\nx\n\\end{document}\n"
    )
    sites = _flagged(src)
    assert len(sites) == 1
    s, e = sites[0]
    assert src[s : s + 14] == "\\renewcommand*"
    assert "\\hb@xt@1.4em" in src[s:e]
    out = src[:s] + _AT_LETTER_PRE + src[s:e] + _AT_LETTER_POST + src[e:]
    # 复跑幂等: 包裹内站点被自注 \\catcode 64=11 事件标 at_letter → 不重裹
    assert _flagged(out) == []


def test_wrap_newcommand_nested_def() -> None:
    """0905.0664 形: 嵌套 ``\\renewcommand\\thefootnote{\\@fnsymbol\\c@footnote}``
    躺在外层 def 体内 —— 体在读侧惰性, 外站一裹全罩。"""
    src = (
        "\\newcommand\\makepapertitle{%\n"
        "  \\renewcommand\\thefootnote{\\@fnsymbol\\c@footnote}%\n"
        "  \\footnotetext{\\@thanks}}\n"
        "\\begin{document}\nx\n"
    )
    sites = _flagged(src)
    assert len(sites) == 1
    s, e = sites[0]
    assert "\\footnotetext{\\@thanks}" in src[s:e]


def test_skip_makeatletter_region() -> None:
    """显式 ``\\makeatletter`` 区内的 def 不裹。"""
    src = (
        "\\makeatletter\n"
        "\\renewcommand\\a@b{x\\@y}\n"
        "\\makeatother\n"
        "\\newcommand\\c@d{y}\n"
    )
    sites = _flagged(src)
    assert len(sites) == 1
    assert src[sites[0][0] : sites[0][0] + 11] == "\\newcommand"


def test_skip_catcode_region() -> None:
    """``\\catcode`@=11``/``=12`` 直写区同判 (``\\makeatletter`` 同义形)。"""
    src = "\\catcode`@=11\n\\def\\x@y{1\\@z}\n\\catcode`@=12\n"
    assert _flagged(src) == []


def test_group_local_letter() -> None:
    """bare 组内 ``\\makeatletter`` 事件组末回 —— 组内站不裹, 组外站裹。"""
    src = "{\\makeatletter \\renewcommand\\a@b{x}}\n\\def\\c@d{y}\n"
    sites = _flagged(src)
    assert len(sites) == 1
    assert src[sites[0][0] : sites[0][0] + 4] == "\\def"


def test_def_family_param_body() -> None:
    """``\\def`` 族: 参数文本 + 单组体收域。"""
    src = "\\def\\widebar#1{o\\@m#1p}\nx\n"
    sites = _flagged(src)
    assert len(sites) == 1
    s, e = sites[0]
    assert src[s:e] == "\\def\\widebar#1{o\\@m#1p}"


def test_no_at_token_no_flag() -> None:
    """def 域无 ``\\<letters>@<letter>`` token → 不裹 (``\\@`` 句读形不中)。"""
    src = "\\newcommand\\foo{see \\@ x\\@.\\a@1b}\n"
    assert _flagged(src) == []


def test_let_newif_not_def() -> None:
    """``\\let``/``\\newif`` 非体 def —— 断名产裸字母非 ``\\@``, 不收。"""
    src = "\\let\\foo@bar\\baz\n\\newif\\ifx@y\n"
    assert _atdef_sites(src) == []


def test_commented_def_masked() -> None:
    src = "% \\renewcommand\\a@b{x}\n\\def\\ok{1}\n"
    assert _flagged(src) == []


def test_csname_name_extent() -> None:
    """``\\csname`` 形名本体免疫但 ``{体}`` 内 ``\\@`` 仍断 → 域吞到体末。"""
    src = "\\renewcommand\\csname l@section\\endcsname[2]{\\@secpenalty#1}\n"
    sites = _flagged(src)
    assert len(sites) == 1
    s, e = sites[0]
    assert src[s:e].endswith("{\\@secpenalty#1}")


def test_end_to_end_apply(tmp_path: Path) -> None:
    """actions._apply 全链: 主文件 def 站落盘包裹。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\renewcommand*\\l@section[2]{\\addpenalty\\@secpenalty#1#2}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert _AT_LETTER_PRE in t
    assert _AT_LETTER_POST in t
    assert "\\catcode 64=11" in t
    assert "\\TeXlateAtRestore" in t
    # 包裹内原文逐字节未动
    assert "\\renewcommand*\\l@section[2]{\\addpenalty\\@secpenalty#1#2}" in t


def test_apply_idempotent(tmp_path: Path) -> None:
    """复跑不双重包裹。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n"
        "\\renewcommand*\\l@section[2]{\\@secpenalty#1}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _note = _apply(tmp_path)
    assert ok
    first = (tmp_path / "main.tex").read_text()
    _ok2, _note2 = _apply(tmp_path)
    second = (tmp_path / "main.tex").read_text()
    assert first == second
    assert first.count("\\catcode 64=11") == 1


def test_apply_no_signature_declines(tmp_path: Path) -> None:
    """err_head 无 spacefactor 签 → decline 不改文。"""
    src = "\\documentclass{article}\n\\def\\a@b{x}\n\\begin{document}\nx\n"
    (tmp_path / "main.tex").write_text(src, encoding="utf-8")
    ok, note = _apply(tmp_path, err_head="Undefined control sequence \\foo")
    assert not ok
    assert "spacefactor" in note
    assert (tmp_path / "main.tex").read_text() == src


def test_apply_sty_untouched(tmp_path: Path) -> None:
    """``.sty`` 件装载期 @ 本即 letter —— 缺省扫描面只 ``.tex``。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "defs.sty").write_text(
        "\\ProvidesPackage{defs}\n\\newcommand\\a@b{x}\n", encoding="utf-8"
    )
    ok, _note = _apply(tmp_path)
    assert not ok
    assert (tmp_path / "defs.sty").read_text().endswith("\\newcommand\\a@b{x}\n")


def test_apply_all_tex_files(tmp_path: Path) -> None:
    """dedup 共位 → 单轮多 .tex 文件集扫净 (含 \\input 跨界片)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\input{macros}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "macros.tex").write_text("\\def\\m@cro#1{\\@x#1}\n", encoding="utf-8")
    ok, note = _apply(tmp_path)
    assert ok, note
    assert "macros.tex" in note
    t = (tmp_path / "macros.tex").read_text()
    assert _AT_LETTER_PRE + "\\def\\m@cro#1{\\@x#1}" + _AT_LETTER_POST in t


def test_undefine_cs_emit_shape() -> None:
    """csfix 清位串改 csname 形 —— 零字面 ``@`` + 真 undefined 右操作数。"""
    ins = _undefine_cs("foo@bar")
    assert "\\makeatletter" not in ins
    assert "\\@undefined" not in ins
    assert ins == ("\\expandafter\\let\\csname foo@bar\\endcsname\\TeXlateUndefCs")


def test_let_cs_emit_shape() -> None:
    """双 csname let 形 —— ``\\let\\<A>\\<B>`` 两侧均可含 ``@``。"""
    ins = _let_cs("@ifdefinable", "@rc@ifdefinable")
    assert ins == (
        "\\expandafter\\let\\csname @ifdefinable\\expandafter\\endcsname"
        "\\csname @rc@ifdefinable\\endcsname"
    )
