r"""占位符编解码与 src↔zh 对账（规格 docs/08 §1.3/§1.6，口径对齐 L0 校验层）。

契约边界：
- `[[TYPE_n]]` 带号占位符——`ph_map` 侧受保护片段；PhType 全枚举（含
  ENV/COMMENT/COND/ENVTAG 等 in_arg 产物）均走此形态。
- `[[NAME]]` 裸标记仅 SL/PL 换行编码系与脆弱空白族间距保护（`[[SL]]`/`[[PL]]`/`[[SP]]`/`[[NBSP]]`/`[[THINSP]]`/`[[MEDSP]]`/`[[THICKSP]]`/`[[NEGSP]]` 及 `_RAW` 变体）——无 `_n` 后缀。
- 换行编码只接管段内 `\n`（分段边界在 chunk 层管理，`[[PL]]` 仅作 `\n\n+` 防御编码）。
- 占位符多重集 diff + lev≤2 模糊配对与 `rule_validator.check_placeholder` 同口径——
  本模块是 xlat 层自带的轻量对账，正式校验器经 pipeline 的
  `validator(src, zh) -> str` 缝替换（返回空串=通过）。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

from texlate.latex.placeholder import PH_RX
from texlate.textutil import PH_FUZZY_RX, lev_capped, mask_comments

# ---------------------------------------------------------------- 正则

#: 带号占位符 [[TYPE_n]]——签发侧唯一定义在 ``latex.placeholder.PH_RX``，此处为别名
TYPED_PH_RX = PH_RX
#: 裸结构标记——实际产出只有 [[SL]]/[[PL]] 系；ENV/COMMENT/COND/ENVTAG 是
#: PhType 成员、走带号 [[ENV_n]] 形态。本正则取超集口径（zh 侧任何裸 ALLCAPS
#: 标记都算候选，含模型臆造的 [[ENV]] 类变体），与 TYPED_PH_RX 不相交——
#: `[A-Z_]+` 不吃数字。
BARE_PH_RX = re.compile(r"\[\[[A-Z][A-Z_]*\]\]")
#: 任一占位符形态
ANY_PH_RX = re.compile(rf"(?:{TYPED_PH_RX.pattern})|(?:{BARE_PH_RX.pattern})")
#: 纯占位符 chunk（可含空白分隔的多个占位符）——不发请求直接落盘
PURE_PH_RX = re.compile(
    rf"\s*(?:{ANY_PH_RX.pattern})(?:\s+(?:{ANY_PH_RX.pattern}))*\s*"
)

#: 换行编码 token
SOFT_NEWLINE = "[[SL]]"
PARA_NEWLINE = "[[PL]]"
#: 源文本字面 `[[SL]]`/`[[PL]]` 的转义形态（防编码碰撞）
SOFT_NEWLINE_RAW = "[[SL_RAW]]"
PARA_NEWLINE_RAW = "[[PL_RAW]]"
#: 脆弱间距命令 `\ ` 的保护 token——裸 `\ ` 对模型不显著（E21/E22 cs_dropped
#: 实测主因，s40 11/4365 chunk 因此三振），编码成占位符吃 C9 保护契约；
#: decode 回 `\ ` 后才进校验，L0 计数口径不变。同族扩列 (2026-09-17,
#: realpostfix2 E22 实证: 2203.13012 `~` 丢、2403.15096 `\,`/`\;` 丢) ——
#: `~`/`\,`/`\:`/`\;`/`\!` 各占一 token 保 decode 无损; 裸标记语法
#: [A-Z_]+ 不吃数字, 命名不带参数位。
SOFT_SPACE = "[[SP]]"
#: 源文本字面 `[[SP]]` 的转义形态
SOFT_SPACE_RAW = "[[SP_RAW]]"
NBSP = "[[NBSP]]"  # `~` 不可断空格
NBSP_RAW = "[[NBSP_RAW]]"
THINSP = "[[THINSP]]"  # `\,`
THINSP_RAW = "[[THINSP_RAW]]"
MEDSP = "[[MEDSP]]"  # `\:`
MEDSP_RAW = "[[MEDSP_RAW]]"
THICKSP = "[[THICKSP]]"  # `\;`
THICKSP_RAW = "[[THICKSP_RAW]]"
NEGSP = "[[NEGSP]]"  # `\!` 负 thin
NEGSP_RAW = "[[NEGSP_RAW]]"

#: 字面转义链族表——(tag, token, RAW 形, 源字面)。字面 token 的防碰撞转义是
#: 不限定深的闭链：``token→RAW→sentinel(2)→sentinel(3)→…`` 逐级升层
#: （sentinel 级名程序化生成，见 ``_sentinel``），decode 反向逐级降回——
#: 替代旧定深四相链（开放端：源含 ``LIT2`` 级以上字面时 decode 降级失真）。
#: SL/PL 族源字面是换行游程不由 lit 位编码（lit 空串占位），其余六族
#: lit 是 TeX 脆弱间距字面（互不为子串，族内序位无关）。
_NEWLINE_FAM: tuple[tuple[str, str, str, str], ...] = (
    ("SL", SOFT_NEWLINE, SOFT_NEWLINE_RAW, ""),
    ("PL", PARA_NEWLINE, PARA_NEWLINE_RAW, ""),
)
_SPACE_FAM: tuple[tuple[str, str, str, str], ...] = (
    ("SP", SOFT_SPACE, SOFT_SPACE_RAW, "\\ "),
    ("NBSP", NBSP, NBSP_RAW, "~"),
    ("THINSP", THINSP, THINSP_RAW, "\\,"),
    ("MEDSP", MEDSP, MEDSP_RAW, "\\:"),
    ("THICKSP", THICKSP, THICKSP_RAW, "\\;"),
    ("NEGSP", NEGSP, NEGSP_RAW, "\\!"),
)
#: 全族序——各族 token/RAW/sentinel 名面互不为子串，升降链逐族独立应用。
_ALL_FAM: tuple[tuple[str, str, str, str], ...] = _NEWLINE_FAM + _SPACE_FAM

#: 各族哨兵级扫描器：``LIT``=level 2、``LIT{n}``=level n+1。
_SENT_RX = {
    tag: re.compile(rf"\[\[__TEXLATE_{tag}_LIT(\d*)__\]\]")
    for tag, _tok, _raw, _lit in _ALL_FAM
}

#: 转义链首个哨兵级（RAW 之上）——``LIT`` 形无数字后缀。
_SENT_BASE = 2


def _sentinel(tag: str, level: int) -> str:
    """转义链 level≥2 的哨兵名：2→``[[__TEXLATE_{tag}_LIT__]]``、k≥3→``LIT{k-1}``。"""
    n = "" if level == _SENT_BASE else str(level - 1)
    return f"[[__TEXLATE_{tag}_LIT{n}__]]"


def _max_sentinel_level(text: str, tag: str) -> int:
    """文中出现的最高哨兵级（无 → ``_SENT_BASE - 1``）。"""
    best = _SENT_BASE - 1
    for d in _SENT_RX[tag].findall(text):
        best = max(best, _SENT_BASE if not d else int(d) + 1)
    return best


def _escape_family(text: str, tag: str, tok: str, raw: str) -> str:
    """单族字面转义闭链。

    哨兵自顶向下逐级 bump（sent(k)→sent(k+1)），再 RAW→sent(2)、
    token→RAW——任意深的字面 token 升一层即脱离当前级，先升高级故产物
    不会被本级及以下的后续替换二次吃掉。
    """
    for k in range(_max_sentinel_level(text, tag), _SENT_BASE - 1, -1):
        text = text.replace(_sentinel(tag, k), _sentinel(tag, k + 1))
    return text.replace(raw, _sentinel(tag, _SENT_BASE)).replace(tok, raw)


def _unescape_family(text: str, tag: str, tok: str, raw: str) -> str:
    """解码降链。

    RAW→token、sent(2)→RAW，再 sent(k)→sent(k-1) 自 3 升序——k 级降出的
    k-1 级是终态字面（其档位已过），不会被二次降。
    """
    text = text.replace(raw, tok).replace(_sentinel(tag, _SENT_BASE), raw)
    for k in range(_SENT_BASE + 1, _max_sentinel_level(text, tag) + 1):
        text = text.replace(_sentinel(tag, k), _sentinel(tag, k - 1))
    return text


_FUZZY_LEV_CAP = 2


# ---------------------------------------------------------------- 基础操作


def find_all(text: str) -> list[str]:
    """返回文本中出现的全部占位符（去重、按首次出现序）。"""
    return list(dict.fromkeys(ANY_PH_RX.findall(text)))


def sort_key(ph: str) -> tuple[str, int]:
    """占位符稳定排序键：TYPE 字典序 + n 数值序（裸标记按 n=-1 排同型之前）。

    前缀缓存命中要求 term_dict 注入顺序逐字节稳定，此键是排序唯一事实源。
    """
    body = ph.strip("[]")
    head, _, tail = body.rpartition("_")
    if head and tail.isdigit():
        return (head, int(tail))
    return (body, -1)


def is_placeholder_only(text: str) -> bool:
    """Chunk 内容是否纯由占位符构成（+ 空白）——此类不发请求，translation=source。"""
    return bool(PURE_PH_RX.fullmatch(text))


#: `\n\n+` 判空段下限（`\n` 是 SL、`\n\n` 起算 PL）
_PARA_BREAK_MIN = 2


def encode_newlines(text: str) -> tuple[str, dict[str, int]]:
    r"""段内换行 → `[[SL]]`，`\n\n+` → `[[PL]]`（防御编码，正常 chunk 不该有空段）。

    先做字面 token 逐级转义防碰撞（不限定深闭链——族内自顶向下升层，
    任意深字面 token 都能无损 round-trip），再编码；返回
    (编码文本, {source_sl, source_pl})。
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    escaped = normalized
    for tag, tok, raw, _lit in _ALL_FAM:
        escaped = _escape_family(escaped, tag, tok, raw)
    for _tag, tok, _raw, lit in _SPACE_FAM:
        escaped = escaped.replace(lit, tok)

    out: list[str] = []
    i, n = 0, len(escaped)
    sl = pl = 0
    while i < n:
        if escaped[i] == "\n":
            j = i
            while j < n and escaped[j] == "\n":
                j += 1
            run = j - i
            if run >= _PARA_BREAK_MIN:
                # k 个换行 = [[PL]]×(k//2) + [[SL]]×(k%2)——k≥3 无损 round-trip
                out.append(PARA_NEWLINE * (run // _PARA_BREAK_MIN))
                pl += run // _PARA_BREAK_MIN
                if run % _PARA_BREAK_MIN:
                    out.append(SOFT_NEWLINE)
                    sl += 1
            else:
                out.append(SOFT_NEWLINE)
                sl += 1
            i = j
        else:
            out.append(escaped[i])
            i += 1
    return "".join(out), {"source_sl": sl, "source_pl": pl}


def decode_newlines(text: str) -> str:
    r"""`[[SL]]`→`\n`、`[[PL]]`→`\n\n`、空白族 token→字面，随后还原被转义的字面 token。"""
    decoded = text.replace(PARA_NEWLINE, "\n\n").replace(SOFT_NEWLINE, "\n")
    for _tag, tok, _raw, lit in _SPACE_FAM:
        decoded = decoded.replace(tok, lit)
    for tag, tok, raw, _lit in _ALL_FAM:
        decoded = _unescape_family(decoded, tag, tok, raw)
    return decoded


# ---------------------------------------------------------------- src↔zh 对账


@dataclass
class PhDiff:
    """占位符 src↔zh 对账结果。`ok` = 无缺失/多余/拼错。"""

    missing: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)
    #: (译文里的疑似拼错 token, 期望 token) —— lev≤2 配对，可自动修复
    misspelled: list[tuple[str, str]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """无差异。"""
        return not (self.missing or self.extra or self.misspelled)

    def describe(self) -> str:
        """一行错误描述，喂给 corrector 的 [Error] 段 / errors_report。"""
        parts = [f"missing placeholder: {ph}" for ph in self.missing]
        parts += [f"extra/unrecognized placeholder: {ph}" for ph in self.extra]
        parts += [
            f"misspelled placeholder: '{bad}' should be '{good}'"
            for bad, good in self.misspelled
        ]
        return "; ".join(parts)


def _ph_in_comments(s: str, masked: str) -> Counter[str]:
    """注释区内占位符多重集 = 原文计数 − masked 计数（mask 保位等长，差集恰是注释区）。"""
    return Counter(ANY_PH_RX.findall(s)) - Counter(ANY_PH_RX.findall(masked))


def diff(src: str, zh: str) -> PhDiff:
    """占位符多重集差分 + lev≤2 模糊配对（与 L0 `check_placeholder` 同口径）。

    xlat 语境下 src 内注释多已被 scanner 折叠为 `[[COMMENT]]`，但 zh 可能裸带 `%`。
    注释豁免只盖内容差异——主比对仍对双侧 masked 文本做：正文占位符被挪进注释
    按 missing 抓、注释内容改写/整条丢弃不追责；另加注释区专项，zh 注释内净多出
    的占位符是 splice 字面残留（sabotage 实测逃逸），计 extra，与 L0 补丁同口径。
    """
    snc, znc = mask_comments(src), mask_comments(zh)
    scnt = Counter(ANY_PH_RX.findall(snc))
    zcnt = Counter(ANY_PH_RX.findall(znc))
    missing = sorted((scnt - zcnt).elements())
    # 模糊候选 = zh 侧多余完整 token + 拼变体；扫未遮盖 zh 与 L0 同口径
    # （注释里的候选一样喂 lev 配对——错了顶多多一条 misspelled 提示）
    cands = list((zcnt - scnt).elements())
    # src 里 verbatim 存在的同形 token（如引用标号 [RS80]）是原文内容而非
    # 臆造占位符——按净差计数豁免，与 L0 _check_placeholder 同口径
    src_literal = Counter(
        m.group(0)
        for m in PH_FUZZY_RX.finditer(src)
        if not ANY_PH_RX.fullmatch(m.group(0))
    )
    zh_fuzzy = Counter(
        m.group(0)
        for m in PH_FUZZY_RX.finditer(zh)
        if not ANY_PH_RX.fullmatch(m.group(0))
    )
    cands += list((zh_fuzzy - src_literal).elements())
    used: set[int] = set()
    out = PhDiff()
    for ph in missing:
        best_idx, best_d = -1, _FUZZY_LEV_CAP + 1
        for ci, cand in enumerate(cands):
            if ci in used:
                continue
            d = lev_capped(ph, cand, _FUZZY_LEV_CAP)
            if d < best_d:
                best_idx, best_d = ci, d
        if best_idx >= 0:
            used.add(best_idx)
            out.misspelled.append((cands[best_idx], ph))
        else:
            out.missing.append(ph)
    out.extra = [cand for ci, cand in enumerate(cands) if ci not in used]
    # 注释区专项：zh 注释内净多出的占位符计 extra——masked 主比对看不见，
    # splice 后字面残留。不进 cands：它不是 missing 的拼错候选，是独立缺陷。
    out.extra += sorted(
        (_ph_in_comments(zh, znc) - _ph_in_comments(src, snc)).elements()
    )
    return out


def recover_copied_tokens(zh: str, ph_map: Mapping[str, str]) -> tuple[str, list[str]]:
    """模型把受保护原文抄回译文时，**exact+unique** 才换回 token（docs/08 §1.6）。

    仅当占位符在 zh 中缺失、且其原文片段在 zh 中恰好出现一次时替换。
    返回 (修复后译文, 已修复占位符列表)。
    """
    present = set(ANY_PH_RX.findall(zh))
    recovered: list[str] = []
    # 长 fragment 先认领——`$x$` 是 `$$x$$` 的子串，短者先换会把长 fragment
    # 的副本啃坏（`$$x$$`→`$[[MATH_1]]$`），长者随之永远失配。
    for ph, fragment in sorted(ph_map.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        if ph in present or not fragment:
            continue
        if zh.count(fragment) == 1:
            zh = zh.replace(fragment, ph, 1)
            recovered.append(ph)
    return zh, recovered


def collect_doc_placeholders(contents: Iterable[str]) -> list[str]:
    """收集文档全部 chunk 的占位符集合，按 `sort_key` 稳定排序（术语表注入用）。"""
    seen: set[str] = set()
    for text in contents:
        seen.update(ANY_PH_RX.findall(text))
    return sorted(seen, key=sort_key)
