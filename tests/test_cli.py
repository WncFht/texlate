"""cli.py 命令面：version + run 子命令（退出码/参数校验/--work-dir 保护）。

``run`` 的全链语义由 test_e2e 钉——这里打 CLI 侧契约：本地目录源分流、
引擎选项校验、退出码映射（0 clean|partial / 1 编译失败 / 2 拒绝或参数错）。
typer CliRunner 三流分离：JSON 报告在 ``result.stdout``、诊断在
``result.stderr``（``output`` 是混合流，不做解析面）。
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from typer.testing import CliRunner

from texlate import e2e
from texlate.cli import app

if TYPE_CHECKING:
    from pathlib import Path

    import pytest
    from conftest import RecordingEngine

_MAIN = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "A paragraph of English text long enough to produce a translation chunk.\n"
    "\\end{document}\n"
)

_DOCSTYLE = (
    "\\documentstyle{article}\n\\begin{document}\nLaTeX 2.09 body.\n\\end{document}\n"
)

_RUNNER = CliRunner()


def _src(tmp_path: Path, body: str = _MAIN) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(body, encoding="utf-8")
    return src


def test_version() -> None:
    result = _RUNNER.invoke(app, ["version"])
    assert result.exit_code == 0
    assert "texlate" in result.output


class TestRun:
    def test_local_dir_clean(
        self,
        tmp_path: Path,
        fake_engine: dict[str, RecordingEngine],
    ) -> None:
        """本地目录源 → 全链 → exit 0 + JSON 报告（status clean）。"""
        src = _src(tmp_path)
        work = tmp_path / "w"
        result = _RUNNER.invoke(
            app, ["run", str(src), "--work-dir", str(work), "--timeout", "30"]
        )
        assert result.exit_code == 0, result.output
        report = json.loads(result.stdout)
        assert report["status"] == "clean"
        assert report["main"] == "main.tex"
        assert "work dir:" in result.stderr
        assert fake_engine  # 引擎确实被驱动

    def test_unknown_engine_exit_2(self, tmp_path: Path) -> None:
        src = _src(tmp_path)
        result = _RUNNER.invoke(app, ["run", str(src), "--engine", "pdftex"])
        assert result.exit_code == 2  # noqa: PLR2004 -- typer 参数错误码
        assert "unknown --engine" in result.stderr

    def test_workdir_nonempty_refused(self, tmp_path: Path) -> None:
        """--work-dir 已存在且非空 → 拒删整树（exit 2）。"""
        src = _src(tmp_path)
        work = tmp_path / "w"
        work.mkdir()
        (work / "keep.txt").write_text("precious", encoding="utf-8")
        result = _RUNNER.invoke(app, ["run", str(src), "--work-dir", str(work)])
        assert result.exit_code == 2  # noqa: PLR2004
        assert "拒绝覆盖删除" in result.stderr
        assert (work / "keep.txt").is_file()  # 没被动

    def test_reject_exit_2(self, tmp_path: Path) -> None:
        r"""``\documentstyle`` 工程 → inject 层拒 → status reject → exit 2。"""
        src = _src(tmp_path, body=_DOCSTYLE)
        result = _RUNNER.invoke(
            app, ["run", str(src), "--work-dir", str(tmp_path / "w")]
        )
        assert result.exit_code == 2  # noqa: PLR2004
        assert json.loads(result.stdout)["status"] == "reject"

    def test_compile_fail_exit_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """编译无 pdf → status fail → exit 1（修复链走尽仍无 pdf）。"""
        from conftest import RecordingEngine  # noqa: PLC0415

        def factory(name: str, **kw: object) -> RecordingEngine:
            eng = RecordingEngine(name, **kw)
            eng.produce_pdf = False
            return eng

        monkeypatch.setattr(e2e, "engine_for", factory)
        for key in ("TEXLATE_ENV_JUDGE", "TEXLATE_NO_L2", "TEXLATE_NO_FIXLOOP"):
            monkeypatch.delenv(key, raising=False)
        src = _src(tmp_path)
        result = _RUNNER.invoke(
            app, ["run", str(src), "--work-dir", str(tmp_path / "w")]
        )
        assert result.exit_code == 1
        assert json.loads(result.stdout)["status"] == "fail"
