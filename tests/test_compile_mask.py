"""mask.py 遮蔽视图与 group_end 的单测（decode_tex 单源在 textutil）。"""

from texlate.compile.mask import (
    apply_edits,
    group_end,
    visible_tex,
    without_comments,
)
from texlate.textutil import decode_tex, mask_comments, mask_tex


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


def test_visible_tex_env_end_no_offset_overshoot() -> None:
    r"""深位 ``\begin`` + 短体：``\end`` 搜索起点不得双计 offset。

    2003.03510 实证：``_env_stop`` 起点误传 ``i + env.end()``（``env.end()``
    已是绝对位）→ 体长 < ``i`` 时真 ``\end`` 被跳过，遮盖延至下一 ``\end``
    或 EOF，``\begin{document}`` 被吞 → no_main_tex。
    """
    pad = "% pad\n" * 40  # \begin 落 ~240 字节深位
    tex = (
        pad
        + "\\begin{comment}\nshort\n\\end{comment}\n"
        + "\\begin{filecontents*}{x.eps}\nEPS\n\\end{filecontents*}\n"
        + "\\begin{document}\n"
    )
    vis = visible_tex(tex)
    assert "\\begin{document}" in vis
    assert "short" not in vis  # comment 体仍被遮
    assert "EPS" not in vis  # filecontents* 体仍被遮


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


# ------------------------------------------------------------- CR-EOL（C 桶）
# 1608.02631 / gr-qc/0605005：CR-only/混合 EOL 文件 ``%`` 注释曾吞到
# EOF——mask/词法层逐 ``\n`` 假设。decode_tex 归一 ``\r\n|\r→\n`` 后
# mask 层再补 ``\r`` 容错（str 直调路径防御）。


def test_decode_tex_normalizes_cr_eol() -> None:
    assert decode_tex(b"a\rb\r\nc\nd") == "a\nb\nc\nd"


def test_mask_comments_cr_line_end() -> None:
    tex = "aa %note\rbb %note2\ncc"
    out = mask_comments(tex)
    assert out.endswith("cc")
    assert "bb" in out
    assert "note" not in out


def test_visible_tex_cr_comment() -> None:
    tex = "abc % \\documentclass hidden\rbd \\begin{document} here"
    vis = visible_tex(tex)
    assert "\\begin{document}" in vis
    assert "\\documentclass" not in vis


def test_mask_tex_cr_comment() -> None:
    tex = "x %note\ry"
    assert mask_tex(tex).endswith("y")
