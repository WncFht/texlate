"""未闭合 \\if* → 文件尾 \\fi 注入双臂单测 (failmine item 4, 16 格)。

实证背景: ``! Incomplete \\iffalse; all text was ignored after line N``
(taxonomy 无专属条目 → ``^.`` 兜底归 other, ctx_suggests 可及) 与
``(\\end occurred when \\ifx on line N was incomplete)`` + ``No pages of
output`` (无 ``!`` 行 → err_head 空 → ctx_suggests 不可及 → early_eof 独立
臂走 source_contains 门 + payload_required 滤 generic no-pages)。

修复面: python3 扫描器对 doc 源件 (.tex/.sty/.cls, mask_tex 剥注释/verb)
做 \\if*/\\fi 栈平衡: 只对"活区"(def 体外) 亏格件在 \\end{document}/
\\endinput/EOF 前注入 \\fi×亏格数。def 体 open 是冻结 token (file-end
\\fi 够不到 → 注入反造 Extra \\fi), 只计不注; \\repeat/\\newif/\\let 等
非 open 语义位与 etoolbox/ifthen \\if* 宏系 denylist 剥离; 跨文件借用对
(\\if 开 A 件 \\fi 闭 B 件) 由全局 opens>closes 闸兜住 —— 扫描器即
draftsty-phantom (展开态 \\iffalse 源件字面平衡) 判别器, 平衡即 noop。
``texlate-fixloop-injected`` 指纹幂等防重复注入。
"""

from pathlib import Path

from _fixloopkit import apply, classify, mk_ctx, rs, rule
from test_fixloop_loop import MockEngine

from texlate.compile.fixloop import actions, fixloop
from texlate.compile.fixloop.engine import LoopCtx, Rule

_RULE_ID = "unclosed_if_close"
_RULE_ID_EOF = "unclosed_if_close_eof"

# 实证签名: 1706.00240 同款 `!` 形 (taxonomy 落 other, pay=None)。
_ERR_IFFALSE = (
    "! Incomplete \\iffalse; all text was ignored after line 5.\n"
    "<inserted text>\n                \\fi\n<*> main.tex"
)
# loop1 格同款: 无 `!` 行, tail 签名 → early_eof pay=\ifx。
_ERR_IFX_EOF = (
    "This is XeTeX\n(\\end occurred when \\ifx on line 9 was incomplete)\n"
    "No pages of output.\n"
)
CLEAN_LOG = "This is XeTeX\nOutput written on main.pdf (1 page).\n"


def _classify(text: str) -> tuple[str | None, str | None]:
    """kit ``classify`` + 补尾换行——旧 ``_classify`` 对 ``parse_text`` 先 ``+"\\n"``。"""
    return classify(text + "\n")


def _cond(rid: str, ctx: LoopCtx) -> tuple[bool, str]:
    """cond 闸直驱——SLF001 豁免一处收口 (kit ``cond_ok`` 待入后归并)。"""
    return actions._cond_ok(rule(rid).condition, rule(rid), ctx, None, None)  # noqa: SLF001


def _apply(r: Rule | str, wdir: Path) -> tuple[bool, str]:
    """kit ``apply`` + ``mk_ctx(main_rel=None)``——原就地 ``LoopCtx`` 口径保持。"""
    return apply(r, mk_ctx(wdir, main_rel=None), None)


# ---------------------------------------------------------------- taxonomy
def test_taxonomy_incomplete_iffalse_is_incomplete_if() -> None:
    """`! Incomplete \\iffalse` → incomplete_if (taxrow 专属行, pay=条件 cs)。"""
    cat, pay = _classify(_ERR_IFFALSE)
    assert cat == "incomplete_if"
    assert pay == "\\iffalse"


def test_taxonomy_end_occurred_ifx_is_early_eof() -> None:
    """`\\end occurred when \\ifx incomplete` + no-pages → early_eof pay=\\ifx。"""
    cat, pay = _classify(_ERR_IFX_EOF)
    assert cat == "early_eof"
    assert pay == "\\ifx"


