"""logparse — ErrReport 提取 + Taxonomy 分类单测 (合成 log)。

双错误格式：`^!` (原型原义) + `file:line:` (impl xelatex -file-line-error);
tail/warnings scope 与 undefined_cs→pdftex_prim subclassify 逐条覆盖。
"""

from functools import lru_cache
from pathlib import Path
from typing import Any

import pytest
from _fixloopkit import mk_ctx, rule, when_cond_ok

from texlate.compile.fixloop import Ruleset, actions, load_ruleset
from texlate.compile.fixloop.actions import _when_ok
from texlate.compile.logparse import (
    ErrReport,
    Taxonomy,
    _ctx_tail_css,
    parse_log,
    parse_text,
)


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    """ruleset 首用时加载——收集期不 IO（坏 yaml 报 test fail 而非 collection error）。"""
    return load_ruleset()


def _warn() -> list[dict[str, Any]]:
    return _rs().warn_patterns


def classify(text: str, *, timed_out: bool = False) -> tuple[str | None, str | None]:
    return _rs().taxonomy.classify(parse_text(text, _warn()), timed_out=timed_out)


# ---------------------------------------------------------------- ErrReport
def test_bang_and_ctx_and_line_no() -> None:
    rep = parse_text("pre\n! Undefined control sequence.\nl.12 \\foo\npost\n", _warn())
    assert rep.n_bang == 1
    assert rep.first == "! Undefined control sequence."
    assert "l.12" in rep.ctx
    assert rep.line_no == 12  # noqa: PLR2004 - 样本行号
    assert "post" in rep.tail


def test_file_line_error_format_counts() -> None:
    # impl xelatex 命令行带 -file-line-error: 错误是 path:line: 无 '!' 前缀
    rep = parse_text(
        "./main.tex:5: Undefined control sequence.\nl.5 \\foo\nok\n", _warn()
    )
    assert rep.n_bang == 1
    assert rep.first == "./main.tex:5: Undefined control sequence."


def test_file_line_warning_not_error() -> None:
    # 同格式的 Warning 行不算错误，否则 clean 门 (n_bang==0) 永不通过
    rep = parse_text(
        "./main.tex:5: LaTeX Warning: Reference `x' undefined\n./main.tex:9: Package foo Warning: bar\n",
        _warn(),
    )
    assert rep.n_bang == 0
    assert rep.first is None


def test_file_stack_tracked() -> None:
    rep = parse_text(
        "(./main.tex\n(./sub/chap.tex\n! Package soul Error: Reconstruction failed.\n",
        _warn(),
    )
    assert rep.file_stack == ["./main.tex", "./sub/chap.tex"]


def test_popped_files_runaway_capture() -> None:
    """runaway 错：``)`` 先于错误行弹真肇事件——popped_files 找回（#78）。"""
    rep = parse_text(
        "(./main.tex\n(./sub/bad.tex\nRunaway argument? )\n"
        "! File ended while scanning use of \\foo.\nl.5 x\n",
        _warn(),
    )
    assert rep.file_stack == ["./main.tex"]
    assert rep.popped_files == ["./sub/bad.tex"]


def test_popped_files_filters_none_frames() -> None:
    """非文件 ``(`` 的 ``None`` 配对帧不入 popped_files。"""
    rep = parse_text("(./main.tex\n(draft\nx ) y )\n! Emergency stop.\n", _warn())
    assert rep.file_stack == []
    assert rep.popped_files == ["./main.tex"]


def test_popped_files_empty_without_error() -> None:
    rep = parse_text("(./main.tex\n)clean\n", _warn())
    assert rep.popped_files == []


def test_parse_log_missing_path() -> None:
    rep = parse_log(None, _warn())
    assert rep.n_bang == 0
    assert rep.first is None
    assert rep.tail == ""


def test_parse_log_reads_file(tmp_path: Path) -> None:
    p = tmp_path / "main.log"
    p.write_text("x\n! Emergency stop.\n")
    rep = parse_log(p, _warn())
    assert rep.n_bang == 1


def test_warn_patterns_scanned() -> None:
    rep = parse_text("Missing character: There is no (U+FFFD) in font cmr10\n", _warn())
    assert "invalid_utf8" in rep.warnings
    assert "missing_char" in rep.warnings


