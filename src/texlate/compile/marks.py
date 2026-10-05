r"""发射侧版面真值（LAYOUT_MARKS）：让 LaTeX 自己吐出元素坐标。

机制：preamble 注入 ``\pdfsavepos`` whatsit + 专用 ``\write`` 流，shipout
时把 ``MARK <uid> x=… y=… p=…`` 落进 ``<stem>.txlm``（x/y 单位 sp，
原点左下、y 向上；p=1-based 绝对页码）。检测侧从「pdftohtml 猜像素」
升级为「解析真值文件」。探针实证：

- ``env/<name>/begin`` 钩子的 mark 落外层流 = 浮体**声明锚点**；
  ``env/<name>/end`` 钩子的 mark 乘 ``\@currbox`` 随盒发排 = **实发位置**。
- deferred ``\write`` 在 shipout 才展开——``\the<counter>`` 一律读发排
  值，uid 必须 ``\edef`` 冻结（``\expandafter\endgroup`` 出组惯用法）。
- 永未发排的物料（measure-then-discard 试排盒/溢出丢弃浮体）整条
  静默 → ``lost_element`` 免费信号。
- ``cmd/@endfloatbox`` 取盒尺寸依赖可被 class 重定义的内部命令（且
  generic cmd hook 对不可补丁命令直接报错），v1 不出 BOX 行——矩形
  级重叠检查留在 poppler 侧（_layoutqc），marks 只校准它。

注入形态对齐 ``inject_float_sizing``：全树 file-walk + 每带
``\begin{document}`` 的文件在 bd 前落块 + 幂等哨兵（多 bd 形态由
``_splice_before_document`` 内置 ``_sentinel_wrap`` 兜）。
"""

from __future__ import annotations

import re
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Iterable

from texlate.latex.chars import match_brace, match_bracket

from ._docseams import _splice_before_document
from .mainfile import _MAIN_TEX_SUFFIXES
from .mask import visible_tex
from .normalize import _read_tex
from .transcode import _iter_files

#: 挂钩的环境清单——浮体/表体/展示数学/定位盒全覆盖；algorithm/
#: lstlisting 等自定义浮体 env 名不在内核钩子清单里的会被
#: env_inventory 计数差暴露（marks_coverage 信号）。
_MARK_ENVS: Final = (
    "figure",
    "figure*",
    "table",
    "table*",
    "wrapfigure",
    "wrapfigure*",
    "wraptable",
    "wraptable*",
    "wrapfloat",
    "tabular",
    "tabularx",
    "longtable",
    "minipage",
    "equation",
    "equation*",
    "align",
    "align*",
    "gather",
    "gather*",
    "multline",
    "multline*",
    "eqnarray",
    "eqnarray*",
    "textblock",
)

_FLOAT_ENVS: Final = frozenset(
    {
        "figure",
        "figure*",
        "table",
        "table*",
        "wrapfigure",
        "wrapfigure*",
        "wraptable",
        "wraptable*",
        "wrapfloat",
    }
)

#: 内层 env——可居变换容器（tikz/rotatebox/sideways），savepos 坐标
#: 不可信，offpage 判定跳过（见 compare_marks 注释）。
_INNER_ENVS: Final = frozenset(
    {"tabular", "tabularx", "longtable", "minipage", "textblock"}
)

