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

注入位: aux 读在 ``\begin{document}`` 执行内 AtBeginDocument 钩之前 →
钩位注不了, 必须 preamble 落位; 包装载期 ``\let`` 再绑 (natbib
``\@citex`` → ``\NAT@citexnum``) 在 usepackage 期完成 → 缝前注入时序
合法。

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
    from texlate.compile.fixloop.engine import Engine, LoopCtx


#: 错误头/日志里的肇事宏名 —— ``Paragraph ended before \X was complete``
#: (file-line 形 ``f.tex:N: Paragraph ended before \X was complete.`` 同面)。
_PARA_ENDED_RE = re.compile(r"Paragraph ended before (\\[A-Za-z@]+)")

#: def-site 改写作用域 —— fileset 内可含宏定义的扩展名集合。
_DEF_EXTS = (".tex", ".sty", ".cls", ".def", ".clo", ".cfg")

#: ``\begin{document}`` 锚 —— wrap 注入缝 (aux 读死线) 定位用。
_BEGIN_DOC_RE = re.compile(r"\\begin\s*\{document\}")

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
    masked = mask_tex(t)
    for m in iter_depth0(_BEGIN_DOC_RE, masked):
        if masked[m.start() : m.end()] != t[m.start() : m.end()]:
            continue  # 遮盖区命中 —— 注释/verbatim 假 \begin{document}
        pos = t.rfind("\n", 0, m.start()) + 1
        ctx.write(main, t[:pos] + snippet + "\n" + t[pos:])
        return True
    return False


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
        main = ctx.main_path()
        existing = (ctx.read(main) or "") if main is not None else ""
        block, todo = _wrap_block(wrap_names, table, existing)
        if todo:
            if _inject_before_begindoc(ctx, block):
                injected = todo
                notes.append(f"wrap x{len(todo)}: {','.join(todo)}")
            else:
                notes.append("wrap site missing (no live \\begin{document})")
    applied = bool(n_def or injected)
    if not applied and not notes:
        notes.append("nothing actionable")
    return applied, "; ".join(notes)
