r"""revtex4 v4.0a era-retire 规则单测 (revtexlane, census 3 格同机)。

实证背景 (0806.4149/1003.0910/1907.00131, stagerun-loop3+loop1):
e-print/user-texmf 自带 revtex4.cls v4.0a 内嵌 textcase v0.06 ——
``\MakeUppercase`` 绑死 ``\MakeTextUppercase``→``\@uclcnotmath``,
内嵌 ``\protected@edef\reserved@a`` 现代 kernel 炸
``Illegal parameter number in definition of \reserved@a``
(\Citeauthor→natbib \NAT@UP, syntax) / ``Use of \@citex doesn't match``
(thebibliography mark 机, other)。修复面 (mnras-retire 裁定形):
工程内 .cls mv .fixloop-iso + 同 stem delegate→revtex4-2;
``~/texmf`` 树外遮蔽只读探测, cwd 根 delegate 遮蔽 (树外不 mv)。
指纹双锚: ``\ProvidesClass{revtex4}`` 本名精确 ∧ ``\@uclcnotmath``。
"""

from collections.abc import Callable
from pathlib import Path

from _fixloopkit import ShadowEng, mk_ctx, proj_texmf, rs, rule

from texlate.compile.fixloop import actions
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.logparse import parse_text

_RULE_ID = "revtex_era_retire"

# 0806.4149 实证首错: \Citeauthor→\NAT@UP→\@uclcnotmath→\reserved@a (syntax)
_ERR_RESERVED = (
    "/work/ms.tex:929: Illegal parameter number in definition of "
    "\\reserved@a.\n<to be read again>\n                   }\n"
    "l.929 ...\\Citeauthor{Osaki85}"
)
# 1003.0910 实证: thebibliography mark 机 → \@citex 失配 (other)
_ERR_CITEX = (
    "/work/x.tex:594: Use of \\@citex doesn't match its definition.\n"
    "\\@uclcnotmath ...s@ {\\noexpand \\cite ##1}\\@citex }\n"
    "l.594 \\begin{thebibliography}{10}"
)

# v4.0a 指纹体: \ProvidesClass{revtex4} 本名 + 内嵌 \@uclcnotmath
# (改名拷贝体内自署不变 —— 文件改名不改 \ProvidesClass 声明)
_STALE_REVTEX4 = (
    "\\ProvidesClass{revtex4}[2020/09/30 v4.0a APS]\n"
    "\\def\\@uclcnotmath#1{\\protected@edef\\reserved@a{#1}}\n"
    "\\let\\MakeUppercase=\\MakeTextUppercase\n"
)
# 现代件反例: (a) revtex4-2 自署别名, 纵有同名机亦非指纹对象
_NEW_42 = "\\ProvidesClass{revtex4-2}[2024/01/01 v4.2f APS]\n\\def\\@uclcnotmath#1{}\n"
# (b) 现代 textcase.sty: \@uclcnotmath 在场但无 {revtex4} 自署 → 单锚不算
_MODERN_TEXTCASE = (
    "\\ProvidesPackage{textcase}[2023/07/27 v1.05]\n"
    "\\def\\@uclcnotmath#1{\\NoCaseChange{#1}}\n"
)


def _fn() -> Callable[..., tuple[bool, str]]:
    return TRANSFORM_FNS["revtex_era_retire"]


def _42(texmf: Path) -> None:
    """递补源: texmf 放 revtex4-2.cls (vendor files/ 另有兜底, 双源皆可)。"""
    (texmf / "revtex4-2.cls").write_text(_NEW_42, encoding="utf-8")


# ---------------------------------------------------------------- taxonomy
def test_taxonomy_reserved_a_is_syntax() -> None:
    """实证签名 Illegal parameter number → syntax (0806.4149 final_cat)。"""
    rep = parse_text(_ERR_RESERVED)
    cat, _ = rs().taxonomy.classify(rep)
    assert cat == "syntax"


def test_taxonomy_citex_pin() -> None:
    """实证签名 \\@citex doesn't match → taxrow 归 cs_mismatch (1003.0910)。"""
    rep = parse_text(_ERR_CITEX)
    cat, _ = rs().taxonomy.classify(rep)
    assert cat == "cs_mismatch"


# ---------------------------------------------------------------- 规则接线
def test_rule_wired() -> None:
    """挂 loop 相 order 11.98 → builtin_transform revtex_era_retire。"""
    rl = rule(_RULE_ID)
    assert rl.order == 11.98  # noqa: PLR2004 - schema 断言值
    cats = {c.get("category") for c in rl.when["any"]}
    assert {"syntax", "other", "early_eof", "undefined_cs"} <= cats
    assert "reserved@a" in rl.condition["ctx_suggests"]
    assert rl.action["kind"] == "builtin_transform"
    assert rl.action["function"] == "revtex_era_retire"


