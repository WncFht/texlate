r"""M1 展开层（mouth/gullet）单元测试：docs/07 §8 验收面。

逐条锁 ``docs/research/latex/expansion-design.md`` §12 移植表的行为：
三态 tokenize / 注释吞行 / ``\def`` 定界参数族 / ``\newcommand`` 调用点 /
``\makeatletter`` / ``\if`` 两档 / 预算降级。corpus 级验证在 bench 侧。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from texlate.latex.gullet import BUDGET, Gullet
from texlate.latex.mouth import CC_LETTER, CatTable, Mouth, Tok

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def toks(src: str) -> list[Tok]:
    """Mouth 全量 tokenize。"""
    return list(Mouth(src))


def text_of(ts: list[Tok]) -> str:
    """token 流 → 表面文本（cs 反带 ``\\``；``consumed`` marker 是事件非文本）。"""
    return "".join(str(t) for t in ts if t.kind != "consumed")


def expand(src: str) -> tuple[list[Tok], Gullet]:
    """Gullet 全量展开，返回 (tokens, gullet) 便于查 warnings。"""
    g = Gullet(src)
    return list(g), g


def expanded_text(src: str) -> str:
    """展开到不动点后的表面文本。"""
    ts, _ = expand(src)
    return text_of(ts)


# ---------------------------------------------------------------- Mouth 三态


def test_mouth_state_m_space_collapse() -> None:
    r"""M 态连续空白折一枚 Space token（``a  \t b`` → ``a`` `` `` ``b``）。"""
    ts = toks("a  \t b")
    assert [(t.kind, t.text) for t in ts] == [
        ("letter", "a"),
        ("space", " "),
        ("letter", "b"),
    ]


def test_mouth_state_n_leading_space_skipped() -> None:
    r"""N 态（行首/源首）空白不产生 token。"""
    ts = toks("   a")
    assert [(t.kind, t.text) for t in ts] == [("letter", "a")]
    ts = toks("a\n   b")  # 行内 \n 后回 N → 下行行首空白跳过
    assert [(t.kind, t.text) for t in ts] == [
        ("letter", "a"),
        ("space", " "),
        ("letter", "b"),
    ]


def test_mouth_state_s_trailing_space_absorbed() -> None:
    r"""S 态（cs/空白后）空白吸收：``a \n b`` 只产一枚 Space。"""
    ts = toks("a \n b")
    assert [(t.kind, t.text) for t in ts] == [
        ("letter", "a"),
        ("space", " "),
        ("letter", "b"),
    ]


def test_mouth_blank_line_eol_par_dedup() -> None:
    r"""N 态 ``\n`` → ``eol_par`` 且相邻去重（``\n\n\n`` = 一个段落边界）。"""
    ts = toks("a\n\n\nb")
    kinds = [(t.kind, t.text) for t in ts]
    assert kinds == [
        ("letter", "a"),
        ("space", " "),
        ("eol_par", "\n"),
        ("letter", "b"),
    ]


def test_mouth_comment_swallows_line() -> None:
    r"""``%`` 吞到行尾含 ``\n`` 本身；下行从 N 态起。"""
    ts = toks("a % comment \\fake{}\n   b")
    assert [(t.kind, t.text) for t in ts] == [
        ("letter", "a"),
        ("space", " "),
        ("letter", "b"),
    ]


def test_mouth_comment_eof_no_newline() -> None:
    r"""无换行的尾部注释吞到 EOF，不产 token。"""
    ts = toks("a % tail")
    assert [(t.kind, t.text) for t in ts] == [("letter", "a"), ("space", " ")]


def test_mouth_cs_letters_and_space_absorb() -> None:
    r"""``\foo`` 字母串成 cs；后随空白吸收（TeX 规则）。"""
    ts = toks("\\foo  bar")
    assert [(t.kind, t.text) for t in ts] == [
        ("cs", "foo"),
        ("letter", "b"),
        ("letter", "a"),
        ("letter", "r"),
    ]


def test_mouth_cs_nonletter_single_char() -> None:
    r"""``\``+非字母 → 单字符 cs（``\$`` ``\%`` ``\\``）。"""
    ts = toks("\\$\\%\\\\")
    assert [(t.kind, t.text) for t in ts] == [
        ("cs", "$"),
        ("cs", "%"),
        ("cs", "\\"),
    ]


def test_mouth_push_tokens_lifo() -> None:
    r"""``push_tokens`` 逆序塞左端：推回 token 先于源流、内部保序。"""
    m = Mouth("zz")
    m.push_tokens([Tok("letter", "a", (-1, 0, 1)), Tok("letter", "b", (-1, 0, 1))])
    assert [t.text for t in m] == ["a", "b", "z", "z"]


def test_mouth_catcode_shared_mutation() -> None:
    r"""CatTable 共享可变：翻 ``@`` 后 ``\@x`` 成单 cs（拉取式硬理由）。"""
    cats = CatTable()
    m = Mouth("\\@x \\@y", cats=cats)
    first = m.next()
    assert (first.kind, first.text) == ("cs", "@")  # @ 尚非字母 → 单字符 cs
    cats.set("@", CC_LETTER)
    rest = [t.text for t in m]
    assert rest == ["x", " ", "@y"]  # 单字符 cs 不吸后随空白（仅 word-cs 吸）


# ---------------------------------------------------------------- \def 家族


def test_gullet_def_simple_expand() -> None:
    r"""``\def\a{some text}\a`` → 体文本展开。"""
    assert expanded_text("\\def\\a{some text}\\a") == "some text"


def test_gullet_def_undelimited_params() -> None:
    r"""``\def\m#1#2{...}`` 无界参数：``{grp}`` 剥壳、裸 token 直取。"""
    out = expanded_text("\\def\\m#1#2{see #1 and #2}\\m{ab}{cd}")
    assert out == "see ab and cd"


