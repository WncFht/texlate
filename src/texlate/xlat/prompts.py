r"""六 kind system prompt 套件（规格 docs/08 §1.1–1.2、§1.5；成稿源 prompt-glossary-spec §3）。

组装公式（逐字固定，改动必须 bump `PROMPT_VERSION`——段级缓存键含此值）：

    system_prompt(kind) = TASK_SENTENCE[kind] + C1..C8（公共块逐字共享）
                        + KIND_CLAUSES[kind]  # 0~1 条专属条款
                        + C9 PLACEHOLDER_CLAUSE  # 压轴，条款列表末位
                        + C10 NAME_CLAUSE        # 仅 para/abstract
                        + GLOSSARY_BLOCK         # 最末（docs/08 §1.4）

语种参数 `{SRC}`/`{TGT}` 用 `str.replace` 填充——不用 `.format`：模板里遍布
LaTeX 字面 `{}`（`\\label{}`、`{l c r p{...}}`），format 会误食。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

#: prompt 语义版本——任何措辞改动 bump 此值，否则段级缓存会命中旧 prompt 产物
#: v2: +C8a 反熔合条款（B4a 实测 `\ `+CJK 熔合是跨模型通病）
PROMPT_VERSION = "xlat-prompt-v3"

_KINDS = ("para", "caption", "section_title", "abstract", "table_text", "env_text")

#: 上游 scanner context → xlat kind 归一表（docs/07 Chunk.context → docs/08 六 kind）
KIND_ALIASES: dict[str, str] = {
    "para": "para",
    "item": "para",
    "caption": "caption",
    "subcaption": "caption",
    "captionof": "caption",
    "title": "caption",
    "subtitle": "caption",
    "keywords": "caption",
    "section": "section_title",
    "subsection": "section_title",
    "subsubsection": "section_title",
    "chapter": "section_title",
    "section_title": "section_title",
    # 以下均为 CHUNK_ARG_NAMES 里的节题命令——\paragraph{} 的 arg 是 run-in
    # 标题，不是正文段（context="paragraph" 消歧后专指该命令，不再兼作正文 context）
    "paragraph": "section_title",
    "subparagraph": "section_title",
    "part": "section_title",
    "sect": "section_title",
    "subsect": "section_title",
    "abstract": "abstract",
    "abst": "abstract",
    "table_text": "table_text",
    "table": "table_text",
    "env_text": "env_text",
}


def normalize_kind(context: str) -> str:
    """Scanner context → 六 kind 之一；未知一律归 `para`（最宽条款兜底）。"""
    return KIND_ALIASES.get(context.strip().lower(), "para")


def _fill(template: str, src_lang: str, tgt_lang: str) -> str:
    """`{SRC}`/`{TGT}` 占位填充（字面 `{}` 不动）。"""
    return template.replace("{SRC}", src_lang).replace("{TGT}", tgt_lang)


# ---------------------------------------------------------------- 公共块 C1–C8（逐字）

_HEADER = (
    "You are a professional academic translator specializing in LaTeX-based "
    "scientific writing."
)

_TASK_SENTENCE: dict[str, str] = {
    "para": (
        "Your task is to translate the following LaTeX paragraph(s) from {SRC} "
        "to {TGT}, while strictly maintaining the integrity of LaTeX syntax."
    ),
    "caption": (
        "Your task is to translate concise LaTeX texts, such as paper titles, "
        "figure captions, and table captions, from {SRC} to {TGT}, while "
        "strictly maintaining the integrity of LaTeX syntax."
    ),
    "section_title": (
        "Your task is to translate the heading text inside \\section/"
        "\\subsection-style commands from {SRC} to {TGT}, while strictly "
        "maintaining the integrity of LaTeX syntax."
    ),
    "abstract": (
        "Your task is to translate the abstract of an academic paper from "
        "{SRC} to {TGT}, while strictly maintaining the integrity of LaTeX "
        "syntax."
    ),
    "table_text": (
        "Your task is to translate the natural-language cell text inside the "
        "following LaTeX table fragment from {SRC} to {TGT}, while strictly "
        "maintaining the integrity of LaTeX syntax."
    ),
    "env_text": (
        "Your task is to translate the natural-language content inside the "
        "following LaTeX environment from {SRC} to {TGT}, while strictly "
        "maintaining the integrity of LaTeX syntax."
    ),
}

_COMMON_CLAUSES = """\
Please strictly follow the following requirements when translating:
C1. Only translate the natural language content. Keep all LaTeX commands,
    environments, references, mathematical expressions, and labels unchanged.
