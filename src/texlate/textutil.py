r"""文本小件单源 —— 注释/逐字遮盖 + 封顶 Levenshtein + 逐字环境注册表。

``mask_comments``：``\`` 后随字符整体跳过（``\%``/``\\%`` 语义正确），
未转义 ``%`` 到行尾替换为等长空格——offset/长度与原文逐字节对齐，
供正则/下标直接使用。**不处理 verbatim 环境**。

``mask_tex``：等长遮盖视图 = 逐字族环境体 + comment 失活环境 + 行内
``\verb``/``\lstinline`` + 行内 ``%`` 注释。定位视图 ≠ 改写目标——masked
view 绝不能拷回原文（``compile.mask`` 的手术都在原文回放）。

``VERBATIM_ENVS``/``DEAD_ENVS``：逐字/失活环境清单的单一事实源——并集自
原 compile.mask、arxiv._texutil、latex.tables 三处漂移清单。

``lev_capped``：带 early-exit 上限的 Levenshtein——L0 占位符拼写配对与
xlat 轻量对账共用一个实现，防两份 DP 各自漂移。

``decode_tex``：arXiv 源码字节 → str 的按文件分档解码。语料实测 ~3.6% 的
.tex 不是 UTF-8——裸 ``errors="replace"`` 会把正文炸成 U+FFFD 喂给翻译层。
旧兜底链 ``utf-8 → gb18030 → cp1252 → latin-1`` 有系统性误吃：gb18030 把
latin 对字节（``é``+ASCII 字母是合法 gb 二字节）解成 CJK——字节探测必须先
判定编码族再解码，判定依据逐文件落 ``EncodingVerdict`` 供 normalize 归因。
"""

from __future__ import annotations

import codecs
import re
from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

__all__ = [
    "CJK_RANGES",
    "CJK_RX",
    "DEAD_ENVS",
    "VERBATIM_ENVS",
    "EncodingVerdict",
    "decode_tex",
    "decode_tex_with",
    "is_cjk_cp",
    "lev_capped",
    "mask_comments",
    "mask_tex",
    "ph_in_cs_net",
    "sniff_tex_encoding",
]


def mask_comments(text: str) -> str:
    r"""``%`` 到行尾等长空格遮盖；``\`` 后随字符整体跳过。保位不保内容。"""
    out = list(text)
    i, n = 0, len(text)
    while i < n:
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == "%":
            j = i
            while j < n and text[j] not in "\r\n":
                out[j] = " "
                j += 1
            i = j
            continue
        i += 1
    return "".join(out)


_PH_IN_CS_RX: Final = re.compile(r"\\[a-zA-Z@]+\[\[[^\[\]\n]{1,48}?\]\][a-zA-Z@]")


def ph_in_cs_net(src: str, zh: str) -> Counter[str]:
    r"""``\cs名[[..]]字母`` 双侧夹持签名净差（zh 侧多出，Counter 多重集）。

    splice 逐字节替换 ``[[PH]]`` 后 ``\fo[[PH]]o`` → ``\fo<payload>o`` 断
    cs 成未定义命令——挪位缺陷签名（scout-spliceguard 实证）。双侧字母夹持
    必需：``\cs[[PH]]`` 尾邻是合法高频形（corpus 271 处 ``\protect[[REF_n]]``
    系）；``+`` 排除 ``\[[PH]]`` display-math 与 ``\\[[PH]]`` 控制符号。
    注释区 ``mask_comments`` 屏蔽；src 自带同形按多重集差豁免。L0
    ``_check_ph_in_cs`` 与 pipeline ``_intercept_ph_in_cs`` 共用本口径。
    """
    return Counter(_PH_IN_CS_RX.findall(mask_comments(zh))) - Counter(
        _PH_IN_CS_RX.findall(mask_comments(src))
    )


# ---------------------------------------------------------------- 逐字/失活环境注册表

#: 逐字族环境基名（三处旧清单的并集）：内容按字面处理，不解析不手术不翻译。
_VERBATIM_BASE: Final = (
    "verbatim",
    "Verbatim",
    "BVerbatim",
    "LVerbatim",
    "lstlisting",
    "lstpython",
    "minted",
    "filecontents",
    "filecontents+",
    "filecontentsheader",
)
#: 逐字族环境全枚举（含 ``*`` 变体）。
VERBATIM_ENVS: Final = frozenset(
    e for base in _VERBATIM_BASE for e in (base, base + "*")
)
#: 失活环境（comment.sty）——内容对 TeX 不可见，遮盖口径同逐字。
DEAD_ENVS: Final = frozenset({"comment", "comment*"})

