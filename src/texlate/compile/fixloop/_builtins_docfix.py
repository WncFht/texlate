r"""_builtins_docfix — 文档结构/定义面打靶修复原语 (_builtins_csfix 再拆叶)。

``pdfstring_cs_disarm``: `` `\cs `` pdfstring 字母常量扫描炸 → 书签域空降格;
``if_phantom_protect``: phantom ``Incomplete \if`` → 前稿 cs 族 ``\protected``
重定义; ``premature_cs_guard``: ``Missing \begin{document}`` @件装载 → 供方
包前置; ``spacefactor_atdef_wrap``: doc-latent @-def 站 exact-restore 包裹;
``cs_delim_tail_fix``: ``\def\X<lit>`` 字面尾译文蚀除 → 逐站补回。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from texlate.compile._seams import find_docclass_ends
from texlate.compile.fixloop._builtins_common import (
    _AT_LETTER_POST,
    _AT_LETTER_PRE,
    _LOAD_SITE_RE,
    _fixloop_log,
    _inject_after_docclass,
    _live_matches,
    _load_elems,
)
from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from texlate.compile.fixloop.engine import Engine, LoopCtx


# ═══ pdfstring 字母常量扫描肇事 cs 空降格 (W165, 2607.10569) ═══

#: ``Improper alphabetic constant`` 行后紧随的 ``<to be read again>``
#: 展示行给出肇事 token——pdfstring/书签域 `` `\cs `` 字母常量扫描只炸
#: 多字符 cs (`` `\x `` 单字符是合法字母常量形, TeX 不报)。
_ALPHA_BAD_CS_RE = re.compile(
    r"Improper alphabetic constant\.\s*\n<to be read again>\s*\n? *(\\[A-Za-z@]+)"
)


def pdfstring_cs_disarm(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""`` `\cs `` pdfstring 字母常量扫描炸 → 肇事 cs 书签域 ``\def`` 空降格。

    触发面: ``$\\times$``/``$\\pdo$`` 类数学进 ``\title``/``\section``/
    ``\author`` 等 moving-arg——hyperref ``\pdfstringdef`` 展开书签时
    `` `\cs `` 扫描撞多字符 cs + intcalc 级联 (acmart+hyperref+xelatex
    上游脆面, 与类无关; tmp/lane-pdo 最小复现 ``$\times$`` in ``\title``)。
    上游文档化逃生舱 ``\pdfstringdefDisableCommands`` 只动书签域——
    正文排版零接触, 比 ``\texorpdfstring`` 逐处包源干净一个量级;
    ``\def\cs{}`` 空降格顺带消掉 "removing `\cs'" 警告 (cs 在展开期
    已消失)。注入走 docclass 缝+``\ifdefined`` 双闸: hyperref 缺席稿
    整件死文本不炸。
    """
    del eng, payload, params
    blob = (ctx.err_head or "") + "\n" + _fixloop_log(ctx)
    names = sorted(
        {
            n
            for n in _ALPHA_BAD_CS_RE.findall(blob)
            if len(n) > 2  # noqa: PLR2004 - 2 = 反斜杠+单字符合法形 (\x) 滤界
        }
    )
    if not names:
        return False, "no multi-char cs behind Improper alphabetic constant"
    main = ctx.main_path()
    if main is None:
        return False, "no main file"
    t = ctx.read(main) or ""
    todo = [n for n in names if f"\\def{n}{{}}" not in t]
    if not todo:
        return False, "offenders already disarmed"
    defs = "".join(f"\\def{n}{{}}" for n in todo)
    snippet = (
        "\\ifdefined\\pdfstringdefDisableCommands\n"
        f"  \\pdfstringdefDisableCommands{{{defs}}}\n"
        "\\fi"
    )
    if not _inject_after_docclass(ctx, snippet):
        return False, "docclass seam injection failed"
    return True, f"pdfstring-disarm {', '.join(todo)}"


# ═══ phantom Incomplete \if — 脆弱前稿 cs 族 eTeX \protected 重定义 (B05 姊妹臂) ═══

