# VLM 语义评审单 — arms-v5-projection.png

- figure: `/home/fanghaotian/src/texlate/docs/research/methods/agent-pipeline-baseline-2026-09-28/charts/arms-v5-projection.png`
- intent: `/home/fanghaotian/src/texlate/tmp/fig_v5_projection.py`（文本截取）
- backend: `claude`
- date: 2026-09-28
- 性质: advisory——本单结论不阻断交付、不进机器审计退出码

## 意图摘要

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

sys.path.insert(0, "/home/fanghaotian/.claude/skills/figure-viz/assets/mpl")
import fvstyle as fv
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

THEME = fv.apply_rc("paper")

PAPERS = ["19330", "19844", "20533", "19506", "20610", "19929", "20739", "20523", "19990", "20581"]

# —— 实测：网关 logs 窗（docs/research/methods/agent-pipeline-baseline-2026-09-28 §2）
AGENT_IN = [75070, 31808, 150840, 2376040, 117062, 987907, 178195, 434008, 316244, 81698]
V4_IN = [38336, 65213, 537040, 4265387, 43086, 215911, 262628, 179713, 129065, 245338]

# —— v5 推算输入件
USER = [35616, 46491, 95684, 346347, 43086, 48110, 68516, 93197, 62474, 63322]  # §4.4 载荷
N_MISS = [10, 13, 30, 37, 12, 19, 19, 32, 19, 32]                            # cr==0 调用数
DOC_PH = [112, 50, 1193, 7544, 148, 889, 1071, 161, 299, 656]                # 去重 ph id
CR_MAX = [272, 1536, 16896, 115200, 0, 12288, 15360, 3072, 4608, 9216]        # 观测 system
MANIFEST_CHARS = [708, 271, 113, 110, 440, 3210, 106, 1126, 1562, 3686]       # 真函数实测
HEAD_EST = [1500, 836, 600, 9584, 1500, 600, 600, 818, 600, 600]              # 非ph头部(未观测两篇给 1.5k)

MANIFEST_TOK = [c * 0.5 for c in MANIFEST_CHARS]
S_V5 = [h + m for h, m in zip(HEAD_EST, MANIFEST_TOK)]
V5_IN = [u + n * s for u, n, s in zip(USER, N_MISS, S_V5)]

# v4 system 常数（观测不到的两篇：ph表 + ~1.5k 头估）
S_V4 = [c if c > 0 else d * 14 + 1500 for c, d in zip(CR_MAX, DOC_PH)]
S_V4[0] = DOC_PH[0] * 14 + 1500  # 19330 仅 272 前言命中，非完整 S
UNOBSERVED = {0, 4}  # x 轴打 * 的篇

C_AGENT, C_V4, C_V5 = fv.HUES["vorange"], fv.HUES["vcoral"], fv.HUES["vteal"]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.6, 4.3))
x = np.arange(len(PAPERS))
w = 0.27

# ---------- panel A: 逐篇新输入 ----------
ax1.bar(x - w, AGENT_IN, w, color=C_AGENT, label="agent（实测）")
ax1.bar(x, V4_IN, w, color=C_V4, label="texlate v4（实测）")
ax1.bar(x + w, V5_IN, w, color=C_V5, hatch="//", edgecolor="white", linewidth=0, label="texlate v5（推算）")
ax1.set_yscale("log")
ax1.set_ylim(2e4, 8e6)
ax1.set_ylabel("新输入 token / 篇")
ax1.set_xlabel("arXiv 2609.xxxxx")
ax1.set_xticks(x)
ax1.set_xticklabels(PAPERS, rotation=45, ha="right", fontsize=7)
ax1.set_title("A · 逐篇新输入（payload + 重发）", loc="left", fontsize=9)
tot = f"Σ agent {sum(AGENT_IN)/1e6:.2f}M\nΣ v4    {sum(V4_IN)/1e6:.2f}M\nΣ v5   {sum(V5_IN)/1e6:.2f}M"
ax1.text(0.03, 0.97, tot, transform=ax1.transAxes, fontsize=7.5, va="top",
         bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=fv.NEUTRALS["vmist"], lw=0.7))
ax1.legend(fontsize=7.5, loc="upper right", framealpha=0.95)

