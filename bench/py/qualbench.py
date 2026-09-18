#!/usr/bin/env python3
r"""qualbench — 翻译质量评测臂：LLM-judge 给 (src_en, zh) chunk 对打分。

现有 bench 全是结构指标（identity/leak/编译成功率/锚点保持），没有译文质量
度量——本脚本补这条臂：对管线真实产出的 chunk 对跑 LLM-judge，输出
1–5 分 + hjfy 反馈通道同款六类 flag，按 paper/model/kind 聚合出报告。
judge 模型与被评模型解耦（--judge-model），支持离线 mock judge 全链自检。

chunk 对来源（--source）：
  state   已有 xlat 产物树的 StateStore 落盘——``--state-root`` 下递归找
          ``state.json``，``results[]`` 末行胜取 (source, translation, kind,
          status)。兼容两种布局：e2e_real 的 ``_xlat_state/{safe_id}/`` 与
          stagerun 的 ``work/{id}/xlat-state/{arm}/``；翻译模型取
          ``meta.model``（stagerun 臂名记进 ``arm`` 字段）。只评
          ok/partial 且译文≠原文的块；skipped/fault 计数进 meta 不送 judge。
  corpus  干净机自检臂：corpus_v3 ``{id}/extracted/*.tex`` 按空行切段、
          内置确定性 mock 翻译（占位符/控制序列原位保留，散文 run →
          固定中文串），不 import texlate.* 也能把全链跑通。

judge 协议（hjfy 反馈类目同款 flag 集）：
  system prompt 声明六类 flag：untranslated_spans（漏翻）/
  placeholder_broken（[[TYPE_n]] 丢/造/改）/term_inconsistency（术语不一致）/
  over_translation（不该翻的翻了：math/命令/引文/人名）/
  hallucinated_content（增译）/grammar（中文不通）。输出严格 JSON
  ``{"score": 1-5, "flags": [...], "note": "<=60ch>"}``；``` 围栏剥皮 +
  首个 {...} 兜底抽取，解析失败补问一次，再败记 judge_error。
  judge 调用直接 httpx 打 OpenAI /v1/chat/completions——不 import
  texlate.xlat（bench 脚本独立轻依赖惯例；--judge-temperature 默认 0.1
  ——3003 网关对 swe-2-medium 把 temperature=0 直接 502
  ``stage=response_event``（2026-09-16 实测，0.01 起正常），
  --judge-max-tokens 默认 4096 给 reasoning 模型留思考预算）。

续跑：records.jsonl 逐块 append，key=``{model}|{paper}|{chunk}|{judge}``
——同 judged chunk 换 judge 模型重评互不覆盖；已有该 key 且带 score 的行
跳过（error 行重跑）。抽样：``--papers``  seed 抽篇 + ``--per-paper`` 按
kind 轮转取块保类型多样，``--n`` 全局封顶（跨篇轮转序取前 n，小样本天然
跨篇分散）。

用法:
  uv run python bench/py/qualbench.py pairs  [--source state] [--papers 5]
  uv run python bench/py/qualbench.py run --mock-judge --papers 5 --per-paper 6
  uv run python bench/py/qualbench.py run --judge-model swe-2-medium \
      --n 3 --out bench/results/qualbench-2026-09-16/smoke
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
DEFAULT_CORPUS = ROOT / "bench/corpus_v3"

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

#: judge flag 全集（hjfy 反馈通道同款类目；未知 flag 归 flags_extra 留痕）
KNOWN_FLAGS = (
    "untranslated_spans",
    "placeholder_broken",
    "term_inconsistency",
    "over_translation",
    "hallucinated_content",
    "grammar",
)

JUDGE_SYSTEM = """\
You are a meticulous bilingual (English to Chinese) translation-quality judge
for academic LaTeX texts. You will receive:
- Kind: the fragment's role (para | caption | section_title | abstract |
  table_text | env_text).
- Source: the original English LaTeX fragment. [[TYPE_n]] tokens (e.g.
  [[MATH_12]], [[CITE_3]], [[REF_7]], [[SL]], [[PL]]) are opaque placeholders
  for protected LaTeX/math/citation fragments — they must appear verbatim in
  the translation.