#: 注入块——``\@for`` 逐环境注册 ``env/<name>/begin|end`` 钩子。
#: uid = ``<env>-<per-env 序>-<b|e>``，per-env 计数器
#: ``\csname txlm@c@<env>\endcsname`` 惰性 ``\newcount``，
#: ``\global\advance`` 抗浮体组作用域；begin 才 bump，end 复用同值成对。
#: begin 钩子 ``\@currenvir`` 自取环境名（此时恒为当前 env）；
#: end 钩子改为注册期烙名 ``\txlm@e{<env>}``——``env/<name>/end``
#: 触发点上 ``\@currenvir`` 可能已恢复成外层环境（2609.20793 实证：
#: \maketitle 内 authblk tabular 的 end 钩子读出 center →
#: ``\the\relax`` 报错 + ``center-0-e`` 毒化 mark + 编译 rc=1）。
LAYOUT_MARKS: Final = r"""% texlate: layout ground-truth marks v1
\makeatletter
\ifdefined\pdfsavepos
\newwrite\txlm@out
\immediate\openout\txlm@out=\jobname.txlm
\newcount\txlm@page
\AddToHook{shipout/before}{\global\advance\txlm@page\@ne}
\def\TeXlateMark#1{\pdfsavepos
  \write\txlm@out{MARK #1 x=\the\pdflastxpos\space y=\the\pdflastypos\space p=\the\txlm@page}}
\def\txlm@mark#1{\begingroup\edef\txlm@uid{#1}%
  \expandafter\endgroup\expandafter\TeXlateMark\expandafter{\txlm@uid}}
\def\txlm@b{\expandafter\ifx\csname txlm@c@\@currenvir\endcsname\relax
    \expandafter\newcount\csname txlm@c@\@currenvir\endcsname\fi
  \global\expandafter\advance\csname txlm@c@\@currenvir\endcsname\@ne
  \txlm@mark{\@currenvir-\the\csname txlm@c@\@currenvir\endcsname-b}}
\def\txlm@e#1{\expandafter\ifx\csname txlm@c@#1\endcsname\relax\else
  \txlm@mark{#1-\the\csname txlm@c@#1\endcsname-e}\fi}
\def\txlm@hook#1{\AddToHook{env/#1/begin}{\txlm@b}%
  \AddToHook{env/#1/end}{\txlm@e{#1}}}
\@for\txlm@n:=figure,figure*,table,table*,wrapfigure,wrapfigure*,wraptable,wraptable*,wrapfloat,tabular,tabularx,longtable,minipage,equation,equation*,align,align*,gather,gather*,multline,multline*,eqnarray,eqnarray*,textblock\do{%
  \expandafter\txlm@hook\expandafter{\txlm@n}}
\AtBeginDocument{\immediate\write\txlm@out{GEOM pw=\the\paperwidth\space
  ph=\the\paperheight\space tw=\the\textwidth\space th=\the\textheight\space
  tm=\the\topmargin\space hh=\the\headheight\space hs=\the\headsep\space
  ho=\the\hoffset\space vo=\the\voffset\space oi=\the\oddsidemargin\space
  cs=\the\columnsep}}
\fi
\makeatother
"""

#: 哨兵名——多 bd 幂等包裹与二次注入判重共用。
SENTINEL: Final = "TeXlateLayoutMarks"

_BEGIN_ENV_RX: Final = re.compile(
    r"\\begin\s*\{(" + "|".join(re.escape(e) for e in _MARK_ENVS) + r")\*?\}"
)

_MARK_RX: Final = re.compile(r"^MARK\s+(\S+)\s+x=(-?\d+)\s+y=(-?\d+)\s+p=(\d+)\s*$")
_GEOM_RX: Final = re.compile(r"^GEOM\s+(.*)$")
_GEOM_KV_RX: Final = re.compile(r"(\w+)=(-?[\d.]+)pt")
_UID_RX: Final = re.compile(r"^(.*)-(\d+)-(b|e)$")

#: sp/pt 换算。
SP_PER_PT: Final = 65536.0

#: Theil-Sen 趋势建模的最小对位浮体对数——<3 对时斜率不可辨识，
#: 退化为页数比外推（compare_marks drift 分支）。
_TREND_MIN_PAIRS: Final = 3


def inject_layout_marks(root: Path) -> int:
    r"""LAYOUT_MARKS 前导块注入：工程含任一受钩环境时才动主文件。

    返回注入文件数（多 ``\documentclass``/subfiles 工程可 >1）。幂等——
    哨兵在档或该文件无合格 bd 缝时不改写。
    """
    sources = {}
    for path in _iter_files(root, _MAIN_TEX_SUFFIXES):
        text = _read_tex(path)
        if text is not None:
            sources[path] = text
    if not any(_BEGIN_ENV_RX.search(visible_tex(text)) for text in sources.values()):
        return 0
    n = 0
    for path, text in sources.items():
        if LAYOUT_MARKS.strip() in text:
            continue
        new_text = _splice_before_document(text, LAYOUT_MARKS, sentinel=SENTINEL)
        if new_text != text:
            try:
                path.write_text(new_text, encoding="utf-8", newline="")
            except OSError:
                continue
            n += 1
    return n