#: ``\begin{env}`` 识别：环境名需 ``re.escape``——名单含 ``*`` 字面，
#: 直接进 alternation 会把 ``verbatim*`` 解析成 ``verbat``+``im*``（旧实现即此 bug）。
_VERBATIM_BEGIN_RX: Final = re.compile(
    r"\\begin\s*\{(" + "|".join(re.escape(e) for e in sorted(VERBATIM_ENVS)) + r")\}"
)
_DEAD_BEGIN_RX: Final = re.compile(
    r"\\begin\s*\{(" + "|".join(re.escape(e) for e in sorted(DEAD_ENVS)) + r")\}"
)
#: TeX 控制序列：`\word*` 或单个非字母字符（DOTALL 让 `\.` 能吃 `\`+换行）。
_COMMAND_RX: Final = re.compile(r"\\(?:[a-zA-Z@]+\*?|.)", re.DOTALL)


def _env_stop(text: str, env: str, pos: int) -> int:
    r"""从 pos 找 ``\end{env}``，返回其结束后 offset；找不到返回 len(text)。"""
    ending = re.search(r"\\end\s*\{" + re.escape(env) + r"\}", text[pos:])
    return pos + ending.end() if ending else len(text)


def _inline_verb_end(text: str, i: int, n: int) -> int | None:
    r"""``\verb``/``\lstinline`` 行内区段的结束 offset；不合法形态返回 None。

    ``\lstinline`` 允许 ``[opt]`` 前缀；定界符取首个非空白字符，
    ``{`` 定界时配 ``}``；未闭合或跨行不算（交回主循环逐字符扫）。
    """
    inline = re.match(r"\\(verb\*?|lstinline\*?)(?![A-Za-z@])", text[i:])
    if not inline:
        return None
    start = i + inline.end()
    if inline[1].startswith("lstinline"):
        options = re.match(r"\s*(?:\[[^\]\n]*\]\s*)?", text[start:])
        start += options.end()
    if start >= n or text[start].isspace():
        return None
    delimiter = text[start]
    end = text.find("}" if delimiter == "{" else delimiter, start + 1)
    nl = re.search(r"[\r\n]", text[start:])
    newline = -1 if nl is None else start + nl.start()
    if end < 0 or (newline >= 0 and newline < end):
        return None
    return end + 1


def mask_tex(text: str, *, mask_dead: bool = True, keep_verbatim: bool = False) -> str:
    r"""逐字环境 + 失活环境 + ``\verb``/``\lstinline`` + 行内 ``%`` 的等长遮盖视图。

    offset/行号与原文字节级对齐（``\n`` 保留）。顺序敏感：先吃逐字环境
    （``\verb|%|`` 里的 ``%`` 不是注释），再遮行内 ``%``。

    ``mask_dead=False`` 供 comment.sty 手术自身——``\end{comment}`` 行尾
    空白修复需要看见 comment 环境内部。
    ``keep_verbatim=True`` 供检测类消费（arxiv 定位/嗅探）——逐字环境体
    原样保留（其中 ``%`` 仍不算注释），不遮盖；计数场景需要这些字面量。
    """
    chars = list(text)

    def mask(start: int, stop: int) -> None:
        chars[start:stop] = [
            c if c in "\r\n" else " " for c in text[start:stop]
        ]

    i = 0
    n = len(text)
    while i < n:
        if text[i] == "%":
            nl = re.search(r"[\r\n]", text[i:])
            stop = n if nl is None else i + nl.start()
            mask(i, stop)
            i = stop
            continue
        if text[i] != "\\":
            i += 1
            continue
        env = _VERBATIM_BEGIN_RX.match(text, i)
        is_verbatim = env is not None
        if env is None and mask_dead:
            env = _DEAD_BEGIN_RX.match(text, i)
        if env:
            stop = _env_stop(text, env[1], env.end())
            if not (keep_verbatim and is_verbatim):
                mask(i, stop)
            i = stop
            continue
        verb_end = _inline_verb_end(text, i, n)
        if verb_end is not None:
            mask(i, verb_end)
            i = verb_end
            continue
        command = _COMMAND_RX.match(text, i)
        # match.end() 是绝对 offset——必须赋值不是累加（旧实现 i+=end 会把
        # i 推到 ~2i，大段注释逃逸遮盖）。
        i = command.end() if command else i + 1
    return "".join(chars)


