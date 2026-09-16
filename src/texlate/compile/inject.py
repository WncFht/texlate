r"""中文支持注入：ctex `[fontset=fandol,UTF8]` 默认路径 + xeCJK 降级路径。

docs/08 §3.3 注入缝：
- 兼容块 → `\begin{document}` 前（normalize.py 的 inject_preamble）
- 字体系块 → `\documentclass{}` 后（本模块 find_docclass_end）
- `\documentstyle` → **禁止注入 + inject 层 reject**（ctex/xeCJK 与 2.09
  互不兼容；route_project 已降级为 latex209_suspect 试编标记——
  inject 是 2.09 的兜底拒绝点，账本记 `inject_reject:latex209`
  与 route reject 分流）

实证：compile-bench 72 次编译中 ctex 注入破坏率 0%（bench/results/compile-report.md）。
"""

from __future__ import annotations

import re
from pathlib import Path

from texlate.textutil import decode_tex

from .mask import visible_tex
from .normalize import inject_preamble

CTEX_LINE = r"\usepackage[fontset=fandol,UTF8]{ctex}"

#: xeCJK 降级块：ctex 与模板冲突时（fixloop/探针编译切换）换这条路径。
XECJK_BLOCK = r"""
% texlate: CJK via xeCJK fallback path
\usepackage{xeCJK}
\setCJKmainfont{FandolSong-Regular.otf}[BoldFont=FandolSong-Bold.otf,ItalicFont=FandolKai-Regular.otf]
\setCJKsansfont{FandolHei-Regular.otf}[BoldFont=FandolHei-Bold.otf]
\setCJKmonofont{FandolFang-Regular.otf}
"""

#: 已有 CJK 支持 → 不重复注入。前边界防 `\impactex`/`sectex` 类宏名
#: 内嵌 "ctex" 的假阳（误判会跳过注入 → 整篇中文静默缺失）；
#: **无尾边界**——`ctexart`/`ctexbook`/`ctexrep`/`ctexbeamer` 文档类必须命中。
CJK_PRESENT_RE = re.compile(r"\b(?:ctex|xeCJK|CJKutf8|CJKfontspec|luatexja)")

#: 共享计数器 theorem 的双 named-dest 补丁（B7 锚点对齐）。
#: `\newtheorem{lemma}[definition]` 类声明在不同内核上 dest 命名分叉：
#: 旧内核（<2026-06，无 \newcounteralias）env 步进根计数器 → 锚点是
#: `definition.N`；新内核 alias 计数器 → env 步进自己的别名 → 锚点
#: `lemma.N`。en/zh 两臂只要工具链不一致就丢一半锚点（2410.17902
#: en 臂在 BasicTeX 2026 新内核上编出 `lemma.*`，zh 臂本地旧内核
#: 出 `definition.*`）。本补丁在 `\@begintheorem`/`\@opargbegintheorem`
#: before 钩子上补发「另一侧名字」的孪生锚点——纯增量不改名，
#: `\@currentHref` 发完即恢复，.aux label 名不受影响：
#: - `\@currenvir`==`\@currentcounter` 且 `alias@ctr@<env>` 存在
#:   → 新内核 alias 情形，补根名 `root.\theH<ctr>`；
#: - 不等且 `\the<env>` 有定义 → 旧内核共享计数器，补 env 名
#:   `env.\theH<ctr>`（`\the<env>` 守卫顺带挡掉 proof 等无号环境）。
#: `\@opargbegintheorem` 在 amsthm 下是 \relax（patch 静默跳过），
#: 在内核原生 theorem 路径上是带 [note] 的入口，两边都挂。
THEOREM_ANCHOR_SHIM = r"""
% texlate: twin named-dest for shared-counter theorems
\makeatletter
\def\TeXlate@thmtwin{%
  \@ifundefined{MakeLinkTarget}{}{%
  \@ifundefined{@currentcounter}{}{%
  \@ifundefined{theH\@currentcounter}{}{%
    \ifx\@currenvir\@currentcounter
      \@ifundefined{alias@ctr@\@currenvir}{}{%
        \edef\TeXlate@twin{\csname alias@ctr@\@currenvir\endcsname}%
        \TeXlate@emit}%
    \else
      \@ifundefined{the\@currenvir}{}{%
        \let\TeXlate@twin\@currenvir
        \TeXlate@emit}%
    \fi}}}%
}%
\def\TeXlate@emit{%
  \begingroup
  \let\TeXlate@save\@currentHref
  \edef\TeXlate@name{\TeXlate@twin.\csname theH\@currentcounter\endcsname}%
  \MakeLinkTarget*{\TeXlate@name}%
  \global\let\@currentHref\TeXlate@save
  \endgroup}%
\AddToHook{cmd/@begintheorem/before}{\TeXlate@thmtwin}%
\AddToHook{cmd/@opargbegintheorem/before}{\TeXlate@thmtwin}%
\makeatother
"""

_DOC_RE = re.compile(r"\\(documentclass|documentstyle)(?![a-zA-Z])")

#: \documentclass 调用参数扫描上限（防御畸形输入死循环）。
_DOCCLASS_SCAN_LIMIT = 4000

