"""渠道数据层 —— ``channels.json`` store + 两段行为探针 + 凭据阶梯 + 路由/冷却。

``routers/channels.py``（HTTP 面）/``cli/channels.py``（命令行面）同名异义
——本叶是三方共享的数据/探测/路由单源（glossary §3 登记）。

文件契约 ``{version: 2, channels: [...], route: {...}}``（0600 原子写）；
channel = ``{id, name, preset, base_url, protocol, models[], priority,
max_concurrency, enabled, api_key|key_env, last_probe}``：

- ``id`` 是稳定键：落盘渠道 ``ch-<8hex>``（创建即钉死，永不随 base_url
  重算）；投影合成渠道用 ``sha1(normalize(base_url))[:8]`` 派生——同一
  物理端点恒同 id，``last_probe``/UI 选中态不挂错档。
- ``models`` 条目 ``{model, redirect_model, enabled, max_concurrency}``：
  ``model`` 是渠道内模型名（展示名/探针报告键），``redirect_model`` 是
  上游请求名——非空时上游收到的是它（重定向目标），空串即本名直发；
  ``wire_model`` 单源取线上名。裸 string 条目不收。
- ``priority`` 大者先路由；写径照写客户端值（字段即事实源）——拖拽
  排序语义 = 调用方按展示序整表重发差 ``PRIORITY_STEP`` 稀疏序号
  （ccload 同款稀疏序，便于单点插入），前端按 ``(len-idx)*10`` 重发。
- ``api_key`` 与 ``key_env`` 互斥；写径 ``api_key=""`` 保留同 id 旧值，
  一方显式写入即清另一方（凭据形态切换）。
- ``key_env`` 存 env 变量**名**不存值——轮换 key 只改环境，渠道零改写；
  ``resolve_auth`` 经 ``key_env_for`` 查名读值，server 任何出参只见名
  不见值。
- ``last_probe`` 服务端独占（PUT 载荷里该键忽略）：渠道面
  （base_url/protocol/models）与 key 指纹双未变才跨写保留。
- ``route`` = ``{channel_id, model}``：``channel_id`` ``"auto"`` 或渠道
  id——钉死则只用该渠道；``model`` 是逻辑模型名（任一渠道的本地名），
  决议时按 redirect 反解。
- 文件缺席时 ``effective_channels`` 把 settings+connections **读径投影**
  成合成渠道表（id=``default`` + 每 connections 槽一条）——迁移
  不落盘，首个 PUT 才物化。
- 旧 ``endpoints.json`` v1 档案读径自动转形（profile→channel 字段映名，
  档案序 → priority 差 10 回填，active → route）；首个 ``save`` 落
  ``channels.json`` 并把旧件改名 ``endpoints-migrated-<rand>.json`` 留档。

冷却是进程态（``cooldowns`` 模块级表单实例）：``(channel_id, wire_model)``
与 ``channel_id`` 两级 ``monotonic`` 到期戳——渠道级失败（传输死/auth）
标渠道键，模型级失败（429/5xx/404）标模型键；冷却中的组合在路由求值
期被滤掉（半死渠道不再每 chunk 先烧一跳）。进程重启清零——冷却是
「近期失败史」不是判决，重启重试是正确语义。
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import logging
import re
import secrets
import threading
import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx

from texlate.server.logredact import scrub
from texlate.server.validate import (
    validate_base_url,
    validate_dialect,
    validate_model,
)
from texlate.textutil import env_raw
from texlate.xlat.client import (
    REASONING_MIN_MAX_TOKENS,
    AuthError,
    BillingError,
    ChatClient,
    ChatError,
    ChatOptions,
    ContentFilterError,
    EndpointNotFoundError,
    MalformedResponseError,
    RetryableHTTPError,
    env_key_for_url,
    normalize_base_url,
    provider_for_url,
)
from texlate.xlat.state import atomic_json

if TYPE_CHECKING:
    from pathlib import Path

log = logging.getLogger(__name__)

# ---------------------------------------------------------------- 文件契约

CHANNELS_FILE = "channels.json"
#: v1 迁移输入——``channels.json`` 缺席且本件在 → 读径转形（不落盘）
ENDPOINTS_LEGACY_FILE = "endpoints.json"
SCHEMA_VERSION = 2
MAX_CHANNELS = 16
MAX_MODELS_PER_CHANNEL = 8
NAME_MAX_LEN = 48
#: 相邻渠道 priority 间距——拖拽重排后按数组序重发差 10 序号
PRIORITY_STEP = 10
#: 渠道/模型并发上限域（``None`` = 只受全局池约束）
MAX_CONCURRENCY_CAP = 64

_ID_RX = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_KEY_ENV_RX = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")

# ---------------------------------------------------------------- 服务商预设

#: 渠道预设目录：``preset`` 字段值域 + 新建渠道表单预填单源。
#: ``protocol`` 即 API 协议族（openai=chat/completions 兼容面）；``key_env``
#: 是凭据 env 约定名；``models`` 是「获取模型」失败时的兜底清单。
CHANNEL_PRESETS: tuple[dict[str, Any], ...] = (
    {
        "id": "gateway",
        "name": "Local Gateway",
        "protocol": "openai",
        "base_url": "http://127.0.0.1:3033",
        "models": ["swe-2-medium"],
        "key_env": "TEXLATE_API_KEY",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "protocol": "openai",
        "base_url": "https://api.deepseek.com",
        "models": ["deepseek-chat", "deepseek-reasoner"],
        "key_env": "DEEPSEEK_API_KEY",
    },
    {
        "id": "openai",
        "name": "OpenAI",
        "protocol": "openai",
        "base_url": "https://api.openai.com",
        "models": ["gpt-4o-mini", "gpt-4o"],
        "key_env": "OPENAI_API_KEY",
    },
    {
        "id": "anthropic",
        "name": "Anthropic",
        "protocol": "anthropic",
        "base_url": "https://api.anthropic.com",
        "models": ["claude-haiku-4-5", "claude-sonnet-4-5"],
        "key_env": "ANTHROPIC_API_KEY",
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "protocol": "openai",
        "base_url": "https://openrouter.ai/api",
        "models": [],
        "key_env": "OPENROUTER_API_KEY",
    },
    {
        "id": "qwen",
        "name": "Alibaba Qwen",
        "protocol": "openai",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode",
        "models": ["qwen-flash", "qwen-plus"],
        "key_env": "DASHSCOPE_API_KEY",
    },
    {
        "id": "custom",
        "name": "Custom",
        "protocol": "auto",
        "base_url": "",
        "models": [],
        "key_env": "TEXLATE_API_KEY",
    },
)

_PRESET_IDS = frozenset(p["id"] for p in CHANNEL_PRESETS)

# ---------------------------------------------------------------- 行为探针

#: 占位符完整性探句——`[[X_N]]` 三枚 token 必须原样存活于译文（译中丢
#: 占位符 = splice 回插静默腐蚀，比翻译质量差更致命，单独判级）
PROBE_SENTENCE = (
    "Translate the following English sentence into Simplified Chinese. "
    "Output the translation only and preserve every [[X_N]] placeholder "
    "byte-identically.\n\n"
    "The [[MATH_1]] norm satisfies [[MATH_2]] \\le 1; see [[CITE_1]]."
)
# 预算/超时对齐生产翻译径（TRANSLATE_MAX_TOKENS=8192）——reasoning 模型把
# 思考链也吃进 max_tokens，小预算会给可用模型判 finish=length 假阴
# （OpenRouter 实测：dots/nemotron 256tok 全灭、8192 双双 usable，2026-10-07）。
PROBE_TIMEOUT = httpx.Timeout(60.0, connect=8.0)
PROBE_MAX_TOKENS = REASONING_MIN_MAX_TOKENS
_PROBE_CONCURRENCY = 4
_PROBE_TOKENS = ("[[MATH_1]]", "[[MATH_2]]", "[[CITE_1]]")
_CJK_RX = re.compile(r"[一-鿿]")
#: 段1 报告里的模型清单截断（OpenRouter 类端点 /v1/models 可 200+ 条——
#: 报告是 UX 面不是镜像，全量无意义）
_STAGE1_MODELS_MAX = 50
#: 段2 整体跳过集：list 已证鉴权死/传输死 → 逐模型再试只是放大失败数
_STAGE2_SKIP = frozenset({"auth_failed", "unreachable", "timeout"})

# ---------------------------------------------------------------- 冷却表

#: 冷却 TTL 分级（秒）：凭据终态（auth/billing）长冷、模型摘除/拒答中冷、
#: 可重试故障短冷——ccload 错误分级语义的单用户裁剪版。
_COOLDOWN_AUTH_S = 300.0
_COOLDOWN_MODEL_S = 600.0
_COOLDOWN_RETRYABLE_S = 60.0


class Cooldowns:
    """``(channel_id, wire_model)``/``channel_id`` 两级冷却表——进程态不落盘。

    失败臂打到期戳；路由求值期 ``is_cooled`` 滤掉冷却中的组合，到期自然
    复活。表无界增长防护：条目带到期戳，``sweep`` 惰性清过期项（每次
    ``mark``/``is_cooled`` 顺带触发，表规模被活跃失败数天然封顶）。
    """

    def __init__(self) -> None:
        """空表 + 互斥锁（mark/is_cooled 可跨 worker 线程并发触达）。"""
        self._until: dict[tuple[str, str], float] = {}
        self._lock = threading.Lock()

    def mark(self, channel_id: str, wire_model: str, ttl: float) -> None:
        """标冷却：``wire_model=""`` = 渠道级（整渠道冷却），否则模型级。"""
        if not channel_id or ttl <= 0:
            return
        self._sweep()
        with self._lock:
            self._until[(channel_id, wire_model)] = time.monotonic() + ttl

    def is_cooled(self, channel_id: str, wire_model: str) -> bool:
        """渠道级或模型级任一冷却中 → True。"""
        now = time.monotonic()
        with self._lock:
            ch_until = self._until.get((channel_id, ""), 0.0)
            m_until = self._until.get((channel_id, wire_model), 0.0)
        return ch_until > now or m_until > now

    def mark_error(self, channel_id: str, wire_model: str, e: ChatError) -> float:
        """失败臂落冷却戳：错误分级 → 渠道级/模型级 TTL；返回所标 TTL（``0`` = 不标）。

        渠道级（``wire=""`` 键）：``AuthError``/``BillingError``（凭据随
        渠道走，换模无救）与传输死（``RetryableHTTPError status<0`` ——
        端点不可达，换模照样死）。模型级：模型摘除（404）/其余故障。
        ``ContentFilterError`` 不标——拒答是块内容属性，整模型背锅会
        误伤后续正常块。
        """
        if not channel_id:
            return 0.0
        if isinstance(e, (AuthError, BillingError)):
            ttl, wire = _COOLDOWN_AUTH_S, ""
        elif isinstance(e, RetryableHTTPError) and e.status < 0:
            ttl, wire = _COOLDOWN_RETRYABLE_S, ""
        elif isinstance(e, ContentFilterError):
            return 0.0
        elif isinstance(e, EndpointNotFoundError):
            ttl, wire = _COOLDOWN_MODEL_S, wire_model
        elif e.retryable:
            ttl, wire = _COOLDOWN_RETRYABLE_S, wire_model
        else:
            ttl, wire = _COOLDOWN_MODEL_S, wire_model
        self.mark(channel_id, wire, ttl)
        return ttl

    def _sweep(self) -> None:
        now = time.monotonic()
        with self._lock:
            dead = [k for k, until in self._until.items() if until <= now]
            for k in dead:
                del self._until[k]


#: 进程级冷却表单例——跨 ChannelStore 实例/任务共享「近期失败史」
cooldowns = Cooldowns()


# ---------------------------------------------------------------- 校验件


def _check_id(value: object) -> str:
    """渠道 id：小写 slug（``[a-z0-9][a-z0-9-]{0,31}``）；``ch-<8hex>``/投影派生形同域。"""
    if not isinstance(value, str) or not _ID_RX.fullmatch(value):
        msg = "channel id 须为 [a-z0-9][a-z0-9-]{0,31} slug"
        raise ValueError(msg)
    return value


def _check_name(value: object) -> str:
    """渠道名：可打印、≤48 字符、strip；缺席/空 → ``""``（出参回兜底名）。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        msg = "name 须为 string"
        raise TypeError(msg)
    v = value.strip()
    if len(v) > NAME_MAX_LEN or not v.isprintable():
        msg = f"name 须为可打印且 ≤{NAME_MAX_LEN} 字符"
        raise ValueError(msg)
    return v


