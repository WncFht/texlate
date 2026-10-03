"""README shots 数据图再生——bench-token.png / bench-e2e.png。

风格台账：editorial token 系统（PAPER/INK/MUTED/SOFT/ACCENT/PINE 取自
web/src/styles/base.css 品牌面），与 shots/bench-pipeline.png（HTML/SVG）
和 shots/bench-parse-libs.png（metrics-2026-09-19/make_readme_figs.py）
同一视觉身份：米色纸面、墨色正文、朱红主角、衬线主张行 + mono 眉题 +
footnote 尾注三层结构。fvstyle 仅供机器审计（register_colors 放行色板）。

几何台账：
- bench-token.png A 面：x=论文序（10 篇 2609.*），y=新输入 token（log，
  柱底贴轴下限 1e4）；两系列=agent 直翻 / 当前管线。B 面：x=指标
  （新输入/总输入/输出），y=token（log，柱底贴 500）；柱顶标绝对值与
  管线/agent 比。
- bench-e2e.png：y=测试集（通用 200 / 新 CS 200），x=篇数 0–200 堆叠
  终态分解（编译即交付 / fixloop 救回 / 修不了 / 上游链断）；行内点线
  tick=原文直编对照交付数。

语义台账：管线=ACCENT 朱红（主角惯例，同 parse-libs 自研列）；agent=
MUTED 灰（对照组惯例）。终态类=交付归因（ACCENT 直接交付、PINE 修复
救回、SOFT 修不了、DIM 上游死）。数据源自
docs/research/methods/token-economy-2026-10-03/data/per-paper-tokens.json
与 e2e 两篇冻帧文档的逐篇交付账。

运行：uv run --with matplotlib python tools/make_readme_shots.py
"""

import json
import sys
from pathlib import Path

import matplotlib as mpl

mpl.use("Agg")

import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle

_ROOT = Path(__file__).resolve().parents[1]
for _c in (
    Path.home() / ".claude/skills/figure-viz/assets/mpl",
    Path.home() / ".agents/skills/figure-viz/assets/mpl",
    Path.home() / ".codex/skills/figure-viz/assets/mpl",
):
    if (_c / "fvstyle.py").exists():
        sys.path.insert(0, str(_c))
        break

import fvstyle as fv

# ---- web brand token system (web/src/styles/base.css) ----
PAPER = "#f5f1e8"
INK = "#211b12"
MUTED = "#6e6454"
SOFT = "#9a8f7c"
ACCENT = "#b23a1f"
PINE = "#2f7d52"


