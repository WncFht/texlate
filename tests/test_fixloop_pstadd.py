"""pstricks-add 成对退役修复链单测 (稿自带过旧 .tex/.sty 对 → 退役换系统/vendor 新件)。

实证背景 (corpus 0707.4206, stagerun flipcheck3 best_effort 残格):
e-print 捆绑 pstricks-add.tex v2.32 (2005/01/16) + pstricks-add.sty 对,
``\\usepackage{pst-all}`` → texlive pst-all.sty ``\\RequirePackage{pstricks-add}``
走 kpathsea cwd 序中稿自带对 → 12 错同根 (dx/dy 键自 pst-node v1.45 移除、
``\\define@key[psset]{}{trueAngle}`` 空族 vs ``\\define@boolkey``、
``\\psset@@tickstyle``/``\\psk@tickstyle`` 自现代核消失)。
``find_vendored_shadows`` 要系统 probe 证 ``ld<sd`` —— 本机 texlive 无
pstricks-add → ``sd=None`` 盲区 (csvsimple_l3_kernel_retire 同型)。
修复面: sh 循环 mv 成对 ``.fixloop-iso`` → 系统件或 missing_file →
vendored_fetch 递 vendor/files v3.94 对 (指纹件跳过不自拆, 否则
v3.94 ``:742 \\colorlet`` 错会退役→重投→死循环)。
"""

from pathlib import Path

from _fixloopkit import classify, rs, rule
from test_fixloop_loop import MockEngine

from texlate.compile.fixloop import actions, fixloop
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.logparse import ErrReport

_VENDOR_DIR = (
    Path(__file__).resolve().parent.parent / "src/texlate/compile/fixloop/vendor/files"
)
_RULE_ID = "pstricks_add_pair_retire"

# 0707.4206 flipcheck3 实证首错簇 (file-line-error 形态): 签名同名不同格
_ERR_UNDEF = "/work/0707.4206/splice/pstricks-add.tex:1544: Undefined control sequence."
_ERR_UNDEF_CTX = """\\ps@next ->\\psset@@tickstyle

l.1544 \\psset{tickstyle=full}"""
_ERR_XKV = (
    "/work/0707.4206/splice/pstricks-add.tex:51: Package xkeyval Error: `dx' "
    "undefined in families `,pstricks,pst-tools,pst-node,pstricks-add'."
)
_ERR_MISSINGNUM = (
    "/work/0707.4206/splice/pstricks-add.tex:1544: Missing number, treated as zero."
)

# '!' 形态同款: rep.first 无文件名, ctx 展开栈回显泄签名 cs
_BANG_ERR = "! Undefined control sequence.\n" + _ERR_UNDEF_CTX

CLEAN_LOG = "This is XeTeX\nOutput written on main.pdf (1 page).\n"


# ---------------------------------------------------------------- taxonomy
def test_taxonomy_undef_signature() -> None:
    """实证签名: file-line Undefined cs → undefined_cs。"""
    cat, _ = classify(_ERR_UNDEF + "\n" + _ERR_UNDEF_CTX + "\n")
    assert cat == "undefined_cs"


def test_taxonomy_missing_number_is_syntax() -> None:
    """Missing number → syntax (tickstyle 内件消失的姊妹错)。"""
    cat, _ = classify(_ERR_MISSINGNUM + "\n")
    assert cat == "syntax"


def test_taxonomy_xkeyval_pin() -> None:
    """Package xkeyval Error → taxrow 归 key_unknown (dx/dy 键移除签名)。"""
    cat, _ = classify(_ERR_XKV + "\n")
    assert cat == "key_unknown"


# ---------------------------------------------------------------- 钉版面
def test_vendored_pstadd_pinned_pair() -> None:
    """vendor/files 成对在场: .tex v3.94 (2023) + .sty v0.17 (2021) wrapper。"""
    tex = (_VENDOR_DIR / "pstricks-add.tex").read_text(encoding="utf-8")
    sty = (_VENDOR_DIR / "pstricks-add.sty").read_text(encoding="utf-8")
    assert "\\def\\fileversion{3.94}" in tex
    assert "\\ProvidesPackage{pstricks-add}[2021/09/10" in sty


