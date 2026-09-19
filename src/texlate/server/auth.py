"""BYOK 凭证决议簇 —— header/settings/env 三级回落 + 租户指纹（§4.3）。

``api_key`` 入口优先级（高→低）：请求头 ``X-Texlate-*`` > ``settings.json``
（0600）> 环境变量；``base_url``/``model``/``dialect`` 走 header > env >
settings——env 是操作员逃生舱，不落盘即可整端覆盖（``resolve_auth``
docstring 同口径）。key 只进内存任务对象，绝不进 tasks/files/日志；
``tenant`` 用 ``sha256(key+server_salt)[:12]`` 指纹隔离（单机模式恒
``local``）。
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from pathlib import Path

from texlate.server.validate import (
    validate_base_url,
    validate_dialect,
    validate_model,
)
from texlate.textutil import env_raw
from texlate.xlat.client import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    PROVIDER_KEY_ENV,
    normalize_base_url,
    provider_for_url,
)

SALT_FILE = "server_salt"


def env_key_for(base_url: str) -> str:
    """按 provider 映射读 env key：``TEXLATE_API_KEY`` 优先，然后按 host 兜底。"""
    direct = env_raw("TEXLATE_API_KEY")
    if direct:
        return direct
    env_name = PROVIDER_KEY_ENV.get(provider_for_url(base_url), "TEXLATE_API_KEY")
    return env_raw(env_name)


def env_base_url() -> str:
    """``TEXLATE_BASE_URL`` env 兜底（未配置返回空）。。"""
    return env_raw("TEXLATE_BASE_URL")


def env_model() -> str:
    r"""``TEXLATE_MODEL`` env 兜底——非空值过 ``validate_model``。

    与 ``header_model`` 臂同闸：控制字符（``\n`` 等）原样透传会进
    任务行/事件载荷构成日志注入面，env 是操作员配置面，错配即早炸。
    """
    v = env_raw("TEXLATE_MODEL")
    return validate_model(v) if v else ""


def env_dialect() -> str:
    """``TEXLATE_DIALECT`` env 兜底——非空值过 ``validate_dialect``（同 env_model 口径）。"""
    v = env_raw("TEXLATE_DIALECT")
    return validate_dialect(v) if v else ""


@dataclass(frozen=True, slots=True)
class _ByokField:
    """BYOK 单字段决议知识单源——请求头/env/settings 三面同源。

    ``env`` 读件签名 ``(base_url) -> str``——入参是已决议端点（仅
    ``api_key`` 的 provider 兜底链消费；其余字段的 env 与端点无关，入参
    忽略）。``validate=None`` 仅 ``api_key``：key 是自由形，任何形态都
    原样透传不校验。
    """

    attr: str  # ``AuthContext`` 属性名
    header: str  # ``X-Texlate-*`` 请求头名（小写——starlette Headers 大小写不敏感）
    env: Callable[[str], str]
    settings_key: str  # ``settings.json`` 键名（connections 分槽键同源）
    validate: Callable[[str], str] | None
    default: str


#: BYOK 字段表——deps 请求头读取、``resolve_auth`` 逐项回落、settings
#: ``_MODEL_PROBE_FIELDS``/connections 分槽键集、app CORS
#: ``allow_headers`` 全部由本表派生；字段增删只改这里。
BYOK_FIELDS: tuple[_ByokField, ...] = (
    _ByokField("api_key", "x-texlate-key", env_key_for, "api_key", None, ""),
    _ByokField(
        "base_url",
        "x-texlate-base-url",
        lambda _url: env_base_url(),
        "base_url",
        validate_base_url,
        DEFAULT_BASE_URL,
    ),
    _ByokField(
        "model",
        "x-texlate-model",
        lambda _url: env_model(),
        "model",
        validate_model,
        DEFAULT_MODEL,
    ),
    _ByokField(
        "dialect",
        "x-texlate-dialect",
        lambda _url: env_dialect(),
        "dialect",
        validate_dialect,
        "auto",
    ),
)

#: ``BYOK_FIELDS`` 按 ``attr`` 的索引——``resolve_auth`` 逐字段取 spec。
_BYOK_SPEC = {spec.attr: spec for spec in BYOK_FIELDS}


#: ``server_salt`` 首调序列化（进程内）；跨进程由 ``O_EXCL`` 原子创建兜。
_SALT_LOCK = threading.Lock()


def server_salt(root: Path) -> str:
    """租户指纹盐：``server_salt`` 文件 0600，首跑生成。

    空/全空白文件视为未初始化——空盐下 ``tenant_for`` 退成裸
    ``sha256(key)``，已知 key 可预计算租户指纹，弱化隔离意义。
    首调并发按「O_CREAT|O_EXCL 独占创建、负方重读落盘值」裁决——
    读-缺-写竞态下各写各盐会让先返回者手里盐与落盘盐分叉，其租户
    指纹重启后不可解析。
    """
    path = root / SALT_FILE
    try:
        salt = path.read_text(encoding="utf-8").strip()
    except OSError:
        salt = ""
    if salt:
        return salt
    new_salt = secrets.token_hex(16)
    with _SALT_LOCK:
        # 生成耗熵不持锁；锁内重读——等待期他线程可能已写妥
        try:
            salt = path.read_text(encoding="utf-8").strip()
        except OSError:
            salt = ""
        if salt:
            return salt
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            # 他进程胜方 open→write 之间文件短暂为空：自旋等写入落地；
            # 预存空白文件（无人写）自旋穷尽后由本进程覆盖重建
            for _ in range(100):
                time.sleep(0.005)
                try:
                    salt = path.read_text(encoding="utf-8").strip()
                except OSError:
                    salt = ""
                if salt:
                    return salt
            path.write_text(new_salt, encoding="utf-8")
        else:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(new_salt)
        path.chmod(0o600)
        return new_salt


@dataclass(frozen=True, slots=True)
class AuthContext:
    """一次请求解析出的有效凭证（只在内存里活过任务生命周期）。

    ``source`` ∈ ``header | settings | env | none``——任务行记
    ``auth_source``，重启恢复时 header 源任务转 ``needs_auth``。
    """

    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    dialect: str = "auto"
    source: str = "none"
    tenant: str = "local"
    settings: dict[str, Any] = field(default_factory=dict)


def _resolve_field(
    spec: _ByokField,
    header_value: str,
    settings: dict[str, Any],
    base_url: str = "",
) -> str:
    """非 key 字段三级回落：header > env > settings（逐项独立）。

    env 值统一再过一遍 ``spec.validate``——``env_base_url`` 裸读不自校验；
    ``env_model``/``env_dialect`` 已自校验，``validate_*`` 幂等重跑无副作用。
    """
    assert spec.validate is not None  # noqa: S101 -- api_key 专径不走本臂，表内约定
    if header_value:
        return spec.validate(header_value)
    env = spec.env(base_url)
    if env:
        return spec.validate(env)
    return str(settings.get(spec.settings_key) or spec.default)


def tenant_for(api_key: str, *, mode: str, salt: str) -> str:
    """租户指纹：local 模式恒 ``local``；server 模式 ``k_+sha256(key+salt)[:12]``。

    key 不入库、指纹入库（§4.3）；server 模式无 key 请求归入匿名桶。
    """
    if mode != "server":
        return "local"
    return "k_" + hashlib.sha256((api_key + salt).encode()).hexdigest()[:12]


def resolve_auth(  # noqa: PLR0913 -- header 四槽/headers/mode/salt 即决议面
    settings: dict[str, Any],
    *,
    header_key: str = "",
    header_base_url: str = "",
    header_model: str = "",
    header_dialect: str = "",
    headers: Mapping[str, str] | None = None,
    mode: str = "local",
    salt: str = "",
) -> AuthContext:
    """逐项独立回落：``api_key`` 走 header > settings > env；其余字段走 header > env > settings。

    ``auth_source`` 由 key 的来源决定（key 才是重启续跑的关键物）；
    header key 校验失败后不落 settings 兜底——显式覆盖语义。
    server 形态例外：无 header key 时 key 不回落 settings/env——匿名
    桶永不携带部署方凭据（匿名 mutation 由 app 中间件 401 挡死，读面
    也绝不外借 key）。
    跨槽闸：``header_base_url`` 显式指定了端点却没带 key 时，存下的
    凭证只回灌给自己的槽位（settings key ↔ settings.base_url、env key
    ↔ env 端点）；异槽一律匿名——防本地任意进程把部署方 key 引到
    自选端点（exfil oracle）。
    ``headers`` 是请求头面（deps 直传 ``request.headers``）——查名按
    ``BYOK_FIELDS`` 单源；给定时覆盖全部 ``header_*`` kwarg，kwarg 面
    保留给单字段直调/测试。
    """
    if headers is not None:
        header_in = {
            spec.attr: str(headers.get(spec.header) or "") for spec in BYOK_FIELDS
        }
    else:
        header_in = {
            "api_key": header_key,
            "base_url": header_base_url,
            "model": header_model,
            "dialect": header_dialect,
        }
    url_spec = _BYOK_SPEC["base_url"]
    base_url = _resolve_field(url_spec, header_in["base_url"], settings)
    env_url = url_spec.env("")
    model = _resolve_field(_BYOK_SPEC["model"], header_in["model"], settings, base_url)
    dialect = _resolve_field(
        _BYOK_SPEC["dialect"], header_in["dialect"], settings, base_url
    )

    key_spec = _BYOK_SPEC["api_key"]
    if header_in["api_key"]:
        api_key, source = header_in["api_key"], "header"
    elif mode == "server":
        api_key, source = "", "none"
    else:
        # 跨槽闸：header 显式指了别的端点却没带 key 时，存下的凭证只能
        # 回灌给它自己的槽位——settings key 只在 header 复指
        # settings.base_url 时放行，env key 只在复指 env 端点时放行；
        # 异槽 → 匿名。否则本地任意可发请求的进程都能把部署方 key
        # 引到攻击者端点（settings_test「覆盖 base_url 须同给 key」同口径）。
        settings_ok = not header_in["base_url"] or base_url == normalize_base_url(
            str(settings.get(url_spec.settings_key) or url_spec.default)
        )
        env_ok = not header_in["base_url"] or (
            bool(env_url) and base_url == validate_base_url(env_url)
        )
        api_key, source = "", "none"
        if settings_ok and settings.get(key_spec.settings_key):
            api_key, source = str(settings[key_spec.settings_key]), "settings"
        elif env_ok:
            api_key = key_spec.env(base_url)
            source = "env" if api_key else "none"

    return AuthContext(
        api_key=api_key,
        base_url=base_url,
        model=model,
        dialect=dialect,
        source=source,
        tenant=tenant_for(api_key, mode=mode, salt=salt),
        settings=settings,
    )
