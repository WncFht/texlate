r"""docclass/bd 注入缝原语 —— inject.py 出叶（C4 拆分）。

原名 ``_seams.py``，改名避与 ``seams.py``（monkeypatch 注册面）撞名——
本叶是注入缝几何件，非 patch 缝。

概念归属：``\documentclass``/``\documentstyle`` 缝位走查与回填原语——
``find_docclass_ends``（visible_tex 遮盖视图上的 depth-0 直缝 + 嵌套
条件构造包容缝 + 宏包声明 proxy 缝）、``_splice_after_seams`` 逐缝回填、
``_splice_before_document`` ``\begin{document}`` 前 depth-0 锚、
``_sentinel_wrap`` 多缝/多锚幂等哨兵包裹。
消费侧 ``inject``（CJK 注入）/``layout``（FLOAT_SIZING/TABLE_FITTING）/
``normalize``（XETEX_EARLY_DEFS）/fixloop builtins 单向取用——本叶仅
依赖 textutil/mask，零 compile 内回引，无环。
"""

from __future__ import annotations

import re

from texlate.textutil import (
    BEGIN_DOC_RX,
    DEAD_ENVS,
    DOCCLASS_RX,
    VERBATIM_ENVS,
    iter_depth,
    iter_depth0,
)

from .mask import group_end, visible_tex

#: ``\begin{逐字/失活环境}`` opener——遮盖视图把 opener 本身也抹成空白，
#: 判断 docclass 行尾是否藏吞行环境必须查原文 tail（fuzz I4）。
_ENV_OPEN_RE = re.compile(
    r"\\begin\s*\{(?:"
    + "|".join(re.escape(e) for e in sorted(VERBATIM_ENVS | DEAD_ENVS))
    + r")\}"
)

#: \documentclass 调用参数扫描上限（防御畸形输入死循环）。
_DOCCLASS_SCAN_LIMIT = 4000


def _docclass_close(vis: str, start: int) -> int:
    r"""从 `\documentclass` 命令名之后扫描 `[opt]{cls}` 配对，返回 `}` 后 offset。

    在 visible_tex 遮盖视图上扫——`%` 注释/verbatim 已等长抹成空格，
    注释内括号不参与配对。命令名与首括号之间只允许空白（含被抹平的
    注释残位）：`\documentclass\cls` 宏实参/裸声明形态下首个非空白
    token 不是 `[`/`{`，扫到则收口返回 start（调用方退化行尾缝）——
    无界前扫曾把远处 `\begin{document}` 的花括号吞成类名实参，缝落
    enddoc 行死注（I2）。
    """
    j, n = start, len(vis)
    db = dc = 0
    seen_brace = False
    while j < n:
        c = vis[j]
        if not seen_brace and db == 0 and c not in "[{ \t\n\r":
            return start
        if c == "\\":
            j += 2
            continue
        if c == "[":
            db += 1
        elif c == "]":
            db -= 1
        elif c == "{":
            dc += 1
            seen_brace = True
        elif c == "}":
            dc -= 1
            if seen_brace and dc == 0 and db <= 0:
                # 畸形 ``{cls}[opts]`` 形态（选项段落在类名花括**后**——
                # 1003.0691 ``\documentclass{article}[11pt,onecolumn,letter]``、
                # 1803.00252 ``{revtex4}[12pt]`` 实档）：不吞则缝位停在 ``}``，
                # ``[opts]`` 孤儿化成 stray-text 页 + Missing ``\begin{document}``。
                # 只认 ``[``——``{`` 尾随组是普通文本组不可吞。
                arg = _trailing_arg(vis, j + 1)
                if arg is not None and vis[arg] == "[":
                    return group_end(vis, arg)
                return j + 1
        if j - start > _DOCCLASS_SCAN_LIMIT:
            break
        j += 1
    return j


def _seam_after_close(tex: str, vis: str, close: int) -> tuple[int, int]:
    r"""``}`` 后缝位判定：同行纯空白/注释 → 行尾缝，有活代码/逐字 opener → 即插。

    ``}`` 后同行纯空白/注释 → 行尾缝（吞注释安全位）；同行有活
    代码（单行文档的 bd/enddoc）或行尾开逐字/失活环境（opener 自身
    在 vis 上被抹平，须查原文 tail）则 ``}`` 后即插——插到其前不
    劈断、不落死文本/环境体（I1/I3/I4）。返回 ``(insert, lineno)``。
    """
    eol = tex.find("\n", close)
    lineno = tex.count("\n", 0, close) + 1
    tail = vis[close : eol if eol >= 0 else len(vis)]
    raw_tail = tex[close : eol if eol >= 0 else len(tex)]
    insert = (
        eol
        if eol >= 0 and not tail.strip() and not _ENV_OPEN_RE.search(raw_tail)
        else close
    )
    return insert, lineno


