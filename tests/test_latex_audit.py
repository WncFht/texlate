r"""latex/ 对抗性二审探针（audit 2026-09-15）：benchmark 门没照到的行为面。

每条对应一个确认过的真实 bug 或留档弱点；修复后应全绿。
corpus 依赖的 property 测试带 skipif 守卫（bench/corpus* 是 gitignored 数据层）。
"""

import re
import time
from pathlib import Path

import pytest
from _fuzzkit import fuzz_rng
from conftest import DOC, blob, scan_doc

from texlate.latex import parse_file, parse_tex, reconstruct
from texlate.latex.flatten import flatten_inputs
from texlate.latex.macro_table import parse_argspec
from texlate.latex.placeholder import PH_RX
from texlate.latex.reconstruct import validate_result

# ---------------------------------------------------------------- 数学段边界


def test_audit_math_dollar_soft_blank_line() -> None:
    r"""``$`` 配对把 ``\n \n``（含空白空行）当段落边界——与主循环 §3.1.4 一致。

    此前 ``_on_dollar`` 只认紧邻 ``\n\n`` → 游离 ``$`` 跨段吞文本成假 MATH。
    """
    res = scan_doc("Before text $a = 1\n \n not math really$ after more text.")
    assert any(w.kind == "unpaired_dollar" for w in res.warnings)
    assert not any(v.startswith("$a = 1\n") for v in res.ph_map.values())


def test_audit_math_ddollar_soft_blank_line() -> None:
    r"""``$$`` 同理：``\n\t\n`` 也算段落边界。"""
    res = scan_doc("Text $$a=1\n\t\n b$$ tail words here.")
    assert not any("\n\t\n" in v for v in res.ph_map.values())


def test_audit_display_math_bracket_skips_comment() -> None:
    r"""``\[...\]`` 的 ``\]`` 搜索跳过注释——``% \]`` 不作闭合符。"""
    body = "text \\[ x+y % fake \\]\n z \\] tail text here"
    res = scan_doc(body)
    math = [v for v in res.ph_map.values() if v.startswith("\\[")]
    assert math
    assert math[0].endswith("z \\]"), math


def test_audit_paren_math_soft_blank() -> None:
    res = scan_doc("pre \\( x\n \n y \\) post text words here.")
    assert not any(v.startswith("\\( x\n") for v in res.ph_map.values())


# ---------------------------------------------------------------- \if 两档


def test_audit_if_macro_inside_case_no_poison() -> None:
    r"""``\ifMacro{a}{b}``（非 LITERAL 宏）在 if-case 内不计嵌套深度。"""
    body = (
        "\\newcommand{\\ifAnon}[2]{#1}\n"
        "\\iftrue selected text long enough to chunk \\ifAnon{x}{y} "
        "more words here \\else other \\fi\nAfter tail text here."
    )
    res = scan_doc(body)
    assert not any(w.kind == "if_unterminated" for w in res.warnings)
    b = blob(res)
    assert "selected text long enough to chunk" in b
    assert "more words here" in b