# ---------------------------------------------------------------- 规则接线
def test_rule_wired_loop_phase() -> None:
    """规则挂 loop 相 order 11.9 → run_tool sh -c 成对 mv .fixloop-iso。"""
    r = rule(_RULE_ID)
    assert r.order == 11.9  # noqa: PLR2004 - schema 断言值
    cats = {c.get("category") for c in r.when["any"]}
    assert cats == {"syntax", "undefined_cs", "other", "key_unknown"}
    assert r.condition["cache_dir_glob"] == "pstricks-add.tex"
    assert "pstricks-add" in r.condition["ctx_suggests"]
    assert r.action["kind"] == "run_tool"
    argv = r.action["params"]["argv"]
    assert argv[:2] == ["sh", "-c"]
    assert "pstricks-add.sty" in argv[2]
    assert "pstricks-add.tex" in argv[2]
    assert "texlate-fixloop-injected" in argv[2]  # 指纹闸: 不退役本引擎注入件


def test_rule_order_before_legacy_shim() -> None:
    """order 排序自洽: csvsimple_l3_kernel_retire(11.8) < 本规则 < legacy_pkg_shim(12)。"""
    orders = {r.id: r.order for r in rs().phase("loop")}
    assert orders["csvsimple_l3_kernel_retire"] < orders[_RULE_ID]
    assert orders[_RULE_ID] < orders["legacy_pkg_shim"]


