r"""fixloop 同轮终编臂 (finalize) 的死编译否决 —— 2403.05523 幻影链钉。

``passes > 1`` 且 pass-1 看似收敛 (pdf + n_bang=0) 时引擎同轮补全遍
终编 (rungen_stub 靠第二遍 ``\write`` 填实)。臂原只排 ``timed_out`` —
— 信号死编译 (xdvipdfmx ``pdf_link_obj`` fatal → xelatex SIGPIPE
mid-\shipout) 同样产 pdf + 截断干净 log, 漏闸后同轮重编正好读上
刚被截在半行的 main.aux → 幻影 ``aux_scan_eof`` 轮自续 (auxeof
普查 2026-09-19, aux 恰截于 16384B 边界实证)。修 = 臂条件改
``not _res_died(res)``, 与 clean 门 (:905) 同一否决语义。
"""

from functools import lru_cache
from pathlib import Path

from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.fixloop.engine import fixloop


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    return load_ruleset()


CLEAN_LOG = "This is XeTeX\nOutput written on main.pdf (1 page).\n"
MAIN_TEX = "\\documentclass{article}\n\\begin{document}\nhi\n\\end{document}\n"


class _Res:
    """impl CompRes 的 duck-type 替身 (同 test_fixloop_aux_eof 口径)
    + ``killed_signal`` 槽 (spec["killed"]=信号号)。"""

    def __init__(self, wdir: Path, main: str, spec: dict) -> None:
        stem = Path(main).stem
        self.log_path = wdir / f"{stem}.log"
        self.log_path.write_text(spec.get("log", ""), encoding="utf-8")
        self.pdf = wdir / f"{stem}.pdf" if spec.get("pdf") else None
        if self.pdf is not None:
            self.pdf.write_bytes(b"%PDF-1.4 fake")
        self.pdf_bytes = self.pdf.stat().st_size if self.pdf else 0
        self.timed_out = spec.get("timed_out", False)
        self.killed_signal = spec.get("killed")
        self.seconds = 0.01
        self.stdout_tail = ""


class _Eng:
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


def _run(tmp_path: Path, script: list) -> tuple[dict, _Eng]:
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    eng = _Eng(script)
    cell = fixloop(tmp_path, eng, ruleset=_rs())
    return cell, eng


def test_finalize_arm_fires_on_clean_pass1(tmp_path: Path) -> None:
    """正控: 健康 pass-1 收敛 → 同轮终编照常补遍 (rungen_stub 通道不塌)。"""
    cell, eng = _run(tmp_path, [{"log": CLEAN_LOG, "pdf": True}] * 2)
    assert any("finalize" in e for e in cell["log"])
    assert eng.rounds >= 2  # pass-1 + 终编复编
    assert cell["verdict"] == "clean"


def test_finalize_arm_skips_killed_signal(tmp_path: Path) -> None:
    """SIGPIPE 截杀轮: pdf + n_bang=0 俱全仍不终编 —— 产出未证, 且
    同轮重编会读上刚截断的 aux (2403.05523 幻影链)。"""
    cell, eng = _run(
        tmp_path,
        [{"log": CLEAN_LOG, "pdf": True, "killed": 13}, {"log": CLEAN_LOG, "pdf": True}],
    )
    assert not any("finalize" in e for e in cell["log"])
    assert cell["rounds"][0]["died"] is True
    assert cell["rounds"][0]["category"] == "killed"


def test_finalize_arm_skips_timed_out(tmp_path: Path) -> None:
    """超时轮回归: timed_out=True 同样不终编 (_res_died 子集语义不变)。"""
    cell, eng = _run(
        tmp_path,
        [{"log": CLEAN_LOG, "pdf": True, "timed_out": True}, {"log": CLEAN_LOG, "pdf": True}],
    )
    assert not any("finalize" in e for e in cell["log"])
    assert cell["rounds"][0]["died"] is True