# ---------- panel B: system 常数规模 ----------
xt = [p + ("*" if i in UNOBSERVED else "") for i, p in enumerate(PAPERS)]
w2 = 0.36
ax2.bar(x - w2 / 2, S_V4, w2, color=C_V4, label="v4 system（cr_max 实测）")
ax2.bar(x + w2 / 2, S_V5, w2, color=C_V5, hatch="//", edgecolor="white", linewidth=0, label="v5 system（推算）")
ax2.set_yscale("log")
ax2.set_ylim(2e2, 4e5)
ax2.set_ylabel("system prompt 常数 token")
ax2.set_xlabel("arXiv 2609.xxxxx（* = v4 无命中，按 ph表+头估）")
ax2.set_xticks(x)
ax2.set_xticklabels(xt, rotation=45, ha="right", fontsize=7)
ax2.set_title("B · doc 级常数：ph 恒等表 → 单行点名册", loc="left", fontsize=9)
ax2.annotate("115,200", xy=(3 - w2 / 2, S_V4[3]), xytext=(3.35, 2.2e5), fontsize=7,
             arrowprops=dict(arrowstyle="-", lw=0.6, color=fv.NEUTRALS["vink"]))
ax2.annotate("≈9.6k\n(manifest 110c)", xy=(3 + w2 / 2, S_V5[3]), xytext=(4.3, 2e4), fontsize=7,
             arrowprops=dict(arrowstyle="-", lw=0.6, color=fv.NEUTRALS["vink"]))
ax2.legend(fontsize=7.5, loc="upper left", framealpha=0.95)

fig.text(0.5, 0.012, "柱状 = 每篇新输入/system 常数｜agent·v4 为网关实测，v5̂ 为同 miss 谱推算（manifest 真函数算得）｜texlate 双臂基线 2026-09-28",
         ha="center", fontsize=7, color=fv.NEUTRALS["baseline"])
fig.tight_layout(rect=[0, 0.045, 1, 1])

problems = fv.audit(fig)
for p in problems:
    print("audit:", p)
out = Path("docs/research/methods/agent-pipeline-baseline-2026-09-28/charts/arms-v5-projection.png")
fig.savefig(out, dpi=220, bbox_inches="tight")
print("wrote", out)

## Checklist

### 1. 主张—数据一致性

判定：____（PASS / CONCERN / FAIL）　证据：____

- [ ] 顶部主张、标题与含义框里的每条断言，是否都有曲线/形状/数值上的直接证据？
- [ ] 有没有主张断言的趋势、大小或因果，在绘制内容里找不到支撑，甚至与证据相反？
- [ ] 数据里显眼的现象（交叉、反转、异常点、平台期）是否都被主张或标注解释，而不是被回避？
- [ ] 示意性简化（单元格数≠真实维度、截断轴、省略分片）是否只声明一次、且不会被误读为真实量？

### 2. 标签可读性

判定：____（PASS / CONCERN / FAIL）　证据：____

- [ ] 全部文字在交付尺寸下是否可读：字号、对比度足够，无裁切、截断或溢出边框？
- [ ] 每个符号、缩写与记号是否在使用处或含义框中定义？有无未解释的孤立记号？
- [ ] 数学排版是否正常（无豆腐块、无缺字形）？旋转/竖排文字是否确有必要？

### 3. 编码通道可辨识度

判定：____（PASS / CONCERN / FAIL）　证据：____

- [ ] 同时出现的色相是否两两可辨（含明度相近色对与色盲安全）？
- [ ] 颜色即语义是否成立：同一色相全图同一含义，换含义才换色相，明度只表幅度？
- [ ] 第二通道（线型/marker/明度层级/纹理）与其声称的类别或幅度是否单调对应？
- [ ] 活跃色相族数是否在预算内（≤4 族 + 中性灰），超出是否有显式声明？

### 4. 阅读顺序

判定：____（PASS / CONCERN / FAIL）　证据：____

- [ ] 视觉动线是否按论证顺序推进（主张→结构/数据→结论），而非让视线来回跳？
- [ ] 连接器方向与语义流向是否一致；反馈回路、分支合流是否一眼可辨？
- [ ] 多面板/多阶段图的默认阅读顺序（行优先/列优先/编号）是否显然？

