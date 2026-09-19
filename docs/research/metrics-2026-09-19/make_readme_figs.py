#!/usr/bin/env python3
"""README figures — regenerate with: uv run --with matplotlib python make_readme_figs.py

Reads the local data/ CSVs (self-contained) and writes PNGs to <repo>/shots/.
Style: Chinese labels (Noto Sans CJK SC), report palette, 200 dpi.
"""

import csv
import datetime as dt
import pathlib

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = REPO / "shots"
OUT.mkdir(exist_ok=True)

# ---- palette (same as report.tex) ----
CA = "#1f6fb2"  # blue
CB = "#c0392b"  # red
CD = "#2e8b57"  # green
CE = "#7d3c98"  # purple
GRAY = "#8a8a8a"
INK = "#222222"
TRACK = "#ececec"

plt.rcParams.update(
    {
        "font.family": "sans-serif",
        "font.sans-serif": ["Noto Sans CJK SC", "DejaVu Sans"],
        "axes.unicode_minus": False,
        "text.color": INK,
        "axes.edgecolor": "#9a9a9a",
        "axes.labelcolor": INK,
        "xtick.color": "#555555",
        "ytick.color": "#555555",
        "axes.linewidth": 0.9,
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "savefig.facecolor": "white",
    }
)


def despine(ax, keep=("left", "bottom")):
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(side in keep)


def ygrid(ax):
    ax.grid(axis="y", color="#c9c9c9", alpha=0.45, linewidth=0.7)
    ax.set_axisbelow(True)


# ============================== A1: compile-health timeline ==============================
def fig_timeline():
    fig, ax = plt.subplots(figsize=(9.8, 4.7), dpi=200)

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

    ax.plot(*zip(*scorecard_union), color=CA, lw=2.2, marker="o", ms=5.5,
            zorder=5, label="计分卡 · 联合口径出 PDF（模拟臂）")
    ax.plot(*zip(*scorecard_clean), color=CB, lw=2.2, marker="o", ms=5.5,
            zorder=5, label="计分卡 · 纯净率")
    ax.plot(*zip(*bare), color=GRAY, lw=0, marker="s", ms=6.5,
            zorder=4, label="裸编译基线 · 联合口径出 PDF")
    ax.plot(*zip(*real), color=CE, lw=0, marker="^", ms=8.5,
            markeredgecolor="white", markeredgewidth=0.9,
            zorder=6, label="真实臂 · 联合口径出 PDF")

    # M2 gate
    ax.axhline(90, color=CD, lw=1.4, ls=(0, (5, 3)), zorder=2)
    ax.text(d("2026-09-15") - dt.timedelta(days=0.15), 90.9, "M2 出口门 ≥90%",
            color=CD, fontsize=9.5, ha="left", va="bottom", fontweight="bold")

    # endpoint value labels
    ax.annotate("98.75", (d("2026-09-19"), 98.75), xytext=(6, 5),
                textcoords="offset points", color=CA, fontsize=10, fontweight="bold")
    ax.annotate("88.75", (d("2026-09-19"), 88.75), xytext=(6, -2),
                textcoords="offset points", color=CB, fontsize=10, fontweight="bold")
    ax.annotate("90.2", (d("2026-09-19"), 90.2), xytext=(-8, 4),
                textcoords="offset points", color="#6e6e6e",
                fontsize=9.5, fontweight="bold", ha="right")

    # milestone annotations
    ax.annotate("修复循环接线\n+18.9pt（同集复跑）",
                xy=(d("2026-09-16") + dt.timedelta(days=0.55), 93.5),
                xytext=(d("2026-09-15") + dt.timedelta(days=0.35), 96.8),
                fontsize=9, color=INK,
                arrowprops=dict(arrowstyle="-|>", color="#777777", lw=1.1,
                                connectionstyle="arc3,rad=-0.18"))
    ax.text(d("2026-09-17") + dt.timedelta(days=0.12), 92.4, "波次战收残面",
            fontsize=9, color="#555555", ha="left", va="center")

    # baseline drift honesty note
    ax.annotate("基线自身亦 +19pt\n（离线宏包/工具链成熟）",
                xy=(d("2026-09-19"), 90.2),
                xytext=(d("2026-09-17") + dt.timedelta(days=0.45), 76.5),
                fontsize=9, color="#6e6e6e",
                arrowprops=dict(arrowstyle="-|>", color="#a5a5a5", lw=1.0,
                                connectionstyle="arc3,rad=0.2"))

    ax.set_ylim(52, 104)
    ax.set_xlim(d("2026-09-14") - dt.timedelta(days=0.4), d("2026-09-19") + dt.timedelta(days=1.0))
    ax.set_xticks([d(f"2026-09-{day}") for day in range(15, 20)])
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
    ax.set_ylabel("出 PDF / 纯净率 %", fontsize=10.5)
    ygrid(ax)
    despine(ax)
    ax.tick_params(labelsize=9.5)

    ax.legend(loc="lower right", fontsize=9, frameon=False, ncol=2,
              columnspacing=1.4, handlelength=1.8, borderaxespad=0.1)

    fig.text(0.008, 0.012,
             "口径：计分卡为 stagerun 落盘记录在代码演进下的重评（loop1 n=5124 → loop2 n=5219 → v3all 跨层样本 n=80）；裸编基线为 compilebench 联合口径（n=180/5059/500）。",
             fontsize=8, color="#8a8a8a")
    fig.tight_layout(rect=(0, 0.035, 1, 1))
    fig.savefig(OUT / "bench-timeline.png")
    plt.close(fig)


