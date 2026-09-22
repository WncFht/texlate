"""booster-select — B01–B07 地板配额补强选择器（verb 形态）。

``bench/corpus/select_booster.py`` 的逐字移植：nominations/*.jsonl 多
agent 提名并集 → 三段选择（B 地板配额内稀有度优先 → W 机制逐代表 →
稀有度填充至 CAP）→ booster_selection.jsonl + selection_report.md。

纯局部确定性变换：无 cell/无测量/无 stage 语义——verb 非 spec。
产出是 tracked 文件（gitignore 白名单点名），跑完 git status 见 delta
属预期。v3 corpus 管线的 extract-booster 消费 booster_selection.jsonl。
"""

import json
import re
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
DEFAULT_CORPUS = REPO / "bench" / "corpus"

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

ARXIV_ID_RX = re.compile(
    r"(?:\d{4}\.\d{4,5}|(?:cond-mat|hep-\w+|math|cs|astro-ph|nucl-\w+|"
    r"quant-ph|gr-qc|nlin|physics|stat|adap-org|alg-geom|chao-dyn|cmp-lg|"
    r"dg-ga|funct-an|patt-sol|q-alg|solv-int|supr-con|acc-phys|ao-sci|"
    r"atom-ph|bayes-an|chem-ph|plasm-ph|q-bio)/\d{7})"
)


def band_of(d: dict) -> str:
    cid = d.get("cluster_id") or d.get("cluster") or ""
    if not cid:
        m = re.search(r"staging/(C\d+)/", str(d.get("evidence") or ""))
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


def load(nom_dir: Path) -> dict[str, dict]:
    """id → merged nom（多 agent 重复提名合并 tags + sources）。"""
    merged: dict[str, dict] = {}
    for f in sorted(nom_dir.glob("*.jsonl")):
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


def ledger_cites(mech_path: Path) -> dict[str, set[str]]:
    """W 机制 → 台账例证论文集（examples+evidence 引用，不限池内）。"""
    out: dict[str, set[str]] = defaultdict(set)
    for line in mech_path.open():
        d = json.loads(line)
        mid = d["mech_id"]
        if not mid.startswith("W"):
            continue
        text = d.get("evidence", "") + " " + " ".join(d.get("examples", []))
        out[mid] |= set(ARXIV_ID_RX.findall(text))
    return out


def derive(mech_path: Path, noms: dict[str, dict]) -> dict[str, set[str]]:
    """台账 W 条目 examples/evidence 引用的池内论文 → 派生覆盖 tag.

    提案是"在该论文上观察到的"——论文被提名时 tag 可能只写了 B 面。
    """
    out: dict[str, set[str]] = defaultdict(set)
    for line in mech_path.open():
        d = json.loads(line)
        mid = d["mech_id"]
        if not mid.startswith("W"):
            continue
        text = d.get("evidence", "") + " " + " ".join(d.get("examples", []))
        for pid in ARXIV_ID_RX.findall(text):
            if pid in noms:
                out[pid].add(mid)
    return out


def run_select(corpus: Path, cap: int, nom_dir: Path, out: Path,
               report: Path) -> dict:
    """The selection itself, verbatim. Returns the summary dict."""
    noms = load(nom_dir)
    # 两层必须不相交：核心层已中选的论文不入补强池（重叠会让 meta.layer 二义）
    core_mf = corpus / "manifest.jsonl"
    core_ids: set[str] = set()
    if core_mf.exists():
        core_ids = {json.loads(ln)["id"] for ln in core_mf.open()}
        noms = {pid: d for pid, d in noms.items() if pid not in core_ids}
    mech_path = corpus / "mechanisms.jsonl"
    derived = derive(mech_path, noms)
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
        for line in mech_path.open()
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

    # ---- 3. 稀有度填充至 cap
    rest = [d for d in noms.values() if d["id"] not in selected]
    rest.sort(key=rarity_score, reverse=True)
    for d in rest[: max(0, cap - len(selected))]:
        pick(d["id"], "rarity-fill")

    out.write_text(
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
    cites = ledger_cites(mech_path)
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
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return {
        "n_noms": len(noms),
        "n_selected": len(selected),
        "bands": dict(sorted(band_n.items())),
        "w_covered": len([w for w in ledger_ids if sel_tag_n.get(w, 0) > 0]),
        "w_total": len(ledger_ids),
        "quota_shortfalls": {
            b: (sel_tag_n.get(b, 0), f)
            for b, f in QUOTA_FLOOR.items()
            if sel_tag_n.get(b, 0) < f
        },
    }


def add_args(sp) -> None:
    sp.add_argument("--corpus-dir", default=str(DEFAULT_CORPUS),
                    help="corpus root holding manifest.jsonl + mechanisms.jsonl")
    sp.add_argument("--cap", type=int, default=CAP,
                    help="total selection cap (default 200)")
    sp.add_argument("--nom-dir", default=None,
                    help="nominations dir (default <corpus>/nominations)")
    sp.add_argument("--out", default=None,
                    help="output jsonl (default <corpus>/booster_selection.jsonl)")
    sp.add_argument("--report", default=None,
                    help="output report (default <corpus>/selection_report.md)")


def main(args) -> int:
    corpus = Path(args.corpus_dir).expanduser().resolve()
    nom_dir = Path(args.nom_dir) if args.nom_dir else corpus / "nominations"
    out = Path(args.out) if args.out else corpus / "booster_selection.jsonl"
    report = (
        Path(args.report) if args.report else corpus / "selection_report.md"
    )
    if not nom_dir.is_dir():
        print(f"booster-select: nominations dir absent: {nom_dir}")
        return 1
    if not (corpus / "mechanisms.jsonl").is_file():
        print(f"booster-select: mechanisms.jsonl absent under {corpus}")
        return 1
    summary = run_select(corpus, int(args.cap), nom_dir, out, report)
    print(f"selected {summary['n_selected']} / {summary['n_noms']} noms")
    print("bands:", summary["bands"])
    print("W covered:", summary["w_covered"], "/", summary["w_total"])
    print("quota shortfalls:", summary["quota_shortfalls"])
    return 0
