#!/usr/bin/env python3
r"""qualanchor — ESA^AI 人审包生成器：judge 预标 + 人核改判 + 0-100 分。

ESA^AI 半标注流程（xlat-quality-eval-2026-09-18 §7，Zouhar 2024 先例）：
LLM judge 先预标错误 span，人只做核实改判 + 给 0-100——比纯人标快一倍多。
本工具从 qualbench esa2 的 records.jsonl 分层抽 ~200 chunk 生成**纯文本
人审包**（零工具可审）；人审完 ``harvest`` 回收成 harvest.jsonl，供
qualstats 做 judge 校准（pairwise acc、分类别 Δ、span precision/recall）。

records.jsonl schema（qualbench._mk_rec 产出，每行一个 judged chunk）：
key=``{model}|{paper}|{chunk_id}|{judge}|esa2``；paper/chunk_id/kind/model；
stated100（主分 0-100）；errors=[{span,category,severity,note,span_verified}]；
flags；contested/contest_reasons；src_excerpt/zh_excerpt（160ch 截断——
人审要全文，``--fulltext`` 给 {paper,chunk_id,src,zh} 行文件 join）。
judge_error/error 行无 score → 抽样跳过。

抽样（sample）：kind × stated100 分带（≥90/75-89/55-74/<55）交叉覆盖——
两层轮转，先保底每 kind ≥1 再逐 cell 轮取；contested=True 超重采样
（配额 ~n/2 保底、clean 池不足时回灌更多 contested——人审价值最高）。
最终选集再 seed 洗牌打散编号，避免审者看出编排模式。

人审包形态（--out DIR）：
  index.tsv       seq,paper,chunk_id,kind,judge_stated100,judge_n_errors,
                  contested,human_score(空),excerpt_only
  items/NNNN.txt  === SOURCE === / === TRANSLATION ===（judge 认可 span
                  就地【...】标出，重叠按长优先）/ === JUDGE PRE-MARKS ===
                  每条 ``[i] severity|category|note|span``
  review/NNNN.json 人填模板 {human_score,human_errors,agree_flags,
                  drop_flags,extra_notes}（agree=人认可 judge error 序号；
                  drop=人判误报序号）
  README.txt      人审说明（类目/severity 枚举、改判方式、只填分也可）
  manifest.jsonl  seq → judge 数据回联账（机器用勿编辑；harvest 靠它把
                  judge_errors/judge_flags 并回人行）
  package_meta.json 生成元数据（records 源/seed/抽样计数）

harvest：读 index.tsv + manifest.jsonl + review/*.json → harvest.jsonl
{seq,paper,chunk_id,human_score,human_errors,agree_flags,drop_flags,
extra_notes,judge_stated100,judge_errors,judge_flags,contested,
excerpt_only,score_source}。空模板跳过计数；坏 json 计数不炸；
index.tsv 的 human_score 列作为只填分快速通道兜底（review 空但
index 有分 → score_source="index" 照收）。

设计取舍：item 文件**不显示 judge_stated100 / contested**——分数先入会
锚定人判，毁掉校准价值；这两列只进 index.tsv 供协调者查。

用法:
  uv run python bench/py/qualanchor.py sample RECORDS.jsonl \
      --fulltext sample.jsonl --n 200 --seed 20260918 --out DIR
  uv run python bench/py/qualanchor.py harvest DIR [--out PATH]
依赖: 纯 stdlib + benchlib（system python3 即可跑）。
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import benchlib

# ---------------------------------------------------------------- 常量

#: stated100 分带（与 qualbench._SCORE_BANDS 同口径）
SCORE_BANDS = ((90, "90-100"), (75, "75-89"), (55, "55-74"), (0, "0-54"))

#: contested 配额占包比例——超重采样但保留 clean 面供高分带校准
CONTESTED_SHARE = 0.5

#: 类目/severity 枚举（README 与人填 human_errors 共用；与 qualbench 单源对齐）
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
KNOWN_SEVERITIES = ("minor", "major", "critical")

#: review 模板——人只动这个文件；字段全默认即「未审」
REVIEW_TEMPLATE = {
    "human_score": None,
    "human_errors": [],
    "agree_flags": [],
    "drop_flags": [],
    "extra_notes": "",
}

README_TEXT = """\
ESA^AI 人审包 —— 评审说明
============================

你在做什么：LLM judge 已经对每段译文预标了错误 span。你的任务不是重新
标注，而是核实这些预标、改判、并给整段一个 0-100 质量分。

