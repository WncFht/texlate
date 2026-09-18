r"""``input_sty_209_requirepkg`` 规则钉 (90-shim-legacy.yaml)。

机制与 ``input_sty_to_usepackage`` (45-graphics.yaml) 同纹异臂:
``\input <pkg>.sty`` 裸装载以 @=catcode-12 读包文件, 包内 @-cs 全裂
(astro-ph/9901081 epsfig.sty:46 ``\define@key`` → ``\define`` undefined_cs)。
LaTeX2e compat 模式 (``\documentstyle``) 下 ``\usepackage`` 恒不定义
(latex.ltx ``\if@compatibility\else\let\usepackage\RequirePackage\fi``),
内核无条件定义的 ``\RequirePackage`` 是唯一存活的包装载 cs——改写为
``\RequirePackage{<pkg>}`` 保 \input 行原位序且走全机器 (@=11/\@filelist/
选项处理)。pstricks/svg 路由门行锚与 probe._PKG_RE 缺件扫描均
``(?:usepackage|RequirePackage)`` 同收, 改写形下游零适配。

弃选两臂 (tmp/lane-inputsty209/ d0-d3 xelatex 实证): 并进
``\documentstyle[opts]`` 丢 \input 行原位序且需合并括号; ``\makeatletter``
包裹不进 \@filelist、不走选项机器, 是 \RequirePackage 严格下位。

order -12 先于 2e 臂 (-11): ``\RequirePackage`` 产出两臂皆合法, 病态
双中头 (真 ``\documentstyle`` + 注释行 ``\documentclass``) 恒走安全臂。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import regex

from texlate.compile.fixloop import load_ruleset

if TYPE_CHECKING:
    from texlate.compile.fixloop.ruleset import Rule

_RULE_ID = "input_sty_209_requirepkg"
_SIBLING_ID = "input_sty_to_usepackage"


def _rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == _RULE_ID)


def _sibling() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == _SIBLING_ID)


def _pat() -> regex.Pattern[str]:
    rw = _rule().raw["action"]["params"]["rewrites"][0]
    return regex.compile(rw["pattern"])


def _sub(src: str) -> str:
    rw = _rule().raw["action"]["params"]["rewrites"][0]
    return _pat().sub(rw["repl"], src)


def test_rule_shape_precheck_first() -> None:
    r"""precheck 殿首 (order -12 < 2e 臂 -11 < pstricks_route)——改写形供
    路由门/缺件扫描同收, 且先于 2e 臂兜住病态双中头。"""
    r = _rule()
    assert r.raw["phase"] == "precheck"
    assert r.raw["order"] == -12  # noqa: PLR2004
    assert r.raw["when"] == {"always": True}
    assert r.raw["action"]["kind"] == "regex_rewrite"
    assert r.raw["action"]["params"]["exts"] == [".tex"]
    assert r.raw["engines"]["xelatex"]["mode"] == "native"
    assert r.raw["engines"]["tectonic"]["mode"] == "same"


def test_gate_is_documentstyle_not_documentclass() -> None:
    r"""头闸 ``\\documentstyle``——与 2e 臂 ``\\documentclass`` 闸互斥分工;
    9901081 ``\\documentstyle{mn}`` 走本臂, 2e 稿仍走旧臂。"""
    assert _rule().raw["condition"]["main_head_contains"] == "\\documentstyle"
    assert _sibling().raw["condition"]["main_head_contains"] == "\\documentclass"


def test_runs_before_sibling() -> None:
    r"""本臂先于 2e 臂: ``\\RequirePackage`` 产出两臂皆合法——``\\documentstyle``
    稿注释行混入 ``\\documentclass`` 子串时不再被译成非法 ``\\usepackage``。"""
    assert _rule().raw["order"] < _sibling().raw["order"]


def test_rewrite_bare_and_braced() -> None:
    r"""bare/braced 两形 → ``\\RequirePackage{pkg}``。"""
    assert _sub("\\input epsfig.sty\n\\begin{document}") == (
        "\\RequirePackage{epsfig}\n\\begin{document}"
    )
    assert _sub("\\input{epsfig.sty}\n\\begin{document}") == (
        "\\RequirePackage{epsfig}\n\\begin{document}"
    )


def test_rewrite_9901081_shape() -> None:
    r"""9901081 原貌: ``\\documentstyle{mn}`` + 连续两条裸 ``\\input .sty``。"""
    src = (
        "\\documentstyle{mn}\n\\newif\\ifAMStwofonts\n\\AMStwofontstrue\n"
        "\\input epsfig.sty\n\\input psfig.sty\n\\begin{document}\n"
    )
    assert _sub(src) == (
        "\\documentstyle{mn}\n\\newif\\ifAMStwofonts\n\\AMStwofontstrue\n"
        "\\RequirePackage{epsfig}\n\\RequirePackage{psfig}\n\\begin{document}\n"
    )


def test_rewrite_multi_and_separators() -> None:
    r"""多处同改 + 分隔空白不吞 (防 ``\\begin`` 并进同行)。"""
    out = _sub("\\input epsfig.sty and \\input pst-foo-bar.sty\n\\begin{document}")
    assert (
        out
        == "\\RequirePackage{epsfig} and \\RequirePackage{pst-foo-bar}\n\\begin{document}"
    )


def test_rewrite_post_document_untouched() -> None:
    r"""``\\begin{document}`` 后的 ``\\input .sty`` 不改——``\\RequirePackage``
    同样 preamble-only (``\\@onlypreamble``)。"""
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


def test_pattern_byte_identical_to_sibling() -> None:
    r"""pattern 与 2e 臂逐字节同形 (同纹异臂=唯 repl 不同)——预筛=执行口径,
    两规则 condition.source_contains 亦同形。"""
    rw = _rule().raw["action"]["params"]["rewrites"][0]
    sib_rw = _sibling().raw["action"]["params"]["rewrites"][0]
    assert rw["pattern"] == sib_rw["pattern"]
    assert rw["pattern"] == _rule().raw["condition"]["source_contains"]
    assert rw["repl"] != sib_rw["repl"]
    assert rw["repl"] == "\\\\RequirePackage{\\g<1>}"
