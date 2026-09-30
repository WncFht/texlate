r"""``latex.reconstruct.mark`` — zh.pdf seq 注锚机械（``reconstruct`` god-file 机械拆分叶）。

``/TLXC <</MCID 50000+seq>> BDC … EMC`` marked-content 锚的 token
工厂 + 五闸谓词面（soul 栈/对齐 env/skip context/moving-arg/行间界，
全貌 docs/dev/projects/pdf-seq-anchors-impl-2026-09-23.md §2.2）：
``_mark_open``/``_MARK_CLOSE`` 造 token，``_pending_arg``/``_in_align_preamble``/
``in_env_args``/``_open_cs``/``_piece_site_map`` 供 ``_Expander._mark_seq``
判闸，``_wrap_seq_mark`` 宏参扫描区三臂处置，``seq_mark_issues``/
``strip_seq_marks`` lint/剥面出口。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from texlate.textutil import mask_tex

if TYPE_CHECKING:
    from collections.abc import Iterator

    from texlate.latex.model import ScanResult

# ---------------------------------------------------------------- seq 锚标记
#: zh.pdf seq 注锚（docs/dev/projects/pdf-seq-anchors-impl-2026-09-23.md）：xdvipdfmx
#: 血统引擎（xelatex/tectonic）把 ``\special{pdf:code ...}`` 原样落内容流；
#: pdf.js ``includeMarkedContent`` 透出 ``{tag,id}`` → textLayer 产
#: ``span.markedContent[id$="_mc<N>"]``——``N - SEQ_MARK_BASE`` 即 chunk
#: seq。whatsit 排版代价实测：块界 vmode 零漂移、段内 hmode ≤2.3bp；跨页
#: 不配平 pdf.js 容忍（页尾自闭合/页首孤儿丢弃）——DOM 不损，最差=部分锚。
SEQ_MARK_TAG = "TLXC"
SEQ_MARK_BASE = 50000  # mcid = SEQ_MARK_BASE + seq；避开文档自有 tagpdf MCID


def _mark_open(seq: int) -> str:
    """BDC 头——``/TLXC`` 恒定 tag + ``/MCID`` 载 seq（pdf.js 须 MCID 才发 DOM id）。"""
    return (
        "\\special{pdf:code /"
        + SEQ_MARK_TAG
        + " <</MCID "
        + str(SEQ_MARK_BASE + seq)
        + ">> BDC}"
    )


_MARK_CLOSE = "\\special{pdf:code EMC}"

#: lint/剥面 token 集——inline 形态可不在行首，剥 token 非剥行。
SEQ_MARK_OPEN_RX = re.compile(
    r"\\special\{pdf:code /" + SEQ_MARK_TAG + r" <</MCID (\d+)>> BDC\}"
)
_SEQ_MARK_EMC_RX = re.compile(r"\\special\{pdf:code EMC\}")
SEQ_MARK_RX = re.compile(
    r"\\special\{pdf:code (?:/" + SEQ_MARK_TAG + r" <</MCID \d+>> BDC|EMC)\}"
)

#: soul/ulem 族逐 token 重扫参数——whatsit 进参 = "Reconstruction failed"
#: 编译错。包围 cs-brace 栈命中即免注（16KB 内有限回溯，深嵌套残余登记）。
_MARK_SOUL_CS = frozenset(
    {
        "ul",
        "hl",
        "sout",
        "xout",
        "dashuline",
        "dotuline",
        "uline",
        "uwave",
        "st",
        "caps",
        "so",
        "letterspace",
        "markoverwith",
    }
)

#: 结构参族——token 落在其 ``{...}`` 参内时 whatsit 腐蚀参语义（cite key/
#: ref 标签/url/文件名/长度）。``_open_cs`` 栈命中即免注；混合参宏
#: (``\href`` arg2 是正文) 不入表——开栈判不出参位，靠 ``_pending_arg``
#: 尾端判据管 ``}{`` 间界。
_MARK_NONTEXT_CS = frozenset(
    {
        "cite",
        "citep",
        "citet",
        "citealp",
        "citealt",
        "citeauthor",
        "citeyear",
        "citeyearpar",
        "parencite",
        "textcite",
        "autocite",
        "footcite",
        "smartcite",
        "nocite",
        "ref",
        "eqref",
        "pageref",
        "autoref",
        "nameref",
        "cref",
        "vref",
        "label",
        "url",
        "nolinkurl",
        "path",
        "email",
        "doi",
        "index",
        "glossary",
        "bibliography",
        "bibliographystyle",
        "input",
        "include",
        "includeonly",
        "usepackage",
        "requirepackage",
        "documentclass",
        "includegraphics",
        "includepdf",
        "bibitem",
        "hspace",
        "vspace",
        "addvspace",
        "hyphenation",
    }
)

#: 对齐族 env——行间 whatsit（``\\`` 与 ``\hline`` 间）→ Misplaced \noalign。
#: 注：whatsit 落单元格 hmode 内合法——闸只拦序言区与行规/omit 前瞻位。
_MARK_ALIGN_ENVS = frozenset(
    {
        "tabular",
        "tabularx",
        "tabulary",
        "tabu",
        "longtabu",
        "tblr",
        "longtblr",
        "talltblr",
        "longtable",
        "deluxetable",
        "planotable",
        "tabbing",
        "supertabular",
        "xtabular",
        "ltablex",
        "nicetabular",
        "nicearray",
        "array",
        "matrix",
        "pmatrix",
        "bmatrix",
        "vmatrix",
        "smallmatrix",
        "cases",
        "blockarray",
    }
)

#: moving-arg context——``\protected@write`` 把参数字面写 .toc/.lof/.lot：
#: 目录页重放同 MCID = 锚歧义（读侧 seqpos occurrence 校验取末收敛）；
#: hyperref ``\pdfstringdef`` 剥 special 仅告警。``mark_moving=True`` 放行。
_MARK_MOVING_CTX = frozenset(
    {
        "section",
        "subsection",
        "subsubsection",
        "paragraph",
        "subparagraph",
        "chapter",
        "part",
        "sect",
        "subsect",
        "caption",
        "subcaption",
        "captionof",
        "tablecaption",
        "addcontentsline",
    }
)

#: 写流/书签类 context——whatsit 进参无锚收益且污染 .idx/.out。
_MARK_SKIP_CTX = frozenset(
    {"intertext", "shortintertext", "pdfbookmark", "index", "glossary"}
)

#: chunk 尾贴 ``\\``/行规族 token = 行间位——whatsit 破 align_peek
#: noalign 资格（未登记对齐 env 的冗余闸；``\end{`` 合法不在表内）。
_MARK_ROW_HEAD_RX = re.compile(
    r"^\s*(?:\\\\|\\(?:hline|noalign|midrule|cline|cmidrule|toprule|bottomrule"
    r"|specialrule|morecmidrules)\b)"
)

#: chunk 前贴 ``\\``（可带 ``[..]`` 垂直距参）——BMC 落 ``\\`` 与行间
#: 材料间同样破 noalign 前瞻。
_MARK_ROW_TAIL_RX = re.compile(r"\\\\(?:\[[^\]]*\])?\s*$")

#: 行首限定 token（omit 前瞻族 + noalign 行规族）——对齐 env 内 head/
#: 展开体头贴这些 = whatsit 破 ``\omit``/``\noalign`` 前瞻扫描。
_MARK_RULE_HEAD_RX = re.compile(
    r"^\s*\\(?:omit|span|multicolumn|hline|noalign|midrule|cline|cmidrule"
    r"|toprule|bottomrule|specialrule|morecmidrules)\b"
)

#: 展开体尾贴 ``\\``/行规 = EMC 落下行首/行间——对齐 env 内拒注。
_MARK_RULE_TAIL_RX = re.compile(
    r"(?:\\\\|\\(?:hline|noalign|midrule|cline|cmidrule|toprule|bottomrule"
    r"|specialrule|morecmidrules)\b(?:\s*\{[^{}]*\})?)\s*$"
)

#: ``\begin{env}`` 锚——对齐序言区判定扫尾串末次 env 开口。
_MARK_BEGIN_RX = re.compile(r"\\begin\s*\{[^{}]*\}")


def _in_align_preamble(tail: str) -> bool:
    r"""引用点在 ``\\begin{env}[opt]{preamble}`` 序言区——whatsit 进参非法。

    末次 ``\\begin{…}`` 之后的尾段若无 ``}``/``&``/``\\\\`` 之一，说明
    还在 env 头参/序言括号内（未进单元格体）→ 拒注。``{cc}`` 已闭合、
    ``&``/``\\\\`` 已见 = 进体 → 放行。
    """
    hits = list(_MARK_BEGIN_RX.finditer(tail))
    if not hits:
        return False
    seg = tail[hits[-1].end() :]
    return not any(t in seg for t in ("}", "&", "\\\\"))


#: env 头参 token——``[opt]``/``{arg}``/``*``/空白序列即 env 参扫描区。未知
#: env 的强制参（``\newtcolorbox`` 族 ``\begin{env}{arg}``）不落 env 头而
#: 进首体 chunk——whatsit 插 ``\begin`` 与参间 = ``Missing { inserted``
#: 编译错（t_e300 ``atriaopenquestion`` 实证，余波 ``Incomplete \iffalse``
#: 吞到 EOF）。判区/切参共用本形；参内嵌 ``{}`` 保守不判（错位注优于断编）。
_MARK_ENV_ARG_RX = re.compile(r"(?:\s|\*|\[[^\]]*\]|\{[^{}]*\})*")


def in_env_args(tail: str) -> bool:
    r"""引用点在 ``\\begin{env}`` 头参扫描区——env 参未扫完，锚须挪参串尾。

    尾段末次 ``\\begin{…}`` 之后仅 ``[opt]``/``{arg}``/``*``/空白即区内
    （已见正文的 ``text`` 尾段不匹配→区外）；对齐 env 不入此判——其序言
    区由 ``_in_align_preamble`` 拒注闸先行罩住。
    """
    hits = list(_MARK_BEGIN_RX.finditer(tail))
    if not hits:
        return False
    return _MARK_ENV_ARG_RX.fullmatch(tail[hits[-1].end() :]) is not None


def _split_arg_head(body: str) -> tuple[str, str]:
    """展开体前导 env 参串切分——``{arg}[opt]`` 前缀 vs 体（arg-zone 挪锚用）。"""
    m = _MARK_ENV_ARG_RX.match(body)
    end = m.end() if m else 0  # ``*`` 量词形零匹配恒成立，None 仅作类型窄化
    return body[:end], body[end:]


#: 宏参型签表——``\\cs`` 尾端参未填齐时下一个 token 会被当参吞走：
#: whatsit 落 ``\href{u}|{t}`` 间界 = \href 吞 ``\special`` 作 arg2,
#: ``{pdf:code ...}`` 成孤儿组 → ``Missing { inserted`` 级联
#: (t_e547 bibitem 劈点实证，fixloop_exhausted 硬毙)。
#: 值 = 参序列型签：``opt`` = ``[..]`` 可选参 (未现即跳), ``text`` = 可容
#: whatsit 的正文参 (BDC 可挪进其 ``{`` 内保锚), ``nontext`` = 结构参
#: (key/url/长度/颜色名——whatsit 进参即破), ``math`` = 数学参 (whatsit
#: 节点虽合法但不取此险)。表外 cs 按 0 参 → 非参区 (未知用户宏残余登记)。
#:
#: 与 ``data/argspec.json`` 的刻意分歧（非副本、勿投影合并）: argspec 是
#: segmenter 的未知-cs **吞参**签名 (逐包采录，``arg_roles`` 判保护/可译);
#: 本表是 reconstruct 的 **whatsit 落点**判定——``text`` 指 "BDC 可挪入锚"
#: 而非 "可译正文"(``\makebox``/``\parbox`` 尾参 argspec 记 ``skip``, 锚侧
#: 仍按 text 容锚)。覆盖互不齐：argspec 不收 ``\begin``/``\end``(parser
#: primitive) 与 math-literal 族 (``\dfrac``/``\binom``/``\bm``/``\substack``
#: 空签名) 及 ``\glossary``/``\requirepackage``/``\addvspace``/``\h``;
#: 可选参元数两侧口径亦不同 (``\href``/``\includegraphics``/``\includepdf``
#: 等)。``math`` 型签 argspec 无对应 role(消费上视同 ``nontext``, 仅留
#: 描述区分)。
_MARK_ARG_CS: dict[str, tuple[str, ...]] = {
    "begin": ("nontext",),
    "end": ("nontext",),
    "href": ("nontext", "text"),
    "hyperref": ("nontext", "text"),
    "textcolor": ("opt", "nontext", "text"),
    "colorbox": ("nontext", "text"),
    "fcolorbox": ("nontext", "nontext", "text"),
    "footnote": ("opt", "text"),
    "thanks": ("text",),
    "title": ("text",),
    "author": ("text",),
    "emph": ("text",),
    "textbf": ("text",),
    "textit": ("text",),
    "textsc": ("text",),
    "textsl": ("text",),
    "texttt": ("text",),
    "textrm": ("text",),
    "textsf": ("text",),
    "textmd": ("text",),
    "textup": ("text",),
    "underline": ("text",),
    "mbox": ("text",),
    "fbox": ("text",),
    "makebox": ("opt", "opt", "text"),
    "framebox": ("opt", "opt", "text"),
    "parbox": ("opt", "opt", "opt", "nontext", "text"),
    "raisebox": ("nontext", "opt", "opt", "text"),
    "multicolumn": ("nontext", "nontext", "text"),
    "multirow": ("nontext", "nontext", "text"),
    "sqrt": ("opt", "math"),
    "frac": ("math", "math"),
    "dfrac": ("math", "math"),
    "tfrac": ("math", "math"),
    "binom": ("math", "math"),
    "dbinom": ("math", "math"),
    "tbinom": ("math", "math"),
    "overset": ("math", "math"),
    "underset": ("math", "math"),
    "stackrel": ("math", "math"),
    "substack": ("math",),
    "mathbf": ("math",),
    "mathit": ("math",),
    "mathrm": ("math",),
    "mathsf": ("math",),
    "mathtt": ("math",),
    "mathcal": ("math",),
    "mathbb": ("math",),
    "mathfrak": ("math",),
    "bm": ("math",),
    "section": ("opt", "text"),
    "subsection": ("opt", "text"),
    "subsubsection": ("opt", "text"),
    "paragraph": ("opt", "text"),
    "subparagraph": ("opt", "text"),
    "chapter": ("opt", "text"),
    "part": ("opt", "text"),
    "caption": ("opt", "text"),
    "cite": ("opt", "opt", "nontext"),
    "citep": ("opt", "opt", "nontext"),
    "citet": ("opt", "opt", "nontext"),
    "citealp": ("opt", "opt", "nontext"),
    "citealt": ("opt", "opt", "nontext"),
    "citeauthor": ("opt", "opt", "nontext"),
    "citeyear": ("opt", "opt", "nontext"),
    "citeyearpar": ("opt", "opt", "nontext"),
    "parencite": ("opt", "opt", "nontext"),
    "textcite": ("opt", "opt", "nontext"),
    "autocite": ("opt", "opt", "nontext"),
    "footcite": ("opt", "opt", "nontext"),
    "smartcite": ("opt", "opt", "nontext"),
    "nocite": ("nontext",),
    "url": ("nontext",),
    "nolinkurl": ("nontext",),
    "path": ("nontext",),
    "email": ("nontext",),
    "doi": ("nontext",),
    "includegraphics": ("opt", "nontext"),
    "includepdf": ("opt", "nontext"),
    "label": ("nontext",),
    "ref": ("nontext",),
    "eqref": ("nontext",),
    "pageref": ("nontext",),
    "autoref": ("nontext",),
    "nameref": ("nontext",),
    "cref": ("nontext",),
    "vref": ("nontext",),
    "index": ("nontext",),
    "glossary": ("nontext",),
    "input": ("nontext",),
    "include": ("opt", "nontext"),
    "includeonly": ("nontext",),
    "usepackage": ("opt", "nontext"),
    "requirepackage": ("opt", "nontext"),
    "documentclass": ("opt", "nontext"),
    "bibitem": ("opt", "nontext"),
    "bibliography": ("nontext",),
    "bibliographystyle": ("nontext",),
    "hyphenation": ("nontext",),
    "hspace": ("nontext",),
    "vspace": ("nontext",),
    "addvspace": ("nontext",),
    "addcontentsline": ("nontext", "nontext", "text"),
    "addtocontents": ("nontext", "text"),
    "'": ("nontext",),
    "`": ("nontext",),
    "^": ("nontext",),
    "~": ("nontext",),
    '"': ("nontext",),
    "=": ("nontext",),
    ".": ("nontext",),
    "c": ("nontext",),
    "v": ("nontext",),
    "h": ("nontext",),
    "t": ("nontext",),
    "u": ("nontext",),
    "b": ("nontext",),
    "d": ("nontext",),
    "r": ("nontext",),
}

#: 参区尾端 cs 扫描——控制字 (``\\[a-zA-Z@]+``) 与单符控制符
#: (``\\'``/``\\~`` 变音族) 同收; ``\\\\`` 行间符走行尾闸不在此判。
_MARK_CS_TAIL_RX = re.compile(r"\\(?:[a-zA-Z@]+\*?|[^\s])")

#: 参区尾端已发锚的 whatsit 剥除——``segs`` 侧前块刚落的 EMC/BDC 不挡
#: 其前悬宏检出 (``\href{u}\special{EMC}`` 尾 = 参区内)。
_MARK_SPECIAL_TAIL_RX = re.compile(r"(?:\\special\{pdf:code[^{}]*\}|\s)*$")

_ARG_TOK_RX = re.compile(r"\[[^\]]*\]|\{[^{}]*\}|\*")


def _pending_arg(text: str) -> tuple[str, int] | None:
    r"""尾端宏参扫描区判定 → ``(待填参型, 宏起点)`` 或 ``None``。

    末位控制序列后仅 ``[opt]``/``{arg}``/``*``/空白 = 参未填齐仍在扫描
    区: 下一个 token (含 whatsit) 会被宏当参吞走。按 ``_MARK_ARG_CS``
    型签逐参消费已见组, 首个未填参的型签返回; 参已填齐/表外宏/后随
    正文 → ``None``。已注锚尾 whatsit 先剥再判 (``segs`` 侧复用)。
    """
    win = text[-4096:]
    seg = _MARK_SPECIAL_TAIL_RX.sub("", win)
    base = len(text) - len(win)
    for m in reversed(list(_MARK_CS_TAIL_RX.finditer(seg))):
        run = seg[m.end() :]
        if _MARK_ENV_ARG_RX.fullmatch(run) is None:
            break  # 末 cs 后见非参字符 → 位在参区外或其参括号内
        spec = _MARK_ARG_CS.get(m.group(0)[1:].rstrip("*").lower())
        if spec is None:
            return None
        toks = [t for t in _ARG_TOK_RX.findall(run) if t != "*"]
        i = 0
        for kind in spec:
            tok = toks[i] if i < len(toks) else None
            if kind == "opt":
                if tok is not None and tok.startswith("["):
                    i += 1
                continue
            if tok is not None and tok.startswith("{"):
                i += 1
                continue
            return kind, base + m.start()
        return None
    return None


_PH_EDGE_HEAD_RX = re.compile(r"^\s*(\[\[[A-Z]+_\d+\]\])")
_PH_EDGE_TAIL_RX = re.compile(r"(\[\[[A-Z]+_\d+\]\])\s*$")


def _wrap_seq_mark(exp: str, seq: int, prev_out: str, *, arg_zone: bool) -> str:
    r"""``BDC…exp…EMC`` 包裹——宏参扫描区双臂处置 (t_e547 ``\href{u}|{t}`` 劈点硬毙实证)。

    - EMC 臂: 展开体尾悬宏 → EMC 截到悬宏前 (锚缩域不丢, 待填参由 head
      侧字面续供);
    - BDC 臂: 前缘尾悬宏 (``prev_out`` = 已发出字面尾) → 待填参是
      ``text`` 且展开体以 ``{`` 起时 BDC 挪进其参内 (whatsit 居正文参
      合法), 否则裸发不注;
    - ``arg_zone`` 仍走 env 参串后挪锚; 三臂之外常规全包。
    """
    pend_prev = _pending_arg(prev_out)
    pend_exp = _pending_arg(exp)
    emc_at = len(exp) if pend_exp is None else pend_exp[1]
    core, tail_seg = exp[:emc_at], exp[emc_at:]
    if pend_prev is not None:
        lead = re.match(r"\s*\{", core)
        if pend_prev[0] == "text" and lead is not None:
            i = lead.end()
            return core[:i] + _mark_open(seq) + core[i:] + _MARK_CLOSE + tail_seg
        return exp  # nontext/数学参或无 ``{`` 参头 → 裸发不注
    if arg_zone:
        a_head, a_rest = _split_arg_head(core)
        if a_rest.strip():
            return a_head + _mark_open(seq) + a_rest + _MARK_CLOSE + tail_seg
        return exp  # 展开体纯 env 参串——锚无体可罩，裸发不注
    return _mark_open(seq) + core + _MARK_CLOSE + tail_seg


_BRACE_TOK_RX = re.compile(r"\\([a-zA-Z@]+\*?)[ \t]*\{|[{}]")


def _brace_events(text: str) -> Iterator[tuple[str, str | None]]:
    r"""``\\cs{``/``{``/``}`` 事件流（``\\{`` 字面豁免——前驱奇数个 ``\\``）。"""
    for m in _BRACE_TOK_RX.finditer(text):
        g = m.group(0)
        if g == "}":
            yield ("close", None)
            continue
        i = m.end() - 1  # '{' 位置
        bs = 0
        while i - bs - 1 >= 0 and text[i - bs - 1] == "\\":
            bs += 1
        if bs % 2:
            continue  # \{ 字面花括号
        yield ("open", m.group(1))


def _open_cs(text: str) -> frozenset[str]:
    r"""扫描末尾仍开放的 ``\\cs{`` 名集（小写、去星、无名组不记名）。"""
    stack: list[str | None] = []
    for ev, name in _brace_events(text):
        if ev == "open":
            stack.append(name)
        elif stack:
            stack.pop()
    return frozenset(n.rstrip("*").lower() for n in stack if n is not None)


def _piece_site_map(res: ScanResult) -> dict[int, frozenset[str]]:
    r"""``piece.span.start`` → 该点包围 ``\\cs{`` 名集（mask_tex 单遍+边界快照）。

    坐标系 = ``vtex``（span 所依）——**非** ``protected_tex``：后者是
    piece.text 拼接的 token 面，位序与 span 不同系，混用产生幻影栈
    （t_e547 chunk9 ``site_cs={'section'}`` 误丢锚实证）。verbatim/comment
    体等长遮盖——其内 ``{}``/``\\cs`` 不可见；piece 起点恰在 ``{`` 位时
    该括号未入栈（piece 内字面侧由 ``_open_cs`` 前缀补）。
    """
    masked = mask_tex(res.vtex)
    out: dict[int, frozenset[str]] = {}
    stack: list[str | None] = []
    starts = iter(sorted(p.span.start for p in res.pieces))
    start = next(starts, None)

    def snap() -> frozenset[str]:
        return frozenset(n.rstrip("*").lower() for n in stack if n is not None)

    for m in _BRACE_TOK_RX.finditer(masked):
        while start is not None and start <= m.start():
            out[start] = snap()
            start = next(starts, None)
        g = m.group(0)
        if g == "}":
            if stack:
                stack.pop()
            continue
        i = m.end() - 1
        bs = 0
        while i - bs - 1 >= 0 and masked[i - bs - 1] == "\\":
            bs += 1
        if bs % 2:
            continue
        stack.append(m.group(1))
    while start is not None:
        out[start] = snap()
        start = next(starts, None)
    return out


def seq_mark_issues(text: str) -> list[str]:
    """注锚失衡诊断：BDC/EMC 数差 + MCID 重复（``[]`` = 干净；lint 判据）。"""
    opens = SEQ_MARK_OPEN_RX.findall(text)
    emc = len(_SEQ_MARK_EMC_RX.findall(text))
    issues: list[str] = []
    if len(opens) != emc:
        issues.append(f"bdc={len(opens)} emc={emc}")
    dup = sorted(m for m, n in Counter(opens).items() if n > 1)
    if dup:
        issues.append("dup_mcid=" + ",".join(dup[:5]))
    return issues


def strip_seq_marks(text: str) -> str:
    """剥全部注锚 token（fixloop 失衡降级——锚全丢换编译面干净）。"""
    return SEQ_MARK_RX.sub("", text)
