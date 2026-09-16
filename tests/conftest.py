"""测试共享件：env 清洗 + fake engine/fetcher + client 工厂。

非 autouse——只服务显式取用 fixture 的测试文件（test_server_* /
test_e2e / test_cli）。fastapi/starlette 只走函数内延迟导入：本 conftest
对全测试集生效，server extra 缺装时其余测试集不能陪葬。
"""

from __future__ import annotations

import io
import tarfile
import time
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from texlate.arxiv.fetch import HeadInfo, SrcResult
    from texlate.compile.engine import CompRes

#: BYOK/行为相关 env——测试必须拿到确定性无凭证环境
_ENV_KEYS = (
    "TEXLATE_API_KEY",
    "TEXLATE_GATEWAY_KEY",
    "TEXLATE_BASE_URL",
    "TEXLATE_MODEL",
    "TEXLATE_MODE",
    "TEXLATE_CACHE_SCOPE",
    "TEXLATE_TRANSLATOR",
    "TEXLATE_NO_FIXLOOP",
    "TEXLATE_DATA_DIR",
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
)

#: 最小可编 tex 工程（section+双段——单行 body 不产生翻译 chunk）
MINI_TEX = (
    "\\documentclass{article}\n"
    "\\begin{document}\n"
    "\\section{Intro}\n"
    "This is a longer paragraph of English text that should definitely be\n"
    "segmented into at least one chunk for translation purposes.\n"
    "\n"
    "And a second paragraph here.\n"
    "\\end{document}\n"
)


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """清掉所有会改变 BYOK/路由行为的 env（本机/CI 环境差异免疫）。"""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