# ============================== B1: pipeline vs bare compile ==============================
def fig_pipeline_vs_bare():
    fig, ax = plt.subplots(figsize=(8.6, 4.4), dpi=200)

    groups = [("xelatex", "纯净率", 56.3, 72.4), ("xelatex", "出 PDF 率", 80.3, 85.4),
              ("tectonic", "纯净率", 38.6, 45.7), ("tectonic", "出 PDF 率", 62.4, 59.8)]
    x = list(range(len(groups)))
    w = 0.36
    base = [g[2] for g in groups]
    zh = [g[3] for g in groups]

    b1 = ax.bar([i - w / 2 for i in x], base, width=w, color="#9d9d9d",
                label="裸编译基线", zorder=3)
    b2 = ax.bar([i + w / 2 for i in x], zh, width=w, color=CA,
                label="中文链（规范化 + ctex 注入后）", zorder=3)

    for bars, vals in ((b1, base), (b2, zh)):
        for rect, v in zip(bars, vals):
            ax.text(rect.get_x() + rect.get_width() / 2, v + 1.6, f"{v}",
                    ha="center", va="bottom", fontsize=9.5,
                    color="#5f5f5f" if bars is b1 else CA,
                    fontweight="bold" if bars is b2 else "normal")

    # +16.1pt bracket on group 0 — stubs stop just above each bar's value label
    y0 = 80
    ax.plot([-w / 2, -w / 2], [base[0] + 6, y0], color=CB, lw=1.1, zorder=4)
    ax.plot([w / 2, w / 2], [zh[0] + 5.5, y0], color=CB, lw=1.1, zorder=4)
    ax.plot([-w / 2, w / 2], [y0, y0], color=CB, lw=1.1, zorder=4)
    ax.text(0, y0 + 1.8, "+16.1pt", ha="center", va="bottom",
            color=CB, fontsize=11, fontweight="bold", zorder=4)

    # union-pdf reference line (bare arm, best-of-two-engines)
    ax.axhline(90.4, color=CD, lw=1.3, ls=(0, (5, 3)), zorder=2)
    ax.text(3.62, 90.4, "裸编双引擎\n联合口径 90.4%", color=CD, fontsize=8.8,
            ha="left", va="center", linespacing=1.3)

    ax.set_xticks(x)
    ax.set_xticklabels([g[1] for g in groups], fontsize=10)
    # engine group labels — second row, centered under each pair
    for cx, name in ((0.5, "xelatex"), (2.5, "tectonic")):
        ax.text(cx, -17, name, ha="center", va="top", fontsize=10.5,
                color="#444444", fontweight="bold")
    ax.plot([], [])  # keep layout
    for sep in (1.5,):
        ax.axvline(sep, color="#d5d5d5", lw=0.9, zorder=1)

    ax.set_ylim(0, 104)
    ax.set_xlim(-0.62, 3.62)
    ax.set_ylabel("%", fontsize=10.5)
    ygrid(ax)
    despine(ax)
    ax.tick_params(axis="x", pad=7, length=0)
    ax.legend(loc="lower left", bbox_to_anchor=(0.0, 1.005), ncol=2,
              fontsize=9.5, frameon=False, columnspacing=1.6, handlelength=1.6)

    fig.text(0.008, 0.012,
             "compilebench 500 格抽样：同一批源包，裸编对照 vs 产品链（规范化 + ctex 中文注入）条件。规范化顺带修复源级缺陷——中文臂纯净率不降反升。",
             fontsize=8, color="#8a8a8a")
    fig.tight_layout(rect=(0, 0.055, 1, 1))
    fig.savefig(OUT / "bench-pipeline-vs-bare.png")
    plt.close(fig)


