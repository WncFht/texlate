"""管线 worker + 任务队列分发器（web-layer §3.1/§3.4）。

- ``TaskRunner``：进程内 ``asyncio.Queue`` + 单 worker 串行（等价
  Semaphore(1) 管线槽——下载/编译重活串行，翻译块级并行由
  ``XlatPipeline`` 内部 ``Semaphore(concurrency)`` 管）；内存 secrets
  注册表（key 绝不入库）；心跳 ticker 维护 ``updated_at``。
- ``PipelineWorker``：驱动产品公共 API 跑真实管线——
  ``acquire_source → route_project → normalize_project → parse_file →
  XlatPipeline → reconstruct → prepare_chinese → engine.compile → judge``。
  阻塞段一律 ``asyncio.to_thread``，DB 写只发生在 loop 线程。
- 断点恢复三级：stage 级磁盘哨兵（``.fetch-done``/``.base-done``/
  ``.splice-done`` + chunks 行）、chunk 级 chunks 表 ``status='pending'``
  续跑、事件级 ``task_events`` 重放。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import logging
import os
import re
import secrets as secrets_mod
import shutil
import sqlite3
import threading
import time
import zipfile
from collections import defaultdict, deque
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass, field
from http import HTTPStatus
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, TypeVar

from texlate import __version__
from texlate.align import build_alignment
from texlate.arxiv.cache import CacheEntry, SourceCache
from texlate.arxiv.fetch import (
    AcquireStatus,
    Fetcher,
    acquire_source,
    normalize_arxiv_id,
)
from texlate.arxiv.meta import fetch_metadata
from texlate.arxiv.ratelimit import RateLimiter
from texlate.arxiv.sniff import BlobKind, SniffError, sniff
from texlate.arxiv.unpack import (
    MAX_FILE_BYTES,
    UnpackError,
    unpack_sniffed,
)
from texlate.compile.engine import CompRes, Engine, engine_for, route_project
from texlate.compile.fixloop import CaseSink, fixloop
from texlate.compile.fixloop.llm_hook import make_llm_hook
from texlate.compile.inject import (
    InjectRejectError,
    find_main_tex,
    prepare_chinese,
)
from texlate.compile.judge import judge
from texlate.compile.normalize import normalize_project
from texlate.compile.probe import dep_seen, deps_diff, target_probe
from texlate.compile.sandbox import find_tool
from texlate.e2e import (
    _ENV_ENV_JUDGE,
    _ENV_NO_L2,
    _KNOWN_ENVS,
    _VERDICT_RANK,
    L2_MAX_CHUNKS,
    _env_flag,
    _env_judge_all,
    _l2_localize,
    _resplice,
    _retranslate_hits,
    _split_cid,
    _TreeRun,
)
from texlate.latex.api import parse_file
from texlate.latex.reconstruct import reconstruct
from texlate.server.babeldoc import (
    BabeldocJob,
    BabeldocRun,
    default_timeout,
    lang_out_for,
    run_babeldoc,
    write_glossary_csv,
)
from texlate.server.settings import (
    SettingsStore,
    cache_scope,
    resolve_auth,
    scrub,
    share_dir,
    validate_model,
)
from texlate.server.store import (
    ACTIVE_STATUSES,
    TERMINAL_STATUSES,
    Store,
    StoreError,
)
from texlate.share import index_append, pack_share, unpack_share
from texlate.validate.l0 import validate_pair
from texlate.xlat.client import (
    AuthError,
    ChatClient,
    ChatError,
    RetryableHTTPError,
    UsageRecord,
)
from texlate.xlat.glossary import (
    LOCAL_GLOSSARY_NAME,
    USER_GLOSSARY_PATH,
    Glossary,
)
from texlate.xlat.pipeline import (
    ChunkIn,
    ChunkResult,
    GatewayTranslator,
    MockTranslator,
    PipelineConfig,
    Translator,
    XlatPipeline,
    chunk_to_in,
)
from texlate.xlat.placeholders import collect_doc_placeholders
from texlate.xlat.prompts import PROMPT_VERSION, normalize_kind
from texlate.xlat.state import ChunkRecord, atomic_json

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Mapping

    from pypdf import PdfWriter
    from pypdf.generic import DictionaryObject

    from texlate.compile.fixloop.ctan import TlpdbIndex
    from texlate.compile.fixloop.engine import LlmHook
    from texlate.compile.judge import Verdict
    from texlate.compile.probe import ProbeReport
    from texlate.latex.model import Chunk, ScanResult
    from texlate.server.events import EventBus

log = logging.getLogger(__name__)

_T = TypeVar("_T")

#: 进度刻度（§2.2：fetching 3→9 / parsing 9→25 / translating 25→85 /
#: compiling 90→99 / 终态 100）
PROGRESS = {
    "fetching": (3, 9),
    "parsing": (9, 25),
    "translating": (25, 85),
    "compiling": (90, 99),
}

#: 管线版本（cache_key 成分；prompt 模板或产品版本变即失效）
PIPELINE_VERSION = f"texlate-{__version__}|{PROMPT_VERSION}"

#: chunk 落盘批量 flush 阈值（§3.4.2：每 8 块或 500ms）
_FLUSH_N = 8
_FLUSH_MS = 0.5

#: 编译超时（docs/08 §4.1 默认值）
COMPILE_TIMEOUT = 240.0

#: 心跳间隔（updated_at 供 SSE/列表页判活）
_HEARTBEAT_S = 5.0

#: upload_tex 解包文件数上限（§2.4：4000 文件）
_MAX_UNPACK_FILES = 4000

#: files.kind → URL kind（§2.3 白名单表）
KIND_URL = {
    "src_tar": "src.tar",
    "en_pdf": "en.pdf",
    "zh_pdf": "zh.pdf",
    "dual_pdf": "dual.pdf",
    "dual_json": "dual.json",
    "zh_src_zip": "zh-src.zip",
    "compile_log": "compile.log",
    "md_zip": "md",
    "zh_docx": "zh.docx",
    "zh_epub": "zh.epub",
}
#: URL kind → files.kind（反查）
URL_KIND = {v: k for k, v in KIND_URL.items()}

#: fetch 失败中重试无意义的终态
_FETCH_NO_RETRY = frozenset(
    {
        AcquireStatus.PDF_ONLY,
        AcquireStatus.UNKNOWN_FORMAT,
        AcquireStatus.TOO_LARGE,
        AcquireStatus.NOT_FOUND,
    }
)

#: zip 成员名拒绝面：绝对路径/盘符
_BAD_ZIP_NAME = re.compile(r"^(?:[a-zA-Z]:|/|\\)")

#: 任务树内哨兵文件（断点恢复用，不进 zh-src.zip / fixloop 回灌）
_SENTINELS = frozenset({".fetch-done", ".base-done", ".splice-done", ".compile-done"})

#: probe diff 聚合行的列表截断上限（一条行不刷屏，超出记 +N）
_PROBE_LIST_CAP = 8

#: ``dep_seen`` 三值 → missing 复核标签：recorded=曾被 .fls/.mk 记录（路径/
#: 时序问题，勿装包）；unseen=真缺失（fixloop install_file 候选）；
#: n/a=引擎未产依赖记录，不可判
_PROBE_SEEN_TAG: dict[bool | None, str] = {
    True: "recorded",
    False: "unseen",
    None: "n/a",
}

#: fixloop 回灌 zh/ 的 TeX 输入层扩展名——rewrite 目标面 + ctan_fetch
#: 平铺落盘面 + install_sysfont 可能投放的字体文件；编译产物
#: （aux/log/pdf/_tect_out/）不在列
_FIXLOOP_SRC_EXTS = frozenset(
    {
        ".tex",
        ".ltx",
        ".latex",
        ".sty",
        ".cls",
        ".bib",
        ".bst",
        ".def",
        ".cfg",
        ".clo",
        ".fd",
        ".tfm",
        ".vf",
        ".enc",
        ".map",
        ".pro",
        ".bbl",
        ".ist",
        ".ins",
        ".dtx",
        ".otf",
        ".ttf",
        ".ttc",
        ".pfb",
        ".afm",
    }
)


def _scrub_deep(value: Any, api_key: str) -> Any:  # noqa: ANN401 -- JSON 形状递归天然 Any
    """递归抹 JSON-able 结构里字符串的 secret 形态（事件载荷落盘前调用）。"""
    if isinstance(value, str):
        return scrub(value, api_key)
    if isinstance(value, list):
        return [_scrub_deep(v, api_key) for v in value]
    if isinstance(value, dict):
        return {k: _scrub_deep(v, api_key) for k, v in value.items()}
    return value


def _fixloop_summary(cell: dict[str, Any]) -> dict[str, Any]:
    """Fixloop cell → 压缩摘要：每轮 ``{cat,pay,rule,result}`` + 前置动作。

    ``rounds``（cat/pay/pdf/n_errors）与 ``actions``（rule/detail）按 round
    归并；``round=0/-1`` 是 precheck/gate 动作，单列 ``setup``——salvage
    轮（round 键为 int、action 键为 ``"salvage"``）单独对齐。
    """
    by_round: dict[str, list[dict[str, Any]]] = {}
    for a in cell.get("actions") or []:
        by_round.setdefault(str(a.get("round")), []).append(a)
    trace = []
    for r in cell.get("rounds") or []:
        acts = by_round.get("salvage" if r.get("salvage") else str(r.get("round")), [])
        head = acts[0] if acts else {}
        trace.append(
            {
                "round": r.get("round"),
                "cat": r.get("category"),
                "pay": r.get("payload"),
                "pdf": bool(r.get("pdf")),
                "n_errors": r.get("n_errors"),
                "rule": head.get("rule"),
                "result": head.get("detail"),
            }
        )
    return {
        "verdict": cell.get("verdict"),
        "main": cell.get("main"),
        "engine": cell.get("engine"),
        "trace": trace,
        "setup": [
            {"rule": a.get("rule"), "result": a.get("detail")}
            for a in cell.get("actions") or []
            if a.get("round") in (0, -1)
        ],
        "installed": cell.get("installed") or [],
        "advisories": cell.get("advisories") or [],
    }


def _sync_fixed_sources(work: Path, zh: Path) -> int:
    """Fixloop 改动回灌：``work`` 内 TeX 输入层文件 → ``zh/`` 镜像（含删除）。

    copytree 起点两侧一致，分叉只来自 fixloop 改写/落包/隔离——按
    ``_FIXLOOP_SRC_EXTS`` 同步并删除 ``zh/`` 侧多余源文件（rename 隔离
    类规则的删除语义）；``_*`` 前缀目录（_tect_out/_minted-*）与哨兵不进。
    返回变更文件数。
    """
    keep: set[str] = set()
    n = 0
    for f in work.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(work)
        if rel.parts[0].startswith("_") or f.name in _SENTINELS:
            continue
        if f.suffix.lower() not in _FIXLOOP_SRC_EXTS:
            continue
        keep.add(rel.as_posix())
        dst = zh / rel
        if not dst.is_file() or dst.read_bytes() != f.read_bytes():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(f, dst)
            n += 1
    for f in zh.rglob("*"):
        if (
            f.is_file()
            and f.name not in _SENTINELS
            and f.suffix.lower() in _FIXLOOP_SRC_EXTS
            and f.relative_to(zh).as_posix() not in keep
        ):
            f.unlink()
            n += 1
    return n


class _RecEngine:
    """``Engine`` 透传代理：记录末次 ``CompRes``（fixloop 内部重编终态取回）。

    ``__getattr__``/``__setattr__`` 全落真引擎——``_wire_engine`` 给
    tectonic 注入 ``ctan_fetch`` callable 必须写在真引擎实例上。
    """

    _inner: Engine
    last: CompRes | None

    def __init__(self, inner: Engine) -> None:
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "last", None)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 -- 代理转发面天然 Any
        return getattr(object.__getattribute__(self, "_inner"), name)

    def __setattr__(self, name: str, value: Any) -> None:  # noqa: ANN401 -- 同上
        setattr(object.__getattribute__(self, "_inner"), name, value)

    def compile(self, wdir: Path, main: str, **kw: Any) -> CompRes:  # noqa: ANN401
        """透传 compile 并记录 CompRes（fixloop 每轮重编都过这里）。"""
        res = self._inner.compile(wdir, main, **kw)
        object.__setattr__(self, "last", res)
        return res


@dataclass(slots=True)
class Secrets:
    """BYOK 运行时凭证（只在内存里活过任务生命周期，绝不入库）。"""

    api_key: str = ""
    base_url: str = ""
    model: str = ""
    source: str = "none"


@dataclass(slots=True)
class TaskCtx:
    """单次 run 的工作上下文：任务行快照 + 目录布局 + 内存态。"""

    store: Store
    bus: EventBus
    task_id: str
    row: dict[str, Any]
    secrets: Secrets
    root: Path  # tasks/{id}/
    scans: dict[str, ScanResult] = field(default_factory=dict)
    main_rel: str = ""
    engine_name: str = "tectonic"
    tokens_est: int = 0
    #: fixloop 跑过的压缩摘要（verdict/trace/installed）——_stage_compile
    #: 终态写 error_json / done 事件载荷用；None = 未跑
    fixloop: dict[str, Any] | None = None
    #: L2 回灌报告（归因 hits/重译/回落名单）——同上进 error_json/done 载荷
    l2: dict[str, Any] | None = None
    #: share 导入对账统计（matched/dropped/missed/extra）——done stats 与
    #: partial error_json 的审计载荷；None = 非 share 任务
    share: dict[str, Any] | None = None
    #: #74 post-resolve dedup 命中行（钉版键二次 ``find_reusable``）——
    #: ``_stage_fetch`` 物化其产物后任务直接终态，parse/translate 不跑
    reuse_hit: dict[str, Any] | None = None

    @property
    def src_dir(self) -> Path:
        """原始源树（fetching 产物，只读）。"""
        return self.root / "src"

    @property
    def base_dir(self) -> Path:
        """Normalize 后树（parsing/translating 输入）。"""
        return self.root / "base"

    @property
    def zh_dir(self) -> Path:
        """译文工程树（splice + ctex 注入产物）。"""
        return self.root / "zh"

    def options(self) -> dict[str, Any]:
        """任务 options_json 反序列化。"""
        try:
            data = json.loads(self.row.get("options_json") or "{}")
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}


def chunk_db_id(src_file: str, byte_start: int, byte_end: int) -> str:
    """``sha256(src_file+byte_start+byte_end)[:24]``（§3.2 chunks.chunk_id）。"""
    h = hashlib.sha256(f"{src_file}:{byte_start}:{byte_end}".encode())
    return h.hexdigest()[:24]


def cache_key_for(
    *,
    arxiv_id: str,
    version: int | None,
    model: str,
    target_lang: str,
    api_key: str = "",
) -> str:
    """产物级 dedup 键：``sha256(arxiv_id@ver|model|pipeline_ver|lang)``。

    故意不含租户身份（§4.3：公开论文的确定性函数可跨租户 reuse——
    hjfy 对等共享缓存是既定产品特性）；``cache_scope()=="per_key"``
    时把 ``sha256(api_key)[:16]`` 拼进材料按凭证分桶，消除跨租户
    缓存存在性 oracle（匿名桶 key="" 共享一桶，与 tenant_for 同语义）。
    """
    ver = f"v{version}" if version else ""
    material = f"{arxiv_id}@{ver}|{model}|{PIPELINE_VERSION}|{target_lang}"
    if cache_scope() == "per_key":
        material += f"|k:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
    return hashlib.sha256(material.encode()).hexdigest()


# ---------------------------------------------------------------- 段缓存桥


class SegmentCache:
    """``translation_cache`` 表的 dict 门面（XlatPipeline ``cache`` 参数契约）。

    键 = ``{cfg_hash}:{seg_key}``——``cfg_hash`` 由
    ``sha256(model|prompt_ver|target_lang|glossary)[:16]`` 派生，管线内部
    ``_seg_key`` 再叠 src_text+kind+masked 快照。读穿透 SELECT，写进
    pending 缓冲由 ``drain`` 随 chunk flush 事务落盘。
    """

    def __init__(
        self,
        store: Store,
        *,
        prefix: str,
        model: str,
        target_lang: str,
    ) -> None:
        """Prefix = 配置指纹前缀（含 key 指纹若 cache_scope=per_key）。"""
        self._store = store
        self._prefix = prefix
        self._model = model
        self._lang = target_lang
        self._pending: dict[str, str] = {}
        self.hits = 0

    def _full(self, seg_key: str) -> str:
        return f"{self._prefix}:{seg_key}"

    def __contains__(self, seg_key: object) -> bool:
        """存在性探测（不 bump hit_count——命中计数只在 ``__getitem__``）。"""
        if not isinstance(seg_key, str):
            return False
        if seg_key in self._pending:
            return True
        row = self._store.conn.execute(
            "SELECT 1 FROM translation_cache WHERE key = ?",
            (self._full(seg_key),),
        ).fetchone()
        return row is not None

    def __getitem__(self, seg_key: str) -> str:
        """读穿透：pending 优先，然后表（命中记 hit_count）。"""
        if seg_key in self._pending:
            return self._pending[seg_key]
        hit = self._store.cache_get(self._full(seg_key))
        if hit is None:
            raise KeyError(seg_key)
        self.hits += 1
        return hit

    def __setitem__(self, seg_key: str, translation: str) -> None:
        """写进 pending 缓冲（drain 前对同 key 读可见）。"""
        self._pending[seg_key] = translation

    def __len__(self) -> int:
        """待写缓冲长度。"""
        return len(self._pending)

    def drain(self) -> list[tuple[str, str, str, str]]:
        """取走待写缓存项 → ``[(key, translation, model, lang)]``。"""
        out = [
            (self._full(k), v, self._model, self._lang)
            for k, v in self._pending.items()
        ]
        self._pending.clear()
        return out


# ---------------------------------------------------------------- 断点 state 桥

_DB_TO_PIPE = {"ok": "ok", "fallback_orig": "skipped", "failed": "fault"}
_PIPE_TO_DB = {
    "ok": "ok",
    "partial": "ok",
    "skipped": "fallback_orig",
    "fault": "failed",
}


def chunk_error_code(rec: ChunkResult | ChunkRecord) -> str | None:
    """Chunk error_code 唯一裁决点（T3）：SSE item 与 chunks 行共用一图。

    ``error_kind`` 归因先行（provider/auth 失败的块落库态是 skipped，
    不能被 validate 规则误标）；skipped → ``placeholder_mismatch``
    （占位符对账炸）/``validate``；fault 余者 → provider_error；
    ok/partial 无码。
    """
    if rec.error_kind in ("auth", "provider", "crash"):
        return {
            "auth": "provider_auth",
            "provider": "provider_error",
            "crash": "internal",
        }[rec.error_kind]
    if rec.skipped:
        if "placeholder" in rec.skip_reason:
            return "placeholder_mismatch"
        return "validate"
    if rec.status == "fault":
        return "validate" if rec.error_kind == "validate" else "provider_error"
    return None


def _new_usage_meter() -> tuple[dict[str, Any], Callable[[UsageRecord], None]]:
    """Usage 累加器 + ``ChatClient.usage_sink`` 回调（T4 真账记账）。

    主链/旁路臂（env_judge、L2、doc export）共用——旁路 client 不挂
    sink 时 token 消耗从 ``task_usage`` 蒸发。
    """
    usage: dict[str, Any] = {
        "calls": 0,
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "latency_s": 0.0,
        "model": "",
    }

    def _on_usage(u: UsageRecord) -> None:
        usage["calls"] += 1
        usage["prompt_tokens"] += u["prompt_tokens"]
        usage["completion_tokens"] += u["completion_tokens"]
        usage["latency_s"] += u["latency_s"]
        usage["model"] = u["model"]

    return usage, _on_usage


def _translator_clients(translator: object) -> list[ChatClient]:
    """取 translator 底层 ``ChatClient`` 列表（usage_sink/aclose 接线面）。

    ``_FallbackTranslator`` 主备两路；单路 translator 只有 ``.client``。
    """
    raw = getattr(translator, "clients", None)
    if raw is None:
        raw = [getattr(translator, "client", None)]
    return [c for c in raw if isinstance(c, ChatClient)]


async def _aclose_clients(clients: list[ChatClient]) -> None:
    """逐一关 translator 底层 client（L2/env_judge 旁路自建 translator 的收尾）。"""
    for c in clients:
        await c.aclose()


class DBStateBridge:
    """``StateStore`` 鸭子型：chunks 表做断点续跑状态面。

    ``load`` → (completed, recs)——completed 只收 ``ok``（pipeline 语义：
    skipped/fault 续跑必须重试）；``record`` → 待写缓冲由 worker flush。
    """

    def __init__(self, store: Store, task_id: str) -> None:
        """绑定 store 与任务。"""
        self._store = store
        self._task_id = task_id
        self.buffer: list[ChunkRecord] = []

    def load(self) -> tuple[set[str], dict[str, ChunkRecord]]:
        """Chunks 行 → (completed, recs)（``_load_resumed`` 契约）。"""
        completed: set[str] = set()
        recs: dict[str, ChunkRecord] = {}
        for r in self._store.all_chunks(self._task_id):
            status = r["status"]
            if status not in _DB_TO_PIPE:
                continue
            rec = ChunkRecord(
                chunk_id=r["chunk_id"],
                source=r["src_text"],
                translation=r["translation"] or "",
                status=_DB_TO_PIPE[status],
                kind=r["kind"],
                skipped=(status == "fallback_orig"),
                attempts=int(r["attempts"]),
                warnings=(json.loads(r["warnings"]) if r.get("warnings") else []),
            )
            recs[rec.chunk_id] = rec
            if status == "ok":
                completed.add(rec.chunk_id)
        return completed, recs

    def record(self, rec: ChunkRecord, *, error: dict[str, Any] | None = None) -> None:
        """缓冲一条结果（worker 按批量事务 flush）。"""
        del error
        self.buffer.append(rec)

    def start(self, total_chunks: int) -> None:
        """开跑登记：只记总数（state.json 语义已由 tasks 表覆盖）。"""
        self._store.update_fields(self._task_id, total_chunks=total_chunks)

    def finish(self) -> None:
        """收尾（落盘在 worker flush——这里无操作）。"""


class _FallbackTranslator:
    """``options.retry_model`` 接线：primary 抛 retryable ``ChatError`` → 同参切备选模型补一发。

    阶梯（``translate_with_ladder``）属 xlat 属主不在此动——本包装把
    「chunk 重试换模型」落在 HTTP 失败层：模型级故障/限流时该块的每次
    调用自带一发备选兜底；non-retryable（401/402/404）换模型无意义，
    直接上抛。validation 反馈驱动的阶梯内重试仍走 primary。
    ``.client`` 暴露 primary 的 ChatClient——``_stage_translate`` finally
    的 ``isinstance(ChatClient)→aclose`` 探测依赖它。
    """

    def __init__(self, primary: GatewayTranslator, fallback: GatewayTranslator) -> None:
        self._primary = primary
        self._fallback = fallback
        self.client = getattr(primary, "client", None)

    @property
    def clients(self) -> list[object]:
        """主备两路底层 client（usage_sink/aclose 接线面）。"""
        return [self.client, getattr(self._fallback, "client", None)]

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """先发 primary；retryable 失败 → 备选模型补一发（仍失败则上抛）。"""
        try:
            return await self._primary.translate(
                system=system,
                user=user,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        except ChatError as e:
            if not e.retryable:
                raise
            log.warning(
                "retry_model: primary %s 失败（%s）→ 备选 %s",
                getattr(self._primary, "model", "?"),
                e,
                getattr(self._fallback, "model", "?"),
            )
        return await self._fallback.translate(
            system=system,
            user=user,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format=response_format,
        )


class _PerCallTranslator:
    """llm_hook 的 BYOK translator：每次 ``translate`` 新建 ``ChatClient`` 即弃。

    ``LlmFixer._drive`` 把每次调用扔进**新线程 + ``asyncio.run`` 新 loop**
    ——共享 ``ChatClient`` 的 httpx 池跨 loop 复用会炸
    （"attached to a different loop"，``llm_hook.py`` docstring 明示的坑），
    故网关面做成 per-call 工厂。``usage_sink`` 仍接同一 meter——
    旁路烧的 token 不从 ``task_usage`` 蒸发。
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        sink: Callable[[UsageRecord], None],
    ) -> None:
        self._base_url = base_url
        self._api_key = api_key
        self._model = model
        self._sink = sink

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        client = ChatClient(self._base_url, self._api_key, usage_sink=self._sink)
        try:
            return await GatewayTranslator(client, self._model).translate(
                system=system,
                user=user,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format=response_format,
            )
        finally:
            await client.aclose()