def _trailing_arg(vis: str, pos: int) -> int | None:
    r"""``pos`` 起跳过空白/单行 ``\n`` 后若是 ``{``/``[`` 实参开 → 返回其位。

    空行（``\par`` token）非可吞空白——遇之即非实参，返回 ``None``。
    """
    n = len(vis)
    j = pos
    while j < n and vis[j] in " \t":
        j += 1
    if j < n and vis[j] == "\n":
        j += 1
        while j < n and vis[j] in " \t":
            j += 1
        if j >= n or vis[j] == "\n":
            return None  # 空行 = \par token——实参扫描到此为止
    return j if j < n and vis[j] in "{[" else None


def _nested_construct_end(vis: str, start: int, depth: int) -> int:
    r"""depth>0 docclass 命中的构造尾：最外包容组的 depth-0 闭 ``}`` 之后 offset。

    ``\IfFileExists{cls}{..\doclass..}{..}`` 形（0812.0615 lang10.tex
    实证）：命中点在 arg2 内（depth 1），先扫到 arg2 闭 ``}``（depth→0），
    再吞同构造紧随的 ``{..}``/``[..]`` 实参——缝落整个条件构造之后，
    任臂执行 prologue 都在真声明后；若停在 arg2 闭 ``}``，注入物会被
    当 arg3 扫走。空白跨行可吞；空行（``\par`` 边界）截断实参扫描。
    """
    n = len(vis)
    i, d = start, depth
    while i < n and d > 0:
        c = vis[i]
        if c == "\\":
            i += 2
            continue
        if c == "{":
            d += 1
        elif c == "}":
            d -= 1
        i += 1
    while (arg := _trailing_arg(vis, i)) is not None:
        i = group_end(vis, arg)
    return i


#: ``\newcommand``/``\def`` 族定义命令探测——``_def_body_spans`` 单源走查，
#: ``_macro_proxy_seams`` 复用其扫描结果不再重跑。
_DEF_CMD_RX = re.compile(
    r"\\(?:(?:new|renew|provide)command|DeclareRobustCommand|def|gdef|edef|xdef)"
    r"\*?\s*\{?\\([a-zA-Z@]+)\}?"
)


def _def_body_spans(vis: str) -> list[tuple[str, int, int, int]]:
    r"""``\newcommand``/``\def`` 族定义点表 ``(宏名, \name 定义位, 体 ``{`` 位, 体尾)``。

    宏体内的 ``\documentclass`` 不是真声明点（归 ``_macro_proxy_seams``
    的调用点缝管）——nested-seam 判定借本表排除；``_macro_proxy_seams``
    直接消费本表（宏名/``\name`` token 位随元组携带），同一 def-site
    走查不再二次跑。
    """
    spans: list[tuple[str, int, int, int]] = []
    for m in _DEF_CMD_RX.finditer(vis):
        brace = vis.find("{", m.end())
        if brace < 0:
            continue
        spans.append((m.group(1), m.start(1) - 1, brace, group_end(vis, brace)))
    return spans


