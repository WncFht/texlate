"""翻译编排骨架（docs/08 §1.3/§1.6）：asyncio.Queue + N worker + 首发单飞暖缓存。

流程：

    chunks[] → 滤 completed（state 续跑）→ 纯占位符直落盘
             → 超大原子块切分 → 短块贪心装箱（≤2000 字符/批）
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
from typing import TYPE_CHECKING, Any, Protocol

from texlate.textutil import JSON_FENCE_RX, bare_cs_net, ph_in_cs_net

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
from .client import (
    HTTP_FORBIDDEN,
    HTTP_UNAUTHORIZED,
    AuthError,
    ChatClient,
    ChatError,
    ChatOptions,
    LengthTruncatedError,
)
from .retry import RetryPolicy, call_with_backoff, translate_with_ladder
from .state import ChunkRecord, StateStore, segment_key

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.latex.model import Chunk

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
    #: ``{ph_token: 原文 fragment}``——recover_copied_tokens 的判定底账；
    #: 给了才启用阶梯的抄回修复臂（None = 不武装，行为同旧版）。
    ph_fragments: dict[str, str] | None = None


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
    skipped: bool = False
    skip_reason: str = ""
    attempts: int = 0
    warnings: list[str] = field(default_factory=list)
    #: 失败成因分类（打标处在异常现场赋值）："" | auth | provider | crash |
    #: validate——auth 闸计数与 error_code 归一的共同输入。
    error_kind: str = ""


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
            return r.content

        return await call_with_backoff(_go, policy=self.policy)


#: mock 译文固定串（e2e mock_a 同款：散文段 → 固定中文，token 原位不动）
MOCK_ZH = "这是译文"


def _strip_json_fence(raw: str) -> str:
    """剥掉整段 ``` 围栏；非围栏原文原样返回。"""
    m = JSON_FENCE_RX.match(raw)
    return m.group("body") if m else raw


#: token 集 = 占位符 + 控制序列 + 括号 + L0 脆弱字符（``~`` 活动字符、``$``/``&``
#: 结构符——丢了会触发 cs_dropped/数学计数差，mock 与 L0 同口径才构成有效 E2E）
_MOCK_TOKEN_RX = re.compile(
    r"\[\[[A-Z_]+_\d+\]\]|\[\[[A-Z][A-Z_]*\]\]|\\[a-zA-Z@]+\*?|\\(?!\[\[).|[][(){}|~$&]"
)
#: 行内字母 run（mock 译文替换单位；``[^\n]`` 不跨行——保住换行布局）
#: 勘误 2026-09-17（登记不修）：ASCII 盲区——西里尔/希腊文等非 ASCII 散文
#: 原样回显不进译文（scout-triage-2026-09-17 F-echo 1 格，low；
#: ``bench/py/qualbench.py`` 同源副本同盲区）。
_PROSE_RUN_RX = re.compile(r"[a-zA-Z][^\n]*[a-zA-Z]|[a-zA-Z]")
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
    r"""e2e mock_a 同款：token 原位保留，字母散文 run → 固定中文串。

    护栏对齐 L0/C8a 口径：只替换行内字母 run（``\eg, Caffe`` →
    ``\eg, 这是译文``），标点/空白/换行原样——否则 ``\cs``+CJK 熔合成
    未定义控制序列（macro 融合 cs/cs_dropped 是 error 级判据）。
    """
    out: list[str] = []
    pos = 0
    for m in _MOCK_TOKEN_RX.finditer(text):
        out.append(_PROSE_RUN_RX.sub(zh, text[pos : m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_PROSE_RUN_RX.sub(zh, text[pos:]))
    return "".join(out)


# ---------------------------------------------------------------- Pipeline


def _leftover_ph_tokens(src: str, zh: str) -> list[str]:
    """``zh`` 中 ∉ ``src`` 占位符集合的 token（按出现序列，重复保留）。

    splice 按 ph_map 成员解析 ``[[X_n]]``：zh 侧 token 不在 src 集合 → 查无
    实体留字面（reconstruct ``dangling``）；在集合内则每处出现都正常展开——
    故取集合差而非多重集差，合法重复引用与 src 字面 ``[[..]]`` 回显不误伤。
    """
    src_set = set(placeholders.ANY_PH_RX.findall(src))
    return [t for t in placeholders.ANY_PH_RX.findall(zh) if t not in src_set]


def _interceptable(src: str, zh: str) -> bool:
    """升格拦截三网的合并判定——``zh`` 命中任一网即会被 ``_collect`` 降 fault。

    ``_cache_store``/缓存命中路共用此口径：过不了拦截的译文既不入缓存、
    命中旧毒条目也清除重翻。
    """
    return bool(
        _leftover_ph_tokens(src, zh) or ph_in_cs_net(src, zh) or bare_cs_net(src, zh)
    )


def _intercept_leftover_ph(r: ChunkResult) -> None:
    """``leftover_ph`` 升格拦截：zh 带 splice 不可解析 token → fault + 回退原文。

    B7 归因：模型幻觉 ``[[MATH_n]]`` 穿透 ladder/校验留字面，splice 后
    ``[[MATH_966]]`` 进文档是用户可见污染（sabotage 1012.5411 实测）——
    回退英文原文是更体面的降级。命中即落 fallback_orig 同形
    （``fault`` + ``skipped`` + ``translation=source``）：不再 splice、
    续跑重试、落库 ``failed`` → 论文级 ``partial`` 而非静默 ok。
    ``attempts>0`` 才记 ``error_kind=validate``——缓存命中没发请求，
    不充当 auth 闸的非-auth 证据。warning 仍落 ``leftover_ph:N`` 供计量。
    只扫 ok/partial——skipped/fault 的 translation 已是 source。
    """
    if r.skipped or r.status not in ("ok", "partial"):
        return
    leftover = _leftover_ph_tokens(r.source, r.translation)
    if not leftover:
        return
    r.warnings.append(f"leftover_ph:{len(leftover)}")
    r.status = "fault"
    r.skipped = True
    r.translation = r.source
    shown = ", ".join(sorted(set(leftover))[:8])
    r.skip_reason = f"leftover placeholder(s) unresolvable in splice: {shown}"
    if r.attempts > 0:
        r.error_kind = r.error_kind or "validate"


def _intercept_ph_in_cs(r: ChunkResult) -> None:
    r"""``ph_in_cs`` 升格拦截：zh 把占位符嵌进 cs 名中段 → fault + 回退原文。

    ``_intercept_leftover_ph`` 同构副层——续跑 state/段级缓存命中旁路
    validator，此层是拦 stale 脏译的唯一闸（l0 ``_check_ph_in_cs`` 的
    缓存旁路姊妹，判定口径 = ``textutil.ph_in_cs_net`` 逐字节一致）。
    splice ``expand`` 逐字节替换后 ``\\fo[[PH]]o`` → ``\\fo<payload>o``
    断名成未定义 cs 且载荷不可复原（scout-spliceguard 14/14 实证）。
    命中落 fallback_orig 同形；``attempts>0`` 才记 ``error_kind=validate``。
    """
    if r.skipped or r.status not in ("ok", "partial"):
        return
    extra = ph_in_cs_net(r.source, r.translation)
    if not extra:
        return
    n = sum(extra.values())
    r.warnings.append(f"ph_in_cs:{n}")
    r.status = "fault"
    r.skipped = True
    r.translation = r.source
    shown = ", ".join(sorted(extra)[:8])
    r.skip_reason = f"placeholder fused into cs name x{n}: {shown}"
    if r.attempts > 0:
        r.error_kind = r.error_kind or "validate"


def _intercept_bare_cs(r: ChunkResult) -> None:
    r"""``bare_cs`` 升格拦截：zh 文本域新增裸 cs → fault + 回退原文。

    ``_intercept_ph_in_cs`` 同构副层——判定口径 = ``textutil.bare_cs_net``
    （与 l0 ``_check_bare_cs`` 逐字节一致），缓存/续跑旁路 validator
    时此层是唯一闸。两类编译炸弹：数学域外 ``MATH_CS`` 表名
    （``\alpha 发射体`` → ``Missing $``，realpostfix2 0905.4907 实证）
    与粘合 cs（``\itemOC``/``\csnamebibitemNoStop`` → undefined cs）。
    命中落 fallback_orig 同形；``attempts>0`` 才记 ``error_kind=validate``。
    """
    if r.skipped or r.status not in ("ok", "partial"):
        return
    extra = bare_cs_net(r.source, r.translation)
    if not extra:
        return
    n = sum(extra.values())
    r.warnings.append(f"bare_cs:{n}")
    r.status = "fault"
    r.skipped = True
    r.translation = r.source
    shown = ", ".join(sorted(extra)[:8])
    r.skip_reason = f"bare cs injected x{n}: {shown}"
    if r.attempts > 0:
        r.error_kind = r.error_kind or "validate"


def _is_auth_error(e: BaseException) -> bool:
    """Auth 类失败判定：401/403（AuthError 或裸 status 命中）。"""
    return isinstance(e, AuthError) or (
        isinstance(e, ChatError) and e.status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN)
    )


def _kind_of(e: BaseException) -> str:
    """异常 → ``ChunkResult.error_kind``：auth | provider | crash。"""
    if isinstance(e, ChatError):
        return "auth" if _is_auth_error(e) else "provider"
    return "crash"


class AuthTrippedError(AuthError):
    """连续 auth-fail 熔断信号（T2）：``run()`` 抛出 = 论文 fault。

    继承 ``AuthError``——调用方既有的 ``except AuthError`` 归类
    （worker → ``provider_auth``）对它天然生效。
    """


@dataclass
class AuthGate:
    """连续 auth-fail 计数闸（一个 ``run()`` 一扇，``run`` 开头重置）。

    - ``consecutive``：当前连续 auth-fail 块数。
    - ``tripped``：``consecutive`` 达到 ``threshold`` 闩锁——run 收尾抛
      ``AuthTrippedError``。
    - ``auth_failures``/``non_auth``：本 run 累计——``all_failed`` 属性是
      「整篇全 auth 败」判定，跨论文熔断（连续 N 篇）由调用方据此自行累计。
    """

    threshold: int = 3
    consecutive: int = 0
    auth_failures: int = 0
    non_auth: int = 0
    tripped: bool = False

    def record(self, r: ChunkResult) -> None:
        """逐结果入账：auth 类累计；真发过请求的非-auth 结果清零连续计数。

        ``attempts==0`` 且无 error_kind 的 ok（缓存命中等）不置证——
        没发请求，对 auth 死活既不清零也不计 ``non_auth`` 分母。
        """
        if r.error_kind == "auth":
            self.consecutive += 1
            self.auth_failures += 1
            if 0 < self.threshold <= self.consecutive:
                self.tripped = True
        elif r.attempts > 0 or r.error_kind:
            self.consecutive = 0
            self.non_auth += 1

    @property
    def all_failed(self) -> bool:
        """本 run 是否「全 auth 败」——已熔断，或有 auth-fail 且零成功请求。"""
        return self.tripped or (self.auth_failures > 0 and self.non_auth == 0)


def _item_chunks(item: tuple[str, Any]) -> list[ChunkIn]:
    """工作单元 → 受影响 ChunkIn（worker crash 兜底记账用）。"""
    kind, payload = item
    if kind == "batch":
        return list(payload[1])
    if kind == "split":
        return [payload[0]]
    return [payload]


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
    #: 连续 auth-fail 块数熔断阈值（T2；≤0 = 不熔断）
    auth_fail_threshold: int = 3

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
        #: auth 熔断闸（``run()`` 每次开头重置；跨论文熔断靠调用方读它累计）
        self.auth_gate = AuthGate(self.cfg.auth_fail_threshold)
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
        # 同实例二次 run 换了文档 → 术语块变了，prompt memo 必须失效重渲染
        self._prompts.clear()

    def _seg_key(self, c: ChunkIn) -> str:
        """段级缓存键：source + role + masked 快照（占位符布局变则 key 变）。"""
        ph_types = [
            p.strip("[]").rpartition("_")[0] or p.strip("[]")
            for p in placeholders.ANY_PH_RX.findall(c.content)
        ]
        return segment_key(c.content, c.kind, masked_snapshot=repr(ph_types))

    def _cache_store(self, c: ChunkIn, zh: str) -> None:
        """段级缓存写入；过不了升格拦截三网的译文不入缓存——防毒化续跑。

        缓存命中旁路校验：同一份污染译文若落缓存，每轮续跑反复命中、永远修不正。
        判定口径 = ``_collect`` 三条 intercept（leftover_ph/ph_in_cs/bare_cs）。
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
                data = json.loads(_strip_json_fence(raw))
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
            repair_fn=self._repair_fn(c),
        )
        status = (
            "ok"
            if res.status == "ok"
            else "partial"
            if res.status == "recovered"
            else "fault"
        )
        if res.status in ("ok", "recovered"):
            self._cache_store(c, res.translation)
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
                user=f"{c.content}\n\n[compile_error]\n{compile_feedback}",
                temperature=self.cfg.temperature,
                max_tokens=self.cfg.max_tokens,
            )
        except Exception as e:  # noqa: BLE001 -- 传输崩=保留原译，不算一次有效修复
            log.debug("retranslate %s transport failed: %s", c.chunk_id, e)
            return None
        zh = placeholders.decode_newlines(raw)
        repair = self._repair_fn(c)
        warnings: list[str] = []
        if repair is not None:
            zh, recovered = repair(c.content, zh)
            if recovered:
                warnings.append(
                    f"recovered copied placeholders: {', '.join(recovered)}"
                )
        err = self.validator(c.content, zh)
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
        _intercept_leftover_ph(r)  # L2 回灌同受拦截——fault 由调用方回落原文
        _intercept_ph_in_cs(r)
        _intercept_bare_cs(r)
        return r

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
                return [
                    self._skip(c, str(e), batch_id, kind=_kind_of(e)) for c in members
                ]
            log.debug("batch %s call failed (%s) → degrade to singles", batch_id, e)
        except Exception as e:  # noqa: BLE001 -- 批量调用崩→退单翻，绝不丢成员
            log.debug("batch %s crashed (%s) → degrade to singles", batch_id, e)

        parts = parse_batch_response(raw, len(members)) if raw is not None else None
        if parts is None:
            return [await self._degrade_one(c, batch_id) for c in members]

        out: list[ChunkResult] = []
        for c, part in zip(members, parts, strict=True):
            zh = placeholders.decode_newlines(part)
            warnings: list[str] = []
            repair = self._repair_fn(c)
            if repair is not None:
                zh, recovered = repair(c.content, zh)
                if recovered:
                    warnings.append(
                        f"recovered copied placeholders: {', '.join(recovered)}"
                    )
            err = self.validator(c.content, zh)
            if err:
                # 批成功但该块校验败 → 单块回炉走完整阶梯
                out.append(await self._degrade_one(c, batch_id))
                continue
            self._cache_store(c, zh)
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
                    warnings=warnings,
                )
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
        """失败回退原文——不阻塞整批（docs/08 §1.6）。``kind`` 记失败成因。"""
        return ChunkResult(
            chunk_id=c.chunk_id,
            source=c.content,
            translation=c.content,
            kind=c.kind,
            status="skipped",
            batch_id=batch_id,
            skipped=True,
            skip_reason=reason,
            error_kind=kind,
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
                    error_kind=r.error_kind,
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
                return [
                    self._skip(c, f"batch crash: {e}", bid, kind=_kind_of(e))
                    for c in members
                ]
        if kind == "split":
            parent, pieces = payload
            translations: list[str] = []
            warnings: list[str] = []
            kinds: list[str] = []
            worst = "ok"
            for piece in pieces:
                try:
                    r = await self._one_chunk(piece)
                except Exception as e:  # noqa: BLE001 -- 片段崩不拖全块
                    r = self._skip(piece, f"split piece crash: {e}", kind=_kind_of(e))
                translations.append(r.translation)
                warnings += r.warnings
                kinds.append(r.error_kind)
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
                    error_kind=(
                        "auth" if "auth" in kinds else next((k for k in kinds if k), "")
                    ),
                )
            ]
        c = payload
        try:
            return [await self._one_chunk(c)]
        except Exception as e:  # noqa: BLE001 -- 同上
            return [self._skip(c, f"chunk crash: {e}", kind=_kind_of(e))]

    def _load_resumed(self) -> tuple[set[str], dict[str, ChunkResult]]:
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
            res = ChunkResult(
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
                warnings=[*rec.warnings],
                error_kind=rec.error_kind,
            )
            # warning 时代落盘的 ok 残留（zh 带源外占位符）→ 就地降 fault，
            # 不进 completed → 本轮重翻自愈；否则旧档会把字面 [[X_n]] 带进 splice。
            _intercept_leftover_ph(res)
            _intercept_ph_in_cs(res)
            _intercept_bare_cs(res)
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
    ) -> tuple[list[ChunkIn], list[tuple[str, Any]]]:
        """路由输入块 → (pending, split_items)。

        completed 直跳过；纯占位符直落盘；超 hard_limit 的原子块切成 split
        工作单元（译文按父 id 合并记账，state/续跑只见父 id）。
        """
        pending: list[ChunkIn] = []
        split_items: list[tuple[str, Any]] = []
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
                r = ChunkResult(
                    chunk_id=cid,
                    source=c.content,
                    translation=c.content,
                    kind=c.kind,
                    status="ok",
                )
                done_map[cid] = r
                _intercept_leftover_ph(r)  # 升格语义下保持与 _collect 同构的后处理
                _intercept_ph_in_cs(r)
                _intercept_bare_cs(r)
                self.auth_gate.record(r)
                try:
                    self._emit(r)
                except Exception:
                    log.exception("emit failed for %s", r.chunk_id)
                continue
            pieces = split_long_chunk(c.content, max_chars=self.cfg.hard_limit)
            if len(pieces) > 1:
                subs = [
                    ChunkIn(f"{cid}~{i}", p, c.kind, ph_fragments=c.ph_fragments)
                    for i, p in enumerate(pieces)
                ]
                split_items.append(("split", (c, subs)))
            else:
                pending.append(c)
        return pending, split_items

    def _build_work_items(
        self,
        pending: list[ChunkIn],
        split_items: list[tuple[str, Any]],
    ) -> list[tuple[str, Any]]:
        """分桶 + 装箱：`("batch",(序号,[ChunkIn])) | ("single",ChunkIn) | split`。

        batch 按 kind 分组再装箱——一批共用 ``members[0].kind`` 的 system
        prompt，混 kind 会让 caption/abstract 等专属条款错配到 para 头上。
        """
        short = [c for c in pending if len(c.content) < self.cfg.short_limit]
        longs = [c for c in pending if len(c.content) >= self.cfg.short_limit]
        by_kind: dict[str, list[ChunkIn]] = {}
        for c in short:
            by_kind.setdefault(c.kind, []).append(c)
        work_items: list[tuple[str, Any]] = []
        seq = 0
        for grp_chunks in by_kind.values():  # dict 保 insertion 序——批次确定性
            for grp in pack_batches(
                [c.content for c in grp_chunks],
                max_chars=self.cfg.batch_max_chars,
            ):
                work_items.append(("batch", (seq, [grp_chunks[j] for j in grp])))
                seq += 1
        work_items += [("single", c) for c in longs]
        return work_items + split_items

    async def _worker(
        self,
        queue: asyncio.Queue[tuple[str, Any] | None],
        done_map: dict[str, ChunkResult],
    ) -> None:
        """消费循环：哨兵退出；item 级 crash 兜底成 skipped。

        worker 不死——否则 queue.join() 死等 + done_map 缺口在 run() 末行
        炸 KeyError。
        """
        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                if self.auth_gate.tripped:
                    # auth 闸已断：剩余块不再发请求，直接按 auth 失败记账
                    results = [
                        self._skip(c, "auth circuit open", kind="auth")
                        for c in _item_chunks(item)
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
                            for c in _item_chunks(item)
                        ]
                self._collect(results, done_map)
            finally:
                queue.task_done()

    def _collect(
        self,
        results: list[ChunkResult],
        done_map: dict[str, ChunkResult],
    ) -> None:
        """结果入账 + 落盘（worker 与 warmup 共用）。

        state.record/on_result 抛错绝不外泄——worker 一死，队列里剩余 item
        永远等不到 task_done，``queue.join()`` 挂死；warmup 侧则直接炸掉整 run。
        """
        for r in results:
            done_map[r.chunk_id] = r
            _intercept_leftover_ph(r)
            _intercept_ph_in_cs(r)
            _intercept_bare_cs(r)
            self.auth_gate.record(r)
            try:
                self._emit(r)
            except Exception:
                log.exception("emit failed for %s", r.chunk_id)

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

        # 首发单飞暖前缀缓存，再并发其余（docs/08 §1.6 warmup 模式）
        first = await queue.get()
        if first is not None:
            try:
                results = await self._process(first)
            except Exception as e:  # 与 _worker 同兜底口径
                log.exception("warmup item crashed")
                results = [
                    self._skip(c, f"warmup crash: {e}", kind=_kind_of(e))
                    for c in _item_chunks(first)
                ]
            self._collect(results, done_map)
        queue.task_done()

        for _ in range(self.cfg.concurrency):
            queue.put_nowait(None)
        workers = [
            asyncio.create_task(self._worker(queue, done_map))
            for _ in range(self.cfg.concurrency)
        ]
        await queue.join()
        await asyncio.gather(*workers)

    async def run(self, chunks: list[ChunkIn]) -> list[ChunkResult]:
        """跑完整篇。返回与输入同序的结果表。

        连续 ``cfg.auth_fail_threshold`` 块 auth 类失败（401/403）→ 抛
        ``AuthTrippedError`` 让论文 fault——凭证失效时绝不把整篇静默写成
        fallback 原文（T2：n100 里 401 逐块吞成 skipped→任务假 done）。
        """
        self.auth_gate = AuthGate(self.cfg.auth_fail_threshold)
        completed, done_map = self._load_resumed()
        pending, split_items = self._route_chunks(chunks, completed, done_map)

        if self.state is not None:
            self.state.start(len(chunks))
        # 术语表物化吃全量 chunks 而非仅 pending——续跑时已完成块同样参与
        # 文档级过滤，保证 system prompt 与全新跑逐字节一致（缓存命中口径）。
        self._materialize(list(chunks))

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
