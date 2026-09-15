"""mask.py 遮蔽视图与 group_end 的单测。"""

from texlate.compile.mask import (
    apply_edits,
    decode_tex,
    group_end,
    visible_tex,
    without_comments,
)


def test_visible_tex_masks_line_comment() -> None:
    tex = "abc % comment with \\documentclass\ndef"
    vis = visible_tex(tex)
    assert "\\documentclass" not in vis
    assert vis.startswith("abc ")
    assert len(vis) == len(tex)
    assert vis.count("\n") == tex.count("\n")


def test_visible_tex_verb_percent_not_comment() -> None:
    r"""`\verb|%|` 里的 % 不是注释。"""
    tex = r"a \verb|%| b % real comment" + "\nnext"
    vis = visible_tex(tex)
    assert "real comment" not in vis
    assert vis.endswith("\nnext")
    assert len(vis) == len(tex)


def test_visible_tex_verbatim_env_masked() -> None:
    tex = "before\n\\begin{verbatim}\n%notacomment \\cmd\n\\end{verbatim}\nafter"
    vis = visible_tex(tex)
    assert "%notacomment" not in vis
    assert "after" in vis
    assert vis.count("\n") == 4  # noqa: PLR2004 - 遮蔽后行数不变是核心断言


def test_visible_tex_comment_env_unmasked_when_disabled() -> None:
    tex = "x\n\\begin{comment}\nbody\n\\end{comment}   \n"
    vis = visible_tex(tex, mask_comment_environments=False)
    assert "\\end{comment}" in vis


def test_without_comments_offset_preserved() -> None:
    tex = "aa %bb\ncc"
    out = without_comments(tex)
    assert len(out) == len(tex)
    assert out.endswith("cc")


def test_group_end_nested() -> None:
    tex = r"\foo{a{b}c}tail"
    assert group_end(tex, 4) == 11  # noqa: PLR2004 - 嵌套括号收尾 offset


def test_group_end_bracket() -> None:
    tex = r"\usepackage[utf8]{inputenc}"
    assert tex[group_end(tex, 11) - 1] == "]"


def test_group_end_escaped_brace() -> None:
    tex = r"{a\}b}x"
    assert group_end(tex, 0) == 6  # noqa: PLR2004 - 转义括号后的收尾 offset


def test_apply_edits_keeps_line_count() -> None:
    tex = "l1\nl2XX\nl3\n"
    out = apply_edits(tex, [(4, 6, "")])
    assert out.count("\n") == tex.count("\n")


def test_decode_tex_latin1_fallback() -> None:
    assert decode_tex("café".encode("latin-1")) == "café"
