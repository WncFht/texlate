"""missing_graphic 三内建 —— graphic_case_link / graphic_repair / metapost .N 扩面。

signature-mining 2026-09-16 top5#2:
  - ``{sf_08_VX}`` vs 盘上 ``SF_08_VX`` 在 Linux 敏感 FS 挂 (2403.15102)
    → graphic_case_link 大小写不敏感找真身, 改写 ``\\includegraphics`` 参数;
  - figDY.pdf 在盘合法但引擎拒载 (1502.06541) → graphic_repair 分级:
    gs pdfwrite 重蒸馏 → 降级 ``\\fbox``/``\\rule`` 占位框;
  - metapost ``diag1.1`` (``.\\d+`` 扩展实为 EPS, 0806.4589 漏归 other)
    → eps_to_pdf 扫源面扩 ``.\\d+``, dst 叠 ``.pdf`` 防 ``diag1.1``/``diag1.2``
    同塌 ``diag1.pdf``。
"""

import shutil
from pathlib import Path

import pytest
from _fixloopkit import which_only

from texlate.compile.fixloop import _builtins_graphics, builtins
from texlate.compile.fixloop.builtins import (
    eps_to_pdf,
    graphic_case_link,
    graphic_repair,
)
from texlate.compile.fixloop.engine import LoopCtx, RunFn

MAIN = (
    "\\documentclass{article}\n\\usepackage{graphicx}\n\\begin{document}\n"
    "\\includegraphics{img/sf_08_VX.pdf}\n\\end{document}\n"
)
MAIN_FIGDY = (
    "\\documentclass{article}\n\\begin{document}\n"
    "\\includegraphics[width=2in]{figDY.pdf}\n\\end{document}\n"
)


def _ctx(tmp_path: Path, runner: RunFn | None = None) -> LoopCtx:
    return LoopCtx(
        wdir=tmp_path, engine_name="xelatex", main_rel="main.tex", runner=runner
    )


def _gs_ok(argv: list[str], _timeout: int, _wdir: Path) -> tuple:
    """模拟 gs: ``-o`` 目标写伪 pdf, rc=0。"""
    Path(argv[argv.index("-o") + 1]).write_bytes(b"%PDF-1.7 redistilled")
    return 0, "GPL Ghostscript ok", 0.1, False


def _gs_fail(_argv: list[str], _timeout: int, _wdir: Path) -> tuple:
    return 1, "gs: corrupted xref", 0.1, False


def _spy(calls: list[list[str]]) -> RunFn:
    """argv 记录间谍 runner —— 断言本轮 gs/convert 未被调用。"""

    def _run(argv: list[str], _t: int, _w: Path) -> tuple:
        calls.append(argv)
        return 0, "", 0.1, False

    return _run


# ─────────────────────────── graphic_case_link ───────────────────────────


def test_case_link_rewrites_to_real_relpath(tmp_path: Path) -> None:
    """2403.15102 形: ``img/sf_08_VX.pdf`` vs ``img/SF_08_VX.pdf`` → 参数改真名。"""
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "SF_08_VX.pdf").write_bytes(b"%PDF real")
    (tmp_path / "main.tex").write_text(MAIN, encoding="utf-8")
    ok, note = graphic_case_link(_ctx(tmp_path), None, "img/sf_08_VX.pdf", {})
    assert ok
    assert "img/SF_08_VX.pdf" in note
    t = (tmp_path / "main.tex").read_text(encoding="utf-8")
    assert "\\includegraphics{img/SF_08_VX.pdf}" in t


def test_case_link_stemless_payload_via_basename(tmp_path: Path) -> None:
    """payload 无扩展名 + 引用无目录 → stem ci 命中 → 改写真名(补全扩展名)。"""
    (tmp_path / "5X.pdf").write_bytes(b"%PDF real")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includegraphics{5x}\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _note = graphic_case_link(_ctx(tmp_path), None, "5x", {})
    assert ok
    assert "\\includegraphics{5X.pdf}" in (tmp_path / "main.tex").read_text()


def test_case_link_subdir_ci_relpath(tmp_path: Path) -> None:
    """目录段大小写也不符 (``IMG/``) → relpath 整串 ci 命中。"""
    (tmp_path / "IMG").mkdir()
    (tmp_path / "IMG" / "SF_08_VX.pdf").write_bytes(b"%PDF")
    (tmp_path / "main.tex").write_text(MAIN, encoding="utf-8")
    ok, _note = graphic_case_link(_ctx(tmp_path), None, "img/sf_08_VX.pdf", {})
    assert ok
    assert "\\includegraphics{IMG/SF_08_VX.pdf}" in (tmp_path / "main.tex").read_text()


