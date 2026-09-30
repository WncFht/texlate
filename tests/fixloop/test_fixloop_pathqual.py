r"""pathqual 车道 (2026-09-19): vendored_sty_shadow 路径限定装载点回填 shim。

1803.03185 实证回退: ``\usepackage{./style/optidef}`` 只对字面相对径
解析, texmf 裸名递补够不到 ``./`` 前缀——``style/optidef.sty`` 被
``.fixloop-iso`` 隔离后该装载点即 ``missing_file`` → unfixable 降格。

修复形: rename 隔离后扫工程内路径限定装载点 (``./x``/``x/y``/``x\y`` +
import 族), 命中即原径回填薄 shim ``\input{<probe 解析系统副本>}`` ——
隔离收益与路径解析两全。裸名装载 (无目录分量) 走 texmf 序天然递补,
不写 shim。伴船件路径限定命中但系统无递补 → 不 rename 直保留。
"""

from pathlib import Path

from texlate.compile.fixloop.builtins import vendored_shadow_isolate
from texlate.compile.fixloop.engine import LoopCtx


class _ShadowEng:
    """probe_file → ``texmf`` 目录直查 (模拟系统副本在场); extra 定点覆盖。"""

    name = "xelatex"

    def __init__(self, texmf: Path, extra: dict[str, Path] | None = None) -> None:
        self.texmf = texmf
        self.extra = extra or {}

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del cwd
        if fname in self.extra:
            return str(self.extra[fname])
        p = self.texmf / fname
        return str(p) if p.is_file() else None

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _ctx(tmp_path: Path) -> LoopCtx:
    return LoopCtx(wdir=tmp_path, engine_name="xelatex", main_rel="main.tex")


_OLD_STY = "\\ProvidesPackage{optidef}[2010/01/01 v1.0 vendored old]\n"
_NEW_STY = "\\ProvidesPackage{optidef}[2020/05/05 v2.0 system new]\n"
_OLD_CORE = "\\def\\fileversion{1.0}\n\\def\\filedate{2006/12/22}\n"
_NEW_CORE = "\\def\\fileversion{2.0}\n\\def\\filedate{2025/12/13}\n"


def _isolate_params() -> dict:
    return {"exts": (".sty", ".cls"), "suffix": ".fixloop-iso"}


def _mk_dirs(tmp_path: Path) -> tuple[Path, Path]:
    wdir = tmp_path / "proj"
    wdir.mkdir()
    texmf = tmp_path / "texmf"
    texmf.mkdir()
    return wdir, texmf


def _sty_cell(tmp_path: Path, loads: str) -> tuple[Path, Path, str, str]:
    """1803.03185 形: sub/ 下旧 sty + texmf 新件 + 主稿装载行。"""
    wdir, texmf = _mk_dirs(tmp_path)
    (texmf / "optidef.sty").write_text(_NEW_STY, encoding="utf-8")
    sub = wdir / "style"
    sub.mkdir()
    (sub / "optidef.sty").write_text(_OLD_STY, encoding="utf-8")
    (wdir / "main.tex").write_text(loads, encoding="utf-8")
    ok, note = vendored_shadow_isolate(
        _ctx(wdir), _ShadowEng(texmf), None, _isolate_params()
    )
    return wdir, texmf, ok, note


# ------------------------------------------------------- 一参装载命令路径限定命中


def test_pathqual_dot_slash_usepackage_shimmed(tmp_path: Path) -> None:
    """1803.03185 复现形: ``\\usepackage{./style/optidef}`` → 隔离 + 原径 shim。"""
    wdir, texmf, ok, note = _sty_cell(
        tmp_path,
        "\\documentclass{article}\n\\usepackage{./style/optidef}\n",
    )
    assert ok, note
    iso = wdir / "style" / "optidef.sty.fixloop-iso"
    shim = wdir / "style" / "optidef.sty"
    assert iso.is_file()  # 旧件已隔离
    assert shim.is_file()  # 原径 shim 回填
    t = shim.read_text()
    assert "\\ProvidesPackage{optidef}" in t
    assert f"\\input{{{(texmf / 'optidef.sty').resolve().as_posix()}}}" in t
    assert t.startswith("% texlate-fixloop-injected:")


def test_pathqual_nodot_rel_shimmed(tmp_path: Path) -> None:
    """``\\usepackage{style/optidef}`` (无 ./) 同为路径限定 → shim。"""
    wdir, _, ok, note = _sty_cell(tmp_path, "\\usepackage{style/optidef}\n")
    assert ok, note
    assert (wdir / "style" / "optidef.sty").is_file()


