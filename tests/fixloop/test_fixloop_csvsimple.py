"""csvsimple 反向版本错位修复链单测 (稿自带过旧件 → 退役换系统/vendor 新件)。

实证背景 (corpus 2112.00045, stagerun-loop2 best_effort_pdf 残格):
e-print 捆绑 csvsimple-l3.sty v2.2.0 (2021), ``\\bool_const:Nn { 1 }``
裸数字字面量撞 expl3 收紧 → ``csvsimple-l3.sty:36: Missing number,
treated as zero`` → ``Missing \\begin{document}`` 级联。两既有机制均
够不到：``_provides_date`` 不读 ``\\ProvidesExplPackage{n}{d}{v}``
brace 日期面 (vendored_shadow_isolate 的 ld<sd 闸拿不到), 指纹闸又
拒覆外来件 (vendored_fetch 原位替换 decline)。修复面：run_tool mv
退役旧件 → 系统 2.7.0 递补; 系统缺件则 missing_file → vendored_fetch
递 vendor/files 钉版 (2.7.0)。
"""

from pathlib import Path

from _fixloopkit import ScriptedEngine, apply, classify, mk_ctx, rs, rule

from texlate.compile.fixloop import actions, fixloop
from texlate.compile.fixloop.builtins import TRANSFORM_FNS

_VENDOR_STY = (
    Path(actions.__file__).resolve().parents[1] / "vendor" / "files" / "csvsimple-l3.sty"
)
_RULE_ID = "csvsimple_l3_kernel_retire"

# 2112.00045 实证首错 (file-line-error 形态): expl3 \\bool_const:Nn{1} 不收
_ERR_LINE = (
    "/work/2112.00045/splice/csvsimple-l3.sty:36: Missing number, treated as zero."
)
_ERR_CTX = """<to be read again>
                   \\relax
l.36 ...onst:Nn \\c__csvsim_package_expl_bool { 1 }"""

# '!' 形态同款：rep.first 无文件名，ctx 的 l.N 源码回显泄签名 cs 名
_BANG_ERR = "! Missing number, treated as zero.\n" + _ERR_CTX

CLEAN_LOG = "This is XeTeX\nOutput written on main.pdf (1 page).\n"


# ---------------------------------------------------------------- taxonomy
def test_taxonomy_real_signature_is_syntax() -> None:
    """实证签名：file-line Missing number → syntax (pay=None)。"""
    cat, pay = classify(_ERR_LINE + "\n" + _ERR_CTX + "\n")
    assert cat == "syntax"
    assert pay is None


def test_taxonomy_bang_form_is_syntax() -> None:
    """'!' 形态同归 syntax —— 无 file-line 名时靠 ctx 签名 cs 判别。"""
    cat, _ = classify(_BANG_ERR + "\n")
    assert cat == "syntax"


# ---------------------------------------------------------------- 钉版面
def test_vendored_csvsimple_pinned_version() -> None:
    """vendor/files 钉版即 texmf-dist 2.7.0 真件 (版本戳 + 已修 bool 字面量)。"""
    text = _VENDOR_STY.read_text(encoding="utf-8")
    assert "\\ProvidesExplPackage{csvsimple-l3}{2024/09/27}{2.7.0}" in text
    # 修复点实证：裸 { 1 } 字面量已换 \\c_true_bool
    assert "\\bool_const:Nn \\c__csvsim_package_expl_bool { \\c_true_bool }" in text


# ---------------------------------------------------------------- 规则接线
def test_rule_wired_loop_phase() -> None:
    """规则挂 loop 相 order 11.8 → run_tool mv .fixloop-iso。"""
    r = rule(_RULE_ID)
    assert r.order == 11.8  # noqa: PLR2004 - schema 断言值
    cats = {c.get("category") for c in r.when["any"]}
    assert cats == {"syntax", "undefined_cs", "other"}
    assert r.condition["cache_dir_glob"] == "csvsimple-l3.sty"
    assert "csvsimple-l3" in r.condition["ctx_suggests"]
    assert r.action["kind"] == "run_tool"
    assert r.action["params"]["argv"] == [
        "mv",
        "csvsimple-l3.sty",
        "csvsimple-l3.sty.fixloop-iso",
    ]


