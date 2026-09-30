"""稿自带 .sty abstract-edef 捕获 hack 中和链单测 (签名件原位补丁, 非退役)。

实证背景 (corpus 1706.00240, iffalse-census #46 残格, unfixable:other):
e-print 自带 draft.sty 载 ``\\protected@edef\\@tempa{\\ifnum`}=\\z@`` —
— `` `} `` 被 ``\\ifnum`` 当字符码操作数吞掉 (125≠0 假值整段空) →
edef 的 ``{`` 失去配对 ``}`` 永不闭合 → abstract 体 + ``\\endabstract``
+ 文末全部流入 edef 扫描, 吸入展开链混入的 ``\\iffalse`` 至 EOF 不合
→ ``Incomplete \\iffalse`` (bt7.tex = article[twocolumn] + verbatim
draft.sty 零 texlate 含量同款复现, 2017 期构形 TL2026 不再容忍)。

修复面: err_head 不点名 sty 文件名 → ctx 签名 (``Incomplete \\if`` /
``File ended ... \\protected@edef``) ∧ wdir ``*.sty`` 在场 → sh 脚本对
``protected@edef.*ifnum`}=.z@`` / ``ifnum`{=.z@`` 逐件确证 (无签名→
no-op exit 0), 首个 ``\\endinput`` 前 (缺席则 EOF) 注入良性
``\\def\\abstract``/``\\endabstract`` 覆写 —— hack 两行仍在文件里但
永不再执行 (sty 载入只扫参不展开, 覆写在后赢); ``\\ifdefined\\maketitle``
保住无 ``\\maketitle`` 稿的题名块 (hack 原意即 abstract 触发题名)。
``texlate-fixloop-injected`` 指纹幂等防重复补丁。
"""

from pathlib import Path

from _fixloopkit import MockEngine, apply, classify, mk_ctx, rs, rule

from texlate.compile.fixloop import actions, fixloop
from texlate.compile.fixloop.engine import Rule

_RULE_ID = "abstract_edef_capture_neutralize"

# 1706.00240 实证首错形态: '!' 形 Incomplete iffalse (taxonomy 无专属
# 条目 → `^.` 兜底归 other) —— 吸收展开至 EOF 的姊妹死法走 runaway_scan。
_ERR_IFFALSE = (
    "! Incomplete \\iffalse; all text was ignored after line 317.\n"
    "<inserted text>\n                \\fi\n<*> torus.tex"
)
_ERR_EDEF_EOF = (
    "! File ended while scanning use of \\protected@edef.\n"
    "<inserted text>\n                }\n<*> torus.tex"
)

CLEAN_LOG = "This is XeTeX\nOutput written on main.pdf (1 page).\n"

# 1706.00240 draft.sty 逐字 hack 段 (字节即语义, 不润色)。
_HACK_STY = (
    "\\NeedsTeXFormat{LaTeX2e}\n"
    "\\ProvidesPackage{draft}[2013/11/08 Draft for astronomy article]\n"
    "\\newcommand*\\othermacro{keep me}\n"
    "\\renewcommand*\\abstract{\\begingroup\n"
    "  \\protected@edef\\@tempa{\\ifnum`}=\\z@\\fi\\ignorespaces}\n"
    "\\renewcommand*\\endabstract{\\ifnum`{=\\z@\\fi}%\n"
    "  \\if@twocolumn\n"
    "    \\twocolumn[\\@twocolumnfalse\\drf@abstract\\@twocolumntrue]%\n"
    "  \\else\n"
    "    \\drf@abstract\n"
    "  \\fi\n"
    "  \\endgroup\\ignorespacesafterend}\n"
    "\\newcommand*\\drf@abstract{\\maketitle}\n"
    "\\endinput\n"
)


def _rule() -> Rule:
    return rule(_RULE_ID)


# ---------------------------------------------------------------- taxonomy
def test_taxonomy_incomplete_iffalse_is_incomplete_if() -> None:
    """实证签名: `! Incomplete \\iffalse` → incomplete_if (taxrow 专属行, payload=条件 cs)。"""
    cat, pay = classify(_ERR_IFFALSE)
    assert cat == "incomplete_if"
    assert pay == "\\iffalse"