class _StageError(Exception):
    """阶段内携带错误码的异常（→ ``run()`` 统一落 fault）。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        """Code 取 §2.2 错误码枚举。"""
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class _RouteRejectError(Exception):
    """路由/主文件策略拒绝载体（F3：``run()`` 归 partial + ``reject_at``，非 fault）。"""


class _ShareRejectError(Exception):
    """共享包本地重验拒绝载体（→ ``run()`` 归 partial + ``reject_at=share_verify``）。"""


def _share_pool(raw: list[object]) -> dict[tuple[str, str], deque[str]]:
    """包内 dual chunks → ``(src_file, en)`` → zh 队列（重复段按序消费）。"""
    pool: dict[tuple[str, str], deque[str]] = defaultdict(deque)
    for c in raw:
        if not isinstance(c, dict):
            continue
        src_file, en, zh = c.get("src_file"), c.get("en"), c.get("zh")
        if isinstance(src_file, str) and isinstance(en, str):
            pool[(src_file, en)].append(zh if isinstance(zh, str) else "")
    return pool


def _share_row(
    r: dict[str, Any], pool: dict[tuple[str, str], deque[str]]
) -> tuple[str, dict[str, Any] | None]:
    """单 chunk 对账 → ``(outcome, update|None)``。

    outcome ∈ ``ok``/``dropped``/``missed``/``resumed_ok``/``resumed``——
    非 pending 行（resume 幂等）只归类不重判，``resumed_ok`` 计入 matched
    防上轮已落库命中在重跑时误判零命中。
    """
    if r["status"] != "pending":
        return ("resumed_ok" if r["status"] == "ok" else "resumed", None)
    q = pool.get((str(r["src_file"]), str(r["src_text"])))
    if not q:
        return "missed", {
            "status": "fallback_orig",
            "translation": str(r["src_text"]),
            "error_code": "share_miss",
        }
    zh = q.popleft()
    rep = validate_pair(str(r["src_text"]), zh)
    if rep.ok:
        return "ok", {"status": "ok", "translation": zh}
    return "dropped", {
        "status": "fallback_orig",
        "translation": str(r["src_text"]),
        "error_code": "validate",
        "warnings": json.dumps(
            [f"share_validate: {rep.feedback()}"], ensure_ascii=False
        ),
    }


# ---------------------------------------------------------------- 上传解包


def _zip_unique(rel: str, seen: dict[str, str]) -> str:
    """Casefold 冲突改名：``foo.eps`` → ``foo~c2.eps``（arxiv.unpack 同款语义）。"""
    stem, dot, ext = rel.rpartition(".")
    if not stem:
        stem, suffix = rel, ""
    else:
        suffix = dot + ext
    k = 2
    while f"{stem}~c{k}{suffix}".lower() in seen:
        k += 1
    return f"{stem}~c{k}{suffix}"


def unpack_zip(data: bytes, dest: Path) -> list[str]:
    """Zip 安全解包（upload_tex 路线；tar/gz 走 ``unpack_sniffed``）。

    拒绝：绝对路径/盘符/``..`` 逃逸/超过 4000 文件/单文件或总量超限。
    与 ``arxiv.unpack`` tar 侧同族：dup 成员告警覆盖（last-wins）、
    casefold 冲突改名 ``~cN``、成员名撞已建目录（或其路径段撞已落
    文件）告警跳过——不静默合并/不抛 IsADirectoryError。
    """
    warnings: list[str] = []
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        msg = f"corrupt zip: {e}"
        raise UnpackError(msg) from e
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        if len(infos) > _MAX_UNPACK_FILES:
            msg = f"too_many_files:{len(infos)}"
            raise UnpackError(msg)
        total = 0
        seen: dict[str, str] = {}
        dest.mkdir(parents=True, exist_ok=True)
        for info in infos:
            rel = PurePosixPath(info.filename)
            parts = [p for p in rel.parts if p not in ("", ".")]
            if _BAD_ZIP_NAME.match(info.filename) or any(p == ".." for p in parts):
                warnings.append(f"reject:{info.filename}")
                continue
            if info.file_size > MAX_FILE_BYTES:
                warnings.append(f"reject_size:{info.filename}")
                continue
            total += info.file_size
            if total > 300 * 1024 * 1024:  # 300MB 解压上限（§2.4）
                warnings.append("reject_totalcap")
                break
            rel_s = PurePosixPath(*parts).as_posix()
            low = rel_s.lower()
            if low in seen and seen[low] != rel_s:
                new_rel = _zip_unique(rel_s, seen)
                warnings.append(f"casefold_rename:{rel_s}->{new_rel}")
                rel_s, low = new_rel, new_rel.lower()
            elif low in seen:
                warnings.append(f"dup_member_overwrite:{rel_s}")
            seen[low] = rel_s
            t_parts = PurePosixPath(rel_s).parts
            target = dest.joinpath(*t_parts)
            # 冲突检测须遍历全部祖先前缀而非只查直接 parent：成员
            # ``a``（文件）+ ``a/b/c.txt`` 同包时 parent ``a/b`` 尚不
            # 存在会漏检，mkdir 撞 ``NotADirectoryError`` 毁整单
            clash = target.is_dir() or any(
                (p := dest.joinpath(*t_parts[:i])).is_file() or p.is_symlink()
                for i in range(1, len(t_parts))
            )
            if clash:
                warnings.append(f"reject_dir_clash:{rel_s}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))
    return warnings


def _zip_kind(data: bytes) -> str:
    """PK 容器细分：docx/epub/upload_tex（坏 zip 交解包处报错）。"""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            names = set(zf.namelist())
            if "word/document.xml" in names:
                return "docx"
            head = b""
            if "mimetype" in names:
                try:
                    head = zf.read("mimetype")[:64].strip()
                except KeyError:
                    head = b""
            if head == b"application/epub+zip" or any(
                n.endswith("content.opf") for n in names
            ):
                return "epub"
    except zipfile.BadZipFile:
        pass  # 坏 zip 交给 upload_tex 路在解包处报错
    return "upload_tex"


def sniff_upload(data: bytes, filename: str) -> str:
    """上传魔数路由（§2.4）→ ``upload_pdf|upload_tex|docx|epub|unknown``。

    判据顺序：``%PDF`` → zip(docx/epub 细分) → gzip/tar → 可解码文本兜底。
    """
    if data[:4] == b"%PDF":
        return "upload_pdf"
    if data[:4] == b"PK\x03\x04":
        return _zip_kind(data)
    try:
        s = sniff(data)
    except SniffError:
        return "unknown"
    if s.kind in (BlobKind.TAR, BlobKind.SINGLE):
        return "upload_tex"
    if filename.lower().endswith((".tex", ".ltx", ".latex", ".txt")):
        return "upload_tex"
    return "upload_tex" if _looks_text(data) else "unknown"


def pdf_pages(pdf: Path) -> int:
    """PDF 页数 best-effort（pypdf；缺库/坏文件返 0）。"""
    try:
        from pypdf import PdfReader  # noqa: PLC0415 -- 重依赖惰性加载

        return len(PdfReader(str(pdf)).pages)
    except Exception:  # noqa: BLE001 -- best-effort：坏文件/缺库都退 0
        return 0


#: ``embed_cjk_mappings`` 注入的 GB1→UCS2 CMap（Adobe 官方资源，BSD 许可
#: ——与 poppler ``cMap/Adobe-GB1/Adobe-GB1-UCS2`` 逐字节一致，随包分发）
_GB1_UCS2_CMAP = Path(__file__).resolve().parent / "cmaps" / "Adobe-GB1-UCS2"


def _font_needs_gb1_cmap(font: DictionaryObject) -> bool:
    """Type0 字体命中注入条件与否。

    无 ToUnicode ∧ Identity-H/V 编码 ∧ CIDSystemInfo 为 Adobe/GB1。
    Ordering 非 GB1 的 Identity-keyed 字体挂 GB1 cmap 反而写错映射——跳过。
    """
    if (
        font.get("/ToUnicode")
        or not font.get("/DescendantFonts")
        or font.get("/Encoding") not in ("/Identity-H", "/Identity-V")
    ):
        return False
    child = font["/DescendantFonts"][0].get_object()
    system = child.get("/CIDSystemInfo", {})
    return system.get("/Registry") == "Adobe" and system.get("/Ordering") == "GB1"


def _iter_pdf_fonts(writer: PdfWriter) -> Iterator[DictionaryObject]:
    """按页树 ``/Resources``（含 XObject 递归）走查字体对象，id 去重。"""
    seen: set[int] = set()
    pending = [page.get("/Resources") for page in writer.pages]
    while pending:
        res = pending.pop()
        if not res:
            continue
        res = res.get_object()
        # /Font 与 /XObject 的值本身可以是 IndirectObject——
        # dict.get 不解引用，IndirectObject.values() 即 AttributeError，
        # 上抛被 _embed_tounicode 吞成一行 log → ToUnicode 静默全丢
        fonts = res.get("/Font", {})
        fonts = fonts.get_object() if fonts else {}
        if isinstance(fonts, dict):
            for ref in fonts.values():
                font = ref.get_object()
                if id(font) not in seen:
                    seen.add(id(font))
                    yield font
        xobjs = res.get("/XObject", {})
        xobjs = xobjs.get_object() if xobjs else {}
        if isinstance(xobjs, dict):
            for ref in xobjs.values():
                obj = ref.get_object()
                if id(obj) not in seen:
                    seen.add(id(obj))
                    pending.append(obj.get("/Resources"))


def embed_cjk_mappings(pdf: Path) -> int:
    """给 ``Identity-H``/Adobe-GB1 无 ToUnicode 的 CID 字体注 ``Adobe-GB1-UCS2`` cmap（docs/08 §3.3）。

    xelatex/tectonic 出的 zh.pdf 里 ctex+fandol 是真 CID-keyed GB1 字体
    且不落 ToUnicode——poppler 靠嵌入字体自身 cmap 能抽，pypdf/极简
    阅读器直抽即乱码（复制/检索失效）。按页树 ``/Resources``（含
    XObject 递归）走查 Type0 字体，命中条件全齐（无 ToUnicode ∧
    Identity-H/V 编码 ∧ CIDSystemInfo 为 Adobe/GB1）才挂共享 cmap
    流——Ordering 非 GB1 的 Identity-keyed 字体注它反而写错映射，
    不碰。改写经临时文件原子替换。返回注入字体数。
    """
    from pypdf import PdfWriter  # noqa: PLC0415 -- 重依赖惰性加载
    from pypdf.generic import (  # noqa: PLC0415
        DecodedStreamObject,
        NameObject,
    )

    writer = PdfWriter(clone_from=pdf)
    count = 0
    cmap_ref = None

    try:
        for font in _iter_pdf_fonts(writer):
            if not _font_needs_gb1_cmap(font):
                continue
            if cmap_ref is None:
                stream = DecodedStreamObject()
                stream.set_data(_GB1_UCS2_CMAP.read_bytes())
                cmap_ref = writer._add_object(  # noqa: SLF001 -- pypdf 无公开 add-raw-stream API
                    stream.flate_encode()
                )
            font[NameObject("/ToUnicode")] = cmap_ref
            count += 1
        if count:
            tmp = pdf.with_suffix(".mapped.pdf")
            writer.write(tmp)
    finally:
        writer.close()
    if count:
        tmp.replace(pdf)
    return count


def _looks_text(data: bytes) -> bool:
    """粗糙文本判定：前 64KB 可 UTF-8 解码且无 NUL。"""
    if b"\x00" in data[:4096]:
        return False
    try:
        data[:65536].decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True


def _safe_name(name: str) -> str:
    """上传文件名 → 安全落盘名（剥目录、滤怪字符，空则 main.tex）。"""
    base = PurePosixPath(name.replace("\\", "/")).name
    base = re.sub(r"[^A-Za-z0-9_.+-]", "_", base)
    if not base or not base.lower().endswith((".tex", ".ltx", ".latex", ".txt")):
        base = (base or "main") + ".tex"
    return base


def _md_member(src_file: str, seen: set[str]) -> str:
    """``src_file`` → md.zip 成员名：剥 ``..``/盘符、``.tex`` 系后缀换 ``.md``、重名 ``~N``。"""
    parts = [
        p
        for p in PurePosixPath(src_file.replace("\\", "/")).parts
        if p not in ("", ".", "..") and not p.endswith(":")
    ]
    name = "/".join(parts) or "document"
    name = re.sub(r"\.(?:tex|ltx|latex|txt)$", "", name, flags=re.IGNORECASE)
    name = re.sub(r"[^A-Za-z0-9_./+-]", "_", name).strip("/") or "document"
    cand, n = name + ".md", 1
    while cand in seen:
        n += 1
        cand = f"{name}~{n}.md"
    seen.add(cand)
    return cand


def _translate_progress(done: int, total: int) -> int:
    """按 done/total 线性映射 translating 段进度（25→85）。"""
    lo, hi = PROGRESS["translating"]
    return min(hi, lo + int((hi - lo) * done / max(1, total)))


def _tgt_lang(target_lang: str) -> str:
    """``zh-CN/zh-TW/en`` → prompt 语言名。"""
    return {"zh-TW": "Traditional Chinese", "en": "English"}.get(target_lang, "Chinese")


# ---------------------------------------------------------------- Worker


class PipelineWorker:
    """单任务管线驱动。注入面：translator_factory / fetcher / engine_factory。

    ``translator_factory(ctx) -> Translator``——缺省按凭证有无分流
    GatewayTranslator / MockTranslator（``TEXLATE_TRANSLATOR`` env 可强制）。
    """

    def __init__(  # noqa: PLR0913 -- 依赖注入面集中声明
        self,
        store: Store,
        bus: EventBus,
        data_dir: Path,
        *,
        translator_factory: Callable[[TaskCtx], Translator] | None = None,
        fetcher: Fetcher | None = None,
        source_cache: SourceCache | None = None,
        engine_factory: Callable[[str], Engine] | None = None,
        babeldoc: str | None = None,
        compile_timeout: float = COMPILE_TIMEOUT,
        deps_index: TlpdbIndex | None = None,
    ) -> None:
        """data_dir = ``TEXLATE_DATA_DIR`` 根；任务工作区 ``tasks/{id}/``。"""
        self.store = store
        self.bus = bus
        self.data_dir = data_dir
        self._translator_factory = translator_factory
        self._fetcher = fetcher
        self._src_cache = source_cache
        self._engine_factory = engine_factory
        self._babeldoc = babeldoc
        #: probe 的 tlpdb 索引注入面：None = `target_probe` 内部惰性 ensure
        self._deps_index = deps_index
        self._compile_timeout = compile_timeout
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_tid = 0
        #: ``mock_translator`` 告警按 task 去重（translate/env_judge/L2/doc 多处
        #: 调 ``_make_translator``，同一任务只留一条痕）
        self._mock_warned: set[str] = set()

    # ------------------------------------------------------------ 事件辅助

    def _on_loop(self, fn: Callable[..., _T], *args: object, **kw: object) -> _T:
        """Worker 线程的 DB/事件写弹回 loop 线程执行（§3.2 单写者纪律）。

        ``asyncio.to_thread`` 段内的 ``store``/``bus`` 调用一律走这里；
        loop 只 ``await`` 线程结果、反向等待不构成环，无死锁。
        """
        if self._loop is None or threading.get_ident() == self._loop_tid:
            return fn(*args, **kw)
        fut: Future[_T] = Future()

        def _run() -> None:
            try:
                fut.set_result(fn(*args, **kw))
            except Exception as e:  # noqa: BLE001 -- 透传回 worker 线程
                fut.set_exception(e)

        self._loop.call_soon_threadsafe(_run)
        return fut.result()

    def _stage(self, ctx: TaskCtx, stage: str, message: str, progress: int) -> None:
        """状态迁移 + stage 事件（先写库再发，同序保证）。

        cancel 竞态守卫同 ``_fail``/``_reject``：行已入终态则跳过——
        否则 cancel 后的下一拍 ``_stage`` 会把 cancelled 覆写回
        ACTIVE，终态 done 事件之后又补 stage 事件。
        """
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return
        self.store.transition(
            ctx.task_id, stage, message=message, progress=progress, force=True
        )
        self.bus.publish(
            ctx.task_id,
            "stage",
            {
                "stage": stage,
                "progress": progress,
                "message": message,
                "at": time.time(),
            },
        )

    def _log(self, ctx: TaskCtx, line: str) -> None:
        self._on_loop(
            self.bus.publish,
            ctx.task_id,
            "log",
            {"line": scrub(line, ctx.secrets.api_key)},
        )

    def _warning(self, ctx: TaskCtx, code: str, message: str) -> None:
        self._on_loop(
            self.bus.publish,
            ctx.task_id,
            "warning",
            {"code": code, "message": scrub(message, ctx.secrets.api_key)},
        )

    def _current_status(self, ctx: TaskCtx) -> str:
        row = self.store.get(ctx.task_id)
        return str(row["status"]) if row else "fault"

    def _check_cancelled(self, ctx: TaskCtx) -> None:
        """段边界 cancel 检查：API 置 cancelled 后由本检查收敛 worker。"""
        if self._current_status(ctx) == "cancelled":
            raise asyncio.CancelledError

    def _fail(  # noqa: PLR0913 -- code/message/retryable/stage/detail 即错误面
        self,
        ctx: TaskCtx,
        code: str,
        message: str,
        *,
        retryable: bool,
        stage: str | None,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """致命错误：fault 迁移 + error 事件 + done 事件（终态一致性）。

        并发 cancel 竞态守卫：行已入终态则整条跳过（cancel 路径已发 done）。
        ``detail`` 附加字段进 error_json（fixloop 摘要等审计载荷）。
        """
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return
        clean = scrub(message, ctx.secrets.api_key)
        err = {"code": code, "message": clean, "retryable": retryable}
        if detail:
            err.update(detail)
        row = self.store.get(ctx.task_id)
        progress = int(row["progress"]) if row else 0
        if row and row["stage"]:
            # ctx.row 是入队快照——error 事件的 stage 以库内现值为准
            stage = str(row["stage"])
        self.store.transition(
            ctx.task_id, "fault", error=err, progress=progress, force=True
        )
        self.bus.publish(
            ctx.task_id, "error", {**err, "stage": stage, "chunk_seq": None}
        )
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": "fault",
                "artifacts": self._artifact_urls(ctx),
                "stats": self._stats(ctx),
            },
        )

    def _reject(  # code/message/reject_at/detail 即错误面
        self,
        ctx: TaskCtx,
        code: str,
        message: str,
        *,
        reject_at: str,
        detail: dict[str, Any] | None = None,
    ) -> None:
        """F3 策略拒绝：``partial`` 终态 + error_json 留 ``reject_at`` 审计字段。

        与 e2e ``status=partial + reject_at`` 同形——拒绝是降级交付不是
        故障（``inject_reject``/``route_reject`` 同输入必再拒，
        ``retryable=False``）。不发 ``error`` 事件：partial 既有通道只有
        ``transition(error=...)`` + ``done``，消费方读 ``snapshot.error``。
        cancel 竞态守卫同 ``_fail``。
        """
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return
        err = {
            "code": code,
            "message": scrub(message, ctx.secrets.api_key),
            "retryable": False,
            "reject_at": reject_at,
        }
        if detail:
            err.update(detail)
        row = self.store.get(ctx.task_id)
        self.store.transition(
            ctx.task_id,
            "partial",
            error=err,
            progress=int(row["progress"]) if row else 0,
            force=True,
            message="部分完成",
        )
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": "partial",
                "artifacts": self._artifact_urls(ctx),
                "stats": self._stats(ctx),
            },
        )

    def _artifact_urls(self, ctx: TaskCtx) -> dict[str, str]:
        """Files 行 → ``{db_kind: /api/files/{id}/{url_kind}}``。"""
        return {
            kind: f"/api/files/{ctx.task_id}/{KIND_URL.get(kind, kind)}"
            for kind in self.store.files(ctx.task_id)
        }

    def _stats(self, ctx: TaskCtx) -> dict[str, Any]:
        counts = self.store.chunk_counts(ctx.task_id)
        out: dict[str, Any] = {
            "tokens": ctx.tokens_est,
            "seconds": round(time.time() - float(ctx.row["created_at"]), 1),
            "chunks_failed": counts["failed"],
        }
        if ctx.fixloop:
            out["fixloop"] = ctx.fixloop.get("verdict")
        if ctx.l2:
            out["l2"] = {
                "enabled": ctx.l2.get("enabled"),
                "errors": ctx.l2.get("errors"),
                "retranslated": len(ctx.l2.get("retranslated") or []),
                "fallback": len(ctx.l2.get("fallback_src") or []),
            }
        if ctx.share:
            out["share"] = ctx.share
        return out

    def _register(self, ctx: TaskCtx, kind: str, rel: str) -> dict[str, Any]:
        """产物登记（bytes/sha256 实测，相对 ``tasks/{id}/``）。"""
        return self._on_loop(
            self.store.put_file, ctx.task_id, kind, rel, data_dir=ctx.root
        )

    # ------------------------------------------------------------ 主入口

    async def run(self, ctx: TaskCtx) -> None:  # noqa: C901, PLR0912 -- 异常阶梯平铺即 §2.2 错误码映射表
        """按 kind 跑全链；异常按错误码映射落 fault/cancelled。"""
        # resume：内存字段从行快照重建（main_tex/engine_resolved 持久化值）
        self._loop = asyncio.get_running_loop()
        self._loop_tid = threading.get_ident()
        ctx.main_rel = str(ctx.row.get("main_tex") or "")
        ctx.engine_name = str(ctx.options().get("engine_resolved") or "tectonic")
        try:
            self._check_cancelled(ctx)
            if ctx.row["kind"] == "upload_pdf":
                await self._run_pdf(ctx)
            elif ctx.row["kind"] in ("docx", "epub"):
                await self._run_doc(ctx)
            elif ctx.row["kind"] == "share":
                await self._run_share(ctx)
            else:
                await self._run_tex(ctx)
        except asyncio.CancelledError:
            # cancel 端点已置 cancelled；只在没有终态时补 interrupted
            if self._current_status(ctx) in ACTIVE_STATUSES:
                self.store.transition(
                    ctx.task_id,
                    "interrupted",
                    force=True,
                    message="worker cancelled",
                )
                # 终态必须配 done 事件——SSE reader/等待者靠它收尾
                self.bus.publish(
                    ctx.task_id,
                    "done",
                    {
                        "status": "interrupted",
                        "artifacts": self._artifact_urls(ctx),
                        "stats": self._stats(ctx),
                    },
                )
            raise
        except _StageError as e:
            self._fail(
                ctx,
                e.code,
                str(e),
                retryable=e.retryable,
                stage=ctx.row["stage"],
            )
        except AuthError as e:
            self._fail(
                ctx,
                "provider_auth",
                str(e),
                retryable=False,
                stage=ctx.row["stage"],
            )
        except RetryableHTTPError as e:
            code = (
                "provider_rate"
                if e.status == HTTPStatus.TOO_MANY_REQUESTS
                else "provider_timeout"
            )
            self._fail(ctx, code, str(e), retryable=True, stage=ctx.row["stage"])
        except ChatError as e:
            self._fail(
                ctx,
                "provider_error",
                str(e),
                retryable=e.retryable,
                stage=ctx.row["stage"],
            )
        except _RouteRejectError as e:
            self._reject(ctx, "route_reject", f"route reject: {e}", reject_at="route")
        except _ShareRejectError as e:
            self._reject(
                ctx,
                "share_verify",
                f"share verify: {e}",
                reject_at="share_verify",
            )
        except InjectRejectError as e:
            self._reject(
                ctx,
                "inject_reject",
                f"inject reject: {e.reason}",
                reject_at="inject",
            )
        except (UnpackError, ValueError, OSError) as e:
            self._fail(ctx, "parse", str(e), retryable=False, stage=ctx.row["stage"])
        except Exception as e:
            log.exception("task %s crashed", ctx.task_id)
            self._fail(
                ctx,
                "internal",
                f"{type(e).__name__}: {e}",
                retryable=True,
                stage=ctx.row["stage"],
            )

    # ------------------------------------------------------------ tex 管线

    async def _run_tex(self, ctx: TaskCtx) -> None:
        """arxiv/upload_tex 共链：fetch → parse → translate → compile。"""
        ctx.root.mkdir(parents=True, exist_ok=True)
        await self._stage_fetch(ctx)
        if ctx.reuse_hit is not None:
            return  # post-resolve dedup 命中——产物已物化 + 终态已写
        await self._stage_parse(ctx)
        await self._stage_translate(ctx)
        await self._stage_compile(ctx)

    async def _stage_fetch(self, ctx: TaskCtx) -> None:
        """fetching：源树就绪 + src.tar 登记（哨兵 .fetch-done 幂等）。"""
        if (ctx.src_dir / ".fetch-done").is_file():
            return
        self._stage(ctx, "fetching", "取源", PROGRESS["fetching"][0])
        if ctx.row["kind"] in ("arxiv", "share"):
            await asyncio.to_thread(self._fetch_arxiv, ctx)
        else:
            await asyncio.to_thread(self._fetch_upload, ctx)
        if ctx.reuse_hit is not None:
            # dedup 命中——不落哨兵：崩溃在终态写入前时 resume 重跑
            # fetch 重查 dedup，等幂
            if self._current_status(ctx) not in TERMINAL_STATUSES:
                await asyncio.to_thread(self._materialize_reuse, ctx, ctx.reuse_hit)
                self._finish_reuse(ctx, ctx.reuse_hit)
            return
        (ctx.src_dir / ".fetch-done").write_text("", encoding="utf-8")
        self._stage(ctx, "fetching", "取源完成", PROGRESS["fetching"][1])
        self._check_cancelled(ctx)

    def _fetch_arxiv(self, ctx: TaskCtx) -> None:
        """``acquire_source`` → extracted → ``src/``；raw blob → ``src.tar``。"""
        arxiv_id = str(ctx.row["arxiv_id"])
        cache = self._src_cache or SourceCache(self.data_dir / "src-cache")
        fetcher = self._fetcher or Fetcher(RateLimiter(cache.root / "ratelimit.json"))
        res = acquire_source(arxiv_id, fetcher=fetcher, cache=cache)
        if res.status not in (AcquireStatus.OK, AcquireStatus.HIT):
            code = (
                "no_latex_source"
                if res.status in (AcquireStatus.PDF_ONLY, AcquireStatus.UNKNOWN_FORMAT)
                else "arxiv_fetch"
            )
            raise _StageError(
                code,
                res.detail or res.status.value,
                retryable=res.status not in _FETCH_NO_RETRY,
            )
        assert res.entry is not None  # noqa: S101 -- ok/hit 必有 entry
        entry = res.entry
        fields: dict[str, Any] = {
            "arxiv_id": f"{entry.arxiv_id}v{entry.resolved_version}",
            "title": str(entry.meta.get("title") or ""),
        }
        # cache meta.json 无 categories——单独 Atom/OAI 拉一次喂
        # glossary category 层；best-effort，挂了只丢该层术语
        try:
            meta = fetch_metadata(arxiv_id, fetcher=fetcher)
        except Exception as e:  # noqa: BLE001 -- 元数据臂不拦主链
            self._log(ctx, f"arxiv meta: {type(e).__name__}: {e}")
            meta = None
        if meta is not None:
            cats = [
                c for c in dict.fromkeys([meta.primary_category, *meta.categories]) if c
            ]
            if cats:
                opts = ctx.options()
                opts["arxiv_categories"] = cats
                # ctx.row 是入队快照——同步内存面防 _build_base 写回丢键
                ctx.row["options_json"] = json.dumps(opts, ensure_ascii=False)
                fields["options_json"] = ctx.row["options_json"]
        self._on_loop(self.store.update_fields, ctx.task_id, **fields)
        if self._post_resolve_reuse(ctx, entry):
            return  # 钉版键命中已完成任务——产物物化由 _stage_fetch 接管
        if ctx.src_dir.exists():
            shutil.rmtree(ctx.src_dir)
        shutil.copytree(entry.extracted_dir, ctx.src_dir)
        raw = entry.raw_path
        if raw is not None and raw.is_file():
            shutil.copyfile(raw, ctx.root / "src.tar")
            self._register(ctx, "src_tar", "src.tar")
        for w in res.warnings:
            self._log(ctx, f"fetch warn: {w}")

    def _post_resolve_reuse(self, ctx: TaskCtx, entry: CacheEntry) -> bool:
        """#74：latest-alias 任务 fetch 定版后按钉版键二次 dedup + re-key。

        入队时 ``id``（无版本）与 ``id@vN`` 产不同 cache_key 材料——enqueue
        的 ``find_reusable`` 拿 alias 键查不到钉版完成的产物。定版后补查
        钉版键：命中 → ``ctx.reuse_hit`` 置位（``_stage_fetch`` 物化产物）；
        未命中且无同键 ACTIVE 任务 → 本行 re-key 成钉版形，让后来的
        ``id@vN`` 请求 enqueue 即命中（双向补齐 dedup 面）。

        跳过条件：非 arxiv 任务（share 必须走 ``_share_apply`` 对账链，
        不得吃 reuse 捷径）；``prefer=fresh``；无 cache_key（fresh 撞键
        降级行）；键形同（本就钉版）。re-key 撞 ACTIVE 唯一索引 → 放弃
        re-key 保留 alias 键（无妨——对方任务覆盖钉版方向）。
        """
        if ctx.row["kind"] != "arxiv":
            return False
        stored = str(ctx.row.get("cache_key") or "")
        if not stored or str(ctx.options().get("prefer") or "reuse") == "fresh":
            return False
        resolved_key = cache_key_for(
            arxiv_id=entry.arxiv_id,
            version=entry.resolved_version,
            model=str(ctx.row["model"]),
            target_lang=str(ctx.row["target_lang"]),
            api_key=ctx.secrets.api_key,
        )
        if resolved_key == stored:
            return False
        hit = self._on_loop(self.store.find_reusable, resolved_key)
        if hit is not None:
            ctx.reuse_hit = hit
            return True
        if self._on_loop(self.store.find_active_by_cache_key, resolved_key) is None:
            try:
                self._on_loop(
                    self.store.update_fields, ctx.task_id, cache_key=resolved_key
                )
            except sqlite3.IntegrityError:
                return False
            ctx.row["cache_key"] = resolved_key
        return False

    def _materialize_reuse(self, ctx: TaskCtx, hit: dict[str, Any]) -> None:
        """把命中任务的 files 产物物理拷进本任务目录并登记（worker 线程）。

        下载面按 ``tasks/{id}/{path}`` 解析——只建行不拷文件会让产物
        链接 404。盘上缺失的产物跳过（文件面以实拷为准）。
        """
        hit_root = self.data_dir / "tasks" / str(hit["id"])
        for kind, f in self._on_loop(self.store.files, str(hit["id"])).items():
            rel = Path(str(f["path"]))
            src = hit_root / rel
            dst = ctx.root / rel
            if (
                rel.is_absolute()
                or ".." in rel.parts
                or not dst.resolve().is_relative_to(ctx.root.resolve())
            ):
                self._log(ctx, f"reuse: 路径越界跳过 {rel}")
                continue
            if not src.is_file():
                self._log(ctx, f"reuse: 产物缺失跳过 {rel}")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            self._register(ctx, kind, rel.as_posix())

    def _finish_reuse(self, ctx: TaskCtx, hit: dict[str, Any]) -> None:
        """post-resolve dedup 收尾：终态镜像命中行 + done 事件（loop 线程）。

        cancel 竞态守卫同 ``_fail``——行已入终态则整条跳过（cancel 路径
        已发 done），不复活用户取消的任务。
        """
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return
        self._log(ctx, f"reuse: 命中任务 {hit['id']} 产物（post-resolve dedup）")
        status = "done" if hit["status"] == "done" else "partial"
        err: dict[str, Any] | None = None
        if status == "partial" and hit.get("error_json"):
            try:
                raw = json.loads(str(hit["error_json"]))
                err = raw if isinstance(raw, dict) else None
            except json.JSONDecodeError:
                err = None
        upd: dict[str, Any] = {"progress": 100}
        if hit.get("main_tex"):
            upd["main_tex"] = str(hit["main_tex"])
        if hit.get("title") and not ctx.row.get("title"):
            upd["title"] = str(hit["title"])
        self.store.update_fields(ctx.task_id, **upd)
        self.store.transition(
            ctx.task_id,
            status,
            progress=100,
            error=err,
            force=True,
            message="完成" if status == "done" else "部分完成",
        )
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": status,
                "artifacts": self._artifact_urls(ctx),
                "stats": self._stats(ctx),
            },
        )

    def _fetch_upload(self, ctx: TaskCtx) -> None:
        """upload_tex：解包 ``upload/`` blob → ``src/``；原文登记 src_tar。"""
        uploads = sorted((ctx.root / "upload").glob("*"))
        if not uploads:
            msg = "upload payload missing"
            raise _StageError(code="internal", message=msg)
        blob_path = uploads[0]
        data = blob_path.read_bytes()
        ctx.src_dir.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []
        try:
            s = sniff(data)
        except SniffError:
            s = None
        if s is not None and s.kind in (BlobKind.TAR, BlobKind.SINGLE):
            res = unpack_sniffed(s, ctx.src_dir, stem_hint=blob_path.name)
            warnings = res.warnings
        elif data[:4] == b"PK\x03\x04":
            warnings = unpack_zip(data, ctx.src_dir)
        elif _looks_text(data) or blob_path.suffix.lower() in (
            ".tex",
            ".ltx",
            ".latex",
            ".txt",
        ):
            (ctx.src_dir / _safe_name(blob_path.name)).write_bytes(data)
        else:
            msg = f"unrecognized upload format: {blob_path.name}"
            raise _StageError(code="unsupported_format", message=msg)
        for w in warnings:
            self._log(ctx, f"unpack: {w}")
        self._register(ctx, "src_tar", f"upload/{blob_path.name}")

    # ------------------------------------------------------------ parsing

    async def _stage_parse(self, ctx: TaskCtx) -> None:
        """parsing：normalize → 主文件定位 → 逐文件 parse → chunks 入库。"""
        if self.store.has_chunks(ctx.task_id):
            self._ensure_scans(ctx)
            return
        self._stage(ctx, "parsing", "解析工程", PROGRESS["parsing"][0])
        if not (ctx.base_dir / ".base-done").is_file():
            await asyncio.to_thread(self._build_base, ctx)
        self._check_cancelled(ctx)
        rows, scans = await asyncio.to_thread(self._parse_all, ctx)
        self.store.insert_chunks(ctx.task_id, rows)
        ctx.scans = scans
        self._stage(ctx, "parsing", "解析完成", PROGRESS["parsing"][1])

    def _build_base(self, ctx: TaskCtx) -> None:
        """``src → base``：route（reject → partial+``reject_at``，F3）→ normalize。"""
        if ctx.base_dir.exists():
            shutil.rmtree(ctx.base_dir)
        shutil.copytree(ctx.src_dir, ctx.base_dir)
        route = route_project(ctx.base_dir)
        for r in route.reasons:
            self._log(ctx, f"route: {r}")
        if route.reject:
            raise _RouteRejectError(route.reject)
        opt_engine = str(ctx.options().get("engine") or "auto")
        engines = route.engines if opt_engine == "auto" else [opt_engine]
        if not engines:
            raise _StageError(code="parse", message="no engine route")
        ctx.engine_name = engines[0]
        override = str(ctx.options().get("main") or "")
        if override:
            # retry body {main} 或 upload main 字段：显式主文件——
            # 必须 confine 在 base/ 内（绝对路径与 ``..`` 逃逸一律拒，
            # resolve 后判——symlink 逃逸同挡），main_tex/编译产物
            # 不许落任务目录外。
            base = ctx.base_dir.resolve()
            cand = (ctx.base_dir / override).resolve()
            if not cand.is_relative_to(base):
                msg = f"main override 越出工程目录: {override}"
                raise _StageError(code="parse", message=msg)
            if not cand.is_file():
                raise _StageError(
                    code="parse", message=f"main override 不存在: {override}"
                )
            ctx.main_rel = cand.relative_to(base).as_posix()
        else:
            main = find_main_tex(ctx.base_dir)
            if main is None:
                # e2e 同位：no main tex 归 route 档策略拒绝（F3）
                msg = "no main tex"
                raise _RouteRejectError(msg)
            ctx.main_rel = main.relative_to(ctx.base_dir).as_posix()
        stats = normalize_project(ctx.base_dir, ctx.engine_name, ctx.main_rel)
        self._log(ctx, f"normalize: {stats}")
        # 引擎路由与主文件持久化——resume 后编译段还要用同一台引擎；
        # route_engines 供 fixloop 跨引擎臂（tectonic 丢 flag → xelatex
        # 重编）判定——显式 engine 覆盖时只剩用户指定那台，跨臂自熄
        opts = ctx.options()
        opts["engine_resolved"] = ctx.engine_name
        opts["route_engines"] = list(engines)
        ctx.row["options_json"] = json.dumps(opts, ensure_ascii=False)
        self._on_loop(
            self.store.update_fields,
            ctx.task_id,
            main_tex=ctx.main_rel,
            options_json=ctx.row["options_json"],
        )
        (ctx.base_dir / ".base-done").write_text("", encoding="utf-8")

    def _parse_all(
        self, ctx: TaskCtx
    ) -> tuple[list[dict[str, Any]], dict[str, ScanResult]]:
        """逐文件半解析 → (chunk 行, scans)。单文件崩不拖全树。"""
        rows: list[dict[str, Any]] = []
        scans: dict[str, ScanResult] = {}
        seq = 0
        for f in sorted(ctx.base_dir.rglob("*.tex")):
            if f.name.startswith("."):
                continue
            rel = f.relative_to(ctx.base_dir).as_posix()
            try:
                res = parse_file(f, flatten=False)
            except Exception as e:  # noqa: BLE001 -- 单文件解析崩记名跳过
                self._log(ctx, f"parse skip {rel}: {e}")
                continue
            scans[rel] = res
            for c in res.chunks:
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                rows.append(
                    {
                        "seq": seq,
                        "chunk_id": cid,
                        "src_file": rel,
                        "byte_start": c.span.start,
                        "byte_end": c.span.end,
                        "kind": normalize_kind(c.context),
                        "src_text": c.content,
                    }
                )
                seq += 1
        return rows, scans

    def _ensure_scans(self, ctx: TaskCtx) -> None:
        """Resume 场景：chunks 已有但内存 scans 空 → 重解析 base/ 补建。"""
        if not ctx.scans:
            _rows, ctx.scans = self._parse_all(ctx)

    def _ph_frag_map(self, ctx: TaskCtx) -> dict[str, dict[str, str]]:
        """``chunk_db_id → ph_fragments``：scans × ph_map 全量映射。

        DB 行与 ``ScanResult.chunks`` 按 byte span 对账（``chunk_db_id``
        同式）；无占位符的块不进表——``ph_fragments=None`` 才不武装。
        """
        frag_of: dict[str, dict[str, str]] = {}
        for rel, res in ctx.scans.items():
            for c in res.chunks:
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                ci = chunk_to_in(c, chunk_id=cid, ph_map=res.ph_map)
                if ci.ph_fragments:
                    frag_of[cid] = ci.ph_fragments
        return frag_of

    # ------------------------------------------------------------ translating

    async def _stage_translate(self, ctx: TaskCtx) -> None:
        """translating：XlatPipeline 跑 chunks pending 集（批量 flush 落盘）。"""
        rows = self.store.all_chunks(ctx.task_id)
        if not rows:
            self._stage(ctx, "translating", "无可译块", PROGRESS["translating"][1])
            return
        self._ensure_scans(ctx)
        self._stage(ctx, "translating", "翻译中", PROGRESS["translating"][0])

        translator = self._make_translator(ctx)
        clients = _translator_clients(translator)
        cache = self._make_cache(ctx)
        state = DBStateBridge(self.store, ctx.task_id)
        seq_map = {r["chunk_id"]: int(r["seq"]) for r in rows}
        status_map = {r["chunk_id"]: str(r["status"]) for r in rows}
        sse_items: list[dict[str, Any]] = []
        last_flush = time.monotonic()
        # T4：每次成功 chat() 的真实 token/延迟记账（ChatClient 回调）
        usage = self._meter_usage(clients)

        def on_result(r: ChunkResult) -> None:
            item: dict[str, Any] = {
                "seq": seq_map.get(r.chunk_id, -1),
                "status": _PIPE_TO_DB.get(r.status, "failed"),
            }
            code = chunk_error_code(r)
            if code is not None:
                item["error_code"] = code
            sse_items.append(item)
            ctx.tokens_est += (len(r.source) + len(r.translation)) // 4

        pipe = XlatPipeline(
            translator,
            config=PipelineConfig(
                concurrency=int(ctx.options().get("concurrency") or 3),
                tgt_lang=_tgt_lang(str(ctx.row["target_lang"])),
            ),
            glossary=self._make_glossary(
                ctx,
                placeholders=collect_doc_placeholders(r["src_text"] for r in rows),
            ),
            state=state,  # type: ignore[arg-type] -- StateStore 鸭子型
            validator=lambda s, z: validate_pair(s, z).feedback(),
            cache=cache,  # type: ignore[arg-type] -- MutableMapping 鸭子型
            on_result=on_result,
        )
        # 主链 ChunkIn 必须带 ph_fragments——不给则 _repair_fn 恒 None，
        # recover_copied_tokens 抄回修复臂整条死代码（_l2_run_state 同款
        # chunk_to_in(ph_map=) 模式；DB chunk_id ↔ scans 按 byte span 对账）
        frag_of = self._ph_frag_map(ctx)
        inputs = [
            ChunkIn(
                chunk_id=r["chunk_id"],
                content=r["src_text"],
                kind=r["kind"],
                ph_fragments=frag_of.get(r["chunk_id"]),
            )
            for r in rows
        ]

        run_task: asyncio.Task[list[ChunkResult]] | None = None
        try:
            run_task = asyncio.create_task(pipe.run(inputs))
            while not run_task.done():
                await asyncio.sleep(0.05)
                self._check_cancelled(ctx)
                if (
                    len(state.buffer) >= _FLUSH_N
                    or time.monotonic() - last_flush >= _FLUSH_MS
                ):
                    await self._flush_translate(
                        ctx, state, cache, status_map, sse_items
                    )
                    last_flush = time.monotonic()
            await run_task  # 传播异常（AuthTrippedError → run() 归 provider_auth）
        finally:
            await self._teardown_translate(
                ctx=ctx,
                run_task=run_task,
                state=state,
                cache=cache,
                status_map=status_map,
                sse_items=sse_items,
                usage=usage,
                clients=clients,
            )
        self._stage(ctx, "translating", "翻译完成", PROGRESS["translating"][1])
        counts = self.store.chunk_counts(ctx.task_id)
        if counts["failed"]:
            self._warning(
                ctx,
                "chunks_failed",
                f"{counts['failed']} 块回退原文（fallback_orig/failed）",
            )
        self._check_cancelled(ctx)

    async def _teardown_translate(  # noqa: PLR0913 -- 收尾现场全员（run_task + flush 参数 + usage + clients）
        self,
        *,
        ctx: TaskCtx,
        run_task: asyncio.Task[list[ChunkResult]] | None,
        state: DBStateBridge,
        cache: SegmentCache,
        status_map: dict[str, str],
        sse_items: list[dict[str, Any]],
        usage: dict[str, Any],
        clients: list[ChatClient],
    ) -> None:
        """收尾 translating 段（正常/fault/cancel 全走）：撤 run_task → usage 落账 → 残余 buffer flush → client 关闭。"""
        if run_task is not None and not run_task.done():
            # cancel 竞态：poll 循环被 _check_cancelled 抛出时 pipe.run
            # 仍在跑——不撤它就是孤儿任务：剩余 item 全标 skipped、flush
            # 后继续写 buffer/sse_items/done_map，且 clients 在任务脚下
            # 被 aclose
            run_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await run_task
        if usage["calls"]:
            # 有真账用真账——tokens_est 由字符估算换成 prompt+completion
            ctx.tokens_est = usage["prompt_tokens"] + usage["completion_tokens"]
            # buffer 空时下面的 _flush_translate 早退，tasks.tokens 滞留估算值
            self.store.update_fields(ctx.task_id, tokens=ctx.tokens_est)
            self.store.record_usage(
                ctx.task_id,
                model=str(usage["model"]),
                calls=int(usage["calls"]),
                prompt_tokens=int(usage["prompt_tokens"]),
                completion_tokens=int(usage["completion_tokens"]),
                latency_s=float(usage["latency_s"]),
            )
        with contextlib.suppress(asyncio.CancelledError):
            # fault/cancel 也要把缓冲里的已完块落盘（原先异常路径丢 buffer）
            await self._flush_translate(ctx, state, cache, status_map, sse_items)
        for c in clients:
            await c.aclose()

    async def _flush_translate(
        self,
        ctx: TaskCtx,
        state: DBStateBridge,
        cache: SegmentCache,
        status_map: dict[str, str],
        sse_items: list[dict[str, Any]],
    ) -> None:
        """批量事务 flush（§3.4.2）：record 缓冲 → chunks 行 + 段缓存 + 计数器 + chunk 事件。"""
        if not state.buffer and not sse_items:
            return
        updates = []
        for rec in state.buffer:
            db_status = _PIPE_TO_DB.get(rec.status, "failed")
            status_map[rec.chunk_id] = db_status
            updates.append(
                (
                    rec.chunk_id,
                    {
                        "status": db_status,
                        "translation": rec.translation,
                        "error_code": chunk_error_code(rec),
                        "warnings": (
                            json.dumps(rec.warnings, ensure_ascii=False)
                            if rec.warnings
                            else None
                        ),
                        "attempts": rec.attempts,
                    },
                )
            )
        state.buffer = []
        n_done = sum(
            v in ("ok", "fallback_orig", "failed") for v in status_map.values()
        )
        n_failed = sum(v in ("fallback_orig", "failed") for v in status_map.values())
        counts = {
            "total": len(status_map),
            "done": n_done,
            "cached": cache.hits,
            "failed": n_failed,
            "tokens": ctx.tokens_est,
            "progress": _translate_progress(n_done, len(status_map)),
        }
        self.store.flush_chunk_batch(ctx.task_id, updates, cache.drain(), counts)
        items_now = list(sse_items)
        sse_items.clear()
        self.bus.publish(
            ctx.task_id,
            "chunk",
            {
                "done": counts["done"],
                "total": counts["total"],
                "cached": counts["cached"],
                "failed": counts["failed"],
                "items": items_now,
            },
        )

    # ------------------------------------------------------------ share 导入

    async def _run_share(self, ctx: TaskCtx) -> None:
        """kind=share：fetch → parse → 包内 dual.json 对账回灌 → compile。

        ``shared-cache.md §5`` 消费侧——与 ``_run_tex`` 唯一差异是
        translating 段换成 ``_stage_share_apply``：译文来自共享包而非
        LLM，但 fetch/parse/splice/inject/compile/judge/dual 全链本地
        重跑。包内 ``zh-src.zip``/``zh.pdf`` 是贡献者侧证据，不解、不进
        产物面——读者看到的每个字节都由本源 + 本地管线再生。
        """
        ctx.root.mkdir(parents=True, exist_ok=True)
        await self._stage_fetch(ctx)
        await self._stage_parse(ctx)
        await self._stage_share_apply(ctx)
        await self._stage_compile(ctx, share=True)

    async def _stage_share_apply(self, ctx: TaskCtx) -> None:
        """translating（共享臂）：包内 chunks 对账本地 chunks → 译文落库。"""
        self._stage(ctx, "translating", "共享译文对账", PROGRESS["translating"][0])
        ctx.share = await asyncio.to_thread(self._share_apply, ctx)
        s = ctx.share
        self._log(
            ctx,
            f"share apply: matched={s['matched']}/{s['total']}"
            f" dropped={s['dropped']} missed={s['missed']} extra={s['extra']}",
        )
        self._stage(ctx, "translating", "对账完成", PROGRESS["translating"][1])
        self._check_cancelled(ctx)

    def _share_apply(self, ctx: TaskCtx) -> dict[str, int]:
        """包内 ``dual.json.chunks`` → 本地 chunks 表译文（§5 第 3 步对账）。

        对账键 ``(src_file, en==src_text)``——本地行按 seq 序贪心消费
        同键包内条目（重复原文段按序各得一份）。命中译文先过
        ``validate_pair``（与 LLM 产出同款 L0 判据）：过 → ``ok``；
        不过 → ``fallback_orig`` + ``validate``。本地无包条目的块 →
        ``fallback_orig`` + ``share_miss``（v1 不回退自译——导入保持
        零 token）；包内多余条目只记 ``extra`` 忽略。零命中即包与本源
        不对应 → ``_ShareRejectError``（不写库）。``flush_chunk_batch``
        单事务落盘——崩溃只有「全没落」一态，resume 重跑即幂等。
        """
        dual_path = ctx.root / "share" / "dual.json"
        try:
            doc = json.loads(dual_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            msg = f"dual.json unreadable: {e}"
            raise _ShareRejectError(msg) from e
        raw = doc.get("chunks") if isinstance(doc, dict) else None
        if not isinstance(raw, list):
            msg = "dual.json missing chunks[]"
            raise _ShareRejectError(msg)
        pool = _share_pool(raw)
        updates: list[tuple[str, dict[str, Any]]] = []
        total = matched = dropped = missed = 0
        for r in self._on_loop(self.store.all_chunks, ctx.task_id):
            total += 1
            outcome, upd = _share_row(r, pool)
            if upd is not None:
                updates.append((r["chunk_id"], upd))
            if outcome in ("ok", "resumed_ok"):
                matched += 1
            elif outcome == "dropped":
                dropped += 1
            elif outcome == "missed":
                missed += 1
        if matched == 0:
            msg = (
                f"share chunks 对账零命中（包内 {len(raw)} 条 vs 本地 "
                f"{total} 块）——包与本源不对应"
            )
            raise _ShareRejectError(msg)
        self._flush_chunk_updates(ctx, updates, [])
        return {
            "total": total,
            "matched": matched,
            "dropped": dropped,
            "missed": missed,
            "extra": sum(len(q) for q in pool.values()),
        }

    # ------------------------------------------------------------ compiling

    async def _stage_compile(self, ctx: TaskCtx, *, share: bool = False) -> None:
        """compiling：en/zh 双侧编译 + zh-src.zip + dual.json + 终态。

        ``share=True``（share 导入链）：重编未出 pdf 不归 fault——共享包
        验证失败是策略拒绝（partial + ``reject_at=share_verify``），
        与 route/inject reject 同形。
        """
        self._stage(ctx, "compiling", "编译", PROGRESS["compiling"][0])
        self._ensure_scans(ctx)
        await asyncio.to_thread(self._build_zh, ctx)
        self._check_cancelled(ctx)
        self.store.update_fields(ctx.task_id, progress=PROGRESS["compiling"][0] + 4)
        await asyncio.to_thread(self._compile_en, ctx)
        ok = await asyncio.to_thread(self._compile_zh, ctx)
        self._check_cancelled(ctx)
        self.store.update_fields(ctx.task_id, progress=PROGRESS["compiling"][1])
        # pypdf 页树走查 + named-dest 对齐是 CPU 重活——出 loop 线程，
        # 否则大 PDF 期间 SSE/心跳/分发全停
        await asyncio.to_thread(self._build_dual, ctx)
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return  # cancel 竞态：终态已写，不再覆盖
        # fixloop 策略拒绝（verdict reject:<rid>）与 e2e 同案归
        # partial + reject_at=fixloop——拒绝是降级交付不是故障
        verdict = str((ctx.fixloop or {}).get("verdict") or "")
        if verdict.startswith("reject:"):
            self._build_md_zip(ctx)
            detail: dict[str, Any] = {}
            if ctx.l2:
                detail["l2"] = ctx.l2
            if ctx.fixloop:
                detail["fixloop"] = ctx.fixloop
            self._reject(
                ctx,
                "fixloop_reject",
                f"fixloop policy reject: {verdict}",
                reject_at="fixloop",
                detail=detail or None,
            )
            await self._maybe_share_pack(ctx)
            return
        failed = self.store.chunk_counts(ctx.task_id)["failed"]
        if ok and failed == 0:
            status, err = "done", None
        elif ok or self._has_pdf(ctx, "zh_pdf"):
            status = "partial"
            err = {
                "code": "compile",
                "message": "有 pdf 但判据未全绿或块级失败",
                "retryable": True,
            }
            if ctx.share:
                err["share"] = ctx.share
            if ctx.l2:
                err["l2"] = ctx.l2
            if ctx.fixloop:
                err["fixloop"] = ctx.fixloop
        else:
            self._no_pdf_finish(ctx, share=share)
            await self._maybe_share_pack(ctx)
            return
        self.store.transition(
            ctx.task_id,
            status,
            progress=100,
            error=err,
            force=True,
            message="完成" if status == "done" else "部分完成",
        )
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": status,
                "artifacts": self._artifact_urls(ctx),
                "stats": self._stats(ctx),
            },
        )
        await self._maybe_share_pack(ctx)

    def _no_pdf_finish(self, ctx: TaskCtx, *, share: bool) -> None:
        """无 pdf 终态臂：md.zip 降级产物 → share 归策略拒绝 / tex 归 fault。

        fixloop 跑过仍无 pdf → 规则耗尽（``fixloop_exhausted``），摘要随
        error_json 落库供 triage。
        """
        self._build_md_zip(ctx)
        detail: dict[str, Any] = {}
        if ctx.l2:
            detail["l2"] = ctx.l2
        if ctx.fixloop:
            detail["fixloop"] = ctx.fixloop
        if share:
            self._reject(
                ctx,
                "share_verify",
                "share zh compile: no pdf",
                reject_at="share_verify",
                detail=detail or None,
            )
            return
        self._fail(
            ctx,
            "fixloop_exhausted" if ctx.fixloop else "compile",
            "zh compile: no pdf",
            retryable=True,
            stage="compiling",
            detail=detail or None,
        )

    def _has_pdf(self, ctx: TaskCtx, kind: str) -> bool:
        rec = self._on_loop(self.store.file_record, ctx.task_id, kind)
        return rec is not None and bool(rec.get("bytes"))

    def _build_zh(self, ctx: TaskCtx) -> None:
        """回写 zh 工程：按 chunks 表译文 splice + ctex 注入 + zip 登记。"""
        if (ctx.zh_dir / ".splice-done").is_file():
            return
        if ctx.zh_dir.exists():
            shutil.rmtree(ctx.zh_dir)
        shutil.copytree(ctx.base_dir, ctx.zh_dir)
        rows = self._on_loop(self.store.all_chunks, ctx.task_id)
        trans = {
            r["chunk_id"]: r["translation"]
            for r in rows
            if r["status"] == "ok" and r["translation"]
        }
        trans = self._env_judge_filter(ctx, trans, rows)
        n_files = 0
        for rel, res in ctx.scans.items():
            by_int: dict[int, str] = {}
            for c in res.chunks:
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                zh = trans.get(cid)
                if zh is not None:
                    by_int[c.id] = zh
            if not by_int:
                continue
            out = reconstruct(res, by_int)
            (ctx.zh_dir / rel).write_text(out, encoding="utf-8")
            n_files += 1
        self._log(ctx, f"splice: {n_files} files rewritten")
        try:
            info = prepare_chinese(ctx.zh_dir, ctx.main_rel)
        except InjectRejectError:
            # F3 降级交付：译文已 splice——zh-src.zip 先落盘，再由
            # run() 归 partial+reject_at=inject（不落 .splice-done，
            # resume 重打重拒同态收敛）
            self._zip_zh(ctx)
            raise
        self._log(ctx, f"inject: {info}")
        # zip 先于哨兵：崩在 zip 里时 resume 会因无哨兵重建 zh/ 重打，
        # 反序则哨兵在、产物登记永远缺席
        self._zip_zh(ctx)
        (ctx.zh_dir / ".splice-done").write_text("", encoding="utf-8")

    def _zip_zh(self, ctx: TaskCtx) -> None:
        """``zh/`` → zh-src.zip 登记（fixloop 回灌后重打复用同一函数）。"""
        zip_path = ctx.root / "zh-src.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(ctx.zh_dir.rglob("*")):
                if f.is_file() and f.name not in _SENTINELS:
                    zf.write(f, f.relative_to(ctx.zh_dir).as_posix())
        self._register(ctx, "zh_src_zip", "zh-src.zip")

    def _env_judge_enabled(self, ctx: TaskCtx) -> bool:
        """env_judge 开关：``options.env_judge`` 显式优先，缺省读 ``TEXLATE_ENV_JUDGE``（默认关）。

        share 任务恒关——零 token 结构承诺，options/env 无权打开。
        """
        if ctx.row["kind"] == "share":
            return False
        v = ctx.options().get("env_judge")
        if v is not None:
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() not in ("0", "false", "no", "off")
        return _env_flag(_ENV_ENV_JUDGE, default=False)

    def _env_judge_filter(
        self,
        ctx: TaskCtx,
        trans: dict[str, str],
        rows: list[dict[str, Any]],
    ) -> dict[str, str]:
        """静态表外 env 块问 LLM 可译性（e2e ``_env_judge_pass`` 同语义）。

        判 false 的块移出 splice 映射（回写时保留原文）并落库
        ``fallback_orig``/``env_judge``。
        """
        if not self._env_judge_enabled(ctx) or not trans:
            return trans
        targets: list[tuple[str, Chunk, str]] = []
        for rel, res in ctx.scans.items():
            for c in res.chunks:
                env_name = (c.env or "").strip()
                if not env_name or env_name in _KNOWN_ENVS:
                    continue
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                if cid in trans:
                    targets.append((cid, c, env_name))
        if not targets:
            return trans
        translator = self._make_translator(ctx)
        clients = _translator_clients(translator)
        usage = self._meter_usage(clients)
        pipe = XlatPipeline(
            translator,
            config=PipelineConfig(tgt_lang=_tgt_lang(str(ctx.row["target_lang"]))),
            glossary=self._make_glossary(ctx),
        )
        try:
            verdicts = asyncio.run(_env_judge_all(pipe, targets))
        finally:
            # judge 调用也烧 token——不入账就从 task_usage 里蒸发
            self._persist_usage(ctx, usage)
            if clients:
                asyncio.run(_aclose_clients(clients))
        reverted = sorted(cid for cid, keep in verdicts.items() if not keep)
        self._log(
            ctx,
            f"env_judge: {len(targets)} 块待判，{len(reverted)} 块回落原文",
        )
        if not reverted:
            return trans
        by_id = {r["chunk_id"]: r for r in rows}
        updates = [
            (
                cid,
                {
                    "status": "fallback_orig",
                    "translation": str(by_id[cid]["src_text"] or ""),
                    "error_code": "env_judge",
                },
            )
            for cid in reverted
            if cid in by_id
        ]
        self._flush_chunk_updates(ctx, updates, [])
        out = dict(trans)
        for cid in reverted:
            out.pop(cid, None)
        return out

    def _engine(self, ctx: TaskCtx) -> Engine:
        """按注入面/默认构造引擎（xelatex 走 best-effort nonstopmode）。"""
        eng = ctx.engine_name or "tectonic"
        if self._engine_factory is not None:
            return self._engine_factory(eng)
        kw: dict[str, Any] = {"halt_on_error": False} if eng == "xelatex" else {}
        return engine_for(eng, **kw)

    def _probe_target(self, ctx: TaskCtx, work: Path) -> ProbeReport | None:
        r"""``target_probe`` best-effort 壳：编译前声明依赖预扫 + 信号播报。

        产物全走 log 事件（最小侵入）：依赖解析计数聚合行 + ``tl_pkg``
        可装清单 + 逐条 ``rep.notes``（missing 清单/路由信号理由——
        ``rep.missing`` 即 fixloop ``missing_file`` 前置情报；装包仍是
        fixloop/tlmgr 职责，此处只播报）。``prefer_engine`` 与
        ``route_project`` 决策不一致时多记一行——只播报不重复决策。
        探针崩溃只记行返回 ``None``，绝不阻塞编译。
        """
        try:
            rep = target_probe(work, ctx.main_rel, deps_index=self._deps_index)
        except Exception as e:  # noqa: BLE001 -- 探针是旁路诊断，崩不拖编译
            self._log(ctx, f"probe crashed: {type(e).__name__}: {e}")
            return None
        parts = [
            f"deps={len(rep.deps)}",
            f"local={sum(d.resolved == 'local' for d in rep.deps)}",
            f"tl_pkg={sum(d.resolved == 'tl_pkg' for d in rep.deps)}",
            f"missing={len(rep.missing)}",
        ]
        if rep.prefer_engine:
            parts.append(f"prefer_engine={rep.prefer_engine}")
        if rep.flags:
            parts.append(f"flags={','.join(rep.flags)}")
        self._log(ctx, "probe: " + " ".join(parts))
        if rep.tl_packages:
            self._log(ctx, f"probe tl_pkg: {','.join(rep.tl_packages)}")
        for n in rep.notes:
            self._log(ctx, f"probe: {n}")
        if rep.prefer_engine and rep.prefer_engine != ctx.engine_name:
            self._log(
                ctx,
                f"probe: prefer_engine={rep.prefer_engine} 与 route 决策 "
                f"{ctx.engine_name} 不一致（仅记录不切换）",
            )
        return rep

    def _probe_diff(self, ctx: TaskCtx, rep: ProbeReport | None, res: CompRes) -> None:
        r"""编译后 ``deps_diff`` 对拍：期望输入集 vs ``res.deps`` 权威集。

        ``expected`` = 静态 ``\input`` 图（``rep.inputs``）+ local 命中声明
        的 detail；``unread`` = 期望却未被引擎读取，``undeclared`` = 权威集
        多出的隐式输入（kpsewhich 解析产物等）——一条聚合行，列表截断。
        ``rep.missing`` 逐条过 ``dep_seen`` 复核（真缺失 vs 路径/时序，
        fixloop ``install_file`` 前置判据）；``rep.flags`` 被引擎拒放的
        （``flags_dropped``）也记一行。全程 best-effort，崩溃只记行。
        """
        if rep is None:
            return
        try:
            expected = set(rep.inputs)
            expected.update(d.detail for d in rep.deps if d.resolved == "local")
            diff = deps_diff(expected, res.deps)
            if diff.authoritative:
                line = (
                    f"probe diff: seen={len(diff.seen)} "
                    f"unread={len(diff.unseen)} undeclared={len(diff.extra)}"
                )
                if diff.unseen:
                    line += " unread: " + ",".join(diff.unseen[:_PROBE_LIST_CAP])
                    if len(diff.unseen) > _PROBE_LIST_CAP:
                        line += f"+{len(diff.unseen) - _PROBE_LIST_CAP}"
                self._log(ctx, line)
                if rep.missing:
                    tags = ", ".join(
                        f"{f}={_PROBE_SEEN_TAG[dep_seen(res.deps, f)]}"
                        for f in rep.missing
                    )
                    self._log(ctx, f"probe missing 复核: {tags}")
            else:
                self._log(
                    ctx,
                    "probe diff: 引擎未产 .fls/.mk 依赖记录——差分不可判",
                )
            dropped = [f for f in rep.flags if f in res.flags_dropped]
            if dropped:
                self._log(
                    ctx,
                    f"probe: 引擎拒放 flags {','.join(dropped)}（flags_dropped）",
                )
        except Exception as e:  # noqa: BLE001 -- 差分诊断崩不拖编译
            self._log(ctx, f"probe diff crashed: {type(e).__name__}: {e}")

    def _compile_en(self, ctx: TaskCtx) -> None:
        """en.pdf：base/ 拷贝编译；失败只记 warning（不阻塞译文链）。"""
        if self._has_pdf(ctx, "en_pdf"):
            return
        work = ctx.root / "build-en"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ctx.base_dir, work)
        rep = self._probe_target(ctx, work)
        res = self._engine(ctx).compile(
            work,
            ctx.main_rel,
            timeout=self._compile_timeout,
            sandbox=True,
            flags=rep.flags if rep else None,
        )
        self._probe_diff(ctx, rep, res)
        if res.has_pdf and res.pdf is not None:
            shutil.copyfile(res.pdf, ctx.root / "en.pdf")
            self._register(ctx, "en_pdf", "en.pdf")
        else:
            self._warning(
                ctx,
                "en_compile",
                f"原文编译未出 pdf（{res.log.first_error or res.stdout_tail[:120]}）",
            )

    def _log_text_of(self, res: CompRes) -> str:
        """CompRes → log 全文（.log 优先、stdout_tail 兜底——tectonic 常无 .log）。"""
        if res.log_path and res.log_path.exists():
            try:
                return res.log_path.read_text(errors="replace")
            except OSError:
                pass
        return res.stdout_tail or ""

    def _fixloop_enabled(self, ctx: TaskCtx) -> bool:
        """Fixloop 开关：``options.fixloop`` false 系值或 ``TEXLATE_NO_FIXLOOP`` 真值 → 关（默认开）。"""
        if os.environ.get("TEXLATE_NO_FIXLOOP", "").strip().lower() in (
            "1",
            "true",
            "yes",
            "on",
        ):
            return False
        v = ctx.options().get("fixloop")
        if v is None or isinstance(v, bool):
            return v is not False
        return str(v).strip().lower() not in ("0", "false", "no", "off")

    def _run_fixloop(
        self, ctx: TaskCtx, work: Path, eng: Engine, first: CompRes
    ) -> CompRes:
        """Fixloop 救援循环（docs/08 §5）：规则引擎在 ``build-zh`` 内重编到出 pdf/放弃。

        摘要留 ``ctx.fixloop`` 并进 ``task_events``（``fixloop`` 事件可重放）+
        ``fixloop-cases.jsonl`` 沉淀（§5.5）。救回出 pdf 时把改动过的 TeX
        输入层文件回灌 ``zh/`` 并重打 zh-src.zip——让用户拿到的源码树真能
        编译。返回末次 ``CompRes``（fixloop 崩溃/未编译则原样回传）。
        """
        rec = _RecEngine(eng)
        hook, hook_usage, hook_clients = self._llm_hook_pack(ctx)
        try:
            cell = fixloop(
                work,
                rec,
                engine_name=ctx.engine_name,
                corpus_id=ctx.task_id,
                cond="zh",
                llm_hook=hook,
                case_sink=CaseSink(self.data_dir / "fixloop-cases.jsonl"),
            )
        except Exception as e:  # noqa: BLE001 -- fixloop 崩不拖垮编译段
            self._log(ctx, f"fixloop crashed: {type(e).__name__}: {e}")
            return first
        finally:
            self._teardown_llm_hook(ctx, hook_usage, hook_clients)
        summary = _fixloop_summary(cell)
        res = rec.last or first
        flags = [str(f) for f in cell.get("engine_flags") or []]
        dropped = [str(f) for f in cell.get("engine_flags_dropped") or []]
        summary["engine_flags"] = flags
        summary["engine_flags_dropped"] = dropped
        adopted_cross = False
        if dropped:
            summary["flags_unapplied"] = True
            # 跨引擎消费（e2e _run_fixloop :723 同臂）：dropped 多为
            # shell-escape 需求——tectonic 沙箱不收 → route 候选里的
            # xelatex 带全量 flag 重编取优。``route_engines`` 是
            # _build_base 持久化的生效候选列表——显式 engine= 覆盖时
            # 只剩用户指定那台，臂自熄（尊重显式选型）
            route_engines = [str(e) for e in ctx.options().get("route_engines") or []]
            v_last = judge(res, expect_cjk=True, log_text=self._log_text_of(res))
            if (
                ctx.engine_name == "tectonic"
                and "xelatex" in route_engines
                and _VERDICT_RANK.get(v_last.status, 0) < _VERDICT_RANK["clean"]
            ):
                xeng = (
                    self._engine_factory("xelatex")
                    if self._engine_factory is not None
                    else engine_for("xelatex")
                )
                xres = xeng.compile(
                    work,
                    ctx.main_rel,
                    timeout=self._compile_timeout,
                    sandbox=True,
                    flags=flags,
                )
                xv = judge(xres, expect_cjk=True, log_text=self._log_text_of(xres))
                summary["cross_engine"] = {
                    "engine": "xelatex",
                    "status": xv.status,
                    "reason": f"engine_flags {dropped} tectonic 不支持 → 换 xelatex",
                }
                if _VERDICT_RANK.get(xv.status, 0) > _VERDICT_RANK.get(
                    v_last.status, 0
                ):
                    res = xres
                    adopted_cross = True
            self._log(
                ctx,
                f"fixloop: engine_flags unsupported on {ctx.engine_name}: {dropped}",
            )
        elif flags:
            self._log(ctx, f"fixloop: engine_flags applied via CLI seam: {flags}")
        ctx.fixloop = _scrub_deep(summary, ctx.secrets.api_key)
        self._on_loop(self.bus.publish, ctx.task_id, "fixloop", ctx.fixloop)
        for ln in cell.get("log") or []:
            self._log(ctx, f"fixloop: {ln}")
        if cell.get("main") and cell["main"] != ctx.main_rel:
            self._log(ctx, f"fixloop: 主文件判定 {cell['main']} ≠ {ctx.main_rel}")
        if cell.get("final_pdf") or adopted_cross:
            n = _sync_fixed_sources(work, ctx.zh_dir)
            if n:
                self._log(ctx, f"fixloop: {n} 个修复文件回灌 zh/，重打 zh-src.zip")
                self._zip_zh(ctx)
        return res

    def _l2_enabled(self, ctx: TaskCtx) -> bool:
        """L2 回灌开关：``options.l2`` 显式优先，缺省读 ``TEXLATE_NO_L2``（默认开）。

        share 任务恒关——零 token 是结构承诺（``_share_apply`` 不回退自译
        同理），options/env 无权打开。
        """
        if ctx.row["kind"] == "share":
            return False
        v = ctx.options().get("l2")
        if v is not None:
            if isinstance(v, bool):
                return v
            return str(v).strip().lower() not in ("0", "false", "no", "off")
        return not _env_flag(_ENV_NO_L2, default=False)

    def _llm_hook_pack(
        self, ctx: TaskCtx
    ) -> tuple[LlmHook | None, dict[str, Any] | None, list[ChatClient]]:
        """Fixloop ``escalate_llm`` 的 server 侧接线：``(hook, usage, clients)``。

        与 e2e ``TEXLATE_FIXLOOP_LLM`` opt-in 不同——server 侧**默认开**
        （与 L2 parity）：任务带真 BYOK key 即建 hook，token 经
        ``usage_sink`` → ``_persist_usage`` 落账。None 条件（序即优先级）：

        - ``kind=="share"``：零 token 结构承诺，任何开关无权开；
        - ``options.llm_hook`` 显式 false / ``TEXLATE_FIXLOOP_LLM=0``；
        - 无 ``api_key``（含 ``TEXLATE_TRANSLATOR=mock``）：不给裸
          env-key client——那会绕开 BYOK 计费面。
        """
        if ctx.row["kind"] == "share":
            return None, None, []
        opt = ctx.options().get("llm_hook")
        if opt is not None and (
            opt is False or str(opt).strip().lower() in ("0", "false", "no", "off")
        ):
            return None, None, []
        if not _env_flag("TEXLATE_FIXLOOP_LLM", default=True):
            return None, None, []
        if self._translator_factory is not None:
            # 注入路径：factory 产 translator 直接给 hook（测试桩语义调用方担）
            tr = self._translator_factory(ctx)
            clients = _translator_clients(tr)
            return make_llm_hook(translator=tr), self._meter_usage(clients), clients
        force = os.environ.get("TEXLATE_TRANSLATOR", "").lower()
        if not ctx.secrets.api_key or force == "mock":
            if opt:
                self._log(ctx, "llm_hook: 无 BYOK api_key——跳过 escalate_llm")
            return None, None, []
        usage, sink = _new_usage_meter()
        model = ctx.secrets.model or "swe-2-medium"
        tr = _PerCallTranslator(ctx.secrets.base_url, ctx.secrets.api_key, model, sink)
        return make_llm_hook(translator=tr, model=model), usage, []

    def _teardown_llm_hook(
        self,
        ctx: TaskCtx,
        usage: dict[str, Any] | None,
        clients: list[ChatClient],
    ) -> None:
        """escalate_llm 旁路收尾：已发调用落账 + factory 路径 client 关闭。"""
        # escalate_llm 烧的是 BYOK token——崩溃/早退也把已发调用落账
        if usage is not None:
            self._persist_usage(ctx, usage)
        if clients:
            asyncio.run(_aclose_clients(clients))

    def _l2_run_state(
        self, ctx: TaskCtx, work: Path
    ) -> tuple[_TreeRun, dict[str, str]]:
        """``e2e._TreeRun`` 形态重建：scans 指向 work 内文件 + trans/chunk_ins。

        ``trans`` 取 chunks 表 status='ok' 译文（= work 内已 splice 内容）；
        ``db_of`` 是 ``"fidx:cid"`` → chunks.chunk_id 的 DB 回写映射。
        """
        ok = {
            r["chunk_id"]: r["translation"]
            for r in self._on_loop(self.store.all_chunks, ctx.task_id)
            if r["status"] == "ok" and r["translation"]
        }
        rels = sorted(ctx.scans)
        trans: dict[int, dict[int, str]] = {}
        chunk_ins: dict[str, ChunkIn] = {}
        db_of: dict[str, str] = {}
        for fidx, rel in enumerate(rels):
            res = ctx.scans[rel]
            for c in res.chunks:
                key = f"{fidx}:{c.id}"
                db_cid = chunk_db_id(rel, c.span.start, c.span.end)
                db_of[key] = db_cid
                chunk_ins[key] = chunk_to_in(c, chunk_id=key, ph_map=res.ph_map)
                zh = ok.get(db_cid)
                if zh is not None:
                    trans.setdefault(fidx, {})[c.id] = zh
        pipe = XlatPipeline(
            self._make_translator(ctx),
            config=PipelineConfig(tgt_lang=_tgt_lang(str(ctx.row["target_lang"]))),
            glossary=self._make_glossary(
                ctx,
                placeholders=collect_doc_placeholders(
                    ci.content for ci in chunk_ins.values()
                ),
            ),
            validator=lambda s, z: validate_pair(s, z).feedback(),
        )
        # 旁路 pipe 不经 run()——_doc_glossary 恒 {}，L2 重译 prompt 会
        # 丢术语块，须显式物化一次。不挂主链 SegmentCache：带
        # [compile_error] hint 语境的修复译文写同前缀缓存会污染主链段
        # 缓存命名空间（段缓存只认 source+masked 快照，不知 hint）
        pipe._materialize(list(chunk_ins.values()))  # noqa: SLF001 -- 旁路复用文档级物化
        run = _TreeRun(
            scans=[(work / rel, ctx.scans[rel]) for rel in rels],
            trans=trans,
            chunk_ins=chunk_ins,
            pipe=pipe,
        )
        return run, db_of

    def _l2_repair_zh(
        self, ctx: TaskCtx, work: Path, eng: Engine, res: CompRes
    ) -> tuple[dict[str, Any], CompRes, Verdict | None]:
        """L2 回灌一轮（镜像 e2e ``_l2_repair``）：归因→重译→resplice→重编→余孽回落。

        resplice 只重写 ``build-zh``——DB 回写 + ``_sync_fixed_sources``
        灌回 ``zh/`` + 重打 zh-src.zip 由本层补齐（worker 的成品树是
        ``zh/`` 而非 work）。返回 (l2 报告, 最新 CompRes, 新 Verdict 或
        None=未重编）。
        """
        rep: dict[str, Any] = {"enabled": True, "cap": L2_MAX_CHUNKS}
        run, db_of = self._l2_run_state(ctx, work)
        clients = _translator_clients(run.pipe.translator)
        usage = self._meter_usage(clients)
        try:
            hits, n_err = _l2_localize(work, run, res)
            rep["errors"] = n_err
            rep["hits"] = hits
            if not hits:
                rep["note"] = "no chunk-level attribution"
                return rep, res, None
            retr = asyncio.run(_retranslate_hits(run, hits, L2_MAX_CHUNKS))
            changed: set[str] = retr.pop("_changed")
            adopted: set[str] = retr.pop("_adopted")
            rep.update(retr)
            if not changed:
                rep["note"] = "no chunk changed"
                return rep, res, None
            rep["rewritten"] = _resplice(
                run, work, ctx.main_rel, {_split_cid(c)[0] for c in changed}
            )
            res2 = eng.compile(
                work, ctx.main_rel, timeout=self._compile_timeout, sandbox=True
            )
            v2 = judge(res2, expect_cjk=True, log_text=self._log_text_of(res2))
            rep["recompiled"] = v2.status
            if v2.status != "clean":
                hits2, _ = _l2_localize(work, run, res2)
                still_bad = sorted(set(hits2) & adopted)
                rep["fallback_src"] = still_bad
                rep["unresolved"] = sorted(set(hits2) - adopted)
                if still_bad:
                    for cid in still_bad:
                        fidx, ccid = _split_cid(cid)
                        run.trans.get(fidx, {}).pop(ccid, None)
                    rep["fallback_rewritten"] = _resplice(
                        run,
                        work,
                        ctx.main_rel,
                        {_split_cid(c)[0] for c in still_bad},
                    )
                    # 回落后未再编——下一级 fixloop 代验
                    rep["fallback_unverified"] = True
            self._l2_writeback(ctx, run, db_of, rep)
            n = _sync_fixed_sources(work, ctx.zh_dir)
            if n:
                self._log(ctx, f"l2: {n} 个重译文件回灌 zh/，重打 zh-src.zip")
                self._zip_zh(ctx)
            return rep, res2, v2
        finally:
            # L2 重译也烧 token——不入账就从 task_usage 里蒸发
            self._persist_usage(ctx, usage)
            if clients:
                asyncio.run(_aclose_clients(clients))

    def _l2_writeback(
        self,
        ctx: TaskCtx,
        run: _TreeRun,
        db_of: dict[str, str],
        rep: dict[str, Any],
    ) -> None:
        """L2 结果落 chunks 表：retranslated→新译文；reverted/fallback→fallback_orig。"""
        upd: dict[str, dict[str, Any]] = {}
        for cid in rep.get("retranslated") or []:
            fidx, ccid = _split_cid(cid)
            zh = (run.trans.get(fidx) or {}).get(ccid)
            if zh is not None and cid in db_of:
                upd[db_of[cid]] = {"translation": zh}
        for cid in (
            *(rep.get("reverted_l0") or []),
            *(rep.get("fallback_src") or []),
        ):
            if cid not in db_of:
                continue
            ci = run.chunk_ins.get(cid)
            upd[db_of[cid]] = {
                "status": "fallback_orig",
                "translation": ci.content if ci is not None else "",
                "error_code": "l2_reverted",
            }
        cache = run.pipe.cache
        cache_puts = cache.drain() if isinstance(cache, SegmentCache) else []
        if not upd and not cache_puts:
            return
        self._flush_chunk_updates(ctx, list(upd.items()), cache_puts)

    def _flush_chunk_updates(
        self,
        ctx: TaskCtx,
        updates: list[tuple[str, dict[str, Any]]],
        cache_puts: list[tuple[str, str, str, str]],
    ) -> None:
        """编译段块级回写事务（L2/env_judge 共用）：chunk 更新 + 段缓存 + 计数器。

        worker 线程调用——``_on_loop`` 压回 loop 线程后读改写一笔成交；
        计数器按 chunks 表最终态全量重算（不靠增量推演），progress 沿用行值。
        """

        def _flush() -> None:
            st = {
                r["chunk_id"]: str(r["status"])
                for r in self.store.all_chunks(ctx.task_id)
            }
            applied = [(cid, f) for cid, f in updates if cid in st]
            for cid, f in applied:
                st[cid] = str(f.get("status") or st[cid])
            row = self.store.get(ctx.task_id)
            counters = {
                "total": len(st),
                "done": sum(
                    s in ("ok", "fallback_orig", "failed") for s in st.values()
                ),
                "cached": int(row["cached_chunks"]) if row else 0,
                "failed": sum(s in ("fallback_orig", "failed") for s in st.values()),
                "tokens": ctx.tokens_est,
                "progress": int(row["progress"]) if row else 0,
            }
            self.store.flush_chunk_batch(ctx.task_id, applied, cache_puts, counters)

        self._on_loop(_flush)

    def _l2_attempt(
        self,
        ctx: TaskCtx,
        work: Path,
        eng: Engine,
        res: CompRes,
        v: Verdict,
    ) -> tuple[CompRes, Verdict]:
        """非 clean 判据后的 L2 臂：跑 ``_l2_repair_zh`` + 报告入账/事件/日志。"""
        if not self._l2_enabled(ctx):
            ctx.l2 = {
                "enabled": False,
                "reason": (
                    "share_zero_token"
                    if ctx.row["kind"] == "share"
                    else "options.l2"
                    if "l2" in ctx.options()
                    else _ENV_NO_L2
                ),
            }
            return res, v
        try:
            rep, res2, v2 = self._l2_repair_zh(ctx, work, eng, res)
        except Exception as e:  # noqa: BLE001 -- L2 崩不拖垮编译段
            self._log(ctx, f"l2 crashed: {type(e).__name__}: {e}")
            return res, v
        ctx.l2 = _scrub_deep(rep, ctx.secrets.api_key)
        self._on_loop(self.bus.publish, ctx.task_id, "l2", ctx.l2)
        for key in ("retranslated", "reverted_l0", "fallback_src", "unresolved"):
            if rep.get(key):
                self._log(ctx, f"l2 {key}: {rep[key]}")
        return res2, (v2 if v2 is not None else v)

    def _compile_zh(self, ctx: TaskCtx) -> bool:
        """zh.pdf：zh/ 拷贝编译 +（非 clean 时）L2 回灌 → fixloop + judge(expect_cjk)。

        修复链顺序对齐 e2e ``pipe_condition``：L2（译文归因重译）先于
        fixloop——L2 resplice 重写 workdir，规则修源在其后兜底。
        ``.compile-done`` 哨兵落 ``zh/`` 内：main 变更的 retry 会 rmtree
        ``zh/``，哨兵与 zh_pdf 记录同生共死；resume 见哨兵+pdf 即跳过重编。
        返回「终态不 fault」——有 pdf 即 partial 起步。
        """
        if (ctx.zh_dir / ".compile-done").is_file() and self._has_pdf(ctx, "zh_pdf"):
            return True
        work = ctx.root / "build-zh"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ctx.zh_dir, work)
        eng = self._engine(ctx)
        rep = self._probe_target(ctx, work)
        res = eng.compile(
            work,
            ctx.main_rel,
            timeout=self._compile_timeout,
            sandbox=True,
            flags=rep.flags if rep else None,
        )
        self._probe_diff(ctx, rep, res)
        v = judge(res, expect_cjk=True, log_text=self._log_text_of(res))
        if v.status != "clean":
            res, v = self._l2_attempt(ctx, work, eng, res, v)
        if v.status != "clean" and self._fixloop_enabled(ctx):
            res = self._run_fixloop(ctx, work, eng, res)
            v = judge(res, expect_cjk=True, log_text=self._log_text_of(res))
        if res.has_pdf and res.pdf is not None:
            shutil.copyfile(res.pdf, ctx.root / "zh.pdf")
            self._embed_tounicode(ctx, ctx.root / "zh.pdf")
            self._register(ctx, "zh_pdf", "zh.pdf")
            (ctx.zh_dir / ".compile-done").write_text("", encoding="utf-8")
        (ctx.root / "compile.log").write_text(
            scrub(self._log_text_of(res), ctx.secrets.api_key),
            encoding="utf-8",
        )
        self._register(ctx, "compile_log", "compile.log")
        for r in v.reasons:
            self._log(ctx, f"judge: {r}")
        for n in v.notes:
            self._log(ctx, f"judge note: {n}")
        self._log(ctx, f"verdict: {v.status} cat={v.category} errs={v.n_errors}")
        return v.status in ("clean", "partial") or res.has_pdf

    def _embed_tounicode(self, ctx: TaskCtx, pdf: Path) -> None:
        """``embed_cjk_mappings`` best-effort 壳：后处理崩不拖编译段。"""
        try:
            n = embed_cjk_mappings(pdf)
        except Exception as e:  # noqa: BLE001 -- 产物后处理失败不该 fault 任务
            self._log(ctx, f"tounicode embed failed: {type(e).__name__}: {e}")
            return
        if n:
            self._log(ctx, f"tounicode: {n} 个 GB1 CJK 字体补 ToUnicode cmap")

    def _build_dual(self, ctx: TaskCtx) -> None:
        """dual.json（§5.4）：documents 版本/pages + 页级 alignment + chunks。

        调用方 ``asyncio.to_thread`` 起（pdf_pages/build_alignment 扫
        content stream 是 CPU 重活）——store 读一律 ``_on_loop`` 回弹。
        """
        files = self._on_loop(self.store.files, ctx.task_id)
        doc: dict[str, Any] = {"version": 1, "documents": {}, "chunks": []}
        en = files.get("en_pdf")
        zh = files.get("zh_pdf")
        if en:
            doc["documents"]["original"] = {
                "version": en.get("sha256") or "",
                "pages": pdf_pages(ctx.root / en["path"]),
            }
        if zh:
            doc["documents"]["translated"] = {
                "version": zh.get("sha256") or "",
                "pages": pdf_pages(ctx.root / zh["path"]),
            }
        # named-dest 单调链锚点同步（texlate.align）；缺侧/无公共锚 → 同页映射
        doc["alignment"] = (
            build_alignment(ctx.root / en["path"], ctx.root / zh["path"])
            if en and zh
            else {"kind": "pages"}
        )
        doc["chunks"] = [
            {
                "seq": r["seq"],
                "src_file": r["src_file"],
                "en": r["src_text"],
                "zh": r["translation"] or "",
                "kind": r["kind"],
            }
            for r in self._on_loop(self.store.all_chunks, ctx.task_id)
        ]
        atomic_json(ctx.root / "dual.json", doc)
        self._register(ctx, "dual_json", "dual.json")

    def _build_md_zip(self, ctx: TaskCtx) -> None:
        """md.zip 降级产物（§5.4）：编译彻底失败但译文在库 → 双语 markdown 包。

        ``view:"html"`` 的登记物——HtmlPane 实读 dual.json ``chunks``，本包
        是同数据的可下载形态（按 ``src_file`` 章节化、seq 锚注释保留 1:1
        对账位）。零译文不产：登记了而 chunks 无料会让前端落 empty 态。
        只在 ``_stage_compile`` 无 pdf 终态分支调用，此处 dual.json 已落。
        """
        rows = self.store.all_chunks(ctx.task_id)
        if not rows or not any(r["translation"] for r in rows):
            return
        by_file: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            by_file.setdefault(str(r["src_file"]), []).append(r)
        seen: set[str] = set()
        with zipfile.ZipFile(ctx.root / "md.zip", "w", zipfile.ZIP_DEFLATED) as zf:
            for src_file in sorted(by_file):
                parts = [
                    f"<!-- chunk:{r['seq']} kind:{r['kind']} -->\n\n"
                    f"{r['src_text']}\n\n---\n\n{r['translation'] or ''}\n"
                    for r in sorted(by_file[src_file], key=lambda x: int(x["seq"]))
                ]
                zf.writestr(_md_member(src_file, seen), "\n".join(parts))
        self._register(ctx, "md_zip", "md.zip")
        self._log(ctx, f"md.zip: {sum(len(v) for v in by_file.values())} chunks")

    # ------------------------------------------------------------ share 打包钩

    def _share_pack_opt_in(self, ctx: TaskCtx) -> bool:
        """``options.share_pack`` 真值判定（bool 直读；字符串按 ``0/false/no/off`` 系判假）。"""
        v = ctx.options().get("share_pack")
        if v is None or isinstance(v, bool):
            return bool(v)
        return str(v).strip().lower() not in ("", "0", "false", "no", "off")

    def _share_glossary_hash(self, ctx: TaskCtx, cfg: Mapping[str, Any]) -> str:
        """``glossary_hash`` 组分：翻译时**生效**的自定义术语层内容复合指纹。

        口径对齐 ``_make_glossary``：配置的 ``glossary`` 路径经
        ``_glossary_path`` confine——拒/缺席即与翻译时同态回落
        ``USER_GLOSSARY_PATH``（``Glossary.load`` 的缺省 user 层）；
        local 层 ``base/glossary.local.yaml`` 恒进指纹。category/default
        内建层随 ``pipeline_ver`` 走不进指纹（cli ``_share_glossary_hash``
        同口径）。无自定义层 → ``""``。
        """
        gpath = str(cfg.get("glossary") or ctx.options().get("glossary") or "")
        gfile: Path | None = None
        if gpath:
            gfile = self._glossary_path(ctx, gpath, str(cfg.get("glossary_dir") or ""))
        if gfile is None and USER_GLOSSARY_PATH.is_file():
            gfile = USER_GLOSSARY_PATH
        files = [
            f
            for f in (gfile, ctx.base_dir / LOCAL_GLOSSARY_NAME)
            if f is not None and f.is_file()
        ]
        if not files:
            return ""
        h = hashlib.sha256()
        for f in files:
            h.update(hashlib.sha256(f.read_bytes()).digest())
        return h.hexdigest()

    async def _maybe_share_pack(self, ctx: TaskCtx) -> None:
        """opt-in 共享包完成钩（shared-cache.md §7/§8）：``_stage_compile`` 各终态分支末尾调用。

        产物面满足 ``REQUIRED_ARTIFACTS``（zh-src.zip+dual.json）即打包——
        zh.pdf 缺席落 partial 包（§9 已放行：fixloop_exhausted 型任务的
        L2/修复译文经包传播有实证价值）。``kind=="share"`` 是导入产物永不
        自包；reuse_hit 捷径在 ``_stage_fetch`` 提前 return 到不了本段——
        命中任务的生效术语表不可知，错标 ``glossary_hash`` 比不打包更糟。
        best-effort：任何失败只留 warning，绝不影响任务终态。
        """
        if ctx.row["kind"] == "share" or not self._share_pack_opt_in(ctx):
            return
        try:
            await asyncio.to_thread(self._share_pack_try, ctx)
        except Exception as e:  # noqa: BLE001 -- 共享打包是附加产物，炸不拖累任务终态
            self._warning(ctx, "share_pack", f"共享打包失败（任务不受影响）: {e}")

    def _share_pack_try(self, ctx: TaskCtx) -> None:
        """Worker 线程侧打包体：key_parts 派生 → ``pack_share`` → ``index_append``。

        包与 ``index.jsonl`` 同落 ``share_dir()``（``TEXLATE_SHARE_DIR`` >
        ``<data>/share``）——index 行 ``url`` 记包文件名（§7 文件级形态：
        目录整体挂静态托管后，行内相对名即取包路径）。``arxiv_id`` 取库内
        现值（fetch 后已钉版成 ``{id}v{N}``），``normalize_arxiv_id`` 拆回
        base+ver 进七组分；upload 类无 arxiv_id 不参与共享寻址，记行跳过。
        打包后 ``unpack_share`` 全量回验一次再落 index——写盘损坏的包不进
        索引（scratch 目录随验随清）。
        """
        row = self._on_loop(self.store.get, ctx.task_id)
        if row is None:
            return
        base, ver = normalize_arxiv_id(str(row.get("arxiv_id") or ""))
        if not base:
            self._log(ctx, "share pack: 任务无 arxiv_id（不参与共享寻址），跳过打包")
            return
        try:
            cfg = json.loads(str(row.get("config_json") or "{}"))
            if not isinstance(cfg, dict):
                cfg = {}
        except json.JSONDecodeError:
            cfg = {}
        manifest: dict[str, object] = {
            "arxiv_id": base,
            "version": f"v{ver}" if ver is not None else "",
            "model": str(row["model"]),
            "prompt_ver": PROMPT_VERSION,
            "target_lang": str(row["target_lang"]),
            "glossary_hash": self._share_glossary_hash(ctx, cfg),
            "pipeline_ver": PIPELINE_VERSION,
        }
        out_dir = share_dir(self.data_dir)
        bundle = pack_share(ctx.root, manifest, out_dir=out_dir)
        scratch = ctx.root / ".share-verify"
        try:
            mf = unpack_share(bundle, scratch)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        index_append(
            out_dir / "index.jsonl",
            mf,
            url=bundle.name,
            package_bytes=bundle.stat().st_size,
        )
        self._log(ctx, f"share pack: {bundle.name} → {out_dir}（index.jsonl 已落行）")

    # ------------------------------------------------------------ pdf 管线

    def _babeldoc_job(
        self, ctx: TaskCtx, src: Path, outdir: Path, workdir: Path
    ) -> BabeldocJob:
        """``TaskCtx`` → ``BabeldocJob``：BYOK 凭证 + config base_url 兜底 + options 透传。

        术语表复用主链 ``_make_glossary``（confine 规则同款），写成
        babeldoc ``--glossary-files`` CSV。
        """
        try:
            cfg = json.loads(str(ctx.row.get("config_json") or "{}"))
        except json.JSONDecodeError:
            cfg = {}
        options = ctx.options()
        glossary_csv = None
        glossary = self._make_glossary(ctx)
        if glossary is not None:
            glossary_csv = write_glossary_csv(
                workdir / "glossary.csv", list(glossary.as_dict().items())
            )
        return BabeldocJob(
            src=src,
            outdir=outdir,
            workdir=workdir,
            model=ctx.secrets.model or str(ctx.row["model"]),
            base_url=ctx.secrets.base_url or str(cfg.get("base_url") or ""),
            api_key=ctx.secrets.api_key,
            lang_out=lang_out_for(str(ctx.row["target_lang"])),
            qps=int(options.get("qps") or 4),
            pages=str(options.get("pages") or "") or None,
            dual=bool(options.get("dual", True)),
            alternating=bool(options.get("alternating", True)),
            send_temperature=bool(options.get("send_temperature", False)),
            custom_system_prompt=(
                str(options.get("custom_system_prompt") or "") or None
            ),
            glossary_csv=glossary_csv,
            timeout=default_timeout(),
        )

    async def _finish_pdf(self, ctx: TaskCtx, run: BabeldocRun) -> None:
        """Sidecar 结果 → 产物登记 + 终态迁移 + done 事件。"""
        ctx.tokens_est = int(run.stats.get("total_tokens") or 0)
        self.store.update_fields(ctx.task_id, tokens=ctx.tokens_est)
        if ctx.tokens_est:
            # babeldoc 不报调用次数——calls=0 只落 token 真账（与主链 T4 同表）
            self.store.record_usage(
                ctx.task_id,
                model=str(ctx.row["model"]),
                calls=0,
                prompt_tokens=int(run.stats.get("prompt_tokens") or 0),
                completion_tokens=int(run.stats.get("completion_tokens") or 0),
                latency_s=float(run.seconds),
            )
        mono = run.outputs.get("mono")
        dual = run.outputs.get("dual")
        if mono is not None:
            shutil.copyfile(mono, ctx.root / "zh.pdf")
            self._embed_tounicode(ctx, ctx.root / "zh.pdf")
            self._register(ctx, "zh_pdf", "zh.pdf")
        if dual is not None:
            shutil.copyfile(dual, ctx.root / "dual.pdf")
            self._embed_tounicode(ctx, ctx.root / "dual.pdf")
            self._register(ctx, "dual_pdf", "dual.pdf")
        self._log(ctx, f"babeldoc rc={run.rc} status={run.status} stats={run.stats}")
        if run.status == "failed":
            for ln in run.stderr_tail.strip().splitlines()[-3:]:
                self._log(ctx, f"babeldoc stderr: {ln}")
            self._fail(
                ctx,
                run.error_code or "compile",
                run.error or "babeldoc 失败",
                retryable=run.retryable,
                stage="compiling",
                detail={"babeldoc": _scrub_deep(run.stats, ctx.secrets.api_key)},
            )
            return
        await asyncio.to_thread(self._build_dual, ctx)
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return  # cancel 竞态：终态已写，不再覆盖
        status, err = "done", None
        if run.status == "degraded":
            status = "partial"
            err = {
                "code": "degraded",
                "message": scrub(run.error, ctx.secrets.api_key),
                "retryable": True,
            }
        self.store.transition(
            ctx.task_id,
            status,
            progress=100,
            error=err,
            force=True,
            message="完成" if status == "done" else "部分完成",
        )
        stats = self._stats(ctx)
        stats["babeldoc"] = _scrub_deep(run.stats, ctx.secrets.api_key)
        self.bus.publish(
            ctx.task_id,
            "done",
            {"status": status, "artifacts": self._artifact_urls(ctx), "stats": stats},
        )

    async def _run_pdf(self, ctx: TaskCtx) -> None:
        """upload_pdf：BabelDOC sidecar（AGPL 边界=独立进程，§2.4 + pdf-path §三）。

        产物面：en.pdf（原文回登记）+ mono→zh.pdf + dual→dual.pdf；
        ``run_babeldoc`` 的 status 判定（tracking/fallback/CJK 兜底）
        映射终态——ok→done、degraded→partial、failed→fault。
        """
        self._stage(ctx, "compiling", "BabelDOC 双语转换", 30)
        uploads = sorted((ctx.root / "upload").glob("*"))
        if not uploads:
            self._fail(
                ctx,
                "internal",
                "upload payload missing",
                retryable=False,
                stage="compiling",
            )
            return
        src = uploads[0]
        en = ctx.root / "en.pdf"
        if not en.exists():
            shutil.copyfile(src, en)
        self._register(ctx, "en_pdf", "en.pdf")
        binary = self._babeldoc or find_tool("babeldoc")
        if binary is None:
            self._fail(
                ctx,
                "internal",
                "babeldoc 未安装（pipx/uv tool install babeldoc）",
                retryable=False,
                stage="compiling",
            )
            return
        outdir = ctx.root / "babeldoc-out"
        workdir = ctx.root / "babeldoc-work"
        for d in (outdir, workdir):
            if d.exists():
                shutil.rmtree(d)  # retry 幂等：旧产物/旧 tracking 不混入本单
        job = self._babeldoc_job(ctx, src, outdir, workdir)
        last_stage = ""

        def on_progress(pct: float, stage: str) -> None:
            nonlocal last_stage
            self._on_loop(
                self.store.update_fields,
                ctx.task_id,
                progress=30 + min(65, round(65 * pct / 100)),
            )
            if stage and stage != last_stage:
                last_stage = stage
                self._log(ctx, f"babeldoc stage: {stage}")

        run = await run_babeldoc(
            job,
            binary=binary,
            on_progress=on_progress,
            on_log=lambda line: self._log(ctx, f"babeldoc: {line}"),
            should_cancel=lambda: self._current_status(ctx) == "cancelled",
        )
        self._check_cancelled(ctx)
        await self._finish_pdf(ctx, run)

    # ------------------------------------------------------------ doc 管线

    async def _run_doc(self, ctx: TaskCtx) -> None:
        """docx/epub：``export_document`` 双语插译（无编译链——产物即双语原文档）。

        ``export_document`` 内部 ``asyncio.run(XlatPipeline)``——必须
        ``to_thread`` 起独立 loop（本 loop 直调即 RuntimeError）；``on_result``
        在 thread 内触发，DB/事件写一律 ``_on_loop`` 回弹。``state_dir`` 落
        ``tasks/{id}/export-state/``——retry 由 StateStore 前缀校验自动续跑，
        成功即被 export 侧清理。产物 kind = ``zh_docx``/``zh_epub``。
        """
        from texlate.export import export_document  # noqa: PLC0415 -- 重依赖惰性加载
        from texlate.export.common import ExportError  # noqa: PLC0415

        uploads = sorted((ctx.root / "upload").glob("*"))
        if not uploads:
            self._fail(
                ctx,
                "internal",
                "upload payload missing",
                retryable=False,
                stage="translating",
            )
            return
        src = uploads[0]
        self._register(ctx, "src_tar", f"upload/{src.name}")
        self._stage(ctx, "translating", "文档插译", PROGRESS["translating"][0])
        translator = self._make_translator(ctx)
        clients = _translator_clients(translator)
        ext = src.suffix.lower()
        if ext not in (".docx", ".epub"):
            ext = f".{ctx.row['kind']}"
        dst = ctx.root / f"{src.stem}_bilingual{ext}"
        counters = {"done": 0, "failed": 0}
        # 真实 token/延迟记账（tex 路 _stage_translate 同款 sink）
        usage = self._meter_usage(clients)

        on_result = self._doc_on_result(ctx, counters)

        try:
            report = await asyncio.to_thread(
                export_document,
                src,
                dst,
                translator,
                target_lang=str(ctx.row["target_lang"]),
                state_dir=ctx.root / "export-state",
                glossary=self._make_glossary(ctx),
                on_result=on_result,
            )
        except ExportError as e:
            # DRM/fixed-layout/畸形包/不识格式——重试无意义的拒翻面
            self._fail(
                ctx,
                "unsupported_format",
                str(e),
                retryable=False,
                stage="translating",
            )
            return
        finally:
            self._persist_usage(ctx, usage)
            # clients 在 to_thread 的 ephemeral loop 里跑过——aclose 尽力而为
            try:
                await _aclose_clients(clients)
            except Exception:
                log.debug("doc client aclose failed", exc_info=True)
        self._check_cancelled(ctx)
        for w in report.warnings:
            self._warning(ctx, "export", w)
        self._register(ctx, f"zh_{ctx.row['kind']}", dst.name)
        n_bad = report.skipped + report.fault
        self.store.update_fields(
            ctx.task_id,
            total_chunks=report.units,
            done_chunks=report.translated + report.unchanged,
            failed_chunks=n_bad,
            tokens=ctx.tokens_est,
        )
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return  # cancel 竞态：终态已写，不再覆盖
        status = "done" if n_bad == 0 else "partial"
        err = None
        if status == "partial":
            err = {
                "code": "provider_error" if report.fault else "validate",
                "message": (
                    f"{n_bad} 段回退原文"
                    f"（skipped {report.skipped} / fault {report.fault}）"
                ),
                "retryable": bool(report.fault),
            }
        self.store.transition(
            ctx.task_id,
            status,
            progress=100,
            error=err,
            force=True,
            message="完成" if status == "done" else "部分完成",
        )
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": status,
                "artifacts": self._artifact_urls(ctx),
                "stats": self._stats(ctx),
            },
        )

    def _doc_on_result(
        self, ctx: TaskCtx, counters: dict[str, int]
    ) -> Callable[[ChunkResult], None]:
        """``on_result`` 工厂：逐 unit 计数 + tokens 估算 → ``_doc_emit`` 回弹。"""

        def on_result(r: ChunkResult) -> None:
            counters["done"] += 1
            if r.status in ("skipped", "fault"):
                counters["failed"] += 1
            ctx.tokens_est += (len(r.source) + len(r.translation)) // 4
            item: dict[str, Any] = {
                "seq": counters["done"],
                "status": _PIPE_TO_DB.get(r.status, "failed"),
            }
            code = chunk_error_code(r)
            if code is not None:
                item["error_code"] = code
            self._on_loop(
                self._doc_emit,
                ctx,
                counters["done"],
                counters["failed"],
                ctx.tokens_est,
                {
                    "done": counters["done"],
                    "total": 0,
                    "cached": 0,
                    "failed": counters["failed"],
                    "items": [item],
                },
            )

        return on_result

    def _doc_emit(
        self,
        ctx: TaskCtx,
        done: int,
        failed: int,
        tokens: int,
        payload: dict[str, Any],
    ) -> None:
        """Doc 路逐 unit 回弹段（``_on_loop`` 切回 loop 线程的单写者面）。

        units 枚举在 export 内部、total 事前不可知——progress 按 done 自增
        近似并钉在 ``hi-1`` 以下（终态 100 由 ``transition`` 写）。
        """
        lo, hi = PROGRESS["translating"]
        self.store.update_fields(
            ctx.task_id,
            done_chunks=done,
            failed_chunks=failed,
            tokens=tokens,
            progress=min(hi - 1, lo + done),
        )
        self.bus.publish(ctx.task_id, "chunk", payload)

    def _meter_usage(self, clients: list[ChatClient]) -> dict[str, Any]:
        """给一组 client 挂 usage_sink 并返回累加 dict（``_new_usage_meter`` 的装配糖）。"""
        usage, sink = _new_usage_meter()
        for c in clients:
            c.usage_sink = sink
        return usage

    def _persist_usage(self, ctx: TaskCtx, usage: dict[str, Any]) -> None:
        """旁路臂真实 usage 落账（``_teardown_translate`` 的旁路对应物）。

        旁路 meter 只数本臂调用——``tokens_est`` **累加**而非覆盖
        （覆盖会把主链真账抹成旁路小计）。ExportError/crash 早退也把
        已发调用的真账留下；``_on_loop`` 回弹使 worker 线程内的旁路臂
        （env_judge/L2/llm_hook）也可直调。
        """
        if not usage["calls"]:
            return
        ctx.tokens_est += usage["prompt_tokens"] + usage["completion_tokens"]
        self._on_loop(self.store.update_fields, ctx.task_id, tokens=ctx.tokens_est)
        self._on_loop(
            self.store.record_usage,
            ctx.task_id,
            model=str(usage["model"]),
            calls=int(usage["calls"]),
            prompt_tokens=int(usage["prompt_tokens"]),
            completion_tokens=int(usage["completion_tokens"]),
            latency_s=float(usage["latency_s"]),
        )

    # ------------------------------------------------------------ translator

    def _make_translator(self, ctx: TaskCtx) -> Translator:
        """默认工厂：key 或 ``TEXLATE_TRANSLATOR=gateway`` → 网关，否则 Mock。

        ``options.retry_model`` 仅在默认网关路径生效——备选模型与 primary
        同 client（同 endpoint+key），``translator_factory``/Mock 注入路径
        由调用方自担语义不包。
        """
        if self._translator_factory is not None:
            return self._translator_factory(ctx)
        force = os.environ.get("TEXLATE_TRANSLATOR", "").lower()
        if force == "mock":
            return MockTranslator()
        if force == "gateway" or ctx.secrets.api_key:
            client = ChatClient(ctx.secrets.base_url, ctx.secrets.api_key)
            primary = GatewayTranslator(client, ctx.secrets.model or "swe-2-medium")
            retry_model = str(ctx.options().get("retry_model") or "").strip()
            if retry_model and retry_model != primary.model:
                try:
                    retry_model = validate_model(retry_model)
                except ValueError:
                    self._warning(
                        ctx,
                        "retry_model",
                        f"options.retry_model {retry_model!r} 非法，忽略",
                    )
                else:
                    return _FallbackTranslator(
                        primary, GatewayTranslator(client, retry_model)
                    )
            return primary
        # 无 key 且未显式 mock/gateway——静默假译文是生产事故面，必须留痕
        if ctx.task_id not in self._mock_warned:
            self._mock_warned.add(ctx.task_id)
            self._warning(
                ctx,
                "mock_translator",
                "未配置 API key——回退 MockTranslator，产出为占位译文而非真实翻译",
            )
        return MockTranslator()

    def _glossary_path(
        self, ctx: TaskCtx, gpath: str, glossary_dir: str
    ) -> Path | None:
        """``glossary`` 选项 → confine 后的实际路径（None = 拒/无命中）。

        防任意文件读（审计 M2：glossary 内容进 LLM prompt 是外泄通道）：
        只收**相对路径**，逐个解析根——任务 ``base/`` 优先，然后
        ``glossary_dir``（settings 指定、运维侧受信目录，经 config_json
        透传）兜底；绝对路径与 ``..`` 形态即拒，resolve 后仍须
        is_relative_to 根（symlink 逃逸同挡）。
        """
        rel = Path(gpath)
        if rel.is_absolute() or ".." in rel.parts:
            self._warning(ctx, "glossary_rejected", f"glossary 路径越界被拒: {gpath!r}")
            return None
        roots = [ctx.base_dir.resolve()]
        if glossary_dir:
            roots.append(Path(glossary_dir).expanduser().resolve())
        for base in roots:
            cand = (base / rel).resolve()
            if cand.is_relative_to(base) and cand.is_file():
                return cand
        self._warning(
            ctx, "glossary_rejected", f"glossary 不在允许根内或不存在: {gpath!r}"
        )
        return None

    def _local_glossary(self, ctx: TaskCtx) -> Path | None:
        """论文级 ``glossary.local.yaml`` 探测：任务 ``base/`` 根下同名文件。

        三级表（user > local > category seed）的 local 层——随源树走的
        项目内覆盖（upload_tex 压缩包/arxiv e-print 自带即生效）；docx/
        epub/pdf 路无 ``base/`` 自然缺省。返回 None = 无该层。
        """
        cand = ctx.base_dir / LOCAL_GLOSSARY_NAME
        return cand if cand.is_file() else None

    def _arxiv_categories(self, ctx: TaskCtx) -> list[str]:
        """``options.arxiv_categories``（``_fetch_arxiv`` 持久化）→ category 层键。"""
        raw = ctx.options().get("arxiv_categories")
        if not isinstance(raw, list):
            return []
        return [c for c in raw if isinstance(c, str)]

    def _make_glossary(
        self, ctx: TaskCtx, *, placeholders: Iterable[str] = ()
    ) -> Glossary | None:
        """术语表：config.glossary 路径优先（confine 后），缺省内置默认层。

        五层序：user > local(``base/glossary.local.yaml``) > categories
        （arXiv 声明分类 → ``terms/*.csv`` 经 index.yaml）> default >
        placeholders（``[[X_n]]`` 恒等注入逼模型原样回抄）。
        """
        try:
            cfg = json.loads(str(ctx.row.get("config_json") or "{}"))
        except json.JSONDecodeError:
            cfg = {}
        gpath = str(cfg.get("glossary") or ctx.options().get("glossary") or "")
        local = self._local_glossary(ctx)
        cats = self._arxiv_categories(ctx)
        try:
            if not gpath:
                return Glossary.load(
                    local_path=local, categories=cats, placeholders=placeholders
                )
            path = self._glossary_path(ctx, gpath, str(cfg.get("glossary_dir") or ""))
            if path is None:
                return Glossary.load(
                    local_path=local, categories=cats, placeholders=placeholders
                )
            return Glossary.load(
                user_path=path,
                local_path=local,
                categories=cats,
                placeholders=placeholders,
            )
        except (OSError, ValueError) as e:
            self._log(ctx, f"glossary load failed: {e}")
            return None

    def _make_cache(self, ctx: TaskCtx) -> SegmentCache:
        """段缓存门面（cfg 指纹前缀含 model/prompt_ver/lang[/key 指纹]）。"""
        try:
            cfg_row = json.loads(str(ctx.row.get("config_json") or "{}"))
        except json.JSONDecodeError:
            cfg_row = {}
        glossary = str(cfg_row.get("glossary") or ctx.options().get("glossary") or "")
        local = self._local_glossary(ctx)
        local_sig = ""
        if local is not None:
            # local 层内容进指纹——同名文件换内容/有无该层都改变有效术语表
            local_sig = hashlib.sha256(local.read_bytes()).hexdigest()[:12]
        # categories 进指纹：不同分类 → category 层术语不同 → 同源句的
        # 翻译函数不同，跨论文共享必须按分类分桶。placeholders 是恒等
        # 注入且逐文档漂移——进指纹会把缓存锁死成单文档桶，不进。
        cats = ",".join(self._arxiv_categories(ctx))
        cfg = hashlib.sha256(
            f"{ctx.row['model']}|{PROMPT_VERSION}|{ctx.row['target_lang']}"
            f"|{glossary}|l:{local_sig}|c:{cats}".encode()
        ).hexdigest()[:16]
        if cache_scope() == "per_key":
            # 与 cache_key_for 同一 oracle 防护：段级 translation_cache
            # 表同样可被跨租户探测命中，按 key 指纹分桶。
            key_sha = hashlib.sha256(ctx.secrets.api_key.encode()).hexdigest()[:16]
            cfg = f"k{key_sha}:{cfg}"
        return SegmentCache(
            self.store,
            prefix=cfg,
            model=str(ctx.row["model"]),
            target_lang=str(ctx.row["target_lang"]),
        )


# ---------------------------------------------------------------- Runner


class TaskRunner:
    """``asyncio.Queue`` 单消费者 + secrets 注册表 + 心跳 + cancel 路由。

    所有 DB 交互都在 loop 线程。``secrets`` 只挂内存——重启后
    ``auth_source='header'`` 的任务因凭证丢失走 ``needs_auth``。
    """

    def __init__(
        self,
        store: Store,
        bus: EventBus,
        worker: PipelineWorker,
        *,
        worker_id: str | None = None,
    ) -> None:
        """worker_id 缺省 ``w-<rand>``（崩溃恢复认领标记）。"""
        self.store = store
        self.bus = bus
        self.worker = worker
        self.worker_id = worker_id or f"w-{secrets_mod.token_hex(6)}"
        self.secrets: dict[str, Secrets] = {}
        self._queue: asyncio.Queue[str] | None = None
        self._dispatcher: asyncio.Task[None] | None = None
        self._ticker: asyncio.Task[None] | None = None
        self._current: tuple[str, asyncio.Task[None]] | None = None

    # ------------------------------------------------------------ 生命周期

    def start(self) -> None:
        """起 dispatcher + 心跳 ticker（必须在 loop 线程调）。"""
        self._queue = asyncio.Queue()
        self._replay_queued()
        self._dispatcher = asyncio.create_task(
            self._dispatch_loop(), name="texlate-dispatch"
        )
        self._ticker = asyncio.create_task(
            self._heartbeat_loop(), name="texlate-heartbeat"
        )

    def _replay_queued(self) -> None:
        """把库内残留 ``queued`` 行灌回内存队列。

        内存队列重启即空、dispatcher 只消费内存队列——不补放则 queued
        行永远显示「排队中」成为僵尸。``auth_source='header'`` 的行已
        被 ``recover_startup`` 分流 needs_auth（header 凭证随进程死亡
        不可恢复），此处再防御性排除；其余按 settings/env 重决议
        secrets——决议不到 key 时与冷启动同语义走 MockTranslator 警告链。
        """
        rows = self.store.conn.execute(
            "SELECT id, model FROM tasks WHERE status = 'queued'"
            " AND auth_source != 'header' ORDER BY created_at, id"
        ).fetchall()
        if not rows:
            return
        auth = resolve_auth(SettingsStore(self.worker.data_dir).load())
        for r in rows:
            self.enqueue(
                str(r["id"]),
                Secrets(
                    api_key=auth.api_key,
                    base_url=auth.base_url,
                    model=str(r["model"]),
                    source=auth.source,
                ),
            )
        log.info("replayed %d queued task(s) after restart", len(rows))

    async def stop(self) -> None:
        """关停：cancel ticker/dispatcher/当前任务，等收尾。"""
        for t in (self._ticker, self._dispatcher):
            if t is not None:
                t.cancel()
        if self._current is not None:
            self._current[1].cancel()
        pending = [t for t in (self._ticker, self._dispatcher) if t]
        if self._current is not None:
            pending.append(self._current[1])
        for t in pending:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001,S112 -- 关停吞全部
                continue

    # ------------------------------------------------------------ 对外

    def enqueue(self, task_id: str, secrets: Secrets | None = None) -> None:
        """入队；``secrets`` 给了就登记（header BYOK 任务的唯一凭证通道）。"""
        if secrets is not None:
            self.secrets[task_id] = secrets
        if self._queue is not None:
            self._queue.put_nowait(task_id)

    def secrets_for(self, task_id: str) -> Secrets | None:
        """读内存凭证（无则 None——API 侧回落 settings/env 决议）。"""
        return self.secrets.get(task_id)

    def cancel_running(self, task_id: str) -> bool:
        """取消正在跑的任务；未在跑（还在队列）返回 False。"""
        if self._current is not None and self._current[0] == task_id:
            self._current[1].cancel()
            return True
        return False

    # ------------------------------------------------------------ 内部

    async def _dispatch_loop(self) -> None:
        """串行消费：dequeue → 状态复核 → 建 ctx → worker.run。"""
        assert self._queue is not None  # noqa: S101 -- start() 后必有
        while True:
            task_id = await self._queue.get()
            try:
                row = self.store.get(task_id)
                if row is None or row["status"] != "queued":
                    self.secrets.pop(task_id, None)
                    continue
                sec = self.secrets.get(task_id) or Secrets(model=str(row["model"]))
                ctx = TaskCtx(
                    store=self.store,
                    bus=self.bus,
                    task_id=task_id,
                    row=row,
                    secrets=sec,
                    root=self.worker.data_dir / "tasks" / task_id,
                )
                self.store.claim(task_id, self.worker_id)
                task = asyncio.create_task(
                    self.worker.run(ctx), name=f"texlate-task-{task_id}"
                )
                self._current = (task_id, task)
                try:
                    await task
                except asyncio.CancelledError:
                    # 子任务 cancel（cancel_running/stop 撤 _current）正常吞;
                    # dispatcher 自身被 cancel 必须重抛——否则循环回
                    # queue.get() 死等,stop() 的 await dispatcher 永久挂起
                    if asyncio.current_task().cancelling() > 0:
                        raise
                except Exception:
                    log.exception("worker escaped for %s", task_id)
                finally:
                    self._current = None
                    self.secrets.pop(task_id, None)
            finally:
                self._queue.task_done()

    async def _heartbeat_loop(self) -> None:
        """每 ``_HEARTBEAT_S`` 秒 bump 当前任务 updated_at。"""
        while True:
            await asyncio.sleep(_HEARTBEAT_S)
            if self._current is not None:
                try:
                    self.store.heartbeat(self._current[0])
                except (StoreError, OSError):
                    continue