# ============================== B2: 8-library parse comparison ==============================
def fig_parse_libs():
    fig, ax = plt.subplots(figsize=(9.8, 5.2), dpi=200)

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

    n_scored = len(scored)
    # scored rows y = 9..5, section header at y=4, unscoreable y = 3..0
    ys_scored = list(range(9, 9 - n_scored, -1))
    ys_unsc = list(range(3, 3 - len(unscoreable), -1))
    barh = 0.56

    for y, (name, p, part, tot, note) in zip(ys_scored, scored):
        pct = 100.0 * (p + part) / tot
        ax.add_patch(Rectangle((0, y - barh / 2), 100, barh,
                               facecolor=TRACK, edgecolor="none", zorder=1))
        c_main = CA if tot == 32 else "#7fa8cc"
        ax.barh(y, 100 * p / tot, height=barh, color=c_main, zorder=3)
        if part:
            ax.barh(y, 100 * part / tot, left=100 * p / tot, height=barh,
                    color="#c7d6e5", zorder=3)
        lbl = f"{p}(+{part})/{tot}" if part else f"{p}/{tot}"
        ax.text(97.6, y, lbl, fontsize=9.5, va="center", ha="right",
                color="white" if tot == 32 else INK,
                fontweight="bold" if tot == 32 else "normal", zorder=5)
        ax.text(0.8, y, name, fontsize=10, va="center", ha="left",
                color=INK, fontweight="bold" if tot == 32 else "normal", zorder=6,
                bbox=dict(facecolor="white", edgecolor="none", alpha=0.85, pad=1.2))
        ax.text(103.5, y, note, fontsize=8.8, va="center", ha="left", color="#8a8a8a")

    # section divider + header for the unscoreable group
    ax.axhline(4.55, color="#c9c9c9", lw=0.9, ls=(0, (2, 2)))
    ax.text(0.8, 4.0, "无法计分（机制性失败，非断言数不足）",
            fontsize=8.8, color="#8a8a8a", va="center", style="italic")

    for y, (name, note) in zip(ys_unsc, unscoreable):
        ax.text(0.8, y, name, fontsize=10, va="center", ha="left", color="#555555")
        ax.text(34, y, "× " + note, fontsize=9.2, va="center", ha="left", color="#a0483c")

    # T01 moat annotation
    ax.text(50, -1.15, "宏展开陷阱 T01（\\be→\\begin{equation}）：八库全灭，唯自研通过",
            fontsize=10, color=CB, ha="center", fontweight="bold")

    ax.set_xlim(0, 100)
    ax.set_ylim(-1.7, 9.7)
    ax.set_yticks([])
    ax.set_xlabel("陷阱断言通过率（过 + 半过 / 断言数）%", fontsize=10)
    ax.xaxis.set_major_formatter(lambda v, _: f"{v:.0f}")
    ax.grid(axis="x", color="#c9c9c9", alpha=0.45, linewidth=0.7)
    ax.set_axisbelow(True)
    despine(ax, keep=("bottom",))
    ax.tick_params(axis="x", labelsize=9.5)

    # legend for pass/partial
    handles = [
        Rectangle((0, 0), 1, 1, facecolor=CA, label="断言通过"),
        Rectangle((0, 0), 1, 1, facecolor="#c7d6e5", label="半过"),
        Rectangle((0, 0), 1, 1, facecolor=TRACK, label="失败/未过"),
    ]
    ax.legend(handles=handles, loc="lower right", fontsize=9, frameon=False,
              ncol=3, bbox_to_anchor=(1.0, -0.02), handlelength=1.4,
              columnspacing=1.2)

    fig.text(0.008, 0.012,
             "D0 八库横评（corpus39 256 文件 + fixtures 断言集，同口径 PROTOCOL）：第三方断言集 25–26 条；自研 32 条全过。pylatexenc 式「无错误信号的静默截断」比崩溃更危险——校验器因此独立成臂。",
             fontsize=8, color="#8a8a8a")
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    fig.savefig(OUT / "bench-parse-libs.png")
    plt.close(fig)


