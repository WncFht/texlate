"""§4 安全回归：main override confine / glossary 任意文件读 / RedactFilter
挂载 / cache_scope 跨租户 oracle / fixloop 编译段接线（docs/08 §5）。"""

from __future__ import annotations

import hashlib
import json
import logging
from functools import partial
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

pytest.importorskip("fastapi", reason="server extra 未装")
pytest.importorskip("starlette.testclient", reason="server extra 未装")

from conftest import (
    MINI_TEX,
    FakeEngine,
    make_app,
    make_targz,
    wait_terminal,
)
from starlette.testclient import TestClient

from texlate.compile.engine import CompRes, parse_log
from texlate.server.events import EventBus
from texlate.server.settings import (
    RedactFilter,
    cache_scope,
    install_log_scrub,
)
from texlate.server.store import Store
from texlate.server.worker import (
    PipelineWorker,
    Secrets,
    TaskCtx,
    cache_key_for,
)
from texlate.xlat.glossary import Glossary
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from fastapi import FastAPI

_ERR_LOG = "! Undefined control sequence.\nl.5 \\badcs\n"
_CLEAN_LOG = "This is fake engine\nOutput written on disk.\n"


class FlakyEngine:
    """按工作目录记名的假引擎：每个 wdir 首次 compile 失败、其后出 pdf。

    ``always_fail=True`` 时永不出 pdf（fixloop 规则耗尽路径）。
    探测面（probe_file/install_file/filemap/rebuild_fontmaps/caps）对齐
    fixloop 规则引擎会触到的 Engine 鸭子型。
    """

    name = "flaky"
    caps: frozenset[str] = frozenset()

    def __init__(self, *, always_fail: bool = False) -> None:
        """seen 记已编过的 wdir；calls 留全部调用供断言。"""
        self.always_fail = always_fail
        self.seen: set[str] = set()
        self.calls: list[dict[str, object]] = []

    def probe_file(self, fname: str, cwd: Path | None = None) -> bool:  # noqa: ARG002
        return False

    def install_file(self, fname: str, *, font_related: bool = False) -> bool:  # noqa: ARG002
        return False

    def filemap(self, fname: str) -> list[str]:  # noqa: ARG002
        return []

    def rebuild_fontmaps(self) -> None:
        return None

    def compile(  # noqa: PLR0913 -- 与 Engine.compile 同签名，kwarg 名是接口
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 1,
        timeout: float | None = None,  # noqa: ARG002
        outdir: Path | None = None,  # noqa: ARG002
        sandbox: bool = True,  # noqa: ARG002
        env_extra: dict[str, str] | None = None,  # noqa: ARG002
        best_effort: bool = False,
    ) -> CompRes:
        """同 wdir 首调失败（! 错 log）、其后成功出假 pdf。"""
        first = str(wdir) not in self.seen
        self.seen.add(str(wdir))
        ok = not self.always_fail and not first
        self.calls.append(
            {"wdir": str(wdir), "passes": passes, "best_effort": best_effort}
        )
        stem = Path(main).stem
        pdf = wdir / f"{stem}.pdf"
        log_path = wdir / f"{stem}.log"
        text = _CLEAN_LOG if ok else _ERR_LOG
        log_path.write_text(text, encoding="utf-8")
        if ok:
            pdf.write_bytes(b"%PDF-1.4\n% fake pdf\n")
        return CompRes(
            engine=self.name,
            ok=ok,
            pdf=pdf if ok else None,
            pdf_bytes=pdf.stat().st_size if ok else 0,
            log=parse_log(text),
            log_path=log_path,
            rc=0 if ok else 1,
            passes=passes,
            seconds=0.01,
        )


def _live_app(tmp_path: Path, **kw: object) -> FastAPI:
    """start_worker app：MockTranslator + 指定 engine（缺省 FakeEngine）。"""
    engine = kw.pop("engine", None) or FakeEngine()
    return make_app(
        tmp_path,
        start_worker=True,
        translator_factory=lambda _ctx: MockTranslator(),
        engine_factory=lambda _name: engine,
        **kw,
    )


def _upload(client: TestClient, *, fields: dict[str, str] | None = None) -> dict:
    """POST /api/upload 带额外表单字段（options/main/...）。"""
    r = client.post(
        "/api/upload",
        files={"file": ("main.tex", MINI_TEX.encode(), "application/octet-stream")},
        data=fields or {},
    )
    assert r.status_code == HTTPStatus.ACCEPTED, r.text
    return r.json()  # type: ignore[no-any-return]


