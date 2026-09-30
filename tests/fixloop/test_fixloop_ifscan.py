r"""条件栈字面扫描器 (textutil.ifscan) + 跳读 phantom 判例单测。

实证背景 (loop4 批一 152 格): TeX 条件跳读扫描按 token 计 ``\if`` 族
——被跳分支里 ``\let`` 不执行, ``\let\Xok\iftrue`` 第二 operand 仍是裸
``\if`` token → 假开臂吞 ``\fi`` → ``Incomplete \ifdefined``。字面
(执行态) 扫描对 operand/名位/def 参位恒按"非开"计, 与跳读态分歧:
凡 ``\if``/``\fi`` token 落非执行位且外层有活条件帧 → phantom 判词。

姊妹盲区同波修: ``\let a=\iftrue`` 字符名形漏吃 operand (误计活开);
``\let<cs><if族>`` if-alias (``\TeXlateCMUok`` 名不带 if 前缀, 裸用
即开臂 —— 事故门正是此形); ``\ifx``/``\ifnum``/``\ifdefined`` 的
operand 位旧版误计开 (``\ifdefined\iffoo`` 假亏格)。
"""

from pathlib import Path

from texlate.compile.fixloop import Ruleset, actions, load_ruleset
from texlate.compile.fixloop.builtins import if_phantom_protect
from texlate.compile.fixloop.engine import LoopCtx, Rule
from texlate.compile.logparse import ErrReport
from texlate.textutil import scan_ifs

_RULE_ID = "unclosed_if_close"

# loop4 批一 事故门核心形: 分支内 \let + 分支外裸用 alias。
_POISON_GATE = (
    "\\documentclass{article}\n"
    "\\ifdefined\\XeTeXversion\n"
    "\\ifdefined\\IfFontExistsTF\n"
    "\\IfFontExistsTF{cmunrm.otf}{\\let\\TeXlateCMUok\\iftrue}"
    "{\\let\\TeXlateCMUok\\iffalse}%\n"
    "\\else\n"
    "\\let\\TeXlateCMUok\\iffalse\n"
    "\\fi\n"
    "\\TeXlateCMUok\n"
    "font wiring\n"
    "\\fi\n"
    "\\fi\n"
    "\\begin{document}x\\end{document}\n"
)


def _rs() -> Ruleset:
    return load_ruleset()


def _rule(rid: str = _RULE_ID) -> Rule:
    return next(r for r in _rs().rules if r.id == rid)


def _apply(rule: Rule, wdir: Path) -> tuple[bool, str]:
    ctx = LoopCtx(wdir=wdir, engine_name="xelatex")
    return actions._apply(rule, ctx, None, None, ErrReport())  # noqa: SLF001


# ---------------------------------------------------------------- 字面平衡
def test_balanced_cond_clean() -> None:
    r"""\ifnum..\else..\fi 平衡 → 无亏格无 phantom。"""
    r = scan_ifs("\\ifnum1=1 yes\\else no\\fi\n\\begin{document}x\\end{document}\n")
    assert r.unclosed_live == []
    assert r.live_opens == 1
    assert r.live_closes == 1
    assert r.phantoms == []


def test_real_deficit_still_reported() -> None:
    r"""真未闭合 \ifx → unclosed_live 计 1, 无 phantom。"""
    r = scan_ifs("\\ifx\\a\\b\ntext\n\\begin{document}x\\end{document}\n")
    assert len(r.unclosed_live) == 1
    assert r.unclosed_live[0][0] == "ifx"
    assert r.phantoms == []


# ---------------------------------------------------------------- \let operand
def test_let_cs_operand_consumed() -> None:
    r"""\let\X\iftrue 顶层 → operand 被吃, 非开非 phantom (无活帧)。"""
    r = scan_ifs("\\let\\X\\iftrue\n\\begin{document}x\\end{document}\n")
    assert r.unclosed_live == []
    assert r.live_opens == 0
    assert r.phantoms == []


