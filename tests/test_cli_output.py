"""``cli/_output`` 渲染件：fixloop 紧凑轮帧 + trace 噪音行过滤。

``fixloop_round_line`` 把 ``cell["rounds"]`` 单轮 dict 渲成一行摘要；
``log_line_filtered`` 在 ``texlate`` logger 未到 DEBUG 时隐去逐规则
``cond skip``/轮次小结/aux-sweep 清扫账——动作叙事行（apply/warn-preempt/
landing sync/wire）始终透传。``CliSink`` 端到端走 ``capsys``（console
动态解析 ``sys.stderr``）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pytest

from texlate.cli._output import (
    CliSink,
    console,
    fixloop_round_line,
    log_line_filtered,
)

if TYPE_CHECKING:
    from typing import Any

_LOG = logging.getLogger("texlate.cli._output")


@pytest.fixture(autouse=True)
def _default_level(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉 WARNING 有效级——不管全局 configure_logging 痕迹，缺省即过滤态。"""
    monkeypatch.setattr(_LOG, "level", logging.WARNING)
    # isEnabledFor 结果有 _cache, setattr(level) 不清——走 manager 全清
    _LOG.manager._clear_cache()  # noqa: SLF001


@pytest.fixture(autouse=True)
def _plain_terminal_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉无色彩端——纯文本断言前提。

    ``FORCE_COLOR``/``TTY_COMPATIBLE`` 会把 rich ``is_terminal`` 顶成 True
    （capsys 捕获非 tty 也出 ANSI），须摘除；``console._color_system`` 又在
    import 时已按当时环境冻结，运行期摘 env 不改已缓存的色域——须置 None
    让 ``style.render`` 走无色路径。
    """
    for key in ("FORCE_COLOR", "TTY_COMPATIBLE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(console, "_color_system", None)


def _round(**kw: object) -> dict[str, Any]:
    base: dict[str, Any] = {
        "round": 1,
        "pdf": True,
        "pdf_bytes": 1024,
        "died": False,
        "driver_fatal": None,
        "n_errors": 68,
        "category": "missing_file",
        "payload": "plex-sans.sty",
        "warnings": [],
        "warnings_sys": [],
        "line_no": 94,
        "file_stack": ["main.tex", "phai.cls"],
        "sec": 15.7,
    }
    base.update(kw)
    return base


class TestFixloopRoundLine:
    def test_full_round(self) -> None:
        line = fixloop_round_line(_round())
        assert line == (
            "fixloop r1 missing_file:plex-sans.sty err=68 at=phai.cls:94 (15.7s)"
        )

    def test_nopdf_died_fatal_warn(self) -> None:
        line = fixloop_round_line(
            _round(
                pdf=False,
                died=True,
                driver_fatal="halt",
                warnings=["missing_char"],
                n_errors=0,
            )
        )
        assert "nopdf" in line
        assert "died" in line
        assert "fatal:halt" in line
        assert "warn=missing_char" in line

    def test_salvage_and_bare_cat(self) -> None:
        line = fixloop_round_line(
            _round(round=5, salvage=True, category=None, payload=None)
        )
        assert line.startswith("fixloop r5 salvage")
        assert "missing_file" not in line

    def test_abs_stack_basename(self) -> None:
        line = fixloop_round_line(_round(file_stack=["/w/main.tex", "/w/cls/phai.cls"]))
        assert "at=phai.cls:94" in line

    def test_minimal(self) -> None:
        line = fixloop_round_line({"round": 2})
        assert line == "fixloop r2 nopdf"


class TestLogLineFiltered:
    @pytest.mark.parametrize(
        "msg",
        [
            "fixloop: rule missing_char_fix: cond skip (no new cps)",
            "fixloop: gate plain_format_route: cond skip (not plain)",
            "fixloop: precheck input_sty_209_requirepkg: cond skip (x)",
            "fixloop: rule graphics_include_strip: skip (sites stripped)",
            "fixloop: rule llm_patch: escalate skip (no hook)",
            "fixloop: precheck static_precheck: skip on xelatex",
            "fixloop: precheck whatever: unsupported on tectonic",
            "fixloop: r1: pdf=True err=68 cat=missing_file pay=x (15.7s)",
            "fixloop: r1 aux-sweep: .aux, .log",
            "fixloop: salvage aux-sweep: .aux",
            "fixloop: final aux-sweep: .aux",
        ],
    )
    def test_noise_dropped(self, msg: str) -> None:
        assert log_line_filtered(msg)

    @pytest.mark.parametrize(
        "msg",
        [
            "fixloop: wire filemap overrides",
            "fixloop: wire ctan_fetch (lazy tlpdb index)",
            "fixloop: precheck static_precheck: degrade on tectonic",
            "fixloop: apply install_file: already-present plex-sans.sty",
            "fixloop: r2 warn-preempt -> missing_char_fix (warmup)",
            "fixloop: warn-preempt: 14 residual cps, no arm applied",
            "fixloop: landing sync: 3 external landing(s)",
            "fixloop: r1 finalize: pass-1 clean → 2-pass (pdf=True err=0)",
            "fixloop: r1 secondary probe: err=4",
            "fixloop: salvage best_effort: pdf=True err=2",
            "fixloop: floor: entry pdf restored (was dirty_pdf)",
            "fixloop: run latexmk -xelatex -> rc=0",
            "fixloop: 主文件判定 main.tex ≠ a.tex",
            "anything else entirely",
        ],
    )
    def test_narrative_kept(self, msg: str) -> None:
        assert not log_line_filtered(msg)

    def test_debug_level_shows_all(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``-vv``/``TEXLATE_LOG=debug`` → DEBUG 有效级，全量 trace 放行。"""
        monkeypatch.setattr(_LOG, "level", logging.DEBUG)
        _LOG.manager._clear_cache()  # noqa: SLF001
        assert not log_line_filtered("fixloop: rule x: cond skip (y)")


