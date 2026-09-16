r"""v1 回退臂（``parse_tex_v1``/``flatten_inputs``）审计修复回归。

- F3  ``flatten_inputs``：``\\``/``\%`` 等 ``\<非字母>`` 控制符号的第二
  字节不得重新起词法（``\\input`` 误内联、``\\endinput`` 误截断）。
- F10 ``scanner._handle_env``/``flatten_inputs`` verb 块：``filecontents*``
  闭环境须行首独占——行中 ``\end{filecontents}`` 诱饵不得截断逐字段
  （v2 segmenter W26 锚定同款移植）。
- F5  ``scanner._process_if``：``\newif`` 注册的 ``\Xtrue/\Xfalse``
  setter（LITERAL 宏）与未注册 ``if*`` 包宏调用形（``\ifdef`` 族）不
  计 ``\fi`` 嵌套——与 ``_handle_cond`` 同一前置。
"""

from pathlib import Path

from texlate.latex import parse_tex_v1, reconstruct
from texlate.latex.flatten import flatten_inputs


def _w(tmp: Path, name: str, text: str) -> Path:
    p = tmp / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


_DOC = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"
_TAIL = "Afterwards enough prose to make a translatable chunk on its own."


# ------------------------------------------------------------------ F3


def test_f3_double_backslash_input_not_inlined(tmp_path: Path) -> None:
    r"""``\\input{b}`` = ``\\`` 换行 + 字面 ``input{b}``——不得内联。"""
    _w(tmp_path, "b.tex", "CONTENTS-OF-B\n")
    src = "\\\\input{b}"
    assert flatten_inputs(src, str(tmp_path)) == src


def test_f3_two_pairs_then_literal_input(tmp_path: Path) -> None:
    r"""``x \\\\input{b}``：两枚 ``\\`` 控制符后 ``input{b}`` 仍是字面。"""
    _w(tmp_path, "b.tex", "CONTENTS-OF-B\n")
    src = "x \\\\\\\\input{b}"
    assert flatten_inputs(src, str(tmp_path)) == src


def test_f3_double_backslash_endinput_not_truncating(tmp_path: Path) -> None:
    r"""``\\endinput`` 是字面文本——不触发文件终止。"""
    src = "tail\\\\endinput\nSHOULD-SURVIVE"
    assert flatten_inputs(src, str(tmp_path)) == src


def test_f3_escaped_percent_not_comment(tmp_path: Path) -> None:
    r"""``\%`` 的字面 ``%`` 不启注释——行尾内容全保留。"""
    src = "a\\%pct rest of line"
    assert flatten_inputs(src, str(tmp_path)) == src


def test_f3_real_input_still_inlines(tmp_path: Path) -> None:
    """对照：真 ``\\input{b}`` 照常内联。"""
    _w(tmp_path, "b.tex", "CONTENTS-OF-B\n")
    assert "CONTENTS-OF-B" in flatten_inputs("\\input{b}", str(tmp_path))


def test_f3_real_endinput_still_truncates(tmp_path: Path) -> None:
    """对照：真 ``\\endinput`` 照常截断当前文件余量。"""
    out = flatten_inputs("A\n\\endinput\nDROP-ME", str(tmp_path))
    assert "DROP-ME" not in out
    assert out.endswith("\\endinput")


def test_f3_verb_after_double_backslash_is_literal(tmp_path: Path) -> None:
    r"""``\\verb|\input{x}|``：TeX 视角 ``verb|`` 是字面文本，其后
    ``\input{x}`` 是真命令——照常内联（旧版误按 ``\verb`` 定界跳过）。"""
    _w(tmp_path, "x.tex", "XFILE\n")
    out = flatten_inputs("a\\\\verb|\\input{x}|b", str(tmp_path))
    assert "XFILE" in out


# ------------------------------------------------------------------ F10


def test_f10_filecontents_midline_end_decoy() -> None:
    r"""行中 ``\end{filecontents}`` 诱饵不截断逐字段——体到行首真 ``\end``
    为止，诱饵行后内容不得漏进可译 chunk，无 ``stray_end``。"""
    src = _DOC % (
        "\\begin{filecontents}{job.bib}\n"
        "line1 \\end{filecontents} mid-line decoy\n"
        "REAL-BIB-LINE\n"
        "\\end{filecontents}\n" + _TAIL
    )
    res = parse_tex_v1(src)
    assert reconstruct(res) == src
    assert not [w for w in res.warnings if w.kind == "stray_end"]
    assert all("REAL-BIB-LINE" not in c.content for c in res.chunks)
    assert any("Afterwards" in c.content for c in res.chunks)