def parse_txlm(path: Path) -> dict:
    """``<stem>.txlm`` → ``{marks: {uid: {x,y,p}}, geom: {kw: pt}, lines: n}``."""
    marks: dict[str, dict] = {}
    geom: dict[str, float] = {}
    lines = 0
    try:
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            raw = line.strip()
            m = _MARK_RX.match(raw)
            if m:
                uid, x, y, p = (
                    m.group(1),
                    int(m.group(2)),
                    int(m.group(3)),
                    int(m.group(4)),
                )
                # (uid,page) keep-first：moving-arg 双发射等重名只取首个
                key = f"{uid}@{p}"
                if key not in marks:
                    marks[key] = {"uid": uid, "x": x, "y": y, "p": p}
                continue
            g = _GEOM_RX.match(raw)
            if g:
                for k, v in _GEOM_KV_RX.findall(g.group(1)):
                    geom[k] = float(v)
            if raw:
                lines += 1
    except OSError:
        pass
    return {"marks": marks, "geom": geom, "lines": lines}


# ---------------------------------------------------------------- live-env 口径

#: ``<stem>.fls`` 的 INPUT 行——引擎开档集是期望面的权威活集（``\subfile``/
#: ``\import`` 族静态闭包抓不全，fls 由引擎背书）；行序=编译读档序。
_FLS_INPUT_RX: Final = re.compile(r"^INPUT\s+(.+?)\s*$")

#: depth-0 ``\end{document}``——其后到死尾的所有 token 引擎不再读。
_ENDDOC_RX: Final = re.compile(r"\\end\s*\{document\}")

_CS_WORD_RX: Final = re.compile(r"\\[a-zA-Z@]+")

#: ``\def``-族 opener（``\outer``/``\long``/``\protected``/``\global`` 前缀
#: token 不影响——扫描只认 opener 本身）。
_DEF_RX: Final = re.compile(
    r"\\(newenvironment|renewenvironment|[gex]?def|newcommand|"
    r"renewcommand|providecommand|DeclareRobustCommand)\s*\*?\s*"
)

_BEGIN_ANY_RX: Final = re.compile(r"\\begin\s*\{([^}\s]+)\}")

_MASK_RX: Final = re.compile(r"[^\n]")


def fls_tex_files(fls: Path, root: Path) -> list[str] | None:  # noqa: C901 -- INPUT 行逐条过豁免/后缀/驻树/stale-root 四道闸，分支即契约
    """``<stem>.fls`` INPUT 行 → ``root`` 相对 ``.tex/.ltx`` 开档序清单。

    缺席/零有效行 → ``None``（调用方退回全树口径）。vault 恢复/迁移
    后的树里 INPUT 记的是原编译机绝对路径、根名也可能被改写
    （fixloop 的 ``.pipe-fix`` → ``splice.real@v*``）——落不进
    ``root`` 的绝对路径按「root 下真实存在的最长路径后缀」映射回
    当前树。
    """
    try:
        lines = fls.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    try:
        base = root.resolve()
    except OSError:
        base = root
    out: list[str] = []
    seen: set[str] = set()
    for line in lines:
        m = _FLS_INPUT_RX.match(line.strip())
        if not m:
            continue
        raw = m.group(1).strip().strip('"')
        p = Path(raw)
        if not p.is_absolute():
            p = fls.parent / p
        try:
            rp = p.resolve()
        except OSError:
            continue
        if rp.suffix.lower() not in _MAIN_TEX_SUFFIXES:
            continue
        try:
            rel = rp.relative_to(base)
        except ValueError:
            rel = _stale_root_rel(Path(raw), base) if p.is_absolute() else None
            if rel is None:
                continue
        s = rel.as_posix()
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out or None


def _stale_root_rel(p: Path, base: Path) -> Path | None:
    """归档 .fls 的绝对 INPUT 路径 → ``base`` 相对路径。

    逐位左移取 ``base`` 下首个落盘存在的路径后缀——最长后缀承载
    最多的原树内相对路径上下文，命中即真身。全不命中 → ``None``
    （原树外文件/未随归档恢复，维持排除语义）。
    """
    parts = p.parts
    for j in range(1, len(parts)):
        tail = parts[j:]
        if ".." in tail:
            continue
        if base.joinpath(*tail).exists():
            return Path(*tail)
    return None


