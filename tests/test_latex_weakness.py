r"""W11/W12/W14 留档弱点的行为钉测试 + 回压/正文字内定义（accept-not-fix）。"""

from pathlib import Path

from texlate.latex import parse_file, parse_tex, reconstruct
from texlate.latex.api import new_state
from texlate.latex.flatten import flatten_inputs
from texlate.latex.model import ScanResult
from texlate.latex.scanner import Scanner
from texlate.latex.tables import BUDGET, MAX_GEN

DOC = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"


def scan(body: str) -> ScanResult:
    return parse_tex(DOC % body)


# ---------------------------------------------------------------- W11


def test_w11_preamble_regex_space_begin() -> None:
    r"""W11 已修：``\begin {document}``（带空格）现被识别 → preamble 正常切除。

    （旧行为：正则不认空格变体 → 整文按正文扫，``\documentclass`` 进 chunk。）
    """
    tex = "\\documentclass{article}\n\\begin {document}\nBody text here.\n"
    res = parse_tex(tex)
    assert res.protected_tex.startswith(
        "\\documentclass{article}\n\\begin {document}\n"
    )
    assert all("documentclass" not in c.content for c in res.chunks)


def test_w11_preamble_commented_begin() -> None:
    r"""W11 已修：注释里的 ``\begin{document}`` 不再误命中（mask_tex 视图）。

    假 begin 在前、真 begin 在后——preamble 必须切到真标记；
    无真标记时（全注释场景）preamble_end=0 整文按正文扫，不炸。
    """
    tex = (
        "\\documentclass{article}\n% \\begin{document} fake\n"
        "\\usepackage{x}\n\\begin{document}\nBody.\n\\end{document}\n"
    )
    res = parse_tex(tex)
    # preamble 切到真 \begin{document}：假注释行与 \usepackage 都在 LITERAL 区
    assert res.protected_tex.startswith("\\documentclass{article}")
    assert "\\begin{document}\nBody." in res.protected_tex
    assert all("documentclass" not in c.content for c in res.chunks)
    # 只有假标记：不识别为 preamble，但解析不炸
    tex2 = "% \\begin{document} fake\n\\documentclass{article}\nreal body\n"
    res2 = parse_tex(tex2)
    assert res2 is not None


def test_w11_normal_preamble() -> None:
    r"""正常 preamble：``\documentclass``+``\begin{document}`` 间整段 LITERAL。"""
    res = parse_tex(DOC % "Body.")
    assert res.protected_tex.startswith("\\documentclass{article}\n\\begin{document}\n")
    # preamble 区不产生 chunk
    assert all("documentclass" not in c.content for c in res.chunks)


# ---------------------------------------------------------------- W12


def test_w12_seen_blocks_legit_reinclude(tmp_path: Path) -> None:
    r"""W12 已修：``_seen`` 降为祖先栈——兄弟位合法重包含照常内联。

    （旧行为：全局 once-set，第二个 ``\input{shared}`` 内容整体丢失。）
    """
    (tmp_path / "shared.tex").write_text("SHARED CONTENT", encoding="utf-8")
    out = flatten_inputs("\\input{shared}\nx\n\\input{shared}", str(tmp_path))
    assert out.count("SHARED CONTENT") == 2  # noqa: PLR2004 - 两次都内联


def test_w12_cycle_still_breaks(tmp_path: Path) -> None:
    r"""祖先栈仍断真环：a→b→a 的 a 二次展开被跳（栈上驻留）。

    被跳的 ``\input`` 命令本体原样留在流内（None → 逐字回放），
    由后续扫描/重编译语义兜底——不静默吞字。
    """
    (tmp_path / "a.tex").write_text("A[\\input{b}]A", encoding="utf-8")
    (tmp_path / "b.tex").write_text("B{\\input{a}}B", encoding="utf-8")
    out = flatten_inputs("\\input{a}", str(tmp_path))
    # a 展开含 b；b 内的 \input{a} 命中祖先栈 → 该命令逐字留存不再展开
    assert out == "A[B{\\input{a}}B]A"


