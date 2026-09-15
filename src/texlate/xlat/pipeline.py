"""翻译编排骨架（docs/08 §1.3/§1.6）：asyncio.Queue + N worker + 首发单飞暖缓存。

流程：

    chunks[] → 滤 completed（state 续跑）→ 纯占位符直落盘
             → 超大原子块切分 → 短块贪心装箱（≤2000 字符/批）
             → 文档级术语表物化 + 各 kind system prompt 预建（逐字节恒定）
             → 首发单飞暖前缀缓存 → N worker 消费 queue
             → 每块经 retry 阶梯 → 占位符对账 → state 逐块落盘
             → 批解析失败/批调用可重试失败 → 成员逐个回炉单翻（复用并发额度）

`Translator` 是协议：真路径 = `GatewayTranslator`（ChatClient + prompts），
mock 路径 = `MockTranslator`（占位译文供 E2E/bench，不触网、确定性）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from . import placeholders, prompts
from .batch import (
    BATCH_MAX_CHARS,
    CHUNK_HARD_LIMIT,
    SHORT_CHAR_LIMIT,
    encode_batch,
    pack_batches,
    parse_batch_response,
    split_long_chunk,
)
from .client import ChatClient, ChatError, ChatOptions
from .retry import RetryPolicy, call_with_backoff, translate_with_ladder
from .state import ChunkRecord, StateStore, segment_key

if TYPE_CHECKING:
    from collections.abc import Callable

    from .glossary import Glossary

log = logging.getLogger(__name__)

#: 翻译温度（docs/08 §1.6：0.2~0.3 保守值；judge/抽取 0）
TRANSLATE_TEMPERATURE = 0.2
#: 翻译输出预算（reasoning 模型下限；短输出不亏——按量计费）
TRANSLATE_MAX_TOKENS = 8192
#: length 截断重试的放大预算
LENGTH_RETRY_MAX_TOKENS = 32768
#: 默认并发（provider 限额 10~50 可调）
DEFAULT_CONCURRENCY = 10


# ---------------------------------------------------------------- 输入/输出


@dataclass
class ChunkIn:
    """xlat 输入块（scanner Chunk 的轻量映射：`context` → `kind` 归一）。"""

    chunk_id: str
    content: str
    kind: str = "para"


@dataclass
class ChunkResult:
    """xlat 输出块。`status`: ok | skipped | fault | partial。"""

    chunk_id: str
    source: str
    translation: str
    kind: str
    status: str = "ok"
    batched: bool = False
    batch_id: str = ""
    skipped: bool = False
    skip_reason: str = ""
    attempts: int = 0
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- Translator 协议


class Translator(Protocol):
    """最小编排面：给定 system+user 出译文（`[[SL]]`/`[[PL]]` 解码在阶梯侧）。"""

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """返回译文原文。"""
        ...


class GatewayTranslator:
    """`ChatClient` 的 Translator 适配：HTTP 退避 + length 截断放大重试。"""

    def __init__(
        self,
        client: ChatClient,
        model: str,
        *,
        policy: RetryPolicy | None = None,
    ) -> None:
        """绑定 client+model；`policy` 覆盖默认 HTTP 退避参数。"""
        self.client = client
        self.model = model
        self.policy = policy or RetryPolicy()

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """一次翻译调用（内部已含 HTTP 退避；length → 32k 放大重试一次）。"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

        async def _go() -> str:
            try:
                r = await self.client.chat(
                    self.model,
                    messages,
                    options=ChatOptions(
                        temperature=temperature,
                        max_tokens=max_tokens,
                        response_format=response_format,
                    ),
                )
            except ChatError as e:
                retryable_length = (
                    e.retryable
                    and e.__class__.__name__ == "LengthTruncatedError"
                    and max_tokens < LENGTH_RETRY_MAX_TOKENS
                )
                if not retryable_length:
                    raise
                r = await self.client.chat(
                    self.model,
                    messages,
                    options=ChatOptions(
                        temperature=temperature,
                        max_tokens=LENGTH_RETRY_MAX_TOKENS,
                        response_format=response_format,
                    ),
                )
            return r.content

        return await call_with_backoff(_go, policy=self.policy)


#: mock 译文固定串（e2e mock_a 同款：散文段 → 固定中文，token 原位不动）
MOCK_ZH = "这是译文"
_MOCK_TOKEN_RX = re.compile(
    r"\[\[[A-Z_]+_\d+\]\]|\[\[[A-Z][A-Z_]*\]\]|\\[a-zA-Z@]+\*?|\\.|[][(){}|]"
)
#: 批行 `[n]` 前缀识别（mock 回显编号用）
_MOCK_NUM_RX = re.compile(r"^(\[\d+\])\s?(.*)$", re.DOTALL)


