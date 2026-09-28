r"""resid — zh 树残英清扫：未进 chunk 表的英文 run → 就地翻译回写。

残英不是 cache 毒——是三路**结构性未送译**，``rexlat`` 重翻够不着，
段级缓存里连对应条目都没有：

1. **保护区体内**（``latex.tables.PROTECTED_ENVS``——table/tabular/
   figure/algorithm/tikzpicture 等）：segmenter 整块占位、只挖 caption
   族 chunk（``MINED_ONLY`` 口径）——胞格散文/浮体说明/算法行内文
   从不送译；
2. **include 图外文件**（scan ``support_files``）：main 主链 ``\input``
   够不着的死文件留英——不进 PDF（不编），但赃 zh 树；
3. **resolver 盲 include**（扫描标记 missing_input、编译期 kpathsea
   却解析成功——大小写变体 ``\input{Our-Solution}``→``our-solution.tex``
   类）：文件进了 PDF 却从没进 chunk 表，整节英文直出成品
   （2208.00283 实证 216 行）。

本件在 ``translate_tree_async`` splice 写回后对 ``root`` 全部 ``.tex``
做就地清扫——口径即 ``nets`` 残英网的抽取面推广到全文：

- ``mask_tex`` 等长遮盖（注释+verbatim 族+comment 死环境+``\verb``/
  ``\lstinline``）+ ``thebibliography`` 体额外排除（bib 留英合法，
  同 ``[[BIB_`` 豁免口径）；``MATH_ENVS`` 体+行内 ``$..$``/``$$..$$``/
  ``\(..\)``/``\[..\]`` 全遮——数学域 ``\text{英}`` 译了出 tofu；
- 空行分段 → ``\\``/``&``/``{}``/``$``/``%``/``#``/``^``/``_``/``~``/
  ``|`` 字符族切 run（单 ``\n`` 不切——胞格散文常 80 列硬折行）；
- 片首 cs 名剥除——``\`` 切分后残片以 cs 名开头时剥 ``\item``/``\section``
  头（否则 ``\item`` 变 ``\中文`` 断命令）；span 再裁到 alnum 核心，
  边沿 ``()``/``.``/``,`` 标点留原文保配对；
- 判据沿用 ``nets`` 门槛+豁免：≥8 词、≥40 拉丁、tech/人名/ident-list
  三豁免；另设**短胞格档** ≥4 词、≥18 拉丁——QC 残英网按渲染行计词，
  数据表短语行卡 nets 门槛漏收照样积成 residual_en；数字 token 过半
  与逗号单字段全小写清单两闸防啃 cite 键串/版本串；键值型命令参数
  （``\cite``/``\ref``/``\label``/``\url``/``\tikzset`` 族）整段预置
  哨兵；``[...]`` 键表按花括号深度切顶层逗号段——键名置哨兵、
  ``=value`` 值域留扫（pgfkeys 选项翻中文即 ``key_unknown`` 断编译，
  2609.20069 实证），``\item``/``\caption`` 散文括号豁免；
- 遮盖区是硬边界——``mask_tex`` 遮区逐位转 ``\x00`` 哨兵、env/math
  遮区两端置哨兵：span 按原文坐标回写，遮区跨进 run 会把 ``% 注释``/
  ``\verb``/``$..$`` 原始文本一并吃掉（v1 桥接形实测吞数学对，zh 树
  ``$`` 计数差为普查口径）；
- span 去重逐条翻译，``resid_v1`` role 复用段级缓存桶——续跑不
  重烧；
- 清理闸：回译含结构符（``\{}&$%#^_~``/``[[``）或零 CJK → 弃置留
  英文——宁留原文不出结构污染；
- 按原文同位右到左回写，不碰任何 LaTeX 结构件。
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
from typing import TYPE_CHECKING, Final

from texlate.latex.tables import MATH_ENVS
from texlate.textutil import CJK_RX, mask_tex
from texlate.textutil.nets import (
    _RESID_EN_MIN_LATIN,
    _RESID_EN_MIN_WORDS,
    _RESID_EN_WORD_RX,
    _ident_list_run,
    _keep_verbatim_run,
    _tech_run,
)
from texlate.xlat.state import segment_key

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.xlat.pipeline import Translator

__all__ = ["DEFAULT_OPTS", "SweepOpts", "find_resid_spans", "sweep_tree"]


#: span 分切字符族——cs/组/单元格/数学/注释/上下标/粘连/vert 界一律断；
#: 单 ``\n`` 不切（散文源文常 80 列硬折行，切了碎成欠阈残段漏收），
#: 空行级段落界由 ``_PARA_BOUND_RX`` 先行切开。``\x00`` 是遮盖区哨
#: 兵——``mask_tex`` 遮区（注释/``\verb``/verbatim 族/死环境）逐位转哨
#: 兵、env/math 遮区两端各置一个；否则遮盖区跨进 run 变成内部空白，
#: 回写时把坐标内原始 ``$..$``/``\verb``/注释文本一并吃掉（1906.00256
#: 实测胞格 ``Low-amplitude $\sim 0.05$ mag in $VRI$`` 类混排重灾区，
#: v1 桥接形 zh 树 ``$`` 计数亏 28 实证）。
_SPAN_DELIM_RX: Final = re.compile(r"[\\{}&$%#^_~|\x00]")
_PARA_BOUND_RX: Final = re.compile(r"\n[ \t]*\n")
#: 回译清理闸：span 嵌在 ``&``/``{}``/cs 邻域，回译带任一类结构符即弃。
_ZH_BAD_RX: Final = re.compile(r"[\\{}&$%#^_~]|\[\[")

_ENV_TAG_RX: Final = re.compile(r"\\(begin|end)\s*\{\s*([A-Za-z@*]+)\s*\}")
#: 体文排除名单——数学族（``\text{}`` 内嵌英译了会出 tofu，数学域留英
#: 合法）+ ``thebibliography``（``[[BIB_`` 豁免同源口径，文献留英合法）。
_EXCL_ENVS: Final = set(MATH_ENVS) | {"thebibliography"}
#: 行内数学开符——``\(...\)``/``\[...\]``/``$...$``/``$$...$$``；``\$``
#: 转义符不配（前断言），``\\$`` 极端组合保守放行。
_MATH_OPEN_RX: Final = re.compile(r"(?<!\\)(\$\$|\$)|\\[\[\(]")

#: 片首控制序列名——``\`` 切分后残片以 cs 名开头（``\item 散文``），剥掉
#: cs 名+可选 ``*``+可选 ``[..]`` 参及后随空白，否则 ``\item`` 变 ``\中文``
#: 断命令。``\section{题目}`` 的 cs 名片剥空自身，brace 内正文照常评。
#: 散文括号 cs（``\item``/``\caption``/章节族）的 ``[..]`` 是读者可见散
#: 文不是选项——走 ``_CS_HEAD_NOOPT_RX`` 不吃括号，留给键表罩+抽取面。
_CS_HEAD_RX: Final = re.compile(r"[A-Za-z@]+\*?[ \t]*(\[[^\]\n]*\])?[ \t]*")
_CS_HEAD_NOOPT_RX: Final = re.compile(r"[A-Za-z@]+\*?[ \t]*")
_CS_NAME_RX: Final = re.compile(r"[A-Za-z@]+\*?")

#: 短胞格档——QC 残英网按**渲染行**计词（``≥4`` 词），数据表短语行
#: 5-8 词/20-37 拉丁虽低于 nets 门槛照样积成 residual_en（1906.00256
#: 实测 73 行主块全是这类）。两闸防误啃：token 半数含数字拒收
#: （``cite{a2008,b2010}`` 多键串/版本串），逗号单字段全小写清单拒收
#: （``smith, jones, taylor`` 形 cite 键串——``PMS, CTT`` 类大写缩写表
#: 仍放行，这类本就是 QC 想翻的对象）。
_SPAN_MIN_WORDS_SHORT: Final = 4
_SPAN_MIN_LATIN_SHORT: Final = 18
_KEYLIST_MIN_SEGS: Final = 2
_DIGIT_IN_RX: Final = re.compile(r"\d")

#: 键值型命令参数整体排除——``\cite{...}``/``\ref``/``\label``/``\url``/
#: ``\path``/``\input``/``\tikzset``/``\pgfplotsset`` 族的括号内容是键名
#: 不是散文，tier-2 降阈后 4+ 键串会够线被误译断引用/断键；整段预置哨
#: 兵比分切后猜形稳。
_KEY_ARG_RX: Final = re.compile(
    r"\\(?:cite[A-Za-z]*|nocite|ref|eqref|pageref|autoref|[cC]ref|label|"
    r"input|include|includegraphics|bibliography|bibliographystyle|"
    r"addbibresource|url|path|doi|tikzset|pgfplotsset|pgfkeys|pgfqkeys|"
    r"usetikzlibrary|hypersetup)[ \t]*"
    r"(?:\[[^\]\n]*\][ \t]*){0,2}\{[^}\n]*\}"
)

#: ``[...]`` 选项表——pgfkeys 键表（``\addplot[only marks, mark=*, mark
#: options={fill=white}]``/``\begin{axis}[scale only axis, width=...]``）
#: 形状与散文不可分，但键名翻成中文即 ``key_unknown``/``dirty_pdf`` 编译
#: 损毁（2609.20069 实测）。按花括号深度切顶层逗号段：每段键部（首个
#: 深度-0 ``=`` 前）须为 pgfkeys 名形；``=`` 段只哨兵键名、值域照常可
#: 扫（``xlabel={Time (s)}`` 值是散文该译），布尔键段整段哨兵。全键形
#: 且（任一带 ``=`` 或全短键 ≥2 段）才算键表——单段无 ``=`` 的长散文
#: 括号（``[see Section 3]`` 类）不误伤；键串散文假阳代价=漏译一行，
#: 远轻于断编译。
_BRACKET_RX: Final = re.compile(r"\[([^\[\]\n]*)\]")
_KEY_NAME_RX: Final = re.compile(r"[A-Za-z@*./][A-Za-z0-9@* .+_'/-]*")
_KEYLIST_MAX_KEY_WORDS: Final = 3
#: 散文括号 cs 豁免——``\item[标签]``/``\caption[短题]``/章节的 ``[..]``
#: 是面向读者的散文不是键表；括号前 text 尾落这类 cs 时跳过键表面罩。
_PROSE_BRACKET_CS: Final = frozenset(
    {
        "item",
        "caption",
        "chapter",
        "part",
        "section",
        "subsection",
        "subsubsection",
        "paragraph",
        "subparagraph",
        "footnote",
        "thanks",
        "title",
        "author",
    }
)
_PROSE_BRACKET_CS_RX: Final = re.compile(
    r"\\(?:" + "|".join(sorted(_PROSE_BRACKET_CS, key=len, reverse=True)) + r")\*?\s*$"
)


def _top0_segs(inner: str) -> list[tuple[int, int]]:
    """花括号深度-0 逗号切段——``{a, b}`` 值域内逗号不切。"""
    bounds: list[tuple[int, int]] = []
    depth = 0
    start = 0
    for i, c in enumerate(inner):
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        elif c == "," and depth == 0:
            bounds.append((start, i))
            start = i + 1
    bounds.append((start, len(inner)))
    return bounds


def _key_part(seg: str) -> tuple[str, bool]:
    """段内首个深度-0 ``=`` 前的键部；返回 ``(key_text, has_eq)``。"""
    depth = 0
    for i, c in enumerate(seg):
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        elif c == "=" and depth == 0:
            return seg[:i], True
    return seg, False


def _bracket_key_spans(inner: str, base: int) -> list[tuple[int, int]]:
    """``[...]`` 内 pgfkeys 键名区间（``base``=inner 起点的全文坐标）。

    非键表形 → ``[]``（调用方面罩跳过）。键表形时 ``=`` 段只回键名区间
    ——值留在扫描面让 ``xlabel={英文标签}`` 照常译；布尔段整段置哨兵。
    """
    bounds = _top0_segs(inner)
    spans: list[tuple[int, int]] = []
    has_eq = False
    for ss, se in bounds:
        ktxt, eq = _key_part(inner[ss:se])
        key = ktxt.strip()
        if not _KEY_NAME_RX.fullmatch(key):
            return []
        has_eq = has_eq or eq
        if not eq and len(_RESID_EN_WORD_RX.findall(key)) > _KEYLIST_MAX_KEY_WORDS:
            return []
        lead = len(ktxt) - len(ktxt.lstrip())
        spans.append((base + ss + lead, base + ss + lead + len(key)))
    if not has_eq and len(bounds) < _KEYLIST_MIN_SEGS:
        return []
    return spans


_SYS_PROMPT: Final = (
    "Translate the English text to Simplified Chinese. The text is a fragment "
    "from a LaTeX document. Output ONLY the translated text on one line — "
    "no LaTeX commands, no math delimiters, no quotes, no explanations. "
    "Keep proper nouns, numbers and units as appropriate for an academic "
    "translation."
)
#: role 里压版本——改 prompt/口径直接 bump，旧桶条目自然失效免逐桶清。
_CACHE_ROLE: Final = "resid_v1"


@dataclasses.dataclass(frozen=True)
class SweepOpts:
    """``sweep_tree`` 调参束——并发/温度/上限随调用方 PipelineConfig 对齐。"""

    concurrency: int = 8
    temperature: float = 0.2
    max_tokens: int = 2048


#: B008——默认 opts 走模块级单例，默认参位不落调用形。
DEFAULT_OPTS: Final = SweepOpts()


def _excl_env_regions(masked: str) -> list[tuple[int, int]]:
    r"""排除环境体区间——``\begin/\end`` 栈扫，名单 ``_EXCL_ENVS``。

    非名单 env 照常入栈保持配对；同名近端配对，错位/未闭合名单体
    遮到 EOF（bib 断尾常见，保守全丢）。verbatim/comment 族体已被
    ``mask_tex`` 盖白——其中字面 ``\begin/\end`` 不可见，栈天然免疫。
    """
    stack: list[tuple[str, int]] = []
    regions: list[tuple[int, int]] = []
    for m in _ENV_TAG_RX.finditer(masked):
        which, name = m.group(1), m.group(2)
        if which == "begin":
            stack.append((name, m.end()))
            continue
        for i in range(len(stack) - 1, -1, -1):
            if stack[i][0] == name:
                _n, body_start = stack[i]
                if name in _EXCL_ENVS:
                    regions.append((body_start, m.start()))
                del stack[i:]
                break
    for name, body_start in stack:
        if name in _EXCL_ENVS:
            regions.append((body_start, len(masked)))
    return regions


def _excl_math_regions(masked: str) -> list[tuple[int, int]]:
    r"""行内数学区间——``$..$``/``$$..$$``/``\(..\)``/``\[..\]`` 配对扫。

    未闭合开符保守遮到行尾（字面 ``$`` 散兵不吞全文）。闭合查找同样
    拒吃转义 ``\$``。
    """
    regions: list[tuple[int, int]] = []
    pos = 0
    while True:
        m = _MATH_OPEN_RX.search(masked, pos)
        if m is None:
            return regions
        tok = m.group(0)
        if tok == r"\(":
            closer = r"\)"
        elif tok == r"\[":
            closer = r"\]"
        else:
            closer = tok
        if closer.startswith("\\"):
            cm = re.compile(re.escape(closer)).search(masked, m.end())
        else:
            cm = re.compile(r"(?<!\\)" + re.escape(closer)).search(masked, m.end())
        if cm is None:
            nl = masked.find("\n", m.start())
            regions.append((m.start(), len(masked) if nl == -1 else nl))
            pos = m.end()
            continue
        regions.append((m.start(), cm.end()))
        pos = cm.end()


def _edge_bounds(run: str) -> tuple[int, int]:
    """Strip 后 run 的 alnum 核心区间——边沿 ``()[].,;:'`` 标点留给原文。

    span 只换核心：``(similar to X)`` 的 ``()`` 留位保配对，``图 3)`` 类
    尾括不被回译吃掉。
    """
    i0 = 0
    n = len(run)
    while i0 < n and not (run[i0].isascii() and run[i0].isalnum()):
        i0 += 1
    i1 = n
    while i1 > i0 and not (run[i1 - 1].isascii() and run[i1 - 1].isalnum()):
        i1 -= 1
    return i0, i1


def _span_ok(core: str) -> bool:
    """候选核心是否真残英散文——``nets`` 残英网同款门槛+豁免。

    span 天生 verbatim（未送译的源文直留），``_ident_list_run`` 在 nets
    侧的 ``core in ss`` 前置此处恒真——名表列无条件豁免。
    """
    if not core:
        return False
    words = _RESID_EN_WORD_RX.findall(core)
    lat = sum(1 for c in core if c.isascii() and c.isalpha())
    if len(words) < _RESID_EN_MIN_WORDS or lat < _RESID_EN_MIN_LATIN:
        if len(words) < _SPAN_MIN_WORDS_SHORT or lat < _SPAN_MIN_LATIN_SHORT:
            return False
        dig = sum(1 for w in words if _DIGIT_IN_RX.search(w))
        if dig * 2 >= len(words):
            return False
        segs = [s.strip() for s in core.split(",") if s.strip()]
        if len(segs) >= _KEYLIST_MIN_SEGS and all(
            len(_RESID_EN_WORD_RX.findall(s)) == 1 and s.islower() for s in segs
        ):
            return False
    return not (_tech_run(core) or _keep_verbatim_run(core) or _ident_list_run(core))


def _mask_zones(text: str, base: str) -> str:
    r"""全部哨兵面罩管道——``mask_tex`` 差区+排除 env/数学+键值参+键表。

    返回等长工作文本：遮区逐位 ``\x00``/空白，可见面原样。
    """
    masked = "".join("\x00" if a != b else b for a, b in zip(text, base, strict=True))
    chars = list(masked)
    for s, e in _excl_env_regions(masked) + _excl_math_regions(masked):
        chars[s:e] = [c if c in "\r\n" else " " for c in masked[s:e]]
        if s < e:
            chars[s] = chars[e - 1] = "\x00"
    masked = "".join(chars)
    for m in _KEY_ARG_RX.finditer(masked):
        s, e = m.start(), m.end()
        chars[s:e] = "\x00" * (e - s)
    masked = "".join(chars)
    for m in _BRACKET_RX.finditer(masked):
        if _PROSE_BRACKET_CS_RX.search(masked[max(0, m.start() - 72) : m.start()]):
            continue
        for s, e in _bracket_key_spans(m.group(1), m.start(1)):
            chars[s:e] = "\x00" * (e - s)
    return "".join(chars)


def find_resid_spans(text: str) -> list[tuple[int, int, str]]:
    """残英 span 抽取：zh ``.tex`` 文本 → ``(start, end, span_text)`` 列表。

    ``mask_tex`` 等长遮盖取位——span 落在原文坐标系，调用方按 ``end``
    降序回写。span 文本保留原换行（送译前折叠，回写整段替换）。
    """
    base = mask_tex(text)
    if len(base) != len(text):  # mask_tex 等长契约违约——坐标系不可用，整文弃扫
        return []
    # mask_tex 遮区（注释/verbatim 族/``\verb``/死环境）逐位转哨兵——span
    # 回写按原文坐标进行，遮区一旦跨进 run，替换会把 ``% 注释``/``\verb|x|``
    # 的原始文本一并吃掉（``\verb`` 内可见文本丢失是成品级损毁）。
    masked = _mask_zones(text, base)

    spans: list[tuple[int, int, str]] = []
    p_start = 0
    bounds = [(m.start(), m.end()) for m in _PARA_BOUND_RX.finditer(masked)]
    bounds.append((len(masked), len(masked)))
    for pb, pe in bounds:
        para = masked[p_start:pb]
        base = p_start
        p_start = pe
        pos = 0
        for piece in _SPAN_DELIM_RX.split(para):
            start = base + pos
            pos += len(piece) + 1  # +1 = 被吃掉的分切字符
            body = piece
            if start > 0 and masked[start - 1] == "\\":
                nm = _CS_NAME_RX.match(body)
                cs = nm.group(0).rstrip("*") if nm is not None else ""
                cm = (
                    _CS_HEAD_NOOPT_RX.match(body)
                    if cs in _PROSE_BRACKET_CS
                    else _CS_HEAD_RX.match(body)
                )
                if cm is not None:
                    start += cm.end()
                    body = body[cm.end() :]
            run = body.strip()
            i0, i1 = _edge_bounds(run)
            core = run[i0:i1]
            if _span_ok(core):
                # strip+edge 位差：span 按 alnum 核心记，边沿标点留原文
                lead = len(body) - len(body.lstrip())
                spans.append((start + lead + i0, start + lead + i1, core))
    return spans


def _clean_zh(zh: str) -> str | None:
    r"""回译清理闸——零 CJK/含结构符（``\{}&$%#^_~``/``[[``）→ ``None``。"""
    zh = re.sub(r"\s+", " ", zh.strip())
    if not zh or _ZH_BAD_RX.search(zh) or not CJK_RX.search(zh):
        return None
    return zh