def test_taxonomy_edef_eof_is_runaway_scan() -> None:
    """姊妹死法: File ended while scanning use of \\protected@edef → runaway_scan。"""
    cat, pay = classify(_ERR_EDEF_EOF)
    assert cat == "runaway_scan"
    assert pay == "\\protected@edef"


# ---------------------------------------------------------------- 规则接线
def test_rule_wired_loop_phase() -> None:
    """规则挂 loop 相 order 11.95 → run_tool sh -c 签名件原位补丁。"""
    rule = _rule()
    assert rule.order == 11.95  # noqa: PLR2004 - schema 断言值
    cats = {c.get("category") for c in rule.when["any"]}
    assert cats == {"incomplete_if", "other", "syntax", "undefined_cs", "runaway_scan"}
    assert rule.condition["cache_dir_glob"] == "*.sty"
    assert rule.condition["tool_available"] == "sh"
    ctx_pats = {c.get("ctx_suggests") for c in rule.condition["any"]}
    assert ctx_pats == {
        "Incomplete \\\\if",
        "File ended while scanning use of \\\\protected@edef",
    }
    assert rule.action["kind"] == "run_tool"
    argv = rule.action["params"]["argv"]
    assert argv[:2] == ["sh", "-c"]
    script = argv[2]
    assert "texlate-fixloop-injected" in script  # 指纹幂等闸
    assert "protected@edef" in script  # 内容签名自证
    assert "\\endinput" in script  # 注入位: 首个 \endinput 前
    assert "\\def\\abstract" in script  # 良性环境覆写
    assert "\\def\\endabstract" in script


def test_rule_order_after_pstadd_before_legacy_shim() -> None:
    """order 排序自洽: pstricks_add_pair_retire(11.9) < 本规则 < legacy_pkg_shim(12)。"""
    orders = {r.id: r.order for r in rs().phase("loop")}
    assert orders["pstricks_add_pair_retire"] < orders[_RULE_ID]
    assert orders[_RULE_ID] < orders["legacy_pkg_shim"]


# ---------------------------------------------------------------- condition 闸
def test_cond_skip_when_no_sty(tmp_path: Path) -> None:
    """wdir 无 .sty → cache_dir_glob 闸拒。"""
    ctx = mk_ctx(tmp_path, err_head=_ERR_IFFALSE)
    ok, why = actions._cond_ok(  # noqa: SLF001 - 闸行为直驱
        _rule().condition, _rule(), ctx, None, None
    )
    assert not ok
    assert "*.sty" in why


def test_cond_skip_when_ctx_unsigned(tmp_path: Path) -> None:
    """.sty 在场但错误无 Incomplete/edef 签名 → ctx_suggests any 闸拒。"""
    (tmp_path / "draft.sty").write_text(_HACK_STY, encoding="utf-8")
    ctx = mk_ctx(
        tmp_path, err_head="./main.tex:10: Undefined control sequence.\nl.10 \\foo\n"
    )
    ok, _ = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert not ok


def test_cond_pass_on_iffalse_signature(tmp_path: Path) -> None:
    """.sty + `Incomplete \\iffalse` err blob → 条件过。"""
    (tmp_path / "draft.sty").write_text(_HACK_STY, encoding="utf-8")
    ctx = mk_ctx(tmp_path, err_head=_ERR_IFFALSE)
    ok, why = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert ok, why


def test_cond_pass_on_edef_eof_signature(tmp_path: Path) -> None:
    """.sty + File-ended-\\protected@edef err blob → 条件过 (姊妹死法臂)。"""
    (tmp_path / "draft.sty").write_text(_HACK_STY, encoding="utf-8")
    ctx = mk_ctx(tmp_path, err_head=_ERR_EDEF_EOF)
    ok, why = actions._cond_ok(_rule().condition, _rule(), ctx, None, None)  # noqa: SLF001
    assert ok, why


