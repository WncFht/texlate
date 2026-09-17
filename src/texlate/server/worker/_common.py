"""``server.worker`` 包共享低层件——TaskCtx/常量/桥/译器包装（原 worker.py 顶层段）。"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from texlate import __version__
from texlate.arxiv.fetch import AcquireStatus
from texlate.server.settings import (
    cache_scope,
    scrub,
)
from texlate.textutil import env_float
from texlate.xlat.client import (
    ChatClient,
    ChatError,
    UsageRecord,
)
from texlate.xlat.pipeline import (
    ChunkResult,
    GatewayTranslator,
)
from texlate.xlat.prompts import PROMPT_VERSION
from texlate.xlat.state import ChunkRecord

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from texlate.arxiv.html import HtmlDoc
    from texlate.latex.model import (
        ScanResult,
    )
    from texlate.server.events import EventBus
    from texlate.server.store import Store


log = logging.getLogger(__name__)


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

_ENV_TIMEOUT_MAX_S = 86400.0  # env 超时值 24h 封顶——更大属配置错误


def _env_timeout(name: str, default: float) -> float:
    """``TEXLATE_*`` 秒数 env 读入——nan/inf/非正/超限一律回默认。"""
    v = env_float(name, default)
    return v if 0.0 < v <= _ENV_TIMEOUT_MAX_S else default


def opt_bool(options: dict[str, Any], key: str, env_on: Callable[[], bool]) -> bool:
    """options[key] 显式值 > env_on()——worker 开关统一 explicit 优先（e2e 同式）。

    options 值容忍 bool 与 ``"0"/"false"/"no"/"off"`` 字符串 false 系；
    env_on 是「开」语义的零参 callable（NO_ 系 env 由调用侧取反喂入）。
    """
    v = options.get(key)
    if v is not None:
        if isinstance(v, bool):
            return v
        return str(v).strip().lower() not in ("0", "false", "no", "off")
    return env_on()


#: 编译超时（docs/08 §4.1 默认值；server 路径无 --timeout flag）——
#: 全链优先级 ``TEXLATE_COMPILE_TIMEOUT`` env > settings.json
#: ``compile_timeout`` > 240s，``create_app`` 装配时解析透传；本常量
#: 兜非 app 构造方（测试/内嵌直 new PipelineWorker 不走 settings）
COMPILE_TIMEOUT = _env_timeout("TEXLATE_COMPILE_TIMEOUT", 240.0)

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
    "src_html": "src.html",
    "en_html": "en.html",
    "zh_html": "zh.html",
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

#: 任务树内哨兵文件（断点恢复用，不进 zh-src.zip / fixloop 回灌）
_SENTINELS = frozenset({".fetch-done", ".base-done", ".splice-done", ".compile-done"})

#: splice 失效即作废的派生产物 kind——zh/ 及其下游（译文快照/编译物/
#: 降级包）全随译文变更过期；en_pdf（base/ 编译）与 src_tar 不依赖
#: chunks，保留
_SPLICE_STALE_KINDS = ("zh_pdf", "zh_src_zip", "dual_json", "compile_log", "md_zip")

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
    if isinstance(value, (list, tuple)):
        return [_scrub_deep(v, api_key) for v in value]
    if isinstance(value, dict):
        return {
            _scrub_deep(k, api_key): _scrub_deep(v, api_key) for k, v in value.items()
        }
    return value


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
    #: judge 的 expect_cjk：0-chunk 主文档（includepdf 壳等）cjk_chars=0
    #: 是正确终态。``_stage_compile`` 在 loop 线程算好——store conn
    #: 有线程亲和，编译线程内不可查
    expect_cjk: bool = True
    #: 散文门分流出的 support 文件（.code.tex 机制件/无散文宏件转储）——
    #: 按原文保留不进翻译集，送译即腐蚀（同 e2e._scan_tree 三级分流）；
    #: _stats 审计面消费
    support_files: list[str] = field(default_factory=list)
    #: _parse_all 单文件解析崩的记名单（e2e ``fault_files`` 同位）——
    #: 此前只有 log 行无结构化面，_stats 落账
    fault_files: list[str] = field(default_factory=list)
    #: splice 译文里的残余占位符计数（e2e ``leftover_ph`` 同位）——
    #: _build_zh 逐文件累计
    leftover_ph: int = 0
    #: arxiv_html 链的 DOM 块模型（fetch/parse 建、emit 用 ph_map 回插）——
    #: tex 链恒 None；resume 路径由 ``_html_doc`` 从 src/index.html 重解析
    html_doc: HtmlDoc | None = None
    #: _probe_target 探出的引擎 flags（-shell-escape 类）——首编经
    #: ``rep.flags`` 直连；L2 重编/cross-engine 重试经此续传（e2e
    #: ``job.probe_flags`` 同式，缺了重试臂在另一套条件下编译）
    probe_flags: list[str] = field(default_factory=list)

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


def cache_key_for(  # noqa: PLR0913 -- 键材料五元组 + source 即 dedup 面
    *,
    arxiv_id: str,
    version: int | None,
    model: str,
    target_lang: str,
    api_key: str = "",
    source: str = "eprint",
) -> str:
    """产物级 dedup 键：``sha256(arxiv_id@ver|model|pipeline_ver|lang)``。

    故意不含租户身份（§4.3：公开论文的确定性函数可跨租户 reuse——
    hjfy 对等共享缓存是既定产品特性）；``cache_scope()=="per_key"``
    时把 ``sha256(api_key)[:16]`` 拼进材料按凭证分桶，消除跨租户
    缓存存在性 oracle（匿名桶 key="" 共享一桶，与 tenant_for 同语义）。

    ``source`` = 获取渠道：eprint 默认（材料不变，存量缓存续命）；
    ``html`` 等异源追加 ``|src:`` 成分——同 id@ver 的 eprint 与 html
    任务产物链不同构，channel-blind 会串桶互喂错产物。
    """
    ver = f"v{version}" if version else ""
    material = f"{arxiv_id}@{ver}|{model}|{PIPELINE_VERSION}|{target_lang}"
    if source != "eprint":
        material += f"|src:{source}"
    if cache_scope() == "per_key":
        material += f"|k:{hashlib.sha256(api_key.encode()).hexdigest()[:16]}"
    return hashlib.sha256(material.encode()).hexdigest()


# ---------------------------------------------------------------- 段缓存桥


class SegmentCache:
    """``translation_cache`` 表的 dict 门面（XlatPipeline ``cache`` 参数契约）。

    键 = ``{cfg_hash}:{seg_key}``——``cfg_hash`` 由
    ``sha256(model|prompt_ver|target_lang|base_url|glossary)[:16]`` 派生，管线内部
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
    """逐一关 translator 底层 client（L2/env_judge 旁路自建 translator 的收尾）。

    单个 aclose 抛错（连接已坏/半关状态）不挡其余、不上浮——收尾失败
    不该把任务终态改判 fault，更不该在 ``finally`` 里盖掉真异常。
    """
    for c in clients:
        try:
            await c.aclose()
        except Exception as e:  # noqa: BLE001 -- 收尾尽力而为
            log.debug("client aclose failed: %s: %s", type(e).__name__, e)


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
            # chunks 表可经直写腐化（attempts 非数值、warnings 坏 JSON/BLOB）
            # ——坏格按 0/[] 容错，不让单格把 resume 拖进永 fault
            try:
                attempts = int(r["attempts"])
            except (TypeError, ValueError):
                attempts = 0
            try:
                warnings = json.loads(r["warnings"]) if r.get("warnings") else []
            except (TypeError, ValueError):
                warnings = []
            rec = ChunkRecord(
                chunk_id=r["chunk_id"],
                source=r["src_text"],
                translation=r["translation"] or "",
                status=_DB_TO_PIPE[status],
                kind=r["kind"],
                skipped=(status == "fallback_orig"),
                attempts=attempts,
                warnings=warnings,
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


def _translate_progress(done: int, total: int) -> int:
    """按 done/total 线性映射 translating 段进度（25→85）。"""
    lo, hi = PROGRESS["translating"]
    return min(hi, lo + int((hi - lo) * done / max(1, total)))


def _tgt_lang(target_lang: str) -> str:
    """``zh-CN/zh-TW/en`` → prompt 语言名。"""
    return {"zh-TW": "Traditional Chinese", "en": "English"}.get(target_lang, "Chinese")
