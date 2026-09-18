r"""pdfsanitize lane (2026-09-19): ``pdf_asset_sanitize`` 内嵌 pdf 重序列化规则。

xlinkobj lane 5 格普查 (1404.5668/1206.0148/1907.00277/2403.05523/2412.19437):
工程船货 .pdf 对象结构残缺 → xdvipdfmx ``pdf:image`` import 回 NULL →
``xdvipdfmx:fatal: pdf_link_obj(): passed invalid object`` → xelatex SIGPIPE。
签名只走 stderr→stdout_tail (.log 干净) —— ``_report_of`` 把 ``\w+:fatal:``
行归一成 '!' 行使签名对 ctx_suggests 可见, 轮内归 ``other`` 类。修复 =
全量内嵌 .pdf ``gs -sDEVICE=pdfwrite`` 重序列化 (内容不动只改对象布局,
原件留 ``.fixloop-rd`` 备份兼幂等标记)。
"""

import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest

from texlate.compile.fixloop import actions, builtins, load_ruleset
from texlate.compile.fixloop.builtins import pdf_asset_sanitize
from texlate.compile.fixloop.engine import LoopCtx, Rule, _report_of
from texlate.compile.fixloop.logparse import ErrReport


class _Eng:
    """builtin_transform/condition 路径的最小引擎替身 (不触 probe/install)。"""

    name = "xelatex"

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


_FATAL = "xdvipdfmx:fatal: pdf_link_obj(): passed invalid object."
_ERR_HEAD = f"! {_FATAL}\n\nNo output PDF file written."


def _ctx(tmp_path: Path, err_head: str = _ERR_HEAD, runner: object = None) -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path,
        engine_name="xelatex",
        main_rel="main.tex",
        runner=runner,
        err_head=err_head,
    )


def _rule() -> Rule:
    return next(r for r in load_ruleset().rules if r.id == "pdf_asset_sanitize")


def _apply(tmp_path: Path, runner: object = None) -> tuple[bool, str]:
    return actions._apply(  # noqa: SLF001 - 钉规则动作直驱
        _rule(), _ctx(tmp_path, runner=runner), _Eng(), None, ErrReport()
    )


def _cond(tmp_path: Path, err_head: str = _ERR_HEAD) -> tuple[bool, str]:
    rule = _rule()
    return actions._cond_ok(  # noqa: SLF001
        rule.condition, rule, _ctx(tmp_path, err_head), _Eng(), None
    )


def _which_gs(name: str) -> str | None:
    return "/usr/bin/gs" if name == "gs" else None


def _which_none(_name: str) -> None:
    return None


def _gs_ok(argv: list[str], _timeout: int, _wdir: Path) -> tuple:
    """假 gs pdfwrite: ``-o`` 目标写重序列化伪 pdf, rc=0。"""
    Path(argv[argv.index("-o") + 1]).write_bytes(b"%PDF-1.7 reserialized\n%%EOF\n")
    return 0, "", 0.05, False


def _gs_fail(_argv: list[str], _timeout: int, _wdir: Path) -> tuple:
    return 1, "gs died", 0.05, False


# ─────────────────────── _report_of 签名可见性 plumbing ───────────────────────


def _res(tmp_path: Path, log_text: str, stdout_tail: str) -> SimpleNamespace:
    log = tmp_path / "main.log"
    log.write_text(log_text, encoding="utf-8")
    return SimpleNamespace(
        log_path=log, log_text="", stdout_tail=stdout_tail, timed_out=False
    )


def test_report_of_surfaces_driver_fatal(tmp_path: Path) -> None:
    """干净 .log + stdout_tail ``*:fatal:`` → 归一成 '!' 行使签名可见。"""
    res = _res(
        tmp_path,
        "This is XeTeX\nOutput written on main.xdv\n",
        f'xdvipdfmx:warning: Didn\'t find "endobj".\n{_FATAL}\n\nNo output PDF file written.\n',
    )
    rep = _report_of(res, [])
    assert rep.n_bang == 1
    assert "pdf_link_obj" in (rep.first or "")
    cat, _pay = load_ruleset().taxonomy.classify(rep, timed_out=False)
    assert cat == "other"  # 签名无专属类目 → other 兜底, 规则 when 面


