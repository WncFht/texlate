#!/usr/bin/env python3
r"""parsebench v2 — ``texlate.latex`` 产品管线评测器 (docs/spec/benchmark.md §B1).

逐 .tex: parse ok/error/ms (30s SIGALRM)、chunk 数与字符中位/p90、泄漏率
($ \cite \ref \begin{ \if \input 六组正则, docs/spec/corpus.md 口径)、round-trip
(vtex vs recon) strict/normalized/diverged+首差异位、flat→vtex 展开足迹、
fake-translation 死占位符/孤儿 chunk、
scan/validate warnings 计数、flatten 覆盖 (是否被主文件 \input 图触及).

逐论文: 主文件定位 (剥注释→documentclass/documentstyle, 多根标 multi_doc)、
class 名/选项、tex 数/总大小/非 UTF-8、路由标签 (reject/xelatex/minted/
non-utf8/no-hyperref——B3 静态路由金标准)、孤儿 tex 清单、stratum_cell/
cluster_id/权重 (供 docs/spec/corpus.md 统计与事后分层).

统计口径 (docs/spec/corpus.md, §8 门槛): 加权池化率 (事后分层权重 w_cell =
frame_cell/sample_cell, stratum_cell 来自 corpus manifest, frame 宇宙计数
来自 bench/frame/strata-era-cat.csv) + 宏平均 (逐篇等权, olmOCR 式) +
raw pooled 三口径并列; Wilson 95% CI (iid 近似) + 月簇稳健 bootstrap CI
(cluster_id‖yymm 重抽样, 无簇键时退化为逐篇 iid bootstrap). 无 stratum_cell
的语料 (corpus39/corpus_v2) 加权列退化为等权 = raw pooled, 报告中注明.

用法:
  uv run python bench/py/parsebench.py --corpus bench/corpus [--out DIR]
  python3 bench/py/parsebench.py --corpus corpus_daily --limit 20   # src shim 兜底

产出 (docs/spec/benchmark.md 统一产出契约): OUT/files.jsonl + OUT/papers.json + OUT/summary.md,
OUT 默认 bench/results/parsebench-{corpus.name}-{date}/.
files.jsonl 逐文件 append 落盘（行在=done）——同 OUT 重跑自动续跑已完成
文件（--rerun 强制重测）；papers.json/summary.md 仍是末尾汇总报告。
manifest 默认 <corpus>/manifest.jsonl; 每行 {"id": ..., "stratum_cell": ...,
"cluster_id": ..., "layer": ...} → 分组统计 + 权重; corpus39 无 manifest →
只按 documentclass 名分组, 统计退化等权. 论文目录形如 {id}/extracted/ 或
{archive}/{id}/ (extracted 子树) 时按 {id} / {archive}/{id} 关联 manifest.

files.jsonl 逐文件契约字段: file / paper_id / ok / wall_ms / identity
(strict|normalized|diverged) / n_chunks / leak_hits[]; 另带 role / leak /
recon / fake / warn_kinds / unresolved_inputs / bug1_ph_tail / vtex_len /
vtex_vs_src 等明细; _lens (逐 chunk 字符数原始表) 随行保留——续跑重载后
聚合仍保真. vtex_len 兼作同代 schema 戳（旧代行无此键, 续跑自动重测）.

判定逻辑: 解析/展平/重建全部走 ``texlate.latex`` (api.parse_file +
flatten.flatten_inputs + reconstruct.reconstruct + validate_result);
flatten 覆盖经 ``texlate.latex.flatten._read_file`` 接缝记录实际读取集
(该接缝即为此用途预留).
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import math
import os
import random
import re
import signal
import statistics
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))  # uv venv 外直跑兼容; uv run 下等价已装包

import benchlib

import texlate.latex.flatten as flatten_mod
from texlate.latex import (
    flatten_inputs,
    parse_file,
    reconstruct,
    validate_result,
)
from texlate.textutil import decode_tex

if TYPE_CHECKING:
    from texlate.latex.model import ScanResult

TIMEOUT_S = 30
GROUP_KEYS = ["era", "archive", "year_band", "stratum_cell", "cluster_id", "layer"]
DEFAULT_FRAME_COUNTS = ROOT / "bench" / "frame" / "strata-era-cat.csv"
BOOTSTRAP_B = 2000
BOOTSTRAP_SEED = 20260915


class ParseTimeout(Exception):
    """SIGALRM 触发的解析超时."""


def _alarm(signum, frame):
    raise ParseTimeout


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
            tex = decode_tex(p.read_bytes())
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


def flatten_reach(tex: str, root_dir: str, *, top_dir: str | None = None) -> set[str]:
    r"""跑 flatten_inputs 并记录它实际读取的文件 = \input 图可达集.

    经 ``texlate.latex.flatten._read_file`` 文件读取接缝注入记录器——
    该接缝即为此用途预留 (flatten.py:76 注释); 遍历/解析逻辑与
    flatten_inputs 严格同源 (file_dir→root_dir→basename 回退, 深度≤8,
    注释/verbatim 不展开, _seen 断环). ``top_dir`` = 论文顶层目录兜底
    (深位 root 的 e-print 根相对 \input, hep-ex/0307068 实例)."""
    reached: set[str] = set()
    orig_reader = flatten_mod._read_file

    def rec(path: str) -> str:
        reached.add(os.path.abspath(path))
        return orig_reader(path)

    flatten_mod._read_file = rec
    try:
        flatten_inputs(tex, root_dir, root_dir, top_dir=top_dir)
    except Exception as exc:  # 覆盖统计尽力而为; 解析异常由逐文件 pass 记录
        print(
            f"  flatten_reach warn: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
    finally:
        flatten_mod._read_file = orig_reader
    return reached


def percentile(sorted_vals: list[int], q: float) -> int | None:
    """最近秩分位: idx=ceil(q*n)-1."""
    if not sorted_vals:
        return None
    return sorted_vals[max(0, math.ceil(q * len(sorted_vals)) - 1)]


PH_TOKEN_RX = re.compile(r"\[\[[A-Z_]+_\d+\]\]")


def ph_tail_risk(res: ScanResult) -> int:
    r"""BUG1 回归计数 (docs/spec/latex-pipeline.md): 占位符 body 以 `\letters` 结尾且其后继字符
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
    for m in PH_TOKEN_RX.finditer(blob):
        body = res.ph_map.get(m.group(0), "")
        if re.search(r"\\[a-zA-Z]+$", body) and blob[m.end() : m.end() + 1].isalpha():
            n += 1
    return n