目录结构：
  items/NNNN.txt   待审段：SOURCE（英文原文）/ TRANSLATION（中文译文，
                   judge 认可的 span 已用【...】就地标出）/ JUDGE
                   PRE-MARKS（judge 预标错误清单，[i] 是错误序号）。
                   只读，不要编辑。
  review/NNNN.json 你要填的文件，与 items/ 同编号一一对应。
  index.tsv        全包索引（协调者用；human_score 列可只填分快速过）。

评审步骤（每段）：
  1. 打开 items/NNNN.txt，对照 SOURCE 读 TRANSLATION。
  2. 看 JUDGE PRE-MARKS 的每条预标：
     - 认可 → 把序号 i 填进 review/NNNN.json 的 "agree_flags"。
     - 误报（不是错/类目错得离谱/severity 严重夸大）→ 填进 "drop_flags"。
     - 既不同意也不反对可两边都不填（存疑项下游单独看）。
  3. judge 漏掉的错误 → 填进 "human_errors"，每条格式：
       {"span": "译文中逐字子串", "category": 见下, "severity": 见下,
        "note": "<=40字说明"}
  4. 给整段打 0-100 分填进 "human_score"（100=完美，用满量程）。
  5. 想说的话写 "extra_notes"。

review/NNNN.json 模板：
  {
    "human_score": null,        // 整数 0-100
    "human_errors": [],         // judge 漏标的错误（见上格式）
    "agree_flags": [],          // 你认可的 judge 错误序号，如 [0, 2]
    "drop_flags": [],           // 你判误报的序号，如 [1]
    "extra_notes": ""
  }

时间紧时：只填 "human_score" 也可（其余留默认）——分数校准价值最高；
或在 index.tsv 的 human_score 列直接填分（harvest 会兜底回收）。

category 枚举（human_errors 用）：
  accuracy-omission          原文内容漏译/丢失
  accuracy-mistranslation    在译但译错（意思扭曲）
  accuracy-addition          增译/编造原文没有的内容
  non-translation            整段未翻（仍是英文）
  terminology                术语错译或前后不一致
  convention-do_not_translate 不该翻的被翻了（人名/引文条目/数学与命令）
  convention-placeholder     [[TYPE_n]] 占位符缺失/臆造/改名/周边损坏
  fluency-grammar            中文不通顺/语病
  fluency-register           语体不合学术腔/直译腔（report-only）

severity 枚举：
  minor    不改意思，略生硬
  major    改/遮意思、坏可读性、或违硬约定（如占位符丢失）
  critical 仅限：整段未翻 / 占位符结构性报废 / 增译翻转含义

注意：
- span 必须是 TRANSLATION 里的逐字子串（复制粘贴，别改写）。
- 判错只针对翻译质量（忠实+通顺），不管 LaTeX 可编译性。
- 人名、引文条目、数学占位符正确保留英文不算错。
- 不要改 items/ 与 manifest.jsonl；只填 review/ 与（可选）index.tsv。