def test_report_of_plain_stdout_keeps_log_report(tmp_path: Path) -> None:
    """stdout_tail 无 error/fatal 行 → .log 报告保留 (归一不无事生非)。"""
    res = _res(
        tmp_path,
        "This is XeTeX\nOutput written on main.pdf (1 page).\n",
        "some benign console noise\n",
    )
    rep = _report_of(res, [])
    assert rep.first is None
    assert rep.raw.startswith("This is XeTeX")


def test_report_of_log_errors_win_over_fatal(tmp_path: Path) -> None:
    """.log 有 '!' 错 → 不查 stdout_tail (先修 TeX 错, fatal 下轮再见)。"""
    res = _res(
        tmp_path,
        "! Undefined control sequence.\nl.5 \\foo\n",
        f"{_FATAL}\n",
    )
    rep = _report_of(res, [])
    assert rep.first == "! Undefined control sequence."


def test_report_of_empty_log_falls_back_anyway(tmp_path: Path) -> None:
    """.log 空 → stdout_tail 兜底照旧 (rep.raw==\"\" 臂不依赖 fatal)。"""
    res = _res(tmp_path, "", "plain output, no errors\n")
    rep = _report_of(res, [])
    assert rep.raw == "plain output, no errors\n"


# ─────────────────────────── rule 注册 / 闸 ───────────────────────────


def test_pdfsanitize_rule_registered() -> None:
    rule = _rule()
    assert rule.order == 18.5  # noqa: PLR2004 - schema 断言值
    assert rule.action["kind"] == "builtin_transform"
    assert rule.action["function"] == "pdf_asset_sanitize"
    assert builtins.TRANSFORM_FNS["pdf_asset_sanitize"] is pdf_asset_sanitize