def find_docclass_ends(tex: str) -> list[tuple[int, int, str]]:
    r"""全部可用的 `\documentclass`/`\documentstyle` 注入缝 `(pos, lineno, cmd)`。

    在 visible_tex 等长遮盖视图上扫（注释/verbatim 命中天然消失，offset
    与原文对齐）。brace depth>0 的命中分两路：宏体（`\newcommand{\ds}{\
    \documentstyle}` 类，1706.07796）仍非真声明点——跳过，零缝时归
    ``_macro_proxy_seams``；可执行组/条件实参内命中（`\IfFileExists{cls}
    {..\doclass..}{..}` 形，B5a）缝取**整个构造的 depth-0 收尾**——
    ``_nested_construct_end`` 扫到最外包容组闭 ``}`` 再吞同构造尾随
    实参，prologue 落构造后任臂皆在真声明后。

    条件分支内命中**不判死活**（`\ifpdf A \else B \fi` 双 docclass 是
    sigma/jhep 系标准形态；`\ifemulate`/`\ifdefined` 同理）——调用方逐缝
    注入，哪条臂执行哪条臂生效（loop1 A 桶：旧版取首个命中，落死分支
    则注入物整段进死代码 → 中文静默缺失）。
    """
    vis = visible_tex(tex)
    hits: list[tuple[int, int, str]] = []
    seen_pos: set[int] = set()
    def_spans: list[tuple[str, int, int, int]] | None = None
    for m, depth in iter_depth(DOCCLASS_RX, vis):
        if depth == 0:
            close = _docclass_close(vis, m.end())
            if close > 0 and vis[close - 1] in "}]":
                # ``]`` 收尾 = ``{cls}[opts]`` 畸形序吞尾成功（``_docclass_close``
                # 对尾随 ``[opts]`` 组返 ``]`` 后 offset）——同属闭合缝。
                insert, lineno = _seam_after_close(tex, vis, close)
            else:
                # 无 {..} 的裸 \documentclass：退化为行尾注入。
                eol = tex.find("\n", m.end())
                lineno = tex.count("\n", 0, m.start()) + 1
                insert = len(tex) if eol < 0 else eol
        else:
            if def_spans is None:
                def_spans = _def_body_spans(vis)
            if any(b <= m.start() < e for _n, _t, b, e in def_spans):
                continue  # 宏体内声明字样非真声明点——归 proxy 缝
            insert, lineno = _seam_after_close(
                tex, vis, _nested_construct_end(vis, m.end(), depth)
            )
        if insert not in seen_pos:  # 单行 `\if..\else..\fi` 双命中同缝
            seen_pos.add(insert)
            hits.append((insert, lineno, m.group(1)))
    if not hits and def_spans:
        # def_spans 为 None ⇒ vis 上零 docclass token——proxy 扫描必空，直跳
        hits = _macro_proxy_seams(tex, vis, def_spans)
    hits.sort()
    return hits


def _macro_proxy_seams(
    tex: str, vis: str, defs: list[tuple[str, int, int, int]]
) -> list[tuple[int, int, str]]:
    r"""宏包声明形态的回退缝。

    ``\def\doc{...\documentclass{cls}...}`` + 顶层 ``\doc`` 调用 —— 真声明
    藏在宏体内（depth>0 被 ``find_docclass_ends`` 主循环跳过），可编译
    文档会静默零注入（I9）。

    ``defs`` = ``_def_body_spans`` 走查结果——体内含声明命令的宏名收集
    为调用面，顶层（depth 0）调用行行尾即缝；注入物在执行序上位于真
    声明之后。
    """
    proxy: dict[str, str] = {}
    def_sites: set[int] = set()
    for name, tok_pos, brace, body_end in defs:
        dm = DOCCLASS_RX.search(vis, brace, body_end)
        if dm is not None:
            proxy[name] = dm.group(1)
            def_sites.add(tok_pos)  # 定义位的 \name token 不算调用
    if not proxy:
        return []
    names = "|".join(sorted(proxy))
    invoke_re = re.compile(rf"\\(?:{names})(?![a-zA-Z@])")
    hits: list[tuple[int, int, str]] = []
    for m in iter_depth0(invoke_re, vis):
        if m.start() in def_sites:
            continue
        eol = tex.find("\n", m.end())
        insert = len(tex) if eol < 0 else eol
        lineno = tex.count("\n", 0, m.start()) + 1
        hits.append((insert, lineno, proxy.get(m.group(0)[1:], "documentclass")))
    return hits


def find_docclass_end(tex: str) -> tuple[int, int, str] | None:
    r"""首个可用 `\documentclass` 缝（``find_docclass_ends`` 的首元素）。"""
    hits = find_docclass_ends(tex)
    return hits[0] if hits else None


#: 条件净深计数（遮盖视图）：``\if*`` 开臂 / ``\fi`` 闭臂。
_COND_OPEN_RX = re.compile(r"\\if[a-zA-Z@]*")
_COND_CLOSE_RX = re.compile(r"\\fi(?![a-zA-Z@])")
#: ``\newif\iffoo`` 声明位的 ``\if`` token 占开臂名额但不是条件体——
#: 按 ``\newif`` 数回吐（TABLE_FITTING 自带 ``\newif\iftexlate@tablefit``）。
_COND_DECL_RX = re.compile(r"\\newif(?![a-zA-Z@])")


def _conditional_delta(vis: str) -> int:
    r"""遮盖视图条件净深：``\if*`` 开数 − ``\fi`` 闭数 − ``\newif`` 声明数。

    只比对**净深差**——文件自带 ``\ifdef``/``\ifstrempty`` 类宏面（无
    ``\fi`` 配对的 etoolbox 判宏）在双侧等值抵销；遮蔽移位（块落进逐字
    区被抹平 / 缝合扰动揭开活码）才会让差值偏离 ``n×块净深``。
    """
    return (
        len(_COND_OPEN_RX.findall(vis))
        - len(_COND_CLOSE_RX.findall(vis))
        - len(_COND_DECL_RX.findall(vis))
    )


