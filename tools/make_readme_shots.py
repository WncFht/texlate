"""README shots 数据图再生——bench-token.png / bench-e2e.png。

几何台账：
- bench-token.png A 面：x=论文序（10 篇 2609.*），y=新输入 token（log，
  柱底贴轴下限 1e4）；两系列=agent 直翻 / 当前管线。B 面：x=指标
  （新输入/总输入/输出），y=token（log，柱底贴 500）；柱顶标绝对值与
  管线/agent 比。
- bench-e2e.png：y=测试集（通用 200 / 新 CS 200），x=篇数 0–200 堆叠
  终态分解（编译即交付 / fixloop 救回 / 修不了 / 上游链断）；行内点线
  tick=原文直编对照交付数。

语义台账：方=实现路线（agent/管线二系一色到底）；终态类=交付归因
（teal 直接交付、gold 修复救回、coral 修不了、mist 上游死）。数据源自
docs/research/methods/token-economy-2026-10-03/data/per-paper-tokens.json
与 e2e 两篇冻帧文档的逐篇交付账。

运行：uv run --with matplotlib python tools/make_readme_shots.py
"""

import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt

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

fv.apply_rc("paper")

DATA = json.loads(
    (_ROOT / "docs/research/methods/token-economy-2026-10-03/data/per-paper-tokens.json").read_text()
)
OUT = _ROOT / "shots"

C_AGENT = "#EE995B"
C_PIPE = "#4F8FA5"


def fig_token() -> None:
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.0, 3.5), width_ratios=[1.55, 1])
    papers = DATA["paper"]
    x = list(range(len(papers)))
    w = 0.38
    a.bar(
        [t - w / 2 for t in x],
        [DATA["agent"][p]["input"] for p in papers],
        width=w,
        bottom=1e4,
        color=C_AGENT,
        label="agent 整篇直翻",
    )
    a.bar(
        [t + w / 2 for t in x],
        [DATA["current"][p]["input"] for p in papers],
        width=w,
        bottom=1e4,
        color=C_PIPE,
        label="texlate 管线",
    )
    a.set_yscale("log")
    a.set_ylim(1e4, 8e6)
    a.set_xticks(x)
    a.set_xticklabels([p.split(".")[1] for p in papers], fontsize=8)
    a.set_xlabel("arXiv 2609.xxxxx")
    a.set_ylabel("新输入 token（对数轴）")
    a.set_title("A · 逐篇新输入", loc="left")
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
    b.bar([t - w / 2 for t in bx], agent_v, width=w, bottom=500, color=C_AGENT)
    b.bar([t + w / 2 for t in bx], cur_v, width=w, bottom=500, color=C_PIPE)
    for i, (av, cv, r) in enumerate(zip(agent_v, cur_v, ratio)):
        b.text(i - w / 2, av * 1.3, f"{av / 1e6:.1f}M", ha="center", fontsize=8.5)
        lab = f"{cv / 1e6:.2f}M" if cv > 1e5 else f"{cv / 1e3:.1f}k"
        b.text(i + w / 2, cv * 1.3, f"{lab}\n{r}", ha="center", fontsize=8.5)
    b.set_yscale("log")
    b.set_ylim(500, 5e8)
    b.set_xticks(bx)
    b.set_xticklabels(metrics, fontsize=9)
    b.set_title("B · 总量（10 篇合计）", loc="left")
    for ax in (a, b):
        ax.grid(axis="y", alpha=0.5)
        ax.set_axisbelow(True)
    fig.text(
        0.5,
        0.015,
        "texlate 管线 vs agent 整篇直翻 · 同 10 篇 · 同模型 swe-2-medium · 网关逐请求账本（2026-09/10）",
        ha="center",
        fontsize=8,
        color="#85898F",
    )
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    problems = fv.audit(fig, ignore=["facet-ylim-mismatch"])
    for p in problems:
        print("token audit:", p)
    fig.savefig(OUT / "bench-token.png", dpi=170)
    plt.close(fig)


def fig_e2e() -> None:
    rows = [
        ("通用留出 200 篇", 129, 42, 3, 26, 152, "85.5%"),
        ("新 CS 200 篇", 141, 50, 1, 8, 192, "95.5%"),
    ]
    cats = ["编译即交付", "fixloop 修复救回", "修不了", "上游链断"]
    colors = ["#4F8FA5", "#D9A93C", "#C95B5B", "#D8DBDE"]
    fig, ax = plt.subplots(figsize=(8.4, 2.6))
    y = [0, 1]
    h = 0.52
    for ci, (cat, color) in enumerate(zip(cats, colors)):
        widths = [r[1 + ci] for r in rows]
        lefts = [sum(r[1 : 1 + ci]) for r in rows]
        ax.barh(y, widths, left=lefts, height=h, color=color, label=cat)
    for yi, (_name, direct, rescued, _unfix, _up, bare, pct) in zip(y, rows):
        delivered = direct + rescued
        ax.text(203, yi, f"{delivered}/200 · {pct}", va="center", fontsize=10)
        ax.vlines(bare, yi - h / 2 - 0.09, yi + h / 2 + 0.09,
                  color="#3A3F45", linewidth=1.4, linestyles=":")
        ax.text(bare, yi - h / 2 - 0.22, str(bare), ha="center", fontsize=8, color="#3A3F45")
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], fontsize=10)
    ax.set_xlim(0, 246)
    ax.set_ylim(-0.62, 1.62)
    ax.set_xlabel("论文篇数")
    ax.grid(axis="x", alpha=0.5)
    ax.set_axisbelow(True)
    handles = [plt.Rectangle((0, 0), 1, 1, color=c) for c in colors]
    handles.append(plt.Line2D([], [], color="#3A3F45", linestyle=":", linewidth=1.4))
    ax.legend(
        handles,
        [*cats, "原文直编交付数"],
        loc="upper center",
        bbox_to_anchor=(0.5, 1.14),
        fontsize=8,
        ncol=5,
        columnspacing=1.0,
        handlelength=1.2,
    )
    fig.text(
        0.5,
        0.02,
        "e2e_eval 留出测试集逐篇终态分解（2026-10-02/03 口径）· 译文可交付 = 编译即交付 + fixloop 救回",
        ha="center",
        fontsize=8,
        color="#85898F",
    )
    fig.tight_layout(rect=[0, 0.09, 1, 1])
    problems = fv.audit(fig)
    for p in problems:
        print("e2e audit:", p)
    fig.savefig(OUT / "bench-e2e.png", dpi=170)
    plt.close(fig)


if __name__ == "__main__":
    fig_token()
    fig_e2e()
    print("shots written")
