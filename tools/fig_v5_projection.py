"""三臂新输入对比图：agent / texlate v4 实测 vs v5 推算（2026-09-28 基线）。

语义台账：
- 柱 = 一篇论文一臂的「新输入 token」(gateway logs input_tokens)。
  agent/v4 = 实测；v5̂ = 推算 = 同 user 源文 + 同 miss 调用数 × S_v5
  （S_v5 = 非ph头部 + manifest tok，manifest 由真函数 collect_doc_placeholders
  + render_placeholder_manifest 在任务 chunks 上算得；miss 谱按 v4 观测照搬）。
- panel B 柱 = 每篇 system prompt 常数规模：v4 取 cr_max（19330/20610 无命中
  不可观测，用 ph表+~1.5k 头估，x 轴打 *）；v5̂ 同上。
- 色相：agent=vorange、v4=vcoral、v5=vteal；v5 一律 // hatch 标「推算」。
"""
# ruff: noqa: E402

import sys
from pathlib import Path

import _env  # noqa: F401 -- 仓根锚（产物路径）

sys.path.insert(0, str(Path.home() / ".claude/skills/figure-viz/assets/mpl"))
import fvstyle as fv
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

THEME = fv.apply_rc("paper")

PAPERS = [
    "19330",
    "19844",
    "20533",
    "19506",
    "20610",
    "19929",
    "20739",
    "20523",
    "19990",
    "20581",
]

# —— 实测：网关 logs 窗（docs/research/methods/agent-pipeline-baseline-2026-09-28 §2）
AGENT_IN = [
    75070,
    31808,
    150840,
    2376040,
    117062,
    987907,
    178195,
    434008,
    316244,
    81698,
]
V4_IN = [38336, 65213, 537040, 4265387, 43086, 215911, 262628, 179713, 129065, 245338]

# —— v5 推算输入件
USER = [
    35616,
    46491,
    95684,
    346347,
    43086,
    48110,
    68516,
    93197,
    62474,
    63322,
]  # §4.4 载荷
N_MISS = [10, 13, 30, 37, 12, 19, 19, 32, 19, 32]  # cr==0 调用数
DOC_PH = [112, 50, 1193, 7544, 148, 889, 1071, 161, 299, 656]  # 去重 ph id
CR_MAX = [272, 1536, 16896, 115200, 0, 12288, 15360, 3072, 4608, 9216]  # 观测 system
MANIFEST_CHARS = [708, 271, 113, 110, 440, 3210, 106, 1126, 1562, 3686]  # 真函数实测
HEAD_EST = [
    1500,
    836,
    600,
    9584,
    1500,
    600,
    600,
    818,
    600,
    600,
]  # 非ph头部(未观测两篇给 1.5k)

MANIFEST_TOK = [c * 0.5 for c in MANIFEST_CHARS]
S_V5 = [h + m for h, m in zip(HEAD_EST, MANIFEST_TOK, strict=True)]
V5_IN = [u + n * s for u, n, s in zip(USER, N_MISS, S_V5, strict=True)]

# v4 system 常数（观测不到的两篇：ph表 + ~1.5k 头估）
S_V4 = [c if c > 0 else d * 14 + 1500 for c, d in zip(CR_MAX, DOC_PH, strict=True)]
S_V4[0] = DOC_PH[0] * 14 + 1500  # 19330 仅 272 前言命中，非完整 S
UNOBSERVED = {0, 4}  # x 轴打 * 的篇

C_AGENT, C_V4, C_V5 = fv.HUES["vorange"], fv.HUES["vcoral"], fv.HUES["vteal"]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.6, 4.3))
x = np.arange(len(PAPERS))
xt = [p + ("*" if i in UNOBSERVED else "") for i, p in enumerate(PAPERS)]
w = 0.27

