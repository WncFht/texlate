r"""``latex.reconstruct.emit`` — splice 落稿哨兵（``reconstruct`` god-file 机械拆分叶）。

``splice_emit_issues`` 四臂体检：``emit_brace_skew`` 花括净深背离 /
``emit_env_unpaired`` env 配对崩坏 / ``emit_trans_dropped`` 交付译文
字符加权覆盖 <90% / ``emit_fffd``+``emit_c1_ctrl`` 解码腐坏烙渣。
只报不拦——note 串由调用方并入 ``slot_diffs`` 对账通道。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Final

from texlate.latex.placeholder import PH_RX
from texlate.latex.reconstruct.mark import _brace_events
from texlate.textutil import mask_tex

_ENV_TOKEN_COUNT_RX = re.compile(r"\\(begin|end)\s*\{([^{}\s]+)\}")
#: C1 控制面（U+0080–U+009F）——双编码残渣烙进产物的哨兵（2105.03852
#: ``Popovi─Н``/2208.00132 ``SipÅ\x91cz`` 类，上游 decode 漏检的落稿兜捕）。
_C1_CTRL_RX = re.compile(r"[\x80-\x9f]")

#: ``emit_trans_dropped`` 覆盖加权的片段长度下限——短片段对 post-fix
#: 触碰过敏，低于此长不进字符加权口径。
_SEG_HIT_MIN_CHARS: Final = 6


def splice_emit_issues(  # noqa: C901 — 四臂哨兵平铺即清单
    src_tex: str,
    zh_tex: str,
    translations: dict[int, str] | None,
    rel: str,
) -> list[str]:
    r"""Splice 落稿哨兵：zh 产物体检 → note 串（``[]``=干净，``emit_*`` 命名）。

    - ``emit_brace_skew``：src/zh 花括净深背离（0905.2435 类——
      ``\edcorr{a}{b}`` 第二实参被译文抬出括号、配对区发散）；
      双侧取 ``mask_tex`` 遮盖视图净深**差**，src 自带失衡不重复归咎。
    - ``emit_env_unpaired``：zh 内某环境 ``\begin``/``\end`` 数不等且
      src 同环境配对正常——splice/译文新引入的配对崩坏（译文内补写
      ``\begin`` 忘 ``\end`` 即此形）。
    - ``emit_trans_dropped``：交付译文逐字面段（``[[PH_n]]`` 占位符切开）
      逐字出现在 zh 的字符加权覆盖 <90%——2508.03541 abstract 完整交付
      而产物半途截断类。
    - ``emit_fffd``/``emit_c1_ctrl``：U+FFFD/C1 控制面烙进 zh 源——
      上游解码腐坏的落稿端可见哨兵。

    只报不拦：note 由调用方并入 ``slot_diffs`` 对账通道。
    """
    issues: list[str] = []

    def _brace_depth(text: str) -> int:
        d = 0
        for ev, _name in _brace_events(mask_tex(text)):
            d += 1 if ev == "open" else -1
        return d

    skew = _brace_depth(zh_tex) - _brace_depth(src_tex)
    if skew:
        issues.append(f"emit_brace_skew:{rel}:{skew:+d}")

    def _env_delta(text: str) -> Counter[str]:
        d: Counter[str] = Counter()
        for m in _ENV_TOKEN_COUNT_RX.finditer(mask_tex(text)):
            d[m.group(2)] += 1 if m.group(1) == "begin" else -1
        return d

    src_env = _env_delta(src_tex)
    zh_env = _env_delta(zh_tex)
    new_unpaired = sorted(
        name for name, d in zh_env.items() if d != 0 and src_env.get(name, 0) == 0
    )
    if new_unpaired:
        issues.append(f"emit_env_unpaired:{rel}:{','.join(new_unpaired[:6])}")

    if translations:
        total = hit = 0
        for t in translations.values():
            for seg in PH_RX.split(t):
                seg_s = seg.strip()
                if len(seg_s) < _SEG_HIT_MIN_CHARS:
                    continue
                total += len(seg_s)
                if seg_s in zh_tex:
                    hit += len(seg_s)
        if total and hit * 10 < total * 9:
            issues.append(f"emit_trans_dropped:{rel}:{hit * 100 // total}%")

    if (n := zh_tex.count("\ufffd")) > 0:
        issues.append(f"emit_fffd:{rel}:{n}")
    if (n := len(_C1_CTRL_RX.findall(zh_tex))) > 0:
        issues.append(f"emit_c1_ctrl:{rel}:{n}")
    return issues
