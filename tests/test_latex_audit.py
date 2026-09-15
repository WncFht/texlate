r"""latex/ 对抗性二审探针（audit 2026-09-15）：benchmark 门没照到的行为面。

每条对应一个确认过的真实 bug 或留档弱点；修复后应全绿。
corpus 依赖的 property 测试带 skipif 守卫（bench/corpus* 是 gitignored 数据层）。
"""

import random
import re
from pathlib import Path

import pytest

from texlate.latex import parse_file, parse_tex, reconstruct
from texlate.latex.api import new_state
from texlate.latex.flatten import flatten_inputs
from texlate.latex.macro_table import parse_argspec
from texlate.latex.model import ScanResult
from texlate.latex.placeholder import PH_RX
from texlate.latex.reconstruct import validate_result
from texlate.latex.scanner import Scanner
from texlate.latex.tables import MAX_GEN

DOC = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"


def scan(body: str) -> ScanResult:
    return parse_tex(DOC % body)


def blob(res: ScanResult) -> str:
    return "\n".join(c.content for c in res.chunks)


# ---------------------------------------------------------------- 数学段边界


def test_audit_math_dollar_soft_blank_line() -> None:
    r"""``$`` 配对把 ``\n \n``（含空白空行）当段落边界——与主循环 §3.1.4 一致。

    此前 ``_on_dollar`` 只认紧邻 ``\n\n`` → 游离 ``$`` 跨段吞文本成假 MATH。
    """
    res = scan("Before text $a = 1\n \n not math really$ after more text.")
    assert any(w.kind == "unpaired_dollar" for w in res.warnings)
    assert not any(v.startswith("$a = 1\n") for v in res.ph_map.values())


def test_audit_math_ddollar_soft_blank_line() -> None:
    r"""``$$`` 同理：``\n\t\n`` 也算段落边界。"""
    res = scan("Text $$a=1\n\t\n b$$ tail words here.")
    assert not any("\n\t\n" in v for v in res.ph_map.values())


def test_audit_display_math_bracket_skips_comment() -> None:
    r"""``\[...\]`` 的 ``\]`` 搜索跳过注释——``% \]`` 不作闭合符。"""
    body = "text \\[ x+y % fake \\]\n z \\] tail text here"
    res = scan(body)
    math = [v for v in res.ph_map.values() if v.startswith("\\[")]
    assert math
    assert math[0].endswith("z \\]"), math


def test_audit_paren_math_soft_blank() -> None:
    res = scan("pre \\( x\n \n y \\) post text words here.")
    assert not any(v.startswith("\\( x\n") for v in res.ph_map.values())


# ---------------------------------------------------------------- \if 两档


def test_audit_if_macro_inside_case_no_poison() -> None:
    r"""``\ifMacro{a}{b}``（非 LITERAL 宏）在 if-case 内不计嵌套深度。"""
    body = (
        "\\newcommand{\\ifAnon}[2]{#1}\n"
        "\\iftrue selected text long enough to chunk \\ifAnon{x}{y} "
        "more words here \\else other \\fi\nAfter tail text here."
    )
    res = scan(body)
    assert not any(w.kind == "if_unterminated" for w in res.warnings)
    b = blob(res)
    assert "selected text long enough to chunk" in b
    assert "more words here" in b


def test_audit_unevaluable_if_landmark_covers_condition() -> None:
    r"""不可求值 ``\ifnum\count0<5`` → 界标 literal 覆盖 ``\if``+条件串，
    条件 token（``\count0<5``）不泄进可译 chunk。"""
    res = scan(
        "\\ifnum\\count0<5 AAA first words enough "
        "\\else BBB second branch words here \\fi"
    )
    b = blob(res)
    assert "\\count0" not in b
    assert "<5" not in b
    assert "AAA first words enough" in b
    assert "BBB second branch words here" in b


def test_audit_read_number_register_index() -> None:
    r"""``\count0``/``\dimen12`` 寄存器号随 ``\cs`` 一起消费（界标完整性）。"""
    res = scan("\\ifnum \\count0 < 2 A side text here \\else B side text \\fi")
    b = blob(res)
    assert "\\count" not in b


# ---------------------------------------------------------------- math-debt 误报


