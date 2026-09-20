"""测试共享件：env 清洗 + fake engine/fetcher + client 工厂。

autouse 仅两件无副作用的隔离件（用户术语表钉缺席 + RedactFilter 还原）；
其余非 autouse——只服务显式取用 fixture 的测试文件（test_server_* /
test_e2e / test_cli）。fastapi/starlette 只走函数内延迟导入：本 conftest
对全测试集生效，server extra 缺装时其余测试集不能陪葬。
"""

from __future__ import annotations

import io
import logging
import os
import sqlite3
import sys
import tarfile
import time
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator

    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from texlate.arxiv.fetch import HeadInfo, SrcResult
    from texlate.compile.engine import CompRes
    from texlate.latex.model import ScanResult
    from texlate.server.store import Store
    from texlate.xlat.pipeline import ChunkIn, ChunkResult

#: BYOK/行为相关 env——测试必须拿到确定性无凭证环境。
#: ``TEXLATE_`` 前缀由 ``clean_env`` 全扫覆盖（新行为旗标自动免疫）；
#: 本表只收非前缀的外部变量。
_ENV_KEYS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "FAKE_BABELDOC_MODE",
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

#: 单 %s 槽文档模板（body 入槽）——latex 半解析测试的统一外壳。
DOC = "\\documentclass{article}\n\\begin{document}\n%s\n\\end{document}\n"

#: 双 %s 槽文档模板（preamble, body）——导言区机关测试用。
ART = "\\documentclass{article}\n%s\\begin{document}\n%s\n\\end{document}\n"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """清掉所有会改变 BYOK/路由/管线行为的 env（本机/CI 环境差异免疫）。

    ``TEXLATE_*`` 全前缀扫描——``NO_BWRAP``/``OFFLINE``/``NO_EXPAND``/
    ``NO_L2`` 等行为旗标与今后新增旗标一并免疫；非前缀外部键走
    ``_ENV_KEYS`` 名单。
    """
    for key in tuple(os.environ):
        if key.startswith("TEXLATE_"):
            monkeypatch.delenv(key, raising=False)
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    return monkeypatch


@pytest.fixture(autouse=True)
def _no_user_glossary(tmp_path: Path) -> Iterator[None]:
    """用户术语表缺省路径钉到不存在文件——宿主 ``~/.texlate/glossary.yaml``
    不得泄入测试（有文件时翻译 prompt 与 ``glossary_hash`` 全漂移）。

    两处绑定都要钉：``Glossary.load`` 读 ``xlat.glossary`` 模块全局；
    ``worker._share_glossary_hash`` 读 ``worker`` 顶层 from-import 的自身
    绑定。worker 未导入时不强拉——它之后 import 时会 from-bind 到
    glossary 已钉的值。

    不走 monkeypatch——autouse 消费它会把共享 monkeypatch 提前实例化、
    teardown 排到其它 autouse fixture 之后（曾致 test_compile_sandbox
    的 ``_clear_probe_caches`` 撞上未还原的 lambda）。手写存/还原。
    """
    from texlate.xlat import glossary as glossary_mod  # noqa: PLC0415

    missing = tmp_path / "no-user-glossary.yaml"
    orig = glossary_mod.USER_GLOSSARY_PATH
    glossary_mod.USER_GLOSSARY_PATH = missing
    seams_mod = sys.modules.get("texlate.server.worker.seams")
    seams_orig = getattr(seams_mod, "USER_GLOSSARY_PATH", None)
    if seams_mod is not None:
        seams_mod.USER_GLOSSARY_PATH = missing
    try:
        yield
    finally:
        glossary_mod.USER_GLOSSARY_PATH = orig
        if seams_mod is not None:
            seams_mod.USER_GLOSSARY_PATH = seams_orig


@pytest.fixture(autouse=True)
def _restore_log_filters() -> Iterator[None]:
    """用例后卸掉 ``install_log_scrub`` 挂的 ``RedactFilter``。

    app lifespan 每次起 app 都往 root/命名 logger 与其全部现有 handler
    （含 pytest capture handler）挂 filter 且不卸——provider 闭包与
    scrub 行为会泄漏给后续用例（断言含 ``sk-*``/``api_key=``/``Bearer``
    文本的 caplog 即序依赖炸）。
    """
    yield
    from texlate.server.settings import RedactFilter  # noqa: PLC0415

    loggers = [logging.getLogger()]
    loggers += [
        lg
        for lg in logging.Logger.manager.loggerDict.values()
        if isinstance(lg, logging.Logger)
    ]
    for lg in loggers:
        for f in [f for f in lg.filters if isinstance(f, RedactFilter)]:
            lg.removeFilter(f)
        for h in lg.handlers:
            for f in [f for f in h.filters if isinstance(f, RedactFilter)]:
                h.removeFilter(f)