def test_gullet_def_delimited_params() -> None:
    r"""``\def\ra[#1 #2 #3]{got #1|#2|#3}\ra[A B C]`` ——语料实测形（§12 锚点）。"""
    out = expanded_text("\\def\\ra[#1 #2 #3]{got #1|#2|#3}\\ra[A B C]")
    assert out == "got A|B|C"


def test_gullet_def_delimiter_keeps_group_braces() -> None:
    r"""定界参数命中 ``{...}`` → 组**带括号**作整体（plasTeX 同语义）。"""
    out = expanded_text("\\def\\d#1,{got #1}\\d{ab,cd},x")
    assert out == "got {ab,cd}x"


def test_gullet_def_hash_brace_until_group() -> None:
    r"""``#{`` 尾形：参数读到 ``{`` 止、``{`` 回吐重开组。"""
    ts, _ = expand("\\def\\rg#1#{pre #1 end}\\rg abc{grp}rest")
    assert text_of(ts) == "pre abc end{grp}rest"


def test_gullet_def_nested_double_hash() -> None:
    r"""嵌套 ``\def``：体里 ``##1`` 展开期折一层 → 内层收 ``#1``。

    折叠判定域是**参数文本**——外层体里的 ``##`` 留给 expand_def，
    若 def 时折叠会把 ``#1`` 当外层参数吞掉（回归：曾产 ``bb{x}``）。
    """
    out = expanded_text("\\def\\a{\\def\\b##1{bb##1}}\\a\\b{x}")
    assert out == "bbx"


def test_gullet_def_double_hash_in_ptext_rescued() -> None:
    r"""``\def\b##1{bb##1}`` 直写（非法 TeX，plasTeX 容忍）：参数文本 ``##`` → 整体折一层。"""
    assert expanded_text("\\def\\b##1{bb##1}\\b{x}") == "bbx"


def test_gullet_def_literal_hash_in_body() -> None:
    r"""体里 ``##`` 在展开期变字面 ``#``（需带文本词防 opaque 分类）。"""
    assert expanded_text("\\def\\a{some ## text}\\a") == "some # text"


