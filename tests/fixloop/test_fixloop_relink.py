r"""misplaced relink 车道 (2026-09-19): install_file already-present 误报修复。

soak-2026-09-18 实证: 编译 cwd = main 所在目录, 而 ``_probe`` 以 ``wdir``
为基——工程内错位件 probe 报 already-present 但 TeX 字面解析照旧
missing_file → unfixable 误判。两形态:

- 2609.19664 fairmeta: 主档 ``templates/arxiv/main.tex`` 引
  ``\\documentclass{templates/arxiv/fairmeta}``——目录形 payload 只走
  ``main_dir/fname`` 字面解析 (kpathsea 对 dir 分量无裸名递补), 件在同
  目录下 probe 仍命中 ``wdir/templates/arxiv/fairmeta.cls``。
- 2609.20640 acronyms1: 主档 ``IEEEtran/main.tex`` 引 ``acronyms1.tex``,
  件置工程根——裸名走 ``main_dir`` + TEXINPUTS, 根件够不到。

``_relink_misplaced`` 把工程内错位件软链进 ``main_dir`` 解析位: 目录形
payload 首段非 main_dir 祖先 → 目录级链罩整枝 (Content/* 链式缺件一轮
收口); 首段恰是祖先或解析位被占 → 落文件级链。
"""

from pathlib import Path

from texlate.compile.fixloop.actions import _apply_install_file, _relink_misplaced
from texlate.compile.fixloop.engine import LoopCtx
from texlate.compile.logparse import ErrReport


class _ProbeEng:
    """probe_file → ``cwd``/``wdir`` 根相对直查 + texmf 递补 (真引擎同序)。"""

    name = "xelatex"

    def __init__(self, texmf: Path) -> None:
        self.texmf = texmf

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        if cwd is not None and (p := cwd / fname).is_file():
            return str(p)
        p = self.texmf / fname
        return str(p) if p.is_file() else None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False

    def rebuild_fontmaps(self) -> None:
        pass

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


def _mk(tmp_path: Path, main_rel: str) -> tuple[Path, Path, LoopCtx]:
    wdir = tmp_path / "proj"
    (wdir / Path(main_rel).parent).mkdir(parents=True, exist_ok=True)
    (wdir / main_rel).write_text("\\documentclass{x}\n", encoding="utf-8")
    texmf = tmp_path / "texmf"
    texmf.mkdir()
    ctx = LoopCtx(wdir=wdir, engine_name="xelatex", main_rel=main_rel)
    return wdir, texmf, ctx


def test_relink_bare_file_at_root(tmp_path: Path) -> None:
    """acronyms1 形：根置 .tex + 主档在子目录 → 文件级链进 main_dir。"""
    wdir, texmf, ctx = _mk(tmp_path, "IEEEtran/main.tex")
    (wdir / "acronyms1.tex").write_text("% acronyms\n", encoding="utf-8")
    eng = _ProbeEng(texmf)
    present = eng.probe_file("acronyms1.tex", cwd=wdir)
    assert present is not None
    link = _relink_misplaced(ctx, "acronyms1.tex", present)
    assert link == wdir / "IEEEtran" / "acronyms1.tex"
    assert link.is_symlink()
    assert link.resolve() == (wdir / "acronyms1.tex").resolve()


def test_relink_dir_payload_main_inside_top(tmp_path: Path) -> None:
    """fairmeta 形：payload 首段恰是 main_dir 祖先 → 不目录链 (防环), 落文件级链。"""
    wdir, _texmf, ctx = _mk(tmp_path, "templates/arxiv/main.tex")
    real = wdir / "templates" / "arxiv" / "fairmeta.cls"
    real.write_text("\\ProvidesClass{fairmeta}\n", encoding="utf-8")
    present = str(real)
    link = _relink_misplaced(ctx, "templates/arxiv/fairmeta.cls", present)
    expected = wdir / "templates" / "arxiv" / "templates" / "arxiv" / "fairmeta.cls"
    assert link == expected
    assert expected.is_symlink()
    assert expected.resolve() == real.resolve()
    assert (
        not (wdir / "templates" / "arxiv" / "templates").is_symlink()
        or (wdir / "templates" / "arxiv" / "templates" / "arxiv").is_symlink()
    )