### 5. 未埋点碰撞风险

判定：____（PASS / CONCERN / FAIL）　证据：____

- [ ] 是否有未进审计的文字/标签压在线上、框上或其他文字上（机器审计只覆盖埋点对象）？
- [ ] 画布边缘是否有被裁掉半个的元素？连接线是否擦过非端点对象？
- [ ] 白衬底标签是否盖住了不该盖的连线或数据？

### 6. 图—caption 一致性

判定：____（PASS / CONCERN / FAIL）　证据：____

- [ ] 底部含义框/标识行描述的是否恰是实际画出的对象，不多不少？
- [ ] 若 intent 给了正文 caption 或台账：图内文字与之是否互相印证，而非各说各话？
- [ ] 标识行是否泄露了图里没有的信息，或漏掉了图中实际存在的关键对象？

## 总判

____（PASS = 全部条目通过；CONCERN = 有疑点需人工复核；FAIL = 主张与图面冲突或可读性失守，拒收重画）

最优先修改建议：____

## 附：可复制的 VLM 提示词

把下面整段连同图片一起喂给任意 VLM（或 `--backend claude` 自动调用）：

```text
你是研究图的语义评审。评审所附图片：只按图面与所给意图判断，
不臆测未给出的数据，不复核几何像素级对齐（那是机器审计的活）。
逐条判定：每项给 PASS / CONCERN / FAIL 加一行证据（指出图中具体
位置），最后给总判（PASS / CONCERN / FAIL）与一句最优先的修改建议。

评审对象图片：/home/fanghaotian/src/texlate/docs/research/methods/agent-pipeline-baseline-2026-09-28/charts/arms-v5-projection.png

## 作者声明的意图
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

sys.path.insert(0, "/home/fanghaotian/.claude/skills/figure-viz/assets/mpl")
import fvstyle as fv
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

THEME = fv.apply_rc("paper")

PAPERS = ["19330", "19844", "20533", "19506", "20610", "19929", "20739", "20523", "19990", "20581"]

# —— 实测：网关 logs 窗（docs/research/methods/agent-pipeline-baseline-2026-09-28 §2）
AGENT_IN = [75070, 31808, 150840, 2376040, 117062, 987907, 178195, 434008, 316244, 81698]
V4_IN = [38336, 65213, 537040, 4265387, 43086, 215911, 262628, 179713, 129065, 245338]

# —— v5 推算输入件
USER = [35616, 46491, 95684, 346347, 43086, 48110, 68516, 93197, 62474, 63322]  # §4.4 载荷
N_MISS = [10, 13, 30, 37, 12, 19, 19, 32, 19, 32]                            # cr==0 调用数
DOC_PH = [112, 50, 1193, 7544, 148, 889, 1071, 161, 299, 656]                # 去重 ph id
CR_MAX = [272, 1536, 16896, 115200, 0, 12288, 15360, 3072, 4608, 9216]        # 观测 system
MANIFEST_CHARS = [708, 271, 113, 110, 440, 3210, 106, 1126, 1562, 3686]       # 真函数实测
HEAD_EST = [1500, 836, 600, 9584, 1500, 600, 600, 818, 600, 600]              # 非ph头部(未观测两篇给 1.5k)

MANIFEST_TOK = [c * 0.5 for c in MANIFEST_CHARS]
S_V5 = [h + m for h, m in zip(HEAD_EST, MANIFEST_TOK)]
V5_IN = [u + n * s for u, n, s in zip(USER, N_MISS, S_V5)]

# v4 system 常数（观测不到的两篇：ph表 + ~1.5k 头估）
S_V4 = [c if c > 0 else d * 14 + 1500 for c, d in zip(CR_MAX, DOC_PH)]
S_V4[0] = DOC_PH[0] * 14 + 1500  # 19330 仅 272 前言命中，非完整 S
UNOBSERVED = {0, 4}  # x 轴打 * 的篇

C_AGENT, C_V4, C_V5 = fv.HUES["vorange"], fv.HUES["vcoral"], fv.HUES["vteal"]

fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.6, 4.3))
x = np.arange(len(PAPERS))
w = 0.27

# ---------- panel A: 逐篇新输入 ----------
ax1.bar(x - w, AGENT_IN, w, color=C_AGENT, label="agent（实测）")
ax1.bar(x, V4_IN, w, color=C_V4, label="texlate v4（实测）")
ax1.bar(x + w, V5_IN, w, color=C_V5, hatch="//", edgecolor="white", linewidth=0, label="texlate v5（推算）")
ax1.set_yscale("log")
ax1.set_ylim(2e4, 8e6)
ax1.set_ylabel("新输入 token / 篇")
ax1.set_xlabel("arXiv 2609.xxxxx")
ax1.set_xticks(x)
ax1.set_xticklabels(PAPERS, rotation=45, ha="right", fontsize=7)
ax1.set_title("A · 逐篇新输入（payload + 重发）", loc="left", fontsize=9)
tot = f"Σ agent {sum(AGENT_IN)/1e6:.2f}M\nΣ v4    {sum(V4_IN)/1e6:.2f}M\nΣ v5   {sum(V5_IN)/1e6:.2f}M"
ax1.text(0.03, 0.97, tot, transform=ax1.transAxes, fontsize=7.5, va="top",
         bbox=dict(boxstyle="round,pad=0.35", fc="white", ec=fv.NEUTRALS["vmist"], lw=0.7))
ax1.legend(fontsize=7.5, loc="upper right", framealpha=0.95)

# ---------- panel B: system 常数规模 ----------
xt = [p + ("*" if i in UNOBSERVED else "") for i, p in enumerate(PAPERS)]
w2 = 0.36
ax2.bar(x - w2 / 2, S_V4, w2, color=C_V4, label="v4 system（cr_max 实测）")
ax2.bar(x + w2 / 2, S_V5, w2, color=C_V5, hatch="//", edgecolor="white", linewidth=0, label="v5 system（推算）")
ax2.set_yscale("log")
ax2.set_ylim(2e2, 4e5)
ax2.set_ylabel("system prompt 常数 token")
ax2.set_xlabel("arXiv 2609.xxxxx（* = v4 无命中，按 ph表+头估）")
ax2.set_xticks(x)
ax2.set_xticklabels(xt, rotation=45, ha="right", fontsize=7)
ax2.set_title("B · doc 级常数：ph 恒等表 → 单行点名册", loc="left", fontsize=9)
ax2.annotate("115,200", xy=(3 - w2 / 2, S_V4[3]), xytext=(3.35, 2.2e5), fontsize=7,
             arrowprops=dict(arrowstyle="-", lw=0.6, color=fv.NEUTRALS["vink"]))
ax2.annotate("≈9.6k\n(manifest 110c)", xy=(3 + w2 / 2, S_V5[3]), xytext=(4.3, 2e4), fontsize=7,
             arrowprops=dict(arrowstyle="-", lw=0.6, color=fv.NEUTRALS["vink"]))
ax2.legend(fontsize=7.5, loc="upper left", framealpha=0.95)

fig.text(0.5, 0.012, "柱状 = 每篇新输入/system 常数｜agent·v4 为网关实测，v5̂ 为同 miss 谱推算（manifest 真函数算得）｜texlate 双臂基线 2026-09-28",
         ha="center", fontsize=7, color=fv.NEUTRALS["baseline"])
fig.tight_layout(rect=[0, 0.045, 1, 1])

problems = fv.audit(fig)
for p in problems:
    print("audit:", p)
out = Path("docs/research/methods/agent-pipeline-baseline-2026-09-28/charts/arms-v5-projection.png")
fig.savefig(out, dpi=220, bbox_inches="tight")
print("wrote", out)

## Checklist
1. 主张—数据一致性
   - 顶部主张、标题与含义框里的每条断言，是否都有曲线/形状/数值上的直接证据？
   - 有没有主张断言的趋势、大小或因果，在绘制内容里找不到支撑，甚至与证据相反？
   - 数据里显眼的现象（交叉、反转、异常点、平台期）是否都被主张或标注解释，而不是被回避？
   - 示意性简化（单元格数≠真实维度、截断轴、省略分片）是否只声明一次、且不会被误读为真实量？
2. 标签可读性
   - 全部文字在交付尺寸下是否可读：字号、对比度足够，无裁切、截断或溢出边框？
   - 每个符号、缩写与记号是否在使用处或含义框中定义？有无未解释的孤立记号？
   - 数学排版是否正常（无豆腐块、无缺字形）？旋转/竖排文字是否确有必要？
3. 编码通道可辨识度
   - 同时出现的色相是否两两可辨（含明度相近色对与色盲安全）？
   - 颜色即语义是否成立：同一色相全图同一含义，换含义才换色相，明度只表幅度？
   - 第二通道（线型/marker/明度层级/纹理）与其声称的类别或幅度是否单调对应？
   - 活跃色相族数是否在预算内（≤4 族 + 中性灰），超出是否有显式声明？
4. 阅读顺序
   - 视觉动线是否按论证顺序推进（主张→结构/数据→结论），而非让视线来回跳？
   - 连接器方向与语义流向是否一致；反馈回路、分支合流是否一眼可辨？
   - 多面板/多阶段图的默认阅读顺序（行优先/列优先/编号）是否显然？
5. 未埋点碰撞风险
   - 是否有未进审计的文字/标签压在线上、框上或其他文字上（机器审计只覆盖埋点对象）？
   - 画布边缘是否有被裁掉半个的元素？连接线是否擦过非端点对象？
   - 白衬底标签是否盖住了不该盖的连线或数据？
6. 图—caption 一致性
   - 底部含义框/标识行描述的是否恰是实际画出的对象，不多不少？
   - 若 intent 给了正文 caption 或台账：图内文字与之是否互相印证，而非各说各话？
   - 标识行是否泄露了图里没有的信息，或漏掉了图中实际存在的关键对象？

总判口径：PASS = 全部条目通过；CONCERN = 有疑点需人工复核；FAIL = 主张与图面冲突或可读性失守，拒收重画。
```