def test_gullet_def_arg_mismatch_passthrough() -> None:
    r"""参数失配 → 已读回吐 + ``\name`` 本体交出（§3.5 降级线）。"""
    ts, g = expand("\\def\\m[#1]{mm #1}\\m x")
    assert text_of(ts).startswith("\\m")
    assert not any(w.kind == "def_parse_fail" for w in g.warnings)


def test_gullet_def_parse_fail_unwinds() -> None:
    r"""``\def`` 缺体 → ``def_parse_fail`` warning + 全部回吐逐字。"""
    ts, g = expand("\\def\\m")
    assert "\\def" in text_of(ts)
    assert any(w.kind == "def_parse_fail" for w in g.warnings)


def test_gullet_def_products_carry_origin() -> None:
    r"""展开产物 ``gen>0`` 且 ``origin`` = 调用点 pos（§2.3 splice 语义）。"""
    ts, _ = expand("\\def\\a{xy}p\\a q")
    prods = [t for t in ts if t.gen > 0]
    assert prods
    assert all(t.origin == (0, 11, 13) for t in prods)


def test_gullet_products_origin_covers_full_call() -> None:
    r"""``origin`` = 整调用区间（含 args）——``\\sw{a}{b}`` 的 args 字节不漏出。

    segmenter-integration §4 表首行：``expand_def`` 原只打 ``trig.pos``
    （cs 名区间）→ ``_invoke`` 返回前按 ``_trace`` 末位补打。
    """
    src = "\\def\\sw#1#2{#2 and #1}\\sw{a}{b}"
    ts, _ = expand(src)
    call = (0, src.index("\\sw{a}"), len(src))
    prods = [t for t in ts if t.gen > 0]
    assert prods
    assert all(t.origin == call for t in prods)
    # gen=0 实参 token 不打 origin——靠 pos 落在调用区间内归组
    args = [t for t in ts if t.gen == 0 and call[1] < t.pos[1] < call[2]]
    assert args
    assert all(t.origin is None for t in args)


# ---------------------------------------------------------------- \newcommand 族


def test_gullet_newcommand_plain() -> None:
    r"""``\newcommand{\f}[2]{F #1 #2}`` 调用点代入。"""
    out = expanded_text("\\newcommand{\\f}[2]{Fo #1 #2}\\f{a}{b}")
    assert out == "Fo a b"


def test_gullet_newcommand_optional_default() -> None:
    r"""``[N][d]`` 可选参数：缺省用 default、显式覆盖。"""
    out = expanded_text(
        "\\newcommand{\\foo}[2][dflt]{Fo #1 #2}\\foo{x} and \\foo[op]{y}"
    )
    assert out == "Fo dflt x and Fo op y"


def test_gullet_newcommand_star_form() -> None:
    r"""``\newcommand*`` 星形照常登记。"""
    out = expanded_text("\\newcommand*{\\f}{StarText}\\f")
    assert out == "StarText"


def test_gullet_providecommand_no_clobber() -> None:
    r"""``\providecommand`` 不覆盖已有定义（setdefault 语义）。"""
    out = expanded_text("\\newcommand{\\f}{First}\\providecommand{\\f}{Second}\\f")
    assert out == "First"


def test_gullet_renewcommand_clobbers() -> None:
    r"""``\renewcommand`` 覆盖。"""
    out = expanded_text("\\newcommand{\\f}{First}\\renewcommand{\\f}{Next}\\f")
    assert out == "Next"


# ---------------------------------------------------------------- catcode / \makeatletter


def test_gullet_makeatletter_scope() -> None:
    r"""``\makeatletter`` 翻 ``@`` → ``\@x`` 成单 cs；``\makeatother`` 翻回。"""
    ts, _ = expand("\\makeatletter\\def\\@x{yea}\\@x\\makeatother")
    assert "yea" in text_of(ts)


