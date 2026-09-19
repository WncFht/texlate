r"""texlog 单遍事件流 + C3 归位 shim 钉点。

- ``iter_log_events``：``stack``/``popped``/``inner``/``err`` 投影 ==
  逐行手工重放 oracle（``update_file_stack``+``patch_graphic_top``）。
- ``match_error_line``：三消费面同词素表（``^!``/``file:line:`` 双格式、
  Warning/``==>`` 复述排除、捕获面）。
- 栈口径守恒：l2/loginfo 含行快照 vs logparse ``file_stack_at`` 排他
  口径——有意分歧逐面钉死。
- ``fixloop.logparse``/``fixloop._yamlish`` 旧路径 shim 名面守恒
  （新老家同物同名）。
"""

from __future__ import annotations

import texlate.compile._yamlish as cym
import texlate.compile.logparse as clp
from texlate.compile.fixloop import _yamlish as fym
from texlate.compile.fixloop import logparse as flp
from texlate.compile.loginfo import parse_log as eng_parse_log
from texlate.texlog import (
    iter_log_events,
    match_error_line,
    patch_graphic_top,
    update_file_stack,
)
from texlate.textutil import AUX_CITEKEY_RE, BIBITEM_KEY_RE, CITE_FAMILY_RE
from texlate.validate.l2 import _match_error_line, parse_log_text


def _oracle(lines: list[str]) -> list[tuple]:
    """逐行手工重放——事件流投影的对照 oracle。"""
    stack: list[str | None] = []
    out = []
    for ln in lines:
        popped: list[str | None] = []
        update_file_stack(ln, stack, popped)
        patch_graphic_top(ln, stack)
        out.append(
            (
                tuple(stack),
                tuple(popped),
                next((s for s in reversed(stack) if s), None),
            )
        )
    return out


# ---------------------------------------------------------------- 事件流投影


def test_iter_events_eq_replay_oracle() -> None:
    lines = [
        "(./main.tex",
        "(./sub/a.tex",
        "Missing character: There is no ) in font nullfont!",
        "y ) (./fig,1.eps",
        "plain tail (nonfile",
        ")",
    ]
    oracle = _oracle(lines)
    for ev, (stack, popped, inner) in zip(iter_log_events(lines), oracle, strict=True):
        assert ev.stack == stack
        assert ev.popped == popped
        assert ev.inner == inner


def test_iter_events_err_field_eq_match_error_line() -> None:
    lines = ["(./a.tex", "! boom", "x.tex:5: LaTeX Warning: w", "./b.tex:7: bad"]
    errs = [ev.err for ev in iter_log_events(lines)]
    assert errs == [match_error_line(ln) for ln in lines]


def test_iter_events_popped_and_inner_on_pop_line() -> None:
    """``)`` 行内弹出进 ``popped``，``inner`` 取弹出后栈顶具名帧。"""
    lines = ["(./main.tex", "(./bad.tex", ")File ended tail", "! e"]
    evs = list(iter_log_events(lines))
    assert evs[2].popped == ("./bad.tex",)
    assert evs[2].inner == "./main.tex"
    assert evs[3].inner == "./main.tex"


def test_match_error_line_table() -> None:
    """双格式命中 + 非错误双腿排除 + 捕获面（与三消费面同词素）。"""
    hit = match_error_line("! Undefined control sequence.")
    assert hit is not None
    assert hit.head == "! Undefined control sequence."
    assert hit.tex_file is None
    assert hit.tex_line is None

    hit = match_error_line("./sub/a.tex:44: Undefined control sequence.")
    assert hit is not None
    assert (hit.tex_file, hit.tex_line) == ("./sub/a.tex", 44)

    # file:line: Warning 行同格式但非错误——n_errors==0 干净门不被击穿
    assert match_error_line("./f.tex:5: LaTeX Warning: w") is None
    assert match_error_line("./f.tex:5: Package foo Warning: w") is None
    # ``==> Fatal error occurred`` 汇总尾行——同一失败的复述
    assert match_error_line("./f.tex:5: ==> Fatal error occurred") is None
    # 普通行/缺空格 file:line: 畸形形
    assert match_error_line("plain line") is None
    assert match_error_line("./f.tex:5:missing space") is None
    assert match_error_line("Makefile:5: not a tex file") is None


# ---------------------------------------------------------------- 消费面口径钉点

_LATE_OPEN_LOG = "(./main.tex\n! err (./late.tex\n"


