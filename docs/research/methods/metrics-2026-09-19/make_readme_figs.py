#!/usr/bin/env python3
"""README figures — regenerate with: uv run --with matplotlib python make_readme_figs.py

All figure data is inlined below (self-contained); writes PNGs to <repo>/shots/.
Style: dataviz-method marks on the diagram-design token system (paper/ink/muted/
accent/link) so all README figures share one visual identity. Chinese labels
(Noto Sans CJK SC), 200 dpi.

bench-pipeline.png is NOT generated here — its source of truth is the
diagram-design HTML (bench-pipeline.html, exported via playwright).
"""

import datetime as dt
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import PathPatch, Rectangle
from matplotlib.path import Path

HERE = pathlib.Path(__file__).resolve().parent
#: repo root = nearest ancestor carrying pyproject.toml. 2026-09-20 docs
#: migration moved this script one level deeper and silently broke a
#: hardcoded parents[N] — walk up instead of counting.
REPO = next(p for p in HERE.parents if (p / "pyproject.toml").is_file())
OUT = REPO / "shots"
OUT.mkdir(exist_ok=True)

for _f in ("LXGWWenKai-Regular.ttf", "LXGWWenKai-Medium.ttf",
           "LXGWWenKai-Light.ttf"):
    font_manager.fontManager.addfont(f"/usr/share/fonts/TTF/{_f}")

SANS = "LXGW WenKai"
MONO = "JetBrainsMono NF"
SERIF = "Noto Serif CJK SC"

# ---- web brand token system (web/src/styles/base.css) ----
PAPER = "#f5f1e8"     # --paper
INK = "#211b12"       # --ink
MUTED = "#6e6454"     # --ink-2
SOFT = "#9a8f7c"      # --ink-3
ACCENT = "#b23a1f"    # --cinnabar
ACCENT_DEEP = "#8c2d17"
PINE = "#2f7d52"      # --pine, stepped up one shade for the chroma floor
OCHRE_DEEP = "#7d5f00"
CRIT = "#b23a1f"      # failed state wears cinnabar in the web UI

def _rgba(h, a):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) + (a,)


GRID = _rgba(INK, 0.10)
SPINE = _rgba(INK, 0.30)
RAIL = _rgba(INK, 0.05)
ACCENT_TRACK = _rgba(ACCENT, 0.10)
ACCENT_PART = _rgba(ACCENT, 0.38)
SLATE_PART = _rgba(MUTED, 0.32)
FOOT = _rgba(INK, 0.42)
DIM = _rgba(INK, 0.20)

KAPPA = 0.5523

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": [SANS, "Noto Sans CJK SC", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "text.color": INK,
        "axes.edgecolor": SPINE,
        "axes.labelcolor": INK,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "axes.linewidth": 0.8,
        "figure.facecolor": PAPER,
        "axes.facecolor": PAPER,
        "savefig.facecolor": PAPER,
        "legend.frameon": False,
    }
)


def despine(ax, keep=("left", "bottom")):
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(side in keep)


def ygrid(ax, axis="y"):
    ax.grid(axis=axis, color=GRID, linewidth=0.8, linestyle="-")
    ax.set_axisbelow(True)


def eyebrow(fig, text):
    fig.text(0.008, 0.975, text, fontsize=7.5, color=SOFT,
             family=MONO, va="top")


def mono_ticks(ax, axis="x"):
    for t in (ax.get_xticklabels() if axis == "x" else ax.get_yticklabels()):
        t.set_fontfamily(MONO)


def footnote(fig, text, rect=(0, 0.045, 1, 0.93)):
    fig.text(0.008, 0.008, text, fontsize=8, color=FOOT, va="bottom",
             linespacing=1.5)
    fig.tight_layout(rect=rect)


def _px_to_data(ax, px):
    """Device px → data units per axis (needs a prior canvas draw)."""
    bb = ax.get_window_extent()
    (x0, x1), (y0, y1) = ax.get_xlim(), ax.get_ylim()
    return px * (x1 - x0) / bb.width, px * (y1 - y0) / bb.height