# ---------------------------------------------------------------- 编码判定
#: ``\usepackage[<opt>]{inputenc}`` / ``\inputencoding{<opt>}`` / 魔数注释
#: / SWP ``CodePage:`` 的声明名 → python codec。声明只作参考（corpus 实证：
#: decl=utf8 实 cp1252、decl=cp866 实 cp1252、decl=latin1 实 utf8），最终
#: 以字节判定为准。
_DECLARED_CODECS: Final = {
    "utf8": "utf-8",
    "utf8x": "utf-8",
    "utf-8": "utf-8",
    "ascii": "ascii",
    "latin1": "latin-1",
    "latin2": "iso8859-2",
    "latin3": "iso8859-3",
    "latin4": "iso8859-4",
    "latin5": "iso8859-9",
    "latin6": "iso8859-10",
    "latin9": "iso8859-15",
    "latin10": "iso8859-16",
    "ansinew": "cp1252",
    "cp1252": "cp1252",
    "applemac": "mac_roman",
    "mac": "mac_roman",
    "maccyrillic": "mac_cyrillic",
    "koi8-r": "koi8-r",
    "koi8-u": "koi8-u",
    "gbk": "gbk",
    "gb18030": "gb18030",
    "big5": "big5",
    "euc-jp": "euc_jp",
    "sjis": "shift_jis",
}
_INPUTENC_RX: Final = re.compile(
    r"\\(?:usepackage|RequirePackage)\s*\[([^]]*)\]\s*\{inputenc\}"
    r"|\\inputencoding\s*\{([^}]+)\}",
    re.IGNORECASE,
)
_MAGIC_RX: Final = re.compile(
    r"%\s*!TEX\s+encoding\s*=\s*(\S+)|-\*-\s*coding:\s*([^\s;]+)",
    re.IGNORECASE,
)
_CODEPAGE_RX: Final = re.compile(r"CodePage:\s*(\d{3,4})")
#: ``utf8`` 混入 usepackage 选项串的正则子项。
_DECL_OPTION_RX: Final = re.compile(r"[a-zA-Z0-9_-]+")


@dataclass(frozen=True)
class EncodingVerdict:
    """单文件编码判定结果——``basis`` 记判定层级，``declared`` 记文件自述。"""

    encoding: str  # 实际采用的 python codec（"utf-8-mixed" 表示分段混合解码）
    basis: str  # bom / strict-utf8 / declared / mixed / detector / fallback
    declared: str | None = None  # 文件自述的编码名（inputenc 选项/魔数/CodePage）
    note: str = ""  # 人读注记（声明不符、混合区段等）


def _declared_name(blob: bytes) -> str | None:
    r"""文件自述编码：inputenc 选项 → ``\inputencoding`` → 魔数注释 → CodePage。

    全文件按 latin-1 视读扫（声明必为 ASCII）；inputenc 多选项取最后一个
    可识别名（TeX 语义同）。
    """
    view = blob.decode("latin-1")
    names: list[str] = []
    for match in _INPUTENC_RX.finditer(view):
        raw = match[1] if match[1] is not None else match[2]
        found = [o.lower() for o in _DECL_OPTION_RX.findall(raw)]
        names.extend(
            o for o in found if o in _DECLARED_CODECS or re.fullmatch(r"cp\d{3,4}", o)
        )
    for regex in (_MAGIC_RX, _CODEPAGE_RX):
        match = regex.search(view)
        if match:
            value = next(g for g in match.groups() if g)
            names.append(f"cp{value}" if regex is _CODEPAGE_RX else value.lower())
    return names[-1] if names else None


def _declared_codec(name: str) -> str | None:
    """声明名 → python codec；不识别的名（如 ``utf8x`` 之外怪名）返回 None。"""
    if name in _DECLARED_CODECS:
        return _DECLARED_CODECS[name]
    if re.fullmatch(r"cp\d{3,4}", name):
        try:
            codecs.lookup(name)
        except LookupError:
            return {"cp936": "gbk", "cp950": "cp950"}.get(name)
        return name
    return None


#: 评分用字符面区间（按表序先中先得）。latin_ext 自 0xA0 起算——拉丁
#: 补充区含 ``©±µ½£`` 等合法单字节证据；typographic 引号/破折号家族
#: 是 Word/Classic-Mac 导出签名（0xD2/0xD3 applemac = ``“”``、
#: cp1252 0x93/0x94 = ``“”``），真实文本得分、乱码解码拿不到。
_CLASS_RANGES: Final = (
    ("latin_ext", ((0xA0, 0x24F), (0x1E00, 0x1EFF))),
    ("cyrillic", ((0x400, 0x52F), (0x2DE0, 0x2DFF))),
    ("greek", ((0x370, 0x3FF), (0x1F00, 0x1FFF))),
    ("boxdraw", ((0x2500, 0x259F),)),
    ("cjk", ((0x3000, 0x33FF),)),
)


def _merge_ranges(
    ranges: Iterable[tuple[int, int]],
) -> tuple[tuple[int, int], ...]:
    """区间列 → 排序不相交面（相邻并入）——bisect 单候选判定前提。"""
    out: list[list[int]] = []
    for lo, hi in sorted(ranges):
        if out and lo <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return tuple(tuple(p) for p in out)


def _in_ranges(
    cp: int, los: tuple[int, ...], merged: tuple[tuple[int, int], ...]
) -> bool:
    """``any(lo <= cp <= hi)`` 的 bisect 版——``merged`` 须排序不相交。"""
    i = bisect_right(los, cp) - 1
    return i >= 0 and cp <= merged[i][1]