#: FLOAT_SIZING 仅在有 figure/table 时注入（docs/08 §3.3）。
FLOAT_SIZING = r"""% texlate: fit complete oversized float boxes v1
\usepackage{graphicx}
\begingroup
\makeatletter
\AtBeginDocument{%
\let\texlate@endfloatbox\@endfloatbox
\def\@endfloatbox{%
\texlate@endfloatbox
\def\texlate@figure{figure}%
\def\texlate@figurestar{figure*}%
\def\texlate@table{table}%
\def\texlate@tablestar{table*}%
\let\texlate@floatscope\@empty
\ifx\@currenvir\texlate@figure\def\texlate@floatscope{1}\fi
\ifx\@currenvir\texlate@figurestar\def\texlate@floatscope{1}\fi
\ifx\@currenvir\texlate@table\def\texlate@floatscope{1}\fi
\ifx\@currenvir\texlate@tablestar\def\texlate@floatscope{1}\fi
\ifx\texlate@floatscope\@empty\else
\ifdim\dimexpr\ht\@currbox+\dp\@currbox\relax>\textheight
\edef\texlate@floatwidth{\the\wd\@currbox}%
\edef\texlate@floatheight{\the\dimexpr\textheight-\baselineskip\relax}%
\ifdim\texlate@floatheight>0pt
\typeout{TeXlate-Float-Fit: \@captype\space \csname the\@captype\endcsname; height \the\dimexpr\ht\@currbox+\dp\@currbox\relax; limit \texlate@floatheight}%
\global\setbox\@currbox=\vbox{\hbox to\texlate@floatwidth{\hfil\resizebox*{!}{\texlate@floatheight}{\box\@currbox}\hfil}}%
\fi\fi\fi}%
}
\endgroup
"""

#: TABLE_FITTING hook threeparttable（adjustbox max width）。
TABLE_FITTING = r"""% texlate: fit complete measured table containers v1
\usepackage{adjustbox}
\begingroup
\makeatletter
\AtBeginDocument{%
\newif\iftexlate@tablefit
\newenvironment{TeXlateFitTable}{%
\iftexlate@tablefit
\let\texlate@endtablefit\relax
\else
\texlate@tablefittrue
\def\texlate@endtablefit{\end{adjustbox}}%
\begin{adjustbox}{max width=\linewidth}%
\fi\ignorespaces
}{\texlate@endtablefit}%
\AddToHook{env/threeparttable/before}{\begin{TeXlateFitTable}}%
\AddToHook{env/threeparttable/after}{\end{TeXlateFitTable}}%
}
\endgroup
"""


class InjectRejectError(ValueError):
    r"""`\documentstyle` 等不可注入形态——走降级链，不进编译。

    与 ``route_project`` 的 reject 分流：route 对 documentstyle 只打
    ``latex209_suspect``（先试编），inject 拒的是「注入后必死」——
    消费侧记 ``inject_reject:<reason>`` 类。
    """

    def __init__(self, reason: str = "latex209") -> None:
        """记录拒绝原因（默认 latex209 documentstyle）。"""
        self.reason = reason
        super().__init__("inject_reject:" + reason)


def find_main_tex(root: Path) -> Path | None:
    r"""定位主 .tex：最浅、最像正文的 `\documentclass`+`\begin{document}` 文件。

    排序：英文正文优先（多语种版本不靠 UTF-8 字节数排序——多字节文字
    系统性吃亏）→ main/paper/ms 名 → 目录深度 → 文件大小。
    """
    candidates = []
    bodies = {}
    for p in sorted(root.rglob("*.tex")):
        try:
            text = visible_tex(decode_tex(p.read_bytes()))
        except OSError:
            continue
        if re.search(r"\\(?:documentclass|documentstyle)\b", text) and re.search(
            r"\\begin\s*\{document\}", text
        ):
            rel = p.relative_to(root).as_posix()
            candidates.append(rel)
            bodies[rel] = text.split(r"\begin{document}", 1)[-1]
    if not candidates:
        return None

    def language_rank(path: str) -> bool:
        body = bodies[path]
        letters = sum(c.isalpha() for c in body)
        latin = len(re.findall(r"[A-Za-z]", body))
        return letters > 0 and latin < letters / 2

    candidates.sort(
        key=lambda p: (
            language_rank(p),
            Path(p).name not in ("main.tex", "paper.tex", "ms.tex"),
            len(Path(p).parts),
            -(root / p).stat().st_size,
        )
    )
    return root / candidates[0]


def _line_has_comment_before(tex: str, start: int) -> bool:
    """`tex[start]` 所在行在 start 之前是否出现未转义 `%`。"""
    i = tex.rfind("\n", 0, start) + 1
    while i < start:
        c = tex[i]
        if c == "\\":
            i += 2
            continue
        if c == "%":
            return True
        i += 1
    return False