- Translation: the Chinese translation produced by a machine translator.

Evaluate ONLY translation quality (faithfulness + fluency), not LaTeX
compilability. Judge against the Kind's expectations (e.g. a section_title
should be a concise heading, a caption a compact legend).

Score (integer 1-5):
5 = accurate, fluent, publication-ready; consistent terminology; nothing
    missed, added, or mistranslated.
4 = good; at most one minor issue (slight awkwardness, one terminology wobble).
3 = understandable but with noticeable problems (a dropped clause, several
    awkward phrases, or one clear terminology inconsistency).
2 = poor; major semantic errors, significant untranslated prose, or broken
    placeholder handling.
1 = unusable; mostly untranslated, hallucinated, or garbled.

Flags — emit EVERY category that applies (empty list if none):
- "untranslated_spans": source prose left in English that should be Chinese.
- "placeholder_broken": a [[TYPE_n]] token missing, invented, renamed, or its
  immediate surroundings garbled by the translation.
- "term_inconsistency": the same technical term translated inconsistently, or
  a standard term clearly mistranslated.
- "over_translation": content that must stay unchanged was translated —
  math, LaTeX commands, citation/reference args, or person names.
- "hallucinated_content": the translation adds claims, entities, or sentences
  absent from the source.
- "grammar": Chinese so ungrammatical or machine-garbled it hinders reading.