def test_audit_verb_dollar_no_false_debt() -> None:
    r"""``\\verb|$HOME|`` 的 ``$`` 是逐字内容——不压 math_debt。"""
    body = "Use \\verb|$HOME| then math $x^2$ done here."
    res = scan(body)
    assert not any(w.kind == "debt_repair" for w in res.warnings)
    assert any(v == "$x^2$" for v in res.ph_map.values())
    assert reconstruct(res) == DOC % body


def test_audit_comment_dollar_no_false_debt() -> None:
    r"""in_arg 注释里的 ``$``（``% cost $5``）同样不压 math_debt。"""
    res = scan("\\caption{aa % has $9\n bb $x$ cc text}")
    assert not any(w.kind == "debt_repair" for w in res.warnings)
    assert any(v == "$x$" for v in res.ph_map.values())


def test_audit_url_dollar_no_false_debt() -> None:
    r"""``\\url{..$..}`` verbatim 参数内的 ``$`` 不压 math_debt。"""
    res = scan("See \\url{http://x/$a} and math $y$ words here.")
    assert not any(w.kind == "debt_repair" for w in res.warnings)


# ---------------------------------------------------------------- argspec / _args


def test_audit_argspec_t_single_char_delim() -> None:
    r"""xparse ``t`` 取单字符定界符——``t*m`` = ``t*`` + ``m``。"""
    spec = parse_argspec("t*m")
    assert [(s.kind, s.delim) for s in spec] == [("t", "*"), ("m", "")]


def test_audit_def_params_span_newline() -> None:
    r"""``\def\a#1\n#2{BODY}``：参数文本里单 ``\n`` 是 space token（TeX 语义）。

    此前 ``\n`` 硬停 → ``ok=True`` 但 body 位对不上 → 静默不登记零 warning。
    """
    res = parse_tex("\\def\\a#1\n#2{BODY}\ntext after \\a{x}{y} end")
    assert "a" in res.macros.cmds
    assert [s.kind for s in res.macros.cmds["a"].spec] == ["m", "m"]
    assert not any(w.kind == "def_parse_fail" for w in res.warnings)


def test_audit_def_bodyless_warns() -> None:
    r"""纯 ``#n`` 序列后无 ``{body}``（EOF/参数被 ``\par`` 截断）→ ``def_parse_fail``。"""
    res = parse_tex("\\def\\c#1")
    assert any(w.kind == "def_parse_fail" for w in res.warnings)
    res = parse_tex("\\def\\d#1\n\nNext para {grp} more")
    assert "d" not in res.macros.cmds
    assert any(w.kind == "def_parse_fail" for w in res.warnings)
    assert reconstruct(res) == "\\def\\d#1\n\nNext para {grp} more"


def test_audit_unknown_cmd_arg_not_across_parbreak() -> None:
    r"""未知命令的 ``{arg}`` 吸收不跨 ``\n\n``——TeX 不定界参数遇 ``\par`` 停。"""
    res = scan("Text \\foo\n\n{arg} more text here.")
    assert not any("\\foo\n\n{arg}" in v for v in res.ph_map.values())


def test_audit_crlf_ws_skip() -> None:
    r"""CRLF 文件：``\\newcommand{\\x}\\r\\n{body}`` 的 body 必须消费。"""
    res = parse_tex(
        "\\documentclass{article}\r\n\\begin{document}\r\n"
        "\\newcommand{\\x}\r\n{bodytext} para text here.\r\n\\end{document}\r\n"
    )
    assert "x" in res.macros.cmds


def test_audit_protect_call_opt_not_across_parbreak() -> None:
    res = scan("See \\cite\n\n[opt]{key} rest text here.")
    assert not any("[opt]" in v for v in res.ph_map.values())


# ---------------------------------------------------------------- flatten


def test_audit_flatten_verb_eol_cap(tmp_path: Path) -> None:
    r"""flatten 的 ``\\verb`` 定界搜索带 EOL 上限（对齐 scanner W9 修复）。

    跨行找闭符会把下一行的 ``\\input`` 误吞进假 verb 体 → 真实 include 丢失。
    """
    Path(tmp_path, "real.tex").write_text("REALFILE", encoding="utf-8")
    tex = "a \\verb|never closed\n\\input{real}\nb | later"
    out = flatten_inputs(tex, str(tmp_path))
    # verb 在行尾终止 → \input{real} 正常触发并展开
    assert "REALFILE" in out