def test_rule_order_before_legacy_shim() -> None:
    """order 排序自洽：pkg_version_skew_vendored(11.7) < 本规则 < legacy_pkg_shim(12)。"""
    orders = {r.id: r.order for r in rs().phase("loop")}
    assert orders["pkg_version_skew_vendored"] < orders[_RULE_ID]
    assert orders[_RULE_ID] < orders["legacy_pkg_shim"]


# ---------------------------------------------------------------- condition 闸
def test_cond_skip_when_file_absent(tmp_path: Path) -> None:
    """wdir 无 csvsimple-l3.sty → cache_dir_glob 闸拒 (不动别的语法错)。"""
    ctx = mk_ctx(tmp_path, main_rel=None, err_head=_ERR_LINE + "\n" + _ERR_CTX)
    ok, why = actions._cond_ok(  # noqa: SLF001 - 闸行为直驱
        rule(_RULE_ID).condition, rule(_RULE_ID), ctx, None, None
    )
    assert not ok
    assert "csvsimple-l3.sty" in why


def test_cond_skip_when_error_elsewhere(tmp_path: Path) -> None:
    """错误不点名 csvsimple (别包 syntax) → ctx_suggests 闸拒。"""
    (tmp_path / "csvsimple-l3.sty").write_text("% stub\n", encoding="utf-8")
    ctx = mk_ctx(
        tmp_path,
        main_rel=None,
        err_head="./main.tex:10: Missing $ inserted.\nl.10 x_i\n",
    )
    ok, _ = actions._cond_ok(  # noqa: SLF001
        rule(_RULE_ID).condition, rule(_RULE_ID), ctx, None, None
    )
    assert not ok


def test_cond_pass_bang_form(tmp_path: Path) -> None:
    """'!' 形态：文件名缺席但签名 cs `\\c__csvsim_package_expl_bool` 在 ctx。"""
    (tmp_path / "csvsimple-l3.sty").write_text("% stub\n", encoding="utf-8")
    ctx = mk_ctx(tmp_path, main_rel=None, err_head=_BANG_ERR)
    ok, why = actions._cond_ok(  # noqa: SLF001
        rule(_RULE_ID).condition, rule(_RULE_ID), ctx, None, None
    )
    assert ok, why


# ---------------------------------------------------------------- 动作直驱
def test_apply_renames_vendored_copy(tmp_path: Path) -> None:
    """_apply 真跑 mv: 稿自带件 → .fixloop-iso (原内容保留，非删)。"""
    old = "\\ProvidesExplPackage{csvsimple-l3}{2021/09/09}{2.2.0}\n"
    (tmp_path / "csvsimple-l3.sty").write_text(old, encoding="utf-8")
    ctx = mk_ctx(tmp_path, main_rel=None)
    ok, note = apply(_RULE_ID, ctx, None)
    assert ok, note
    assert not (tmp_path / "csvsimple-l3.sty").exists()
    iso = tmp_path / "csvsimple-l3.sty.fixloop-iso"
    assert iso.read_text(encoding="utf-8") == old


# ---------------------------------------------------------------- vendor 递补
def test_vendored_fetch_delivers_pinned(tmp_path: Path) -> None:
    """退役后系统缺件 → missing_file → vendored_fetch 递 2.7.0 钉版。"""
    ctx = mk_ctx(tmp_path, main_rel=None)
    ok, note = TRANSFORM_FNS["vendored_fetch"](ctx, None, "csvsimple-l3.sty", {})
    assert ok, note
    text = (tmp_path / "csvsimple-l3.sty").read_text(encoding="utf-8")
    assert text.startswith("% texlate-fixloop-injected:")
    assert "{2024/09/27}{2.7.0}" in text