# ---------------------------------------------------------------- taxonomy: head scope
@pytest.mark.parametrize(
    ("log", "cat", "pay"),
    [
        ("! LaTeX Error: File `import.sty' not found.", "missing_file", "import.sty"),
        ("! I can't find file `foo.sty'.", "missing_file", "foo.sty"),
        (
            "! Font \\iclrtenhv=phvb at 8.0pt not loadable: Metric (TFM) file",
            "missing_tfm",
            "phvb",
        ),
        # (\S+) 连句号一起吃进 payload —— 原型原样语义，不修剪
        ("! Cannot use XeTeXglyph with ptmr8c.", "xetexglyph_tfm", "ptmr8c."),
        (
            '! xdvipdfmx:fatal: Cannot proceed without .vf or "physical" font',
            "missing_pfb",
            None,
        ),
        (
            '! Package fontspec Error: The font "FandolSong-Regular" cannot be found',
            "fontspec_missing",
            "FandolSong-Regular",
        ),
        ("! Illegal unit of measure (pt inserted).", "illegal_unit", None),
        (
            "! LaTeX Error: Option clash for package hyperref.",
            "option_clash",
            "hyperref",
        ),
        (
            "! LaTeX Error: Command \\c@thm already defined.",
            "already_def",
            "c@thm",
        ),
        # 2026-09-19 反引号签扩收 (failmine2 \Bbbk 族 23 cells): 老
        # \@ifdefinable/amssymb 系 `` `\X' `` 形 —— 下行是 stagerun-loop2
        # compile.jsonl 原样实录 (amssymb.sty:261)。
        (
            (
                "/usr/share/texmf-dist/tex/latex/amsfonts/amssymb.sty:261: "
                "LaTeX Error: Command `\\Bbbk' already defined."
            ),
            "already_def",
            "Bbbk",
        ),
        # ltcmd `'\X'` 引号形 (1706.07911 实证)
        (
            "! LaTeX Error: Command '\\liningnums' already defined.",
            "already_def",
            "liningnums",
        ),
        # ntheorem 姊妹条目 (Theorem style X) 不受 Command 形扩收影响
        (
            "ntheorem.sty:524: LaTeX Error: Theorem style plain already defined",
            "already_def",
            "plain",
        ),
        # 负闸：`` `\X' `` 在邻接标记内不得误归 —— Control sequence 签
        # 留给 ctlseq/fontspec_double_merge 车道 (other, 无 payload);
        # "already defined" 短语锚不放的 (was never defined) 与
        # `` `X' `` 在无关报文内 均不落 already_def。
        (
            "ctex.sty:500: LaTeX Error: Control sequence \\chinese already defined.",
            "other",
            None,
        ),
        (
            "! LaTeX Error: Command `\\foo' was never defined.",
            "other",
            None,
        ),
        ("! Package foo Error: option `bar' unknown.", "other", None),
        ("! Package soul Error: Reconstruction failed.", "soul_err", None),
        ("! Not a letter.\nl.3 \\hyphenation{中-文}", "hyphenation", None),
        ("! Package minted Error: frozencache file missing.", "minted_froz", None),
        (
            "! LaTeX2e command \\usepackage in LaTeX 2.09 document.",
            "latex209",
            None,
        ),
        # undefined_cs payload 抓上下文顶行末位 cs 名 (供 polyfill/shadow 定位);
        # 无宏展开时顶行即 l.N 行 (payload-scout-2026-09-17)
        ("! Undefined control sequence.\nl.5 \\foo", "undefined_cs", "foo"),
        # 2026-09-19: \renewcommand 对未定义 cs 的内核签归 undefined_cs
        # (natbib \renewcommand\newblock 面，failmine2 ~13 cells)
        (
            "! LaTeX Error: Command \\newblock undefined.",
            "undefined_cs",
            "newblock",
        ),
        (
            "./main.bbl:1: LaTeX Error: Command \\newblock undefined.",
            "undefined_cs",
            "newblock",
        ),
        # 2026-09-16: inputenc 拒载 Unicode 引擎 (inputenc.sty:164)
        (
            "! Package inputenc Error: inputenc is not designed for xetex or luatex.",
            "inputenc_unicode",
            None,
        ),
        (
            "./main.tex:12: Package inputenc Error: inputenc is not designed for xetex or lua",
            "inputenc_unicode",
            None,
        ),
        # 2026-09-16: Extra } 族归 syntax (原落 other 兜底)
        ("! Extra }, or forgotten $.", "syntax", None),
        ("! Extra \\fi.", "syntax", None),
        ("! Forgotten \\endgroup.", "syntax", None),
        ("! TeX capacity exceeded, sorry.", "capacity", None),
        ("! Emergency stop.", "emergency", None),
        (
            "! LaTeX Error: \\begin{foo} on input line 5 ended by \\end{bar}.",
            "env_mismatch",
            None,
        ),
        ("! Missing $ inserted.", "syntax", None),
        # 2026-09-19 colorquote: 真实发射是 `` `X' `` 引法 + 三发行方
        # (ledger 实证; 原直引 pattern 零命中 ~44 cells 落 other)。
        (
            "! Package xcolor Error: Undefined color `MAROON'.",
            "undefined_color",
            "MAROON",
        ),
        (
            "! LaTeX Error: Undefined color `mygray'.",
            "undefined_color",
            "mygray",
        ),
        (
            "! Package color Error: Undefined color `White'.",
            "undefined_color",
            "White",
        ),
        # 直引形兼容收 (ledger 未见真实发射，防回归)
        (
            "! Package xcolor Error: Undefined color 'red'.",
            "undefined_color",
            "red",
        ),
        # "Undefined color model `X'" taxrow 并收 undefined_color (模型名
        # 非色名，消费侧自行分辨) —— undefined_color_fallback 的
        # ctx_suggests `Undefined color [`']` 闸把 model 形挡在投递外。
        (
            "! Package xcolor Error: Undefined color model `cmyk7'.",
            "undefined_color",
            "cmyk7",
        ),
        (
            "! LaTeX Error: Undefined color model `这是译文'.",
            "undefined_color",
            "这是译文",
        ),
        # ── 2026-09-20 extless 车道 (failmine4 9-cell): graphicx \Gin@i
        # 对无扩展名 \includegraphics{X} 落 `File `X' not found.` (裸
        # basename——前列 missing_file 臂要 \.ext 够不着，原落 other)。
        # 定证 = errhelp "I could not locate ... extensions:" 恒居错误行
        # +8, 恰出 ctx8 → use_post 扩展窗。下行实录自 2501.01277
        # (file-line 头 + l.N 回显折行，`...hics` 截断无完整 cs ——
        # cs 旁证够不着，errhelp 是唯一定证; payload 带路径原样)。
        (
            (
                "./introduction.tex:42: LaTeX Error: File `Figures/scope' not found.\n"
                "\n"
                "See the LaTeX manual or LaTeX Companion for explanation.\n"
                "Type  H <return>  for immediate help.\n"
                " ...\n"
                "\n"
                "l.42 ...hics[width=0.6\\columnwidth]{Figures/scope}\n"
                "\n"
                "I could not locate the file with any of these extensions:\n"
                ".pdf,.png,.jpg,.eps\n"
            ),
            "missing_graphic",
            "Figures/scope",
        ),
        # bang 头形态 (file-line 关掉的档) + l.N 回显完整 cs + errhelp。
        (
            (
                "! LaTeX Error: File `fig1' not found.\n"
                "\n"
                "See the LaTeX manual or LaTeX Companion for explanation.\n"
                "Type  H <return>  for immediate help.\n"
                " ...\n"
                "\n"
                "l.42 \\includegraphics{fig1}\n"
                "\n"
                "I could not locate the file with any of these extensions:\n"
                ".ps,.eps,.pstex\n"
            ),
            "missing_graphic",
            "fig1",
        ),
        # PoSlogo 钩形态 (0812.0404 实录): \AtBeginDocument 装载缺失
        # logo, l.N 回显 `\begin{document}` —— 回显无 graphic cs,
        # errhelp 仍是定证。
        (
            (
                "./proc_brauner.tex:303: LaTeX Error: File `PoSlogo' not found.\n"
                "\n"
                "See the LaTeX manual or LaTeX Companion for explanation.\n"
                "Type  H <return>  for immediate help.\n"
                " ...\n"
                "\n"
                "l.303 \\begin{document}\n"
                "\n"
                "I could not locate the file with any of these extensions:\n"
                ".ps,.eps,.pstex\n"
            ),
            "missing_graphic",
            "PoSlogo",
        ),
        # 参数折行截断形态 (2505.06480 实录): l.N 回显停在宏参数中段，
        # 无 cs —— `fig:pipeline_abstract` 的 `:` 不触发 file:line 闸。
        (
            (
                "./main_text.tex:68: LaTeX Error: File `01-abstract' not found.\n"
                "\n"
                "See the LaTeX manual or LaTeX Companion for explanation.\n"
                "Type  H <return>  for immediate help.\n"
                " ...\n"
                "\n"
                "l.68 ...tenna (green line)}{fig:pipeline_abstract}\n"
                "\n"
                "I could not locate the file with any of these extensions:\n"
                ".pdf,.png,.jpg,.eps\n"
            ),
            "missing_graphic",
            "01-abstract",
        ),
        # errhelp 缺席 (非 graphicx producer 或截断 log): l.N 回显的
        # graphic cs 为同窗旁证 —— per-err err_candidates 面 (无 post)
        # 也靠此支路。
        (
            (
                "! LaTeX Error: File `plot-a' not found.\n"
                "\n"
                "See the LaTeX manual or LaTeX Companion for explanation.\n"
                "Type  H <return>  for immediate help.\n"
                " ...\n"
                "\n"
                "l.12 \\includegraphics{plot-a}\n"
            ),
            "missing_graphic",
            "plot-a",
        ),
        # 无 errhelp 且无 graphic cs 的 ext-less File-not-found
        # (\lstinputlisting/\verbatiminput 型 producer 发不出 graphicx
        # errhelp): taxrow missing_file_extless 行收裸名 →
        # missing_file|stem → install_file filemap miss 后 decline。
        (
            (
                "! LaTeX Error: File `snippet' not found.\n"
                "\n"
                "See the LaTeX manual or LaTeX Companion for explanation.\n"
                "Type  H <return>  for immediate help.\n"
                " ...\n"
                "\n"
                "l.30 \\lstinputlisting{snippet}\n"
            ),
            "missing_file",
            "snippet",
        ),
        # tempered 前瞻闸：chunk1 (非图形 producer 短块) 不得跨后续错
        # 误起点 (`:9: ` file:line 前缀/`Error:`/`File ` 三重闸) 借
        # fig2 的证据 —— fig2 自有标记在位重命中，payload 归 fig2
        # 而非 chunk1 即闸生效。
        (
            (
                "! LaTeX Error: File `chunk1' not found.\n"
                "l.5 \\usechunk{chunk1}\n"
                "./main.tex:9: LaTeX Error: File `fig2' not found.\n"
                "\n"
                "See the LaTeX manual or LaTeX Companion for explanation.\n"
                "Type  H <return>  for immediate help.\n"
                " ...\n"
                "\n"
                "l.9 \\includegraphics{fig2}\n"
                "\n"
                "I could not locate the file with any of these extensions:\n"
            ),
            "missing_graphic",
            "fig2",
        ),
        # 带扩展名 File-not-found + errhelp: 前列 missing_file 臂
        # (\.[a-zA-Z0-9]+) 评估序先签 —— 既有 eps-strip 路由不扰。
        (
            (
                "! LaTeX Error: File `plot.eps' not found.\n"
                "\n"
                "See the LaTeX manual or LaTeX Companion for explanation.\n"
                "Type  H <return>  for immediate help.\n"
                " ...\n"
                "\n"
                "l.7 \\includegraphics{plot}\n"
                "\n"
                "I could not locate the file with any of these extensions:\n"
                ".ps,.eps\n"
            ),
            "missing_file",
            "plot.eps",
        ),
        ("! Something utterly bizarre", "other", None),
    ],
)
def test_head_categories(log: str, cat: str, pay: str | None) -> None:
    assert classify(log) == (cat, pay)


