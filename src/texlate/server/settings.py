"""BYOK 与本地设置层（web-layer.md §4）。

key 入口优先级（高→低）：请求头 ``X-Texlate-*`` > ``settings.json``（0600）
> 环境变量。key 只进内存任务对象，绝不进 tasks/files/日志；``tenant`` 用
``sha256(key+server_salt)[:12]`` 指纹隔离（单机模式恒 ``local``）。

四层不落日志防线：异常边界 ``redact()`` 先过、根 logger 挂
:class:`RedactFilter` 同款正则 scrub、API 出参只给 ``has_api_key``、
``validate_base_url`` 拒 userinfo/query + 非 localhost/tailnet 强制 https。
"""

from __future__ import annotations

import contextlib
import hashlib
import ipaddress
import json
import logging
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

from texlate.xlat.client import (
    _LOOPBACK_HOSTS,
    _TAILNET_V4,
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    PROVIDER_KEY_ENV,
    normalize_base_url,
    provider_for_url,
    redact,
)
from texlate.xlat.state import atomic_json

log = logging.getLogger(__name__)

DEFAULT_TARGET_LANG = "zh-CN"

SETTINGS_FILE = "settings.json"
CONNECTIONS_FILE = "connections.json"
SALT_FILE = "server_salt"

#: 上传/解包上限（texglot 常量，web-layer §2.4）
UPLOAD_CAP = 80 * 1024 * 1024
INFLATED_CAP = 300 * 1024 * 1024
MAX_FILES = 4000

#: 目标语言白名单（M0 只做中译向；UI 表单项）
TARGET_LANGS = frozenset({"zh-CN", "zh-TW", "en"})

#: 模型名长度上限（防滥用长串）
MODEL_MAX_LEN = 200


def _is_plaintext_ok_host(hostname: str) -> bool:
    """HTTP 放行：localhost，或 tailnet 主机（CGNAT 字面量 / ``*.ts.net``）。

    tailnet 放行依据：WireGuard 传输本身已加密，HTTP 不泄密。
    """
    h = hostname.lower()
    if h in _LOOPBACK_HOSTS or h.endswith(".ts.net"):
        return True
    try:
        return ipaddress.ip_address(h) in _TAILNET_V4
    except ValueError:
        return False


def data_dir() -> Path:
    """数据目录：``TEXLATE_DATA_DIR`` > ``~/.texlate``；mkdir 0700。"""
    raw = os.environ.get("TEXLATE_DATA_DIR")
    root = Path(raw).expanduser() if raw else Path.home() / ".texlate"
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def server_mode() -> str:
    """``TEXLATE_MODE``：``local``（默认）| ``server``（多租户部署形态）。"""
    return os.environ.get("TEXLATE_MODE", "local")


def cache_scope() -> str:
    """``TEXLATE_CACHE_SCOPE``：``shared``（默认）| ``per_key``。

    ``shared`` = hjfy 对等共享缓存（既定产品特性：公开论文的翻译结果是
    确定性函数，跨租户 reuse 省下重复 LLM 调用）；``per_key`` 把
    ``sha256(api_key)[:16]`` 混入缓存键按凭证分桶——消除「探测他租户是否
    译过某论文」的存在性 oracle，代价是缓存命中按 key 碎片化。
    旧名 ``tenant`` 同义 ``per_key``；非法值回落 ``shared``。
    """
    v = os.environ.get("TEXLATE_CACHE_SCOPE", "shared").strip().lower()
    if v in ("per_key", "tenant"):
        return "per_key"
    if v != "shared":
        log.warning("TEXLATE_CACHE_SCOPE=%r 非法，回落 shared", v)
    return "shared"


