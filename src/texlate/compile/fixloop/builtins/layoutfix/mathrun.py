r"""builtins.layoutfix.mathrun — 行内数学断点 penalty 清零 + 强剂量 (layoutfix 拆分)。

fp unbreakable_para_run 臂: ``\relpenalty``/``\binoppenalty`` 归零 +
para_loosen 已注格就地升级强剂量 (``\emergencystretch=3em``/
``\tolerance=9999``)。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.builtins.common import _inject_before_begindoc

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx

__all__ = [
    "_LOOSEN_MARK",
    "_LOOSEN_UP_RX",
    "_MATHRUN_SNIPPET",
    "_MATHRUN_STRONG",
    "math_run_break",
]

#: 断点清零注入块——``\relpenalty``/``\binoppenalty`` 归零使行内数学在
#: 关系符/二元符后可断 (集合记法/元组 run 的不可断死结面; 默认 500/700
#: 的软禁在长 run 里等价不可断)。
_MATHRUN_SNIPPET = (
    "% texlate-fixloop: math-run break hints\n"
    "\\relpenalty=0\\relax\n"
    "\\binoppenalty=0\\relax"
)

#: 强剂量——para_loosen 未注时随本块同注 (断不开的段落仍需三遍排版
#: 兜底); 已注走就地升级 (下方正则臂)。
_MATHRUN_STRONG = "\n\\emergencystretch=3em\\relax\n\\tolerance=9999\\relax"

#: ``para_loosen`` 注入块标记行 (builtins.optfix._LOOSEN_SNIPPET 首行)——
#: 已注检出即升级剂量而非重注 (同位赋值后注后胜，不叠注语义靠升级臂)。
_LOOSEN_MARK = "% texlate-fixloop: overfull-hbox mitigation"
_LOOSEN_UP_RX = (
    (re.compile(r"\\emergencystretch\s*=\s*[\d.]+em"), "\\emergencystretch=3em"),
    (re.compile(r"\\tolerance\s*=\s*\d+"), "\\tolerance=9999"),
)


def math_run_break(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""warn_overfull 行内数学臂: penalty 清零 + 强排版剂量。

    实证面 (qc unbreakable_para_run 桶, 24 格): ``$...$`` 长 run
    (set-builder/braket/pmatrix/tuple/CJK 混排) 无合法断点把词间 glue
    拉竭——``\relpenalty=0 \binoppenalty=0`` 放开关系/二元符后断点;
    ``\emergencystretch=3em \tolerance=9999`` 强剂量对 para_loosen
    已注格就地升级 (标记行检出), 未注格随本块同注——两条目同
    warn_overfull 驱动面不互抢 (同标记共存稿各臂按序收)。

    ``\Big\{…\Big\}`` 单原子不可断格 (0806.2533 180pt 实证) 断点全缺
    本臂无解——promotion (overfull 内联数 → display) 未实装, 留
    known_gap。
    """
    del eng, payload, params
    main = ctx.main_path()
    if main is None:
        return False, "no main file"
    t = ctx.read(main)
    if t is None:
        return False, "main unreadable"
    parts: list[str] = []
    nt = t
    if _LOOSEN_MARK in nt:  # para_loosen 已注 → 就地升级强剂量
        for rx, rep_s in _LOOSEN_UP_RX:
            nt = rx.sub(rep_s, nt)
        if nt != t:
            ctx.write(main, nt)
            parts.append("loosen dose upgraded to tier2 (3em/9999)")
            t = nt
    if _MATHRUN_SNIPPET.split("\n", 1)[0] not in t:
        snippet = _MATHRUN_SNIPPET + ("" if _LOOSEN_MARK in t else _MATHRUN_STRONG)
        if _inject_before_begindoc(ctx, snippet, fallback="head"):
            parts.append(
                "injected \\relpenalty/\\binoppenalty=0"
                + ("" if _LOOSEN_MARK in t else " +tier2 stretch")
            )
    if not parts:
        return False, "math-run hints already present"
    return True, "; ".join(parts)
