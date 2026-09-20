r"""重试：HTTP 指数退避 + 四段语义阶梯（docs/spec/translate.md 定案参数）。

两层分开：

1. `call_with_backoff` —— HTTP 层。`retry_delay·2^attempt`；429/rate-limit 用
   `3^attempt` 下限 5s；timeout 下限 10s；`Retry-After` 从其值；`retryable=False`
   的错误（401/403/402/404/余 4xx）立即抛出。

2. `translate_with_ladder` —— 语义阶梯（照抄 docs/08:113）：
   整段×2（字段化反馈）→ 行级修复（闭合 scope 边界按句号切）→
   slots JSON 兜底（`⟪S0000⟫` 槽位、`response_format json_object`、8 槽/批、
   失败槽只重问失败批）→ 三振 `fallback_orig` + warning → `partial` 终态。

   B4a 实测修订：`response_format` 在 3003 网关被静默忽略（三变体输出全同
   全 200）——它只是 prompt 增强，真正的槽位约束是 `_valid_slot_text`
   校验 + 失败槽重问；429 的 retry_after 在响应 body `error.retry_after`
   （client 层已解析进 `ChatError.retry_after`）。

阶梯只编排不实现——`translate_fn`/`validate_fn`/`slots_fn` 由 pipeline 注入
（真网关走 client+prompts，mock 走 MockTranslator，测试走 fake）。
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .batch import abbrev_cut, split_long_chunk
from .client import HTTP_TOO_MANY_REQUESTS, ChatError
from .placeholders import (
    ANY_PH_RX,
    MEDSP,
    NBSP,
    NEGSP,
    PARA_NEWLINE,
    SOFT_NEWLINE,
    SOFT_SPACE,
    THICKSP,
    THINSP,
    decode_newlines,
    diff,
    encode_newlines,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

log = logging.getLogger(__name__)

#: 槽位 token 形态（`⟪S0000⟫`）
SLOT_PREFIX = "⟪S"
SLOT_SUFFIX = "⟫"
SLOT_NAME_RX = re.compile(r"⟪S\d{4,}⟫")
#: 槽/占位符 token 的括号字符集——``_valid_slot_text`` 按字符出现拒收，
#: 罩住规范形与非规范残码（texglot 同款过滤的超集）。
_SLOT_PH_BRACKETS = ("⟪", "⟫", "[[", "]]")
#: 槽值"非空"判定的零宽字符集——``str.strip()``/``isspace`` 不吃
#: ``\u200b`` ZWSP/``\ufeff`` BOM 系，零宽-only 应答会判非空放行，
#: 该槽正文静默丢进装配译文（含 ZWNJ/ZWJ/WJ/SHY/MVS）。
_SLOT_ZW_CHARS = "\u200b\u200c\u200d\ufeff\u2060\u00ad\u180e"
#: 象形括号邻 ``S\d{4,}`` 的槽 token 形变回显（``⟦S0000⟧``/``《S0000》``/
#: ``「S0000」``/``［S0000］``/``⟨S0000⟩``/``｟S0000｠``/``【S0000】`` 系，
#: 含半边形态）——这些括号本身是合法中文标点（``［1］`` 引用号不误伤：
#: 无 ``S`` 前缀、不足四位数），括号贴 ``S``+四位数只会是 ``⟪S0000⟫``
#: 的形变；``diff`` 看不见这类残码，须在槽值入口拒。
_SLOT_ECHO_RX = re.compile(
    r"[⟦⟨｟《「［【]\s*[Ss]\d{4,}\s*[⟧⟩｠》」］】]"
    r"|[⟦⟨｟《「［【]\s*[Ss]\d{4,}"
    r"|[Ss]\d{4,}\s*[⟧⟩｠》」］】]"
)
#: 每批槽位数（docs/08:113）
SLOTS_PER_BATCH = 8
#: slots 模式单槽最大字符（过长槽按 batch.split_long_chunk 句界二分）
SLOT_MAX_CHARS = 1500
#: slots 阶段轮数：首轮 + 失败槽重问一轮
SLOTS_MAX_ROUNDS = 2


# ---------------------------------------------------------------- HTTP 退避


@dataclass
class RetryPolicy:
    """HTTP 层退避参数（docs/spec/translate.md：3~5 试、429 ³ 阶、timeout 下限 10s）。"""

    max_tries: int = 5
    base_delay: float = 1.0
    rate_limit_floor: float = 5.0
    timeout_floor: float = 10.0


def _backoff_delay(e: BaseException, attempt: int, p: RetryPolicy) -> float | None:
    """本次失败应睡多久；`None` = 不重试（non-retryable 或已是最后一试）。

    ``ChatError.max_tries`` 收窄该错误自己的总尝试数（EmptyContentError
    只翻身一次——连续空响应不是瞬时抖动，不值得烧满 policy 上限）。
    """
    limit = p.max_tries
    if isinstance(e, ChatError) and e.max_tries is not None:
        limit = min(limit, e.max_tries)
    if attempt >= limit - 1:
        return None
    delay: float | None = None
    if isinstance(e, ChatError):
        if e.retryable:
            if e.retry_after is not None:
                delay = e.retry_after
            elif e.status == HTTP_TOO_MANY_REQUESTS:
                delay = max(p.rate_limit_floor, p.base_delay * (3**attempt))
            elif (
                e.status < 0
                or "timeout" in str(e).lower()
                or "timed out" in str(e).lower()
            ):
                delay = max(p.timeout_floor, p.base_delay * (2**attempt))
            else:
                delay = p.base_delay * (2**attempt)
    else:
        # 裸 TimeoutError 等传输层错误
        delay = max(p.timeout_floor, p.base_delay * (2**attempt))
    return delay


async def call_with_backoff[T](
    fn: Callable[[], Awaitable[T]],
    *,
    policy: RetryPolicy | None = None,
    on_retry: Callable[[int, BaseException, float], None] | None = None,
) -> T:
    """指数退避调用。`ChatError.retryable=False` 的错误立即抛。

    延迟：`base·2^attempt`；429 → `base·3^attempt` 且 ≥`rate_limit_floor`；
    timeout → ≥`timeout_floor`；`Retry-After` 头从其值（>60s 已在 client 层拒掉）。
    """
    p = policy or RetryPolicy()
    if p.max_tries < 1:
        msg = f"call_with_backoff: max_tries={p.max_tries} < 1"
        raise ValueError(msg)
    last: BaseException | None = None
    for attempt in range(p.max_tries):
        try:
            return await fn()
        except (ChatError, TimeoutError) as e:
            last = e
            delay = _backoff_delay(e, attempt, p)
            if delay is None:
                if isinstance(e, TimeoutError) and not isinstance(e, ChatError):
                    msg = f"timeout after {attempt + 1} tries"
                    raise ChatError(msg) from e
                raise
            if on_retry:
                on_retry(attempt, e, delay)
            await asyncio.sleep(delay)
    if last is not None:
        raise last
    msg = "call_with_backoff: unreachable"
    raise ChatError(msg)


# ---------------------------------------------------------------- 语义阶梯


@dataclass
class LadderResult:
    """阶梯产物。`status`: ok | recovered | fallback_orig。"""

    translation: str
    status: str  # "ok" | "recovered" | "fallback_orig"
    stage: str  # "whole" | "lines" | "slots" | "fallback"
    attempts: int = 0
    warnings: list[str] = field(default_factory=list)


def _validate(src: str, zh: str) -> str:
    """默认校验 = 占位符对账（L0 全量规则由 pipeline 的 validator 参数接入）。"""
    return diff(src, zh).describe()


#: 换行/脆弱空白八族 token——``decode_newlines`` 把它们还原成非 token 字符
#: （``\n``/``\n\n``/``\ ``/``~``/``\,``/``\:``/``\;``/``\!``），post-decode
#: 的 ``diff``/拦截网对它们全盲：模型凭空铸 token（``[[NEGSP]]``→``\!`` 落进
#: 文本域是数学模式专属命令、编译炸弹）或丢 token（``[[SL]]`` 丢→吞换行）都
#: 是静默注入/丢失，只能前置到 decode 前按「模型所见输入 vs 原始应答」逐族
#: 对账。哨兵族 ``[[__TEXLATE_*_LIT*__]]`` 对 ANY_PH_RX 对称不可见故不计；
#: ``*_RAW`` 族 decode 后仍是 token 形，归 leftover/diff 网管辖。
_DECODE_FAM_TOKENS: tuple[str, ...] = (
    SOFT_NEWLINE,
    PARA_NEWLINE,
    SOFT_SPACE,
    NBSP,
    THINSP,
    MEDSP,
    THICKSP,
    NEGSP,
)


def bare_token_audit(shown_src: str, zh_raw: str) -> str:
    """Decode 前对账：``shown_src`` 与生应答 ``zh_raw`` 的八族 token 多重集须逐族相等。

    ``shown_src`` 取各调用点实际发给模型的文本形态——ladder 整段/行级是
    ``encode_newlines`` 产物，corrector/retranslate 是未编码原文（模型所见
    不同，期望多重集随之不同）。返回违规描述（``""``=通过），走各路径现成
    的校验失败通道消化（阶梯重试/批退单翻/fault 回退）。
    """
    bad = [
        f"{tok}(in={shown_src.count(tok)},out={zh_raw.count(tok)})"
        for tok in _DECODE_FAM_TOKENS
        if shown_src.count(tok) != zh_raw.count(tok)
    ]
    if not bad:
        return ""
    return "structural token multiset mismatch: " + ", ".join(bad)


#: 模型输出退化坍缩签名：20+ 连排句读标点 → 坍成单 ``.``（BabelDOC
#: ``il_translator_llm_only.py`` :754 同款清理；合法 LaTeX 源不产 20+
#: 连排点——TOC 点线是编译期生成，源文本无此形态）。
_PUNCT_RUN_RX = re.compile(r"[.。…，]{20,}")


def assess_answer(
    src: str,
    zh: str,
    *,
    audit_err: str = "",
    repair_fn: Callable[[str, str], tuple[str, list[str]]] | None,
    validate_fn: Callable[[str, str], str],
) -> tuple[str, str, list[str]]:
    """Decode 后统一后评：坍缩标点清理 → 占位符抄回修复 → ``audit_err or validate``。

    ``zh`` 取各调用点 decode 产物（``decode_newlines``/槽位装配/行拼合——形态
    各异故 decode 留调用方）；``audit_err`` 是 decode 前 ``bare_token_audit``
    的对账结果（无该闸的路径省略）。返回 ``(zh, err, warnings)``——``err``
    空串即通过；``warnings``（修复抄回记录）只在调用方采纳该件时并入账本，
    被拒件不留 "recovered" 伪报（取代 ``_LadderCtx.repair`` 的无条件落账）。
    """
    zh = _PUNCT_RUN_RX.sub(".", zh)
    warnings: list[str] = []
    if repair_fn is not None:
        zh, recovered = repair_fn(src, zh)
        if recovered:
            warnings.append(f"recovered copied placeholders: {', '.join(recovered)}")
    return zh, audit_err or validate_fn(src, zh), warnings


def sentence_ends(text: str, stop: int | None = None) -> Iterator[int]:
    r"""闭合-scope 句号切点逐枚产出：depth==0 的 ``.!?`` 后随空白处的 ``i+1`` 位。

    ``\\`` 转义双跳 + ``{}`` 深度跟踪 + ``abbrev_cut`` 缩写位豁免——
    ``batch._best_split`` 同款扫描规则的单源实现（升 batch.py 后两处共享）；
    ``stop`` 限扫描窗（_best_split 只在 limit 内取切）。切位语义归消费方：
    行级切分吸收后续空白入前片，best_split 记窗内最右切点。
    """
    depth = 0
    i, n = 0, len(text) if stop is None else min(len(text), stop)
    while i < n:
        c = text[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        elif (
            c in ".!?"
            and depth == 0
            and i + 1 < n
            and text[i + 1] in " \n"
            and not abbrev_cut(text, i)
        ):
            yield i + 1
        i += 1


def _split_lines_scoped(text: str) -> list[str]:
    """闭合 scope 边界按句号切（`{}` 深度 0 的 `.!?`+空白 处断）——行级修复切分。"""
    parts: list[str] = []
    start, n = 0, len(text)
    for cut in sentence_ends(text):
        j = cut
        while j < n and text[j] in " \n":
            j += 1
        parts.append(text[start:j])
        start = j
    if start < n:
        tail = text[start:]
        if parts and not tail.strip():
            # 纯空白尾片（`\t`/`\xa0` 等非分隔空白）并入前片——独立成项过不了
            # 非空判定会被过滤，`join(parts)` 丢尾部字节
            parts[-1] += tail
        else:
            parts.append(tail)
    return parts or [text]


def _make_slots(encoded: str) -> tuple[dict[str, str], list[tuple[str, str]]]:
    """把（已换行编码的）文本切成散文槽位 + 占位符/raw 交错序列。

    返回 ({sid: 散文原文}, seq)；seq = [("slot"|"ph"|"raw", payload), ...]。
    空散文段不产生槽位（相邻占位符直接相连），纯空白段以 raw 保留。
    超 ``SLOT_MAX_CHARS`` 的散文段按句界二分成连续槽位（seq 相邻
    ``slot`` 项重组时顺序拼接，接缝处由源文自带空白隔开）。
    """
    seq: list[tuple[str, str]] = []
    slots: dict[str, str] = {}

    def emit_prose(seg: str) -> None:
        for piece in split_long_chunk(seg, max_chars=SLOT_MAX_CHARS):
            if not piece.strip():
                # 散文段内 >SLOT_MAX_CHARS 空白 run 被二分出的整片——按 raw
                # 记账保 seq 平铺编码文，丢弃则装配译文静默丢字节
                seq.append(("raw", piece))
                continue
            sid = f"{SLOT_PREFIX}{len(slots):04d}{SLOT_SUFFIX}"
            slots[sid] = piece
            seq.append(("slot", sid))

    pos = 0
    for m in ANY_PH_RX.finditer(encoded):
        seg = encoded[pos : m.start()]
        if seg.strip():
            emit_prose(seg)
        elif seg:
            seq.append(("raw", seg))
        seq.append(("ph", m.group(0)))
        pos = m.end()
    tail = encoded[pos:]
    if tail.strip():
        emit_prose(tail)
    elif tail:
        seq.append(("raw", tail))
    return slots, seq


def _valid_slot_text(v: object) -> bool:
    """槽译文合法性：非空字符串、无槽位/占位符 token 形态（含非规范变体）。

    规范槽位是 ``⟪S0000⟫``、占位符是 ``[[X]]`` 系；模型回显的残码不限
    规范形（``⟪S1⟫``/``⟪s0000⟫``/未闭合半边/``[[math_1]]`` 小写态），
    括号字符 ``⟪⟫[[ ]]`` 任一出现即拒——畸形 token 放行会原文进装配译文。
    象形括号 ``⟦⟧《》`` 系贴 ``S``+四位数的形变回显同拒（``_SLOT_ECHO_RX``）；
    "非空"按可见字符计——零宽字符（``_SLOT_ZW_CHARS``）不算内容。
    """
    return (
        isinstance(v, str)
        and any(not c.isspace() and c not in _SLOT_ZW_CHARS for c in v)
        and not any(m in v for m in _SLOT_PH_BRACKETS)
        and _SLOT_ECHO_RX.search(v) is None
    )


@dataclass
class _LadderCtx:
    """阶梯运行态——attempts/warnings/best_zh 跨阶段共享。"""

    source: str
    encoded: str
    translate_fn: Callable[[str, str], Awaitable[str]]
    slots_fn: Callable[[dict[str, str], str], Awaitable[dict[str, str]]]
    validate_fn: Callable[[str, str], str]
    corrector_fn: Callable[[str, str, str], Awaitable[str]] | None
    repair_fn: Callable[[str, str], tuple[str, list[str]]] | None = None
    attempts: int = 0
    warnings: list[str] = field(default_factory=list)
    best_zh: str = ""

    async def call(self, src_text: str, feedback: str = "") -> str:
        """计数的 translate_fn 调用。"""
        self.attempts += 1
        return await self.translate_fn(src_text, feedback)


async def _stage_whole(ctx: _LadderCtx) -> str | None:
    """Stage 1：整段×2（第二试 corrector 三段式或字段化反馈）。通过返回译文。"""
    raw = await ctx.call(ctx.encoded)
    zh, err, w = assess_answer(
        ctx.source,
        decode_newlines(raw),
        audit_err=bare_token_audit(ctx.encoded, raw),
        repair_fn=ctx.repair_fn,
        validate_fn=ctx.validate_fn,
    )
    if not err:
        ctx.warnings.extend(w)
        return zh
    if ctx.corrector_fn is not None:
        ctx.attempts += 1
        raw2 = await ctx.corrector_fn(ctx.source, zh, err)
        # corrector 收未编码原文（三段式 [Original] 段）——期望基线随之是原文
        shown2 = ctx.source
    else:
        raw2 = await ctx.call(ctx.encoded, err)
        shown2 = ctx.encoded
    zh2, err2, w2 = assess_answer(
        ctx.source,
        decode_newlines(raw2),
        audit_err=bare_token_audit(shown2, raw2),
        repair_fn=ctx.repair_fn,
        validate_fn=ctx.validate_fn,
    )
    if not err2:
        ctx.warnings.extend(w2)
        return zh2
    ctx.warnings.append(f"whole×2 failed: {err2}")
    ctx.best_zh = zh2  # 行级修复以较新一版为参照（装配仍走槽位原文）
    return None


async def _stage_lines(ctx: _LadderCtx) -> str | None:
    """Stage 2：闭合 scope 边界按句号切，逐行重翻后整段对账。"""
    lines = _split_lines_scoped(ctx.encoded)
    if len(lines) <= 1:
        return None
    fixed: list[str] = []
    bad_lines = 0
    for line in lines:
        src_l = decode_newlines(line)
        raw_l = await ctx.call(line)
        audit = bare_token_audit(line, raw_l)
        if audit:
            # 锻造/丢 token 的行应答其 decode 产物不可信——带 audit err 作
            # feedback 重试一次（``[[SP]]`` 族锻造是瞬时幻觉高发签名，
            # seq-49/51 实证 +1 调用比升 slots 便宜且更可能整段救回）
            raw_l = await ctx.call(line, audit)
            audit = bare_token_audit(line, raw_l)
        if audit:
            # 重试仍锻造——该行回退原文进装配，不让 ``\!``/``\:`` 等字面
            # 混进 candidate（行级修复本就 best-effort；装配体残英由
            # residual_en 网兜底拒收升 slots，不再静默出货）
            bad_lines += 1
            fixed.append(src_l)
            continue
        zh_l, err_l, w_l = assess_answer(
            src_l,
            decode_newlines(raw_l),
            repair_fn=ctx.repair_fn,
            validate_fn=ctx.validate_fn,
        )
        if err_l:
            raw_l = await ctx.call(line, err_l)
            if not bare_token_audit(line, raw_l):
                zh2_l, err2_l, w2_l = assess_answer(
                    src_l,
                    decode_newlines(raw_l),
                    repair_fn=ctx.repair_fn,
                    validate_fn=ctx.validate_fn,
                )
                if not err2_l:
                    zh_l, w_l = zh2_l, w2_l
                    err_l = ""
        if err_l:
            bad_lines += 1
        # zh_l 恒入 fixed（败北行作 best-effort 成员装配）——只挂最终入列件
        # 的修复告警，被 zh2_l 顶掉的首版不留 "recovered" 伪报
        ctx.warnings.extend(w_l)
        fixed.append(zh_l)
    candidate, err, w_c = assess_answer(
        ctx.source,
        "\n".join(fixed),
        repair_fn=ctx.repair_fn,
        validate_fn=ctx.validate_fn,
    )
    if err:
        ctx.warnings.append(f"lines failed: {err}")
        ctx.best_zh = candidate
        return None
    ctx.warnings.extend(w_c)
    ctx.warnings.append(f"line-level repair rescued ({bad_lines} bad lines)")
    return candidate


async def _slots_round(
    ctx: _LadderCtx,
    pending: dict[str, str],
    translated: dict[str, str],
    failures: dict[str, str],
) -> None:
    """一轮槽位请求：8 槽/批、批内失败槽留 pending 进下一轮。"""
    keys = list(pending)
    for i in range(0, len(keys), SLOTS_PER_BATCH):
        group = {k: pending[k] for k in keys[i : i + SLOTS_PER_BATCH]}
        # 结算按发送时键快照迭代——slots_fn 收同一 dict，回调原地 clear/pop
        # 会丢弃自己的有效应答并把"框架丢答"误记成 "no answer"
        group_sids = list(group)
        ctx.attempts += 1
        feedback = json.dumps(failures, ensure_ascii=False) if failures else ""
        try:
            got = await ctx.slots_fn(group, feedback)
        except ChatError:
            raise  # 认证/余额/连续 HTTP 失败——真错误直接上抛不兜底
        except Exception as e:  # noqa: BLE001 -- 槽位调用崩→该批留 pending 重问
            log.debug("slots batch failed: %s", e)
            continue
        for sid in group_sids:
            v = got.get(sid) if isinstance(got, dict) else None
            if _valid_slot_text(v):
                translated[sid] = v
                pending.pop(sid, None)
                failures.pop(sid, None)
            else:
                failures[sid] = (
                    "empty / non-string / contains slot or placeholder token"
                )
    for sid in pending:
        failures.setdefault(sid, "no answer")


def _assemble_slots(seq: list[tuple[str, str]], translated: dict[str, str]) -> str:
    """槽译文 + 占位符/raw 原文按 seq 重组为整段译文。"""
    parts: list[str] = []
    for kind, payload in seq:
        # [[SL]]/[[PL]]/[[SP]] 也是 ph 项——必须解码回字节形态，否则装配
        # 译文残留字面 token，校验按多余占位符判死（s40 阶梯全军覆没根因）
        text = translated[payload] if kind == "slot" else payload
        parts.append(decode_newlines(text))
    return "".join(parts)


async def _stage_slots(ctx: _LadderCtx) -> str | None:
    """Stage 3：slots JSON 兜底（`⟪S0000⟫`、json_object、失败槽只重问失败批）。"""
    slots, seq = _make_slots(ctx.encoded)
    if not slots:
        return None
    translated: dict[str, str] = {}
    pending = dict(slots)
    failures: dict[str, str] = {}
    for _round in range(SLOTS_MAX_ROUNDS):
        if not pending:
            break
        await _slots_round(ctx, pending, translated, failures)
    if pending:
        ctx.warnings.append(f"slots unanswered after retries: {sorted(pending)}")
        return None
    candidate, err, w = assess_answer(
        ctx.source,
        _assemble_slots(seq, translated),
        repair_fn=ctx.repair_fn,
        validate_fn=ctx.validate_fn,
    )
    if err:
        ctx.warnings.append(f"slots assembled but still invalid: {err}")
        return None
    ctx.warnings.extend(w)
    ctx.warnings.append("slots fallback path rescued")
    return candidate


async def translate_with_ladder(  # noqa: PLR0913 -- 阶梯可插拔点全集（依赖注入面）
    source: str,
    *,
    translate_fn: Callable[[str, str], Awaitable[str]],
    slots_fn: Callable[[dict[str, str], str], Awaitable[dict[str, str]]],
    validate_fn: Callable[[str, str], str] = _validate,
    corrector_fn: Callable[[str, str, str], Awaitable[str]] | None = None,
    repair_fn: Callable[[str, str], tuple[str, list[str]]] | None = None,
) -> LadderResult:
    """四段语义阶梯（各阶段内调用方已含 HTTP 退避）。

    `translate_fn(src_text, error_feedback)` —— 整段/行级调用；`error_feedback`
    是 `previous_validation_error` 字段化反馈（比对话式"你错了"稳）。
    `slots_fn(slots_map, failures_json)` —— JSON 槽位调用；`failures_json` 是
    `slot_validation_failures` 字段（失败槽只重问失败批）。
    `validate_fn(src, zh)` —— 错误描述字符串，空串 = 通过。
    `corrector_fn(original, translation, error)` —— 可选三段式 corrector，
    提供时替换 stage-1 第二试（corrector 是更强的修复臂）。
    `repair_fn(src, zh) -> (zh, recovered)` —— 可选 decode 后/validate 前的
    占位符抄回修复（模型把受保护原文抄进译文时换回 token）。
    """
    ctx = _LadderCtx(
        source=source,
        encoded=encode_newlines(source)[0],
        translate_fn=translate_fn,
        slots_fn=slots_fn,
        validate_fn=validate_fn,
        corrector_fn=corrector_fn,
        repair_fn=repair_fn,
    )

    zh = await _stage_whole(ctx)
    if zh is not None:
        return LadderResult(zh, "ok", "whole", ctx.attempts, ctx.warnings)

    zh = await _stage_lines(ctx)
    if zh is not None:
        return LadderResult(zh, "recovered", "lines", ctx.attempts, ctx.warnings)

    zh = await _stage_slots(ctx)
    if zh is not None:
        return LadderResult(zh, "recovered", "slots", ctx.attempts, ctx.warnings)

    # stage 4：三振 fallback_orig + warning（终态 partial 由调用方标记）。
    # translation 必须是原文——名实相符且防下游误用 .translation 把未过审
    # 译文拼回文档；best_zh 折进 warnings 留诊断。
    if ctx.best_zh:
        ctx.warnings.append(f"best-effort zh (unspliced): {ctx.best_zh[:200]}")
    ctx.warnings.append("all ladder stages exhausted → fallback to original")
    return LadderResult(
        ctx.source, "fallback_orig", "fallback", ctx.attempts, ctx.warnings
    )
