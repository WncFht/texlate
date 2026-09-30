"""specs.qualbench.const — qualbench 常量区（路径钉点 + 判定面正则 + ESA/MQM 词表 + judge 协议串）。

逐行移植自 ``specs/qualbench/__init__.py`` HEAD 单件期常量段——judge prompt
串/类目表/阈值一经改动即换测量语义，须与 PROTOCOL_V/EPOCH 联动评估。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
NOMINATIONS = REPO / "bench" / "nominations"

# ---------------------------------------------------------------- 常量（逐行移植）

#: 占位符 token 同 ANY_PH_RX 口径（独立实现——本 spec 不 import texlate.* 于判定面）
PH_TOKEN_RX = re.compile(r"\[\[[A-Z_]+_\d+\]\]|\[\[[A-Z][A-Z_]*\]\]")
#: zh 中残留英文散文词（≥4 字母，占位符/控制序列先剥掉）——漏翻确定性信号
EN_WORD_RX = re.compile(r"[A-Za-z]{4,}")
CS_RX = re.compile(r"\\[a-zA-Z@]+\*?")
#: ```json 围栏剥皮（网关忽略 response_format，模型可能仍包 fence）
JSON_FENCE_RX = re.compile(
    r"^\s*```[A-Za-z]*\s*\n(?P<body>.*?)\n?\s*```\s*$", re.DOTALL
)
#: 首个平衡 JSON 对象兜底抽取（fence 剥不掉时扫 {...}）
JSON_OBJ_RX = re.compile(r"\{.*\}", re.DOTALL)

#: 协议版本——进 variant，协议切换不静默截留旧测量
PROTOCOL_V = "esa2"
#: spec 测具代次——spec 内部修复（非协议变化）挪 claim 空间用；
#: 两者都进 variant 前段：``esa2@v1|…``
EPOCH = "v1"

#: ESA/MQM 化类目表（六 flag 的 MQM 化 + fluency-register report-only +
#: accuracy-mistranslation 补「在译但错」收容位 + non-translation 整段未翻）
KNOWN_CATEGORIES = (
    "accuracy-omission",
    "accuracy-mistranslation",
    "accuracy-addition",
    "non-translation",
    "terminology",
    "convention-do_not_translate",
    "convention-placeholder",
    "fluency-grammar",
    "fluency-register",
)

#: report-only：不入 derived 罚分、不进 critical 触发
REPORT_ONLY_CATS = frozenset({"fluency-register"})

#: critical 收窄到枚举致命类目（整段未翻/占位符结构报废/增译翻转含义）——
#: 越界 critical 解析侧钳回 major 并计 sev_clamped
CRITICAL_CATS = frozenset(
    {"non-translation", "convention-placeholder", "accuracy-addition"}
)

SEV_WEIGHT = {"minor": 1, "major": 5, "critical": 25}
#: ESA/Freitag 惯例：每段最多记 5 错（derived 取权重最高 5 条）
MAX_ERRORS = 5
#: record 侧最多保留的错误条数（防 judge 超发撑爆 case 行）
MAX_ERRORS_KEPT = 10

#: MQM 类目 → flag 词表（下游 repair/M8 消费口径；保序去重）
CATEGORY_TO_FLAG = {
    "accuracy-omission": "untranslated_spans",
    "non-translation": "untranslated_spans",
    "accuracy-addition": "hallucinated_content",
    "accuracy-mistranslation": "mistranslation",
    "terminology": "term_inconsistency",
    "convention-do_not_translate": "over_translation",
    "convention-placeholder": "placeholder_broken",
    "fluency-grammar": "grammar",
    "fluency-register": "fluency_register",
}

#: judge flag 全集（六 flag + mistranslation/fluency_register 派生值；
#: 未知类目 verbatim 落 cats_extra 留痕）
KNOWN_FLAGS = tuple(dict.fromkeys(CATEGORY_TO_FLAG.values()))

#: judge 池顺位（swe-2-medium 与被评同型自评病灶，永不任 judge）
JUDGE_POOL = ("swe-2-max", "swe-2-high")
JUDGE_BANNED = "swe-2-medium"

#: contested 触发阈值（xlat-quality-eval §7 冻结值）
DELTA_CONTEST = 15
STATED_CONTEST = 55
EN_RESIDUE_CONTEST = 8

#: judge 调用超时（烘焙进 factory——ChatOptions 无 timeout 字段，见头注 DELTA）
JUDGE_TIMEOUT = 300.0

JUDGE_SYSTEM = """\
You are a meticulous bilingual (English to Chinese) translation-quality
annotator for academic LaTeX texts, following the ESA error-annotation
protocol. You will receive:
- Kind: the fragment's role (para | caption | section_title | abstract |
  table_text | env_text).
- Source: the original English LaTeX fragment. [[TYPE_n]] tokens (e.g.
  [[MATH_12]], [[CITE_3]], [[REF_7]], [[SL]], [[PL]]) are opaque placeholders
  for protected LaTeX/math/citation fragments — they must appear verbatim in
  the translation.
- Translation: the Chinese translation produced by a machine translator.

Step 1 — identify EVERY error span in the TRANSLATION (at most 5: report
the 5 most severe). For each error report:
- "span": the exact substring of the Translation where the error occurs
  (copy it verbatim; for whole-segment errors repeat the full translation).
- "category": exactly one of
  "accuracy-omission" (source content dropped or left untranslated),
  "accuracy-mistranslation" (meaning distorted vs the source),
  "accuracy-addition" (content invented, absent from the source),
  "non-translation" (the whole segment left untranslated),
  "terminology" (technical term mistranslated or used inconsistently),
  "convention-do_not_translate" (content that must stay unchanged was
    translated: person names, citation/bibliography entries, math or LaTeX
    commands),
  "convention-placeholder" (a [[TYPE_n]] placeholder missing, invented,
    renamed, or its immediate surroundings garbled),
  "fluency-grammar" (ungrammatical or garbled Chinese),
  "fluency-register" (register/style mismatch for academic prose, e.g.
    machine-translation flavor — report only, does not affect the score).
- "severity": "minor" (doesn't change meaning; slight awkwardness),
  "major" (changes or obscures meaning, breaks readability, or violates a
    hard convention such as a lost placeholder),
  "critical" (ONLY for: non-translation of the whole segment; broken
    placeholders leaving the text structurally unusable; added content
    that inverts the source meaning).
- "note": <=40 chars describing the error.

Rules:
- Judge ONLY translation quality (faithfulness + fluency), not LaTeX
  compilability. Judge against the Kind's expectations (a section_title is
  a concise heading, a caption a compact legend).
- Do NOT mark an error for content correctly left in English (person
  names, citation/bibliography entries, math placeholders).
- A Source fragment containing [[BIB_n]] tokens is a bibliography
  region the pipeline intentionally keeps in English: a Translation
  identical to the Source there is CORRECT — do not flag
  non-translation or any other error for it.
- If the translation is fully correct, return an empty error list.

Step 2 — after the error list, give "score": your overall 0-100 quality
score for the translation (100 = perfect; use the full scale).

Output STRICT JSON only — no markdown fence, no commentary:
{"errors": [{"span": "...", "category": "...", "severity": "...", "note": "..."}], "score": <int 0-100>}"""

JUDGE_RETRY_SUFFIX = (
    "\n\nYour previous reply was not parseable JSON. Reply with ONLY the JSON "
    'object: {"errors": [{"span": "...", "category": "...", "severity": '
    '"...", "note": "..."}], "score": <int 0-100>}'
)