def test_audit_flatten_lstinline_opt_prefix(tmp_path: Path) -> None:
    r"""``\\lstinline[opt]|x|`` 的 ``[opt]`` 在 flatten 也被跳过。"""
    Path(tmp_path, "real.tex").write_text("REALFILE", encoding="utf-8")
    tex = "\\lstinline[language=T]|\\input{real}| rest"
    out = flatten_inputs(tex, str(tmp_path))
    assert "REALFILE" not in out  # lstinline 内容里的 \input 不得展开


def test_audit_flatten_endinput_truncates() -> None:
    r"""``\\endinput`` 丢弃当前文件余下内容（TeX 语义；corpus_v3 24 文件在用）。"""
    out = flatten_inputs("keep \\endinput discarded", "definitely-no-such-dir")
    assert "discarded" not in out
    assert "keep" in out


def test_audit_scanner_endinput_cutoff() -> None:
    r"""未 flatten 的 ``\\endinput``：扫描截停、余下逐字（splice-safe）。"""
    body = "keep this long enough text \\endinput discarded text after"
    res = scan(body)
    assert "discarded text after" not in blob(res)
    assert reconstruct(res) == DOC % body


# ---------------------------------------------------------------- reconstruct


def test_audit_reconstruct_self_ref_no_recursion() -> None:
    r"""译文自指 ``[[CHUNK_k]]``（LLM 幻觉）→ 留 token 不 RecursionError。"""
    res = scan("Some long enough text here to chunk.")
    tid = res.chunks[0].id
    out = reconstruct(res, {tid: f"自指 [[CHUNK_{tid}]] 译文"})
    assert "自指" in out


def test_audit_ph_collision_identity() -> None:
    r"""源文含 ``[[CMD_1]]`` 形字面 + 同名占位符签发 → identity 不破。"""
    body = "text \\foo{a} and literal [[CMD_1]] in source"
    res = scan(body)
    assert reconstruct(res) == DOC % body
    assert any(w.kind == "ph_collision" for w in res.warnings)


def test_audit_chunk_collision_identity() -> None:
    r"""``[[CHUNK_0]]`` 形字面落在可译文本内 → 死位跳号 + 字面逐字还原。"""
    body = "literal [[CHUNK_0]] in source then a long enough paragraph text to chunk."
    res = scan(body)
    assert reconstruct(res) == DOC % body


# ---------------------------------------------------------------- env / 其他


def test_audit_stray_end_empty_stack_warns() -> None:
    r"""裸 ``\\end{env}``（栈空）也发 ``stray_end``——静默降级是本项目大忌。"""
    res = scan("para text here \\end{itemize} more text")
    assert any(w.kind == "stray_end" for w in res.warnings)


def test_audit_gen_cap_emits_warning() -> None:
    r"""``gen >= MAX_GEN`` 降级必须留信号（此前三处静默）。"""
    state = new_state()
    sc = Scanner(state, gen=MAX_GEN)
    out = sc.scan(
        "\\begin{figure}\\caption{Deep cap text enough to chunk}\\end{figure}"
    )
    assert any(w.kind == "gen_overflow" for w in out.warnings)


def test_audit_find_env_end_skips_verb() -> None:
    r"""``\\verb|\\end{equation}|`` 内的假闭合不截断 env 体。"""
    body = "\\begin{equation}x \\verb|\\end{equation}| y\\end{equation} tail text."
    res = scan(body)
    math = [v for v in res.ph_map.values() if v.startswith("\\begin{equation}")]
    assert math
    assert math[0].endswith("y\\end{equation}"), res.ph_map
    assert reconstruct(res) == DOC % body


def test_audit_empty_protect_arg_no_ph() -> None:
    r"""TRANSPARENT 宏缺省可选参的零宽占位不签发空 ``[[KEY]]``。"""
    res = scan("\\newcommand{\\secref}[1][]{See \\ref{#1}}\n\\secref text here.")
    assert "" not in res.ph_map.values()


# ---------------------------------------------------------------- fuzz 不变式

