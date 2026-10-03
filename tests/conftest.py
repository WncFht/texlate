"""测试共享件：env 清洗 + fake engine/fetcher + client 工厂。

autouse 仅两件无副作用的隔离件（用户术语表钉缺席 + RedactFilter 还原）；
其余非 autouse——只服务显式取用 fixture 的测试文件（test_server_* /
test_e2e / test_cli）。fastapi/starlette 只走函数内延迟导入。
"""

from __future__ import annotations

import contextlib
import io
import logging
import os
import re
import socket
import sqlite3
import sys
import tarfile
import time
from functools import partial
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator
    from types import ModuleType

    import httpx
    from fastapi import FastAPI
    from starlette.testclient import TestClient

    from texlate.arxiv.fetch import Fetcher, HeadInfo, SrcResult
    from texlate.arxiv.ratelimit import RateLimiter
    from texlate.compile.engine import CompRes
    from texlate.latex.gullet import Gullet
    from texlate.latex.model import ScanResult
    from texlate.latex.mouth import Tok
    from texlate.server.store import Store
    from texlate.server.worker import TaskCtx
    from texlate.validate.rules import RulesReport
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

#: 最小可编 tex 工程（section+ 双段——单行 body 不产生翻译 chunk）
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

#: 单 %s 槽 beamer 模板（body 入槽）——argspec/分派钉版的 beamer 外壳。
BEAMER = "\\documentclass{beamer}\n\\begin{document}\n%s\n\\end{document}\n"

#: 公共散文负载——凑足 scout ≥4 连词判据。
PROSE = "We consider a two form antisymmetric tensor field theory in detail"
#: 公共 cite-key 负载（非散文参钉版）。
KEY = "dalianis2020"

