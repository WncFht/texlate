r"""``input_sty_to_usepackage`` 规则钉 (45-graphics.yaml)。

机制: ``\input <pkg>.sty`` 裸装载以 @=catcode-12 读包文件——包内
@-cs 断成 ``\define``+``@key`` 垃圾 (astro-ph/9901081 epsfig.sty:46
``\define@key`` → ``\define`` undefined_cs 实证)。改写为
``\usepackage{<pkg>}`` = LaTeX2e 唯一正载 (@=11/选项处理/\@filelist
注册), 且转换形被 static_precheck 缺件扫描与 pstricks/svg 路由门同收。

前瞻 ``(?=[\s\S]*\\begin{document})`` 只改导言区位——post-doc
``\input .sty`` 换 ``\usepackage`` 会 preamble-only 新错, 原样保留。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import regex

from texlate.compile.fixloop import load_ruleset

if TYPE_CHECKING:
    from texlate.compile.fixloop.ruleset import Rule


def _rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == "input_sty_to_usepackage")


def _pat() -> regex.Pattern[str]:
    rw = _rule().raw["action"]["params"]["rewrites"][0]
    return regex.compile(rw["pattern"])


def _sub(src: str) -> str:
    rw = _rule().raw["action"]["params"]["rewrites"][0]
    return _pat().sub(rw["repl"], src)


def test_rule_shape_precheck_first() -> None:
    r"""precheck 殿首 (order -11 < pstricks_route)——改写把 ``\input``
    形翻译成 ``\usepackage`` 供路由门/缺件扫描同收。"""
    r = _rule()
    assert r.raw["phase"] == "precheck"
    assert r.raw["order"] == -11  # noqa: PLR2004
    assert r.raw["when"] == {"always": True}
    assert r.raw["action"]["kind"] == "regex_rewrite"
    assert r.raw["action"]["params"]["exts"] == [".tex"]
    assert r.raw["engines"]["tectonic"]["mode"] == "same"


def test_rewrite_bare_and_braced() -> None:
    r"""bare/braced 两形 → ``\usepackage{pkg}``, 文件界 ``(?![\w.-])`` 后留。"""
    assert _sub("\\input epsfig.sty\n\\begin{document}") == (
        "\\usepackage{epsfig}\n\\begin{document}"
    )
    assert _sub("\\input{epsfig.sty}\n\\begin{document}") == (
        "\\usepackage{epsfig}\n\\begin{document}"
    )


def test_rewrite_multi_and_separators() -> None:
    r"""多处同改 + 分隔空白不吞 (旧 ``\\s*\\}?`` 会把 ``\\begin`` 并进同行)。"""
    out = _sub("\\input epsfig.sty and \\input pst-foo-bar.sty\n\\begin{document}")
    assert (
        out == "\\usepackage{epsfig} and \\usepackage{pst-foo-bar}\n\\begin{document}"
    )


def test_rewrite_post_document_untouched() -> None:
    r"""``\\begin{document}`` 后的 ``\\input .sty`` 不改——``\\usepackage``
    换入会 preamble-only 新错 (corpus 2 格实证保留)。"""
    src = "\\begin{document}\n\\input late.sty\n"
    assert _sub(src) == src


def test_rewrite_no_begindoc_untouched() -> None:
    r"""无 ``\\begin{document}`` 的片段文件不动 (非主文件语境)。"""
    src = "\\input frag.sty\nmore text\n"
    assert _sub(src) == src


def test_rewrite_partial_name_rejected() -> None:
    r"""``epsfig.styx`` 半名不中——``(?![\\w.-])`` 界防前缀误吃。"""
    src = "\\input epsfig.styx\n\\begin{document}"
    assert _sub(src) == src
    src2 = "\\input{weird.styx}\n\\begin{document}"
    assert _sub(src2) == src2


def test_condition_pattern_matches_yaml() -> None:
    r"""condition source_contains 与 rewrite pattern 同形 (预筛=执行口径)。"""
    cond = _rule().raw["condition"]["source_contains"]
    rw = _rule().raw["action"]["params"]["rewrites"][0]["pattern"]
    assert cond == rw