def test_gullet_at_outside_scope_is_nonletter() -> None:
    r"""``\@x`` 在 makeatletter 域外 = ``\@``+``x`` 两 token（TeX 本义）。"""
    ts, _ = expand("\\@x")
    assert [(t.kind, t.text) for t in ts] == [("cs", "@"), ("letter", "x")]


def test_gullet_catcode_prim() -> None:
    r"""``\catcode`@=11`` 原语直改共享表。"""
    g = Gullet("\\catcode`@=11 \\@z")
    ts = list(g)
    assert ("cs", "@z") in [(t.kind, t.text) for t in ts]


# ---------------------------------------------------------------- \if 两档


def test_gullet_iftrue_iffalse_select() -> None:
    r"""可求值档：条件消费、只放选中支（``\ifnum`` 同）。"""
    assert expanded_text("\\iftrue T\\else F\\fi") == "T"
    assert expanded_text("\\iffalse T\\else F\\fi") == "F"
    assert expanded_text("\\ifnum 3>2 T\\else F\\fi") == " T"
    assert expanded_text("\\ifnum 1>2 T\\else F\\fi") == "F"  # \else 后空格被吸


def test_gullet_ifcase_index() -> None:
    r"""``\ifcase`` 按值选支、超界落 else——``_read_number`` 返 float 需 ``int()``。"""
    assert expanded_text("\\ifcase 0 z\\or o\\or t\\fi") == " z"  # 数字后空格回吐
    assert expanded_text("\\ifcase 1 z\\or o\\or t\\fi") == "o"  # \or 后空格被吸
    assert expanded_text("\\ifcase 2 z\\or o\\or t\\fi") == "t"
    assert expanded_text("\\ifcase 9 z\\or o\\else e\\fi") == "e"


def test_gullet_ifodd() -> None:
    assert expanded_text("\\ifodd 3 odd\\else even\\fi") == " odd"
    assert expanded_text("\\ifodd 4 odd\\else even\\fi") == "even"


def test_gullet_if_unknown_landmark_both_branches() -> None:
    r"""界标档：``\ifblah`` 不可求值 → ``\ifX``+``\else``+``\fi`` 界标齐放、双支都流。"""
    ts, _ = expand("\\ifblah T\\else F\\fi")
    names = [(t.kind, t.text) for t in ts]
    assert names == [
        ("cs", "ifblah"),
        ("letter", "T"),
        ("cs", "else"),
        ("letter", "F"),
        ("cs", "fi"),
    ]


def test_gullet_if_nested_selected_branch() -> None:
    r"""嵌套 ``\if`` 在弃支里正确计深——真 ``if*`` 计、宏表 ``if*`` 不计。"""
    src = "\\ifnum 1>2 \\ifnum 3>2 X\\else Y\\fi \\else W\\fi"
    assert expanded_text(src) == "W"


def test_gullet_newif_lifecycle() -> None:
    r"""``\newif\ifzz`` → IfCond+双 IfSetter；``\zztrue/false`` 翻旗标。"""
    assert expanded_text("\\newif\\ifzz\\zztrue\\ifzz T\\else F\\fi") == "\\zztrueT"
    assert expanded_text("\\newif\\ifzz\\zzfalse\\ifzz T\\else F\\fi") == "\\zzfalseF"


def test_gullet_ifdefined_and_ifundefined() -> None:
    r"""``\ifdefined``/``\@ifundefined``（makeatletter 域内）双参取支。"""
    assert expanded_text("\\def\\zz{}\\ifdefined\\zz D\\else U\\fi") == "D"
    src = "\\makeatletter\\@ifundefined{zz}{UNDEF}{DEF}\\makeatother"
    assert "UNDEF" in expanded_text(src)
    src = "\\makeatletter\\def\\zz{}\\@ifundefined{zz}{UNDEF}{DEF}\\makeatother"
    assert "DEF" in expanded_text(src)


def test_gullet_if_unterminated_warns() -> None:
    r"""缺 ``\fi`` → ``if_unterminated`` warning（降级不崩）。"""
    _, g = expand("\\iftrue T no end")
    assert any(w.kind == "if_unterminated" for w in g.warnings)