def _check_key_env(value: object) -> str:
    """Key_env：env 变量名形态（``[A-Za-z_][A-Za-z0-9_]{0,63}``）。"""
    if value is None:
        return ""
    if not isinstance(value, str) or not _KEY_ENV_RX.fullmatch(value):
        msg = "key_env 须为合法 env 变量名"
        raise ValueError(msg)
    return value


def _check_preset(value: object) -> str:
    """预设 id：预设表内或 ``custom``；空 → ``custom``。"""
    if value is None or value == "":
        return "custom"
    if not isinstance(value, str):
        msg = "preset 须为 string"
        raise TypeError(msg)
    v = value.strip().lower()
    if v not in _PRESET_IDS:
        msg = f"preset ∈ {sorted(_PRESET_IDS)}"
        raise ValueError(msg)
    return v


def _check_priority(value: object) -> int:
    """优先级：可转 int；非法 → 0（读径容错面——写径同函数，int 域即合法）。"""
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0


def _check_max_concurrency(value: object) -> int | None:
    """并发上限：``None``/``0``/缺席 → ``None``（不限）；正 int clamp ≤64。"""
    if value is None or value == 0:
        return None
    try:
        return max(1, min(MAX_CONCURRENCY_CAP, int(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        msg = f"max_concurrency 须为 null 或 1–{MAX_CONCURRENCY_CAP} int"
        raise ValueError(msg) from None


def _model_entry(item: object) -> dict[str, Any]:
    """单条目 → ``{model, redirect_model, enabled, max_concurrency}`` 归一 dict。"""
    if not isinstance(item, dict):
        msg = "models 成员须为 {model, redirect_model} 对象"
        raise TypeError(msg)
    raw_name = item.get("model")
    if not isinstance(raw_name, str):
        msg = "models 条目 model 须为 string"
        raise TypeError(msg)
    name = validate_model(raw_name)
    raw_red = item.get("redirect_model")
    if raw_red is not None and not isinstance(raw_red, str):
        msg = "models 条目 redirect_model 须为 string"
        raise TypeError(msg)
    redirect = validate_model(raw_red) if raw_red and raw_red.strip() else ""
    if redirect == name:
        redirect = ""  # 与模型名同名是冗余写法——归一清空
    enabled = item.get("enabled", True)
    if not isinstance(enabled, bool):
        msg = "models 条目 enabled 须为 bool"
        raise TypeError(msg)
    return {
        "model": name,
        "redirect_model": redirect,
        "enabled": enabled,
        "max_concurrency": _check_max_concurrency(item.get("max_concurrency")),
    }


def _check_models(value: object) -> list[dict[str, Any]]:
    """Models：条目一律 dict，归一保序。

    ``model`` = 渠道内模型名（展示/探针报告键），``redirect_model`` = 上游
    请求名——非空时上游收的是它。逐条校验、按模型名去重保序、≤8；
    ``None → []``。裸 string 条目不收。
    """
    if value is None:
        return []
    if not isinstance(value, list):
        msg = "models 须为 list"
        raise TypeError(msg)
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for item in value:
        entry = _model_entry(item)
        if entry["model"] not in seen:
            seen.add(entry["model"])
            out.append(entry)
    if len(out) > MAX_MODELS_PER_CHANNEL:
        msg = f"models 至多 {MAX_MODELS_PER_CHANNEL} 条"
        raise ValueError(msg)
    return out


def _check_model_names(value: object) -> list[str]:
    """模型名子集（probe ``{id, models}`` 请求面 selector）：``string[]`` → 去重保序名表。

    不是渠道 schema——只是「探哪些模型名」的选择器，逐条 ``validate_model``；
    ``None → []``；非 list/非 str 成员 → TypeError。
    """
    if value is None:
        return []
    if not isinstance(value, list):
        msg = "models 须为 string list"
        raise TypeError(msg)
    seen: set[str] = set()
    out: list[str] = []
    for item in value:
        if not isinstance(item, str):
            msg = "models 成员须为 string（模型名选择器）"
            raise TypeError(msg)
        name = validate_model(item)
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def wire_model(entry: dict[str, Any]) -> str:
    """模型条目 → 上游请求名（``redirect_model`` 非空优先，否则模型名）。"""
    return str(entry.get("redirect_model") or "") or str(entry.get("model") or "")


def local_model_name(entry: dict[str, Any]) -> str:
    """模型条目 → 渠道内模型名（展示/探针报告键）。"""
    return str(entry.get("model") or "")


def _key_fp(api_key: str) -> str:
    """Key → sha256 前 8 hex 指纹（``last_probe`` 有效性对账；空 key → ``""``）。"""
    return hashlib.sha256(api_key.encode()).hexdigest()[:8] if api_key else ""


def _name_for(base_url: str) -> str:
    """空 name 兜底：provider 名；custom 端点取 host。"""
    provider = provider_for_url(base_url)
    if provider != "custom":
        return provider
    try:
        host = urlsplit(base_url).hostname or ""
    except ValueError:
        host = ""
    return host or "endpoint"


def _stable_id(base_url: str) -> str:
    """投影渠道的稳定派生 id：``sha1(normalize(base_url))[:8]``——同端点恒同 id。"""
    return (
        "ch-"
        + hashlib.sha1(  # noqa: S324 -- 非安全用途：url→稳定 id 派生
            normalize_base_url(base_url).encode()
        ).hexdigest()[:8]
    )


def _quarantine(path: Path, why: str, *args: object) -> None:
    """损坏文件改名隔离（xlat.state 同口径）：``*-invalid-<rand>`` 兄弟名 + warn，不删。"""
    bad = path.with_name(f"{path.stem}-invalid-{secrets.token_hex(4)}{path.suffix}")
    path.rename(bad)
    log.warning(why, *args, bad.name)


# ---------------------------------------------------------------- 归一化


def _entry_from_v1(item: object) -> object:
    """v1 ``{model, redirect_model}`` → v2 条目形（缺省键由 ``_model_entry`` 补）。"""
    return item  # v1 键名与 v2 兼容——额外键由校验件补默认


def _load_channel(raw: object) -> dict[str, Any] | None:
    """读径容错归一：坏成员整渠道丢弃（None），不让一条手改烂行炸穿全表。"""
    if not isinstance(raw, dict):
        return None
    try:
        pid = _check_id(raw.get("id"))
        base_url = validate_base_url(str(raw.get("base_url") or ""))
        protocol = validate_dialect(str(raw.get("protocol") or "auto"))
        models = _check_models(raw.get("models"))
        name = _check_name(raw.get("name"))
        preset = _check_preset(raw.get("preset"))
        priority = _check_priority(raw.get("priority"))
        max_conc = _check_max_concurrency(raw.get("max_concurrency"))
    except (TypeError, ValueError):
        return None
    api_key = raw.get("api_key")
    api_key = api_key if isinstance(api_key, str) else ""
    key_env = raw.get("key_env")
    key_env = (
        key_env if isinstance(key_env, str) and _KEY_ENV_RX.fullmatch(key_env) else ""
    )
    if api_key and key_env:
        # 手改文件撞互斥 → env 引用优先（不落盘的凭据形态更安全）
        api_key = ""
    last_probe = raw.get("last_probe")
    if not isinstance(last_probe, dict):
        last_probe = None
    return {
        "id": pid,
        "name": name or _name_for(base_url),
        "preset": preset,
        "base_url": base_url,
        "protocol": protocol,
        "models": models,
        "priority": priority,
        "max_concurrency": max_conc,
        "enabled": bool(raw.get("enabled", True)),
        "api_key": api_key,
        "key_env": key_env,
        "last_probe": last_probe,
    }


def _channel_from_v1(raw: object) -> dict[str, Any] | None:
    """v1 profile dict → v2 channel dict 转形（label→name、dialect→protocol）。"""
    if not isinstance(raw, dict):
        return None
    mapped = dict(raw)
    mapped["name"] = mapped.pop("label", mapped.get("name"))
    mapped["protocol"] = mapped.pop("dialect", mapped.get("protocol", "auto"))
    mapped["preset"] = _preset_for_url(str(mapped.get("base_url") or ""))
    return _load_channel(mapped)


def _preset_for_url(base_url: str) -> str:
    """base_url → 预设 id（provider_for_url 命中即预设，否则 custom）。"""
    provider = provider_for_url(base_url)
    return provider if provider in _PRESET_IDS else "custom"


def _load_route(raw: object, channels: list[dict[str, Any]]) -> dict[str, str]:
    """``route`` 小节容错读：``{channel_id: "auto"|id, model: str}``。

    channel_id 指向不存在渠道 → 落 ``auto``（渠道被删后路由不失忆，
    model 选择仍有效）。非法 model → 空串。
    """
    if not isinstance(raw, dict):
        return {"channel_id": "auto", "model": ""}
    cid = str(raw.get("channel_id") or "auto")
    if cid != "auto" and all(c["id"] != cid for c in channels):
        cid = "auto"
    model = str(raw.get("model") or "")
    try:
        model = validate_model(model) if model.strip() else ""
    except ValueError:
        model = ""
    return {"channel_id": cid, "model": model}


def _normalize_channel(  # noqa: C901 -- 全字段校验 + 凭据互斥/保留合并 + probe 继承阶梯平铺
    raw: object, existing_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """写径严格归一（PUT 语义）：全字段校验 + 凭据互斥/保留合并 + last_probe 继承。

    ``id`` 空串/缺席 → 生成 ``ch-<8hex>`` 稳定键（撞名重骰）。
    凭据合并规则：``api_key``/``key_env`` 同时显式非空 → ValueError；
    单方显式非空 → 清另一方（形态切换）；双方缺省/空串 → 承旧值。
    ``last_probe`` 服务端独占：仅当渠道面（base_url/protocol/models）与
    有效 key 指纹均未变才从旧档继承。
    """
    if not isinstance(raw, dict):
        msg = "channel 须为 object"
        raise TypeError(msg)
    raw_id = raw.get("id")
    pid = _check_id(raw_id) if raw_id else ""
    existing = existing_by_id.get(pid) if pid else None
    if not pid:
        while True:
            pid = f"ch-{secrets.token_hex(4)}"
            if pid not in existing_by_id:
                break
    base_url = validate_base_url(str(raw.get("base_url") or ""))
    protocol = validate_dialect(str(raw.get("protocol") or "auto"))
    models = _check_models(raw.get("models"))
    name = _check_name(raw.get("name")) or _name_for(base_url)
    preset = _check_preset(raw.get("preset"))
    priority = _check_priority(raw.get("priority"))
    max_conc = _check_max_concurrency(raw.get("max_concurrency"))
    enabled = raw.get("enabled", True)
    if not isinstance(enabled, bool):
        msg = "enabled 须为 bool"
        raise TypeError(msg)

    api_in = raw.get("api_key")
    env_in = raw.get("key_env")
    if api_in is not None and not isinstance(api_in, str):
        msg = "api_key 须为 string"
        raise TypeError(msg)
    if env_in is not None and not isinstance(env_in, str):
        msg = "key_env 须为 string"
        raise TypeError(msg)
    if api_in and env_in:
        msg = "api_key 与 key_env 互斥——同渠道只能带一种凭据引用"
        raise ValueError(msg)
    old_key = str(existing.get("api_key") or "") if existing else ""
    old_env = str(existing.get("key_env") or "") if existing else ""
    api_key = api_in or old_key
    key_env = _check_key_env(env_in) if env_in else old_env
    if env_in:
        api_key = ""  # 显式 key_env 覆盖存量 inline key（凭据形态切换）
    if api_in:
        key_env = ""  # 显式 api_key 覆盖存量 env 引用

    channel: dict[str, Any] = {
        "id": pid,
        "name": name,
        "preset": preset,
        "base_url": base_url,
        "protocol": protocol,
        "models": models,
        "priority": priority,
        "max_concurrency": max_conc,
        "enabled": enabled,
        "api_key": api_key,
        "key_env": key_env,
        "last_probe": None,
    }
    last = existing.get("last_probe") if existing else None
    if (
        isinstance(last, dict)
        and base_url == existing.get("base_url")
        and protocol == existing.get("protocol")
        and models == existing.get("models")
        and last.get("key_fp") == _key_fp(api_key or env_raw(key_env))
    ):
        channel["last_probe"] = last
    return channel


def _dedupe_ids(channels: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """读径 id 去重（先见赢）+ 数量封顶。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for p in channels:
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        out.append(p)
    return out[:MAX_CHANNELS]


# ---------------------------------------------------------------- store


class ChannelStore:
    """``channels.json``（0600）渠道 store——``SettingsStore`` 同套机制。

    渠道 = BYOK 上游实体（base_url/协议/凭据/模型清单/优先级/并发上限）；
    顶层 ``route`` 小节存路由选择（``channel_id``+``model``）。旧
    ``endpoints.json`` 经读径转形自动迁移（不落盘，首个 save 物化 +
    旧件改名留档）。mtime 标记缓存 + 深拷贝出参 + 损坏 quarantine——
    全照 SettingsStore 口径。
    """

    def __init__(self, root: Path) -> None:
        """Root = 数据目录（与 ``settings.json`` 同根，已 0700 建妥）。"""
        self.root = root
        self.path = root / CHANNELS_FILE
        self.legacy_path = root / ENDPOINTS_LEGACY_FILE
        self._save_lock = threading.Lock()
        self._load_cache: tuple[tuple[int, int] | None, dict[str, Any]] | None = None
        self._load_lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        """读 channels.json → ``{"version":2,"channels":[...],"route":{...}}``（深拷贝出参）。

        缺席且 ``endpoints.json`` 在 → v1 读径转形（不落盘）；双缺席 →
        空表。JSON 损坏 → quarantine 隔离 + 空表；version 非法 → warn +
        空表；逐渠道容错过滤，坏成员只丢自己。
        """
        try:
            st = self.path.stat()
            sig: tuple[int, int] | None = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig = None  # 缺席也按标记缓存——缺席是常态（未建渠道）
        with self._load_lock:
            if self._load_cache is not None and self._load_cache[0] == sig:
                return copy.deepcopy(self._load_cache[1])
            data: dict[str, Any] = {
                "version": SCHEMA_VERSION,
                "channels": [],
                "route": {"channel_id": "auto", "model": ""},
            }
            if sig is not None:
                data = self._load_v2(sig, data)
            else:
                migrated = self._load_legacy()
                if migrated is not None:
                    data = migrated
            self._load_cache = (sig, data)
            return copy.deepcopy(data)

    def _load_v2(self, _sig: tuple[int, int], data: dict[str, Any]) -> dict[str, Any]:
        """channels.json v2 读径本体。"""
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (
            OSError,
            UnicodeDecodeError,
            json.JSONDecodeError,
            RecursionError,
        ) as e:
            _quarantine(self.path, "channels.json 损坏（%s）→ quarantined as %s", e)
            return data
        if not isinstance(raw, dict) or raw.get("version") != SCHEMA_VERSION:
            log.warning(
                "channels.json version 非法（%s）→ 按空表处理",
                raw.get("version") if isinstance(raw, dict) else type(raw).__name__,
            )
            return data
        items = raw.get("channels")
        items = items if isinstance(items, list) else []
        channels = _dedupe_ids(
            [c for c in (_load_channel(i) for i in items) if c is not None]
        )
        data["channels"] = channels
        data["route"] = _load_route(raw.get("route"), channels)
        return data

    def _load_legacy(self) -> dict[str, Any] | None:
        """endpoints.json v1 → v2 转形；文件缺席/损坏/非法 → ``None``。

        转形规则：``profiles[]`` → ``channels[]``（label→name、
        dialect→protocol、档案序 → priority 差 10 递减回填、preset 按
        base_url 派生）；``active`` 命中的渠道 + ``settings.model`` 不进
        route——读径拿不到 settings，``route`` 留 auto 由投影/首个 save
        落定（迁移窗口期路由等价「未配置」→ settings 四键投影照常兜底）。
        """
        try:
            raw = json.loads(self.legacy_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            return None
        if not isinstance(raw, dict) or raw.get("version") != 1:
            return None
        items = raw.get("profiles")
        if not isinstance(items, list):
            return None
        channels = _dedupe_ids(
            [c for c in (_channel_from_v1(i) for i in items) if c is not None]
        )
        for idx, ch in enumerate(channels):
            if not ch["priority"]:
                ch["priority"] = (len(channels) - idx) * PRIORITY_STEP
        return {
            "version": SCHEMA_VERSION,
            "channels": channels,
            "route": {"channel_id": "auto", "model": ""},
        }

    def save(
        self,
        channels: list[object],
        route: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """整表替换写（PUT 语义）：逐条严格校验 → 0600 原子写；返回归一化后数据。

        ``route=None`` 承旧值；显式 ``{"channel_id","model"}`` 走严格校验
        （channel_id ∈ ``auto``∪现存 id，model 过 ``validate_model``）。
        写后顺带迁移收尾：旧 ``endpoints.json`` 改名 ``-migrated-<rand>``
        留档（channels.json 已是事实源，旧件再被读径转形会复活已删渠道）。
        """
        with self._save_lock:
            if not isinstance(channels, list):
                msg = "channels 须为 list"
                raise TypeError(msg)
            if len(channels) > MAX_CHANNELS:
                msg = f"channels 至多 {MAX_CHANNELS} 条"
                raise ValueError(msg)
            cur = self.load()
            existing = {p["id"]: p for p in cur["channels"]}
            out: list[dict[str, Any]] = []
            seen: set[str] = set()
            for raw in channels:
                c = _normalize_channel(raw, existing)
                if c["id"] in seen:
                    msg = f"channel id 重复：{c['id']}"
                    raise ValueError(msg)
                seen.add(c["id"])
                out.append(c)
            if route is None:
                route_out = _load_route(cur.get("route"), out)
            else:
                route_out = self._check_route(route, out)
            # UTF-8 预探雷（settings._save 同口径）——atomic_json 半路炸
            # 会留半写文件；先序列化探雷，炸了按非法更新处理磁盘零写
            try:
                json.dumps(out, ensure_ascii=False).encode("utf-8")
            except UnicodeEncodeError as e:
                msg = "channels 含不可编码字符"
                raise ValueError(msg) from e
            payload = {
                "version": SCHEMA_VERSION,
                "channels": out,
                "route": route_out,
            }
            atomic_json(self.path, payload)
            self.path.chmod(0o600)
            self._rename_legacy()
            with self._load_lock:
                self._load_cache = None
            return copy.deepcopy(payload)

    def _rename_legacy(self) -> None:
        """旧 ``endpoints.json`` 改名留档。``_save_lock`` 内调用。

        channels.json 物化后旧件再被读径转形会复活已删渠道。
        """
        if not self.legacy_path.exists():
            return
        legacy = self.legacy_path.with_name(
            f"endpoints-migrated-{secrets.token_hex(4)}.json"
        )
        self.legacy_path.rename(legacy)
        log.info("endpoints.json 已迁移 → channels.json（旧件留档 %s）", legacy.name)

    def _check_route(
        self, raw: object, channels: list[dict[str, Any]]
    ) -> dict[str, str]:
        """写径 route 严格校验：channel_id ∈ ``auto``∪现存 id；model 非空过 ``validate_model``。"""
        if not isinstance(raw, dict):
            msg = "route 须为 object"
            raise TypeError(msg)
        cid = str(raw.get("channel_id") or "auto")
        if cid != "auto" and all(c["id"] != cid for c in channels):
            msg = f"route.channel_id 指向不存在的渠道：{cid}"
            raise ValueError(msg)
        model = str(raw.get("model") or "")
        model = validate_model(model) if model.strip() else ""
        return {"channel_id": cid, "model": model}

    def record_probe(self, channel_id: str, report: dict[str, Any]) -> None:
        """把探针报告钉到指定渠道的 ``last_probe``；文件缺席/id 无命中 → no-op。

        ``models`` 段按键 **merge**——同凭据（``key_fp`` 一致）下逐模型子集
        探测只更新被探条目，未探模型保留旧 verdict；stage1-only 报告
        （``models={}``）不动既有模型段。换凭据（fp 变）则整报告覆盖。
        """
        with self._save_lock:
            data = self.load()
            hit = next((c for c in data["channels"] if c["id"] == channel_id), None)
            if hit is None:
                return
            old = hit.get("last_probe")
            if (
                isinstance(old, dict)
                and isinstance(old.get("models"), dict)
                and old.get("key_fp") == report.get("key_fp")
            ):
                merged = dict(old["models"])
                merged.update(report.get("models") or {})
                report = dict(report)
                report["models"] = merged
            hit["last_probe"] = report
            atomic_json(self.path, data)
            self.path.chmod(0o600)
            self._rename_legacy()
            with self._load_lock:
                self._load_cache = None

    # ------------------------------------------------------------ 读径投影/查找

    def effective_channels(
        self,
        settings: dict[str, Any],
        connections: dict[str, dict[str, str]],
    ) -> list[dict[str, Any]]:
        """当前有效渠道集：文件/迁移件在 → 归一化渠道表；双缺席 → 投影合成（不落盘）。"""
        if self.path.exists() or self.legacy_path.exists():
            return self.load()["channels"]
        return _project_channels(settings, connections)

    def key_env_for(self, base_url: str) -> str:
        """base_url 命中渠道的 ``key_env`` 名；无命中 → ``""``。

        enabled 无关——凭据元数据不是参与身份（disabled 渠道的 env 名
        照样是合法 key 源）。``resolve_auth`` env 层的查名钩。
        """
        target = normalize_base_url(base_url)
        for c in self.load()["channels"]:
            if normalize_base_url(str(c.get("base_url") or "")) == target:
                return str(c.get("key_env") or "")
        return ""

    def resolve_route(  # noqa: C901 -- 钉渠道/按名匹配/兜底三级 + 冷却过滤阶梯平铺
        self,
        settings: dict[str, Any],
        connections: dict[str, dict[str, str]],
    ) -> dict[str, Any] | None:
        """路由决议 → ``{channel, entry, api_key, wire_model}``；无档案/无可用渠道 → ``None``。

        候选集 = enabled 渠道；``route.channel_id`` 钉死则收敛单渠道。
        ``route.model`` 非空时优先选「models 显式含该名」的 priority 最高
        渠道；全不命中 → 最高 priority 渠道 + 裸名直发（redirect 空）。
        凭据走 ``credential_for`` 四级阶梯；冷却中的 (渠道,模型) 滤掉。
        """
        if not (self.path.exists() or self.legacy_path.exists()):
            return None
        data = self.load()
        route = data["route"]
        channels = [c for c in data["channels"] if c.get("enabled")]
        if not channels:
            return None
        if route["channel_id"] != "auto":
            pinned = next((c for c in channels if c["id"] == route["channel_id"]), None)
            channels = [pinned] if pinned else []
        channels.sort(key=lambda c: -int(c["priority"]))
        want = route["model"] or str(settings.get("model") or "")
        for ch in channels:
            if cooldowns.is_cooled(ch["id"], ""):
                continue
            entry = next(
                (
                    e
                    for e in ch["models"]
                    if e["enabled"]
                    and want
                    and (local_model_name(e) == want or wire_model(e) == want)
                ),
                None,
            )
            if entry is None or cooldowns.is_cooled(ch["id"], wire_model(entry)):
                continue
            return self._routed(ch, entry, connections)
        for ch in channels:
            if cooldowns.is_cooled(ch["id"], ""):
                continue
            if ch["models"]:
                entry = next((e for e in ch["models"] if e["enabled"]), ch["models"][0])
            else:
                entry = {
                    "model": want,
                    "redirect_model": "",
                    "enabled": True,
                    "max_concurrency": None,
                }
            if not local_model_name(entry) and not want:
                continue
            if cooldowns.is_cooled(ch["id"], wire_model(entry)):
                continue
            return self._routed(ch, entry, connections)
        return None

    def _routed(
        self,
        ch: dict[str, Any],
        entry: dict[str, Any],
        connections: dict[str, dict[str, str]],
    ) -> dict[str, Any]:
        """(渠道,条目) → 决议包（调用方已前置冷却过滤）。"""
        key, src = credential_for(ch, connections)
        return {
            "channel": ch,
            "entry": entry,
            "api_key": key,
            "key_source": src,
            "wire_model": wire_model(entry),
        }


# ---------------------------------------------------------------- 投影/出参


def _project_channels(
    settings: dict[str, Any],
    connections: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """settings+connections → 合成渠道表（读径投影迁移，不落盘）。

    活动 settings 行映成 id=``default`` 的渠道（model 合 settings.model
    与同槽 slot.model 去重）；connections 其余槽位各映一条，id 取
    ``_stable_id`` 派生（同端点恒同 id）。合成表的 models 允许为空。
    """
    channels: list[dict[str, Any]] = []
    active_url = str(settings.get("base_url") or "")
    slot = (
        connections.get(active_url)
        or connections.get(normalize_base_url(active_url))
        or {}
    )
    models = [
        {"model": m, "redirect_model": "", "enabled": True, "max_concurrency": None}
        for m in _dedupe_keep(
            [str(settings.get("model") or ""), str(slot.get("model") or "")]
        )
    ]
    channels.append(
        {
            "id": "default",
            "name": _name_for(active_url),
            "preset": _preset_for_url(active_url),
            "base_url": active_url,
            "protocol": str(settings.get("dialect") or slot.get("dialect") or "auto"),
            "models": models,
            "priority": (len(connections) + 1) * PRIORITY_STEP,
            "max_concurrency": None,
            "enabled": True,
            "api_key": str(settings.get("api_key") or slot.get("api_key") or ""),
            "key_env": "",
            "last_probe": None,
        }
    )
    for idx, (url, cslot) in enumerate(connections.items()):
        if normalize_base_url(url) == normalize_base_url(active_url):
            continue
        channels.append(
            {
                "id": _stable_id(url),
                "name": _name_for(url),
                "preset": _preset_for_url(url),
                "base_url": url,
                "protocol": str(cslot.get("dialect") or "auto"),
                "models": [
                    {
                        "model": m,
                        "redirect_model": "",
                        "enabled": True,
                        "max_concurrency": None,
                    }
                    for m in _dedupe_keep([str(cslot.get("model") or "")])
                ],
                "priority": (len(connections) - idx) * PRIORITY_STEP,
                "max_concurrency": None,
                "enabled": True,
                "api_key": str(cslot.get("api_key") or ""),
                "key_env": "",
                "last_probe": None,
            }
        )
    return channels[:MAX_CHANNELS]


def _dedupe_keep(items: list[str]) -> list[str]:
    """Strip + 去空 + 去重保序（投影合成用，不走 validate_model——槽位值已是校验过的）。"""
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        m = item.strip()
        if m and m not in seen:
            seen.add(m)
            out.append(m)
    return out


def active_channel_id(channels: list[dict[str, Any]], settings: dict[str, Any]) -> str:
    """路由视角的活动渠道 id：``settings.base_url`` 归一命中者（兼容旧 UI/报告面）。

    enabled 无关——活动身份是定位不是参与。无命中 → ``""``。
    """
    target = normalize_base_url(str(settings.get("base_url") or ""))
    for c in channels:
        if normalize_base_url(str(c.get("base_url") or "")) == target:
            return str(c["id"])
    return ""


def public_channel(c: dict[str, Any]) -> dict[str, Any]:
    """Channel → API 出参面：key 值绝不出叶，只报 has_api_key/env 名/env 是否已设置。"""
    key_env = str(c.get("key_env") or "")
    return {
        "id": c["id"],
        "name": c["name"],
        "preset": c["preset"],
        "base_url": c["base_url"],
        "protocol": c["protocol"],
        "models": copy.deepcopy(c["models"]),
        "priority": int(c["priority"]),
        "max_concurrency": c.get("max_concurrency"),
        "enabled": bool(c["enabled"]),
        "has_api_key": bool(c.get("api_key")),
        "key_env": key_env,
        "has_env_key": bool(key_env and env_raw(key_env)),
        "last_probe": copy.deepcopy(c.get("last_probe")),
    }


def credential_for(
    channel: dict[str, Any],
    connections: dict[str, dict[str, str]],
) -> tuple[str, str]:
    """Channel → ``(api_key, source)`` 四级凭据阶梯：inline > key_env > connections 槽 > provider env。

    worker 回退链各臂按自家 base_url 走本阶梯——``ctx.secrets.api_key``
    绝不跨端点发送（exfil 墙）。``source`` 记档值（``channel``/
    ``env:<NAME>``/``connection``/``provider_env``/``none``）供
    warning/日志归因，key 本体不进日志。
    """
    key = str(channel.get("api_key") or "")
    if key:
        return key, "channel"
    env_name = str(channel.get("key_env") or "")
    if env_name:
        key = env_raw(env_name)
        if key:
            return key, f"env:{env_name}"
    base_url = str(channel.get("base_url") or "")
    slot = (
        connections.get(base_url) or connections.get(normalize_base_url(base_url)) or {}
    )
    key = str(slot.get("api_key") or "")
    if key:
        return key, "connection"
    key = env_key_for_url(base_url)
    if key:
        return key, "provider_env"
    return "", "none"


# ---------------------------------------------------------------- 两段探针


def _red(text: str, api_key: str) -> str:
    """Detail 字段统一脱敏 + 截断。"""
    return scrub(text, api_key)[:300]


def _transport_verdict(e: ChatError) -> str:
    """传输错误（status<0）细分：超时 vs 其余不可达。"""
    text = str(e).lower()
    return "timeout" if "timed out" in text or "timeout" in text else "unreachable"


def _probe_error_verdict(e: Exception, api_key: str) -> tuple[str, str]:
    """段2 异常 → ``(verdict, detail)``：ChatError 分类学映射 + 传输细分。"""
    raw = str(e) if isinstance(e, ChatError) else f"{type(e).__name__}: {e}"
    detail = _red(raw, api_key)
    if isinstance(e, ContentFilterError):
        return "refused", detail
    if isinstance(e, AuthError):
        return "auth_failed", detail
    if isinstance(e, RetryableHTTPError) and e.status < 0:
        return _transport_verdict(e), detail
    return "http_error", detail


def _content_verdict(content: str) -> str:
    """段2 应答正文判级：空 → 占位符完整性 → CJK 命中 → usable。"""
    if not content.strip():
        return "empty"
    if any(tok not in content for tok in _PROBE_TOKENS):
        return "placeholder_lost"
    if not _CJK_RX.search(content):
        return "no_cjk"
    return "usable"


async def _probe_model_chat(
    client: ChatClient,
    uid: str,
    listed: set[str] | None,
) -> dict[str, Any]:
    """段2 单模型行为探：``probe_chat`` 直发（绕开 ``chat`` 降级臂）+ 占位符/CJK 双判。"""
    t0 = time.monotonic()
    detail = ""
    try:
        r = await client.probe_chat(
            uid,
            [{"role": "user", "content": PROBE_SENTENCE}],
            ChatOptions(temperature=0.0, max_tokens=PROBE_MAX_TOKENS),
            req_timeout=PROBE_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001 -- 探针对任意失败返 verdict 绝不抛出
        verdict, detail = _probe_error_verdict(e, client.api_key)
    else:
        verdict = _content_verdict(r.content)
        if r.finish_reason == "length" and verdict == "usable":
            detail = f"finish=length（{PROBE_MAX_TOKENS}tok 截断——探句短，仍判 usable）"
    return {
        "verdict": verdict,
        "latency_s": round(time.monotonic() - t0, 2),
        "detail": detail,
        "listed": None if listed is None else uid in listed,
    }


async def probe_channel(
    base_url: str,
    api_key: str,
    protocol: str,
    models: list[dict[str, Any]],
) -> dict[str, Any]:
    """两段行为探针 → ``last_probe`` 报告 dict（key_fp 按所给已决议 key 记）。

    段1 ``list_models`` 判端点形态：``ok``/``no_models_dir``/``auth_failed``
    /``unreachable``/``timeout``/``http_error``。段2 逐模型 ``probe_chat``
    行为判（并发 4）：``usable``/``placeholder_lost``/``no_cjk``/``empty``
    /``refused``/``auth_failed``/``http_error``/``timeout``/``unreachable``；
    段1 属 ``_STAGE2_SKIP`` 时整段跳（各模型记 ``skipped``）。

    ``models`` 条目请求按 ``wire_model``（redirect 优先）发到上游，
    ``listed`` 判定也对线上名（上游清单只认线上名）；报告 ``models``
    的键一律是渠道内模型名。
    """
    client = ChatClient(base_url=base_url, api_key=api_key, dialect=protocol or "auto")
    report: dict[str, Any] = {
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
        "key_fp": _key_fp(api_key),
        "stage1": {"verdict": "unreachable", "models": [], "detail": ""},
        "models": {},
    }
    try:
        listed: set[str] | None = None
        try:
            ids = await client.list_models()
        except AuthError as e:
            report["stage1"] = {
                "verdict": "auth_failed",
                "models": [],
                "detail": _red(str(e), api_key),
            }
        except (EndpointNotFoundError, MalformedResponseError) as e:
            report["stage1"] = {
                "verdict": "no_models_dir",
                "models": [],
                "detail": _red(str(e), api_key),
            }
        except RetryableHTTPError as e:
            verdict = _transport_verdict(e) if e.status < 0 else "http_error"
            report["stage1"] = {
                "verdict": verdict,
                "models": [],
                "detail": _red(str(e), api_key),
            }
        except ChatError as e:
            report["stage1"] = {
                "verdict": "http_error",
                "models": [],
                "detail": _red(str(e), api_key),
            }
        except Exception as e:  # noqa: BLE001 -- 同段2：探针绝不抛出
            report["stage1"] = {
                "verdict": "unreachable",
                "models": [],
                "detail": _red(f"{type(e).__name__}: {e}", api_key),
            }
        else:
            report["stage1"] = {
                "verdict": "ok",
                "models": ids[:_STAGE1_MODELS_MAX],
                "detail": "",
            }
            listed = set(ids)

        if report["stage1"]["verdict"] in _STAGE2_SKIP:
            for entry in models:
                report["models"][local_model_name(entry)] = {
                    "verdict": "skipped",
                    "latency_s": 0.0,
                    "detail": "",
                    "listed": None,
                }
            return report

        sem = asyncio.Semaphore(_PROBE_CONCURRENCY)

        async def _one(entry: dict[str, Any]) -> tuple[str, dict[str, Any]]:
            async with sem:
                return local_model_name(entry), await _probe_model_chat(
                    client, wire_model(entry), listed
                )

        rows = await asyncio.gather(
            *(_one(entry) for entry in models[:MAX_MODELS_PER_CHANNEL])
        )
        report["models"] = dict(rows)
        return report
    finally:
        await client.aclose()