def test_case_link_no_variant(tmp_path: Path) -> None:
    """工程内无 ci 变体 → False 不谎报。"""
    (tmp_path / "main.tex").write_text(MAIN, encoding="utf-8")
    ok, note = graphic_case_link(_ctx(tmp_path), None, "img/sf_08_VX.pdf", {})
    assert not ok
    assert "no case-variant" in note


def test_case_link_verbatim_resolves(tmp_path: Path) -> None:
    """payload 本身已能按字面目解析 → 非大小写病灶 → False。"""
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "sf_08_VX.pdf").write_bytes(b"%PDF")
    (tmp_path / "main.tex").write_text(MAIN, encoding="utf-8")
    ok, note = graphic_case_link(_ctx(tmp_path), None, "img/sf_08_VX.pdf", {})
    assert not ok
    assert "verbatim" in note
    assert "img/sf_08_VX.pdf" in (tmp_path / "main.tex").read_text()


def test_case_link_idempotent_second_fire(tmp_path: Path) -> None:
    """二次触火: 引用已指向可解析真身 → 守卫跳过 → False, 文本不变。"""
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "SF_08_VX.pdf").write_bytes(b"%PDF")
    (tmp_path / "main.tex").write_text(MAIN, encoding="utf-8")
    ctx = _ctx(tmp_path)
    ok1, _n1 = graphic_case_link(ctx, None, "img/sf_08_VX.pdf", {})
    t1 = (tmp_path / "main.tex").read_text()
    ok2, note2 = graphic_case_link(ctx, None, "img/sf_08_VX.pdf", {})
    assert ok1
    assert not ok2
    assert "no ref rewrote" in note2
    assert (tmp_path / "main.tex").read_text() == t1


def test_case_link_unrelated_resolving_ref_untouched(tmp_path: Path) -> None:
    """同名其他目录引用本可解析 → 不是病灶, 不被改写。"""
    (tmp_path / "img").mkdir()
    (tmp_path / "img" / "SF_08_VX.pdf").write_bytes(b"%PDF")
    (tmp_path / "other").mkdir()
    (tmp_path / "other" / "img").mkdir()
    (tmp_path / "other" / "img" / "sf_08_VX.pdf").write_bytes(b"%PDF other")
    (tmp_path / "main.tex").write_text(MAIN, encoding="utf-8")
    (tmp_path / "other" / "sub.tex").write_text(
        "\\includegraphics{img/sf_08_VX.pdf}\n", encoding="utf-8"
    )
    ok, _note = graphic_case_link(_ctx(tmp_path), None, "img/sf_08_VX.pdf", {})
    assert ok
    # main.tex 的引用解析不到 (wdir/img/sf_08_VX.pdf 不存在) → 改
    assert "img/SF_08_VX.pdf" in (tmp_path / "main.tex").read_text()
    # other/sub.tex 的引用相对其目录可解析 → 不动
    assert "img/sf_08_VX.pdf" in (tmp_path / "other" / "sub.tex").read_text()


# ─────────────────────────── graphic_repair ───────────────────────────


def test_repair_redistill_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """gs 在 → pdfwrite 重蒸馏就地覆盖, 原件留 .fixloop-rd 旁记。"""
    monkeypatch.setattr(shutil, "which", which_only("gs"))
    (tmp_path / "figDY.pdf").write_bytes(b"%PDF-corrupt-ish")
    (tmp_path / "main.tex").write_text(MAIN_FIGDY, encoding="utf-8")
    ok, note = graphic_repair(_ctx(tmp_path, runner=_gs_ok), None, "figDY.pdf", {})
    assert ok
    assert "redistilled" in note
    assert (tmp_path / "figDY.pdf").read_bytes() == b"%PDF-1.7 redistilled"
    assert (tmp_path / "figDY.pdf.fixloop-rd").read_bytes() == b"%PDF-corrupt-ish"
    # redistill 不改 tex
    assert (
        "\\includegraphics[width=2in]{figDY.pdf}" in (tmp_path / "main.tex").read_text()
    )


def test_repair_no_gs_falls_to_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """无 gs → 降级 stub: ``\\fbox{\\rule{0pt}{H}\\rule{W}{0pt}}`` 保 width= 尺寸。"""
    monkeypatch.setattr(shutil, "which", which_only())
    (tmp_path / "figDY.pdf").write_bytes(b"%PDF-corrupt")
    (tmp_path / "main.tex").write_text(MAIN_FIGDY, encoding="utf-8")
    ok, note = graphic_repair(_ctx(tmp_path), None, "figDY.pdf", {})
    assert ok
    assert "stub" in note
    assert "no gs" in note
    t = (tmp_path / "main.tex").read_text()
    assert "\\fbox{\\rule{0pt}{0.45\\linewidth}\\rule{2in}{0pt}}" in t
    assert "\\includegraphics" not in t


