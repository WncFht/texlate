r"""compile.latex209.math — 数学域模态走查与两族受限转写叶 (compile.latex209 域缝叶)。

模态域判定单源：``$`` 系定界 + 数学环境体为数学域、``_TEXTARG_CS_209``
命令实参为文本域，嵌套域按 ``_innermost`` 最内层判。两族转写：
``{\em/\it/\bf X}`` switch 组 → 数学字母命令、数学域裸 cite 族调用
``\mbox{}`` 包裹；``wrap_math_cites`` 是 cite 臂的独立出口（fixloop
``cite_in_math_mbox`` 规则复用同走查）。
"""

from __future__ import annotations

import re
from typing import Final

from texlate.compile.mask import apply_edits, group_end, visible_tex
from texlate.latex.model import ws_skip
from texlate.textutil import CMD_BOUNDARY, cs_events_spans

#: 数学域 209 字体开关组 ``{\em/\it/\bf X}`` → 2e 数学字母命令映射。
#: 209 时代 ``\em``/``\it``/``\bf`` 是 switch（组内余生全换体）；2e 下
#: ``\em`` 经 ``\@nomath`` 警告后落到 ``\itshape``——``\not@math@alphabet``
#: 硬报 ``Command \itshape invalid in math mode``（astro-ph/9910310
#: ``\sum_{{\em fields}\,i}`` 实证标记）。``\it``/``\bf`` 经
#: ``\@fontswitch``+``\math@bgroup`` 在数学域本就退化出组 switch 语义
#: 不报错，仍一并归一为参数形消歧。``\rm/\sf/\tt/\cal/\mit`` 同机制
#: 本就正确不动；``\sl/\sc`` 数学域仅 ``\@nomath`` 警告丢字形（无标准
#: 数学字母对应，改写即改语义）不动。
#: 过渡期稿混用 2e 声明形 ``{\bfseries/\itshape/\rmfamily/\sffamily/\ttfamily
#: X}`` 同踩 ``\not@math@alphabet`` 硬报（gr-qc/9901082 实证）——并入映射；
#: ``\slshape/\scshape/\upshape/\mdseries/\normalfont`` 无单义数学字母
#: 对应（sl→mathit 属语义改写）保守不收。
_MATH_SWITCH_209: Final = {
    "em": "mathit",
    "it": "mathit",
    "bf": "mathbf",
    "bfseries": "mathbf",
    "itshape": "mathit",
    "rmfamily": "mathrm",
    "sffamily": "mathsf",
    "ttfamily": "mathtt",
}

#: 候选组定位：``{`` 后仅横向空白接开关系 cs——switch 须为组首
#: token 才可整组转写（``{\xyz\em X}`` 前段不在开关作用域，保守不动）；
#: ``(?<![\\])`` 挡 ``\{`` 转义花括号误中；横向空白口径挡行间注释
#: ``{%c\n\em X}`` 被静默吞进参数形；长名先列防 ``bf`` 前缀截
#: ``bfseries``（``CMD_BOUNDARY`` 本可兜住，显式排序双保险）。
_MATH_SWITCH_RE: Final = re.compile(
    r"(?<!\\)\{[^\S\n]*\\(bfseries|itshape|rmfamily|sffamily|ttfamily|em|it|bf)"
    + CMD_BOUNDARY
)

#: 数学域内 cite 族命令 ``\mbox`` 包裹清单——revtex4-2+natbib 链路
#: ``\cite`` → ``\rtx@citex`` → ``\NAT@citex``/``\@citex`` 的未定义引用标记是
#: ``{\reset@font\bfseries ?}`` **无盒**直排（natbib.sty:385/518；alias 路径
#: :607 同形 ``(alias?)``），``\bfseries`` 在数学域触发 ``\not@math@alphabet``
#: 硬报 ``Command \bfseries invalid in math mode``（gr-qc/9901082
#: ``$\phi^i_{\pm}=0 \cite{HawMos}.$`` 实证）。
#: fixloop halt_on_error 让编译死在 thebibliography 之前、``\bibcite`` 永不
#: 写回 aux → 引用每轮保持未定义 → 同错自续；``\mbox{\cite{..}}`` 把标记
#: 放回文本域（min6 实证首遍净过），已定义引用盒内外渲染一致（min7）——
#: 命中即裹、不判定义与否。清单取 natbib.sty ``\DeclareRobustCommand`` 全
#: 引用面（含 ``\citeyearpar``/``\citefullauthor``/``\citetalias``/``\citepalias``
#: 与大写句首形 ``\Citet`` 系，同走 ``\@citex``/alias 标记路径）；内核
#: ``\@citex`` 的 ``\hbox`` 包壳路径（plain article）与 ``\ref``/``\eqref``
#: 的 ``\nfss@text`` 本就安全不收；``\citetext`` 是字面文本实参、无引用
#: 标记路径不收。长名先列，``CMD_BOUNDARY`` 兜底整词。
_MATH_CITE_CS_209: Final = (
    "citefullauthor",
    "citeyearpar",
    "citeauthor",
    "Citeauthor",
    "citetalias",
    "citepalias",
    "citeyear",
    "citealt",
    "citealp",
    "citenum",
    "Citealt",
    "Citealp",
    "citep",
    "citet",
    "Citep",
    "Citet",
    "cite",
)