#: 展开态 phantom 链的宿主面: frontmatter/moving-arg 里常被 ``\edef``/
#: ``\xdef``/``\MakeUppercase``/``\pdfstringdef`` 展开的 cs——``\footnote``/
#: ``\thanks`` (amsproc ``\shortauthors`` → ``\markboth`` edef 实证) +
#: 2.09 字体声明 ``\bf\it\rm\sf\tt\sc\sl`` (myectaart ``\xdef\@argi{#1}``
#: 实证)。保护后其 ``\newif``-setter 替换体里的 ``\if@X\iffalse`` 不再被
#: 执行——未定义名经 ``\ifdefined`` 闸跳过, 不造新坏定义。
_IFPROT_FAMILY: tuple[str, ...] = (
    "footnote",
    "thanks",
    "bf",
    "it",
    "rm",
    "sf",
    "tt",
    "sc",
    "sl",
)

#: 字面扫描器已跑过的凭据: ``unclosed_if_close`` (order 196) 的 run_tool
#: note 固定带 ``ifclose:`` 判词 (``noop``/``injected`` 皆证"本轮已查字面
#: 平衡")。该凭据缺席 = 扫描器 cond-skip (python3 缺位) 或 order 未达——
#: 字面亏格可能悬着, 本规则的 ``\protected`` 域不含它, 保守不收。
_IFPROT_SCANNER_RULE = "unclosed_if_close"