# ---------------------------------------------------------------- let / edef / expandafter / csname


def test_gullet_let_snapshot() -> None:
    r"""``\let\t\s`` 快照当时含义：先 ``\def`` 后 ``\let`` → 别名生效。"""
    assert expanded_text("\\def\\s{see}\\let\\t\\s\\t") == "see"


def test_gullet_let_undefined_snapshot() -> None:
    r"""``\let`` 未定义源 → 别名落空（TeX 快照语义，非动态解析）。"""
    ts, _ = expand("\\let\\t\\s\\def\\s{see}\\t")
    assert ("cs", "t") in [(t.kind, t.text) for t in ts]


def test_gullet_let_literal_token() -> None:
    r"""``\let\eq==`` → ``\eq`` 以字面 ``=`` token 交出。"""
    ts, _ = expand("\\let\\eq== a\\eq b")
    assert ("other", "=") in [(t.kind, t.text) for t in ts]


def test_gullet_edef_eager_expansion() -> None:
    r"""``\edef`` 体即时展开：``\b`` → ``BB`` 先烤进体。"""
    assert expanded_text("\\def\\b{BB}\\edef\\e{\\b}\\e") == "BB"


def test_gullet_edef_noexpand_one_shot() -> None:
    r"""``\noexpand`` 一次性：edef 体存 ``\b`` 本体，调用点再展开 → ``BBBB``。"""
    assert expanded_text("\\def\\b{BB}\\edef\\e{\\b\\noexpand\\b}\\e") == "BBBB"


def test_gullet_noexpand_stream() -> None:
    r"""常流里 ``\noexpand\b`` → ``\b`` 本体交出（跳一次展开）。"""
    ts, _ = expand("\\def\\b{BB}\\noexpand\\b")
    assert ("cs", "b") in [(t.kind, t.text) for t in ts]


def test_gullet_expandafter_csname() -> None:
    r"""``\expandafter\def\csname zz\endcsname{..}`` ——经典 LaTeX 内联定义式。"""
    out = expanded_text("\\expandafter\\def\\csname zz\\endcsname{zzbody}\\zz")
    assert out == "zzbody"


def test_gullet_csname_builds_cs() -> None:
    r"""``\csname..\endcsname`` 拼名成 cs token；未定义 → 原样交分段器。"""
    ts, _ = expand("\\csname zz\\endcsname")
    assert ("cs", "zz") in [(t.kind, t.text) for t in ts]


# ---------------------------------------------------------------- 其他定义面


def test_gullet_newenvironment_registers() -> None:
    r"""``\newenvironment`` 登记 EnvDef（begin/end 本体交分段器裁决）。"""
    g = Gullet("\\newenvironment{bx}[1]{Beg<#1>}{End}\\begin{bx}{q}")
    list(g)
    e = g.macros.lookup_env("bx")
    assert e is not None
    assert len(e.spec) == 1


def test_gullet_newtheorem_registers() -> None:
    r"""``\newtheorem{n}[c]{Cap}[w]`` → 定理类 env（spec 带可选 caption 位）。"""
    g = Gullet("\\newtheorem{thm}[sec]{Theorem}[ch]")
    list(g)
    e = g.macros.lookup_env("thm")
    assert e is not None
    assert e.kind == "theorem"


def test_gullet_declare_math_operator() -> None:
    r"""``\DeclareMathOperator{\\Res}{Resid}`` → math 类（体包 ``\operatorname``）。"""
    g = Gullet("\\DeclareMathOperator{\\Res}{Resid}\\Res")
    ts = list(g)
    e = g.macros.lookup("Res")
    assert e is not None
    assert e.kind == "math"
    assert ("cs", "Res") in [(t.kind, t.text) for t in ts]  # math 不交展开层


def test_gullet_global_def_writes_bottom_frame() -> None:
    r"""``\\gdef`` → scope=global 落底帧。"""
    g = Gullet("\\gdef\\x{gtext}\\x")
    ts = list(g)
    e = g.macros.lookup("x")
    assert e is not None
    assert e.scope == "global"
    assert "gtext" in text_of(ts)