def test_undefined_color_backtick_reaches_fallback_rule(tmp_path: Path) -> None:
    r"""端到端路由钉: ``Undefined color `X'`` → undefined_color|X 后,

    ``undefined_color_fallback`` (75-syntax:166) 的 when
    (category+payload_required) 通过 —— 扩收前该标记落 other 无 payload,
    规则不可达 (firezero ~44 cells)。"""
    log = "! Package xcolor Error: Undefined color `MAROON'."
    cat, pay = classify(log)
    assert (cat, pay) == ("undefined_color", "MAROON")
    r = rule("undefined_color_fallback")
    ctx = mk_ctx(tmp_path, err_head=log)
    assert _when_ok(r.when, cat, pay, ctx)


def test_undefined_color_kernel_issuer_reaches_fallback_rule(
    tmp_path: Path,
) -> None:
    r"""内核发行方同钉: ``LaTeX Error: Undefined color `X'`` 同样可达。"""
    log = "! LaTeX Error: Undefined color `mygray'."
    cat, pay = classify(log)
    assert (cat, pay) == ("undefined_color", "mygray")
    r = rule("undefined_color_fallback")
    ctx = mk_ctx(tmp_path, err_head=log)
    assert _when_ok(r.when, cat, pay, ctx)


def test_undefined_color_fallback_emits_braced_name(tmp_path: Path) -> None:
    r"""0905.2120 实证回归钉: repl 须出 ``\definecolor{X}{rgb}`` 花括号形。

    ``{payload}`` 占位含花括号, ``_substitute`` 连括号吞——旧 repl
    ``\definecolor{payload}`` 实产 ``\definecolormygray`` 粘连非法 cs;
    现 ``{{payload}}`` 双花括号外留一层。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx\n\\end{document}\n"
    )
    r = rule("undefined_color_fallback")
    ctx = mk_ctx(tmp_path)
    ok, note = actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        r, ctx, None, "mygray", ErrReport()
    )
    assert ok, note
    t = (tmp_path / "main.tex").read_text()
    assert "\\definecolor{mygray}{rgb}{0,0,0}" in t
    assert "\\definecolormygray" not in t


def test_already_def_backtick_reaches_undefine_rule(tmp_path: Path) -> None:
    r"""端到端路由钉: ``Command `\Bbbk'`` → already_def|Bbbk 后,

    ``already_def_undefine`` (75-syntax:113) 的 when
    (category+payload_required) 与 condition (ctx_suggests "Command")
    双闸通过 —— 扩收前该标记落 other 无 payload, already_def_* 三家
    全够不到 (failmine2 23 cells)。"""
    log = "! LaTeX Error: Command `\\Bbbk' already defined."
    cat, pay = classify(log)
    assert (cat, pay) == ("already_def", "Bbbk")
    assert when_cond_ok(
        "already_def_undefine",
        cat,
        pay,
        "amssymb.sty:261: LaTeX Error: Command `\\Bbbk' already defined.",
        tmp_path,
    )