def test_vendored_fetch_foreign_not_overwritten(tmp_path: Path) -> None:
    """稿自带旧件在场 (未退役) → 指纹闸拒覆 —— 退役规则必须先行。"""
    (tmp_path / "csvsimple-l3.sty").write_text("% old v2.2.0\n", encoding="utf-8")
    ctx = mk_ctx(tmp_path, main_rel=None)
    ok, note = TRANSFORM_FNS["vendored_fetch"](ctx, None, "csvsimple-l3.sty", {})
    assert not ok
    assert "foreign" in note
    assert (tmp_path / "csvsimple-l3.sty").read_text() == "% old v2.2.0\n"


# ---------------------------------------------------------------- e2e
def _proj(tmp_path: Path) -> Path:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{csvsimple-l3}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "csvsimple-l3.sty").write_text(
        "\\ProvidesExplPackage{csvsimple-l3}{2021/09/09}{2.2.0}\n"
        "\\bool_const:Nn \\c__csvsim_package_expl_bool { 1 }\n",
        encoding="utf-8",
    )
    return tmp_path


def _mv_runner(
    argv: list[str], timeout: int, wdir: Path
) -> tuple[int, str, float, bool]:
    """真跑 mv 的 runner (runner 签名：argv, timeout, wdir → rc,out,sec,to)。"""
    del timeout
    if argv[0] == "mv":
        (Path(wdir) / argv[1]).rename(Path(wdir) / argv[2])
        return 0, "", 0.0, False
    return 1, "unsupported argv", 0.0, False


def test_e2e_retire_then_system_resolves(tmp_path: Path) -> None:
    """整链：syntax 签名 → mv 退役 → 下轮系统件载入 → clean。"""
    eng = ScriptedEngine(
        [
            {"log": _ERR_LINE + "\n" + _ERR_CTX + "\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        available={"csvsimple-l3.sty"},
    )
    cell = fixloop(_proj(tmp_path), eng, runner=_mv_runner)
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == _RULE_ID for a in cell["actions"])
    assert not (tmp_path / "csvsimple-l3.sty").exists()
    assert (tmp_path / "csvsimple-l3.sty.fixloop-iso").exists()


def test_e2e_retire_then_vendored_fallback(tmp_path: Path) -> None:
    """系统缺件：退役 → missing_file → vendored_fetch 递 2.7.0 钉版 → clean。"""
    eng = ScriptedEngine(
        [
            {"log": _ERR_LINE + "\n" + _ERR_CTX + "\n"},
            {
                "log": "File `csvsimple-l3.sty' not found.\n"
                "Enter file name:\n"
                "Emergency stop.\n"
            },
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(_proj(tmp_path), eng, runner=_mv_runner)
    assert cell["verdict"] == "clean"
    rules_fired = [a["rule"] for a in cell["actions"]]
    assert _RULE_ID in rules_fired
    assert "vendored_fetch" in rules_fired
    dropped = (tmp_path / "csvsimple-l3.sty").read_text(encoding="utf-8")
    assert "{2024/09/27}{2.7.0}" in dropped


def test_e2e_no_fire_on_other_syntax(tmp_path: Path) -> None:
    """非 csvsimple 签名：别包 syntax 错 → 本规则不动 wdir 件。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\nx_i\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "csvsimple-l3.sty").write_text("% old\n", encoding="utf-8")
    eng = ScriptedEngine(
        [
            {"log": "./main.tex:3: Missing $ inserted.\nl.3 x_i\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(tmp_path, eng, runner=_mv_runner)
    assert not any(a["rule"] == _RULE_ID for a in cell["actions"])
    assert (tmp_path / "csvsimple-l3.sty").read_text() == "% old\n"