def _class_lookup_table() -> tuple[tuple[int, int, str], ...]:
    """``_CLASS_RANGES`` → 排序不相交 (lo,hi,name) 查找面。

    重叠子段归 ``_CLASS_RANGES`` 先名（首中语义）——对任意区间内容
    逐点等价，bisect 取 ``lo<=cp`` 的末区间即答案。
    """
    out: list[tuple[int, int, str]] = []
    for name, ranges in _CLASS_RANGES:
        for lo, hi in ranges:
            parts = [(lo, hi)]
            for plo, phi, _prev in out:
                nxt: list[tuple[int, int]] = []
                for a, b in parts:
                    if a < plo:
                        nxt.append((a, min(b, plo - 1)))
                    if b > phi:
                        nxt.append((max(a, phi + 1), b))
                parts = nxt
                if not parts:
                    break
            out.extend((a, b, name) for a, b in parts)
    return tuple(sorted(out))


#: ``_CLASS_RANGES`` 的查找面 + lo 列——``_score_text`` 逐字调用
#: （breview 全文 ~976K 次），线性 any() 改 bisect。
_CLASS_MERGED: Final = _class_lookup_table()
_CLASS_LOS: Final = tuple(lo for lo, _, _ in _CLASS_MERGED)


def _char_class(ch: str) -> str:
    """字符粗分类：latin_ext / cyrillic / greek / cjk / boxdraw / other。"""
    cp = ord(ch)
    i = bisect_right(_CLASS_LOS, cp) - 1
    if i >= 0 and cp <= _CLASS_MERGED[i][1]:
        return _CLASS_MERGED[i][2]
    return "cjk" if is_cjk_cp(cp) else "other"


_TYPO_PUNCT: Final = frozenset("“”‘’‚„‹›«»–—…†‡•′″")
#: 评分权重（corpus 校准值，勿拍脑袋调——改动须过 encoding_probe 全量）。
_RUN_CHAR_SCORE: Final = 4.0  # 同脚本连排每字
_RUN_CHAR_CAP: Final = 20  # 连排计分上限（防一次长 run 锁死）
_SINGLE_LATIN_SCORE: Final = 1.0
_SINGLE_NONLATIN_SCORE: Final = 0.5
_TYPO_SCORE: Final = 2.0
_MATH_SCORE: Final = 1.5
_C1_PENALTY: Final = -15.0
_REPLACEMENT_PENALTY: Final = -25.0
_BOXDRAW_PENALTY: Final = -4.0
_RARE_CYRILLIC_PENALTY: Final = -3.0
_ADJACENT_ASCII_PENALTY: Final = -6.0
_MOJIBAKE_PENALTY: Final = -8.0
_NONLATIN_MASS_MIN: Final = 12  # 非拉丁脚本成规模阈值
_NONLATIN_MASS_SCORE: Final = 3.0
#: C1 控制区（cp1252 把 0x80-0x9F 解成印刷符号、latin-1 解成控制符）。
_C1_LO: Final = 0x80
_C1_HI: Final = 0x9F
#: 数学/科学符号面——applemac 0xA3=``≤``、0xD0=``–`` 这类单字节证据
#: 只有符号分能压过 cp1252 的 ``£``/``Ð`` 字面解（hep-ph/9910443 实证）。
_MATH_PUNCT: Final = frozenset("≤≥≠±×÷·∂∇∫∮∑∏√∞∈∉⊂⊃∪∩∧∨¬≈≡∝←→↑↓↔")
_MOJIBAKE_RX: Final = re.compile(r"[ÃÂ][\u0080-\u00bf]|â€.")
#: blob 内存在真 UTF-8 多字节序列（2+ 字节 lead+continuation）才算混合文件。
_UTF8_SEQ_RX: Final = re.compile(rb"[\xc2-\xf4][\x80-\xbf]")


#: 常用西里尔字母（俄语+乌克兰语扩展）。cp866/gb 字节被 cp1251 误吃时会
#: 混出 Serbian ``j``/罕见 ``Ъ`` 等语言不可能共现的字母——罕见字扣分。
_COMMON_CYRILLIC: Final = frozenset(
    "абвгдежзийклмнопрстуфхцчшщъыьэюяАБВГДЕЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯёЁіІїЇєЄґҐ"
)


