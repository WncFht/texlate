r"""占位符编解码与 src↔zh 对账（规格 docs/08 §1.3/§1.6，口径对齐 L0 校验层）。

契约边界：
- `[[TYPE_n]]` 带号占位符——`ph_map` 侧受保护片段；PhType 全枚举（含
  ENV/COMMENT/COND/ENVTAG 等 in_arg 产物）均走此形态。
- `[[NAME]]` 裸标记仅 SL/PL 换行编码系（`[[SL]]`/`[[PL]]` 及 `_RAW` 变体）——无 `_n` 后缀。
- 换行编码只接管段内 `\n`（分段边界在 chunk 层管理，`[[PL]]` 仅作 `\n\n+` 防御编码）。
- 占位符多重集 diff + lev≤2 模糊配对与 `rule_validator.check_placeholder` 同口径——
  本模块是 xlat 层自带的轻量对账，正式 L0 校验器就绪后经 `PhValidator` 协议替换。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

from texlate.latex.placeholder import PH_RX
from texlate.textutil import lev_capped, mask_comments

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

#: 模糊占位符候选（zh 侧）：完整 [[..]] / 缺右括号 / 单层 [X_n] / 【..】（与 L0 同口径）
PH_FUZZY_RX = re.compile(
    r"\[\[[^\[\]\n]{1,48}?\]\]"  # [[..]] 完整（含全角/空格等变体）
    r"|\[\[[^\[\]\n]{1,48}?\](?!\])"  # [[..] 缺右括号
    r"|(?<!\[)\[[A-Za-z_]+_?-?\d+\](?!\])"  # [X_1] 单层括号
    r"|【[^【】\n]{1,48}?】"  # 【..】 CJK 括号
)

#: 换行编码 token
SOFT_NEWLINE = "[[SL]]"
PARA_NEWLINE = "[[PL]]"
#: 源文本字面 `[[SL]]`/`[[PL]]` 的转义形态（防编码碰撞，照 ieeA 两级转义）
SOFT_NEWLINE_RAW = "[[SL_RAW]]"
PARA_NEWLINE_RAW = "[[PL_RAW]]"
_SOFT_NEWLINE_SENTINEL = "[[__TEXLATE_SL_LIT__]]"
_PARA_NEWLINE_SENTINEL = "[[__TEXLATE_PL_LIT__]]"

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

    先做字面 token 两级转义防碰撞，再编码；返回 (编码文本, {source_sl, source_pl})。
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    # 字面转义：先保 sentinel 级（源里若真有 [[SL_RAW]] 不能再被第二轮吃掉）
    escaped = normalized.replace(SOFT_NEWLINE_RAW, _SOFT_NEWLINE_SENTINEL)
    escaped = escaped.replace(PARA_NEWLINE_RAW, _PARA_NEWLINE_SENTINEL)
    escaped = escaped.replace(SOFT_NEWLINE, SOFT_NEWLINE_RAW)
    escaped = escaped.replace(PARA_NEWLINE, PARA_NEWLINE_RAW)

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
    r"""`[[SL]]`→`\n`、`[[PL]]`→`\n\n`，随后还原被转义的字面 token。"""
    decoded = text.replace(PARA_NEWLINE, "\n\n").replace(SOFT_NEWLINE, "\n")
    decoded = decoded.replace(SOFT_NEWLINE_RAW, SOFT_NEWLINE)
    decoded = decoded.replace(PARA_NEWLINE_RAW, PARA_NEWLINE)
    decoded = decoded.replace(_SOFT_NEWLINE_SENTINEL, SOFT_NEWLINE_RAW)
    return decoded.replace(_PARA_NEWLINE_SENTINEL, PARA_NEWLINE_RAW)


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


def diff(src: str, zh: str) -> PhDiff:
    """占位符多重集差分 + lev≤2 模糊配对（与 L0 `check_placeholder` 同口径，含注释豁免）。

    xlat 语境下 src 内注释多已被 scanner 折叠为 `[[COMMENT]]`，但 zh 可能裸带 `%`；
    双侧豁免与 L0 完全对齐，防"模型把占位符写进注释"造成误判。
    """
    snc, znc = mask_comments(src), mask_comments(zh)
    scnt = Counter(ANY_PH_RX.findall(snc))
    zcnt = Counter(ANY_PH_RX.findall(znc))
    missing = sorted((scnt - zcnt).elements())
    # 模糊候选 = zh 侧多余完整 token + 拼变体；扫未遮盖 zh 与 L0 同口径
    # （注释里的候选一样喂 lev 配对——错了顶多多一条 misspelled 提示）
    cands = list((zcnt - scnt).elements())
    cands += [
        m.group(0)
        for m in PH_FUZZY_RX.finditer(zh)
        if not ANY_PH_RX.fullmatch(m.group(0))
    ]
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


#: xlat 侧对账协议——正式 L0 校验器实现同签名即可无缝替换 `diff`
class PhValidator:
    """占位符校验器协议（可插拔点：接 `texlate.validate` L0 后用同一签名）。"""

    def __call__(self, src: str, zh: str) -> PhDiff:  # pragma: no cover - 协议声明
        """返回 src↔zh 占位符对账。"""


def collect_doc_placeholders(contents: Iterable[str]) -> list[str]:
    """收集文档全部 chunk 的占位符集合，按 `sort_key` 稳定排序（术语表注入用）。"""
    seen: set[str] = set()
    for text in contents:
        seen.update(ANY_PH_RX.findall(text))
    return sorted(seen, key=sort_key)
