"""ops.status_panel html 小件叶 —— chip/hbar/stacked/badge/table/minibar
片段件（status_panel.py 拆分叶）。

门面回引名单见 ``ops.status_panel._LEAF_EXPORTS``。
"""

from __future__ import annotations

from ops._status_panel_util import esc


def chip(label: str, value: str, sub: str = "", cls: str = "") -> str:
    return (
        f"<div class='chip {cls}'><div class='k'>{esc(label)}</div>"
        f"<div class='v'>{esc(value)}</div>"
        f"<div class='s'>{esc(sub)}</div></div>"
    )


def hbar(label: str, n: float, maxn: float, color: str, extra: str = "") -> str:
    pct = n / maxn * 100 if maxn else 0
    return (
        f"<div class='hrow'><div class='hl'>{esc(label)}</div>"
        f"<div class='hb'><div class='hf' style='width:{pct:.1f}%;"
        f"background:{color}'></div></div>"
        f"<div class='hn'>{n:g}{esc(extra)}</div></div>"
    )


def stacked(parts: list[tuple[str, int, str]], total: int) -> str:
    segs, legend = [], []
    for label, n, color in parts:
        if not n or not total:
            continue
        w = n / total * 100
        segs.append(
            f"<div class='seg' style='width:{w:.2f}%;background:{color}' "
            f"title='{esc(label)} {n}'></div>"
        )
        legend.append(
            f"<span class='lg'><i style='background:{color}'></i>"
            f"{esc(label)} {n}</span>"
        )
    return (
        "<div class='stack'>" + "".join(segs) + "</div>"
        "<div class='legend'>" + "".join(legend) + "</div>"
    )


def badge(text: str, color: str) -> str:
    return (
        f"<span class='bdg' style='background:{color}1a;color:{color};"
        f"border-color:{color}55'>{esc(text)}</span>"
    )


def table(headers: list[str], rows: list[list[str]]) -> str:
    th = "".join(f"<th>{esc(h)}</th>" for h in headers)
    trs = "".join(
        "<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows
    )
    return f"<table><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>"


def minibar(done: float, total: float) -> str:
    pct = min(done / total * 100, 100) if total else 0
    return (
        f"<div class='mb'><div class='mf' style='width:{pct:.0f}%'></div></div>"
        f"<span class='mbn'>{done:g}/{total:g}</span>"
    )