def test_pathqual_bare_load_no_shim(tmp_path: Path) -> None:
    """对照: 裸名 ``\\usepackage{optidef}`` 走 texmf 序递补 → 不写 shim。"""
    wdir, _, ok, note = _sty_cell(tmp_path, "\\usepackage{optidef}\n")
    assert ok, note
    assert (wdir / "style" / "optidef.sty.fixloop-iso").is_file()
    assert not (wdir / "style" / "optidef.sty").exists()


def test_pathqual_comma_list_shimmed(tmp_path: Path) -> None:
    """逗号组内路径限定成员 → shim (``\\usepackage{a,./style/optidef}``)。"""
    wdir, _, ok, note = _sty_cell(tmp_path, "\\usepackage{amsmath,./style/optidef}\n")
    assert ok, note
    assert (wdir / "style" / "optidef.sty").is_file()


def test_pathqual_input_with_ext_shimmed(tmp_path: Path) -> None:
    """``\\input{./style/optidef.sty}`` 字面全径 → shim。"""
    wdir, _, ok, note = _sty_cell(tmp_path, "\\input{./style/optidef.sty}\n")
    assert ok, note
    assert (wdir / "style" / "optidef.sty").is_file()


def test_pathqual_requirepackage_opts_shimmed(tmp_path: Path) -> None:
    """``\\RequirePackage[opts]{./style/optidef}`` → shim。"""
    wdir, _, ok, note = _sty_cell(
        tmp_path, "\\RequirePackage[short]{./style/optidef}\n"
    )
    assert ok, note
    assert (wdir / "style" / "optidef.sty").is_file()


def test_pathqual_root_dot_slash_shimmed(tmp_path: Path) -> None:
    """根位件 ``./foo`` 形亦断 —— ``./`` 只对字面 cwd 径解 → 根位 shim。"""
    wdir, texmf = _mk_dirs(tmp_path)
    (texmf / "foo.sty").write_text(_NEW_STY, encoding="utf-8")
    (wdir / "foo.sty").write_text(_OLD_STY, encoding="utf-8")
    (wdir / "main.tex").write_text("\\usepackage{./foo}\n", encoding="utf-8")
    ok, note = vendored_shadow_isolate(
        _ctx(wdir), _ShadowEng(texmf), None, _isolate_params()
    )
    assert ok, note
    t = (wdir / "foo.sty").read_text()
    assert "\\input{" in t
    assert "foo.sty" in t


def test_pathqual_backslash_sep_shimmed(tmp_path: Path) -> None:
    """``\\usepackage{.\\style/optidef}`` 反斜杠分隔 → 归一命中 → shim。"""
    wdir, _, ok, note = _sty_cell(tmp_path, "\\usepackage{.\\style/optidef}\n")
    assert ok, note
    assert (wdir / "style" / "optidef.sty").is_file()


def test_pathqual_documentclass_shimmed(tmp_path: Path) -> None:
    """``\\documentclass{./cls/foo}`` → ``\\ProvidesClass`` shim。"""
    wdir, texmf = _mk_dirs(tmp_path)
    (texmf / "foo.cls").write_text(
        "\\ProvidesClass{foo}[2020/01/01 v2 system]\n", encoding="utf-8"
    )
    (wdir / "cls").mkdir()
    (wdir / "cls" / "foo.cls").write_text(
        "\\ProvidesClass{foo}[2005/01/01 v1 vendored]\n", encoding="utf-8"
    )
    (wdir / "main.tex").write_text("\\documentclass{./cls/foo}\n", encoding="utf-8")
    ok, note = vendored_shadow_isolate(
        _ctx(wdir), _ShadowEng(texmf), None, _isolate_params()
    )
    assert ok, note
    t = (wdir / "cls" / "foo.cls").read_text()
    assert "\\ProvidesClass{foo}" in t
    assert "\\input{" in t


def test_pathqual_commented_site_no_shim(tmp_path: Path) -> None:
    """遮盖面: 注释内 ``% \\usepackage{./style/optidef}`` 不算装载点。"""
    wdir, _, ok, note = _sty_cell(
        tmp_path,
        "% \\usepackage{./style/optidef}\n\\usepackage{amsmath}\n",
    )
    assert ok, note
    assert not (wdir / "style" / "optidef.sty").exists()


def test_pathqual_unrelated_dir_no_shim(tmp_path: Path) -> None:
    """异径 ``\\usepackage{./other/optidef}`` 不指本件 → 不写 shim。"""
    wdir, _, ok, note = _sty_cell(tmp_path, "\\usepackage{./other/optidef}\n")
    assert ok, note
    assert not (wdir / "style" / "optidef.sty").exists()


# ------------------------------------------------------- paired .tex 核 / 伴船 / 幂等