def _patch(ax, verts, codes, color, zorder):
    ax.add_patch(PathPatch(Path(verts, codes), facecolor=color,
                           edgecolor="none", zorder=zorder))


def hbar_rail(ax, x0, x1, y, h, rx, ry, color, zorder=1):
    """Capsule rail — both ends rounded."""
    rx = min(rx, (x1 - x0) / 2)
    ry = min(ry, h / 2)
    cx, cy = KAPPA * rx, KAPPA * ry
    yb, yt = y - h / 2, y + h / 2
    verts = [
        (x0 + rx, yb), (x1 - rx, yb),
        (x1 - rx + cx, yb), (x1, yb + ry - cy), (x1, yb + ry),
        (x1, yt - ry),
        (x1, yt - ry + cy), (x1 - rx + cx, yt), (x1 - rx, yt),
        (x0 + rx, yt),
        (x0 + rx - cx, yt), (x0, yt - ry + cy), (x0, yt - ry),
        (x0, yb + ry),
        (x0, yb + ry - cy), (x0 + rx - cx, yb), (x0 + rx, yb),
    ]
    codes = [Path.MOVETO, Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
             Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
             Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
             Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4]
    _patch(ax, verts, codes, color, zorder)


def hbar_end(ax, x0, x1, y, h, rx, ry, color, zorder=3):
    """Bar square at baseline (x0), rounded at data end (x1)."""
    if x1 <= x0:
        return
    rx = min(rx, (x1 - x0))
    ry = min(ry, h / 2)
    cx, cy = KAPPA * rx, KAPPA * ry
    yb, yt = y - h / 2, y + h / 2
    verts = [
        (x0, yb), (x1 - rx, yb),
        (x1 - rx + cx, yb), (x1, yb + ry - cy), (x1, yb + ry),
        (x1, yt - ry),
        (x1, yt - ry + cy), (x1 - rx + cx, yt), (x1 - rx, yt),
        (x0, yt), (x0, yb),
    ]
    codes = [Path.MOVETO, Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
             Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
             Path.LINETO, Path.CLOSEPOLY]
    _patch(ax, verts, codes, color, zorder)


def vbar_top(ax, xc, y1, w, rx, ry, color, zorder=3):
    """Column square at baseline, rounded top."""
    x0, x1 = xc - w / 2, xc + w / 2
    rx = min(rx, w / 2)
    ry = min(ry, y1 / 2)
    cx, cy = KAPPA * rx, KAPPA * ry
    verts = [
        (x0, 0), (x0, y1 - ry),
        (x0, y1 - ry + cy), (x0 + rx - cx, y1), (x0 + rx, y1),
        (x1 - rx, y1),
        (x1 - rx + cx, y1), (x1, y1 - ry + cy), (x1, y1 - ry),
        (x1, 0), (x0, 0),
    ]
    codes = [Path.MOVETO, Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
             Path.LINETO, Path.CURVE4, Path.CURVE4, Path.CURVE4,
             Path.LINETO, Path.CLOSEPOLY]
    _patch(ax, verts, codes, color, zorder)


