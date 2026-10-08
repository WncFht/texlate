"""本地设置层（2026-09-15-web-layer.md §4）——``settings.json`` 只存任务策略/外观键。

端点配置（``api_key``/``base_url``/``model``/``dialect``）自渠道改造起
全部迁往 ``channels.json``（``server/channels.py`` 数据层）——本文件
不再携带任何 BYOK 字段；旧文件的四键由 ``ChannelStore.bootstrap``
一次性物化剥走。凭据决议只认两级：请求头 ``X-Texlate-*`` >
环境变量（``resolve_auth``）；渠道命中的请求再走渠道凭据阶梯。

三关切拆叶（本文件留 SettingsStore 本体与字段 spec 单源）：

- ``validate.py``：``base_url``/``model``/``dialect`` 边界校验——渠道写径
  与 auth 决议径共用件，独立成叶解开 settings↔auth 双向依赖。
- ``auth.py``：凭证两级回落（``resolve_auth``/``AuthContext``/env 兜底）
  + ``tenant_for``/``server_salt`` 指纹盐。
- ``logredact.py``：日志脱敏（``scrub``/``RedactFilter``/``install_log_scrub``）。

不落日志防线：异常边界 ``scrub()`` 先过、根 logger 挂
:class:`RedactFilter` 同款正则 scrub、``validate_base_url`` 拒
userinfo/query + 非 localhost/tailnet 强制 https。

公共面守恒：``settings.X`` 与 ``from texlate.server.settings import X``
逐名照旧（含 tests/ 白盒钉点 ``_parse_origin``/``_check_cors_origins``）。
"""

from __future__ import annotations

import copy
import json
import logging
import threading
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
from texlate.server.validate import (  # noqa: F401 -- 边界校验出叶
    MODEL_MAX_LEN,
    _is_plaintext_ok_host,
    validate_base_url,
    validate_dialect,
    validate_model,
)
from texlate.share import cache_scope  # noqa: F401 -- 寻址键政策出叶（单源在 share）
from texlate.textutil import data_root, env_raw, env_str
from texlate.textutil.osutil import (
    ENV_MODE,
    ENV_SHARE_DIR,
)
from texlate.xlat.state import atomic_json

log = logging.getLogger(__name__)

DEFAULT_TARGET_LANG = "zh-CN"

SETTINGS_FILE = "settings.json"
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
    """``settings.json``（0600）任务策略/外观键存取。

    BYOK 端点字段已全面迁出（``channels.json`` 唯一事实源）——本 store
    只管 target_lang/engine/concurrency/glossary/quota 等任务策略与
    外观键；mtime 标记缓存 + 深拷贝出参 + 0600 原子写。
    """

    FIELDS = _FIELD_NAMES

    def __init__(self, root: Path) -> None:
        """Root = 数据目录（已 0700 建妥）。"""
        self.root = root
        self.path = root / SETTINGS_FILE
        #: ``save`` 临界区串行锁——load→merge→write 原靠事件循环单线程
        #: 隐式串行；``settings_put`` 经 ``asyncio.to_thread`` 卸载后并发
        #: PUT 在 worker 线程真并行，无锁会丢更新
        self._save_lock = threading.Lock()
        #: ``load`` 磁盘缓存：``(mtime_ns, size) | None 标记 → 归一化 dict``。
        #: app 每请求 + RedactFilter 每条 record 都调 load——标记不变
        #: 直接命中，省读盘+parse。``_save`` 写盘后显式失效兜底粗粒度
        #: mtime 文件系统（同秒同大小写盘标记不变）的漏判。
        self._load_cache: tuple[tuple[int, int] | None, dict[str, Any]] | None = None
        self._load_lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        """读 settings.json；缺席/损坏回落默认。

        返回缓存本体的深拷贝——调用方可能就地改 ``cors_origins`` 等
        嵌套容器；浅拷贝会让改动穿透进缓存体，污染后续全部 ``load()``。
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
        """合并更新 → 校验 → 0600 原子写。"""
        with self._save_lock:
            return self._save(updates)

    def _save(self, updates: dict[str, Any]) -> dict[str, Any]:
        """``save`` 临界区本体——调用方须已持 ``_save_lock``。"""
        old = self.load()
        # 白名单收口：API 层已滤 + 回显 ignored，此处再闸直调面——未知键
        # 永不进 settings.json。
        values = {k: v for k, v in updates.items() if k in self.FIELDS}
        _normalize_updates(values)
        merged = old | values
        # 预检：任一值不可 UTF-8 编码（孤 surrogate）时 atomic_json 半路炸
        # 会留半写文件——先序列化探雷，炸了按非法更新处理，磁盘零写
        try:
            json.dumps(merged, ensure_ascii=False).encode("utf-8")
        except UnicodeEncodeError as e:
            msg = "settings 含不可编码字符"
            raise ValueError(msg) from e
        atomic_json(self.path, merged)
        self.path.chmod(0o600)
        with self._load_lock:
            self._load_cache = None  # 粗粒度 mtime 标记同值兜底——写后必失效
        return merged

    def public(self) -> dict[str, Any]:
        """出参形态 = 归一化全量（BYOK 键已不在 FIELDS——无可剥敏感项）。"""
        return self.load()
