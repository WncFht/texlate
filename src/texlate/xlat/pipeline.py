"""翻译编排骨架（docs/spec/translate.md）：asyncio.Queue + N worker + 首发单飞暖缓存。

流程：

    chunks[] → 滤 completed（state 续跑）→ 纯占位符直落盘
             → 超大原子块切分 → 全量 K 量化等大装箱（≤12000 字符/批）
             → 文档级术语表物化 + 各 kind system prompt 预建（逐字节恒定）
             → 首发单飞暖前缀缓存 → N worker 消费 queue
             → 每块经 retry 阶梯 → 占位符对账（leftover token 升格回退原文）
             → state 逐块落盘
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
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

# ``ChunkIn`` 契约下沉 ``texlate.chunk``（arxiv 降级链同消费——底层不能
# 向上 import 本包）；转口保持 ``from texlate.xlat.pipeline import ChunkIn``
# 钉点面守恒（repair_l2/e2e/worker/tests）。
from texlate.chunk import ChunkIn
from texlate.textutil import JSON_FENCE_RX

from . import placeholders, prompts
from .authgate import AuthGate, AuthTrippedError, _kind_of
from .batch import (
    BATCH_MAX_CHARS,
    BATCH_MAX_ITEMS,
    BATCH_MIN_CHARS,
    CHUNK_HARD_LIMIT,
    encode_batch_members,
    pack_batches,
    parse_batch_response,
    split_long_chunk,
)
from .client import (
    HTTP_UNAUTHORIZED,
    REASONING_MIN_MAX_TOKENS,
    ChatClient,
    ChatError,
    ChatOptions,
    LengthTruncatedError,
)
from .intercept import (
    _INTERCEPT_NETS,
    # 包装函钉点面——``_net_apply_fn`` 经 ``globals()`` 晚绑定取件，
    # tests ``monkeypatch.setattr(pl, "_intercept_*")`` 缝在本模块命名空间
    _intercept_bare_cs,  # noqa: F401
    _intercept_leftover_ph,  # noqa: F401
    _intercept_ph_in_cs,  # noqa: F401
    _intercept_residual_en,  # noqa: F401
    _interceptable,
)

# 转口——``from texlate.xlat.pipeline import MockTranslator/MOCK_ZH`` 钉点
# （src/tests/bench ~40 处）在 MockTranslator 出叶 ``.mock`` 后口径不变；
# 私名 ``_mock_translate_text`` 同钉（translators_bench/test_sabotage_arms）。
from .mock import MOCK_ZH, MockTranslator, _mock_translate_text  # noqa: F401
from .retry import (
    RetryPolicy,
    assess_answer,
    bare_token_audit,
    call_with_backoff,
    translate_with_ladder,
)
from .state import ChunkRecord, StateStore, segment_key

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from texlate.latex.model import Chunk

    from .glossary import Glossary
    from .intercept import _InterceptNet

log = logging.getLogger(__name__)

#: 翻译温度（docs/spec/translate.md：0.2~0.3 保守值；judge/抽取 0）
TRANSLATE_TEMPERATURE = 0.2
#: 翻译输出预算（reasoning 模型下限；短输出不亏——按量计费）——
#: 别名 client 层的 reasoning 地板常量（autogloss.EXTRACT_MAX_TOKENS 同款），
#: 地板上调时翻译预算随动不滞后
TRANSLATE_MAX_TOKENS = REASONING_MIN_MAX_TOKENS
#: length 截断重试的放大预算
LENGTH_RETRY_MAX_TOKENS = 32768
#: 默认并发（provider 限额 10~50 可调）
DEFAULT_CONCURRENCY = 10
#: paper-context 锚定块的 abstract 截断上限（texglot ``limit_context`` 同族）
PAPER_CTX_MAX_CHARS = 6000


# ---------------------------------------------------------------- 输入/输出


def chunk_to_in(
    c: Chunk, *, chunk_id: str | None = None, ph_map: dict[str, str] | None = None
) -> ChunkIn:
    """``Chunk`` → ``ChunkIn`` 唯一适配点（context → kind 走 ``normalize_kind``）。

    ``chunk_id`` 缺省 ``str(c.id)``；多文件编排时调用方给命名空间 id
    （如 ``f"{file_idx}:{c.id}"``）。``ph_map`` 给 ScanResult.ph_map 时按
    块内出现的 token 裁出 ``ph_fragments``，武装抄回修复臂。
    """
    frags: dict[str, str] | None = None
    if ph_map is not None:
        toks = c.placeholders or placeholders.TYPED_PH_RX.findall(c.content)
        frags = {ph: ph_map[ph] for ph in toks if ph in ph_map}
    return ChunkIn(
        chunk_id=chunk_id if chunk_id is not None else str(c.id),
        content=c.content,
        kind=prompts.normalize_kind(c.context),
        ph_fragments=frags,
    )


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
    skip_reason: str = ""
    attempts: int = 0
    warnings: list[str] = field(default_factory=list)
    #: 失败成因分类（打标处在异常现场赋值）："" | auth | provider | crash |
    #: validate——auth 闸计数与 error_code 归一的共同输入。
    error_kind: str = ""

    @property
    def fell_back(self) -> bool:
        """zh≡src 有意回退簿记（单源派生）——DB 侧 ``fallback_orig`` 同语义。

        ``status == "skipped"``，或 ``fault`` + 回退原文 + 记有 ``skip_reason``。
        故名 ``fell_back`` 而非 ``skipped``——覆盖面比 ``status=="skipped"``
        宽，同名会把 fault 臂读者带偏。``retranslate_chunk`` 仍败的 fault
        形同形回退但无簿记（O1 留档异形）——区分键正是 ``skip_reason``
        缺位；写方只落 status/translation/skip_reason 三件事实，本标记
        读其逻辑后果。
        """
        return self.status == "skipped" or (
            self.status == "fault"
            and self.translation == self.source
            and bool(self.skip_reason)
        )

    @classmethod
    def from_record(cls, rec: ChunkRecord) -> ChunkResult:
        """``ChunkRecord`` → ``ChunkResult`` 唯一适配点（``batch_id`` None→""、warnings 拷份）。"""
        return cls(
            chunk_id=rec.chunk_id,
            source=rec.source,
            translation=rec.translation,
            kind=rec.kind,
            status=rec.status,
            batched=rec.batched,
            batch_id=rec.batch_id or "",
            skip_reason=rec.skip_reason,
            attempts=rec.attempts,
            warnings=[*rec.warnings],
            error_kind=rec.error_kind,
        )

    def to_record(self) -> ChunkRecord:
        """→ ``ChunkRecord``（``batch_id`` ""→None；warnings 沿用同列——record 落盘口径）。"""
        return ChunkRecord(
            chunk_id=self.chunk_id,
            source=self.source,
            translation=self.translation,
            status=self.status,
            kind=self.kind,
            batched=self.batched,
            batch_id=self.batch_id or None,
            skipped=self.fell_back,
            skip_reason=self.skip_reason,
            attempts=self.attempts,
            warnings=self.warnings,
            error_kind=self.error_kind,
        )


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


#: LLM 输出裸 C0 控制符（``\x09\x0a\x0d`` 合法空白保留）——剥除防 slots JSON strict
#: 拒收整批弃置、以及 C0 落进 .tex 后 compile ``invalid_char``（``non_utf8_recode``
#: 不管合法 UTF-8 控制符）。上游 BabelDOC PR #612 同坑实证。
_C0_RX = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


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
                    and isinstance(e, LengthTruncatedError)
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
            return _C0_RX.sub("", r.content)

        return await call_with_backoff(_go, policy=self.policy)


def _strip_json_fence(raw: str) -> str:
    """剥掉整段 ``` 围栏；非围栏原文原样返回。"""
    m = JSON_FENCE_RX.match(raw)
    return m.group("body") if m else raw


# ---------------------------------------------------------------- Pipeline


def _net_apply_fn(net: _InterceptNet) -> Callable[[ChunkResult], None]:
    """``net`` 的模块级 apply 包装函（``_intercept_<name>`` 词根约定）。

    ``globals()`` 晚绑定取件而非条目持引用——tests 的 ``monkeypatch.setattr``
    改模块属性后账本形/裸形两消费点仍拿到补丁件（fault 注入钉点面守恒，
    早绑定会把注入静默旁路）。注册表与包装函本体已出叶 ``.intercept``——
    本件留本模块正是因为 ``globals()`` 钉的是本命名空间。
    """
    return globals()[f"_intercept_{net.name}"]


class WorkItem(NamedTuple):
    """工作单元 tagged union——``kind`` + 命名 accessor 是生产侧唯一解码点。

    tuple 形为存量两元解包/下标消费面（``for k, payload in items``、
    ``it[0]``）保兼容；``payload`` 位序语义只经本类 accessor 读——
    ``payload[0]`` 在 ``batch`` 是批序号、``split`` 是父块、``single``
    载荷即块本身。新增 item 种类只改本类 + ``_process`` 一处。

    - ``batch``：``(seq, members)``
    - ``split``：``(parent, pieces)``——片段译文合并后按父 id 记账
    - ``single``：``ChunkIn``
    """

    kind: str  # "batch" | "split" | "single"
    payload: Any  # tagged union 载荷形态随 kind 变，命名 accessor 给出类型

    @property
    def seq(self) -> int:
        """``batch`` 批序号。"""
        return int(self.payload[0])

    @property
    def members(self) -> list[ChunkIn]:
        """``batch`` 成员列表。"""
        return list(self.payload[1])

    @property
    def parent(self) -> ChunkIn:
        """``split`` 父块（记账 id 属主）。"""
        return self.payload[0]  # type: ignore[no-any-return]

    @property
    def pieces(self) -> list[ChunkIn]:
        """``split`` 片段序列。"""
        return list(self.payload[1])

    @property
    def chunk(self) -> ChunkIn:
        """``single`` 载荷块。"""
        return self.payload  # type: ignore[no-any-return]

    def affected(self) -> list[ChunkIn]:
        """本单元覆盖的 ChunkIn（auth 闸/worker crash 兜底记账用）。"""
        if self.kind == "batch":
            return self.members
        if self.kind == "split":
            return [self.parent]
        return [self.chunk]


def _slots_user_obj(
    c: ChunkIn,
    slots_map: dict[str, str],
    failures_json: str,
    *,
    cfg: PipelineConfig,
) -> dict[str, Any]:
    """Slots 调用 user JSON：slots + instructions + 可选字段。

    ``placeholder_values``（占位符值参考，截断口径同 user 后缀块）与
    ``slot_validation_failures`` 各自有才挂——字段缺席即"无此信息"，
    比空值少一层解析歧义。
    """
    user_obj: dict[str, Any] = {
        "slots": slots_map,
        "instructions": (
            f"Translate each slot value from {cfg.src_lang} to "
            f"{cfg.tgt_lang}. Return a JSON object mapping each "
            "slot id to its translation. Keep ids unchanged."
        ),
    }
    if c.ph_fragments:
        user_obj["placeholder_values"] = prompts.truncate_value_frags(c.ph_fragments)
    if failures_json:
        user_obj["slot_validation_failures"] = failures_json
    return user_obj


def _merged_value_frags(members: list[ChunkIn]) -> dict[str, str]:
    """批成员 ``ph_fragments`` 合并——token 文档内唯一，同 key 后写赢。

    同 token 跨成员指向同实体，冲突本不该出现；合并块随批 user 尾挂，
    给模型读着消歧（texglot ``value_tokens`` 同族）。
    """
    merged: dict[str, str] = {}
    for c in members:
        if c.ph_fragments:
            merged.update(c.ph_fragments)
    return merged


@dataclass
class PipelineConfig:
    """编排参数（docs/spec/translate.md 定案默认值）。"""

    concurrency: int = DEFAULT_CONCURRENCY
    batch_max_chars: int = BATCH_MAX_CHARS
    batch_max_items: int = BATCH_MAX_ITEMS
    batch_min_chars: int = BATCH_MIN_CHARS
    hard_limit: int = CHUNK_HARD_LIMIT
    temperature: float = TRANSLATE_TEMPERATURE
    max_tokens: int = TRANSLATE_MAX_TOKENS
    src_lang: str = "English"
    tgt_lang: str = "Chinese"
    #: 连续 auth-fail 块数熔断阈值（T2；≤0 = 不熔断）
    auth_fail_threshold: int = 3
    #: 逐篇术语抽取件（``autogloss.extract_terms`` 的 partial）——
    #: ``async (masked_texts) -> {en: zh}``；None=关。抽取结果进 doc_glossary
    #: 底层（同 key 由既有五层表赢——curated 覆盖 auto）。调用方负责
    #: memoize（worker ctx.memo / e2e 单例），否则 resume 会重抽。
    auto_glossary_fn: Callable[[list[str]], Awaitable[dict[str, str]]] | None = None

    def __post_init__(self) -> None:
        """数值钳位：0/负并发会饿死 worker 让 queue.join 死等；hard_limit<1 让 split 死循环。"""
        self.concurrency = max(1, self.concurrency)
        self.hard_limit = max(1, self.hard_limit)


class XlatPipeline:
    """asyncio.Queue 编排：分桶 → 装箱 → N worker → 阶梯 → 对账 → 落盘。

    `validator(src, zh) -> str` 可注入 L0 全量规则（返回空串=通过）；
    缺省 = 占位符对账。`state` 给了就断点续跑 + 逐块落盘；`cache` 是
    段级缓存 dict（调用方负责 file_cache_key 维度的装载/落盘）。
    """

    def __init__(  # noqa: PLR0913 -- 依赖注入面（docs/spec/translate.md 可插拔点全集）
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
        #: auth 熔断闸（``run()`` 每次开头重置；跨论文熔断靠调用方读它累计）
        self.auth_gate = AuthGate(self.cfg.auth_fail_threshold)
        self._doc_glossary: dict[str, str] = {}
        self._paper_ctx = ""
        self._prompts: dict[tuple[str, bool, bool], str] = {}

    # ------------------------------------------------------------ 物化

    def _system_prompt(
        self, kind: str, *, batch: bool = False, paper_ctx: bool = True
    ) -> str:
        key = (kind, batch, paper_ctx)
        if key not in self._prompts:
            self._prompts[key] = prompts.build_system_prompt(
                kind,
                src_lang=self.cfg.src_lang,
                tgt_lang=self.cfg.tgt_lang,
                glossary_terms=self._doc_glossary,
                batch=batch,
                paper_context=self._paper_ctx if paper_ctx else None,
            )
        return self._prompts[key]

    async def _auto_glossary(
        self, chunks: list[ChunkIn], pending: list[ChunkIn]
    ) -> dict[str, str]:
        """``auto_glossary_fn`` 抽取层——空 pending 不抽；失败降级 {} 不炸主链。

        术语是增强件：抽取调用炸（网关/JSON/超时）只损失一层术语注入，
        不该让论文 fault。输入=全量 chunks 的 masked 文本（与
        ``_materialize`` 文档级过滤同口径，``[[X_n]]`` 占位符由抽取
        prompt 按不透明 token 跳过）。
        """
        fn = self.cfg.auto_glossary_fn
        if fn is None or not pending:
            return {}
        try:
            terms = await fn([c.content for c in chunks])
        except Exception as e:  # noqa: BLE001 -- 增强件失败只告警不致死
            log.warning("auto-glossary extraction failed → 无 auto 层续跑: %s", e)
            return {}
        return terms or {}

    def _materialize(
        self, chunks: list[ChunkIn], auto_terms: dict[str, str] | None = None
    ) -> None:
        """文档级术语表过滤一次——整个跑批期间 system prompt 逐字节恒定。

        ``chunks`` 是全量输入块（含 state 已完成块）而非 pending 子集——
        ``doc_filter`` 与 ``_paper_ctx`` 锚定须见已完成块，续跑口径才与
        全新跑逐字节一致（前缀缓存身份 + abstract 锚不漂）。
        """
        self._doc_glossary = dict(auto_terms or {})
        if self.glossary is not None:
            # curated 五层表 update 在后赢同 key——auto 抽取层是底座
            self._doc_glossary.update(
                self.glossary.doc_filter(c.content for c in chunks)
            )
        # 首个 abstract 块 masked 原文截断做 paper-context 锚定块（texglot
        # ``paper_context`` 同族）；[[X_n]] 保留无妨——值由 user 侧
        # placeholder_values 块供读。全量 chunks 扫描（含已完成块）——
        # 续跑口径与全新跑逐字节一致。
        self._paper_ctx = next(
            (c.content[:PAPER_CTX_MAX_CHARS] for c in chunks if c.kind == "abstract"),
            "",
        )
        # 同实例二次 run 换了文档 → 术语块变了，prompt memo 必须失效重渲染
        self._prompts.clear()

    def _seg_key(self, c: ChunkIn) -> str:
        """段级缓存键：source + role + masked 快照（占位符布局变则 key 变）。"""
        ph_types = [
            placeholders.ph_type(p)
            for p in placeholders.ANY_PH_RX.findall(c.content)
        ]
        return segment_key(c.content, c.kind, masked_snapshot=repr(ph_types))

    def _cache_store(self, c: ChunkIn, zh: str) -> None:
        """段级缓存写入；过不了升格拦截网注册表的译文不入缓存——防毒化续跑。

        缓存命中旁路校验：同一份污染译文若落缓存，每轮续跑反复命中、永远修不正。
        判定口径 = ``_INTERCEPT_NETS`` 各 ``detect``（``_collect`` 升格拦截同源）。
        """
        if self.cache is None or _interceptable(c.content, zh):
            return
        self.cache[self._seg_key(c)] = zh

    # ------------------------------------------------------------ 单块路径

    def _repair_fn(
        self, c: ChunkIn
    ) -> Callable[[str, str], tuple[str, list[str]]] | None:
        """阶梯修复臂：译文缺 token 且 fragment 唯一命中 → 抄回（placeholders 层）。"""
        frags = c.ph_fragments
        if not frags:
            return None

        def _repair(src_text: str, zh: str) -> tuple[str, list[str]]:
            todo = {
                ph: frags[ph]
                for ph in placeholders.diff(src_text, zh).missing
                if ph in frags
            }
            return placeholders.recover_copied_tokens(zh, todo)

        return _repair

    def _cache_hit(self, c: ChunkIn, batch_id: str) -> ChunkResult | None:
        """缓存命中解析 → ok 结果；命中旧毒条目则清除并返回 None（落回重翻自愈）。

        旧版写入侧放行过 ``_interceptable`` 译文——不清则缓存命中旁路校验，
        毒译每轮续跑都被 intercept 降 fault、永不修复。
        """
        if self.cache is None:
            return None
        key = self._seg_key(c)
        if key not in self.cache:
            return None
        zh = self.cache[key]
        if _interceptable(c.content, zh):
            del self.cache[key]
            log.warning("evicted poisoned cache entry for %s", c.chunk_id)
            return None
        return ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=zh,
            kind=c.kind,
            status="ok",
            batch_id=batch_id,
        )

    async def _one_chunk(self, c: ChunkIn, *, batch_id: str = "") -> ChunkResult:
        """单块：缓存命中 → 否则阶梯翻译 → 校验 → 结果。"""
        if hit := self._cache_hit(c, batch_id):
            return hit

        system = self._system_prompt(c.kind)

        async def translate_fn(src_text: str, feedback: str) -> str:
            user = src_text + prompts.render_value_context(c.ph_fragments or {})
            if feedback:
                user = f"{user}\n\n[previous_validation_error]\n{feedback}"
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
            user_obj = _slots_user_obj(c, slots_map, failures_json, cfg=self.cfg)
            # response_format 在 3003 网关被静默忽略（B4a 实测三变体同输出）——
            # 只是 prompt 增强；真正约束在阶梯侧的槽位合法性校验+失败重问。
            raw = await self.translator.translate(
                system=self._system_prompt(c.kind, paper_ctx=False),
                user=json.dumps(user_obj, ensure_ascii=False),
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
                response_format={"type": "json_object"},
            )
            try:
                data = json.loads(_strip_json_fence(raw))
            except (json.JSONDecodeError, RecursionError):
                # RecursionError：模型输出超深嵌套同坏 JSON 计——弃本轮 slots
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
            repair_fn=self._repair_fn(c),
        )
        status = (
            "ok"
            if res.status == "ok"
            else "partial"
            if res.status == "recovered"
            else "fault"
        )
        # 坍缩标点清理已收口进阶梯 postlude（``assess_answer``）——fallback_orig
        # 原文在此不再过清洗，保住 ``fell_back`` 的 zh≡src 簿记不变量
        zh = res.translation
        if res.status in ("ok", "recovered"):
            self._cache_store(c, zh)
        return ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=zh,
            kind=c.kind,
            status=status,
            batch_id=batch_id,
            skip_reason=(
                "; ".join(res.warnings) if res.status == "fallback_orig" else ""
            ),
            attempts=res.attempts,
            warnings=res.warnings,
            error_kind="validate" if res.status == "fallback_orig" else "",
        )

    async def retranslate_chunk(
        self, c: ChunkIn, compile_feedback: str
    ) -> ChunkResult | None:
        """L2 回灌单发重译：带 ``[compile_error]`` 反馈再要一次，不走阶梯。

        每 chunk 只此一发的配额由调用方（e2e L2 回灌）记账。返回值：

        - ``None`` —— 传输层异常：保留原译，调用方按"未变"处理；
        - ``status="ok"`` —— L0 过：新译可入 splice（并写段级缓存）；
        - ``status="fault"`` + ``translation=source`` —— L0 仍败：
          调用方应回落原文（spec：再不过 → fallback 原文）。
        """
        system = self._system_prompt(c.kind)
        try:
            raw = await self.translator.translate(
                system=system,
                user=(
                    f"{c.content}"
                    f"{prompts.render_value_context(c.ph_fragments or {})}"
                    f"\n\n[compile_error]\n{compile_feedback}"
                ),
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )
        except Exception as e:  # noqa: BLE001 -- 传输崩=保留原译，不算一次有效修复
            log.debug("retranslate %s transport failed: %s", c.chunk_id, e)
            return None
        # 回灌 user 是未编码原文——token 多重集期望基线同为原文形态
        zh, err, warnings = assess_answer(
            c.content,
            placeholders.decode_newlines(raw),
            audit_err=bare_token_audit(c.content, raw),
            repair_fn=self._repair_fn(c),
            validate_fn=self.validator,
        )
        if err:
            return ChunkResult(
                chunk_id=c.chunk_id,
                source=c.content,
                translation=c.content,
                kind=c.kind,
                status="fault",
                attempts=1,
                warnings=[*warnings, f"retranslate still invalid: {err}"],
                error_kind="validate",
            )
        self._cache_store(c, zh)
        r = ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=zh,
            kind=c.kind,
            status="ok",
            attempts=1,
            warnings=warnings,
        )
        # L2 回灌同受拦截——fault 由调用方回落原文；与账本形同表晚绑定取件，
        # 新增网在本臂不会漏挂。
        for net in _INTERCEPT_NETS:
            _net_apply_fn(net)(r)
        return r

    # ------------------------------------------------------------ 批量路径

    async def _one_batch(
        self, members: list[ChunkIn], batch_id: str
    ) -> list[ChunkResult]:
        """一批：成员先过段级缓存短路，实发子集走编号批量协议。

        逐成员 ``_cache_hit`` 前置（D4）：命中块不进批载荷——省 token、防新应答
        经 ``_cache_store`` 覆盖原条目、批级失败（非可重试 skip/退单翻）也不再
        连坐有缓存的成员。批序号按实发子集编排，``send`` 记原序位回填，返回
        列表与 ``members`` 同序。
        """
        out: dict[int, ChunkResult] = {}
        send: list[tuple[int, ChunkIn]] = []
        for i, c in enumerate(members):
            if hit := self._cache_hit(c, batch_id):
                out[i] = hit
            else:
                send.append((i, c))
        if send:
            out.update(await self._batch_call(send, batch_id))
        return [out[i] for i in range(len(members))]

    async def _batch_call(
        self, send: list[tuple[int, ChunkIn]], batch_id: str
    ) -> dict[int, ChunkResult]:
        """实发子集的批量往返：编号请求 → 解析失败整批退单翻（成员走完整阶梯）。

        ``send`` = ``(members 内原序位, ChunkIn)`` 对；返回 ``{原序位: 结果}``。
        """
        members = [c for _i, c in send]
        system = self._system_prompt(members[0].kind, batch=True)
        # 各成员 ph_fragments 合并成批级 value-context 随 user 尾挂；成员编码
        # 只跑一次——``enc_members[k]`` 直作下方 ``bare_token_audit`` 基线
        #（与线发字节结构性同源，免逐成员二次 ``encode_newlines`` 重推导）
        payload, enc_members = encode_batch_members([c.content for c in members])
        user = payload + (prompts.render_value_context(_merged_value_frags(members)))

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
                return {
                    i: self._skip(c, str(e), batch_id, kind=_kind_of(e))
                    for i, c in send
                }
            log.debug("batch %s call failed (%s) → degrade to singles", batch_id, e)
        except Exception as e:  # noqa: BLE001 -- 批量调用崩→退单翻，绝不丢成员
            log.debug("batch %s crashed (%s) → degrade to singles", batch_id, e)

        parts = parse_batch_response(raw, len(members)) if raw is not None else None
        out: dict[int, ChunkResult] = {}
        if parts is None:
            for i, c in send:
                out[i] = await self._degrade_one(c, batch_id)
            return out

        for k, ((i, c), part) in enumerate(zip(send, parts, strict=True)):
            # 批成员按 ``encode_batch_members`` 同款编码形态对账锻造 token（D3）——
            # ``enc_members[k]`` 即 ``encode_newlines(c.content)[0]`` 的同源基线
            zh, err, warnings = assess_answer(
                c.content,
                placeholders.decode_newlines(part),
                audit_err=bare_token_audit(enc_members[k], part),
                repair_fn=self._repair_fn(c),
                validate_fn=self.validator,
            )
            if err:
                # 批成功但该块校验败 → 单块回炉走完整阶梯
                out[i] = await self._degrade_one(c, batch_id)
                continue
            self._cache_store(c, zh)
            out[i] = ChunkResult(
                chunk_id=c.chunk_id,
                source=c.content,
                translation=zh,
                kind=c.kind,
                status="ok",
                batched=True,
                batch_id=batch_id,
                attempts=1,
                warnings=warnings,
            )
        return out

    async def _degrade_one(self, c: ChunkIn, batch_id: str) -> ChunkResult:
        """批量退路：单块走阶梯；阶梯/传输失败 → 回退原文 skipped。"""
        try:
            return await self._one_chunk(c, batch_id=batch_id)
        except ChatError as e:
            return self._skip(c, f"degraded single: {e}", batch_id, kind=_kind_of(e))
        except Exception as e:  # noqa: BLE001 -- 单块崩不拖全批
            return self._skip(c, f"degraded single crash: {e}", batch_id, kind="crash")

    @staticmethod
    def _skip(
        c: ChunkIn, reason: str, batch_id: str = "", *, kind: str = ""
    ) -> ChunkResult:
        """失败回退原文——不阻塞整批（docs/spec/translate.md）。``kind`` 记失败成因。"""
        return ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=c.content,
            kind=c.kind,
            status="skipped",
            batch_id=batch_id,
            skip_reason=reason,
            error_kind=kind,
        )

    @staticmethod
    def _passthrough_result(
        c: ChunkIn, *, warnings: list[str] | None = None
    ) -> ChunkResult:
        """zh≡src 直通结果——placeholder_only 与 ``[[BIB_`` 文献域共用落形。"""
        return ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=c.content,
            kind=c.kind,
            status="ok",
            warnings=warnings or [],
        )

    def _emit(self, r: ChunkResult) -> None:
        if self.state is not None:
            self.state.record(
                r.to_record(),
                error=({"error": r.skip_reason} if r.fell_back else None),
            )
        if self.on_result is not None:
            self.on_result(r)

    # ------------------------------------------------------------ 主编排

    async def _process(self, item: WorkItem) -> list[ChunkResult]:
        """统一工作单元执行（warmup 与 worker 共用）。

        item 形态：`WorkItem("batch", (序号, [ChunkIn]))` / `("single", ChunkIn)` /
        `("split", (父 ChunkIn, [片段...]))`——拆分块内部逐段走阶梯、译文合并
        后按父 id 记账（state/续跑只见父 id，不见片段 id）。
        """
        if item.kind == "batch":
            bid, members = f"batch_{item.seq:04d}", item.members
            try:
                return await self._one_batch(members, bid)
            except Exception as e:  # noqa: BLE001 -- worker 绝不让一批炸全队
                return [
                    self._skip(c, f"batch crash: {e}", bid, kind=_kind_of(e))
                    for c in members
                ]
        if item.kind == "split":
            parent, pieces = item.parent, item.pieces
            translations: list[str] = []
            warnings: list[str] = []
            kinds: list[str] = []
            attempts = 0
            worst = "ok"
            for piece in pieces:
                try:
                    r = await self._one_chunk(piece)
                except Exception as e:  # noqa: BLE001 -- 片段崩不拖全块
                    r = self._skip(piece, f"split piece crash: {e}", kind=_kind_of(e))
                translations.append(r.translation)
                warnings += r.warnings
                kinds.append(r.error_kind)
                attempts += r.attempts
                if r.status in ("fault", "skipped"):
                    worst = "fault"
                elif r.status == "partial" and worst == "ok":
                    worst = "partial"
            merged = " ".join(translations)
            status = worst if worst != "ok" else "ok"
            if status == "fault":
                # 保 skipped⇒translation==source 簿记不变量（D2）——merged 半成品
                # 折进 warnings 留诊断（对齐 fallback_orig 的 best_zh 口径）
                warnings.append(f"best-effort zh (unspliced): {merged[:200]}")
            return [
                ChunkResult(
                    chunk_id=parent.chunk_id,
                    source=parent.content,
                    translation=parent.content if status == "fault" else merged,
                    kind=parent.kind,
                    status=status,
                    skip_reason="split piece(s) failed" if status == "fault" else "",
                    attempts=attempts,
                    warnings=warnings,
                    error_kind=(
                        "auth" if "auth" in kinds else next((k for k in kinds if k), "")
                    ),
                )
            ]
        c = item.chunk
        try:
            return [await self._one_chunk(c)]
        except Exception as e:  # noqa: BLE001 -- 同上
            return [self._skip(c, f"chunk crash: {e}", kind=_kind_of(e))]

    def _load_resumed(
        self, fatal: list[BaseException]
    ) -> tuple[set[str], dict[str, ChunkResult]]:
        """续跑装载：state → (completed 集合, chunk_id→ChunkResult)。"""
        if self.state is None:
            return set(), {}
        completed, recs = self.state.load()
        # completed 只认 ok/partial：skipped/fault（三振回退原文、网关抖动 skip）
        # 在续跑里必须重试——否则一次瞬时失败会把该块永久冻结成英文原文。
        # state.json 里 completed 仍记全部已尝试块（审计口径不变），过滤只在
        # 编排侧生效；重试结果经 record() 追加覆盖 done_map。
        done_map: dict[str, ChunkResult] = {}
        for cid, rec in recs.items():
            res = ChunkResult.from_record(rec)
            # warning 时代落盘的 ok 残留（zh 带源外占位符）→ 就地降 fault，
            # 不进 completed → 本轮重翻自愈；否则旧档会把字面 [[X_n]] 带进 splice。
            self._ledger_intercepts(fatal, res)
            done_map[cid] = res
        completed = {
            cid
            for cid in completed
            if cid in done_map and done_map[cid].status in ("ok", "partial")
        }
        return completed, done_map

    def _route_chunks(
        self,
        chunks: list[ChunkIn],
        completed: set[str],
        done_map: dict[str, ChunkResult],
        fatal: list[BaseException],
    ) -> tuple[list[ChunkIn], list[WorkItem]]:
        """路由输入块 → (pending, split_items)。

        completed 直跳过；纯占位符直落盘；超 hard_limit 的原子块切成 split
        工作单元（译文按父 id 合并记账，state/续跑只见父 id）。
        """
        pending: list[ChunkIn] = []
        split_items: list[WorkItem] = []
        for c in chunks:
            cid = c.chunk_id
            prev = done_map.get(cid)
            if cid in completed and prev is not None:
                if prev.source == c.content:
                    continue
                # parse 漂移下同 id 命中陈旧记录——其译文的 [[X_n]] 在新
                # ph_map 缺席 → splice 留字面残留（n100 实测 1524 例）。
                # 按未命中重翻自愈；丢出 done_map 防异常路径把旧译文当结果。
                log.warning(
                    "chunk %s source drifted (recorded %dB != current %dB) → re-translate",
                    cid,
                    len(prev.source),
                    len(c.content),
                )
                del done_map[cid]
            if placeholders.is_placeholder_only(c.content.strip()):
                r = self._passthrough_result(c)
                done_map[cid] = r
                # 与 _collect 同构的账本调用（拦截网 + record + emit）——
                # BaseException 收 fatal 由 run() 序章尾统一重抛，
                # Exception 档行为不变。
                self._ledger_outcome(fatal, r)
                continue
            if "[[BIB_" in c.content:
                # 用户裁决①：[[BIB_]]（\bibitem/bibliography 占位）块=文献域，
                # 约定留英不送翻——直通 zh=src，占位符链下游照常还原。
                # zh≡src 使各拦截网 diff 恒空，intercept 形同虚设但账本调用与
                # placeholder_only 路保持同构（计量/auth 闸口径一致）。
                r = self._passthrough_result(c, warnings=["bib_passthrough"])
                done_map[cid] = r
                self._ledger_outcome(fatal, r)
                continue
            pieces = split_long_chunk(c.content, max_chars=self.cfg.hard_limit)
            if len(pieces) > 1:
                subs = [
                    ChunkIn(f"{cid}~{i}", p, c.kind, ph_fragments=c.ph_fragments)
                    for i, p in enumerate(pieces)
                ]
                split_items.append(WorkItem("split", (c, subs)))
            else:
                pending.append(c)
        return pending, split_items

    def _build_work_items(
        self,
        pending: list[ChunkIn],
        split_items: list[WorkItem],
    ) -> list[WorkItem]:
        """全量装箱：`WorkItem("batch",(序号,[ChunkIn])) | ("single",ChunkIn) | split`。

        不分 short/long——产线对账批质量 ≥ 单发（per-placeholder 错率 0.32%
        vs 8.93%），全量入批只为削 ``n_req × ~2.9s`` 固定开销。batch 按 kind
        分组再装箱——一批共用 ``members[0].kind`` 的 system prompt，混 kind
        会让 caption/abstract 等专属条款错配到 para 头上。装箱吃
        ``concurrency`` 做 K 量化等大对齐（batchmodel-2026-09-18 §8）；
        装箱退化成单成员的组走 ``single`` 阶梯路径（比一发批协议多 corrector/
        slots/repair 全套修复臂）。
        """
        by_kind: dict[str, list[ChunkIn]] = {}
        for c in pending:
            by_kind.setdefault(c.kind, []).append(c)
        work_items: list[WorkItem] = []
        seq = 0
        for grp_chunks in by_kind.values():  # dict 保 insertion 序——批次确定性
            for grp in pack_batches(
                [c.content for c in grp_chunks],
                max_chars=self.cfg.batch_max_chars,
                max_items=self.cfg.batch_max_items,
                min_chars=self.cfg.batch_min_chars,
                workers=self.cfg.concurrency,
            ):
                if len(grp) == 1:
                    work_items.append(WorkItem("single", grp_chunks[grp[0]]))
                else:
                    work_items.append(
                        WorkItem("batch", (seq, [grp_chunks[j] for j in grp]))
                    )
                    seq += 1
        return work_items + split_items

    async def _worker(
        self,
        queue: asyncio.Queue[WorkItem | None],
        done_map: dict[str, ChunkResult],
        fatal: list[BaseException],
    ) -> None:
        """消费循环：哨兵退出；item 级 crash 兜底成 skipped。

        worker 不死——否则 queue.join() 死等 + done_map 缺口在 run() 末行
        炸 KeyError。BaseException 族（KI/SE/GE）同样不可任 worker 带其
        死掉：sentinel 与 worker 一一对应，死者那份无人消费，join() 死锁
        （E3）。记入 ``fatal`` 降级成 skipped 后继续消费；``fatal`` 已挂
        时只吃不做排空到 sentinel——提前 return 会让剩余项无人 task_done，
        join() 照样死等——由 _drain 收敛后重抛。
        """
        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                if fatal:
                    # 致命异常已挂：排空队列项保 join 会计，不再发翻译请求
                    continue
                if self.auth_gate.tripped:
                    # auth 闸已断：剩余块不再发请求，直接按 auth 失败记账
                    results = [
                        self._skip(c, "auth circuit open", kind="auth")
                        for c in item.affected()
                    ]
                else:
                    try:
                        results = await self._process(item)
                    except Exception as e:
                        # _process 各分支已兜底；真逃逸（bug/中断）也要把受影响
                        # 块记成 skipped 而不是拖死整个消费循环。
                        log.exception("worker item crashed")
                        results = [
                            self._skip(c, f"worker crash: {e}", kind=_kind_of(e))
                            for c in item.affected()
                        ]
                    except BaseException as e:  # 收账转 _drain 重抛
                        log.exception("worker item crashed fatally")
                        fatal.append(e)
                        results = [
                            self._skip(c, f"worker crash: {e}", kind=_kind_of(e))
                            for c in item.affected()
                        ]
                self._collect(results, done_map, fatal)
            finally:
                queue.task_done()

    @staticmethod
    def _ledger_call(
        fatal: list[BaseException],
        r: ChunkResult,
        name: str,
        fn: Callable[[ChunkResult], None],
    ) -> None:
        """账本调用统一双档网。

        普通 ``Exception`` 记 log 续走（绝不外泄）；``BaseException``
        （KI/SE/GE）收 ``fatal`` 账本——逃逸即杀 worker → ``queue.join()``
        死锁（E3），由 ``_drain`` 收敛后重抛。
        """
        try:
            fn(r)
        except Exception:
            log.exception("%s failed for %s", name, r.chunk_id)
        except BaseException as e:
            log.exception("%s crashed fatally for %s", name, r.chunk_id)
            fatal.append(e)

    def _ledger_intercepts(self, fatal: list[BaseException], r: ChunkResult) -> None:
        """升格拦截网注册表的统一账本序列（``_load_resumed`` 与 ``_ledger_outcome`` 共用）。"""
        for net in _INTERCEPT_NETS:
            self._ledger_call(fatal, r, f"{net.name} intercept", _net_apply_fn(net))

    def _ledger_outcome(self, fatal: list[BaseException], r: ChunkResult) -> None:
        """拦截网 + auth 闸 + emit 的账本序列（``_route_chunks`` 与 ``_collect`` 共用；点数随 ``_INTERCEPT_NETS`` 注册表走）。"""
        self._ledger_intercepts(fatal, r)
        self._ledger_call(fatal, r, "auth_gate.record", self.auth_gate.record)
        self._ledger_call(fatal, r, "emit", self._emit)

    def _collect(
        self,
        results: list[ChunkResult],
        done_map: dict[str, ChunkResult],
        fatal: list[BaseException],
    ) -> None:
        """结果入账 + 落盘（worker 与 warmup 共用）。

        state.record/on_result 抛错绝不外泄——worker 一死，队列里剩余 item
        永远等不到 task_done，``queue.join()`` 挂死；warmup 侧则直接炸掉整 run。
        ``BaseException`` 族（KI/SE）同此理：逃逸即杀 worker → join 死锁，
        逐调用收进 ``fatal`` 由 ``_drain`` 收敛后重抛（E3 同族第二注入点）。
        """
        for r in results:
            done_map[r.chunk_id] = r
            self._ledger_outcome(fatal, r)

    async def _drain(
        self,
        work_items: list[WorkItem | tuple[str, Any]],
        done_map: dict[str, ChunkResult],
    ) -> None:
        """首发单飞暖前缀缓存 → N worker 消费 queue（哨兵收尾）。

        入队统一成 ``WorkItem``——存量 tuple 形工作单元在此收口归一，
        下游 ``_process``/``affected()`` 只见命名访问面。
        """
        if not work_items:
            return
        queue: asyncio.Queue[WorkItem | None] = asyncio.Queue()
        for item in work_items:
            queue.put_nowait(item if isinstance(item, WorkItem) else WorkItem(*item))

        # 首发单飞暖前缀缓存，再并发其余（docs/spec/translate.md warmup 模式）
        fatal: list[BaseException] = []
        first = await queue.get()
        if first is not None:
            try:
                results = await self._process(first)
            except Exception as e:  # 与 _worker 同兜底口径
                log.exception("warmup item crashed")
                results = [
                    self._skip(c, f"warmup crash: {e}", kind=_kind_of(e))
                    for c in first.affected()
                ]
            self._collect(results, done_map, fatal)
        queue.task_done()

        for _ in range(self.cfg.concurrency):
            queue.put_nowait(None)
        workers = [
            asyncio.create_task(self._worker(queue, done_map, fatal))
            for _ in range(self.cfg.concurrency)
        ]
        try:
            await queue.join()
        finally:
            # cancel/异常撕开 join 时 worker 仍在飞——不收尸就揣着半开
            # client 游离；cancel + gather 收敛（return_exceptions 防
            # CancelledError 自 gather 再抛一次盖掉原异常链）
            for w in workers:
                if not w.done():
                    w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        if fatal:
            raise fatal[0]

    async def run(self, chunks: list[ChunkIn]) -> list[ChunkResult]:
        """跑完整篇。返回与输入同序的结果表。

        连续 ``cfg.auth_fail_threshold`` 块 auth 类失败（401/403）→ 抛
        ``AuthTrippedError`` 让论文 fault——凭证失效时绝不把整篇静默写成
        fallback 原文（T2：n100 里 401 逐块吞成 skipped→任务假 done）。
        """
        self.auth_gate = AuthGate(self.cfg.auth_fail_threshold)
        # 序章账本：_load_resumed/_route_chunks 的 interceptor/auth_gate/_emit
        # 调用点与 _collect 同款收账——BaseException 在此统一重抛，先于
        # state.start()/队列编排，免得上半段收账下半段无人抛。
        fatal: list[BaseException] = []
        completed, done_map = self._load_resumed(fatal)
        pending, split_items = self._route_chunks(chunks, completed, done_map, fatal)
        if fatal:
            raise fatal[0]

        if self.state is not None:
            self.state.start(len(chunks))
        # 术语表物化吃全量 chunks 而非仅 pending——续跑时已完成块同样参与
        # 文档级过滤，保证 system prompt 与全新跑逐字节一致（缓存命中口径）。
        auto_terms = await self._auto_glossary(chunks, pending)
        self._materialize(list(chunks), auto_terms)

        await self._drain(self._build_work_items(pending, split_items), done_map)

        if self.state is not None:
            self.state.finish()
        if self.auth_gate.tripped:
            msg = (
                f"auth circuit open: {self.auth_gate.consecutive} consecutive "
                "auth failures (401/403) — check credentials"
            )
            raise AuthTrippedError(msg, status=HTTP_UNAUTHORIZED)
        return [done_map[c.chunk_id] for c in chunks]
