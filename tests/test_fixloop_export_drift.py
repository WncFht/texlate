"""fixloop builtins 门面导出漂移闸——``_export_drift()`` 审计钉零。

``texlate.compile.fixloop.builtins`` 是 PEP 562 惰性门面：``__all__`` /
``_LEAF_EXPORTS``（叶→名映射）/ ``_TRANSFORM_KEYS`` / 本地公共名四者任
一手改漏同步都是首访 ``AttributeError`` 定时弹。``_export_drift`` 是
模块内建的装载外审计件（零运行时消费方，专供测试），空表 = 同步；
门面结构的静态对拍（TYPE_CHECKING 块 ↔ ``_LEAF_EXPORTS``）在
``test_fixloop_builtins_facade.py``。
"""

from texlate.compile.fixloop import builtins


def test_export_drift_clean() -> None:
    """``builtins._export_drift()`` 全向审计 → 空表（无断链/幽灵/漏列）。"""
    assert builtins._export_drift() == []  # noqa: SLF001 -- 审计件即测试专用闸