def test_gullet_long_outer_prefix_chain() -> None:
    r"""``\\long\\def`` 前缀链穿到 def 族。"""
    assert expanded_text("\\long\\def\\x{ltext}\\x") == "ltext"


def test_gullet_cs_letter_adjacency_classifies_transparent() -> None:
    r"""``\def\x{\text foo}`` ——被吸收空格使表面 ``\textfoo`` 粘连。

    ``_surface`` 在 cs+letter 邻接处补空格，否则整体当命令名剥掉、
    含文本的体误判 opaque（回归：曾不展开）。被吸空格在 token 层不可
    恢复——产出即 ``\\textfoo``，断言点在 ``\x`` 真的展开。
    """
    assert expanded_text("\\def\\x{\\text foo}\\x") == "\\textfoo"


def test_gullet_opaque_body_call_site_protected() -> None:
    r"""opaque 类（无文本体）调用点保护：``\m`` 本体交出、参数不读。"""
    ts, _ = expand("\\def\\m{x}\\m")
    assert ("cs", "m") in [(t.kind, t.text) for t in ts]


# ---------------------------------------------------------------- 预算降级


def test_gullet_gen_overflow_degrades() -> None:
    r"""``\def\loop{\loop loop}\loop`` 自归 → ``gen_overflow`` 一次 + 本体交出。"""
    ts, g = expand("\\def\\loop{\\loop loop}\\loop")
    assert ("cs", "loop") in [(t.kind, t.text) for t in ts]
    assert [w.kind for w in g.warnings].count("gen_overflow") == 1


def test_gullet_budget_overflow_degrades(monkeypatch: pytest.MonkeyPatch) -> None:
    r"""steps 顶到 ``BUDGET`` → ``expansion_overflow`` 一次、余者逐字。"""
    monkeypatch.setattr("texlate.latex.gullet.BUDGET", 4)
    ts, g = expand("\\def\\a{alpha}\\def\\b{\\a beta}\\b\\b\\b")
    assert any(w.kind == "expansion_overflow" for w in g.warnings)
    assert ("cs", "b") in [(t.kind, t.text) for t in ts]


def test_gullet_budget_warns_once(monkeypatch: pytest.MonkeyPatch) -> None:
    r"""溢出 warning 只记一次（``overflow`` 旗标防抖）。"""
    monkeypatch.setattr("texlate.latex.gullet.BUDGET", 4)
    _, g = expand("\\def\\a{alpha}\\a\\a\\a\\a\\a\\a\\a\\a")
    assert len([w for w in g.warnings if w.kind == "expansion_overflow"]) == 1


def test_gullet_budget_default_budget_ample() -> None:
    r"""默认 BUDGET 内普通文档宏展开不触发溢出（常数冒烟）。"""
    assert isinstance(BUDGET, int)
    assert BUDGET > 0


# ---------------------------------------------------------------- \\input


def test_gullet_input_inlines_file(tmp_path: Path) -> None:
    r"""``\input{sub}`` 按 including 目录解析、内容进流（file_id 分源）。"""
    sub = tmp_path / "sub.tex"
    sub.write_text("sub words here", encoding="utf-8")
    g = Gullet("pre \\input{sub} post", root_dir=str(tmp_path))
    ts = list(g)
    assert "sub words here" in text_of(ts)


def test_gullet_input_missing_warns(tmp_path: Path) -> None:
    r"""缺文件 → ``missing_input`` warning + ``\input`` 本体逐字。"""
    g = Gullet("\\input{nosuchfile}", root_dir=str(tmp_path))
    ts = list(g)
    assert any(w.kind == "missing_input" for w in g.warnings)
    assert "\\input" in text_of(ts)


