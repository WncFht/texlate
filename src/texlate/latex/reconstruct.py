r"""splice 重建 + DAG 递归展开 + validate（docs/07 §9）。

- **identity**：``translations=None`` → 平铺 pieces + ph 体逐字 → 逐字节 = 原文。
- O(总规模)+memo；相对 spike ``str.replace`` 不动点语义等价
  （同一替换表迭代至不动点 ≡ DAG 递归展开；构造上无环，assert 兜底）。
- **译文侧契约**：译文必须保留 ``chunk.placeholders`` 全列；
  :func:`validate_translation` 校验缺失/幻觉占位符（由 translate 层消费）。
- ``cjk_glue_fix``（``\\cmd这是`` → 插空格）是 post-reconstruct 全局修正一步，
  只在有译文时启用（identity 路径保持逐字节）。
- ``unicode_math_fix``（译文里游离的 ``β``/``∂`` → ``$\beta$``/``$\partial$``）
  是 pre-splice 的逐条译文修正——文本字体没有这些字形，缺字判据见 judge。
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from texlate.latex.model import Chunk, ScanResult, ScanWarning
from texlate.latex.placeholder import CHUNK_RX, PH_RX
from texlate.textutil import CJK_RANGES, mask_tex

_CJK_RX = re.compile(
    r"(\\[a-zA-Z@]+\\*?)(?=["
    + "".join(f"{chr(lo)}-{chr(hi)}" if lo != hi else chr(lo) for lo, hi in CJK_RANGES)
    + "])"
)


def cjk_glue_fix(s: str) -> str:
    r"""``\cmd这是`` → ``\cmd 这是``：控制字后直接贴 CJK 时插空格。

    控制字后随空格在 TeX 里被吸收 → 源码语义不变，渲染更稳。
    命中点在 ``mask_tex`` 视图上找——verbatim/comment 体内的 ``\cmd中``
    是字面内容，不可编辑（等长遮盖位对齐，逆序回放）。
    """
    hits = [m.end() for m in _CJK_RX.finditer(mask_tex(s))]
    for pos in reversed(hits):
        s = s[:pos] + " " + s[pos:]
    return s


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


def reconstruct(res: ScanResult, translations: dict[int, str] | None = None) -> str:
    """按 pieces splice + 占位符 DAG 递归展开（docs/07 §9 伪码原样）。

    ``translations``：``{chunk_id: 译文}``；None → identity 重建。
    """
    trans = (
        {}
        if translations is None
        else {f"[[CHUNK_{k}]]": unicode_math_fix(v) for k, v in translations.items()}
    )
    memo: dict[str, str] = {}
    chunks = res.chunks
    active: set[str] = set()

    def expand(token: str) -> str:  # token 形如 [[X_n]]
        if token in memo:
            return memo[token]
        if token in active:
            return token  # 译文侧自指/互指环（ph_map 构造上无环）→ 留字面
        active.add(token)
        body = trans.get(token)
        if body is None:
            body = res.ph_map.get(token)
        if body is None:
            m = CHUNK_RX.fullmatch(token)
            idx = int(m.group(1)) if m else -1
            body = chunks[idx].content if 0 <= idx < len(chunks) else token
        memo[token] = PH_RX.sub(lambda mm: expand(mm.group(0)), body)
        active.discard(token)
        return memo[token]

    # LITERAL 段也可能内嵌 ph（短 run / MINED_ONLY run 发渲染文本）——全段展开。
    out = [PH_RX.sub(lambda m: expand(m.group(0)), p.text) for p in res.pieces]
    result = "".join(out)
    if translations:
        result = cjk_glue_fix(result)
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


def validate_result(res: ScanResult) -> list[ScanWarning]:  # noqa: C901 — 四类校验各一段，平铺即清单
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
            else:
                warns.append(ScanWarning("dangling_chunk_ref", 0, tok))
        elif tok in res.ph_map:
            stack.extend(PH_RX.findall(res.ph_map[tok]))
        else:
            warns.append(ScanWarning("dangling_ph", 0, tok))

    for k, c in enumerate(res.chunks):
        if f"[[CHUNK_{c.id}]]" not in reachable:
            warns.append(ScanWarning("orphan_chunk", c.span.start, f"chunk#{k}"))
    warns.extend(
        ScanWarning("dead_ph", 0, ph) for ph in res.ph_map if ph not in reachable
    )
    return warns