审完后由协调者回收：qualanchor.py harvest <本目录> → harvest.jsonl。
"""


# ---------------------------------------------------------------- 记录读入
def band_of(score: int) -> str:
    """0-100 → 分带标签（≥90 / 75-89 / 55-74 / <55）。"""
    for lo, label in SCORE_BANDS:
        if score >= lo:
            return label
    return SCORE_BANDS[-1][1]


def load_records(path: Path) -> tuple[list[dict], dict]:
    """records.jsonl → (judged rows, skip 计数)。

    - 无 score 行（judge_error/error 失败账）跳过计 n_noscore
    - 同 key 末行胜（rerun append 惯例）
    - stated100 缺失回退 score 字段；二者皆无 → n_noscore
    """
    raw = benchlib.read_jsonl(path)
    by_key: dict[str, dict] = {}
    n_noscore = 0
    n_badtype = 0
    for r in raw:
        if not isinstance(r, dict):
            n_badtype += 1
            continue
        stated = r.get("stated100")
        if not isinstance(stated, int) or isinstance(stated, bool):
            stated = r.get("score") if isinstance(r.get("score"), int) else None
        if stated is None or isinstance(stated, bool):
            n_noscore += 1
            continue
        row = dict(r)
        row["stated100"] = stated
        by_key[
            str(
                row.get("key")
                or f"{row.get('paper')}|{row.get('chunk_id')}|{len(by_key)}"
            )
        ] = row
    return list(by_key.values()), {
        "n_rows": len(raw),
        "n_noscore": n_noscore,
        "n_badtype": n_badtype,
        "n_eligible": len(by_key),
    }


def load_fulltext(path: Path) -> dict[tuple[str, str], dict]:
    """--fulltext 行文件 → {(paper, chunk_id): {src, zh}}（末行胜）。

    容忍别名字段：src|source、zh|translation——qualsample 冻结样本与
    state 导出两种形态都能吃。
    """
    out: dict[tuple[str, str], dict] = {}
    for r in benchlib.read_jsonl(path):
        if not isinstance(r, dict):
            continue
        src = r.get("src") if r.get("src") is not None else r.get("source")
        zh = r.get("zh") if r.get("zh") is not None else r.get("translation")
        paper, cid = r.get("paper"), r.get("chunk_id")
        if paper is None or cid is None:
            continue
        out[(str(paper), str(cid))] = {"src": str(src or ""), "zh": str(zh or "")}
    return out


# ---------------------------------------------------------------- 分层抽样
def _cell_key(rec: dict) -> tuple[str, str]:
    """(kind, band) 分层 cell。"""
    return (str(rec.get("kind") or "?"), band_of(rec["stated100"]))


def stratified_pick(recs: list[dict], quota: int, rng: random.Random) -> list[dict]:
    """kind × band 两层轮转抽样：先保底每 kind ≥1，再逐 cell 轮取到 quota。

    桶内 seed 洗牌——确定性复现；quota ≥ cell 数时每 cell 至少出一条。
    """
    cells: dict[tuple[str, str], list[dict]] = {}
    for r in recs:
        cells.setdefault(_cell_key(r), []).append(r)
    for v in cells.values():
        rng.shuffle(v)
    out: list[dict] = []
    # pass 1：kind 保底——每个 kind 随机取一个非空 cell 出 1 条
    by_kind: dict[str, list[tuple[str, str]]] = {}
    for ck in cells:
        by_kind.setdefault(ck[0], []).append(ck)
    for kind in sorted(by_kind):
        if len(out) >= quota:
            break
        live = [ck for ck in by_kind[kind] if cells[ck]]
        if live:
            out.append(cells[rng.choice(live)].pop())
    # pass 2+：cell 轮转填满 quota
    keys = sorted(cells)
    while len(out) < quota:
        progressed = False
        for ck in keys:
            if cells[ck] and len(out) < quota:
                out.append(cells[ck].pop())
                progressed = True
        if not progressed:
            break
    return out


def select_sample(recs: list[dict], n: int, seed: int) -> tuple[list[dict], dict]:
    """contested 超重 + kind×band 分层 → 选集（已洗牌、待编 seq）。

    contested 配额 = min(len(contested), max(n·SHARE, n−len(clean)))——
    平时 contested 全进（自然占比远低于 50%）；contested 池超半包时
    截到 ~n/2 保住 clean 面校准；clean 池不足时 contested 回灌补满。
    """
    rng = random.Random(seed)
    contested = [r for r in recs if r.get("contested")]
    clean = [r for r in recs if not r.get("contested")]
    if not n or n >= len(recs):
        picked = list(recs)
    else:
        cq = min(
            len(contested),
            max(int(n * CONTESTED_SHARE), n - len(clean)),
        )
        picked = stratified_pick(contested, cq, rng)
        rest = n - len(picked)
        picked += stratified_pick(clean, rest, rng)
        # contested 池少于配额时 clean 已在 rest 里自然补满；clean 池不足
        # 时上面 cq 公式已放行更多 contested——两侧都无须二次回灌
    rng.shuffle(picked)
    meta = {
        "n_want": n,
        "n_got": len(picked),
        "n_contested_pool": len(contested),
        "n_contested_picked": sum(1 for r in picked if r.get("contested")),
        "band_dist": {},
        "kind_dist": {},
    }
    for r in picked:
        b = band_of(r["stated100"])
        meta["band_dist"][b] = meta["band_dist"].get(b, 0) + 1
        k = str(r.get("kind") or "?")
        meta["kind_dist"][k] = meta["kind_dist"].get(k, 0) + 1
    return picked, meta


# ---------------------------------------------------------------- 人审包生成
def mark_spans(zh: str, errors: list[dict]) -> tuple[str, list[int]]:
    """zh 里把 span_verified=True 的 span 用【...】标出；重叠按长优先。

    返回 (marked_zh, marked_error_indices)。span 在展示文本中找不到
    （excerpt 截断/记录陈旧）→ 该错误序号不进返回表，PRE-MARKS 行尾标
    ``[unverified-in-text]`` 由调用方负责。
    """
    spans: dict[str, list[int]] = {}
    for i, e in enumerate(errors):
        sp = str(e.get("span") or "")
        if e.get("span_verified") and sp:
            spans.setdefault(sp, []).append(i)
    claimed: list[tuple[int, int]] = []
    hit_idx: set[int] = set()
    for sp in sorted(spans, key=lambda s: -len(s)):
        pos = 0
        while True:
            j = zh.find(sp, pos)
            if j < 0:
                break
            if not any(j < e2 and s2 < j + len(sp) for s2, e2 in claimed):
                claimed.append((j, j + len(sp)))
                hit_idx.update(spans[sp])
            pos = j + 1
    if not claimed:
        return zh, []
    out: list[str] = []
    pos = 0
    for s, e in sorted(claimed):
        out += [zh[pos:s], "【", zh[s:e], "】"]
        pos = e
    out.append(zh[pos:])
    return "".join(out), sorted(hit_idx)


def item_text(seq: int, rec: dict, src: str, zh: str) -> str:
    """单段人审文件全文（judge 分/contested 刻意不进——防分数锚定）。"""
    errors = rec.get("errors") or []
    marked_zh, marked_idx = mark_spans(zh, errors)
    lines = [
        (
            f"# seq={seq:04d} paper={rec.get('paper')} chunk={rec.get('chunk_id')}"
            f" kind={rec.get('kind') or '?'} model={rec.get('model') or '?'}"
        ),
        "=== SOURCE ===",
        src,
        "=== TRANSLATION ===",
        marked_zh,
        "=== JUDGE PRE-MARKS ===",
    ]
    if errors:
        for i, e in enumerate(errors):
            tail = "" if i in marked_idx else " [unverified-in-text]"
            lines.append(
                f"[{i}] {e.get('severity') or '?'}|{e.get('category') or '?'}"
                f"|{e.get('note') or ''}|{e.get('span') or ''}{tail}"
            )
    else:
        lines.append("(judge 未标错误)")
    return "\n".join(lines) + "\n"


def write_package(picked: list[dict], fulltext: dict | None, args) -> dict:
    """选集 → DIR/{index.tsv,README.txt,manifest.jsonl,package_meta.json,
    items/,review/}。返回 package_meta。"""
    out = Path(args.out)
    items_d = out / "items"
    review_d = out / "review"
    items_d.mkdir(parents=True, exist_ok=True)
    review_d.mkdir(parents=True, exist_ok=True)

    idx_rows = [
        (
            "seq\tpaper\tchunk_id\tkind\tjudge_stated100\tjudge_n_errors"
            "\tcontested\thuman_score\texcerpt_only"
        )
    ]
    manifest = []
    n_excerpt = 0
    for seq, rec in enumerate(picked, start=1):
        key = (str(rec.get("paper")), str(rec.get("chunk_id")))
        ft = (fulltext or {}).get(key)
        excerpt_only = ft is None
        n_excerpt += excerpt_only
        src = ft["src"] if ft else str(rec.get("src_excerpt") or "")
        zh = ft["zh"] if ft else str(rec.get("zh_excerpt") or "")
        errors = rec.get("errors") or []
        flags = rec.get("flags") or []
        (items_d / f"{seq:04d}.txt").write_text(
            item_text(seq, rec, src, zh), encoding="utf-8"
        )
        (review_d / f"{seq:04d}.json").write_text(
            json.dumps(REVIEW_TEMPLATE, ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )
        idx_rows.append(
            "\t".join(
                [
                    f"{seq:04d}",
                    str(rec.get("paper")),
                    str(rec.get("chunk_id")),
                    str(rec.get("kind") or "?"),
                    str(rec["stated100"]),
                    str(len(errors)),
                    "1" if rec.get("contested") else "0",
                    "",
                    "1" if excerpt_only else "",
                ]
            )
        )
        manifest.append(
            {
                "seq": seq,
                "key": rec.get("key"),
                "paper": rec.get("paper"),
                "chunk_id": rec.get("chunk_id"),
                "kind": rec.get("kind"),
                "model": rec.get("model"),
                "judge_model": rec.get("judge_model"),
                "judge_stated100": rec["stated100"],
                "judge_derived100": rec.get("derived100"),
                "score_delta": rec.get("score_delta"),
                "judge_errors": errors,
                "judge_flags": flags,
                "contested": bool(rec.get("contested")),
                "contest_reasons": rec.get("contest_reasons") or [],
                "excerpt_only": excerpt_only,
            }
        )
    (out / "index.tsv").write_text("\n".join(idx_rows) + "\n", encoding="utf-8")
    with (out / "manifest.jsonl").open("w", encoding="utf-8") as fh:
        for row in manifest:
            benchlib.write_jsonl(fh, row)
    (out / "README.txt").write_text(README_TEXT, encoding="utf-8")
    meta = {
        "records": str(args.records),
        "fulltext": str(args.fulltext) if args.fulltext else None,
        "seed": args.seed,
        "n_excerpt_only": n_excerpt,
    }
    (out / "package_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    return meta


def cmd_sample(args) -> None:
    records_path = Path(args.records)
    if not records_path.is_file():
        sys.exit(f"records 不存在: {records_path}")
    recs, load_meta = load_records(records_path)
    if not recs:
        sys.exit(f"无可审记录（全部无 score）: {records_path}")
    fulltext = None
    if args.fulltext:
        ft_path = Path(args.fulltext)
        if not ft_path.is_file():
            sys.exit(f"--fulltext 不存在: {ft_path}")
        fulltext = load_fulltext(ft_path)
    picked, sel_meta = select_sample(recs, args.n, args.seed)
    pkg_meta = write_package(picked, fulltext, args)
    meta = {**load_meta, **sel_meta, **pkg_meta}
    print(
        f"rows={meta['n_rows']} eligible={meta['n_eligible']} "
        f"noscore_skip={meta['n_noscore']} -> picked={meta['n_got']} "
        f"(contested {meta['n_contested_picked']}/{meta['n_contested_pool']}) "
        f"excerpt_only={meta['n_excerpt_only']}",
        flush=True,
    )
    print(f"  bands={meta['band_dist']} kinds={meta['kind_dist']}", flush=True)
    print(f"package -> {args.out}", flush=True)


# ---------------------------------------------------------------- harvest
def _norm_score(v) -> tuple[int | None, bool]:
    """人填分 → (int 0-100, 合法?)——容忍数字串/整值 float。"""
    if v is None:
        return None, True
    if isinstance(v, bool):
        return None, False
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    if isinstance(v, str) and v.strip().isdigit():
        v = int(v.strip())
    if isinstance(v, int) and 0 <= v <= 100:
        return v, True
    return None, False


def _filled(review: dict) -> bool:
    """模板被碰过即算已审：分非空/任一列表非空/notes 非空。"""
    return (
        review.get("human_score") is not None
        or bool(review.get("human_errors"))
        or bool(review.get("agree_flags"))
        or bool(review.get("drop_flags"))
        or bool(str(review.get("extra_notes") or "").strip())
    )


def cmd_harvest(args) -> None:
    d = Path(args.dir)
    if not d.is_dir():
        sys.exit(f"包目录不存在: {d}")
    manifest = {
        int(m["seq"]): m
        for m in benchlib.read_jsonl(d / "manifest.jsonl")
        if isinstance(m.get("seq"), int)
    }
    # index.tsv：seq→行 + human_score 快速通道兜底
    index_score: dict[int, str] = {}
    idx_p = d / "index.tsv"
    if idx_p.is_file():
        for line in idx_p.read_text(encoding="utf-8").splitlines()[1:]:
            cols = line.split("\t")
            if len(cols) >= 8 and cols[0].strip().isdigit():
                index_score[int(cols[0])] = cols[7].strip()

    rows = []
    n_files = n_filled = n_empty = n_bad = n_index_only = n_bad_score = 0
    review_d = d / "review"
    files = sorted(review_d.glob("*.json")) if review_d.is_dir() else []
    for f in files:
        n_files += 1
        try:
            seq = int(f.stem)
        except ValueError:
            n_bad += 1
            continue
        m = manifest.get(seq)
        if m is None:
            n_bad += 1
            continue
        try:
            review = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            review = None
        if not isinstance(review, dict):
            review = None
        if review is None:
            # 坏 json/非 dict ≠ 空模板——人碰过但读不出，单列计数不静默吞；
            # 仍可被 index 快速通道救回，救不回也不计入 empty
            n_bad += 1
            if index_score.get(seq):
                s2, ok2 = _norm_score(index_score[seq])
                if ok2 and s2 is not None:
                    m2 = manifest[seq]
                    n_filled += 1
                    n_index_only += 1
                    rows.append(
                        {
                            "seq": seq,
                            "paper": m2["paper"],
                            "chunk_id": m2["chunk_id"],
                            "human_score": s2,
                            "human_errors": [],
                            "agree_flags": [],
                            "drop_flags": [],
                            "extra_notes": "",
                            "judge_stated100": m2.get("judge_stated100"),
                            "judge_errors": m2.get("judge_errors") or [],
                            "judge_flags": m2.get("judge_flags") or [],
                            "contested": m2.get("contested"),
                            "excerpt_only": m2.get("excerpt_only"),
                            "score_source": "index",
                            "_warn": "bad_review_json",
                        }
                    )
                else:
                    n_bad_score += 1
            continue
        filled = _filled(review)
        score, score_ok = _norm_score(review.get("human_score"))
        if not score_ok:
            n_bad_score += 1
        score_source = "review" if score is not None else None
        if not filled and index_score.get(seq):
            # index.tsv 快速通道：review 全空但 index 填了分
            s2, ok2 = _norm_score(index_score[seq])
            if ok2 and s2 is not None:
                score, score_source, filled = s2, "index", True
                n_index_only += 1
            else:
                n_bad_score += 1
        if not filled:
            n_empty += 1
            continue
        n_filled += 1
        review = review or {}
        rows.append(
            {
                "seq": seq,
                "paper": m["paper"],
                "chunk_id": m["chunk_id"],
                "human_score": score,
                "human_errors": review.get("human_errors") or [],
                "agree_flags": review.get("agree_flags") or [],
                "drop_flags": review.get("drop_flags") or [],
                "extra_notes": review.get("extra_notes") or "",
                "judge_stated100": m.get("judge_stated100"),
                "judge_errors": m.get("judge_errors") or [],
                "judge_flags": m.get("judge_flags") or [],
                "contested": m.get("contested"),
                "excerpt_only": m.get("excerpt_only"),
                "score_source": score_source,
            }
            | ({"_warn": "bad_human_score"} if not score_ok else {})
        )
    # index 快速通道覆盖：有 index 分但 review 文件整个缺失
    have = {r["seq"] for r in rows}
    for seq, raw in index_score.items():
        if seq in have or not raw or seq not in manifest:
            continue
        s2, ok2 = _norm_score(raw)
        if not (ok2 and s2 is not None):
            continue
        m = manifest[seq]
        n_filled += 1
        n_index_only += 1
        rows.append(
            {
                "seq": seq,
                "paper": m["paper"],
                "chunk_id": m["chunk_id"],
                "human_score": s2,
                "human_errors": [],
                "agree_flags": [],
                "drop_flags": [],
                "extra_notes": "",
                "judge_stated100": m.get("judge_stated100"),
                "judge_errors": m.get("judge_errors") or [],
                "judge_flags": m.get("judge_flags") or [],
                "contested": m.get("contested"),
                "excerpt_only": m.get("excerpt_only"),
                "score_source": "index",
            }
        )
    rows.sort(key=lambda r: r["seq"])
    out_p = Path(args.out) if args.out else d / "harvest.jsonl"
    with out_p.open("w", encoding="utf-8") as fh:
        for r in rows:
            benchlib.write_jsonl(fh, r)
    print(
        f"review_files={n_files} filled={n_filled} empty_skip={n_empty} "
        f"bad={n_bad} index_only={n_index_only} bad_score={n_bad_score} "
        f"-> {out_p}",
        flush=True,
    )


# ---------------------------------------------------------------- CLI
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_s = sub.add_parser("sample", help="records.jsonl → 分层抽样 + 人审包")
    p_s.add_argument("records", help="qualbench esa2 records.jsonl")
    p_s.add_argument(
        "--fulltext",
        default=None,
        help="{paper,chunk_id,src,zh} 行文件 join 全文（缺省用 160ch excerpt "
        "并在 index 标 excerpt_only）",
    )
    p_s.add_argument("--n", type=int, default=200, help="抽样量（0=全部 eligible）")
    p_s.add_argument("--seed", type=int, default=20260918)
    p_s.add_argument("--out", required=True, help="人审包输出目录")
    p_s.set_defaults(fn=cmd_sample)

    p_h = sub.add_parser("harvest", help="回收 review/*.json → harvest.jsonl")
    p_h.add_argument("dir", help="人审包目录")
    p_h.add_argument("--out", default=None, help="默认 DIR/harvest.jsonl")
    p_h.set_defaults(fn=cmd_harvest)

    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