# ============================== A1: compile-health timeline ==============================
def fig_timeline():
    fig, ax = plt.subplots(figsize=(9.8, 4.9), dpi=200)
    eyebrow(fig, "TEXLATE · COMPILE HEALTH")

    d = lambda s: dt.date.fromisoformat(s)

    # scorecard re-evaluations of stagerun records (loop1 -> loop2 -> v3all)
    scorecard_union = [(d("2026-09-16"), 89.17), (d("2026-09-17"), 97.89),
                       (d("2026-09-18"), 97.26), (d("2026-09-19"), 98.75)]
    scorecard_clean = [(d("2026-09-16"), 57.20), (d("2026-09-17"), 84.99),
                       (d("2026-09-18"), 86.42), (d("2026-09-19"), 88.75)]
    # bare-compile union baseline (compilebench)
    bare = [(d("2026-09-15"), 71.7), (d("2026-09-16"), 71.3), (d("2026-09-19"), 90.2)]
    # real-LLM arm, union
    real = [(d("2026-09-17"), 98.5), (d("2026-09-19"), 96.7)]

    ax.plot(*zip(*scorecard_union), color=ACCENT, lw=1.8, marker="o", ms=6,
            markeredgecolor=PAPER, markeredgewidth=1.4,
            zorder=6, label="计分卡 · 联合口径出 PDF（模拟臂）")
    ax.plot(*zip(*scorecard_clean), color=PINE, lw=1.8, marker="o", ms=6,
            markeredgecolor=PAPER, markeredgewidth=1.4,
            zorder=5, label="计分卡 · 纯净率")
    ax.plot(*zip(*bare), color=SOFT, lw=1.1, ls=(0, (2, 2)), marker="s", ms=5.5,
            markeredgecolor=PAPER, markeredgewidth=1.2,
            zorder=4, label="裸编译基线 · 联合口径出 PDF")
    ax.plot(*zip(*real), color=ACCENT, lw=0, marker="^", ms=8,
            markerfacecolor=PAPER, markeredgecolor=ACCENT, markeredgewidth=1.6,
            zorder=7, label="真实臂 · 联合口径出 PDF")

    # M2 gate — threshold treatment (dashed hairline + label)
    ax.axhline(90, color=MUTED, lw=1.1, ls=(0, (5, 3)), zorder=2)
    ax.text(d("2026-09-15") - dt.timedelta(days=0.15), 90.9, "M2 出口门 ≥90%",
            color=MUTED, fontsize=9, ha="left", va="bottom", fontweight="bold")

    # endpoint value labels (selective: last point of each series)
    ax.annotate("98.75", (d("2026-09-19"), 98.75), xytext=(7, 4),
                textcoords="offset points", color=INK, fontsize=10.5,
                fontweight="bold", family=MONO)
    ax.annotate("88.75", (d("2026-09-19"), 88.75), xytext=(7, -3),
                textcoords="offset points", color=INK, fontsize=10.5,
                fontweight="bold", family=MONO)
    ax.annotate("96.7", (d("2026-09-19"), 96.7), xytext=(8, -11),
                textcoords="offset points", color=INK, fontsize=9,
                fontweight="bold", family=MONO)
    ax.annotate("90.2", (d("2026-09-19"), 90.2), xytext=(-2, 7),
                textcoords="offset points", color=SOFT, fontsize=9,
                fontweight="bold", ha="right", family=MONO)

    # milestone annotations
    ax.annotate("修复循环接线 +18.9pt（同集复跑）",
                xy=(d("2026-09-16") + dt.timedelta(days=0.55), 93.5),
                xytext=(d("2026-09-15") + dt.timedelta(days=0.15), 97.6),
                fontsize=9, color=INK,
                arrowprops=dict(arrowstyle="-|>", color=SOFT, lw=1.0,
                                connectionstyle="arc3,rad=-0.18"))
    ax.text(d("2026-09-17") + dt.timedelta(days=0.12), 92.4, "波次战收残面",
            fontsize=9, color=MUTED, ha="left", va="center")

    # baseline drift honesty note
    ax.annotate("基线自身亦 +19pt（离线宏包/工具链成熟）",
                xy=(d("2026-09-19"), 90.2),
                xytext=(d("2026-09-17") + dt.timedelta(days=0.4), 76.0),
                fontsize=9, color=MUTED,
                arrowprops=dict(arrowstyle="-|>", color=SOFT, lw=1.0,
                                connectionstyle="arc3,rad=0.2"))

    ax.set_ylim(52, 104)
    ax.set_xlim(d("2026-09-14") - dt.timedelta(days=0.4),
                d("2026-09-19") + dt.timedelta(days=1.0))
    ax.set_xticks([d(f"2026-09-{day}") for day in range(15, 20)])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.set_ylabel("出 PDF / 纯净率 %", fontsize=10)
    ygrid(ax)
    despine(ax)
    ax.tick_params(labelsize=9)
    mono_ticks(ax)

    ax.legend(loc="lower right", fontsize=8.8, ncol=2,
              columnspacing=1.3, handlelength=1.7, borderaxespad=0.1)

    footnote(fig,
             "口径：计分卡为 stagerun 落盘记录在代码演进下的重评（loop1 n=5124 → loop2 n=5219 → v3all 跨层样本 n=80）；\n"
             "裸编基线为 compilebench 联合口径（n=180/5059/500）。",
             rect=(0, 0.065, 1, 0.93))
    fig.savefig(OUT / "bench-timeline.png")
    plt.close(fig)