_TOKENS = [
    "\\section{",
    "\\caption[",
    "\\begin{figure}",
    "\\end{",
    "\\cite{",
    "\\ref{",
    "\\verb|",
    "\\url{",
    "\\href{",
    "\\input{",
    "\\newcommand{\\x}{",
    "\\def\\a#1",
    "\\iftrue",
    "\\ifnum 3<",
    "\\else",
    "\\fi",
    "\\or",
    "\\newif\\ifq",
    "$",
    "$$",
    "\\[",
    "\\]",
    "\\(",
    "\\)",
    "{",
    "}",
    "[",
    "]",
    "%",
    "\n\n",
    "\n",
    "\\item",
    "\\author{",
    "\\label{",
    "\\emph{",
    "\\begin{verbatim}",
    "\\end{verbatim}",
    "\\begin{equation}",
    "\\begin{itemize}",
    "\\qtrue",
    "word ",
    "\\foo",
    "\\",
    "\\\\",
    "~",
    "#1",
    "\\includegraphics{",
    "&",
    "\\endinput",
    "\r\n",
]


def test_audit_fuzz_never_raises_tiles_identity() -> None:
    """token 汤 fuzz：零异常 + pieces 无缝平铺 + protected_tex 自洽 + identity。"""
    rng = random.Random(42)  # noqa: S311 — 测试用确定性种子，非加密用途
    for _ in range(400):
        tex = "".join(rng.choice(_TOKENS) for _ in range(rng.randint(1, 40)))
        res = parse_tex(tex)  # 铁律 1：绝不抛异常
        pos = 0
        for p in res.pieces:
            assert p.span.start == pos, f"gap at {p.span} in {tex[:80]!r}"
            pos = p.span.end
        assert pos == len(tex)
        assert res.protected_tex == "".join(p.text for p in res.pieces)
        assert reconstruct(res) == tex


def test_audit_fuzz_random_bytes() -> None:
    """纯随机字节 fuzz（含 \\r/|/<> 等脏字符）：零异常 + 平铺 + identity。"""
    rng = random.Random(7)  # noqa: S311 — 测试用确定性种子，非加密用途
    alpha = "abcd$%{}[]\\~^_&# \t\n\r|<>*-=+':;,.!?/0123456789"
    for _ in range(400):
        tex = "".join(rng.choice(alpha) for _ in range(rng.randint(0, 200)))
        res = parse_tex(tex)
        pos = 0
        for p in res.pieces:
            assert p.span.start == pos
            pos = p.span.end
        assert pos == len(tex)
        assert reconstruct(res) == tex


# ---------------------------------------------------------------- corpus property

_CORPUS = Path(__file__).resolve().parent.parent / "bench" / "corpus_v3"


def _corpus_mains() -> list[Path]:
    mains: list[Path] = []
    if not _CORPUS.is_dir():
        return mains
    for d in sorted(_CORPUS.iterdir()):
        if not d.is_dir():
            continue
        for f in sorted(d.rglob("*.tex")):
            try:
                t = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            if "\\begin{document}" in t or "\\documentclass" in t:
                mains.append(f)
                break
    return mains


@pytest.mark.skipif(
    not _CORPUS.is_dir(), reason="bench/corpus_v3 不在本地（gitignored 数据层）"
)
def test_audit_corpus_pieces_tiling_sample() -> None:
    """corpus_v3 抽样：pieces 平铺 + protected_tex 自洽 + reconstruct 无异常。"""
    mains = _corpus_mains()
    rng = random.Random(1)  # noqa: S311 — 测试用确定性种子，非加密用途
    for f in rng.sample(mains, min(60, len(mains))):
        res = parse_file(f)
        pos = 0
        for p in res.pieces:
            assert p.span.start == pos, f"{f}: gap at {p.span}"
            pos = p.span.end
        assert res.protected_tex == "".join(p.text for p in res.pieces), f
        reconstruct(res)  # 不抛异常


def test_audit_no_dangling_ph_re() -> None:
    """protected_tex/chunk/ph_map 内所有 ``[[X_n]]`` 均可解析（不悬空）。"""
    res = scan(
        "\\begin{figure}\\caption{Cap \\cite{a} text}\\end{figure}"
        "\\section{T \\emph{em} \\url{u}} tail \\footnote{f $x$ g}"
    )
    assert validate_result(res) == []
    seen = set(PH_RX.findall(res.protected_tex))
    for c in res.chunks:
        seen.update(PH_RX.findall(c.content))
    for v in res.ph_map.values():
        seen.update(PH_RX.findall(v))
    for tok in seen:
        m = re.fullmatch(r"\[\[CHUNK_(\d+)\]\]", tok)
        if m:
            assert int(m.group(1)) < len(res.chunks)
        else:
            assert tok in res.ph_map, tok