_MATH_CITE_RE: Final = re.compile(
    r"\\(" + "|".join(_MATH_CITE_CS_209) + r")" + CMD_BOUNDARY
)

#: ``$`` 系定界之外的数学环境（209 内建 + amsmath/amstex/IEEE/breqn 族）——
#: 环境体整段按数学域处理。同名 begin/end 栈式配对；未闭合 begin 不成域
#: （编译本即死，域内修复无意义，保守弃）。
_MATH_ENVS_209: Final = frozenset(
    {
        "math",
        "displaymath",
        "mathdisplay",
        "equation",
        "equation*",
        "eqnarray",
        "eqnarray*",
        "gather",
        "gather*",
        "align",
        "align*",
        "flalign",
        "flalign*",
        "multline",
        "multline*",
        "alignat",
        "alignat*",
        "xalignat",
        "xalignat*",
        "xxalignat",
        "gathered",
        "aligned",
        "alignedat",
        "split",
        "multlined",
        "IEEEeqnarray",
        "IEEEeqnarray*",
        "dmath",
        "dmath*",
        "dgroup",
        "dgroup*",
    }
)

_MATH_ENV_RE: Final = re.compile(
    r"\\(begin|end)\{("
    + "|".join(re.escape(n) for n in sorted(_MATH_ENVS_209, key=len, reverse=True))
    + r")\}"
)

#: 数学域内实参为文本域的命令及其 ``{...}`` 实参数——``\mbox{...}`` 内是
#: hbox 文本域，``{\em}`` 合法；转 ``\mathit`` 反而报错，作排除域。实参数
#: 逐个消耗防 ``\textbf{A} {\em B}$`` 后组被误吞成命令实参；``[..]``
#: 可选参跳过不计数。
_TEXTARG_CS_209: Final = {
    "mbox": 1,
    "fbox": 1,
    "makebox": 1,
    "framebox": 1,
    "raisebox": 2,
    "parbox": 2,
    "sbox": 1,
    "savebox": 1,
    "hbox": 1,
    "vbox": 1,
    "vtop": 1,
    "text": 1,
    "textrm": 1,
    "textsf": 1,
    "texttt": 1,
    "textmd": 1,
    "textbf": 1,
    "textup": 1,
    "textit": 1,
    "textsl": 1,
    "textsc": 1,
    "textnormal": 1,
    "emph": 1,
    "intertext": 1,
    "shortintertext": 1,
}

_TEXTARG_CS_RE: Final = re.compile(
    r"\\("
    + "|".join(sorted(_TEXTARG_CS_209, key=len, reverse=True))
    + r")"
    + CMD_BOUNDARY
)

#: ``\sbox``/``\savebox`` 首参是盒子寄存器 ``\cs``——非 ``{...}`` 实参，
#: 消耗一 token 不计实参数。
_BOXREG_CS_209: Final = frozenset({"sbox", "savebox"})

_BOXREG_RE: Final = re.compile(r"\s*\\[a-zA-Z@]+\*?")

#: ``\hbox``/``\vbox``/``\vtop`` 可带 ``to <dim>``/``spread <dim>`` 盒规格
#: ——消耗规格词（dimen 可裸值或 ``\cs``）再认 ``{...}`` 实参。
_BOXSPEC_CS_209: Final = frozenset({"hbox", "vbox", "vtop"})

_BOXSPEC_RE: Final = re.compile(
    r"\s*(?:to|spread)(?![a-zA-Z])\s*"
    r"(?:\\[a-zA-Z@]+\*?|[-+]?(?:\d+\.?\d*|\.\d+)\s*[a-zA-Z]{1,3})"
)