def _balance_or_fallback(tex: str, out: str, block: str, n: int) -> str:
    r"""注入后条件平衡自检：失衡回退 ``\documentclass`` 缝前位 / 文件头。

    注入只追加 ``\n``+块（块内 ``\if/\fi`` 恒成对，净深差应为
    ``n×block_delta``）；失衡 ⇒ 缝位咬穿逐字遮蔽或条件臂错位
    （1107.0304 ``Incomplete \iffalse`` 全稿吞没类）。回退重插首个
    ``\documentclass`` **前**（缝前位不在任何条件/逐字遮蔽内）；块内
    ``\usepackage`` 在该位是内核级硬错（latex.ltx ``\usepackage before
    \documentclass``），回退副本先降为 ``\RequirePackage``（前导区语义
    等价、且是唯一的 docclass 前置安全装载器）。无 docclass 落文件头。
    """
    expect = _conditional_delta(visible_tex(tex)) + n * _conditional_delta(
        visible_tex(block)
    )
    if _conditional_delta(visible_tex(out)) == expect:
        return out
    safe_block = block.replace("\\usepackage", "\\RequirePackage")
    m = DOCCLASS_RX.search(visible_tex(tex))
    pos = m.start() if m else 0
    return tex[:pos] + "\n" + safe_block + "\n" + tex[pos:]


def _splice_after_seams(tex: str, hits: list[tuple[int, int, str]], block: str) -> str:
    r"""逐缝 ``\n``+block 回填——pos 为原 tex 绝对 offset，顺序累加 delta。"""
    out = tex
    delta = 0
    for pos, _ln, _c in hits:
        out = out[: pos + delta] + "\n" + block + out[pos + delta :]
        delta += len(block) + 1
    if hits:
        out = _balance_or_fallback(tex, out, block, len(hits))
    return out


def _sentinel_wrap(
    block: str, sentinel: str, *, what: str, why: str = "multi-seam"
) -> str:
    r"""多缝/多锚幂等哨兵包裹：活臂执行立 ``\def\<sentinel>{1}`` 哨，余点整块跳过。

    ``\fi`` 配对安全前提：被包块内 ``\if`` 全成对（skip 计数平衡）。
    docclass 多缝（``_splice_after_seams`` 侧消费方）与多 bd 锚
    （``_splice_before_document``）共用本助手——``what`` 为注释面
    标签、``why`` 为幂等语境缀（multi-seam/multi-bd），字节格式单源。
    """
    return (
        f"% texlate: {what} ({why} idempotent)\n"
        f"\\ifdefined\\{sentinel}\\else\n"
        f"\\def\\{sentinel}{{1}}%\n" + block + "\\fi\n"
    )


def _splice_before_document(
    tex: str, block: str, *, after: int = 0, sentinel: str = "TeXlateMathFB"
) -> str:
    r"""``\begin{document}`` 前逐点 ``\n``+block 回填——preamble 尾锚。

    多 bd 形态（条件双 bd/坏档）逐点注入 + 幂等哨兵（``_sentinel_wrap``
    单源包裹，与 docclass 多缝同款：活臂执行立哨，余点整块跳过）；
    右向左回填免 offset 簿记。
    只认 ``after``（首个 docclass 缝位）之后的 bd——先于缝位的 bd 不是
    preamble 尾，锚在那里会把声明放到 ``\documentclass`` 行之前。
    bd 命中取 ``iter_depth0``：``\def\bd{\begin{document}}``/``\newcommand``
    宏体内的 bd 字样不是真文档起点——裸 finditer 把注入块楔进 ``\def\bd{``
    与 ``\begin{document}}`` 之间，宏体吞含 ``#1`` 的定义即 "Illegal
    parameter number in definition of \bd"（hep-th/0307203、
    hep-th/9910011、0905.0876 实案）；depth>0 一律不算锚点。
    无合格 bd 则原样返回（调用方负责退化路径）。
    """
    positions = sorted(
        {
            m.start()
            for m in iter_depth0(BEGIN_DOC_RX, visible_tex(tex))
            if m.start() > after
        }
    )
    if not positions:
        return tex
    if len(positions) > 1:
        block = _sentinel_wrap(block, sentinel, what=sentinel, why="multi-bd")
    out = tex
    for pos in reversed(positions):
        out = out[:pos] + "\n" + block + out[pos:]
    return _balance_or_fallback(tex, out, block, len(positions))