def _score_text(text: str) -> float:  # noqa: C901 — 逐字计分，分支即签名清单
    r"""解码结果的自然文本评分：脚本连排加分、控制符/乱码签名扣分。

    签名：``Ã``/``Â``+高字节 = UTF-8 被单字节解码（mojibake）；U+2500 块
    画符 = cp866 误吃拉丁；CJK/西里尔紧邻 ASCII 字母 = 多字节误吃 latin
    对；非拉丁脚本成规模（≥12 字）才是真实使用——稀疏重音是 latin 常态。
    """
    score = 0.0
    run_class = ""
    run_len = 0
    prev = ""
    mass = {"latin_ext": 0, "cyrillic": 0, "greek": 0, "cjk": 0, "boxdraw": 0}

    def flush() -> None:
        nonlocal score
        if run_len > 1:
            score += _RUN_CHAR_SCORE * min(run_len, _RUN_CHAR_CAP)
        elif run_len:
            # 孤立字符只有 latin 重音是强证据；非拉丁单字（cp866 把
            # 0xA3 吃成 ``г``、抢赢 cp1252 的 ``£``——hep-ph/9910443
            # 实证）只给半分——非拉丁真身靠连排长度取胜。
            score += (
                _SINGLE_LATIN_SCORE
                if run_class == "latin_ext"
                else _SINGLE_NONLATIN_SCORE
            )

    for ch in text:
        cls = _char_class(ch)
        if cls == "other":
            flush()
            run_len = 0
            if ch in _TYPO_PUNCT:
                score += _TYPO_SCORE
            elif ch in _MATH_PUNCT:
                score += _MATH_SCORE
            if _C1_LO <= ord(ch) <= _C1_HI:
                score += _C1_PENALTY
            elif ch == "\ufffd":
                score += _REPLACEMENT_PENALTY
            prev = ch
            continue
        mass[cls] += 1
        if cls == run_class:
            run_len += 1
        else:
            flush()
            run_class = cls
            run_len = 1
        if cls == "boxdraw":
            score += _BOXDRAW_PENALTY
        if cls == "cyrillic" and ch not in _COMMON_CYRILLIC:
            score += _RARE_CYRILLIC_PENALTY
        if cls in ("cjk", "cyrillic", "greek") and prev.isascii() and prev.isalnum():
            score += _ADJACENT_ASCII_PENALTY
        prev = ch
    flush()
    score += _MOJIBAKE_PENALTY * len(_MOJIBAKE_RX.findall(text))
    dominant = max(mass["cyrillic"], mass["cjk"], mass["greek"])
    if dominant >= _NONLATIN_MASS_MIN:
        score += _NONLATIN_MASS_SCORE * dominant
    return score


#: 高字节界（≥0x80 即非 ASCII）。
_HIGH_BYTE: Final = 0x80
#: utf-16 无 BOM 判定：头采样窗 / 最小样本 / NUL 占比 ≥1/4。
_UTF16_HEAD: Final = 4096
_UTF16_MIN_LEN: Final = 16
_UTF16_NUL_DIV: Final = 4
#: 双字节族快判阈值：最小高字节证据量 / 相邻占比 / 「大体合法 UTF-8」
#: 守卫（坏点须 > 高字节 1/8 才交双字节族）。
_GATE_MIN_HIGH: Final = 8
_GATE_MIN_ADJACENT: Final = 0.6
_UTF8_BAD_DIV: Final = 8
#: CJK 判定成案分 / run 级最小长度 / utf-8 序列最大宽。
_CJK_MIN_SCORE: Final = 3.0
_CJK_RUN_MIN: Final = 4
_UTF8_SEQ_MAX: Final = 4
#: 西里尔否决：常见字母连排的最小规模 / 罕见字占比分母（≤1/20）。
_CYR_MASS_MIN: Final = 8
_CYR_RARE_DIV: Final = 20
#: 声明采纳的落后容差（一个标点级分差）与混合结构加分。
_DECLARED_SLACK: Final = 4.0
_MIXED_STRUCT_BONUS: Final = 20.0

_SINGLE_BYTE_CODECS: Final = (
    "cp1252",
    "mac_roman",
    "cp1251",
    "latin-1",
    "cp866",
    "koi8-r",
)
#: 双字节候选族。gb18030 对几乎任意字节可解（4 字节扩展段吞一切）——
#: 族间仲裁只能看产出质量，不能看 decode 成败。euc_kr 被移出：GBK
#: 字节对落在 euc_kr A1-FE 区时 strict 解出假谚文，+4 专属面加分反杀
#: 真 gb18030（2105.03820 decl=cp936 实测 29:14）——arXiv 韩文语料
#: 实测为零，误路由代价大于假想覆盖。
_CJK_CODECS: Final = ("gb18030", "big5", "shift_jis", "euc_jp")
#: 声明名里的 CJK 族（含 cp 别名——``codecs.lookup("cp936")`` 能解，
#: ``_declared_codec`` 会原样返回而非归一到 ``gbk``）。
_CJK_DECLARED: Final = frozenset(
    (*_CJK_CODECS, "gbk", "cp936", "cp950", "cp932", "cp949", "cp54936")
)
#: 专属面区间：假名（0x3040-0x30FF）/谚文音节+字母。gb18030 误吃 SJIS
#: 只产表意字——命中这些面即族铁证。
_KANA_HANGUL_RANGES: Final = ((0x3040, 0x30FF), (0x1100, 0x11FF), (0xAC00, 0xD7AF))
_KANA_MERGED: Final = _merge_ranges(_KANA_HANGUL_RANGES)
_KANA_LOS: Final = tuple(lo for lo, _ in _KANA_MERGED)
_CJK_CHAR_SCORE: Final = 1.0
_KANA_HANGUL_BONUS: Final = 4.0
_CJK_FFFD_PENALTY: Final = -20.0