def test_f10_filecontents_normal_close_unchanged() -> None:
    """对照：行首 ``\\end{filecontents}`` 照常闭合逐字段。"""
    src = _DOC % (
        "\\begin{filecontents}{job.bib}\nBIB-LINE\n\\end{filecontents}\n" + _TAIL
    )
    res = parse_tex_v1(src)
    assert reconstruct(res) == src
    assert all("BIB-LINE" not in c.content for c in res.chunks)
    assert any("Afterwards" in c.content for c in res.chunks)


def test_f10_flatten_filecontents_decoy(tmp_path: Path) -> None:
    r"""flatten 侧同锚定：诱饵行后 ``\input`` 仍在逐字段内——不内联。"""
    _w(tmp_path, "evil.tex", "EVIL-INLINE\n")
    src = (
        "\\begin{filecontents*}{f.bib}\n"
        "decoy \\end{filecontents*} mid-line\n"
        "\\input{evil}\n"
        "\\end{filecontents*}\n"
    )
    assert flatten_inputs(src, str(tmp_path)) == src


# ------------------------------------------------------------------ F5


def test_f5_newif_setter_inside_if_not_counted() -> None:
    r"""``\newif\ififx`` 的 ``\ifxtrue`` setter 不计 ``\fi`` 嵌套——真
    ``\fi`` 不被吞、``if_unterminated`` 不报、尾段照常成 chunk。"""
    src = _DOC % ("\\newif\\ififx\n\\ififx TRUE-PATH \\ifxtrue SETTER \\fi\n" + _TAIL)
    res = parse_tex_v1(src)
    assert reconstruct(res) == src
    assert not [w for w in res.warnings if w.kind == "if_unterminated"]
    assert any("Afterwards" in c.content for c in res.chunks)


def test_f5_bare_setter_sets_flag() -> None:
    r"""顶层 ``\ifxtrue`` 独立 setter——旗标翻真后 ``\ififx`` 走真支
    （dispatch 面回归对照）。"""
    src = _DOC % (
        "\\newif\\ififx\n\\ifxtrue\n"
        "\\ififx ON-PATH enough prose to be a real chunk \\fi\n" + _TAIL
    )
    res = parse_tex_v1(src)
    assert reconstruct(res) == src
    assert any("ON-PATH" in c.content for c in res.chunks)


def test_f5_iffalse_dead_branch_setter() -> None:
    r"""``\iffalse`` 死支里的 ``\ifxtrue`` 不计嵌套：真 ``\fi`` 正常收尾、
    死支内容不进 chunk。"""
    src = _DOC % ("\\newif\\ififx\n\\iffalse DEAD \\ifxtrue MORE-DEAD \\fi\n" + _TAIL)
    res = parse_tex_v1(src)
    assert reconstruct(res) == src
    assert not [w for w in res.warnings if w.kind == "if_unterminated"]
    assert all("MORE-DEAD" not in c.content for c in res.chunks)
    assert any("Afterwards" in c.content for c in res.chunks)


def test_f5_unregistered_if_macro_not_counted() -> None:
    r"""未注册 ``\ifdef`` 族包宏调用形不计嵌套（core 审计同型残留）——
    真 ``\fi`` 配对外层 ``\iftrue``，尾段不整吞。"""
    src = _DOC % ("\\iftrue KEEP-TEXT \\ifdef{\\x}{Y}{Z} DROP \\fi\n" + _TAIL)
    res = parse_tex_v1(src)
    assert reconstruct(res) == src
    assert not [w for w in res.warnings if w.kind == "if_unterminated"]
    assert any("Afterwards" in c.content for c in res.chunks)


def test_f5_nested_real_if_still_pairs() -> None:
    """对照：真嵌套 ``\\if`` 照常配 ``\\fi``——收紧不矫枉过正。"""
    src = _DOC % ("\\iftrue KEEP-A \\iftrue KEEP-B \\fi TAIL-INNER \\fi\n" + _TAIL)
    res = parse_tex_v1(src)
    assert reconstruct(res) == src
    assert not [w for w in res.warnings if w.kind == "if_unterminated"]
    assert any("Afterwards" in c.content for c in res.chunks)


def test_f5_newif_flag_still_counts_as_opener() -> None:
    r"""对照：``\newif`` 旗标 ``\ifX`` 嵌套在另一 ``\if`` 内仍计开器——
    旗标语义不回归。"""
    src = _DOC % (
        "\\newif\\ifabc\n\\iftrue OUTER \\ifabc INNER \\fi TAIL \\fi\n" + _TAIL
    )
    res = parse_tex_v1(src)
    assert reconstruct(res) == src
    assert not [w for w in res.warnings if w.kind == "if_unterminated"]
    assert any("Afterwards" in c.content for c in res.chunks)
