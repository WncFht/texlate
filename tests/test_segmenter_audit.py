r"""latex-audit-2026-09-17 波次 segmenter 发现回归（F1/F2/S2/S4/F4/F11/F7）。

- F1/F2 占位符保留集两洞：``_new_chunk`` 死位跳号（v1 scanner 同款）+
  ``ph_reserved`` 随 ``\\input`` 懒加载文件增量采样——源内 ``[[X_n]]``/``[[CHUNK_n]]``
  字面与签发占位符撞号会让 reconstruct 把原文当 ph 展开（identity 破）。
- S2 ``\\author[opt]`` 无 ``{arg}`` 的 abort 路径：``[opt]`` 段字节既盖进
  ph 体又回放重扫 → 译文双份。
- S4 ``_handle_chunk_arg`` tidx 位空时 ``real[-1]`` 兜底不分 braced/optional：
  ``\\captionof{figure}`` 类型名、``\\section[opt]`` 可选参被当正文译。
- F4 ``_args_tok`` t/d/r/R 定界匹配不查 kind——``\\+``/``\\<``/``\\>`` cs
  控制符被当字面定界符吃。
- F11 ``{\\let\\gl\\relax}Body`` 族：``{`` 与 ``\\let`` 冲刷成字面后孤 ``}``
  落 chunk 头——LLM 丢/改即下游花括失衡；chunk 头孤 ``}`` 改盖字面。
- F7 ``\\begin{document}`` 住 ``\\input`` 子文件：preamble 档由主流
  ``\\documentclass``/``\\begin`` token 现场翻，不再只看 fid-0 mask 视图。
"""

from pathlib import Path

import pytest

from texlate.latex import parse_file, parse_tex, reconstruct
from texlate.latex.model import ScanResult
from texlate.latex.reconstruct import validate_result

ART = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"


