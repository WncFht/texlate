"""第二波验收：md_zip 降级产物（§5.4 view=html）/ server 模式 CORS allowlist /
tenant 配额（quota_max_*）/ options.retry_model 备选模型兜底。"""

from __future__ import annotations

import asyncio
import json
import zipfile
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import FakeEngine, make_app, wait_terminal
from starlette.testclient import TestClient
from test_server_security import FlakyEngine, _live_app, _upload

from texlate.server.settings import SettingsStore
from texlate.server.store import Store
from texlate.server.worker import (
    PipelineWorker,
    Secrets,
    TaskCtx,
    _FallbackTranslator,
    _md_member,
)
from texlate.xlat.client import ChatClient, ChatError
from texlate.xlat.pipeline import GatewayTranslator, MockTranslator

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import Response


def _settings(data_root: Path, **updates: object) -> None:
    """create_app 之前预写 settings.json（CORS/quota 等 create 期读取的项用）。"""
    data_root.mkdir(parents=True, exist_ok=True)
    SettingsStore(data_root).save(updates)


def _md_zip_members(data_root: Path, tid: str) -> dict[str, str]:
    """tasks/{id}/md.zip → {member: text}。"""
    zpath = data_root / "tasks" / tid / "md.zip"
    assert zpath.is_file()
    out: dict[str, str] = {}
    with zipfile.ZipFile(zpath) as zf:
        for name in zf.namelist():
            out[name] = zf.read(name).decode("utf-8")
    return out