def if_phantom_protect(  # noqa: PLR0911 - 逐门 decline 即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""Phantom ``Incomplete \if`` → 脆弱前稿 cs 族 ``\protected`` let-wrap 重定义。

    phantom 机制: ``\let\if@X\iffalse`` 形 ``\newif``-setter 的替换体含活
    conditional——``\edef``/``\xdef`` 展开扫描里 ``\let`` 惰性但 ``\if@X``
    (=\iffalse) 执行 → 假 open 吞 token 到 EOF。源件字面平衡 → 196 号
    字面扫描器 noop (applied 烧 dedup 位后下轮才轮到本规则)。eTeX
    ``\protected`` 属性钉在 cs 自身, 不受 ``\let\protect\relax`` 剥除影响
    (``\DeclareRobustCommand`` 的死穴) → 被护 cs 在 edef 扫描内整体带过,
    setter 链根本走不到。正文体正常展开域里 wrapper 逐跳还原旧义, 语义
    零变化 (min8 ``\protected\def\footnote`` / t2 ``\bf`` 双臂已实证出 PDF)。

    注入 ``\AtBeginDocument`` 块 (docclass 缝): 全 preamble+包重定义
    (hyperref 改 ``\footnote`` 等) 跑完才护, 不被反超; ``\maketitle`` 内
    edef 触发时保护已就位。逐 cs ``\ifdefined`` 闸。
    """
    del eng, payload
    fam = tuple(str(c).lstrip("\\") for c in (params.get("cs") or _IFPROT_FAMILY))
    if not fam:
        return False, "empty cs family"
    seen = None
    for a in ctx.actions:
        if a.get("rule") == _IFPROT_SCANNER_RULE and "ifclose:" in str(a.get("detail")):
            seen = str(a.get("detail"))  # 最新一轮判词为准
    if seen is None:
        return False, "literal if-scanner verdict not on ledger — abstain"
    m = re.search(r"phantom=(\d+)", seen)
    if m is not None and int(m.group(1)) > 0:
        # 跳读形嫌疑在场 (\let operand/名位/def 参位内 \if-token + 活条件
        # 帧) —— \protected 域不含此机制, 注了修不到 → abstain。
        return (
            False,
            f"skip-phantom suspects on ledger (phantom={m.group(1)}) — abstain",
        )
    main = ctx.main_path()
    if main is None:
        return False, "no main file"
    # 退文件头 = cls 加载前, \AtBeginDocument 未定义 → 必须有 docclass 缝
    if not find_docclass_ends(ctx.read(main) or ""):
        return False, "no docclass seam"
    lines = "".join(
        f"\\ifdefined\\{n}\\let\\TXLorig{n}\\{n}"
        f"\\protected\\def\\{n}{{\\TXLorig{n}}}\\fi\n"
        for n in fam
    )
    snippet = (
        "% fixloop: phantom Incomplete \\if — \\protected frontmatter cs\n"
        "\\AtBeginDocument{%\n" + lines + "}"
    )
    if not _inject_after_docclass(ctx, snippet):
        return False, "protected re-defs already injected"
    return True, f"protected {len(fam)} frontmatter cs ({', '.join(fam)})"


# ═══ premature provider-cs: Missing \begin{document} @件装载补供格 (2009.11053) ═══

#: file:line 形 ``Missing \begin{document}`` —— ``path/<file>.<ext>:N:``
#: 前缀给出肇事执行文件 (随源 .sty 常见), ``l.N`` 上下文行给出肇事 cs。
_MBD_ERR_RE = re.compile(
    r"^[ \t]*\S*?([\w.+-]+)\.(sty|cls|tex|def|clo):\d+:"
    r"\s*LaTeX Error:\s*Missing \\begin\{document\}",
    re.MULTILINE,
)
#: ``l.N`` 上下文行 —— TeX 行内截到炸点, 最后一个 cs 即肇事者。
_L_CTX_LINE_RE = re.compile(r"(?m)^l\.\d+[^\n]*")
_L_CTX_CS_RE = re.compile(r"\\([A-Za-z@]+)")

#: 肇事 cs → 供方包 (``params.cs_pkg`` 可扩) —— 供方先装载即真 def
#: 就位; gobble/空 polyfill 会静默吞掉计数器重编号语义, 只收真实供方。
_PREMATURE_CS_PKG: dict[str, str] = {
    # 2009.11053: mystyle.sty:33 \numberwithin —— amsmath 在 ms.tex:48
    # 逗号列才装, 供方晚于消费方 → 前置到 \usepackage{mystyle} 前。
    "numberwithin": "amsmath",
}


def _mbd_pairs(blob: str) -> list[tuple[str, str, str]]:
    r"""``Missing \begin{document}`` 行与 ``l.N`` 上下文配对 → [(肇事茎, 扩展名, cs)]。

    错误行后首个 ``l.N`` 行即本错上下文 (TeX 序: 错误行→help→l.行);
    行内最后一个 cs 是炸点肇事者 (左到右执行序)。
    """
    out = []
    for em in _MBD_ERR_RE.finditer(blob):
        lm = _L_CTX_LINE_RE.search(blob, em.end())
        if lm is None:
            continue
        css = _L_CTX_CS_RE.findall(lm.group(0))
        if not css:
            continue
        out.append((em.group(1), em.group(2), css[-1]))
    return out


def premature_cs_guard(  # noqa: C901, PLR0912, PLR0915 - 双臂逐站分派 + seen 幂等, 逐门 decline 即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Missing \begin{document}`` @件装载 → 供方包前置到消费方装载点。

    触发面: 随源 .sty 在装载期调 ``\numberwithin`` 类排版 cs, 而供方包
    (amsmath) 由更靠后的 ``\usepackage`` 行才装 —— kernel 对 preamble
    期排版动作报 ``Missing \begin{document}`` (级联签, syntax 类)。
    修 = 供方 ``\usepackage`` 前置到肇事 sty 的每个 live 用户件装载点
    之前 (供方先跑, 消费方整件覆盖, 真 def 语义无损 —— 非 gobble);
    同文件内已先装供方的站跳过 (含上轮自注行, 天然幂等)。肇事文件是
    .tex (main/``\input`` 件) 无 usepackage 锚点 → docclass 缝顶补供方
    (先于一切 preamble 行); 肇事 ``.cls``/``.def``/``.clo`` 系 cls/包
    内传递装载, 缝位对 cls 执行期鞭长莫及 → abstain 交下位。
    """
    del payload
    table = dict(_PREMATURE_CS_PKG)
    table.update(params.get("cs_pkg") or {})
    stem_provs: dict[str, set[str]] = {}
    seam_provs: set[str] = set()
    blob = (ctx.err_head or "") + "\n" + _fixloop_log(ctx)
    for stem, ext, cs in _mbd_pairs(blob):
        prov = table.get(cs)
        if prov is None:
            continue  # 表外肇事 cs —— 供方不可考, 不收
        if ext == "tex":
            seam_provs.add(prov)
        elif ext == "sty":
            stem_provs.setdefault(stem.lower(), set()).add(prov)
        # cls/def/clo 系传递装载无用户件锚点 —— abstain
    if not stem_provs and not seam_provs:
        return False, "no premature-cs pair in Missing-\\begin{document} error"

    done: list[str] = []
    n_sites = 0
    if stem_provs:
        for f in ctx.tex_files((".tex", ".sty", ".cls")):
            t = ctx.read(f)
            if not t:
                continue
            seen: set[str] = set()
            out: list[str] = []
            prev = 0
            for m in _live_matches(_LOAD_SITE_RE, t):  # 死区装载点不锚
                elems = _load_elems(m)
                provs = sorted(
                    {
                        p
                        for stem, ps in stem_provs.items()
                        if stem in elems
                        for p in ps
                        if p not in seen
                    }
                )
                seen.update(elems)  # 本文件先装供方 → 后站免前置 (幂等)
                if not provs:
                    continue
                ins = "".join(
                    f"\\usepackage{{{p}}} % fixloop: premature provider\n"
                    for p in provs
                )
                out.append(t[prev : m.start()])
                out.append(ins)
                prev = m.start()
                seen.update(provs)
                n_sites += 1
            if out:
                out.append(t[prev:])
                ctx.write(f, "".join(out))
    if n_sites:
        done.append(f"provider prepend at {n_sites} load site(s)")

    if seam_provs:
        main = ctx.main_path()
        main_t = (ctx.read(main) or "") if main is not None else ""
        loaded = {
            e
            for m in _live_matches(_LOAD_SITE_RE, main_t)
            for e in _load_elems(m)
        }
        todo = sorted(p for p in seam_provs if p not in loaded)
        if todo and _inject_after_docclass(
            ctx,
            "\n".join(
                f"\\RequirePackage{{{p}}} % fixloop: premature provider" for p in todo
            ),
        ):
            done.append(f"docclass-seam provider {', '.join(todo)}")

    if not done:
        return False, "no reachable consumer load site — abstain"
    provs = sorted({p for ps in stem_provs.values() for p in ps} | seam_provs)
    missing = [
        p
        for p in provs
        if not (eng.probe_file(f"{p}.sty") or eng.install_file(f"{p}.sty"))
    ]
    if missing:
        done.append(f"WARNING: {', '.join(missing)}.sty not found")
    return True, "; ".join(done)


# ═══ doc-latent @-def 站 exact-restore 包裹格 (spacefactor lane, 1206.0445) ═══

#: ``@``=catcode-12 宿主下 ``\@cs`` 断名成 ``\@``+裸字母 —— ``\@`` 即
#: ``\spacefactor\@m`` 间距宏, 展开点执行 → ``You can't use '\spacefactor'
#: in vertical mode`` / ``in math mode`` / ``Improper \spacefactor`` /
#: ``Package calc Error: '\spacefactor' invalid`` 四头 (全落 other 类)。
#: def 域内 ``\\[A-Za-z]*@[A-Za-z]`` 即肇事形 (``\l@section``/``\@secpenalty``
#: /``\hb@xt@``/``\c@footnote``); 裸 ``\@ `` (句读间距宏) 不带后继字母, 不中。
_AT_TOKEN_RE = re.compile(r"\\[A-Za-z]*@[A-Za-z]")

#: ambient @ 事件 —— ``\makeatletter``/``\makeatother``/``\catcode`@=N``/
#: ``\catcode 64=N``/``\catcode"40=N``/``\catcode'100=N``; 本族 restore cs
#: (``_AT_LETTER_*`` 与 pkgload ``_SHIP_WRAP_*`` 的复元符) 只裹非 letter 站,
#: 复元值恒为 other —— 走查直接建模。
_ATDEF_EVENT_RE = re.compile(
    r"\\makeat(letter|other)(?![A-Za-z])"
    r"|\\catcode\s*(?:`@|64|\"40|'100)\s*=\s*(\d+)"
    r"|\\TeXlate(?:At|StyIn)Restore(?![A-Za-z])"
)

#: def 命令面 —— 名+参+体跨域收 ``\@`` 站: ``\renewcommand*\l@section`` 名断
#: (体随文执行) 与 ``\newcommand\foo{...\@x...}`` 体断同修; ``\def`` 族
#: (``\long``/``\outer``/``\global``/``\protected`` 前缀任序) 走参数文本
#: 扫描, 其余走 ``[opt]``/``{grp}`` 贪婪组列。``\let``/``\newif`` 无体
#: def 不收 (断名产裸字母非 ``\@``)。
_ATDEF_CMD_RE = re.compile(
    r"\\(?:newcommand|renewcommand|providecommand|DeclareRobustCommand"
    r"|NewDocumentCommand|DeclareDocumentCommand|RenewDocumentCommand"
    r"|ProvideDocumentCommand|newenvironment|renewenvironment|newtheorem"
    r"|newfont|newmathalphabet|NewMathAlphabet|DeclareMathAlphabet"
    r"|DeclareMathOperator|DeclareMathSymbol|DeclareMathDelimiter"
    r"|DeclareMathAccent|DeclareMathRadical)(?![A-Za-z])"
    r"|(?:\\(?:long|outer|global|protected)(?![A-Za-z])[ \t]*)*"
    r"\\(?:gdef|edef|xdef|def)(?![A-Za-z])"
)

#: ``\def`` 参数文本窗上限 —— 无 ``{`` 体 (残缺稿) 按名末截域, 不吞全文。
_DEF_PARAM_MAX = 64

#: ``\csname`` 形 def 名的随尾 ``\endcsname`` —— ``_def_extent`` 名位专用。
_ENDCSNAME_RE = re.compile(r"\\endcsname(?![A-Za-z])")


def _skip_ws(vis: str, pos: int) -> int:
    while pos < len(vis) and vis[pos] in " \t":
        pos += 1
    return pos


def _brace_end(vis: str, pos: int) -> int:
    r"""``vis[pos]=='{'`` → 配对 ``}`` 后 offset; 未配对 → ``len(vis)``。"""
    depth, j = 1, pos + 1
    while j < len(vis) and depth:
        c = vis[j]
        if c == "\\":
            j += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        j += 1
    return j


def _cs_end(vis: str, pos: int) -> int:
    r"""``vis[pos]=='\\'`` → cs 名末 offset (字母+``@`` 连读; 单字符 cs 收一)。"""
    j = pos + 1
    if j < len(vis) and (vis[j].isalpha() or vis[j] == "@"):
        while j < len(vis) and (vis[j].isalpha() or vis[j] == "@"):
            j += 1
        return j
    return j + 1


def _def_extent(vis: str, pos: int, is_def: bool) -> int:  # noqa: C901, PLR0912, FBT001 - def/非 def 两臂域界分派, 每门即归因
    r"""\def 域末 offset: 可选 ``*`` → 名 (``{grp}``/``\cs``) → 参/体组列。

    ``\def`` 族: 参数文本跑到首个 ``{`` (``\{`` 转义不算) 再收一组即停
    (单体形); 参数文本超 ``_DEF_PARAM_MAX``/遇 ``\n\n``/无 ``{`` → 按名末
    截域。其余族: ``[opt]``/``{grp}`` 贪婪连收 (``\newenvironment`` 的
    beg/end 双组, ``\newtheorem`` 的 within opt 同形)。``\csname`` 名
    (``\renewcommand\csname l@section\endcsname``) 吞到 ``\endcsname``
    再续组列 —— 名本体免疫 catcode 但 ``{体}`` 内 ``\@`` 仍断名。
    """
    n = len(vis)
    pos = _skip_ws(vis, pos)
    if pos < n and vis[pos] == "*":
        pos = _skip_ws(vis, pos + 1)
    if pos < n and vis[pos] == "{":
        pos = _brace_end(vis, pos)
    elif pos < n and vis[pos] == "\\":
        if vis.startswith("\\csname", pos) and (
            pos + 7 >= n or not vis[pos + 7].isalpha()
        ):
            m = _ENDCSNAME_RE.search(vis, pos + 7)
            pos = n if m is None else m.end()
        else:
            pos = _cs_end(vis, pos)
    pos = _skip_ws(vis, pos)
    if is_def:
        j = pos
        while j < n and vis[j] != "{":
            if vis[j] == "\\":
                j += 2
                continue
            if vis[j : j + 2] == "\n\n":
                return pos
            j += 1
        if j >= n or j - pos > _DEF_PARAM_MAX:
            return pos
        return _brace_end(vis, j)
    while pos < n:
        if vis[pos] == "[":
            k = vis.find("]", pos + 1)
            pos = _skip_ws(vis, n if k < 0 else k + 1)
        elif vis[pos] == "{":
            pos = _skip_ws(vis, _brace_end(vis, pos))
        else:
            break
    return pos


def _atdef_sites(vis: str) -> list[tuple[int, int, bool]]:
    r"""遮盖视图走查 def 站 → ``[(start, extent_end, at_letter)]``。

    ``\makeatletter``/``\makeatother``/``\catcode`` 事件按组局部语义入栈 —
    — ``{`` 推现值 ``}`` 复元 (bare 组内事件读侧执行, 组末自动回); def 域
    整体跳过 (替换体在读侧惰性 —— 体内 ``\makeatletter`` 是调用期 token,
    不影响后续顶读的 ambient; 域内站点由外层站的包裹一并罩住)。
    """
    sites: list[tuple[int, int, bool]] = []
    at_letter = False
    stack: list[bool] = []
    pos, n = 0, len(vis)
    while pos < n:
        c = vis[pos]
        if c == "\\":
            ev = _ATDEF_EVENT_RE.match(vis, pos)
            if ev is not None:
                if ev.group(1) is not None:
                    at_letter = ev.group(1) == "letter"
                elif ev.group(2) is not None:
                    at_letter = ev.group(2) == "11"
                else:  # 本族 restore cs —— 只裹非 letter 站, 复元恒 other
                    at_letter = False
                pos = ev.end()
                continue
            d = _ATDEF_CMD_RE.match(vis, pos)
            if d is not None:
                end = _def_extent(vis, d.end(), d.group(0).rstrip().endswith("def"))
                sites.append((pos, end, at_letter))
                pos = end
                continue
            pos += 2
            continue
        if c == "{":
            stack.append(at_letter)
            pos += 1
            continue
        if c == "}":
            if stack:
                at_letter = stack.pop()
            pos += 1
            continue
        pos += 1
    return sites


def spacefactor_atdef_wrap(
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""doc-latent @-def 站 exact-restore @=11 包裹 → ``\@cs`` 断名根修。

    2.09-era 稿把 cls 内码抄进 preamble def 体而无 ``\makeatletter``:
    ``\renewcommand*\l@section[2]{...\addpenalty\@secpenalty...\hb@xt@...}``
    (1206.0445 :399-412), ``\newcommand\makepapertitle{...\renewcommand
    \thefootnote{\@fnsymbol\c@footnote}...\@thanks}`` (0905.0664) —— 体在
    @=12 下 tokenize → ``\@cs`` 断名成 ``\@``+裸字母 → def 站行或调用点
    ``\@`` 执行 → ``\spacefactor`` vmode/math/Improper/calc 四头。

    包裹取 svglov3.clo exact-restore idiom (``_AT_LETTER_PRE``/``_POST``):
    ``\edef`` 存 ``\catcode 64`` 现值 → ``=11`` 读域 → 复元 —— ``\input``
    跨界件宿主 ambient 不可测时恒等安全, 裸 ``\makeatletter`` 对会把
    letter 宿主尾段强翻回 12 (1803.02902 ``\widebar`` 实证)。dedup 键
    ``{rule}:None`` 全族共位 → 单轮全文件集扫净; 复跑时自注的
    ``\catcode 64=11`` 事件使域内站点天然 at_letter 跳过 (幂等)。
    ``params.exts`` 可覆写扫描面 (缺省 ``.tex`` —— ``.sty``/``.cls`` 装载
    期 @ 本即 letter)。
    """
    del eng, payload
    head = ctx.err_head or ""
    log = _fixloop_log(ctx)
    gate = params.get("gate_terms", ("spacefactor",))
    if gate and not any(t in head or t in log for t in gate):
        return False, f"no gate signature ({'|'.join(gate)})"
    exts = tuple(params.get("exts") or (".tex",))
    changed: list[str] = []
    for f in ctx.tex_files(exts):
        t = ctx.read(f)
        if t is None or "@" not in t:
            continue
        vis = mask_tex(t)
        edits = [
            (s, e)
            for s, e, al in _atdef_sites(vis)
            if not al and _AT_TOKEN_RE.search(vis[s:e])
        ]
        if not edits:
            continue
        out = t
        for s, e in reversed(edits):
            out = out[:s] + _AT_LETTER_PRE + out[s:e] + _AT_LETTER_POST + out[e:]
        if out != t:
            ctx.write(f, out)
            changed.append(f"{f.name}(x{len(edits)})")
    return (bool(changed)), f"@def exact-restore wrap in {', '.join(changed)}"


# ═══ \def\X<lit> 字面尾译文蚀除 → 逐站补回 (csdelim lane, 5 cells) ═══

#: TeX 错误头 ``Use of \X doesn't match its definition.`` —— X 是 def 时
#: 带字面参数文本的 cs。``\S+?`` 懒惰: 词型 (``\ch``) 收满字母段,
#: 符型 (``\0``/``\~``) 收单字符。
_MISMATCH_ERR_RE = re.compile(r"Use of \\(\S+?) doesn't match its definition")

#: ``\def`` 族的 cs 名 + 字面参数尾 —— 前缀 ``\long``/``\outer``/
#: ``\protected``/``\global`` 可叠, 本体 ``[egx]def``。尾 = ``{``/换行前的
#: 原文: ``\def\c3h2{`` → ``3h2``; ``\def\b {`` → 空 (裸参宏); ``\def\a#1{``
#: → ``#1`` 含 ``#`` 即真参宏, 不收。``\``/``{``/``}`` 入尾同理不收。
_DEF_TAIL_RE = re.compile(
    r"(?:\\(?:long|outer|protected|global)\s*)*"
    r"\\[egx]?def\s*"
    r"\\([A-Za-z@]+|[^A-Za-z\s])"
    r"([^\n{]*)"
)

#: 词型 cs 后的空白吸收 —— TeX 在 control word 后跳过 space token 序列
#: (``\n`` 亦按一 space 计); 符型 cs 不吸收 (``\0 `` 的空格进正文)。
_DELIM_SKIP_RE = re.compile(r"[ \t]*(?:\n[ \t]*)?")

#: 字面尾不可含的字符 —— ``#`` 真参 / ``\`` cs / ``{}`` 定界, 皆出机制面。
_TAIL_BAD_RE = re.compile(r"[#\\{}]")


def _tail_align(vis: str, pos: int, rest: str) -> tuple[int, int, int]:
    r"""``rest`` 在 ``vis[pos:]`` 上的乱序对齐 → (consumed, end, junk)。

    逐字符扫: 命中 ``rest[i]`` 前进; 非 ASCII 字 (译文残骸) 跳过记 junk;
    ASCII 未命中时仅在 junk 已见 (有蚀除证据) 时前视 ``rest`` 后段 ——
    蚀除吃掉的是居间 tail 字。``end`` = 最后一枚命中字符的后界。
    """
    i = 0
    q = pos
    last = pos
    junk = 0
    seen = False
    n = len(vis)
    while q < n and i < len(rest):
        c = vis[q]
        if c == rest[i]:
            i += 1
            q += 1
            last = q
            seen = False
        elif not c.isascii():
            q += 1
            junk += 1
            seen = True
        elif seen:
            nxt = rest.find(c, i)
            if nxt < 0:
                break
            i = nxt + 1
            q += 1
            last = q
            seen = False
        else:
            break
    return i, last, junk


def _delim_sites(  # noqa: C901 - 逐站证据分派, 每门即归因
    vis: str,
    site_rx: re.Pattern[str],
    tail_pos: list[tuple[int, str | None]],
    global_tail: str | None,
    *,
    letter_cs: bool,
) -> list[tuple[int, int, str]]:
    """单文件内某 cs 的蚀除站 → [(start, end, replacement)] 编辑面。

    有效尾 = 站点前最近的本文件 def 尾; 本文件无此 cs 的 def 时回落
    全局唯一尾 (def 在他件的 preamble 装载序)。def 在站点之后 = 该站
    沿用更早定义 (上游本就不同的语义) → 不收; 全局多尾歧义 → 不收。
    全对齐 → REPLACE 损毁域为尾 (junk 夹在两枚幸存尾字间 = 必为蚀除);
    部分对齐/零对齐 + 蚀除证据 (junk>0 或已消费>0) → 已配前缀后 INSERT
    残余尾 (零内容损失); 无证据 → 上游本就断裂, 不动。
    """
    edits: list[tuple[int, int, str]] = []
    n = len(vis)
    for m in site_rx.finditer(vis):
        pos = m.start()
        eff: str | None = None
        later_def = False
        for dp, dt in tail_pos:
            if dp < pos:
                eff = dt
            else:
                later_def = True
                break
        if later_def and eff is None:
            continue  # 站先于本文件一切 def —— 上游语义不可考
        if not tail_pos:
            eff = global_tail
        if not eff:
            continue
        j = m.end()
        if letter_cs:
            sm = _DELIM_SKIP_RE.match(vis, j)
            j = sm.end() if sm else j
        k = 0
        while k < len(eff) and j + k < n and vis[j + k] == eff[k]:
            k += 1
        if k == len(eff):
            continue  # 字面尾完好 (含 def 行自身)
        i, last, junk = _tail_align(vis, j + k, eff[k:])
        if i == len(eff) - k:
            edits.append((j, last, eff))
        elif junk > 0 or i > 0:
            edits.append((j + k, j + k, eff[k:]))
    return edits


def cs_delim_tail_fix(  # noqa: C901, PLR0912 - def 扫面 × 逐 cs 分派, 每门即归因
    ctx: LoopCtx, eng: Engine, payload: str | None, params: dict[str, Any]
) -> tuple[bool, str]:
    r"""``Use of \X doesn't match its definition`` → ``\def\X<lit>`` 字面尾补回。

    机制 (5 cells 同族): 作者用 ``\def\c3h2{...}``/``\def\b0bmode{...}``/
    ``\def\0cc{...}``/``\def\ch3oh{...}`` 造伪多名宏 —— TeX 解为 cs +
    字面参数文本, 上游一切调用点 ``\X<lit>`` 合法; 译者把尾中字母段当
    正文吃掉 (``\c3h2`` → ``\c3这是译文2``, ``\ch3oh`` → ``\ch3这是译文…``)
    → 调用点不再带全尾 → def-match 断。修 = 站点字面尾补回:
    蚀除域可证 (乱序对齐全命中) 时整域还原, 部分证据时插缺 (零删字)。
    多 def 取站点前最近者 (``\def\b``→``\def\b0bmode`` 重定义序,
    hep-ex/0408083 实证); def 在 .sty/.cls 时跨文件全局唯一尾回落
    (astro-ph/0408446 ``0343.sty`` 实证) —— 同侪 .tex 的装载序不可考,
    错补到沿用前义的站会静默改内容, 回落只信非 .tex def。包内
    delimited 宏 (工程外 def 不可见) 无尾可查 → abstain。
    """
    del eng, payload
    blob = (ctx.err_head or "") + "\n" + _fixloop_log(ctx)
    names: list[str] = []
    for m in _MISMATCH_ERR_RE.finditer(blob):
        if m.group(1) not in names:
            names.append(m.group(1))
    if not names:
        return False, "no cs in Use-of-doesn't-match error"

    exts = tuple(
        params.get("exts")
        or (".tex", ".sty", ".cls", ".def", ".clo", ".bbl", ".inc", ".cfg")
    )
    files = ctx.tex_files(exts)
    views: dict[Any, tuple[str, str]] = {}
    defs: dict[str, dict[Any, list[tuple[int, str | None]]]] = {}
    tails: dict[str, set[str]] = {}
    nontex_def: set[str] = set()
    for f in files:
        t = ctx.read(f)
        if t is None:
            continue
        vis = mask_tex(t)
        views[f] = (t, vis)
        for dm in _DEF_TAIL_RE.finditer(vis):
            cs = dm.group(1)
            if cs not in names:
                continue
            tail = dm.group(2).strip()
            entry: str | None = None
            if tail and not _TAIL_BAD_RE.search(tail):
                entry = tail
            defs.setdefault(cs, {}).setdefault(f, []).append((dm.start(), entry))
            if entry:
                tails.setdefault(cs, set()).add(entry)
            if f.suffix.lower() != ".tex":
                nontex_def.add(cs)

    changed: list[str] = []
    for cs in names:
        per_file = defs.get(cs, {})
        cst = tails.get(cs, set())
        global_tail = next(iter(cst)) if len(cst) == 1 and cs in nontex_def else None
        letter_cs = cs[:1].isalpha() or cs[:1] == "@"
        site_rx = re.compile(
            r"(?<!\\)\\" + re.escape(cs) + (r"(?![A-Za-z@])" if letter_cs else "")
        )
        for f, (t, vis) in views.items():
            if site_rx.search(vis) is None:
                continue
            edits = _delim_sites(
                vis, site_rx, per_file.get(f, []), global_tail, letter_cs=letter_cs
            )
            if not edits:
                continue
            out = t
            for s, e, rep in reversed(edits):
                out = out[:s] + rep + out[e:]
            if out != t:
                ctx.write(f, out)
                changed.append(f"{f.name}(\\{cs} x{len(edits)})")
    if not changed:
        return False, "no doc-side delimited def or intact sites only"
    return True, f"delim-tail restore in {', '.join(changed)}"
