"""validate.rules.main — rules 主入口叶 (validate.rules 域缝叶)。

``_CHECKERS`` 全量检查表（序即执行序——新增/移除检查只动本表一条目，
调用点迭代驱动自动并入）+ ``CACHE_VETO_RULES`` 缓存否决级规则集
（``xlat.intercept._INTERCEPT_NETS`` 各 ``mirror_rule`` 镜像钉，双向钉
由 ``TestInterceptRegistry`` 拦截漂移）+ ``validate_pair``/
``pair_feedback`` 对外入口。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from texlate.validate.rules.cs import (
    _check_bare_cs,
    _check_dangerous_cs,
    _check_item_glue,
    _check_macro,
    _check_ph_in_cs,
)
from texlate.validate.rules.guard import (
    _check_comment_eof,
    _check_protocol_echo,
)
from texlate.validate.rules.lex import _Ctx
from texlate.validate.rules.ph import _check_placeholder
from texlate.validate.rules.prose import (
    _check_length,
    _check_residual_en,
    _check_same_source,
)
from texlate.validate.rules.report import RulesReport
from texlate.validate.rules.struct import (
    _check_brace,
    _check_env,
    _check_key,
    _check_math,
)

if TYPE_CHECKING:
    from collections.abc import Callable

#: 缓存否决级规则 id 集——pipeline 升格拦截网（``xlat.pipeline._INTERCEPT_NETS``
#: 各条 ``mirror_rule`` 字段）镜像复判的 rules 规则集：段级缓存命中与续跑装载旁路
#: ``validate_pair``，这五类 error 级标记由拦截网兜底防毒译出货
#: （``placeholder`` 网只镜像 zh−src 净多出占位符臂——缺失/锚定臂归阶梯
#: 修复管辖）。与注册表成员双向钉，漂移由 ``TestInterceptRegistry`` 拦截。
CACHE_VETO_RULES: Final = frozenset(
    {"placeholder", "ph_in_cs", "bare_cs", "residual_en", "dangerous_cs"}
)


#: ``validate_pair`` 全量检查表（序即执行序）——新增/移除检查只动本表
#: 一条目，调用点迭代驱动自动并入，不再逐名点名。入参 ``_Ctx`` 携
#: 共享预处理视图，各 checker 按需取用不再重复推导。
_CHECKERS: Final[tuple[Callable[[_Ctx], None], ...]] = (
    _check_placeholder,
    _check_brace,
    _check_env,
    _check_key,
    _check_math,
    _check_same_source,
    _check_length,
    _check_residual_en,
    _check_macro,
    _check_item_glue,
    _check_ph_in_cs,
    _check_bare_cs,
    _check_dangerous_cs,
    _check_protocol_echo,
    _check_comment_eof,
)


def validate_pair(src: str, zh: str) -> RulesReport:
    """对 ``(src_chunk, zh_chunk)`` 跑 ``_CHECKERS`` 全表检查，返回结构化 verdict。

    ``report.ok`` 为 True 即可送 cst/拼回；False 时 ``report.feedback()``
    的文本可直接进 corrector 的 ``previous_validation_error`` 字段。
    """
    rep = RulesReport(src_len=len(src), zh_len=len(zh))
    ctx = _Ctx(src, zh, rep.issues)
    for check in _CHECKERS:
        check(ctx)
    return rep


def pair_feedback(src: str, zh: str) -> str:
    """``validate_pair(src, zh).feedback()``——pipeline.validator 签名对齐版。

    四个调用臂（e2e/pipecore/worker×2）曾各手写同一 RulesReport→str lambda
    适配；反馈文本语义归本层。
    """
    return validate_pair(src, zh).feedback()
