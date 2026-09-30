"""specs._validbench_cases — 语料底材叶 (validbench 拆分叶).

root pick → 30s 子进程隔离解析 (SIGALRM 在 worker 线程禁用，内核 process
executor 不可 pickle —— G8) → chunk 窗过滤 → per-paper seed shuffle →
ph/raw × clean+c01–c10 case 生成 (``_gen_paper_cases``)。
"""

from __future__ import annotations

import json
import random
import subprocess
import sys
import zlib
from collections import Counter
from types import SimpleNamespace
from typing import TYPE_CHECKING

from specs import _bootstrap

_bootstrap.ensure()

from specs._validbench_corrupt import CORRUPTIONS
from specs._validbench_pseudo import pseudo_translate, rehydrate

if TYPE_CHECKING:
    from pathlib import Path

PARSE_TIMEOUT_S = 30


def _pick_root(src: Path) -> Path | None:
    """find_main_tex 定主档 (产品同款启发式); 无候选退最大 .tex."""
    from texlate.compile.mainfile import find_main_tex

    m = find_main_tex(src)
    if m is not None:
        return m
    texs = sorted(src.rglob("*.tex"))
    return max(texs, key=lambda f: f.stat().st_size) if texs else None


class _ParseFail(Exception):
    """子进程解析失败（超时/崩溃/输出缺）——旧 _ParseTimeout+ 异常同桶."""


_CHILD_SRC = r"""
import json, sys
from pathlib import Path
from texlate.latex import parse_file
res = parse_file(Path(sys.argv[1]))
out = {"chunks": [{"id": c.id, "content": c.content} for c in res.chunks],
       "ph_map": res.ph_map}
sys.stdout.write(json.dumps(out, ensure_ascii=False))
"""


def _parse_subprocess(root: Path, timeout: int) -> tuple[list, dict]:
    """30s 隔离解析——worker 线程禁 SIGALRM 且内核 process executor 是
    不可 pickle 闭包 (G8)，超时壳只能由 subprocess 承载。"""
    try:
        res = subprocess.run(
            [sys.executable, "-c", _CHILD_SRC, str(root)],
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as e:
        msg = f"Timeout(>{timeout}s)"
        raise _ParseFail(msg) from e
    if res.returncode != 0:
        tail = res.stderr.decode("utf-8", "replace")[-200:]
        msg = f"rc={res.returncode}: {tail}"
        raise _ParseFail(msg)
    try:
        d = json.loads(res.stdout)
    except ValueError as e:
        msg = f"bad child stdout: {e}"
        raise _ParseFail(msg) from e
    chunks = [SimpleNamespace(id=c["id"], content=c["content"]) for c in d["chunks"]]
    return chunks, d["ph_map"]


def _gen_paper_cases(
    pid: str,
    src: Path,
    *,
    max_per_paper: int,
    min_len: int,
    max_len: int,
    seed: int,
) -> tuple[list[dict], dict]:
    """单篇 case 生成：窗过滤 → per-paper rng shuffle → ph/raw × clean+c10。

    返回 (cases, stats)。stats 带 attempted/none_skips/raw_skipped ——
    「应产 case 集」与「实产」双计数 (None-able 算子的分母守恒口径)。
    """
    root = _pick_root(src)
    if root is None:
        return [], {"root": None}
    chunks_all, ph_map = _parse_subprocess(root, PARSE_TIMEOUT_S)
    windowed = [c for c in chunks_all if min_len <= len(c.content) <= max_len]
    # per-paper 播种：cell 结果不随同跑 paper 集漂移（旧全局 rng 语义见 docstring）
    prng = random.Random(f"{seed}:{pid}")
    prng.shuffle(windowed)
    picked = windowed[:max_per_paper]
    cases: list[dict] = []
    none_skips: Counter = Counter()
    n_pairs = n_raw_skip = 0
    for c in picked:
        for level, csrc in (
            ("ph", c.content),
            ("raw", rehydrate(c.content, ph_map)),
        ):
            if level == "raw" and csrc == c.content:
                n_raw_skip += 1
                continue  # 无占位符 -> 与 ph 层重复（守恒键 raw_skipped）
            zh = pseudo_translate(csrc)
            cid = f"{pid}/c{c.id}/{level}"
            cases.append(
                {
                    "id": cid + "/clean",
                    "paper": pid,
                    "chunk": c.id,
                    "level": level,
                    "kind": "clean",
                    "src": csrc,
                    "zh": zh,
                }
            )
            n_pairs += 1
            for kind, fn in CORRUPTIONS:
                crng = random.Random(zlib.crc32((cid + kind).encode()))
                bad = fn(zh, crng)
                if bad is None:
                    none_skips[kind] += 1
                    continue
                cases.append(
                    {
                        "id": f"{cid}/{kind}",
                        "paper": pid,
                        "chunk": c.id,
                        "level": level,
                        "kind": kind,
                        "src": csrc,
                        "zh": bad,
                    }
                )
    stats = {
        "root": root.name,
        "chunks": len(chunks_all),
        "windowed": len(windowed),
        "picked": len(picked),
        "pairs": n_pairs,
        "raw_skipped": n_raw_skip,
        "none_skips": dict(none_skips),
        # 应产 = 实产 + none 剔除（分母对拍键）
        "n_attempted": len(cases) + sum(none_skips.values()),
    }
    return cases, stats