def test_already_def_backtick_reaches_renew_rule(tmp_path: Path) -> None:
    """姊妹闸：``already_def_newcmd_renew`` (75-syntax:111) 同样可接。"""
    log = "! LaTeX Error: Command `\\Bbbk' already defined."
    cat, pay = classify(log)
    r = rule("already_def_newcmd_renew")
    ctx = mk_ctx(tmp_path, err_head=log)
    assert _when_ok(r.when, cat, pay, ctx)


def test_undefined_cs_subclassifies_pdftex_prim() -> None:
    cat, pay = classify("! Undefined control sequence.\nl.5 \\pdfoutput=1")
    assert (cat, pay) == ("pdftex_prim", "pdfoutput")


def test_undefined_cs_blank_lineno_variant() -> None:
    """1909.05039 实证：l.N 行空白时取展开上下文尾行的末位 cs。"""
    log = (
        "! Undefined control sequence.\n"
        "\\__hook shipout/firstpage ...geHook \\headerps@out \n"
        "                                                  {/burl@stx null def /BU.S ...\n"
        "l.196 \n"
    )
    cat, pay = classify(log)
    assert (cat, pay) == ("undefined_cs", "headerps@out")


def test_undefined_cs_blank_lineno_pdftex_subclass() -> None:
    """空 l.N 变体同样走 pdftex_prim 细分。"""
    log = "! Undefined control sequence.\n\\foo \\pdfoutput \nl.9 \n"
    cat, pay = classify(log)
    assert (cat, pay) == ("pdftex_prim", "pdfoutput")


