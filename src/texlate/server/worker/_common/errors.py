"""阶段控制流信号域（自 ``_common`` 出叶）：四类异常载体。

``_StageError``/``_RouteRejectError``/``_ShareRejectError`` 是 ``run()``
收口前的终态裁决载体（fault / partial+reject_at 分流）；``_SectionAbort``
是 ephemeral-loop 段内取消哨兵——``_common.xlator._AbortingTranslator``
置位即抛、export 内嵌管线的 ``_worker`` 按 ``except Exception`` 归
crash-skip（CancelledError 会把 task 直接打死，``queue.join()`` 永挂）。
"""

from __future__ import annotations


class _StageError(Exception):
    """阶段内携带错误码的异常（→ ``run()`` 统一落 fault）。"""

    def __init__(self, code: str, message: str, *, retryable: bool = False) -> None:
        """Code 取 §2.2 错误码枚举。"""
        self.code = code
        self.retryable = retryable
        super().__init__(message)


class _RouteRejectError(Exception):
    """路由/主文件策略拒绝载体（F3：``run()`` 归 partial + ``reject_at``，非 fault）。"""


class _ShareRejectError(Exception):
    """共享包本地重验拒绝载体（→ ``run()`` 归 partial + ``reject_at=share_verify``）。"""


class _SectionAbort(Exception):  # noqa: N818 -- 取消控制流信号非 Error 语义
    """线程段内取消哨兵——**不是** ``CancelledError``。

    export 内嵌管线的 ``_worker`` 按 ``except Exception`` 归 crash-skip——
    取消信号折成普通异常，剩余 unit 逐条快失败排空队列（零 token 消耗），
    段边界 ``_check_cancelled`` 再收敛成真 cancel。抛 CancelledError 会
    把 ``_worker`` task 直接打死，``queue.join()`` 永久挂起（孤儿线程
    更糟）。
    """
