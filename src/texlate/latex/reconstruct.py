r"""splice 重建 + DAG 递归展开 + validate（docs/spec/latex-pipeline.md）。

- **identity**：``translations=None`` → 平铺 pieces + ph 体逐字 → 逐字节 = 原文。
- O(总规模)+memo；相对 spike ``str.replace`` 不动点语义等价
  （同一替换表迭代至不动点 ≡ DAG 递归展开；构造上无环，assert 兜底）。
- **译文侧契约**：译文必须保留 ``chunk.placeholders`` 全列；
  :func:`validate_translation` 校验缺失/幻觉占位符（由 translate 层消费）。
- ``cjk_glue_fix``（``\\cmd这是`` → 插空格）是 post-reconstruct 全局修正一步，
  只在有译文时启用（identity 路径保持逐字节）。
- ``cjk_punct_close_guard``（CJK 标点 + ``\end{``/``\)``/``\]`` → 标点后插
  ``{}``）同位同门——xeCJK CheckFullRight 前瞻断链护栏。
- ``seg_join`` 接缝守卫（``\cs`` 尾 + 字母头 → 接缝插空格）在 expand/平铺
  两级生效，同样只随译文启用——latin 版不能用平铺正则（``\itemsep``/
  ``\parindent``/``\partial``/用户 camelCase 宏全是前缀撞名，语料万级
  存量），只能打接缝（cs token 永不跨段，``\cs|letter`` 接缝必是分隔被吞）。
- ``unicode_math_fix``（译文里游离的 ``β``/``∂`` → ``$\beta$``/``$\partial$``）
  是 pre-splice 的逐条译文修正——文本字体没有这些字形，缺字判据见 judge。
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from texlate.latex.model import Chunk, ScanResult, ScanWarning, Span
from texlate.latex.placeholder import CHUNK_RX, PH_RX
from texlate.textutil import CJK_RANGES, mask_tex, needs_seam_space

if TYPE_CHECKING:
    from collections.abc import Iterator

log = logging.getLogger(__name__)

_CJK_RX = re.compile(
    r"(\\[a-zA-Z@]+\\*?)(?=["
    + "".join(f"{chr(lo)}-{chr(hi)}" if lo != hi else chr(lo) for lo, hi in CJK_RANGES)
    + "])"
)


def _insert_masked(s: str, rx: re.Pattern[str], piece: str) -> str:
    r"""``mask_tex`` 视图命中点后插 ``piece``（verbatim/comment 体字面不可编辑，逆序回放）。

    命中位在等长遮盖视图上取——遮盖位与原串逐字节对齐，逆序回放使前序
    插入不扰后序命中位。``cjk_glue_fix``/``cjk_punct_close_guard`` 同骨架。
    """
    hits = [m.end() for m in rx.finditer(mask_tex(s))]
    for pos in reversed(hits):
        s = s[:pos] + piece + s[pos:]
    return s


def cjk_glue_fix(s: str) -> str:
    r"""``\cmd这是`` → ``\cmd 这是``：控制字后直接贴 CJK 时插空格。

    控制字后随空格在 TeX 里被吸收 → 源码语义不变，渲染更稳。
    命中点在 ``mask_tex`` 视图上找——verbatim/comment 体内的 ``\cmd中``
    是字面内容，不可编辑（等长遮盖位对齐，逆序回放）。
    """
    return _insert_masked(s, _CJK_RX, " ")


#: FullRight 类 CJK 标点（xeCJK punct 类右半族）——与暴露面普查口径一致。
_CJK_PUNCT_RIGHT = "，。、；：？！’”）】》〉」』〕〗"

#: CJK 标点前瞻护栏命中形：``。\end{sl}`` → ``。{}\end{sl}``。
#: xeCJK CheckFullRight（默认 on）对标点后 token 做 peek 前瞻，
#: ``\peek_remove_spaces`` 跳空格——``。 \end`` 同样踩。前瞻把
#: ``\end{env}`` 部分展开，fake env（``\end<env>`` 未定义，作者
#: 速记宏对产物）时 ``\endsl`` 上抛 undefined_cs（0806.2915
#: W157，pipe 11 err/base clean）。跟随者白名单只收 close-ish：
#: ``\end{``/``\)``/``\]``——``\(``（1623 良性 hits）、``\cite``
#: 类字母 cs（54k hits）前瞻不误伤，收入即过度改写。
#: ``[ \t]*(?:\n[ \t]*)?`` 容 ≤1 换行（单 ``\n``≡空格 token，前瞻
#: 照跳）；``\n\n``=``\par`` 天然断链，排除在匹配外。
_CJK_PUNCT_CLOSE_RX = re.compile(
    r"[" + _CJK_PUNCT_RIGHT + r"](?=[ \t]*(?:\n[ \t]*)?\\(?:end\{|\)|\]))"
)


def cjk_punct_close_guard(s: str) -> str:
    r"""CJK 标点后贴 close-ish token → 标点后插 ``{}`` 断前瞻链。

    ``{}`` 空组是恒等 token（无输出、非空格），peek 前瞻落在 ``{}``
    上即断链，不再吞 ``\end``/``\)``/``\]``——可对全部暴露点无条件
    适用，无需探测 ``\end<env>`` 是否有定义。命中点取 ``mask_tex``
    视图（verbatim/comment 体字面不可编辑），原串逆序回放——与
    ``cjk_glue_fix`` 同规。
    """
    return _insert_masked(s, _CJK_PUNCT_CLOSE_RX, "{}")


#: 段尾控制字（``\foo``/``\@foo``）：译文字母直接贴上即成更长 cs 名
#: （``\item FSU`` → ``\itemFSU``，realarm bug-B LLM 回显侧融合）。
#: 接缝判据 ``needs_seam_space`` 走 ``textutil.nets`` 单源——cs 尾形
#: ``cs_letter_tail_rx`` + ASCII 字母头（``\item\n`` 尾已自带分隔不算
#: 接缝命中；孤 ``\@`` 控制符号不收）。头字符 ASCII-only 是严口径：
#: 本处 TeX 吸收空格本无所谓，统一即消 ``isalpha`` 双侧漂移。
#: 有意分歧不复用：``xlat.batch._CS_TAIL_RX``（``\*?`` 星形 + ``$``
#: 收尾——cut retreat 的「尾落 cs token」安检，另一判据）。

#: 译文体内的 ``\itemFSU`` 保险丝（realarm spec）：模型回显把 ``\item``
#: 与大写首字母黏合。``\\item(?=[A-Z])`` 零误伤——``\item``+大写无合法
#: 先例（bfuse 普查），``\itemsep`` 类小写前缀撞名天然避开。只打译文体：
#: 源文侧 ``\cs<letter>`` 本就是一个 cs token，不构成该形。
LATIN_ITEM_RX = re.compile(r"\\item(?=[A-Z])")

#: 行首控制字采集：``\obeylines``/``^^M``-delimited 参数等换行语义域里
#: ``\X``-at-line-start 是定界 token（2009.11130 ``\GetTitle`` runaway——
#: para 段切把 `` \Title\n<text>\n \ShortTitle\n<text>`` 折成单行，
#: 译文回显后 ``^^M\X`` 定界符被吞，扫描奔到 EOF）。行首 ``\cs`` 归位
#: 在普通 catcode 下 ``\n``≡空格是恒等改写，只在换行语义域才兑现结
#: 构——所以无需识别 ``\obeylines`` 作用域，全量 chunk 统一适用。
_LINESTART_CS_RX = re.compile(r"(?m)^[ \t]*\\([a-zA-Z@]+)")


def _restore_linestarts(vtex: str, span: Span, zh: str) -> str:
    r"""行首 ``\cs`` 归位：源 span 内行首控制字若在译文里被压回行中，插 ``\n`` 复位。

    只在译文本面打 ``text␣\X`` → ``text\n\X``——``(?<=\S)`` 要求空白串
    前置非空白字符：已在行首（``\n ␣\X`` 形）的 ``\X`` 不动——其缩进
    空白串每个位置前都是 ``\n`` 或空白，匹配无从起步（旧 ``(?<=.)``
    能从空白串中段起步：``\n   ␣\X`` → ``\n ␣\n\X`` 孤儿空格行即
    ``\par``，2507.14695 ``\institute`` 104 err 实案）。占位符 token
    无 ``\`` 天然豁免，受保护体内部不进本层（ph 展开在其后）。行中
    无空格黏合的 ``text\X`` 不改——插 ``\n`` 会凭空多出一个空格
    token，语义不再恒等。
    """
    names = {m.group(1) for m in _LINESTART_CS_RX.finditer(vtex, span.start, span.end)}
    if not names:
        return zh
    rx = re.compile(
        r"(?m)(?<=\S)[ \t]+(\\(?:"
        + "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True))
        + r")(?![a-zA-Z@]))"
    )
    return rx.sub(r"\n\g<1>", zh)


def seg_join(segs: list[str]) -> str:
    r"""相邻展开段接缝守卫：``\cs`` 尾 + 字母头 → 接缝插空格。

    源文 ``\cs`` 与后继字母之间恒有分隔（空格/换行/注释——缺省即单
    cs 名 ``\itemFSU``，segmenter 从不把 cs token 切进两段）——接缝
    两侧直接拼出 ``\cs<letter>`` 必是分隔被吞（译文回显/占位展开边
    界），补空格恢复名字边界。体内部的 ``\fooBar`` 用户宏不在接缝
    上，天然豁免——这也是它比平铺 ``\\item(?=[A-Z])`` 后处理安全
    的原因（``\itemsep``/``\parindent``/``\partial`` 语料万级存量，
    平铺即误伤）。
    """
    out: list[str] = []
    for seg in segs:
        if not seg:
            continue
        if out and needs_seam_space(out[-1], seg):
            out.append(" ")
        out.append(seg)
    return "".join(out)


# ---------------------------------------------------------------- unicode → math
#: 模型译文里游离的 Unicode 数学字符 → LaTeX 命令。文本字体（lmroman/Fandol）
#: 没有这些字形 → missing_character 丢字（e2e-real 实证：β U+03B2 被丢）。
#: 包 ``$\cdot$`` 走数学字体渲染——不依赖任何字体探测的确定解。
#: 只收**确定缺席**的字符（希腊字母全谱 + 数学算子/关系/箭头）；±§°–— 等
#: TU 文本字体常备字形不在表内——过度包裹反而改变原文排版语义。
# fmt: off
_TEXT_TO_MATH: dict[str, str] = {
    # 希腊小写
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta",
    "ε": r"\epsilon", "ϵ": r"\varepsilon", "ζ": r"\zeta", "η": r"\eta",
    "θ": r"\theta", "ϑ": r"\vartheta", "ι": r"\iota", "κ": r"\kappa",
    "ϰ": r"\varkappa", "λ": r"\lambda", "μ": r"\mu", "µ": r"\mu",
    "ν": r"\nu", "ξ": r"\xi", "ο": r"\mathrm{o}", "π": r"\pi",
    "ϖ": r"\varpi", "ρ": r"\rho", "ϱ": r"\varrho", "σ": r"\sigma",
    "ς": r"\varsigma", "τ": r"\tau", "υ": r"\upsilon", "φ": r"\phi",
    "ϕ": r"\varphi", "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega",
    # 希腊大写（与拉丁同形的归 \mathrm，避免 \Alpha 等非标准命令）
    "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda",
    "Ξ": r"\Xi", "Π": r"\Pi", "Σ": r"\Sigma", "Υ": r"\Upsilon",
    "Φ": r"\Phi", "Χ": r"\Chi", "Ψ": r"\Psi", "Ω": r"\Omega",
    "Α": r"\mathrm{A}", "Β": r"\mathrm{B}", "Ε": r"\mathrm{E}",
    "Ζ": r"\mathrm{Z}", "Η": r"\mathrm{H}", "Ι": r"\mathrm{I}",
    "Κ": r"\mathrm{K}", "Μ": r"\mathrm{M}", "Ν": r"\mathrm{N}",
    "Ο": r"\mathrm{O}", "Ρ": r"\mathrm{P}", "Τ": r"\mathrm{T}",
    "Ϝ": r"\digamma", "ϝ": r"\digamma",
    # 数学算子/关系/箭头/界符（文本字体必缺）
    "−": "-", "′": "'", "″": "''", "‴": "'''", "⁗": "''''",
    "∂": r"\partial", "∇": r"\nabla", "∈": r"\in", "∉": r"\notin",
    "∋": r"\ni", "∏": r"\prod", "∐": r"\coprod", "∑": r"\sum",
    "√": r"\surd", "∞": r"\infty", "∫": r"\int", "∬": r"\iint",
    "∭": r"\iiint", "∮": r"\oint", "∧": r"\wedge", "∨": r"\vee",
    "∩": r"\cap", "∪": r"\cup", "⊂": r"\subset", "⊃": r"\supset",
    "⊆": r"\subseteq", "⊇": r"\supseteq", "⊄": r"\nsubseteq",
    "⊈": r"\nsubseteq", "⊊": r"\subsetneq", "⊋": r"\supsetneq",
    "∀": r"\forall", "∃": r"\exists", "∄": r"\nexists", "∅": r"\emptyset",
    "∝": r"\propto", "∼": r"\sim", "≃": r"\simeq", "≅": r"\cong",
    "≡": r"\equiv", "≈": r"\approx", "≤": r"\leq", "≥": r"\geq",
    "≠": r"\neq", "≪": r"\ll", "≫": r"\gg", "⊗": r"\otimes",
    "⊕": r"\oplus", "⊖": r"\ominus", "⊙": r"\odot", "⊘": r"\oslash",
    "∘": r"\circ", "∗": r"\ast", "⋅": r"\cdot", "⋆": r"\star",
    "→": r"\to", "←": r"\leftarrow", "↑": r"\uparrow", "↓": r"\downarrow",
    "↔": r"\leftrightarrow", "↕": r"\updownarrow", "⇐": r"\Leftarrow",
    "⇒": r"\Rightarrow", "⇑": r"\Uparrow", "⇓": r"\Downarrow",
    "⇔": r"\Leftrightarrow", "↦": r"\mapsto", "⟨": r"\langle",
    "⟩": r"\rangle", "⌈": r"\lceil", "⌉": r"\rceil", "⌊": r"\lfloor",
    "⌋": r"\rfloor", "∥": r"\parallel", "∤": r"\nmid", "ℏ": r"\hbar",
    "ℓ": r"\ell", "ℜ": r"\Re", "ℑ": r"\Im", "ℵ": r"\aleph",
    "⊥": r"\perp", "≺": r"\prec", "≻": r"\succ", "⪯": r"\preceq",
    "⪰": r"\succeq", "⊢": r"\vdash", "⊣": r"\dashv", "⊨": r"\models",
    "◦": r"\circ",
}
# fmt: on

_UNICODE_MATH_RX = re.compile("[" + "".join(re.escape(c) for c in _TEXT_TO_MATH) + "]")

#: 短参写回的 ``\par`` 折叠：命令参数位（``\caption``/``\section``/``\footnote``
#: 等 chunk-arg 语境，``Chunk.context`` 非 ``para``/``item``）里 ``\n\n``
#: 是 ``\par``——nameref ``\NR@gettitle``/``\@sect`` 等非 ``\long`` 读取宏
#: 遇之即 runaway（1109.5963 实证：译文自带 ``\n`` 叠 ph 体前导 ``\n  ``
#: 在 ``\caption`` 参数内合成 ``\n\n``）。译文内部与占位符边界合并出的
#: 段落断在展开后文本上统一压成单 ``\n``；正文段（``para``/``item``）
#: 的 ``\n\n`` 合法，不动。
PAR_RUN_RX = re.compile(r"\n(?:[ \t\r]*\n)+")

#: 译文侧的占位符切分（typed ``[[X_n]]`` + 裸 ``[[NAME]]`` 都算——模型可能
#: 把 [[SL]] 等编码 token 原样回显，其内部不许进 unicode→math 替换）。
#: 捕获组保留分隔符——``re.split`` 产出 [文本, token, 文本, ...] 交错序列。
_TRANS_PH_RX = re.compile(rf"((?:{PH_RX.pattern})|(?:\[\[[A-Z][A-Z_]*\]\]))")


def unicode_math_fix(zh: str) -> str:
    r"""译文非占位符段内的 Unicode 数学字符 → ``$\alpha$`` 形式。

    占位符 token 整段豁免（``[[MATH_1]]`` 体内是原样回放的受保护原文，
    其内部 ``$\beta$`` 已是合法数学）。已写成 ``\beta``/``$..$`` 的不动。
    """
    parts = _TRANS_PH_RX.split(zh)
    out: list[str] = []
    for i, seg in enumerate(parts):
        if i % 2:
            out.append(seg)  # 占位符 token 原样
        else:
            out.append(
                _UNICODE_MATH_RX.sub(lambda m: f"${_TEXT_TO_MATH[m.group(0)]}$", seg)
            )
    return "".join(out)


def translation_tokens(
    res: ScanResult, translations: dict[int, str] | None
) -> dict[str, str]:
    r"""``{chunk_id: 译文}`` → ``{"[[CHUNK_k]]": 落盘位译文本}`` token 映射。

    ``reconstruct``/``repair_l2.chunk_spans`` 同一构造——译文侧变换链
    ``_restore_linestarts`` 行首 ``\cs`` 归位 → ``unicode_math_fix`` →
    ``LATIN_ITEM_RX`` 保险丝逐条同序施加；``res.chunks`` 界外/非 int
    键直通原值。``None`` → 空映射（identity 面无译文本）。
    """
    if translations is None:
        return {}
    return {
        f"[[CHUNK_{k}]]": LATIN_ITEM_RX.sub(
            r"\\item ",
            unicode_math_fix(
                _restore_linestarts(res.vtex, res.chunks[k].span, v)
                if isinstance(k, int) and 0 <= k < len(res.chunks)
                else v
            ),
        )
        for k, v in translations.items()
    }


# ---------------------------------------------------------------- seq 锚标记
#: zh.pdf seq 注锚（docs/dev/pdf-seq-anchors-impl-2026-09-23.md）：xdvipdfmx
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
        "ul", "hl", "sout", "xout", "dashuline", "dotuline", "uline", "uwave",
        "st", "caps", "so", "letterspace", "markoverwith",
    }
)

#: 对齐族 env——行间 whatsit（``\\`` 与 ``\hline`` 间）→ Misplaced \noalign。
_MARK_ALIGN_ENVS = frozenset(
    {
        "tabular", "tabularx", "tabulary", "tabu", "longtabu", "tblr",
        "longtblr", "talltblr", "longtable", "deluxetable", "planotable",
        "tabbing", "supertabular", "xtabular", "ltablex", "nicetabular",
        "nicearray", "array", "matrix", "pmatrix", "bmatrix", "vmatrix",
        "smallmatrix", "cases", "blockarray",
    }
)

#: moving-arg context——``\protected@write`` 把参数字面写 .toc/.lof/.lot：
#: 目录页重放同 MCID = 锚歧义；hyperref ``\pdfstringdef`` 剥 special 告警。
#: 调用方 ``mark_moving=True`` 证明无该面后放行。
_MARK_MOVING_CTX = frozenset(
    {
        "section", "subsection", "subsubsection", "paragraph", "subparagraph",
        "chapter", "part", "sect", "subsect", "caption", "subcaption",
        "captionof", "tablecaption", "addcontentsline",
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

#: moving-arg 放行探针（调用方对全部 vtex 扫一遍——目录/listof/hyperref
#: 任一在场即 ``mark_moving=False``；``hyperref`` 裸词匹 usepackage/RequirePackage
#: 两行，误伤面是自定义同名宏→不注锚降级，方向安全）。
MARK_MOVING_UNSAFE_RX = re.compile(
    r"\\(?:tableofcontents|listoffigures|listoftables|listofalgorithms?)\b|hyperref"
)

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
    return frozenset(
        n.rstrip("*").lower() for n in stack if n is not None
    )


def _piece_site_map(res: ScanResult) -> dict[int, frozenset[str]]:
    r"""``piece.span.start`` → 该点包围 ``\\cs{`` 名集（mask_tex 单遍+边界快照）。

    verbatim/comment 体等长遮盖——其内 ``{}``/``\\cs`` 不可见；piece 起点
    恰在 ``{`` 位时该括号未入栈（piece 内字面侧由 ``_open_cs`` 前缀补）。
    """
    masked = mask_tex(res.protected_tex)
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


class _Expander:
    r"""``[[X_n]]`` 占位符 DAG 递归展开器（``reconstruct``/``chunk_spans`` 单源）。

    ``trans_map`` = ``translation_tokens`` 产物；``glue_latin`` 开接缝
    守卫（译文落盘侧恒真，identity 路径恒假）。``expand`` 解析优先级
    ``trans_map → ph_map → CHUNK_RX.fullmatch → chunks[idx].content →
    字面``；memo + ``active`` 环检内建（译文侧自指/互指环留字面），
    查无实体的 token 记 ``dangling``（``ph_reserved`` 豁免）。
    """

    def __init__(
        self,
        res: ScanResult,
        trans_map: dict[str, str],
        *,
        glue_latin: bool,
        mark_seq0: int | None = None,
        mark_moving: bool = False,
    ) -> None:
        self.res = res
        self.trans = trans_map
        self.glue_latin = glue_latin
        self.memo: dict[str, str] = {}
        self.active: set[str] = set()
        # seq 注锚表：{chunk_idx: seq}；None → 不注锚（identity/chunk_spans 同径）
        self.mark = (
            {c.id: mark_seq0 + c.id for c in res.chunks}
            if mark_seq0 is not None
            else None
        )
        self.mark_moving = mark_moving
        # piece 级 site 上下文（顶层 expand_body 前由 reconstruct 逐 piece 写入）
        self._site_cs: frozenset[str] = frozenset()
        self._site_prev = ""
        self._site_next = ""
        # 查无实体的 ph token——留字面并记名（原静默残留）
        self.dangling: set[str] = set()
        # 短参 chunk 集：context 非 para/item 的已译 [[CHUNK_n]]——展开后
        # ``\n\n`` 压单 ``\n``（见 PAR_RUN_RX 注）。
        self.short_arg: set[str] = {
            f"[[CHUNK_{c.id}]]"
            for c in res.chunks
            if c.context not in ("para", "item") and f"[[CHUNK_{c.id}]]" in trans_map
        }

    def expand(self, token: str) -> str:  # token 形如 [[X_n]]
        """单 token → 展开体（memo 命中直返）。"""
        memo = self.memo
        if token in memo:
            return memo[token]
        if token in self.active:
            return token  # 译文侧自指/互指环（ph_map 构造上无环）→ 留字面
        self.active.add(token)
        body = self.trans.get(token)
        if body is None:
            body = self.res.ph_map.get(token)
        if body is None:
            m = CHUNK_RX.fullmatch(token)
            idx = int(m.group(1)) if m else -1
            if 0 <= idx < len(self.res.chunks):
                body = self.res.chunks[idx].content
            else:
                if token not in self.res.ph_reserved:
                    self.dangling.add(token)
                body = token
        expanded = self.expand_body(body, fold_par=token in self.short_arg)
        memo[token] = expanded
        self.active.discard(token)
        return memo[token]

    def set_site(
        self, cs: frozenset[str], prev: str, nxt: str
    ) -> None:
        """Piece 级 site 上下文写入——``reconstruct`` 逐顶层 piece 调用。"""
        self._site_cs = cs
        self._site_prev = prev
        self._site_next = nxt

    def _mark_seq(  # noqa: C901, PLR0911, PLR0912 — 五闸顺序短路，逐条直铺即谓词清单
        self, tok: str, body: str, mstart: int, mend: int, *, top: bool
    ) -> int | None:
        r"""引用点注锚判定——seq 或 None（保守方向：判不出=不注，丢锚不丢编译）。

        谓词全貌见 docs/dev/pdf-seq-anchors-impl-2026-09-23.md §2.2：
        soul 栈/对齐 env/skip context/moving-arg/行间界五闸。``top`` 区分
        顶层 piece 体（前后文可查 ``_site_prev/_site_next``）与嵌套体
        （体外上下文不可知→首尾判不出即弃注）。
        """
        if self.mark is None:
            return None
        m = CHUNK_RX.fullmatch(tok)
        if not m:
            return None
        idx = int(m.group(1))
        if not (0 <= idx < len(self.res.chunks)):
            return None
        chunk = self.res.chunks[idx]
        ctx = (chunk.context or "").lower()
        if ctx in _MARK_SKIP_CTX:
            return None
        env = (chunk.env or "").lower().rstrip("*")
        if env in _MARK_ALIGN_ENVS or env.endswith("matrix") or env.startswith("nice"):
            return None
        site_cs = self._site_cs | _open_cs(body[:mstart])
        if site_cs & _MARK_SOUL_CS:
            return None
        if not self.mark_moving and (
            ctx in _MARK_MOVING_CTX or site_cs & _MARK_MOVING_CTX
        ):
            return None
        pre = body[:mstart]
        if pre.strip():
            if _MARK_ROW_TAIL_RX.search(pre):
                return None
        elif top:
            if _MARK_ROW_TAIL_RX.search(self._site_prev):
                return None
        else:
            return None
        post = body[mend:]
        if post.strip():
            if _MARK_ROW_HEAD_RX.match(post):
                return None
        elif top:
            if _MARK_ROW_HEAD_RX.match(self._site_next):
                return None
        else:
            return None
        return self.mark.get(idx)

    def expand_body(
        self, body: str, *, fold_par: bool = False, top: bool = False
    ) -> str:
        r"""字面+ph 交错体展开——token 递归展开后过接缝守卫。

        ``fold_par`` 折叠域 = 本层字面段 + 字面↔ph 接缝；嵌套 ph 展开体
        **内部**的 ``\\n\\n`` 不动——受保环境体的真段落界不属短参 arg 上
        下文（S3）。接缝处理一律剥字面侧（foldable 面），ph 体只读：
        字面尾 ``\\n`` + ph 头 ``\\n`` → 字面退一格；ph 尾 ``\\n`` +
        字面头 ``\\n`` → 字面退一格。ph↔ph 直邻接缝不处理（双侧皆不可
        折叠面，存残留记档）。
        """
        segs: list[str] = []
        prev_ph = False  # segs[-1] 是否 ph 展开体（ph↔ph 接缝无字面侧可剥）

        def push_literal(seg: str) -> None:
            nonlocal prev_ph
            if fold_par:
                seg = PAR_RUN_RX.sub("\n", seg)
                if seg.startswith("\n") and segs and segs[-1].endswith("\n"):
                    seg = seg[1:]
            segs.append(seg)
            prev_ph = False

        def push_ph(tok: str, mstart: int, mend: int) -> None:
            nonlocal prev_ph
            exp = self.expand(tok)
            if (
                fold_par
                and not prev_ph
                and exp.startswith("\n")
                and segs
                and segs[-1].endswith("\n")
            ):
                segs[-1] = segs[-1][:-1]
            seq = self._mark_seq(tok, body, mstart, mend, top=top)
            if seq is not None and exp != tok:
                exp = _mark_open(seq) + exp + _MARK_CLOSE
            segs.append(exp)
            prev_ph = True

        pos = 0
        for mm in PH_RX.finditer(body):
            push_literal(body[pos : mm.start()])
            push_ph(mm.group(0), mm.start(), mm.end())
            pos = mm.end()
        push_literal(body[pos:])
        return seg_join(segs) if self.glue_latin else "".join(segs)


def reconstruct(
    res: ScanResult,
    translations: dict[int, str] | None = None,
    *,
    mark_seq0: int | None = None,
    mark_moving: bool = False,
) -> str:
    r"""按 pieces splice + 占位符 DAG 递归展开（docs/spec/latex-pipeline.md 伪码原样）。

    ``translations``：``{chunk_id: 译文}``；None → identity 重建（永不注锚，
    字节等价原文）。``mark_seq0`` 给本文件 seq 基址——非 None 且有译文时
    ``[[CHUNK_n]]`` 引用点按安全谓词包 ``/TLXC <</MCID 50000+seq>> BDC``
    marked-content 锚（seq = mark_seq0 + chunk 下标）；``mark_moving`` 由
    调用方证明无 ``\\tableofcontents``/``\\listof*``/hyperref 后放行
    moving-arg chunk。
    """
    glue_latin = translations is not None
    marking = translations is not None and mark_seq0 is not None
    ex = _Expander(
        res,
        translation_tokens(res, translations),
        glue_latin=glue_latin,
        mark_seq0=mark_seq0 if marking else None,
        mark_moving=mark_moving,
    )
    # LITERAL 段也可能内嵌 ph（短 run / MINED_ONLY run 发渲染文本）——全段展开。
    if marking:
        sites = _piece_site_map(res)
        out = []
        for i, p in enumerate(res.pieces):
            ex.set_site(
                sites.get(p.span.start, frozenset()),
                res.pieces[i - 1].text[-64:] if i else "",
                res.pieces[i + 1].text[:64] if i + 1 < len(res.pieces) else "",
            )
            out.append(ex.expand_body(p.text, top=True))
    else:
        out = [ex.expand_body(p.text) for p in res.pieces]
    result = seg_join(out) if glue_latin else "".join(out)
    if ex.dangling:
        log.warning(
            "splice unresolved placeholders left literal: %d kinds (e.g. %s)",
            len(ex.dangling),
            ", ".join(sorted(ex.dangling)[:8]),
        )
    if translations:
        result = cjk_glue_fix(result)
        result = cjk_punct_close_guard(result)
    return result


# ---------------------------------------------------------------- validate


@dataclass(slots=True)
class TranslationVerdict:
    """``validate_translation`` 结果。"""

    ok: bool
    missing: list[str] = field(default_factory=list)  # 译文丢失的占位符
    extra: list[str] = field(default_factory=list)  # 译文幻觉出的占位符


def validate_translation(chunk: Chunk, text: str) -> TranslationVerdict:
    """译文侧契约校验：``chunk.placeholders`` 多重集必须逐枚出现在 text 里。

    multiset 语义——``[[MATH_1]]``×2 被译文吃掉一个也算 missing
    （list-membership 版会漏，与 L0 ``Counter`` 口径对齐）。
    """
    want = Counter(chunk.placeholders or PH_RX.findall(chunk.content))
    got = Counter(PH_RX.findall(text))
    missing = sorted((want - got).elements())
    extra = sorted((got - want).elements())
    return TranslationVerdict(
        ok=not missing and not extra, missing=missing, extra=extra
    )


def validate_result(res: ScanResult) -> list[ScanWarning]:  # noqa: C901, PLR0912 — 四类校验各一段，平铺即清单
    """结构校验：孤儿 chunk、死 ph、pieces 非平铺、悬空占位符引用。"""
    warns: list[ScanWarning] = []

    # pieces 平铺不变式：首 start==0 且无缝
    pos = 0
    for k, p in enumerate(res.pieces):
        if p.span.start != pos:
            warns.append(
                ScanWarning(
                    "pieces_gap",
                    p.span.start,
                    f"piece#{k} start={p.span.start} expect={pos}",
                )
            )
            break
        pos = p.span.end
    if res.pieces and res.pieces[0].span.start != 0:
        warns.append(
            ScanWarning("pieces_gap", 0, f"pieces[0].start={res.pieces[0].span.start}")
        )

    # 可达性：protected_tex → ph/chunk → 递归展开
    reachable: set[str] = set()
    stack = list(PH_RX.findall(res.protected_tex))
    while stack:
        tok = stack.pop()
        if tok in reachable:
            continue
        reachable.add(tok)
        m = CHUNK_RX.fullmatch(tok)
        if m:
            idx = int(m.group(1))
            if idx < len(res.chunks):
                stack.extend(PH_RX.findall(res.chunks[idx].content))
            elif tok not in res.ph_reserved:
                warns.append(ScanWarning("dangling_chunk_ref", 0, tok))
            # ``ph_map[CHUNK]`` fallback 体同走 ``expand`` 优先级——内含
            # ``[[EXPAND_n]]`` 引用属可达面，不计 dead_ph
            if tok in res.ph_map:
                stack.extend(PH_RX.findall(res.ph_map[tok]))
        elif tok in res.ph_map:
            stack.extend(PH_RX.findall(res.ph_map[tok]))
        elif tok not in res.ph_reserved:
            warns.append(ScanWarning("dangling_ph", 0, tok))
        # 落到此 = ph_reserved 字面：源文自带 [[X_n]] 是声明保留的过路
        # 文本而非悬空引用，不告警（S2——dangling_chunk_ref 同规豁免）

    for k, c in enumerate(res.chunks):
        if f"[[CHUNK_{c.id}]]" not in reachable:
            warns.append(ScanWarning("orphan_chunk", c.span.start, f"chunk#{k}"))
    warns.extend(
        ScanWarning("dead_ph", 0, ph) for ph in res.ph_map if ph not in reachable
    )
    return warns