def test_undefined_cs_no_subclassify_when_absent() -> None:
    cat, _pay = classify("! Undefined control sequence.\nl.5 \\mycs")
    assert cat == "undefined_cs"


def test_first_error_wins_order() -> None:
    # 两个 '!' 行：只有首个进 head —— 第二个错误不影响分类
    cat, _ = classify("! Illegal unit of measure.\n! Package soul Error: x\n")
    assert cat == "illegal_unit"


# ---------------------------------------------------------------- taxonomy: tail scope
def test_tail_missing_file_with_guard() -> None:
    cat, pay = classify("lots of text\nFile `epsf.sty' not found.\nEnter file name:\n")
    assert (cat, pay) == ("missing_file", "epsf.sty")


def test_tail_enter_file_name_alone() -> None:
    cat, pay = classify("blah\nEnter file name: \n")
    assert (cat, pay) == ("missing_file", None)


def test_tail_latex209() -> None:
    cat, _ = classify("...\nThis is a \\documentstyle era document\n")
    assert cat == "latex209"


def test_head_beats_tail() -> None:
    # preempts 时代 (regress4): tail missing_file 条目带
    # preempts=[…,emergency] —— emergency 头错被尾部真缺文件夺路由;
    # 未列名的强类别 (illegal_unit) 仍由 head 胜出。
    preempted = (
        "! Emergency stop.\n"
        + "pad line\n" * 12
        + "File `x.sty' not found.\nEnter file name:"
    )
    assert classify(preempted)[0] == "missing_file"
    held = (
        "! Illegal unit of measure (pt inserted).\n"
        + "pad line\n" * 12
        + "File `x.sty' not found.\nEnter file name:"
    )
    assert classify(held)[0] == "illegal_unit"