Output STRICT JSON only — no markdown fence, no commentary:
{"score": <int>, "flags": [<flag>, ...], "note": "<=60 chars; the single most
important issue, or 'ok'>"}"""

JUDGE_RETRY_SUFFIX = (
    "\n\nYour previous reply was not parseable JSON. Reply with ONLY the JSON "
    'object: {"score": <int 1-5>, "flags": [...], "note": "..."}'
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


def _un_safe_id(name: str) -> str:
    """``safe_id`` 单层目录名 → 论文 id（``--`` → ``/``）。"""
    return name.replace("--", "/")


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
    """corpus_v3 extracted/*.tex 空行切段 + 内置 mock 翻译 → 待评对。"""
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
        "src_chars": len(src),
        "zh_chars": len(zh),
    }


# ---------------------------------------------------------------- judge
def mock_judge(pair: Pair) -> dict:
    """确定性 mock judge：按确定性信号出分/flag——离线全链自检用。"""
    sig = pair_signals(pair.src, pair.zh)
    flags: list[str] = []
    score = 5
    if pair.zh.strip() == pair.src.strip() or not pair.zh.strip():
        return {"score": 1, "flags": ["untranslated_spans"], "note": "zh==src"}
    if sig["ph_missing"] or sig["ph_invented"]:
        flags.append("placeholder_broken")
        score = min(score, 2)
    if sig["en_residue"] >= 8:
        flags.append("untranslated_spans")
        score = min(score, 2)
    elif sig["en_residue"] >= 3:
        flags.append("untranslated_spans")
        score = min(score, 3)
    if not flags:
        # sha 奇偶给 4/5 的确定性分布——聚合面能被真实走到
        score = (
            4 if int(hashlib.sha256(pair.key.encode()).hexdigest(), 16) % 3 == 0 else 5
        )
    return {"score": score, "flags": flags, "note": "mock-judge"}


def parse_judge_json(raw: str) -> dict | None:
    """judge 输出 → dict；fence 剥皮 + {...} 兜底；不合格返回 None。"""
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
    score = data.get("score")
    if isinstance(score, float) and score.is_integer():
        score = int(score)
    if not isinstance(score, int) or isinstance(score, bool) or not 1 <= score <= 5:
        return None
    flags = [str(f) for f in data.get("flags") or []]
    return {
        "score": score,
        "flags": [f for f in flags if f in KNOWN_FLAGS],
        "flags_extra": [f for f in flags if f not in KNOWN_FLAGS],
        "note": str(data.get("note") or "")[:80],
    }


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
            content = (ch.get("message") or {}).get("content") or ""
            usage = payload.get("usage") or {}
            return {
                "content": content,
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


async def judge_pair(http, pair: Pair, args: argparse.Namespace) -> dict:
    """judge 一对 → record 字段；解析失败补问一次，再败记 judge_error。"""
    r = await call_judge(http, pair, args.judge_model, max_tokens=args.judge_max_tokens)
    if "content" in r:
        parsed = parse_judge_json(r["content"])
        if parsed is None:
            # 补问一次：user 带严格 JSON 提醒后缀
            r2 = await call_judge(
                http,
                pair,
                args.judge_model,
                max_tokens=args.judge_max_tokens,
                user_suffix=JUDGE_RETRY_SUFFIX,
            )
            if "content" in r2:
                parsed = parse_judge_json(r2["content"])
                r = {**r2, "reparsed": True, "raw_first": r["content"][:200]}
        if parsed is not None:
            return {**r, **parsed}
        return {**r, "judge_error": "unparseable", "raw": r.get("content", "")[:300]}
    return r


# ---------------------------------------------------------------- 聚合/报告
def _dist(scores: list[int]) -> str:
    c = {s: scores.count(s) for s in range(1, 6)}
    return " ".join(f"{s}:{c[s]}" for s in range(5, 0, -1))


def aggregate(recs: list[dict]) -> dict:
    """records → {by_group, by_paper, by_kind, worst, n_error}。"""
    groups: dict[str, list[dict]] = {}
    for r in recs:
        if r.get("score") is None:
            continue
        groups.setdefault(
            f"{r.get('model', '?')} × judge={r.get('judge_model', '?')}", []
        ).append(r)
    by_paper: dict[str, list[dict]] = {}
    by_kind: dict[str, list[dict]] = {}
    for r in recs:
        if r.get("score") is None:
            continue
        by_paper.setdefault(str(r.get("paper")), []).append(r)
        by_kind.setdefault(str(r.get("kind") or "?"), []).append(r)
    worst = sorted(
        (r for r in recs if r.get("score") is not None),
        key=lambda r: (r["score"], -len(r.get("flags") or [])),
    )[:30]
    return {
        "groups": groups,
        "by_paper": by_paper,
        "by_kind": by_kind,
        "worst": worst,
        "n_error": sum(1 for r in recs if r.get("score") is None),
    }


def _flag_tally(recs: list[dict]) -> dict[str, int]:
    t: dict[str, int] = {}
    for r in recs:
        for f in r.get("flags") or []:
            t[f] = t.get(f, 0) + 1
    return t


def _score_row(recs: list[dict]) -> str:
    scores = [int(r["score"]) for r in recs]
    return (
        f"{len(recs)} | {statistics.mean(scores):.2f} | "
        f"{statistics.median(scores):.0f} | {_dist(scores)}"
    )


def write_report(recs: list[dict], meta: dict, out_dir: Path) -> None:
    """records + run_meta → report.md（聚合惯例照 xlatbench）。"""
    agg = aggregate(recs)
    lines = [
        "# qualbench — 译文质量 LLM-judge",
        "",
        f"- judge_model: `{meta.get('judge_model')}`（mock={meta.get('mock_judge')}）",
        f"- source: {meta.get('source')} · seed={meta.get('seed')} · "
        f"papers={len(meta.get('papers') or [])} · judged={sum(len(v) for v in agg['groups'].values())} chunks"
        + (f" · judge_error={agg['n_error']}" if agg["n_error"] else ""),
        f"- started: {meta.get('started_at')}",
        "",
        "## 总分（model × judge）",
        "",
        "| model × judge | n | mean | median | 分布 5→1 |",
        "| --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        f"| {name} | {_score_row(agg['groups'][name])} |"
        for name in sorted(agg["groups"])
    )

    lines += ["", "## flag 频率（全体 judged chunk）", ""]
    tally = _flag_tally([r for v in agg["groups"].values() for r in v])
    if tally:
        for f, c in sorted(tally.items(), key=lambda kv: -kv[1]):
            lines.append(f"- `{f}`: {c}")
    else:
        lines.append("- （无 flag）")
    extra = _flag_tally(
        [
            {**r, "flags": r.get("flags_extra") or []}
            for v in agg["groups"].values()
            for r in v
        ]
    )
    if extra:
        lines.append(
            "- flags_extra（judge 自造名）: "
            + ", ".join(f"{k}×{v}" for k, v in sorted(extra.items()))
        )

    lines += [
        "",
        "## per-kind",
        "",
        "| kind | n | mean | median | 分布 5→1 | flags |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for k in sorted(agg["by_kind"]):
        rs = agg["by_kind"][k]
        ft = _flag_tally(rs)
        lines.append(
            f"| {k} | {_score_row(rs)} | "
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
        "| paper | model | n | mean | 分布 5→1 | flags |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for p in sorted(agg["by_paper"]):
        rs = agg["by_paper"][p]
        ft = _flag_tally(rs)
        scores = [int(r["score"]) for r in rs]
        lines.append(
            f"| {p} | {rs[0].get('model', '?')} | {len(rs)} | "
            f"{statistics.mean(scores):.2f} | {_dist(scores)} | "
            + (
                ", ".join(
                    f"{f}×{c}" for f, c in sorted(ft.items(), key=lambda kv: -kv[1])
                )
                or "—"
            )
            + " |"
        )

    if agg["worst"]:
        lines += [
            "",
            "## 最差 chunk（score 升序前 30）",
            "",
            "| paper | chunk | kind | score | flags | note |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for r in agg["worst"]:
            if r["score"] >= 4 and not r.get("flags"):
                continue
            lines.append(
                f"| {r.get('paper')} | {r.get('chunk_id')} | {r.get('kind', '?')} "
                f"| {r['score']} | {','.join(r.get('flags') or []) or '—'} "
                f"| {str(r.get('note') or '')[:60]} |"
            )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


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
    else:
        pairs, meta_src = collect_corpus_pairs(args)
    done = {
        k
        for k, r in ((r["key"], r) for r in benchlib.read_jsonl(rec_path) if "key" in r)
        if r.get("score") is not None
    }
    judge_label = "mock-judge" if args.mock_judge else args.judge_model
    todo = [p for p in pairs if f"{p.key}|{judge_label}" not in done]
    print(
        f"pairs={len(pairs)} done={len(done)} todo={len(todo)} "
        f"judge={judge_label} source={args.source}",
        flush=True,
    )

    meta = {
        "source": args.source,
        "seed": args.seed,
        "papers": meta_src.get("papers"),
        "judge_model": judge_label,
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
            j = mock_judge(p)
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
                f"score={rec.get('score')} flags={rec.get('flags')} "
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
    """Pair + judge 输出 → record 行（确定性信号 + 摘要一并落账）。"""
    rec = {
        "key": f"{pair.key}|{judge_label}",
        "paper": pair.paper,
        "chunk_id": pair.chunk_id,
        "kind": pair.kind,
        "model": pair.model,
        "arm": pair.arm or None,
        "status": pair.status,
        "judge_model": judge_label,
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
    p.add_argument("--source", choices=["state", "corpus"], default="state")
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
    p_run.add_argument("--judge-model", default="swe-2-medium")
    p_run.add_argument(
        "--base-url",
        default=os.environ.get("TEXLATE_BASE_URL", "http://127.0.0.1:3003"),
    )
    p_run.add_argument("--api-key", default=os.environ.get("TEXLATE_API_KEY", ""))
    p_run.add_argument("--mock-judge", action="store_true", help="离线确定性 judge")
    p_run.add_argument(
        "--concurrency",
        type=int,
        default=2,
        help="judge 并发——swe-2-medium 全局闸 4（多会话共享），本臂自限 ≤2",
    )
    p_run.add_argument("--judge-timeout", type=float, default=180.0)
    p_run.add_argument(
        "--judge-temperature",
        type=float,
        default=0.1,
        help="judge 温度——3003 网关 temperature=0 会 502（response_event），用近零正值",
    )
    p_run.add_argument(
        "--judge-max-tokens",
        type=int,
        default=4096,
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
    args.fn(args)


if __name__ == "__main__":
    main()
