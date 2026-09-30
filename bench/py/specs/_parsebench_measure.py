r"""specs._parsebench_measure — 逐文件测量叶 (parsebench 拆分叶).

SIGALRM 超时壳 ``parse_one`` (**仅 worker 主线程可跑**——thread executor
下 ``signal.signal`` 抛 ValueError) + 判定件: 六族泄漏 scan_chunks /
孤儿 chunk / identity 三档 classify_recon / fake-translation splice
rebuild_metrics / bug1 ph_tail 探针 / 单行 ``file_metrics`` 全字段。

measure_error 纪律原样：判定层异常是行级 flag 不判 parse fail。
"""

from __future__ import annotations

import difflib
import math
import os
import re
import signal
import statistics
import time
from typing import TYPE_CHECKING

from specs import _bootstrap

_bootstrap.ensure()

from specs._leak import LEAK_PATTERNS
from texlate.latex import (
    flatten_inputs,
    parse_file,
    reconstruct,
    validate_result,
)
from texlate.textutil import decode_tex

if TYPE_CHECKING:
    from pathlib import Path


class ParseTimeout(Exception):
    """SIGALRM 触发的解析超时——只在 worker 主线程合法（thread executor
    下 ``signal.signal`` 本身即 ValueError，这就是 subprocess 存在的理由）。"""


def _alarm(signum, frame):
    raise ParseTimeout


def percentile(sorted_vals: list[int], q: float) -> int | None:
    """最近秩分位：idx=ceil(q*n)-1."""
    if not sorted_vals:
        return None
    return sorted_vals[max(0, math.ceil(q * len(sorted_vals)) - 1)]


PH_TOKEN_RX = re.compile(r"\[\[[A-Z_]+_\d+\]\]")


def ph_tail_risk(res) -> int:
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


# ---------------------------------------------------------------- 判定 (docs/spec/corpus.md 口径，产品 API 版)


def parse_one(path: Path, timeout_s: int) -> dict:
    """api.parse_file（产品路径）+ SIGALRM 超时——**仅 worker 主线程可跑**。

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


def scan_chunks(res) -> dict:
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


def orphan_chunk_ids(res) -> int:
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
    """占位译文：保留全部内嵌占位符 (契约面), 正文替换为全角标记."""
    keep = re.findall(r"\[\[[A-Z_]+_\d+\]\]", chunk.content)
    return f"【假译文{idx}】" + "".join(keep)


def rebuild_metrics(res) -> dict:
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


# ---------------------------------------------------------------- 逐文件评测


def file_metrics(
    path: Path,
    rel: str,
    paper: str,
    role: str,
    non_utf8: bool,
    timeout_s: int,
    *,
    cached: dict | None = None,
) -> dict:
    """单文件评测全字段——``cached`` 复用拓扑段的 root 解析结果（同一次
    parse 不跑两遍；wall_ms 即该次计时）。"""
    entry = {
        "file": rel,
        "paper_id": paper,
        "role": role,  # root / input_reached / orphan / no_root
        "size": path.stat().st_size,
        "non_utf8": non_utf8,
    }
    r = cached if cached is not None else parse_one(path, timeout_s)
    entry["ok"] = r["ok"]
    entry["wall_ms"] = r["ms"]
    if not r["ok"]:
        entry["error"] = r["error"]
        entry["vtex_len"] = None  # 旧 schema 戳字段随行保留（行级口径锚）
        return entry

    res = r["res"]
    entry["n_chunks"] = len(res.chunks)
    entry["n_placeholders"] = len(res.ph_map)
    entry["vtex_len"] = len(res.vtex)

    try:
        lens = sorted(len(c.content) for c in res.chunks)
        entry["chunk_chars_median"] = statistics.median(lens) if lens else None
        entry["chunk_chars_p90"] = percentile(lens, 0.9)
        entry["chunk_chars_max"] = lens[-1] if lens else None
        entry["_lens"] = lens  # 聚合用，随行落盘（derive 重组分位保真）

        # scan/validate warnings 分类计数 (泄漏类 bug 第一手线索)
        wk: dict[str, int] = {}
        for w in res.warnings:
            wk[w.kind] = wk.get(w.kind, 0) + 1
        for w in validate_result(res):
            wk[w.kind] = wk.get(w.kind, 0) + 1
        entry["warn_kinds"] = wk
        # res.inputs 混合语义：resolved 记 realpath, 漏网记原始名——isabs 过滤
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
        # 展开足迹：vtex vs 展平源 (strict = 展开机对本文件无净改动)
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