def test_tail_fatal_preempts_weak_head() -> None:
    """regress4-2410.00012: tail 致命收尾抢占弱 head 类别。

    真杀手在 log 尾 (File-not-found + Enter file name), 但首个 '!' 是
    上游包内 undefined_cs —— 带 ``preempts`` 的 tail 条目可夺路由。"""
    tax = Taxonomy(
        [
            {"id": "undefined_cs", "pattern": "Undefined control sequence"},
            {
                "id": "missing_file",
                "scope": "tail",
                "pattern": r"File `([^']+)' not found",
                "guard": "Enter file name",
                "preempts": ["undefined_cs", "pdftex_prim", "other", "emergency"],
            },
        ]
    )
    log = (
        "! Undefined control sequence.\nl.5 \\foo\n"
        + "pad line\n" * 15
        + "File `chemgreek.sty' not found.\n! Emergency stop.\nEnter file name:"
    )
    assert tax.classify(parse_text(log, _warn())) == ("missing_file", "chemgreek.sty")


def test_tail_fatal_no_preempt_unlisted_head() -> None:
    """preempts 未列名的 head 类别不被抢 (强错误仍先修)。"""
    tax = Taxonomy(
        [
            {"id": "illegal_unit", "pattern": "Illegal unit of measure"},
            {
                "id": "missing_file",
                "scope": "tail",
                "pattern": r"File `([^']+)' not found",
                "guard": "Enter file name",
                "preempts": ["undefined_cs", "other"],
            },
        ]
    )
    log = (
        "! Illegal unit of measure (pt inserted).\n"
        + "pad\n" * 15
        + "File `x.sty' not found.\nEnter file name:"
    )
    cat, _ = tax.classify(parse_text(log, _warn()))
    assert cat == "illegal_unit"


# ---------------------------------------------------------------- taxonomy: warnings/timeout/clean
def test_warn_utf8_when_no_bang() -> None:
    cat, _ = classify("Missing character: There is no (U+FFFD) in font cmr10\n")
    assert cat == "warn_utf8"


def test_warn_utf8_not_reached_when_bang() -> None:
    # 有 '!' 行 → head 命中优先，warning 不升级
    cat, _ = classify(
        "! Package soul Error: x\nMissing character: There is no (U+FFFD) in font\n"
    )
    assert cat == "soul_err"


# ---------------------------------------------------------------- warnings 归因
def test_warn_utf8_sys_file_not_project() -> None:
    """sys 件 invalid_utf8 (texmf 绝对路径栈顶) → ``warnings_sys`` 观察项，

    不进 ``rep.warnings`` → ``warn_utf8`` 伪类别不点火 (stagerun-loop3
    1907.00067 实证：``_texmf`` 树 misccorr.sty 坏字节曾使 final_cat
    =warn_utf8 每轮再生，judge 侧早已归 sys_warn note)。"""
    log = (
        "(./main.tex\n"
        "(/usr/share/texmf-dist/tex/latex/t2/misccorr.sty\n"
        "Invalid UTF-8 byte or sequence at line 29 replaced by U+FFFD.\n"
        ")\n"
        "Output written on main.pdf (1 page).\n"
    )
    rep = parse_text(log, _warn())
    assert rep.warnings == []
    assert rep.warnings_sys == ["invalid_utf8@misccorr.sty"]
    assert classify(log) == ("clean", None)


def test_warn_utf8_usertree_under_project_root(tmp_path: Path) -> None:
    """root 内 ``_texmf`` usertree 件仍是系统语义 (fixloop 自装包落此树)。"""
    log = (
        "(./main.tex\n"
        f"({tmp_path}/_texmf/home/tex/latex/t2/faktor.sty\n"
        "Invalid UTF-8 byte or sequence at line 61 replaced by U+FFFD.\n"
    )
    rep = parse_text(log, _warn(), project_root=tmp_path)
    assert rep.warnings == []
    assert rep.warnings_sys == ["invalid_utf8@faktor.sty"]


