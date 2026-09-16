r"""fixloop aux 截断重试规则（2211.13013 闭环·引擎自产臂）。

taxonomy ``aux_scan_eof`` 接 ``File ended while scanning use of \@newl@bel``
签名 → ``aux_purge_regen`` 规则调 ``purge_corrupt_intermediates`` 删损坏
可再生中间件。shipped 侧归 normalize.INTERMEDIATE_SUFFIXES 转码，本侧管
引擎自产件的运行时截断。
"""

from pathlib import Path

from texlate.compile.fixloop import load_ruleset
from texlate.compile.fixloop.builtins import TRANSFORM_FNS
from texlate.compile.fixloop.engine import LoopCtx, fixloop
from texlate.compile.fixloop.logparse import parse_text

RS = load_ruleset()

_EOF_LOG = (
    "This is XeTeX\n(./main.aux\n! File ended while scanning use of \\@newl@bel.\n"
    "<inserted text>\n                \\par\nl.5 \\begin{document}\n"
)
CLEAN_LOG = "This is XeTeX\nOutput written on main.pdf (1 page).\n"
MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}\n"


class _Res:
    """impl CompRes 的 duck-type 替身（同 test_fixloop_loop.MockRes 口径）。"""

    def __init__(self, wdir: Path, main: str, spec: dict) -> None:
        stem = Path(main).stem
        self.log_path = wdir / f"{stem}.log"
        self.log_path.write_text(spec.get("log", ""), encoding="utf-8")
        self.pdf = wdir / f"{stem}.pdf" if spec.get("pdf") else None
        if self.pdf is not None:
            self.pdf.write_bytes(b"%PDF-1.4 fake")
        self.pdf_bytes = self.pdf.stat().st_size if self.pdf else 0
        self.timed_out = False
        self.seconds = 0.01
        self.stdout_tail = ""

    @property
    def has_pdf(self) -> bool:
        return self.pdf is not None and self.pdf_bytes > 0


class _Eng:
    """script 逐轮吐 spec；本规则不触 install 路径，余桩一律 False/None。"""

    name = "xelatex"
    caps = frozenset({"kpsewhich", "tlmgr", "updmap"})

    def __init__(self, script: list) -> None:
        self.script = list(script)
        self.rounds = 0

    def compile(self, wdir: Path, main: str, *, passes: int = 2, **_kw: object) -> _Res:
        del passes, _kw
        i = min(self.rounds, len(self.script) - 1)
        self.rounds += 1
        return _Res(Path(wdir), main, self.script[i])

    def probe_file(self, fname: str, cwd: Path | None = None) -> str | None:
        del fname, cwd
        return None

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:
        del fname, font_related
        return False

    def rebuild_fontmaps(self) -> bool:
        return True

    def filemap(self, fname: str) -> list[str]:
        del fname
        return []


# ---------------------------------------------------------------- taxonomy
def test_aux_eof_classifies_with_payload() -> None:
    rep = parse_text(_EOF_LOG)
    cat, pay = RS.taxonomy.classify(rep)
    assert cat == "aux_scan_eof"
    assert pay == "newl@bel"  # payload_group=1 抓到回读宏名


def test_aux_eof_beats_emergency_in_ctx8() -> None:
    """'!' 行后 ctx8 混入 Emergency stop 不抢签（条目先于 emergency 评估）。"""
    log = _EOF_LOG + "Emergency stop\n!  ==> Fatal error occurred\n"
    rep = parse_text(log)
    cat, _ = RS.taxonomy.classify(rep)
    assert cat == "aux_scan_eof"


def test_generic_scan_eof_not_aux() -> None:
    """非回读宏的 EOF 扫描（如截断的 main.tex 撞上 \\section）不归本类。"""
    rep = parse_text("! File ended while scanning use of \\section.\nl.9 x\n")
    cat, _ = RS.taxonomy.classify(rep)
    assert cat == "other"


# ---------------------------------------------------------------- builtin 单测
def _purge(wdir: Path) -> tuple[bool, str]:
    ctx = LoopCtx(wdir=wdir, engine_name="xelatex")
    return TRANSFORM_FNS["purge_corrupt_intermediates"](ctx, None, None, {})


def test_purge_deletes_only_corrupt(tmp_path: Path) -> None:
    (tmp_path / "main.aux").write_bytes(b"\\newlabel{a}{{1}{1}{t\xe4\xb8")
    (tmp_path / "main.toc").write_bytes("\\contentsline{章}{一}{1}\n".encode())
    (tmp_path / "keep.aux").write_bytes(b"\\newlabel{b}{{1}{1}{ok}}\n")
    (tmp_path / "main.bib").write_bytes(b"@x{k,title={\xe9}}\n")  # 非 utf-8 但非中间件
    ok, note = _purge(tmp_path)
    assert ok
    assert "main.aux" in note
    assert not (tmp_path / "main.aux").exists()
    assert (tmp_path / "main.toc").exists()  # 完整 utf-8 + 尾换行 = 健康
    assert (tmp_path / "keep.aux").exists()
    assert (tmp_path / "main.bib").exists()


def test_purge_catches_clean_boundary_truncation(tmp_path: Path) -> None:
    """边界恰好落在字符缝：可解码但末行不完整（TeX 完整行必以 \\n 收尾）。"""
    (tmp_path / "main.aux").write_bytes(b"\\newlabel{a}{{1}{1}{ok}")
    ok, _ = _purge(tmp_path)
    assert ok
    assert not (tmp_path / "main.aux").exists()


def test_purge_no_corrupt_returns_false(tmp_path: Path) -> None:
    (tmp_path / "main.aux").write_bytes(b"\\relax\n\\newlabel{a}{{1}{1}{ok}}\n")
    ok, _ = _purge(tmp_path)
    assert not ok
    assert (tmp_path / "main.aux").exists()


# ---------------------------------------------------------------- 端到端
def test_fixloop_aux_eof_roundtrip(tmp_path: Path) -> None:
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (tmp_path / "main.aux").write_bytes(b"\\newlabel{a}{{1}{1}{t\xe4\xb8")
    eng = _Eng([{"log": _EOF_LOG, "pdf": False}, {"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(tmp_path, eng, ruleset=RS)
    assert cell["verdict"] == "clean"
    assert any(a["rule"] == "aux_purge_regen" for a in cell["actions"])
    assert not (tmp_path / "main.aux").exists()  # 损坏件已删, 下遍引擎重生成


def test_fixloop_aux_eof_no_corrupt_falls_through(tmp_path: Path) -> None:
    """签名命中但无损坏件 → 规则 applied=False, 不误伤健康 aux。"""
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    (tmp_path / "main.aux").write_bytes(b"\\newlabel{a}{{1}{1}{ok}}\n")
    eng = _Eng([{"log": _EOF_LOG, "pdf": False}] * 4)
    cell = fixloop(tmp_path, eng, ruleset=RS)
    assert cell["verdict"] != "clean"
    assert (tmp_path / "main.aux").exists()
    assert all(a["rule"] != "aux_purge_regen" for a in cell["actions"])
