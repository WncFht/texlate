"""specs.validbench.corrupt — c01–c10 破坏算子叶 (validbench 拆分叶).

(gen_cases.py c01–c10 照搬; rv.PH_RX/KEY_CMD_RX → rules.PH_ANY_LIKE_RX/KEY_CMD_RX 同口径。
 产品化修订 (全部有实测漏检出典): 候选一律限注释区外 (rules 规则经 mask_comments
 豁免注释，注释内破坏是语义 no-op); c06 修 `]` 补回合法 token 的自愈路径与
 裸标记无数字回退; c07 用 _lex bs token 选真定界符 (\\\\[5pt] 的 \\[ 不算);
 c09 跳过空 key 匹配如 \\bibitem[]{}; c08/c10 插入位按"前一字符在注释内即死".)
"""

from __future__ import annotations

import bisect
import re
from typing import TYPE_CHECKING

from specs import _bootstrap

_bootstrap.ensure()

from texlate.validate import rules

if TYPE_CHECKING:
    import random


def _comment_spans(s: str) -> list[int]:
    """注释区间 [start,end) 排序扁平表 (rules._lex 的 cmt token), 供 bisect 查."""
    spans: list[int] = []
    for kind, text, pos in rules._lex(s):
        if kind == "cmt":
            spans += [pos, pos + len(text)]
    return spans


def _in_comment(spans: list[int], pos: int) -> bool:
    """``pos`` 落在注释区间 → True (spans 为扁平 [s0,e0,s1,e1,...])."""
    i = bisect.bisect_right(spans, pos)
    return bool(i % 2)


def _live_insert_positions(s: str, spans: list[int]) -> list[int]:
    """可插入位：落在 ``pos`` 的文本拼进 ``s[pos-1]`` 所在词法区 ——
    ``pos-1`` 在注释内即注释内插入 (含注释行尾 ``\\n`` 前位，实测漏检来源)."""
    return [p for p in range(len(s) + 1) if p == 0 or not _in_comment(spans, p - 1)]


def _unescaped_positions(s: str, ch: str) -> list[int]:
    """``ch`` 的非转义/非注释出现位——``rules._lex`` ch token 自带豁免
    (bs/cmt 不进 ch), 且注释止于 ``[\\r\\n]`` 比手扫的 ``\\n`` 更严."""
    return [pos for kind, text, pos in rules._lex(s) if kind == "ch" and text == ch]


def _pick_uncommented(
    zh: str, rx: re.Pattern, rng: random.Random, keep=None
) -> re.Match | None:
    """注释区外候选随机取一 (rules 规则经 mask_comments 豁免注释 —— 注释内
    破坏是语义 no-op); ``keep`` 附加过滤 (如 c09 空 key 不计多重集)."""
    spans = _comment_spans(zh)
    ms = [
        m
        for m in rx.finditer(zh)
        if not _in_comment(spans, m.start()) and (keep is None or keep(m))
    ]
    return None if not ms else ms[rng.randrange(len(ms))]


def c01_drop_rbrace(zh: str, rng: random.Random) -> str | None:
    pos = _unescaped_positions(zh, "}")
    if not pos:
        return None
    p = pos[rng.randrange(len(pos))]
    return zh[:p] + zh[p + 1 :]


def c02_drop_dollar(zh: str, rng: random.Random) -> str | None:
    pos = _unescaped_positions(zh, "$")
    if not pos:
        return None
    p = pos[rng.randrange(len(pos))]
    return zh[:p] + zh[p + 1 :]


_END_RX = re.compile(r"\\end\{[^{}]*\}")


def c03_rename_end(zh: str, rng: random.Random) -> str | None:
    m = _pick_uncommented(zh, _END_RX, rng)
    if m is None:
        return None
    begins = {m.group(1) for m in re.finditer(r"\\begin\{([^{}]*)\}", zh)}
    name = re.match(r"\\end\{([^{}]*)\}", m.group(0)).group(1)
    alts = [b for b in begins if b != name]
    new = rng.choice(alts) if alts else name + "*"
    return zh[: m.start()] + "\\end{" + new + "}" + zh[m.end() :]


def c04_drop_end(zh: str, rng: random.Random) -> str | None:
    m = _pick_uncommented(zh, _END_RX, rng)
    if m is None:
        return None
    return zh[: m.start()] + zh[m.end() :]