@pytest.fixture(autouse=True)
def _testclient_loopback_host() -> Iterator[None]:
    """TestClient 缺省 ``base_url`` 钉 ``http://localhost``——配合 local Host 白名单。

    app ``request_gate_mw`` 在 local 形态拒非 loopback ``Host``（DNS
    rebinding 收口）；starlette 缺省 ``testserver`` 会让全量用例 403。
    包装 ``__init__`` 统一默认值——测试文件 ``from starlette.testclient
    import TestClient`` 拿到的是同一类对象，实例化时生效；显式传
    ``base_url`` 的用例不受影响。server extra 缺装时安静跳过。
    """
    try:
        from starlette.testclient import TestClient  # noqa: PLC0415
    except ImportError:
        yield
        return
    orig_init = TestClient.__init__

    def _init(self: TestClient, app: object, *args: object, **kwargs: object) -> None:
        kwargs.setdefault("base_url", "http://localhost")
        orig_init(self, app, *args, **kwargs)

    TestClient.__init__ = _init  # type: ignore[method-assign]
    try:
        yield
    finally:
        TestClient.__init__ = orig_init  # type: ignore[method-assign]


def make_targz(files: dict[str, str | bytes]) -> bytes:
    """内存构造 tar.gz（arxiv FakeFetcher 的 e-print 载荷）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, content in files.items():
            data = content.encode() if isinstance(content, str) else content
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def make_tar(members: list[tuple[tarfile.TarInfo, bytes]]) -> bytes:
    """内存构造裸 tar——TarInfo 由调用方造（对抗性元数据成员专用）。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for info, data in members:
            tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def tar_reg(name: str, size: int, **kw: object) -> tarfile.TarInfo:
    """普通文件 TarInfo；``**kw`` setattr 附加元数据（mode/uid/type 等）。"""
    info = tarfile.TarInfo(name)
    info.size = size
    for k, v in kw.items():
        setattr(info, k, v)
    return info