class TestMdZip:
    """§5.4 降级路径：编译彻底失败但译文在库 → md.zip + reader view=html。"""

    def test_md_zip_on_total_compile_failure(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        eng = FlakyEngine(always_fail=True)
        with TestClient(_live_app(tmp_path, engine=eng)) as c:
            tid = _upload(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "fault"
            rec = c.portal.call(partial(c.app.state.store.file_record, tid, "md_zip"))
            assert rec is not None
            assert rec["bytes"]
            members = _md_zip_members(tmp_path / "data", tid)
            assert "main.md" in members
            body = members["main.md"]
            assert "<!-- chunk:" in body
            assert "这是译文" in body  # MockTranslator 译文进包
            assert "longer paragraph" in body  # en 侧原文同包
            r = c.get(f"/api/task/{tid}/reader")
            assert r.status_code == HTTPStatus.OK, r.text
            assert r.json()["view"] == "html"
            # 产物可下载：KIND_URL md_zip→md
            r2 = c.get(f"/api/files/{tid}/md")
            assert r2.status_code == HTTPStatus.OK
            assert r2.headers["content-type"].startswith("application/zip")

    def test_no_md_zip_on_success(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        with TestClient(_live_app(tmp_path)) as c:
            tid = _upload(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done"
            rec = c.portal.call(partial(c.app.state.store.file_record, tid, "md_zip"))
            assert rec is None
            assert c.get(f"/api/task/{tid}/reader").json()["view"] == "pdf"

    def test_retry_success_restores_pdf_view(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """fault 期登记的 md_zip 在 retry 出 pdf 后不把视图钉死在 html。"""
        engs = [FlakyEngine(always_fail=True)]
        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: MockTranslator(),
            engine_factory=lambda _n: engs[0],
        )
        with TestClient(app) as c:
            tid = _upload(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "fault"
            assert (
                c.portal.call(partial(c.app.state.store.file_record, tid, "md_zip"))
                is not None
            )
            engs[0] = FakeEngine()
            r = c.post(f"/api/task/{tid}/retry", json={})
            assert r.status_code == HTTPStatus.ACCEPTED, r.text
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done"
            rec = c.portal.call(partial(c.app.state.store.file_record, tid, "md_zip"))
            assert rec is not None  # 旧降级产物仍在（可下载留档）
            assert c.get(f"/api/task/{tid}/reader").json()["view"] == "pdf"

    def test_md_member_sanitize(self) -> None:
        seen: set[str] = set()
        assert _md_member("main.tex", seen) == "main.md"
        assert _md_member("sec/intro.tex", seen) == "sec/intro.md"
        assert _md_member("../evil.tex", seen) == "evil.md"
        assert _md_member("C:/abs/x.tex", seen) == "abs/x.md"  # 盘符段剥除
        seen2: set[str] = set()
        assert _md_member("a/b.tex", seen2) == "a/b.md"
        assert _md_member("a/b.tex", seen2) == "a/b~2.md"  # 重名脱冲突
        assert _md_member("weird name!.tex", seen2) == "weird_name_.md"


class TestCorsAllowlist:
    """TEXLATE_MODE=server 正式 allowlist；空 = 禁跨域；local 不读此项。"""

    def test_settings_roundtrip_and_validation(self, client: TestClient) -> None:
        r = client.put(
            "/api/settings",
            json={
                "cors_origins": [
                    "https://a.example",
                    "https://a.example/",
                    " https://b.example:8443 ",
                ]
            },
        )
        assert r.status_code == HTTPStatus.OK, r.text
        got = client.get("/api/settings").json()["cors_origins"]
        assert got == ["https://a.example", "https://b.example:8443"]
        for bad in (
            {"cors_origins": "https://x.example"},  # 非数组
            {"cors_origins": ["ftp://x.example"]},  # 非 http(s)
            {"cors_origins": ["https://x.example/path"]},  # 带 path
            {"cors_origins": ["https://u:p@x.example"]},  # userinfo
        ):
            r = client.put("/api/settings", json=bad)
            assert r.status_code == HTTPStatus.BAD_REQUEST, bad

    def test_server_mode_allows_listed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        monkeypatch.setenv("TEXLATE_MODE", "server")
        _settings(tmp_path / "data", cors_origins=["https://ok.example"])
        with TestClient(make_app(tmp_path)) as c:
            r = c.options(
                "/api/health",
                headers={
                    "Origin": "https://ok.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert r.headers.get("access-control-allow-origin") == (
                "https://ok.example"
            )
            r2 = c.options(
                "/api/health",
                headers={
                    "Origin": "https://evil.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert "access-control-allow-origin" not in r2.headers
            # 非预检跨域 GET：listed 带 ACAO，未列不带
            r3 = c.get("/api/health", headers={"Origin": "https://ok.example"})
            assert r3.headers.get("access-control-allow-origin") == (
                "https://ok.example"
            )
            r4 = c.get("/api/health", headers={"Origin": "https://evil.example"})
            assert "access-control-allow-origin" not in r4.headers

    def test_server_mode_default_denies(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        monkeypatch.setenv("TEXLATE_MODE", "server")
        with TestClient(make_app(tmp_path)) as c:
            r = c.options(
                "/api/health",
                headers={
                    "Origin": "https://any.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert "access-control-allow-origin" not in r.headers

    def test_local_mode_ignores_origins(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        monkeypatch.setenv("TEXLATE_MODE", "local")
        _settings(tmp_path / "data", cors_origins=["https://ok.example"])
        with TestClient(make_app(tmp_path)) as c:
            r = c.options(
                "/api/health",
                headers={
                    "Origin": "https://ok.example",
                    "Access-Control-Request-Method": "GET",
                },
            )
            assert "access-control-allow-origin" not in r.headers


class TestTenantQuota:
    """settings.quota_max_tasks/quota_max_bytes：超限 429 quota_exceeded。"""

    def _arxiv(self, c: TestClient, arxiv_id: str, key: str = "") -> Response:
        headers = {"x-texlate-key": key} if key else {}
        return c.post(f"/api/arxiv/{arxiv_id}/translate", json={}, headers=headers)

    def test_tasks_cap(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        _settings(tmp_path / "data", quota_max_tasks=1)
        with TestClient(make_app(tmp_path)) as c:
            assert self._arxiv(c, "2401.00001").status_code == HTTPStatus.ACCEPTED
            r = self._arxiv(c, "2401.00002")
            assert r.status_code == HTTPStatus.TOO_MANY_REQUESTS
            assert r.json()["code"] == "quota_exceeded"

    def test_bytes_cap(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        _settings(tmp_path / "data", quota_max_bytes=10)
        with TestClient(make_app(tmp_path)) as c:
            r = c.post(
                "/api/upload",
                files={"file": ("main.tex", b"x" * 300, "application/octet-stream")},
            )
            assert r.status_code == HTTPStatus.TOO_MANY_REQUESTS
            assert r.json()["code"] == "quota_exceeded"
        # 0 = 不限（另一数据目录新 app 默认无配额）
        with TestClient(make_app(tmp_path / "w2")) as c2:
            r = c2.post(
                "/api/upload",
                files={"file": ("main.tex", b"x" * 300, "application/octet-stream")},
            )
            assert r.status_code == HTTPStatus.ACCEPTED

    def test_tenant_isolation(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """server 模式配额按 tenant 指纹分桶：A 用尽不误伤 B。"""
        monkeypatch.setenv("TEXLATE_MODE", "server")
        _settings(tmp_path / "data", quota_max_tasks=1)
        with TestClient(make_app(tmp_path)) as c:
            assert self._arxiv(c, "2401.00003", key="sk-A").status_code == (
                HTTPStatus.ACCEPTED
            )
            assert self._arxiv(c, "2401.00004", key="sk-A").status_code == (
                HTTPStatus.TOO_MANY_REQUESTS
            )
            assert self._arxiv(c, "2401.00005", key="sk-B").status_code == (
                HTTPStatus.ACCEPTED
            )

    def test_tenant_usage_unit(self, tmp_path: Path) -> None:
        """store.tenant_usage：任务数 + files.bytes 合计（按 tenant 过滤）。"""
        store = Store(tmp_path / "t.db")
        store.open()
        tdir = tmp_path / "tasks" / "t_a"
        tdir.mkdir(parents=True)
        (tdir / "en.pdf").write_bytes(b"%PDF-1234")
        for tid, tenant in (("t_a", "k_x"), ("t_b", "k_x"), ("t_c", "k_y")):
            store.create_task(
                task_id=tid,
                kind="arxiv",
                target_lang="zh-CN",
                model="m",
                arxiv_id=None,
                source_name="s",
                title="",
                config={},
                options={},
                auth_source="settings",
                tenant=tenant,
                cache_key=None,
            )
        store.put_file("t_a", "en_pdf", "en.pdf", data_dir=tdir)
        try:
            assert store.tenant_usage("k_x") == {"tasks": 2, "bytes": 9}
            assert store.tenant_usage("k_y") == {"tasks": 1, "bytes": 0}
            assert store.tenant_usage("k_none") == {"tasks": 0, "bytes": 0}
        finally:
            store.close()


class _BoomTranslator:
    """固定抛错的假 Translator。"""

    def __init__(self, exc: ChatError) -> None:
        self.exc = exc
        self.calls = 0

    async def translate(self, **_kw: object) -> str:
        self.calls += 1
        raise self.exc


class _OkTranslator:
    """固定成功的假 Translator（记录调用参数）。"""

    def __init__(self, zh: str = "译文") -> None:
        self.zh = zh
        self.calls = 0
        self.kw: dict[str, object] = {}

    async def translate(self, **kw: object) -> str:
        self.calls += 1
        self.kw = kw
        return self.zh


class _NullBus:
    """_make_translator warning 路径只要求 publish 鸭子型。"""

    def publish(self, *_a: object, **_kw: object) -> None:
        return None


class TestRetryModel:
    """options.retry_model：primary retryable 失败 → 备选模型同参补一发。"""

    def test_fallback_on_retryable(self) -> None:
        p = _BoomTranslator(ChatError("rate", status=429, retryable=True))
        f = _OkTranslator()
        t = _FallbackTranslator(p, f)  # type: ignore[arg-type] -- 鸭子型替身
        out = asyncio.run(
            t.translate(system="s", user="u", temperature=0.0, max_tokens=1024)
        )
        assert out == "译文"
        assert p.calls == 1
        assert f.calls == 1
        assert f.kw["user"] == "u"

    def test_non_retryable_propagates(self) -> None:
        p = _BoomTranslator(ChatError("auth", status=401, retryable=False))
        f = _OkTranslator()
        t = _FallbackTranslator(p, f)  # type: ignore[arg-type]
        with pytest.raises(ChatError):
            asyncio.run(
                t.translate(system="s", user="u", temperature=0.0, max_tokens=1)
            )
        assert f.calls == 0

    def _ctx(self, tmp_path: Path, **options: object) -> tuple[TaskCtx, PipelineWorker]:
        store = Store(tmp_path / "t.db")
        store.open()
        bus = _NullBus()
        worker = PipelineWorker(store, bus, tmp_path)  # type: ignore[arg-type]
        ctx = TaskCtx(
            store=store,
            bus=bus,  # type: ignore[arg-type] -- publish-only 鸭子型
            task_id="t_ctx",
            row={
                "config_json": "{}",
                "options_json": json.dumps(options),
                "model": "m",
                "target_lang": "zh-CN",
            },
            secrets=Secrets(
                api_key="sk-x",
                base_url="http://127.0.0.1:3003",
                model="pri-m",
            ),
            root=tmp_path / "task",
        )
        return ctx, worker

    def test_make_translator_wraps(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        ctx, worker = self._ctx(tmp_path, retry_model="alt-m")
        t = worker._make_translator(ctx)  # noqa: SLF001 -- 装配面即被测对象
        assert isinstance(t, _FallbackTranslator)
        assert isinstance(t.client, ChatClient)
        asyncio.run(t.client.aclose())

    def test_make_translator_plain_without_option(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        ctx, worker = self._ctx(tmp_path)
        t = worker._make_translator(ctx)  # noqa: SLF001
        assert isinstance(t, GatewayTranslator)
        asyncio.run(t.client.aclose())
        ctx2, worker2 = self._ctx(tmp_path / "same", retry_model="pri-m")
        t2 = worker2._make_translator(ctx2)  # noqa: SLF001
        assert isinstance(t2, GatewayTranslator)  # 同名不包
        asyncio.run(t2.client.aclose())

    def test_pipeline_integration(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """真管线：primary 每发都 429（retryable）→ 备选模型译文进 chunks。"""
        primary = _BoomTranslator(ChatError("rate", status=429, retryable=True))
        fallback = _OkTranslator("备选译文")
        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: _FallbackTranslator(
                primary,  # type: ignore[arg-type]
                fallback,  # type: ignore[arg-type]
            ),
            engine_factory=lambda _n: FakeEngine(),
        )
        with TestClient(app) as c:
            tid = _upload(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done"
            rows = c.portal.call(partial(c.app.state.store.all_chunks, tid))
        assert primary.calls > 0
        assert fallback.calls > 0
        assert any("备选译文" in (r["translation"] or "") for r in rows)
