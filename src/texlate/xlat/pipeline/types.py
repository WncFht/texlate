"""pipeline 数据契约域（自 ``pipeline`` 出叶）：常量 + 输入适配 + 结果/配置 dataclass。

``chunk_to_in``/``ChunkResult``/``PipelineConfig`` 是编排三方（编排器、
worker 侧消费方、export/repair_l2）的共同词汇；常量定案值见
docs/spec/translate.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from texlate.chunk import ChunkIn
from texlate.xlat import placeholders, prompts
from texlate.xlat.batch import (
    BATCH_MAX_CHARS,
    BATCH_MAX_ITEMS,
    BATCH_MIN_CHARS,
    CHUNK_HARD_LIMIT,
)
from texlate.xlat.client import REASONING_MIN_MAX_TOKENS
from texlate.xlat.state import ChunkRecord

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from texlate.latex.model import Chunk

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
    #: 底层（同 key 由既有四层表赢——curated 覆盖 auto）。调用方负责
    #: memoize（worker ctx.memo / e2e 单例），否则 resume 会重抽。
    auto_glossary_fn: Callable[[list[str]], Awaitable[dict[str, str]]] | None = None

    def __post_init__(self) -> None:
        """数值钳位：0/负并发会饿死 worker 让 queue.join 死等；hard_limit<1 让 split 死循环。"""
        self.concurrency = max(1, self.concurrency)
        self.hard_limit = max(1, self.hard_limit)