def test_warn_utf8_project_file_still_fires() -> None:
    """工程文件帧顶的 invalid_utf8 照驱 ``warn_utf8`` (归因不吞真红线)。"""
    log = (
        "(./main.tex\n"
        "(./sub/bad.tex\n"
        "Invalid UTF-8 byte or sequence at line 9 replaced by U+FFFD.\n"
    )
    rep = parse_text(log, _warn())
    assert rep.warnings == ["invalid_utf8"]
    assert rep.warnings_sys == []
    assert classify(log) == ("warn_utf8", None)


def test_warn_utf8_mixed_sys_and_project() -> None:
    """sys + 工程混合命中：sys 件降 ``warnings_sys``, 工程命中照驱 warn_utf8。"""
    log = (
        "(/usr/share/texmf-dist/tex/latex/t2/misccorr.sty\n"
        "Invalid UTF-8 byte or sequence at line 29 replaced by U+FFFD.\n"
        ")\n"
        "(./main.tex\n"
        "Invalid UTF-8 byte or sequence at line 5 replaced by U+FFFD.\n"
    )
    rep = parse_text(log, _warn())
    assert rep.warnings == ["invalid_utf8"]
    assert rep.warnings_sys == ["invalid_utf8@misccorr.sty"]
    assert classify(log) == ("warn_utf8", None)


def test_warn_utf8_dos_eps_tagged(tmp_path: Path) -> None:
    """DOS 魔数 EPS 源降 sys 并打 ``(dos-eps)`` 尾标 (loginfo 同口径)。"""
    (tmp_path / "fig.eps").write_bytes(b"\xc5\xd0\xd3\xc6%!PS-Adobe-3.0 EPSF")
    log = (
        "(./main.tex\n"
        "(fig.eps\n"
        "Invalid UTF-8 byte or sequence at line 1 replaced by U+FFFD.\n"
    )
    rep = parse_text(log, _warn(), project_root=tmp_path)
    assert rep.warnings == []
    assert rep.warnings_sys == ["invalid_utf8@fig.eps(dos-eps)"]


def test_warn_utf8_unattributable_keeps_redline(tmp_path: Path) -> None:
    """空栈/不可归因命中保守归工程——不可归因不掉红线 (loginfo 同口径)。"""
    log = "Invalid UTF-8 byte or sequence at line 3 replaced by U+FFFD.\n"
    rep = parse_text(log, _warn(), project_root=tmp_path)
    assert rep.warnings == ["invalid_utf8"]
    assert rep.warnings_sys == []


def test_missing_char_not_attributed() -> None:
    """``missing_char`` 输出侧警告不归因——sys 帧顶命中仍进 ``warnings``。

    栈顶是排版执行位而非字源，缺字照样落 PDF——刻意不套
    ``_FILE_ATTRIBUTED_WARNS`` 过滤。"""
    log = (
        "(/usr/share/texmf-dist/tex/latex/t2/misccorr.sty\n"
        "Missing character: There is no 中 in font cmr10\n"
    )
    rep = parse_text(log, _warn())
    assert rep.warnings == ["missing_char"]
    assert rep.warnings_sys == []


def test_timeout_overrides() -> None:
    cat, _ = classify("! Emergency stop.\n", timed_out=True)
    assert cat == "timeout"


def test_clean_log() -> None:
    cat, pay = classify(
        "This is pdfTeX, Version 3\nOutput written on main.pdf (1 page).\n"
    )
    assert (cat, pay) == ("clean", None)


def test_undefined_cs_expansion_stack_root() -> None:
    """2410.00012 实证：宏内炸 —— 冒犯 cs 在展开栈区域末位 (\\pdfobj),

    l.N 行末只剩表面宏 (\\SpotSpace)。subclassify 须认栈末位。"""
    log = (
        "splice/ieeeaccess.cls:128: Undefined control sequence.\n"
        "\\AddSpotColor #1#2#3#4->\\def \\obj { 0 R}\\pdfobj \n"
        "                                {<</C0[0 0 0 0]/FunctionType...\n"
        "l.128 ...SpotSpace 3015\\SpotSpace C} {1 0.3 0 0.2}\n"
    )
    assert classify(log) == ("pdftex_prim", "pdfobj")


