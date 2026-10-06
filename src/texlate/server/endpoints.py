"""端点档案数据层 —— ``endpoints.json`` store + 两段行为探针 + 凭据阶梯。

``routers/endpoints.py``（HTTP 面）/``cli/endpoints.py``（命令行面）同名异义
——本叶是三方共享的数据/探测单源（glossary §3 登记）。

文件契约 ``{version: 1, profiles: [...]}``（0600 原子写）；profile =
``{id, label, base_url, dialect, models[], enabled, api_key|key_env, last_probe}``：

- ``api_key`` 与 ``key_env`` 互斥；写径 ``api_key=""`` 保留同 id 旧值
  （settings.save 同口径），一方显式写入即清另一方（凭据形态切换）。
- ``key_env`` 存 env 变量**名**不存值——轮换 key 只改环境，档案零改写；
  ``resolve_auth`` 经 ``key_env_for`` 查名读值，server 任何出参只见名不见值。
- ``last_probe`` 服务端独占（PUT 载荷里该键忽略）：端点面
  （base_url/dialect/models）与 key 指纹双未变才跨写保留。
- 文件缺席时 ``effective_profiles`` 把 settings+connections **读径投影**
  成合成 profile 表（id=``default`` + 每 connections 槽一条）——迁移
  不落盘，首个 PUT 才物化。
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
    AuthError,
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

ENDPOINTS_FILE = "endpoints.json"
SCHEMA_VERSION = 1
MAX_PROFILES = 16
MAX_MODELS_PER_PROFILE = 8
LABEL_MAX_LEN = 48

_ID_RX = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
_KEY_ENV_RX = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,63}")

# ---------------------------------------------------------------- 行为探针

#: 占位符完整性探句——`[[X_N]]` 三枚 token 必须原样存活于译文（译中丢
#: 占位符 = splice 回插静默腐蚀，比翻译质量差更致命，单独判级）
PROBE_SENTENCE = (
    "Translate the following English sentence into Simplified Chinese. "
    "Output the translation only and preserve every [[X_N]] placeholder "
    "byte-identically.\n\n"
    "The [[MATH_1]] norm satisfies [[MATH_2]] \\le 1; see [[CITE_1]]."
)
PROBE_TIMEOUT = httpx.Timeout(20.0, connect=8.0)
PROBE_MAX_TOKENS = 256
_PROBE_CONCURRENCY = 4
_PROBE_TOKENS = ("[[MATH_1]]", "[[MATH_2]]", "[[CITE_1]]")
_CJK_RX = re.compile(r"[一-鿿]")
#: 段1 报告里的模型清单截断（OpenRouter 类端点 /v1/models 可 200+ 条——
#: 报告是 UX 面不是镜像，全量无意义）
_STAGE1_MODELS_MAX = 50
#: 段2 整体跳过集：list 已证鉴权死/传输死 → 逐模型再试只是放大失败数
_STAGE2_SKIP = frozenset({"auth_failed", "unreachable", "timeout"})


# ---------------------------------------------------------------- 校验件


def _check_id(value: object) -> str:
    """Profile id：小写 slug（``[a-z0-9][a-z0-9-]{0,31}``），URL/文件名片段安全。"""
    if not isinstance(value, str) or not _ID_RX.fullmatch(value):
        msg = "profile id 须为 [a-z0-9][a-z0-9-]{0,31} slug"
        raise ValueError(msg)
    return value


def _check_label(value: object) -> str:
    """Label：可打印、≤48 字符、strip；缺席/空 → ``""``（调用方回兜底名）。"""
    if value is None:
        return ""
    if not isinstance(value, str):
        msg = "label 须为 string"
        raise TypeError(msg)
    v = value.strip()
    if len(v) > LABEL_MAX_LEN or not v.isprintable():
        msg = f"label 须为可打印且 ≤{LABEL_MAX_LEN} 字符"
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


def _check_models(value: object) -> list[str]:
    """Models：string list、逐条 ``validate_model``、去重保序、≤8；None → []。"""
    if value is None:
        return []
    if not isinstance(value, list):
        msg = "models 须为 string list"
        raise TypeError(msg)
    seen: set[str] = set()
    out: list[str] = []
    for m in value:
        if not isinstance(m, str):
            msg = "models 成员须为 string"
            raise TypeError(msg)
        uid = validate_model(m)
        if uid not in seen:
            seen.add(uid)
            out.append(uid)
    if len(out) > MAX_MODELS_PER_PROFILE:
        msg = f"models 至多 {MAX_MODELS_PER_PROFILE} 条"
        raise ValueError(msg)
    return out


def _key_fp(api_key: str) -> str:
    """Key → sha256 前 8 hex 指纹（``last_probe`` 有效性对账；空 key → ``""``）。"""
    return hashlib.sha256(api_key.encode()).hexdigest()[:8] if api_key else ""


def _label_for(base_url: str) -> str:
    """空 label 兜底名：provider 名；custom 端点取 host。"""
    provider = provider_for_url(base_url)
    if provider != "custom":
        return provider
    try:
        host = urlsplit(base_url).hostname or ""
    except ValueError:
        host = ""
    return host or "endpoint"


def _slug_for(base_url: str, taken: set[str]) -> str:
    """base_url → 唯一 profile id：provider 名优先，custom 取 host slug，撞名加 ``-N``。"""
    provider = provider_for_url(base_url)
    if provider != "custom":
        base = provider
    else:
        try:
            host = (urlsplit(base_url).hostname or "").lower()
        except ValueError:
            host = ""
        base = re.sub(r"[^a-z0-9]+", "-", host).strip("-") or "endpoint"
    # 留 -NN 后缀余量，slug 主体 ≤24
    base = base[:24].strip("-") or "endpoint"
    candidate, n = base, 2
    while candidate in taken:
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def _quarantine(path: Path, why: str, *args: object) -> None:
    """损坏文件改名隔离（xlat.state 同口径）：``*-invalid-<rand>`` 兄弟名 + warn，不删。"""
    bad = path.with_name(f"{path.stem}-invalid-{secrets.token_hex(4)}{path.suffix}")
    path.rename(bad)
    log.warning(why, *args, bad.name)


# ---------------------------------------------------------------- 归一化


def _load_profile(raw: object) -> dict[str, Any] | None:
    """读径容错归一：坏成员整 profile 丢弃（None），不让一条手改烂行炸穿全表。"""
    if not isinstance(raw, dict):
        return None
    try:
        pid = _check_id(raw.get("id"))
        base_url = validate_base_url(str(raw.get("base_url") or ""))
        dialect = validate_dialect(str(raw.get("dialect") or "auto"))
        models = _check_models(raw.get("models"))
        label = _check_label(raw.get("label"))
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
        "label": label or _label_for(base_url),
        "base_url": base_url,
        "dialect": dialect,
        "models": models,
        "enabled": bool(raw.get("enabled", True)),
        "api_key": api_key,
        "key_env": key_env,
        "last_probe": last_probe,
    }


def _normalize_write(
    raw: object, existing_by_id: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """写径严格归一（PUT 语义）：全字段校验 + 凭据互斥/保留合并 + last_probe 继承。

    凭据合并规则：``api_key``/``key_env`` 同时显式非空 → 400 级 ValueError；
    单方显式非空 → 清另一方（形态切换）；双方缺省/空串 → 承旧值
    （``api_key=""`` 不覆盖的 settings.save 口径，key_env 同）。
    ``last_probe`` 服务端独占：仅当端点面（base_url/dialect/models）与
    有效 key 指纹均未变才从旧档继承。
    """
    if not isinstance(raw, dict):
        msg = "profile 须为 object"
        raise TypeError(msg)
    pid = _check_id(raw.get("id"))
    existing = existing_by_id.get(pid)
    base_url = validate_base_url(str(raw.get("base_url") or ""))
    dialect = validate_dialect(str(raw.get("dialect") or "auto"))
    models = _check_models(raw.get("models"))
    label = _check_label(raw.get("label")) or _label_for(base_url)
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
        msg = "api_key 与 key_env 互斥——同 profile 只能带一种凭据引用"
        raise ValueError(msg)
    old_key = str(existing.get("api_key") or "") if existing else ""
    old_env = str(existing.get("key_env") or "") if existing else ""
    api_key = api_in or old_key
    key_env = _check_key_env(env_in) if env_in else old_env
    if env_in:
        api_key = ""  # 显式 key_env 覆盖存量 inline key（凭据形态切换）
    if api_in:
        key_env = ""  # 显式 api_key 覆盖存量 env 引用

    profile: dict[str, Any] = {
        "id": pid,
        "label": label,
        "base_url": base_url,
        "dialect": dialect,
        "models": models,
        "enabled": enabled,
        "api_key": api_key,
        "key_env": key_env,
        "last_probe": None,
    }
    last = existing.get("last_probe") if existing else None
    if (
        isinstance(last, dict)
        and base_url == existing.get("base_url")
        and dialect == existing.get("dialect")
        and models == existing.get("models")
        and last.get("key_fp") == _key_fp(api_key or env_raw(key_env))
    ):
        profile["last_probe"] = last
    return profile


def _dedupe_ids(profiles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """读径 id 去重（先见赢）+ 数量封顶。"""
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for p in profiles:
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        out.append(p)
    return out[:MAX_PROFILES]


# ---------------------------------------------------------------- store


class EndpointStore:
    """``endpoints.json``（0600）端点档案 store——``SettingsStore`` 同套机制。

    ``settings.json``/``connections.json`` 之外的第三块凭据面：多 profile
    端点档案（BYOK 库），worker 跨端点回退链与路由层探针的报告位。
    mtime 标记缓存 + 深拷贝出参 + 损坏 quarantine——全照 SettingsStore 口径。
    """

    def __init__(self, root: Path) -> None:
        """Root = 数据目录（与 ``settings.json`` 同根，已 0700 建妥）。"""
        self.root = root
        self.path = root / ENDPOINTS_FILE
        self._save_lock = threading.Lock()
        self._load_cache: tuple[tuple[int, int] | None, dict[str, Any]] | None = None
        self._load_lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        """读 endpoints.json → ``{"version":1,"profiles":[...]}``（深拷贝出参）。

        缺席 → 空表；JSON 损坏 → quarantine 隔离 + 空表；version 非法 →
        warn + 空表（不改名——高版本文件留给能读它的新进程）；逐 profile
        容错过滤，坏成员只丢自己。
        """
        try:
            st = self.path.stat()
            sig: tuple[int, int] | None = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig = None  # 缺席也按标记缓存——缺席是常态（未建档案）
        with self._load_lock:
            if self._load_cache is not None and self._load_cache[0] == sig:
                return copy.deepcopy(self._load_cache[1])
            data: dict[str, Any] = {"version": SCHEMA_VERSION, "profiles": []}
            if sig is not None:
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                except (
                    OSError,
                    UnicodeDecodeError,
                    json.JSONDecodeError,
                    RecursionError,
                ) as e:
                    _quarantine(
                        self.path, "endpoints.json 损坏（%s）→ quarantined as %s", e
                    )
                else:
                    if isinstance(raw, dict) and raw.get("version") == SCHEMA_VERSION:
                        items = raw.get("profiles")
                        items = items if isinstance(items, list) else []
                        data["profiles"] = _dedupe_ids(
                            [
                                p
                                for p in (_load_profile(i) for i in items)
                                if p is not None
                            ]
                        )
                    else:
                        log.warning(
                            "endpoints.json version 非法（%s）→ 按空表处理",
                            raw.get("version")
                            if isinstance(raw, dict)
                            else type(raw).__name__,
                        )
            self._load_cache = (sig, data)
            return copy.deepcopy(data)

    def save(self, profiles: list[object]) -> list[dict[str, Any]]:
        """整表替换写（PUT 语义）：逐条严格校验 → 0600 原子写；返回归一化表。"""
        with self._save_lock:
            if not isinstance(profiles, list):
                msg = "profiles 须为 list"
                raise TypeError(msg)
            if len(profiles) > MAX_PROFILES:
                msg = f"profiles 至多 {MAX_PROFILES} 条"
                raise ValueError(msg)
            existing = {p["id"]: p for p in self.load()["profiles"]}
            out: list[dict[str, Any]] = []
            seen: set[str] = set()
            for raw in profiles:
                p = _normalize_write(raw, existing)
                if p["id"] in seen:
                    msg = f"profile id 重复：{p['id']}"
                    raise ValueError(msg)
                seen.add(p["id"])
                out.append(p)
            # UTF-8 预探雷（settings._save 同口径）——atomic_json 半路炸
            # 会留半写文件；先序列化探雷，炸了按非法更新处理磁盘零写
            try:
                json.dumps(out, ensure_ascii=False).encode("utf-8")
            except UnicodeEncodeError as e:
                msg = "endpoints 含不可编码字符"
                raise ValueError(msg) from e
            atomic_json(self.path, {"version": SCHEMA_VERSION, "profiles": out})
            self.path.chmod(0o600)
            with self._load_lock:
                self._load_cache = None
            return copy.deepcopy(out)

    def record_probe(self, profile_id: str, report: dict[str, Any]) -> None:
        """把探针报告钉到指定 profile 的 ``last_probe``；文件缺席/id 无命中 → no-op。

        只动该键不重校验整表——load 归一化面已滤过坏成员。
        """
        with self._save_lock:
            data = self.load()
            hit = next((p for p in data["profiles"] if p["id"] == profile_id), None)
            if hit is None:
                return
            hit["last_probe"] = report
            atomic_json(self.path, data)
            self.path.chmod(0o600)
            with self._load_lock:
                self._load_cache = None

    # ------------------------------------------------------------ 读径投影/查找

    def effective_profiles(
        self,
        settings: dict[str, Any],
        connections: dict[str, dict[str, str]],
    ) -> list[dict[str, Any]]:
        """当前有效 profile 集：文件在 → 归一化文件表；缺席 → 投影合成（不落盘）。"""
        if self.path.exists():
            return self.load()["profiles"]
        return _project_profiles(settings, connections)

    def key_env_for(self, base_url: str) -> str:
        """base_url 命中 profile 的 ``key_env`` 名；无命中 → ``""``。

        enabled 无关——凭据元数据不是参与身份（disabled profile 的 env 名
        照样是合法 key 源）。``resolve_auth`` env 层的查名钩。
        """
        target = normalize_base_url(base_url)
        for p in self.load()["profiles"]:
            if normalize_base_url(str(p.get("base_url") or "")) == target:
                return str(p.get("key_env") or "")
        return ""


# ---------------------------------------------------------------- 投影/出参


def _project_profiles(
    settings: dict[str, Any],
    connections: dict[str, dict[str, str]],
) -> list[dict[str, Any]]:
    """settings+connections → 合成 profile 表（读径投影迁移，不落盘）。

    活动 settings 行映成 id=``default`` 的 profile（model 合 settings.model
    与同槽 slot.model 去重）；connections 其余槽位各映一条，id 取
    provider/host slug。合成表的 models 允许为空（槽位没记过 model）——
    activate/探针按空表自然处理。
    """
    profiles: list[dict[str, Any]] = []
    taken = {"default"}
    active_url = str(settings.get("base_url") or "")
    slot = (
        connections.get(active_url)
        or connections.get(normalize_base_url(active_url))
        or {}
    )
    models = _dedupe_keep(
        [str(settings.get("model") or ""), str(slot.get("model") or "")]
    )
    profiles.append(
        {
            "id": "default",
            "label": _label_for(active_url),
            "base_url": active_url,
            "dialect": str(settings.get("dialect") or slot.get("dialect") or "auto"),
            "models": models,
            "enabled": True,
            "api_key": str(settings.get("api_key") or slot.get("api_key") or ""),
            "key_env": "",
            "last_probe": None,
        }
    )
    for url, cslot in connections.items():
        if normalize_base_url(url) == normalize_base_url(active_url):
            continue
        pid = _slug_for(url, taken)
        taken.add(pid)
        profiles.append(
            {
                "id": pid,
                "label": _label_for(url),
                "base_url": url,
                "dialect": str(cslot.get("dialect") or "auto"),
                "models": _dedupe_keep([str(cslot.get("model") or "")]),
                "enabled": True,
                "api_key": str(cslot.get("api_key") or ""),
                "key_env": "",
                "last_probe": None,
            }
        )
    return profiles[:MAX_PROFILES]


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


def active_id(profiles: list[dict[str, Any]], settings: dict[str, Any]) -> str:
    """活动 profile id：首个 base_url 归一后与 ``settings.base_url`` 一致者。

    enabled 无关——活动身份是定位不是参与（disabled 的活动 profile 仍
    是活动 profile，只是不参与回退链）。无命中 → ``""``。
    """
    target = normalize_base_url(str(settings.get("base_url") or ""))
    for p in profiles:
        if normalize_base_url(str(p.get("base_url") or "")) == target:
            return str(p["id"])
    return ""


def public_profile(p: dict[str, Any]) -> dict[str, Any]:
    """Profile → API 出参面：key 值绝不出叶，只报 has_api_key/env 名/env 是否已设置。"""
    key_env = str(p.get("key_env") or "")
    return {
        "id": p["id"],
        "label": p["label"],
        "base_url": p["base_url"],
        "dialect": p["dialect"],
        "models": list(p["models"]),
        "enabled": bool(p["enabled"]),
        "has_api_key": bool(p.get("api_key")),
        "key_env": key_env,
        "has_env_key": bool(key_env and env_raw(key_env)),
        "last_probe": copy.deepcopy(p.get("last_probe")),
    }


def credential_for(
    profile: dict[str, Any],
    connections: dict[str, dict[str, str]],
) -> tuple[str, str]:
    """Profile → ``(api_key, source)`` 四级凭据阶梯：inline > key_env > connections 槽 > provider env。

    worker 回退链各臂按自家 base_url 走本阶梯——``ctx.secrets.api_key``
    绝不跨端点发送（exfil 墙）。``source`` 记档值（``profile``/
    ``env:<NAME>``/``connection``/``provider_env``/``none``）供
    warning/日志归因，key 本体不进日志。
    """
    key = str(profile.get("api_key") or "")
    if key:
        return key, "profile"
    env_name = str(profile.get("key_env") or "")
    if env_name:
        key = env_raw(env_name)
        if key:
            return key, f"env:{env_name}"
    base_url = str(profile.get("base_url") or "")
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
            detail = "finish=length（256tok 截断——探句短，仍判 usable）"
    return {
        "verdict": verdict,
        "latency_s": round(time.monotonic() - t0, 2),
        "detail": detail,
        "listed": None if listed is None else uid in listed,
    }


async def probe_endpoint(
    base_url: str,
    api_key: str,
    dialect: str,
    models: list[str],
) -> dict[str, Any]:
    """两段行为探针 → ``last_probe`` 报告 dict（key_fp 按所给已决议 key 记）。

    段1 ``list_models`` 判端点形态：``ok``（拿到清单）/``no_models_dir``
    （404/畸形——异形端点不提供模型目录，段2 照跑）/``auth_failed``
    /``unreachable``/``timeout``/``http_error``。段2 逐模型 ``probe_chat``
    行为判（并发 4）：``usable``/``placeholder_lost``/``no_cjk``/``empty``
    /``refused``/``auth_failed``/``http_error``/``timeout``/``unreachable``；
    段1 属 ``_STAGE2_SKIP`` 时整段跳（各模型记 ``skipped``）。
    """
    client = ChatClient(base_url=base_url, api_key=api_key, dialect=dialect or "auto")
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
            for uid in models:
                report["models"][uid] = {
                    "verdict": "skipped",
                    "latency_s": 0.0,
                    "detail": "",
                    "listed": None,
                }
            return report

        sem = asyncio.Semaphore(_PROBE_CONCURRENCY)

        async def _one(uid: str) -> tuple[str, dict[str, Any]]:
            async with sem:
                return uid, await _probe_model_chat(client, uid, listed)

        rows = await asyncio.gather(
            *(_one(uid) for uid in models[:MAX_MODELS_PER_PROFILE])
        )
        report["models"] = dict(rows)
        return report
    finally:
        await client.aclose()
