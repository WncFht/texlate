r"""qualbench spec — LLM-judge 翻译质量评测（原 ``bench/py/qualbench.py`` spec 化）。

测量面逐行移植：ESA esa2 协议（judge 先标错误 span 再赋 0-100 分；
规格见 docs/research/methods/2026-09-18-xlat-quality-eval.md §7）、
九类目 MQM 化表 + 六 flag 派生 + stated100/derived100 双分 +
contested 触发二裁。格模型重做——一 frame 行（paper, chunk_id, judge）
一格：idc=paper、arm=被评翻译模型、variant=``esa2@{EPOCH}|{judge}|
{chunk_id}``、up=frame 行 provenance。``dedup_key``=(idc,arm,variant)
显式声明（付费段强制）；测量行进 eval_records 道 + emit_case 全量
record。跨 run dedup 永驻——协议/测具变化靠 PROTOCOL_V/EPOCH 升号挪
claim 空间，绝不原地覆盖。

chunk 对来源 = **frame**（冻结选样层）：``bench/nominations/qualframe-
*.jsonl`` 每行一对，由 ``specs/_qualframe.py`` 烘焙——旧 ``--source``
三道的正身：``mock``（湖格 mock 译文 + ``judge=mock-judge`` 零网关自检）、
``state``（``xlat-state/{arm}/state.json`` 树→ok/partial∧zh≠src 行，
judge 烘焙时按 route_judge 路由）、``manifest``（qualsample 冻结
sample.jsonl 直收）。frame 行 ``sha`` 进 ``fp_input``；src/zh/kind/
src_status 四参 fp=True（frame 重烘焙同键改内容→新测量）。
**frame 丢失 = spec 加载即炸**——选样层是被测对象的一部分，静默退化
会把「没测」读成「测了」。

状态映射（status_class 逐格声明；audit 三件套之 status 映射）：
  judge 出分（含 contested、含 judge2 内部失败）→ ``ok``
  传输/协议错或两次输出均不可解析          → ``error``（retriable——
      网关抖动/模型暂缺可回；旧 done-error 行的正身）
  网关把请求降级到非路由模型（fallback）   → ``error`` + judge_fallback
      （retriable——路由禁则被破坏宁可重测不记账；见下 DELTA）
  ``route_judge`` 全员被禁                 → ``reject`` + no_eligible_judge
      （terminal——池不变不会自愈，重跑无义）
  src/zh 任一空                          → ``reject`` + empty_pair
      （terminal——确定性终态）

done 定义（audit 三件套之二）：每格恰一条 terminal/retriable 行；
测量分母 = 全部格（reject 格也算分母——frame 选了就该交代结果；
empty/no_eligible 是「测量对象自证不合法」，与「未测」分开计数）。
分母守恒对拍：frame 行数 == 格数 == 终态+可重试行数，无静默丢格。

参数面：src/zh/kind/src_status fp=True（cell 侧内容指纹）；chunk_id/
judge fp=False（已在 variant，声明只为参数 schema 完整）；second_model/
no_second/judge_temperature/judge_max_tokens fp=True（测量语义旋钮，
改动=新测量空间）；frames/ids/judges/n 为 select 闸（fp=False，n 为
selector 自带排除）。select 语义：frame 序即烘焙序（seeded），过滤器
先过再取前 n。

DELIBERATE DELTAS（对旧驱动的刻意迁移，均已核对语义）：
- judge 调压栈由「裸 httpx 3-try 指数退避」改为 ``session.request`` 一
  发——ChatClient 内部已是同 taxonomy 的重试梯队（retryable/
  max_tries/retry_after），外层再套循环会双倍预算。ChatError 逃逸 =
  梯队已尽 → judge_error（retriable），不再就地退避。
- 新增 **judge_fallback 闸**：ChatClient.chat 带免费集降级臂（loopback
  网关 ``is_free_gateway_url``=True，swe-2-max 失败可静默换 swe-2-medium
  ——被禁同型自评）。每发响应 ``res.model != 请求模型`` → judge_error，
  不记账。旧裸 httpx 无此臂，本闸是 spec 化必须的等价防线。
- ``--judge-timeout`` 参数被删：ChatOptions 无 timeout 字段、factory 是
  spec 级（params 解析前即建）——参数在结构上不可达。超时烘焙进
  factory 的 ``GatewayChat(timeout=300.0)``（值同旧默认）。
- ``--judge-model`` 从 run 参数挪进 frame 行 ``judge`` 列（烘焙时路由，
  进 variant）——「谁裁」是测量坐标不是运行旋钮；换主裁=换 frame=
  新 claim 空间，不重测旧键。
- no_eligible_judge / empty_pair 由「done-error 无限重跑」改 terminal
  reject（retry 无出口的状态不应挂 retriable）。
- 并发面：driver ``--concurrency 2`` → factory ``nslots=2``；网关全局
  decode ~550 tok/s 自限不变。
- ``--mock-judge`` 开关改 frame 行 ``judge="mock-judge"``——fn 在
  ctx.gateway() **之前** 分流（懒构造=付费断言，mock 格零请求零花费），
  但仍走完整付费段 claim/dedup 机械（刻意：全链自检不豁免）。
- ``pairs``/``report`` 子命令与抽样 CLI 整体消失——选样下沉
  ``specs/_qualframe.py``（烘焙产物即 frame），聚合属分析动词。
- record 落点：records.jsonl append → emit_case（cases 表 + cases.jsonl
  与终态批量原子落）；key={model}|{paper}|{chunk}|{judge}|{proto} 的
  五元组由 (idc,arm,variant) 三键承载（proto/epoch 在 variant 前段）。

拆分（facade 化 god-split）：实现体按职域拆进同包私有叶——
``_qualbench_const``（REPO/NOMINATIONS 钉点 + 判定面正则 + ESA/MQM
词表阈值 + judge 协议串）、``_qualbench_judge``（Pair + pair_signals +
ESA 解析/规范化/路由/contest/mock/shape 全纯逻辑面）、
``_qualbench_paid``（_judge_call/_judge_pair 付费通道）、
``_qualbench_main``（FRAMES→items/_Select/_judge 格函数/_factory/spec
装配）。本文件是 PEP 562 惰性门面（同 ``specs/soak.py`` 形制）——平名
经 ``_LEAF_EXPORTS`` 映射回叶子，``qualbench.X`` 与
``from specs.qualbench import X`` 读面与拆分前逐名等价（
``specs/_qualframe.py`` 的 ``from specs.qualbench import Pair,
route_judge`` 走的就是这条面）；``spec`` 住 ``_qualbench_main`` 叶
（``load_spec`` 首访惰性解析）。叶间直引 ``from specs._qualbench_X
import Y`` 不绕本门面（避环）。spec 文件经 load_spec exec（非包内
导入，``__package__`` 为空）——叶名走 ``_PKG = __package__ or
"specs"`` 归一。
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

from kernel.spec import SC_OK_REJECT, Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

import importlib
import sys
from typing import TYPE_CHECKING

from specs import _select as _sel  # run 期收窄单源（ids/only/n 管道）
from specs._shared import (
    DEFAULT_BASE_URL,
    DEFAULT_PRICES,
    GatewayChat,
)

if TYPE_CHECKING:
    # __all__ 名单静态落地——F822 要名可解，F401 以 __all__ re-export 豁免。
    from specs._qualbench_const import (
        CATEGORY_TO_FLAG,
        CRITICAL_CATS,
        CS_RX,
        DELTA_CONTEST,
        EN_RESIDUE_CONTEST,
        EN_WORD_RX,
        EPOCH,
        JSON_FENCE_RX,
        JSON_OBJ_RX,
        JUDGE_BANNED,
        JUDGE_POOL,
        JUDGE_RETRY_SUFFIX,
        JUDGE_SYSTEM,
        JUDGE_TIMEOUT,
        KNOWN_CATEGORIES,
        KNOWN_FLAGS,
        MAX_ERRORS,
        MAX_ERRORS_KEPT,
        NOMINATIONS,
        PH_TOKEN_RX,
        PROTOCOL_V,
        REPO,
        REPORT_ONLY_CATS,
        SEV_WEIGHT,
        STATED_CONTEST,
    )
    from specs._qualbench_judge import (
        Pair,
        _norm_parsed,
        contest_reasons,
        derived100,
        flags_of,
        judge_user_prompt,
        mock_judge,
        pair_signals,
        parse_esa_json,
        route_judge,
        shape_judged,
        verify_spans,
    )
    from specs._qualbench_main import (
        FRAMES,
        _factory,
        _items,
        _iter_frame,
        _judge,
        _metric_view,
        _Select,
        spec,
    )
    from specs._qualbench_paid import _judge_call, _judge_pair

_LEAF_EXPORTS: dict[str, tuple[str, ...]] = {
    "_qualbench_const": (
        "CATEGORY_TO_FLAG",
        "CRITICAL_CATS",
        "CS_RX",
        "DELTA_CONTEST",
        "EN_RESIDUE_CONTEST",
        "EN_WORD_RX",
        "EPOCH",
        "JSON_FENCE_RX",
        "JSON_OBJ_RX",
        "JUDGE_BANNED",
        "JUDGE_POOL",
        "JUDGE_RETRY_SUFFIX",
        "JUDGE_SYSTEM",
        "JUDGE_TIMEOUT",
        "KNOWN_CATEGORIES",
        "KNOWN_FLAGS",
        "MAX_ERRORS",
        "MAX_ERRORS_KEPT",
        "NOMINATIONS",
        "PH_TOKEN_RX",
        "PROTOCOL_V",
        "REPORT_ONLY_CATS",
        "REPO",
        "SEV_WEIGHT",
        "STATED_CONTEST",
    ),
    "_qualbench_judge": (
        "Pair",
        "contest_reasons",
        "derived100",
        "flags_of",
        "judge_user_prompt",
        "mock_judge",
        "pair_signals",
        "parse_esa_json",
        "route_judge",
        "shape_judged",
        "verify_spans",
        "_norm_parsed",
    ),
    "_qualbench_main": (
        "FRAMES",
        "_Select",
        "_factory",
        "_items",
        "_iter_frame",
        "_judge",
        "_metric_view",
        "spec",
    ),
    "_qualbench_paid": (
        "_judge_call",
        "_judge_pair",
    ),
}

_LAZY: dict[str, str] = {
    name: mod for mod, names in _LEAF_EXPORTS.items() for name in names
}

_PKG = __package__ or "specs"  # load_spec exec 径下 __package__ 是 ""

# 字面列表——拆分前顶层名面 (import/常量/函数/spec 全量) 逐名保留；新增导出
# 两侧同步（``_export_drift`` 是三表同步闸）。
__all__ = [
    "CATEGORY_TO_FLAG",
    "CRITICAL_CATS",
    "CS_RX",
    "DEFAULT_BASE_URL",
    "DEFAULT_PRICES",
    "DELTA_CONTEST",
    "EN_RESIDUE_CONTEST",
    "EN_WORD_RX",
    "EPOCH",
    "FRAMES",
    "JSON_FENCE_RX",
    "JSON_OBJ_RX",
    "JUDGE_BANNED",
    "JUDGE_POOL",
    "JUDGE_RETRY_SUFFIX",
    "JUDGE_SYSTEM",
    "JUDGE_TIMEOUT",
    "KNOWN_CATEGORIES",
    "KNOWN_FLAGS",
    "MAX_ERRORS",
    "MAX_ERRORS_KEPT",
    "NOMINATIONS",
    "PH_TOKEN_RX",
    "PROTOCOL_V",
    "REPO",
    "REPORT_ONLY_CATS",
    "SC_OK_REJECT",
    "SEV_WEIGHT",
    "STATED_CONTEST",
    "GatewayChat",
    "Pair",
    "Param",
    "Path",
    "Spec",
    "Stage",
    "_Select",
    "_bootstrap",
    "_factory",
    "_items",
    "_iter_frame",
    "_judge",
    "_judge_call",
    "_judge_pair",
    "_metric_view",
    "_norm_parsed",
    "_sel",
    "contest_reasons",
    "dataclass",
    "derived100",
    "flags_of",
    "hashlib",
    "json",
    "judge_user_prompt",
    "mock_judge",
    "pair_signals",
    "parse_esa_json",
    "re",
    "route_judge",
    "shape_judged",
    "spec",
    "time",
    "verify_spans",
]


def __getattr__(name: str) -> object:
    """平名惰性解析 → 叶子属性。"""
    leaf = _LAZY.get(name)
    if leaf is not None:
        value = getattr(importlib.import_module(f"{_PKG}.{leaf}"), name)
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
    for name in __all__:
        try:
            getattr(mod, name)
        except Exception as exc:  # 审计兜全漂移，非首错即死
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