#: ctan/tlpdb 测试统一镜像字面量。
MIRROR = "https://m.test/tlnet"


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    """清掉所有会改变 BYOK/路由/管线行为的 env（本机/CI 环境差异免疫）。

    ``TEXLATE_*`` 全前缀扫描——``NO_BWRAP``/``OFFLINE``/``NO_EXPAND``/
    ``NO_LOGFIX`` 等行为旗标与今后新增旗标一并免疫；非前缀外部键走
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

    ``USER_GLOSSARY_PATH`` 在两模块都是 ``__getattr__`` 惰性名——teardown
    不能只回写当时算出的值（会落成冻结 attr、永久遮蔽惰性求值）：缺席
    的按 ``delattr`` 还原 ``__getattr__``，在场的才回写旧值。
    """
    from texlate.xlat import glossary as glossary_mod  # noqa: PLC0415

    missing = tmp_path / "no-user-glossary.yaml"
    seams_mod = sys.modules.get("texlate.server.worker.seams")
    mods = [glossary_mod] + ([seams_mod] if seams_mod is not None else [])
    absent = object()
    saved = {m: vars(m).get("USER_GLOSSARY_PATH", absent) for m in mods}
    for m in mods:
        m.USER_GLOSSARY_PATH = missing
    try:
        yield
    finally:
        for m in mods:
            if saved[m] is absent:
                del m.USER_GLOSSARY_PATH
            else:
                m.USER_GLOSSARY_PATH = saved[m]


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
    ``base_url`` 的用例不受影响。
    """
    from starlette.testclient import TestClient  # noqa: PLC0415

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


def make_tar(
    members: list[tuple[tarfile.TarInfo, bytes]],
    *,
    format: int = tarfile.DEFAULT_FORMAT,  # noqa: A002 -- tarfile.open 形参同名
) -> bytes:
    """内存构造裸 tar——TarInfo 由调用方造（对抗性元数据成员专用）。

    ``format`` 透传 ``tarfile.open``——ustar 钉版（``tarfile.USTAR_FORMAT``）
    走这里或下面 ``tar_bytes`` 的缺省。
    """
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=format) as tf:
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


def tar_bytes(
    members: dict[str, bytes] | Iterable[tuple[str, bytes]],
    *,
    format: int = tarfile.USTAR_FORMAT,  # noqa: A002 -- tarfile.open 形参同名
) -> bytes:
    """裸 tar 内存构造——``name→bytes`` 成员面，缺省钉 USTAR（``ustar`` 魔数 @257）。

    dict 与 ``(name, bytes)`` 对列皆收（对列形保留重复名表达力）；
    tar-gate 簇的 ``ustar_blob``/``_tar_bytes`` 本地副本统一收敛到此。
    """
    items = members.items() if isinstance(members, dict) else members
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w", format=format) as tf:
        for name, data in items:
            tf.addfile(tar_reg(name, len(data)), io.BytesIO(data))
    return buf.getvalue()


MIRROR = "https://m.test/tlnet"


def make_tarxz(
    members: dict[str, bytes] | Iterable[tuple[tarfile.TarInfo, bytes]],
) -> bytes:
    """内存构造 ``archive/<pkg>.tar.xz`` 响应体（dict 形为常规成员）。

    ``(TarInfo, bytes)`` 对列形留给对抗性元数据成员（traversal 钉版族）。
    """
    import lzma  # noqa: PLC0415 -- 一次性压缩件，随用随引

    if isinstance(members, dict):
        members = [(tar_reg(n, len(d)), d) for n, d in members.items()]
    return lzma.compress(make_tar(list(members)))


def make_zip(
    members: dict[str, str | bytes] | Iterable[tuple[str, str | bytes]],
) -> bytes:
    """内存构造 zip——``members`` 为 dict 或 ``(name, content)`` 对列
    （对列形保留重复名表达力——重名成员钉版勿改 dict）。"""
    import zipfile  # noqa: PLC0415

    buf = io.BytesIO()
    items = members.items() if isinstance(members, dict) else members
    with zipfile.ZipFile(buf, "w") as zf:
        for name, content in items:
            zf.writestr(name, content)
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
        """Protocol: noop False."""
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


def failing_engine(name: str, **kw: object) -> RecordingEngine:
    """永败引擎工厂——``produce_pdf=False`` 编译全不落 pdf。"""
    eng = RecordingEngine(name, **kw)
    eng.produce_pdf = False
    return eng


def judge_mod() -> ModuleType:
    """judge 子模块对象（包级 re-export 同名函数遮蔽模块属性路径）。"""
    import importlib  # noqa: PLC0415

    return importlib.import_module("texlate.compile.judge")


def make_comp_res(
    tmp_path: Path | None = None,
    *,
    pdf: bool = True,
    log_text: str = "",
    timed_out: bool = False,
    rc: int | None = 0,
) -> CompRes:
    """pdf/log 就绪的 ``CompRes``——judge/salvage 用例的编译产物替身。

    ``tmp_path`` 在场时写真 ``main.pdf``（``pdf_bytes`` 取真实大小）；缺席时
    钉 ``/nonexistent.pdf`` + 1024（fuzz/misschar 臂只读 log，不碰 pdf 路径）。
    """
    from texlate.compile.engine import CompRes  # noqa: PLC0415
    from texlate.compile.loginfo import parse_log  # noqa: PLC0415

    res = CompRes(engine="xelatex")
    res.ok = not timed_out
    res.timed_out = timed_out
    res.rc = rc
    if pdf:
        if tmp_path is None:
            res.pdf = Path("/nonexistent.pdf")
            res.pdf_bytes = 1024
        else:
            p = tmp_path / "main.pdf"
            p.write_bytes(b"%PDF-fake")
            res.pdf = p
            res.pdf_bytes = p.stat().st_size
    res.log = parse_log(log_text)
    return res


@pytest.fixture
def fake_engine(monkeypatch: pytest.MonkeyPatch) -> dict[str, RecordingEngine]:
    """``texlate.e2e.engine_for`` 换 RecordingEngine + judge CJK 计数钉成 500。

    pdftotext 在假 pdf 上必败（→ -1 降级 note）——patch 成正常值让
    ``expect_cjk`` 路径判定确定、不受本机 poppler 有无影响。
    修复链 env 旗标（ENV_JUDGE/NO_LOGFIX/NO_FIXLOOP）钉成缺省——本机 env
    不污染报告形状。
    """
    from texlate import e2e  # noqa: PLC0415

    engines: dict[str, RecordingEngine] = {}

    def factory(name: str, **kwargs: object) -> RecordingEngine:
        eng = RecordingEngine(name, **kwargs)
        engines.setdefault(name, eng)
        return eng

    monkeypatch.setattr(e2e, "engine_for", factory)
    for key in ("TEXLATE_ENV_JUDGE", "TEXLATE_NO_LOGFIX", "TEXLATE_NO_FIXLOOP"):
        monkeypatch.delenv(key, raising=False)
    # 包级 re-export 的 judge 函数遮蔽了同名子模块属性路径——按模块对象打
    monkeypatch.setattr(judge_mod(), "pdf_text_stats", lambda _p: (500, 0))
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
        arxiv_id: str,
        version: int | None = None,
        *,
        head: HeadInfo | None = None,
        etag: str = "",  # noqa: ARG002
        last_modified: str = "",  # noqa: ARG002
    ) -> SrcResult:
        """固定 OK + 真 sniff（_commit_phase 会真解包进缓存）。

        签名对齐 ``Fetcher.get_src``——``head=None`` 时内置 HEAD 预检
        （本替身即 ``self.head_src``）。
        """
        from texlate.arxiv.fetch import FetchStatus, SrcResult  # noqa: PLC0415
        from texlate.arxiv.sniff import sniff  # noqa: PLC0415

        if head is None:
            head = self.head_src(arxiv_id, version)
        return SrcResult(
            status=FetchStatus.OK,
            head=head,
            body=self._body,
            sniffed=sniff(self._body),
        )


class FakeClock:
    """注入限速器/重试的 fake 时钟：sleep 即前进并记账，零真等待。

    逐文件 ``_Clock`` 副本的统一形——``slept`` 是全集成员（不读的变体
    缺席此属性也无妨，clk.sleeps 读取点改名为 slept 即对齐）。
    """

    def __init__(self) -> None:
        """t=真实 epoch（day rollover 语义正常）；slept 记全部睡眠时长。"""
        self.t = 1_700_000_000.0
        self.slept: list[float] = []

    def now(self) -> float:
        """当前假时刻。"""
        return self.t

    def sleep(self, d: float) -> None:
        """记 d 秒睡眠并前进时钟。"""
        self.slept.append(d)
        self.t += d


def mk_fetcher(  # noqa: PLR0913 -- 线形 fetcher 工厂，每 kwarg 即一个注入面
    handler: httpx.MockTransport | Callable[[httpx.Request], httpx.Response],
    clk: FakeClock,
    *,
    hosts: tuple[str, ...] = ("arxiv.org", "export.arxiv.org"),
    follow_redirects: bool = False,
    rl: RateLimiter | None = None,
    sleep: Callable[[float], None] | None = None,
) -> Fetcher:
    """共享 MockTransport ``Fetcher`` 工厂——限速/重试睡眠全挂 ``clk``。

    ``handler`` 收预制 ``httpx.MockTransport``（meta/fetch/html 形）或裸
    ``Callable``（fuzz 形，此处包一层 MockTransport）。``rl`` 传预置桶
    （断路/park 注入面）；``sleep`` 是 ``Fetcher`` 层重试睡眠，默认
    ``clk.sleep`` 假睡（需真睡眠语义的钉传 ``time.sleep``）。
    """
    import httpx as _httpx  # noqa: PLC0415

    from texlate.arxiv.fetch import Fetcher  # noqa: PLC0415
    from texlate.arxiv.ratelimit import RateLimiter  # noqa: PLC0415

    transport = (
        handler
        if isinstance(handler, _httpx.MockTransport)
        else _httpx.MockTransport(handler)
    )
    return Fetcher(
        rl if rl is not None else RateLimiter(clock=clk.now, sleep=clk.sleep),
        client=_httpx.Client(transport=transport, follow_redirects=follow_redirects),
        hosts=hosts,
        sleep=clk.sleep if sleep is None else sleep,
    )


def make_app(tmp_path: Path, **overrides: object) -> FastAPI:
    """create_app 包装：data_dir 落 tmp_path，默认 start_worker=False。"""
    from texlate.server.app import create_app  # noqa: PLC0415

    kw: dict[str, object] = {"data_dir": tmp_path / "data", "start_worker": False}
    kw.update(overrides)
    return create_app(**kw)  # type: ignore[arg-type]


def live_app(
    tmp_path: Path,
    translator_factory: Callable[[TaskCtx], object],
    **overrides: object,
) -> FastAPI:
    """``start_worker=True`` 的 app——FakeEngine 常驻；``overrides`` 透传 ``make_app``。"""
    kw: dict[str, object] = {
        "start_worker": True,
        "translator_factory": translator_factory,
        "engine_factory": lambda _name: FakeEngine(),
    }
    kw.update(overrides)
    return make_app(tmp_path, **kw)


@contextlib.contextmanager
def refused_base_url() -> Iterator[str]:
    """bind 127.0.0.1:0 不 listen——确定性 ECONNREFUSED 的 base_url。

    块内一直占着端口（bind 即占、不进 listen 队列必拒连），泄放前不被外部
    抢占——bind-release 的窗口期端口可能被别的进程拿走后变成可连，假阴性源。
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        yield f"http://127.0.0.1:{sock.getsockname()[1]}"


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
def server_client(
    tmp_path: Path,
    clean_env: pytest.MonkeyPatch,  # noqa: ARG001 -- fixture 副作用
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[TestClient]:
    """server 形态 TestClient（worker 按住）。"""
    from starlette.testclient import TestClient  # noqa: PLC0415

    monkeypatch.setenv("TEXLATE_MODE", "server")
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
    app = live_app(
        tmp_path,
        lambda _ctx: MockTranslator(),
        engine_factory=lambda _name: engine,
    )
    with TestClient(app) as c:
        yield c


@pytest.fixture
def recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """``asyncio.sleep`` 录制——退避节奏断言靠录不靠真睡。"""
    import asyncio  # noqa: PLC0415

    sleeps: list[float] = []

    async def fake_sleep(d: float) -> None:
        sleeps.append(d)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return sleeps


@pytest.fixture
def plain_terminal(monkeypatch: pytest.MonkeyPatch) -> None:
    """钉无色彩端——纯文本断言前提（opt-in：仅取用者钉版）。

    ``FORCE_COLOR``/``TTY_COMPATIBLE`` 会把 rich ``is_terminal`` 顶成 True
    （capsys/CliRunner 捕获非 tty 也出 ANSI），须摘除；``console._color_system``
    又在 import 时已按当时环境冻结，运行期摘 env 不改已缓存的色域——须置
    None 让 ``style.render`` 走无色路径。
    """
    from texlate.cli._output import console  # noqa: PLC0415

    for key in ("FORCE_COLOR", "TTY_COMPATIBLE"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(console, "_color_system", None)


def upload_tex(client: TestClient, tex: str = MINI_TEX) -> dict:
    """POST /api/upload 一个 .tex → 202 body。"""
    r = client.post(
        "/api/upload",
        files={"file": ("main.tex", tex.encode(), "application/octet-stream")},
    )
    assert r.status_code == HTTPStatus.ACCEPTED, r.text
    return r.json()


def upload(  # noqa: PLR0913 -- conftest hoist 目标签名（tex/name/data/fields 全槽）
    client: TestClient,
    tex: str = MINI_TEX,
    *,
    name: str = "main.tex",
    data: bytes | None = None,
    fields: dict[str, str] | None = None,
    content_type: str = "application/octet-stream",
    **post_kw: object,
) -> dict:
    """POST /api/upload → 202 body（multipart ``file`` + ``fields`` 表单槽）。"""
    r = client.post(
        "/api/upload",
        files={
            "file": (name, data if data is not None else tex.encode(), content_type)
        },
        data=fields or {},
        **post_kw,
    )
    assert r.status_code == HTTPStatus.ACCEPTED, r.text
    return r.json()


def scan_doc(body: str) -> ScanResult:
    """``parse_tex(DOC % body)``——v2 臂 canonical 小入口。"""
    from texlate.latex import parse_tex  # noqa: PLC0415

    return parse_tex(DOC % body)


def scan(body: str, defs: str = "", art: str = ART) -> ScanResult:
    """``art % (defs, body)`` → ``parse_tex`` → ``check_invariants`` 三件套。"""
    from texlate.latex import parse_tex  # noqa: PLC0415

    tex = art % (defs, body)
    res = parse_tex(tex)
    check_invariants(res, tex)
    return res


#: ``_segkit.scan_art`` 的同位名——两 home 签名一致，conftest 是公共源。
scan_art = scan


def ph_bodies(res: ScanResult, kind: str = "CMD") -> list[str]:
    """全部 ``[[KIND_n]]`` ph 体（覆盖区间原文）。

    ``fullmatch`` 与 ``startswith("[[KIND_")`` 等效——PlaceholderIssuer 只产
    ``[[TYPE_\\d+]]`` 键；必须带下划线，裸 ``[[ENV`` 前缀会误吃 ``[[ENVTAG_n]]``。
    """
    return [
        body
        for ph, body in res.ph_map.items()
        if re.fullmatch(rf"\[\[{kind}_\d+\]\]", ph)
    ]


def cmd_bodies(res: ScanResult) -> list[str]:
    """全部 ``[[CMD_n]]`` ph 体（覆盖区间原文）。"""
    return ph_bodies(res, "CMD")


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


def toks(src: str) -> list[Tok]:
    """Mouth 全量 tokenize。"""
    from texlate.latex.mouth import Mouth  # noqa: PLC0415

    return list(Mouth(src))


def text_of(ts: Iterable[Tok]) -> str:
    """token 流 → 表面文本（cs 反带 ``\\``；``consumed`` marker 是事件非文本）。"""
    return "".join(str(t) for t in ts if t.kind != "consumed")


def expand(src: str) -> tuple[list[Tok], Gullet]:
    """Gullet 全量展开，返回 (tokens, gullet) 便于查 warnings。"""
    from texlate.latex.gullet import Gullet  # noqa: PLC0415

    g = Gullet(src)
    return list(g), g


def expanded_text(src: str) -> str:
    """展开到不动点后的表面文本。"""
    ts, _ = expand(src)
    return text_of(ts)


def mk_chunk(content: str, cid: str, kind: str = "para") -> ChunkIn:
    """``ChunkIn(chunk_id=cid, content=content, kind=kind)`` 小工厂。"""
    from texlate.xlat import pipeline as pl  # noqa: PLC0415

    return pl.ChunkIn(chunk_id=cid, content=content, kind=kind)


def big_para(
    cid: str,
    fill: str = "x",
    tail: str = "",
    prefix: str = "Long prose ",
    ph_fragments: dict[str, str] | None = None,
) -> ChunkIn:
    """``prefix + fill*400 + tail`` 惰性填料块——够长但远低于切分门限。"""
    c = mk_chunk(prefix + fill * 400 + tail, cid)
    c.ph_fragments = ph_fragments
    return c


def run_pipeline(chunks: list[ChunkIn], **kw: object) -> list[ChunkResult]:
    """``asyncio.run(XlatPipeline(**kw).run(chunks))`` 同步壳。"""
    import asyncio  # noqa: PLC0415

    from texlate.xlat import pipeline as pl  # noqa: PLC0415

    return asyncio.run(pl.XlatPipeline(**kw).run(chunks))


def pass_validate(_src: str, _zh: str) -> str:
    """恒放行 validate hook——隔离校验层专测拦截臂。"""
    return ""


def _issues(rep: RulesReport, rule: str) -> list:
    return [i for i in rep.issues if i.rule == rule]


def l0_sev(rep: RulesReport, rule: str) -> list:
    """``rep.issues`` 按 ``rule`` 过滤取 severity 列。"""
    return [i.severity for i in rep.issues if i.rule == rule]


def mk_task_row(store: Store, **kw: object) -> dict:
    """create_task 缺省四字段（task_id/kind/target_lang/model），``**kw`` 透传。"""
    from texlate.server.store import new_task_id  # noqa: PLC0415

    kw.setdefault("task_id", new_task_id())
    kw.setdefault("kind", "arxiv")
    kw.setdefault("target_lang", "zh-CN")
    kw.setdefault("model", "m")
    return store.create_task(**kw)  # type: ignore[arg-type]


def mk_store(tmp_path: Path, name: str = "x.db") -> Store:
    """开好连接的 Store（DDL 已落）。"""
    from texlate.server.store import Store  # noqa: PLC0415

    s = Store(tmp_path / name)
    s.open()
    return s


def mk_task_id(store: Store, **kw: object) -> str:
    """建行 → task_id（``mk_task_row`` 的 id 投影）。"""
    return str(mk_task_row(store, **kw)["id"])


def mk_chunk_row(seq: int, **over: object) -> dict:
    """``insert_chunks`` 行 dict 工厂——``**over`` 覆盖缺省值。"""
    row: dict[str, object] = {
        "seq": seq,
        "chunk_id": f"c{seq}",
        "src_file": "main.tex",
        "byte_start": seq * 10,
        "byte_end": seq * 10 + 9,
        "kind": "text",
        "src_text": f"t{seq}",
    }
    return row | over


def chunk_row(
    seq: int,
    *,
    chunk_id: str | None = None,
    kind: str = "text",
    src_text: str | None = None,
) -> dict:
    """``insert_chunks`` 行 dict——缺省 ``c{seq}``/``text {seq}`` 槽位。

    与 ``mk_chunk_row`` 的分工：本件是 kw-only 具名槽（fuzz 族原位签名），
    ``mk_chunk_row`` 是 ``**over`` 全字段覆盖形（fixes2/compat 族签名）。
    """
    return {
        "seq": seq,
        "chunk_id": chunk_id or f"c{seq}",
        "src_file": "main.tex",
        "byte_start": seq * 10,
        "byte_end": seq * 10 + 9,
        "kind": kind,
        "src_text": src_text if src_text is not None else f"text {seq}",
    }


def store_call[T](client: TestClient, fn: Callable[..., T], *args: object) -> T:
    """``portal.call`` 回 loop 线程直调 store 方法（events/get 同缝）。"""
    return client.portal.call(partial(fn, *args))


def task_events(client: TestClient, tid: str) -> list[dict]:
    """task_events 全量回放（portal 回 loop 线程读 store）。"""
    return store_call(client, client.app.state.store.events_since, tid, 0)


def force_status(client: TestClient, tid: str, status: str) -> None:
    """store.transition force 通道——把任务钉到指定状态。"""
    client.portal.call(
        partial(client.app.state.store.transition, tid, status, force=True)
    )


def get_row(client: TestClient, tid: str) -> dict | None:
    """portal 回 loop 线程读 ``store.get(tid)`` 行。"""
    return client.portal.call(partial(client.app.state.store.get, tid))


def reg_artifact(
    client: TestClient,
    tid: str,
    kind: str,
    name: str,
    blob: bytes = b"%PDF-1.4 fake",
) -> dict:
    """``tasks/{tid}/{name}`` 落盘 + files 表登记 → rec（含 path/sha256）。"""
    tdir = client.app.state.data_dir / "tasks" / tid
    tdir.mkdir(parents=True, exist_ok=True)
    (tdir / name).write_bytes(blob)
    return client.portal.call(
        partial(client.app.state.store.put_file, tid, kind, name, data_dir=tdir)
    )


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


def write_tex(root: Path, rel: str, text: str) -> Path:
    """mkdir -p + 写文——返回落件 Path。"""
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


#: ``_write`` 原位名同体——既有 ``from conftest import _write`` 取用面不改名。
_write = write_tex


def make_project(root: Path, main: str = MINI_TEX) -> Path:
    """单文件 tex 工程：``root/main.tex`` 落 ``main`` 并返回 root。"""
    root.mkdir(parents=True, exist_ok=True)
    (root / "main.tex").write_text(main, encoding="utf-8")
    return root
