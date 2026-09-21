"""cli.py 命令面：version + parse + run 子命令 + web/share 面。

``run`` 的全链语义由 test_e2e 钉——这里打 CLI 侧契约：本地目录源分流、
引擎选项校验、退出码映射（0 clean|partial / 1 编译失败 / 2 拒绝或参数错）、
``--work-dir`` 保护与临时目录清理、``~`` 展开、fetcher 连接池关闭。
``run --server`` 瘦客户端块（MockTransport 背板 + SSE 实况帧）拆出至
``test_cli_thin``。typer CliRunner 三流分离：JSON 报告在 ``result.stdout``、
诊断在 ``result.stderr``（``output`` 是混合流，不做解析面）。
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from typing import TYPE_CHECKING

import pytest
from conftest import failing_engine, mk_task_dir
from typer.testing import CliRunner

from texlate import cli, e2e
from texlate.arxiv.cache import SourceCache
from texlate.cli import app

if TYPE_CHECKING:
    from pathlib import Path

    from conftest import RecordingEngine

_MAIN = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "A paragraph of English text long enough to produce a translation chunk.\n"
    "\\end{document}\n"
)

_DOCSTYLE = (
    "\\documentstyle{ias}\n\\begin{document}\nLaTeX 2.09 body.\n\\end{document}\n"
)

_RUNNER = CliRunner()


@pytest.fixture(autouse=True)
def _plain_terminal_env(plain_terminal: None) -> None:
    """钉无色彩端——纯文本 stderr 断言前提（conftest ``plain_terminal`` 全文件套用）。

    ``FORCE_COLOR``/``TTY_COMPATIBLE`` 会把 rich ``is_terminal`` 顶成 True
    （CliRunner 捕获非 tty 也开 Live 进度条与转义序列），须摘除；
    ``console._color_system`` 又在 import 时已按当时环境冻结，运行期摘 env
    不改已缓存的色域——须置 None 让 ``style.render`` 走无色路径。
    """


def _src(tmp_path: Path, body: str = _MAIN) -> Path:
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.tex").write_text(body, encoding="utf-8")
    return src


def _seed_cache(cache_root: Path, arxiv_id: str, version: int = 1) -> None:
    """离线铺一条 src-cache 钉版条目：extracted/ 内放 _MAIN 工程。"""
    cache = SourceCache(cache_root)
    staging = cache.stage()
    extracted = staging / "extracted"
    extracted.mkdir()
    (extracted / "main.tex").write_text(_MAIN, encoding="utf-8")
    (staging / "meta.json").write_text(
        json.dumps({"resolved_version": version}), encoding="utf-8"
    )
    cache.commit(staging, arxiv_id, version)


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
        r"""``\documentstyle`` 工程 → inject 层拒 → partial+reject_at → exit 2。"""
        src = _src(tmp_path, body=_DOCSTYLE)
        result = _RUNNER.invoke(
            app, ["run", str(src), "--work-dir", str(tmp_path / "w")]
        )
        assert result.exit_code == 2  # noqa: PLR2004
        rep = json.loads(result.stdout)
        assert rep["status"] == "partial"  # F3: reject 合成 partial
        assert rep["reject_at"] == "inject"

    def test_compile_fail_exit_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """编译无 pdf → status fail → exit 1（修复链走尽仍无 pdf）。"""
        monkeypatch.setattr(e2e, "engine_for", failing_engine)
        for key in ("TEXLATE_ENV_JUDGE", "TEXLATE_NO_L2", "TEXLATE_NO_FIXLOOP"):
            monkeypatch.delenv(key, raising=False)
        src = _src(tmp_path)
        result = _RUNNER.invoke(
            app, ["run", str(src), "--work-dir", str(tmp_path / "w")]
        )
        assert result.exit_code == 1
        assert json.loads(result.stdout)["status"] == "fail"

    def test_offline_miss_exit_1(self, tmp_path: Path) -> None:
        """--offline + 空缓存 → offline_no_cache → exit 1，不静默联网。"""
        result = _RUNNER.invoke(
            app,
            ["run", "2001.00001", "--offline", "--cache", str(tmp_path / "c")],
        )
        assert result.exit_code == 1
        rep = json.loads(result.stdout)
        assert rep["status"] == "error"
        assert "offline_no_cache" in rep["detail"]

    def test_offline_env_flag_miss(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """TEXLATE_OFFLINE=1 等效 --offline：无缓存同样 exit 1。"""
        monkeypatch.setenv("TEXLATE_OFFLINE", "1")
        result = _RUNNER.invoke(
            app, ["run", "2001.00001", "--cache", str(tmp_path / "c")]
        )
        assert result.exit_code == 1
        assert "offline_no_cache" in json.loads(result.stdout)["detail"]

    def test_offline_hit_full_pipeline(
        self,
        tmp_path: Path,
        fake_engine: dict[str, RecordingEngine],
    ) -> None:
        """--offline 命中钉版缓存 → 全链照跑 → exit 0 + status clean。"""
        cache_root = tmp_path / "c"
        _seed_cache(cache_root, "2001.00001")
        result = _RUNNER.invoke(
            app,
            [
                "run",
                "2001.00001",
                "--offline",
                "--cache",
                str(cache_root),
                "--work-dir",
                str(tmp_path / "w"),
            ],
        )
        assert result.exit_code == 0, result.output
        # stdout 是两段 JSON：_echo_acquire 一行 + verdict indent=2 块。
        first = json.loads(result.stdout.splitlines()[0])
        assert first["status"] == "cache_hit"
        assert first["detail"] == "offline"
        assert fake_engine

    def test_offline_local_dir_unaffected(
        self,
        tmp_path: Path,
        fake_engine: dict[str, RecordingEngine],
    ) -> None:
        """--offline + 本地目录源 → 分流不进缓存查找，全链 exit 0。"""
        src = _src(tmp_path)
        result = _RUNNER.invoke(
            app,
            ["run", str(src), "--offline", "--work-dir", str(tmp_path / "w")],
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["status"] == "clean"
        assert fake_engine  # 引擎确实被驱动

    def test_wait_without_server_exit_2(self, tmp_path: Path) -> None:
        """``--wait``（含显式默认值 1800）脱离 --server → exit 2 不误放。"""
        src = _src(tmp_path)
        result = _RUNNER.invoke(app, ["run", str(src), "--wait", "1800"])
        assert result.exit_code == 2  # noqa: PLR2004
        assert "仅配合 --server" in result.stderr

    def test_source_tilde_expands(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        fake_engine: dict[str, RecordingEngine],
    ) -> None:
        """引号包住未展开的 ``~/dir`` 源 → expanduser 后按本地目录分流。"""
        home = tmp_path / "home"
        (home / "proj").mkdir(parents=True)
        (home / "proj" / "main.tex").write_text(_MAIN, encoding="utf-8")
        monkeypatch.setenv("HOME", str(home))
        result = _RUNNER.invoke(
            app, ["run", "~/proj", "--work-dir", str(tmp_path / "w")]
        )
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["status"] == "clean"
        assert fake_engine

    def test_copytree_failure_cleans_mkdtemp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """copytree 抛 OSError → exit 1 干净报错 + mkdtemp 目录不残留。"""
        src = _src(tmp_path)

        def _boom(*_a: object, **_kw: object) -> None:
            msg = "simulated disk full"
            raise OSError(msg)

        # mkdtemp 钉进本用例私有 tmp_path——gettempdir() 共享目录断言会吃
        # 并行 pytest 会话并发增删 texlate-run-* 的互踩 flake。
        monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
        monkeypatch.setattr(shutil, "copytree", _boom)
        result = _RUNNER.invoke(app, ["run", str(src)])
        assert result.exit_code == 1
        assert "工作目录准备失败" in result.stderr
        assert not list(tmp_path.glob("texlate-run-*"))


class TestParse:
    def test_parse_summary_and_out(self, tmp_path: Path) -> None:
        src = _src(tmp_path) / "main.tex"
        out = tmp_path / "chunks.jsonl"
        result = _RUNNER.invoke(app, ["parse", str(src), "-o", str(out)])
        assert result.exit_code == 0, result.output
        rep = json.loads(result.stdout)
        assert rep["chunks"] >= 1
        lines = out.read_text(encoding="utf-8").splitlines()
        assert all(json.loads(line)["content"] for line in lines)

    def test_out_same_as_input_refused(self, tmp_path: Path) -> None:
        """``-o`` 指向输入自身 → exit 2 拒写（读毕再写会截断源文件）。"""
        src = _src(tmp_path) / "main.tex"
        result = _RUNNER.invoke(app, ["parse", str(src), "-o", str(src)])
        assert result.exit_code == 2  # noqa: PLR2004
        assert "拒绝覆写" in result.stderr
        assert "documentclass" in src.read_text(encoding="utf-8")

    def test_out_unwritable_exit_1(self, tmp_path: Path) -> None:
        """``-o`` 父目录不存在 → OSError 归一干净报错，不抛 traceback。"""
        src = _src(tmp_path) / "main.tex"
        out = tmp_path / "nope" / "chunks.jsonl"
        result = _RUNNER.invoke(app, ["parse", str(src), "-o", str(out)])
        assert result.exit_code == 1
        assert "不可写" in result.stderr
        assert "Traceback" not in result.output


class TestFetch:
    def test_offline_closes_fetcher_client(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``acquire_source`` 用完 Fetcher 显式关 httpx.Client 连接池。"""
        made: list[cli.Fetcher] = []
        real = cli.Fetcher

        def _factory(*a: object, **kw: object) -> cli.Fetcher:
            f = real(*a, **kw)
            made.append(f)
            return f

        monkeypatch.setattr(cli, "Fetcher", _factory)
        result = _RUNNER.invoke(
            app, ["fetch", "2001.00001", "--offline", "--cache", str(tmp_path)]
        )
        assert result.exit_code == 1  # 空缓存 offline_no_cache
        assert made, "fetcher 未构造"
        assert all(f.client.is_closed for f in made)