def _cjk_decode_score(text: str) -> float:
    """双字节解码质量分：表意字 +1，假名/谚文再 +4（族铁证），FFFD -20。

    假名/谚文是专属面——SJIS 字节被 gb18030 误吃只产表意字垃圾
    （cond-mat/0111097 实测 ``82f0…``→"擖偟偰…" vs sjis→"入してください"）。
    """
    score = 0.0
    for ch in text:
        cp = ord(ch)
        if _char_class(ch) == "cjk":
            score += _CJK_CHAR_SCORE
        if _in_ranges(cp, _KANA_LOS, _KANA_MERGED):
            score += _KANA_HANGUL_BONUS
        elif ch == "\ufffd":
            score += _CJK_FFFD_PENALTY
    return score


def _decode_high_run(run: bytes) -> tuple[str, str]:  # noqa: C901 — 局部仲裁平铺
    """高字节连续段的局部解码：成段 CJK 先试，否则 UTF-8 前缀步进+单字节评分。"""
    if len(run) >= _CJK_RUN_MIN:
        best_enc, best_text, best_score = "", "", 0.0
        for enc in _CJK_CODECS:
            try:
                text = run.decode(enc)
            except UnicodeDecodeError:
                # run 在 UTF-8 分段边界被裁断——尾字节可能恰是半对，
                # replace 容许半截配 FFFD 罚分进仲裁。
                text = run.decode(enc, errors="replace")
            score = _cjk_decode_score(text)
            if score > best_score:
                best_enc, best_text, best_score = enc, text, score
        if best_score >= _CJK_MIN_SCORE:
            return best_text, best_enc
    out: list[str] = []
    i = 0
    while i < len(run):
        for width in range(min(_UTF8_SEQ_MAX, len(run) - i), 1, -1):
            try:
                piece = run[i : i + width].decode("utf-8")
            except UnicodeDecodeError:
                continue
            out.append(piece)
            i += width
            break
        else:
            byte = run[i : i + 1]
            best = ""
            best_score = float("-inf")
            for enc in _SINGLE_BYTE_CODECS:
                try:
                    piece = byte.decode(enc)
                except UnicodeDecodeError:
                    continue
                score = _score_text(piece)
                if score > best_score:
                    best, best_score = piece, score
            out.append(best or byte.decode("latin-1"))
            i += 1
    return "".join(out), "mixed"


def _decode_mixed(blob: bytes) -> tuple[str, dict[int, str]]:
    """UTF-8 分段 + 高字节 run 局部解码。返回 (文本, {offset: 区段 codec})。"""
    parts: list[str] = []
    regions: dict[int, str] = {}
    pos = 0
    n = len(blob)
    while pos < n:
        try:
            parts.append(blob[pos:].decode("utf-8"))
            break
        except UnicodeDecodeError as err:
            start = pos + err.start
            parts.append(blob[pos:start].decode("utf-8"))
            end = start
            while end < n and blob[end] >= _HIGH_BYTE:
                end += 1
            text, how = _decode_high_run(blob[start:end])
            parts.append(text)
            regions[start] = how
            pos = end
    return "".join(parts), regions