def test_let_charname_operand_consumed() -> None:
    r"""\let a=\iftrue 字符名形 → operand 被吃 (旧版漏吃误计活开)。"""
    r = scan_ifs("\\let a=\\iftrue\n\\begin{document}x\\end{document}\n")
    assert r.unclosed_live == []
    assert r.live_opens == 0


def test_let_bracename_operand_consumed() -> None:
    r"""\let{\iftrue} {名 → 组内首 cs operand 被吃。"""
    r = scan_ifs("\\let{\\iftrue}\n\\begin{document}x\\end{document}\n")
    assert r.unclosed_live == []
    assert r.live_opens == 0


def test_let_comma_operand_fi_live() -> None:
    r"""\let\sep=,\fi → operand 是字符 ',', \fi 是 live close (elsarticle 形)。"""
    r = scan_ifs(
        "\\ifdefined\\foo\n\\let\\sep=,\\fi\n\\begin{document}x\\end{document}\n"
    )
    assert r.live_closes == 1
    assert r.unclosed_live == []


def test_let_operand_phantom_in_cond() -> None:
    r"""活条件内 \let\flag\iftrue → operand 记 phantom open (跳读按 token 计)。"""
    r = scan_ifs(
        "\\ifdefined\\foo\n\\let\\flag\\iftrue\n\\fi\n"
        "\\begin{document}x\\end{document}\n"
    )
    assert r.unclosed_live == []
    assert ("iftrue", 2, "open") in r.phantoms


def test_let_fi_operand_phantom_close() -> None:
    r"""活条件内 \let\X\fi → operand 记 phantom close。"""
    r = scan_ifs(
        "\\ifdefined\\foo\n\\let\\X\\fi\n\\fi\n\\begin{document}x\\end{document}\n"
    )
    assert ("fi", 2, "close") in r.phantoms


# ---------------------------------------------------------------- 其他非执行位
def test_newif_name_phantom_in_cond() -> None:
    r"""活条件内 \newif\ifbar → 名位 \ifbar 记 phantom open。"""
    r = scan_ifs(
        "\\ifdefined\\foo\n\\newif\\ifbar\n\\fi\n\\begin{document}x\\end{document}\n"
    )
    assert ("ifbar", 2, "open") in r.phantoms


def test_newcommand_skipgrp_phantom_in_cond() -> None:
    r"""活条件内 \newcommand{\ifbar} → skip 组内 \ifbar 记 phantom open。"""
    r = scan_ifs(
        "\\ifdefined\\foo\n\\newcommand{\\ifbar}{x}\n\\fi\n"
        "\\begin{document}x\\end{document}\n"
    )
    assert ("ifbar", 2, "open") in r.phantoms


def test_def_body_open_defopen_in_cond() -> None:
    r"""活条件内 \def\bar{\ifbaz} → def 区 open 记 def-open (已计入 opens 仅上报)。"""
    r = scan_ifs(
        "\\ifdefined\\foo\n\\def\\bar{\\ifbaz}\n\\fi\n"
        "\\begin{document}x\\end{document}\n"
    )
    assert r.unclosed_live == []
    assert r.def_unclosed == 1
    assert ("ifbaz", 2, "def-open") in r.phantoms


def test_def_body_top_no_phantom() -> None:
    r"""顶层 \def\bar{\ifbaz} → 冻结 token, 无 phantom (无活帧)。"""
    r = scan_ifs("\\def\\bar{\\ifbaz}\n\\begin{document}x\\end{document}\n")
    assert r.def_unclosed == 1
    assert r.phantoms == []


def test_newif_top_no_phantom() -> None:
    r"""顶层 \newif\ifbar → 名位被吃, 无 phantom (无活帧)。"""
    r = scan_ifs("\\newif\\ifbar\n\\begin{document}x\\end{document}\n")
    assert r.live_opens == 0
    assert r.phantoms == []