class TestWeb:
    """``web`` 命令：``configure_server_logging`` 接线——``<data_dir>/logs/`` 落盘。"""

    def test_web_installs_file_logging(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """起服路径装 server 日志：``uvicorn.run`` 前 ``<data_dir>/logs/texlate.log`` 就位。"""
        import uvicorn  # noqa: PLC0415 -- server extra（dev env 在场）

        import texlate.server.app as sapp  # noqa: PLC0415

        runs: list[tuple] = []
        monkeypatch.setattr(uvicorn, "run", lambda *a, **k: runs.append((a, k)))
        monkeypatch.setattr(sapp, "create_app", object)
        result = _RUNNER.invoke(app, ["web", "--data-dir", str(tmp_path)])
        assert result.exit_code == 0, result.output
        assert runs  # uvicorn.run 真被调
        assert (tmp_path / "logs" / "texlate.log").is_file()


class TestShareErrors:
    """share pack 的 CLI 侧错误归一：库读失败/写失败 → exit 1 不 traceback。"""

    def test_pack_corrupt_db_exit_1(self, tmp_path: Path) -> None:
        """texlate.db 在场但非 sqlite → ``sqlite3.Error`` 归一干净报错。"""
        data = tmp_path / "data"
        tdir = data / "tasks" / "t_corrupt01"
        tdir.mkdir(parents=True)
        (tdir / "dual.json").write_text("{}", encoding="utf-8")
        (tdir / "zh.pdf").write_bytes(b"%PDF-1.4")
        (data / "texlate.db").write_text("not a sqlite file", encoding="utf-8")
        result = _RUNNER.invoke(app, ["share", "pack", str(tdir)])
        assert result.exit_code == 1
        assert "任务库不可读" in result.stderr
        assert "Traceback" not in result.output

    def test_pack_out_under_file_exit_1(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``-o`` 落在已存在文件之下 → mkdir OSError 归一 exit 1。"""
        monkeypatch.setenv("TEXLATE_DATA_DIR", str(tmp_path / "env-data"))
        data = tmp_path / "data"
        tdir = mk_task_dir(
            data, "t_thincli01", {"dual.json": "{}", "zh.pdf": b"%PDF-1.4"}
        )
        blocker = tmp_path / "blocker"
        blocker.write_text("x", encoding="utf-8")
        result = _RUNNER.invoke(
            app, ["share", "pack", str(tdir), "-o", str(blocker / "x.zip")]
        )
        assert result.exit_code == 1
        assert "share pack:" in result.stderr
        assert "Traceback" not in result.output


def test_parse_fifo_refused(tmp_path: Path) -> None:
    """fifo/非正则文件：api 层 is_file 闸 → 干净报错不悬挂不 traceback。"""
    fifo = tmp_path / "pipe.tex"
    os.mkfifo(fifo)
    result = _RUNNER.invoke(app, ["parse", str(fifo)])
    assert result.exit_code == 2  # noqa: PLR2004
    assert "不可读" in result.stderr
    assert "Traceback" not in result.output