def sniff_tex_encoding(blob: bytes) -> EncodingVerdict:  # noqa: C901, PLR0911, PLR0912, PLR0915 — 分档链即规格序
    """按文件归属分档判定编码（不解码大文本时只判不定）。

    层级：BOM → strict UTF-8 → 自述声明（strict 可解码且评分不劣于检测器）
    → 检测器（单字节族 + gb18030/big5 全体 argmax 评分）+ UTF-8 混合分段。
    """
    if blob.startswith(b"\xef\xbb\xbf"):
        return EncodingVerdict("utf-8-sig", "bom")
    if blob.startswith((b"\xff\xfe", b"\xfe\xff")):
        return EncodingVerdict("utf-16", "bom")
    declared_raw = _declared_name(blob)
    declared = _declared_codec(declared_raw) if declared_raw else None
    # utf-16le/be 无 BOM 时是合法 UTF-8（NUL+ASCII）——必须先于 strict 判定。
    # 比例口径：头 4K 里 NUL 占 ≥1/4 即成案（utf-16 ASCII 区恒 ~50%）。
    head = blob[:_UTF16_HEAD]
    if (
        head.count(b"\x00") > len(head) // _UTF16_NUL_DIV
        and len(head) >= _UTF16_MIN_LEN
    ):
        for enc in ("utf-16-le", "utf-16-be"):
            try:
                blob.decode(enc)
            except UnicodeDecodeError:
                continue
            return EncodingVerdict(enc, "detector", declared_raw, "nul-dense")
    try:
        blob.decode("utf-8")
    except UnicodeDecodeError as err:
        # 尾部半截 UTF-8 序列 = 截断文件（aux/bib 8192B 边界劈断同型，
        # 2211.13013）——仍属 UTF-8 家族；decode_tex_with 用 replace
        # 兜一个 FFFD 收尾，远好过误入 gb18030/cp1252 检测器把全文
        # 炸成乱码后转码写回。判别：已解码前缀须自带多字节序列——
        # 纯 ASCII 前缀 + 尾部孤立高字节（latin-1 "café" 的 0xE9 同报
        # "unexpected end of data"）与截断不可区分，交回检测器仲裁。
        if err.reason == "unexpected end of data" and any(
            b >= _HIGH_BYTE for b in blob[: err.start]
        ):
            return EncodingVerdict(
                "utf-8", "strict-utf8", declared_raw, "truncated utf-8 tail"
            )
    else:
        note = (
            ""
            if declared in (None, "utf-8")
            else f"declared {declared_raw} ignored: bytes are strict utf-8"
        )
        return EncodingVerdict("utf-8", "strict-utf8", declared_raw, note)
    # 双字节族快判：高字节「前位亦高」相邻占比 ≥60% 且总量 ≥8——真
    # GBK/SJIS/Big5/EUC 文的高字节两两相连；latin/cyrillic 的高字节被
    # ASCII 断开（latin 重音后随字母落在 gb trail 区间会把「下位字节」
    # 判据喂满——1206.5832 的 7 个稀疏重音曾误判 gb18030，故改相邻口径）。
    # 守卫：坏点稀疏的「大体合法 UTF-8」文件不交双字节族——gb18030 会把
    # UTF-8 三字节当合法对整段吞成 CJK 乱码，该走 mixed 分段。
    high = [i for i, b in enumerate(blob) if b >= _HIGH_BYTE]
    if len(high) >= _GATE_MIN_HIGH:
        adjacent = sum(1 for i in high if i > 0 and blob[i - 1] >= _HIGH_BYTE)
        utf8_bad = blob.decode("utf-8", errors="replace").count("\ufffd")
        if adjacent / len(
            high
        ) >= _GATE_MIN_ADJACENT and utf8_bad * _UTF8_BAD_DIV > len(high):
            best_enc, best_score = "", 0.0
            for enc in _CJK_CODECS:
                try:
                    text = blob.decode(enc)
                except UnicodeDecodeError:
                    text = blob.decode(enc, errors="replace")
                score = _cjk_decode_score(text)
                if score > best_score:
                    best_enc, best_score = enc, score
            if best_score >= _CJK_MIN_SCORE:
                # 西里尔否决：真 cp1251 文的高字节同样全相邻（相邻占比
                # 分不出「成对编码」与「纯西里尔连排」）——cp1251 解码出
                # 常见字母成规模连排即真俄文；GBK 被 cp1251 误吃必混入
                # ЅЎў 等罕见字母（2105.03820 实测 25%）。declared 为 CJK
                # 族时声明先验直通——短 GBK 串在 cp1251 下罕见字占比
                # 低是固有歧义，作者声明说了算。
                veto = False
                if declared not in _CJK_DECLARED:
                    cyr = blob.decode("cp1251", errors="replace")
                    cyr_chars = [c for c in cyr if _char_class(c) == "cyrillic"]
                    rare = sum(1 for c in cyr_chars if c not in _COMMON_CYRILLIC)
                    veto = len(cyr_chars) >= _CYR_MASS_MIN and rare <= max(
                        1, len(cyr_chars) // _CYR_RARE_DIV
                    )
                if not veto:
                    return EncodingVerdict(
                        best_enc,
                        "detector",
                        declared_raw,
                        f"paired-bytes={adjacent / len(high):.2f}",
                    )
    candidates: list[tuple[str, str, float]] = []  # (encoding, basis, score)
    mixed_text, regions = _decode_mixed(blob)
    if _UTF8_SEQ_RX.search(blob):
        # 含真 UTF-8 多字节序列才是混合文件，否则与单字节全量解码同文；
        # +20 结构分——合法 UTF-8 序列的存在本身就是该走分段解码的证据
        candidates.append(
            ("utf-8-mixed", "mixed", _score_text(mixed_text) + _MIXED_STRUCT_BONUS)
        )
    for enc in (*_SINGLE_BYTE_CODECS, *_CJK_CODECS):
        try:
            text = blob.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
        candidates.append((enc, "detector", _score_text(text)))
    declared_text_score: float | None = None
    if declared:
        try:
            declared_text = blob.decode(declared)
            declared_text_score = _score_text(declared_text)
        except (UnicodeDecodeError, LookupError):
            declared_text_score = None
    if declared_text_score is not None:
        best = max(candidates, key=lambda c: c[2], default=None)
        # 声明是作者先验：解码非负且落后不超过一个标点级分差即采纳——
        # 相对比例会把「decl=latin1 实 latin-1 法文」让给 mac_roman
        # 碰巧解出的 ``†``（5.0 vs 6.0 噪声级差距）。
        if declared_text_score >= 0.0 and (
            best is None or declared_text_score >= best[2] - _DECLARED_SLACK
        ):
            note = ""
            if best is not None and best[0] != declared:
                note = f"declared {declared_raw} accepted over {best[0]}"
            return EncodingVerdict(declared, "declared", declared_raw, note)
    if candidates:
        enc, basis, _ = max(candidates, key=lambda c: c[2])
        note = ""
        if declared:
            note = f"declared {declared_raw} mismatch" if enc != declared else ""
        if basis == "mixed":
            kinds = sorted(set(regions.values()))
            note = (note + " " if note else "") + f"regions:{','.join(kinds)}"
        return EncodingVerdict(enc, basis, declared_raw, note)
    return EncodingVerdict("latin-1", "fallback", declared_raw)


