#!/usr/bin/env python3
r"""qualbench — 翻译质量评测臂：LLM-judge 给 (src_en, zh) chunk 对打分。

现有 bench 全是结构指标（identity/leak/编译成功率/锚点保持），没有译文质量
度量——本脚本补这条臂：对管线真实产出的 chunk 对跑 LLM-judge，输出
ESA 协议 errors[]+stated100 + 派生六类 flag，按 paper/model/kind 聚合出报告。
judge 模型与被评模型解耦（--judge-model），支持离线 mock judge 全链自检。

chunk 对来源（--source）：
  state   已有 xlat 产物树的 StateStore 落盘——``--state-root`` 下递归找
          ``state.json``，``results[]`` 末行胜取 (source, translation, kind,
          status)。兼容两种布局：e2e_real 的 ``_xlat_state/{safe_id}/`` 与
          stagerun 的 ``work/{id}/xlat-state/{arm}/``；翻译模型取
          ``meta.model``（stagerun 臂名记进 ``arm`` 字段）。只评
          ok/partial 且译文≠原文的块；skipped/fault 计数进 meta 不送 judge。
  corpus  干净机自检臂：corpus ``{id}/extracted/*.tex`` 按空行切段、
          内置确定性 mock 翻译（占位符/控制序列原位保留，散文 run →
          固定中文串），不 import texlate.* 也能把全链跑通。

judge 协议（ESA 两步单发，``protocol_v=esa2``；规格见
docs/research/methods/xlat-quality-eval-2026-09-18.md §7）：
  judge 先标错误 span（须为译文逐字子串）再赋 0-100 分——gemba_esa 同款
  形态（WMT24 prompt 系最强 reference-free 指标）。输出严格 JSON
  ``{"errors":[{span,category,severity,note}], "score":0-100}``；``` 围栏
  剥皮 + 首个 {...} 兜底，解析失败补问一次，再败记 judge_error。
  类目表 = 六 flag 的 MQM 化：accuracy-omission/mistranslation/addition、
  non-translation、terminology、convention-do_not_translate（窄枚举防
  GEMBA-MQM locale 滥用）、convention-placeholder、fluency-grammar、
  fluency-register（report-only 不入罚分）。severity minor/major/critical，
  critical 收窄到枚举致命类目（整段未翻/占位符结构报废/增译翻转含义）。
  主分取 stated100；derived100=100-Σ(minor1/major5/critical25，权重最高
  5 条）只作自洽校验——|Δ| 超阈进 contested。
  judge 路由：主 swe-2-max；二裁 swe-2-high，触发 |Δ|>15、stated≤55、
  任一 critical、L0 信号矛盾（ph 缺失/en_residue≥8 但 judge 未报对应
  类目）。judge≠translator 按 chunk 级 meta.model 强制；swe-2-medium
  永不任 judge。judge 调用直接 httpx 打 OpenAI /v1/chat/completions
  ——不 import texlate.xlat（--judge-temperature 默认 0.1：3033 网关
  temperature=0 直接 502；--judge-max-tokens 默认 8192 给 reasoning
  留预算；--judge-timeout 默认 300s）。

续跑：records.jsonl 逐块 append，key=``{model}|{paper}|{chunk}|{judge}|{protocol_v}``
——协议切换后旧协议记录不再截留新协议产出；已有该 key 且带 score 的行
跳过（error 行重跑）。抽样：``--papers``  seed 抽篇 + ``--per-paper`` 按
kind 轮转取块保类型多样，``--n`` 全局封顶（跨篇轮转序取前 n，小样本天然
跨篇分散）；``--source manifest`` 直接吃 qualsample 冻结的 sample.jsonl。

用法:
  uv run python bench/py/qualbench.py pairs  [--source state] [--papers 5]
  uv run python bench/py/qualbench.py run --mock-judge --papers 5 --per-paper 6
  uv run python bench/py/qualbench.py run --judge-model swe-2-max \
      --n 3 --out bench/results/qualbench-2026-09-16/smoke
  uv run python bench/py/qualbench.py run --source manifest \
      --manifest bench/results/qualbase/sample.jsonl --concurrency 4
  uv run python bench/py/qualbench.py report DIR
产出: DIR/{records.jsonl,report.md,run_meta.json}
依赖: uv venv（仅 httpx）；state 源要 e2e_real/stagerun 已跑的 state.json。
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import random
import re
import statistics
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import benchlib

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATE_ROOT = ROOT / "bench/work_e2ereal/_xlat_state"
DEFAULT_CORPUS = ROOT / "bench/corpus"

# ---------------------------------------------------------------- 常量

#: 占位符 token 同 ANY_PH_RX 口径（独立实现——本脚本不 import texlate.*）
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

#: 协议版本——进 resume key，协议切换不静默截留旧记录
PROTOCOL_V = "esa2"

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
#: record 侧最多保留的错误条数（防 judge 超发撑爆 jsonl 行）
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


# ---------------------------------------------------------------- chunk 对
@dataclass
class Pair:
    """一个待评 chunk 对。``model`` 是产出该译文的翻译模型。"""

    paper: str
    chunk_id: str
    kind: str
    model: str
    src: str
    zh: str
    arm: str = ""
    status: str = "ok"

    @property
    def key(self) -> str:
        return f"{self.model}|{self.paper}|{self.chunk_id}"


#: ``safe_id`` 单层目录名 → 论文 id——单源下沉 ``benchlib.canon_id``，保名。
_un_safe_id = benchlib.canon_id


def _state_files(roots: list[Path]) -> list[tuple[Path, str, str]]:
    """``--state-root`` 下递归找 state.json → [(path, paper, arm)]。

    布局识别：路径含 ``xlat-state/{arm}``（stagerun）→ paper=其上一级目录、
    arm=下一级；否则 paper=state.json 所在目录名（e2e_real ``_xlat_state``
    布局），arm=""。
    """
    out: list[tuple[Path, str, str]] = []
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("state.json")):
            parts = p.relative_to(root).parts
            if "xlat-state" in parts:
                i = parts.index("xlat-state")
                paper = _un_safe_id(parts[i - 1]) if i else p.parent.parent.name
                arm = parts[i + 1] if i + 1 < len(parts) - 1 else ""
            else:
                paper = _un_safe_id(p.parent.name)
                arm = ""
            out.append((p, paper, arm))
    return out


def collect_state_pairs(args: argparse.Namespace) -> tuple[list[Pair], dict]:
    """state.json 树 → 待评 chunk 对 + meta（skipped/fault 计数留痕）。"""
    files = _state_files([Path(r) for r in args.state_root])
    want_ids = (
        {i.strip() for i in args.ids.split(",") if i.strip()} if args.ids else None
    )
    kinds = (
        {k.strip() for k in args.kinds.split(",") if k.strip()} if args.kinds else None
    )
    rng = random.Random(args.seed)
    entries = [(p, paper, arm) for p, paper, arm in files]
    if want_ids is not None:
        entries = [e for e in entries if e[1] in want_ids]
    else:
        rng.shuffle(entries)
        entries = entries[: args.papers] if args.papers else entries
    entries.sort(key=lambda e: e[1])

    pairs: list[Pair] = []
    meta_papers: list[dict] = []
    for path, paper, arm in entries:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        model = str((data.get("meta") or {}).get("model") or "?")
        last: dict[str, dict] = {}
        n_dead = 0
        for r in data.get("results") or []:
            last[str(r.get("chunk_id"))] = r
        cands: dict[str, list[dict]] = {}
        for r in last.values():
            zh = str(r.get("translation") or "")
            src = str(r.get("source") or "")
            status = str(r.get("status") or "")
            if status not in ("ok", "partial") or zh == src:
                n_dead += 1
                continue
            kind = str(r.get("kind") or "para")
            if kinds and kind not in kinds:
                continue
            if not (args.min_chars <= len(src) <= args.max_chars):
                continue
            cands.setdefault(kind, []).append(r)
        # kind 轮转抽样：桶内 seed 洗牌后逐桶轮取，保类型多样
        picked: list[dict] = []
        buckets = list(cands.values())
        for b in buckets:
            rng.shuffle(b)
        while sum(len(b) for b in buckets) and (
            not args.per_paper or len(picked) < args.per_paper
        ):
            progressed = False
            for b in buckets:
                if b and (not args.per_paper or len(picked) < args.per_paper):
                    picked.append(b.pop())
                    progressed = True
            if not progressed:
                break
        pairs.extend(
            Pair(
                paper=paper,
                chunk_id=str(r.get("chunk_id")),
                kind=str(r.get("kind") or "para"),
                model=model,
                src=str(r.get("source") or ""),
                zh=str(r.get("translation") or ""),
                arm=arm,
                status=str(r.get("status") or "ok"),
            )
            for r in picked
        )
        state_abs = path.resolve()
        meta_papers.append(
            {
                "id": paper,
                "model": model,
                "arm": arm,
                "n_pairs": len(picked),
                "n_unjudged": n_dead,
                "state": (
                    str(state_abs.relative_to(ROOT))
                    if state_abs.is_relative_to(ROOT)
                    else str(state_abs)
                ),
            }
        )
    # 跨篇轮转序：--n 小样本天然分散到不同论文
    by_paper: dict[str, list[Pair]] = {}
    for pr in pairs:
        by_paper.setdefault(pr.paper, []).append(pr)
    ordered: list[Pair] = []
    queues = [by_paper[k] for k in sorted(by_paper)]
    while any(queues):
        ordered.extend(q.pop(0) for q in queues if q)
    if args.n:
        ordered = ordered[: args.n]
    return ordered, {"papers": meta_papers}


# ---------------------------------------------------------------- corpus mock 源

_MOCK_ZH = "这是译文"
_MOCK_TOKEN_RX = re.compile(
    r"\[\[[A-Z_]+_\d+\]\]|\[\[[A-Z][A-Z_]*\]\]|\\[a-zA-Z@]+\*?|\\(?!\[\[).|[][(){}|~$&]"
)
_PROSE_RUN_RX = re.compile(r"[a-zA-Z][^\n]*[a-zA-Z]|[a-zA-Z]")
#: corpus 切段时跳过的 preamble/非散文块信号
_SKIP_BLOCK_RX = re.compile(
    r"\\documentclass|\\usepackage|\\begin\{document\}|\\bibliography\{|"
    r"\\begin\{(?:verbatim|lstlisting|minted)"
)
_ASCII_WORDS_RX = re.compile(r"[A-Za-z]{2,}")


def _mock_translate(text: str) -> str:
    """确定性 mock 译文：占位符/控制序列/括号原位保留，散文 run → 固定中文。"""
    out: list[str] = []
    pos = 0
    for m in _MOCK_TOKEN_RX.finditer(text):
        out.append(_PROSE_RUN_RX.sub(_MOCK_ZH, text[pos : m.start()]))
        out.append(m.group(0))
        pos = m.end()
    out.append(_PROSE_RUN_RX.sub(_MOCK_ZH, text[pos:]))
    return "".join(out)


def collect_corpus_pairs(args: argparse.Namespace) -> tuple[list[Pair], dict]:
    """corpus extracted/*.tex 空行切段 + 内置 mock 翻译 → 待评对。"""
    corpus = Path(args.corpus_root)
    rng = random.Random(args.seed)
    want_ids = (
        {i.strip() for i in args.ids.split(",") if i.strip()} if args.ids else None
    )
    dirs = sorted(d for d in corpus.iterdir() if (d / "extracted").is_dir())
    if want_ids is not None:
        dirs = [d for d in dirs if d.name in want_ids]
    else:
        rng.shuffle(dirs)
        dirs = dirs[: args.papers] if args.papers else dirs
        dirs.sort(key=lambda d: d.name)

    pairs: list[Pair] = []
    meta_papers: list[dict] = []
    for d in dirs:
        blocks: list[tuple[str, str]] = []  # (chunk_id, src)
        for fi, f in enumerate(sorted((d / "extracted").rglob("*.tex"))):
            try:
                text = f.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            for bi, raw_blk in enumerate(re.split(r"\n\s*\n", text)):
                blk = raw_blk.strip()
                if not (args.min_chars <= len(blk) <= args.max_chars):
                    continue
                if len(_ASCII_WORDS_RX.findall(blk)) < 3:
                    continue
                if _SKIP_BLOCK_RX.search(blk):
                    continue
                blocks.append((f"{fi}:{bi}", blk))
        rng.shuffle(blocks)
        picked = blocks[: args.per_paper] if args.per_paper else blocks
        pairs.extend(
            Pair(
                paper=d.name,
                chunk_id=cid,
                kind="para",
                model="mock-translator",
                src=src,
                zh=_mock_translate(src),
            )
            for cid, src in picked
        )
        meta_papers.append(
            {"id": d.name, "model": "mock-translator", "n_pairs": len(picked)}
        )
    if args.n:
        pairs = pairs[: args.n]
    return pairs, {"papers": meta_papers}


# ---------------------------------------------------------------- 确定性信号
def pair_signals(src: str, zh: str) -> dict:
    """每对都算的免费确定性特征——judge flag 的对照底账。"""
    from collections import Counter

    src_ph = Counter(PH_TOKEN_RX.findall(src))
    zh_ph = Counter(PH_TOKEN_RX.findall(zh))
    missing = src_ph - zh_ph
    invented = zh_ph - src_ph
    zh_clean = CS_RX.sub(" ", PH_TOKEN_RX.sub(" ", zh))
    return {
        "ph_missing": sum(missing.values()),
        "ph_invented": sum(invented.values()),
        "en_residue": len(EN_WORD_RX.findall(zh_clean)),
        "src_bib": "[[BIB_" in src,
        "src_chars": len(src),
        "zh_chars": len(zh),
    }


# ---------------------------------------------------------------- judge
def _norm_parsed(errs_raw: object, score: int) -> dict:
    """errors 列表规范化 + 衍生字段（parse_esa_json 与 mock 路径共用）。

    - 类目不在 KNOWN_CATEGORIES → verbatim 保留 + 计 cats_extra
    - severity 不在三档 → 钳 minor 计 sev_clamped；critical 落在
      CRITICAL_CATS 外 → 钳 major 计 sev_clamped
    - derived100 = 100 − Σ 权重最高 MAX_ERRORS 条（report-only 类豁免）
    """
    errors: list[dict] = []
    cats_extra: list[str] = []
    sev_clamped = 0
    for e in (errs_raw if isinstance(errs_raw, list) else [])[:MAX_ERRORS_KEPT]:
        if not isinstance(e, dict):
            continue
        cat = str(e.get("category") or "?")
        sev = str(e.get("severity") or "minor").lower()
        if sev not in SEV_WEIGHT:
            sev = "minor"
            sev_clamped += 1
        elif sev == "critical" and cat not in CRITICAL_CATS:
            sev = "major"
            sev_clamped += 1
        if cat not in KNOWN_CATEGORIES:
            cats_extra.append(cat)
        errors.append(
            {
                "span": str(e.get("span") or ""),
                "category": cat,
                "severity": sev,
                "note": str(e.get("note") or "")[:80],
            }
        )
    derived = derived100(errors)
    return {
        "errors": errors,
        "stated100": score,
        "derived100": derived,
        "score_delta": score - derived,
        "cats_extra": sorted(set(cats_extra)),
        "sev_clamped": sev_clamped,
    }


def derived100(errors: list[dict]) -> int:
    """规则聚合：100 − Σ severity 权重（权重最高 MAX_ERRORS 条，report-only 豁免）。"""
    pen = sorted(
        (
            SEV_WEIGHT[e["severity"]]
            for e in errors
            if e["category"] not in REPORT_ONLY_CATS
        ),
        reverse=True,
    )[:MAX_ERRORS]
    return max(0, 100 - sum(pen))


def flags_of(errors: list[dict]) -> list[str]:
    """errors 类目 → flag 词表（下游消费口径；保序去重）。"""
    out: list[str] = []
    for e in errors:
        f = CATEGORY_TO_FLAG.get(e["category"])
        if f and f not in out:
            out.append(f)
    return out


def verify_spans(errors: list[dict], zh: str) -> list[dict]:
    """就地写 span_verified——span 须为译文逐字子串。"""
    for e in errors:
        e["span_verified"] = bool(e["span"]) and e["span"] in zh
    return errors


def contest_reasons(parsed: dict, sig: dict) -> list[str]:
    """contested 触发：|Δ|>15 / stated≤55 / 任一 critical / L0 信号矛盾。"""
    reasons: list[str] = []
    if abs(parsed["score_delta"]) > DELTA_CONTEST:
        reasons.append("delta_gt15")
    if parsed["stated100"] <= STATED_CONTEST:
        reasons.append("stated_le55")
    if any(e["severity"] == "critical" for e in parsed["errors"]):
        reasons.append("critical_present")
    cats = {e["category"] for e in parsed["errors"]}
    if (sig["ph_missing"] or sig["ph_invented"]) and (
        "convention-placeholder" not in cats
    ):
        reasons.append("l0_ph_unreported")
    if (
        sig["en_residue"] >= EN_RESIDUE_CONTEST
        and not ({"accuracy-omission", "non-translation"} & cats)
        and not sig["src_bib"]
    ):
        reasons.append("l0_en_unreported")
    return reasons


def mock_judge(pair: Pair) -> dict:
    """确定性 mock judge（ESA 形态）：按确定性信号出 errors+stated100。"""
    sig = pair_signals(pair.src, pair.zh)
    raw_errors: list[dict] = []
    if sig["src_bib"]:
        # bib 直通语境：zh≡src 是正确态——占位符守恒外零错误。
        if sig["ph_missing"] or sig["ph_invented"]:
            raw_errors.append(
                {
                    "span": "[[",
                    "category": "convention-placeholder",
                    "severity": "major",
                    "note": "placeholder mismatch",
                }
            )
            return _norm_parsed(raw_errors, 70)
        return _norm_parsed(raw_errors, 95)
    if pair.zh.strip() == pair.src.strip() or not pair.zh.strip():
        raw_errors.append(
            {
                "span": pair.zh[:80] or " ",
                "category": "non-translation",
                "severity": "critical",
                "note": "zh==src",
            }
        )
        return _norm_parsed(raw_errors, 5)
    if sig["ph_missing"] or sig["ph_invented"]:
        raw_errors.append(
            {
                "span": "[[",
                "category": "convention-placeholder",
                "severity": "major",
                "note": "placeholder mismatch",
            }
        )
    if sig["en_residue"] >= 8:
        w = EN_WORD_RX.search(CS_RX.sub(" ", PH_TOKEN_RX.sub(" ", pair.zh)))
        raw_errors.append(
            {
                "span": w.group(0) if w else pair.zh[:40],
                "category": "accuracy-omission",
                "severity": "major",
                "note": f"en_residue={sig['en_residue']}",
            }
        )
    elif sig["en_residue"] >= 3:
        raw_errors.append(
            {
                "span": pair.zh[:40],
                "category": "accuracy-omission",
                "severity": "minor",
                "note": f"en_residue={sig['en_residue']}",
            }
        )
    if not raw_errors:
        # sha 奇偶给 90/97 的确定性分布——聚合面能被真实走到
        stated = (
            90
            if int(hashlib.sha256(pair.key.encode()).hexdigest(), 16) % 3 == 0
            else 97
        )
    else:
        stated = (
            100
            - 10 * len(raw_errors)
            - (15 if sig["ph_missing"] or sig["ph_invented"] else 0)
        )
    return _norm_parsed(raw_errors, max(0, stated))


def parse_esa_json(raw: str) -> dict | None:
    """judge ESA 输出 → parsed dict；fence 剥皮 + {...} 兜底；不合格 None。"""
    m = JSON_FENCE_RX.match(raw)
    body = m.group("body") if m else raw
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        m2 = JSON_OBJ_RX.search(body)
        if not m2:
            return None
        try:
            data = json.loads(m2.group(0))
        except json.JSONDecodeError:
            return None
    if not isinstance(data, dict):
        return None
    if not isinstance(data.get("errors"), list):
        return None
    score = data.get("score")
    if isinstance(score, float) and score.is_integer():
        score = int(score)
    if isinstance(score, str) and score.strip().isdigit():
        score = int(score.strip())
    if not isinstance(score, int) or isinstance(score, bool) or not 0 <= score <= 100:
        return None
    return _norm_parsed(data["errors"], score)


def route_judge(pair: Pair, preferred: str) -> str | None:
    """judge 路由：preferred 非 banned（与被评同型/swe-2-medium）即用，否则池内顺位。"""
    banned = {pair.model, JUDGE_BANNED}
    if preferred and preferred not in banned:
        return preferred
    for m in JUDGE_POOL:
        if m not in banned:
            return m
    return None


def judge_user_prompt(pair: Pair) -> str:
    """结构化 user 消息：Kind/Source/Translation 三段。"""
    return f"[Kind]\n{pair.kind}\n\n[Source]\n{pair.src}\n\n[Translation]\n{pair.zh}"


async def call_judge(
    http,
    pair: Pair,
    model: str,
    *,
    max_tokens: int,
    user_suffix: str = "",
    tries: int = 3,
) -> dict:
    """一次 judge 调用（429/5xx/传输错指数退避）；返回 raw content + 计量。"""
    url = f"{http['base_url']}/v1/chat/completions"
    messages = [
        {"role": "system", "content": JUDGE_SYSTEM},
        {"role": "user", "content": judge_user_prompt(pair) + user_suffix},
    ]
    last_err = ""
    for attempt in range(tries):
        t0 = time.monotonic()
        try:
            resp = await http["client"].post(
                url,
                headers={"Authorization": f"Bearer {http['api_key']}"},
                json={
                    "model": model,
                    "messages": messages,
                    "temperature": http["temperature"],
                    "max_tokens": max_tokens,
                },
                timeout=http["timeout"],
            )
        except Exception as e:
            last_err = f"transport: {e!r:.200}"
            await asyncio.sleep(min(2**attempt * 2, 20))
            continue
        dt = round(time.monotonic() - t0, 2)
        if resp.status_code == 200:
            try:
                payload = resp.json()
            except json.JSONDecodeError:
                return {"error": f"non-JSON body: {resp.text[:160]}", "seconds": dt}
            choices = payload.get("choices")
            ch = choices[0] if isinstance(choices, list) and choices else {}
            if not isinstance(ch, dict):
                ch = {}
            msg = ch.get("message") or {}
            content = msg.get("content") or ""
            usage = payload.get("usage") or {}
            return {
                "content": content,
                "reasoning_chars": len(msg.get("reasoning_content") or ""),
                "finish": ch.get("finish_reason") or "",
                "seconds": dt,
                "tok_in": usage.get("prompt_tokens"),
                "tok_out": usage.get("completion_tokens"),
            }
        last_err = f"http {resp.status_code}: {resp.text[:200]}"
        # 4xx（除 408/429）重试无意义
        if resp.status_code not in (408, 429) and resp.status_code < 500:
            break
        await asyncio.sleep(min(2**attempt * 3, 30))
    return {"error": last_err or "unknown"}


def shape_judged(parsed: dict, pair: Pair, sig: dict) -> dict:
    """parsed ESA + pair/确定性信号 → record 判定字段块（span 校验 + contested）。"""
    verify_spans(parsed["errors"], pair.zh)
    reasons = contest_reasons(parsed, sig)
    return {
        "stated100": parsed["stated100"],
        "score": parsed["stated100"],
        "derived100": parsed["derived100"],
        "score_delta": parsed["score_delta"],
        "errors": parsed["errors"],
        "n_errors": len(parsed["errors"]),
        "n_span_unverified": sum(1 for e in parsed["errors"] if not e["span_verified"]),
        "sev_counts": {
            s: sum(1 for e in parsed["errors"] if e["severity"] == s)
            for s in SEV_WEIGHT
        },
        "sev_clamped": parsed.get("sev_clamped", 0),
        "cats_extra": parsed.get("cats_extra", []),
        "flags": flags_of(parsed["errors"]),
        "contested": bool(reasons),
        "contest_reasons": reasons,
    }


async def judge_pair(http, pair: Pair, args: argparse.Namespace) -> dict:
    """ESA 流程：主裁一次调用 → parse/verify/contest → 触规则 swe-2-high 二裁。"""
    jm = route_judge(pair, args.judge_model)
    if jm is None:
        return {"judge_error": f"no_eligible_judge(translator={pair.model})"}
    r = await call_judge(http, pair, jm, max_tokens=args.judge_max_tokens)
    if "content" not in r:
        return {**r, "judge_model_used": jm}
    parsed = parse_esa_json(r["content"])
    if parsed is None:
        # 补问一次：user 带严格 JSON 提醒后缀
        r2 = await call_judge(
            http,
            pair,
            jm,
            max_tokens=args.judge_max_tokens,
            user_suffix=JUDGE_RETRY_SUFFIX,
        )
        if "content" in r2:
            parsed = parse_esa_json(r2["content"])
            r = {**r2, "reparsed": True, "raw_first": r["content"][:200]}
    if parsed is None:
        return {
            **r,
            "judge_model_used": jm,
            "judge_error": "unparseable",
            "raw": r.get("content", "")[:300],
        }
    out = {
        "judge_model_used": jm,
        **shape_judged(parsed, pair, pair_signals(pair.src, pair.zh)),
        "seconds": r.get("seconds"),
        "tok_in": r.get("tok_in"),
        "tok_out": r.get("tok_out"),
        "reasoning_chars": r.get("reasoning_chars"),
        "finish": r.get("finish"),
        "reparsed": r.get("reparsed"),
        "raw": r.get("content", "")[:500],
    }
    # contested → 二裁（judge2 块落 record 备查，主分仍取主裁 stated）
    if out["contested"] and not args.no_second:
        jm2 = route_judge(pair, args.second_model)
        if jm2 is None or jm2 == jm:
            out["judge2"] = {"judge2_error": "no_eligible_second"}
        else:
            r2nd = await call_judge(http, pair, jm2, max_tokens=args.judge_max_tokens)
            if "content" in r2nd:
                p2 = parse_esa_json(r2nd["content"])
                if p2 is not None:
                    verify_spans(p2["errors"], pair.zh)
                    out["judge2"] = {
                        "judge_model": jm2,
                        "stated100": p2["stated100"],
                        "derived100": p2["derived100"],
                        "score_delta": p2["score_delta"],
                        "n_errors": len(p2["errors"]),
                        "errors": p2["errors"],
                        "flags": flags_of(p2["errors"]),
                        "seconds": r2nd.get("seconds"),
                        "tok_in": r2nd.get("tok_in"),
                        "tok_out": r2nd.get("tok_out"),
                    }
                else:
                    out["judge2"] = {
                        "judge_model": jm2,
                        "judge2_error": "unparseable",
                    }
            else:
                out["judge2"] = {
                    "judge_model": jm2,
                    "judge2_error": r2nd.get("error", "call_failed"),
                }
    return out


# ---------------------------------------------------------------- 聚合/报告
_SCORE_BANDS = ((90, "90-100"), (75, "75-89"), (55, "55-74"), (0, "0-54"))


def _dist(scores: list[int]) -> str:
    """0-100 分带分布（≥90 / 75-89 / 55-74 / <55）。"""
    c = {label: 0 for _, label in _SCORE_BANDS}
    for s in scores:
        for lo, label in _SCORE_BANDS:
            if s >= lo:
                c[label] += 1
                break
    return " ".join(f"{label}:{c[label]}" for _, label in _SCORE_BANDS)


def aggregate(recs: list[dict]) -> dict:
    """records → {by_group, by_paper, by_kind, cat_sev, worst, contested, n_error}。"""
    groups: dict[str, list[dict]] = {}
    judged = [r for r in recs if r.get("score") is not None]
    for r in judged:
        groups.setdefault(
            f"{r.get('model', '?')} × judge={r.get('judge_model', '?')}", []
        ).append(r)
    by_paper: dict[str, list[dict]] = {}
    by_kind: dict[str, list[dict]] = {}
    cat_sev: dict[str, dict[str, int]] = {}
    for r in judged:
        by_paper.setdefault(str(r.get("paper")), []).append(r)
        by_kind.setdefault(str(r.get("kind") or "?"), []).append(r)
        for e in r.get("errors") or []:
            row = cat_sev.setdefault(
                e.get("category") or "?", {"minor": 0, "major": 0, "critical": 0}
            )
            row[e.get("severity") or "minor"] = (
                row.get(e.get("severity") or "minor", 0) + 1
            )
        for c in r.get("cats_extra") or []:
            row = cat_sev.setdefault(
                f"?(extra:{c})", {"minor": 0, "major": 0, "critical": 0}
            )
    contested = [r for r in judged if r.get("contested")]
    worst = sorted(
        judged,
        key=lambda r: (r["score"], -(r.get("n_errors") or 0)),
    )[:30]
    return {
        "groups": groups,
        "by_paper": by_paper,
        "by_kind": by_kind,
        "cat_sev": cat_sev,
        "contested": contested,
        "worst": worst,
        "n_error": sum(1 for r in recs if r.get("score") is None),
        "n_judged": len(judged),
    }


def _flag_tally(recs: list[dict]) -> dict[str, int]:
    t: dict[str, int] = {}
    for r in recs:
        for f in r.get("flags") or []:
            t[f] = t.get(f, 0) + 1
    return t


def _score_row(recs: list[dict]) -> str:
    scores = [int(r["score"]) for r in recs]
    deltas = [int(r["score_delta"]) for r in recs if r.get("score_delta") is not None]
    return (
        f"{len(recs)} | {statistics.mean(scores):.1f} | "
        f"{statistics.median(scores):.0f} | {_dist(scores)}"
        + (f" | {statistics.mean(deltas):+.1f}" if deltas else " | —")
    )


def write_report(recs: list[dict], meta: dict, out_dir: Path) -> None:
    """records + run_meta → report.md（ESA 口径：stated100 分布 + cat×sev 表 + contested 率）。"""
    agg = aggregate(recs)
    n_contested = len(agg["contested"])
    lines = [
        "# qualbench — 译文质量 LLM-judge（ESA）",
        "",
        (
            f"- protocol_v: `{meta.get('protocol_v', '?')}` · "
            f"judge: `{meta.get('judge_model')}`"
            f"（mock={meta.get('mock_judge')}）· 二裁: `{meta.get('second_model')}`"
        ),
        f"- source: {meta.get('source')} · seed={meta.get('seed')} · "
        f"papers={len(meta.get('papers') or [])} · judged={agg['n_judged']} chunks"
        + (f" · judge_error={agg['n_error']}" if agg["n_error"] else "")
        + (
            f" · contested={n_contested} ({n_contested / agg['n_judged'] * 100:.1f}%)"
            if agg["n_judged"]
            else ""
        ),
        f"- started: {meta.get('started_at')}",
        "",
        "## 总分 stated100（model × judge）",
        "",
        "| model × judge | n | mean | median | 分布 ≥90/75+/55+/<55 | Δmean |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {name} | {_score_row(agg['groups'][name])} |"
        for name in sorted(agg["groups"])
    )

    lines += ["", "## 错误分类 × severity（全体 judged chunk）", ""]
    if agg["cat_sev"]:
        lines += [
            "| category | minor | major | critical | total |",
            "| --- | --- | --- | --- | --- |",
        ]
        for cat, row in sorted(
            agg["cat_sev"].items(), key=lambda kv: -sum(kv[1].values())
        ):
            tot = sum(row.values())
            lines.append(
                f"| `{cat}` | {row['minor']} | {row['major']} | {row['critical']} | {tot} |"
            )
    else:
        lines.append("- （无错误标注）")

    lines += ["", "## flag 频率（类目派生）", ""]
    tally = _flag_tally([r for v in agg["groups"].values() for r in v])
    if tally:
        for f, c in sorted(tally.items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{f}`: {c}")
    else:
        lines.append("- （无 flag）")

    lines += [
        "",
        "## per-kind",
        "",
        "| kind | n | mean | median | 分布 ≥90/75+/55+/<55 | flags |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for k in sorted(agg["by_kind"]):
        rs = agg["by_kind"][k]
        ft = _flag_tally(rs)
        scores = [int(r["score"]) for r in rs]
        lines.append(
            f"| {k} | {len(rs)} | {statistics.mean(scores):.1f} | "
            f"{statistics.median(scores):.0f} | {_dist(scores)} | "
            + (
                ", ".join(
                    f"{f}×{c}" for f, c in sorted(ft.items(), key=lambda kv: -kv[1])
                )
                or "—"
            )
            + " |"
        )

    lines += [
        "",
        "## per-paper",
        "",
        "| paper | model | n | mean | 分布 ≥90/75+/55+/<55 | flags |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for p in sorted(agg["by_paper"]):
        rs = agg["by_paper"][p]
        ft = _flag_tally(rs)
        scores = [int(r["score"]) for r in rs]
        lines.append(
            f"| {p} | {rs[0].get('model', '?')} | {len(rs)} | "
            f"{statistics.mean(scores):.1f} | {_dist(scores)} | "
            + (
                ", ".join(
                    f"{f}×{c}" for f, c in sorted(ft.items(), key=lambda kv: -kv[1])
                )
                or "—"
            )
            + " |"
        )

    if agg["contested"]:
        lines += [
            "",
            "## contested chunk（触发二裁）",
            "",
            "| paper | chunk | reasons | stated | derived | judge2.stated |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for r in agg["contested"][:30]:
            j2 = r.get("judge2") or {}
            lines.append(
                f"| {r.get('paper')} | {r.get('chunk_id')} "
                f"| {','.join(r.get('contest_reasons') or [])} "
                f"| {r.get('stated100')} | {r.get('derived100')} "
                f"| {j2.get('stated100', j2.get('judge2_error', '—'))} |"
            )

    if agg["worst"]:
        lines += [
            "",
            "## 最差 chunk（stated100 升序前 30）",
            "",
            "| paper | chunk | kind | stated | Δ | flags | span✗ | note |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
        for r in agg["worst"]:
            if r["score"] >= 85 and not r.get("flags"):
                continue
            note = ""
            if r.get("errors"):
                note = str(r["errors"][0].get("note") or "")[:40]
            lines.append(
                f"| {r.get('paper')} | {r.get('chunk_id')} | {r.get('kind', '?')} "
                f"| {r['score']} | {r.get('score_delta', '—')} "
                f"| {','.join(r.get('flags') or []) or '—'} "
                f"| {r.get('n_span_unverified') or 0} | {note} |"
            )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ---------------------------------------------------------------- manifest 源
def collect_manifest_pairs(args: argparse.Namespace) -> tuple[list[Pair], dict]:
    """qualsample 冻结 sample.jsonl → 待评对（基线批直接喂 judge）。"""
    rows = benchlib.read_jsonl(Path(args.manifest))
    pairs = [
        Pair(
            paper=str(r["paper"]),
            chunk_id=str(r["chunk_id"]),
            kind=str(r.get("kind") or "para"),
            model=str(r.get("model") or "?"),
            src=str(r.get("src") or r.get("source") or ""),
            zh=str(r.get("zh") or r.get("translation") or ""),
            arm=str(r.get("arm") or ""),
            status=str(r.get("status") or "ok"),
        )
        for r in rows
    ]
    if args.n:
        pairs = pairs[: args.n]
    papers: dict[str, dict] = {}
    for p in pairs:
        e = papers.setdefault(p.paper, {"id": p.paper, "model": p.model, "n_pairs": 0})
        e["n_pairs"] += 1
    return pairs, {"papers": list(papers.values()), "manifest": args.manifest}


# ---------------------------------------------------------------- 命令
async def cmd_run(args: argparse.Namespace) -> None:
    out_dir = (
        Path(args.out)
        if args.out
        else ROOT / "bench/results" / f"{args.tag}-{args.date}"
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    rec_path = out_dir / "records.jsonl"

    if args.source == "state":
        pairs, meta_src = collect_state_pairs(args)
    elif args.source == "manifest":
        pairs, meta_src = collect_manifest_pairs(args)
    else:
        pairs, meta_src = collect_corpus_pairs(args)
    done = {
        r["key"]
        for r in benchlib.read_jsonl(rec_path)
        if "key" in r and r.get("score") is not None
    }
    judge_label = "mock-judge" if args.mock_judge else args.judge_model
    todo = [p for p in pairs if f"{p.key}|{judge_label}|{PROTOCOL_V}" not in done]
    print(
        f"pairs={len(pairs)} done={len(done)} todo={len(todo)} "
        f"judge={judge_label} second={args.second_model} "
        f"protocol={PROTOCOL_V} source={args.source}",
        flush=True,
    )

    meta = {
        "source": args.source,
        "seed": args.seed,
        "papers": meta_src.get("papers"),
        "manifest": meta_src.get("manifest"),
        "judge_model": judge_label,
        "second_model": None if args.no_second else args.second_model,
        "no_second": args.no_second,
        "protocol_v": PROTOCOL_V,
        "mock_judge": args.mock_judge,
        "base_url": None if args.mock_judge else args.base_url,
        "per_paper": args.per_paper,
        "n_cap": args.n,
        "concurrency": args.concurrency,
        "judge_max_tokens": args.judge_max_tokens,
        "started_at": datetime.now(UTC).isoformat(),
        "prompt_sha": hashlib.sha256(JUDGE_SYSTEM.encode()).hexdigest()[:12],
    }
    (out_dir / "run_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    if args.mock_judge:
        recs = []
        for p in todo:
            parsed = mock_judge(p)
            j = shape_judged(parsed, p, pair_signals(p.src, p.zh))
            recs.append(_mk_rec(p, judge_label, j))
            benchlib.append_jsonl(rec_path, recs[-1])
    else:
        import httpx

        http = {
            "client": httpx.AsyncClient(),
            "base_url": args.base_url.rstrip("/"),
            "api_key": args.api_key,
            "timeout": args.judge_timeout,
            "temperature": args.judge_temperature,
        }
        sem = asyncio.Semaphore(args.concurrency)
        recs = []

        async def _go(p: Pair) -> dict:
            async with sem:
                j = await judge_pair(http, p, args)
            rec = _mk_rec(p, judge_label, j)
            benchlib.append_jsonl(rec_path, rec)
            print(
                f"  {p.paper} {p.chunk_id} kind={p.kind} -> "
                f"stated={rec.get('stated100')} Δ={rec.get('score_delta')} "
                f"flags={rec.get('flags')} contested={rec.get('contested')} "
                f"err={rec.get('error') or rec.get('judge_error') or ''}",
                flush=True,
            )
            return rec

        try:
            recs = list(await asyncio.gather(*(_go(p) for p in todo)))
        finally:
            await http["client"].aclose()

    all_recs = benchlib.read_jsonl(rec_path)
    write_report(all_recs, meta, out_dir)
    n_ok = sum(1 for r in recs if r.get("score") is not None)
    n_err = len(recs) - n_ok
    print(f"done -> {out_dir} (judged={n_ok} error={n_err})", flush=True)


def _mk_rec(pair: Pair, judge_label: str, j: dict) -> dict:
    """Pair + judge 输出 → record 行（确定性信号 + 摘要一并落账）。

    key 并入 protocol_v——协议切换后旧协议记录不再截留新产出。
    """
    rec = {
        "key": f"{pair.key}|{judge_label}|{PROTOCOL_V}",
        "paper": pair.paper,
        "chunk_id": pair.chunk_id,
        "kind": pair.kind,
        "model": pair.model,
        "arm": pair.arm or None,
        "status": pair.status,
        "judge_model": judge_label,
        "protocol_v": PROTOCOL_V,
        **pair_signals(pair.src, pair.zh),
        "src_excerpt": pair.src[:160],
        "zh_excerpt": pair.zh[:160],
    }
    rec.update({k: v for k, v in j.items() if v is not None})
    return rec


def cmd_pairs(args: argparse.Namespace) -> None:
    """离线预览抽样（不调 judge）。"""
    if args.source == "state":
        pairs, meta = collect_state_pairs(args)
    elif args.source == "manifest":
        pairs, meta = collect_manifest_pairs(args)
    else:
        pairs, meta = collect_corpus_pairs(args)
    for p in pairs:
        sig = pair_signals(p.src, p.zh)
        print(
            f"{p.paper:24} {p.chunk_id:8} kind={p.kind:14} model={p.model:14} "
            f"src={sig['src_chars']:5}B zh={sig['zh_chars']:5}B "
            f"ph±={sig['ph_missing']}/{sig['ph_invented']} en_res={sig['en_residue']}"
        )
    print(f"total {len(pairs)} pairs / {len(meta.get('papers') or [])} papers")


def cmd_report(args: argparse.Namespace) -> None:
    """存量 records.jsonl 重生成 report.md。"""
    d = Path(args.dir)
    recs = benchlib.read_jsonl(d / "records.jsonl")
    meta_p = d / "run_meta.json"
    meta = json.loads(meta_p.read_text()) if meta_p.exists() else {}
    write_report(recs, meta, d)
    print(f"report -> {d / 'report.md'} ({len(recs)} records)")


def _add_sampling_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--source", choices=["state", "corpus", "manifest"], default="state")
    p.add_argument(
        "--manifest",
        default=None,
        help="--source manifest 时：qualsample 冻结的 sample.jsonl",
    )
    p.add_argument(
        "--state-root",
        action="append",
        default=None,
        help="state.json 搜索根（可多次）；默认 bench/work_e2ereal/_xlat_state",
    )
    p.add_argument("--corpus-root", default=str(DEFAULT_CORPUS))
    p.add_argument("--ids", default=None, help="逗号分隔论文 id（定点）")
    p.add_argument("--papers", type=int, default=0, help="seed 抽篇数（0=全部）")
    p.add_argument(
        "--per-paper", type=int, default=12, help="每篇 chunk 上限（kind 轮转）"
    )
    p.add_argument("--kinds", default=None, help="逗号分隔 kind 过滤")
    p.add_argument("--min-chars", type=int, default=8)
    p.add_argument("--max-chars", type=int, default=20000)
    p.add_argument("--n", type=int, default=0, help="全局 chunk 封顶（0=不限）")
    p.add_argument("--seed", type=int, default=42)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="抽样 + judge + records/report")
    _add_sampling_args(p_run)
    p_run.add_argument(
        "--judge-model",
        default="swe-2-max",
        help="主裁模型（swe-2-medium 永不任 judge；与被评同型自动改路由）",
    )
    p_run.add_argument(
        "--second-model",
        default="swe-2-high",
        help="contested 二裁模型",
    )
    p_run.add_argument("--no-second", action="store_true", help="关掉 contested 二裁")
    p_run.add_argument(
        "--base-url",
        default=os.environ.get("TEXLATE_BASE_URL", "http://127.0.0.1:3033"),
    )
    p_run.add_argument("--api-key", default=os.environ.get("TEXLATE_API_KEY", ""))
    p_run.add_argument("--mock-judge", action="store_true", help="离线确定性 judge")
    p_run.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="judge 并发——网关全局 decode 吞吐 ~550 tok/s 多会话共享，本臂自限 ≤4",
    )
    p_run.add_argument("--judge-timeout", type=float, default=300.0)
    p_run.add_argument(
        "--judge-temperature",
        type=float,
        default=0.1,
        help="judge 温度——3033 网关 temperature=0 会 502（response_event），用近零正值",
    )
    p_run.add_argument(
        "--judge-max-tokens",
        type=int,
        default=8192,
        help="judge 输出预算（reasoning 模型需思考余量）",
    )
    p_run.add_argument("--out", default=None, help="显式产出目录")
    p_run.add_argument("--tag", default="qualbench")
    p_run.add_argument("--date", default=str(datetime.now(UTC).date()))
    p_run.set_defaults(fn=lambda a: asyncio.run(cmd_run(a)))

    p_pairs = sub.add_parser("pairs", help="离线预览抽样")
    _add_sampling_args(p_pairs)
    p_pairs.set_defaults(fn=cmd_pairs)

    p_rep = sub.add_parser("report", help="records.jsonl 重生成 report.md")
    p_rep.add_argument("dir")
    p_rep.set_defaults(fn=cmd_report)

    args = ap.parse_args()
    if getattr(args, "state_root", None) is None:
        args.state_root = [str(DEFAULT_STATE_ROOT)]
    if getattr(args, "source", None) == "manifest" and not getattr(
        args, "manifest", None
    ):
        ap.error("--source manifest 需要 --manifest PATH")
    args.fn(args)


if __name__ == "__main__":
    main()