def test_paired_core_pathqual_input_shimmed(tmp_path: Path) -> None:
    """pst-* 一体形 + ``\\input{./x}`` → wrapper/核双退役 + 核原径 shim。"""
    wdir, texmf = _mk_dirs(tmp_path)
    (texmf / "x.sty").write_text(_NEW_STY.replace("optidef", "x"), encoding="utf-8")
    (texmf / "x.tex").write_text(_NEW_CORE, encoding="utf-8")
    (wdir / "x.sty").write_text(_OLD_STY.replace("optidef", "x"), encoding="utf-8")
    (wdir / "x.tex").write_text(_OLD_CORE, encoding="utf-8")
    (wdir / "main.tex").write_text("\\input{./x}\n", encoding="utf-8")
    ok, note = vendored_shadow_isolate(
        _ctx(wdir), _ShadowEng(texmf), None, _isolate_params()
    )
    assert ok, note
    assert "paired core" in note
    assert (wdir / "x.tex.fixloop-iso").is_file()
    t = (wdir / "x.tex").read_text()
    assert "\\input{" in t
    assert "x.tex}" in t


def test_shim_not_reflagged_second_round(tmp_path: Path) -> None:
    """幂等: shim ``\\ProvidesPackage`` 署 2026 新期 → 下轮非遮蔽候选, 不再动。"""
    wdir, texmf, ok, _ = _sty_cell(tmp_path, "\\usepackage{./style/optidef}\n")
    assert ok
    first = (wdir / "style" / "optidef.sty").read_text()
    ok2, _ = vendored_shadow_isolate(
        _ctx(wdir), _ShadowEng(texmf), None, _isolate_params()
    )
    assert not ok2  # 无确证更旧件——shim 署期 > 系统
    assert (wdir / "style" / "optidef.sty").read_text() == first
    assert not (wdir / "style" / "optidef.sty.fixloop-iso.fixloop-iso").exists()


def test_pathqual_cohort_no_replacement_stays(tmp_path: Path) -> None:
    """伴船件路径限定命中但系统无递补 → 不 rename (rename 即造 missing_file)。"""
    wdir, texmf = _mk_dirs(tmp_path)
    (texmf / "biblatex.sty").write_text(
        "\\ProvidesPackage{biblatex}[2020/01/01 v3 new]\n", encoding="utf-8"
    )
    (wdir / "biblatex.sty").write_text(
        "\\ProvidesPackage{biblatex}[2010/01/01 v1 old]\n", encoding="utf-8"
    )
    (wdir / "sub").mkdir()
    (wdir / "sub" / "foo.bbx").write_text("% vendored bbx\n", encoding="utf-8")
    (wdir / "main.tex").write_text("\\input{./sub/foo.bbx}\n", encoding="utf-8")
    params = _isolate_params() | {"cohort_map": {"biblatex.sty": ["*.bbx", "*.cbx"]}}
    ok, note = vendored_shadow_isolate(_ctx(wdir), _ShadowEng(texmf), None, params)
    assert ok, note
    assert (wdir / "biblatex.sty.fixloop-iso").is_file()
    assert (wdir / "sub" / "foo.bbx").is_file()  # 无递补 → 保留
    assert not (wdir / "sub" / "foo.bbx.fixloop-iso").exists()


def test_pathqual_cohort_shimmed(tmp_path: Path) -> None:
    """伴船件路径限定命中 ∧ 系统有递补 → rename + 原径 shim。"""
    wdir, texmf = _mk_dirs(tmp_path)
    (texmf / "biblatex.sty").write_text(
        "\\ProvidesPackage{biblatex}[2020/01/01 v3 new]\n", encoding="utf-8"
    )
    (texmf / "foo.bbx").write_text("% system bbx\n", encoding="utf-8")
    (wdir / "biblatex.sty").write_text(
        "\\ProvidesPackage{biblatex}[2010/01/01 v1 old]\n", encoding="utf-8"
    )
    (wdir / "sub").mkdir()
    (wdir / "sub" / "foo.bbx").write_text("% vendored bbx\n", encoding="utf-8")
    (wdir / "main.tex").write_text("\\input{./sub/foo.bbx}\n", encoding="utf-8")
    params = _isolate_params() | {"cohort_map": {"biblatex.sty": ["*.bbx", "*.cbx"]}}
    ok, note = vendored_shadow_isolate(_ctx(wdir), _ShadowEng(texmf), None, params)
    assert ok, note
    assert (wdir / "sub" / "foo.bbx.fixloop-iso").is_file()
    t = (wdir / "sub" / "foo.bbx").read_text()
    assert "\\input{" in t
    assert "foo.bbx}" in t