def _eol_norm(text: str) -> str:
    r"""``\r\n``/``\r`` → ``\n``——TeX 输入处理同口径。

    下游（mask/词法/mouth）逐 ``\n`` 假设不再逐点设防：CR-only/混合 EOL
    文件的 ``%`` 注释曾吞到 EOF，整篇 bd 不可见 → no_main_tex
    （1608.02631/gr-qc/0605005 取证）。
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def decode_tex_with(blob: bytes) -> tuple[str, EncodingVerdict]:
    """``decode_tex`` + 判定归因。永不抛——latin-1 兜底。"""
    verdict = sniff_tex_encoding(blob)
    if verdict.encoding == "utf-8-mixed":
        return _eol_norm(_decode_mixed(blob)[0]), verdict
    try:
        return _eol_norm(blob.decode(verdict.encoding)), verdict
    except UnicodeDecodeError:
        # 判定族正确但含零星坏点（SJIS 孤立半对尾）——replace 保住
        # 95% 正确字符，远好于 latin-1 全毁。
        return (
            _eol_norm(blob.decode(verdict.encoding, errors="replace")),
            verdict,
        )
    except LookupError:
        pass
    return (
        _eol_norm(blob.decode("latin-1")),
        EncodingVerdict("latin-1", "fallback", verdict.declared, "decode failed"),
    )


def decode_tex(blob: bytes) -> str:
    """解码 arXiv 源码字节；判定层级见 :func:`sniff_tex_encoding`。"""
    return decode_tex_with(blob)[0]


# ---------------------------------------------------------------- CJK 码点面

#: CJK 统一表意码点面：扩A + 基本区 + 兼容区 + 〇（U+3007，日期用字）
#: + 扩B~F（U+20000–2FA1F）。judge/l0/l2 三处计数曾各自漂移（judge 缺
#: 〇、l0 只有三区、l2 扩F 截断在 2EBEF）——单源化后口径唯一。
CJK_RANGES: Final = (
    (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF),
    (0xF900, 0xFAFF),
    (0x3007, 0x3007),
    (0x20000, 0x2FA1F),
)

#: ``CJK_RANGES`` 的字符类形态（``findall`` 计数用）。
CJK_RX: Final = re.compile(
    "["
    + "".join(f"{chr(lo)}-{chr(hi)}" if lo != hi else chr(lo) for lo, hi in CJK_RANGES)
    + "]"
)


#: ``CJK_RANGES`` 的排序不相交面 + lo 列——``_char_class``/l2 逐字调用
#: （breview ``_score_text`` 全文体 ~5.9M 次），线性 any() 改 bisect。
_CJK_MERGED: Final = _merge_ranges(CJK_RANGES)
_CJK_LOS: Final = tuple(lo for lo, _ in _CJK_MERGED)


def is_cjk_cp(cp: int) -> bool:
    """码点是否落在 ``CJK_RANGES``（``Missing character:`` 码点判定用）。"""
    return _in_ranges(cp, _CJK_LOS, _CJK_MERGED)


def lev_capped(a: str, b: str, cap: int) -> int:
    """Levenshtein 距离，超 cap 提前返回 cap+1。"""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        rowmin = i
        for j, cb in enumerate(b, 1):
            v = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
            cur.append(v)
            rowmin = min(rowmin, v)
        if rowmin > cap:
            return cap + 1
        prev = cur
    return prev[-1]
