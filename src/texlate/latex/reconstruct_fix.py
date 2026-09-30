r"""``latex.reconstruct_fix`` — splice 译文侧修正链（``reconstruct`` god-file 机械拆分叶）。

``translations`` 落盘前的逐条/全局修正：``_restore_linestarts`` 行首
``\cs`` 归位 → ``unicode_math_fix`` → ``LATIN_ITEM_RX`` 保险丝（
``translation_tokens`` 逐条同序施加）；splice 后 ``cjk_glue_fix``/
``cjk_punct_close_guard``/``dblbrace_arg_fix`` 全局修正；``seg_join``
接缝守卫平铺/展开两级共用。全部只在有译文时启用——identity 路径
保持逐字节。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from texlate.latex.placeholder import PH_RX
from texlate.textutil import CJK_RANGES, mask_tex, needs_seam_space

if TYPE_CHECKING:
    from texlate.latex.model import ScanResult, Span

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


#: 引用/标签族 ``\cs{{key}}`` 双层花括形（译文侧偶发机械错——1003.0675
#: ``\ref{{key}}`` ×13 实证，内层组使 key 名带上 ``{}`` 即 undefined ref）。
#: 仅当外层组恰为单层内组时折叠（``{a{b}c}``/``{{a},{b}}`` 非机械形不收），
#: 名字长名在前免 ``cite`` 前缀吞 ``citep``/``citet`` 命中。
_DBL_BRACE_ARG_RX = re.compile(
    r"\\(citealp|citep|citet|autoref|eqref|pageref|nameref|footref"
    r"|footnote|label|cref|Cref|cite|ref)(\*?)[ \t]*\{\s*\{([^{}]*)\}\s*\}"
)


def dblbrace_arg_fix(s: str) -> str:
    r"""``\ref{{key}}`` → ``\ref{key}``：译文双层花括机械折叠（splice 后归一）。

    只在译文路径启用（identity 面保持逐字节）；命中点取 ``mask_tex``
    遮盖视图——verbatim/comment 体内的字面 ``{{}}`` 不动——原串逆序
    回放替换（``_insert_masked`` 同骨架，插换同位）。
    """
    masked = mask_tex(s)
    edits = [
        (
            m.start(),
            m.end(),
            "\\" + m.group(1) + (m.group(2) or "") + "{" + m.group(3) + "}",
        )
        for m in _DBL_BRACE_ARG_RX.finditer(masked)
    ]
    for start, end, repl in reversed(edits):
        s = s[:start] + repl + s[end:]
    return s


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
#: 捕获组保留分隔符——``re.split`` 产出 [文本，token, 文本，...] 交错序列。
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