def _grp_end(vis: str, i: int) -> int:
    """``{`` 在 i → 平衡闭组后位；配不上 → ``i+1``（内容仍按活扫）。"""
    e = match_brace(vis, i, openers="{", nest="{")
    return i + 1 if e is None else e


def _brk_end(vis: str, i: int) -> int:
    """``[`` 在 i → 匹配 ``]`` 后位；配不上 → ``i+1``。"""
    e = match_bracket(vis, i)
    return i + 1 if e is None else e


def _if_boundary(vis: str, i: int, depth: int) -> tuple[int, int, bool]:
    r"""条件深度账：i 起扫至首个 ``\\else``@depth==1 或收 depth→0 的 ``\\fi``。

    返回 ``(tok_start, tok_end, is_else)``——EOF → ``(n, n, False)``。
    """
    j, n = i, len(vis)
    while j < n:
        w = _CS_WORD_RX.match(vis, j)
        if not w:
            j += 2 if vis[j] == "\\" else 1
            continue
        tok = w.group(0)
        if tok.startswith("\\if"):
            depth += 1
        elif tok == "\\else":
            if depth == 1:
                return j, w.end(), True
        elif tok == "\\fi":
            depth -= 1
            if depth == 0:
                return j, w.end(), False
        j = w.end()
    return n, n, False


def _walk_dead(vis: str) -> tuple[list[tuple[int, int]], bool]:  # noqa: C901 -- char 级 token 分派即分支面
    r"""结构死区一遍扫。

    depth-0 ``\\end{document}`` 死尾 + 全深度 ``\\iffalse`` 死支
    （``\\else`` 支是活的，死区止于 else 而非 fi）。返回
    ``(spans, hit_enddoc)``——hit_enddoc 标记 depth-0 job 终结。
    """
    spans: list[tuple[int, int]] = []
    i, n, depth = 0, len(vis), 0
    while i < n:
        c = vis[i]
        if c == "\\":
            m = _ENDDOC_RX.match(vis, i)
            if m:
                if depth == 0:
                    spans.append((i, n))
                    return spans, True
                i = m.end()
                continue
            w = _CS_WORD_RX.match(vis, i)
            if not w:
                i += 2
                continue
            tok = w.group(0)
            if tok == "\\bgroup":
                depth += 1
            elif tok == "\\egroup":
                depth = max(0, depth - 1)
            elif tok == "\\iffalse":
                _s, e, _is_else = _if_boundary(vis, i, 0)
                spans.append((i, e))
                i = e
                continue
            i = w.end()
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth = max(0, depth - 1)
        i += 1
    return spans, False


def _walk_defs(  # noqa: C901, PLR0912, PLR0915 -- def-族语法分派表：opener/name/opt/body 逐支平铺即 spec
    vis: str,
) -> tuple[list[tuple[int, int]], dict[str, int]]:
    r"""``\\def``-族定义点一遍扫：opener→body 组整段死（体只在调用时执行）。

    返回 ``(spans, {名: arity})``——命令族体全空记弃料宏名
    （``\\newcommand{\\ignore}[1]{}`` → ``ignore:1``），供调用点
    ``\\ignore{…}`` 参数组留白；env 族 before/after 空不吞 env 体
    （``\\begin``/``\\end`` 之间的内容照常排版），永不记名。
    """
    spans: list[tuple[int, int]] = []
    discards: dict[str, int] = {}
    n = len(vis)
    for m in _DEF_RX.finditer(vis):
        fam = m.group(1)
        kind = (
            "env" if "environment" in fam else ("def" if fam.endswith("def") else "cmd")
        )
        j = m.end()
        name_end = j
        defname = ""
        if j < n and vis[j] == "\\":
            w = _CS_WORD_RX.match(vis, j)
            if w:
                defname = w.group(0)[1:]
                j = w.end()
            else:
                j = min(j + 2, n)
            name_end = j
        elif j < n and vis[j] == "{":
            e = _grp_end(vis, j)
            inner = vis[j + 1 : e - 1].strip()
            defname = inner.removeprefix("\\")
            j = e
            name_end = j
        elif j < n:
            defname = vis[j]
            j += 1
            name_end = j
        arity = 0
        if kind == "def":
            # 参数文本无括号——扫到首个 ``{`` 即 body 起点（封顶防
            # 无 body 的病态 def 吞到 EOF）。
            cap = min(n, j + 512)
            while j < cap:
                c = vis[j]
                if c == "\\":
                    j += 2
                    continue
                if c == "{":
                    break
                if c == "#" and j + 1 < n and vis[j + 1].isdigit():
                    arity = max(arity, int(vis[j + 1]))
                    j += 2
                    continue
                j += 1
        else:
            # ``[N]``/``[N][d]`` opt 槽先行——首个是 arity
            first_opt = True
            while True:
                while j < n and vis[j] in " \t\r\n":
                    j += 1
                if j >= n or vis[j] != "[":
                    break
                e = _brk_end(vis, j)
                if first_opt:
                    first_opt = False
                    with suppress(ValueError):
                        arity = int(vis[j + 1 : e - 1].strip())
                j = e
        bodies = 0
        body_all_ws = True
        want = 2 if kind == "env" else 1
        while bodies < want:
            while j < n and vis[j] in " \t\r\n":
                j += 1
            if j >= n or vis[j] != "{":
                break
            e = _grp_end(vis, j)
            if vis[j + 1 : e - 1].strip():
                body_all_ws = False
            j = e
            bodies += 1
        if kind != "env" and bodies and body_all_ws and defname:
            discards.setdefault(defname, arity)
        spans.append((m.start(), j if bodies else name_end))
    return spans, discards


