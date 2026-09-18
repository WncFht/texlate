r"""``begindoc_tail_recomment`` 规则钉 (80-bib.yaml)。

机制: ``natbib_numbers_pass`` (95-targeted order 186) 的
``(\\begin\{document\})`` 重写无注释遮盖——注释行提到 ``\begin{document}``
的被替换 ``\n`` 切成两半, 尾巴脱注释成行首活 ``\begin{document}``
(astro-ph/0307344 ms.tex:172 ``\begin{document} command.`` / :198
``\begin{document}.`` 实证)。首个活行在 ``\NAT@numberstrue`` 注入位
(:285) 之前触发 aux 读 → compat 炸 + ``Can be used only in preamble``
级联 (103 err)。本规则收伤: 行首 ``\begin{document}`` 带可见尾文且
后文另有行首者重注释——aux purge 治不了 tex 层裂伤。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import regex

from texlate.compile.fixloop import load_ruleset

if TYPE_CHECKING:
    from texlate.compile.fixloop.ruleset import Rule

# 仿真 natbib_numbers_pass 裂伤产物: 注释行内 \begin{document} 被 \n
# 切出活行 ×2, 真 \begin{document} 在注入位之后单独成行。
_DAMAGED = (
    "\\documentclass{aastex}\n"
    "%% macros should appear before the "
    "\\makeatletter\\ifdefined\\NAT@numberstrue\\NAT@numberstrue\\fi\\makeatother\n"
    "\\begin{document} command.\n"
    "\\newcommand{\\x}{y}\n"
    "%% Indicate the beginning of the paper itself with "
    "\\makeatletter\\ifdefined\\NAT@numberstrue\\NAT@numberstrue\\fi\\makeatother\n"
    "\\begin{document}.\n"
    "\\makeatletter\\ifdefined\\NAT@numberstrue\\NAT@numberstrue\\fi\\makeatother\n"
    "\\begin{document}\n"
    "body\n"
    "\\end{document}\n"
)


def _rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == "begindoc_tail_recomment")


def _pat() -> regex.Pattern[str]:
    rw = _rule().raw["action"]["params"]["rewrites"][0]
    flags = 0
    for fl in rw.get("flags") or []:
        flags |= getattr(regex, fl)
    return regex.compile(rw["pattern"], flags)


def _sub(src: str) -> str:
    rw = _rule().raw["action"]["params"]["rewrites"][0]
    return _pat().sub(rw["repl"], src)


def test_rule_shape() -> None:
    r"""loop 相 order 194 (natbib_numbers_pass 186 裂伤兜底) + other 猫 +
    双签 ctx_suggests + source_contains 预筛。"""
    r = _rule()
    assert r.raw["phase"] == "loop"
    assert r.raw["order"] == 194  # noqa: PLR2004
    assert r.raw["when"] == {"category": "other"}
    assert r.raw["action"]["kind"] == "regex_rewrite"
    assert r.raw["action"]["params"]["exts"] == [".tex"]
    cond = r.raw["condition"]
    assert "Bibliography not compatible" in cond["ctx_suggests"]
    assert "Can be used only in preamble" in cond["ctx_suggests"]
    assert "source_contains" in cond
    assert r.raw["engines"]["xelatex"]["mode"] == "native"
    assert r.raw["engines"]["tectonic"]["mode"] == "same"


def test_rewrite_repairs_stray_begins() -> None:
    r"""裂伤双活行重注释, 真 ``\\begin{document}`` 单行长存。"""
    out = _sub(_DAMAGED)
    assert "%\\begin{document} command." in out
    assert "%\\begin{document}." in out
    # 真 \begin{document} 行未动
    assert "\n\\begin{document}\n" in out
    # 注入位完好
    assert "\\ifdefined\\NAT@numberstrue\\NAT@numberstrue\\fi" in out


def test_rewrite_real_begin_untouched() -> None:
    r"""唯一 ``\\begin{document}`` 单独成行 (0408240 清洁注入形) → 不动。"""
    src = (
        "\\documentclass{article}\n"
        "\\makeatletter\\ifdefined\\NAT@numberstrue\\NAT@numberstrue\\fi\\makeatother\n"
        "\\begin{document}\n"
        "body\n"
        "\\end{document}\n"
    )
    assert _sub(src) == src


def test_rewrite_begin_trailing_comment_untouched() -> None:
    r"""``\\begin{document} % note`` 尾挂注释是合法真行 → 不动。"""
    src = "\\documentclass{article}\n\\begin{document} % go\nbody\n\\end{document}\n"
    assert _sub(src) == src


def test_rewrite_sole_begin_trailing_text_untouched() -> None:
    r"""唯一带尾文 ``\\begin{document}Hello`` (合法罕见形) —— 无后起
    行首 ``\\begin{document}``, lookahead 门放行不动。"""
    src = "\\documentclass{article}\n\\begin{document}Hello\n\\end{document}\n"
    assert _sub(src) == src


def test_rewrite_commented_begin_untouched() -> None:
    r"""注释内 ``\\begin{document}`` 非行首 → 本就不中, 幂等。"""
    src = "%% see \\begin{document} usage\n\\begin{document}\nx\n\\end{document}\n"
    assert _sub(src) == src


def test_rewrite_idempotent() -> None:
    """二入幂等: 修后再 sub 文本不变。"""
    once = _sub(_DAMAGED)
    assert _sub(once) == once


def test_condition_source_contains_precise() -> None:
    r"""source_contains 预筛: 裂伤 blob 中, 清洁 blob/尾挂注释 blob 不中。"""
    cond = _rule().raw["condition"]["source_contains"]
    assert regex.search(cond, _DAMAGED)
    clean = "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    assert not regex.search(cond, clean)
    cmt = "\\documentclass{article}\n\\begin{document} % note\nx\n\\end{document}\n"
    assert not regex.search(cond, cmt)