# ============================== A2: assets growth (2x2) ==============================
def fig_assets():
    days = ["09-14", "09-15", "09-16", "09-17", "09-18", "09-19"]
    panels = [
        ("pytest 用例", [0, 798, 1920, 4333, 5261, 6450], CA),
        ("修复规则", [0, 31, 50, 71, 106, 143], CB),
        ("源码文件", [0, 72, 89, 174, 355, 425], CE),
        ("评测语料（篇）", [39, 1378, 5410, 5410, 5410, 13266], CD),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(9.4, 4.6), dpi=200)
    x = range(len(days))
    for ax, (title, vals, color) in zip(axes.flat, panels):
        ax.bar(x, vals, width=0.6, color=color, alpha=0.85, zorder=3)
        last = vals[-1]
        ax.text(len(days) - 1, last, f"{last:,}",
                ha="right", va="bottom", fontsize=11.5, fontweight="bold",
                color=color)
        ax.set_title(title, fontsize=11, pad=4)
        ax.set_xticks(list(x))
        ax.set_xticklabels([d[3:] for d in days], fontsize=8.5)
        ax.set_ylim(0, last * 1.2)
        ax.set_yticks([])
        despine(ax, keep=("bottom",))
        ax.tick_params(length=0)
    fig.suptitle("六天评测资产增长（09-14 → 09-19）", fontsize=12.5,
                 fontweight="bold", y=0.985)
    fig.text(0.008, 0.012,
             "同日口径抽样自 git 历史：规则库为 16 分片 yaml；语料为 corpus_v3 钉版层累加（另 corpus_daily 日更渠 ~1,200 篇/日在库外增长）。",
             fontsize=8, color="#8a8a8a")
    fig.tight_layout(rect=(0, 0.045, 1, 0.95), h_pad=1.8, w_pad=2.0)
    fig.savefig(OUT / "bench-assets.png")
    plt.close(fig)


