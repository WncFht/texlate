"""auth 失败分类 + 连续熔断闸（自 ``pipeline`` 出叶）。

``_kind_of`` 把异常归一成 ``ChunkResult.error_kind``（auth|provider|crash），
是 ``AuthGate`` 计数与落库簿记的共同输入；``AuthGate`` 逐结果入账，连续
auth-fail 达 ``threshold`` 闩锁 → ``run()`` 收尾抛 ``AuthTrippedError``
让论文 fault——凭证失效时绝不把整篇静默写成 fallback 原文（T2）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from .client import HTTP_FORBIDDEN, HTTP_UNAUTHORIZED, AuthError, ChatError

if TYPE_CHECKING:
    from .pipeline import ChunkResult


def _is_auth_error(e: BaseException) -> bool:
    """Auth 类失败判定：401/403（AuthError 或裸 status 命中）。"""
    return isinstance(e, AuthError) or (
        isinstance(e, ChatError) and e.status in (HTTP_UNAUTHORIZED, HTTP_FORBIDDEN)
    )


def _kind_of(e: BaseException) -> str:
    """异常 → ``ChunkResult.error_kind``：auth | provider | crash。"""
    if isinstance(e, ChatError):
        return "auth" if _is_auth_error(e) else "provider"
    return "crash"


class AuthTrippedError(AuthError):
    """连续 auth-fail 熔断信号（T2）：``run()`` 抛出 = 论文 fault。

    继承 ``AuthError``——调用方既有的 ``except AuthError`` 归类
    （worker → ``provider_auth``）对它天然生效。
    """


@dataclass
class AuthGate:
    """连续 auth-fail 计数闸（一个 ``run()`` 一扇，``run`` 开头重置）。

    - ``consecutive``：当前连续 auth-fail 块数。
    - ``tripped``：``consecutive`` 达到 ``threshold`` 闩锁——run 收尾抛
      ``AuthTrippedError``。
    - ``auth_failures``/``non_auth``：本 run 累计——``all_failed`` 属性是
      「整篇全 auth 败」判定，跨论文熔断（连续 N 篇）由调用方据此自行累计。
    """

    threshold: int = 3
    consecutive: int = 0
    auth_failures: int = 0
    non_auth: int = 0
    tripped: bool = False

    def record(self, r: ChunkResult) -> None:
        """逐结果入账：auth 类累计；真发过请求的非-auth 结果清零连续计数。

        ``attempts==0`` 且无 error_kind 的 ok（缓存命中等）不置证——
        没发请求，对 auth 死活既不清零也不计 ``non_auth`` 分母。
        """
        if r.error_kind == "auth":
            self.consecutive += 1
            self.auth_failures += 1
            if 0 < self.threshold <= self.consecutive:
                self.tripped = True
        elif r.attempts > 0 or r.error_kind:
            self.consecutive = 0
            self.non_auth += 1

    @property
    def all_failed(self) -> bool:
        """本 run 是否「全 auth 败」——已熔断，或有 auth-fail 且零成功请求。"""
        return self.tripped or (self.auth_failures > 0 and self.non_auth == 0)