def _math_env_spans(vis: str) -> list[tuple[int, int]]:
    r"""``\begin{<数学env>}...\end{<同名>}`` 区间——同名栈式配对。

    未闭合 begin 弃（编译本即死）；异名交错由栈深度自然兜底——同名
    env 合法不可嵌套，交错末配对段保守不收。
    """
    stack: dict[str, list[int]] = {}
    spans: list[tuple[int, int]] = []
    for m in _MATH_ENV_RE.finditer(vis):
        kind, name = m.group(1), m.group(2)
        if kind == "begin":
            stack.setdefault(name, []).append(m.start())
        elif stack.get(name):
            spans.append((stack[name].pop(), m.end()))
    return spans


def _textarg_spans(vis: str, pos: int, name: str) -> list[tuple[int, int]]:
    r"""``<name>`` 命令自 ``pos`` 起的 ``{...}`` 实参区间表（文本域排除用）。

    ``[..]`` 可选参跳过不计数；``\sbox`` 系先消耗 ``\cs`` 寄存器参、
    ``\hbox`` 系先消耗 ``to/spread <dim>`` 规格再数 ``{...}``。
    """
    i = pos
    if name in _BOXREG_CS_209:
        m = _BOXREG_RE.match(vis, i)
        if m is not None:
            i = m.end()
    if name in _BOXSPEC_CS_209:
        m = _BOXSPEC_RE.match(vis, i)
        if m is not None:
            i = m.end()
    spans: list[tuple[int, int]] = []
    while len(spans) < _TEXTARG_CS_209[name]:
        i = ws_skip(vis, i)
        if i >= len(vis) or vis[i] not in "[{":
            break
        e = group_end(vis, i)
        if e <= i:
            break
        if vis[i] == "{":
            spans.append((i, e))
        i = e
    return spans


def _innermost(
    regions: list[tuple[int, int, str]], pos: int
) -> tuple[int, int, str] | None:
    r"""包含 ``pos`` 的最小区间——嵌套域按最内层模态判。

    ``\mbox{${\em}$}`` 内层 ``$`` 域小于 mbox 实参域 → 数学；
    ``$\mbox{{\em}}$`` 反之 → 文本。
    """
    best: tuple[int, int, str] | None = None
    for a, b, mode in regions:
        if a <= pos < b and (best is None or b - a < best[1] - best[0]):
            best = (a, b, mode)
    return best


def _cite_call_end(vis: str, pos: int) -> int:
    r"""``pos`` 起 cite 调用尾端的后一 offset：``*`` + ≤2 ``[..]`` + ``{key}``。

    缺 ``{key}`` 实参返回 ``-1``——裸 ``\cite`` token 裹 ``\mbox{}`` 会让
    ``\@citex`` 把 ``}`` 读成 key 实参，保守不动。``[..]``/``{..}`` 配对
    走 ``group_end``（转义/嵌套/行间注释形态同 ``_textarg_spans`` 口径）。
    """
    i = pos
    n = len(vis)
    for _ in range(3):  # ``*`` 槽 + 两个 ``[..]`` 槽——槽序由实见字符自证
        i = ws_skip(vis, i)
        if i < n and vis[i] == "*":
            i += 1
            continue
        if i < n and vis[i] == "[":
            e = group_end(vis, i)
            if e <= i:
                return -1
            i = e
            continue
        break
    i = ws_skip(vis, i)
    if i >= n or vis[i] != "{":
        return -1
    e = group_end(vis, i)
    return e if e > i else -1


def _math_regions(vis: str) -> list[tuple[int, int, str]]:
    r"""模态域区间表: ``$`` 系定界 + 数学环境体为 ``"m"``, 文本实参域为 ``"t"``。

    ``cs_events_spans`` 配对 ``$..$``/``$$..$$``/``\(..\)``/``\[..]``，
    ``_math_env_spans`` 配对数学环境体；``_TEXTARG_CS_209`` 命令实参为
    文本域——嵌套域由 :func:`_innermost` 按最内层判。无数学域直接返回
    空表（textarg 域无独立意义）。``_fix_math_209`` 与 fixloop
    ``wrap_math_cites`` 共用的模态判定单源。
    """
    _, dollar_spans = cs_events_spans(vis)
    spans = dollar_spans + _math_env_spans(vis)
    if not spans:
        return []
    regions: list[tuple[int, int, str]] = [(a, b, "m") for a, b in spans]
    for m in _TEXTARG_CS_RE.finditer(vis):
        regions.extend((a, b, "t") for a, b in _textarg_spans(vis, m.end(), m.group(1)))
    return regions


