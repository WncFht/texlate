r"""占位符编解码与 src↔zh 对账（规格 docs/spec/translate.md，口径对齐 L0 校验层）。

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
#: 盲区登记（2026-09-17，不修）：转义哨兵 `[[__TEXLATE_{tag}_LIT{n}__]]` 以 `_`
#: 起头对 ANY_PH_RX/PH_ANY_LIKE_RX 均不可见——src/zh 对称不可见故保留即干净，
#: 但源字面即哨兵形时模型丢弃哨兵无信号（静默丢字面）。触发条件=源 .tex 字面
#: 含哨兵语法（真实语料≈0，自指/对抗文档才命中）；单级转义 `[[SL_RAW]]` 已在
#: 管辖内。若要收口须同步扩 ANY_PH_RX 与 l0.PH_ANY_LIKE_RX 两处口径。
BARE_PH_RX = re.compile(r"\[\[[A-Z][A-Z_]*\]\]")
#: 任一占位符形态
ANY_PH_RX = re.compile(rf"(?:{TYPED_PH_RX.pattern})|(?:{BARE_PH_RX.pattern})")
#: 纯占位符 chunk（可含空白分隔的多个占位符）——不发请求直接落盘
PURE_PH_RX = re.compile(
    rf"\s*(?:{ANY_PH_RX.pattern})(?:\s+(?:{ANY_PH_RX.pattern}))*\s*"
)

#: 批量 ``[n]`` 协议的退化残留：回复只剩序号桩 = 实质空译。
#: ``parse_batch_response`` 序号路径会把裸 ``[1]``（单块批的"空槽"回复）
#: 原样当译文留下——插出去是根号渣，按空译判 unchanged。xlat/batch.py
#: 的 ``_STUB_ONLY_RX`` 与 export/common.py 的 ``STUB_ONLY_RE`` 同口径
#: 单源在此（export/common.py 已 import 本模块，方向不反）。
STUB_ONLY_RX = re.compile(r"\s*(?:\[\d+\]\s*)+")

#: 换行编码 token
SOFT_NEWLINE = "[[SL]]"
PARA_NEWLINE = "[[PL]]"
#: 源文本字面 `[[SL]]`/`[[PL]]` 的转义形态（防编码碰撞）
SOFT_NEWLINE_RAW = "[[SL_RAW]]"
PARA_NEWLINE_RAW = "[[PL_RAW]]"
#: 脆弱间距命令 `\ ` 的保护 token——裸 `\ ` 对模型不显著（E21/E22 cs_dropped
#: 实测主因，s40 11/4365 chunk 因此三振），编码成占位符吃 Placeholders 条款保护契约；
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


def _sent_d(tag: str, d: str) -> str:
    """按哨兵后缀 d 直取名（``""``=level 2）——免 ``int()`` 的任意长后缀路径。"""
    return f"[[__TEXLATE_{tag}_LIT{d}__]]"


def _sentinel_ds(text: str, tag: str) -> list[str]:
    """文中规范哨兵后缀升序去重表（``""``=level 2 恒排首）。

    ``_SENT_RX`` 命中的非规范后缀（``"0"``/``"1"``/前导零形）不在升降链
    管辖内——编码双向均不产出也不吃，原样透传，此剔除。级序走
    ``(len, 字典序)`` 而非 ``int()``：稀疏在册级迭代不撑开区间
    （``LIT99999999`` 级字面曾致 ~1e8 次空转 replace），且任意长后缀
    不触 int 位限（``LIT{9×5000}`` 曾 ValueError 炸链）。
    """
    ds = {
        d for d in _SENT_RX[tag].findall(text) if d == "" or (d[0] != "0" and d != "1")
    }
    return sorted(ds, key=lambda d: (d != "", len(d), d))


def _dec_succ(d: str) -> str:
    """规范十进制后缀 +1（字符串进位——任意长不触 int 位限）。"""
    i = len(d) - 1
    while i >= 0 and d[i] == "9":
        i -= 1
    if i < 0:
        return "1" + "0" * len(d)
    return d[:i] + chr(ord(d[i]) + 1) + "0" * (len(d) - i - 1)


def _dec_pred(d: str) -> str:
    """规范十进制后缀 -1（仅 d≥``"2"`` 调用；``"2"→""`` 即 level 3→2 降档）。"""
    if d == "2":
        return ""
    i = len(d) - 1
    while d[i] == "0":
        i -= 1
    return (d[:i] + chr(ord(d[i]) - 1) + "9" * (len(d) - i - 1)).lstrip("0")


def _escape_family(text: str, tag: str, tok: str, raw: str) -> str:
    """单族字面转义闭链。

    在册哨兵自顶向下逐级 bump（sent(k)→sent(k+1)），再 RAW→sent(2)、
    token→RAW——任意深的字面 token 升一层即脱离当前级，先升高级故产物
    不会被本级及以下的后续替换二次吃掉。
    """
    for d in reversed(_sentinel_ds(text, tag)):
        succ = "2" if d == "" else _dec_succ(d)
        text = text.replace(_sent_d(tag, d), _sent_d(tag, succ))
    return text.replace(raw, _sentinel(tag, _SENT_BASE)).replace(tok, raw)


def _unescape_family(text: str, tag: str, tok: str, raw: str) -> str:
    """解码降链。

    RAW→token、sent(2)→RAW，再在册 sent(k)→sent(k-1) 自 3 升序——k 级降出的
    k-1 级是终态字面（其档位已过），不会被二次降。
    """
    text = text.replace(raw, tok).replace(_sentinel(tag, _SENT_BASE), raw)
    for d in _sentinel_ds(text, tag):
        text = text.replace(_sent_d(tag, d), _sent_d(tag, _dec_pred(d)))
    return text


_FUZZY_LEV_CAP = 2


# ---------------------------------------------------------------- 基础操作


def find_all(text: str) -> list[str]:
    """返回文本中出现的全部占位符（去重、按首次出现序）。"""
    return list(dict.fromkeys(ANY_PH_RX.findall(text)))


def ph_type(ph: str) -> str:
    """占位符 token → 类型名：``[[REF_5]]``→``REF``，无 ``_`` 前缀段时原样返回。

    刻意裸 ``rpartition``——``_`` 尾段不做数字守卫，``[[NBSP_RAW]]``→``NBSP``。
    ``_BENIGN_EXTRA_TYPES`` 豁免与 ``pipeline._seg_key`` 段键快照（=缓存键）
    均依赖此口径，勿加 ``isdigit`` 守卫；``sort_key`` 是另一解析，见下。
    """
    body = ph.strip("[]")
    return body.rpartition("_")[0] or body


def sort_key(ph: str) -> tuple[str, int]:
    """占位符稳定排序键：TYPE 字典序 + n 数值序（裸标记按 n=-1 排同型之前）。

    前缀缓存命中要求 term_dict 注入顺序逐字节稳定，此键是排序唯一事实源。
    ``tail.isdigit()`` 守卫刻意与 ``ph_type`` 不同径——``NBSP_RAW`` 在此归
    ``NBSP_RAW`` 型而非 ``NBSP``，两解析各自服务、不合并。
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


