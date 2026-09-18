"""cli.py 命令面：version + parse + run 子命令 + run --server 瘦客户端。

``run`` 的全链语义由 test_e2e 钉——这里打 CLI 侧契约：本地目录源分流、
引擎选项校验、退出码映射（0 clean|partial / 1 编译失败 / 2 拒绝或参数错）、
``--work-dir`` 保护与临时目录清理、``~`` 展开、fetcher 连接池关闭。
瘦客户端经 ``httpx.MockTransport`` 全离线驱动：提交/409 attach/快照终态/
产物 sha256 对账/lost·needs_auth 短路。typer CliRunner 三流分离：JSON 报告
在 ``result.stdout``、诊断在 ``result.stderr``（``output`` 是混合流，不做解析面）。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
from typing import TYPE_CHECKING

import httpx
from typer.testing import CliRunner

from texlate import cli, e2e
from texlate.arxiv.cache import SourceCache
from texlate.cli import app
from texlate.server.store import DDL

if TYPE_CHECKING:
    from collections.abc import Callable
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
    "\\documentstyle{ias}\n\\begin{document}\nLaTeX 2.09 body.\n\\end{document}\n"
)

_RUNNER = CliRunner()


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


def _patch_httpx(
    monkeypatch: pytest.MonkeyPatch, handler: Callable[[httpx.Request], httpx.Response]
) -> list[str]:
    """``httpx.Client`` 换 ``MockTransport`` 背板——返回请求路径流水供断言。"""
    calls: list[str] = []

    def _h(request: httpx.Request) -> httpx.Response:
        calls.append(f"{request.method} {request.url.path}")
        return handler(request)

    real = httpx.Client

    def _factory(*a: object, **kw: object) -> httpx.Client:
        kw["transport"] = httpx.MockTransport(_h)
        return real(*a, **kw)

    monkeypatch.setattr(httpx, "Client", _factory)
    return calls


class TestThinRun:
    """``run --server`` 瘦客户端：MockTransport 全离线——提交/轮询/下载/退出码。"""

    _TASK = "t_thin01"

    def _handler_ok(self, blob: bytes, sha: str) -> Callable:
        def handler(req: httpx.Request) -> httpx.Response:
            p = req.url.path
            if p.endswith("/translate"):
                return httpx.Response(
                    200, json={"task_id": self._TASK, "status": "queued"}
                )
            if p == f"/api/task/{self._TASK}":
                return httpx.Response(
                    200,
                    json={
                        "status": "done",
                        "stage": "compile",
                        "progress": 100,
                        "counters": {"done": 5, "total": 5, "failed": 0},
                    },
                )
            if p == f"/api/files/{self._TASK}":
                return httpx.Response(
                    200,
                    json={
                        "artifacts": {
                            "zh.pdf": {
                                "url": f"/api/files/{self._TASK}/zh.pdf",
                                "sha256": sha,
                            }
                        }
                    },
                )
            if p == f"/api/files/{self._TASK}/zh.pdf":
                return httpx.Response(200, content=blob)
            return httpx.Response(404)

        return handler

    def _invoke(self, *args: str) -> object:
        return _RUNNER.invoke(
            app, ["run", "2001.00001v2", "--server", "http://s", *args]
        )

    def test_done_downloads_artifacts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """终态 done → 产物逐件流式下载 + sha256 对账 → exit 0。"""
        blob = b"%PDF-zh fake"
        sha = hashlib.sha256(blob).hexdigest()
        _patch_httpx(monkeypatch, self._handler_ok(blob, sha))
        out = tmp_path / "o"
        result = self._invoke("--out", str(out))
        assert result.exit_code == 0, result.output
        rep = json.loads(result.stdout)
        assert rep["task_id"] == self._TASK
        assert rep["status"] == "done"
        assert rep["artifacts"]["zh.pdf"] == str(out / "zh.pdf")
        assert (out / "zh.pdf").read_bytes() == blob
        assert not list(out.glob("*.part"))  # 临时件不残留

    def test_conflict_attach_existing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """409 duplicate_active → 复用其 task_id attach → 正常等终态。"""
        blob = b"%PDF-zh"
        sha = hashlib.sha256(blob).hexdigest()
        ok = self._handler_ok(blob, sha)

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path.endswith("/translate"):
                return httpx.Response(
                    409, json={"detail": "duplicate_active", "task_id": self._TASK}
                )
            return ok(req)

        _patch_httpx(monkeypatch, handler)
        result = self._invoke("--out", str(tmp_path / "o"))
        assert result.exit_code == 0, result.output
        assert "attach 进行中任务 t_thin01" in result.stderr

    def test_lost_skips_download(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """快照非 200 → lost → exit 1，且不再请求产物清单（端点已失联）。"""
        calls = _patch_httpx(
            monkeypatch,
            lambda req: (
                httpx.Response(200, json={"task_id": self._TASK, "status": "queued"})
                if req.url.path.endswith("/translate")
                else httpx.Response(404, json={"detail": "gone"})
            ),
        )
        result = self._invoke()
        assert result.exit_code == 1
        assert json.loads(result.stdout)["status"] == "lost"
        assert not any("/api/files/" in c for c in calls)

    def test_needs_auth_skips_download(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """终态 needs_auth → exit 2；任务未产出 → 不打产物清单。"""
        calls = _patch_httpx(
            monkeypatch,
            lambda req: (
                httpx.Response(200, json={"task_id": self._TASK, "status": "queued"})
                if req.url.path.endswith("/translate")
                else httpx.Response(200, json={"status": "needs_auth"})
            ),
        )
        result = self._invoke()
        assert result.exit_code == 2  # noqa: PLR2004
        assert not any("/api/files/" in c for c in calls)

    def test_non_dict_snapshot_is_lost(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """快照 200 但非对象 JSON → 不当崩溃（AttributeError）而是 lost exit 1。"""
        _patch_httpx(
            monkeypatch,
            lambda req: (
                httpx.Response(200, json={"task_id": self._TASK, "status": "queued"})
                if req.url.path.endswith("/translate")
                else httpx.Response(200, json=["not", "a", "dict"])
            ),
        )
        result = self._invoke()
        assert result.exit_code == 1
        assert "快照非法" in result.stderr
        assert "Traceback" not in result.output

    def test_wait_zero_times_out(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """--wait 0 + 非终态快照 → 立即超时 exit 1 + attach 提示。"""
        _patch_httpx(
            monkeypatch,
            lambda req: (
                httpx.Response(200, json={"task_id": self._TASK, "status": "queued"})
                if req.url.path.endswith("/translate")
                else httpx.Response(
                    200,
                    json={
                        "status": "running",
                        "stage": "xlat",
                        "progress": 40,
                        "counters": {"done": 2, "total": 5, "failed": 0},
                    },
                )
            ),
        )
        result = self._invoke("--wait", "0")
        assert result.exit_code == 1
        assert "等待超时" in result.stderr
        assert "attach" in result.stderr

    def test_submit_rejected_exit_2(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """提交被拒（422）→ exit 2 干净报错。"""
        _patch_httpx(
            monkeypatch,
            lambda _req: httpx.Response(422, json={"detail": "bad id"}),
        )
        result = self._invoke()
        assert result.exit_code == 2  # noqa: PLR2004
        assert "translate 422" in result.stderr

    def test_sha256_mismatch_skips_artifact(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """产物 sha256 不符 → 跳过该件不留盘，任务本身 done → exit 0。"""
        _patch_httpx(monkeypatch, self._handler_ok(b"%PDF-real", "f" * 64))
        out = tmp_path / "o"
        result = self._invoke("--out", str(out))
        assert result.exit_code == 0, result.output
        assert "sha256 不符" in result.stderr
        rep = json.loads(result.stdout)
        assert rep["artifacts"] == {}
        assert not (out / "zh.pdf").exists()
        assert not list(out.glob("*.part"))

    def test_traversal_artifact_name_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """产物 url 末段 ``..`` → 跳过且不发请求（防 dest 外逃逸）。"""
        blob = b"%PDF-zh"
        sha = hashlib.sha256(blob).hexdigest()
        ok = self._handler_ok(blob, sha)

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == f"/api/files/{self._TASK}":
                return httpx.Response(
                    200,
                    json={
                        "artifacts": {
                            "evil": {
                                "url": f"/api/files/{self._TASK}/..",
                                "sha256": sha,
                            },
                            "zh.pdf": {
                                "url": f"/api/files/{self._TASK}/zh.pdf",
                                "sha256": sha,
                            },
                        }
                    },
                )
            return ok(req)

        calls = _patch_httpx(monkeypatch, handler)
        out = tmp_path / "o"
        result = self._invoke("--out", str(out))
        assert result.exit_code == 0, result.output
        assert "产物名非法" in result.stderr
        rep = json.loads(result.stdout)
        assert set(rep["artifacts"]) == {"zh.pdf"}
        assert (out / "zh.pdf").is_file()
        assert not any(c.endswith((" /..", "/..")) for c in calls)

    def test_empty_artifacts_no_dir_residue(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """产物清单为空 → 不建默认 ``texlate-{id}-{task}`` 目录（cwd 零残渣）。"""
        ok = self._handler_ok(b"%PDF-zh", "f" * 64)

        def handler(req: httpx.Request) -> httpx.Response:
            if req.url.path == f"/api/files/{self._TASK}":
                return httpx.Response(200, json={"artifacts": {}})
            return ok(req)

        _patch_httpx(monkeypatch, handler)
        monkeypatch.chdir(tmp_path)
        result = self._invoke()
        assert result.exit_code == 0, result.output
        assert not list(tmp_path.iterdir())

    def test_all_fetches_fail_removes_new_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """产物全下载失败 → 本调用新建的空壳目录回收，不留空 dir。"""
        _patch_httpx(monkeypatch, self._handler_ok(b"%PDF-zh", "f" * 64))
        monkeypatch.chdir(tmp_path)
        result = self._invoke()
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["artifacts"] == {}
        assert not list(tmp_path.iterdir())


def _mk_task_dir(data: Path, task_id: str = "t_thincli01") -> Path:
    """合成 ``<data>/tasks/<id>`` 产物 + ``texlate.db`` 任务行（share pack 前置）。"""
    tdir = data / "tasks" / task_id
    tdir.mkdir(parents=True)
    (tdir / "dual.json").write_text("{}", encoding="utf-8")
    (tdir / "zh.pdf").write_bytes(b"%PDF-1.4")
    conn = sqlite3.connect(str(data / "texlate.db"))
    try:
        conn.executescript(DDL)
        conn.execute(
            "INSERT INTO tasks (id, kind, status, arxiv_id, source_name,"
            " target_lang, model, config_json, options_json, cache_key,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                task_id,
                "arxiv",
                "done",
                "2001.00001v1",
                "",
                "zh-CN",
                "m",
                "{}",
                "{}",
                "",
                0.0,
                0.0,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return tdir


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
        tdir = _mk_task_dir(data)
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
