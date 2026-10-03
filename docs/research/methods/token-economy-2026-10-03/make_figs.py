"""token-economy-2026-10-03 图组再生脚本。

输入：data/per-paper-tokens.json（逐篇账，含早期实现存档字段，图面只绘
当前实现与 agent 两路）+ data/ekg-19506.json（2609.19506 逐调用
[in, cr, out] 行）。产物：charts/*.png。
运行：uv run --with matplotlib python make_figs.py
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import matplotlib.pyplot as plt
from _figstyle import HUES, NEUTRALS, apply_rc

apply_rc("paper")

DATA = json.loads((HERE / "data" / "per-paper-tokens.json").read_text())
EKG = json.loads((HERE / "data" / "ekg-19506.json").read_text())
PAPERS = DATA["paper"]
LABELS = {"current": "当前实现", "agent": "agent 直翻"}
COLORS = {"current": HUES["vteal"], "agent": HUES["vorange"]}


def _short(pid: str) -> str:
    return pid.split(".")[1]


def fig_per_paper() -> None:
    fig, (a, b) = plt.subplots(1, 2, figsize=(11.5, 4.2))
    x = range(len(PAPERS))
    w = 0.38
    for i, arm in enumerate(("current", "agent")):
        vals = [DATA[arm][p]["input"] for p in PAPERS]
        a.bar(
            [t + (i - 0.5) * w for t in x],
            vals,
            width=w,
            color=COLORS[arm],
            label=LABELS[arm],
        )
        calls = [DATA[arm][p]["calls"] for p in PAPERS]
        b.bar(
            [t + (i - 0.5) * w for t in x],
            calls,
            width=w,
            color=COLORS[arm],
            label=LABELS[arm],
        )
    a.set_yscale("log")
    a.set_ylabel("新输入 token（对数轴）")
    a.set_title("A · 逐篇新输入", loc="left")
    b.set_ylabel("API 调用数")
    b.set_title("B · 逐篇调用数", loc="left")
    for ax in (a, b):
        ax.set_xticks(list(x))
        ax.set_xticklabels([_short(p) for p in PAPERS], rotation=45, ha="right")
        ax.set_xlabel("arXiv 论文（2609.xxxxx）")
        ax.grid(axis="y", alpha=0.5)
        ax.set_axisbelow(True)
    a.legend()
    fig.tight_layout()
    fig.savefig(HERE / "charts" / "per-paper-input.png", dpi=180)
    plt.close(fig)


def fig_composition() -> None:
    fig, (a, b) = plt.subplots(1, 2, figsize=(7.5, 4.2))
    arms = ("current", "agent")
    payload = {
        "current": 902_843,
        "agent": 3_298_789,
    }
    overhead = {
        "current": 1_094_448 - 902_843,
        "agent": 1_450_083,
    }
    x = range(len(arms))
    a.bar(x, [payload[k] for k in arms], color=HUES["vteal"], label="有效载荷")
    a.bar(
        x,
        [overhead[k] for k in arms],
        bottom=[payload[k] for k in arms],
        color=HUES["vcoral"],
        label="重发/常数开销",
    )
    for i, k in enumerate(arms):
        total = payload[k] + overhead[k]
        a.text(i, total * 1.05, f"{total / 1e6:.2f}M", ha="center", fontsize=9)
    a.set_yscale("log")
    a.set_ylim(1e4, 3e7)
    a.set_xticks(list(x))
    a.set_xticklabels([LABELS[k] for k in arms])
    a.set_ylabel("新输入 token（对数轴）")
    a.set_title("A · 新输入组成", loc="left")
    a.legend(loc="upper left")
    cr = [DATA["_total"][k]["cache_read"] for k in arms]
    b.bar(x, cr, color=[COLORS[k] for k in arms])
    for i, v in enumerate(cr):
        b.text(i, v * 1.3, f"{v / 1e6:.2f}M" if v > 1e5 else f"{v:,}", ha="center", fontsize=9)
    b.set_yscale("log")
    b.set_ylim(500, 3e8)
    b.set_xticks(list(x))
    b.set_xticklabels([LABELS[k] for k in arms])
    b.set_ylabel("缓存读 token（对数轴）")
    b.set_title("B · 缓存读（前缀命中量）", loc="left")
    for ax in (a, b):
        ax.grid(axis="y", alpha=0.5)
        ax.set_axisbelow(True)
    fig.tight_layout()
    fig.savefig(HERE / "charts" / "input-composition.png", dpi=180)
    plt.close(fig)


def fig_ekg() -> None:
    fig, axes = plt.subplots(2, 1, figsize=(10, 4.8), sharex=False)
    spec = [
        ("agent", "agent 直翻 · 308 次调用"),
        ("current", "当前实现 · 74 次调用"),
    ]
    for ax, (key, title) in zip(axes, spec, strict=True):
        rows = EKG[key]
        for i, (inp, cr, _out) in enumerate(rows):
            if key == "agent":
                color = HUES["vorange"] if cr == 0 else HUES["vgold"]
            else:
                color = HUES["vteal"]
            ax.vlines(i, 1, inp, color=color, linewidth=1.1)
        ax.set_yscale("log")
        ax.set_ylim(1, 3e5)
        ax.set_title(title, loc="left", fontsize=10)
        ax.grid(axis="y", alpha=0.5)
        ax.set_axisbelow(True)
        ax.set_ylabel("单次新输入")
    axes[-1].set_xlabel("调用序号")
    from matplotlib.lines import Line2D

    axes[0].legend(
        handles=[
            Line2D([], [], color=HUES["vgold"], lw=2, label="增量（历史前缀命中缓存）"),
            Line2D([], [], color=HUES["vorange"], lw=2, label="全量重发（缓存失守）"),
        ],
        loc="upper right",
        fontsize=8,
    )
    fig.tight_layout()
    fig.savefig(HERE / "charts" / "ekg-19506.png", dpi=180)
    plt.close(fig)


if __name__ == "__main__":
    fig_per_paper()
    fig_composition()
    fig_ekg()
    print("charts written")