def test_audit_unevaluable_if_landmark_covers_condition() -> None:
    r"""不可求值 ``\ifnum\count0<5`` → 界标 literal 覆盖 ``\if``+条件串，
    条件 token（``\count0<5``）不泄进可译 chunk。"""
    res = scan_doc(
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
    res = scan_doc("\\ifnum \\count0 < 2 A side text here \\else B side text \\fi")
    b = blob(res)
    assert "\\count" not in b


# ---------------------------------------------------------------- math-debt 误报


def test_audit_verb_dollar_no_false_debt() -> None:
    r"""``\\verb|$HOME|`` 的 ``$`` 是逐字内容——不压 math_debt。"""
    body = "Use \\verb|$HOME| then math $x^2$ done here."
    res = scan_doc(body)
    assert not any(w.kind == "debt_repair" for w in res.warnings)
    assert any(v == "$x^2$" for v in res.ph_map.values())
    assert reconstruct(res) == DOC % body


def test_audit_comment_dollar_no_false_debt() -> None:
    r"""in_arg 注释里的 ``$``（``% cost $5``）同样不压 math_debt。"""
    res = scan_doc("\\caption{aa % has $9\n bb $x$ cc text}")
    assert not any(w.kind == "debt_repair" for w in res.warnings)
    assert any(v == "$x$" for v in res.ph_map.values())


def test_audit_url_dollar_no_false_debt() -> None:
    r"""``\\url{..$..}`` verbatim 参数内的 ``$`` 不压 math_debt。"""
    res = scan_doc("See \\url{http://x/$a} and math $y$ words here.")
    assert not any(w.kind == "debt_repair" for w in res.warnings)


# ---------------------------------------------------------------- argspec / _args


def test_audit_argspec_t_single_char_delim() -> None:
    r"""xparse ``t`` 取单字符定界符——``t*m`` = ``t*`` + ``m``。"""
    spec = parse_argspec("t*m")
    assert [(s.kind, s.delim) for s in spec] == [("t", "*"), ("m", "")]


def test_audit_def_params_span_newline() -> None:
    r"""``\def\a#1\n#2{BODY}``：参数文本 ``\n`` 成 space token → ``#1`` 空格定界。

    v2 按 TeX 语义登记 [delim, m]（v1 的 ["m","m"] 是近似）；关键是登记成功
    且无 def_parse_fail——v1 此前 ``\n`` 硬停曾静默不登记零 warning。
    """
    res = parse_tex("\\def\\a#1\n#2{BODY}\ntext after \\a{x}{y} end")
    e = res.macros.lookup("a")
    assert e is not None
    assert [s.kind for s in e.spec] == ["delim", "m"]
    assert not any(w.kind == "def_parse_fail" for w in res.warnings)


def test_audit_def_bodyless_warns() -> None:
    r"""纯 ``#n`` 序列后无 ``{body}``（EOF 截断）→ ``def_parse_fail``。"""
    res = parse_tex("\\def\\c#1")
    assert res.macros.lookup("c") is None
    assert any(w.kind == "def_parse_fail" for w in res.warnings)


def test_audit_unknown_cmd_arg_not_across_parbreak() -> None:
    r"""未知命令的 ``{arg}`` 吸收不跨 ``\n\n``——TeX 不定界参数遇 ``\par`` 停。"""
    res = scan_doc("Text \\foo\n\n{arg} more text here.")
    assert not any("\\foo\n\n{arg}" in v for v in res.ph_map.values())


def test_audit_crlf_ws_skip() -> None:
    r"""CRLF 文件：``\\newcommand{\\x}\\r\\n{body}`` 的 body 必须消费。"""
    res = parse_tex(
        "\\documentclass{article}\r\n\\begin{document}\r\n"
        "\\newcommand{\\x}\r\n{bodytext} para text here.\r\n\\end{document}\r\n"
    )
    assert res.macros.lookup("x") is not None


def test_audit_protect_call_opt_not_across_parbreak() -> None:
    res = scan_doc("See \\cite\n\n[opt]{key} rest text here.")
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
    res = scan_doc(body)
    assert "discarded text after" not in blob(res)
    assert reconstruct(res) == DOC % body


# ---------------------------------------------------------------- reconstruct


def test_audit_reconstruct_self_ref_no_recursion() -> None:
    r"""译文自指 ``[[CHUNK_k]]``（LLM 幻觉）→ 留 token 不 RecursionError。"""
    res = scan_doc("Some long enough text here to chunk.")
    tid = res.chunks[0].id
    out = reconstruct(res, {tid: f"自指 [[CHUNK_{tid}]] 译文"})
    assert "自指" in out


def test_audit_ph_collision_identity() -> None:
    r"""源文含 ``[[CMD_1]]`` 形字面 + 同名占位符签发 → identity 不破。"""
    body = "text \\foo{a} and literal [[CMD_1]] in source"
    res = scan_doc(body)
    assert reconstruct(res) == DOC % body
    assert any(w.kind == "ph_collision" for w in res.warnings)


def test_audit_chunk_collision_identity() -> None:
    r"""``[[CHUNK_0]]`` 形字面落在可译文本内 → 死位跳号 + 字面逐字还原。"""
    body = "literal [[CHUNK_0]] in source then a long enough paragraph text to chunk."
    res = scan_doc(body)
    assert reconstruct(res) == DOC % body


# ---------------------------------------------------------------- env / 其他


def test_audit_stray_end_empty_stack_warns() -> None:
    r"""裸 ``\\end{env}``（栈空）也发 ``stray_end``——静默降级是本项目大忌。"""
    res = scan_doc("para text here \\end{itemize} more text")
    assert any(w.kind == "stray_end" for w in res.warnings)


def test_audit_find_env_end_skips_verb() -> None:
    r"""``\\verb|\\end{equation}|`` 内的假闭合不截断 env 体。"""
    body = "\\begin{equation}x \\verb|\\end{equation}| y\\end{equation} tail text."
    res = scan_doc(body)
    math = [v for v in res.ph_map.values() if v.startswith("\\begin{equation}")]
    assert math
    assert math[0].endswith("y\\end{equation}"), res.ph_map
    assert reconstruct(res) == DOC % body


def test_audit_empty_protect_arg_no_ph() -> None:
    r"""TRANSPARENT 宏缺省可选参的零宽占位不签发空 ``[[KEY]]``。"""
    res = scan_doc("\\newcommand{\\secref}[1][]{See \\ref{#1}}\n\\secref text here.")
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
    rng = fuzz_rng(42)
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
    rng = fuzz_rng(7)
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


@pytest.mark.slow
@pytest.mark.skipif(
    not any(_CORPUS.rglob("meta.json")),
    reason="bench/corpus_v3 数据不在本地（gitignored 数据层）",
)
def test_audit_corpus_pieces_tiling_sample() -> None:
    """corpus_v3 抽样：pieces 平铺 + protected_tex 自洽 + reconstruct 无异常。"""
    mains = _corpus_mains()
    rng = fuzz_rng(1)
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
    res = scan_doc(
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


# ---------------------------------------------------------------- scanner-audit F 系列（2026-09-15 修复钉）


def test_audit_f1_deep_bracket_no_recursion_crash() -> None:
    r"""F1：``[``×1500 深嵌套不爆栈——match_bracket 已迭代化。"""
    res = parse_tex(DOC % ("\\cite" + "[" * 1500 + "x" + "]" * 1500 + " tail"))
    assert res is not None  # 不抛 RecursionError 即过
    assert reconstruct(res) == DOC % (
        "\\cite" + "[" * 1500 + "x" + "]" * 1500 + " tail"
    )


def test_audit_f2_title_opt_short_vs_long() -> None:
    r"""F2：``\title[短题]{长题}`` 取 ``{长题}`` 为可译参数。"""
    res = scan_doc("\\title[Short Cap]{The Real Full Title Of The Paper}")
    contents = [c.content for c in res.chunks]
    assert any("Real Full Title" in c for c in contents)
    assert not any(c.strip() == "Short Cap" for c in contents)


def test_audit_f3_newenvironment_opt_default() -> None:
    r"""F3：``\newenvironment{env}[n][dflt]{beg}{end}`` 登记 + 尾部不回落。"""
    res = scan_doc(
        "\\newenvironment{mybox}[1][dflt]{\\textbf{#1} begintext}{endtext}\n"
        "Para text follows here with words."
    )
    assert res.macros.lookup_env("mybox") is not None
    assert not any(
        "begintext" in c.content or "endtext" in c.content for c in res.chunks
    )


def test_audit_f4_comment_between_cmd_and_arg() -> None:
    r"""F4：``\cite%\n{key}`` 注释断参已修——key 进 CITE 占位符不落正文。"""
    res = scan_doc(
        "See \\cite% note\n{key2020} and \\section% x\n{My Title} body text."
    )
    assert any("key2020" in v for v in res.ph_map.values())
    assert not any("key2020" in c.content for c in res.chunks)
    assert any("My Title" in c.content for c in res.chunks)


def test_audit_f4_comment_then_blank_line_still_par() -> None:
    r"""F4 边界：注释吃完紧跟空行仍是 ``\par``——``\section%c\n\n{T}`` 不取参。

    ``{NotArg}`` 组本身作为正文文本 chunk 出现是合法（它本来就是正文），
    钉的是不产生 ``section`` 上下文的参数 chunk。
    """
    res = scan_doc("\\section% c\n\n{NotArg} body text here.")
    assert not any(c.context == "section" for c in res.chunks)


def test_audit_f5_math_close_skips_comments() -> None:
    r"""F5：``$$`` 闭合搜索跳注释——注释内 ``$$`` 不作闭合符。"""
    body = "Math $$ a % b $$ still comment\nc $$ done"
    res = scan_doc(body)
    math_ph = [v for v in res.ph_map.values() if v.startswith("$$")]
    # 正确配对应吞到第二行真 $$（含注释行整段），不是注释内的假 $$
    assert any("still comment" in v for v in math_ph)
    assert reconstruct(res) == DOC % body


def test_audit_f7_hard_cut_never_splits_token() -> None:
    r"""F7：硬切点处横跨的 ``[[X_n]]`` 不再腰斩（全 core 扫 token）。"""
    # 构造：>CHUNK_MAX 且无安全切点，长 token 起点在旧探测窗外
    tok = "[[GRAPHICS_99999]]"
    core = "a" * 3983 + tok + "b" * 100
    res = scan_doc("\\footnote{" + core + "}")
    # 所有 chunk 内的 [[X_n]] 必须完整可匹配（不断腰）
    for c in res.chunks:
        for m in re.finditer(r"\[\[", c.content):
            assert re.match(r"\[\[[A-Z_]+_\d+\]\]", c.content[m.start() :])
    assert reconstruct(res) == DOC % ("\\footnote{" + core + "}")


def test_audit_f9_backtick_escape_charcode() -> None:
    r"""F9：``\ifnum`\A=65`` 转义形字符码消费 3 字符、值取 A=65。"""
    res = scan_doc("\\ifnum`\\A=65 yes branch text that is long enough to chunk\\fi")
    # 'A' 不再成残片落 chunk
    assert not any(c.content.startswith("A=65") for c in res.chunks)
    assert (
        reconstruct(res)
        == DOC % "\\ifnum`\\A=65 yes branch text that is long enough to chunk\\fi"
    )


def test_audit_f11_url_delim_form() -> None:
    r"""F11：``\url|http://…|`` 定界形整体进 URL 占位符。"""
    res = scan_doc("See \\url|http://example.com| for more info here.")
    assert any("http://example.com" in v for v in res.ph_map.values())
    assert not any("example.com" in c.content for c in res.chunks)


def test_audit_f10_e_spec_arg_consumed() -> None:
    r"""F10：``e{^}`` 修饰参消费 ``^{arg}``——``{sup}{second}`` 不落正文。

    OPAQUE 宏整段进 ``[[MACRO]]``：旧实现 ``e`` 不占位 → 第二 ``m`` 把
    ``^`` 当单 token 参吞掉，``{sup}{second}`` 裸组落 chunk。
    """
    body = (
        "\\NewDocumentCommand{\\x}{m e{^} m}{#1#2}\n"
        "Before \\x{first}^{sup}{second} after words here."
    )
    res = scan_doc(body)
    b = blob(res)
    assert "{sup}" not in b
    assert "{second}" not in b
    assert "first" not in b  # 整调用 [[MACRO]]，无残片
    assert reconstruct(res) == DOC % body


def test_audit_f10_e_spec_absent_keeps_position() -> None:
    r"""F10 缺省形：``\\x{a}{b}`` 无 ``^``——e 位占零宽、后参不错位。"""
    body = (
        "\\NewDocumentCommand{\\x}{m e{^} m}{#1#2}\n"
        "Before \\x{first}{second} after words here."
    )
    res = scan_doc(body)
    b = blob(res)
    assert "{second}" not in b
    assert "first" not in b
    assert reconstruct(res) == DOC % body


def test_audit_f10_e_spec_multi_tokens() -> None:
    r"""F10：``e{^_}`` 双 token——``^{a}_{b}`` 全段覆盖。"""
    body = (
        "\\NewDocumentCommand{\\x}{m e{^_} m}{#1#2}\n"
        "Before \\x{first}^{up}_{dn}{second} after words."
    )
    res = scan_doc(body)
    b = blob(res)
    assert "{up}" not in b
    assert "{dn}" not in b
    assert "{second}" not in b
    assert reconstruct(res) == DOC % body


def test_audit_f6_theorem_opt_title_flows() -> None:
    r"""F6：``\begin{theorem}[标题]`` 的 ``[opt]`` 放行成正文 chunk。

    旧规格（§3.5）无条件吞 opt → 定理标题永不翻译（corpus 8.3%）。
    """
    body = (
        "\\begin{theorem}[Pythagoras 定理] Body text of the theorem here "
        "long enough. \\end{theorem}"
    )
    res = scan_doc(body)
    b = blob(res)
    assert "Pythagoras" in b
    assert reconstruct(res) == DOC % body


def test_audit_f6_proof_opt_title_flows() -> None:
    r"""F6：amsthm ``\begin{proof}[Proof of X]`` 同理放行。"""
    body = "\\begin{proof}[Proof of Main Lemma] We argue as follows at length. \\end{proof}"
    res = scan_doc(body)
    assert "Proof of Main Lemma" in blob(res)


def test_audit_f6_format_opts_still_eaten() -> None:
    r"""F6 对照：版式参照吃——``[noitemsep]``（列表容器 env）与 ``[t]``。"""
    body = (
        "\\begin{itemize}[noitemsep]\\item first item text here\\end{itemize}\n"
        "\\begin{mybox}[t] box body text enough to chunk words \\end{mybox}"
    )
    res = scan_doc(body)
    b = blob(res)
    assert "noitemsep" not in b
    assert "[t]" not in b
    assert reconstruct(res) == DOC % body


def test_audit_ifconst_hmode_vmode_plastex_truth() -> None:
    r"""``\\ifhmode``→True、``\\ifvmode``→False——plasTeX 恒值（曾写反）。"""
    res = scan_doc(
        "\\ifvmode dead branch text that should not chunk "
        "\\else live branch words that should chunk \\fi"
    )
    b = blob(res)
    assert "live branch words" in b
    assert "dead branch text" not in b
    res = scan_doc(
        "\\ifhmode live branch words that should chunk "
        "\\else dead branch text that should not chunk \\fi"
    )
    b = blob(res)
    assert "live branch words" in b
    assert "dead branch text" not in b


def test_audit_f12_unclosed_env_nested_surplus() -> None:
    r"""F12：未闭合 env 墓标（``_EnvDead``）的嵌套盈余直答 ≡ 逐字符重扫。

    外 ``\\begin{equation}`` 查询失败录墓标；内层同 env 查询按
    ``S(x)==S(j)``（盈余相等）bisect 直答 ``\\end`` 命中；第三个同 env
    ``\\begin`` 在墓标内无满足盈余的 end → None。可观察面：恰两条
    unclosed_env、内层 env 成 ``[[MATH]]``、identity 不破。
    """
    tex = (
        "pre \\begin{equation} mid \\begin{equation} x+y \\end{equation} "
        "post \\begin{equation} tail"
    )
    res = parse_tex(tex)
    assert [w.kind for w in res.warnings] == ["unclosed_env", "unclosed_env"]
    assert "\\begin{equation} x+y \\end{equation}" in res.ph_map.values()
    assert reconstruct(res) == tex


def test_audit_f12_unclosed_env_perf_gate() -> None:
    r"""F12 性能门（docs/07 §11 max≤500ms）：800 未闭合 ``\\begin`` 不再 O(N·n)。"""
    tex = "".join(f"text {k} \\begin{{equation}} x_{{{k}}}+y\n\n" for k in range(800))
    t0 = time.perf_counter()
    res = parse_tex(tex)
    gate_s = 0.5  # docs/07 §11 max≤500ms
    assert time.perf_counter() - t0 < gate_s
    assert reconstruct(res) == tex


def test_audit_minor_cite_second_brace_is_text() -> None:
    r"""audit 次要 2：``\cite{a}{b}`` 的 ``{b}`` 是正文不是参数——mand=1。

    修复前 ``_protect_call`` 固定吃 3 个 ``{..}`` 组，``{b}`` 被藏进
    ``[[CITE]]`` 体永不进 chunk。
    """
    res = scan_doc("See \\cite{key2020}{second group is body text} for details.")
    b = blob(res)
    assert "second group is body text" in b
    assert (
        reconstruct(res)
        == DOC % "See \\cite{key2020}{second group is body text} for details."
    )


def test_audit_minor_escaped_bracket_not_math_close() -> None:
    r"""audit 次要 1：``\\\\]`` 不提前关闭 ``\\[..\\]``——``\\<x>`` 成对消费。

    同理 ``\\%`` 不杀闭符搜索（百分号前反斜杠是转义不是注释头）。
    """
    body = "display \\[ a \\\\] b \\] math done. tail text words here."
    res = scan_doc(body)
    assert reconstruct(res) == DOC % body
    # \\[..\\] 整段一个 MATH 占位符——体含 \\] 残片
    math_bodies = [v for k, v in res.ph_map.items() if k.startswith("[[MATH_")]
    assert any("\\\\]" in v for v in math_bodies)


def test_audit_minor_boundary_tail_args_stay_literal() -> None:
    r"""audit 次要 3：``\\setlength{\\parindent}{0pt}`` 结构参进 LITERAL。

    修复前 BOUNDARY 只盖命令名，``{\\parindent}{0pt}`` 落正文 chunk——
    裸命令进译文。结构参消费但 ``\\item[label]`` 的可译 label 不收。
    """
    res = scan_doc("\\setlength{\\parindent}{0pt}Body text words here enough.")
    b = blob(res)
    assert "parindent" not in b
    assert "0pt" not in b
    assert "Body text words here enough" in b
    assert (
        reconstruct(res)
        == DOC % "\\setlength{\\parindent}{0pt}Body text words here enough."
    )