def _mask_spans(vis: str, spans: list[tuple[int, int]]) -> str:
    r"""死区 span 等长留白（``\\n`` 保留保行号）——``\\begin`` 不再计。"""
    for s, e in sorted(spans):
        vis = vis[:s] + _MASK_RX.sub(" ", vis[s:e]) + vis[e:]
    return vis


def _discard_arg_spans(vis: str, names: dict[str, int]) -> list[tuple[int, int]]:
    r"""空体宏调用点——``\\name`` 后 arity 个 ``{..}``/``[..]`` 槽整段死。

    参数被丢，槽内 ``\\begin`` 不执行。
    """
    if not names:
        return []
    rx = re.compile(r"\\(" + "|".join(re.escape(k) for k in names) + r")(?![a-zA-Z@])")
    out: list[tuple[int, int]] = []
    n = len(vis)
    for m in rx.finditer(vis):
        j = m.end()
        left = names[m.group(1)]
        while left:
            while j < n and vis[j] in " \t\r\n":
                j += 1
            if j < n and vis[j] == "{":
                j = _grp_end(vis, j)
                left -= 1
            elif j < n and vis[j] == "[":
                j = _brk_end(vis, j)
            else:
                break
        out.append((m.start(), j))
    return out


def _dead_spans(vis: str) -> tuple[list[tuple[int, int]], dict[str, int], bool]:
    r"""单文件死区：结构面（enddoc 死尾/iffalse 死支）→ def 体 + 弃料名。

    顺序：结构面先行——死区内的 ``\\newcommand`` 定义不生效
    （``\\iffalse`` 跳过整段），弃料名只在活区收集才不会错杀调用点。
    """
    spans, hit = _walk_dead(vis)
    dspans, discards = _walk_defs(_mask_spans(vis, spans))
    spans.extend(dspans)
    return spans, discards, hit


def _live_sources(root: Path, files: Iterable[Path] | None) -> list[str]:
    r"""源文件 → live 视图清单：visible_tex 遮盖 → 死区留白。

    死区 = enddoc 死尾/``\\iffalse`` 死支/def 体/弃料宏参数组。
    ``files`` 非空按编译序（fls 开档序）走读并止于首个含 depth-0
    ``\\end{document}`` 的文件（job 终结，其后文件引擎不再读）；
    ``None`` 退回 ``_iter_files`` 全树序（序未知，死尾仍切但不截
    文件流）。弃料名全局并集——定义与调用跨文件是常态。
    """
    paths = (
        list(_iter_files(root, _MAIN_TEX_SUFFIXES)) if files is None else list(files)
    )
    vises: list[str] = []
    deads: list[list[tuple[int, int]]] = []
    discards: dict[str, int] = {}
    for p in paths:
        text = _read_tex(p)
        vis = visible_tex(text) if text is not None else ""
        spans, dnames, hit = _dead_spans(vis)
        vises.append(vis)
        deads.append(spans)
        for nm, ar in dnames.items():
            discards.setdefault(nm, ar)
        if hit and files is not None:
            break
    out: list[str] = []
    for vis, spans in zip(vises, deads, strict=True):
        live = _mask_spans(vis, spans)
        if discards:
            live = _mask_spans(live, _discard_arg_spans(live, discards))
        out.append(live)
    return out