# ---------- panel A: 逐篇新输入 ----------
ax1.bar(x - w, AGENT_IN, w, color=C_AGENT, label="agent（实测）")
ax1.bar(x, V4_IN, w, color=C_V4, label="texlate v4（实测）")
ax1.bar(
    x + w,
    V5_IN,
    w,
    color=C_V5,
    hatch="//",
    edgecolor="white",
    linewidth=0,
    label="texlate v5（推算）",
)
ax1.set_yscale("log")
ax1.set_ylim(2e4, 8e6)
ax1.set_ylabel("新输入 token / 篇")
ax1.set_xlabel("arXiv 2609.xxxxx")
ax1.set_xticks(x)
ax1.set_xticklabels(xt, rotation=45, ha="right", fontsize=7)
ax1.set_title("A · 逐篇新输入（payload + 重发）", loc="left", fontsize=9)
tot = f"Σ agent {sum(AGENT_IN) / 1e6:.2f}M\nΣ v4    {sum(V4_IN) / 1e6:.2f}M\nΣ v5   {sum(V5_IN) / 1e6:.2f}M"
ax1.text(
    0.03,
    0.97,
    tot,
    transform=ax1.transAxes,
    fontsize=7.5,
    va="top",
    bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=fv.NEUTRALS["vmist"], lw=0.7),
)
ax1.legend(fontsize=7.5, loc="upper right", framealpha=0.95)
ax1.text(
    0.03,
    0.70,
    "* 两篇 v4 实测≈裸载荷（重发面近乎零），\nmiss 谱照搬使 v5 推算柱偏高——读作上界",
    transform=ax1.transAxes,
    fontsize=6.5,
    va="top",
    color=fv.NEUTRALS["vink"],
)

# ---------- panel B: system 常数规模 ----------
w2 = 0.36
ax2.bar(x - w2 / 2, S_V4, w2, color=C_V4, label="v4 system（cr_max 实测）")
ax2.bar(
    x + w2 / 2,
    S_V5,
    w2,
    color=C_V5,
    hatch="//",
    edgecolor="white",
    linewidth=0,
    label="v5 system（推算）",
)
ax2.set_yscale("log")
ax2.set_ylim(2e2, 4e5)
ax2.set_ylabel("system prompt 常数 token")
ax2.set_xlabel("arXiv 2609.xxxxx（* = v4 无命中，按 ph表+头估）")
ax2.set_xticks(x)
ax2.set_xticklabels(xt, rotation=45, ha="right", fontsize=7)
ax2.set_title("B · doc 级常数：ph 恒等表 → 单行点名册", loc="left", fontsize=9)
ax2.annotate(
    "115,200",
    xy=(3 - w2 / 2, S_V4[3]),
    xytext=(3.35, 2.2e5),
    fontsize=7,
    arrowprops=dict(arrowstyle="-", lw=0.6, color=fv.NEUTRALS["vink"]),
)
ax2.annotate(
    "≈9.6k\n(manifest 110c)",
    xy=(3 + w2 / 2, S_V5[3]),
    xytext=(4.3, 2e4),
    fontsize=7,
    arrowprops=dict(arrowstyle="-", lw=0.6, color=fv.NEUTRALS["vink"]),
)
ax2.legend(fontsize=7.5, loc="upper left", framealpha=0.95)

fig.text(
    0.5,
    0.012,
    "柱状 = 每篇新输入/system 常数｜agent·v4 为网关实测，v5 为同 miss 谱推算（manifest 真函数算得）｜三臂对比 2026-09-28",
    ha="center",
    fontsize=7,
    color=fv.NEUTRALS["baseline"],
)
fig.tight_layout(rect=[0, 0.045, 1, 1])

problems = fv.audit(fig)
for p in problems:
    print("audit:", p)
out = (
    _env.REPO
    / "docs/research/methods/agent-pipeline-baseline-2026-09-28/charts/arms-v5-projection.png"
)
fig.savefig(out, dpi=220, bbox_inches="tight")
print("wrote", out)