def _events(client: TestClient, tid: str) -> list[dict]:
    """task_events 全量回放（portal 回 loop 线程读 store）。"""
    store: Store = client.app.state.store
    return client.portal.call(partial(store.events_since, tid, 0))  # type: ignore[no-any-return]


class TestMainOverrideConfine:
    """worker._build_base：``options.main`` 必须 confine 在 base/ 内。"""

    def test_absolute_path_rejected(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        with TestClient(_live_app(tmp_path)) as c:
            tid = _upload(c, fields={"main": "/etc/passwd"})["task_id"]
            snap = wait_terminal(c, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "parse"
        assert "越出工程目录" in snap["error"]["message"]

    def test_dotdot_escape_rejected(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        with TestClient(_live_app(tmp_path)) as c:
            tid = _upload(
                c, fields={"options": json.dumps({"main": "../../etc/passwd"})}
            )["task_id"]
            snap = wait_terminal(c, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "parse"
        assert "越出工程目录" in snap["error"]["message"]

    def test_legit_override_ok(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        with TestClient(_live_app(tmp_path)) as c:
            tid = _upload(c, fields={"main": "main.tex"})["task_id"]
            snap = wait_terminal(c, tid)
        assert snap["status"] == "done"


@pytest.fixture
def glossary_spy(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """``Glossary.load`` 调用记录器——断 confine 后实际加载了哪条路径。"""
    calls: list[dict] = []
    orig = Glossary.load

    def spy(**kw: object) -> Glossary:
        calls.append(kw)
        return orig(**kw)

    monkeypatch.setattr(Glossary, "load", spy)
    return calls


def _glossary_warnings(evs: list[dict]) -> list[dict]:
    return [
        e
        for e in evs
        if e["type"] == "warning" and e["data"].get("code") == "glossary_rejected"
    ]


class TestGlossaryConfine:
    """_make_glossary：相对路径 + 允许根（base/、settings.glossary_dir）二选一。"""

    def test_absolute_path_rejected(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        glossary_spy: list[dict],
    ) -> None:
        with TestClient(_live_app(tmp_path)) as c:
            tid = _upload(
                c, fields={"options": json.dumps({"glossary": "/etc/passwd"})}
            )["task_id"]
            snap = wait_terminal(c, tid)
            evs = _events(c, tid)
        assert snap["status"] == "done"  # 拒后回落默认表，不阻塞任务
        assert _glossary_warnings(evs)
        assert glossary_spy[-1].get("user_path") is None

    def test_dotdot_rejected(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        glossary_spy: list[dict],
    ) -> None:
        with TestClient(_live_app(tmp_path)) as c:
            tid = _upload(c, fields={"options": json.dumps({"glossary": "../g.csv"})})[
                "task_id"
            ]
            snap = wait_terminal(c, tid)
            evs = _events(c, tid)
        assert snap["status"] == "done"
        assert _glossary_warnings(evs)
        assert glossary_spy[-1].get("user_path") is None

    def test_outside_roots_rejected(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        glossary_spy: list[dict],
    ) -> None:
        with TestClient(_live_app(tmp_path)) as c:
            tid = _upload(c, fields={"options": json.dumps({"glossary": "nope.csv"})})[
                "task_id"
            ]
            snap = wait_terminal(c, tid)
            evs = _events(c, tid)
        assert snap["status"] == "done"
        assert _glossary_warnings(evs)
        assert glossary_spy[-1].get("user_path") is None

    def test_workdir_glossary_accepted(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        glossary_spy: list[dict],
    ) -> None:
        blob = make_targz({"main.tex": MINI_TEX, "terms.csv": "tensor,张量\n"})
        with TestClient(_live_app(tmp_path)) as c:
            r = c.post(
                "/api/upload",
                files={
                    "file": ("proj.tar.gz", blob, "application/gzip"),
                },
                data={"options": json.dumps({"glossary": "terms.csv"})},
            )
            assert r.status_code == HTTPStatus.ACCEPTED, r.text
            tid = r.json()["task_id"]
            snap = wait_terminal(c, tid)
            evs = _events(c, tid)
        assert snap["status"] == "done"
        assert not _glossary_warnings(evs)
        used = glossary_spy[-1].get("user_path")
        assert used is not None
        assert used.name == "terms.csv"

    def test_settings_glossary_dir_root(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
        glossary_spy: list[dict],
    ) -> None:
        gdir = tmp_path / "glossaries"
        gdir.mkdir()
        (gdir / "t.csv").write_text("tensor,张量\n", encoding="utf-8")
        with TestClient(_live_app(tmp_path)) as c:
            # 请求面塞不进根：options.glossary_dir 不进 config_json
            tid = _upload(
                c,
                fields={
                    "options": json.dumps({"glossary": "t.csv", "glossary_dir": "/etc"})
                },
            )["task_id"]
            snap = wait_terminal(c, tid)
            evs = _events(c, tid)
            assert snap["status"] == "done"
            assert _glossary_warnings(evs)  # /etc 未生效 → 根内无 t.csv → 拒
            row = c.portal.call(partial(c.app.state.store.get, tid))
            cfg = json.loads(row["config_json"])
            assert cfg.get("glossary_dir") in (None, "")
            # settings 侧根生效
            r = c.put("/api/settings", json={"glossary_dir": str(gdir)})
            assert r.status_code == HTTPStatus.OK, r.text
            tid2 = _upload(c, fields={"options": json.dumps({"glossary": "t.csv"})})[
                "task_id"
            ]
            snap2 = wait_terminal(c, tid2)
            evs2 = _events(c, tid2)
        assert snap2["status"] == "done"
        assert not _glossary_warnings(evs2)
        used = glossary_spy[-1].get("user_path")
        assert used == (gdir / "t.csv").resolve()

    def test_glossary_dir_validation(self, client: TestClient) -> None:
        r = client.put("/api/settings", json={"glossary_dir": "rel/path"})
        assert r.status_code == HTTPStatus.BAD_REQUEST
        r = client.put("/api/settings", json={"glossary_dir": "/nonexistent-dir-xyz"})
        assert r.status_code == HTTPStatus.BAD_REQUEST


class _Capture(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


class TestRedactMounted:
    """install_log_scrub：filter 落 root logger + 全部现有 handler。"""

    def test_propagated_record_scrubbed(self) -> None:
        root = logging.getLogger()
        cap = _Capture()
        root.addHandler(cap)
        try:
            install_log_scrub(lambda: ["sk-live-secret-7"])
            # 子 logger 本源无 filter——传播到 root handler 才被 handler 级 filter 抹
            logging.getLogger("texlate.submod").warning(
                "gw fail api_key=sk-live-secret-7 tail"
            )
            logging.getLogger("other.lib").warning(
                "Authorization: Bearer sk-abcdef123456"
            )
        finally:
            root.removeHandler(cap)
        assert cap.messages, "capture handler 应收到的确两条记录"
        blob = "\n".join(cap.messages)
        assert "sk-live-secret-7" not in blob
        assert "sk-abcdef123456" not in blob

    def test_reinstall_replaces(self) -> None:
        install_log_scrub(None)
        f2 = install_log_scrub(None)
        root = logging.getLogger()
        n = sum(1 for f in root.filters if isinstance(f, RedactFilter))
        assert n == 1
        assert root.filters[-1] is f2


class TestCacheScope:
    """cache_scope：shared 默认（hjfy 对等共享）| per_key 按 key 指纹分桶。"""

    def test_scope_env(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        assert cache_scope() == "shared"
        monkeypatch.setenv("TEXLATE_CACHE_SCOPE", "per_key")
        assert cache_scope() == "per_key"
        monkeypatch.setenv("TEXLATE_CACHE_SCOPE", "tenant")  # 旧名同义
        assert cache_scope() == "per_key"
        monkeypatch.setenv("TEXLATE_CACHE_SCOPE", "bogus")
        assert cache_scope() == "shared"

    def test_cache_key_shared_ignores_key(
        self,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        kw = {
            "arxiv_id": "2401.00001",
            "version": 1,
            "model": "m",
            "target_lang": "zh-CN",
        }
        assert cache_key_for(**kw, api_key="sk-A") == cache_key_for(
            **kw, api_key="sk-B"
        )

    def test_cache_key_per_key_buckets(
        self,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        monkeypatch.setenv("TEXLATE_CACHE_SCOPE", "per_key")
        kw = {
            "arxiv_id": "2401.00001",
            "version": 1,
            "model": "m",
            "target_lang": "zh-CN",
        }
        ka = cache_key_for(**kw, api_key="sk-A")
        kb = cache_key_for(**kw, api_key="sk-B")
        assert ka != kb
        assert cache_key_for(**kw, api_key="sk-A") == ka

    def _ctx(self, tmp_path: Path, api_key: str) -> tuple[TaskCtx, PipelineWorker]:
        store = Store(tmp_path / "t.db")
        store.open()
        bus = EventBus(store)
        worker = PipelineWorker(store, bus, tmp_path)
        ctx = TaskCtx(
            store=store,
            bus=bus,
            task_id="t_ctx",
            row={
                "config_json": "{}",
                "options_json": "{}",
                "model": "m",
                "target_lang": "zh-CN",
            },
            secrets=Secrets(api_key=api_key),
            root=tmp_path / "task",
        )
        return ctx, worker

    def test_segment_cache_per_key_prefix(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        monkeypatch.setenv("TEXLATE_CACHE_SCOPE", "per_key")
        ctx_a, wa = self._ctx(tmp_path / "a", "sk-A")
        ctx_b, wb = self._ctx(tmp_path / "b", "sk-B")
        cache_a = wa._make_cache(ctx_a)  # noqa: SLF001 -- 内部装配面即被测对象
        cache_b = wb._make_cache(ctx_b)  # noqa: SLF001
        cache_a["seg"] = "译"
        cache_b["seg"] = "译"
        key_a = cache_a.drain()[0][0]
        key_b = cache_b.drain()[0][0]
        fp_a = hashlib.sha256(b"sk-A").hexdigest()[:16]
        assert key_a.startswith(f"k{fp_a}:")
        assert key_a != key_b

    def test_segment_cache_shared_prefix(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        ctx_a, wa = self._ctx(tmp_path / "a", "sk-A")
        ctx_b, wb = self._ctx(tmp_path / "b", "sk-B")
        cache_a = wa._make_cache(ctx_a)  # noqa: SLF001
        cache_b = wb._make_cache(ctx_b)  # noqa: SLF001
        cache_a["seg"] = "译"
        cache_b["seg"] = "译"
        assert cache_a.drain()[0][0] == cache_b.drain()[0][0]


class TestFixloopWiring:
    """docs/08 §5：zh 编译首判非 clean → fixloop 规则循环 → 摘要留痕。"""

    def test_rescue_to_done(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        eng = FlakyEngine()
        with TestClient(_live_app(tmp_path, engine=eng)) as c:
            tid = _upload(c)["task_id"]
            snap = wait_terminal(c, tid)
            evs = _events(c, tid)
        assert snap["status"] == "done"
        fix_ev = [e for e in evs if e["type"] == "fixloop"]
        assert fix_ev, "fixloop 事件应落 task_events（可重放）"
        assert fix_ev[0]["data"]["verdict"] == "clean"
        done_ev = next(e for e in evs if e["type"] == "done")
        assert done_ev["data"]["stats"].get("fixloop") == "clean"
        # §5.5 cases 沉淀
        cases = tmp_path / "data" / "fixloop-cases.jsonl"
        assert cases.is_file()
        rows = [json.loads(x) for x in cases.read_text().splitlines() if x.strip()]
        assert any(r.get("corpus") == tid for r in rows)

    def test_exhausted_fault(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        eng = FlakyEngine(always_fail=True)
        with TestClient(_live_app(tmp_path, engine=eng)) as c:
            tid = _upload(c)["task_id"]
            snap = wait_terminal(c, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "fixloop_exhausted"
        fl = snap["error"].get("fixloop")
        assert fl is not None
        assert fl.get("verdict")
        assert "trace" in fl

    def test_disabled_by_option(
        self,
        tmp_path: Path,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        eng = FlakyEngine(always_fail=True)
        with TestClient(_live_app(tmp_path, engine=eng)) as c:
            tid = _upload(c, fields={"options": json.dumps({"fixloop": False})})[
                "task_id"
            ]
            snap = wait_terminal(c, tid)
            evs = _events(c, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "compile"  # 未跑 fixloop → 普通编译错
        assert "fixloop" not in snap["error"]
        assert not [e for e in evs if e["type"] == "fixloop"]
        # en + zh 各一编——没有第三轮就说明 loop 没跑
        zh_calls = [x for x in eng.calls if "build-zh" in str(x["wdir"])]
        assert len(zh_calls) == 1

    def test_disabled_by_env(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        clean_env: pytest.MonkeyPatch,  # noqa: ARG002
    ) -> None:
        monkeypatch.setenv("TEXLATE_NO_FIXLOOP", "1")
        eng = FlakyEngine(always_fail=True)
        with TestClient(_live_app(tmp_path, engine=eng)) as c:
            tid = _upload(c)["task_id"]
            snap = wait_terminal(c, tid)
        assert snap["status"] == "fault"
        assert snap["error"]["code"] == "compile"
        assert "fixloop" not in snap["error"]