#: 响应侧行界归一：`\r\n`/`\r`/VT/FF/NEL/U+2028/U+2029 统一按 `\n`——
#: 行首锚定覆盖所有真实换行形态，模型裸发 Unicode 行界分隔序号时仍按
#: 锚定路径解析（`\x1c`–`\x1e` 属 splitlines 超集但非行界语义，不收）。
EOL_RX = re.compile("\r\n|[\r\x0b\x0c\x85\u2028\u2029]")


def decode_newlines(text: str) -> str:
    r"""`[[SL]]`→`\n`、`[[PL]]`→`\n\n`、空白族 token→字面，随后还原被转义的字面 token。

    先经 ``EOL_RX`` 归一裸行界符——单块阶梯臂（73ffa4c 前 1-member 组走
    批解析自带 ``_EOL_RX``）曾漏此步，``\x0b`` 直落 export 被 sanitize
    抹平而非归一成 ``\n``（export 控制符契约钉）。
    """
    decoded = EOL_RX.sub("\n", text)
    decoded = decoded.replace(PARA_NEWLINE, "\n\n").replace(SOFT_NEWLINE, "\n")
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
    def real_extra(self) -> list[str]:
        """``extra`` 剔除幂等无载荷类型（``_BENIGN_EXTRA_TYPES``）后的净多 token。"""
        return [e for e in self.extra if ph_type(e) not in _BENIGN_EXTRA_TYPES]

    @property
    def ok(self) -> bool:
        """无差异（多余仅含 benign 类型不算差异）。"""
        return not (self.missing or self.real_extra or self.misspelled)

    def describe(self) -> str:
        """一行错误描述，喂给 corrector 的 [Error] 段 / errors_report。"""
        parts = [f"missing placeholder: {ph}" for ph in self.missing]
        parts += [f"extra/unrecognized placeholder: {ph}" for ph in self.real_extra]
        parts += [
            f"misspelled placeholder: '{bad}' should be '{good}'"
            for bad, good in self.misspelled
        ]
        return "; ".join(parts)


#: extra 判定豁免的占位符类型——载荷无内容的幂等标记（``[[NBSP]]`` 解码即
#: ``~``）。模型把源文字面 ``~``（``Fig.~[[REF_5]]``/``H.~Tan``）规范成
#: ``[[NBSP]]`` 是更正确的掩码恢复而非缺陷；计入 extra 判负只会白触发
#: 成员级单发重翻（batchmodel-2026-09-18 §6 实测批内 NBSP 喷发）。
#: splice 侧仍有 ``_leftover_ph_tokens`` 兜底：src 集外 token 不可解析时
#: 照样拦，豁免只放松多重集计数。
_BENIGN_EXTRA_TYPES = frozenset({"NBSP"})


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


