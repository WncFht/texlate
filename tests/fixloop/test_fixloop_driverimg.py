r"""drvstage 车道 (2026-09-20): ``driver_missing_image_stub`` 驱动期缺图占位规则。

failmine4 普查 4 格 (2501.01611/2502.00335/2504.06306/2505.07205): tex 趟净
(.xbb 旁件供 bbox / ``\special{psfile}`` 裸递 / nonstop 先错已修的残轮) 但
xdvipdfmx 嵌入期 ``Image inclusion failed. Could not find file: X`` ——
签名只走合并 stdout: ``_report_of`` 归一成 '!' 行 → ``other`` 类目;
``_round_cat`` driver_fatal 兜底臂走 payload。builtin 抽名落占位
(与 ``graphic_missing_placeholder`` 同 ``_stub_graphic_at`` 核)。
"""

from pathlib import Path
from types import SimpleNamespace

from texlate.compile.fixloop import actions, builtins, load_ruleset
from texlate.compile.fixloop.builtins import driver_missing_image_stub
from texlate.compile.fixloop.engine import LoopCtx, Rule, _report_of
from texlate.compile.logparse import ErrReport


class _Eng:
    """builtin_transform/condition 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


_FATAL_PNG = (
    "xdvipdfmx:fatal: Image inclusion failed. Could not find file: image/shufflenet.png"
)
_ERR_HEAD = f"! {_FATAL_PNG}\n\nNo output PDF file written."


def _ctx(
    tmp_path: Path,
    err_head: str = _ERR_HEAD,
    files: dict[str, str] | None = None,
    main_rel: str = "main.tex",
) -> LoopCtx:
    for rel, txt in (files or {}).items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(txt, encoding="utf-8")
    return LoopCtx(
        wdir=tmp_path,
        engine_name="xelatex",
        main_rel=main_rel,
        err_head=err_head,
    )


def _rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == "driver_missing_image_stub")


def _cond(
    tmp_path: Path, err_head: str = _ERR_HEAD, pay: str | None = None
) -> tuple[bool, str]:
    rule = _rule()
    return actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path, err_head), _Eng(), pay
    )


# ─────────────────────── _report_of 签名可见性 plumbing ───────────────────────


def _res(tmp_path: Path, log_text: str, stdout_tail: str) -> SimpleNamespace:
    log = tmp_path / "main.log"
    log.write_text(log_text, encoding="utf-8")
    return SimpleNamespace(
        log_path=log, log_text="", stdout_tail=stdout_tail, timed_out=False
    )


def test_report_of_surfaces_missing_image_fatal(tmp_path: Path) -> None:
    """干净 .log + stdout_tail ``Could not find file`` → '!' 行使签名可见。"""
    res = _res(
        tmp_path,
        "This is XeTeX\nOutput written on main.xdv\n",
        f"{_FATAL_PNG}\n\nNo output PDF file written.\n",
    )
    rep = _report_of(res, [])
    assert rep.n_bang == 1
    assert "Image inclusion failed" in (rep.first or "")
    cat, _pay = load_ruleset().taxonomy.classify(rep, timed_out=False)
    assert cat == "other"  # 签名无专属类目 → other 兜底，规则 when 面


def test_report_of_log_errors_win_over_fatal(tmp_path: Path) -> None:
    """.log 有 '!' 错 → stdout_tail 不查 (missing_graphic 臂先行，fatal 残轮再见)。"""
    res = _res(
        tmp_path,
        "! Unable to load picture or PDF file 'a.png'.\nl.5 \\includegraphics{a.png}\n",
        f"{_FATAL_PNG}\n",
    )
    rep = _report_of(res, [])
    assert rep.first == "! Unable to load picture or PDF file 'a.png'."


# ─────────────────────────── rule 注册 / 闸 ───────────────────────────


def test_driverimg_rule_registered() -> None:
    rule = _rule()
    assert rule.order == 18.6  # noqa: PLR2004 - schema 断言值
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "driver_missing_image_stub"
    assert (
        builtins.TRANSFORM_FNS["driver_missing_image_stub"] is driver_missing_image_stub
    )


def test_driverimg_when_matches_other_and_driver_fatal(tmp_path: Path) -> None:
    """other (归一 '!' 行主面) 与 driver_fatal (_round_cat 兜底臂) 双过 when。"""
    rule = _rule()
    ctx = _ctx(tmp_path)
    assert actions._when_ok(rule.when, "other", None, ctx)  # noqa: SLF001
    assert actions._when_ok(  # noqa: SLF001
        rule.when, "driver_fatal", _FATAL_PNG, ctx
    )
    assert not actions._when_ok(  # noqa: SLF001
        rule.when, "missing_graphic", "x.png", ctx
    )


def test_driverimg_cond_fires_on_err_head(tmp_path: Path) -> None:
    """other 面：归一 '!' fatal 行进 err_head → ctx_suggests 放行。"""
    ok, why = _cond(tmp_path)
    assert ok, why


def test_driverimg_cond_fires_on_payload(tmp_path: Path) -> None:
    """driver_fatal 面：err_head 空 + payload=原始 fatal 行 → payload_pattern 放行。"""
    ok, why = _cond(tmp_path, err_head="", pay=_FATAL_PNG)
    assert ok, why


def test_driverimg_cond_declines_unrelated_other(tmp_path: Path) -> None:
    """无关 other 签名 → 双闸拒。"""
    ok, _why = _cond(tmp_path, err_head="! LaTeX Error: Something else")
    assert not ok


# ─────────────────────────── builtin 行为 ───────────────────────────


def test_err_head_png_drops_binary_placeholder(tmp_path: Path) -> None:
    """err_head 抽 ``image/shufflenet.png`` → main_dir 下落 PNG 占位 + mkdir。"""
    ctx = _ctx(tmp_path)
    ok, note = driver_missing_image_stub(ctx, _Eng(), None, {})
    assert ok, note
    out = tmp_path / "image/shufflenet.png"
    assert out.is_file()
    assert out.read_bytes().startswith(b"\x89PNG")


def test_payload_eps_drops_text_placeholder(tmp_path: Path) -> None:
    """driver_fatal 面：payload=原始 fatal 行 (err_head 空) → EPS 占位。"""
    ctx = _ctx(tmp_path, err_head="")
    ok, note = driver_missing_image_stub(
        ctx,
        _Eng(),
        "xdvipdfmx:fatal: Image inclusion failed. Could not find file: vInfComp.eps",
        {},
    )
    assert ok, note
    out = tmp_path / "vInfComp.eps"
    assert out.read_text(encoding="utf-8").startswith("%!PS-Adobe")


def test_main_in_subdir_bases_at_main_dir(tmp_path: Path) -> None:
    """main 住子目录 → 占位落 main_dir (TeX cwd 解析位) 非 wdir 根。"""
    ctx = _ctx(
        tmp_path,
        err_head="! xdvipdfmx:fatal: Image inclusion failed. "
        "Could not find file: figs/a.png",
        files={"sub/main.tex": "\\documentclass{article}\n"},
        main_rel="sub/main.tex",
    )
    ok, note = driver_missing_image_stub(ctx, _Eng(), None, {})
    assert ok, note
    assert (tmp_path / "sub/figs/a.png").is_file()
    assert not (tmp_path / "figs/a.png").exists()


def test_second_fire_is_noop(tmp_path: Path) -> None:
    """幂等：占位已在盘 → resolved meanwhile decline, 内容不被覆写。"""
    ctx = _ctx(tmp_path)
    ok, _note = driver_missing_image_stub(ctx, _Eng(), None, {})
    assert ok
    out = tmp_path / "image/shufflenet.png"
    out.write_bytes(b"real png bytes")
    ok, note = driver_missing_image_stub(ctx, _Eng(), None, {})
    assert not ok
    assert "resolved meanwhile" in note
    assert out.read_bytes() == b"real png bytes"


def test_ci_variant_declines(tmp_path: Path) -> None:
    """盘存大小写变体 → rescue_check 让位 (占位不遮可救真图)。"""
    ctx = _ctx(
        tmp_path,
        files={"main.tex": "x\n", "shufflenet.png": "real"},
        err_head="! xdvipdfmx:fatal: Image inclusion failed. "
        "Could not find file: shufflenet.PNG",
    )
    ok, note = driver_missing_image_stub(ctx, _Eng(), None, {})
    assert not ok
    assert "ci-variant" in note
    assert not (tmp_path / "shufflenet.PNG").exists()


def test_non_graphic_ext_refused(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        err_head="! xdvipdfmx:fatal: Image inclusion failed. "
        "Could not find file: foo.sty",
    )
    ok, note = driver_missing_image_stub(ctx, _Eng(), None, {})
    assert not ok
    assert "not a known graphic ext" in note
    assert not (tmp_path / "foo.sty").exists()


def test_path_traversal_refused(tmp_path: Path) -> None:
    ctx = _ctx(
        tmp_path,
        err_head="! xdvipdfmx:fatal: Image inclusion failed. "
        "Could not find file: ../evil.png",
    )
    ok, note = driver_missing_image_stub(ctx, _Eng(), None, {})
    assert not ok
    assert "traversal" in note
    assert not (tmp_path.parent / "evil.png").exists()


def test_no_signature_refused(tmp_path: Path) -> None:
    ctx = _ctx(tmp_path, err_head="! LaTeX Error: unrelated")
    ok, note = driver_missing_image_stub(ctx, _Eng(), None, {})
    assert not ok
    assert "no driver missing-image name" in note


def test_payload_err_head_dedupes_same_name(tmp_path: Path) -> None:
    """同名同现 payload+err_head (双面签名) → 单件落盘不单。"""
    ctx = _ctx(tmp_path)
    ok, note = driver_missing_image_stub(ctx, _Eng(), _FATAL_PNG, {})
    assert ok, note
    assert "swept" not in note
    assert (tmp_path / "image/shufflenet.png").is_file()


def test_sweep_arm_covers_second_missing(tmp_path: Path) -> None:
    """多缺件格 (2501.01611 双缺面): err_head 只曝首件，源枚举臂补
    ``\\includegraphics`` 第二缺件 —— 单补即 ``{rid}:None`` 封派发会卡 stuck,
    sweep 一轮尽列双落占位。"""
    ctx = _ctx(
        tmp_path,
        files={
            "main.tex": "\\documentclass{article}\n\\begin{document}\n"
            "\\includegraphics{other/missing.png}\n\\end{document}\n"
        },
    )
    ok, note = driver_missing_image_stub(ctx, _Eng(), None, {})
    assert ok, note
    assert "swept" in note
    assert (tmp_path / "image/shufflenet.png").is_file()
    assert (tmp_path / "other/missing.png").is_file()


def test_apply_via_rule_other_path(tmp_path: Path) -> None:
    """钉规则动作直驱 (other 面 pay=None): 闸后 _apply 落占位。"""
    ok, note = actions._apply(  # noqa: SLF001
        _rule(), _ctx(tmp_path), _Eng(), None, ErrReport()
    )
    assert ok, note
    assert (tmp_path / "image/shufflenet.png").is_file()