def c05_drop_ph(zh: str, rng: random.Random) -> str | None:
    m = _pick_uncommented(zh, rules.PH_ANY_LIKE_RX, rng)
    if m is None:
        return None
    return zh[: m.start()] + zh[m.end() :]


def c06_typo_ph(zh: str, rng: random.Random) -> str | None:
    m = _pick_uncommented(zh, rules.PH_ANY_LIKE_RX, rng)
    if m is None:
        return None
    tok = m.group(0)
    inner = tok[2:-2]
    # 变体菜单; 某些变体在特定上下文是语义 no-op 要避开：
    #   v1 掉 ] —— 若 match 后紧跟 ] (如 [[REF_1]]] 外层括号), 截断后与残余 ]
    #       重新拼成合法 token → 自愈，校验器正确地无报 → 该上下文禁选 v1
    #   v2 改数字 index —— 裸标记 ([[SL]] 无 \d+) 无 index 可改 → 回退 v0
    variants = []
    inner2 = inner[:-1] + ("Z" if inner[-1] != "Z" else "Y")
    variants.append("[[" + inner2 + "]]")  # v0: 内部末字符改字母 lev=1
    if zh[m.end() : m.end() + 1] != "]":
        variants.append(tok[:-1])  # v1: 掉一个 ] lev=1
    d = re.search(r"\d+", inner)
    if d:
        variants.append(
            "[[%s%d]]" % (inner[: d.start()], int(d.group(0)) + 7)
        )  # v2: 合法 token 集合错位 lev<=2
    new = variants[rng.randrange(len(variants))]
    return zh[: m.start()] + new + zh[m.end() :]


def c07_unpair_lbrack(zh: str, rng: random.Random) -> str | None:
    # 候选取 rules._lex 的 bs token —— 正则 \\\] 会把 \\[5pt] 的 \[ (linebreak
    # 可选参，非 display 定界符) 算进来，删了不在 math 词表 = 语义 no-op
    # (实测漏检来源); bs token 自带注释/转义豁免。
    rb = [pos for kind, text, pos in rules._lex(zh) if kind == "bs" and text == "\\]"]
    if rb:
        p = rb[rng.randrange(len(rb))]
        return zh[:p] + zh[p + 2 :]
    lb = [pos for kind, text, pos in rules._lex(zh) if kind == "bs" and text == "\\["]
    if not lb:
        return None
    p = lb[rng.randrange(len(lb))]
    return zh[:p] + zh[p + 2 :]


def c08_halluc_macro(zh: str, rng: random.Random) -> str | None:
    ins = "\\newcommand{\\zhxbox}[1]{\\fbox{#1}}\\zhxbox{译注}"
    live = _live_insert_positions(zh, _comment_spans(zh))
    pos = live[rng.randrange(len(live))]
    return zh[:pos] + "\n" + ins + "\n" + zh[pos:]


def c09_drop_key(zh: str, rng: random.Random) -> str | None:
    # 空 key 不计多重集; KEY_CMD_RX 三臂的 key 落在不同 group —— 逐组扫
    # (原 m.group(1) 对 \cite/\label 臂恒 None, 实测直接 AttributeError)
    m = _pick_uncommented(
        zh,
        rules.KEY_CMD_RX,
        rng,
        keep=lambda m: any(k.strip() for g in m.groups() if g for k in g.split(",")),
    )
    if m is None:
        return None
    return zh[: m.start()] + zh[m.end() :]


def c10_extra_ph(zh: str, rng: random.Random) -> str | None:
    live = _live_insert_positions(zh, _comment_spans(zh))
    pos = live[rng.randrange(len(live))]
    return zh[:pos] + "[[MATH_9999]]" + zh[pos:]


CORRUPTIONS = [
    ("c01_drop_rbrace", c01_drop_rbrace),
    ("c02_drop_dollar", c02_drop_dollar),
    ("c03_rename_end", c03_rename_end),
    ("c04_drop_end", c04_drop_end),
    ("c05_drop_ph", c05_drop_ph),
    ("c06_typo_ph", c06_typo_ph),
    ("c07_unpair_lbrack", c07_unpair_lbrack),
    ("c08_halluc_macro", c08_halluc_macro),
    ("c09_drop_key", c09_drop_key),
    ("c10_extra_ph", c10_extra_ph),
]