# ---------------------------------------------------------------- 规则接线
def test_rule_other_arm_wired() -> None:
    """other 臂: when=other, ctx_suggests Incomplete \\if + python3, run_tool。"""
    r = rule(_RULE_ID)
    assert r.order == 196  # noqa: PLR2004 - schema 断言值
    cats = {c.get("category") for c in r.when["any"]}
    assert cats == {"other", "incomplete_if"}
    assert r.condition["ctx_suggests"] == "Incomplete \\\\if"
    assert r.condition["tool_available"] == "python3"
    assert r.action["kind"] == "run_tool"
    argv = r.action["params"]["argv"]
    assert argv[:2] == ["{python}", "-c"]
    script = argv[2]
    assert "texlate-fixloop-injected" in script
    assert "scan_ifs" in script  # 扫描器在 textutil.ifscan (注释/verb 经 mask_tex 剥)
    # 注入碎片是转义字面 `"\\fi" * len(pre/post)`——脚本注释里的裸 `\fi` 不算
    assert "\\\\fi" in script


def test_rule_eof_arm_wired() -> None:
    """early_eof 臂: payload_required 滤 generic no-pages, source_contains 门。"""
    r = rule(_RULE_ID_EOF)
    assert r.order == 196.5  # noqa: PLR2004 - schema 断言值
    assert r.when == {"category": "early_eof", "payload_required": True}
    assert r.condition["source_contains"] == "\\\\if"
    assert r.condition["tool_available"] == "python3"
    assert r.action["params"]["argv"][:2] == ["{python}", "-c"]


def test_rule_order_after_pdfstring_before_sentinel() -> None:
    """order 排序自洽: pdfstring_cs_disarm(193) < 本双臂 < undefined_cs_guess(900)。"""
    orders = {r.id: r.order for r in rs().phase("loop")}
    assert orders["pdfstring_cs_disarm"] < orders[_RULE_ID]
    assert orders[_RULE_ID] < orders[_RULE_ID_EOF]
    assert orders[_RULE_ID_EOF] < orders["undefined_cs_guess"]
    # draftsty 补丁 (11.95) 先行: phantom 格真修先拿, 本臂兜真亏格
    assert orders["abstract_edef_capture_neutralize"] < orders[_RULE_ID]


# ---------------------------------------------------------------- condition 闸
def test_cond_other_arm_pass_on_incomplete_ctx(tmp_path: Path) -> None:
    """ctx 带 Incomplete \\if 签名 → other 臂条件过。"""
    ctx = mk_ctx(tmp_path, main_rel=None, err_head=_ERR_IFFALSE)
    ok, why = _cond(_RULE_ID, ctx)
    assert ok, why


def test_cond_other_arm_reject_unsigned_ctx(tmp_path: Path) -> None:
    """other 错误无 Incomplete 签名 → 闸拒 (防任意 other 烧 dedup 槽)。"""
    ctx = mk_ctx(
        tmp_path,
        main_rel=None,
        err_head="./main.tex:10: Undefined control sequence.\nl.10 \\foo\n",
    )
    ok, _ = _cond(_RULE_ID, ctx)
    assert not ok


def test_cond_eof_arm_pass_on_if_source(tmp_path: Path) -> None:
    """源件含 \\if → early_eof 臂条件过 (err_head 空不依赖 ctx)。"""
    (tmp_path / "main.tex").write_text("\\ifx\\a\\b x\n", encoding="utf-8")
    ok, why = _cond(_RULE_ID_EOF, mk_ctx(tmp_path, main_rel=None))
    assert ok, why


def test_cond_eof_arm_reject_no_if_source(tmp_path: Path) -> None:
    """源件无 \\if → 闸拒。"""
    (tmp_path / "main.tex").write_text("plain text\n", encoding="utf-8")
    ok, _ = _cond(_RULE_ID_EOF, mk_ctx(tmp_path, main_rel=None))
    assert not ok


def test_when_eof_arm_payload_required() -> None:
    """early_eof 裸 no-pages (pay=None) → _when_ok 拒; \\ifx payload → 过。"""
    ctx = mk_ctx(Path("/nonexistent"), main_rel=None)
    when = rule(_RULE_ID_EOF).when
    assert not actions._when_ok(when, "early_eof", None, ctx)  # noqa: SLF001
    assert actions._when_ok(when, "early_eof", "\\ifx", ctx)  # noqa: SLF001
    assert not actions._when_ok(when, "other", "\\ifx", ctx)  # noqa: SLF001


