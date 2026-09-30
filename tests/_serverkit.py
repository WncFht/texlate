"""server 测试公共骨架——``live_app``/``upload``/``events``/``preset_settings``/``sse_frames`` + ``FlakyEngine``。

``test_server_*``/``test_fixloop_live_events`` 簇逐文件复刻的同构脚手架归此
一处（沿用 ``_workerkit``/``_fixloopkit``/``_fuzzkit`` 抽取先例）：

- ``FlakyEngine``：按 wdir 记名的假引擎——每目录首编失败其后出 pdf，
  ``always_fail=True`` 时永不出 pdf（fixloop 规则耗尽路径）。
- ``live_app``：``start_worker`` app 工厂——translator/engine 双可注入
  （缺省 MockTranslator+FakeEngine），``**kw`` 透传 ``make_app``。
- ``upload``：POST ``/api/upload`` 一个 .tex（``tex`` 换内容、``fields``
  带额外表单字段），202 断言后回 body。
- ``events``：``task_events`` 全量回放（portal 回 loop 线程读 store）。
- ``preset_settings``：``create_app`` 前预写 settings.json（CORS/quota 等
  create 期读取项用）。
- ``sse_frames``：``GET /api/task/{id}`` SSE 流回放 → ``(id, event, data)``
  三元组；``last_event_id`` 非 None 即发 ``Last-Event-ID`` 头
  （``""``/``"abc"`` 等边界形也是显式传值，不按真值判断）。

文件域内变体（``_upload_pdf``、scoped ``_events`` 等）仍留各文件本地。
"""

from __future__ import annotations

import json
from functools import partial
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING

from conftest import MINI_TEX, FakeEngine, make_app

from texlate.compile.engine import CompRes, parse_log
from texlate.server.settings import SettingsStore
from texlate.xlat.pipeline import MockTranslator