def _cite_mbox_edits(
    vis: str, regions: list[tuple[int, int, str]]
) -> tuple[list[tuple[int, int, str]], int]:
    r"""数学域内裸 cite 族调用的两端零宽插入 edits → ``(edits, n_calls)``。

    命中判据与 ``_MATH_CITE_CS_209`` 注同：最内域须数学域、完整调用
    （``_cite_call_end`` 配出 ``{key}``）须含于同一域内。同位插入按
    生成序拼接——相邻调用 ``\cite{a}\cite{b}`` 的左闭 ``}`` 与右开
    ``\mbox{`` 落在同一 offset，``apply_edits`` 同位只按 repl 字典序
    排，须预先拼好（finditer 升序命中保证先闭后开）。
    """
    inserts: dict[int, list[str]] = {}
    n = 0
    for m in _MATH_CITE_RE.finditer(vis):
        inner = _innermost(regions, m.start())
        if inner is None or inner[2] != "m":
            continue
        end = _cite_call_end(vis, m.end())
        if end < 0 or end > inner[1]:
            continue
        inserts.setdefault(m.start(), []).append("\\mbox{")
        inserts.setdefault(end, []).append("}")
        n += 1
    return [(pos, pos, "".join(strs)) for pos, strs in inserts.items()], n


def wrap_math_cites(tex: str) -> tuple[str, int]:
    r"""数学域内裸 cite 族调用 ``\cite[..]{k}`` → ``\mbox{\cite[..]{k}}``；返回 ``(new_tex, n)``。

    ``_fix_math_209`` cite 臂的独立出口——非 209 时代稿 (fixloop
    ``cite_in_math_mbox`` 规则, invalid_in_math 标记) 复用同一模态域
    走查；机制/清单论证见 ``_MATH_CITE_CS_209`` 注。``visible_tex``
    遮盖面定位 + ``apply_edits`` 回填保行号。幂等——已裹调用居
    ``\mbox`` 文本域不再命中。
    """
    vis = visible_tex(tex)
    edits, n = _cite_mbox_edits(vis, _math_regions(vis))
    if not edits:
        return tex, 0
    return apply_edits(tex, edits), n


def _fix_math_209(tex: str) -> tuple[str, int, int]:
    r"""数学域两族受限转写（共用一次模态域走查）→ ``(new_tex, n_switch, n_cite)``。

    switch 组 ``{\em/\it/\bf X}`` → ``\mathit{...}``/``\mathbf{...}``（209 时代
    switch 在 2e 数学域硬报 ``\not@math@alphabet``）；裸 cite 族调用
    ``\cite[..]{k}`` → ``\mbox{\cite[..]{k}}``（未定义引用标记 ``\bfseries``
    同标记硬报且 fixloop 自续，见 ``_MATH_CITE_CS_209`` 注）。

    模态判定：``_math_regions`` 单源——``$`` 系定界 + 数学环境体为数学域、
    ``_TEXTARG_CS_209`` 命令实参为文本域，嵌套域按 :func:`_innermost` 最内层
    判。组/调用整体须含于同一数学域内（越界即残缺形态不动）。定位全在
    ``visible_tex`` 遮盖视图——注释/逐字内容里的同形不参与；回填
    ``apply_edits`` 保行号。cite 包裹是两端零宽插入（``\mbox{``/``}``），
    与 switch 的段替换不争 span——逆序回放下 ``$\cite{{\em x}}$`` 这类
    两族命中互不覆盖。
    """
    vis = visible_tex(tex)
    regions = _math_regions(vis)
    if not regions:
        return tex, 0, 0
    edits: list[tuple[int, int, str]] = []
    n_switch = 0
    for m in _MATH_SWITCH_RE.finditer(vis):
        inner = _innermost(regions, m.start())
        if (
            inner is not None
            and inner[2] == "m"
            and group_end(vis, m.start()) <= inner[1]
        ):
            edits.append(
                (m.start(), m.end(), "\\" + _MATH_SWITCH_209[m.group(1)] + "{")
            )
            n_switch += 1
    cite_edits, n_cite = _cite_mbox_edits(vis, regions)
    edits.extend(cite_edits)
    if not edits:
        return tex, 0, 0
    return apply_edits(tex, edits), n_switch, n_cite