class MockTranslator:
    """占位译文：占位符/控制字/括号原位保留，非空散文段 → 固定中文串。

    供 E2E 与 bench 用——不触网、确定性、占位符契约天然成立。
    批输入（每行 `[n]` 开头）回显编号，保证批量解析路径被真实走到。
    """

    def __init__(self, zh: str = MOCK_ZH) -> None:
        """`zh` = 散文段替换成的固定中文串。"""
        self.zh = zh
        self.calls: list[dict[str, Any]] = []  # 测试可断言调用次数/内容

    async def translate(
        self,
        *,
        system: str,
        user: str,
        temperature: float,
        max_tokens: int,
        response_format: dict[str, str] | None = None,
    ) -> str:
        """返回 mock 译文。"""
        self.calls.append(
            {
                "system": system,
                "user": user,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
        )
        if response_format is not None and response_format.get("type") == "json_object":
            try:
                payload = json.loads(user)
                slots = payload.get("slots") or {}
                return json.dumps(dict.fromkeys(slots, self.zh), ensure_ascii=False)
            except (json.JSONDecodeError, AttributeError):
                return "{}"
        lines = user.split("\n")
        if lines and all(_MOCK_NUM_RX.match(ln) for ln in lines if ln.strip()):
            return "\n".join(
                f"{m.group(1)} {_mock_translate_text(m.group(2), self.zh)}"
                if (m := _MOCK_NUM_RX.match(ln))
                else _mock_translate_text(ln, self.zh)
                for ln in lines
            )
        return _mock_translate_text(user, self.zh)


def _mock_translate_text(text: str, zh: str) -> str:
    """e2e mock_a 同款：token 原位保留，散文段 → 固定中文串。"""
    out: list[str] = []
    pos = 0
    for m in _MOCK_TOKEN_RX.finditer(text):
        seg = text[pos : m.start()]
        out.append(zh if seg.strip() else seg)
        out.append(m.group(0))
        pos = m.end()
    tail = text[pos:]
    out.append(zh if tail.strip() else tail)
    return "".join(out)


# ---------------------------------------------------------------- Pipeline


@dataclass
class PipelineConfig:
    """编排参数（docs/08 §1.6 定案默认值）。"""

    concurrency: int = DEFAULT_CONCURRENCY
    short_limit: int = SHORT_CHAR_LIMIT
    batch_max_chars: int = BATCH_MAX_CHARS
    hard_limit: int = CHUNK_HARD_LIMIT
    temperature: float = TRANSLATE_TEMPERATURE
    max_tokens: int = TRANSLATE_MAX_TOKENS
    src_lang: str = "English"
    tgt_lang: str = "Chinese"


class XlatPipeline:
    """asyncio.Queue 编排：分桶 → 装箱 → N worker → 阶梯 → 对账 → 落盘。

    `validator(src, zh) -> str` 可注入 L0 全量规则（返回空串=通过）；
    缺省 = 占位符对账。`state` 给了就断点续跑 + 逐块落盘；`cache` 是
    段级缓存 dict（调用方负责 file_cache_key 维度的装载/落盘）。
    """

    def __init__(  # noqa: PLR0913 -- 依赖注入面（docs/08 §1.6 可插拔点全集）
        self,
        translator: Translator,
        *,
        config: PipelineConfig | None = None,
        glossary: Glossary | None = None,
        state: StateStore | None = None,
        validator: Callable[[str, str], str] | None = None,
        cache: dict[str, str] | None = None,
        on_result: Callable[[ChunkResult], None] | None = None,
    ) -> None:
        """组装编排器；`state`/`cache`/`validator`/`on_result` 均可选。"""
        self.translator = translator
        self.cfg = config or PipelineConfig()
        self.glossary = glossary
        self.state = state
        self.validator = validator or (lambda s, z: placeholders.diff(s, z).describe())
        self.cache = cache
        self.on_result = on_result
        self._doc_glossary: dict[str, str] = {}
        self._prompts: dict[tuple[str, bool], str] = {}

    # ------------------------------------------------------------ 物化

    def _system_prompt(self, kind: str, *, batch: bool = False) -> str:
        key = (kind, batch)
        if key not in self._prompts:
            self._prompts[key] = prompts.build_system_prompt(
                kind,
                src_lang=self.cfg.src_lang,
                tgt_lang=self.cfg.tgt_lang,
                glossary_terms=self._doc_glossary,
                batch=batch,
            )
        return self._prompts[key]

    def _materialize(self, pending: list[ChunkIn]) -> None:
        """文档级术语表过滤一次——整个跑批期间 system prompt 逐字节恒定。"""
        self._doc_glossary = {}
        if self.glossary is not None:
            self._doc_glossary = self.glossary.doc_filter(c.content for c in pending)

    def _seg_key(self, c: ChunkIn) -> str:
        """段级缓存键：source + role + masked 快照（占位符布局变则 key 变）。"""
        ph_types = [
            p.strip("[]").rpartition("_")[0] or p.strip("[]")
            for p in placeholders.ANY_PH_RX.findall(c.content)
        ]
        return segment_key(c.content, c.kind, masked_snapshot=repr(ph_types))

    # ------------------------------------------------------------ 单块路径

    async def _one_chunk(self, c: ChunkIn, *, batch_id: str = "") -> ChunkResult:
        """单块：缓存命中 → 否则阶梯翻译 → 校验 → 结果。"""
        key = self._seg_key(c)
        if self.cache is not None and key in self.cache:
            return ChunkResult(
                chunk_id=c.chunk_id,
                source=c.content,
                translation=self.cache[key],
                kind=c.kind,
                status="ok",
            )

        system = self._system_prompt(c.kind)

        async def translate_fn(src_text: str, feedback: str) -> str:
            user = src_text
            if feedback:
                user = f"{src_text}\n\n[previous_validation_error]\n{feedback}"
            return await self.translator.translate(
                system=system,
                user=user,
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )

        async def corrector_fn(original: str, translation: str, error: str) -> str:
            return await self.translator.translate(
                system=prompts.corrector_system_prompt(
                    self.cfg.src_lang, self.cfg.tgt_lang
                ),
                user=prompts.corrector_user_prompt(original, translation, error),
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )

        async def slots_fn(
            slots_map: dict[str, str], failures_json: str
        ) -> dict[str, str]:
            user_obj: dict[str, Any] = {
                "slots": slots_map,
                "instructions": (
                    f"Translate each slot value from {self.cfg.src_lang} to "
                    f"{self.cfg.tgt_lang}. Return a JSON object mapping each "
                    "slot id to its translation. Keep ids unchanged."
                ),
            }
            if failures_json:
                user_obj["slot_validation_failures"] = failures_json
            # response_format 在 3003 网关被静默忽略（B4a 实测三变体同输出）——
            # 只是 prompt 增强；真正约束在阶梯侧的槽位合法性校验+失败重问。
            raw = await self.translator.translate(
                system=system,
                user=json.dumps(user_obj, ensure_ascii=False),
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
                response_format={"type": "json_object"},
            )
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                return {}
            if isinstance(data, dict) and isinstance(data.get("slots"), dict):
                data = data["slots"]
            return data if isinstance(data, dict) else {}

        res = await translate_with_ladder(
            c.content,
            translate_fn=translate_fn,
            corrector_fn=corrector_fn,
            slots_fn=slots_fn,
            validate_fn=self.validator,
        )
        status = (
            "ok"
            if res.status == "ok"
            else "partial"
            if res.status == "recovered"
            else "fault"
        )
        if self.cache is not None and res.status in ("ok", "recovered"):
            self.cache[key] = res.translation
        return ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=res.translation,
            kind=c.kind,
            status=status,
            batch_id=batch_id,
            skipped=(res.status == "fallback_orig"),
            skip_reason=(
                "; ".join(res.warnings) if res.status == "fallback_orig" else ""
            ),
            attempts=res.attempts,
            warnings=res.warnings,
        )

    # ------------------------------------------------------------ 批量路径

    async def _one_batch(
        self, members: list[ChunkIn], batch_id: str
    ) -> list[ChunkResult]:
        """一批：编号批量请求 → 解析失败整批退单翻（成员走完整阶梯）。"""
        system = self._system_prompt(members[0].kind, batch=True)
        user = encode_batch([c.content for c in members])

        raw: str | None = None
        try:
            raw = await self.translator.translate(
                system=system,
                user=user,
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )
        except ChatError as e:
            if not e.retryable:
                # 认证/余额/地址类错误重试无意义——直接整块 skip
                return [self._skip(c, str(e), batch_id) for c in members]
            log.debug("batch %s call failed (%s) → degrade to singles", batch_id, e)
        except Exception as e:  # noqa: BLE001 -- 批量调用崩→退单翻，绝不丢成员
            log.debug("batch %s crashed (%s) → degrade to singles", batch_id, e)

        parts = parse_batch_response(raw, len(members)) if raw is not None else None
        if parts is None:
            return [await self._degrade_one(c, batch_id) for c in members]

        out: list[ChunkResult] = []
        for c, part in zip(members, parts, strict=True):
            zh = placeholders.decode_newlines(part)
            err = self.validator(c.content, zh)
            if err:
                # 批成功但该块校验败 → 单块回炉走完整阶梯
                out.append(await self._degrade_one(c, batch_id))
                continue
            if self.cache is not None:
                self.cache[self._seg_key(c)] = zh
            out.append(
                ChunkResult(
                    chunk_id=c.chunk_id,
                    source=c.content,
                    translation=zh,
                    kind=c.kind,
                    status="ok",
                    batched=True,
                    batch_id=batch_id,
                    attempts=1,
                )
            )
        return out

    async def _degrade_one(self, c: ChunkIn, batch_id: str) -> ChunkResult:
        """批量退路：单块走阶梯；阶梯/传输失败 → 回退原文 skipped。"""
        try:
            return await self._one_chunk(c, batch_id=batch_id)
        except ChatError as e:
            return self._skip(c, f"degraded single: {e}", batch_id)
        except Exception as e:  # noqa: BLE001 -- 单块崩不拖全批
            return self._skip(c, f"degraded single crash: {e}", batch_id)

    @staticmethod
    def _skip(c: ChunkIn, reason: str, batch_id: str = "") -> ChunkResult:
        """失败回退原文——不阻塞整批（docs/08 §1.6）。"""
        return ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=c.content,
            kind=c.kind,
            status="skipped",
            batch_id=batch_id,
            skipped=True,
            skip_reason=reason,
        )

    def _emit(self, r: ChunkResult) -> None:
        if self.state is not None:
            self.state.record(
                ChunkRecord(
                    chunk_id=r.chunk_id,
                    source=r.source,
                    translation=r.translation,
                    status=r.status,
                    kind=r.kind,
                    batched=r.batched,
                    batch_id=r.batch_id or None,
                    skipped=r.skipped,
                    skip_reason=r.skip_reason,
                    attempts=r.attempts,
                    warnings=r.warnings,
                ),
                error=({"error": r.skip_reason} if r.skipped else None),
            )
        if self.on_result is not None:
            self.on_result(r)

    # ------------------------------------------------------------ 主编排

    async def _process(self, item: tuple[str, Any]) -> list[ChunkResult]:
        """统一工作单元执行（warmup 与 worker 共用）。

        item 形态：`("batch", (序号, [ChunkIn]))` / `("single", ChunkIn)` /
        `("split", (父 ChunkIn, [片段...]))`——拆分块内部逐段走阶梯、译文合并
        后按父 id 记账（state/续跑只见父 id，不见片段 id）。
        """
        kind, payload = item
        if kind == "batch":
            bid, members = f"batch_{payload[0]:04d}", payload[1]
            try:
                return await self._one_batch(members, bid)
            except Exception as e:  # noqa: BLE001 -- worker 绝不让一批炸全队
                return [self._skip(c, f"batch crash: {e}", bid) for c in members]
        if kind == "split":
            parent, pieces = payload
            translations: list[str] = []
            warnings: list[str] = []
            worst = "ok"
            for piece in pieces:
                try:
                    r = await self._one_chunk(piece)
                except Exception as e:  # noqa: BLE001 -- 片段崩不拖全块
                    r = self._skip(piece, f"split piece crash: {e}")
                translations.append(r.translation)
                warnings += r.warnings
                if r.status in ("fault", "skipped"):
                    worst = "fault"
                elif r.status == "partial" and worst == "ok":
                    worst = "partial"
            merged = " ".join(translations)
            status = worst if worst != "ok" else "ok"
            return [
                ChunkResult(
                    chunk_id=parent.chunk_id,
                    source=parent.content,
                    translation=merged,
                    kind=parent.kind,
                    status=status,
                    skipped=(status == "fault"),
                    skip_reason="split piece(s) failed" if status == "fault" else "",
                    warnings=warnings,
                )
            ]
        c = payload
        try:
            return [await self._one_chunk(c)]
        except Exception as e:  # noqa: BLE001 -- 同上
            return [self._skip(c, f"chunk crash: {e}")]

    def _load_resumed(self) -> tuple[set[str], dict[str, ChunkResult]]:
        """续跑装载：state → (completed 集合, chunk_id→ChunkResult)。"""
        if self.state is None:
            return set(), {}
        completed, recs = self.state.load()
        done_map: dict[str, ChunkResult] = {}
        for cid, rec in recs.items():
            done_map[cid] = ChunkResult(
                chunk_id=rec.chunk_id,
                source=rec.source,
                translation=rec.translation,
                kind=rec.kind,
                status=rec.status,
                batched=rec.batched,
                batch_id=rec.batch_id or "",
                skipped=rec.skipped,
                skip_reason=rec.skip_reason,
                attempts=rec.attempts,
                warnings=rec.warnings,
            )
        return completed, done_map

    def _route_chunks(
        self,
        chunks: list[ChunkIn],
        completed: set[str],
        done_map: dict[str, ChunkResult],
    ) -> tuple[list[ChunkIn], list[tuple[str, Any]]]:
        """路由输入块 → (pending, split_items)。

        completed 直跳过；纯占位符直落盘；超 hard_limit 的原子块切成 split
        工作单元（译文按父 id 合并记账，state/续跑只见父 id）。
        """
        pending: list[ChunkIn] = []
        split_items: list[tuple[str, Any]] = []
        for c in chunks:
            cid = c.chunk_id
            if cid in completed and cid in done_map:
                continue
            if placeholders.is_placeholder_only(c.content.strip()):
                r = ChunkResult(
                    chunk_id=cid,
                    source=c.content,
                    translation=c.content,
                    kind=c.kind,
                    status="ok",
                )
                done_map[cid] = r
                self._emit(r)
                continue
            pieces = split_long_chunk(c.content, max_chars=self.cfg.hard_limit)
            if len(pieces) > 1:
                subs = [ChunkIn(f"{cid}~{i}", p, c.kind) for i, p in enumerate(pieces)]
                split_items.append(("split", (c, subs)))
            else:
                pending.append(c)
        return pending, split_items

    def _build_work_items(
        self,
        pending: list[ChunkIn],
        split_items: list[tuple[str, Any]],
    ) -> list[tuple[str, Any]]:
        """分桶 + 装箱：`("batch",(序号,[ChunkIn])) | ("single",ChunkIn) | split`。"""
        short = [c for c in pending if len(c.content) < self.cfg.short_limit]
        longs = [c for c in pending if len(c.content) >= self.cfg.short_limit]
        work_items: list[tuple[str, Any]] = [
            ("batch", (i, [short[j] for j in grp]))
            for i, grp in enumerate(
                pack_batches(
                    [c.content for c in short],
                    max_chars=self.cfg.batch_max_chars,
                )
            )
        ]
        work_items += [("single", c) for c in longs]
        return work_items + split_items

    async def _drain(
        self,
        work_items: list[tuple[str, Any]],
        done_map: dict[str, ChunkResult],
    ) -> None:
        """首发单飞暖前缀缓存 → N worker 消费 queue（哨兵收尾）。"""
        if not work_items:
            return
        queue: asyncio.Queue[tuple[str, Any] | None] = asyncio.Queue()
        for item in work_items:
            queue.put_nowait(item)

        async def worker() -> None:
            while True:
                item = await queue.get()
                try:
                    if item is None:
                        return
                    for r in await self._process(item):
                        done_map[r.chunk_id] = r
                        self._emit(r)
                finally:
                    queue.task_done()

        # 首发单飞暖前缀缓存，再并发其余（docs/08 §1.6 warmup 模式）
        first = await queue.get()
        if first is not None:
            for r in await self._process(first):
                done_map[r.chunk_id] = r
                self._emit(r)
        queue.task_done()

        for _ in range(self.cfg.concurrency):
            queue.put_nowait(None)
        workers = [asyncio.create_task(worker()) for _ in range(self.cfg.concurrency)]
        await queue.join()
        await asyncio.gather(*workers)

    async def run(self, chunks: list[ChunkIn]) -> list[ChunkResult]:
        """跑完整篇。返回与输入同序的结果表。"""
        completed, done_map = self._load_resumed()
        pending, split_items = self._route_chunks(chunks, completed, done_map)

        if self.state is not None:
            self.state.start(len(chunks))
        self._materialize(
            [*pending] + [p for _k, (_c, pieces) in split_items for p in pieces]
        )

        await self._drain(self._build_work_items(pending, split_items), done_map)

        if self.state is not None:
            self.state.finish()
        return [done_map[c.chunk_id] for c in chunks]