def _docclass_close(tex: str, start: int) -> int:
    r"""从 `\documentclass` 命令名之后扫描 `[opt]{cls}` 配对，返回 `}` 后 offset。"""
    j, n = start, len(tex)
    db = dc = 0
    seen_brace = False
    while j < n:
        c = tex[j]
        if c == "\\":
            j += 2
            continue
        if c == "%":
            k = tex.find("\n", j)
            j = n if k < 0 else k + 1
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
                return j + 1
        if j - start > _DOCCLASS_SCAN_LIMIT:
            break
        j += 1
    return j


def find_docclass_end(tex: str) -> tuple[int, int, str] | None:
    r"""首个非注释 `\documentclass`/`\documentstyle` 调用的行尾位置。

    返回 `(insert_pos, lineno, cmd)`；括号匹配跨行、注释感知
    （revtex4-2 的 docclass 参数被注释穿插成五选一，实测语料 2308.07483）。
    """
    for m in _DOC_RE.finditer(tex):
        if _line_has_comment_before(tex, m.start()):
            continue
        close = _docclass_close(tex, m.end())
        if close < len(tex) and tex[close - 1] == "}":
            eol = tex.find("\n", close)
            return (
                (len(tex) if eol < 0 else eol),
                tex.count("\n", 0, close) + 1,
                m.group(1),
            )
        # 无 {..} 的裸 \documentclass：退化为行尾注入。
        eol = tex.find("\n", m.end())
        return (
            (len(tex) if eol < 0 else eol),
            tex.count("\n", 0, m.start()) + 1,
            m.group(1),
        )
    return None


def inject_cjk(tex: str, *, mode: str = "ctex") -> tuple[str, dict]:
    r"""在主文件文本上注入中文支持。返回 `(new_text, info)`。

    mode `"ctex"`：`\documentclass` 行后插 `\usepackage[fontset=fandol,UTF8]{ctex}`
    （hjfy 同款、双引擎实测 0% 破坏、白拿节名汉化）。
    mode `"xecjk"`：同缝插 xeCJK+Fandol 块（ctex 冲突签名→fixloop/探针切换用）。

    `\documentstyle` → 抛 InjectRejectError（2.09 注入层兜底拒绝——
    route 已降级为 suspect 试编标记，原文可编，注不进 CJK 才拒）。
    """
    if CJK_PRESENT_RE.search(visible_tex(tex)):
        return tex, {"status": "already"}
    hit = find_docclass_end(tex)
    if hit is None:
        return tex, {"status": "no-docline"}
    pos, lineno, cmd = hit
    if cmd == "documentstyle":
        raise InjectRejectError
    block = CTEX_LINE + "  % [texlate injected]" if mode == "ctex" else XECJK_BLOCK
    block += THEOREM_ANCHOR_SHIM
    return tex[:pos] + "\n" + block + tex[pos:], {
        "status": "injected",
        "mode": mode,
        "line": lineno,
    }


def inject_float_sizing(root: Path) -> int:
    r"""FLOAT_SIZING 前导块：仅在工程确实含 figure/table 环境时注入主文件。

    超高 float 用 `\resizebox*` 缩进页高 + `\typeout{TeXlate-Float-Fit:}`
    供日志回读。返回注入文件数（0/1）。
    """
    sources = {}
    for path in root.rglob("*.tex"):
        if path.is_file():
            sources[path] = decode_tex(path.read_bytes())
    if not any(
        re.search(r"\\begin\s*\{(?:figure|table)\*?\}", visible_tex(text))
        for text in sources.values()
    ):
        return 0
    n = 0
    for path, text in sources.items():
        vis = visible_tex(text)
        if FLOAT_SIZING.strip() in text:
            continue
        if re.search(r"\\(?:documentclass|documentstyle)\b", vis) and re.search(
            r"\\begin\s*\{document\}", vis
        ):
            path.write_text(inject_preamble(text, FLOAT_SIZING), encoding="utf-8")
            n += 1
    return n


def inject_table_fitting(tex: str) -> str:
    """TABLE_FITTING 前导块：工程含 threeparttable 时注入（调用方负责判据）。"""
    if TABLE_FITTING.strip() in tex:
        return tex
    return inject_preamble(tex, TABLE_FITTING)


def prepare_chinese(
    root: Path, main: Path | str, *, mode: str = "ctex", float_sizing: bool = True
) -> dict:
    r"""工程级中文注入编排：主文件 ctex/xeCJK + 按需 FLOAT_SIZING/TABLE_FITTING。

    返回注入报告 dict（注入缝行号/模式/已存在标记）。`\documentstyle` 工程
    抛 InjectRejectError——调用方应记 ``inject_reject:<reason>`` 类 reject
    （与 route reject 分流），而非编译失败。
    """
    main_path = root / main if isinstance(main, str) else main
    text = decode_tex(main_path.read_bytes())
    new_text, info = inject_cjk(text, mode=mode)
    if info["status"] == "injected":
        vis = visible_tex(new_text)
        if re.search(r"\\begin\s*\{threeparttable\}", vis) or re.search(
            r"threeparttable", vis
        ):
            new_text = inject_table_fitting(new_text)
        main_path.write_text(new_text, encoding="utf-8")
    if float_sizing:
        info["float_sizing"] = inject_float_sizing(root)
    return info