def test_stack_snapshot_semantics_pinned() -> None:
    """错误行自携 ``(`` 开帧：含行快照（l2/loginfo）vs 排他栈（logparse）。"""
    v = parse_log_text(_LATE_OPEN_LOG)
    assert v.first_error is not None
    assert v.first_error.file_stack == ("./main.tex", "./late.tex")

    info = eng_parse_log(_LATE_OPEN_LOG)
    assert info.file_stack == ["./main.tex", "./late.tex"]

    rep = clp.parse_text(_LATE_OPEN_LOG)
    assert rep.file_stack == ["./main.tex"]


def test_logparse_popped_files_runaway() -> None:
    """runaway 排他口径：首错行前 ``)`` 弹出的真肇事件进 popped_files（#78）。"""
    log = "(./main.tex\n(./bad.tex\n) pop\n! File ended while scanning use of \\x.\n"
    rep = clp.parse_text(log)
    assert rep.file_stack == ["./main.tex"]
    assert rep.popped_files == ["./bad.tex"]

    v = parse_log_text(log)
    assert v.first_error is not None
    assert v.first_error.eof_file == "./bad.tex"


def test_l2_match_error_line_delegate() -> None:
    """bench ``extract_l2_fixture`` 钉点签名守恒——``(head, tex_file)``。"""
    assert _match_error_line("! e") == ("! e", None)
    assert _match_error_line("./a.tex:9: m") == ("./a.tex:9: m", "./a.tex")
    assert _match_error_line("x.tex:1: LaTeX Warning: w") is None


def test_parse_text_attr_warns_projection() -> None:
    """归因警告投影并进主遍——工程源进 warnings、系统件降 warnings_sys。"""
    pats = [{"id": "invalid_utf8", "pattern": "Invalid UTF-8"}]
    log = (
        "(/usr/share/texmf-dist/tex/latex/old/pkg.sty\n"
        "Invalid UTF-8 byte sequence\n"
        ")\n"
        "(./main.tex\n"
        "! Undefined control sequence.\n"
    )
    rep = clp.parse_text(log, pats, project_root=None)
    assert rep.warnings == []  # texmf 系统件源不驱 warn_*
    assert rep.warnings_sys == ["invalid_utf8@pkg.sty"]


# ---------------------------------------------------------------- C3 归位 shim 面


def test_logparse_shim_surface() -> None:
    """旧路径名面转口守恒——新旧模块同物同名（含私名）。"""
    names = [
        "ErrReport",
        "Taxonomy",
        "parse_log",
        "parse_text",
        "_is_runaway_output",
        "_is_err_line",
        "_ctx_tail_css",
        "_collect_warnings",
        "_payload",
        "_cap_bracket_tag",
        "_capacity_pending",
        "_capacity_payload",
        "_cap_verdict_cat",
        "_AttrWarns",
        "_RUNAWAY_VBOX_RX",
        "_RUNAWAY_VBOX_MIN",
        "_RUNAWAY_VBOX_DENSITY",
        "_RUNAWAY_PAGE_RX",
        "_RUNAWAY_PAGE_MAX",
        "_LINE_NO_RE",
        "_LN_ROW_RE",
        "_CS_NAME_RE",
        "_CTX_HEAD_RE",
        "_CAP_BRACKET_RX",
        "_CAP_BRACKET_TAG",
        "_CAP_CS_RX",
        "_CAP_MACRO_RX",
        "_CAP_HEAD_RX",
        "_CAP_LN_ROW_RX",
        "_CAP_UPSTREAM_RECURSION_CS",
        "_PAYLOAD_SCANS",
        "_ERRS_MAX",
        "_PRE_LINES",
        "_FILE_ATTRIBUTED_WARNS",
    ]
    for name in names:
        assert getattr(flp, name) is getattr(clp, name), name
    assert flp.__all__ == clp.__all__


def test_yamlish_shim_surface() -> None:
    """``fixloop._yamlish`` 名面转口守恒——``ruleset`` 等旧 import 不动。"""
    for name in ["YamlishError", "loads", "load_yaml", "_merge_into", "_merge_maps"]:
        assert getattr(fym, name) is getattr(cym, name), name


# ---------------------------------------------------------------- textutil cite 叶


def test_cite_leaf_regexes() -> None:
    """键表抽取正则行为面——facade 导出直测（旧 ``_builtins_bib`` 私有表同形）。"""
    m = CITE_FAMILY_RE.search(r"see \citet[§2]{foo&a,b_2} and \cite{c3}")
    assert m is not None
    assert m.group(1) == "foo&a,b_2"
    m = BIBITEM_KEY_RE.search(r"\bibitem[label]{key_1}")
    assert m is not None
    assert m.group(1) == "key_1"
    assert AUX_CITEKEY_RE.search(r"\bibcite{k1}{1}").group(1) == "k1"  # type: ignore[union-attr]
    assert AUX_CITEKEY_RE.search(r"\citation{a,b}").group(1) == "a,b"  # type: ignore[union-attr]