# ---------------------------------------------------------------- 动作直驱 (真 python3)
def test_apply_unclosed_iffalse_injects_before_enddoc(tmp_path: Path) -> None:
    """中段 \\iffalse 未闭 → \\end{document} 行前排注入 \\fi + 指纹。"""
    main = (
        "\\documentclass{article}\n\\begin{document}\nhello\n"
        "\\iffalse\nhidden\n\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    ok, note = _apply(_RULE_ID, tmp_path)
    assert ok, note
    patched = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "texlate-fixloop-injected" in patched
    assert patched.index("\\fi % texlate-fixloop-injected") < patched.index(
        "\\end{document}"
    )
    assert patched.index("hidden") < patched.index("\\fi")


def test_apply_unclosed_in_input_file(tmp_path: Path) -> None:
    """\\input 件亏格 → \\fi 落在该件 (非主件), EOF 追加。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\input{sec.tex}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "sec.tex").write_text("text\n\\ifnum 1=2\nhidden\n", encoding="utf-8")
    ok, note = _apply(_RULE_ID, tmp_path)
    assert ok, note
    sec = (tmp_path / "sec.tex").read_text(encoding="utf-8")
    assert "texlate-fixloop-injected" in sec
    assert "\\fi" in sec
    assert "texlate-fixloop-injected" not in (tmp_path / "main.tex").read_text(
        encoding="utf-8"
    )


def test_apply_balanced_doc_untouched(tmp_path: Path) -> None:
    """平衡档 → 逐字节不动。"""
    main = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\ifnum 1=1\nyes\n\\fi\ntext\n\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    ok, note = _apply(_RULE_ID, tmp_path)
    assert ok, note
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == main


def test_apply_comment_line_if_skipped(tmp_path: Path) -> None:
    """注释行 \\iffalse 不计 → 平衡档不动 (mask_tex 面)。"""
    main = (
        "\\documentclass{article}\n\\begin{document}\n"
        "% \\iffalse hidden in comment\nreal\n\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    ok, note = _apply(_RULE_ID, tmp_path)
    assert ok, note
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == main


def test_apply_idempotent_second_run(tmp_path: Path) -> None:
    """指纹闸: 二次 _apply 不再注入。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\iffalse\nhidden\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    ok1, _ = _apply(_RULE_ID, tmp_path)
    assert ok1
    once = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert once.count("texlate-fixloop-injected") == 1
    ok2, _ = _apply(_RULE_ID, tmp_path)
    assert ok2
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == once


def test_apply_multi_deficit_injects_n_fi(tmp_path: Path) -> None:
    """双亏格 → 单行 \\fi\\fi (不拆两处)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\ifx\\a\\b hidden\n"
        "\\iffalse more\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _apply(_RULE_ID, tmp_path)
    assert ok, note
    patched = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\fi\\fi % texlate-fixloop-injected" in patched
    assert patched.index("\\fi\\fi") < patched.index("\\end{document}")


def test_apply_endinput_cls_injects_before_endinput(tmp_path: Path) -> None:
    """cls 件活区亏格 → \\endinput 前注入 (非 EOF 追加)。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{mycls}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "mycls.cls").write_text(
        "\\ProvidesClass{mycls}\n\\iffalse\nhidden\n\\endinput\n", encoding="utf-8"
    )
    ok, note = _apply(_RULE_ID, tmp_path)
    assert ok, note
    cls = (tmp_path / "mycls.cls").read_text(encoding="utf-8")
    assert cls.index("\\fi % texlate-fixloop-injected") < cls.index("\\endinput")