def _copied_boundary_rx(fragment: str) -> re.Pattern[str]:
    r"""逐片段类型选边界守卫——裸 ``replace`` 会把 token 嵌进更长文本。

    ``\alpha`` 命中 ``\alphax`` 内、``$x$`` 命中 ``$$x$$`` 内、``42`` 命中
    ``42.5`` 内。上游 texglot llm.py:148-156 三守卫同款。
    """
    pat = re.escape(fragment)
    if fragment.startswith("$") and fragment.endswith("$"):
        return re.compile(rf"(?<!\$){pat}(?!\$)")
    if fragment.startswith("\\"):
        return re.compile(rf"{pat}(?![A-Za-z@])")
    if fragment[-1].isalnum() or fragment[-1] == "_":
        return re.compile(rf"{pat}(?![A-Za-z0-9_.])")
    return re.compile(pat)


def recover_copied_tokens(zh: str, ph_map: Mapping[str, str]) -> tuple[str, list[str]]:
    """模型把受保护原文抄回译文时，**exact+unique** 才换回 token（docs/spec/translate.md）。

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
        rx = _copied_boundary_rx(fragment)
        if len(rx.findall(zh)) == 1:
            zh = rx.sub(ph, zh, count=1)
            recovered.append(ph)
    return zh, recovered


def collect_doc_placeholders(contents: Iterable[str]) -> list[str]:
    """收集文档全部 chunk 的占位符集合，按 `sort_key` 稳定排序（manifest 点名用）。

    ``sort_key`` 非全序（``[[A_1]]``/``[[A_01]]`` 同键）——同键按 token 字面
    消歧，否则 tie 落 set 迭代序 = 哈希序，注入序随 PYTHONHASHSEED 漂移。
    """
    seen: set[str] = set()
    for text in contents:
        seen.update(ANY_PH_RX.findall(text))
    return sorted(seen, key=lambda p: (sort_key(p), p))


# ---------------------------------------------------------------- 点名册 manifest

#: manifest 行头——压 ``<Glossary>`` 块末行的文档级占位符点名册（v5 恒等表
#: 替代件；实测字节形见 docs/spec/translate.md §1.9）。``- `` 前缀使其合法
#: 混入 ``- en: zh`` 行表。
PH_MANIFEST_HEADER = "- placeholders used in this document (preserve each verbatim): "

#: manifest 行字符上限——超出退化为无括号计数形 ``TYPE×n``（恒等表 98% 体积
#: 事故的重发闸）。稀疏编号文档最差实测 ~3.2kc，4000 留头部使常见规模
#: 仍走已验证的连续段枚举形。
_PH_MANIFEST_MAX_CHARS = 4000


def render_placeholder_manifest(phs: Iterable[str]) -> str:
    """文档占位符集 → 单行点名册（``<Glossary>`` 块末行；⑤层恒等注入的替代件）。

    入参任意 iterable——``ANY_PH_RX.fullmatch`` 过滤后按 ``(sort_key, 字面)``
    排序；同 head 连续编号段压 ``[[H_a]]..[[H_b]]``（≥2 连号即压，稀疏区不
    伪造在册 id——虚增 id 正对 invented-placeholder 校验判据），裸标记原样
    直出。渲染超 ``_PH_MANIFEST_MAX_CHARS`` 退化为无括号计数形 ``TYPE×n``：
    ``[[CITE]]`` 命中 ``BARE_PH_RX``、``[[CITE_n]]`` 命中 ``PH_FUZZY_RX``，
    括号形若被回抄均判 extra 触发成员级重翻，故退化形不含任何 ``[[…]]``。
    空集返回 ``""``。
    """
    toks = sorted(
        {p for p in phs if ANY_PH_RX.fullmatch(p)},
        key=lambda p: (sort_key(p), p),
    )
    if not toks:
        return ""
    parts: list[str] = []
    i = 0
    while i < len(toks):
        head, n = sort_key(toks[i])
        if n < 0:
            parts.append(toks[i])
            i += 1
            continue
        j = i + 1
        while j < len(toks) and sort_key(toks[j]) == (head, n + j - i):
            j += 1
        parts.append(f"{toks[i]}..{toks[j - 1]}" if j - i > 1 else toks[i])
        i = j
    line = PH_MANIFEST_HEADER + ", ".join(parts)
    if len(line) <= _PH_MANIFEST_MAX_CHARS:
        return line
    counts = Counter(sort_key(t)[0] for t in toks)
    tally = ", ".join(f"{h}×{c}" for h, c in counts.items())
    return PH_MANIFEST_HEADER + tally