# ---------------------------------------------------------------- 判定 (docs/spec/corpus.md 口径, 产品 API 版)


def parse_one(path: Path, timeout_s: int) -> dict:
    """api.parse_file（产品路径）+ SIGALRM 超时.

    gullet 自解析 \\input 内联——vtex = 展开机产出；``flat`` 仍由
    flatten_inputs 算出供 vtex_vs_src 对照（展开足迹 = vtex 与 flatten
    输出的差异）。返回 {ok,res,flat,ms}|{ok,error,ms}.
    """
    t0 = time.perf_counter()
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout_s)
    try:
        orig = decode_tex(path.read_bytes())
        flat = flatten_inputs(orig, str(path.parent), str(path.parent))
        res = parse_file(str(path))
        ms_ = (time.perf_counter() - t0) * 1000
        return {"ok": True, "res": res, "flat": flat, "ms": round(ms_, 1)}
    except ParseTimeout:
        return {"ok": False, "error": f"Timeout(>{timeout_s}s)", "ms": timeout_s * 1000}
    except Exception as e:
        ms_ = (time.perf_counter() - t0) * 1000
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "ms": round(ms_, 1)}
    finally:
        signal.alarm(0)


LEAK_PATTERNS = {
    "dollar": re.compile(r"\$"),
    "cite_family": re.compile(r"\\cite[a-zA-Z]*"),
    "ref_family": re.compile(r"\\(?:eq|auto|c|page|name|sub)?ref(?![a-zA-Z])"),
    "begin_env": re.compile(r"\\begin\{"),
    "conditional": re.compile(r"\\(?:if[a-zA-Z]+|else|fi)(?![a-zA-Z])"),
    "input_include": re.compile(r"\\(?:input|include)\{"),
}


def scan_chunks(res: ScanResult) -> dict:
    """泄漏判据 (docs/spec/corpus.md): 可译 chunk 命中六组正则任一 → 记 hit."""
    per_chunk = []
    hits = dict.fromkeys(LEAK_PATTERNS, 0)
    leaked = 0
    for c in res.chunks:
        found = [name for name, rx in LEAK_PATTERNS.items() if rx.search(c.content)]
        if found:
            leaked += 1
            for f in found:
                hits[f] += 1
            per_chunk.append(
                {"context": c.context, "leaks": found, "snippet": c.content[:120]}
            )
    return {
        "n_translatable_chunks": len(res.chunks),
        "n_leaked": leaked,
        "hits": hits,
        "examples": per_chunk[:5],
    }


def orphan_chunk_ids(res: ScanResult) -> int:
    """chunk 的占位符在任何可及位置都见不到 → 内容被静默丢弃."""
    blob = (
        res.protected_tex
        + "\n"
        + "\n".join(res.ph_map.values())
        + "\n"
        + "\n".join(c.content for c in res.chunks)
    )
    orphans = 0
    for c in res.chunks:
        if f"[[CHUNK_{c.id}]]" not in blob:
            orphans += 1
    return orphans


def classify_recon(orig: str, recon: str) -> tuple[str, float, int]:
    """identity 三档 (docs/spec/corpus.md): strict 逐字节 / normalized 仅空白 / diverged."""
    if orig == recon:
        return "strict", 1.0, -1

    def norm(s):
        return re.sub(r"\s+", " ", s).strip()

    if norm(orig) == norm(recon):
        return "normalized", 1.0, -1
    i = 0
    n = min(len(orig), len(recon))
    while i < n and orig[i] == recon[i]:
        i += 1
    ratio = difflib.SequenceMatcher(None, orig, recon).quick_ratio()
    return "diverged", round(ratio, 4), i


def fake_translation(chunk, idx: int) -> str:
    """占位译文: 保留全部内嵌占位符 (契约面), 正文替换为全角标记."""
    keep = re.findall(r"\[\[[A-Z_]+_\d+\]\]", chunk.content)
    return f"【假译文{idx}】" + "".join(keep)


def rebuild_metrics(res: ScanResult) -> dict:
    """identity 重建 + fake-translation splice 残留 + 孤儿 chunk (docs/spec/corpus.md)."""
    recon_identity = reconstruct(res)
    translated = {c.id: fake_translation(c, i) for i, c in enumerate(res.chunks)}
    recon_fake = reconstruct(res, translated)
    residue_chunk = len(re.findall(r"\[\[CHUNK_\d+\]\]", recon_fake))
    residue_prot = len(re.findall(r"\[\[[A-Z_]+_\d+\]\]", recon_fake))
    return {
        "recon_identity": recon_identity,
        "recon_fake": recon_fake,
        "residue_chunk_ph": residue_chunk,
        "residue_protect_ph": residue_prot,
        "n_orphan_chunks": orphan_chunk_ids(res),
    }


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


