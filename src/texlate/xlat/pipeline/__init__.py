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

拆分：实现体按子域下沉同包六叶——``pipeline.types``（常量/ChunkResult/
PipelineConfig/chunk_to_in 数据契约）、``pipeline.translator``（Translator
协议/GatewayTranslator 适配/输出清洗）、``pipeline.materialize``
（_XlatMaterialize：system prompt memo + 术语/锚定/点名册 + 段级缓存）、
``pipeline.single``（_XlatSingle：阶梯调用点 + L2 回灌）、``pipeline.batch``
（_XlatBatch：编号批协议 + 退单翻）、``pipeline.ledger``（_XlatLedger：
skip/直通落形 + 拦截网/auth 闸/emit 账本）、``pipeline.orch``（WorkItem +
_XlatOrch 主编排 + ``XlatPipeline`` 组合根）。本文件是 PEP 562 惰性门面
（同 ``kernel.kernel``/``worker.compile`` 形制）——平名经 ``_LEAF_EXPORTS``
映射回叶子，``__getattr__`` 首访解析并缓存。

monkeypatch 锚点守恒（docs/dev/seams.md §5）：五个 ``_intercept_<name>``
包装函 + ``_net_apply_fn`` 必须 eager 驻留本模块——后者经 ``globals()``
晚绑定取件，钉的是本命名空间，tests ``setattr(pl, "_intercept_*")`` 才能
照常触达账本/裸形两消费点（移进叶子 globals() 即换主，补丁静默旁路）。
``pl.AuthGate.record`` 是类级补丁，惰性解析拿到同一类对象照常生效；
``setattr(pl, <别名>)`` 形补丁（``_interceptable``/``_INTERCEPT_NETS``/
``translate_with_ladder`` 等）按通用门面口径不再传播——消费方已下沉叶内
绑定，要 patch 指到属主叶（seams 登记缝不受影响）。
"""

from __future__ import annotations

import importlib
import logging
import sys
from typing import TYPE_CHECKING

# ``ChunkIn`` 契约下沉 ``texlate.chunk``（arxiv 降级链同消费——底层不能
# 向上 import 本包）；转口保持 ``from texlate.xlat.pipeline import ChunkIn``
# 钉点面守恒（repair_l2/e2e/worker/tests）。``JSON_FENCE_RX`` 同——
# ``_strip_json_fence`` 出叶 ``pipeline.translator`` 后名仍挂本面。
from texlate.chunk import ChunkIn
from texlate.textutil import JSON_FENCE_RX
from texlate.xlat import placeholders, prompts
from texlate.xlat.intercept import (
    _INTERCEPT_NETS,
    # 包装函钉点面——``_net_apply_fn`` 经 ``globals()`` 晚绑定取件，
    # tests ``monkeypatch.setattr(pl, "_intercept_*")`` 缝在本模块命名空间；
    # 惰性槽位会让 globals() 查无键炸 KeyError，故七个名必须 eager。
    _intercept_bare_cs,
    _intercept_dangerous_cs,
    _intercept_leftover_ph,
    _intercept_ph_in_cs,
    _intercept_residual_en,
    _interceptable,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.xlat.authgate import AuthGate, AuthTrippedError, _kind_of
    from texlate.xlat.batch import (
        BATCH_MAX_CHARS,
        BATCH_MAX_ITEMS,
        BATCH_MIN_CHARS,
        CHUNK_HARD_LIMIT,
        batch_member_overhead,
        encode_batch_members,
        pack_batches,
        parse_batch_response,
        split_long_chunk,
    )
    from texlate.xlat.client import (
        HTTP_UNAUTHORIZED,
        REASONING_MIN_MAX_TOKENS,
        ChatClient,
        ChatError,
        ChatOptions,
        LengthTruncatedError,
    )
    from texlate.xlat.intercept import _InterceptNet
    from texlate.xlat.mock import MOCK_ZH, MockTranslator, _mock_translate_text
    from texlate.xlat.pipeline.batch import _merged_value_frags, _XlatBatch
    from texlate.xlat.pipeline.ledger import _FatalLedger, _XlatLedger
    from texlate.xlat.pipeline.materialize import _XlatMaterialize
    from texlate.xlat.pipeline.orch import WorkItem, XlatPipeline, _XlatOrch
    from texlate.xlat.pipeline.single import _slots_user_obj, _XlatSingle
    from texlate.xlat.pipeline.translator import (
        _C0_RX,
        GatewayTranslator,
        Translator,
        _strip_json_fence,
    )
    from texlate.xlat.pipeline.types import (
        DEFAULT_CONCURRENCY,
        LENGTH_RETRY_MAX_TOKENS,
        PAPER_CTX_MAX_CHARS,
        TRANSLATE_MAX_TOKENS,
        TRANSLATE_TEMPERATURE,
        ChunkResult,
        PipelineConfig,
        chunk_to_in,
    )
    from texlate.xlat.retry import (
        RetryPolicy,
        assess_answer,
        bare_token_audit,
        call_with_backoff,
        translate_with_ladder,
    )
    from texlate.xlat.state import ChunkRecord, StateStore, segment_key

log = logging.getLogger(__name__)

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "types": (
        "DEFAULT_CONCURRENCY",
        "LENGTH_RETRY_MAX_TOKENS",
        "PAPER_CTX_MAX_CHARS",
        "TRANSLATE_MAX_TOKENS",
        "TRANSLATE_TEMPERATURE",
        "ChunkResult",
        "PipelineConfig",
        "chunk_to_in",
    ),
    "translator": (
        "GatewayTranslator",
        "Translator",
        "_C0_RX",
        "_strip_json_fence",
    ),
    "materialize": ("_XlatMaterialize",),
    "single": (
        "_XlatSingle",
        "_slots_user_obj",
    ),
    "batch": (
        "_XlatBatch",
        "_merged_value_frags",
    ),
    "ledger": ("_FatalLedger", "_XlatLedger"),
    "orch": (
        "WorkItem",
        "XlatPipeline",
        "_XlatOrch",
    ),
    # 原样转口——拆叶前就在本模块命名空间的 import 名（``from texlate.xlat.pipeline import``
    # 钉点面），惰性映射回属主模块逐名解析。键为绝对路径：门面已收包
    # (``pipeline/``)，``__package__`` 下没有这些顶层 sibling。
    "texlate.xlat.authgate": (
        "AuthGate",
        "AuthTrippedError",
        "_kind_of",
    ),
    "texlate.xlat.batch": (
        "BATCH_MAX_CHARS",
        "BATCH_MAX_ITEMS",
        "BATCH_MIN_CHARS",
        "CHUNK_HARD_LIMIT",
        "batch_member_overhead",
        "encode_batch_members",
        "pack_batches",
        "parse_batch_response",
        "split_long_chunk",
    ),
    "texlate.xlat.client": (
        "HTTP_UNAUTHORIZED",
        "REASONING_MIN_MAX_TOKENS",
        "ChatClient",
        "ChatError",
        "ChatOptions",
        "LengthTruncatedError",
    ),
    "texlate.xlat.mock": (
        "MOCK_ZH",
        "MockTranslator",
        "_mock_translate_text",
    ),
    "texlate.xlat.retry": (
        "RetryPolicy",
        "assess_answer",
        "bare_token_audit",
        "call_with_backoff",
        "translate_with_ladder",
    ),
    "texlate.xlat.state": (
        "ChunkRecord",
        "StateStore",
        "segment_key",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

# 字面列表——ruff F401 re-export 判定要静态 __all__；覆盖 _LAZY 键集 + 本模块
# eager 转口名（``_export_drift`` 是三表同步闸）。
__all__ = [
    "BATCH_MAX_CHARS",
    "BATCH_MAX_ITEMS",
    "BATCH_MIN_CHARS",
    "CHUNK_HARD_LIMIT",
    "DEFAULT_CONCURRENCY",
    "HTTP_UNAUTHORIZED",
    "JSON_FENCE_RX",
    "LENGTH_RETRY_MAX_TOKENS",
    "MOCK_ZH",
    "PAPER_CTX_MAX_CHARS",
    "REASONING_MIN_MAX_TOKENS",
    "TRANSLATE_MAX_TOKENS",
    "TRANSLATE_TEMPERATURE",
    "_C0_RX",
    "_INTERCEPT_NETS",
    "AuthGate",
    "AuthTrippedError",
    "ChatClient",
    "ChatError",
    "ChatOptions",
    "ChunkIn",
    "ChunkRecord",
    "ChunkResult",
    "GatewayTranslator",
    "LengthTruncatedError",
    "MockTranslator",
    "PipelineConfig",
    "RetryPolicy",
    "StateStore",
    "Translator",
    "WorkItem",
    "XlatPipeline",
    "_FatalLedger",
    "_XlatBatch",
    "_XlatLedger",
    "_XlatMaterialize",
    "_XlatOrch",
    "_XlatSingle",
    "_intercept_bare_cs",
    "_intercept_dangerous_cs",
    "_intercept_leftover_ph",
    "_intercept_ph_in_cs",
    "_intercept_residual_en",
    "_interceptable",
    "_kind_of",
    "_merged_value_frags",
    "_mock_translate_text",
    "_net_apply_fn",
    "_slots_user_obj",
    "_strip_json_fence",
    "assess_answer",
    "bare_token_audit",
    "batch_member_overhead",
    "call_with_backoff",
    "chunk_to_in",
    "encode_batch_members",
    "pack_batches",
    "parse_batch_response",
    "placeholders",
    "prompts",
    "segment_key",
    "split_long_chunk",
    "translate_with_ladder",
]


def _net_apply_fn(net: _InterceptNet) -> Callable[[ChunkResult], None]:
    """``net`` 的模块级 apply 包装函（``_intercept_<name>`` 词根约定）。

    ``globals()`` 晚绑定取件而非条目持引用——tests 的 ``monkeypatch.setattr``
    改模块属性后账本形/裸形两消费点仍拿到补丁件（fault 注入钉点面守恒，
    早绑定会把注入静默旁路）。注册表与包装函本体已出叶 ``.intercept``——
    本件留本模块正是因为 ``globals()`` 钉的是本命名空间；拆叶后两消费点
    （``pipeline.ledger._ledger_intercepts``/``pipeline.single.
    retranslate_chunk``）仍回本门面取件。
    """
    return globals()[f"_intercept_{net.name}"]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        mod = leaf if leaf.startswith("texlate.") else f"{__package__}.{leaf}"
        value = getattr(importlib.import_module(mod), name)
        globals()[name] = value
        return value
    msg = f"module {__name__!r} has no attribute {name!r}"
    raise AttributeError(msg)


def __dir__() -> list[str]:
    return __all__


def _export_drift() -> list[str]:
    """``__all__``/``_LEAF_EXPORTS``/本地公共名三表同步审计 → 漂移描述表。

    空表 = 同步，测试断言 ``== []`` 即可。三向覆盖：

    - ``_LAZY`` 键全进 ``__all__``;
    - ``__all__`` 逐名 ``getattr`` 可解——叶子断链 (``_LEAF_EXPORTS``
      配名叶子不提供) 与幽灵条 (既非叶子名也非本地名) 在此曝，是首访
      ``AttributeError`` 唯一的提前闸;
    - 本地公共名 (本模块定义的函数/类) 全进 ``__all__``。

    审计实载全部叶子，只供测试调用，装载期不自检。
    """
    mod = sys.modules[__name__]
    drift = [
        f"{name} in _LEAF_EXPORTS but missing from __all__"
        for name in _LAZY
        if name not in __all__
    ]
    if len(__all__) != len(set(__all__)):
        drift.append("__all__ has duplicate entries")
    drift += [
        f"leaf stem {stem!r} shadows an exported name (rename the leaf)"
        for stem in _LEAF_EXPORTS
        if stem in _LAZY
    ]
    for name in __all__:
        try:
            getattr(mod, name)
        except Exception as exc:  # noqa: BLE001 -- 审计兜全漂移，非首错即死
            drift.append(f"__all__ entry {name} does not resolve: {exc}")
    local_publics = {
        name
        for name, v in vars(mod).items()
        if not name.startswith("_")
        and name not in _LAZY
        and callable(v)
        and getattr(v, "__module__", None) == __name__
    }
    drift += [
        f"{name} defined locally but missing from __all__"
        for name in sorted(local_publics)
        if name not in __all__
    ]
    return drift
