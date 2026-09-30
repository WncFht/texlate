"""``texlate.pipecore.policy`` — 修复链开关决议 + ``reject:<rid>`` 判词叶（``pipecore`` 拆分叶）。

``_opt_switch`` 三层链（显式 > options > ``TEXLATE_NO_*`` env 缺省皆开）
薄壳 + ``RepairPolicy`` 双闸决议快照 + ``reject:<rid>`` 判词
（``reject_verdict``/``precheck_reject``）——e2e/worker 两臂修复链
policy 的单源。

门面回引名单见 ``texlate.pipecore._LEAF_EXPORTS``。
monkeypatch 锚点：setattr patch 须指本叶，指门面无效。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from texlate.repair import ENV_NO_FIXLOOP
from texlate.repair_l2 import ENV_NO_L2
from texlate.textutil import env_flag
from texlate.textutil.osutil import opt_switch

if TYPE_CHECKING:
    from collections.abc import Mapping


def _opt_switch(
    options: Mapping[str, Any] | None,
    key: str,
    env_name: str,
    *,
    explicit: bool | None,
) -> bool:
    """修复链单开关决议：``explicit`` > ``options[key]`` > ``not env_flag``——薄壳。

    三层链与 ``"0"/"false"/"no"/"off"`` 字符串 false 系归一化单源在
    ``textutil.osutil.opt_switch``；``TEXLATE_NO_*`` env 是「关」语义，
    取反喂入故缺省皆开。e2e 只喂 explicit、worker 只喂 options——两臂
    各自的两级闸是同一条优先级链上的不同入口。pipecore 内部件——
    worker 侧经 ``worker._common.opt_bool`` 本地化（``_seq_marks_on``）。
    """
    return opt_switch(
        options,
        key,
        lambda: not env_flag(env_name, default=False),
        explicit=explicit,
    )


@dataclass(frozen=True)
class RepairPolicy:
    """修复链开关决议快照——precheck/L2/fixloop 三级链闸的 policy 单源。

    e2e ``_repair_chain``（``fixloop_on``/``l2_on`` 显式闸）与 worker
    ``_compile_zh``（``options.*`` 闸）此前各复写同一条「显式 > options >
    ``TEXLATE_NO_*``（缺省皆开）」优先级链；``resolve`` 收成一处。
    precheck 闸随 ``fixloop``；``l2`` 另吃 ``precheck_reject`` 拒门与
    worker 侧 share 零 token 硬闸（臂内保留，不进本对象）。
    """

    fixloop: bool
    l2: bool

    @classmethod
    def resolve(
        cls,
        options: Mapping[str, Any] | None = None,
        *,
        fixloop_on: bool | None = None,
        l2_on: bool | None = None,
    ) -> RepairPolicy:
        """双闸同链决议：``*_on`` 显式 > ``options[键]`` > env 缺省开。"""
        return cls(
            fixloop=_opt_switch(
                options, "fixloop", ENV_NO_FIXLOOP, explicit=fixloop_on
            ),
            l2=_opt_switch(options, "l2", ENV_NO_L2, explicit=l2_on),
        )


def reject_verdict(verdict: object) -> bool:
    """``reject:<rid>`` verdict 判——precheck/fixloop 报告与终态合成同口径。"""
    return str(verdict or "").startswith("reject:")


def precheck_reject(rep: Mapping[str, Any] | None) -> bool:
    """``precheck`` 报告的 ``reject:<rid>`` 判（报告缺席按非拒）。"""
    return reject_verdict((rep or {}).get("verdict"))