# ---------------------------------------------------------------- if-alias
def test_alias_bare_use_is_open() -> None:
    r"""\let\flag\iftrue 顶层 + \flag..\fi → alias 计开, 平衡 (旧版漏开)。"""
    r = scan_ifs(
        "\\let\\flag\\iftrue\n\\flag\ntext\n\\fi\n\\begin{document}x\\end{document}\n"
    )
    assert r.unclosed_live == []
    assert r.live_opens == 1
    assert r.live_closes == 1


def test_alias_operand_phantom() -> None:
    r"""alias 作 \let operand 在活条件内 → phantom open (按前 \let 态判)。"""
    r = scan_ifs(
        "\\let\\flag\\iftrue\n"
        "\\ifdefined\\foo\n\\let\\X\\flag\n\\fi\n"
        "\\begin{document}x\\end{document}\n"
    )
    assert ("flag", 3, "open") in r.phantoms


def test_alias_redef_dealiases() -> None:
    r"""\let\flag\relax 重定义 → 销 alias, 后续 \flag 非开非 phantom。"""
    r = scan_ifs(
        "\\let\\flag\\iftrue\n\\let\\flag\\relax\n"
        "\\ifdefined\\foo\n\\flag\n\\fi\n"
        "\\begin{document}x\\end{document}\n"
    )
    assert r.unclosed_live == []
    assert r.phantoms == []


def test_def_redef_dealiases() -> None:
    r"""\def\flag{..} 重定义 → 销 alias。"""
    r = scan_ifs(
        "\\let\\flag\\iftrue\n\\def\\flag{x}\n"
        "\\ifdefined\\foo\n\\flag\n\\fi\n"
        "\\begin{document}x\\end{document}\n"
    )
    assert r.phantoms == []
    assert r.unclosed_live == []


# ---------------------------------------------------------------- cond operand 预算
def test_ifnum_operand_not_open() -> None:
    r"""\ifnum\count@<32 → \count@ 是 operand 位, 非开。"""
    r = scan_ifs("\\ifnum\\count@<32 ok\\fi\n\\begin{document}x\\end{document}\n")
    assert r.unclosed_live == []
    assert r.live_closes == 1


def test_ifdefined_ifcs_operand_not_open() -> None:
    r"""\ifdefined\iffoo → \iffoo 是 operand 位, 非开 (旧版误计开假亏格)。"""
    r = scan_ifs("\\ifdefined\\iffoo yes\\fi\n\\begin{document}x\\end{document}\n")
    assert r.unclosed_live == []
    assert r.live_opens == 1
    assert r.live_closes == 1


def test_ifx_if_operands_not_open() -> None:
    r"""\ifx\iffoo\ifbar → 两 operand 非开; 活条件内则 phantom open。"""
    r = scan_ifs("\\ifx\\iffoo\\ifbar yes\\fi\n\\begin{document}x\\end{document}\n")
    assert r.unclosed_live == []
    r2 = scan_ifs(
        "\\ifdefined\\outer\n\\ifx\\iffoo\\ifbar yes\\fi\n\\fi\n"
        "\\begin{document}x\\end{document}\n"
    )
    assert ("iffoo", 2, "open") in r2.phantoms
    assert ("ifbar", 2, "open") in r2.phantoms


def test_ifnum_alias_operand_phantom() -> None:
    r"""\ifnum\ok=1 且 \ok 是 if-alias → operand 位记 phantom 非计开。"""
    r = scan_ifs(
        "\\ifdefined\\foo\n\\let\\ok\\iftrue\n\\fi\n"
        "\\ifnum\\ok=1 yes\\fi\n"
        "\\begin{document}x\\end{document}\n"
    )
    assert r.unclosed_live == []
    assert ("ok", 4, "open") in r.phantoms


# ---------------------------------------------------------------- 事故形
def test_poison_gate_shape() -> None:
    r"""分支内 \let + 分支外 \TeXlateCMUok 裸开 → 字面平衡 + phantom 判出。"""
    r = scan_ifs(_POISON_GATE)
    assert r.unclosed_live == []
    assert r.live_opens == r.live_closes == 3  # noqa: PLR2004 - schema 断言值
    names = {n for n, _, _ in r.phantoms}
    assert {"iftrue", "iffalse"} <= names
    assert "TeXlateCMUok" in names  # 第二 \let 名位按"已记 alias"态判