def test_undefined_cs_stack_tail_not_pdf_stays() -> None:
    """顶行末位非 pdf 原语 → 不细分 (allowed 不凭空放行)。

    payload-scout-2026-09-17: payload 取上下文顶行末位 cs（真肇事者
    ``\\somecs``），``l.9`` 行末 ``\\myouter`` 只是调用点。
    """
    log = "! Undefined control sequence.\n\\mymacro ->\\somecs \nl.9 \\myouter{x}\n"
    assert classify(log) == ("undefined_cs", "somecs")


# ---------------------------------------------------------------- ctx head 位
def test_ctx_tail_css_argument_head() -> None:
    """1801.06287 实证：``<argument>`` 头行末位 cs 是冒犯候选。

    头行续行 (该层剩余输入 ``>0 \\edef \\Gin@extensions``) 携带的 cs 曾把
    区域末位带偏到 post-offending 噪声——头位显式抽取取回
    ``\\pdfshellescape`` (join 候选集，区域/l.N 两位语义不动)。
    """
    ctx = (
        "! Undefined control sequence.\n"
        "<argument> \\ifnum \\pdfshellescape \n"
        "                                  >0 \\edef \\Gin@extensions {\\Gin@extensions ...\n"
        "l.12 \\begin{document}\n"
    )
    css = _ctx_tail_css(ctx)
    assert "pdfshellescape" in css  # head 位 (真冒犯)
    assert "Gin@extensions" in css  # 区域末位照旧
    assert "begin" in css  # l.N 行末照旧


def test_ctx_tail_css_recently_read_head() -> None:
    """1412.6980 实证：``<recently read>`` 头行 cs 入候选集。"""
    ctx = (
        "! Undefined control sequence.\n"
        "<recently read> \\pdfoutput \n"
        "                            =1\n"
        "l.2 \\pdfoutput\n"
    )
    assert "pdfoutput" in _ctx_tail_css(ctx)


def test_ctx_tail_css_head_after_lineno_ignored() -> None:
    """``l.N`` 后的 ``<argument>`` 属下一错误 ctx (8 行窗溢出), 不抽取。"""
    ctx = (
        "! Undefined control sequence.\n"
        "l.5 \\foo\n"
        "! Missing number, treated as zero.\n"
        "<argument> \\othercs \n"
    )
    assert _ctx_tail_css(ctx) == {"foo"}


def test_ctx_tail_css_argument_elided_or() -> None:
    """1811.03624 实证：``...`` 省略前缀下末位 cs 才是冒犯 token (``\\or``),

    非紧跟字面量的 ``\\ifcase``。"""
    ctx = (
        "! Extra \\or.\n"
        "<argument> ...pach \\ifcase \\@chclass \\@classz \\or \n"
        "                                                   \\@classi \\or \\@classii \\or...\n"
        "l.283 ...2.2cm}|C{2.2cm}C{2.2cm}|C{2.2cm}C{2.2cm}}\n"
    )
    css = _ctx_tail_css(ctx)
    assert "or" in css
    assert "ifcase" not in css


def test_ctx_tail_css_head_cs_trailing_nonletter() -> None:
    """astro-ph/0501080 实证：头行末位字母 cs 后跟非字母 cs (``\\ ``/``\\^^M``)

    → 主 pattern 行 1 抓取锚失败 (pay=None), 头位仍取回 ``\\copyright``。"""
    ctx = (
        "! Use of \\affilmark doesn't match its definition.\n"
        "<argument> ...ce {-1.3cm}\\copyright \\, 2005 \\ \\^^M\n"
        "                                                   S.S.Tsygankov\\affilmark {1...\n"
        "l.193 ...k{1}$^{\\,*}$, A.A.Lutovinov\\affilmark{1}}\n"
    )
    css = _ctx_tail_css(ctx)
    assert "copyright" in css
    assert "affilmark" in css


def test_undefined_cs_argument_head_still_pdftex() -> None:
    """classify 级钉：``<argument>`` 头行形态路由保持 pdftex_prim。"""
    log = (
        "! Undefined control sequence.\n"
        "<argument> \\ifnum \\pdfshellescape \n"
        "                                  >0 \\edef \\Gin@extensions {\\Gin@extensions ...\n"
        "l.12 \\begin{document}\n"
    )
    assert classify(log) == ("pdftex_prim", "pdfshellescape")