def test_repair_gs_fail_falls_to_stub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """gs 失败 → 同 call 内降级 stub; 无残留 .fixloop-tmp。"""
    monkeypatch.setattr(shutil, "which", which_only("gs"))
    (tmp_path / "figDY.pdf").write_bytes(b"%PDF-corrupt")
    (tmp_path / "main.tex").write_text(MAIN_FIGDY, encoding="utf-8")
    ok, note = graphic_repair(_ctx(tmp_path, runner=_gs_fail), None, "figDY.pdf", {})
    assert ok
    assert "stub" in note
    assert "gs failed rc=1" in note
    assert "\\fbox{" in (tmp_path / "main.tex").read_text()
    assert not (tmp_path / "figDY.pdf.fixloop-tmp").exists()


def test_repair_marker_skips_redistill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """上轮蒸馏过仍拒载 → .fixloop-rd marker 短路直落 stub, gs 不再跑。"""
    monkeypatch.setattr(shutil, "which", which_only("gs"))
    calls: list[list[str]] = []
    (tmp_path / "figDY.pdf").write_bytes(b"%PDF-redistilled")
    (tmp_path / "figDY.pdf.fixloop-rd").write_bytes(b"%PDF-orig")
    (tmp_path / "main.tex").write_text(MAIN_FIGDY, encoding="utf-8")
    ok, note = graphic_repair(_ctx(tmp_path, runner=_spy(calls)), None, "figDY.pdf", {})
    assert ok
    assert "stub" in note
    assert "already redistilled" in note
    assert not calls


def test_repair_force_stub_skips_gs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """params.force_stub → 跳过蒸馏直接 stub (rules.yaml 独立 stub 规则面)。"""
    monkeypatch.setattr(shutil, "which", which_only("gs"))
    calls: list[list[str]] = []
    (tmp_path / "figDY.pdf").write_bytes(b"%PDF")
    (tmp_path / "main.tex").write_text(MAIN_FIGDY, encoding="utf-8")
    ok, note = graphic_repair(
        _ctx(tmp_path, runner=_spy(calls)), None, "figDY.pdf", {"force_stub": True}
    )
    assert ok
    assert "force_stub" in note
    assert not calls
    assert (
        "\\fbox{\\rule{0pt}{0.45\\linewidth}\\rule{2in}{0pt}}"
        in (tmp_path / "main.tex").read_text()
    )


def test_repair_stub_both_dims(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """width=+height= 双全 → 占位框取原尺寸。"""
    monkeypatch.setattr(shutil, "which", which_only())
    (tmp_path / "x.pdf").write_bytes(b"%PDF")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includegraphics[width=3in,height=2in]{x.pdf}\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, _note = graphic_repair(_ctx(tmp_path), None, "x.pdf", {})
    assert ok
    assert (
        "\\fbox{\\rule{0pt}{2in}\\rule{3in}{0pt}}"
        in (tmp_path / "main.tex").read_text()
    )


def test_repair_missing_file(tmp_path: Path) -> None:
    """payload 在盘上不存在 → False (missing 侧归 case_link/install_file)。"""
    (tmp_path / "main.tex").write_text(MAIN_FIGDY, encoding="utf-8")
    ok, note = graphic_repair(_ctx(tmp_path), None, "nofile.pdf", {})
    assert not ok
    assert "not found" in note


def test_repair_stub_idempotent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """stub 后无 ``\\includegraphics`` 引用 → 二次触火 False 不重复改。"""
    monkeypatch.setattr(shutil, "which", which_only())
    (tmp_path / "figDY.pdf").write_bytes(b"%PDF-corrupt")
    (tmp_path / "main.tex").write_text(MAIN_FIGDY, encoding="utf-8")
    ctx = _ctx(tmp_path)
    ok1, _n1 = graphic_repair(ctx, None, "figDY.pdf", {})
    t1 = (tmp_path / "main.tex").read_text()
    ok2, note2 = graphic_repair(ctx, None, "figDY.pdf", {})
    assert ok1
    assert not ok2
    assert "no \\includegraphics ref" in note2
    assert (tmp_path / "main.tex").read_text() == t1


# ─────────────────── eps_to_pdf: metapost ``.\d+`` 扩面 ───────────────────


def _fake_convert(_tool: str, _src: Path, dst: Path) -> tuple:
    """假转换器: 直接写 dst, 绕开真 epstopdf/gs 子进程。"""
    dst.write_bytes(b"%PDF-fake")
    return 0, "", False


@pytest.fixture
def _convert_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """eps_to_pdf 转换面双钉: epstopdf/gs 在场 + ``_run_convert`` 假转换器。"""
    monkeypatch.setattr(shutil, "which", which_only("epstopdf", "gs"))
    monkeypatch.setattr(_builtins_graphics, "_run_convert", _fake_convert)


@pytest.mark.usefixtures("_convert_env")
def test_eps_to_pdf_metapost_numeric_ext(tmp_path: Path) -> None:
    """0806.4589 形: ``diag1.1``/``diag1.10`` 进转换面 → ``name+'.pdf'`` dst 防互塌。"""
    (tmp_path / "diag1.1").write_bytes(b"%!PS-Adobe-3.0 EPSF")
    (tmp_path / "diag1.10").write_bytes(b"%!PS-Adobe-3.0 EPSF")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includegraphics{diag1.1}\n\\includegraphics{diag1.10}\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = eps_to_pdf(_ctx(tmp_path), None, None, {})
    assert ok
    assert "2/2" in note
    assert (tmp_path / "diag1.1.pdf").is_file()
    assert (tmp_path / "diag1.10.pdf").is_file()
    t = (tmp_path / "main.tex").read_text()
    assert "\\includegraphics{diag1.1.pdf}" in t
    assert "\\includegraphics{diag1.10.pdf}" in t


@pytest.mark.usefixtures("_convert_env")
def test_eps_to_pdf_numeric_idempotent(tmp_path: Path) -> None:
    """二次触火: dst 已存在复用, ``diag1.1.pdf`` 不被叠成 ``diag1.1.pdf.pdf``。"""
    (tmp_path / "diag1.1").write_bytes(b"%!PS-Adobe-3.0 EPSF")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includegraphics{diag1.1}\n\\end{document}\n",
        encoding="utf-8",
    )
    ctx = _ctx(tmp_path)
    ok1, _n1 = eps_to_pdf(ctx, None, None, {})
    ok2, _n2 = eps_to_pdf(ctx, None, None, {})
    assert ok1
    assert ok2  # dst 复用仍记 applied, 但引用侧不重写
    t = (tmp_path / "main.tex").read_text()
    assert "diag1.1.pdf" in t
    assert "diag1.1.pdf.pdf" not in t