def test_apply_def_body_open_no_inject(tmp_path: Path) -> None:
    """def 体内未闭 open (aastex61 \\if@two@col 型) → file-end 不注。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{mycls}\n\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    cls = (
        "\\ProvidesClass{mycls}\n"
        "\\def\\broken{\\if@two@col\\twocolumngrid}\n"
        "\\def\\fixed{\\if@two@col\\twocolumngrid\\fi}\n"
        "\\endinput\n"
    )
    (tmp_path / "mycls.cls").write_text(cls, encoding="utf-8")
    ok, note = _apply(_RULE_ID, tmp_path)
    assert ok, note
    assert (tmp_path / "mycls.cls").read_text(encoding="utf-8") == cls
    assert "texlate-fixloop-injected" not in (tmp_path / "main.tex").read_text(
        encoding="utf-8"
    )


def test_apply_crossfile_borrow_noop(tmp_path: Path) -> None:
    """借用对: \\if 开 main 件 \\fi 闭 input 件 → 全局平衡 noop。"""
    main = (
        "\\documentclass{article}\n\\begin{document}\n\\iffalse\n"
        "\\input{part.tex}\n\\end{document}\n"
    )
    part = "\\fi\nrestored\n"
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    (tmp_path / "part.tex").write_text(part, encoding="utf-8")
    ok, note = _apply(_RULE_ID, tmp_path)
    assert ok, note
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == main
    assert (tmp_path / "part.tex").read_text(encoding="utf-8") == part


def test_apply_draftsty_phantom_no_misfire(tmp_path: Path) -> None:
    """draftsty phantom 型: hack 件在场但源件字面平衡 → 全线不动。"""
    main = (
        "\\documentclass[twocolumn]{article}\n\\usepackage{draft}\n"
        "\\begin{document}\n\\begin{abstract}\nx\n\\end{abstract}\n"
        "\\end{document}\n"
    )
    sty = (
        "\\ProvidesPackage{draft}\n"
        "\\renewcommand*\\abstract{\\begingroup\n"
        "  \\protected@edef\\@tempa{\\ifnum`}=\\z@\\fi\\ignorespaces}\n"
        "\\renewcommand*\\endabstract{\\ifnum`{=\\z@\\fi}%\n"
        "  \\if@twocolumn\\twocolumn[\\drf@abstract]\\else\\drf@abstract\\fi\n"
        "  \\endgroup}\n"
        "\\newcommand*\\drf@abstract{\\maketitle}\n"
        "\\endinput\n"
    )
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    (tmp_path / "draft.sty").write_text(sty, encoding="utf-8")
    ok, note = _apply(_RULE_ID, tmp_path)
    assert ok, note
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == main
    assert (tmp_path / "draft.sty").read_text(encoding="utf-8") == sty


def test_apply_newif_and_loop_repeat_balanced(tmp_path: Path) -> None:
    """\\newif 声明位 + \\loop\\if...\\repeat 惯用法 → 不误判亏格。"""
    main = (
        "\\documentclass{article}\n\\begin{document}\n"
        "\\loop\\ifnum\\count0<5 \\advance\\count0 by1 \\repeat\n"
        "\\newif\\iffoo\\footrue\n\\iffoo yes\\fi\n"
        "\\newcommand{\\ifbar}{x}\n\\end{document}\n"
    )
    (tmp_path / "main.tex").write_text(main, encoding="utf-8")
    ok, note = _apply(_RULE_ID, tmp_path)
    assert ok, note
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == main


def test_apply_eof_arm_same_scanner(tmp_path: Path) -> None:
    """early_eof 臂共用扫描器: 亏格件同样获注入。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\ifx\\a\\b hidden\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = _apply(_RULE_ID_EOF, tmp_path)
    assert ok, note
    assert "\\fi % texlate-fixloop-injected" in (tmp_path / "main.tex").read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------------- e2e
def _proj(tmp_path: Path, body: str) -> Path:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n" + body + "\\end{document}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_e2e_iffalse_injected_then_clean(tmp_path: Path) -> None:
    """整链: Incomplete \\iffalse 首错 → \\fi 注入 → 下轮 clean。"""
    _proj(tmp_path, "hello\n\\iffalse\nhidden\n")
    eng = MockEngine(
        [
            {"log": _ERR_IFFALSE + "\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(tmp_path, eng)
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == _RULE_ID for a in cell["actions"])
    patched = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\fi % texlate-fixloop-injected" in patched
    assert patched.index("\\fi %") < patched.index("\\end{document}")


def test_e2e_eof_arm_injected_then_clean(tmp_path: Path) -> None:
    """整链: \\end-occurred-\\ifx early_eof → eof 臂注入 → 下轮 clean。"""
    _proj(tmp_path, "hello\n\\ifx\\a\\b hidden\n")
    eng = MockEngine(
        [
            {"log": _ERR_IFX_EOF + "\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(tmp_path, eng)
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == _RULE_ID_EOF for a in cell["actions"])
    assert "\\fi % texlate-fixloop-injected" in (tmp_path / "main.tex").read_text(
        encoding="utf-8"
    )


def test_e2e_balanced_doc_no_fire(tmp_path: Path) -> None:
    """Incomplete 签名但源件平衡 → 规则 fire 但 noop (不注入)。"""
    main_body = "hello\n\\ifnum 1=1\nyes\n\\fi\n"
    _proj(tmp_path, main_body)
    eng = MockEngine(
        [
            {"log": _ERR_IFFALSE + "\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(tmp_path, eng)
    assert cell["verdict"] == "clean"
    patched = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "texlate-fixloop-injected" not in patched
