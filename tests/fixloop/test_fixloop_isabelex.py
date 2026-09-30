r"""isabelex 车道 (runawayscan 车道普查 2026-09-19): ``comment_csform_isabelle_env``
规则 + ``detab_end_scanlines`` 签名闸。

1206.0136 (loop2, payload ``\next``): isabelle.sty ``\isakeeptag``/``\isadroptag``
经 ``\includecomment``/``\excludecomment`` 产 ``isadelim<tag>``/``isatag<tag>``
comment env 对, Isabelle 生成稿以 cs 形 ``\isadelimtheory…\endisadelimtheory``
调用——comment.sty v3.8 行扫描器整行等值比字面 ``\end{<env>}`` 哨兵, cs 形
终结行恒不中 → 吞到 EOF ``File ended while scanning use of \next``。修 =
cs 形 → env 形 (end 侧产字面哨兵; ``\begin`` 把 begin 宏首步 ``\endgroup``
的组配对还上)。

detab 闸: 原 ``when: {category: runaway_scan}`` 裸类对全 payload 盲发——
1206.0136 去缩进 ``\end{boxedminipage}``/eq 行白烧一轮, 2009.11130
(``\GetTitle``)/1109.5754 (``\@xdblarg``) 同列。收窄到 ``\next``
(comment.sty 行扫描器) 族, 其他 runaway cs 不进。
"""

from pathlib import Path

from _fixloopkit import EngStub, apply, classify, mk_ctx, rs, rule

from texlate.compile.fixloop import actions
from texlate.compile.fixloop.engine import Rule
from texlate.compile.logparse import ErrReport

_RID = "comment_csform_isabelle_env"

_NEXT_ERR = (
    "Including 'isadelimtheory' comment.)\n"
    "Runaway argument?\n"
    "! File ended while scanning use of \\next.\n"
    "<inserted text>\n"
    "                \\par\n"
    "l.3 \\input{Paper.tex}\n"
)


def _apply(
    tmp_path: Path, err_head: str = _NEXT_ERR, pay: str = "\\next"
) -> tuple[bool, str]:
    return apply(rule(_RID), mk_ctx(tmp_path, err_head=err_head), pay)


def _cond(
    rule_: Rule, tmp_path: Path, err_head: str, pay: str = "\\next"
) -> tuple[bool, str]:
    return actions._cond_ok(  # noqa: SLF001
        rule_.condition, rule_, mk_ctx(tmp_path, err_head=err_head), EngStub(), pay
    )


_CSFORM_DOC = (
    "\\documentclass{article}\n"
    "\\usepackage{comment}\n"
    "\\includecomment{isadelimtheory}\n"
    "\\includecomment{isatagtheory}\n"
    "\\begin{document}\n"
    "\\begin{isabellebody}%\n"
    "\\isadelimtheory\n"
    "%\n"
    "\\endisadelimtheory\n"
    "%\n"
    "\\isatagtheory\n"
    "theory tag body\n"
    "\\endisatagtheory\n"
    "{\\isafoldtheory}%\n"
    "%\n"
    "\\isadelimproof\n"
    "proof body\n"
    "\\endisadelimproof\n"
    "\\end{isabellebody}%\n"
    "\\end{document}\n"
)


# ---------------------------------------------------------------- 规则注册
def test_isabelex_rule_registered() -> None:
    r = rule(_RID)
    assert r.phase == "loop"
    assert r.order == 163.5  # noqa: PLR2004 - schema 断言值: detab(164) 前
    assert r.when["category"] == "runaway_scan"
    assert r.when["payload_required"] is True
    assert r.action["kind"] == "regex_rewrite"
    rws = r.action["params"]["rewrites"]
    assert len(rws) == 4  # noqa: PLR2004 - delim/tag × begin/end 四臂
    assert set(r.action["params"]["exts"]) == {".tex"}
    assert all(rw.get("match_surface") == "masked" for rw in rws)


def test_isabelex_before_detab() -> None:
    """同 \\next 族内 cs 形先收——env 形+缩进残面才落 detab。"""
    ids = [r.id for r in rs().phase("loop")]
    assert ids.index("comment_csform_isabelle_env") < ids.index("detab_end_scanlines")


