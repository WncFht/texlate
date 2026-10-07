"""第二波验收：md_zip 降级产物（§5.4 view=html）/ server 模式 CORS allowlist /
tenant 配额（quota_max_*）/ options.retry_model 备选模型兜底。"""

from __future__ import annotations

import asyncio
import json
import zipfile
from http import HTTPStatus
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest
from _serverkit import FlakyEngine, preset_settings
from conftest import (
    FakeEngine,
    live_app,
    make_app,
    store_call,
    upload,
    wait_terminal,
)
from starlette.testclient import TestClient

from texlate.server.endpoints import EndpointStore
from texlate.server.store import Store
from texlate.server.worker import (
    PipelineWorker,
    Secrets,
    TaskCtx,
    _aclose_clients,
    _FallbackTranslator,
    _md_member,
)
from texlate.xlat.client import (
    AuthError,
    ChatClient,
    ChatError,
    EndpointNotFoundError,
    RetryableHTTPError,
)
from texlate.xlat.pipeline import GatewayTranslator, MockTranslator

if TYPE_CHECKING:
    from pathlib import Path

    from httpx import Response


def _md_zip_members(data_root: Path, tid: str) -> dict[str, str]:
    """tasks/{id}/md.zip → {member: text}."""
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
        app = live_app(
            tmp_path,
            lambda _ctx: MockTranslator(),
            engine_factory=lambda _n: eng,
        )
        with TestClient(app) as c:
            tid = upload(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "fault"
            rec = store_call(c, c.app.state.store.file_record, tid, "md_zip")
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
        app = live_app(tmp_path, lambda _ctx: MockTranslator())
        with TestClient(app) as c:
            tid = upload(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done"
            rec = store_call(c, c.app.state.store.file_record, tid, "md_zip")
            assert rec is None
            assert c.get(f"/api/task/{tid}/reader").json()["view"] == "pdf"

    def test_retry_success_restores_pdf_view(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """fault 期登记的 md_zip 在 retry 出 pdf 后不把视图钉死在 html。"""
        engs = [FlakyEngine(always_fail=True)]
        app = live_app(
            tmp_path,
            lambda _ctx: MockTranslator(),
            engine_factory=lambda _n: engs[0],
        )
        with TestClient(app) as c:
            tid = upload(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "fault"
            assert (
                store_call(c, c.app.state.store.file_record, tid, "md_zip") is not None
            )
            engs[0] = FakeEngine()
            r = c.post(f"/api/task/{tid}/retry", json={})
            assert r.status_code == HTTPStatus.ACCEPTED, r.text
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done"
            rec = store_call(c, c.app.state.store.file_record, tid, "md_zip")
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
        preset_settings(tmp_path / "data", cors_origins=["https://ok.example"])
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
        preset_settings(tmp_path / "data", cors_origins=["https://ok.example"])
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
        preset_settings(tmp_path / "data", quota_max_tasks=1)
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
        preset_settings(tmp_path / "data", quota_max_bytes=10)
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
        """server 模式配额按 tenant 指纹分桶：A 用尽不误伤**异 IP** 的 B。

        per-IP 兜底桶与 tenant 桶叠加——同 IP 换 key 刷请求撞的是
        ``同 IP 任务配额`` 桶（key 轮转不改对端事实），故 B 的探活
        须换一个对端地址。
        """
        monkeypatch.setenv("TEXLATE_MODE", "server")
        preset_settings(tmp_path / "data", quota_max_tasks=1)
        app = make_app(tmp_path)
        with TestClient(app) as c:
            assert self._arxiv(c, "2401.00003", key="sk-A").status_code == (
                HTTPStatus.ACCEPTED
            )
            assert self._arxiv(c, "2401.00004", key="sk-A").status_code == (
                HTTPStatus.TOO_MANY_REQUESTS
            )
            # 同 IP 换 key：tenant 桶是新的，但 per-IP 兜底桶已满 → 429
            assert self._arxiv(c, "2401.00005", key="sk-B").status_code == (
                HTTPStatus.TOO_MANY_REQUESTS
            )
        with TestClient(app, client=("10.9.9.9", 1)) as c2:
            assert self._arxiv(c2, "2401.00005", key="sk-B").status_code == (
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
    """固定成功的假 Translator（记录调用参数；zh 按 user 长度折倍——
    E24 长度比带下固定短桩是坍缩比会触发 length error）。"""

    def __init__(self, zh: str = "译文") -> None:
        self.zh = zh
        self.calls = 0
        self.kw: dict[str, object] = {}

    async def translate(self, **kw: object) -> str:
        self.calls += 1
        self.kw = kw
        return self.zh * max(1, len(str(kw.get("user", ""))) // 8)


class _NullBus:
    """_make_translator warning 路径只要求 publish 鸭子型。"""

    def publish(self, *_a: object, **_kw: object) -> None:
        return None


class TestRetryModel:
    """options.retry_model：primary retryable 失败 → 备选模型同参补一发。"""

    def test_fallback_on_retryable(self) -> None:
        p = _BoomTranslator(ChatError("rate", status=429, retryable=True))
        f = _OkTranslator()
        t = _FallbackTranslator(p, [f])  # type: ignore[arg-type] -- 鸭子型替身
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
        t = _FallbackTranslator(p, [f])  # type: ignore[arg-type]
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
        app = live_app(
            tmp_path,
            lambda _ctx: _FallbackTranslator(
                primary,  # type: ignore[arg-type]
                [fallback],  # type: ignore[arg-type]
            ),
        )
        with TestClient(app) as c:
            tid = upload(c)["task_id"]
            snap = wait_terminal(c, tid)
            assert snap["status"] == "done"
            rows = store_call(c, c.app.state.store.all_chunks, tid)
        assert primary.calls > 0
        assert fallback.calls > 0
        assert any("备选译文" in (r["translation"] or "") for r in rows)


# ---------------------------------------------------------------- 跨端点回退链


class _ArmTranslator:
    """带 ``.client``/``.model`` 的鸭子臂（``_arm_could_help`` 跨 client 判定按 identity）。"""

    def __init__(
        self,
        *,
        out: str = "",
        exc: ChatError | None = None,
        client: object = None,
        model: str = "m",
    ) -> None:
        self.client = client
        self.model = model
        self._out = out
        self._exc = exc
        self.calls = 0

    async def translate(self, **_kw: object) -> str:
        self.calls += 1
        if self._exc is not None:
            raise self._exc
        return self._out or self.model


class TestEndpointFallback:
    """``_FallbackTranslator`` N 臂链 + ``_endpoint_arms`` 跨端点建档。"""

    def test_cross_client_auth_error_switches(self) -> None:
        """异 client 臂：AuthError（本端点判死）照样切——换端点换凭据有救。"""
        p = _ArmTranslator(
            exc=AuthError("bad key", status=401),
            client=object(),
            model="a",
        )
        f = _ArmTranslator(out="ok", client=object(), model="b")
        t = _FallbackTranslator(p, [f])  # type: ignore[arg-type]
        out = asyncio.run(
            t.translate(system="s", user="u", temperature=0.0, max_tokens=16)
        )
        assert out == "ok"
        assert f.calls == 1

    def test_same_client_auth_error_propagates(self) -> None:
        """同 client 臂：AuthError 换模无救（同 key 同端点必同死）。"""
        shared = object()
        p = _ArmTranslator(
            exc=AuthError("bad key", status=401), client=shared, model="a"
        )
        f = _ArmTranslator(out="ok", client=shared, model="b")
        t = _FallbackTranslator(p, [f])  # type: ignore[arg-type]
        with pytest.raises(AuthError):
            asyncio.run(
                t.translate(system="s", user="u", temperature=0.0, max_tokens=16)
            )
        assert f.calls == 0

    def test_chain_order_and_last_raises(self) -> None:
        """臂序补发；末臂仍败原样上抛。"""
        c1, c2, c3 = object(), object(), object()
        p = _ArmTranslator(
            exc=RetryableHTTPError("429", status=429, retryable=True),
            client=c1,
        )
        f1 = _ArmTranslator(exc=EndpointNotFoundError("404", status=404), client=c2)
        f2 = _ArmTranslator(out="ok", client=c3)
        switches: list[tuple[object, object]] = []
        t = _FallbackTranslator(
            p,  # type: ignore[arg-type]
            [f1, f2],  # type: ignore[arg-type]
            on_switch=lambda frm, to, _e: switches.append((frm, to)),
        )
        out = asyncio.run(
            t.translate(system="s", user="u", temperature=0.0, max_tokens=16)
        )
        assert out == "ok"
        assert switches == [(p, f1), (f1, f2)]

    def _ep_ctx(self, tmp_path: Path, **over: object) -> tuple[TaskCtx, PipelineWorker]:
        store = Store(tmp_path / "t.db")
        store.open()
        worker = PipelineWorker(store, _NullBus(), tmp_path)  # type: ignore[arg-type]
        secrets_kw: dict[str, object] = {
            "api_key": "sk-ds",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "source": "settings",
        }
        secrets_kw.update(over.pop("secrets", {}))
        ctx = TaskCtx(
            store=store,
            bus=_NullBus(),  # type: ignore[arg-type]
            task_id="t_ep",
            row={
                "config_json": "{}",
                "options_json": json.dumps(over),
                "model": "m",
                "target_lang": "zh-CN",
            },
            secrets=Secrets(**secrets_kw),  # type: ignore[arg-type]
            root=tmp_path / "task",
        )
        return ctx, worker

    def _save_profiles(self, root: Path, *profiles: dict[str, object]) -> None:
        EndpointStore(root).save(list(profiles))

    def _profile(self, pid: str, url: str, **over: object) -> dict[str, object]:
        p: dict[str, object] = {
            "id": pid,
            "label": "",
            "base_url": url,
            "dialect": "auto",
            "models": [],
            "enabled": True,
            "api_key": "",
            "key_env": "",
        }
        p.update(over)
        return p

    def test_no_file_empty_arms(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """endpoints.json 缺席 → 空链（与无档案形态逐字节同构）。"""
        ctx, worker = self._ep_ctx(tmp_path)
        client = ChatClient("https://api.deepseek.com")
        assert worker._endpoint_arms(ctx, client, {"m"}) == []  # noqa: SLF001
        asyncio.run(client.aclose())

    def test_header_source_never_fans_out(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """header 凭据：单发 key 绝不进第二端点——档案在也空链。"""
        self._save_profiles(
            tmp_path,
            self._profile(
                "p1", "https://api.anthropic.com", api_key="sk-ant", models=["claude-x"]
            ),
        )
        ctx, worker = self._ep_ctx(tmp_path, secrets={"source": "header"})
        client = ChatClient("https://api.deepseek.com")
        assert worker._endpoint_arms(ctx, client, {"m"}) == []  # noqa: SLF001
        asyncio.run(client.aclose())

    def test_server_mode_no_arms(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,
    ) -> None:
        """非 local 形态：部署拓扑不自助回退。"""
        clean_env.setenv("TEXLATE_MODE", "server")
        self._save_profiles(
            tmp_path,
            self._profile(
                "p1", "https://api.anthropic.com", api_key="sk-ant", models=["claude-x"]
            ),
        )
        ctx, worker = self._ep_ctx(tmp_path)
        client = ChatClient("https://api.deepseek.com")
        assert worker._endpoint_arms(ctx, client, {"m"}) == []  # noqa: SLF001
        asyncio.run(client.aclose())

    def test_arms_active_extra_models_then_cross_endpoint(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """活动 profile 余模同 client 先行；异端点 profile 各带自家凭据。"""
        self._save_profiles(
            tmp_path,
            self._profile(
                "p1",
                "https://api.deepseek.com",
                api_key="sk-ds",
                models=["deepseek-chat", "deepseek-v4"],
            ),
            self._profile(
                "p2",
                "https://api.anthropic.com",
                api_key="sk-ant",
                models=["claude-x", "claude-y"],
            ),
            self._profile(
                "p3",
                "https://api.openai.com",
                api_key="sk-oai",
                models=["gpt-x"],
                enabled=False,
            ),
        )
        ctx, worker = self._ep_ctx(tmp_path)
        client = ChatClient("https://api.deepseek.com", "sk-ds")
        arms = worker._endpoint_arms(ctx, client, {"deepseek-chat", "alt"})  # noqa: SLF001
        assert [a.model for a in arms] == ["deepseek-v4", "claude-x"]
        assert arms[0].client is client  # 余模同 client
        assert arms[1].client is not client  # 异端点自家 client
        assert arms[1].client.api_key == "sk-ant"  # 凭据走 profile 不借 ctx key
        asyncio.run(_aclose_clients([client, arms[1].client]))

    def test_arms_use_wire_names(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """redirect 条目：臂名取线名（redirect 优先），exclude 也对线名。"""
        self._save_profiles(
            tmp_path,
            self._profile(
                "p1",
                "https://api.deepseek.com",
                api_key="sk-ds",
                models=[
                    {"model": "alias", "redirect_model": "wire-x"},
                    {"model": "m2", "redirect_model": ""},
                ],
            ),
        )
        ctx, worker = self._ep_ctx(tmp_path)
        client = ChatClient("https://api.deepseek.com", "sk-ds")
        arms = worker._endpoint_arms(ctx, client, {"deepseek-chat"})  # noqa: SLF001
        assert [a.model for a in arms] == ["wire-x", "m2"]
        asyncio.run(client.aclose())

    def test_keyless_remote_skipped_loopback_kept(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """无凭据远程端点必 401 白烧一跳——跳过；回环端点无 key 合法保留。"""
        self._save_profiles(
            tmp_path,
            self._profile(
                "p1",
                "https://api.deepseek.com",
                api_key="sk-ds",
                models=["deepseek-chat"],
            ),
            self._profile(
                "p2", "https://api.anthropic.com", models=["claude-x"]
            ),  # 无凭据
            self._profile(
                "p3", "http://127.0.0.1:11434", models=["qwen3"]
            ),  # 回环无 key
        )
        ctx, worker = self._ep_ctx(tmp_path)
        client = ChatClient("https://api.deepseek.com")
        arms = worker._endpoint_arms(ctx, client, {"deepseek-chat"})  # noqa: SLF001
        assert [a.model for a in arms] == ["qwen3"]
        asyncio.run(_aclose_clients([client, arms[0].client]))

    def test_make_translator_chain_end_to_end(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """整链：retry_model + 端点臂都进 ``_FallbackTranslator``，clients 去重。"""
        self._save_profiles(
            tmp_path,
            self._profile(
                "p1",
                "https://api.deepseek.com",
                api_key="sk-ds",
                models=["deepseek-chat"],
            ),
            self._profile(
                "p2", "https://api.anthropic.com", api_key="sk-ant", models=["claude-x"]
            ),
        )
        ctx, worker = self._ep_ctx(tmp_path, retry_model="deepseek-v4")
        t = worker._make_translator(ctx)  # noqa: SLF001
        assert isinstance(t, _FallbackTranslator)
        assert [a.model for a in t._fallbacks] == [  # noqa: SLF001
            "deepseek-v4",
            "claude-x",
        ]
        # primary/retry 同 client 去重 → 存留两端点 client
        assert {c.base_url for c in t.clients if isinstance(c, ChatClient)} == {
            "https://api.deepseek.com",
            "https://api.anthropic.com",
        }
        asyncio.run(
            _aclose_clients([c for c in t.clients if isinstance(c, ChatClient)])
        )

    def test_arm_switch_warn_dedupes_per_url(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """``_arm_switch_warn``：每任务每目标端点只警一次（``ctx.memo`` 记档）。"""
        ctx, worker = self._ep_ctx(tmp_path)
        a = _ArmTranslator(client=SimpleNamespace(base_url="https://a"), model="m1")
        b = _ArmTranslator(client=SimpleNamespace(base_url="https://b"), model="m2")
        e = ChatError("x", status=429, retryable=True)
        worker._arm_switch_warn(ctx, a, b, e)  # noqa: SLF001
        worker._arm_switch_warn(ctx, a, b, e)  # noqa: SLF001
        assert ctx.memo["endpoint_fallback_seen"] == {"endpoint_fallback:https://b"}