# ---------------------------------------------------------------- 动作直驱 (真 sh)
def test_apply_patches_signed_sty(tmp_path: Path) -> None:
    """_apply 真跑 sh: hack 件 → \\endinput 前注入良性覆写, 其余逐字节保留。"""
    (tmp_path / "draft.sty").write_text(_HACK_STY, encoding="utf-8")
    ctx = mk_ctx(tmp_path)
    ok, note = apply(_RULE_ID, ctx, None)
    assert ok, note
    patched = (tmp_path / "draft.sty").read_text(encoding="utf-8")
    assert "texlate-fixloop-injected" in patched
    assert "\\def\\abstract{\\ifdefined\\maketitle\\maketitle\\fi" in patched
    assert "\\def\\endabstract{\\endquotation" in patched
    # 注入位在 \endinput 前 (注入行在 endinput 行之前)
    assert patched.index("texlate-fixloop-injected") < patched.index("\\endinput")
    # 原 hack 行仍在 (覆写赢在执行层, 非删除) + 其余宏逐字节保留
    assert "\\protected@edef\\@tempa{\\ifnum`}=\\z@" in patched
    assert "\\newcommand*\\othermacro{keep me}" in patched
    # 逐字节差分: 原行全部保留, 新增恰为指纹注释+两行覆写
    orig_lines = _HACK_STY.splitlines(keepends=True)
    new_lines = patched.splitlines(keepends=True)
    assert new_lines[: len(orig_lines) - 1] == orig_lines[:-1]
    assert new_lines[-1] == orig_lines[-1]
    assert len(new_lines) == len(orig_lines) + 3


def test_apply_skips_unsigned_sty(tmp_path: Path) -> None:
    """无签名件 → 脚本 continue, 文件逐字节不动。"""
    clean = "\\ProvidesPackage{foo}\\newcommand*\\foo{bar}\n\\endinput\n"
    (tmp_path / "foo.sty").write_text(clean, encoding="utf-8")
    ctx = mk_ctx(tmp_path)
    ok, note = apply(_RULE_ID, ctx, None)
    assert ok, note  # run_tool 恒 applied (rc=0 no-op)
    assert (tmp_path / "foo.sty").read_text(encoding="utf-8") == clean


def test_apply_idempotent_second_run(tmp_path: Path) -> None:
    """指纹闸: 二次 _apply 同件不再补丁 (防重投/重复注入)。"""
    (tmp_path / "draft.sty").write_text(_HACK_STY, encoding="utf-8")
    ctx = mk_ctx(tmp_path)
    ok1, _ = apply(_RULE_ID, ctx, None)
    assert ok1
    once = (tmp_path / "draft.sty").read_text(encoding="utf-8")
    assert once.count("texlate-fixloop-injected") == 1
    ok2, _ = apply(_RULE_ID, ctx, None)
    assert ok2
    assert (tmp_path / "draft.sty").read_text(encoding="utf-8") == once


def test_apply_appends_when_no_endinput(tmp_path: Path) -> None:
    """无 \\endinput 件 → 覆写落 EOF (仍在 hack 定义后 → 执行层赢)。"""
    no_eof = _HACK_STY.replace("\\endinput\n", "")
    (tmp_path / "draft.sty").write_text(no_eof, encoding="utf-8")
    ctx = mk_ctx(tmp_path)
    ok, note = apply(_RULE_ID, ctx, None)
    assert ok, note
    patched = (tmp_path / "draft.sty").read_text(encoding="utf-8")
    assert patched.startswith(no_eof)
    assert patched.rstrip().endswith(
        "\\def\\endabstract{\\endquotation\\ignorespacesafterend}%"
    )