def tar_dir(name: str) -> tarfile.TarInfo:
    """目录 TarInfo。"""
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.size = 0
    return info


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
        flags: list[str] | None = None,  # noqa: ARG002
        should_cancel: Callable[[], bool] | None = None,  # noqa: ARG002
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
    本类对齐 ``engine_for(name, **kwargs)`` 签名与 ``Engine`` Protocol 全面
    （非 clean 时 fixloop 修复链会走 probe_file/install_file/filemap/caps
    ——空能力集 + 全 False 桩让 fixloop 真跑一轮后自然收敛）。
    ``produce_pdf=False`` 时返回无 pdf 的 CompRes（编译失败路径）。
    """

    caps: frozenset[str] = frozenset()

    def __init__(self, name: str, **kwargs: object) -> None:
        """记构造参数（halt_on_error 等引擎旋钮从此透传）。"""
        self.name = name
        self.ctor_kwargs = kwargs
        self.calls: list[dict[str, object]] = []
        self.produce_pdf = True

    def detect(self) -> str:
        """Protocol：返回假二进制路径（非 None = 可用）。"""
        return "/fake/engine"

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
        best_effort: bool = False,  # noqa: ARG002 -- fixloop salvage 旋钮
        flags: Iterable[str] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> CompRes:
        """写 ``<stem>.pdf``+干净 ``<stem>.log`` → ``CompRes(ok=True)``。"""
        import asyncio  # noqa: PLC0415

        from texlate.compile.engine import CompRes  # noqa: PLC0415

        if should_cancel is not None and should_cancel():
            raise asyncio.CancelledError
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
        self.calls.append(
            {
                "wdir": str(wdir),
                "main": main,
                "timeout": timeout,
                "passes": passes,
                "flags": list(flags) if flags else [],
            }
        )
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

    def probe_file(self, fname: str, *, cwd: Path | None = None) -> None:  # noqa: ARG002
        """Protocol：永远找不到（kpsewhich/filemap 语义全空）。"""
        return

    def install_file(
        self,
        fname: str,  # noqa: ARG002
        *,
        font_related: bool = False,  # noqa: ARG002
    ) -> bool:
        """Protocol：装不了。"""
        return False

    def rebuild_fontmaps(self) -> bool:
        """Protocol：noop False。"""
        return False

    def filemap(self, fname: str) -> list[str]:  # noqa: ARG002
        """Protocol：file→包索引空。"""
        return []

    def parse_log(self, res: CompRes) -> object:
        """Protocol：log_path 在则真解析，否则退 stdout_tail。"""
        from texlate.compile.engine import parse_log  # noqa: PLC0415

        text = (
            res.log_path.read_text(errors="replace")
            if res.log_path and res.log_path.exists()
            else res.stdout_tail
        )
        return parse_log(text)


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> dict[str, RecordingEngine]:
    """``texlate.e2e.engine_for`` 换 RecordingEngine + judge CJK 计数钉成 500。

    pdftotext 在假 pdf 上必败（→ -1 降级 note）——patch 成正常值让
    ``expect_cjk`` 路径判定确定、不受本机 poppler 有无影响。
    修复链 env 旗标（ENV_JUDGE/NO_L2/NO_FIXLOOP）钉成缺省——本机 env
    不污染报告形状。
    """
    import importlib  # noqa: PLC0415

    from texlate import e2e  # noqa: PLC0415

    engines: dict[str, RecordingEngine] = {}

    def factory(name: str, **kwargs: object) -> RecordingEngine:
        eng = RecordingEngine(name, **kwargs)
        engines.setdefault(name, eng)
        return eng

    monkeypatch.setattr(e2e, "engine_for", factory)
    for key in ("TEXLATE_ENV_JUDGE", "TEXLATE_NO_L2", "TEXLATE_NO_FIXLOOP"):
        monkeypatch.delenv(key, raising=False)
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
    deadline = time.monotonic() + timeout
    snap: dict = {}
    while time.monotonic() < deadline:
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


def scan_doc(body: str) -> ScanResult:
    """``parse_tex(DOC % body)``——v2 臂 canonical 小入口。"""
    from texlate.latex import parse_tex  # noqa: PLC0415

    return parse_tex(DOC % body)


def check_invariants(res: ScanResult, tex: str) -> None:
    """公共断言：恒等重建 + 校验零告警 + pieces 无缝平铺 vtex。"""
    from texlate.latex import reconstruct  # noqa: PLC0415
    from texlate.latex.reconstruct import validate_result  # noqa: PLC0415

    assert reconstruct(res) == tex
    assert validate_result(res) == []
    pos = 0
    for p in res.pieces:
        assert p.span.start == pos
        pos = p.span.end
    assert pos == len(res.vtex)


def chunk_text(res: ScanResult) -> str:
    """全部 chunk surface 拼接——泄漏断言的统一口径。"""
    return " ".join(c.content for c in res.chunks)


def blob(res: ScanResult) -> str:
    """全部 chunk content 的换行拼接。"""
    return "\n".join(c.content for c in res.chunks)


def mk_chunk(content: str, cid: str, kind: str = "para") -> ChunkIn:
    """``ChunkIn(chunk_id=cid, content=content, kind=kind)`` 小工厂。"""
    from texlate.xlat import pipeline as pl  # noqa: PLC0415

    return pl.ChunkIn(chunk_id=cid, content=content, kind=kind)


def run_pipeline(chunks: list[ChunkIn], **kw: object) -> list[ChunkResult]:
    """``asyncio.run(XlatPipeline(**kw).run(chunks))`` 同步壳。"""
    import asyncio  # noqa: PLC0415

    from texlate.xlat import pipeline as pl  # noqa: PLC0415

    return asyncio.run(pl.XlatPipeline(**kw).run(chunks))


def pass_validate(_src: str, _zh: str) -> str:
    """恒放行 validate hook——隔离校验层专测拦截臂。"""
    return ""


def mk_task_row(store: Store, **kw: object) -> dict:
    """create_task 缺省四字段（task_id/kind/target_lang/model），``**kw`` 透传。"""
    from texlate.server.store import new_task_id  # noqa: PLC0415

    kw.setdefault("task_id", new_task_id())
    kw.setdefault("kind", "arxiv")
    kw.setdefault("target_lang", "zh-CN")
    kw.setdefault("model", "m")
    return store.create_task(**kw)  # type: ignore[arg-type]


def mk_api_task(
    client: TestClient,
    arxiv_id: str,
    headers: dict | None = None,
    **json_kw: object,
) -> str:
    """POST ``/api/arxiv/{arxiv_id}/translate`` → task_id（缺省 202 断言）。"""
    r = client.post(
        f"/api/arxiv/{arxiv_id}/translate",
        json=dict(json_kw),
        headers=headers or {},
    )
    assert r.status_code == HTTPStatus.ACCEPTED, r.text
    return r.json()["task_id"]


def mk_task_dir(data: Path, task_id: str, files: dict[str, str | bytes]) -> Path:
    """合成 ``<data>/tasks/<id>`` 产物 + ``texlate.db`` 任务行（share pack 前置）。

    ``files`` = 成员名 → 内容（``str`` 走 UTF-8 text，``bytes`` 走 binary）。
    任务行填 share pack 满意的最小集（done/arxiv）；要变体行（状态/臂/
    cache_key）的复杂场景见 ``test_share_cli._mk_task`` 的参数化版。
    """
    from texlate.server.store import DDL  # noqa: PLC0415

    tdir = data / "tasks" / task_id
    tdir.mkdir(parents=True)
    for name, content in files.items():
        p = tdir / name
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
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
