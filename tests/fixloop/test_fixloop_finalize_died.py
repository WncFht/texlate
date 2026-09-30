r"""fixloop 同轮终编臂 (finalize) 的死编译否决 —— 2403.05523 幻影链钉。

``passes > 1`` 且 pass-1 看似收敛 (pdf + n_bang=0) 时引擎同轮补全遍
终编 (rungen_stub 靠第二遍 ``\write`` 填实)。臂原只排 ``timed_out`` —
— 信号死编译 (xdvipdfmx ``pdf_link_obj`` fatal → xelatex SIGPIPE
mid-\shipout) 同样产 pdf + 截断干净 log, 漏闸后同轮重编正好读上
刚被截在半行的 main.aux → 幻影 ``aux_scan_eof`` 轮自续 (auxeof
普查 2026-09-19, aux 恰截于 16384B 边界实证)。修 = 臂条件改
``not _res_died(res)``, 与 ``_round_verdict`` clean 门同一否决语义。
"""

from functools import lru_cache
from pathlib import Path

from _fixloopkit import MAIN_TEX, MockEngine

from texlate.compile.fixloop import Ruleset, load_ruleset
from texlate.compile.fixloop.engine import fixloop


@lru_cache(maxsize=1)
def _rs() -> Ruleset:
    return load_ruleset()


CLEAN_LOG = "This is XeTeX\nOutput written on main.pdf (1 page).\n"
_CLEAN_PLUS_FINAL = 2  # pass-1 收敛 + 同轮终编复编


def _run(tmp_path: Path, script: list) -> tuple[dict, MockEngine]:
    (tmp_path / "main.tex").write_text(MAIN_TEX, encoding="utf-8")
    eng = MockEngine(script)
    cell = fixloop(tmp_path, eng, ruleset=_rs())
    return cell, eng


def test_finalize_arm_fires_on_clean_pass1(tmp_path: Path) -> None:
    """正控：健康 pass-1 收敛 → 同轮终编照常补遍 (rungen_stub 通道不塌)。"""
    cell, eng = _run(tmp_path, [{"log": CLEAN_LOG, "pdf": True}] * 2)
    assert any("finalize" in e for e in cell["log"])
    assert eng.rounds >= _CLEAN_PLUS_FINAL
    assert cell["verdict"] == "clean"


def test_finalize_arm_skips_killed_signal(tmp_path: Path) -> None:
    """SIGPIPE 截杀轮：pdf + n_bang=0 俱全仍不终编 —— 产出未证，且
    同轮重编会读上刚截断的 aux (2403.05523 幻影链)。"""
    cell, _eng = _run(
        tmp_path,
        [
            {"log": CLEAN_LOG, "pdf": True, "killed_signal": 13},
            {"log": CLEAN_LOG, "pdf": True},
        ],
    )
    assert not any("finalize" in e for e in cell["log"])
    assert cell["rounds"][0]["died"] is True
    assert cell["rounds"][0]["category"] == "killed"


def test_finalize_arm_skips_timed_out(tmp_path: Path) -> None:
    """超时轮回归：timed_out=True 同样不终编 (_res_died 子集语义不变)。"""
    cell, _eng = _run(
        tmp_path,
        [
            {"log": CLEAN_LOG, "pdf": True, "timed_out": True},
            {"log": CLEAN_LOG, "pdf": True},
        ],
    )
    assert not any("finalize" in e for e in cell["log"])
    assert cell["rounds"][0]["died"] is True