def test_gullet_input_cycle_broken(tmp_path: Path) -> None:
    r"""``a→b→a`` 祖先栈断环（W12）；兄弟位重包含不受影响。"""
    a = tmp_path / "a.tex"
    b = tmp_path / "b.tex"
    a.write_text("A\\input{b}A2", encoding="utf-8")
    b.write_text("B\\input{a}B2", encoding="utf-8")
    g = Gullet("\\input{a}", root_dir=str(tmp_path))
    ts = list(g)
    out = text_of(ts)
    assert "B" in out  # b 内容进流
    assert "B2" in out  # a 环断不递归


# ---------------------------------------------------------------- consumed marker / skip_past（§4 接线）


def test_gullet_def_emits_consumed_marker() -> None:
    r"""``\def`` 静默段 → ``consumed`` marker；pos 盖整个定义区段。"""
    src = "pre \\def\\a{x} post"
    ts, _ = expand(src)
    marks = [t for t in ts if t.kind == "consumed"]
    assert len(marks) == 1
    assert marks[0].text == "def:a"
    assert marks[0].pos == (0, 4, src.index(" post"))
    assert text_of(ts) == "pre  post"  # marker 不落表面文本


def test_gullet_marker_head_covers_prefix_chain() -> None:
    r"""``\long\global\def`` marker 自首个前缀 token 起算（``head`` 参数）。"""
    src = "\\long\\global\\def\\a{x}"
    ts, _ = expand(src)
    marks = [t for t in ts if t.kind == "consumed"]
    assert len(marks) == 1
    assert marks[0].text == "def:a"
    assert marks[0].pos == (0, 0, len(src))


def test_gullet_def_family_marker_names() -> None:
    r"""定义面 marker 文本 = ``family:payload``（newcommand/let/newif）。"""
    src = "\\newcommand{\\foo}[1]{#1!}\\let\\b\\foo\\newif\\ifzz"
    ts, _ = expand(src)
    marks = [t.text for t in ts if t.kind == "consumed"]
    assert marks == ["newcommand:foo", "let:b", "newif:zz"]


def test_gullet_env_def_markers() -> None:
    r"""``\newenvironment``/``\newtheorem``/``\DeclareMathOperator`` marker。"""
    src = (
        "\\newenvironment{bx}{B}{E}\\newtheorem{thm}{T}\\DeclareMathOperator{\\Res}{R}"
    )
    ts, _ = expand(src)
    marks = [t.text for t in ts if t.kind == "consumed"]
    assert marks == ["newenv:bx", "newtheorem:thm", "mathop:Res"]


def test_gullet_if_marker_covers_condition_only() -> None:
    r"""可求值 ``\if``：marker 盖 ``\if``+条件段——``process_if`` 前取端点。

    ``_read_number`` 末位多读一枚再回吐（条件后空格）→ 端点含该 token；
    其一字节重叠无害（覆盖去重、token 仍照流）。
    """
    src = "\\ifnum 1<2 T\\else F\\fi"
    ts, _ = expand(src)
    m = ts[0]
    assert m.kind == "consumed"
    assert m.text == "if:ifnum"
    assert m.pos == (0, 0, src.index("T"))
    assert text_of(ts) == " T"


def test_gullet_newif_cond_marker_just_cs() -> None:
    r"""``IfCond`` 无条件段——marker 恰盖 ``\ifzz`` 本体，不得延到 ``\fi``。"""
    src = "\\newif\\ifzz\\zztrue\\ifzz T\\else F\\fi"
    ts, _ = expand(src)
    m = [t for t in ts if t.kind == "consumed" and t.text == "if:ifzz"]
    assert len(m) == 1
    at = src.index("\\ifzz T")
    assert m[0].pos == (0, at, at + len("\\ifzz"))
    assert text_of(ts) == "\\zztrueT"


def test_gullet_input_marker_registers_path(tmp_path: Path) -> None:
    r"""``\input`` 成功 → marker 文本 ``input:<解析路径>``，pos 盖调用点。"""
    sub = tmp_path / "sub.tex"
    sub.write_text("sub words", encoding="utf-8")
    src = "pre \\input{sub} post"
    g = Gullet(src, root_dir=str(tmp_path))
    ts = list(g)
    marks = [t for t in ts if t.kind == "consumed"]
    assert len(marks) == 1
    assert marks[0].text.startswith("input:")
    assert marks[0].text.endswith("sub.tex")
    assert marks[0].pos == (0, src.index("\\input"), src.index(" post"))
    assert text_of(ts) == "pre sub words post"