def test_apply_patches_signed_cls(tmp_path: Path) -> None:
    """.cls 臂: hack 在 cls 件 (sty 伴生在旁过 glob 闸) → cls 同获补丁。"""
    (tmp_path / "draft.cls").write_text(_HACK_STY, encoding="utf-8")
    (tmp_path / "dummy.sty").write_text("\\ProvidesPackage{dummy}\n", encoding="utf-8")
    ctx = mk_ctx(tmp_path)
    ok, note = apply(_RULE_ID, ctx, None)
    assert ok, note
    assert "texlate-fixloop-injected" in (tmp_path / "draft.cls").read_text(
        encoding="utf-8"
    )
    assert "texlate-fixloop-injected" not in (tmp_path / "dummy.sty").read_text(
        encoding="utf-8"
    )


def test_apply_noop_when_dir_empty(tmp_path: Path) -> None:
    """空 wdir → *.sty 字面量不命中, [ -f ] 兜住 → exit 0 no-op。"""
    ctx = mk_ctx(tmp_path)
    ok, note = apply(_RULE_ID, ctx, None)
    assert ok, note
    assert list(tmp_path.iterdir()) == []


def test_apply_skips_comment_only_signature(tmp_path: Path) -> None:
    """签名仅活注释行 (draft.sty 的 :62-64 被注变体形) → 判无签名不补丁。"""
    comment_only = (
        "\\ProvidesPackage{foo}\n"
        "%\\renewcommand*\\abstract{\\begingroup\n"
        "%  \\protected@edef\\@tempa{\\ifnum`}=\\z@\\fi\\ignorespaces}\n"
        "%\\renewcommand*\\endabstract{\\ifnum`{=\\z@\\fi}\n"
        "\\newcommand*\\foo{bar}\n"
        "\\endinput\n"
    )
    (tmp_path / "foo.sty").write_text(comment_only, encoding="utf-8")
    ctx = mk_ctx(tmp_path)
    ok, note = apply(_RULE_ID, ctx, None)
    assert ok, note
    assert (tmp_path / "foo.sty").read_text(encoding="utf-8") == comment_only


# ---------------------------------------------------------------- e2e
class _MockEngine(MockEngine):
    """逐轮吐 spec——``caps`` 钉 ``{kpsewhich,tlmgr}`` 变体 (无 updmap 面)。"""

    caps = frozenset({"kpsewhich", "tlmgr"})


def _proj(tmp_path: Path) -> Path:
    (tmp_path / "main.tex").write_text(
        "\\documentclass[twocolumn]{article}\n\\usepackage{draft}\n"
        "\\begin{document}\n\\begin{abstract}\nx\n\\end{abstract}\n"
        "\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "draft.sty").write_text(_HACK_STY, encoding="utf-8")
    return tmp_path


def test_e2e_iffalse_patched_then_clean(tmp_path: Path) -> None:
    """整链: Incomplete \\iffalse 首错 → 签名件补丁 → 下轮 clean。"""
    eng = _MockEngine(
        [
            {"log": _ERR_IFFALSE + "\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == _RULE_ID for a in cell["actions"])
    patched = (tmp_path / "draft.sty").read_text(encoding="utf-8")
    assert "texlate-fixloop-injected" in patched
    assert "\\def\\abstract{\\ifdefined\\maketitle" in patched


def test_e2e_edef_eof_arm_patched(tmp_path: Path) -> None:
    """姊妹死法臂: File-ended-\\protected@edef 首错 → 同规则补丁。"""
    eng = _MockEngine(
        [
            {"log": _ERR_EDEF_EOF + "\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == _RULE_ID for a in cell["actions"])
    assert "texlate-fixloop-injected" in (tmp_path / "draft.sty").read_text(
        encoding="utf-8"
    )


def test_e2e_no_fire_on_unsigned_ctx(tmp_path: Path) -> None:
    """.sty 带 hack 但错误是别家签名 → ctx 闸拒, 不动文件。"""
    eng = _MockEngine(
        [
            {"log": "./main.tex:5: Undefined control sequence.\nl.5 \\foo\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(_proj(tmp_path), eng)
    assert not any(a["rule"] == _RULE_ID for a in cell["actions"])
    assert (tmp_path / "draft.sty").read_text(encoding="utf-8") == _HACK_STY
