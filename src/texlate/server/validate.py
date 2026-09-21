"""请求边界校验件 —— ``base_url``/``model`` 入参闸（web-layer.md §4.2）。

settings 写径（``_FIELD_SPECS`` 校验列）与 auth 决议径（header/env 覆盖值）
共用的纯校验函数——独立成叶为解开 settings↔auth 双向依赖：两侧都只
消费本叶，互不反向引用。
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlsplit

from texlate.xlat.client import (
    _LOOPBACK_HOSTS,
    _TAILNET_V4,
    API_DIALECTS,
    normalize_base_url,
)

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


def validate_base_url(value: str) -> str:
    """base_url 校验（texglot ``validate_url`` 移植）。

    拒：userinfo/query/fragment 内嵌、非 localhost/tailnet 的 http。返回归一化串。
    """
    v = value.strip().rstrip("/")
    if any(c.isspace() or not c.isprintable() for c in v):
        # urlsplit 对内嵌空白/控制字符不设防——``exa mple.com`` 会当合法
        # hostname 落库，请求期才在 httpx 侧炸；先整串拒掉
        msg = "invalid base_url（含空白/控制字符）"
        raise ValueError(msg)
    u = urlsplit(v)
    try:
        port = u.port
    except ValueError as e:
        # urlsplit 的端口校验是惰性的——``h:abc``/``h:99999``/``h:80:90``
        # 只在 ``.port`` 属性访问时炸；不探则脏值落库、请求期才炸 InvalidURL
        msg = "invalid base_url（端口非法）"
        raise ValueError(msg) from e
    if (
        u.scheme not in ("https", "http")
        or not u.hostname
        or "@" in u.netloc  # 任意 userinfo——``u.username`` 真值判漏空形 ``@host``
        or (port is None and u.netloc.endswith(":"))  # ``h:``——``@`` 上条已拒
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


def validate_dialect(value: str) -> str:
    """方言枚举闸：``auto|openai|anthropic|responses``——settings/header/env 三面同源。"""
    v = value.strip().lower()
    if v not in API_DIALECTS:
        msg = f"invalid dialect（expect {'|'.join(sorted(API_DIALECTS))}）"
        raise ValueError(msg)
    return v