def test_gullet_endinput_marker_and_sibling_reinclude(tmp_path: Path) -> None:
    r"""``\endinput`` → marker + 余下字节丢弃；``_seen`` 回撤使兄弟位再包含不断。"""
    sub = tmp_path / "sub.tex"
    sub.write_text("A\\endinput DISCARDED", encoding="utf-8")
    g = Gullet("\\input{sub} mid \\input{sub} tail", root_dir=str(tmp_path))
    ts = list(g)
    marks = [t.text for t in ts if t.kind == "consumed"]
    assert [m.split(":")[0] for m in marks] == [
        "input",
        "endinput",
        "input",
        "endinput",
    ]
    assert marks[0] == marks[2]  # 兄弟位重包含成功（_seen 已回撤）
    assert text_of(ts) == "A mid A tail"


def test_gullet_expansion_inner_marker_gen1() -> None:
    r"""展开产物里的 ``\def`` 执行 → marker ``gen>0``（仅组内边界语义）。"""
    ts, _ = expand("\\def\\a{ok \\def\\b{y}}\\a")
    marks = [t for t in ts if t.kind == "consumed"]
    assert [m.text for m in marks] == ["def:a", "def:b"]
    assert marks[0].gen == 0
    assert marks[1].gen > 0


def test_gullet_skip_past_resyncs_mouth() -> None:
    r"""``skip_past`` 把源消费指针推到闭合末，其后 token 照常读。"""
    src = "ab %verb\n cd"
    g = Gullet(src)
    assert g.read() is not None  # 拉一枚让 i 离开 0
    assert g.skip_past(0, src.index("cd"))
    assert text_of(list(g)) == "cd"


def test_gullet_skip_past_filters_tokbuf() -> None:
    r"""缓冲 token：``end<=pos`` 逐字区残骸丢、``start>=pos`` 真内容留。"""
    g = Gullet("0123456789abcdef")
    top = g.inputs[-1]
    stale = Tok("other", "%", (0, 3, 4))  # 落在闭合区间内 → 丢
    fresh = Tok("letter", "z", (0, 12, 13))  # 闭合符后 → 留
    top.push_tokens([fresh, stale])  # 逆序塞左端 → 弹出序 stale, fresh
    assert g.skip_past(0, 10)
    assert g.read() is fresh
    assert not top.tokbuf  # stale 残骸已丢


def test_gullet_skip_past_straddle_refused() -> None:
    r"""缓冲 token 跨界（start<pos<end）→ warning + False，源不动。"""
    g = Gullet("0123456789")
    g.inputs[-1].push_tokens([Tok("cs", "x", (0, 5, 8))])
    assert not g.skip_past(0, 6)
    assert any(w.kind == "verb_resync_failed" for w in g.warnings)


def test_gullet_skip_past_missing_fid_warns() -> None:
    r"""目标 fid 不在栈 → ``verb_resync_failed`` + False。"""
    g = Gullet("ab")
    assert not g.skip_past(9, 1)
    assert any(w.kind == "verb_resync_failed" for w in g.warnings)


def test_gullet_skip_past_under_synthetic_top() -> None:
    r"""栈顶 ``from_tokens`` 合成源（file_id<0）时向栈深找 fid，滞留源仍先排。"""
    g = Gullet("ab cd")
    g.inputs.append(Mouth.from_tokens([Tok("letter", "Q", (-1, 0, 1))], g.cats))
    assert g.skip_past(0, 3)  # 真源在栈深仍命中
    assert g.read().text == "Q"  # 合成 token 先排
    assert text_of(list(g)) == "cd"  # 合成源耗尽 → 真源自 i=3 续