# ---------------------------------------------------------------- condition 闸
def test_cond_skip_when_file_absent(tmp_path: Path) -> None:
    """wdir 无 pstricks-add.tex → cache_dir_glob 闸拒 (不动别格错)。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _ERR_UNDEF + "\n" + _ERR_UNDEF_CTX
    ok, why = actions._cond_ok(  # noqa: SLF001 - 闸行为直驱
        rule(_RULE_ID).condition, rule(_RULE_ID), ctx, None, None
    )
    assert not ok
    assert "pstricks-add.tex" in why


def test_cond_skip_when_error_elsewhere(tmp_path: Path) -> None:
    """错误不点名 pstricks-add (别包 undefined_cs) → ctx_suggests 闸拒。"""
    (tmp_path / "pstricks-add.tex").write_text("% stub\n", encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = "./main.tex:10: Undefined control sequence.\nl.10 \\foo\n"
    ok, _ = actions._cond_ok(rule(_RULE_ID).condition, rule(_RULE_ID), ctx, None, None)  # noqa: SLF001
    assert not ok


def test_cond_pass_bang_form(tmp_path: Path) -> None:
    """'!' 形态: 文件名缺席但签名 cs `\\psset@@tickstyle` 在 ctx 展开栈。"""
    (tmp_path / "pstricks-add.tex").write_text("% stub\n", encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ctx.err_head = _BANG_ERR
    ok, why = actions._cond_ok(  # noqa: SLF001 - 闸行为直驱
        rule(_RULE_ID).condition, rule(_RULE_ID), ctx, None, None
    )
    assert ok, why


# ---------------------------------------------------------------- 动作直驱 (真 sh)
def test_apply_retires_both_files(tmp_path: Path) -> None:
    """_apply 真跑 sh: 稿自带对 → 双双 .fixloop-iso (原内容保留, 非删)。"""
    old_tex = "% pstricks-add.tex v2.32 2005/01/16\n"
    old_sty = "% pstricks-add.sty v0.07 2004\n"
    (tmp_path / "pstricks-add.tex").write_text(old_tex, encoding="utf-8")
    (tmp_path / "pstricks-add.sty").write_text(old_sty, encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(rule(_RULE_ID), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert not (tmp_path / "pstricks-add.tex").exists()
    assert not (tmp_path / "pstricks-add.sty").exists()
    assert (tmp_path / "pstricks-add.tex.fixloop-iso").read_text() == old_tex
    assert (tmp_path / "pstricks-add.sty.fixloop-iso").read_text() == old_sty


def test_apply_retires_tex_only_when_sty_absent(tmp_path: Path) -> None:
    """单件残局: 只有 .tex 在场 → 只退它, 脚本不炸。"""
    (tmp_path / "pstricks-add.tex").write_text("% old\n", encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(rule(_RULE_ID), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert not (tmp_path / "pstricks-add.tex").exists()
    assert (tmp_path / "pstricks-add.tex.fixloop-iso").exists()


def test_apply_skips_fingerprinted_injection(tmp_path: Path) -> None:
    """本引擎注入件 (texlate-fixloop-injected 指纹) 不退役 —— 防退役→重投死循环。"""
    inj = "% texlate-fixloop-injected: 0123456789ab\n% v3.94\n"
    (tmp_path / "pstricks-add.tex").write_text(inj, encoding="utf-8")
    (tmp_path / "pstricks-add.sty").write_text("% bundled old sty\n", encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = actions._apply(rule(_RULE_ID), ctx, None, None, ErrReport())  # noqa: SLF001
    assert ok, note
    assert (tmp_path / "pstricks-add.tex").read_text(encoding="utf-8") == inj
    assert (tmp_path / "pstricks-add.sty.fixloop-iso").exists()


# ---------------------------------------------------------------- vendor 递补
def test_vendored_fetch_delivers_pinned_tex(tmp_path: Path) -> None:
    """退役后系统缺件 → missing_file → vendored_fetch 递 v3.94 钉版。"""
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = TRANSFORM_FNS["vendored_fetch"](ctx, None, "pstricks-add.tex", {})
    assert ok, note
    text = (tmp_path / "pstricks-add.tex").read_text(encoding="utf-8")
    assert text.startswith("% texlate-fixloop-injected:")
    assert "\\def\\fileversion{3.94}" in text


def test_vendored_fetch_foreign_not_overwritten(tmp_path: Path) -> None:
    """稿自带旧件在场 (未退役) → 指纹闸拒覆 —— 退役规则必须先行。"""
    (tmp_path / "pstricks-add.tex").write_text("% old v2.32\n", encoding="utf-8")
    ctx = LoopCtx(wdir=tmp_path, engine_name="xelatex")
    ok, note = TRANSFORM_FNS["vendored_fetch"](ctx, None, "pstricks-add.tex", {})
    assert not ok
    assert "foreign" in note
    assert (tmp_path / "pstricks-add.tex").read_text() == "% old v2.32\n"


# ---------------------------------------------------------------- e2e
def _proj(tmp_path: Path) -> Path:
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\usepackage{pst-all}\n"
        "\\begin{document}\nx\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "pstricks-add.tex").write_text(
        "%% $Id: pstricks-add.tex 100 2005-01-16 herbert $\n"
        "\\def\\fileversion{2.32}\n\\def\\filedate{2005/01/16}\n",
        encoding="utf-8",
    )
    (tmp_path / "pstricks-add.sty").write_text(
        "\\ProvidesPackage{pstricks-add}[2004/07/18 v. 0.07 package wrapper]\n"
        "\\input{pstricks-add.tex}\n",
        encoding="utf-8",
    )
    return tmp_path


def _sh_runner(
    argv: list[str], timeout: int, wdir: Path
) -> tuple[int, str, float, bool]:
    """真跑 sh -c 的 runner (argv, timeout, wdir → rc,out,sec,to)。

    不仿真脚本语义 —— subprocess 原样执行, 指纹闸/`[ -f ]` 判空都走真件。
    """
    import subprocess  # noqa: PLC0415 - 测试替身局部用

    p = subprocess.run(  # noqa: S603 - argv 列表无 shell 拼接; sh -c 是规则自身的原语
        argv,
        cwd=wdir,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return p.returncode, (p.stdout or "") + (p.stderr or ""), 0.0, False


def test_e2e_retire_then_system_resolves(tmp_path: Path) -> None:
    """整链: undefined_cs 签名 → 成对 mv 退役 → 下轮系统件载入 → clean。"""
    eng = MockEngine(
        [
            {"log": _ERR_UNDEF + "\n" + _ERR_UNDEF_CTX + "\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        available={"pstricks-add.sty", "pstricks-add.tex"},
    )
    cell = fixloop(_proj(tmp_path), eng, runner=_sh_runner)
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == _RULE_ID for a in cell["actions"])
    assert not (tmp_path / "pstricks-add.tex").exists()
    assert not (tmp_path / "pstricks-add.sty").exists()
    assert (tmp_path / "pstricks-add.tex.fixloop-iso").exists()
    assert (tmp_path / "pstricks-add.sty.fixloop-iso").exists()


def test_e2e_retire_then_vendored_fallback(tmp_path: Path) -> None:
    """系统缺件: 退役 → missing_file → vendored_fetch 递 v3.94 对 → clean。"""
    eng = MockEngine(
        [
            {"log": _ERR_UNDEF + "\n" + _ERR_UNDEF_CTX + "\n"},
            {
                "log": "File `pstricks-add.sty' not found.\n"
                "Enter file name:\n"
                "Emergency stop.\n"
            },
            {
                "log": "! I can't find file `pstricks-add.tex'.\n"
                "l.5 \\input{pstricks-add.tex}\n"
                "Emergency stop.\n"
            },
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(_proj(tmp_path), eng, runner=_sh_runner)
    assert cell["verdict"] == "clean"
    rules_fired = [a["rule"] for a in cell["actions"]]
    assert _RULE_ID in rules_fired
    assert "vendored_fetch" in rules_fired
    dropped = (tmp_path / "pstricks-add.tex").read_text(encoding="utf-8")
    assert "\\def\\fileversion{3.94}" in dropped
    dropped_sty = (tmp_path / "pstricks-add.sty").read_text(encoding="utf-8")
    assert "2021/09/10" in dropped_sty


def test_e2e_no_fire_on_other_error(tmp_path: Path) -> None:
    """非 pstricks-add 签名: 别包 undefined_cs → 本规则不动 wdir 件。"""
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n\\foo\n\\end{document}\n",
        encoding="utf-8",
    )
    (tmp_path / "pstricks-add.tex").write_text("% old\n", encoding="utf-8")
    (tmp_path / "pstricks-add.sty").write_text("% old\n", encoding="utf-8")
    eng = MockEngine(
        [
            {"log": "./main.tex:3: Undefined control sequence.\nl.3 \\foo\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(tmp_path, eng, runner=_sh_runner)
    assert not any(a["rule"] == _RULE_ID for a in cell["actions"])
    assert (tmp_path / "pstricks-add.tex").read_text() == "% old\n"
    assert (tmp_path / "pstricks-add.sty").read_text() == "% old\n"


def test_e2e_injected_not_retired_breaks_loop(tmp_path: Path) -> None:
    """vendor v3.94 注入后再报同名错: 指纹闸保件不退役 —— 无退役→重投环。"""
    eng = MockEngine(
        [
            {"log": _ERR_UNDEF + "\n" + _ERR_UNDEF_CTX + "\n"},
            {
                "log": "File `pstricks-add.sty' not found.\n"
                "Enter file name:\n"
                "Emergency stop.\n"
            },
            {
                "log": "! I can't find file `pstricks-add.tex'.\n"
                "l.5 \\input{pstricks-add.tex}\n"
                "Emergency stop.\n"
            },
            # v3.94 已注入却仍报错 (pstcol 未修的 :742 \colorlet 场景):
            # 签名变 → payload 变 → 规则再评估; 脚本指纹闸必须跳过注入件
            {
                "log": "/work/x/splice/pstricks-add.tex:742: Undefined control sequence.\n"
                "\\psset@pstricks-add@startColor ->\\colorlet\n\n"
                "l.742 \\psset{linecolor=blue}\n"
            },
            {"log": CLEAN_LOG, "pdf": True},
        ]
    )
    cell = fixloop(_proj(tmp_path), eng, runner=_sh_runner)
    assert cell["verdict"] == "clean"
    body = (tmp_path / "pstricks-add.tex").read_text(encoding="utf-8")
    assert body.startswith("% texlate-fixloop-injected:")  # 注入件原样在盘
    assert "\\def\\fileversion{3.94}" in body