## VLM 回复

已看图，并复核了脚本推算：V5_IN、S_V5、S_V4 逐项重算与柱高一致（Σ 4.75/5.98/1.53M、19506 的 115,200 与 ≈9.6k 注记均核对无误）。

**1. 主张—数据一致性：CONCERN**
19330 与 20610 两篇 v5̂ 柱反高于 v4 实测（约 5.4e4>3.8e4、6.4e4>4.3e4），是全图唯二"推算更贵"的反转，图面无任何解释；尤其 20610 的 v4 实测 43,086 恰好等于其 user payload 本身，属可疑数据点（v4 该篇疑似无可观测重发），照搬 miss 谱后 v5̂ 必然虚高。

**2. 标签可读性：PASS**
交付尺寸下全部文字清晰；`*` 在 panel B 轴标签内定义；`(manifest 110c)` 偏隐晦但可解读。

**3. 编码通道：PASS**
三色相族 + 中性灰在预算内；v5 一律 teal+`//` hatch 跨两面板语义一致；vorange 琥珀与 vcoral 砖红两两可辨。

**4. 阅读顺序：PASS**
A→B 编号左起，先逐篇量级后常数拆解，动线符合论证。

**5. 未埋点碰撞：PASS**
Σ 框、115,200 与 ≈9.6k 注记均落空白区，箭头未穿非端点柱；≈9.6k 文字与 19929 红柱顶留可见间隙。

**6. 图—caption 一致性：CONCERN**
脚注 "texlate **双臂**基线" 与图面三臂并列措辞相悖（应指 v4/v5 两 texlate 臂，但字面易误读）；panel B 图例 "cr_max 实测" 实际覆盖 19330\*/20610\* 两根估值柱（有 `*+轴注` 兜底，属弱披露）。

**总判：CONCERN**

最优先修改：在 panel A 给 19330/20610 加一条注记（或脚注一句话）说明"v4 该两篇输入≈裸 payload、无命中可观测，v5̂ 按照搬 miss 谱故反高"——否则"V5 全面省 token"的读感会被这两根反转柱当场质疑。

## 产物

- 评审单: `/home/fanghaotian/src/texlate/docs/research/methods/agent-pipeline-baseline-2026-09-28/charts/arms-v5-projection.vlm-judge.md`
- 评审对象: `/home/fanghaotian/src/texlate/docs/research/methods/agent-pipeline-baseline-2026-09-28/charts/arms-v5-projection.png`
- intent: `/home/fanghaotian/src/texlate/tmp/fig_v5_projection.py`