def file_metrics(
    path: Path,
    rel: str,
    paper: str,
    role: str,
    non_utf8: bool,
    timeout_s: int,
) -> dict:
    entry = {
        "file": rel,
        "paper_id": paper,
        "role": role,  # root / input_reached / orphan / no_root
        "size": path.stat().st_size,
        "non_utf8": non_utf8,
    }
    r = parse_one(path, timeout_s)
    entry["ok"] = r["ok"]
    entry["wall_ms"] = r["ms"]
    if not r["ok"]:
        entry["error"] = r["error"]
        entry["vtex_len"] = None  # schema 戳: 续跑认此键判同代口径行
        return entry

    res: ScanResult = r["res"]
    entry["n_chunks"] = len(res.chunks)
    entry["n_placeholders"] = len(res.ph_map)
    entry["vtex_len"] = len(res.vtex)

    try:
        lens = sorted(len(c.content) for c in res.chunks)
        entry["chunk_chars_median"] = statistics.median(lens) if lens else None
        entry["chunk_chars_p90"] = percentile(lens, 0.9)
        entry["chunk_chars_max"] = lens[-1] if lens else None
        entry["_lens"] = lens  # 聚合用, 随行落盘（续跑后聚合仍保真）

        # scan/validate warnings 分类计数 (泄漏类 bug 第一手线索, docs/spec/latex-pipeline.md model)
        wk: dict[str, int] = {}
        for w in res.warnings:
            wk[w.kind] = wk.get(w.kind, 0) + 1
        for w in validate_result(res):
            wk[w.kind] = wk.get(w.kind, 0) + 1
        entry["warn_kinds"] = wk
        # res.inputs 混合语义: resolved 记 abs path, 漏网记原始名——isabs 过滤
        entry["unresolved_inputs"] = [
            name for _pos, name in res.inputs if not os.path.isabs(name)
        ]

        lk = scan_chunks(res)  # 6 组正则 (docs/spec/corpus.md), chunk 命中任一即泄漏
        entry["leak"] = {
            "n_translatable": lk["n_translatable_chunks"],
            "n_leaked": lk["n_leaked"],
            "rate": (
                round(lk["n_leaked"] / lk["n_translatable_chunks"], 4)
                if lk["n_translatable_chunks"]
                else None
            ),
            "hits": {k: v for k, v in lk["hits"].items() if v},
            # 逐条归因素材 (≤5/file): context/hits/snippet
            "examples": lk["examples"],
        }
        entry["leak_hits"] = sorted(entry["leak"]["hits"])

        rb = rebuild_metrics(res)  # identity + fake-translation 重建
        # recon 重建的是 res.vtex（展开后虚拟文本）→ 对比基准同侧
        status, ratio, first_diff = classify_recon(res.vtex, rb["recon_identity"])
        entry["identity"] = status
        entry["recon"] = {
            "quick_ratio": ratio,
            "first_diff_at": first_diff,
        }
        # 展开足迹: vtex vs 展平源 (strict = 展开机对本文件无净改动)
        entry["vtex_vs_src"] = classify_recon(r["flat"], res.vtex)[0]
        entry["fake"] = {
            "residue_chunk_ph": rb["residue_chunk_ph"],
            "residue_protect_ph": rb["residue_protect_ph"],
            "n_orphan_chunks": rb["n_orphan_chunks"],
        }
        entry["bug1_ph_tail"] = ph_tail_risk(res)
    except Exception as exc:
        # 判定层异常不判 parse 失败 (api.parse_file 已返回), 单列桶归因——
        # 统计分母用 measured=ok 且 measure_error 缺席的文件
        entry["measure_error"] = f"{type(exc).__name__}: {exc}"
    return entry


# ---------------------------------------------------------------- 论文分组


def is_tex(p: Path) -> bool:
    """大小写不敏感 .tex 判定——野语料存在 .TEX 古早文件
    (corpus 实测: 0707.2108/pmeyerxi.TEX, 0806.0433/*.TEX)."""
    return p.is_file() and p.suffix.lower() == ".tex"


def glob_tex(d: Path) -> list[Path]:
    return [p for p in d.iterdir() if is_tex(p)]


def rglob_tex(d: Path) -> list[Path]:
    return [p for p in d.rglob("*") if is_tex(p)]


