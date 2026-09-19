"""§3.1/§3.4 worker e2e：upload_tex/arxiv 全链 → done + 产物登记 + 终态守卫。"""

from __future__ import annotations

import asyncio
import json
import re
import time
from functools import partial
from http import HTTPStatus
from typing import TYPE_CHECKING

import httpx
import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import (
    MINI_TEX,
    FakeEngine,
    FakeFetcher,
    make_app,
    make_targz,
    upload_tex,
    wait_terminal,
)
from starlette.testclient import TestClient

from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import HeadInfo, SrcResult
from texlate.server.store import new_task_id
from texlate.server.worker import chunk_db_id, chunk_error_code
from texlate.xlat.client import AuthError, ChatClient, ChatError
from texlate.xlat.pipeline import GatewayTranslator, MockTranslator
from texlate.xlat.state import ChunkRecord

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

    from texlate.server.worker import TaskCtx

_CHUNK_ID_LEN = 24  # sha256[:24]

#: 假翻译应答的拉丁→中文映射——``[[X_n]]`` 占位符原样保留，其余拉丁词
#: 变「文」（residual_en 网下合法的纯中文应答形）。
_SINICIZE_RX = re.compile(r"(\[\[[A-Z][A-Z0-9_]*(?:_\d+)?\]\])|([A-Za-z]+)")


def _sinicize(s: str) -> str:
    """拉丁词→文、``[[X_n]]`` 原样——供 canned handler 产合规中文译文。"""
    return _SINICIZE_RX.sub(lambda m: m.group(1) or "文", s)


#: ≥3 段 tex——T2 auth 闸熔断需要连续 3 块 auth 失败
_MULTI_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "First paragraph of English prose long enough to be a real chunk.\n"
    "\n"
    "Second paragraph here with more English text for the pipeline.\n"
    "\n"
    "Third paragraph carrying yet more translatable English content.\n"
    "\n"
    "Fourth paragraph of English prose keeping the document going.\n"
    "\n"
    "Fifth paragraph of English prose closing out the document body.\n"
    "\\end{document}\n"
)


@pytest.fixture
def arxiv_client(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,  # noqa: ARG001 -- fixture 副作用
) -> Iterator[TestClient]:
    """arxiv 路 e2e：FakeFetcher 供 tar.gz、Mock 翻译、Fake 引擎。"""
    engine = FakeEngine()
    app = make_app(
        tmp_path,
        start_worker=True,
        translator_factory=lambda _ctx: MockTranslator(),
        engine_factory=lambda _name: engine,
        fetcher=FakeFetcher(make_targz({"main.tex": MINI_TEX})),
        source_cache=SourceCache(tmp_path / "src-cache"),
    )
    with TestClient(app) as c:
        yield c


class TestUploadTexE2E:
    def test_full_pipeline_done(self, live_client: TestClient) -> None:
        body = upload_tex(live_client)
        snap = wait_terminal(live_client, body["task_id"])
        assert snap["status"] == "done"
        assert snap["progress"] == 100  # noqa: PLR2004 - 终态进度 100
        arts = snap["artifacts"]
        assert "zh_pdf" in arts
        assert "dual_json" in arts
        assert "zh_src_zip" in arts

    def test_chunk_counters(self, live_client: TestClient) -> None:
        body = upload_tex(live_client)
        snap = wait_terminal(live_client, body["task_id"])
        assert snap["counters"]["total"] >= 1
        assert snap["counters"]["done"] == snap["counters"]["total"]
        assert snap["counters"]["failed"] == 0

    def test_dual_json_schema(self, live_client: TestClient) -> None:
        body = upload_tex(live_client)
        tid = body["task_id"]
        wait_terminal(live_client, tid)
        r = live_client.get(f"/api/files/{tid}/dual.json")
        assert r.status_code == HTTPStatus.OK
        doc = r.json()
        assert doc["version"] == 1
        assert doc["documents"]["translated"]["pages"] >= 0
        assert doc["alignment"]["kind"] == "pages"
        chunk0 = doc["chunks"][0]
        assert {"seq", "src_file", "en", "zh", "kind"} <= set(chunk0)

    def test_file_download(self, live_client: TestClient) -> None:
        body = upload_tex(live_client)
        tid = body["task_id"]
        wait_terminal(live_client, tid)
        r = live_client.get(f"/api/files/{tid}/zh.pdf")
        assert r.status_code == HTTPStatus.OK
        assert r.content.startswith(b"%PDF")
        r2 = live_client.get(f"/api/files/{tid}/zh.pdf", params={"download": 1})
        assert "attachment" in r2.headers["Content-Disposition"]

    def test_reader_after_done(self, live_client: TestClient) -> None:
        body = upload_tex(live_client)
        tid = body["task_id"]
        wait_terminal(live_client, tid)
        r = live_client.get(f"/api/task/{tid}/reader")
        assert r.status_code == HTTPStatus.OK
        doc = r.json()
        assert doc["documents"]["translated"]["url"] == f"/api/files/{tid}/zh.pdf"
        assert doc["view"] == "pdf"


