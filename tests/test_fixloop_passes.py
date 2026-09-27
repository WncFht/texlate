r"""passes 分层 (perf-fix): 分类轮 p1 / 收敛轮同轮 ``compile_passes`` 终编。

修复轮分类只需 pass-1 log; 收敛轮探到收敛后同轮全遍终编 (≤自适应上限
传 None 等值语义, >2 显式诉求原样透传); tectonic 自定遍数引擎豁免复编;
终编浮出新错回流重分类。另钉 ``_report_of`` 的 ``res.log_text`` 优先
(fix#10) 与 ``_bounded_sub`` regex 超时臂零线程泄漏。
"""

import threading
import time
from pathlib import Path

import regex
from test_fixloop_loop import (
    CLEAN_LOG,
    MockEngine,
    MockRes,
    MockTectonic,
    make_proj,
    mini_rs,
)

from texlate.compile.fixloop import actions, fixloop
from texlate.compile.fixloop.engine import _report_of


# ---------------------------------------------------------------- passes 分层 (perf-fix: 分类轮 p1 / 终编轮全遍)
class _CallsRecorder:
    """每次 compile 的 ``(passes, best_effort)`` 落 ``self.calls`` (mixin)。"""

    def __init__(self, script: list, **kw: object) -> None:
        super().__init__(script, **kw)
        self.calls: list[dict[str, object]] = []

    def compile(
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 2,
        best_effort: bool = False,
        **kw: object,
    ) -> MockRes:
        self.calls.append({"passes": passes, "best_effort": best_effort})
        return super().compile(wdir, main, passes=passes, best_effort=best_effort, **kw)


class PassRecordingEngine(_CallsRecorder, MockEngine):
    """xelatex 形引擎的记录臂——分层断言用。"""


class PassRecordingTectonic(_CallsRecorder, MockTectonic):
    """同上的 tectonic 臂——``del passes`` 自定遍数引擎的复编豁免断言。"""


def test_classify_rounds_pass1_final_pass2(tmp_path: Path) -> None:
    """修复轮分类只需 pass-1 log；收敛轮同轮 ``compile_passes`` 终编定稿。"""
    eng = PassRecordingEngine(
        [
            {"log": "! LaTeX Error: File `zhnumber.sty' not found.\n"},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"zhnumber.sty"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert len(cell["rounds"]) == 2  # noqa: PLR2004 - 修复轮 + 收敛轮
    # r1 分类轮 p1; r2 收敛轮 p1 探 + 终编——compile_passes=2 ≤自适应上限
    # → passes=None (rerun-hint 才升遍, 引擎 MAX_PASSES=2 同值语义)
    assert [c["passes"] for c in eng.calls] == [1, 1, None]
    assert not any(c["best_effort"] for c in eng.calls)


def test_first_round_clean_probes_then_finalizes(tmp_path: Path) -> None:
    """首轮即收敛: p1 探到 clean → 同轮全遍复编——成品仍经第二遍 \\write 填实。"""
    eng = PassRecordingEngine([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert len(cell["rounds"]) == 1
    assert [c["passes"] for c in eng.calls] == [1, None]


def test_nonconverging_cell_all_pass1(tmp_path: Path) -> None:
    """不产成品的格: 分类轮 + salvage 兜底全 p1——无收敛终编轮。"""
    eng = PassRecordingEngine([{"log": "! Undefined control sequence.\nl.5 \\mycs\n"}])
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "unfixable:undefined_cs"
    assert eng.calls, "至少一轮分类编译"
    assert [c["passes"] for c in eng.calls] == [1] * len(eng.calls)
    assert eng.calls[-1]["best_effort"] is True  # 末次是 salvage 兜底轮


def test_tectonic_converge_no_finalize_recompile(tmp_path: Path) -> None:
    """tectonic 自定遍数 (impl ``del passes``)——收敛轮不复编, 全程一次 compile。"""
    eng = PassRecordingTectonic([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng, engine_name="tectonic")
    assert cell["verdict"] == "clean"
    assert [c["passes"] for c in eng.calls] == [1]


def test_finalize_recompile_resurfaces_errors(tmp_path: Path) -> None:
    """pass-2-emergent: p1 探收敛但终编复编出新错 → 重分类回流修复路径。

    r2 p1 clean → 全遍复编冒出 missing_file:other.sty → 装包续轮；
    r3 再收敛终编 → clean。终编轮错误不吞、轮记账按全遍结果。
    """
    eng = PassRecordingEngine(
        [
            {"log": "! LaTeX Error: File `zhnumber.sty' not found.\n"},
            {"log": CLEAN_LOG, "pdf": True},
            {"log": "! LaTeX Error: File `other.sty' not found.\n", "pdf": True},
            {"log": CLEAN_LOG, "pdf": True},
        ],
        installable={"zhnumber.sty", "other.sty"},
    )
    cell = fixloop(make_proj(tmp_path), eng)
    assert cell["verdict"] == "clean"
    assert len(cell["rounds"]) == 3  # noqa: PLR2004 - r1修 + r2终编浮err修 + r3收敛
    assert cell["rounds"][1]["category"] == "missing_file"
    assert cell["rounds"][1]["payload"] == "other.sty"
    assert [c["passes"] for c in eng.calls] == [1, 1, None, 1, None]
    assert {"zhnumber.sty", "other.sty"} <= set(cell["installed"])


def test_finalize_compile_passes_gt2_passthrough(tmp_path: Path) -> None:
    """``compile_passes > 2`` 超自适应上限的显式诉求——原样透传不吞成 None。"""
    rs = mini_rs(rules=[], taxonomy=[], loop_cfg={"compile_passes": 3})
    eng = PassRecordingEngine([{"log": CLEAN_LOG, "pdf": True}])
    cell = fixloop(make_proj(tmp_path), eng, ruleset=rs)
    assert cell["verdict"] == "clean"
    assert [c["passes"] for c in eng.calls] == [1, 3]


def test_report_of_prefers_compres_log_text(tmp_path: Path) -> None:
    """``_report_of`` 复用 ``res.log_text`` (fix#10)——盘面 .log 不再二次开读。

    log_text 与 .log 文件分歧时以 log_text (编译期读到的原文) 为准。
    """
    res = MockRes(tmp_path, "main.tex", {"log": "! BOOM on-disk\n", "pdf": True})
    res.log_text = "! CACHED in-memory\nl.9 \\x\n"
    rep = _report_of(res, [])
    assert rep.first == "! CACHED in-memory"
    assert rep.n_bang == 1


def test_bounded_sub_timeout_returns_none_no_leak() -> None:
    r"""病态 pattern 超时 → ``None`` 且零线程泄漏（``regex`` 原生 timeout 臂）。

    旧 daemon-thread 弃守形把 spinner 泄漏进进程——泄漏线程在 C 层回溯
    不放 GIL，整进程冻结（guardsmoke fixloop 格 Thread-4 utime 29min
    实证，2026-09-18）。``regex`` 的匹配环内 deadline 检查是真中断。
    """
    pat = regex.compile(r"(a|a)*$")
    before = threading.enumerate()
    t0 = time.monotonic()
    assert actions._bounded_sub(pat, "x", "a" * 30 + "b", timeout_s=0.5) is None  # noqa: SLF001
    assert time.monotonic() - t0 < 10  # noqa: PLR2004 -- 上限即超时闸本身
    assert threading.enumerate() == before