def test_pdfsanitize_cond_fires_on_signature(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """pdf_link_obj invalid-object 签名 err_head → 闸放行。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    ok, why = _cond(tmp_path)
    assert ok, why


def test_pdfsanitize_cond_declines_unrelated_other(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无关 other 类目错 → ctx_suggests 拒。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    ok, _why = _cond(tmp_path, "LaTeX Error: Something else entirely")
    assert not ok


def test_pdfsanitize_cond_declines_no_gs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gs 缺席 → tool_available 拒。"""
    monkeypatch.setattr(shutil, "which", _which_none)
    ok, why = _cond(tmp_path)
    assert not ok
    assert "gs" in why


# ─────────────────────────── builtin 行为 ───────────────────────────


def test_pdfsanitize_rewrites_pdf_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """内嵌 .pdf 全量重写: 内容替换 + 原件留 .fixloop-rd 备份。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    (tmp_path / "img").mkdir()
    (tmp_path / "img/bad.pdf").write_bytes(b"%PDF-1.4 malformed-no-endobj")
    (tmp_path / "fig2.pdf").write_bytes(b"%PDF-1.4 token-per-line")
    (tmp_path / "main.tex").write_text("\\includegraphics{img/bad.pdf}\n")
    ok, note = _apply(tmp_path, runner=_gs_ok)
    assert ok, note
    assert "2/2" in note
    assert (tmp_path / "img/bad.pdf").read_bytes() == b"%PDF-1.7 reserialized\n%%EOF\n"
    # 原件备份在 marker, 兼「已 sanitize」幂等标记
    assert (tmp_path / "img/bad.pdf.fixloop-rd").read_bytes() == (
        b"%PDF-1.4 malformed-no-endobj"
    )
    assert (tmp_path / "fig2.pdf.fixloop-rd").is_file()


def test_pdfsanitize_skips_main_and_artifacts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """主输出 pdf / 隐藏快照 / _texmf 封装树非内嵌图件 —— 不动。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    (tmp_path / "main.pdf").write_bytes(b"%PDF main output")
    (tmp_path / ".fixloop-entry.pdf").write_bytes(b"%PDF floor snap")
    (tmp_path / "_texmf/pkg").mkdir(parents=True)
    (tmp_path / "_texmf/pkg/doc.pdf").write_bytes(b"%PDF vendored")
    (tmp_path / "fig.pdf").write_bytes(b"%PDF figure")
    ok, note = _apply(tmp_path, runner=_gs_ok)
    assert ok, note
    assert "1/1" in note
    assert (tmp_path / "main.pdf").read_bytes() == b"%PDF main output"
    assert (tmp_path / ".fixloop-entry.pdf").read_bytes() == b"%PDF floor snap"
    assert (tmp_path / "_texmf/pkg/doc.pdf").read_bytes() == b"%PDF vendored"


def test_pdfsanitize_idempotent_marked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """marker 在场 = 已 sanitize → 跳过; 全 skipped → False 让位。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    (tmp_path / "fig.pdf").write_bytes(b"%PDF figure")
    (tmp_path / "fig.pdf.fixloop-rd").write_bytes(b"%PDF original")
    ok, note = _apply(tmp_path, runner=_gs_ok)
    assert not ok
    assert "already sanitized" in note
    assert (tmp_path / "fig.pdf").read_bytes() == b"%PDF figure"


def test_pdfsanitize_no_pdf_assets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """工程零内嵌 .pdf → False (签名命中但无可修面)。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    (tmp_path / "main.tex").write_text("\\includegraphics{img.png}\n")
    ok, note = _apply(tmp_path, runner=_gs_ok)
    assert not ok
    assert "no pdf assets" in note


def test_pdfsanitize_gs_failure_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gs 全败 → False 不谎报, 原件不动 (失败残留清掉)。"""
    monkeypatch.setattr(shutil, "which", _which_gs)
    src = tmp_path / "fig.pdf"
    src.write_bytes(b"%PDF figure")
    ok, note = _apply(tmp_path, runner=_gs_fail)
    assert not ok
    assert "0/1 sanitized" in note
    assert src.read_bytes() == b"%PDF figure"
    assert not (tmp_path / "fig.pdf.fixloop-tmp").exists()


def test_pdfsanitize_no_gs_builtin_false(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """builtin 直调 (绕闸): gs 缺席 → False (condition 之外再保险)。"""
    monkeypatch.setattr(shutil, "which", _which_none)
    (tmp_path / "fig.pdf").write_bytes(b"%PDF figure")
    ok, note = pdf_asset_sanitize(_ctx(tmp_path), _Eng(), None, {})
    assert not ok
    assert "no gs" in note


@pytest.mark.skipif(shutil.which("gs") is None, reason="gs not on PATH")
def test_pdfsanitize_real_gs_repairs_malformed(tmp_path: Path) -> None:
    """真 gs 端到端: 剥 endobj 的残缺 pdf → 重序列化非空产出 + 原件备份。"""
    good = (
        b"%PDF-1.4\n"
        b"1 0 obj\n<</Type/Catalog/Pages 2 0 R>>\nendobj\n"
        b"2 0 obj\n<</Type/Pages/Kids[3 0 R]/Count 1>>\nendobj\n"
        b"3 0 obj\n<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>\nendobj\n"
        b"trailer\n<</Root 1 0 R>>\n%%EOF\n"
    )
    i = good.rfind(b"endobj\n")
    src = tmp_path / "fig.pdf"
    src.write_bytes(good[:i] + good[i + len(b"endobj\n") :])
    ok, note = pdf_asset_sanitize(_ctx(tmp_path), _Eng(), None, {})
    assert ok, note
    out = src.read_bytes()
    assert out.startswith(b"%PDF-")
    assert len(out) > 200  # noqa: PLR2004 - 重序列化产物量断言
    assert (tmp_path / "fig.pdf.fixloop-rd").is_file()


def test_pdfsanitize_ruleset_loads() -> None:
    rs = load_ruleset()
    assert len(rs.rules) >= 114  # noqa: PLR2004 - 库规模断言