def test_w12_self_include_blocked(tmp_path: Path) -> None:
    r"""主文件自包含：parse_file 预种主文件路径 → 一层都不展开。"""
    (tmp_path / "main.tex").write_text("X\n\\input{main}\nY", encoding="utf-8")
    res = parse_file(tmp_path / "main.tex")
    assert res.protected_tex.count("X") == 1
    assert "\\input{main}" in res.protected_tex  # 原样留下不展开


# ---------------------------------------------------------------- W14


def test_w14_unpaired_dollar_linear() -> None:
    r"""W14：``$`` 配对逐次向前扫（理论上最坏 O(n²)），行为钉：
    不配对的 ``$`` → literal + ``unpaired_dollar`` warning，不吞后文。"""
    body = "Text with $unclosed dollar sign here.\n\nNext para text."
    res = scan(body)
    assert any(w.kind == "unpaired_dollar" for w in res.warnings)
    assert reconstruct(res) == DOC % body


def test_math_debt_repair() -> None:
    r"""``$`` 配对跨占位符：ph 体内含奇数 ``$`` 不破坏后随 ``$x$`` 配对。

    v2 语义变更：token 级 ``$..$`` 本地配对天然免疫（v1 的 debt_repair
    合并机制退役——它会误并 ``[CMD]and $`` 再甩出 unpaired_dollar）。
    断言面 = ``$x$`` 完整 MATH + 无 unpaired_dollar + identity。
    """
    body = "Text \\foo{a $b} and $x$ more text."
    res = scan(body)
    assert reconstruct(res) == DOC % body
    assert any(v == "$x$" for v in res.ph_map.values())
    assert not any(w.kind == "unpaired_dollar" for w in res.warnings)


# ---------------------------------------------------------------- 回压


def test_budget_backpressure() -> None:
    r"""``state.steps`` 超 BUDGET → 宏不再分流，整调用 ``[[MACRO]]`` + warning。"""
    # state 不可经 parse_tex 外取——直接构造超支场景：steps 灌到 BUDGET
    _ = scan("\\newcommand{\\m}{\\ensuremath{x}}\n" + "\\m " * 50)

    state = new_state()
    state.steps = BUDGET  # 下一次宏调用 → BUDGET+1 → 恰触发一次性 warning
    sc = Scanner(state)
    tex = "\\newcommand{\\m}{\\ensuremath{x}}\nuse \\m here"
    sc.scan(tex)
    assert any(w.kind == "expansion_overflow" for w in state.warnings)


def test_max_gen_guard() -> None:
    r"""``gen >= MAX_GEN`` → 子扫描不再递归挖（直接原样入 run）。"""
    state = new_state()
    sc = Scanner(state, gen=MAX_GEN)
    tex = "\\caption{Cap text with enough words to chunk}"
    out = sc.scan(tex)
    # 超代数 → _handle_chunk_arg 不子扫：整段原文进 run，只有 paragraph chunk
    assert all(c.context != "caption" for c in out.chunks)


# ---------------------------------------------------------------- 体内 \def


def test_def_in_body_registers() -> None:
    r"""正文里的 ``\newcommand`` 同样登记（分派行 2 不在 preamble 也生效）。"""
    res = scan("Text \\newcommand{\\late}{L} then \\late more text here.")
    assert res.macros.lookup("late") is not None
    assert (
        reconstruct(res)
        == DOC % "Text \\newcommand{\\late}{L} then \\late more text here."
    )


def test_env_begin_macro_endpoint() -> None:
    r"""``\beq``/``\eeq`` 宏端点：ENV_BEGIN/ENV_END 宏参与 ``\end`` 配对。"""
    body = (
        "\\newcommand{\\beq}{\\begin{equation}}\n"
        "\\newcommand{\\eeq}{\\end{equation}}\n"
        "\\beq x=1 \\eeq\nText after."
    )
    res = scan(body)
    assert any(v == "\\beq x=1 \\eeq" for v in res.ph_map.values())
    assert reconstruct(res) == DOC % body


def test_parse_file_end_to_end(tmp_path: Path) -> None:
    """``parse_file`` 全链：读盘→展平→扫描。"""
    (tmp_path / "sub.tex").write_text("SUB FILE BODY", encoding="utf-8")
    main = tmp_path / "main.tex"
    main.write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{sub}\n\\end{document}\n",
        encoding="utf-8",
    )
    res = parse_file(main)
    assert "SUB FILE BODY" in res.protected_tex