def _collect_jobs(root: Path) -> tuple[list[tuple[Path, str, list]], dict[str, None]]:
    """扫 ``root`` 全部 ``.tex`` 取残英 span——同步件，async 侧 ``to_thread`` 起。"""
    jobs: list[tuple[Path, str, list[tuple[int, int, str]]]] = []
    uniq: dict[str, None] = {}
    for p in sorted(root.rglob("*.tex")):
        raw = p.read_text(encoding="utf-8", errors="replace")
        spans = find_resid_spans(raw)
        if not spans:
            continue
        jobs.append((p, raw, spans))
        for _s, _e, run in spans:
            uniq[run] = None
    return jobs, uniq


def _apply_jobs(
    jobs: list[tuple[Path, str, list]],
    table: dict[str, str | None],
    metrics: dict,
) -> None:
    """翻译表按 span 右到左回写进 ``.tex``——同步件，``to_thread`` 起。"""
    for p, raw, spans in jobs:
        text = raw
        for start, end, run in sorted(spans, key=lambda t: -t[0]):
            zh = table.get(run)
            if zh is None:
                metrics["kept_en"] += 1
                continue
            text = text[:start] + zh + text[end:]
            metrics["replaced"] += 1
        if text != raw:
            p.write_text(text, encoding="utf-8")