@pytest.fixture(autouse=True)
def _pin_v2(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉死 v2（Gullet+Segmenter）路径——外部 ``TEXLATE_NO_EXPAND`` 不串扰。"""
    monkeypatch.delenv("TEXLATE_NO_EXPAND", raising=False)


def check_invariants(res: ScanResult, tex: str) -> None:
    """公共断言：恒等重建 + 校验零告警 + pieces 无缝平铺 vtex。"""
    assert reconstruct(res) == tex
    assert validate_result(res) == []
    pos = 0
    for p in res.pieces:
        assert p.span.start == pos
        pos = p.span.end
    assert pos == len(res.vtex)


def chunk_text(res: ScanResult) -> str:
    """全部 chunk surface 拼接——泄漏断言的统一口径。"""
    return " ".join(c.content for c in res.chunks)


# ------------------------------------------------------------------ F1


def test_f1_literal_chunk0_gets_dead_slot() -> None:
    r"""源内字面 ``[[CHUNK_0]]``：0 号补死位，真 chunk 顺延到 1。"""
    tex = ART % (
        "The placeholder [[CHUNK_0]] is literal text in this sentence, "
        "long enough to be a chunk of its own right."
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert res.chunks[0].content == "[[CHUNK_0]]"  # 死位自引用
    assert res.chunks[1].content.startswith("The placeholder [[CHUNK_0]]")
    assert any(w.kind == "ph_collision" for w in res.warnings)


def test_f1_literal_chunk_n_later_slots_skip() -> None:
    r"""字面 ``[[CHUNK_1]]`` 同理跳号——真实 chunk 不占被撞的 1 号。"""
    tex = ART % (
        "First chunk sentence is here with enough words to stand alone.\n\n"
        "Second para holds the literal [[CHUNK_1]] marker in a long sentence."
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    # chunk0=首段（未撞号）；次段签到 2——1 号是源内字面被死位让出
    assert res.chunks[0].content.startswith("First chunk")
    assert res.chunks[1].content == "[[CHUNK_1]]"  # 死位
    assert res.chunks[2].content.startswith("Second para")


# ------------------------------------------------------------------ F2


def test_f2_subfile_literal_placeholder_not_unfolded(tmp_path: Path) -> None:
    r"""``\\input`` 子文件内 ``[[MATH_1]]`` 字面：签发避让 + ph_collision。"""
    sub = tmp_path / "sub.tex"
    sub.write_text(
        "literal [[MATH_1]] markers and $x+y$ math plus more words for chunk.\n"
    )
    main = tmp_path / "main.tex"
    main.write_text(ART % "\\input{sub}")
    res = parse_file(main)
    out = reconstruct(res)
    # 字面 [[MATH_1]] 不被展开成签发的数学体
    assert "literal [[MATH_1]] markers" in out
    assert out.count("$x+y$") == 1
    assert any(w.kind == "ph_collision" for w in res.warnings)


def test_f2_subfile_chunk_literal_dead_slot(tmp_path: Path) -> None:
    r"""子文件内 ``[[CHUNK_0]]`` 字面同样让签发跳号（增量采样生效）。"""
    sub = tmp_path / "sub.tex"
    sub.write_text("literal [[CHUNK_0]] marker plus more words to make a chunk.\n")
    main = tmp_path / "main.tex"
    main.write_text(ART % "Lead text.\\input{sub}")
    res = parse_file(main)
    assert res.chunks[0].content == "[[CHUNK_0]]"  # 死位自引用
    assert res.chunks[1].content.startswith("literal [[CHUNK_0]]")
    assert any(w.kind == "ph_collision" for w in res.warnings)


# ------------------------------------------------------------------ S2


def test_s2_author_opt_without_arg_no_double_cover() -> None:
    r"""``\\author[opt]`` 无 ``{arg}``：abort 只护 ``\\author``，``[opt]`` 不双份。"""
    tex = ART % "\\author[Short Names]Then body prose goes here to make a full chunk."
    res = parse_tex(tex)
    check_invariants(res, tex)
    authors = [v for k, v in res.ph_map.items() if k.startswith("[[AUTHOR")]
    assert authors == ["\\author"]  # ph 体不含 [opt]
    # [opt] 只进 run surface 一次——不再既受保护又进 chunk
    assert chunk_text(res).count("[Short Names]") == 1


def test_s2_author_opt_with_arg_still_protected() -> None:
    r"""正常面：``\\author[opt]{arg}`` 整块保护不变。"""
    tex = ART % "\\author[Short]{Long Name}Then body prose goes here for chunk."
    res = parse_tex(tex)
    check_invariants(res, tex)
    authors = [v for k, v in res.ph_map.items() if k.startswith("[[AUTHOR")]
    assert authors == ["\\author[Short]{Long Name}"]
    assert "Long Name" not in chunk_text(res)


def test_s2_author_opt_unclosed_brace_no_double_cover() -> None:
    r"""``\\author[opt]{`` 未闭合同样 abort——``[opt]`` 只重扫一次。"""
    tex = ART % "\\author[Short Names]{unclosed then body prose for the chunk."
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert chunk_text(res).count("[Short Names]") == 1


# ------------------------------------------------------------------ S4


def test_s4_captionof_type_arg_not_translated() -> None:
    r"""``\\captionof{figure}`` 缺 ``{text}``：类型名不进 chunk 单独翻译。"""
    tex = ART % "\\captionof{figure}\nBody text here long enough to be its own chunk."
    res = parse_tex(tex)
    check_invariants(res, tex)
    # bail：整调用连同 {figure} 留 run——花括号在 chunk 内保持字面形态
    assert "\\captionof{figure}" in chunk_text(res)
    assert not any(c.context == "captionof" for c in res.chunks)


def test_s4_section_opt_alone_not_chunked() -> None:
    r"""``\\section[Draft Short]`` 无 ``{arg}``：可选参不被当正文 chunk。"""
    tex = (
        ART % "\\section[Draft Short]\nBody text here long enough to be its own chunk."
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert not any(c.context == "section" for c in res.chunks)


def test_s4_normal_chunk_args_unaffected() -> None:
    r"""正常面：``\\section{T}``/``\\captionof{type}{text}`` 挖参不变。"""
    tex = ART % (
        "\\section{Real Title}\nBody text here long enough to be its own chunk."
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert res.chunks[0].content == "Real Title"
    assert res.chunks[0].context == "section"

    tex2 = ART % (
        "\\captionof{figure}{A real caption}Body text here long enough chunk."
    )
    res2 = parse_tex(tex2)
    check_invariants(res2, tex2)
    assert res2.chunks[0].content == "A real caption"
    assert res2.chunks[0].context == "captionof"


# ------------------------------------------------------------------ F4


def test_f4_cs_control_symbol_not_delimiter() -> None:
    r"""``\\onslide\\+{A}``：``\\+`` cs 不被 ``t+`` 当定界符吃。"""
    tex = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\onslide\\+{A}Para text long enough to be its own chunk indeed yes.\n"
        "\\end{document}\n"
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "\\+" in chunk_text(res)


def test_f4_cs_pair_not_angle_delims() -> None:
    r"""``\\frametitle\\<nosuch{T}``：``\\<`` 不触发 ``d<>`` 扫到 EOF。"""
    tex = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\frametitle\\<nosuch{T}Para text long enough to be its own chunk indeed.\n"
        "\\end{document}\n"
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert "\\<nosuch" in chunk_text(res)


def test_f4_real_delimited_arg_still_works() -> None:
    r"""正常面：``\\frametitle<1>{T}`` 真 ``d<>`` 参照常过签名。"""
    tex = (
        "\\documentclass{beamer}\n\\begin{document}\n"
        "\\frametitle<1>{Title Here}Para text long enough to be its own chunk.\n"
        "\\end{document}\n"
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert res.chunks[0].content == "Title Here"
    assert res.chunks[0].context == "frametitle"


# ------------------------------------------------------------------ F11


def test_f11_orphan_rbrace_after_let_goes_literal() -> None:
    r"""``{\\let\\gl\\relax}Body``：孤 ``}`` 盖字面——chunk 头不再带 ``}``。"""
    tex = ART % "{\\let\\gl\\relax}Body text long enough for own chunk yes indeed."
    res = parse_tex(tex)
    check_invariants(res, tex)
    [c] = res.chunks
    assert c.content == "Body text long enough for own chunk yes indeed."


def test_f11_orphan_rbrace_after_def_goes_literal() -> None:
    r"""``{\\def\\gd{G}}`` 同款：孤 ``}`` 不进 chunk。"""
    tex = ART % "{\\def\\gd{G}}Body text long enough for own chunk yes \\gd."
    res = parse_tex(tex)
    check_invariants(res, tex)
    assert not any(c.content.startswith("}") for c in res.chunks)


def test_f11_balanced_group_unchanged() -> None:
    r"""正常面：``{zz}Body``/``{\\relax}Body`` 配对花括号仍整进 chunk。"""
    for body in (
        "{zz}Body text long enough for own chunk yes indeed more.",
        "{\\relax}Body text long enough for own chunk yes indeed.",
    ):
        tex = ART % body
        res = parse_tex(tex)
        check_invariants(res, tex)
        assert res.chunks[0].content.startswith("{")  # 配对组整进 chunk


def test_f11_midrun_orphan_rbrace_stays() -> None:
    r"""run 中段孤 ``}``（eol_par 跨组切分）留 run——分段不变。"""
    tex = ART % "Text {first words here\n\nsecond words here} tail words fill out."
    res = parse_tex(tex)
    check_invariants(res, tex)
    contents = [c.content for c in res.chunks]
    assert contents == [
        "Text {first words here",
        "second words here} tail words fill out.",
    ]


# ------------------------------------------------------------------ F7


def test_f7_whole_doc_in_subfile_preamble_literal(tmp_path: Path) -> None:
    r"""``\\documentclass``+``\\begin{document}`` 全在子文件：preamble 整段字面。"""
    sub = tmp_path / "realmain.tex"
    sub.write_text(
        "\\documentclass{article}\n"
        "\\newcommand{\\foo}{BAR}\n"
        "Preamble prose line that must stay literal and never translate.\n"
        "\\title{My Title}\n"
        "\\begin{document}\n"
        "Body sentence long enough to be its own chunk for the test.\n"
        "\\end{document}\n"
    )
    main = tmp_path / "main.tex"
    main.write_text("\\input{realmain}\n")
    res = parse_file(main)
    # preamble 全文（含散文/\title）literal——只有正文进 chunk
    [c] = res.chunks
    assert c.content.startswith("Body sentence")
    assert "Preamble prose" not in chunk_text(res)
    assert "My Title" not in chunk_text(res)
    assert not res.warnings


def test_f7_docclass_main_begin_subfile(tmp_path: Path) -> None:
    r"""主文件 ``\\documentclass`` + 子文件 ``\\begin{document}``：跨文件翻档。"""
    sub = tmp_path / "body.tex"
    sub.write_text(
        "\\begin{document}\n"
        "Body sentence long enough for its own chunk to appear.\n"
        "\\end{document}\n"
    )
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\nPreamble prose here stays literal.\n\\input{body}\n"
    )
    res = parse_file(main)
    [c] = res.chunks
    assert c.content.startswith("Body sentence")
    assert "Preamble prose" not in chunk_text(res)
    assert not res.warnings


def test_f7_normal_doc_unchanged() -> None:
    r"""正常面：fid-0 完整 preamble 判定不变。"""
    tex = (
        "\\documentclass{article}\n\\usepackage{foo}\nPreamble prose here.\n"
        "\\begin{document}\nBody sentence long enough to be its own chunk.\n"
        "\\end{document}\n"
    )
    res = parse_tex(tex)
    check_invariants(res, tex)
    [c] = res.chunks
    assert c.content.startswith("Body sentence")


def test_f7_no_docclass_no_preamble(tmp_path: Path) -> None:
    r"""无 ``\\documentclass`` 的子文件 ``\\begin{document}`` 不触发 preamble 档。"""
    sub = tmp_path / "body.tex"
    sub.write_text(
        "\\begin{document}\nBody sentence long enough for its own chunk.\n\\end{document}\n"
    )
    main = tmp_path / "main.tex"
    main.write_text("Lead sentence long enough for its own chunk too.\\input{body}\n")
    res = parse_file(main)
    assert any("Lead sentence" in c.content for c in res.chunks)
    assert any("Body sentence" in c.content for c in res.chunks)