def test_rule_order_in_retire_family() -> None:
    """order 自洽: lamsarrow(11.97) < 本规则 < legacy_pkg_shim(12)。"""
    orders = {r.id: r.order for r in rs().phase("loop")}
    assert orders["lamsarrow_lams_fonts_drop"] < orders[_RULE_ID]
    assert orders[_RULE_ID] < orders["legacy_pkg_shim"]


# ---------------------------------------------------------------- condition 闸
def test_cond_skip_unrelated(tmp_path: Path) -> None:
    """err_head 无签名 → ctx_suggests 闸拒。"""
    ctx = mk_ctx(tmp_path)
    ctx.err_head = "./main.tex:10: LaTeX Error: Something else.\nl.10 x\n"
    rl = rule(_RULE_ID)
    ok, _ = actions._cond_ok(rl.condition, rl, ctx, None, None)  # noqa: SLF001
    assert not ok


def test_cond_skip_revtex42_name(tmp_path: Path) -> None:
    """err_head 只提 revtex4-2.cls → ``revtex4\\.cls`` 带点锚不命中。"""
    ctx = mk_ctx(tmp_path)
    ctx.err_head = "./revtex4-2.cls:10: LaTeX Error: boom.\nl.10 x\n"
    rl = rule(_RULE_ID)
    ok, _ = actions._cond_ok(rl.condition, rl, ctx, None, None)  # noqa: SLF001
    assert not ok


def test_cond_pass_reserved_a(tmp_path: Path) -> None:
    ctx = mk_ctx(tmp_path)
    ctx.err_head = _ERR_RESERVED
    rl = rule(_RULE_ID)
    ok, why = actions._cond_ok(rl.condition, rl, ctx, None, None)  # noqa: SLF001
    assert ok, why


def test_cond_pass_citex(tmp_path: Path) -> None:
    ctx = mk_ctx(tmp_path)
    ctx.err_head = _ERR_CITEX
    rl = rule(_RULE_ID)
    ok, why = actions._cond_ok(rl.condition, rl, ctx, None, None)  # noqa: SLF001
    assert ok, why


def test_cond_pass_filename(tmp_path: Path) -> None:
    """file-line 点名 revtex4.cls → 第三签命中。"""
    ctx = mk_ctx(tmp_path)
    ctx.err_head = "./revtex4.cls:3737: LaTeX Error: boom.\nl.3737 x\n"
    rl = rule(_RULE_ID)
    ok, why = actions._cond_ok(rl.condition, rl, ctx, None, None)  # noqa: SLF001
    assert ok, why


# ---------------------------------------------------------------- pass 1 指纹退役
def test_stale_revtex4_retired_with_delegate(tmp_path: Path) -> None:
    """本名 revtex4.cls v4.0a → .fixloop-iso + 同名 delegate 接 revtex4-2。

    本名亦须 delegate —— 系统 TL 无 ``revtex4`` 名递补 (唯 revtex4-2),
    裸退役即 missing_file/再中毒 (与 amsmath 本名无 delegate 形不同)。
    """
    wdir, texmf = proj_texmf(tmp_path)
    _42(texmf)
    (wdir / "revtex4.cls").write_text(_STALE_REVTEX4, encoding="utf-8")
    ok, note = _fn()(mk_ctx(wdir), ShadowEng(texmf), None, {})
    assert ok, note
    assert (wdir / "revtex4.cls.fixloop-iso").is_file()
    body = (wdir / "revtex4.cls").read_text(encoding="utf-8")
    assert body.startswith("% texlate-fixloop-injected:")
    assert "\\ProvidesClass{revtex4}" in body
    assert "\\LoadClassWithOptions{revtex4-2}" in body


def test_renamed_copy_gets_stem_delegate(tmp_path: Path) -> None:
    """改名件 revtex4old.cls (体内仍署 {revtex4}) → 退役 + stem 名 delegate。"""
    wdir, texmf = proj_texmf(tmp_path)
    _42(texmf)
    (wdir / "revtex4old.cls").write_text(_STALE_REVTEX4, encoding="utf-8")
    ok, note = _fn()(mk_ctx(wdir), ShadowEng(texmf), None, {})
    assert ok, note
    assert (wdir / "revtex4old.cls.fixloop-iso").is_file()
    body = (wdir / "revtex4old.cls").read_text(encoding="utf-8")
    assert "\\ProvidesClass{revtex4old}" in body
    assert "\\LoadClassWithOptions{revtex4-2}" in body


