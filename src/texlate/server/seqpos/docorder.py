r"""seqpos.docorder — chunk seq → 文档序 rank (seqpos 子包叶)。

dual.json 的 chunk 序是 ``src_file`` 字母序——abstract/conclusions/
experiments/introduction 的字典序 ≠ PDF 阅读序，pass-A 光标与
pass-B ``s < seq`` 夹逼全建立在线性假设上，乱序即级联塌方（实测
2/85 覆盖）。这里从 ``base/``（缺则 ``zh/``）源码树重建真序：
``\\documentclass`` 根起 DFS 展平 ``\\input/\\include``，文件序 ×
文件内 seq 序合成全局 rank。无根 → 文件按 min-seq 兜底排。
"""

from __future__ import annotations

import posixpath
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any

_INPUT_RX = re.compile(r"\\(?:input|include|subfile)\s*\{([^}]+)\}")


def _read_tex(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _dfs_flat(texs: dict[str, Path], root: str) -> list[str]:
    r"""``\documentclass`` 根起 DFS 展平 ``\input/\include/\subfile`` → 文件阅读序。"""
    seen: set[str] = set()
    flat: list[str] = []

    def resolve(tgt: str, base: str) -> str | None:
        # \input{sec} 无后缀；目标对根相对，少数对含入文件目录相对
        tgt = tgt.strip().replace("\\", "/")
        base_dir = posixpath.dirname(base)
        for t in (tgt, f"{tgt}.tex"):
            for c_ in (t, posixpath.normpath(f"{base_dir}/{t}")):
                if c_ in texs:
                    return c_
        return None

    def dfs(rel: str) -> None:
        if rel in seen:
            return
        seen.add(rel)
        flat.append(rel)
        for m in _INPUT_RX.finditer(_read_tex(texs[rel])):
            r = resolve(m.group(1), rel)
            if r is not None:
                dfs(r)

    dfs(root)
    return flat


def _doc_order(task_dir: Path, chunks: list[dict[str, Any]]) -> dict[int, int]:
    r"""Chunk seq → 文档序 rank。

    dual.json 的 chunk 序是 ``src_file`` 字母序——abstract/conclusions/
    experiments/introduction 的字典序 ≠ PDF 阅读序，pass-A 光标与
    pass-B ``s < seq`` 夹逼全建立在线性假设上，乱序即级联塌方（实测
    2/85 覆盖）。这里从 ``base/``（缺则 ``zh/``）源码树重建真序：
    ``\documentclass`` 根起 DFS 展平 ``\input/\include``，文件序 ×
    文件内 seq 序合成全局 rank。无根 → 文件按 min-seq 兜底排。
    """
    by_file: dict[str, list[int]] = {}
    for c in chunks:
        seq, sf = c.get("seq"), c.get("src_file")
        if isinstance(seq, int) and isinstance(sf, str):
            by_file.setdefault(sf.replace("\\", "/"), []).append(seq)
    if not by_file:
        return {}
    for seqs in by_file.values():
        seqs.sort()

    flat: list[str] = []
    for root_dir in (task_dir / "base", task_dir / "zh"):
        if not root_dir.is_dir():
            continue
        texs = {
            p.relative_to(root_dir).as_posix(): p
            for p in root_dir.rglob("*")
            if p.suffix.lower() == ".tex"
        }
        doc_root = next(
            (rel for rel, p in texs.items() if "\\documentclass" in _read_tex(p)),
            None,
        )
        if doc_root is not None:
            flat = _dfs_flat(texs, doc_root)
            break

    # 未入 DFS 链的文件（游离 \input 链外/无根兜底）按 min-seq 追加尾部
    rest = sorted(
        (sf for sf in by_file if sf not in flat), key=lambda sf: by_file[sf][0]
    )
    rank_of = {rel: i for i, rel in enumerate(flat)}
    rank_of.update({sf: len(flat) + i for i, sf in enumerate(rest)})
    big = 1 << 20
    order: dict[int, int] = {}
    for sf, seqs in by_file.items():
        r = rank_of.get(sf, len(flat) + len(rest))
        for j, s in enumerate(seqs):
            order[s] = r * big + j
    return order