@pytest.mark.usefixtures("_convert_env")
def test_eps_to_pdf_mps_and_uppercase(tmp_path: Path) -> None:
    """``.mps`` 与 ``.EPS`` 大写后缀同进转换面。"""
    (tmp_path / "fig.mps").write_bytes(b"%!PS-Adobe-3.0 EPSF")
    (tmp_path / "OLD.EPS").write_bytes(b"%!PS-Adobe-3.0 EPSF")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\epsfig{file=fig.mps}\n\\includegraphics{OLD.EPS}\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = eps_to_pdf(_ctx(tmp_path), None, None, {})
    assert ok
    assert "2/2" in note
    assert (tmp_path / "fig.pdf").is_file()
    assert (tmp_path / "OLD.pdf").is_file()
    t = (tmp_path / "main.tex").read_text()
    assert "file=fig.pdf" in t
    assert "\\includegraphics{OLD.pdf}" in t


@pytest.mark.usefixtures("_convert_env")
def test_eps_to_pdf_dos_exts(tmp_path: Path) -> None:
    """``.epsi``/``.epsf`` (DOS 约定 EPS) 与 PS_GRAPHIC_SUFFIXES 同步进转换面。"""
    (tmp_path / "fig.epsi").write_bytes(b"%!PS-Adobe-3.0 EPSF")
    (tmp_path / "plot.EPSF").write_bytes(b"%!PS-Adobe-3.0 EPSF")
    (tmp_path / "main.tex").write_text(
        "\\documentclass{article}\n\\begin{document}\n"
        "\\includegraphics{fig.epsi}\n\\epsfig{file=plot.EPSF}\n\\end{document}\n",
        encoding="utf-8",
    )
    ok, note = eps_to_pdf(_ctx(tmp_path), None, None, {})
    assert ok
    assert "2/2" in note
    assert (tmp_path / "fig.pdf").is_file()
    assert (tmp_path / "plot.pdf").is_file()


def test_eps_to_pdf_no_sources(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """无 PS 族源文件 → False。"""
    monkeypatch.setattr(shutil, "which", which_only("epstopdf", "gs"))
    (tmp_path / "main.tex").write_text(MAIN, encoding="utf-8")
    ok, note = eps_to_pdf(_ctx(tmp_path), None, None, {})
    assert not ok
    assert "no .eps" in note


def test_transform_fns_registry() -> None:
    """两个新内建注册进 TRANSFORM_FNS (rules.yaml function: 面)。"""
    assert builtins.TRANSFORM_FNS["graphic_case_link"] is graphic_case_link
    assert builtins.TRANSFORM_FNS["graphic_repair"] is graphic_repair