def test_mixed_real_deficit_and_phantom() -> None:
    r"""真亏格与 phantom 并存 → 两边各自照报。"""
    r = scan_ifs(
        "\\ifdefined\\foo\n\\let\\flag\\iftrue\n\\fi\n"
        "\\ifx\\a\\b\nunclosed\n\\begin{document}x\\end{document}\n"
    )
    assert len(r.unclosed_live) == 1
    assert ("iftrue", 2, "open") in r.phantoms


def test_masked_comment_not_counted() -> None:
    r"""注释内 \if/\let 被 mask_tex 剥除 → 不计不判。"""
    r = scan_ifs("% \\iffoo \\let\\x\\iftrue\n\\begin{document}x\\end{document}\n")
    assert r.live_opens == 0
    assert r.phantoms == []


# ---------------------------------------------------------------- e2e 规则臂
def test_rule_phantom_field_in_noop_verdict(tmp_path: Path) -> None:
    r"""事故形 wdir → run_tool noop 判词带 phantom=N>0 (判别臂凭据)。"""
    (tmp_path / "main.tex").write_text(_POISON_GATE, encoding="utf-8")
    ok, note = _apply(_rule(), tmp_path)
    assert ok, note
    assert "ifclose: noop" in note
    assert "phantom=" in note
    n = int(note.split("phantom=")[1].split()[0])
    assert n > 0
    assert "texlate-fixloop-injected" not in (tmp_path / "main.tex").read_text(
        encoding="utf-8"
    )


def test_rule_real_deficit_injects_despite_phantom(tmp_path: Path) -> None:
    r"""真亏格件 + phantom 嫌疑并存 → 仍注入 \fi (phantom 不挡修复面)。"""
    main = (
        "\\ifdefined\\foo\n\\let\\flag\\iftrue\n\\fi\n"
        "\\ifx\\a\\b\nunclosed\n\\begin{document}x\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    ok, note = _apply(_rule(), tmp_path)
    assert ok, note
    assert "injected" in note
    patched = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "texlate-fixloop-injected" in patched


# ---------------------------------------------------------------- ifprot 判别臂
def _ifprot_ctx(tmp_path: Path, ledger: list[dict]) -> LoopCtx:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{amsproc}\n\\title{T}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    return LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", actions=ledger
    )


def _ledger(detail: str) -> list[dict]:
    return [{"round": 1, "rule": "unclosed_if_close", "detail": detail}]


def test_ifprot_abstains_on_skip_phantom(tmp_path: Path) -> None:
    r"""判词 phantom=N>0 → 跳读形嫌疑在场, \protected 域不含 → abstain。"""
    ctx = _ifprot_ctx(
        tmp_path, _ledger("rc=0 ifclose: noop opens=3 closes=3 deficits=0 phantom=4")
    )
    ok, note = if_phantom_protect(ctx, None, None, {})
    assert not ok
    assert "phantom" in note


def test_ifprot_fires_on_zero_phantom(tmp_path: Path) -> None:
    r"""判词 phantom=0 → 无跳读嫌疑, edef 域照旧放行。"""
    ctx = _ifprot_ctx(
        tmp_path, _ledger("rc=0 ifclose: noop opens=3 closes=3 deficits=0 phantom=0")
    )
    ok, note = if_phantom_protect(ctx, None, None, {})
    assert ok, note


def test_ifprot_fires_on_legacy_verdict(tmp_path: Path) -> None:
    r"""判词无 phantom 字段 (旧扫描器产物) → 保持现行放行 (backcompat)。"""
    ctx = _ifprot_ctx(
        tmp_path, _ledger("rc=0 ifclose: noop opens=3 closes=3 deficits=0")
    )
    ok, note = if_phantom_protect(ctx, None, None, {})
    assert ok, note