# ---------------------------------------------------------------- 分类路由
def test_taxonomy_next_runaway_payload() -> None:
    """comment.sty 扫描器 runaway → runaway_scan 携 ``\\next`` payload。"""
    cat, pay = classify(_NEXT_ERR)
    assert (cat, pay) == ("runaway_scan", "\\next")


# ---------------------------------------------------------------- 条件闸
def test_cond_passes_on_next_csform(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(_CSFORM_DOC, encoding="utf-8")
    ok, why = _cond(rule(_RID), tmp_path, _NEXT_ERR)
    assert ok, why


def test_cond_skips_other_runaway_payload(tmp_path: Path) -> None:
    """``\\GetTitle``/``\\protected@edef`` 等非 \\next 扫描器不属本族。"""
    (tmp_path / "main.tex").write_text(_CSFORM_DOC, encoding="utf-8")
    for cs in ("\\GetTitle", "\\protected@edef", "\\@xdblarg"):
        err = f"! File ended while scanning use of {cs}.\nl.1 x\n"
        ok, why = _cond(rule(_RID), tmp_path, err, pay=cs)
        assert not ok, f"{cs} 应被 \\next 闸拦下 ({why})"


def test_cond_skips_env_form_source(tmp_path: Path) -> None:
    """已 env 形稿 (无 \\endisa*) → 让位 detab。"""
    doc = (
        "\\begin{isabellebody}%\n"
        "\\begin{isadelimtheory}\n%\n\\end{isadelimtheory}\n"
        "\\begin{isatagtheory}\nx\n\\end{isatagtheory}\n"
        "\\end{isabellebody}%\n"
    )
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ok, why = _cond(rule(_RID), tmp_path, _NEXT_ERR)
    assert not ok
    assert "源码无" in why


# ---------------------------------------------------------------- 改写面
def test_apply_csform_pairs_to_env(tmp_path: Path) -> None:
    """isabelle 实形: delim/tag cs 对 → env 形, ``\\isafold`` 纯宏不动。"""
    (tmp_path / "main.tex").write_text(_CSFORM_DOC, encoding="utf-8")
    ok, note = _apply(tmp_path)
    assert ok, note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\begin{isadelimtheory}\n" in t
    assert "\\end{isadelimtheory}\n" in t
    assert "\\begin{isatagtheory}\n" in t
    assert "\\end{isatagtheory}\n" in t
    assert "\\begin{isadelimproof}\n" in t
    assert "\\end{isadelimproof}\n" in t
    assert "\\isafoldtheory" in t  # 纯宏非 env 不收
    assert "\\endisadelimtheory" not in t
    assert "\\endisatagtheory" not in t


def test_apply_untouched_cs(tmp_path: Path) -> None:
    """``\\isabelle``/``\\endisabellebody`` 等非 delim/tag 名与 env 形行原样。"""
    doc = (
        "\\begin{isabellebody}%\n"
        "\\isadelimtheory\n\\endisadelimtheory\n"
        "\\end{isabellebody}%\n"
    )
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ok, _ = _apply(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\begin{isabellebody}%" in t
    assert "\\end{isabellebody}%" in t  # \\endisa(delim|tag) 不盖 isabelle 名


def test_apply_masked_comment_untouched(tmp_path: Path) -> None:
    """% 注释内字面 ``\\endisa*`` 不改 (masked 面), 活面照常转。"""
    doc = (
        "% \\endisadelimtheory 被注释掉的字面 cs\n"
        "\\isadelimtheory\n\\endisadelimtheory\n"
    )
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ok, _ = _apply(tmp_path)
    assert ok
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert t.startswith("% \\endisadelimtheory")  # 注释行原样
    assert "\\begin{isadelimtheory}\n\\end{isadelimtheory}\n" in t


def test_apply_idempotent(tmp_path: Path) -> None:
    """env 化后零命中 → decline, 内容稳定。"""
    (tmp_path / "main.tex").write_text(_CSFORM_DOC, encoding="utf-8")
    ok, _ = _apply(tmp_path)
    assert ok
    once = (tmp_path / "main.tex").read_text(encoding="utf-8")
    ok2, note2 = _apply(tmp_path)
    assert not ok2, note2
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == once


def test_apply_env_form_declines(tmp_path: Path) -> None:
    """全 env 形稿无 cs 形 → 0 files decline。"""
    doc = (
        "\\begin{isadelimtheory}\nbody\n\\end{isadelimtheory}\n"
        "\\begin{isatagtheory}\nx\n\\end{isatagtheory}\n"
    )
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ok, note = _apply(tmp_path)
    assert not ok
    assert "0 files" in note
    assert (tmp_path / "main.tex").read_text(encoding="utf-8") == doc


# ---------------------------------------------------------------- detab 签名闸
def test_detab_gated_to_next_payload() -> None:
    r = rule("detab_end_scanlines")
    assert r.when["category"] == "runaway_scan"
    assert r.when["payload_required"] is True


def test_detab_cond_next_reaches(tmp_path: Path) -> None:
    """\\next runaway + 缩进 \\end{ 在源 → detab 闸过且仍去缩进。"""
    doc = "\\begin{CCSXML}\n<ccs/>\n\t\\end{CCSXML}\n\\end{document}\n"
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    ok, why = _cond(rule("detab_end_scanlines"), tmp_path, _NEXT_ERR)
    assert ok, why
    applied, note = apply(
        rule("detab_end_scanlines"),
        mk_ctx(tmp_path, err_head=_NEXT_ERR),
        "\\next",
    )
    assert applied, note
    assert "\n\\end{CCSXML}\n" in (tmp_path / "main.tex").read_text(encoding="utf-8")


def test_detab_cond_skips_other_payloads(tmp_path: Path) -> None:
    """非 \\next runaway payload → cond skip, 不再盲发去缩进。"""
    doc = "\\begin{CCSXML}\n<ccs/>\n\t\\end{CCSXML}\n\\end{document}\n"
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    for cs in ("\\GetTitle", "\\protected@edef", "\\@xdblarg", "\\arg"):
        err = f"! File ended while scanning use of {cs}.\nl.1 x\n"
        ok, _why = _cond(rule("detab_end_scanlines"), tmp_path, err, pay=cs)
        assert not ok, f"{cs} 应被 \\next 闸拦下"
        assert (tmp_path / "main.tex").read_text(encoding="utf-8") == doc


def test_detab_cond_nextfoo_no_false_positive(tmp_path: Path) -> None:
    """``\\next`` 前缀共享名 (\\nextfoo) 不误中——``\\b`` 词界。"""
    doc = "\\begin{CCSXML}\n<ccs/>\n\t\\end{CCSXML}\n\\end{document}\n"
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    err = "! File ended while scanning use of \\nextfoo.\nl.1 x\n"
    ok, _ = _cond(rule("detab_end_scanlines"), tmp_path, err, pay="\\nextfoo")
    assert not ok


# ---------------------------------------------------------------- 联调派发
def test_match_apply_prefers_isabelex_on_csform(tmp_path: Path) -> None:
    """cs 形稿 + \\next → 全库派发首个命中即 isabelex (detab 不抢轮)。"""
    (tmp_path / "main.tex").write_text(_CSFORM_DOC, encoding="utf-8")
    hit, _note = actions._match_apply(  # noqa: SLF001
        rs(),
        mk_ctx(tmp_path, err_head=_NEXT_ERR),
        EngStub(),
        "runaway_scan",
        "\\next",
        ErrReport(first="! File ended while scanning use of \\next.", ctx="l.3 x"),
    )
    assert hit is not None
    assert hit.id == "comment_csform_isabelle_env"


def test_match_apply_detab_on_envform_indented(tmp_path: Path) -> None:
    """env 形+缩进 \\end → isabelex 让位, detab 接住同签名。"""
    doc = "\\begin{CCSXML}\n<ccs/>\n\t\\end{CCSXML}\n\\end{document}\n"
    (tmp_path / "main.tex").write_text(doc, encoding="utf-8")
    hit, _note = actions._match_apply(  # noqa: SLF001
        rs(),
        mk_ctx(tmp_path, err_head=_NEXT_ERR),
        EngStub(),
        "runaway_scan",
        "\\next",
        ErrReport(first="! File ended while scanning use of \\next.", ctx="l.3 x"),
    )
    assert hit is not None
    assert hit.id == "detab_end_scanlines"
