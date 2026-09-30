"""specs._layoutqc.logcheck — 编译日志信号叶 (_layoutqc 拆分叶).

overfull 去重计数 + 峰值 + 分层 (titlepage/\\output 例程)、Float-Fit
typeout、浮体丢失/超高、未解引用键集——日志正则通道全检。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from specs._layoutqc.thresh import (
    _FLOAT_FIT_RX,
    _FLOAT_LOST_RX,
    _FLOAT_OVERSIZE_RX,
    _OUTPUT_ACTIVE_RX,
    _OVERFULL_LINE_RX,
    _OVERFULL_RX,
    _UNDEF_KEY_RX,
    FLOAT_OVERSIZE_WARN_PT,
    OVERFULL_COUNT,
    OVERFULL_COUNT_MIN_PT,
    OVERFULL_MAX_PT,
    OVERFULL_VBOX_FLOOR_PT,
)

if TYPE_CHECKING:
    from pathlib import Path


def _frontmatter_lines(tex_files: list[Path]) -> set[int]:
    """各 splice tex 的 ``\\maketitle`` 行号与 titlepage 环境行区间的
    并集（1-based；对撞文件只共享行号不共享文件名——单发大 overfull
    降权路径只覆盖能反查到标题语境的格）。"""
    out: set[int] = set()
    for p in tex_files:
        try:
            tl = p.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        depth = 0
        for i, ln in enumerate(tl, 1):
            if re.search(r"\\begin\s*\{titlepage\}", ln):
                depth += 1
            if depth:
                out.add(i)
            if re.search(r"\\end\s*\{titlepage\}", ln):
                depth = max(0, depth - 1)
            if re.search(r"\\maketitle\b", ln):
                out.add(i)
    return out


def _logscan(
    log_text: str, title_lines: set[int] | None = None
) -> tuple[list[dict], dict]:
    """编译日志信号：overfull 去重计数 + 峰值、Float-Fit typeout、浮体
    丢失（浮体臂）、未解引用键集（喂 xlat_broken_refs 证据面）。

    overfull 判定三层先收口：(1) ``(kind, round(pt,1))`` 去重——逐页
    同值 running-head/vbox 条目塌缩成单签；(2) vbox <2pt 亚像素带整丢；
    (3) 计数臂 ``distinct > OVERFULL_COUNT`` 还须峰值 ≥20pt，峰值臂
    >50pt 不变。``title_lines`` 给出 splice tex 的 \\maketitle/
    titlepage 行号集——全部驱动级（≥20pt）溢出都落在标题语境时降为
    ``layout:overfull_titlepage``（INFO；cms-tdr banner 测量盒实证）。
    第四层：``while \\output is active`` 例程内条目（页眉页脚家具/
    超高 vbox）剔出正文溢出计数，单列 ``layout:overfull_output``
    INFO 记账（overfull 簇 0928 accept_as_is 裁定）。"""
    findings: list[dict] = []
    seen: set[tuple[str, float]] = set()
    ov: list[tuple[str, float, int | None, bool]] = []
    for m in _OVERFULL_RX.finditer(log_text):
        kind, pt = m.group(1), float(m.group(2))
        if kind == "v" and pt < OVERFULL_VBOX_FLOOR_PT:
            continue
        key = (kind, round(pt, 1))
        if key in seen:
            continue
        seen.add(key)
        ctx = log_text[m.end() : m.end() + 160]
        # \\output 例程判只认本条语境段——下一条 Overfull 起头截断，
        # 不然相邻条目的 "while \output is active" 会跨界误染。
        seg = ctx.split("Overfull", 1)[0]
        out_active = bool(_OUTPUT_ACTIVE_RX.search(seg))
        lm = _OVERFULL_LINE_RX.search(ctx)
        ov.append((kind, pt, int(lm.group(1)) if lm else None, out_active))
    fit = len(_FLOAT_FIT_RX.findall(log_text))
    lost = len(_FLOAT_LOST_RX.findall(log_text))
    over_hits = _FLOAT_OVERSIZE_RX.findall(log_text)
    over_pts = [float(a) for a, b in over_hits if a]
    over_unknown = len(over_hits) - len(over_pts)
    undef_keys = sorted(set(_UNDEF_KEY_RX.findall(log_text)))
    ov_body = [o for o in ov if not o[3]]
    ov_out = [o for o in ov if o[3]]
    body_max = max((p for _, p, _, _ in ov_body), default=0.0)
    metrics = {
        "overfull_n": len(ov),
        "overfull_max_pt": max((p for _, p, _, _ in ov), default=0.0),
        "overfull_vbox_n": sum(1 for k, _, _, _ in ov if k == "v"),
        "overfull_output_n": len(ov_out),
        "float_fit_typeout": fit,
        "float_lost_warn": lost,
        "float_oversize_n": len(over_hits),
        "float_oversize_max_pt": max(over_pts, default=0.0),
        "undef_ref_keys": undef_keys,
    }
    if (len(ov_body) > OVERFULL_COUNT and body_max >= OVERFULL_COUNT_MIN_PT) or (
        body_max > OVERFULL_MAX_PT
    ):
        drivers = [o for o in ov_body if o[1] >= OVERFULL_COUNT_MIN_PT]
        title_ctx = bool(
            title_lines
            and drivers
            and all(o[2] is not None and o[2] in title_lines for o in drivers)
        )
        findings.append(
            {
                "sig": (
                    "layout:overfull_titlepage" if title_ctx else "layout:overfull"
                ),
                "n": len(ov_body),
                "max_pt": body_max,
                "vbox_n": sum(1 for k, _, _, _ in ov_body if k == "v"),
            }
        )
    if ov_out:
        # \\output 例程溢出（页眉页脚家具/超高 vbox）——源稿本就溢出或
        # 模板属性，accept_as_is：发 INFO sig 记账不进 dirty（overfull
        # 簇 0928 裁定；headfoot 7 格 + 超高 vbox 6 格实证）。同格正文域
        # 溢出仍走 layout:overfull（1306.0005 figure 段实证分层）。
        findings.append(
            {
                "sig": "layout:overfull_output",
                "n": len(ov_out),
                "max_pt": max(p for _, p, _, _ in ov_out),
                "vbox_n": sum(1 for k, _, _, _ in ov_out if k == "v"),
            }
        )
    if fit:
        findings.append({"sig": "layout:float_fit", "n": fit})
    if over_hits:
        findings.append(
            {
                "sig": (
                    "layout:float_oversize_big"
                    if over_unknown
                    or metrics["float_oversize_max_pt"] >= FLOAT_OVERSIZE_WARN_PT
                    else "layout:float_oversize"
                ),
                "n": len(over_hits),
                "max_pt": metrics["float_oversize_max_pt"],
            }
        )
    if lost:
        findings.append({"sig": "layout:float_lost", "n": lost})
    return findings, metrics