def env_inventory(root: Path, files: Iterable[Path] | None = None) -> dict[str, int]:
    r"""源树 ``\\begin{<env>}`` 逐环境计数（marks 覆盖率的期望面）。

    只数活区——``\\end{document}`` 死尾/``\\iffalse`` 死支/def 体/弃料
    宏参数组里的 ``\\begin`` 引擎永不执行，不计期望。``files`` 给
    fls 开档序的活文件集时按编译序走读（止于 job 终结文件），缺席
    退回全树扫描。
    """
    inv: dict[str, int] = {}
    for vis in _live_sources(root, files):
        for m in _BEGIN_ANY_RX.finditer(vis):
            env = m.group(1)
            inv[env] = inv.get(env, 0) + 1
    return inv


def env_sequence(
    root: Path,
    envs: frozenset = _FLOAT_ENVS,
    files: Iterable[Path] | None = None,
) -> list[str]:
    """源序浮体 uid 清单 ``<env>-<per-env 序>``——声明锚真值。

    跨臂元素匹配的**主键**（不用 b-mark：探针实证 b whatsit 独占末页
    galley 时不触发 page builder，浮体孤页会丢 b-mark；源扫出的声明序
    与编译行为无关、恒真）。``demote_wrapfloats`` 改名不改序——
    splice 树与 src 树的浮体序列等长、按位对即同元素。
    ``files``/死区口径同 ``env_inventory``——幻影声明剔除后 zip
    对位更稳。
    """
    seq: list[str] = []
    counters: dict[str, int] = {}
    for vis in _live_sources(root, files):
        for m in _BEGIN_ANY_RX.finditer(vis):
            env = m.group(1)
            if env not in envs:
                continue
            counters[env] = counters.get(env, 0) + 1
            seq.append(f"{env}-{counters[env]}")
    return seq