def test_relink_dir_payload_sibling_tree(tmp_path: Path) -> None:
    """Content 形：payload 首段是 main_dir 的兄弟树 → 目录级链罩整枝，
    同枝后续缺件经活链判 already-present (不再重复链接)。"""
    wdir, texmf, ctx = _mk(tmp_path, "IEEEtran/main.tex")
    (wdir / "Content").mkdir()
    (wdir / "Content" / "introTEST.tex").write_text("% a\n", encoding="utf-8")
    (wdir / "Content" / "other.tex").write_text("% b\n", encoding="utf-8")
    eng = _ProbeEng(texmf)
    present = eng.probe_file("Content/introTEST.tex", cwd=wdir)
    link = _relink_misplaced(ctx, "Content/introTEST.tex", present)
    dlink = wdir / "IEEEtran" / "Content"
    assert link == dlink
    assert dlink.is_symlink()
    assert dlink.is_dir()
    # 同枝第二件：经目录链可达 → None → install_file 走 already-present
    present2 = eng.probe_file("Content/other.tex", cwd=wdir)
    assert _relink_misplaced(ctx, "Content/other.tex", present2) is None


def test_relink_texmf_hit_returns_none(tmp_path: Path) -> None:
    """texmf 系统件命中 → None (TEXINPUTS 本可达，无 relink 面)。"""
    _wdir, texmf, ctx = _mk(tmp_path, "sub/main.tex")
    (texmf / "foo.sty").write_text("% sys\n", encoding="utf-8")
    assert _relink_misplaced(ctx, "foo.sty", str(texmf / "foo.sty")) is None


def test_relink_already_at_expected_returns_none(tmp_path: Path) -> None:
    """解析位已有真件 → None —— 真 already-present/名冲突, 不覆盖现场。"""
    wdir, _texmf, ctx = _mk(tmp_path, "sub/main.tex")
    (wdir / "foo.tex").write_text("% stray\n", encoding="utf-8")
    (wdir / "sub" / "foo.tex").write_text("% real\n", encoding="utf-8")
    assert _relink_misplaced(ctx, "foo.tex", str(wdir / "foo.tex")) is None
    assert (wdir / "sub" / "foo.tex").read_text() == "% real\n"


def test_relink_live_symlink_returns_none(tmp_path: Path) -> None:
    """解析位活链已占位 → None (视为已在解析位)。"""
    wdir, _texmf, ctx = _mk(tmp_path, "sub/main.tex")
    (wdir / "foo.tex").write_text("% stray\n", encoding="utf-8")
    (wdir / "sub" / "foo.tex").symlink_to(wdir / "foo.tex")
    assert _relink_misplaced(ctx, "foo.tex", str(wdir / "foo.tex")) is None


def test_relink_dead_symlink_replaced(tmp_path: Path) -> None:
    """解析位死链 → 换新指向 probe 命中件。"""
    wdir, _texmf, ctx = _mk(tmp_path, "sub/main.tex")
    (wdir / "foo.tex").write_text("% stray\n", encoding="utf-8")
    dead = wdir / "sub" / "foo.tex"
    dead.symlink_to(wdir / "nonexistent.tex")
    link = _relink_misplaced(ctx, "foo.tex", str(wdir / "foo.tex"))
    assert link == dead
    assert dead.is_symlink()
    assert dead.resolve() == (wdir / "foo.tex").resolve()


def test_install_file_relinks_misplaced(tmp_path: Path) -> None:
    """集成面：``_apply_install_file`` present 分支先 relink, note 记链位。"""
    wdir, texmf, ctx = _mk(tmp_path, "IEEEtran/main.tex")
    (wdir / "acronyms1.tex").write_text("% acronyms\n", encoding="utf-8")
    ok, note = _apply_install_file(
        ctx, _ProbeEng(texmf), {"file": "acronyms1.tex"}, ErrReport()
    )
    assert ok, note
    assert note.startswith("relinked acronyms1.tex ->")
    assert (wdir / "IEEEtran" / "acronyms1.tex").is_symlink()


def test_install_file_true_already_present(tmp_path: Path) -> None:
    """对照：件已在 ``main_dir`` 解析位 → relink 不动，走 already-present。"""
    wdir, texmf, ctx = _mk(tmp_path, "main.tex")
    (wdir / "helper.tex").write_text("% h\n", encoding="utf-8")
    ok, note = _apply_install_file(
        ctx, _ProbeEng(texmf), {"file": "helper.tex"}, ErrReport()
    )
    assert ok, note
    assert note.startswith("already-present helper.tex")
    assert not (wdir / "helper.tex").is_symlink()