def discover_papers(corpus: Path) -> tuple[dict[str, Path], set[str]]:
    """corpus 下一层目录直接含 .tex → 论文; 否则为 archive 分组目录
    (hep-th/9901001 式旧版 ID, 或 {id}/extracted 式 v2/v3 布局——extracted
    作为第二层目录落进论文键), 论文在第二层. corpus 根目录自身直接含
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
        strip_comments(decode_tex(p.read_bytes())) for p in tex_files
    )

    # flatten 覆盖: 所有根的 \input 图并集 (multi_doc 时并集口径)
    covered: set[str] = set()
    reach_by_root: dict[str, set[str]] = {}
    for r in roots:
        tex = decode_tex(r["file"].read_bytes())
        reach = flatten_reach(tex, str(r["file"].parent), top_dir=str(pdir))
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
        "rootless": not roots,
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


# ---------------------------------------------------------------- 聚合 + 统计


def _measured(files: list[dict]) -> list[dict]:
    """ok 且判定层无异常的文件——identity/leak/fake 指标的分母."""
    return [f for f in files if f.get("ok") and "measure_error" not in f]


def aggregate(files: list[dict]) -> dict:
    """raw pooled 口径 (分母=全体 .tex / 全体可译 chunk); 加权/宏平均另算."""
    ok = [f for f in files if f.get("ok")]
    meas = _measured(files)
    recon = {"strict": 0, "normalized": 0, "diverged": 0}
    chunks = leaked = 0
    res_c = res_p = orph = bug1 = 0
    hits: dict[str, int] = {}
    warn: dict[str, int] = {}
    lens: list[int] = []
    for f in meas:
        ident = f.get("identity")
        if ident in recon:
            recon[ident] += 1
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
    for f in files:
        for k, v in (f.get("warn_kinds") or {}).items():
            warn[k] = warn.get(k, 0) + v
    lens.sort()
    return {
        "files": len(files),
        "ok": len(ok),
        "error": len(files) - len(ok),
        "measure_error": len(ok) - len(meas),
        "ok_rate": round(len(ok) / len(files), 4) if files else None,
        "strict": recon["strict"],
        "normalized": recon["normalized"],
        "diverged": recon["diverged"],
        "identity_rate": round(recon["strict"] / len(meas), 4) if meas else None,
        "chunks": chunks,
        "leaked_chunks": leaked,
        "leak_rate": round(leaked / chunks, 4) if chunks else None,
        "hits": hits,
        "warn_kinds": warn,
        "chunk_chars_median": statistics.median(lens) if lens else None,
        "chunk_chars_p90": percentile(lens, 0.9),
        "residue_chunk_ph": res_c,
        "residue_protect_ph": res_p,
        "orphan_chunks": orph,
        "bug1_ph_tail": bug1,
    }


def load_manifest(path: Path | None) -> dict[str, dict]:
    if not path or not path.exists():
        return {}
    out = {}
    for rec in benchlib.iter_jsonl(path):
        pid = rec.get("id") or rec.get("arxiv") or rec.get("paper_id")
        if pid:
            out[str(pid)] = rec
    return out


def load_frame_counts(path: Path | None) -> dict[str, int]:
    """frame 宇宙 cell 计数: csv year_band,cat_group,n → {"band|cat": n}."""
    if not path or not path.exists():
        return {}
    out = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[f"{row['year_band']}|{row['cat_group']}"] = int(row["n"])
    return out


def build_weights(
    papers: list[dict], manifest: dict[str, dict], frame_counts: dict[str, int]
) -> dict[str, float]:
    """事后分层权重 (docs/spec/corpus.md): w_cell = N_frame_cell / n_sample_cell.

    n_sample_cell 用 manifest 行 (抽出的样本) 计数; 样本行缺 stratum_cell
    或 frame 表缺该 cell → 该篇无权重, 加权统计剔除并在报告注明.
    语料无 stratum_cell (corpus39/v2) → 返回空 dict → 调用方退化等权.
    有 layer 字段的 manifest (v3): 只有 layer=="core" 行入 n_cell/得权重——
    补强层是策展非随机样, 池化估计只用核心层 (docs/spec/corpus.md)."""
    has_layer = any("layer" in m for m in manifest.values())
    n_cell: dict[str, int] = {}
    for m in manifest.values():
        if has_layer and m.get("layer") != "core":
            continue
        cell = m.get("stratum_cell")
        if cell:
            n_cell[cell] = n_cell.get(cell, 0) + 1
    if not n_cell or not frame_counts:
        return {}
    weights: dict[str, float] = {}
    for p in papers:
        meta = p.get("meta") or {}
        if has_layer and meta.get("layer") != "core":
            continue  # 补强层不进加权池化
        cell = meta.get("stratum_cell")
        if cell and cell in frame_counts and n_cell.get(cell):
            weights[p["id"]] = frame_counts[cell] / n_cell[cell]
    return weights


def wilson_ci(k: int, n: int, z: float = 1.959964) -> tuple[float | None, float | None]:
    """Wilson score 区间 (Brown-Cai-DasGupta 2001); n=0 → (None, None)."""
    if n == 0:
        return None, None
    p = k / n
    den = 1 + z * z / n
    center = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, center - half), min(1.0, center + half)


def cluster_bootstrap(
    papers: list[dict], files: list[dict], n_boot: int = BOOTSTRAP_B
) -> dict[str, tuple[float, float] | None]:
    """月簇稳健 bootstrap (docs/spec/corpus.md): 按簇键 (cluster_id‖yymm‖pid) 有放回
    重抽样论文, 重算 pooled 比率取 2.5/97.5 分位. 无簇键时逐篇 iid (退化标注)."""
    if not papers:
        return {}
    clusters: dict[str, list[str]] = {}
    for p in papers:
        meta = p.get("meta") or {}
        key = meta.get("cluster_id") or meta.get("yymm") or p["id"]
        clusters.setdefault(str(key), []).append(p["id"])
    keys = sorted(clusters)
    rng = random.Random(BOOTSTRAP_SEED)

    # 每篇预聚合 (单遍): ok/meas/strict/chunks/leaked/reached/orphan
    sums_keys = (
        "files",
        "ok",
        "measured",
        "strict",
        "chunks",
        "leaked",
        "reached",
        "orphan",
    )
    zero = dict.fromkeys(sums_keys, 0)
    per_paper: dict[str, dict] = {p["id"]: dict(zero) for p in papers}
    for f in files:
        d = per_paper.get(f["paper_id"])
        if d is None:
            continue
        d["files"] += 1
        if f.get("ok"):
            d["ok"] += 1
        if f.get("ok") and "measure_error" not in f:
            d["measured"] += 1
            if f["identity"] == "strict":
                d["strict"] += 1
            d["chunks"] += f["leak"]["n_translatable"]
            d["leaked"] += f["leak"]["n_leaked"]
        if f["role"] in ("root", "input_reached"):
            d["reached"] += 1
        elif f["role"] == "orphan":
            d["orphan"] += 1

    def ratios(sel: list[str]) -> tuple[float, ...]:
        agg = {k: sum(per_paper[pid][k] for pid in sel) for k in sums_keys}
        return (
            agg["ok"] / agg["files"] if agg["files"] else math.nan,
            agg["strict"] / agg["measured"] if agg["measured"] else math.nan,
            agg["leaked"] / agg["chunks"] if agg["chunks"] else math.nan,
            (agg["reached"] / (agg["reached"] + agg["orphan"]))
            if agg["reached"] + agg["orphan"]
            else math.nan,
        )

    samples: list[tuple[float, ...]] = []
    for _ in range(n_boot):
        sel = [
            pid
            for k in (keys[rng.randrange(len(keys))] for _ in range(len(keys)))
            for pid in clusters[k]
        ]
        samples.append(ratios(sel))
    names = ("ok", "identity", "leak", "flatten_coverage")
    out: dict[str, tuple[float, float] | None] = {}
    for i, name in enumerate(names):
        vals = sorted(s[i] for s in samples if not math.isnan(s[i]))
        if not vals:
            out[name] = None
            continue
        lo = vals[max(0, math.floor(0.025 * len(vals)))]
        hi = vals[min(len(vals) - 1, math.ceil(0.975 * len(vals)) - 1)]
        out[name] = (lo, hi)
    return out


def weighted_rates(
    files: list[dict], weights: dict[str, float]
) -> dict[str, float | None]:
    """加权池化率 (事后分层): Σ w·x / Σ w·n, 文件/chunk 继承所属篇权重.

    无权重篇目剔除 (报告注明). 全部等权时等价 raw pooled."""
    wok = wfiles = wstrict = wmeas = wleak = wchunks = 0.0
    wreached = worph = 0.0
    for f in files:
        w = weights.get(f["paper_id"], 0.0)
        if not w:
            continue
        wfiles += w
        if f.get("ok"):
            wok += w
        # coverage 只看 flatten 拓扑角色, 与解析成败无关 (no_root 篇目除外)
        if f["role"] in ("root", "input_reached"):
            wreached += w
        elif f["role"] == "orphan":
            worph += w
        if "measure_error" in f or not f.get("ok"):
            continue
        wmeas += w
        if f["identity"] == "strict":
            wstrict += w
        wchunks += w * f["leak"]["n_translatable"]
        wleak += w * f["leak"]["n_leaked"]
    return {
        "ok": wok / wfiles if wfiles else None,
        "identity": wstrict / wmeas if wmeas else None,
        "leak": wleak / wchunks if wchunks else None,
        "coverage": wreached / (wreached + worph) if wreached + worph else None,
    }


def macro_rates(files: list[dict], papers: list[dict]) -> dict[str, float | None]:
    """宏平均 (olmOCR 式等权桶): 逐篇比率等权平均——每篇一票, 与其体量无关.

    逐篇 leak 率 = 该篇 leaked/translatable (0-chunk 篇剔除); 逐篇 coverage =
    reached/(reached+orphan) (rootless 篇无此指标, 剔除)."""
    ok_r, ident_r, leak_r, cov_r = [], [], [], []
    reach_orph: dict[str, list[int]] = {}
    for f in files:
        if f["role"] in ("root", "input_reached", "orphan"):
            ro = reach_orph.setdefault(f["paper_id"], [0, 0])
            ro[0 if f["role"] in ("root", "input_reached") else 1] += 1
    for p in papers:
        s = p["stats"]
        if s["files"]:
            ok_r.append(s["ok"] / s["files"])
        meas = s["files"] - s["error"] - s["measure_error"]
        if meas:
            ident_r.append(s["strict"] / meas)
        if s["chunks"]:
            leak_r.append(s["leaked_chunks"] / s["chunks"])
        ro = reach_orph.get(p["id"])
        if ro and ro[0] + ro[1]:
            cov_r.append(ro[0] / (ro[0] + ro[1]))
    return {
        "ok": statistics.fmean(ok_r) if ok_r else None,
        "identity": statistics.fmean(ident_r) if ident_r else None,
        "leak": statistics.fmean(leak_r) if leak_r else None,
        "coverage": statistics.fmean(cov_r) if cov_r else None,
    }


# ---------------------------------------------------------------- summary


def _pct(x: float | None, nd: int = 1) -> str:
    return f"{100 * x:.{nd}f}" if x is not None else "—"


def _ci_str(ci: tuple[float | None, float | None] | None, nd: int = 2) -> str:
    if not ci or ci[0] is None:
        return "—"
    return f"[{_pct(ci[0], nd)}, {_pct(ci[1], nd)}]"


def write_summary(
    out_md: Path,
    corpus: Path,
    files: list[dict],
    papers: list[dict],
    manifest: dict[str, dict],
    wall_s: float,
    weights: dict[str, float],
    boot: dict[str, tuple[float, float] | None],
    weighted_note: str,
    n_boot: int,
) -> None:
    lines = []
    tot = aggregate(files)
    n_reached = sum(1 for f in files if f["role"] in ("root", "input_reached"))
    n_orphan = sum(1 for f in files if f["role"] == "orphan")
    n_no_root = sum(1 for f in files if f["role"] == "no_root")
    cover = n_reached / (n_reached + n_orphan) if n_reached + n_orphan else None
    lines.append(f"# parsebench summary — {corpus.name}\n")
    lines.append(
        f"- papers: {len(papers)}   files (.tex): {tot['files']}   wall: {wall_s}s"
    )
    lines.append(
        f"- parse ok: **{tot['ok']}/{tot['files']}** "
        f"({_pct(tot['ok_rate'])}%)   errors: {tot['error']}   "
        f"measure_errors: {tot['measure_error']}"
    )
    lines.append(
        f"- identity: strict **{tot['strict']}** / normalized "
        f"{tot['normalized']} / diverged {tot['diverged']} "
        f"(strict-rate {_pct(tot['identity_rate'])}%)"
    )
    vs_src = {"strict": 0, "normalized": 0, "diverged": 0}
    for f in files:
        v = f.get("vtex_vs_src")
        if v in vs_src:
            vs_src[v] += 1
    if any(vs_src.values()):
        lines.append(
            f"- expand 足迹 (flat→vtex): strict {vs_src['strict']} / "
            f"normalized {vs_src['normalized']} / diverged {vs_src['diverged']}"
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
    if tot["warn_kinds"]:
        lines.append(f"- scan/validate warnings: {tot['warn_kinds']}")
    lines.append(
        f"- flatten coverage: {n_reached} reached / {n_orphan} orphan tex / "
        f"{n_no_root} rootless   (触及率 {_pct(cover)}%)\n"
    )

    # ---- docs/spec/benchmark.md B1 漏斗: fetched → .tex → rooted → ok → identity → leak → dead/orphan
    n_multi = sum(1 for p in papers if p["multi_doc"])
    n_rootless = sum(1 for p in papers if not p["roots"])
    lines.append("## funnel\n")
    lines.append("| stage | n |")
    lines.append("|---|---|")
    if manifest:
        statuses = [m.get("status") for m in manifest.values()]
        n_src_ok = (
            sum(1 for s in statuses if s == "ok")
            if any(s is not None for s in statuses)
            else len(manifest)
        )
        lines.append(f"| fetched (manifest rows) | {len(manifest)} |")
        lines.append(f"| source ok | {n_src_ok} |")
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
        f"{n_reached} / {n_orphan} / {n_no_root} |\n"
    )

    # ---- docs/spec/corpus.md 门槛
    wil_ok = wilson_ci(tot["ok"], tot["files"])
    n_meas = tot["files"] - tot["error"] - tot["measure_error"]
    wil_id = wilson_ci(tot["strict"], n_meas)
    wil_leak = wilson_ci(tot["leaked_chunks"], tot["chunks"])
    dead_total = (
        tot["residue_chunk_ph"] + tot["residue_protect_ph"] + tot["orphan_chunks"]
    )
    gates = [
        (
            "parse ok (file)",
            f"{_pct(tot['ok_rate'])}% CI {_ci_str(wil_ok)}",
            "100% & Wilson lb ≥99.5%",
            "PASS"
            if tot["ok_rate"] == 1.0 and (wil_ok[0] or 0) >= 0.995
            else "FAIL"
            if tot["ok_rate"] != 1.0
            else "PASS(low-n)",
        ),
        (
            "strict identity",
            f"{_pct(tot['identity_rate'], 2)}% CI {_ci_str(wil_id)}",
            "≥99.5%",
            "PASS" if (tot["identity_rate"] or 0) >= 0.995 else "FAIL",
        ),
        (
            "leak rate (chunk)",
            f"{_pct(tot['leak_rate'], 3)}% CI {_ci_str(wil_leak, 3)}",
            "≤0.15%",
            "PASS" if (tot["leak_rate"] or 0) <= 0.0015 else "FAIL",
        ),
        (
            "dead/orphan",
            (
                f"{dead_total} (chunk {tot['residue_chunk_ph']} "
                f"+ protect {tot['residue_protect_ph']} + orphan {tot['orphan_chunks']})"
            ),
            "=0",
            "PASS" if dead_total == 0 else "FAIL",
        ),
        (
            "flatten coverage",
            f"{_pct(cover)}% ({n_reached}/{n_reached + n_orphan})",
            "≥99% †",
            "PASS" if (cover or 0) >= 0.99 else "BELOW",
        ),
    ]
    lines.append("## gates (docs/spec/corpus.md)\n")
    lines.append("| gate | value | 门槛 | verdict |")
    lines.append("|---|---|---|---|")
    lines.extend(f"| {g} | {v} | {t} | {d} |" for g, v, t, d in gates)
    lines.append(
        "\n† coverage 口径勘误 (docs/spec/corpus.md 表下): orphan 大头是 e-print 内未被主文件 "
        "\\input 触及的随附 tex (preamble/poster 件), 属语料真实属性而非实现漏跟; "
        "v3 实测 ~93%.\n"
    )

    # ---- docs/spec/corpus.md 三口径 + CI
    wr = weighted_rates(files, weights)
    mr = macro_rates(files, papers)
    lines.append("## 统计口径 (docs/spec/corpus.md)\n")
    lines.append(
        f"- 权重: {weighted_note}; bootstrap: 簇键 cluster_id‖yymm‖pid, "
        f"B={n_boot}, seed={BOOTSTRAP_SEED} (无簇键即逐篇 iid)"
    )
    lines.append(
        "| 指标 | pooled | 加权池化 | 宏平均(逐篇) | Wilson 95% | 簇 boot 95% |"
    )
    lines.append("|---|---|---|---|---|---|")
    boot_ok = boot.get("ok")
    boot_id = boot.get("identity")
    boot_lk = boot.get("leak")
    lines.append(
        f"| parse ok (file) | {_pct(tot['ok_rate'], 3)}% "
        f"({tot['ok']}/{tot['files']}) | {_pct(wr['ok'], 3)}% "
        f"| {_pct(mr['ok'], 3)}% | {_ci_str(wil_ok, 3)} | {_ci_str(boot_ok, 3)} |"
    )
    lines.append(
        f"| strict identity | {_pct(tot['identity_rate'], 3)}% "
        f"({tot['strict']}/{n_meas}) | {_pct(wr['identity'], 3)}% "
        f"| {_pct(mr['identity'], 3)}% | {_ci_str(wil_id, 3)} | {_ci_str(boot_id, 3)} |"
    )
    lines.append(
        f"| leak (chunk) | {_pct(tot['leak_rate'], 3)}% "
        f"({tot['leaked_chunks']}/{tot['chunks']}) | {_pct(wr['leak'], 3)}% "
        f"| {_pct(mr['leak'], 3)}% | {_ci_str(wil_leak, 3)} | {_ci_str(boot_lk, 3)} |"
    )
    lines.append(
        f"| flatten coverage | {_pct(cover, 2)}% "
        f"({n_reached}/{n_reached + n_orphan}) | {_pct(wr['coverage'], 2)}% "
        f"| {_pct(mr['coverage'], 2)}% | — "
        f"| {_ci_str(boot.get('flatten_coverage'), 2)} |\n"
    )

    errs = [f for f in files if not f.get("ok")]
    merrs = [f for f in files if f.get("measure_error")]
    if errs or merrs:
        lines.append("## parse errors\n")
        lines.append("| file | error | wall_ms |")
        lines.append("|---|---|---|")
        lines.extend(
            f"| {f['file']} | {f.get('error', '')} | {f['wall_ms']} |" for f in errs
        )
        lines.extend(
            f"| {f['file']} | measure_error: {f.get('measure_error', '')} | "
            f"{f['wall_ms']} |"
            for f in merrs
        )
        lines.append("")

    # ---- 泄漏逐条归因表 (docs/spec/benchmark.md B1-4: 人工复核素材 → mechanisms.jsonl)
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
        if len(groups) <= 1 and "—" in groups:
            return
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
    ap = argparse.ArgumentParser(
        description="parsebench v2 — texlate.latex corpus benchmark"
    )
    ap.add_argument(
        "--corpus",
        required=True,
        type=Path,
        help="语料目录 (bench/corpus|corpus_daily; 裸名按 bench/ 下解析)",
    )
    ap.add_argument(
        "--manifest",
        type=Path,
        default=None,
        help="默认 <corpus>/manifest.jsonl (存在即用)",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=None,
        help="产出目录 (默认 bench/results/parsebench-{tag}-{date})",
    )
    ap.add_argument("--tag", default=None, help="产出目录名中段 (默认 corpus.name)")
    ap.add_argument("--date", default=str(datetime.now(UTC).date()))
    ap.add_argument(
        "--frame-counts",
        type=Path,
        default=DEFAULT_FRAME_COUNTS,
        help="frame 宇宙 cell 计数 csv (year_band,cat_group,n); 缺则加权退化等权",
    )
    ap.add_argument("--bootstrap", type=int, default=BOOTSTRAP_B)
    ap.add_argument("--timeout", type=int, default=TIMEOUT_S)
    ap.add_argument("--only", default=None, help="substring filter on paper id")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--rerun",
        action="store_true",
        help="无视 files.jsonl 续跑行全部重测（默认行在=done 跳过）",
    )
    args = ap.parse_args()

    corpus = args.corpus
    if not corpus.exists() and (ROOT / "bench" / str(corpus)).exists():
        corpus = ROOT / "bench" / str(corpus)
    corpus = corpus.resolve()
    tag = args.tag or corpus.name
    out = args.out or ROOT / "bench" / "results" / f"parsebench-{tag}-{args.date}"
    if not out.is_absolute():
        out = Path.cwd() / out
    out.mkdir(parents=True, exist_ok=True)
    manifest_path = args.manifest or corpus / "manifest.jsonl"
    manifest = load_manifest(manifest_path)
    frame_counts = load_frame_counts(args.frame_counts)

    t0 = time.perf_counter()
    tex_files = sorted(rglob_tex(corpus))
    papers, groupers = discover_papers(corpus)
    single = next(iter(papers.values())) if len(papers) == 1 else None
    if single is not None and single != corpus:
        single = None  # 仅当 corpus 自身即论文时启用
    print(f"corpus {corpus}: {len(tex_files)} .tex in {len(papers)} papers")
    if manifest:
        print(f"  manifest: {len(manifest)} rows ({manifest_path.name})")
    print(f"  frame counts: {len(frame_counts)} cells ({args.frame_counts})")

    # ---- pass 1: 论文级 (主文件定位/路由标签/flatten 覆盖)
    prec_map: dict[str, dict] = {}
    for pid, pdir in sorted(papers.items()):
        if args.only and args.only not in pid:
            continue
        if args.limit is not None and len(prec_map) >= args.limit:
            break
        prec = analyze_paper(pid, pdir, corpus)
        # corpus_v2/v3 布局: 论文目录是 {id}/extracted/ 或 {archive}/{id}/,
        # manifest id 是 {id} / {archive}/{id}
        mkey = pid.removesuffix("/extracted")
        if mkey in manifest:
            prec["meta"] = manifest[mkey]
        prec_map[pid] = prec
    n_multi = sum(1 for p in prec_map.values() if p["multi_doc"])
    n_rootless = sum(1 for p in prec_map.values() if not p["roots"])
    print(
        f"  roots: {n_multi} multi_doc, {n_rootless} rootless"
        + (
            f"  [filtered {len(prec_map)}/{len(papers)}]"
            if args.only or args.limit
            else ""
        )
    )
    if manifest:
        n_meta = sum(1 for p in prec_map.values() if "meta" in p)
        print(f"  manifest matched: {n_meta}/{len(prec_map)} papers")
        # manifest 即抽样框：只评 manifest 列出的论文（corpus 核心/补强
        # 两层同目录共存，层间切换靠 --manifest 指向对应 jsonl）
        keep = {pid for pid in prec_map if pid.removesuffix("/extracted") in manifest}
        n_drop = len(prec_map) - len(keep)
        if n_drop:
            print(f"  manifest frame: dropped {n_drop} unlisted paper dirs")
            prec_map = {pid: prec_map[pid] for pid in keep}

    # ---- pass 2: 逐文件评测 —— files.jsonl append 真账（行在=done），
    # 同 out 目录重跑自动续跑；--rerun 强制重测。pass 1 (analyze_paper)
    # 仍全量重建——_roots/_covered 私有集决定逐文件 role，不落盘。
    sel = set(prec_map)
    f_jsonl = out / "files.jsonl"
    file_entries: list[dict] = []
    done_files: set[str] = set()
    if f_jsonl.exists() and not args.rerun:
        n_prior_all = 0
        for e in benchlib.iter_jsonl(f_jsonl):
            n_prior_all += 1
            # 选样缩圈（--only/--limit/manifest frame）或旧代 schema
            # （v1 臂时代行无 vtex_len 键）的存量行不算 done——重测保口径一致
            if e.get("paper_id") in sel and "vtex_len" in e:
                file_entries.append(e)
                done_files.add(e["file"])
        if n_prior_all:
            print(
                f"  resume: {len(file_entries)}/{n_prior_all} prior rows kept",
                flush=True,
            )

    with f_jsonl.open("w", encoding="utf-8") as fh:
        for e in file_entries:  # 续跑行重写回——顺带压实截尾坏行/口径外行
            benchlib.write_jsonl(fh, e)
        n_new = 0
        for f in tex_files:
            rel = f.relative_to(corpus)
            pid = paper_id_of(rel, groupers, single)
            if pid not in sel:
                continue
            rel_s = str(rel)
            if rel_s in done_files:
                continue
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
                f,
                rel_s,
                pid,
                role,
                apath in (prec["_non_utf8"] if prec else set()),
                args.timeout,
            )
            file_entries.append(e)
            benchlib.write_jsonl(fh, e)  # _lens 随行落盘：续跑聚合保真
            n_new += 1
            if n_new % 25 == 0:
                print(f"  +{n_new} files...", flush=True)
        if n_new:
            print(f"  pass2: +{n_new} new, {len(file_entries)} total", flush=True)

    # ---- 论文级聚合 stats
    for prec in prec_map.values():
        pfiles = [e for e in file_entries if e["paper_id"] == prec["id"]]
        prec["stats"] = aggregate(pfiles)
        meta = prec.get("meta") or {}
        for k in ("stratum_cell", "cluster_id", "layer", "yymm", "year_band"):
            if k in meta:
                prec[k] = meta[k]
        for k in ("_covered", "_tex_files", "_roots", "_non_utf8"):
            prec.pop(k, None)

    wall = round(time.perf_counter() - t0, 1)
    paper_list = sorted(prec_map.values(), key=lambda p: p["id"])

    # ---- 统计口径: 权重 → 加权池化; bootstrap 簇重抽
    weights = build_weights(paper_list, manifest, frame_counts)
    n_unweighted = sum(1 for p in paper_list if p["id"] not in weights)
    if weights:
        weighted_note = (
            f"post-strat w=N_cell/n_cell (核心层), {len(weights)}/{len(paper_list)} 篇有权"
            + (
                f", {n_unweighted} 篇无 stratum_cell/非核心层 → 剔除加权列"
                if n_unweighted
                else ""
            )
        )
    else:
        # 无 stratum_cell/frame 表 → 等权退化 (weighted 列 = raw pooled)
        weights = {p["id"]: 1.0 for p in paper_list}
        weighted_note = "等权退化 (语料无 stratum_cell 或 frame 计数缺失) = raw pooled"
    boot = (
        cluster_bootstrap(paper_list, file_entries, n_boot=args.bootstrap)
        if args.bootstrap
        else {}
    )
    for p in paper_list:
        p["weight"] = round(weights.get(p["id"], 0.0), 4) or None

    # ---- 落盘 (docs/spec/benchmark.md 契约三件套；files.jsonl 已随 pass2 append 落盘)
    p_json = out / "papers.json"
    s_md = out / "summary.md"

    p_json.write_text(
        json.dumps(
            {
                "corpus": str(corpus),
                "wall_s": wall,
                "weighted_note": weighted_note,
                "papers": paper_list,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    write_summary(
        s_md,
        corpus,
        file_entries,
        paper_list,
        manifest,
        wall,
        weights,
        boot,
        weighted_note,
        args.bootstrap,
    )

    tot = aggregate(file_entries)
    print(
        f"done {wall}s — ok {tot['ok']}/{tot['files']}, "
        f"strict {tot['strict']}, leak {tot['leak_rate']} "
        f"({tot['leaked_chunks']}/{tot['chunks']})"
    )
    print(f"wrote {f_jsonl}\n      {p_json}\n      {s_md}")


if __name__ == "__main__":
    main()