def make_targz(files: dict[str, str]) -> bytes:
    """内存构造 tar.gz（arxiv FakeFetcher 的 e-print 载荷）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            blob = content.encode()
            info = tarfile.TarInfo(name)
            info.size = len(blob)
            tf.addfile(info, io.BytesIO(blob))
    return buf.getvalue()


class FakeEngine:
    """``engine_factory`` 注入件：``compile`` 写假 pdf + ``CompRes(ok=True)``。"""

    def __init__(self) -> None:
        """calls 记录每次 compile 调用（wdir/main）。"""
        self.calls: list[dict[str, str]] = []

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
    ) -> CompRes:
        """不写真引擎：%PDF 假字节 + rc=0。judge 走 has_pdf 路径。"""
        from texlate.compile.engine import CompRes  # noqa: PLC0415

        pdf = wdir / (Path(main).stem + ".pdf")
        pdf.write_bytes(b"%PDF-1.4\n% fake pdf for tests\n")
        self.calls.append({"wdir": str(wdir), "main": main})
        return CompRes(
            engine="fake",
            ok=True,
            pdf=pdf,
            pdf_bytes=pdf.stat().st_size,
            rc=0,
            passes=passes,
            seconds=0.01,
        )


class RecordingEngine:
    """``texlate.e2e.engine_for`` 替换件：写真 pdf+log、记构造/compile 调用。

    与 FakeEngine 分工：FakeEngine 服务 server worker（无 name 构造参）；
    本类对齐 ``engine_for(name, **kwargs)`` 签名——xelatex 会收到
    ``halt_on_error=False``，构造 kwargs 与 compile 调用都可断言。
    ``produce_pdf=False`` 时返回无 pdf 的 CompRes（编译失败路径）。
    """

    def __init__(self, name: str, **kwargs: object) -> None:
        """记构造参数（halt_on_error 等引擎旋钮从此透传）。"""
        self.name = name
        self.ctor_kwargs = kwargs
        self.calls: list[dict[str, object]] = []
        self.produce_pdf = True

    def compile(  # noqa: PLR0913 -- 与 Engine.compile 同签名，kwarg 名是接口
        self,
        wdir: Path,
        main: str,
        *,
        passes: int = 1,
        timeout: float | None = None,
        outdir: Path | None = None,  # noqa: ARG002
        sandbox: bool = True,  # noqa: ARG002
        env_extra: dict[str, str] | None = None,  # noqa: ARG002
    ) -> CompRes:
        """写 ``<stem>.pdf``+干净 ``<stem>.log`` → ``CompRes(ok=True)``。"""
        from texlate.compile.engine import CompRes  # noqa: PLC0415

        stem = Path(main).stem
        pdf: Path | None = None
        pdf_bytes = 0
        if self.produce_pdf:
            pdf = wdir / f"{stem}.pdf"
            pdf.write_bytes(b"%PDF-1.4\n% fake pdf for tests\n")
            pdf_bytes = pdf.stat().st_size
        log = wdir / f"{stem}.log"
        log.write_text(
            "This is a fake log\nOutput written on disk.\n", encoding="utf-8"
        )
        self.calls.append({"wdir": str(wdir), "main": main, "timeout": timeout})
        return CompRes(
            engine=self.name,
            ok=True,
            pdf=pdf,
            pdf_bytes=pdf_bytes,
            log_path=log,
            rc=0,
            passes=passes,
            seconds=0.01,
        )


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> dict[str, RecordingEngine]:
    """``texlate.e2e.engine_for`` 换 RecordingEngine + judge CJK 计数钉成 500。

    pdftotext 在假 pdf 上必败（→ -1 降级 note）——patch 成正常值让
    ``expect_cjk`` 路径判定确定、不受本机 poppler 有无影响。
    """
    import importlib  # noqa: PLC0415

    from texlate import e2e  # noqa: PLC0415

    engines: dict[str, RecordingEngine] = {}

    def factory(name: str, **kwargs: object) -> RecordingEngine:
        eng = RecordingEngine(name, **kwargs)
        engines.setdefault(name, eng)
        return eng

    monkeypatch.setattr(e2e, "engine_for", factory)
    # 包级 re-export 的 judge 函数遮蔽了同名子模块属性路径——按模块对象打
    judge_mod = importlib.import_module("texlate.compile.judge")
    monkeypatch.setattr(judge_mod, "pdf_cjk_chars", lambda _p: 500)
    return engines


class FakeFetcher:
    """``head_src``/``get_src`` 鸭子型——内存 tar.gz 载荷，不触网。"""

    def __init__(self, body: bytes) -> None:
        """body = e-print blob（通常 make_targz 产物）。"""
        self._body = body

    def head_src(self, arxiv_id: str, version: int | None = None) -> HeadInfo:
        """固定 resolved_version=1 + etag（二次请求经 304/缓存短路）。"""
        from texlate.arxiv.fetch import HeadInfo  # noqa: PLC0415

        return HeadInfo(
            http_status=200,
            url=f"https://export.arxiv.org/e-print/{arxiv_id}",
            cd_filename=f"{arxiv_id}v1.tar.gz",
            resolved_version=version or 1,
            kind_hint="tar.gz",
            etag="fake-etag",
            content_length=len(self._body),
        )

    def get_src(
        self,
        arxiv_id: str,  # noqa: ARG002
        version: int,  # noqa: ARG002
        *,
        head: HeadInfo,
        etag: str = "",  # noqa: ARG002
        last_modified: str = "",  # noqa: ARG002
    ) -> SrcResult:
        """固定 OK + 真 sniff（_commit_phase 会真解包进缓存）。"""
        from texlate.arxiv.fetch import FetchStatus, SrcResult  # noqa: PLC0415
        from texlate.arxiv.sniff import sniff  # noqa: PLC0415

        return SrcResult(
            status=FetchStatus.OK,
            head=head,
            body=self._body,
            sniffed=sniff(self._body),
        )


def make_app(tmp_path: Path, **overrides: object) -> FastAPI:
    """create_app 包装：data_dir 落 tmp_path，默认 start_worker=False。"""
    from texlate.server.app import create_app  # noqa: PLC0415 -- server extra 延迟

    kw: dict[str, object] = {"data_dir": tmp_path / "data", "start_worker": False}
    kw.update(overrides)
    return create_app(**kw)  # type: ignore[arg-type]


def wait_terminal(client: TestClient, task_id: str, timeout: float = 30.0) -> dict:
    """轮询快照直到终态（worker 测试用；超时即断言失败）。"""
    deadline = time.time() + timeout
    snap: dict = {}
    while time.time() < deadline:
        snap = client.get(f"/api/task/{task_id}").json()
        if snap["status"] in (
            "done",
            "partial",
            "fault",
            "cancelled",
            "interrupted",
            "needs_auth",
        ):
            return snap
        time.sleep(0.05)
    pytest.fail(f"task {task_id} did not reach terminal: {snap}")
    return snap  # pragma: no cover -- fail() 不返回


@pytest.fixture
def client(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,  # noqa: ARG001 -- fixture 副作用（env 清洗）
) -> Iterator[TestClient]:
    """无 worker 的 TestClient（lifespan 已跑——store 已 open）。"""
    from starlette.testclient import TestClient  # noqa: PLC0415

    with TestClient(make_app(tmp_path)) as c:
        yield c


@pytest.fixture
def live_client(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,  # noqa: ARG001 -- fixture 副作用
) -> Iterator[TestClient]:
    """worker 跑全链的 TestClient：MockTranslator + FakeEngine。"""
    from starlette.testclient import TestClient  # noqa: PLC0415

    from texlate.xlat.pipeline import MockTranslator  # noqa: PLC0415

    engine = FakeEngine()
    app = make_app(
        tmp_path,
        start_worker=True,
        translator_factory=lambda _ctx: MockTranslator(),
        engine_factory=lambda _name: engine,
    )
    with TestClient(app) as c:
        yield c


def upload_tex(client: TestClient, tex: str = MINI_TEX) -> dict:
    """POST /api/upload 一个 .tex → 202 body。"""
    r = client.post(
        "/api/upload",
        files={"file": ("main.tex", tex.encode(), "application/octet-stream")},
    )
    assert r.status_code == HTTPStatus.ACCEPTED, r.text
    return r.json()