# ============================== B1: pipeline vs bare compile (dumbbell) ==============================
def fig_pipeline_vs_bare():
    fig, ax = plt.subplots(figsize=(9.8, 4.2), dpi=200)
    eyebrow(fig, "TEXLATE · PIPELINE vs BARE COMPILE")

    # (label, bare, zh)
    rows = [
        ("xelatex · 纯净率", 56.3, 72.4),
        ("xelatex · 出 PDF 率", 80.3, 85.4),
        ("tectonic · 纯净率", 38.6, 45.7),
        ("tectonic · 出 PDF 率", 62.4, 59.8),
    ]
    ys = [3, 2, 1, 0]

    for y, (name, b, z) in zip(ys, rows):
        ax.plot([b, z], [y, y], color=DIM, lw=2.2,
                zorder=2, solid_capstyle="round")
        ax.plot(b, y, "o", color=SOFT, ms=8, markeredgecolor=PAPER,
                markeredgewidth=1.5, zorder=4)
        ax.plot(z, y, "o", color=ACCENT, ms=8, markeredgecolor=PAPER,
                markeredgewidth=1.5, zorder=5)
        lo, hi = (b, z) if b < z else (z, b)
        # value labels on the outer side of each dot
        ax.text(lo - 1.6, y, f"{min(b, z)}", ha="right", va="center",
                fontsize=9.5, color=MUTED if min(b, z) == b else INK,
                fontweight="normal" if min(b, z) == b else "bold",
                family=MONO)
        ax.text(hi + 1.6, y, f"{max(b, z)}", ha="left", va="center",
                fontsize=9.5, color=MUTED if max(b, z) == b else INK,
                fontweight="normal" if max(b, z) == b else "bold",
                family=MONO)
        delta = z - b
        dtxt = f"+{delta:.1f}pt" if delta > 0 else f"{delta:.1f}pt"
        ax.text(103, y, dtxt, ha="right", va="center", fontsize=10.5,
                color=ACCENT if delta > 10 else INK,
                fontweight="bold", family=MONO)

    ax.set_yticks(ys)
    ax.set_yticklabels([r[0] for r in rows], fontsize=10.5, color=INK)
    ax.axhline(1.5, color=GRID, lw=0.8, zorder=1)

    ax.set_xlim(0, 105)
    ax.set_ylim(-0.7, 3.7)
    ax.set_xticks([0, 20, 40, 60, 80, 100])
    ax.set_xlabel("%", fontsize=10)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    despine(ax, keep=("bottom",))
    ax.tick_params(axis="x", labelsize=9)
    ax.tick_params(axis="y", length=0)
    mono_ticks(ax)

    handles = [
        Line2D([0], [0], marker="o", color="none", markerfacecolor=SOFT,
               markeredgecolor=PAPER, markeredgewidth=1.2, ms=8,
               label="裸编译基线"),
        Line2D([0], [0], marker="o", color="none", markerfacecolor=ACCENT,
               markeredgecolor=PAPER, markeredgewidth=1.2, ms=8,
               label="中文链（规范化 + ctex 注入后）"),
    ]
    ax.legend(handles=handles, loc="lower left", bbox_to_anchor=(0.0, 1.0),
              ncol=2, fontsize=9.5, columnspacing=1.6, handlelength=1.0)

    footnote(fig,
             "compilebench 500 格抽样：同一批源包，裸编对照 vs 产品链（规范化 + ctex 中文注入）条件。\n"
             "规范化顺带修复源级缺陷——中文臂纯净率不降反升；裸编双引擎联合口径出 PDF 90.4%。",
             rect=(0, 0.07, 1, 0.93))
    fig.savefig(OUT / "bench-pipeline-vs-bare.png")
    plt.close(fig)


