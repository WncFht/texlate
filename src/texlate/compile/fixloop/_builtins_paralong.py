r"""_builtins_paralong — "Paragraph ended before \X was complete" 修复原语。

签名面: 非 ``\long`` 宏的参数扫描在 arg 内部撞上 ``\par`` (空行) →
扫描中止, 宏调用+已扫前缀整段丢弃 → 内容丢失+下游级联错。
payload=None (syntax 类不产 payload), dedup 键 ``{rule}:{None}`` 全族
共用一格 —— transform 必须单次应用把日志里**所有** para_ended 肇事宏
一并处理 (多宏共享格否则后宏永烧不到)。

双臂 (para-census #145 普查定形):
  - def-site 补 ``\long``: fileset (.tex/.sty/.cls/.def/.clo/.cfg) 内
    ``\def\X``/``\gdef``/``\edef``/``\xdef`` 无 ``\long`` 前缀 → 前插;
    starred ``\newcommand*``/``\renewcommand*``/``\providecommand*``/
    ``\DeclareRobustCommand*`` 去星 (unstarred = \long)。用户宏尾
    (\rf/\Reff 族) 与 shipped-cls 内部宏 (\@argswap/\add@AUCO@grp 族)
    都走这条, 零表。
  - ``\par``-strip wrap: 内核/包内非 ``\long`` 宏不在 fileset →
    ``\begin{document}`` 前注入 ``\ifdefined`` 闸 + ``\let`` 快照 +
    ``\long\def`` wrapper, 逐参经 ``\TL@pl@strip`` 剥掉顶层 ``\par``
    再按原签名转发给快照原宏。**裸 ``\let``-wrap 无效** —— 转发
    ``{#n}`` 里若仍含 ``\par``, 原宏的非 ``\long`` 重扫在别名名下原样
    复炸 (runaway 检不管括号深度, 实测 ``Paragraph ended before
    \aliasorig``); 语义上也只该剥顶层 ``\par`` —— 肇事空行本即拼接
    伪影, 参数不该有段断。strip 是 ``\par``-定界递归, 展开式纯 token
    手术, 与原宏体版本无关 (免 body-copy 的版本漂移险)。嵌套组内
    ``\par`` 剥不到 —— 已知残面, 语料肇事均为顶层。

注入位双缝: aux 读在 ``\begin{document}`` 执行内 AtBeginDocument 钩之前 →
钩位注不了, 必须 preamble 落位; 包装载期 ``\let`` 再绑 (natbib
``\@citex`` → ``\NAT@citexnum``) 在 usepackage 期完成 → 缝前注入时序
合法。
  - preamble 调用点缝 (paraearly): wrap 表宏在 ``\begin{document}``
    **之前**被调用 (``\author``/``\institute`` 族 frontmatter 面,
    2112.00059/2112.00071 实证) 时 begindoc 缝到的太晚 → 落块改注
    在最早 preamble 调用点的行首前 (调用点 = 遮盖视图 depth-0 live
    命中且紧邻前缀非定义者尾缀; 装载期 .sty/.cls 件内调用恒属
    preamble; 全 fileset 无 ``\begin{document}`` 的 2.09 稿取首个
    live 命中)。``\ifdefined`` 闸使早落位天然安全。
  - ``\begin{document}`` 缝 (原径): 无 preamble 调用点的宏不变 ——
    aux 扫描器触发面无源码调用点, body 调用也统一由 preamble 末位
    落块覆盖 (比逐调用点更靠前)。

拒收面: 暂存/级联宏名单 (\bbl@temp* babel kv 暂存 = babel_opt 级联,
\@tempa*/\@oparg 载体外的 amstex 暂存, \next/\do/\reserved@* 迭代暂存)
—— 修上游错才是根修, 暂存名重定义瞬时被覆写。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop._builtins_common import (
    _AT_LETTER_POST,
    _AT_LETTER_PRE,
    _fixloop_log,
    _live_matches,
    _map_tex_files,
)
from texlate.textutil import iter_depth0, mask_tex

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.compile.fixloop.engine import Engine, LoopCtx


#: 错误头/日志里的肇事宏名 —— ``Paragraph ended before \X was complete``
#: (file-line 形 ``f.tex:N: Paragraph ended before \X was complete.`` 同面)。
_PARA_ENDED_RE = re.compile(r"Paragraph ended before (\\[A-Za-z@]+)")

#: def-site 改写作用域 —— fileset 内可含宏定义的扩展名集合。
_DEF_EXTS = (".tex", ".sty", ".cls", ".def", ".clo", ".cfg")

#: ``\begin{document}`` 锚 —— wrap 注入缝 (aux 读死线) 定位用。
_BEGIN_DOC_RE = re.compile(r"\\begin\s*\{document\}")

#: 装载期件后缀 —— .sty/.cls/.def/.clo/.cfg 经 ``\usepackage``/``\documentclass``
#: 读入, 其内 ``\X`` 调用在执行序上恒属 preamble (无所谓件内 ``\begin{document}``
#: 位置 —— 装载期件根本不会有活的)。
_LOAD_EXTS = (".sty", ".cls", ".def", ".clo", ".cfg")

#: ``\X`` 紧邻前缀的「定义者」尾缀判 —— ``\def\X``/``\let\X``/``\newcommand\X``
#: 类是**定义点**不是调用点, 不能当 seam 锚。``{\X}``/``{name}`` 形 brace
#: 深度 >0 已被 ``iter_depth0`` 排除, 此表只兜 depth-0 无括号形; ``*def``/
#: ``*let`` 尾缀顺带覆盖 ``\gdef``/``\edef``/``\chardef``/``\futurelet`` 族。
#: ``\Z`` 锚 (非 ``$``) —— 须贴死匹配起点, ``\def\n\author`` 不许误判。
_DEF_TAIL_RX = re.compile(
    r"(?:\\(?:long|outer|global|protected)[ \t]*)*"
    r"\\(?:[A-Za-z@]*def|[A-Za-z@]*let|newcommand|renewcommand"
    r"|providecommand|DeclareRobustCommand|DeclareMathOperator|newif)"
    r"[ \t]*(?:\*[ \t]*)?(?:\[[0-9]+\][ \t]*)?\{?[ \t]*\Z"
)

#: wrap 签名表: cs 名 (无反斜杠) → (wrapper 捕获签名, 终级转发模板)。
#: def_sig 逐字作 wrapper 形参 (定界符原样: ``[#1]``/``#1>``/``#1\\``);
#: fwd_sig 是终级 stage 体内 ``\ALIAS`` 后的转发文本 —— 各级剥好的
#: ``{s_n}`` 按序就位, ``#n`` 引用即第 n 个剥净参数, 定界参的花括号
#: 剥壳由下一级无界捕获自动完成 (``{#1}[#2]`` → ``\ALIAS{s1}[s2]``;
#: ``#1>`` → ``\ALIAS s1>``)。签名逐条对上游实档核过 (para-census
#: definer-site map; nameref.sty:201 / latex.ltx:17351 / natbib.sty:507 /
#: latex.ltx:153 / amsthm.sty:43 / latex.ltx:12903 / hyperref.sty:5015 /
#: nameref.sty:310-311 当前已 \long 但旧档非 \long, shipped 旧拷贝仍发
#: → 表项保留)。
_WRAP_TABLE: dict[str, tuple[str, str]] = {
    "NR@gettitle": ("#1", "{#1}"),
    "addcontentsline": ("#1#2#3", "{#1}{#2}{#3}"),
    "make@footnotetext": ("#1", "{#1}"),
    "pacs": ("#1", "{#1}"),
    "institute": ("#1", "{#1}"),
    "author": ("#1", "{#1}"),
    "address": ("#1", "{#1}"),
    "@citex": ("[#1][#2]#3", "[#1][#2]{#3}"),
    "NAT@@citetp": ("[#1]", "[#1]"),  # natbib.sty:690 opt-arg 入口 → \@citex
    "@doendnote": ("#1#2", "{#1}{#2}"),  # revtex4.cls:5773 endnote 路
    "@providesfile": ("#1[#2]", "{#1}[#2]"),
    "@oparg": ("#1[#2]", "{#1}[#2]"),
    "@sect": ("#1#2#3#4#5#6[#7]#8", "{#1}{#2}{#3}{#4}{#5}{#6}[#7]{#8}"),
    "select@group": ("#1#2#3#4", "{#1}{#2}{#3}{#4}"),
    "@fourthoffive": ("#1#2#3#4#5", "{#1}{#2}{#3}{#4}{#5}"),
    "@fifthoffive": ("#1#2#3#4#5", "{#1}{#2}{#3}{#4}{#5}"),
    "hyper@readexternallink": ("#1\\\\#2#3#4", "#1\\\\{#2}{#3}{#4}"),
    "blx@citeargs@iii": ("#1#2", "{#1}{#2}"),
    "strip@prefix": ("#1>", "#1>"),
    "@argswap": ("#1#2", "{#1}{#2}"),
    "setlength": ("#1#2", "{#1}{#2}"),
    "@iinput": ("#1", "{#1}"),
    "mathbfit": ("#1", "{#1}"),
    "mathbfss": ("#1", "{#1}"),
    "org@markboth": ("#1#2", "{#1}{#2}"),
    # ── institutesig wave-7 普查 (117 cells/31 cs → 19 表外格) —— 逐条上游实档核签 ──
    "abstract": (
        "#1",
        "{#1}",
    ),  # aa.cls:271 \let\abstract=\aaabstract 别名 (无 \def\abstract 定义点)
    "@titleone": ("#1", "{#1}"),  # mn2e.cls:1197
    "@affil@match": ("#1#2#3#4#5", "{#1}{#2}{#3}{#4}{#5}"),  # revtex4-2.cls:2317
    "add@AUCO@grp": ("#1#2#3#4", "{#1}{#2}{#3}{#4}"),  # revtex4-2.cls:2184
    "@sect@ltx": (
        "#1#2#3#4#5#6[#7]#8",
        "{#1}{#2}{#3}{#4}{#5}{#6}[#7]{#8}",
    ),  # ltxutil.sty:810 / revtex4-1:794 / revtex4-2:815
    "MT@is@char": (
        '#1\\CHAR"#2#3#4\\relax',
        '#1\\CHAR"{#2}{#3}#4\\relax',
    ),  # microtype.sty:1819
    "verbatim@start": ("#1", "{#1}"),  # verbatim.sty:107
    "ltx@def@footproc": (
        "#1[#2]",
        "{#1}[#2]",
    ),  # ltxutil.sty:455 / revtex4-1:439 / revtex4-2:460
    "@float@HH": ("#1[H]", "{#1}[H]"),  # float.sty:78
    "TP@textblock": ("[#1,#2](#3,#4)", "[#1,#2](#3,#4)"),  # textpos.sty:253
    "pgffor@var@add": (
        "#1#2\\pgffor@stop",
        "{#1}#2\\pgffor@stop",
    ),  # pgffor.code.tex:75
    "caption@prepareanchor": ("#1#2", "{#1}{#2}"),  # caption*.sty:319 \newcommand*[2]
    # pictex 非 \long \put (现行档 pictexwd.tex:2310 已 \long, 老档非; 签名
    # 含字面 " at " 与空格定界 —— 定界参裸转发, 尾空格是 #4 定界符不可省)。
    "put": ("#1#2 at #3 #4 ", "{#1}#2 at #3 #4 "),
}

#: 暂存/级联宏拒收名单 —— 定义随用随覆写或属上游错级联, wrap 无意义。
_DENY_NAMES: frozenset[str] = frozenset(
    {
        "@tempa",
        "@tempb",
        "@tempc",
        "@tempd",
        "@tempe",
        "@tforloop",
        "next",
        "do",
        "loop",
        "@nil",
        "@nnil",
        "@gobble",
        "@firstofone",
        "@firstoftwo",
        "@secondoftwo",
        "if",
        "else",
        "fi",
        # abraces.sty:172,187 \let-派发暂存 (\abrace@next=\@abrace@is@arg@fully@used@/\relax)
        "abrace@next",
    }
)

#: 拒收前缀族 —— babel kv 暂存 (babel_opt 级联), kernel 寄存器暂存,
#: LaTeX 迭代暂存。
_DENY_PREFIXES = ("bbl@temp", "reserved@", "iter@", "@ene@r", "t@exp@")


def _para_macros(ctx: LoopCtx) -> list[str]:
    r"""err_head → 全日志序扫 ``Paragraph ended before \X`` 肇事宏名 (去重保序)。

    err_head 是本轮 dispatch 的错误 blob (主错或孪生候选), 先扫它锁定
    本轮肇事宏; 全日志兜底收同格其它 para_ended 宏 —— dedup 键
    ``{rule}:None`` 全族共位, 一次应用必须全收。
    """
    out: list[str] = []
    for src in (ctx.err_head or "", _fixloop_log(ctx)):
        for m in _PARA_ENDED_RE.finditer(src):
            name = m.group(1)[1:]
            if name not in out:
                out.append(name)
    return out


def _longize_defs(t: str, name: str) -> tuple[str, int]:
    r"""文本内 ``\X`` 非 ``\long`` 定义点 → 补 ``\long``/去星 → (新文本, 改动数)。

    ``\def``/``\gdef``/``\edef``/``\xdef`` 族: 前缀串 (``\long\outer
    \global\protected`` 任意序) 无 ``\long`` → ``\def`` 前插 ``\long ``;
    已 ``\long`` 跳过。``\newcommand*``/``\renewcommand*``/
    ``\providecommand*``/``\DeclareRobustCommand*`` 星形 → 去星
    (unstarred 本即 \long); 无星不碰。遮盖视图命中, 注释/verbatim 内
    死定义不改写。``\@namedef``/``\csname`` 间接定义面不收。
    """
    esc = re.escape(name)
    edits: list[tuple[int, int, str]] = []
    def_rx = re.compile(
        r"(?P<pre>(?:\\(?:long|outer|global|protected)[ \t]*)*)"
        r"(?P<cmd>\\(?:gdef|edef|xdef|def))"
        r"(?P<tail>[ \t]*\\" + esc + r"(?![A-Za-z@]))"
    )
    for m in _live_matches(def_rx, t):
        if "\\long" in m.group("pre"):
            continue
        edits.append((m.start("cmd"), 0, "\\long "))
    star_rx = re.compile(
        r"(?P<cmd>\\(?:newcommand|renewcommand|providecommand"
        r"|DeclareRobustCommand)[ \t]*)\*[ \t]*"
        r"(?=\{?[ \t]*\\" + esc + r"(?![A-Za-z@]))"
    )
    edits.extend(
        (m.end("cmd"), m.end() - m.end("cmd"), "") for m in _live_matches(star_rx, t)
    )
    if not edits:
        return t, 0
    for pos, ln, rep in sorted(edits, reverse=True):
        t = t[:pos] + rep + t[pos + ln :]
    return t, len(edits)


def _live_begin_pos(t: str, masked: str) -> int | None:
    r"""首个活 ``\begin{document}`` 起点 offset; 遮盖区命中跳过, 无 → None。"""
    for m in iter_depth0(_BEGIN_DOC_RE, masked):
        if masked[m.start() : m.end()] == t[m.start() : m.end()]:
            return m.start()
    return None


def _inject_before_begindoc(ctx: LoopCtx, snippet: str) -> bool:
    r"""主文件首个活 ``\begin{document}`` 行首前注入 snippet (幂等)。

    ``\let``-wrap 专用缝: aux 读/``\@fourthoffive`` 族 aux 扫描器触发面
    在 ``\begin{document}`` 执行内, AtBeginDocument 钩位之后 → 钩注
    够不到, 须 preamble 末位落。无活 ``\begin{document}`` → False。
    """
    main = ctx.main_path()
    if main is None:
        return False
    t = ctx.read(main) or ""
    if snippet in t:
        return False
    bd = _live_begin_pos(t, mask_tex(t))
    if bd is None:
        return False
    pos = t.rfind("\n", 0, bd) + 1
    ctx.write(main, t[:pos] + snippet + "\n" + t[pos:])
    return True


def _depth0_line_start(masked: str, start: int) -> int:
    r"""``start`` 回退到最近的 depth-0 行首。

    ``start`` 自身在 depth 0 (``iter_depth0`` 保证) 但其**行首**可能仍在
    前续行开启的 ``{`` 组内 —— 组内落块会把 ``\def``/``\let`` 锁成局部
    定义, 组闭即失效 (静默死注)。行首→start 段内出现净 ``}`` (扫到 depth
    <0) 即行首在组内 → 再退一行; ``\\`` 双字符跳过不吃配对 (同
    ``iter_depth0`` 走查约定)。
    """
    pos = masked.rfind("\n", 0, start) + 1
    while pos:
        depth = 0
        in_group = False
        i = pos
        while i < start:
            c = masked[i]
            if c == "\\":
                i += 2
                continue
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth < 0:
                    in_group = True
                    break
            i += 1
        if not in_group:
            break
        pos = masked.rfind("\n", 0, pos - 1) + 1
    return pos


def _first_preamble_call(
    name: str, texts: dict[Path, str], main: Path | None, *, has_bd: bool
) -> tuple[Path, int] | None:
    r"""Fileset 内 ``\name`` 最早 preamble 调用点 → (文件, 落块行首 offset)。

    候选 = 遮盖视图 depth-0 live 命中且紧邻前缀非定义者尾缀 (``\def\X``
    类是定义点非调用)。件域分判:
      - 装载期件 (.sty/.cls/.def/.clo/.cfg): 执行序恒在 preamble → 全部
        live 命中候选;
      - .tex: 本件活 ``\begin{document}`` 之前的命中; 该件无 ``\begin{document}``
        时仅当**全 fileset** 都无 (2.09 ``\documentstyle``/plain 稿) 才候选 ——
        否则属 body 调用, ``\begin{document}`` 缝更靠前更划算 (aux 读面同罩)。
    主档候选优先, 余按文件序; 行首经 ``_depth0_line_start`` 校正。
    """
    call_rx = re.compile(r"\\" + re.escape(name) + r"(?![A-Za-z@])")
    ordered = list(texts)
    if main is not None and main in texts:
        ordered.remove(main)
        ordered.insert(0, main)
    for f in ordered:
        t = texts.get(f) or ""
        if not t:
            continue
        masked = mask_tex(t)
        bd = _live_begin_pos(t, masked)
        load_file = f.suffix.lower() in _LOAD_EXTS
        if not load_file and bd is None and has_bd:
            continue
        for m in iter_depth0(call_rx, masked):
            if masked[m.start() : m.end()] != t[m.start() : m.end()]:
                continue
            if not load_file and bd is not None and m.start() >= bd:
                break
            if _DEF_TAIL_RX.search(masked[: m.start()]):
                continue
            return f, _depth0_line_start(masked, m.start())
    return None


def _inject_at(ctx: LoopCtx, path: Path, pos: int, snippet: str) -> bool:
    r"""``path`` 内 ``pos`` (depth-0 行首) 前注入 snippet (幂等)。"""
    t = ctx.read(path) or ""
    if snippet in t:
        return False
    ctx.write(path, t[:pos] + snippet + "\n" + t[pos:])
    return True


def _inject_sites(
    ctx: LoopCtx,
    sites: dict[tuple[Path, int], list[str]],
    table: dict[str, tuple[str, str]],
    texts: dict[Path, str],
) -> list[str]:
    r"""逐 (文件, 行首) 缝位落 wrap 块 → 实际注入宏名表。

    同件多缝按位置倒序注 —— 前位落块不移后位 offset。
    """
    injected: list[str] = []
    per_file: dict[Path, list[tuple[int, list[str]]]] = {}
    for (f, pos), names in sites.items():
        per_file.setdefault(f, []).append((pos, names))
    for f, segs in per_file.items():
        for pos, names in sorted(segs, key=lambda s: s[0], reverse=True):
            block, done = _wrap_block(names, table, texts.get(f) or "")
            if done and _inject_at(ctx, f, pos, block):
                injected.extend(done)
    return injected


def _apply_wraps(
    ctx: LoopCtx,
    wrap_names: list[str],
    table: dict[str, tuple[str, str]],
    notes: list[str],
) -> list[str]:
    r"""Wrap 双缝分发 → 实际注入宏名表。

    preamble 调用点缝优先 (块落最早调用行首前); 无候选者收
    ``\begin{document}`` 缝 (aux 扫描器无源码调用点, body 调用亦由此缝
    更靠前覆盖)。别名指纹 fileset 级查重 —— 跨件重注会把 ``\TL@pl@X``
    重快照到 wrapper 自身, 造自指递归。
    """
    main = ctx.main_path()
    texts = {f: ctx.read(f) or "" for f in ctx.tex_files(_DEF_EXTS)}
    pool = "\n".join(texts.values())
    has_bd = any(_live_begin_pos(t, mask_tex(t)) is not None for t in texts.values())
    sites: dict[tuple[Path, int], list[str]] = {}
    rest: list[str] = []
    for name in wrap_names:
        if "\\TL@pl@" + name in pool:
            continue  # 别名指纹已在 fileset —— 跨件重注会造自指递归
        site = _first_preamble_call(name, texts, main, has_bd=has_bd)
        if site is None:
            rest.append(name)
        else:
            sites.setdefault(site, []).append(name)
    injected = _inject_sites(ctx, sites, table, texts)
    if rest:
        existing = texts.get(main) if main is not None else ""
        block, done = _wrap_block(rest, table, existing or "")
        if done:
            if _inject_before_begindoc(ctx, block):
                injected.extend(done)
            else:
                notes.append("wrap site missing (no live \\begin{document})")
    return injected


#: ``\par``-strip 共享原语 —— 每 wrap 块注入一次。
#: ``\TL@pl@strip{raw}\CONT`` → ``\CONT{raw-sans-toplevel-\par}``:
#: ``\par``-定界递归逐段重拼, ``\ifx`` 哨兵判停 (``\TL@pl@nil`` 自指
#: 宏义独一, 空 #4 时双哨兵相撞即真); ``\long`` 全程 —— 递归级与
#: strip 入口都吃含 ``\par`` 料。哨兵绝不展开 (只作定界符/ifx 操作数)。
#: ``\expandafter\TL@pl@first/\else\TL@pl@second\fi`` 是硬约束 ——
#: CONT 链若含吃无界实参的宏 (``\@citex`` 的 #3 等), 在 ``\ifx`` 真
#: 分支里执行会把挂起的 ``\else`` 当实参吞掉, 残留 else 支二次执行
#: 连锁炸下游 (实测 ``\@fortmp`` runaway); 必须先 ``\expandafter``
#: 出 ``\fi`` 再交控制权。
_STRIP_HELPERS: tuple[str, ...] = (
    "\\long\\def\\TL@pl@strip#1#2{\\TL@pl@stripA{}{#2}#1\\par\\TL@pl@nil}",
    (
        "\\long\\def\\TL@pl@stripA#1#2#3\\par#4\\TL@pl@nil{"
        "\\ifx\\TL@pl@nil#4\\TL@pl@nil\\expandafter\\TL@pl@first"
        "\\else\\expandafter\\TL@pl@second\\fi"
        "{\\TL@pl@fin{#2}{#1#3}}{\\TL@pl@stripA{#1#3}{#2}#4\\TL@pl@nil}}"
    ),
    "\\long\\def\\TL@pl@first#1#2{#1}",
    "\\long\\def\\TL@pl@second#1#2{#2}",
    "\\long\\def\\TL@pl@fin#1#2{#1{#2}}",
    "\\def\\TL@pl@nil{\\TL@pl@nil}",
)


def _wrap_block(
    names: list[str], table: dict[str, tuple[str, str]], existing: str
) -> tuple[str, list[str]]:
    r"""拼 ``\makeatletter`` \par-strip wrap 块 → (snippet, 实际纳入宏名表)。

    每宏 (K 参): ``\ifdefined`` 闸 (宏未定义不造残 wrapper) + ``\let``
    快照 (此时绑定的活义, ``\let`` 间接绑如 ``\@citex``→``\NAT@citexnum``
    快照到目标体) + ``\long`` wrapper 按 def_sig 捕获 → 第 1 参入
    ``\TL@pl@strip``, 续体链 stage ``@s1..@sK`` 逐级剥参 (raw 先行,
    剥净尾随 —— strip 输出 ``{s}`` 追加在续体后), 终级 ``\ALIAS<fwd>``
    把剥净实参按原签名 (含定界符) 送回快照原宏。别名 ``TL@pl@<name>``
    已在件 → 跳过 (跨轮幂等)。
    """
    lines: list[str] = []
    done: list[str] = []
    helpers = False
    for name in names:
        spec = table.get(name)
        if spec is None:
            continue
        alias = "TL@pl@" + name
        if "\\" + alias in existing:
            continue
        sig, fwd = spec
        k = len(re.findall(r"#\d", sig))
        if k < 1:
            continue
        if not helpers:
            lines += _STRIP_HELPERS
            helpers = True
        stage = "TL@pl@" + name + "@s"
        # stage 序号走罗马数字 —— cs 名只收字母, 数字会断名成 \…@s+"1"
        rom = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x")
        cont = (
            "\\"
            + stage
            + rom[0]
            + "".join("{#" + str(i) + "}" for i in range(2, k + 1))
        )
        lines.append(
            "\\ifdefined\\"
            + name
            + "\\let\\"
            + alias
            + "\\"
            + name
            + "\\long\\def\\"
            + name
            + sig
            + "{\\TL@pl@strip{#1}{"
            + cont
            + "}}"
        )
        params = "".join("#" + str(i) for i in range(1, k + 1))
        for i in range(1, k):
            cont = (
                "\\"
                + stage
                + rom[i]
                + "".join("{#" + str(j) + "}" for j in range(2, k - i + 1))
                + "".join("{#" + str(j) + "}" for j in range(k - i + 1, k + 1))
            )
            lines.append(
                "\\long\\def\\"
                + stage
                + rom[i - 1]
                + params
                + "{\\TL@pl@strip{#1}{"
                + cont
                + "}}"
            )
        lines.append(
            "\\long\\def\\"
            + stage
            + rom[k - 1]
            + params
            + "{\\"
            + alias
            + fwd
            + "}\\fi"
        )
        done.append(name)
    if not lines:
        return "", done
    block = "\n".join(
        [
            "% fixloop: para_longize \\par-strip wrap",
            _AT_LETTER_PRE,
            *lines,
            _AT_LETTER_POST,
        ]
    )
    return block, done


def _fix_one(
    ctx: LoopCtx,
    name: str,
    table: dict[str, tuple[str, str]],
    deny: frozenset[str],
    wrap_names: list[str],
) -> tuple[int, str | None]:
    r"""单宏双臂: 拒收面短路 → fileset def-site 补 ``\long`` → 表内宏备 wrap。

    返回 (def-site 改动数, note)。表内宏一律入 wrap_names —— def-site
    改到的是 fileset 死定义, 与运行时真定义同名不同体时 wrap 仍兜底;
    表外且无定义点 → note 记 decline (LLM 手留面)。
    """
    if name in deny or name.startswith(_DENY_PREFIXES):
        return 0, f"\\{name} denied(scratch/cascade)"
    n = _map_tex_files(ctx, _DEF_EXTS, lambda t, nm=name: _longize_defs(t, nm))
    note = f"\\{name} def-site x{n}" if n else None
    if name in table:
        wrap_names.append(name)
    elif not n:
        note = f"\\{name} no def-site, not in wrap table"
    return n, note


def para_longize(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""para_ended 族修复: def-site ``\long`` + 内核/包内宏 \par-strip wrap。

    日志全肇事宏一趟收 (dedup ``{rule}:None`` 共位); 逐宏先 fileset
    def-site 补 ``\long``, 表内宏再备 wrap 注入 ``\begin{document}`` 前
    (双保险: fileset 死定义与运行时真定义不同名时 wrap 仍兜底)。
    ``params.wrap_table`` 同形条目扩表, ``params.deny`` 扩拒收名单,
    ``params.max_macros`` 上限 (默认 8)。
    """
    del eng, payload
    head = ctx.err_head or ""
    log = _fixloop_log(ctx)
    if "Paragraph ended before" not in head and "Paragraph ended before" not in log:
        return False, "no para_ended signature"
    macros = _para_macros(ctx)
    if not macros:
        return False, "para_ended: no letter-name macro extracted"
    table = dict(_WRAP_TABLE)
    table.update(params.get("wrap_table") or {})
    deny = _DENY_NAMES | frozenset(params.get("deny") or ())
    cap = int(params.get("max_macros") or 8)
    notes: list[str] = []
    n_def = 0
    wrap_names: list[str] = []
    for name in macros[:cap]:
        n, note = _fix_one(ctx, name, table, deny, wrap_names)
        n_def += n
        if note:
            notes.append(note)
    injected: list[str] = []
    if wrap_names:
        injected = _apply_wraps(ctx, wrap_names, table, notes)
        if injected:
            notes.append(f"wrap x{len(injected)}: {','.join(injected)}")
    applied = bool(n_def or injected)
    if not applied and not notes:
        notes.append("nothing actionable")
    return applied, "; ".join(notes)
