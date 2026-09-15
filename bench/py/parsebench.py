#!/usr/bin/env python3
r"""parsebench — PROTOCOL 评测逻辑泛化跑分器: 任意语料目录 → 逐文件/逐论文指标.

逐 .tex: parse ok/error/ms (30s SIGALRM)、chunk 数与字符中位/p90、泄漏率
($ \cite \ref \begin{ 等, 与 miniscanner_test 同正则)、round-trip
identical/normalized/diverged+首差异位、fake-translation 死占位符/孤儿 chunk、
flatten 覆盖 (是否被主文件 \input 图触及).

逐论文: 主文件定位 (剥注释→documentclass/documentstyle, 多根标 multi_doc)、
class 名/选项、tex 数/总大小/非 UTF-8、路由标签 (reject/xelatex/minted/
non-utf8/no-hyperref)、孤儿 tex 列表.

用法:
  python3 bench/py/parsebench.py --corpus DIR [--manifest M.jsonl] --out DIR

产出 (docs/10 §统一产出契约): OUT/files.jsonl + OUT/papers.json + OUT/summary.md,
OUT 形如 bench/results/parsebench-{corpus}-{date}/.
manifest.jsonl 每行 {"id": "...", "era": ..., "archive": ...} → 按 era/archive
分组统计 (缺省则只按 documentclass 名分组). 论文目录形如 {id}/extracted/
时按 {id} 关联 manifest.

files.jsonl 逐文件契约字段: file / paper_id / ok / wall_ms / identity
(strict|normalized|diverged) / n_chunks / leak_hits[]; 另带 role / leak /
recon / fake / bug1_ph_tail 等明细.

判定逻辑全部复用 miniscanner_test (parse_one/scan_chunks/classify_recon/
rebuild_metrics), 保证与 miniscanner-parse.json 同口径可互相对拍.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import miniscanner as ms
import miniscanner_test as mt  # 复用同口径判定函数

TIMEOUT_S = 30
GROUP_KEYS = ["era", "archive"]  # manifest 里存在的键才分组


# ---------------------------------------------------------------- 工具


def strip_comments(tex: str) -> str:
    r"""去注释: `\X` 先吃两字符 (故 \% 不触发注释, \\% 后 % 仍是注释),
    裸 % 到行尾丢弃 (保留换行). 不感知 verbatim — 仅用于主文件定位/路由标签."""
    out = []
    i, n = 0, len(tex)
    while i < n:
        c = tex[i]
        if c == "\\":
            out.append(tex[i : i + 2])
            i += 2
            continue
        if c == "%":
            k = tex.find("\n", i)
            if k < 0:
                break
            out.append("\n")
            i = k + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def is_non_utf8(path: Path) -> bool:
    """含 0x80+ 字节且 UTF-8 decode 失败 → 非 UTF-8."""
    b = path.read_bytes()
    if not any(x > 0x7F for x in b):
        return False
    try:
        b.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


DOCCLASS_RX = re.compile(
    r"\\(documentclass|documentstyle)\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}",
    re.DOTALL,
)


def find_roots(tex_files: list[Path]) -> list[dict]:
    """剥注释后含 \\documentclass/\\documentstyle 的文件 → 根."""
    roots = []
    for p in sorted(tex_files):
        try:
            tex = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        m = DOCCLASS_RX.search(strip_comments(tex))
        if m:
            roots.append(
                {
                    "file": p,
                    "cmd": m.group(1),
                    "class": m.group(3).strip(),
                    # 选项内可穿插注释剥除后残留的换行 (2308.07483) → 归一化
                    "options": re.sub(r"\s+", " ", m.group(2) or "").strip(),
                }
            )
    return roots


def flatten_reach(tex: str, root_dir: str) -> set[str]:
    r"""跑 ms.flatten_inputs 并记录它实际 open 的文件 = \input 图可达集.

    在 miniscanner 模块命名空间临时注入 open 记录器 — 遍历/解析逻辑与
    flatten_inputs 严格同源 (file_dir→root_dir→basename 回退, 深度≤8,
    注释/verbatim 不展开)."""
    reached: set[str] = set()
    sentinel = object()
    orig = ms.__dict__.get("open", sentinel)

    def rec(file, *a, **k):
        reached.add(os.path.abspath(file))
        return open(file, *a, **k)

    ms.open = rec
    try:
        ms.flatten_inputs(tex, root_dir, root_dir)
    except Exception as exc:  # 覆盖统计尽力而为; 解析异常由逐文件 pass 记录
        print(
            f"  flatten_reach warn: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    finally:
        if orig is sentinel:
            ms.__dict__.pop("open", None)
        else:
            ms.open = orig
    return reached


def percentile(sorted_vals: list[int], q: float) -> int | None:
    """最近秩分位: idx=ceil(q*n)-1."""
    if not sorted_vals:
        return None
    return sorted_vals[max(0, math.ceil(q * len(sorted_vals)) - 1)]


PH_RX = re.compile(r"\[\[[A-Z_]+_\d+\]\]")


def ph_tail_risk(res: ms.ScanResult) -> int:
    r"""BUG1 回归计数 (docs/07 §11): 占位符 body 以 `\letters` 结尾且其后继字符
    是字母 → 展开后命令吞掉后继字母, token 合并. 扫描域 = protected_tex +
    ph bodies + chunk contents (嵌套占位符的全部可见位置)."""
    blob = (
        res.protected_tex
        + "\n"
        + "\n".join(res.ph_map.values())
        + "\n"
        + "\n".join(c.content for c in res.chunks)
    )
    n = 0
    for m in PH_RX.finditer(blob):
        body = res.ph_map.get(m.group(0), "")
        if re.search(r"\\[a-zA-Z]+$", body) and blob[m.end() : m.end() + 1].isalpha():
            n += 1
    return n


# ---------------------------------------------------------------- 路由标签

RX_EPS_PS = re.compile(
    r"\.eps\b|pstricks|\\begin\{pspicture\}|"
    r"\\usepackage(?:\[[^\]]*\])?\{pst[-a-z]*",
    re.IGNORECASE,
)
RX_MINTED = re.compile(
    r"\\begin\{minted\}|\\inputminted|\\mint(?:inline)?\b|"
    r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*minted"
)
RX_HYPERREF = re.compile(
    r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*hyperref"
)


def paper_tags(roots: list[dict], stripped_blob: str, non_utf8: list[str]) -> list[str]:
    tags = []
    if any(r["cmd"] == "documentstyle" for r in roots):
        tags.append("reject")  # LaTeX 2.09 \documentstyle
    if RX_EPS_PS.search(stripped_blob):
        tags.append("xelatex")  # .eps/pstricks → 非 pdflatex 路由
    if RX_MINTED.search(stripped_blob):
        tags.append("minted")  # 需 -shell-escape
    if non_utf8:
        tags.append("non-utf8")
    if not RX_HYPERREF.search(stripped_blob):
        tags.append("no-hyperref")
    return tags


# ---------------------------------------------------------------- 逐文件评测


def file_metrics(path: Path, rel: str, paper: str, role: str, non_utf8: bool) -> dict:
    entry = {
        "file": rel,
        "paper_id": paper,
        "role": role,  # root / input_reached / orphan / no_root
        "size": path.stat().st_size,
        "non_utf8": non_utf8,
    }
    r = mt.parse_one(path, timeout_s=TIMEOUT_S, flatten=True)
    entry["ok"] = r["ok"]
    entry["wall_ms"] = r["ms"]
    if not r["ok"]:
        entry["error"] = r["error"]
        return entry

    res: ms.ScanResult = r["res"]
    entry["n_chunks"] = len(res.chunks)
    entry["n_placeholders"] = len(res.ph_map)
    lens = sorted(len(c.content) for c in res.chunks)
    entry["chunk_chars_median"] = statistics.median(lens) if lens else None
    entry["chunk_chars_p90"] = percentile(lens, 0.9)
    entry["chunk_chars_max"] = lens[-1] if lens else None
    entry["_lens"] = lens  # 聚合用, 落盘前剔除

    lk = mt.scan_chunks(res)  # 同 test: 6 组正则, chunk 命中任一即泄漏
    entry["leak"] = {
        "n_translatable": lk["n_translatable_chunks"],
        "n_leaked": lk["n_leaked"],
        "rate": (
            round(lk["n_leaked"] / lk["n_translatable_chunks"], 4)
            if lk["n_translatable_chunks"]
            else None
        ),
        "hits": {k: v for k, v in lk["hits"].items() if v},
        # 逐条归因素材 (≤5/file, 同 miniscanner_test 口径): context/hits/snippet
        "examples": lk["examples"],
    }
    entry["leak_hits"] = sorted(entry["leak"]["hits"])

    rb = mt.rebuild_metrics(res)  # identity + fake-translation 重建 (同 test)
    orig = path.read_text(encoding="utf-8", errors="replace")
    orig_flat = ms.flatten_inputs(orig, str(path.parent), str(path.parent))
    status, ratio, first_diff = mt.classify_recon(orig_flat, rb["recon_identity"])
    # 契约命名: identical → strict (docs/09 §7.1 GROBID strict match)
    entry["identity"] = {"identical": "strict"}.get(status, status)
    entry["recon"] = {
        "quick_ratio": ratio,
        "first_diff_at": first_diff,
    }
    entry["fake"] = {
        "residue_chunk_ph": rb["residue_chunk_ph"],
        "residue_protect_ph": rb["residue_protect_ph"],
        "n_orphan_chunks": rb["n_orphan_chunks"],
    }
    entry["bug1_ph_tail"] = ph_tail_risk(res)
    return entry


# ---------------------------------------------------------------- 论文分组


def is_tex(p: Path) -> bool:
    """大小写不敏感 .tex 判定——野语料存在 .TEX 古早文件
    (corpus_v3 实测: 0707.2108/pmeyerxi.TEX, 0806.0433/*.TEX)."""
    return p.is_file() and p.suffix.lower() == ".tex"


def glob_tex(d: Path) -> list[Path]:
    return [p for p in d.iterdir() if is_tex(p)]


def rglob_tex(d: Path) -> list[Path]:
    return [p for p in d.rglob("*") if is_tex(p)]


def discover_papers(corpus: Path) -> tuple[dict[str, Path], set[str]]:
    """corpus 下一层目录直接含 .tex → 论文; 否则为 archive 分组目录
    (hep-th/9901001 式旧版 ID), 论文在第二层. corpus 根目录自身直接含
    .tex 时 → 整个 corpus 视为单论文 (id=目录名). 返回 (pid→dir, groupers)."""
    if glob_tex(corpus):
        return {corpus.name: corpus}, set()
    groupers = {d.name for d in corpus.iterdir() if d.is_dir() and not glob_tex(d)}
    papers: dict[str, Path] = {}
    for d in sorted(corpus.iterdir()):
        if not d.is_dir():
            continue
        if d.name in groupers:
            for sub in sorted(d.iterdir()):
                if sub.is_dir() and rglob_tex(sub):
                    papers[f"{d.name}/{sub.name}"] = sub
        elif rglob_tex(d):
            papers[d.name] = d
    return papers, groupers


def paper_id_of(rel: Path, groupers: set[str], single: Path | None) -> str:
    parts = rel.parts
    if single is not None:
        return single.name
    if len(parts) == 1:
        return Path(parts[0]).stem
    return "/".join(parts[:2]) if parts[0] in groupers else parts[0]


def analyze_paper(paper_id: str, pdir: Path, corpus: Path) -> dict:
    tex_files = sorted(rglob_tex(pdir))
    all_files = [p for p in pdir.rglob("*") if p.is_file()]
    non_utf8_set = {os.path.abspath(p) for p in tex_files if is_non_utf8(p)}

    roots = find_roots(tex_files)
    stripped_blob = "\n".join(
        strip_comments(p.read_text(encoding="utf-8", errors="replace"))
        for p in tex_files
    )

    # flatten 覆盖: 所有根的 \input 图并集 (multi_doc 时并集口径)
    covered: set[str] = set()
    reach_by_root: dict[str, set[str]] = {}
    for r in roots:
        tex = r["file"].read_text(encoding="utf-8", errors="replace")
        reach = flatten_reach(tex, str(r["file"].parent))
        reach.add(os.path.abspath(r["file"]))
        reach_by_root[os.path.abspath(r["file"])] = reach
        covered |= reach

    primary = None
    if roots:
        # 主文件 = \input 图触及文件最多的根 (multi_doc 的代表), 平手取路径短者
        primary = max(
            roots,
            key=lambda r: (
                len(reach_by_root[os.path.abspath(r["file"])]),
                -len(str(r["file"])),
            ),
        )["file"]

    return {
        "id": paper_id,
        "dir": str(pdir.relative_to(corpus)),
        "n_tex": len(tex_files),
        "n_files": len(all_files),
        "tex_bytes": sum(p.stat().st_size for p in tex_files),
        "total_bytes": sum(p.stat().st_size for p in all_files),
        "roots": [
            {
                "file": str(r["file"].relative_to(pdir)),
                "cmd": r["cmd"],
                "class": r["class"],
                "options": r["options"],
            }
            for r in roots
        ],
        "multi_doc": len(roots) > 1,
        "primary_root": str(primary.relative_to(pdir)) if primary else None,
        "docclass": roots[0]["class"] if roots else None,
        "docclass_options": roots[0]["options"] if roots else None,
        "non_utf8_files": [
            str(Path(p).relative_to(pdir)) for p in sorted(non_utf8_set)
        ],
        "tags": paper_tags(roots, stripped_blob, [str(x) for x in non_utf8_set]),
        "orphan_tex": [
            str(p.relative_to(pdir))
            for p in tex_files
            if roots and os.path.abspath(p) not in covered
        ],
        # 内部键 (落盘前剔除)
        "_covered": covered,
        "_tex_files": tex_files,
        "_roots": {os.path.abspath(r["file"]) for r in roots},
        "_non_utf8": non_utf8_set,
    }


# ---------------------------------------------------------------- 聚合


def aggregate(files: list[dict]) -> dict:
    ok = [f for f in files if f.get("ok")]
    recon = {"strict": 0, "normalized": 0, "diverged": 0}
    chunks = leaked = 0
    res_c = res_p = orph = bug1 = 0
    hits: dict[str, int] = {}
    lens: list[int] = []
    for f in ok:
        recon[f["identity"]] += 1
        lk = f["leak"]
        chunks += lk["n_translatable"]
        leaked += lk["n_leaked"]
        for k, v in lk["hits"].items():
            hits[k] = hits.get(k, 0) + v
        res_c += f["fake"]["residue_chunk_ph"]
        res_p += f["fake"]["residue_protect_ph"]
        orph += f["fake"]["n_orphan_chunks"]
        bug1 += f["bug1_ph_tail"]
        lens.extend(f.get("_lens") or [])
    lens.sort()
    return {
        "files": len(files),
        "ok": len(ok),
        "error": len(files) - len(ok),
        "ok_rate": round(len(ok) / len(files), 4) if files else None,
        "strict": recon["strict"],
        "normalized": recon["normalized"],
        "diverged": recon["diverged"],
        "identity_rate": round(recon["strict"] / len(ok), 4) if ok else None,
        "chunks": chunks,
        "leaked_chunks": leaked,
        "leak_rate": round(leaked / chunks, 4) if chunks else None,
        "hits": hits,
        "chunk_chars_median": statistics.median(lens) if lens else None,
        "chunk_chars_p90": percentile(lens, 0.9),
        "residue_chunk_ph": res_c,
        "residue_protect_ph": res_p,
        "orphan_chunks": orph,
        "bug1_ph_tail": bug1,
    }


def load_manifest(path: Path | None) -> dict[str, dict]:
    if not path:
        return {}
    out = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        rec = json.loads(line)
        pid = rec.get("id") or rec.get("arxiv") or rec.get("paper_id")
        if pid:
            out[str(pid)] = rec
    return out


def _pct(x: float | None, nd: int = 1) -> str:
    return f"{100 * x:.{nd}f}" if x is not None else "—"


def write_summary(
    out_md: Path,
    corpus: Path,
    files: list[dict],
    papers: list[dict],
    manifest: dict[str, dict],
    wall_s: float,
) -> None:
    lines = []
    tot = aggregate(files)
    n_reached = sum(1 for f in files if f["role"] in ("root", "input_reached"))
    n_orphan = sum(1 for f in files if f["role"] == "orphan")
    lines.append(f"# parsebench summary — {corpus.name}\n")
    lines.append(
        f"- papers: {len(papers)}   files (.tex): {tot['files']}   wall: {wall_s}s"
    )
    lines.append(
        f"- parse ok: **{tot['ok']}/{tot['files']}** "
        f"({_pct(tot['ok_rate'])}%)   errors: {tot['error']}"
    )
    lines.append(
        f"- identity: strict **{tot['strict']}** / normalized "
        f"{tot['normalized']} / diverged {tot['diverged']} "
        f"(strict-rate {_pct(tot['identity_rate'])}%)"
    )
    lines.append(
        f"- leak: **{tot['leaked_chunks']}/{tot['chunks']}** chunks "
        f"= {_pct(tot['leak_rate'], 2)}%   hits={tot['hits']}"
    )
    lines.append(
        f"- chunk chars: median {tot['chunk_chars_median']}   "
        f"p90 {tot['chunk_chars_p90']}"
    )
    lines.append(
        f"- fake-translation: dead CHUNK ph {tot['residue_chunk_ph']}   "
        f"dead protect ph {tot['residue_protect_ph']}   "
        f"orphan chunks {tot['orphan_chunks']}   "
        f"bug1 ph-tail {tot['bug1_ph_tail']}"
    )
    lines.append(
        f"- flatten coverage: {n_reached} reached / {n_orphan} orphan tex / "
        f"{sum(1 for f in files if f['role'] == 'no_root')} rootless\n"
    )

    # ---- docs/10 B1 漏斗: fetched → .tex → rooted → ok → identity → leak → dead/orphan
    n_multi = sum(1 for p in papers if p["multi_doc"])
    n_rootless = sum(1 for p in papers if not p["roots"])
    lines.append("## funnel\n")
    lines.append("| stage | n |")
    lines.append("|---|---|")
    if manifest:
        n_src_ok = sum(1 for m in manifest.values() if m.get("status") == "ok")
        lines.append(f"| manifest rows | {len(manifest)} |")
        lines.append(f"| source ok (manifest) | {n_src_ok} |")
    lines.append(f"| papers discovered | {len(papers)} |")
    lines.append(f"| .tex files | {tot['files']} |")
    lines.append(
        f"| rooted papers | {len(papers) - n_rootless} "
        f"(multi_doc {n_multi}, rootless {n_rootless}) |"
    )
    lines.append(f"| parse ok | {tot['ok']} |")
    lines.append(
        f"| identity | strict {tot['strict']} / normalized "
        f"{tot['normalized']} / diverged {tot['diverged']} |"
    )
    lines.append(f"| translatable chunks | {tot['chunks']} |")
    lines.append(f"| leaked chunks | {tot['leaked_chunks']} |")
    lines.append(f"| dead CHUNK ph | {tot['residue_chunk_ph']} |")
    lines.append(f"| dead protect ph | {tot['residue_protect_ph']} |")
    lines.append(f"| orphan chunks | {tot['orphan_chunks']} |")
    lines.append(f"| bug1 ph-tail | {tot['bug1_ph_tail']} |")
    lines.append(
        f"| flatten reached / orphan / rootless | "
        f"{n_reached} / {n_orphan} / "
        f"{sum(1 for f in files if f['role'] == 'no_root')} |\n"
    )

    errs = [f for f in files if not f.get("ok")]
    if errs:
        lines.append("## parse errors\n")
        lines.append("| file | error | wall_ms |")
        lines.append("|---|---|---|")
        lines.extend(
            f"| {f['file']} | {f.get('error', '')} | {f['wall_ms']} |" for f in errs
        )
        lines.append("")

    # ---- 泄漏逐条归因表 (docs/10 B1-4: 人工复核素材)
    leaked_files = [f for f in files if f.get("leak", {}).get("n_leaked")]
    if leaked_files:
        lines.append("## leak detail\n")
        lines.append("| file | leaked/trans | hits | leaked-chunk snippets |")
        lines.append("|---|---|---|---|")
        for f in leaked_files:
            lk = f["leak"]
            ex = "<br>".join(
                f"{e['leaks']} `{e['snippet'][:80]}`" for e in lk["examples"]
            )
            more = (
                f" (+{lk['n_leaked'] - len(lk['examples'])} more)"
                if lk["n_leaked"] > len(lk["examples"])
                else ""
            )
            lines.append(
                f"| {f['file']} | {lk['n_leaked']}/{lk['n_translatable']} "
                f"| {','.join(lk['hits'])} | {ex}{more} |"
            )
        lines.append("")

    lines.append("## per-paper\n")
    lines.append(
        "| paper | class | options | roots | tags | tex | ok | strict | "
        "leak% | orphan-tex |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for p in papers:
        s = p["stats"]
        cls = p["docclass"] or "—"
        if p["multi_doc"]:
            cls += f" (×{len(p['roots'])})"
        lines.append(
            f"| {p['id']} | {cls} | {p['docclass_options'] or '—'} "
            f"| {len(p['roots'])} | {', '.join(p['tags']) or '—'} "
            f"| {s['files']} | {s['ok']} | {s['strict']} "
            f"| {_pct(s['leak_rate'], 2)} | {len(p['orphan_tex'])} |"
        )
    lines.append("")

    def group_table(title: str, key_fn) -> None:
        groups: dict[str, list[dict]] = {}
        for p in papers:
            groups.setdefault(str(key_fn(p) or "—"), []).append(p)
        lines.append(f"## by {title}\n")
        lines.append(f"| {title} | papers | files | ok% | ident% | leak% |")
        lines.append("|---|---|---|---|---|---|")
        for g in sorted(groups):
            pids = {pp["id"] for pp in groups[g]}
            s = aggregate([f for f in files if f["paper_id"] in pids])
            lines.append(
                f"| {g} | {len(groups[g])} | {s['files']} "
                f"| {_pct(s['ok_rate'])} | {_pct(s['identity_rate'])} "
                f"| {_pct(s['leak_rate'], 2)} |"
            )
        lines.append("")

    group_table("class", lambda p: p["docclass"])
    if manifest:
        for k in GROUP_KEYS:
            if any(k in m for m in manifest.values()):
                group_table(k, lambda p, k=k: p.get("meta", {}).get(k))

    out_md.write_text("\n".join(lines), encoding="utf-8")


# ---------------------------------------------------------------- main


def main() -> None:
    ap = argparse.ArgumentParser(description="corpus parse benchmark (miniscanner)")
    ap.add_argument("--corpus", required=True, type=Path)
    ap.add_argument("--manifest", type=Path, default=None)
    ap.add_argument(
        "--out",
        required=True,
        type=Path,
        help="产出目录 (契约: files.jsonl + papers.json + summary.md)",
    )
    args = ap.parse_args()

    corpus = args.corpus.resolve()
    out = args.out
    if not out.is_absolute():
        out = Path.cwd() / out
    out.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(args.manifest)

    t0 = time.perf_counter()
    tex_files = sorted(rglob_tex(corpus))
    papers, groupers = discover_papers(corpus)
    single = next(iter(papers.values())) if len(papers) == 1 else None
    if single is not None and single != corpus:
        single = None  # 仅当 corpus 自身即论文时启用
    print(f"corpus {corpus}: {len(tex_files)} .tex in {len(papers)} papers")

    # ---- pass 1: 论文级 (主文件定位/路由标签/flatten 覆盖)
    prec_map: dict[str, dict] = {}
    for pid, pdir in sorted(papers.items()):
        prec = analyze_paper(pid, pdir, corpus)
        # corpus_v2 布局: 论文目录是 {id}/extracted/, manifest id 是 {id}
        mkey = pid.removesuffix("/extracted")
        if mkey in manifest:
            prec["meta"] = manifest[mkey]
        prec_map[pid] = prec
    n_multi = sum(1 for p in prec_map.values() if p["multi_doc"])
    n_rootless = sum(1 for p in prec_map.values() if not p["roots"])
    print(f"  roots: {n_multi} multi_doc, {n_rootless} rootless")
    if manifest:
        n_meta = sum(1 for p in prec_map.values() if "meta" in p)
        print(f"  manifest matched: {n_meta}/{len(prec_map)} papers")

    # ---- pass 2: 逐文件评测
    file_entries = []
    for i, f in enumerate(tex_files):
        rel = f.relative_to(corpus)
        pid = paper_id_of(rel, groupers, single)
        prec = prec_map.get(pid)
        apath = os.path.abspath(f)
        if prec is None or not prec["_roots"]:
            role = "no_root"
        elif apath in prec["_roots"]:
            role = "root"
        elif apath in prec["_covered"]:
            role = "input_reached"
        else:
            role = "orphan"
        e = file_metrics(
            f, str(rel), pid, role, apath in (prec["_non_utf8"] if prec else set())
        )
        file_entries.append(e)
        if (i + 1) % 25 == 0 or i + 1 == len(tex_files):
            print(f"  {i + 1}/{len(tex_files)} files...")

    # ---- 论文级聚合 stats
    for prec in prec_map.values():
        pfiles = [e for e in file_entries if e["paper_id"] == prec["id"]]
        prec["stats"] = aggregate(pfiles)
        for k in ("_covered", "_tex_files", "_roots", "_non_utf8"):
            prec.pop(k, None)

    wall = round(time.perf_counter() - t0, 1)
    paper_list = sorted(prec_map.values(), key=lambda p: p["id"])

    # ---- 落盘 (docs/10 契约三件套)
    f_jsonl = out / "files.jsonl"
    p_json = out / "papers.json"
    s_md = out / "summary.md"

    with f_jsonl.open("w", encoding="utf-8") as fh:
        for e in file_entries:
            fh.write(
                json.dumps(
                    {k: v for k, v in e.items() if k != "_lens"},
                    ensure_ascii=False,
                )
                + "\n"
            )
    p_json.write_text(
        json.dumps(
            {"corpus": str(corpus), "wall_s": wall, "papers": paper_list},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_summary(s_md, corpus, file_entries, paper_list, manifest, wall)

    tot = aggregate(file_entries)
    print(
        f"done {wall}s — ok {tot['ok']}/{tot['files']}, "
        f"strict {tot['strict']}, leak {tot['leak_rate']} "
        f"({tot['leaked_chunks']}/{tot['chunks']})"
    )
    print(f"wrote {f_jsonl}\n      {p_json}\n      {s_md}")


if __name__ == "__main__":
    main()