def _drift_findings(
    pairs: list[tuple[int, str, str, dict, dict]],
    *,
    zh_pages: int | None,
    base_pages: int | None,
    drift_pages: int,
) -> list[dict]:
    """离群漂移：浮体落点趋势建模后取残差。

    zh 篇幅整体压缩时 dp 随位置线性增长（2512.01407 实证 −2→−14 渐
    变，中位模型两头尾巴全误报），故 ≥_TREND_MIN_PAIRS 对走 Theil-Sen
    稳健线性趋势 ``zh_p ≈ a + b·base_p``（斜率=伸缩率、抗单点离群），
    残差 ≥drift_pages 才算真错位；更少对退化为页数比外推期望。
    """
    out: list[dict] = []
    if len(pairs) >= _TREND_MIN_PAIRS:
        slopes = [
            (z2["p"] - z1["p"]) / (b2["p"] - b1["p"])
            for _i, _u1, _u2, b1, z1 in pairs
            for _j, _v1, _v2, b2, z2 in pairs
            if b2["p"] != b1["p"] and _j > _i
        ]
        b_slope = sorted(slopes)[len(slopes) // 2] if slopes else 1.0
        inter = sorted(z["p"] - b_slope * be["p"] for _, _, _, be, z in pairs)
        a_icept = inter[len(inter) // 2]
        for i, buid, zuid, be, ze in pairs:
            expect = a_icept + b_slope * be["p"]
            dev = ze["p"] - expect
            if abs(dev) >= drift_pages:
                out.append(
                    {
                        "sig": "layout:float_drift",
                        "i": i,
                        "base_uid": buid,
                        "zh_uid": zuid,
                        "dev": round(dev, 2),
                        "expect_p": round(expect, 1),
                        "trend": [round(a_icept, 2), round(b_slope, 3)],
                        "zh_p": ze["p"],
                        "base_p": be["p"],
                    }
                )
    elif pairs and zh_pages and base_pages:
        ratio = zh_pages / base_pages
        for i, buid, zuid, be, ze in pairs:
            dev = ze["p"] - round(be["p"] * ratio)
            if abs(dev) >= drift_pages:
                out.append(
                    {
                        "sig": "layout:float_drift",
                        "i": i,
                        "base_uid": buid,
                        "zh_uid": zuid,
                        "dp": ze["p"] - be["p"],
                        "expect_p": round(be["p"] * ratio),
                        "zh_p": ze["p"],
                        "base_p": be["p"],
                    }
                )
    return out


def _order_findings(pairs: list[tuple[int, str, str, dict, dict]]) -> list[dict]:
    """发排序对拍：base (p,-y) 序 vs zh 同元素集的 (p,-y) 序。

    同页倒置是双栏几何伪影——(p,-y) 行主序把右栏顶排在左栏底之
    前，但视觉阅读序是先左栏后右栏（2601.02468/2607.06115 实证全
    部同页倒置均为栏位伪影）；只有跨页倒置才可能是真错序。
    对称地，base 侧同页落位的对也没有权威序——同页两浮体的先后
    只是打包副产物，zh 把其中一方重排到别页属合法回流（CS 语料
    实证 ~62% bad 对由此类构成）；要求 base 对本身跨页才认倒置。
    """
    base_order = [
        z for _, _, z, be, _ in sorted(pairs, key=lambda t: (t[3]["p"], -t[3]["y"]))
    ]
    zh_order = [
        z for _, _, z, _, ze in sorted(pairs, key=lambda t: (t[4]["p"], -t[4]["y"]))
    ]
    if zh_order == base_order:
        return []
    pos = {z: i for i, z in enumerate(zh_order)}
    ze_of = {z: ze for _, _, z, _, ze in pairs}
    be_of = {z: be for _, _, z, be, _ in pairs}
    bad = [
        (a, b)
        for i, a in enumerate(base_order)
        for b in base_order[i + 1 :]
        if pos.get(a, -1) > pos.get(b, -1)
        and ze_of[a]["p"] != ze_of[b]["p"]
        and be_of[a]["p"] != be_of[b]["p"]
    ]
    if not bad:
        return []
    return [
        {
            "sig": "layout:order_inversion",
            "pairs": bad,
            "base_order": base_order,
            "zh_order": zh_order,
        }
    ]


def _env_of(uid: str) -> str | None:
    """``<env>-<ord>-<b|e>`` → env 名；不合成 None。"""
    m = _UID_RX.match(uid)
    return m.group(1) if m else None


def _float_b_seq(marks: dict) -> list[str]:
    """文件序浮体 decl 列表（dict 插入序=txlm 行序≈声明序）。"""
    return [
        k.rsplit("@", 1)[0][:-2]
        for k in marks
        if k.rsplit("@", 1)[0].endswith("-b")
        and _env_of(k.rsplit("@", 1)[0]) in _FLOAT_ENVS
    ]


def _e_map(marks: dict) -> dict[str, dict]:
    """``<env>-<ord>`` decl → e-mark（longtable 跨页重名末位覆盖）。"""
    out: dict[str, dict] = {}
    for k, v in marks.items():
        uid = k.rsplit("@", 1)[0]
        if uid.endswith("-e"):
            out[uid[:-2]] = v
    return out


def _offpage_findings(zh: dict, offpage_pt: float) -> list[dict]:
    """单侧出页检查：savepos 坐标超出纸张 + 容差即报。

    内层 env（tabular/minipage/textblock…）常居变换容器内（tikz
    rotate 节点/rotatebox/sidewaystable），savepos 报变换前布局坐标
    → 渲染在框内也判 offpage（2402.07927 实证 13 个 tikz 树内嵌
    tabular 全误报）。内层元素的出框改由 poppler 词级 breach 兜
    （渲染后真值）；marks 只管浮体与展示数学这类外层、不继承图形
    变换的锚点。
    """
    out: list[dict] = []
    geom = zh.get("geom") or {}
    pw, ph = geom.get("pw"), geom.get("ph")
    if not (pw and ph):
        return out
    lim = offpage_pt * SP_PER_PT
    for v in zh.get("marks", {}).values():
        env = _env_of(v["uid"])
        if env in _INNER_ENVS:
            continue
        if (
            v["x"] < -lim
            or v["x"] > pw * SP_PER_PT + lim
            or v["y"] < -lim
            or v["y"] > ph * SP_PER_PT + lim
        ):
            out.append(
                {
                    "sig": "layout:offpage",
                    "uid": v["uid"],
                    "x": v["x"],
                    "y": v["y"],
                    "p": v["p"],
                }
            )
    return out


def _cross_findings(  # noqa: PLR0913 -- 同 compare_marks 旋钮面直通
    zh: dict,
    base: dict,
    *,
    zh_decl: list[str] | None,
    base_decl: list[str] | None,
    zh_pages: int | None,
    base_pages: int | None,
    drift_pages: int,
) -> list[dict]:
    """跨臂对位主路。

    声明序主键 zip → seq_mismatch/lost_element + drift/order 两助手。
    """
    out: list[dict] = []
    zh_e = _e_map(zh.get("marks", {}))
    base_e = _e_map(base.get("marks", {}))
    zs = zh_decl if zh_decl is not None else _float_b_seq(zh.get("marks", {}))
    bs = base_decl if base_decl is not None else _float_b_seq(base.get("marks", {}))
    if len(zs) != len(bs):
        out.append(
            {
                "sig": "layout:float_seq_mismatch",
                "zh_floats": len(zs),
                "base_floats": len(bs),
            }
        )
    pairs: list[tuple[int, str, str, dict, dict]] = []
    for i, (buid, zuid) in enumerate(zip(bs, zs, strict=False)):
        be = base_e.get(buid)
        ze = zh_e.get(zuid)
        if be is None:
            continue  # base 自己没发排——固有缺陷，不归 zh
        if ze is None:
            out.append(
                {
                    "sig": "layout:lost_element",
                    "i": i,
                    "base_uid": buid,
                    "zh_uid": zuid,
                    "base_env": _env_of(buid + "-b"),
                    "zh_env": _env_of(zuid + "-b"),
                    "base_p": be["p"],
                }
            )
            continue
        pairs.append((i, buid, zuid, be, ze))
    out.extend(
        _drift_findings(
            pairs, zh_pages=zh_pages, base_pages=base_pages, drift_pages=drift_pages
        )
    )
    out.extend(_order_findings(pairs))
    return out


def compare_marks(  # noqa: PLR0913 -- 检测旋钮面穿透（decl 主键/页数外推/阈值各臂）
    zh: dict,
    base: dict | None,
    *,
    zh_decl: list[str] | None = None,
    base_decl: list[str] | None = None,
    zh_pages: int | None = None,
    base_pages: int | None = None,
    drift_pages: int = 2,
    offpage_pt: float = 2.0,
) -> list[dict]:
    """zh/base 两副 marks 对照 → findings 清单（逐条 {sig, …}）。

    base=None 时只做单侧检查（offpage）。跨臂元素匹配**不按 uid 名**——
    ``demote_wrapfloats`` 把 wrapfigure→figure 且注入 minipage，uid 面
    全乱；主键是**声明序**：``zh_decl``/``base_decl`` 给源树浮体序
    （``env_sequence`` 产出 ``<env>-<序>`` 不带 -b/-e），缺省退化到
    b-mark 文件序（浮体孤页丢 b 的边例下不准——上层应尽量传 decl）。
    env 改名如实记进 finding（``base_env``/``zh_env``）。非浮体 env
    （minipage 注入会移位序）v1 不做跨臂比对，只吃单侧 offpage。

    ``p`` 是绝对页码轴：float_drift 判「离群漂移」——先对全体
    对位浮体建 zh_p≈a+b·base_p 稳健趋势再取残差（建模细则在
    _drift_findings），order_inversion 按对位浮体 e-mark 的
    (p,-y) 序对拍、只吃跨页倒置（同页伪影细则在 _order_findings）。
    """
    out = _offpage_findings(zh, offpage_pt)
    if base:
        out.extend(
            _cross_findings(
                zh,
                base,
                zh_decl=zh_decl,
                base_decl=base_decl,
                zh_pages=zh_pages,
                base_pages=base_pages,
                drift_pages=drift_pages,
            )
        )
    return out