# ============================== B2: 8-library parse comparison ==============================
def fig_parse_libs():
    fig, ax = plt.subplots(figsize=(9.8, 5.4), dpi=200)
    eyebrow(fig, "TEXLATE · PARSEBENCH 8-LIB")

    # (name, pass, partial, total, note)
    scored = [
        ("texlate.latex（自研）", 32, 0, 32, "主解析器"),
        ("latex-utensils (TS)", 24, 2, 26, "签名表参考"),
        ("TexSoup (PY)", 21, 0, 25, "tokenizer 参考"),
        ("unified-latex (TS)", 19, 4, 26, "CTAN 宏表 + 展开参考"),
        ("ieeA (PY)", 16, 3, 26, "反面基线"),
    ]
    unscoreable = [
        ("pylatexenc (PY)", "假成功：90/90 报成功，98% 内容静默截断零报错"),
        ("tree-sitter-latex (TS)", "灾难性 ERROR（非解析器定位）→ 转任译文校验器"),
        ("plasTeX (PY)", "~8 主文件静默截断 → 转任展开层设计 oracle"),
        ("LaTeX.js (TS)", "无宏展开，非真 TeX"),
    ]

    fig.canvas.draw()
    rx, ry = _px_to_data(ax, 3.5)

    n_scored = len(scored)
    ys_scored = list(range(9, 9 - n_scored, -1))
    ys_unsc = list(range(3, 3 - len(unscoreable), -1))
    barh = 0.52
    gap, _ = _px_to_data(ax, 2)

    for y, (name, p, part, tot, note) in zip(ys_scored, scored):
        is_self = tot == 32
        track = ACCENT_TRACK if is_self else RAIL
        fill = ACCENT if is_self else MUTED
        pfill = ACCENT_PART if is_self else SLATE_PART
        p_pct, part_pct = 100 * p / tot, 100 * part / tot
        hbar_rail(ax, 0, 100, y, barh, rx, ry, track, zorder=1)
        end = p_pct + part_pct
        if part:
            hbar_end(ax, p_pct + gap / 2, end, y, barh, rx, ry, pfill, zorder=3)
        hbar_rail(ax, 0, p_pct, y, barh, rx, ry, fill, zorder=3)
        lbl = f"{p}(+{part})/{tot}" if part else f"{p}/{tot}"
        ax.text(p_pct - 1.8, y, lbl, fontsize=9.5, va="center", ha="right",
                color="white", family=MONO,
                fontweight="bold" if is_self else "normal", zorder=5)
        ax.text(1.2, y, name, fontsize=10, va="center", ha="left",
                color=INK, fontweight="bold" if is_self else "normal",
                family=SANS if is_self else MONO, zorder=6,
                bbox=dict(facecolor=PAPER, edgecolor="none",
                          alpha=0.92, pad=1.4))
        ax.text(103.5, y, note, fontsize=8.8, va="center", ha="left",
                color=SOFT)

    # section divider + header for the unscoreable group
    ax.axhline(4.55, color=GRID, lw=0.9, ls=(0, (2, 2)))
    ax.text(1.2, 4.0, "无法计分（机制性失败，非断言数不足）",
            fontsize=8.8, color=SOFT, va="center", style="italic")

    for y, (name, note) in zip(ys_unsc, unscoreable):
        ax.text(1.2, y, name, fontsize=10, va="center", ha="left",
                color=MUTED, family=MONO)
        ax.text(34, y, "×", fontsize=10.5, va="center", ha="left",
                color=CRIT, fontweight="bold", family=MONO)
        ax.text(36.5, y, note, fontsize=9.2, va="center", ha="left", color=MUTED)

    # T01 moat annotation
    ax.text(50, -1.35,
            "宏展开陷阱 T01（\\be→\\begin{equation}）：八库全灭，唯自研通过",
            fontsize=10, color=INK, ha="center", fontweight="semibold",
            family=SERIF)

    ax.set_xlim(0, 100)
    ax.set_ylim(-2.6, 9.7)
    ax.set_yticks([])
    ax.set_xlabel("陷阱断言通过率（过 + 半过 / 断言数）%", fontsize=10)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}")
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    despine(ax, keep=("bottom",))
    ax.tick_params(axis="x", labelsize=9)
    mono_ticks(ax)

    handles = [
        Rectangle((0, 0), 1, 1, facecolor=ACCENT, label="通过 · 自研"),
        Rectangle((0, 0), 1, 1, facecolor=MUTED, label="通过 · 第三方"),
        Rectangle((0, 0), 1, 1, facecolor=SLATE_PART, label="半过"),
        Rectangle((0, 0), 1, 1, facecolor=RAIL, label="失败/未过"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=9,
              ncol=4, bbox_to_anchor=(1.0, 0.0), handlelength=1.3,
              columnspacing=1.2)

    footnote(fig,
             "D0 八库横评（corpus39 256 文件 + fixtures 断言集，同口径 PROTOCOL）：第三方断言集 25–26 条；自研 32 条全过。\n"
             "pylatexenc 式「无错误信号的静默截断」比崩溃更危险——校验器因此独立成臂。",
             rect=(0, 0.065, 1, 0.93))
    fig.savefig(OUT / "bench-parse-libs.png")
    plt.close(fig)


# ============================== A2: assets growth (2x2) ==============================
def fig_assets():
    days = ["09-14", "09-15", "09-16", "09-17", "09-18", "09-19"]
    panels = [
        ("pytest 用例", [0, 798, 1920, 4333, 5261, 6450]),
        ("修复规则", [0, 31, 50, 71, 106, 143]),
        ("源码文件", [0, 72, 89, 174, 355, 425]),
        ("评测语料（篇）", [39, 1378, 5410, 5410, 5410, 13266]),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(9.4, 4.8), dpi=200)
    eyebrow(fig, "TEXLATE · BENCH ASSETS")
    x = range(len(days))
    for ax, (title, vals) in zip(axes.flat, panels):
        ax.set_xlim(-0.6, len(days) - 0.4)
        ax.set_ylim(0, max(vals) * 1.25)
        fig.canvas.draw()
        rx, ry = _px_to_data(ax, 2.5)
        for xi, v in zip(x, vals):
            if v > 0:
                vbar_top(ax, xi, v, 0.58, rx, ry, ACCENT, zorder=3)
        last = vals[-1]
        ax.text(len(days) - 1, last * 1.045, f"{last:,}",
                ha="right", va="bottom", fontsize=13, fontweight="bold",
                color=INK, family=MONO)
        ax.set_title(title, fontsize=11, pad=5, color=INK, loc="left",
                     fontweight="semibold", family=SERIF)
        ax.set_xticks(list(x))
        ax.set_xticklabels([d[3:] for d in days], fontsize=8.5)
        ax.set_yticks([])
        despine(ax, keep=("bottom",))
        ax.tick_params(length=0)
        mono_ticks(ax)
    footnote(fig,
             "同日口径抽样自 git 历史（2026-09-14 → 09-19）：规则库为 16 分片 yaml；\n"
             "语料为 corpus_v3 钉版层累加（另 corpus_daily 日更渠 ~1,200 篇/日在库外增长）。",
             rect=(0, 0.065, 1, 0.9))
    fig.savefig(OUT / "bench-assets.png")
    plt.close(fig)


if __name__ == "__main__":
    fig_timeline()
    fig_pipeline_vs_bare()
    fig_parse_libs()
    fig_assets()
    print("wrote:", *sorted(p.name for p in OUT.glob("bench-*.png")), sep="\n  ")
