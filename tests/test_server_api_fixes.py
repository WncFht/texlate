"""review-web-2026-09-17 后端 API 修复钉板（fix-be-api 批）。

gate 双闸（peer 回环 + Host 缺席 fail-closed）/ tasks 分页+total /
options 序列化尺寸帽 / file_get TOCTOU→404 / retry 先守卫迁移后清理
（清理失败转 fault）/ delete 条件写 / 孤儿 tasks/ 目录启动清扫 /
server 形态跨租户 reuse 物化口径 / IntegrityError→409 /
_validation_400 可读 detail / ``web --host`` 非回环警告。
"""

from __future__ import annotations

from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")
pytest.importorskip("uvicorn", reason="server extra 未装")

from conftest import force_status, get_row, make_app, mk_api_task, reg_artifact
from starlette.testclient import TestClient
from typer.testing import CliRunner

import texlate.cli as cli_mod
from texlate.server.app import _loopback_bind
from texlate.server.store import StoreError

if TYPE_CHECKING:
    from pathlib import Path

ARXIV = "2401.00031"
KEY_A = {"X-Texlate-Key": "sk-tenant-a"}
KEY_B = {"X-Texlate-Key": "sk-tenant-b"}
_RUNNER = CliRunner()


class TestPeerGate:
    """local 形态双闸：TCP 对端回环 + Host 白名单（伪造 Host 绕不过 peer 闸）。"""

    def test_missing_host_403(self, client: TestClient) -> None:
        r = client.get("/api/health", headers={"Host": ""})
        assert r.status_code == HTTPStatus.FORBIDDEN

    def test_non_loopback_peer_403(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """外网对端发 ``Host: localhost`` 照样死——peer 是网络层事实。"""
        with TestClient(make_app(tmp_path), client=("8.8.8.8", 1234)) as c:
            r = c.get("/api/health")
        assert r.status_code == HTTPStatus.FORBIDDEN
        assert "peer" in r.json()["detail"]

    def test_loopback_peer_ok(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        with TestClient(make_app(tmp_path), client=("127.0.0.1", 1234)) as c:
            assert c.get("/api/health").status_code == HTTPStatus.OK

    def test_mapped_v6_loopback_ok(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """``::`` 双栈监听下 IPv4 对端以 ::ffff:127.x 呈现——归一后回环。"""
        with TestClient(make_app(tmp_path), client=("::ffff:127.0.0.1", 1234)) as c:
            assert c.get("/api/health").status_code == HTTPStatus.OK


class TestLoopbackBind:
    def test_loopback_true(self) -> None:
        for host in ("127.0.0.1", "localhost", "::1", "a.localhost"):
            assert _loopback_bind(host), host

    def test_non_loopback_false(self) -> None:
        for host in (
            "0.0.0.0",  # noqa: S104 -- 字符串比较非绑定
            "::",
            "example.lan",
            "",
        ):
            assert not _loopback_bind(host), host


class TestTasksPagination:
    def test_limit_offset_total(self, client: TestClient) -> None:
        for i in range(5):
            mk_api_task(client, f"2401.0004{i}")
        r = client.get("/api/tasks", params={"limit": 2, "offset": 0})
        assert r.status_code == HTTPStatus.OK
        body = r.json()
        assert body["total"] == 5  # noqa: PLR2004 -- 样本量
        assert len(body["tasks"]) == 2  # noqa: PLR2004 -- page size
        ids = {t["task_id"] for t in body["tasks"]}
        r2 = client.get("/api/tasks", params={"limit": 2, "offset": 4})
        body2 = r2.json()
        assert body2["total"] == 5  # noqa: PLR2004
        assert len(body2["tasks"]) == 1
        assert not ids & {t["task_id"] for t in body2["tasks"]}

    def test_default_limit_back_compat(self, client: TestClient) -> None:
        """无参请求仍回全量（≤100）+ total 键。"""
        tid = mk_api_task(client, ARXIV)
        body = client.get("/api/tasks").json()
        assert body["total"] == 1
        assert body["tasks"][0]["task_id"] == tid

    def test_status_filter(self, client: TestClient) -> None:
        tid = mk_api_task(client, "2401.00050")
        force_status(client, tid, "done")
        mk_api_task(client, "2401.00051")  # queued
        body = client.get("/api/tasks", params={"status": "done"}).json()
        assert body["total"] == 1
        assert [t["task_id"] for t in body["tasks"]] == [tid]

    def test_limit_validation_400(self, client: TestClient) -> None:
        for bad in ("0", "1001", "abc"):
            r = client.get("/api/tasks", params={"limit": bad})
            assert r.status_code == HTTPStatus.BAD_REQUEST, bad
        detail = client.get("/api/tasks", params={"limit": "abc"}).json()["detail"]
        assert "limit" in detail  # _validation_400 出 loc:msg 可读串


class TestOptionsSizeCap:
    def test_oversize_options_400(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"options": {"note": "x" * 70000}},
        )
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "invalid_request"

    def test_normal_options_ok(self, client: TestClient) -> None:
        r = client.post(
            f"/api/arxiv/{ARXIV}/translate",
            json={"options": {"concurrency": 2}},
        )
        assert r.status_code == HTTPStatus.ACCEPTED


class TestFileGetToctou:
    def test_vanished_artifact_404_json(self, client: TestClient) -> None:
        """登记在册、盘上已删的产物 → 404 JSON（旧路径 FileResponse 惰性
        stat 抛 RuntimeError 裸 500）。"""
        tid = mk_api_task(client, ARXIV)
        rec = reg_artifact(client, tid, "zh_pdf", "zh.pdf")
        target = client.app.state.data_dir / "tasks" / tid / rec["path"]
        target.unlink()
        r = client.get(f"/api/files/{tid}/zh.pdf")
        assert r.status_code == HTTPStatus.NOT_FOUND
        assert r.json()["detail"] == "artifact file missing"

    def test_present_artifact_serves(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        reg_artifact(client, tid, "zh_pdf", "zh.pdf")
        r = client.get(f"/api/files/{tid}/zh.pdf")
        assert r.status_code == HTTPStatus.OK
        assert r.content == b"%PDF-1.4 fake"


class TestRetryOrdering:
    def test_cleanup_failure_faults(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """抢到 queued 后清理/写 options 折了 → 转 fault 不留半成品。"""
        tid = mk_api_task(client, ARXIV)
        client.portal.call(
            partial(client.app.state.store.update_fields, tid, main_tex="main.tex")
        )
        force_status(client, tid, "fault")

        def _boom(*_a: object, **_k: object) -> None:
            msg = "boom"
            raise StoreError(msg)

        store = client.app.state.store
        monkeypatch.setattr(store, "update_fields", _boom)
        r = client.post(f"/api/task/{tid}/retry", json={"main": "other.tex"})
        assert r.status_code == HTTPStatus.INTERNAL_SERVER_ERROR
        assert get_row(client, tid)["status"] == "fault"

    def test_double_retry_second_409(self, client: TestClient) -> None:
        """守卫迁移先行——行已 queued 时第二发 retry 纯 409，不动 chunks。"""
        tid = mk_api_task(client, ARXIV)
        force_status(client, tid, "fault")
        r1 = client.post(f"/api/task/{tid}/retry", json={})
        assert r1.status_code == HTTPStatus.ACCEPTED
        r2 = client.post(f"/api/task/{tid}/retry", json={})
        assert r2.status_code == HTTPStatus.CONFLICT


class TestDeleteGuard:
    def test_terminal_delete_ok(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)
        tdir = client.app.state.data_dir / "tasks" / tid
        tdir.mkdir(parents=True, exist_ok=True)
        (tdir / "keep.bin").write_bytes(b"x")
        force_status(client, tid, "done")
        r = client.delete(f"/api/task/{tid}")
        assert r.status_code == HTTPStatus.OK
        assert get_row(client, tid) is None
        assert not tdir.exists()

    def test_active_delete_409(self, client: TestClient) -> None:
        tid = mk_api_task(client, ARXIV)  # queued = ACTIVE
        r = client.delete(f"/api/task/{tid}")
        assert r.status_code == HTTPStatus.CONFLICT
        assert get_row(client, tid) is not None

    def test_guard_false_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """条件写兜底臂：读时终态、删时被并发激活 → False → 409 不删。"""
        tid = mk_api_task(client, ARXIV)
        force_status(client, tid, "done")
        store = client.app.state.store
        monkeypatch.setattr(store, "delete_task_guard", lambda *_a, **_k: False)
        r = client.delete(f"/api/task/{tid}")
        assert r.status_code == HTTPStatus.CONFLICT
        assert get_row(client, tid) is not None


class TestOrphanSweep:
    def test_lifespan_sweeps_orphan_task_dirs(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """重启清扫无 DB 行的 ``tasks/{id}/`` 孤儿；合法行目录与非法名不碰。"""
        with TestClient(make_app(tmp_path)) as c:
            tid = mk_api_task(c, ARXIV)
        tasks = tmp_path / "data" / "tasks"
        orphan = tasks / "t_0000000000000abc"
        orphan.mkdir(parents=True)
        (orphan / "junk.bin").write_bytes(b"x")
        real = tasks / tid
        real.mkdir(parents=True, exist_ok=True)
        (real / "keep.bin").write_bytes(b"x")
        stranger = tasks / "not-a-task-id"
        stranger.mkdir()
        with TestClient(make_app(tmp_path)):
            pass
        assert not orphan.exists()
        assert (real / "keep.bin").is_file()
        assert stranger.is_dir()


class TestCrossTenantReuse:
    def test_done_hit_creates_tenant_owned_task(
        self, server_client: TestClient
    ) -> None:
        """跨租户 done 命中 → 202 建行（存 alias 键逼 worker 物化），
        不再回对方永远读不到的 task_id。"""
        tid_a = mk_api_task(server_client, f"{ARXIV}v1", headers=KEY_A)
        force_status(server_client, tid_a, "done")
        r = server_client.post(
            f"/api/arxiv/{ARXIV}v1/translate", json={}, headers=KEY_B
        )
        assert r.status_code == HTTPStatus.ACCEPTED
        tid_b = r.json()["task_id"]
        assert tid_b != tid_a
        # B 拿到自己租户的可读句柄（旧 bug：直回 A 的 id → _get_task 恒 404）
        got = server_client.get(f"/api/task/{tid_b}", headers=KEY_B)
        assert got.status_code == HTTPStatus.OK
        row_a = get_row(server_client, tid_a)
        row_b = get_row(server_client, tid_b)
        assert row_b["tenant"] != row_a["tenant"]
        # alias（无版本）键——stored≠resolved 触发 _post_resolve_reuse 物化
        assert "@" not in row_b["cache_key"]

    def test_same_tenant_done_hit_reuses(self, server_client: TestClient) -> None:
        """同租户命中仍走 200 reuse 直返。"""
        tid_a = mk_api_task(server_client, f"{ARXIV}v2", headers=KEY_A)
        force_status(server_client, tid_a, "done")
        r = server_client.post(
            f"/api/arxiv/{ARXIV}v2/translate", json={}, headers=KEY_A
        )
        assert r.status_code == HTTPStatus.OK
        assert r.json()["task_id"] == tid_a
        assert r.json()["reused"] is True


class TestIntegrityErrorMapped:
    def test_active_dedup_race_409(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """dedup 查臂与 INSERT 之间并发撞 ACTIVE 唯一索引 → 409
        duplicate_active（旧路径裸 500）。"""
        mk_api_task(client, ARXIV)  # queued 同 cache_key 行占位
        store = client.app.state.store
        monkeypatch.setattr(store, "find_active_by_cache_key", lambda *_a, **_k: None)
        r = client.post(f"/api/arxiv/{ARXIV}/translate", json={})
        assert r.status_code == HTTPStatus.CONFLICT
        assert r.json()["code"] == "duplicate_active"


class TestErrorSurface:
    def test_http_exception_has_code(self, client: TestClient) -> None:
        r = client.get("/api/task/not-an-id")
        assert r.status_code == HTTPStatus.NOT_FOUND
        assert r.json()["code"] == "not_found"

    def test_settings_put_array_body_400(self, client: TestClient) -> None:
        r = client.put("/api/settings", json=[1, 2])
        assert r.status_code == HTTPStatus.BAD_REQUEST
        assert r.json()["code"] == "invalid_request"


class TestWebBindWarning:
    def _invoke(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        host: str,
    ) -> str:
        import uvicorn  # noqa: PLC0415 -- server extra 延迟导入同口径

        monkeypatch.setattr(uvicorn, "run", lambda *_a, **_k: None)
        result = _RUNNER.invoke(
            cli_mod.app,
            ["web", "--data-dir", str(tmp_path), "--host", host],
        )
        assert result.exit_code == 0, result.output
        return result.stderr

    def test_non_loopback_warns(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        err = self._invoke(
            tmp_path,
            monkeypatch,
            "0.0.0.0",  # noqa: S104 -- 参数非绑定
        )
        assert "非回环" in err

    def test_loopback_quiet(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        err = self._invoke(tmp_path, monkeypatch, "127.0.0.1")
        assert "非回环" not in err

    def test_server_mode_quiet(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002 -- fixture 副作用
    ) -> None:
        """server 形态有 X-Texlate-Key 鉴权——非回环绑定不警告。"""
        monkeypatch.setenv("TEXLATE_MODE", "server")
        err = self._invoke(
            tmp_path,
            monkeypatch,
            "0.0.0.0",  # noqa: S104 -- 参数非绑定
        )
        assert "非回环" not in err