def _blend(fg: str, alpha: float, bg: str = PAPER) -> str:
    """alpha 色落成纸面等效 hex（OFFPALETTE 按实体色审计）。"""
    f = tuple(int(fg[i : i + 2], 16) for i in (1, 3, 5))
    b = tuple(int(bg[i : i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(
        f"{round(f[i] * alpha + b[i] * (1 - alpha)):02X}" for i in range(3)
    )


GRID = _blend(INK, 0.10)
SPINE = _blend(INK, 0.30)
DIM = _blend(INK, 0.20)
FOOT = _blend(INK, 0.42)

for _f in ("LXGWWenKai-Regular.ttf", "LXGWWenKai-Medium.ttf", "LXGWWenKai-Light.ttf"):
    if Path(f"/usr/share/fonts/TTF/{_f}").is_file():
        font_manager.fontManager.addfont(f"/usr/share/fonts/TTF/{_f}")

SANS = "LXGW WenKai"
MONO = "JetBrainsMono NF"
SERIF = "Noto Serif CJK SC"

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

DATA = json.loads(
    (
        _ROOT
        / "docs/research/methods/token-economy-2026-10-03/data/per-paper-tokens.json"
    ).read_text()
)
OUT = _ROOT / "shots"

fv.register_colors(PAPER, INK, MUTED, SOFT, ACCENT, PINE, GRID, SPINE, DIM, FOOT)


def despine(ax, keep=("left", "bottom")):
    for side in ("top", "right", "left", "bottom"):
        ax.spines[side].set_visible(side in keep)


def eyebrow(fig, text):
    fig.text(0.008, 0.975, text, fontsize=7.5, color=SOFT, family=MONO, va="top")


def mono_ticks(ax, axis="both"):
    for t in (
        ax.get_xticklabels() + ax.get_yticklabels()
        if axis == "both"
        else (ax.get_xticklabels() if axis == "x" else ax.get_yticklabels())
    ):
        t.set_fontfamily(MONO)


def footnote(fig, text, rect=(0, 0.045, 1, 0.93)):
    fig.text(0.008, 0.008, text, fontsize=8, color=FOOT, va="bottom", linespacing=1.5)
    fig.tight_layout(rect=rect)


def claim(fig, text, y):
    fig.text(
        0.5,
        y,
        text,
        fontsize=10.5,
        color=INK,
        ha="center",
        family=SERIF,
        fontweight="semibold",
    )


def fig_token() -> None:
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.8, 3.8), width_ratios=[1.55, 1])
    eyebrow(fig, "TEXLATE · TOKEN ECONOMY")

    papers = DATA["paper"]
    x = list(range(len(papers)))
    w = 0.38
    a.bar(
        [t - w / 2 for t in x],
        [DATA["agent"][p]["input"] for p in papers],
        width=w,
        bottom=1e4,
        color=MUTED,
        label="agent 直翻",
    )
    a.bar(
        [t + w / 2 for t in x],
        [DATA["current"][p]["input"] for p in papers],
        width=w,
        bottom=1e4,
        color=ACCENT,
        label="texlate 管线",
    )
    a.set_yscale("log")
    a.set_ylim(1e4, 8e6)
    a.set_xticks(x)
    a.set_xticklabels([p.split(".")[1] for p in papers], fontsize=8)
    a.set_xlabel("arXiv 2609.xxxxx", fontsize=9.5)
    a.set_ylabel("新输入 token（对数轴）", fontsize=9.5)
    a.legend(loc="upper right", fontsize=8.5)

    tot = DATA["_total"]
    metrics = ["新输入", "总输入\n(含缓存读)", "输出"]
    agent_v = [
        tot["agent"]["input"],
        tot["agent"]["input"] + tot["agent"]["cache_read"],
        tot["agent"]["output"],
    ]
    cur_v = [
        tot["current"]["input"],
        tot["current"]["input"] + tot["current"]["cache_read"],
        tot["current"]["output"],
    ]
    ratio = ["0.23×", "0.02×", "0.48×"]
    bx = list(range(3))
    b.bar([t - w / 2 for t in bx], agent_v, width=w, bottom=500, color=MUTED)
    b.bar([t + w / 2 for t in bx], cur_v, width=w, bottom=500, color=ACCENT)
    for i, (av, cv, r) in enumerate(zip(agent_v, cur_v, ratio, strict=True)):
        b.text(
            i - w / 2,
            av * 1.3,
            f"{av / 1e6:.1f}M",
            ha="center",
            fontsize=8.5,
            family=MONO,
        )
        lab = f"{cv / 1e6:.2f}M" if cv > 1e5 else f"{cv / 1e3:.1f}k"
        b.text(
            i + w / 2, cv * 1.3, f"{lab}\n{r}", ha="center", fontsize=8.5, family=MONO
        )
    b.set_yscale("log")
    b.set_ylim(500, 5e8)
    b.set_xticks(bx)
    b.set_xticklabels(metrics, fontsize=9)

    for ax in (a, b):
        ax.grid(axis="y", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
        despine(ax)
        mono_ticks(ax, "y")

    claim(
        fig, "同 10 篇同模型：管线新输入为 agent 的 23%、总输入 2.0%、输出 48%", 0.075
    )
    footnote(
        fig,
        "两路同题对照 · 同模型 swe-2-medium · 网关逐请求账本（2026-09/10）",
        rect=(0, 0.16, 1, 0.96),
    )
    problems = fv.audit(fig, ignore=["facet-ylim-mismatch"])
    for p in problems:
        print("token audit:", p)
    fig.savefig(OUT / "bench-token.png", dpi=200)
    plt.close(fig)


def fig_e2e() -> None:
    rows = [
        ("通用留出 200 篇", 129, 42, 3, 26, 152, "85.5%"),
        ("新 CS 200 篇", 141, 50, 1, 8, 192, "95.5%"),
    ]
    cats = ["编译即交付", "fixloop 修复救回", "修不了", "上游链断"]
    colors = [ACCENT, PINE, SOFT, DIM]
    fig, ax = plt.subplots(figsize=(9.8, 3.0))
    eyebrow(fig, "TEXLATE · E2E HOLDOUT")

    y = [0, 1]
    h = 0.52
    for ci, (_cat, color) in enumerate(zip(cats, colors, strict=True)):
        widths = [r[1 + ci] for r in rows]
        lefts = [sum(r[1 : 1 + ci]) for r in rows]
        ax.barh(y, widths, left=lefts, height=h, color=color)
    for yi, (_name, direct, rescued, _unfix, _up, bare, pct) in zip(
        y, rows, strict=True
    ):
        delivered = direct + rescued
        ax.text(
            204, yi, f"{delivered}/200 · {pct}", va="center", fontsize=10, family=MONO
        )
        ax.vlines(
            bare,
            yi - h / 2 - 0.09,
            yi + h / 2 + 0.09,
            color=INK,
            linewidth=1.4,
            linestyles=":",
        )
        ax.text(
            bare + 2,
            yi + h / 2 + 0.14,
            str(bare),
            ha="left",
            fontsize=8,
            color=INK,
            family=MONO,
        )
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=10)
    ax.set_xlim(0, 248)
    ax.set_ylim(-0.62, 1.62)
    ax.set_xlabel("论文篇数", fontsize=9.5)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    despine(ax, keep=("bottom",))
    mono_ticks(ax, "x")

    handles = [Rectangle((0, 0), 1, 1, facecolor=c) for c in colors]
    handles.append(Line2D([], [], color=INK, linestyle=":", linewidth=1.4))
    ax.legend(
        handles,
        [*cats, "原文直编交付数"],
        loc="upper center",
        bbox_to_anchor=(0.5, 1.16),
        fontsize=8,
        ncol=5,
        columnspacing=1.0,
        handlelength=1.2,
    )

    claim(fig, "交付面贴平原文直编上限：通用集反超 19 篇，新 CS 集差 1 篇", 0.135)
    footnote(
        fig,
        "e2e_eval 留出测试集逐篇终态分解（2026-10-02/03 口径）",
        rect=(0, 0.26, 1, 0.94),
    )
    problems = fv.audit(fig)
    for p in problems:
        print("e2e audit:", p)
    fig.savefig(OUT / "bench-e2e.png", dpi=200)
    plt.close(fig)


if __name__ == "__main__":
    fig_token()
    fig_e2e()
    print("shots written")