def share_dir(root: Path | None = None) -> Path:
    """共享包发布目录：``TEXLATE_SHARE_DIR`` > ``<root>/share``（root 缺省 ``data_dir()``）。

    worker share 完成钩把 ``{share_key}.share.zip`` + 旁挂 ``index.jsonl``
    落此——指向静态托管/对象存储挂载点即完成发布（shared-cache.md §7
    文件级服务端形态）。惰性建目录（pack/index_append 各自 mkdir parents）。
    """
    raw = os.environ.get("TEXLATE_SHARE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser()
    return (root if root is not None else data_dir()) / "share"


def validate_base_url(value: str) -> str:
    """base_url 校验（texglot ``validate_url`` 移植）。

    拒：userinfo/query/fragment 内嵌、非 localhost/tailnet 的 http。返回归一化串。
    """
    v = value.strip().rstrip("/")
    u = urlsplit(v)
    if (
        u.scheme not in ("https", "http")
        or not u.hostname
        or u.username
        or u.password
        or u.query
        or u.fragment
    ):
        msg = "invalid base_url（不含 userinfo/query/fragment 的裸服务根）"
        raise ValueError(msg)
    if u.scheme == "http" and not _is_plaintext_ok_host(u.hostname):
        msg = "远程 API 强制 HTTPS；仅 localhost 或 tailnet 可用 HTTP"
        raise ValueError(msg)
    return normalize_base_url(v)


def validate_model(value: str) -> str:
    r"""模型名校验：非空、长度上限、不含控制字符。

    控制字符（``\n`` 等）会原样进 ``log.warning``/事件载荷——日志注入面；
    ``isprintable`` 放行空格/CJK/emoji，只挡 C0/C1/分隔符族。
    """
    v = value.strip()
    if not v or len(v) > MODEL_MAX_LEN or not v.isprintable():
        msg = "invalid model（空/超 200 字符/含控制字符）"
        raise ValueError(msg)
    return v


def _check_glossary_dir(value: object) -> str:
    """``glossary_dir`` 校验：空串放行（=仅 workdir 根）；否则须已存在的绝对目录。"""
    raw = str(value or "").strip()
    if not raw:
        return ""
    gdir = Path(raw).expanduser()
    if not gdir.is_absolute():
        msg = "glossary_dir 必须是绝对路径"
        raise ValueError(msg)
    if not gdir.is_dir():
        msg = f"glossary_dir 不存在或不是目录: {gdir}"
        raise ValueError(msg)
    return str(gdir)


def _parse_origin(value: object) -> str | None:
    """CORS origin 归一化：``scheme://host[:port]``；非法形态返 None。"""
    o = str(value or "").strip().rstrip("/")
    if not o:
        return None
    try:
        o.encode("utf-8")
    except UnicodeEncodeError:
        return None
    u = urlsplit(o)
    if (
        u.scheme not in ("http", "https")
        or not u.hostname
        or u.username
        or u.password
        or u.query
        or u.fragment
        or u.path not in ("", "/")
    ):
        return None
    return o


def _check_cors_origins(value: object) -> list[str]:
    """``cors_origins`` 校验：字符串数组逐项过 ``_parse_origin``，去重保序。"""
    if not isinstance(value, list) or not all(isinstance(o, str) for o in value):
        msg = "cors_origins 必须是字符串数组"
        raise ValueError(msg)
    out: list[str] = []
    for raw in value:
        o = _parse_origin(raw)
        if o is None:
            msg = f"invalid cors origin: {raw!r}（须 http(s)://host[:port]）"
            raise ValueError(msg)
        out.append(o)
    return list(dict.fromkeys(out))


def _check_quota(value: object, name: str) -> int:
    """配额字段校验：非负 int（0=不限）。"""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        msg = f"{name} 必须是非负整数"
        raise ValueError(msg) from None
    if n < 0:
        msg = f"{name} 必须是非负整数"
        raise ValueError(msg)
    return n


def _normalize_updates(values: dict[str, Any]) -> None:
    """``save`` 的逐字段归一化/校验（就地改写 ``values``）。"""
    if "base_url" in values:
        values["base_url"] = validate_base_url(str(values["base_url"]))
    if "model" in values:
        values["model"] = validate_model(str(values["model"]))
    if "concurrency" in values:
        values["concurrency"] = max(1, min(16, int(values["concurrency"])))
    if "engine" in values and values["engine"] not in (
        "auto",
        "xelatex",
        "tectonic",
    ):
        msg = "engine ∈ auto|xelatex|tectonic"
        raise ValueError(msg)
    if "target_lang" in values and values["target_lang"] not in TARGET_LANGS:
        msg = f"target_lang ∈ {sorted(TARGET_LANGS)}"
        raise ValueError(msg)
    if "glossary_dir" in values:
        values["glossary_dir"] = _check_glossary_dir(values["glossary_dir"])
    if "cors_origins" in values:
        values["cors_origins"] = _check_cors_origins(values["cors_origins"])
    for q in ("quota_max_tasks", "quota_max_bytes"):
        if q in values:
            values[q] = _check_quota(values[q], q)


# ---------------------------------------------------------------- 设置存储


def _load_origins(value: object) -> list[str]:
    """``cors_origins`` 容错读：非法项记 warning 丢弃（手改文件不炸 load）。"""
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for raw in value:
        o = _parse_origin(raw)
        if o is None:
            log.warning("settings.json cors_origins 非法项已丢弃: %r", raw)
        else:
            out.append(o)
    return list(dict.fromkeys(out))


def _load_str(value: object, default: str) -> str:
    """字符串字段容错读：不可 UTF-8 编码（孤 surrogate）→ 默认。

    损坏文件里的孤 surrogate 若原样透传进 ``merged``，``save()`` 的
    ``atomic_json``（``ensure_ascii=False``）写盘即 ``UnicodeEncodeError``
    ——此后每次 ``save`` 都炸，settings 面永久不可写。回落默认让
    ``load()`` 自愈。
    """
    s = str(value or default)
    try:
        s.encode("utf-8")
    except UnicodeEncodeError:
        return default
    return s


def _load_quota(value: object) -> int:
    """配额字段容错读：非法/负值 → 0（不限）。"""
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0


def _load_concurrency(value: object) -> int:
    """``concurrency`` 容错读：非法值 → 3。

    ``load()`` 其余字段的强转（``str``/``bool``）永不炸——唯一会抛的是
    本项 ``int()``；手改文件留个 ``"abc"`` 会炸穿 ``load()`` 连带全部
    ``_auth``/settings 端点 500，与 ``_load_quota`` 同口径容错回落。
    """
    try:
        return max(1, int(value or 3))
    except (TypeError, ValueError, OverflowError):
        return 3


class SettingsStore:
    """``settings.json``（0600）+ ``connections.json`` 分槽 key 池。

    ``connections.json`` 按 base_url 分槽存 ``{api_key, model}``——切
    endpoint 时各自的 key 都能找回（texglot 模式）。settings 本体不落
    key 进日志/出参；``public()`` 只给 ``has_api_key``。
    """

    FIELDS = (
        "base_url",
        "model",
        "api_key",
        "target_lang",
        "glossary",
        "glossary_dir",
        "concurrency",
        "engine",
        "context_guidance",
        "cors_origins",
        "quota_max_tasks",
        "quota_max_bytes",
    )

    def __init__(self, root: Path) -> None:
        """Root = 数据目录（已 0700 建妥）。"""
        self.root = root
        self.path = root / SETTINGS_FILE
        self.connections_path = root / CONNECTIONS_FILE

    def load(self) -> dict[str, Any]:
        """读 settings.json；缺席/损坏回落默认。"""
        data: dict[str, Any] = {}
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    data = {k: raw[k] for k in self.FIELDS if k in raw}
            except (OSError, json.JSONDecodeError) as e:
                log.warning("settings.json 损坏（%s）→ 用默认值", e)
        return {
            "base_url": _load_str(data.get("base_url"), DEFAULT_BASE_URL),
            "model": _load_str(data.get("model"), DEFAULT_MODEL),
            "api_key": _load_str(data.get("api_key"), ""),
            "target_lang": _load_str(data.get("target_lang"), DEFAULT_TARGET_LANG),
            "glossary": _load_str(data.get("glossary"), ""),
            "glossary_dir": _load_str(data.get("glossary_dir"), ""),
            "concurrency": _load_concurrency(data.get("concurrency")),
            "engine": _load_str(data.get("engine"), "auto"),
            "context_guidance": bool(data.get("context_guidance", True)),
            "cors_origins": _load_origins(data.get("cors_origins")),
            "quota_max_tasks": _load_quota(data.get("quota_max_tasks")),
            "quota_max_bytes": _load_quota(data.get("quota_max_bytes")),
        }

    def save(self, updates: dict[str, Any]) -> dict[str, Any]:
        """合并更新 → 校验 → 0600 原子写 + connections 分槽同步。

        ``api_key`` 传空串不覆盖旧值；``clear_api_key=True`` 显式清。
        base_url 变更时从 connections 槽找回该 endpoint 的历史 key
        （texglot merge_settings 语义）。
        """
        old = self.load()
        values = dict(updates)
        values.pop("has_api_key", None)
        clear_key = bool(values.pop("clear_api_key", False))
        _normalize_updates(values)
        if not values.get("api_key"):
            values.pop("api_key", None)
        merged = old | values
        if "api_key" not in values and merged["base_url"] != old["base_url"]:
            # 换 endpoint 未带 key → 找回新 endpoint 槽位历史 key。
            # 只改 merged——old 动不得：下方 conns 回写按 cfg.base_url
            # 分槽，old.api_key 若被换成新 endpoint 的 key，旧槽会被
            # 错写（切回旧 endpoint 时把新 key 发给它）。
            merged["api_key"] = (
                self.connections().get(str(merged["base_url"]), {}).get("api_key") or ""
            )
        if clear_key:
            merged["api_key"] = ""
        conns = self.connections()
        for cfg in (old, merged):
            conns.pop(cfg["base_url"], None)
            conns[cfg["base_url"]] = {
                "api_key": cfg["api_key"],
                "model": cfg["model"],
            }
        # 预检：任一值不可 UTF-8 编码（孤 surrogate）时 atomic_json 会在
        # connections 已写、settings 未写之间炸 → 文件对半更新。先序列化
        # 探雷，炸了按非法更新处理，磁盘零写。
        try:
            json.dumps(conns, ensure_ascii=False).encode("utf-8")
            json.dumps(merged, ensure_ascii=False).encode("utf-8")
        except UnicodeEncodeError as e:
            msg = "settings 含不可编码字符"
            raise ValueError(msg) from e
        atomic_json(self.connections_path, conns)
        self.connections_path.chmod(0o600)
        atomic_json(self.path, merged)
        self.path.chmod(0o600)
        return merged

    def connections(self) -> dict[str, dict[str, str]]:
        """``connections.json`` → ``{base_url: {api_key, model}}``。"""
        if not self.connections_path.exists():
            return {}
        try:
            data = json.loads(self.connections_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(data, dict):
            return {}
        out: dict[str, dict[str, str]] = {}
        for k, v in data.items():
            if not isinstance(v, dict):
                continue
            try:
                json.dumps(v, ensure_ascii=False).encode("utf-8")
            except UnicodeEncodeError:
                log.warning("connections.json 槽位含不可编码值已丢弃: %r", k)
                continue
            out[str(k)] = dict(v)
        return out

    def public(self) -> dict[str, Any]:
        """出参形态：剥 key 本体 + ``has_api_key``（§4.2 第三道防线）。"""
        data = self.load()
        data["has_api_key"] = bool(data.pop("api_key"))
        return data


# ---------------------------------------------------------------- BYOK 解析


def env_key_for(base_url: str) -> str:
    """按 provider 映射读 env key：``TEXLATE_API_KEY`` 优先，然后按 host 兜底。"""
    direct = os.environ.get("TEXLATE_API_KEY", "")
    if direct:
        return direct
    env_name = PROVIDER_KEY_ENV.get(provider_for_url(base_url), "TEXLATE_API_KEY")
    return os.environ.get(env_name, "")


def env_base_url() -> str:
    """``TEXLATE_BASE_URL`` env 兜底（未配置返回空）。。"""
    return os.environ.get("TEXLATE_BASE_URL", "").strip()


def env_model() -> str:
    """``TEXLATE_MODEL`` env 兜底。"""
    return os.environ.get("TEXLATE_MODEL", "").strip()


def server_salt(root: Path) -> str:
    """租户指纹盐：``server_salt`` 文件 0600，首跑生成。

    空/全空白文件视为未初始化——空盐下 ``tenant_for`` 退成裸
    ``sha256(key)``，已知 key 可预计算租户指纹，弱化隔离意义。
    """
    path = root / SALT_FILE
    if path.exists():
        try:
            salt = path.read_text(encoding="utf-8").strip()
        except OSError:
            salt = ""
        if salt:
            return salt
    salt = secrets.token_hex(16)
    path.write_text(salt, encoding="utf-8")
    path.chmod(0o600)
    return salt


@dataclass(frozen=True, slots=True)
class AuthContext:
    """一次请求解析出的有效凭证（只在内存里活过任务生命周期）。

    ``source`` ∈ ``header | settings | env | none``——任务行记
    ``auth_source``，重启恢复时 header 源任务转 ``needs_auth``。
    """

    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    source: str = "none"
    tenant: str = "local"
    settings: dict[str, Any] = field(default_factory=dict)


def tenant_for(api_key: str, *, mode: str, salt: str) -> str:
    """租户指纹：local 模式恒 ``local``；server 模式 ``k_+sha256(key+salt)[:12]``。

    key 不入库、指纹入库（§4.3）；server 模式无 key 请求归入匿名桶。
    """
    if mode != "server":
        return "local"
    return "k_" + hashlib.sha256((api_key + salt).encode()).hexdigest()[:12]


def resolve_auth(  # noqa: PLR0913 -- header/base_url/model/mode/salt 即决议面
    settings: dict[str, Any],
    *,
    header_key: str = "",
    header_base_url: str = "",
    header_model: str = "",
    mode: str = "local",
    salt: str = "",
) -> AuthContext:
    """三级回落：header > settings > env（每项独立回落，texglot 同款）。

    ``auth_source`` 由 key 的来源决定（key 才是重启续跑的关键物）；
    header key 校验失败后不落 settings 兜底——显式覆盖语义。
    server 形态例外：无 header key 时 key 不回落 settings/env——匿名
    桶永不携带部署方凭据（匿名 mutation 由 app 中间件 401 挡死，读面
    也绝不外借 key）。
    """
    base_url = settings["base_url"] or DEFAULT_BASE_URL
    if header_base_url:
        base_url = validate_base_url(header_base_url)
    elif env_base_url():
        base_url = validate_base_url(env_base_url())

    model = settings["model"] or DEFAULT_MODEL
    if header_model:
        model = validate_model(header_model)
    elif env_model():
        model = env_model()

    if header_key:
        api_key, source = header_key, "header"
    elif mode == "server":
        api_key, source = "", "none"
    elif settings.get("api_key"):
        api_key, source = str(settings["api_key"]), "settings"
    else:
        api_key = env_key_for(base_url)
        source = "env" if api_key else "none"

    return AuthContext(
        api_key=api_key,
        base_url=base_url,
        model=model,
        source=source,
        tenant=tenant_for(api_key, mode=mode, salt=salt),
        settings=settings,
    )


# ---------------------------------------------------------------- 日志脱敏

_KEY_PATTERNS = [
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9._-]{4,}"),
    re.compile(r"sk-ant-[A-Za-z0-9._-]{4,}"),
    re.compile(r"key-[A-Za-z0-9._-]{4,}"),
    re.compile(r"AIza[0-9A-Za-z_-]{10,}"),
    re.compile(r"(?:api[_-]?key|x-api-key|token)[=:]\s*[\"']?\S+", re.IGNORECASE),
]


def scrub(text: str, api_key: str = "") -> str:
    """redact() 同族：已知 secret 形态 + 显式 key 值（§4.2 第一道防线）。"""
    out = redact(text, api_key)
    for rx in _KEY_PATTERNS:
        out = rx.sub("***", out)
    return out


#: ``install_log_scrub`` 额外覆盖的具名 logger（uvicorn 系自带 handler，
#: propagate 链上各自独立判定；texlate 根包 logger 本身无 handler，
#: 挂上挡本源直写）。
_LOG_NAMES = ("texlate", "uvicorn", "uvicorn.error", "uvicorn.access")


class RedactFilter(logging.Filter):
    """根 logger 脱敏（§4.2 第二道防线，防三方库把请求体打进 traceback）。

    ``key_provider`` 返回当前该抹掉的 key 值集合（settings key +
    运行中的 header key）——动态取，key 轮换即生效。
    """

    def __init__(self, key_provider: object = None) -> None:
        """key_provider: ``() -> Iterable[str]``，None 时只抹正则形态。"""
        super().__init__()
        self._key_provider = key_provider

    def _keys(self) -> list[str]:
        if callable(self._key_provider):
            try:
                return [k for k in self._key_provider() if k]
            except Exception:  # noqa: BLE001 -- 过滤器绝不能炸掉日志调用
                return []
        return []

    def _scrub(self, text: str) -> str:
        for key in self._keys():
            text = text.replace(key, "***")
        for rx in _KEY_PATTERNS:
            text = rx.sub("***", text)
        return text

    def filter(self, record: logging.LogRecord) -> bool:
        """命中 secret 形态时改写 msg 并清空 args（避免二次格式化还原）。

        ``exc_info``/``stack_info`` 不走 ``msg``——Formatter 另路渲染；
        含 key 的异常文本（三方库把请求体打进异常）须先行 format 再
        洗，写回 ``record.exc_text`` 供 Formatter 直接用缓存值。
        """
        try:
            msg = record.getMessage()
        except Exception:  # noqa: BLE001 -- 同上，filter 不炸
            return True
        clean = self._scrub(msg)
        if clean != msg:
            record.msg = clean
            record.args = ()
        if record.exc_info:
            with contextlib.suppress(Exception):
                record.exc_text = self._scrub(
                    logging.Formatter().formatException(record.exc_info)
                )
        if record.stack_info:
            record.stack_info = self._scrub(record.stack_info)
        return True


def install_log_scrub(
    key_provider: Callable[[], Iterable[str]] | None = None,
) -> RedactFilter:
    """把 :class:`RedactFilter` 挂到 root logger 与其全部现有 handler。

    语义坑：logger 级 filter 只在记录「本源」logger 上判定，传播链上
    每个 handler 独立判定——所以 root logger 本体（拦直接
    ``logging.warning(...)`` 的本源记录）+ root handlers（拦
    ``texlate.*``/三方传播上来的记录）+ uvicorn 系私有 handler 都要挂。
    重复调用先卸旧 filter 再挂新的（key_provider 轮换/多次装配幂等）。
    须在 uvicorn log config 就绪后调用（app lifespan 起点）。
    """
    filt = RedactFilter(key_provider)
    loggers = [logging.getLogger(), *(logging.getLogger(n) for n in _LOG_NAMES)]
    for lg in loggers:
        for old in (f for f in lg.filters if isinstance(f, RedactFilter)):
            lg.removeFilter(old)
        lg.addFilter(filt)
        for h in lg.handlers:
            for old in (f for f in h.filters if isinstance(f, RedactFilter)):
                h.removeFilter(old)
            h.addFilter(filt)
    return filt


# ---------------------------------------------------------------- providers


def provider_presets(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """``GET /api/providers`` 出参：预设清单 + 当前选中态（key 只给 has_api_key）。"""
    conns_url = settings.get("base_url", "")
    presets = [
        {
            "id": "gateway",
            "name": "Local Gateway",
            "base_url": DEFAULT_BASE_URL,
            "model": DEFAULT_MODEL,
            "key_env": PROVIDER_KEY_ENV["gateway"],
        },
        {
            "id": "deepseek",
            "name": "DeepSeek",
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
            "key_env": PROVIDER_KEY_ENV["deepseek"],
        },
        {
            "id": "openai",
            "name": "OpenAI",
            "base_url": "https://api.openai.com",
            "model": "gpt-4o-mini",
            "key_env": PROVIDER_KEY_ENV["openai"],
        },
        {
            "id": "anthropic",
            "name": "Anthropic",
            "base_url": "https://api.anthropic.com",
            "model": "claude-haiku-4-5",
            "key_env": PROVIDER_KEY_ENV["anthropic"],
        },
        {
            "id": "qwen",
            "name": "Alibaba Qwen",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode",
            "model": "qwen-flash",
            "key_env": PROVIDER_KEY_ENV["qwen"],
        },
        {
            "id": "custom",
            "name": "Custom (OpenAI 兼容)",
            "base_url": "",
            "model": "",
            "key_env": PROVIDER_KEY_ENV["custom"],
        },
    ]
    current_provider = provider_for_url(conns_url) if conns_url else ""
    for p in presets:
        p["active"] = p["id"] == current_provider
        p["has_env_key"] = bool(os.environ.get(p["key_env"], ""))
    return presets