class TestCliSink:
    def test_log_filters_noise_keeps_narrative(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sink = CliSink()
        sink.log("fixloop: rule x: cond skip (y)")
        sink.log("fixloop: r1: pdf=True err=1 cat=a pay=b (1.0s)")
        sink.log("fixloop: apply install_file: already-present plex-sans.sty")
        err = capsys.readouterr().err
        assert "cond skip" not in err
        assert "pdf=True" not in err
        assert "apply install_file" in err

    def test_fixloop_round_compact_and_done(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sink = CliSink()
        sink.event("fixloop", {"phase": "round", "round": _round()})
        sink.event(
            "fixloop",
            {"phase": "done", "cell": {"verdict": "dirty_pdf", "rounds": [{}, {}]}},
        )
        err = capsys.readouterr().err
        assert "fixloop r1 missing_file:plex-sans.sty err=68" in err
        assert "'pdf_bytes'" not in err  # 不再是整 dict repr
        assert "fixloop done verdict=dirty_pdf rounds=2" in err

    def test_fixloop_round_non_dict_fallback(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sink = CliSink()
        sink.event("fixloop", {"phase": "round", "round": 3})
        assert "fixloop round 3" in capsys.readouterr().err

    def test_verdict_summary_line(self, capsys: pytest.CaptureFixture[str]) -> None:
        sink = CliSink()
        sink.event(
            "verdict",
            {
                "status": "partial",
                "verdict": {
                    "category": "undefined_cs",
                    "payload": "DeclareKeys",
                    "n_errors": 261,
                    "missing_chars": 26476,
                },
            },
        )
        err = capsys.readouterr().err
        assert "done partial undefined_cs:DeclareKeys errors=261 missing=26476" in err

    def test_verdict_clean_bare(self, capsys: pytest.CaptureFixture[str]) -> None:
        sink = CliSink()
        sink.event("verdict", {"status": "clean", "verdict": {}})
        assert "done clean" in capsys.readouterr().err