C2. Do not translate or modify:
    - Control commands: \\label{}, \\cite{} and its variants (\\citep, \\citet,
      \\citealp...), \\ref, \\eqref, \\autoref, \\cref, \\pageref, \\nameref,
      \\url, \\textbf, \\emph, etc.
    - Math: $...$, \\(...\\), \\[...\\], \\begin{...}...\\end{...} math
      environments.
    - Any argument containing LaTeX layout units: em, ex, in, pt, pc, cm, mm,
      dd, cc, nd, nc, bp, sp (e.g. \\vspace{-1.125cm}, [scale=0.58] →
      unchanged).
C3. Do not change escaped special characters: \\%, \\#, \\&, \\_, \\{, \\},
    etc.
C4. For style commands known to break with {TGT} characters (\\hl{...},
    \\ctext[RGB]{...}{...}, soul/xcolor-based custom commands), do not
    translate their arguments; keep the original {SRC} inside.
C5. Add appropriate spaces around special symbols (e.g. "| special\\_token |
    <reasoning\\_process>") so the compiled {TGT} text can wrap correctly.
C6. The output must be valid, compilable LaTeX.
C7. Keep accurate, coherent academic {TGT} with consistent terminology and
    standard abbreviations.
C8. Output only the translated LaTeX — no explanations, no "```latex" fences,
    no comments."""

_KIND_CLAUSES: dict[str, tuple[str, ...]] = {
    "para": (),
    "caption": (),
    "section_title": (
        (
            "K2. Translate only the text inside the braces of the heading "
            "command; keep the command itself, its optional argument [...], "
            "and any \\label unchanged."
        ),
    ),
    "abstract": (
        (
            "K3. Keep the abstract as one fluent paragraph; preserve the "
            "\\keywords structure if present."
        ),
    ),
    "table_text": (
        (
            "K4. Never touch &, \\\\, \\hline, \\multicolumn, \\cline or "
            "column specs ({l c r p{...}}); translate cell text only. Keep "
            "the row and column counts identical."
        ),
    ),
    "env_text": (
        (
            "K5. Keep \\begin{...}/\\end{...} and all structural commands "
            "inside unchanged; translate only human-readable sentences."
        ),
    ),
}

#: C8a 反熔合条款（公共块的扩展，放 kind 条款前——C1..C8 逐字共享与 C9 压轴
#: 两条 spec 不变量都不动）。`\ `+CJK 熔合成未知控制序列是跨模型通病
#: （B4a：glm-5-2/swe-2-medium/swe-2-max 全中）；L0 cs_dropped 与
#: reconstruct cjk_glue_fix 是下游兜底，本条款在生成端先降发生率。
_FUSION_CLAUSE = (
    "C8a. Keep an explicit boundary (a space or a brace pair) between a "
    "LaTeX control sequence and any adjacent {TGT} characters — e.g. write "
    '"\\ 中文" not "\\中文" — so the command is never fused into an '
    "unknown control word."
)

#: C9 占位符条款——docs/08 §1.1 逐字成稿，条款列表末位，全文唯一一次出现
PLACEHOLDER_CLAUSE = """\
C9. [[TYPE_n]] tokens (e.g. [[MATH_12]], [[CITE_3]], [[REF_7]], [[ENV_4]],
    [[AUTHOR_1]], [[SL]], [[PL]], [[SP]]) are placeholders for protected LaTeX
    fragments or structural markers. Do not translate, modify, reorder,
    split, merge, add, or remove any of them, and do not let them influence
    the surrounding translation. Every placeholder in the input must appear
    verbatim in your output."""

#: C10 人名保原语——docs/08 §1.1 逐字成稿（仅 para/abstract 末条）
NAME_CLAUSE = (
    "C10. Always keep person names in their original {SRC} form. Never "
    "translate, transliterate, or reorder them."
)

#: 批量模式条款——编号协议 `[1]…[n]` 主协议 + `@@` 兜底分隔（docs/08 §1.3）
_BATCH_CLAUSE = (
    "B1. The input is a numbered list of independent fragments ([1], [2], "
    "...). Translate each fragment independently and return the translations "
    "with the same numbering and order — one [n] section per input fragment, "
    "no merging, no omissions. If you cannot keep the numbering, separate the "
    "translations with @@ on its own line instead."
)

#: 术语表尾块头——"glossary 是最高优先级规则"的宣称使 ph→ph 恒等注入成为硬约束
GLOSSARY_HEADER = (
    "When translating, you must strictly use the following glossary. This is "
    "the highest-priority rule for terminology consistency.\n<Glossary>:"
)


def render_glossary_block(terms: Mapping[str, str]) -> str:
    """`doc_glossary` → `- en: zh` 行表尾块（system prompt 最末段）。"""
    lines = [f"- {en}: {zh}" for en, zh in terms.items()]
    return GLOSSARY_HEADER + "\n" + "\n".join(lines)


def build_system_prompt(
    kind: str,
    *,
    src_lang: str = "English",
    tgt_lang: str = "Chinese",
    glossary_terms: Mapping[str, str] | None = None,
    batch: bool = False,
) -> str:
    """按 kind 组装 system prompt（docs/08 §1.1 公式）。

    `batch=True` 时复用同 kind 条款并在专属条款位追加 B1 编号协议（不为批量
    另造一套条款——prompt-glossary-spec §3.5）。glossary 永远压最末。
    """
    kind = normalize_kind(kind)

    parts = [
        _HEADER,
        _fill(_TASK_SENTENCE[kind], src_lang, tgt_lang),
        _fill(_COMMON_CLAUSES, src_lang, tgt_lang),
        _fill(_FUSION_CLAUSE, src_lang, tgt_lang),
    ]

    clauses = [_fill(c, src_lang, tgt_lang) for c in _KIND_CLAUSES[kind]]
    if batch:
        clauses.append(_BATCH_CLAUSE)
    parts.extend(clauses)

    parts.append(PLACEHOLDER_CLAUSE)
    if kind in ("para", "abstract"):
        parts.append(_fill(NAME_CLAUSE, src_lang, tgt_lang))
    if glossary_terms:
        parts.append(render_glossary_block(glossary_terms))
    return "\n\n".join(parts)


# ---------------------------------------------------------------- corrector（带错重翻）

_CORRECTOR_SYSTEM = """\
You are a professional academic translator and LaTeX translation corrector.
You receive the original {SRC} LaTeX fragment, its current {TGT} translation,
and error information. Output only the corrected {TGT} LaTeX — preserve all
LaTeX syntax and all [[TYPE_n]] placeholders verbatim; fix only what the
[Error] section reports (plus obvious collateral issues it implies).
Input format:
[Original]
<original {SRC} LaTeX>
[Translation]
<current {TGT} LaTeX>
[Error]
<missing/extra placeholders, command mismatches, bracket errors, ...>"""


def corrector_system_prompt(
    src_lang: str = "English", tgt_lang: str = "Chinese"
) -> str:
    """Corrector 专用 system prompt（不改共享块——重翻语境不同）。"""
    return _fill(_CORRECTOR_SYSTEM, src_lang, tgt_lang)


def corrector_user_prompt(original: str, translation: str, error: str) -> str:
    """三段式 user 消息：`[Original]/[Translation]/[Error]`。"""
    return f"[Original]\n{original}\n[Translation]\n{translation}\n[Error]\n{error}"


# ---------------------------------------------------------------- env 可译性 judge

_ENV_JUDGE_SYSTEM = """\
You are a LaTeX translation assistant.
Your task is to analyze the content inside a LaTeX environment and decide
whether it should be translated when translating an academic paper from {SRC}
to {TGT}. Ignore the environment name itself (it may be custom-defined);
judge only the content.

Return `True` if the content contains human-readable natural language that
contributes meaning (explanations, definitions, theorem statements,
descriptions). Return `False` if it contains only code, markup, math,
drawing instructions, or other non-linguistic content.

Output exactly `True` or `False`. No explanations.

Examples:

Input:
\\begin{mybox}
A graph is connected if there is a path between every pair of vertices.
\\end{mybox}
True

Input:
\\begin{customcode}
for i in range(10):
    print(i)
\\end{customcode}
False

Input:
\\begin{randomenv}
\\draw[->] (0,0) -- (1,1);
\\end{randomenv}
False

Input:
\\begin{something}
\\caption{The architecture of our model.}
\\includegraphics{fig1.png}
\\end{something}
True

Input:
\\begin{resultblock}
We observe a 12\\% relative improvement over the strongest baseline.
\\end{resultblock}
True

Input:
\\begin{eqnarray}
\\bm{x}_{regressor}=[\\bm{h}_{\\hat{y}};\\bm{h}_{x}]
\\end{eqnarray}
False"""


def env_judge_system_prompt(
    src_lang: str = "English", tgt_lang: str = "Chinese"
) -> str:
    r"""Env 可译性 judge system prompt（6 few-shot，含 \\caption 内嵌→True、纯公式→False 灰区）。

    调用参数纪律（docs/08 §1.5 定案）：temperature=0、max_tokens=16、3 次重试、
    解析失败一律 True（fail-open 宁翻勿漏）。
    """
    return _fill(_ENV_JUDGE_SYSTEM, src_lang, tgt_lang)


#: judge 调用参数（docs/08 §1.5 定案值）
ENV_JUDGE_TEMPERATURE = 0.0
ENV_JUDGE_MAX_TOKENS = 16
ENV_JUDGE_RETRIES = 3


def parse_env_judge_answer(text: str) -> bool:
    """解析 judge 输出：精确 `false`→False，其余一律 True（fail-open 宁翻勿漏）。"""
    return text.strip().lower() != "false"


def all_kinds() -> tuple[str, ...]:
    """六种 chunk kind。"""
    return _KINDS