class TestArxivE2E:
    def test_arxiv_done(self, arxiv_client: TestClient) -> None:
        r = arxiv_client.post("/api/arxiv/2401.00003/translate", json={})
        assert r.status_code == HTTPStatus.ACCEPTED
        snap = wait_terminal(arxiv_client, r.json()["task_id"])
        assert snap["status"] == "done"
        # src.tar 应已登记（raw blob 回放产物）
        assert "src_tar" in snap["artifacts"]


class TestFaultPaths:
    def test_translate_fault(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """translator 构造期 AuthError → fault + provider_auth（§3.3 ACTIVE 异常）。"""

        def boom_factory(_ctx: TaskCtx) -> object:
            msg = "bad key"
            raise AuthError(msg, status=401)

        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=boom_factory,
            engine_factory=lambda _name: FakeEngine(),
        )
        with TestClient(app) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "provider_auth"
        assert snap["error"]["retryable"] is False

    def test_all_chunks_failed_partial(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """块级 ChatError 被管线吸收 → failed chunks，仍出 pdf → partial（§3.4）。"""

        class Boom:
            async def translate(self, **_kw: object) -> object:
                msg = "provider down"
                raise ChatError(msg, status=500, retryable=False)

        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: Boom(),
            engine_factory=lambda _name: FakeEngine(),
        )
        with TestClient(app) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
            r = c.get(f"/api/files/{tid}/dual.json")
        assert snap["status"] == "partial"
        assert snap["counters"]["failed"] == snap["counters"]["total"]
        assert snap["counters"]["total"] >= 1
        # 非 ok 行 zh 位不得装 en 原文（fallback_orig 回写）——空串才是
        # 对账/阅读器认的 miss 形态
        assert r.status_code == HTTPStatus.OK
        assert all(ch["zh"] == "" for ch in r.json()["chunks"])

    def test_cancel_during_run(self, live_client: TestClient) -> None:
        """排队中的任务 cancel → cancelled（不进入 running 态也成立）。"""
        tid = upload_tex(live_client)["task_id"]
        # 跑得飞快——cancel 可能赶在终态前（ACTIVE→cancelled）或后（409）
        r = live_client.post(f"/api/task/{tid}/cancel")
        assert r.status_code in (HTTPStatus.OK, HTTPStatus.CONFLICT)
        snap = wait_terminal(live_client, tid)
        assert snap["status"] in ("cancelled", "done")

    def test_auth_trip_faults_task(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """T2：≥3 块连续 401 → AuthTrippedError → provider_auth fault——
        不再静默全 skipped 出 done。"""

        class Denied:
            async def translate(self, **_kw: object) -> object:
                msg = "denied"
                raise AuthError(msg, status=401)

        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: Denied(),
            engine_factory=lambda _name: FakeEngine(),
        )
        with TestClient(app) as c:
            tid = upload_tex(c, tex=_MULTI_TEX)["task_id"]
            snap = wait_terminal(c, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "provider_auth"
        # T3：chunks.error_code 走唯一裁决点——auth 归因不写成 validate
        # （app.state.store 的 sqlite 连接粘 worker 线程——本线程另开只读实例）
        from texlate.server.store import Store  # noqa: PLC0415 -- 测试线程独立连

        s2 = Store(tmp_path / "data" / "texlate.db")
        s2.open()
        try:
            rows = s2.all_chunks(tid)
        finally:
            s2.close()
        assert rows
        assert all(r["error_code"] == "provider_auth" for r in rows)

    def test_usage_sink_recorded(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """T4：ChatClient.usage_sink → task_usage 行 + snapshot.usage 出账。"""

        def handler(req: httpx.Request) -> httpx.Response:
            # user 内容拉丁词→文、占位符原样——中文前缀+英文回显的旧形会撞
            # residual_en 网（E24 same_source 门槛的姊妹闸）；slots JSON 逐槽
            # 同形，批量/单翻两侧校验都过
            body = json.loads(req.content)
            user = body["messages"][-1]["content"]
            try:
                slots = json.loads(user).get("slots")
            except (json.JSONDecodeError, AttributeError):
                slots = None
            content = (
                json.dumps(
                    {
                        "slots": {
                            k: "译文：" + _sinicize(str(v)) for k, v in slots.items()
                        }
                    },
                    ensure_ascii=False,
                )
                if isinstance(slots, dict)
                else "译文：" + _sinicize(user)
            )
            return httpx.Response(
                HTTPStatus.OK,
                json={
                    "model": "m1",
                    "choices": [
                        {
                            "message": {
                                "role": "assistant",
                                "content": content,
                            },
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {"prompt_tokens": 11, "completion_tokens": 7},
                },
            )

        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        chat_client = ChatClient("http://127.0.0.1:3003", "k", http=http)
        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: GatewayTranslator(chat_client, "m1"),
            engine_factory=lambda _name: FakeEngine(),
        )
        with TestClient(app) as c:
            tid = upload_tex(c)["task_id"]
            snap = wait_terminal(c, tid)
        assert snap["status"] == "done"
        assert snap["usage"]["calls"] >= 1
        assert snap["usage"]["prompt_tokens"] >= 11  # noqa: PLR2004 -- 真实账单
        assert snap["usage"]["completion_tokens"] >= 7  # noqa: PLR2004
        assert snap["usage"]["model"] == "m1"


class _HeadErrFetcher:
    """head_src 恒 500 → ``_head_gate`` 短路 ``AcquireStatus.ERROR``。"""

    def head_src(self, arxiv_id: str, version: int | None = None) -> HeadInfo:
        """500 → ``_head_phase`` 直出 ERROR（不进 GET/缓存）。"""
        return HeadInfo(
            http_status=HTTPStatus.INTERNAL_SERVER_ERROR,
            url=f"https://export.arxiv.org/src/{arxiv_id}",
            resolved_version=version or 1,
        )

    def get_src(self, *_a: object, **_kw: object) -> SrcResult:
        """head 已被 gate 短路——进 GET 即 bug。"""
        pytest.fail("head 500 应被 _head_gate 短路，不该进 GET")


class TestStageErrorCodes:
    """fetch/parse 段 ``_StageError`` → fault ``error.code``/``retryable`` 终态映射。

    ``no_latex_source``/``arxiv_fetch``/``unsupported_format``/``parse`` 此前
    零覆盖——每个 code 的 retryable 极性一并钉死（重试面是契约）。
    """

    def _live(self, tmp_path: Path, **overrides: object) -> TestClient:
        """worker 起跑的 client（Mock 翻译 + Fake 引擎——失败先于两者触发）。"""
        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: MockTranslator(),
            engine_factory=lambda _name: FakeEngine(),
            **overrides,
        )
        return TestClient(app)

    def test_pdf_only_no_latex_source(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """e-print 只出 pdf → ``no_latex_source``，PDF_ONLY ∈ 非重试集。"""
        with self._live(
            tmp_path,
            fetcher=FakeFetcher(b"%PDF-1.4 fake"),
            source_cache=SourceCache(tmp_path / "src-cache"),
        ) as c:
            r = c.post("/api/arxiv/2401.00077/translate", json={})
            assert r.status_code == HTTPStatus.ACCEPTED
            snap = wait_terminal(c, r.json()["task_id"])
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "no_latex_source"
        assert snap["error"]["retryable"] is False

    def test_head_error_arxiv_fetch_retryable(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """HEAD 500 → ``arxiv_fetch`` + retryable（瞬时故障值得重试）。"""
        with self._live(
            tmp_path,
            fetcher=_HeadErrFetcher(),
            source_cache=SourceCache(tmp_path / "src-cache"),
        ) as c:
            r = c.post("/api/arxiv/2401.00078/translate", json={})
            assert r.status_code == HTTPStatus.ACCEPTED
            snap = wait_terminal(c, r.json()["task_id"])
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "arxiv_fetch"
        assert snap["error"]["retryable"] is True

    def test_upload_blob_unsupported_format(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """worker 侧 ``unsupported_format``：路由 400 与 worker 判别同规则，

        该分支 HTTP 不可达（route ``sniff_upload`` 先拦）——直建行 +
        runner.enqueue 绕路由驱动（store/runner 皆 loop 线程对象，
        经 portal.call 入 loop）。
        """
        with self._live(tmp_path) as c:
            tid = new_task_id()
            updir = c.app.state.data_dir / "tasks" / tid / "upload"
            updir.mkdir(parents=True)
            (updir / "blob.bin").write_bytes(b"\x00\x01\x02\x03\x04")
            c.portal.call(
                partial(
                    c.app.state.store.create_task,
                    task_id=tid,
                    kind="upload_tex",
                    target_lang="zh-CN",
                    model="m",
                )
            )
            c.portal.call(partial(c.app.state.runner.enqueue, tid))
            snap = wait_terminal(c, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "unsupported_format"
        assert snap["error"]["retryable"] is False

    @pytest.mark.parametrize("main", ["missing.tex", "../escape.tex"])
    def test_main_override_parse_fault(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        main: str,
    ) -> None:
        """options.main 覆盖主文件：不存在/越出 base 两分支 → ``parse`` fault。"""
        with self._live(tmp_path) as c:
            r = c.post(
                "/api/upload",
                files={
                    "file": ("main.tex", MINI_TEX.encode(), "application/octet-stream")
                },
                data={"main": main},
            )
            assert r.status_code == HTTPStatus.ACCEPTED, r.text
            snap = wait_terminal(c, r.json()["task_id"])
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "parse"
        assert snap["error"]["retryable"] is False


class TestChunkErrorCode:
    """T3：SSE item 与 chunks 行共用 ``chunk_error_code``——单写点单图。"""

    def _rec(self, **kw: object) -> ChunkRecord:
        base: dict[str, object] = {
            "chunk_id": "c",
            "source": "s",
            "translation": "t",
            "kind": "para",
        }
        base.update(kw)
        return ChunkRecord(**base)  # type: ignore[arg-type]

    def test_mapping_table(self) -> None:
        assert chunk_error_code(self._rec()) is None  # ok
        assert chunk_error_code(self._rec(status="partial")) is None
        # error_kind 归因先行：provider/auth 失败落库态是 skipped，
        # 不能被 skip_reason 字符串嗅探误标成 validate
        assert (
            chunk_error_code(self._rec(skipped=True, error_kind="auth"))
            == "provider_auth"
        )
        assert (
            chunk_error_code(self._rec(skipped=True, error_kind="provider"))
            == "provider_error"
        )
        assert (
            chunk_error_code(self._rec(skipped=True, error_kind="crash")) == "internal"
        )
        # skipped：占位符对账炸 → placeholder_mismatch；余 validate
        assert (
            chunk_error_code(self._rec(skipped=True, skip_reason="placeholder diff"))
            == "placeholder_mismatch"
        )
        assert (
            chunk_error_code(self._rec(skipped=True, skip_reason="ladder"))
            == "validate"
        )
        # fault：无归因 → provider_error；validate 归因 → validate
        assert chunk_error_code(self._rec(status="fault")) == "provider_error"
        assert (
            chunk_error_code(self._rec(status="fault", error_kind="validate"))
            == "validate"
        )


class TestResume:
    def test_interrupted_chunks_resume(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        """translating 中崩 → cancelled 后 chunks 表保留断点（total≥1）。"""

        class HangTranslator:
            def __init__(self) -> None:
                self.n = 0

            async def translate(self, **_kw: object) -> object:
                self.n += 1
                await asyncio.sleep(30)  # 永不返回 → 测试靠 cancel 杀
                return None

        engine = FakeEngine()
        app = make_app(
            tmp_path,
            start_worker=True,
            translator_factory=lambda _ctx: HangTranslator(),
            engine_factory=lambda _name: engine,
        )
        with TestClient(app) as c:
            tid = upload_tex(c)["task_id"]
            # 等到 chunks 已入库（parsing 完成）
            deadline = time.time() + 10
            while time.time() < deadline:
                snap = c.get(f"/api/task/{tid}").json()
                if snap["counters"]["total"] >= 1 or snap["status"] in (
                    "translating",
                    "compiling",
                ):
                    break
                time.sleep(0.05)
            c.post(f"/api/task/{tid}/cancel")
            snap = wait_terminal(c, tid)
            assert snap["status"] == "cancelled"
            assert snap["counters"]["total"] >= 1


def test_chunk_db_id_stable() -> None:
    """chunk_id = sha256(src_file:byte_start:byte_end)[:24]——splice 重建靠它稳定。"""
    a = chunk_db_id("a.tex", 0, 5)
    b = chunk_db_id("a.tex", 0, 5)
    assert a == b
    assert len(a) == _CHUNK_ID_LEN
    assert chunk_db_id("a.tex", 0, 6) != a