if TYPE_CHECKING:
    from collections.abc import Callable

    from fastapi import FastAPI
    from starlette.testclient import TestClient

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
        flags: list[str] | None = None,
        should_cancel: Callable[[], bool] | None = None,  # noqa: ARG002
    ) -> CompRes:
        """同 wdir 首调失败（! 错 log）、其后成功出假 pdf。"""
        first = str(wdir) not in self.seen
        self.seen.add(str(wdir))
        ok = not self.always_fail and not first
        self.calls.append(
            {
                "wdir": str(wdir),
                "passes": passes,
                "best_effort": best_effort,
                "flags": flags,
            }
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


def live_app(
    tmp_path: Path,
    *,
    translator: object | None = None,
    engine: object | None = None,
    **kw: object,
) -> FastAPI:
    """start_worker app：可注入 translator/engine（缺省 Mock+Fake）。"""
    t = translator if translator is not None else MockTranslator()
    e = engine if engine is not None else FakeEngine()
    return make_app(
        tmp_path,
        start_worker=True,
        translator_factory=lambda _ctx: t,
        engine_factory=lambda _name: e,
        **kw,
    )


def upload(
    client: TestClient,
    tex: str = MINI_TEX,
    *,
    fields: dict[str, str] | None = None,
) -> dict:
    """POST /api/upload 一个 .tex（``fields`` 带额外表单字段）→ 202 body。"""
    r = client.post(
        "/api/upload",
        files={"file": ("main.tex", tex.encode(), "application/octet-stream")},
        data=fields or {},
    )
    assert r.status_code == HTTPStatus.ACCEPTED, r.text
    return r.json()  # type: ignore[no-any-return]


def events(client: TestClient, tid: str) -> list[dict]:
    """task_events 全量回放（portal 回 loop 线程读 store）。"""
    store = client.app.state.store
    return client.portal.call(partial(store.events_since, tid, 0))  # type: ignore[no-any-return]


def preset_settings(data_root: Path, **updates: object) -> None:
    """create_app 之前预写 settings.json（CORS/quota 等 create 期读取的项用）。"""
    data_root.mkdir(parents=True, exist_ok=True)
    SettingsStore(data_root).save(updates)


def sse_frames(
    client: TestClient,
    tid: str,
    last_event_id: str | None = None,
) -> list[tuple[str, str, dict]]:
    """回放 SSE 流 → ``[(id, event, data)]``（done 帧自然终流）。

    ``last_event_id is not None`` 即发 ``Last-Event-ID`` 头——``""`` 等
    边界值也算显式传（fuzz 面会喂），不能按真值判断。
    """
    headers = {"Accept": "text/event-stream"}
    if last_event_id is not None:
        headers["Last-Event-ID"] = last_event_id
    with client.stream("GET", f"/api/task/{tid}", headers=headers) as r:
        lines = [ln for ln in r.iter_lines() if ln]
    out: list[tuple[str, str, dict]] = []
    fid = ""
    for i, ln in enumerate(lines):
        if ln.startswith("id: "):
            fid = ln[4:]
        elif ln.startswith("event:"):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            data = (
                json.loads(nxt.removeprefix("data:").strip())
                if nxt.startswith("data:")
                else {}
            )
            out.append((fid, ln.removeprefix("event:").strip(), data))
    return out


#: L2 可归因错误 log：``(./main.tex`` 文件栈 + ``l.N`` 行号 → main.tex chunk。
#: 行号运行时取——ctex 注入往 preamble 塞了几十行，写死的行号会落在注入
#: 锅炉板里（chunk 全部在其后，顺序读取不变量下不可归因——#78 修复后
#: forward-fallback 不再把 preamble 错误错归给首个正文块）。
def _attr_err_log(wdir: Path, stem: str) -> str:
    """``l.N`` 指向 zh 树里首个译文块所在行（mock 标记 ``这是译文``）。"""
    ln = 1
    src = wdir / f"{stem}.tex"
    if src.is_file():
        for i, line in enumerate(
            src.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if "这是译文" in line:
                ln = i
                break
    return f"(./main.tex\n! Undefined control sequence.\nl.{ln} \\badcs\n"


class L2FlakyEngine:
    """按 wdir 计数的假引擎：``build-zh`` 前 ``n_fail`` 次 compile 出可归因
    L2 错误 log；``build-en`` 等其余目录恒净。

    ``n_fail=1`` → L2 重编即绿（验证 L2 修好就跳过 fixloop）；
    ``n_fail=2`` → L2 重编仍败 → 回落后**裸编验证**即绿；
    ``n_fail=3`` → 回落态验证仍败（验证 fixloop 在 L2 之后兜底）。
    en 侧必须恒净——worker 以 en 编译错误签名作 zh 归因的源生基线，
    en 同签名失败会把 zh 错误判源携带豁免掉（过滤语义本身正确，
    本 fixture 的前提是「en 干净、错由译文引入」）。
    探测面对齐 fixloop 会触到的 Engine 鸭子型。
    """

    name = "l2flaky"
    caps: frozenset[str] = frozenset()

    def __init__(self, n_fail: int = 1) -> None:
        """calls 记全部 compile（wdir/passes）供断言。"""
        self.n_fail = n_fail
        self.calls: list[dict[str, object]] = []

    def probe_file(self, fname: str, cwd: Path | None = None) -> bool:  # noqa: ARG002
        """Protocol：永远找不到。"""
        return False

    def install_file(
        self,
        fname: str,  # noqa: ARG002
        *,
        font_related: bool = False,  # noqa: ARG002
    ) -> bool:
        """Protocol：装不了。"""
        return False

    def filemap(self, fname: str) -> list[str]:  # noqa: ARG002
        """Protocol：空。"""
        return []

    def rebuild_fontmaps(self) -> None:
        """Protocol：noop。"""
        return

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
        flags: list[str] | None = None,  # noqa: ARG002
        should_cancel: Callable[[], bool] | None = None,  # noqa: ARG002
    ) -> CompRes:
        """build-zh 同 wdir 前 n_fail 次写出错 log 无 pdf，其后出假 pdf。"""
        n = sum(1 for c in self.calls if c["wdir"] == str(wdir))
        ok = n >= self.n_fail or "build-zh" not in str(wdir)
        self.calls.append(
            {"wdir": str(wdir), "passes": passes, "best_effort": best_effort}
        )
        stem = Path(main).stem
        log_path = wdir / f"{stem}.log"
        text = _CLEAN_LOG if ok else _attr_err_log(wdir, stem)
        log_path.write_text(text, encoding="utf-8")
        pdf = wdir / f"{stem}.pdf"
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