async def sweep_tree(
    root: Path,
    translator: Translator,
    opts: SweepOpts = DEFAULT_OPTS,
    *,
    cache: dict | None = None,
) -> dict:
    """``sweep_tree``——``root`` 下全部 ``.tex`` 残英清扫回写；返回 metrics。

    ``translator`` 复用 ``XlatPipeline`` 同款 ``.translate(system=, user=,
    temperature=, max_tokens=)`` 面；``cache`` 传段级缓存桶（span 以
    ``resid_env_v1`` role 入键，与 chunk 键同桶不同名域）。文件 IO 全
    走 ``to_thread``——async 体不落阻塞 pathlib（ASYNC240）。
    """
    jobs, uniq = await asyncio.to_thread(_collect_jobs, root)
    metrics = {
        "files": len(jobs),
        "spans": sum(len(s) for _p, _r, s in jobs),
        "uniq": len(uniq),
        "calls": 0,
        "cache_hits": 0,
        "kept_en": 0,
        "replaced": 0,
    }
    if not jobs:
        return metrics

    sem = asyncio.Semaphore(max(1, opts.concurrency))
    table: dict[str, str | None] = {}

    async def _one(run: str) -> None:
        key = segment_key(run, _CACHE_ROLE)
        if cache is not None and key in cache:
            zh = _clean_zh(str(cache[key]))
            if zh is not None:
                metrics["cache_hits"] += 1
                table[run] = zh
                return
        async with sem:
            try:
                out = await translator.translate(
                    system=_SYS_PROMPT,
                    user=re.sub(r"\s+", " ", run),
                    temperature=opts.temperature,
                    max_tokens=opts.max_tokens,
                )
            except Exception:  # noqa: BLE001 — 单 span 败不拖篇，留英文
                table[run] = None
                return
        metrics["calls"] += 1
        zh = _clean_zh(str(out))
        if zh is not None and cache is not None:
            cache[key] = zh
        table[run] = zh

    await asyncio.gather(*(_one(run) for run in uniq))
    await asyncio.to_thread(_apply_jobs, jobs, table, metrics)
    return metrics
