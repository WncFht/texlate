#!/usr/bin/env python3
"""P3 补强层选择器：nominations/ → booster_selection.jsonl + selection_report.md.

规则（docs/09 §4.3）：
- B01–B07 是**地板配额**（最小保障）：B01 30 / B02 30 / B03 30 / B04 30 / B05 25 / B06 20 / B07 25。
- 补强层不进池化——选择目标是机制覆盖，不是代表性。
- 算法：先 B 地板（每 quota 内优先"稀有 W tag 覆盖最多"的提名）→ 再逐 W 机制补代表
  → 最后按稀有度填到 ~200 封顶。
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

BASE = Path(__file__).parent
NOM_DIR = BASE / "nominations"
OUT = BASE / "booster_selection.jsonl"
REPORT = BASE / "selection_report.md"
CAP = 200
QUOTA_FLOOR = {
    "B01": 30,
    "B02": 30,
    "B03": 30,
    "B04": 30,
    "B05": 25,
    "B06": 20,
    "B07": 25,
}

CLUSTER_BAND = {f"C{n:02d}": "abcde"[min((n - 1) // 6, 4)] for n in range(1, 31)}


def band_of(d: dict) -> str:
    cid = d.get("cluster_id") or d.get("cluster") or ""
    if not cid:
        m = re.search(r"staging/(C\d+)/", d.get("evidence", ""))
        cid = m.group(1) if m else ""
    if cid in CLUSTER_BAND:
        return CLUSTER_BAND[cid]
    mm = (d.get("member") or "").split("/")[0]
    if re.fullmatch(r"\d{4}", mm):
        y = 2000 + int(mm[:2])
        return (
            "a"
            if y <= 2006
            else "b"
            if y <= 2011
            else "c"
            if y <= 2016
            else "d"
            if y <= 2020
            else "e"
        )
    return "?"


def load() -> dict[str, dict]:
    """id → merged nom（多 agent 重复提名合并 tags + sources）。"""
    merged: dict[str, dict] = {}
    for f in sorted(NOM_DIR.glob("*.jsonl")):
        if ".mechs." in f.name:
            continue
        agent = f.name[:-6]
        for line in f.open():
            d = json.loads(line)
            tags = set(d.get("mech_tags", []))
            if not tags:  # clean read 无机制标记——不是补强候选
                continue
            pid = d["id"]
            if pid in merged:
                m = merged[pid]
                m["mech_tags"] = sorted(set(m["mech_tags"]) | tags)
                m["sources"].append(agent)
            else:
                d["mech_tags"] = sorted(tags)
                d["sources"] = [agent]
                d["band"] = band_of(d)
                merged[pid] = d
    return merged


def ledger_cites() -> dict[str, set[str]]:
    """W 机制 → 台账例证论文集（examples+evidence 引用，不限池内）。"""
    pat = re.compile(
        r"(?:\d{4}\.\d{4,5}|(?:cond-mat|hep-\w+|math|cs|astro-ph|nucl-\w+|quant-ph|gr-qc|nlin|physics|stat|adap-org|alg-geom|chao-dyn|cmp-lg|dg-ga|funct-an|patt-sol|q-alg|solv-int|supr-con|acc-phys|ao-sci|atom-ph|bayes-an|chem-ph|plasm-ph|q-bio)/\d{7})"
    )
    out: dict[str, set[str]] = defaultdict(set)
    for line in (BASE / "mechanisms.jsonl").open():
        d = json.loads(line)
        mid = d["mech_id"]
        if not mid.startswith("W"):
            continue
        text = d.get("evidence", "") + " " + " ".join(d.get("examples", []))
        out[mid] |= set(pat.findall(text))
    return out


def derive(noms: dict[str, dict]) -> dict[str, set[str]]:
    """台账 W 条目 examples/evidence 引用的池内论文 → 派生覆盖 tag.

    提案是"在该论文上观察到的"——论文被提名时 tag 可能只写了 B 面。
    """
    pat = re.compile(
        r"(?:\d{4}\.\d{4,5}|(?:cond-mat|hep-\w+|math|cs|astro-ph|nucl-\w+|quant-ph|gr-qc|nlin|physics|stat|adap-org|alg-geom|chao-dyn|cmp-lg|dg-ga|funct-an|patt-sol|q-alg|solv-int|supr-con|acc-phys|ao-sci|atom-ph|bayes-an|chem-ph|plasm-ph|q-bio)/\d{7})"
    )
    out: dict[str, set[str]] = defaultdict(set)
    for line in (BASE / "mechanisms.jsonl").open():
        d = json.loads(line)
        mid = d["mech_id"]
        if not mid.startswith("W"):
            continue
        text = d.get("evidence", "") + " " + " ".join(d.get("examples", []))
        for pid in pat.findall(text):
            if pid in noms:
                out[pid].add(mid)
    return out


def main() -> None:
    noms = load()
    # 两层必须不相交：核心层已中选的论文不入补强池（重叠会让 meta.layer 二义）
    core_mf = BASE / "manifest.jsonl"
    core_ids: set[str] = set()
    if core_mf.exists():
        core_ids = {json.loads(ln)["id"] for ln in core_mf.open()}
        noms = {pid: d for pid, d in noms.items() if pid not in core_ids}
    derived = derive(noms)
    for pid, extra in derived.items():
        noms[pid]["mech_tags"] = sorted(set(noms[pid]["mech_tags"]) | extra)
        noms[pid]["derived_tags"] = sorted(extra)
    tag_n = Counter(t for d in noms.values() for t in d["mech_tags"])
    selected: dict[str, dict] = {}

    def pick(pid: str, why: str) -> None:
        if pid not in selected:
            d = noms[pid]
            d["pick_reason"] = why
            selected[pid] = d

    def rarity_score(d: dict) -> float:
        """tags 稀有度加权和（越稀有的 tag 权重越高）。"""
        return sum(1.0 / tag_n[t] for t in d["mech_tags"])

    # ---- 1. B 地板
    for b, floor in QUOTA_FLOOR.items():
        pool = [d for d in noms.values() if b in d["mech_tags"]]
        pool.sort(key=rarity_score, reverse=True)
        for d in pool[:floor]:
            pick(d["id"], f"quota:{b}")

    # ---- 2. W 机制代表（未被 1 覆盖的每个 W tag 补 1 例，带例证的优先）
    ledger_ids = {
        json.loads(line)["mech_id"]
        for line in (BASE / "mechanisms.jsonl").open()
        if json.loads(line)["mech_id"].startswith("W")
    }
    covered_tags = {t for d in selected.values() for t in d["mech_tags"]}
    for w in sorted(ledger_ids):
        if w in covered_tags:
            continue
        pool = [
            d for d in noms.values() if w in d["mech_tags"] and d["id"] not in selected
        ]
        if not pool:
            continue
        pool.sort(
            key=lambda d: (len(set(d["mech_tags"]) & ledger_ids), rarity_score(d)),
            reverse=True,
        )
        pick(pool[0]["id"], f"mech:{w}")

    # ---- 3. 稀有度填充至 ~200
    rest = [d for d in noms.values() if d["id"] not in selected]
    rest.sort(key=rarity_score, reverse=True)
    for d in rest[: max(0, CAP - len(selected))]:
        pick(d["id"], "rarity-fill")

    OUT.write_text(
        "".join(json.dumps(d, ensure_ascii=False) + "\n" for d in selected.values()),
        encoding="utf-8",
    )

    # ---- 报告
    sel_tag_n = Counter(t for d in selected.values() for t in d["mech_tags"])
    band_n = Counter(d["band"] for d in selected.values())
    q_rows = []
    for b, floor in QUOTA_FLOOR.items():
        q_rows.append(f"| {b} | {floor} | {sel_tag_n.get(b, 0)} | {tag_n.get(b, 0)} |")
    uncovered_w = [w for w in sorted(ledger_ids) if sel_tag_n.get(w, 0) == 0]
    no_nom_w = [w for w in sorted(ledger_ids) if tag_n.get(w, 0) == 0]
    cites = ledger_cites()
    core_only_w = [
        w for w in no_nom_w if any(pid in core_ids for pid in cites.get(w, set()))
    ]
    lines = [
        "# 补强层选择报告",
        "",
        f"提名池 {len(noms)} 唯一篇（{sum(len(d['sources']) for d in noms.values())} 提名记录）→ 选中 {len(selected)}。",
        "",
        "## B 配额达成",
        "| quota | 地板 | 选中 | 池内可得 |",
        "| --- | --- | --- | --- |",
        *q_rows,
        "",
        f"## 带分布：{dict(sorted(band_n.items()))}",
        "",
        f"## W 机制覆盖：{len([w for w in ledger_ids if sel_tag_n.get(w, 0) > 0])}/{len(ledger_ids)} 有代表",
        f"- 选中集未覆盖（池内无提名——hunter exhausted 或 curator 未见）: {', '.join(no_nom_w) or '无'}",
        f"  （其中例证在核心层，语料仍有代表）: {', '.join(core_only_w) or '无'}",
        f"- 池内有提名但未选（额度挤占）: {', '.join(w for w in uncovered_w if w not in no_nom_w) or '无'}",
        "",
        "选中明细见 booster_selection.jsonl（pick_reason: quota:* 地板配额 / mech:* 机制代表 / rarity-fill 稀有度填充）。",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"selected {len(selected)} / {len(noms)} noms")
    print("bands:", dict(sorted(band_n.items())))
    print(
        "W covered:",
        len([w for w in ledger_ids if sel_tag_n.get(w, 0) > 0]),
        "/",
        len(ledger_ids),
    )
    print(
        "quota shortfalls:",
        {
            b: (sel_tag_n.get(b, 0), f)
            for b, f in QUOTA_FLOOR.items()
            if sel_tag_n.get(b, 0) < f
        },
    )


if __name__ == "__main__":
    main()