# ============================== pipeline flowchart ==============================
def fig_pipeline():
    fig, ax = plt.subplots(figsize=(12.6, 6.3), dpi=200)
    ax.set_xlim(0, 140)
    ax.set_ylim(0, 72)
    ax.axis("off")

    def stage(x, w, title, items, h=30, y=34, title_c=CA):
        ax.add_patch(FancyBboxPatch(
            (x, y), w, h, boxstyle="round,pad=0.6,rounding_size=1.6",
            facecolor="white", edgecolor="#b9c6d2", lw=1.2, zorder=3))
        ax.add_patch(FancyBboxPatch(
            (x, y + h - 5.2), w, 5.2, boxstyle="round,pad=0.6,rounding_size=1.6",
            facecolor=title_c, edgecolor="none", zorder=4))
        ax.add_patch(Rectangle((x, y + h - 5.2), w, 2.2,
                               facecolor=title_c, edgecolor="none", zorder=4))
        ax.text(x + w / 2, y + h - 2.6, title, ha="center", va="center",
                fontsize=10.5, fontweight="bold", color="white", zorder=5)
        for i, it in enumerate(items):
            ax.text(x + 1.5, y + h - 8.3 - i * 3.35, it, ha="left", va="center",
                    fontsize=8.6, color=INK, zorder=5)
        return (x, y, w, h)

    def arrow(x1, x2, y=49, color="#8a8a8a", lw=1.6):
        ax.annotate("", xy=(x2, y), xytext=(x1, y),
                    arrowprops=dict(arrowstyle="-|>", color=color, lw=lw))

    # ---- main chain ----
    stage(1.5, 15.5, "fetch 获取", [
        "arXiv ID → e-print",
        "版本四元组钉版",
        "源包缓存 ~/.cache",
        "解压源树",
    ])
    stage(21.5, 19.5, "parse 半解析", [
        "main.tex 定位",
        "多文件合平 flatten",
        "gullet 展开机·宏表",
        "segmenter 切分 pieces",
        "译段 + 占位符保护",
        "→ chunks.jsonl",
    ])
    stage(45.5, 18.5, "xlat 翻译", [
        "段级并发编排",
        "LLM 网关 BYOK",
        "mock 假译臂自检",
        "SQLite 段缓存",
    ])
    stage(68.5, 15, "inject 注入", [
        "译文回填 pieces",
        "ctex 中文环境",
        "normalize 规范化",
        "路由预检·引擎分流",
    ])
    stage(88, 19, "compile 编译", [
        "xelatex / tectonic",
        "沙箱 ≤2 轮·240s",
        "texlog 日志栈解析",
        "fixloop: taxonomy",
        "→ yaml 规则·重试",
    ])
    stage(111.5, 14.5, "judge 判定", [
        "纯净/带瑕/失败",
        "CJK 字数核验",
        "named-dest 锚点",
        "→ 双语 PDF",
    ])
    stage(130.5, 9.5, "web 阅读", [
        "SSE 进度",
        "锚点同步",
        "滚动对照",
    ], title_c=CD)

    for x1, x2 in [(17, 21.5), (41, 45.5), (64, 68.5), (83.5, 88), (107, 111.5), (126, 130.5)]:
        arrow(x1, x2)

    # ---- fixloop feedback arc: judge fail -> back into compile ----
    ax.annotate("", xy=(97.5, 33.4), xytext=(118.5, 33.4),
                arrowprops=dict(arrowstyle="-|>", color=CB, lw=1.5,
                                connectionstyle="arc3,rad=0.35"))
    ax.text(108, 27.5, "失败格 → fixloop 修复 → 重编译", ha="center",
            fontsize=8.8, color=CB)

    # ---- fallback chain (dashed, under fetch/parse) ----
    ax.add_patch(FancyBboxPatch(
        (1.5, 15.5), 41.5, 12.5, boxstyle="round,pad=0.6,rounding_size=1.6",
        facecolor="#fafafa", edgecolor="#a08a5a", lw=1.1, ls=(0, (4, 3)), zorder=2))
    ax.text(3.2, 25.3, "降级链（无 LaTeX 源时）", fontsize=8.8, color="#8a6d00",
            fontweight="bold")
    ax.text(3.2, 21.6, "e-print 无源 → arXiv HTML（同覆盖异构）",
            fontsize=8.6, color="#6b5d3a")
    ax.text(3.2, 18.1, "→ 仅 PDF → BabelDOC sidecar（AGPL 隔离）",
            fontsize=8.6, color="#6b5d3a")
    ax.annotate("", xy=(9, 33.4), xytext=(9, 28.4),
                arrowprops=dict(arrowstyle="-|>", color="#a08a5a", lw=1.2,
                                ls=(0, (4, 3))))

    # ---- validators chip (under xlat) ----
    ax.add_patch(FancyBboxPatch(
        (45.5, 17.5), 37, 9.5, boxstyle="round,pad=0.6,rounding_size=1.6",
        facecolor="#f4f0f8", edgecolor=CE, lw=1.1, zorder=2))
    ax.text(47.2, 24.4, "校验器（独立成臂）", fontsize=8.8, color=CE, fontweight="bold")
    ax.text(47.2, 20.2, "L0 占位符多重集 diff·brace/env/cite-key；L1 tree-sitter", fontsize=8.4,
            color="#5b4a70")
    ax.annotate("", xy=(55, 33.4), xytext=(55, 27.8),
                arrowprops=dict(arrowstyle="-|>", color=CE, lw=1.2))

    # ---- bench badges along the bottom ----
    badges = [
        (9.2, "corpus_v3\n13,266 篇·8 层钉版"),
        (31, "parsebench\n一致率 99.99%·泄漏 0.004%"),
        (54.5, "xlat/qualbench\n硬契约 93.7%·ESA 94.0"),
        (77.5, "validbench\n1,503 对·100% 检出"),
        (97.5, "compilebench\n联合出 PDF 90.4%"),
        (118.5, "e2e/stagerun\n98.75%·0 引入回归"),
    ]
    for cx, txt in badges:
        w = 17.4
        ax.add_patch(FancyBboxPatch(
            (cx - w / 2, 3.5), w, 9.5, boxstyle="round,pad=0.5,rounding_size=1.4",
            facecolor="#f2f2f2", edgecolor="#c9c9c9", lw=0.9, zorder=2))
        ax.text(cx, 8.25, txt, ha="center", va="center", fontsize=8,
                color="#5a5a5a", linespacing=1.45)

    fig.text(0.5, 0.975, "texlate 管线与评测对应关系",
             ha="center", fontsize=12.5, fontweight="bold")
    fig.tight_layout(rect=(0, 0.005, 1, 0.955))
    fig.savefig(OUT / "bench-pipeline.png")
    plt.close(fig)


if __name__ == "__main__":
    fig_timeline()
    fig_pipeline_vs_bare()
    fig_parse_libs()
    fig_assets()
    fig_pipeline()
    print("wrote:", *sorted(p.name for p in OUT.glob("bench-*.png")), sep="\n  ")
