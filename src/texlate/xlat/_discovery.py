"""xlat 免费集发现面：端点闸判定 + 面板/v1 枚举 + 探活 + 偏好排序。

``client.py`` 出叶（hoist）：``normalize_base_url`` 端点归一、
``is_free_gateway_url`` 网络位置闸（loopback/tailnet——发现/探活链只准
打这个面）、``FreeModel`` 载具、``_get_json``/``list_models``/
``panel_models``/``probe_model``/``discover_free_models``/
``fallback_candidates`` 发现链与 ``rank_models``/``pick_model`` 排序。
函数吃 ``client`` 形参并经其方法回探缝面（``_chat_once``/``_get_json``/
``discover_free_models``——monkeypatch 锚点语义不变）；``ChatClient``
侧留薄委托（钉点名不变），门面回引常数与 ``FreeModel``。叶子不引
``client``（环断）。
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx

from texlate.xlat._dialects import ChatOptions
from texlate.xlat._errors import (
    _TRANSPORT_ERRORS,
    ChatError,
    MalformedResponseError,
    _transport_error,
    redact,
)

if TYPE_CHECKING:
    from texlate.xlat.client import ChatClient

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- 常量

#: 探活请求预算（只要求非空 content，给思考留 1k 余量足够）
PROBE_MAX_TOKENS = 1024
PROBE_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

#: 免费集偏好序（动态发现后按此排序——不是免费集本身，命中才选；
#: 自有网关按实际模型集调整或经 TEXLATE_MODEL 指定）
DEFAULT_MODEL_PREFERENCE = ("swe-2-medium", "swe-2-high", "swe-2-max", "glm-5-2")
#: 免费集禁用名单（契约事故史/不可预算）
DEFAULT_MODEL_DENYLIST = frozenset({"swe-1-7", "swe-1-7-medium"})
#: 单次 chat 降级臂最多补发候选数（对齐 §1.7 备选链深度 medium→high→max，
#: 防半死网关上一次调用放大成十数发——外层 ``call_with_backoff`` 还会整体重试）
FALLBACK_MAX_CANDIDATES = 3


# ---------------------------------------------------------------- 载具


@dataclass
class FreeModel:
    """动态发现的一个免费模型（panel 元数据 + 探活结果）。"""

    uid: str
    promo_end: str = ""
    context_tokens: int = 0
    supports_thinking: bool = False
    probe_ok: bool = False
    probe_latency_s: float = 0.0
    probe_error: str = ""


# ---------------------------------------------------------------- 端点归一/闸判定

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})
#: tailnet CGNAT 段（与 ``settings._is_plaintext_ok_host`` 同信任域——
#: 自有网段上跑的只会是部署方自有服务，探活打过去不烧第三方 quota）
_TAILNET_V4 = ipaddress.ip_network("100.64.0.0/10")


def normalize_base_url(base_url: str) -> str:
    """宽容归一：剥尾 `/`、`/chat/completions`、`/v1` 后缀，得到裸服务根。"""
    url = base_url.strip().rstrip("/")
    for suffix in ("/v1/chat/completions", "/chat/completions", "/v1"):
        if url.endswith(suffix):
            url = url[: -len(suffix)]
            break
    return url.rstrip("/")


def is_free_gateway_url(base_url: str) -> bool:
    """内置免费网关判定：host ∈ loopback ∪ tailnet（CGNAT / ``*.ts.net``）。

    发现/探活链只准打这个面——公网 BYOK 预设（anthropic/deepseek/qwen/
    openai）与任意 custom 公网端点一律 False，一个探测请求都不发。
    ``provider_for_url`` 单独不能当闸：tailnet 网关（``*.ts.net``/
    CGNAT）解析成 ``"custom"``，BYOK 也可以是 custom——端点身份只能
    看网络位置。
    """
    try:
        host = (urlsplit(normalize_base_url(base_url)).hostname or "").lower()
    except ValueError:
        return False  # 畸形 URL 必非内置网关——发现/探活面零放行
    if host in _LOOPBACK_HOSTS or host.endswith(".ts.net"):
        return True
    try:
        return ipaddress.ip_address(host) in _TAILNET_V4
    except ValueError:
        return False


def _safe_int(value: object) -> int:
    """面板元数据字段 → int；coerce 失败退化 0——展示元数据非合同字段，单字段畸形不挡成员入集。"""
    try:
        return int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return 0


# ---------------------------------------------------------------- 发现链


async def _get_json(client: ChatClient, path: str) -> tuple[Any, str]:
    """``GET {base_url}{path}`` → (parsed JSON, 脱敏 body 摘要)。

    传输/HTTP 状态/JSON 解析错误按 ``_chat_once`` 同口径分类抛出；
    返回的 ``snippet``（响应体前 200 字符脱敏）留给调用方拼形状错误消息。
    """
    try:
        resp = await client._http.get(  # noqa: SLF001 -- 出叶委托面（同模块实现组）
            f"{client.base_url}{path}",
            headers=client._openai_headers(),  # noqa: SLF001 -- 同上
        )
    except _TRANSPORT_ERRORS as e:
        raise _transport_error(e) from e
    client._status_gate(resp)  # noqa: SLF001 -- 同上
    snippet = redact(resp.text[:200], client.api_key)
    try:
        return resp.json(), snippet
    except (json.JSONDecodeError, RecursionError) as e:
        msg = f"non-JSON response: {snippet}"
        raise MalformedResponseError(msg) from e


def _model_ids_from(items: object) -> list[str] | None:
    """``/v1/models`` 的 ``data`` 成员 → 模型 id 列；非 list 回 ``None``。

    ``list_models``（上方）与 ``server.providers.list_provider_models``
    的同一形状合同——list 闸 + dict+``id`` 逐成员过滤 + ``str()`` 强转；
    两侧只差失败包装（``MalformedResponseError`` vs ``None``）。
    """
    if not isinstance(items, list):
        return None
    return [str(m["id"]) for m in items if isinstance(m, dict) and "id" in m]


async def list_models(client: ChatClient) -> list[str]:
    """`GET /v1/models` → 模型 id 列表。"""
    data, snippet = await client._get_json("/v1/models")  # noqa: SLF001 -- 出叶委托面（同模块实现组）
    if not isinstance(data, dict):
        msg = f"non-object JSON response: {snippet}"
        raise MalformedResponseError(msg)
    # ``or []``：``data`` 缺失/None/空值按空集过闸（非畸形）——与 providers
    # 侧 ``data.get("data")`` 直取的 None 失败口径刻意不同，勿并
    ids = _model_ids_from(data.get("data") or [])
    if ids is None:
        msg = f"unexpected data field: {snippet}"
        raise MalformedResponseError(msg)
    return ids


async def panel_models(client: ChatClient) -> list[dict[str, Any]]:
    """`GET /panel/api/models` → 面板模型表（含 cost_tier/promo/disabled）。"""
    data, snippet = await client._get_json("/panel/api/models")  # noqa: SLF001 -- 出叶委托面（同模块实现组）
    if isinstance(data, dict):
        models = data.get("models") or []
        # 可迭代但非 list（str/dict）走逐成员过滤回 []；不可迭代标量
        # （int/bool/float）与 list_models 的 data 字段同口径报畸形
        if not isinstance(models, Iterable):
            msg = f"unexpected models field: {snippet}"
            raise MalformedResponseError(msg)
        return [m for m in models if isinstance(m, dict)]
    if isinstance(data, list):
        return [m for m in data if isinstance(m, dict)]
    return []


async def probe_model(client: ChatClient, uid: str) -> FreeModel:
    """探活单模型：一次最小 chat 往返（方言随 ``client.dialect``），要求非空 content。

    复用 ``_chat_once``——request 组装/响应解析/错误分类三方口径一致，
    ``PROBE_TIMEOUT`` 经其单次请求覆盖收紧。
    """
    t0 = time.monotonic()
    try:
        r = await client._chat_once(  # noqa: SLF001 -- 出叶委托面（同模块实现组）
            uid,
            [{"role": "user", "content": "Reply with exactly: OK"}],
            ChatOptions(max_tokens=PROBE_MAX_TOKENS),
            req_timeout=PROBE_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 -- 探活对任意失败都返回不可用，绝不抛出
        return FreeModel(
            uid=uid,
            probe_ok=False,
            probe_error=redact(str(e), client.api_key)[:200],
            probe_latency_s=round(time.monotonic() - t0, 2),
        )
    ok = bool(r.content.strip()) and r.finish_reason in (
        "",
        "stop",
        "end_turn",
        "stop_sequence",
    )
    return FreeModel(
        uid=uid,
        probe_ok=ok,
        probe_error="" if ok else f"empty content or bad finish ({r.finish_reason})",
        probe_latency_s=round(r.latency_s, 2),
    )


async def discover_free_models(
    client: ChatClient, *, probe: bool = True, max_probe: int = 12
) -> list[FreeModel]:
    """免费集动态发现：panel 筛 free+promo.active+enabled ∩ /v1/models ∩ 探活。

    promo 到期（如 glm-5-2 2026-09-16）后该 uid 自然掉出——绝不硬编码。
    `probe=False` 只做两步交集（清单≠可用，正式选路必须 probe）。
    生产调用方：``fallback_candidates``（``chat`` 降级臂经此枚举）。
    """
    panel = await client.panel_models()
    try:
        v1_ids = set(await client.list_models())
    except ChatError:
        v1_ids = set()  # /v1/models 挂了不挡发现路（退化为只信 panel）

    candidates: list[FreeModel] = []
    for m in panel:
        if m.get("cost_tier") != "free":
            continue
        if m.get("disabled"):
            continue
        promo = m.get("promo")
        if not isinstance(promo, dict) or not promo.get("active"):
            continue
        uid = str(m.get("uid") or "")
        if not uid or (v1_ids and uid not in v1_ids):
            continue
        candidates.append(
            FreeModel(
                uid=uid,
                promo_end=str(promo.get("end_date") or ""),
                context_tokens=_safe_int(m.get("context_tokens")),
                supports_thinking=bool(m.get("supports_thinking")),
            )
        )
    if not probe or not candidates:
        return candidates

    sem = asyncio.Semaphore(4)

    async def _probe(fm: FreeModel) -> FreeModel:
        async with sem:
            probed = await client.probe_model(fm.uid)
            fm.probe_ok = probed.probe_ok
            fm.probe_latency_s = probed.probe_latency_s
            fm.probe_error = probed.probe_error
            return fm

    return list(await asyncio.gather(*(_probe(fm) for fm in candidates[:max_probe])))


async def fallback_candidates(client: ChatClient) -> list[str]:
    """免费集降级候选 uid 表（``rank_models`` 偏好序）：惰性发现 + memoize。

    非内置网关（``is_free_gateway_url`` False）与发现链任何失败一律
    返回 []——BYOK/公网端点一个探测请求都不发，调用方静默退化为
    静态模型行为。``chat`` 降级臂与 worker 侧枚举共用此面。
    候选数封顶 ``FALLBACK_MAX_CANDIDATES``。
    """
    if not is_free_gateway_url(client.base_url):
        return []
    if client._free_uids is None:  # noqa: SLF001 -- 出叶委托面（同模块实现组）
        async with client._discovery_lock:  # noqa: SLF001 -- 同上
            if client._free_uids is None:  # noqa: SLF001 -- 同上
                try:
                    client._free_uids = rank_models(  # noqa: SLF001 -- 同上
                        await client.discover_free_models()
                    )
                except Exception as e:  # noqa: BLE001 -- 发现失败静默退化，绝不挡 chat
                    log.warning("免费集发现失败（%s）——模型降级臂停用", e)
                    client._free_uids = []  # noqa: SLF001 -- 同上
    return client._free_uids[:FALLBACK_MAX_CANDIDATES]  # noqa: SLF001 -- 同上


# ---------------------------------------------------------------- 排序


def rank_models(
    discovered: list[FreeModel],
    *,
    preference: tuple[str, ...] = DEFAULT_MODEL_PREFERENCE,
    denylist: frozenset[str] = DEFAULT_MODEL_DENYLIST,
) -> list[str]:
    """探活通过的免费集 → 有序候选 uid 表（denylist 剔除；偏好序在前，其余按 uid 字典序）。"""
    alive = {m.uid for m in discovered if m.probe_ok} - set(denylist)
    pref = [u for u in preference if u in alive]
    return pref + sorted(alive - set(pref))


def pick_model(
    discovered: list[FreeModel],
    *,
    preference: tuple[str, ...] = DEFAULT_MODEL_PREFERENCE,
    denylist: frozenset[str] = DEFAULT_MODEL_DENYLIST,
) -> str | None:
    """从探活通过的免费集里按偏好序选模型（denylist 一票否决）。"""
    ranked = rank_models(discovered, preference=preference, denylist=denylist)
    return ranked[0] if ranked else None
