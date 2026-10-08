"""BYOK 与本地设置层（2026-09-15-web-layer.md §4）。

``api_key`` 入口优先级（高→低）：请求头 ``X-Texlate-*`` > ``settings.json``
（0600）> 环境变量；``base_url``/``model``/``dialect`` 走 header > env >
settings——env 是操作员逃生舱，不落盘即可整端覆盖。key 只进内存任务
对象，绝不进 tasks/files/日志；``tenant`` 用
``sha256(key+server_salt)[:12]`` 指纹隔离（单机模式恒 ``local``）。

四关切拆叶（本文件留 SettingsStore 本体与字段 spec 单源）：

- ``validate.py``：``base_url``/``model`` 边界校验——settings 写径与
  auth 决议径共用件，独立成叶解开 settings↔auth 双向依赖。
- ``auth.py``：凭证三级回落（``resolve_auth``/``AuthContext``/env 兜底）
  + ``tenant_for``/``server_salt`` 指纹盐。
- ``logredact.py``：日志脱敏（``scrub``/``RedactFilter``/``install_log_scrub``）。
- ``providers.py``：``/v1/models`` 探活传输 + provider 预设目录；
  探活编排（TTL 缓存/``model_warning``/``TEXLATE_MODEL_PROBE`` 闸）留本
  文件——消费面与 monkeypatch 面都钉在 settings 名空间，不出叶。

四层不落日志防线：异常边界 ``scrub()`` 先过、根 logger 挂
:class:`RedactFilter` 同款正则 scrub、API 出参只给 ``has_api_key``、
``validate_base_url`` 拒 userinfo/query + 非 localhost/tailnet 强制 https。

公共面守恒：``settings.X`` 与 ``from texlate.server.settings import X``
逐名照旧（含 tests/ 白盒钉点 ``_parse_origin``/``_check_cors_origins``/
``_MODELS_CACHE``/``list_provider_models``）。
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from collections.abc import Callable

from texlate.compile.engine import DEFAULT_TIMEOUT, ENGINE_NAMES
from texlate.server.auth import (  # noqa: F401 -- auth 关切出叶，属性面守恒
    _SALT_LOCK,
    BYOK_FIELDS,
    SALT_FILE,
    AuthContext,
    env_base_url,
    env_dialect,
    env_key_for,
    env_model,
    resolve_auth,
    server_salt,
    tenant_for,
)
from texlate.server.logredact import (  # noqa: F401 -- 脱敏关切出叶
    _KEY_PATTERNS,
    _LOG_NAMES,
    RedactFilter,
    install_log_scrub,
    scrub,
)
from texlate.server.providers import (  # noqa: F401 -- provider 目录/常量转口
    _MODEL_PROBE_TIMEOUT_S,
    list_provider_models,  # 探活编排本文件消费；settings 名空间是 patch 面
    provider_presets,
)
from texlate.server.validate import (  # noqa: F401 -- 边界校验出叶
    MODEL_MAX_LEN,
    _is_plaintext_ok_host,
    validate_base_url,
    validate_dialect,
    validate_model,
)
from texlate.share import cache_scope  # noqa: F401 -- 寻址键政策出叶（单源在 share）
from texlate.textutil import data_root, env_flag, env_raw, env_str
from texlate.textutil.osutil import (
    ENV_MODE,
    ENV_MODEL_PROBE,
    ENV_SHARE_DIR,
)
from texlate.xlat.client import API_DIALECTS, DEFAULT_BASE_URL, DEFAULT_MODEL
from texlate.xlat.state import atomic_json

log = logging.getLogger(__name__)

DEFAULT_TARGET_LANG = "zh-CN"

SETTINGS_FILE = "settings.json"
CONNECTIONS_FILE = "connections.json"
#: ``SALT_FILE`` 归 auth.py（``server_salt`` 同叶），经上方 import 转口。

#: 上传/解包上限（texglot 常量，web-layer §2.4）
UPLOAD_CAP = 80 * 1024 * 1024
INFLATED_CAP = 300 * 1024 * 1024
MAX_FILES = 4000

#: 目标语言白名单（M0 只做中译向；UI 表单项）
TARGET_LANGS = frozenset({"zh-CN", "zh-TW", "en"})

#: 编译引擎白名单（``_normalize_updates`` 与 ``load`` 容错回落同口径；
#: 单源 ``compile.engine.ENGINE_NAMES``，app 侧 ``_ENGINE_NAMES`` 同件转口）
ENGINES = ENGINE_NAMES

#: 编译超时秒数：默认单源 ``compile.engine.DEFAULT_TIMEOUT``（docs/spec/
#: compile.md）经 engine facade 转口；上限仍本地镜像 worker ``_env_timeout``
#: 域（``_ENV_TIMEOUT_MAX_S``=86400——settings 不反向 import worker 防环），
#: 待 hoist 至 ``compile/engine/_base.py`` 后与默认值同槽转口
DEFAULT_COMPILE_TIMEOUT_S = DEFAULT_TIMEOUT
COMPILE_TIMEOUT_MAX_S = 86400.0

#: 探活清单 TTL——同 endpoint 连续 ``save`` 不重复打 ``/models``
_MODEL_PROBE_CACHE_TTL_S = 20.0

#: ``save`` 里触发模型可用性重估的字段（凭证/端点/模型/方言任一变更才可能
#: 改变可达性）——BYOK 槽位由 ``BYOK_FIELDS`` 单源派生 + ``clear_api_key``
#: 写径动词
_MODEL_PROBE_FIELDS = frozenset(
    {spec.settings_key for spec in BYOK_FIELDS} | {"clear_api_key"}
)

#: ``connections.json`` 分槽值键集——``base_url`` 是槽主键不进值面；与
#: ``BYOK_FIELDS`` 同源，加 BYOK 字段自动进槽
_CONNECTION_SLOTS = tuple(
    spec.settings_key for spec in BYOK_FIELDS if spec.attr != "base_url"
)


def data_dir() -> Path:
    """数据目录：``TEXLATE_DATA_DIR`` > ``~/.texlate``；mkdir 0700。"""
    root = data_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    return root


def server_mode() -> str:
    """``TEXLATE_MODE``：``local``（默认）| ``server``（多租户部署形态）。"""
    return env_str(ENV_MODE) or "local"


def share_dir(root: Path | None = None) -> Path:
    """共享包发布目录：``TEXLATE_SHARE_DIR`` > ``<root>/share``（root 缺省 ``data_dir()``）。

    worker share 完成钩把 ``{share_key}.share.zip`` + 旁挂 ``index.jsonl``
    落此——指向静态托管/对象存储挂载点即完成发布（2026-09-16-shared-cache.md §7
    文件级服务端形态）。惰性建目录（pack/index_append 各自 mkdir parents）。
    """
    raw = env_raw(ENV_SHARE_DIR)
    if raw:
        return Path(raw).expanduser()
    return (root if root is not None else data_dir()) / "share"


# ---------------------------------------------------------------- 字段校验件


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
    """CORS origin 归一化：``scheme://host[:port]`` 小写形；非法形态返 None。

    浏览器 Origin 头恒按小写序列化——``HTTP://EXAMPLE.COM`` 原样入库永不
    匹配（静默死配），故按 ``u.hostname``（已小写）+ ``u.port`` 重组。
    """
    o = str(value or "").strip().rstrip("/")
    if not o:
        return None
    try:
        o.encode("utf-8")
    except UnicodeEncodeError:
        return None
    try:
        u = urlsplit(o)
        port = u.port  # 惰性端口校验——``h:abc``/``h:99999`` 访问才炸
    except ValueError:
        return None
    if (
        u.scheme not in ("http", "https")
        or not u.hostname
        or "@" in u.netloc  # 含 ``@host`` 空 userinfo 形
        or (port is None and u.netloc.endswith(":"))  # ``h:``——``@`` 上条已拒
        or u.query
        or u.fragment
        or u.path not in ("", "/")
    ):
        return None
    host = u.hostname
    if ":" in host:  # IPv6 字面量补回方括号
        host = f"[{host}]"
    # 浏览器 Origin 头恒省略 scheme 默认端口——显式写的 :80/:443 剥掉，
    # 否则归一化结果与真实 Origin 永不相等，配置成静默死配
    if port == (80 if u.scheme == "http" else 443):
        port = None
    netloc = host if port is None else f"{host}:{port}"
    return f"{u.scheme}://{netloc}"


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


def _check_concurrency(value: object) -> int:
    """``concurrency`` 校验：可转 int 并 clamp 1–16。"""
    try:
        return max(1, min(16, int(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        # ``int()`` 对 ``None``/``[3]`` 抛 TypeError、对 ``1e999`` 抛
        # OverflowError——都归一成 ValueError，否则 PUT 500
        msg = "concurrency 须为可转 int 的值（clamp 1–16）"
        raise ValueError(msg) from None


def _check_quota(value: object, name: str) -> int:
    """配额字段校验：非负 int（0=不限）。"""
    try:
        n = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        msg = f"{name} 必须是非负整数"
        raise ValueError(msg) from None
    if n < 0:
        msg = f"{name} 必须是非负整数"
        raise ValueError(msg)
    return n


def _check_compile_timeout(value: object) -> float:
    """``compile_timeout`` 校验：可转 float 秒数，clamp 1–86400。"""
    try:
        return max(1.0, min(COMPILE_TIMEOUT_MAX_S, float(value)))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        msg = f"compile_timeout 须为可转数值的秒数（clamp 1–{COMPILE_TIMEOUT_MAX_S:g}）"
        raise ValueError(msg) from None


def _check_enum(name: str, allowed: frozenset[str]) -> Callable[[Any], Any]:
    """写径枚举闸工厂：非白名单值 → ValueError（读径容错由 ``_load_enum`` 对称）。"""

    def check(value: object) -> object:
        if value not in allowed:
            msg = f"{name} ∈ {sorted(allowed)}"
            raise ValueError(msg)
        return value

    return check


# ---------------------------------------------------------------- 读径容错件


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


def _load_enum(value: object, allowed: frozenset[str], default: str) -> str:
    """枚举字段容错读：非白名单值（手改文件）→ 默认。

    ``engine``/``target_lang`` 非法值若 ``str()`` 原样透传，``public()``
    回吐脏值、下游任务创建按白名单全 400——手改一行即锁死新建任务面。
    """
    s = _load_str(value, default)
    if s not in allowed:
        log.warning("settings.json 非法枚举值已回落默认: %r → %r", s, default)
        return default
    return s


def _load_quota(value: object) -> int:
    """配额字段容错读：非法/负值 → 0（不限）。"""
    try:
        return max(0, int(value))  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return 0


def _load_concurrency(value: object) -> int:
    """``concurrency`` 容错读：非法值 → 10；clamp 1–16 与写径 ``_check_concurrency`` 同域。

    ``load()`` 其余字段的强转（``str``/``bool``）永不炸——唯一会抛的是
    本项 ``int()``；手改文件留个 ``"abc"`` 会炸穿 ``load()`` 连带全部
    ``_auth``/settings 端点 500，与 ``_load_quota`` 同口径容错回落。
    缺省 10 对齐 translating 段历史每任务 worker 数——本键自渠道改造起
    升任服务级在飞总闸（``_scope_limits`` global scope），缺省守住
    单任务历史吞吐。
    """
    try:
        return max(1, min(16, int(value or 10)))
    except (TypeError, ValueError, OverflowError):
        return 10


def _load_compile_timeout(value: object) -> float:
    """``compile_timeout`` 容错读：非法/越界 → ``DEFAULT_COMPILE_TIMEOUT_S``。"""
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_COMPILE_TIMEOUT_S
    return v if 0.0 < v <= COMPILE_TIMEOUT_MAX_S else DEFAULT_COMPILE_TIMEOUT_S


def _load_bool(value: object, *, default: bool) -> bool:
    """布尔字段容错读：str 走 falsy 集（``opt_bool`` 同口径）。

    手改 ``"false"``/``"0"`` 若裸 ``bool()`` 反读 True——save 侧
    写径闸死非 bool，load 侧须解析字符串语义才对称。
    缺键（None）落 default，其余类型维持 ``bool()`` 语义。
    """
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() not in ("0", "false", "no", "off", "")
    return bool(value)


# ---------------------------------------------------------------- 字段 spec 表


@dataclass(frozen=True, slots=True)
class _FieldSpec:
    """settings.json 单字段知识单源——``FIELDS``/写径校验/读径容错三面同源。

    ``scalar``：写径标量类型闸（``str``/``bool``，``None`` = 容器/数值型
    字段由 ``check`` 自带类型容错）；``load``：读径容错归一化；``check``：
    写径校验器（``None`` = 只过标量闸——``api_key``/``glossary``/
    ``context_guidance``）。新增字段只改 ``_FIELD_SPECS`` 一行。
    """

    name: str
    scalar: type | None
    load: Callable[[Any], Any]
    check: Callable[[Any], Any] | None


_FIELD_SPECS: tuple[_FieldSpec, ...] = (
    _FieldSpec(
        "base_url",
        str,
        lambda v: _load_str(v, DEFAULT_BASE_URL),
        lambda v: validate_base_url(str(v)),
    ),
    _FieldSpec(
        "model",
        str,
        lambda v: _load_str(v, DEFAULT_MODEL),
        lambda v: validate_model(str(v)),
    ),
    _FieldSpec(
        "dialect",
        str,
        lambda v: _load_enum(v, API_DIALECTS, "auto"),
        _check_enum("dialect", API_DIALECTS),
    ),
    _FieldSpec("api_key", str, lambda v: _load_str(v, ""), None),
    _FieldSpec(
        "target_lang",
        str,
        lambda v: _load_enum(v, TARGET_LANGS, DEFAULT_TARGET_LANG),
        _check_enum("target_lang", TARGET_LANGS),
    ),
    _FieldSpec("glossary", str, lambda v: _load_str(v, ""), None),
    _FieldSpec("glossary_dir", str, lambda v: _load_str(v, ""), _check_glossary_dir),
    _FieldSpec("concurrency", None, _load_concurrency, _check_concurrency),
    _FieldSpec("compile_timeout", None, _load_compile_timeout, _check_compile_timeout),
    _FieldSpec(
        "engine",
        str,
        lambda v: _load_enum(v, ENGINES, "auto"),
        _check_enum("engine", ENGINES),
    ),
    _FieldSpec(
        "context_guidance",
        bool,
        lambda v: _load_bool(v, default=True),
        None,
    ),
    _FieldSpec("cors_origins", None, _load_origins, _check_cors_origins),
    _FieldSpec(
        "quota_max_tasks",
        None,
        _load_quota,
        lambda v: _check_quota(v, "quota_max_tasks"),
    ),
    _FieldSpec(
        "quota_max_bytes",
        None,
        _load_quota,
        lambda v: _check_quota(v, "quota_max_bytes"),
    ),
    _FieldSpec(
        "retention_days",
        None,
        _load_quota,
        lambda v: _check_quota(v, "retention_days"),
    ),
    _FieldSpec(
        "retention_max_gb",
        None,
        _load_quota,
        lambda v: _check_quota(v, "retention_max_gb"),
    ),
)

_FIELD_NAMES = tuple(spec.name for spec in _FIELD_SPECS)

#: 标量闸报错文案——``str``/``bool`` 之外出现新 scalar 须先扩表
_SCALAR_LABEL: Final = {str: "字符串", bool: "布尔值"}


def _normalize_updates(values: dict[str, Any]) -> None:
    """``save`` 的逐字段归一化/校验（就地改写 ``values``）。

    两段闸序（与原 ``_check_scalar_types`` + 校验链同构）：先全字段标量
    类型闸（``str`` 字段拒容器——``dict`` 撞枚举 frozenset 校验是
    TypeError 不是 ValueError、``dict/list`` 落 ``str()`` 成字面量脏持久
    化），再逐字段 ``check`` 归一化。多字段同坏的报错先后按 spec 表序。
    """
    for spec in _FIELD_SPECS:
        if (
            spec.name in values
            and spec.scalar is not None
            and not isinstance(values[spec.name], spec.scalar)
        ):
            msg = f"{spec.name} 必须是{_SCALAR_LABEL[spec.scalar]}"
            raise ValueError(msg)
    for spec in _FIELD_SPECS:
        if spec.name in values and spec.check is not None:
            values[spec.name] = spec.check(values[spec.name])


# ---------------------------------------------------------------- 设置存储


class SettingsStore:
    """``settings.json``（0600）+ ``connections.json`` 分槽 key 池。

    ``connections.json`` 按 base_url 分槽存 ``{api_key, model, dialect}``
    （槽键集 ``_CONNECTION_SLOTS`` 由 ``BYOK_FIELDS`` 派生）——切
    endpoint 时各自的 key 都能找回（texglot 模式）。settings 本体不落
    key 进日志/出参；``public()`` 只给 ``has_api_key``。
    """

    FIELDS = _FIELD_NAMES

    def __init__(self, root: Path) -> None:
        """Root = 数据目录（已 0700 建妥）。"""
        self.root = root
        self.path = root / SETTINGS_FILE
        self.connections_path = root / CONNECTIONS_FILE
        #: ``save`` 临界区串行锁——load→merge→write 原靠事件循环单线程
        #: 隐式串行；``settings_put`` 经 ``asyncio.to_thread`` 卸载后并发
        #: PUT 在 worker 线程真并行，无锁会丢更新
        self._save_lock = threading.Lock()
        #: 最近一次 ``save`` 探活的模型可用性警告（进程瞬态不落盘；
        #: ``None`` = 无警告或未知），``public()`` 随出参透给前端
        self._model_warning: str | None = None
        #: ``load`` 磁盘缓存：``(mtime_ns, size) | None 标记 → 归一化 dict``。
        #: app 每请求 + RedactFilter 每条 record 都调 load——标记不变
        #: 直接命中，省读盘+parse。``_save`` 写盘后显式失效兜底粗粒度
        #: mtime 文件系统（同秒同大小写盘标记不变）的漏判。
        self._load_cache: tuple[tuple[int, int] | None, dict[str, Any]] | None = None
        self._load_lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        """读 settings.json；缺席/损坏回落默认。

        返回缓存本体的深拷贝——``public()`` 会 ``pop("api_key")``、
        调用方可能就地改 ``cors_origins`` 等嵌套容器；浅拷贝会让
        改动穿透进缓存体，污染后续全部 ``load()``。
        """
        try:
            st = self.path.stat()
            sig: tuple[int, int] | None = (st.st_mtime_ns, st.st_size)
        except OSError:
            sig = None  # 文件缺席也按标记缓存——缺席是常态不是异常
        with self._load_lock:
            if self._load_cache is not None and self._load_cache[0] == sig:
                return copy.deepcopy(self._load_cache[1])
            data: dict[str, Any] = {}
            if sig is not None:
                try:
                    raw = json.loads(self.path.read_text(encoding="utf-8"))
                    if isinstance(raw, dict):
                        data = {k: raw[k] for k in self.FIELDS if k in raw}
                except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
                    # UnicodeDecodeError 是 ValueError 非 JSONDecodeError——
                    # GBK 存盘的手改文件漏它会炸穿 load()（每请求经 deps.auth
                    # 调用），连带 save() 修复路径一并锁死；与 worker/share.py
                    # ``dual.json`` 读径同口径
                    log.warning("settings.json 损坏（%s）→ 用默认值", e)
            out = self._normalize(data)
            self._load_cache = (sig, out)
            return copy.deepcopy(out)

    @staticmethod
    def _normalize(data: dict[str, Any]) -> dict[str, Any]:
        """原始 dict → 归一化 settings（容错读集中于此供 ``load`` 缓存）。"""
        return {spec.name: spec.load(data.get(spec.name)) for spec in _FIELD_SPECS}

    def save(self, updates: dict[str, Any]) -> dict[str, Any]:
        """合并更新 → 校验 → 0600 原子写 + connections 分槽同步。

        ``api_key`` 传空串不覆盖旧值；``clear_api_key=True`` 显式清。
        base_url 变更时从 connections 槽找回该 endpoint 的历史 key
        （texglot merge_settings 语义）。
        """
        with self._save_lock:
            return self._save(updates)

    def _save(self, updates: dict[str, Any]) -> dict[str, Any]:
        """``save`` 临界区本体——调用方须已持 ``_save_lock``。"""
        old = self.load()
        values = dict(updates)
        values.pop("has_api_key", None)
        clear_key = bool(values.pop("clear_api_key", False))
        # 白名单收口：API 层已滤 + 回显 ignored，此处再闸直调面——未知键
        # 永不进 settings.json。
        values = {k: v for k, v in values.items() if k in self.FIELDS}
        _normalize_updates(values)
        if not values.get("api_key"):
            values.pop("api_key", None)
        merged = old | values
        # connections.json 单读共用：api_key/dialect 槽位找回与下方回写吃
        # 同一快照——分次读在 ``_save_lock`` 内付重复读盘+parse，且槽位
        # 查找与回写可能观测到不同内容
        conns = self.connections()
        if "api_key" not in values and merged["base_url"] != old["base_url"]:
            # 换 endpoint 未带 key → 找回新 endpoint 槽位历史 key。
            # 只改 merged——old 动不得：下方 conns 回写按 cfg.base_url
            # 分槽，old.api_key 若被换成新 endpoint 的 key，旧槽会被
            # 错写（切回旧 endpoint 时把新 key 发给它）。
            merged["api_key"] = (
                conns.get(str(merged["base_url"]), {}).get("api_key") or ""
            )
        if "dialect" not in values and merged["base_url"] != old["base_url"]:
            # 换 endpoint 未带 dialect → 找回新槽位历史值（缺槽归 auto）——
            # 方言是端点属性，残留旧值会把 openai 请求打向 responses-only 端点
            merged["dialect"] = (
                conns.get(str(merged["base_url"]), {}).get("dialect") or "auto"
            )
        if clear_key:
            merged["api_key"] = ""
        for cfg in (old, merged):
            conns.pop(cfg["base_url"], None)
            conns[cfg["base_url"]] = {slot: cfg[slot] for slot in _CONNECTION_SLOTS}
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
        with self._load_lock:
            self._load_cache = None  # 粗粒度 mtime 标记同值兜底——写后必失效
        if _MODEL_PROBE_FIELDS & set(updates):
            # 凭证/端点/模型变更后 best-effort 探活——provider 清单不含
            # 当前 model 时存警告（保存照存：不可用模型仍允许入设置，
            # 但 PUT 响应带 model_warning 提醒后续任务会毒化 fault）
            self._model_warning = model_availability_warning(
                str(merged["base_url"]), str(merged["api_key"]), str(merged["model"])
            )
        return merged

    def connections(self) -> dict[str, dict[str, str]]:
        """``connections.json`` → ``{base_url: {api_key, model, dialect}}``."""
        if not self.connections_path.exists():
            return {}
        try:
            data = json.loads(self.connections_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            # 非 UTF-8 存盘（GBK 手改）同「损坏」口径回落空表——漏
            # UnicodeDecodeError 会让 save() 的槽位找回步炸 500
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
            out[str(k)] = {fk: _load_str(fv, "") for fk, fv in v.items()}
        return out

    def public(self) -> dict[str, Any]:
        """出参形态：剥 key 本体 + ``has_api_key``（§4.2 第三道防线）。

        ``model_warning`` 仅在上次 ``save`` 探活判定模型未被 provider
        清单广告时出现——PUT 响应即时透出毒化模型警告，GET 复现同一警告。
        """
        data = self.load()
        data["has_api_key"] = bool(data.pop("api_key"))
        if self._model_warning:
            data["model_warning"] = self._model_warning
        return data


# ---------------------------------------------------------------- 探活编排

#: ``base_url → (monotonic 时间戳，清单或 None)`` 探活缓存；进程级共享——
#: 清单是 endpoint 形态不是 store 形态。base_url 是用户输入键，不封顶
#: 会被 PUT 喷雾灌成进程期增长——FIFO 逐出最旧条。
_MODELS_CACHE_CAP: Final = 64
_MODELS_CACHE: dict[str, tuple[float, list[str] | None]] = {}
_MODELS_CACHE_LOCK = threading.Lock()


def _cached_provider_models(base_url: str, api_key: str) -> list[str] | None:
    """TTL 缓存的 ``list_provider_models``——``save`` 高频调用不重复探活。

    按 ``base_url`` 单键缓存（不细分 api_key）：清单不可达/鉴权失败的
    ``None`` 同样缓存 TTL 期——探活是 UX 警告不是正确性闸，短窗口内
    用旧 verdict 可接受。
    """
    now = time.monotonic()
    with _MODELS_CACHE_LOCK:
        hit = _MODELS_CACHE.get(base_url)
        if hit is not None and now - hit[0] < _MODEL_PROBE_CACHE_TTL_S:
            return hit[1]
    models = list_provider_models(base_url, api_key)
    with _MODELS_CACHE_LOCK:
        if len(_MODELS_CACHE) >= _MODELS_CACHE_CAP:
            _MODELS_CACHE.pop(next(iter(_MODELS_CACHE)))
        _MODELS_CACHE[base_url] = (time.monotonic(), models)
    return models


def _model_probe_enabled() -> bool:
    """``TEXLATE_MODEL_PROBE`` 标准旗标语义：非真值显式关闭 save 期探活（离线/CI 兜底闸）。"""
    return env_flag(ENV_MODEL_PROBE, default=True)


def model_availability_warning(base_url: str, api_key: str, model: str) -> str | None:
    """``/models`` 清单不含当前 model → UX 警告；探活失败/清单命中 → ``None``。"""
    if not _model_probe_enabled():
        return None
    models = _cached_provider_models(base_url, api_key)
    if models is None or model in models:
        return None
    return (
        f"model {model!r} 不在 provider /models 清单内——已保存；"
        "若属拼写错误，后续任务会在翻译阶段失败"
    )