def test_modern_revtex42_untouched(tmp_path: Path) -> None:
    """\\ProvidesClass{revtex4-2} 纵含同名机 → 名锚不中, 不动。"""
    wdir, texmf = proj_texmf(tmp_path)
    _42(texmf)
    (wdir / "revtex4-2.cls").write_text(_NEW_42, encoding="utf-8")
    ok, _ = _fn()(mk_ctx(wdir), ShadowEng(texmf), None, {})
    assert not ok
    assert (wdir / "revtex4-2.cls").is_file()


def test_modern_textcase_untouched(tmp_path: Path) -> None:
    """uclc 单锚 (现代 textcase.sty 同机) → 不动 —— 双锚必要性。"""
    wdir, texmf = proj_texmf(tmp_path)
    _42(texmf)
    (wdir / "textcase.cls").write_text(_MODERN_TEXTCASE, encoding="utf-8")
    ok, _ = _fn()(mk_ctx(wdir), ShadowEng(texmf), None, {})
    assert not ok


def test_idempotent_second_call(tmp_path: Path) -> None:
    """二轮直驱: delegate 无 uclc 锚 + 指纹行 → False 幂等。"""
    wdir, texmf = proj_texmf(tmp_path)
    _42(texmf)
    (wdir / "revtex4.cls").write_text(_STALE_REVTEX4, encoding="utf-8")
    ctx = mk_ctx(wdir)
    eng = ShadowEng(texmf)
    ok1, _ = _fn()(ctx, eng, None, {})
    assert ok1
    ok2, _ = _fn()(ctx, eng, None, {})
    assert not ok2


# ---------------------------------------------------------------- pass 2 树外遮蔽
def test_texmf_shadow_dropped_not_moved(tmp_path: Path) -> None:
    """~/texmf v4.0a 遮蔽 → 根 delegate 落盘, texmf 原件只读不动。"""
    wdir, texmf = proj_texmf(tmp_path)
    _42(texmf)
    # ShadowEng 直查 texmf/<fname> —— 放 texmf/revtex4.cls 让 probe 命中
    shallow = texmf / "revtex4.cls"
    shallow.write_text(_STALE_REVTEX4, encoding="utf-8")
    ok, note = _fn()(mk_ctx(wdir), ShadowEng(texmf), None, {})
    assert ok, note
    body = (wdir / "revtex4.cls").read_text(encoding="utf-8")
    assert body.startswith("% texlate-fixloop-injected:")
    assert "\\LoadClassWithOptions{revtex4-2}" in body
    # 树外件只读 —— mv 反遭 install_file 回投循环 (mnras-retire 裁定)
    assert shallow.read_text(encoding="utf-8") == _STALE_REVTEX4


def test_texmf_modern_no_delegate(tmp_path: Path) -> None:
    """probe 命中系统 revtex4-2/modern → 指纹不中, 不落 delegate。"""
    wdir, texmf = proj_texmf(tmp_path)
    (texmf / "revtex4.cls").write_text(_NEW_42, encoding="utf-8")
    _42(texmf)
    ok, _ = _fn()(mk_ctx(wdir), ShadowEng(texmf), None, {})
    assert not ok
    assert not (wdir / "revtex4.cls").exists()


def test_wdir_texmf_subtree_skipped(tmp_path: Path) -> None:
    """wdir/_texmf 引擎树内指纹件 → pass 1 跳过 (非稿自带), 根 delegate 遮蔽。"""
    wdir, texmf = proj_texmf(tmp_path)
    _42(texmf)
    inner = wdir / "_texmf" / "home" / "tex" / "latex" / "revtex4"
    inner.mkdir(parents=True)
    (inner / "revtex4.cls").write_text(_STALE_REVTEX4, encoding="utf-8")
    ok, note = _fn()(mk_ctx(wdir), ShadowEng(texmf), None, {})
    assert ok, note
    # _texmf 件不 mv (引擎树) —— 根 delegate 经 cwd 序遮蔽即可
    assert (inner / "revtex4.cls").is_file()
    assert not (inner / "revtex4.cls.fixloop-iso").exists()
    assert (
        (wdir / "revtex4.cls")
        .read_text(encoding="utf-8")
        .startswith("% texlate-fixloop-injected:")
    )


# ---------------------------------------------------------------- 递补闸
def test_replacement_missing_refuses(tmp_path: Path) -> None:
    """revtex4-2 probe/vendor 双空 → 拒动 (delegate 死路闸)。"""
    wdir, texmf = proj_texmf(tmp_path)
    (wdir / "revtex4.cls").write_text(_STALE_REVTEX4, encoding="utf-8")
    empty_vendor = tmp_path / "novendor"
    ok, _ = _fn()(mk_ctx(wdir), ShadowEng(texmf), None, {"dir": str(empty_vendor)})
    assert not ok
    assert (wdir / "revtex4.cls").is_file()  # 原样保留
    assert not (wdir / "revtex4.cls.fixloop-iso").exists()
