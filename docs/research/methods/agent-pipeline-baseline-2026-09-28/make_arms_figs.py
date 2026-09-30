"""三臂实测图组：agent / texlate v4 / texlate v5（2026-09-28 基线 + v5 夜跑）。

语义台账：
- 图 1 arms-input-tokens.png: 柱=逐篇新输入 token（网关 input_tokens 窗Σ）。
  三臂同模型同网关同时段；v5 窗=server key 268cd（与 task_usage 逐字节核平）。
- 图 2 arms-request-ekg.png: 19506 逐调用「心电图」——x=调用序，y=单次 in(log)；
  v4 条带按 miss(vcoral)/hit(vteal) 分色，agent=vorange、v5=vteal 单臂色。
  语义：一次 API 调用的全价新输入；v4 的 122k 尖刺=ph 恒等表全价重发。
- 图 3 arms-v5-validation.png: v5 推算柱 (//hatch) vs 实测柱 逐篇对照；
  验证「载荷+miss×S_v5」记账模型（推算常数见 make_arms_v5_projection_fig 注释源）。
- 图 4 arms-quality.png: 残英 eff 行 + ngram 退化分两面板；x 轴带终态标。
色相：agent=vorange, v4=vcoral, v5=vteal（全图组一致）。

数据源（同目录归档件优先；缺件且给 --gw-db 时回退现场查询）：
  baseline-tokens.json                agent/v4 逐篇聚合（input/output/calls）
  v5-ledger.json + v5-arm-wins.json   v5 逐篇聚合 + 窗口（epoch 起止 + status/secs）
  arms-ekg-rows.json                  图 2 三臂逐调用行（2609.19506，[in,cr,out]）
  qc-results-v5.json                  图 4 v5 质量闸指标（残英 eff / ngram 退化）
  qc-results-v4-agent.json            图 4 v4/agent 质量闸指标（键 2609.xxxxx/arm）
  --gw-db PATH                        内部 OpenAI 兼容网关 logs 表（sqlite 只读）
                                      回退路：v5 聚合走窗Σ、ekg 走原窗查询；
                                      v4/v5 臂须各给 --v4-key-hash/--v5-key-hash

运行（本目录内；仓 .venv 无 matplotlib，numpy 由 matplotlib 传递带入）：
  uv run --with matplotlib python make_arms_figs.py [--gw-db PATH ...]
产物写 charts/*.png，与已提交图语义一致（字节随 mpl/字体版本漂移）。
"""

import argparse
import json
import sqlite3
import statistics as st
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import _figstyle as fv
import matplotlib.pyplot as plt
import numpy as np

fv.apply_rc("paper")

DIR = Path(__file__).resolve().parent
CH = DIR / "charts"
BASE = 1790553600  # 2026-09-28 00:00 UTC
C_AGENT, C_V4, C_V5 = fv.HUES["vorange"], fv.HUES["vcoral"], fv.HUES["vteal"]

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

AGENT_WINS = {
    "2609.19330": ("17:13:13", "17:16:18"),
    "2609.19844": ("17:16:18", "17:21:16"),
    "2609.20533": ("17:21:16", "17:34:37"),
    "2609.19506": ("17:34:37", "18:01:30"),
    "2609.19929": ("18:01:30", "18:48:18"),
    "2609.20739": ("18:48:18", "18:54:30"),
    "2609.20523": ("18:54:30", "19:08:53"),
    "2609.19990": ("19:08:53", "19:22:24"),
    "2609.20581": ("19:22:24", "19:35:21"),
    "2609.20610": ("16:30:00", "17:11:00"),
}
V4_WINS = {
    "2609.19330": ("17:14:44", "17:17:04"),
    "2609.19844": ("17:17:04", "17:21:05"),
    "2609.20533": ("17:21:05", "17:25:05"),
    "2609.19506": ("17:25:05", "17:35:05"),
    "2609.20610": ("17:35:05", "17:36:46"),
    "2609.19929": ("17:36:46", "17:39:46"),
    "2609.20739": ("17:39:46", "17:45:26"),
    "2609.20523": ("17:45:26", "17:59:07"),
    "2609.19990": ("17:59:07", "18:01:47"),
    "2609.20581": ("18:01:47", "18:21:28"),
}

# v5 推算值（make_arms_v5_projection_fig.py 同口径常数）
V5_PROJ = dict(
    zip(
        PAPERS,
        [
            35616 + 10 * (1500 + 354),
            46491 + 13 * (836 + 136),
            95684 + 30 * (600 + 57),
            346347 + 37 * (9584 + 55),
            43086 + 12 * (1500 + 220),
            48110 + 19 * (600 + 1605),
            68516 + 19 * (600 + 53),
            93197 + 32 * (818 + 563),
            62474 + 19 * (600 + 781),
            63322 + 32 * (600 + 1843),
        ],
    )
)


def ms(hms: str) -> int:
    h, m, s = map(int, hms.split(":"))
    return (BASE + h * 3600 + m * 60 + s - 8 * 3600) * 1000


def gw_rows(db, api, key, t0, t1):
    q = (
        "select input_tokens, cache_read_tokens, output_tokens from logs"
        " where api=? and time>=? and time<=?"
    )
    a = [api, ms(t0), ms(t1)]
    if key:
        q = q.replace("where api", "where key_hash=? and api")
        a = [key, api, ms(t0), ms(t1)]
    return db.execute(q, a).fetchall()


def v5_rows(db, key, w):
    """v5 臂逐调用行：arm-wins 窗 + key_hash 过滤；epoch 直取防跨零点。"""
    t0_ms = int(w["t0"] * 1000) if w.get("t0") else ms(w["t0_hms"])
    t1_ms = int(w["t1"] * 1000) if w.get("t1") else ms(w["t1_hms"])
    if t1_ms < t0_ms:
        t1_ms += 86400_000
    return db.execute(
        "select input_tokens, cache_read_tokens, output_tokens from logs"
        " where api='openai-chat' and key_hash=? and time>=? and time<=?",
        (key, t0_ms, t1_ms),
    ).fetchall()


def load_arch(name):
    """同目录归档 JSON；缺件返回 None（调用方决定回退或报错）。"""
    p = DIR / name
    return json.loads(p.read_text()) if p.is_file() else None


def need_arch(name):
    """必备归档件；缺件即死并点名（归档集随脚本同目录分发）。"""
    v = load_arch(name)
    if v is None:
        sys.exit(f"缺归档数据件 {name}（应与脚本同目录；数据源清单见模块 docstring）")
    return v


def parse_args(argv=None):
    ap = argparse.ArgumentParser(description="三臂实测图组再生（口径见模块 docstring）")
    ap.add_argument(
        "--gw-db",
        metavar="PATH",
        help="内部 OpenAI 兼容网关 logs 库（sqlite，只读打开）；不给则全走归档 JSON",
    )
    ap.add_argument(
        "--v4-key-hash", metavar="HEX", help="v4 臂 key_hash（--gw-db 路需要）"
    )
    ap.add_argument(
        "--v5-key-hash", metavar="HEX", help="v5 臂 key_hash（--gw-db 路需要）"
    )
    return ap.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    gw = sqlite3.connect(f"file:{args.gw_db}?mode=ro", uri=True) if args.gw_db else None
    CH.mkdir(exist_ok=True)
    wrote = []

    bt = need_arch("baseline-tokens.json")
    wins = need_arch("v5-arm-wins.json")
    qc = need_arch("qc-results-v5.json")
    qc4 = need_arch("qc-results-v4-agent.json")

    # ---------- v5 实测（归档 ledger 优先；缺件回退网关窗Σ + 对账） ----------
    led = load_arch("v5-ledger.json")
    if led is None:
        if gw is None:
            sys.exit("v5 聚合无源：缺 v5-ledger.json 且未给 --gw-db")
        if not args.v5_key_hash:
            sys.exit("v5 走 --gw-db 窗Σ须给 --v5-key-hash")
    v5 = {}
    for pid_raw, w in wins.items():
        p = pid_raw.replace("2609.", "").split("v")[0]
        if led is not None:
            e = led[f"2609.{p}"]
            v5[p] = {
                "calls": e["calls"],
                "in": e["input"],
                "cr": e["cache_read"],
                "out": e["output"],
                "in_p50": e["in_p50"],
                "in_max": e["in_max"],
                "status": w.get("status"),
                "secs": w.get("secs"),
            }
        else:
            rows = v5_rows(gw, args.v5_key_hash, w)
            ins = [r[0] for r in rows]
            crs = [r[1] for r in rows]
            v5[p] = {
                "calls": len(rows),
                "in": sum(ins),
                "cr": sum(crs),
                "out": sum(r[2] for r in rows),
                "in_p50": st.median(ins) if ins else 0,
                "in_max": max(ins) if ins else 0,
                "status": w.get("status"),
                "secs": w.get("secs"),
            }

    short = {p.replace("2609.", ""): p for p in AGENT_WINS}
    a_in = [bt["agent"][short[s]]["input"] for s in PAPERS]
    a_out = [bt["agent"][short[s]]["output"] for s in PAPERS]
    a_calls = [bt["agent"][short[s]]["calls"] for s in PAPERS]
    v4_in = [bt["texlate"][short[s]]["input"] for s in PAPERS]
    v4_out = [bt["texlate"][short[s]]["output"] for s in PAPERS]
    v4_calls = [bt["texlate"][short[s]]["calls"] for s in PAPERS]
    v5_in = [v5[s]["in"] for s in PAPERS]
    v5_out = [v5[s]["out"] for s in PAPERS]
    v5_calls = [v5[s]["calls"] for s in PAPERS]

    x = np.arange(len(PAPERS))
    w = 0.27

    # ================= 图 1 三臂新输入 =================
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.6, 3.8))
    a1.bar(x - w, a_in, w, color=C_AGENT, label="agent")
    a1.bar(x, v4_in, w, color=C_V4, label="texlate v4")
    a1.bar(x + w, v5_in, w, color=C_V5, label="texlate v5")
    a1.set_yscale("log")
    a1.set_ylim(2e4, 9e6)
    a1.set_ylabel("新输入 token / 篇")
    a1.set_xticks(x)
    a1.set_xticklabels(PAPERS, rotation=45, ha="right", fontsize=8.5)
    a1.set_xlabel("arXiv 2609.xxxxx")
    a1.set_title("A · 逐篇新输入（实测，log）", loc="left", fontsize=10.5)
    a1.text(
        0.03,
        0.97,
        f"Σ agent {sum(a_in) / 1e6:.2f}M\nΣ v4    {sum(v4_in) / 1e6:.2f}M\n"
        f"Σ v5    {sum(v5_in) / 1e6:.2f}M",
        transform=a1.transAxes,
        fontsize=8.5,
        va="top",
        bbox=dict(
            boxstyle="round,pad=0.35", fc="white", ec=fv.NEUTRALS["vmist"], lw=0.7
        ),
    )
    a1.legend(fontsize=8.5, loc="upper right", framealpha=0.95)
    for xi, s in ((1, "19844"), (9, "20581")):
        a1.annotate(
            "v5>agent\n（重试）",
            xy=(xi, v5_in[xi]),
            xytext=(xi - 0.3, v5_in[xi] * 5),
            fontsize=8.5,
            color=fv.NEUTRALS["baseline"],
            ha="center",
            arrowprops=dict(arrowstyle="-", lw=0.6, color=fv.NEUTRALS["vmist"]),
        )
    a2.bar(x - w, a_calls, w, color=C_AGENT)
    a2.bar(x, v4_calls, w, color=C_V4)
    a2.bar(x + w, v5_calls, w, color=C_V5)
    a2.set_yscale("log")
    a2.set_ylim(8, 800)
    a2.set_ylabel("API 调用数 / 篇")
    a2.set_xticks(x)
    a2.set_xticklabels(PAPERS, rotation=45, ha="right", fontsize=8.5)
    a2.set_xlabel("arXiv 2609.xxxxx")
    a2.set_title("B · 逐篇调用数", loc="left", fontsize=10.5)
    a2.text(
        0.03,
        0.97,
        f"Σ agent {sum(a_calls)}\nΣ v4    {sum(v4_calls)}\nΣ v5    {sum(v5_calls)}",
        transform=a2.transAxes,
        fontsize=8.5,
        va="top",
        bbox=dict(
            boxstyle="round,pad=0.35", fc="white", ec=fv.NEUTRALS["vmist"], lw=0.7
        ),
    )
    a2.annotate(
        "v5/v4 = 140/74 ≈ 1.9×\n（退单翻小调用）",
        xy=(3 + w, v5_calls[3]),
        xytext=(3.7, 420),
        fontsize=8.5,
        color=fv.NEUTRALS["baseline"],
        ha="left",
        arrowprops=dict(arrowstyle="-", lw=0.6, color=fv.NEUTRALS["vmist"]),
    )
    fig.text(
        0.5,
        0.012,
        "柱 = 每篇新输入 token（A）/ API 调用数（B）｜三臂同模型 swe-2-medium 同网关"
        "｜窗：agent 全天 / v4 17:14–18:21 / v5 23:28–00:35｜2026-09-28",
        ha="center",
        fontsize=8,
        color=fv.NEUTRALS["baseline"],
    )
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    fig.savefig(CH / "arms-input-tokens.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    wrote.append("arms-input-tokens.png")

    # ================= 图 2 19506 逐调用 EKG =================
    # 归档 rows 优先；缺件且给 --gw-db 时按原口径现场查；皆无则跳过本图。
    pid = "2609.19506"
    ekg = load_arch("arms-ekg-rows.json")
    seqs = None
    if ekg is not None:
        seqs = {arm: [tuple(r) for r in ekg[arm]] for arm in ("agent", "v4", "v5")}
    elif gw is not None:
        if not args.v4_key_hash or not args.v5_key_hash:
            sys.exit("ekg 走 --gw-db 须同时给 --v4-key-hash 与 --v5-key-hash")
        seqs = {}
        for arm, (api, key, win_map) in {
            "agent": ("openai-responses", None, AGENT_WINS),
            "v4": ("openai-chat", args.v4_key_hash, V4_WINS),
        }.items():
            t0, t1 = win_map[pid]
            seqs[arm] = gw_rows(gw, api, key, t0, t1)
        seqs["v5"] = v5_rows(
            gw, args.v5_key_hash, next(v for k, v in wins.items() if k.startswith(pid))
        )
    if seqs is None:
        print("skip fig2：无 arms-ekg-rows.json 且未给 --gw-db")
    else:
        fig, axes = plt.subplots(3, 1, figsize=(8.6, 5.8), sharex=False)
        conf = [
            (
                "agent",
                C_AGENT,
                "agent · 增量上下文逐轮重发（金=命中增量，橙刺=全价重发）",
            ),
            (
                "v4",
                C_V4,
                "texlate v4 · ph 恒等表随批全价重发（红刺=miss 全价，金=命中）",
            ),
            ("v5", C_V5, "texlate v5 · manifest 单行点名册（全部 miss）"),
        ]
        for ax, (arm, col, title) in zip(axes, conf):
            rows = seqs[arm]
            ins = [r[0] for r in rows]
            cols = [col if r[1] == 0 else fv.HUES["vgold"] for r in rows]
            ax.bar(range(len(rows)), ins, width=1.0, color=cols, linewidth=0)
            ax.set_yscale("log")
            ax.set_ylim(2e2, 3e5)
            ax.set_title(
                f"{title}（{len(rows)} 调用，Σin {sum(ins) / 1e3:.0f}k）",
                loc="left",
                fontsize=10.5,
            )
            ax.set_xlabel("调用序")
        axes[0].set_ylabel("in tok")
        axes[1].set_ylabel("in tok")
        axes[2].set_ylabel("in tok")
        fig.text(
            0.5,
            0.012,
            "2609.19506 逐调用新输入（log）｜竖线=单次全价新输入｜暖色=miss 重发（agent 橙/v4 红）｜青=v5 常数 miss｜金=命中｜2026-09-28",
            ha="center",
            fontsize=8,
            color=fv.NEUTRALS["baseline"],
        )
        fig.tight_layout(rect=[0, 0.04, 1, 1])
        fig.savefig(CH / "arms-request-ekg.png", dpi=220, bbox_inches="tight")
        plt.close(fig)
        wrote.append("arms-request-ekg.png")

    # ================= 图 3 推算 vs 实测 =================
    fig, ax = plt.subplots(figsize=(7.6, 3.6))
    proj = [V5_PROJ[s] for s in PAPERS]
    meas = v5_in
    ax.bar(
        x - w / 2,
        proj,
        w,
        color=C_V5,
        hatch="//",
        edgecolor="white",
        linewidth=0,
        label="v5 推算（同 miss 谱）",
    )
    ax.bar(x + w / 2, meas, w, color=C_V5, label="v5 实测")
    ax.set_yscale("log")
    ax.set_ylim(1.5e4, 8e6)
    ax.set_ylabel("新输入 token / 篇")
    ax.set_xticks(x)
    ax.set_xticklabels(
        [p + "*" if p in ("20739", "19990", "20581") else p for p in PAPERS],
        rotation=45,
        ha="right",
        fontsize=8.5,
    )
    ax.set_xlabel("arXiv 2609.xxxxx（* = 实测反超推算篇）")
    ax.set_title("v5 记账模型验证：推算 vs 实测", loc="left", fontsize=10.5)
    ax.legend(fontsize=10, loc="upper right")
    ratio = sum(meas) / sum(proj)
    ax.text(
        0.03,
        0.95,
        f"Σ 推算 {sum(proj) / 1e6:.2f}M → 实测 {sum(meas) / 1e6:.2f}M（{ratio:.0%}）\n"
        "偏低：S_v5 常数 ~1k + 批载荷 < 推算上限\n"
        "反超（20739/19990/20581）= 退单翻放大调用数",
        transform=ax.transAxes,
        fontsize=8.5,
        va="top",
        bbox=dict(
            boxstyle="round,pad=0.35", fc="white", ec=fv.NEUTRALS["vmist"], lw=0.7
        ),
    )
    fig.text(
        0.5,
        0.012,
        "柱 = 每篇 v5 新输入 token｜推算 = Σuser + n_miss × S_v5（v4 miss 谱），实测 = 网关窗Σ（核平 task_usage）｜2026-09-28",
        ha="center",
        fontsize=8,
        color=fv.NEUTRALS["baseline"],
    )
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    fig.savefig(CH / "arms-v5-validation.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    wrote.append("arms-v5-validation.png")

    # ================= 图 4 三臂质量闸 =================
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(8.6, 3.8))

    def qcent(src, p, arm="texlate"):
        return src.get(f"2609.{p}/{arm}") or src.get(f"2609.{p}") or {}

    def qcget(src, p, k, arm="texlate"):
        return (qcent(src, p, arm).get("metrics") or {}).get(k, 0) or 0

    def qcget5(p, k):
        return ((qc.get(f"2609.{p}") or {}).get("metrics") or {}).get(k, 0) or 0

    has_a = [bool(qcent(qc4, p, "agent").get("metrics")) for p in PAPERS]
    has_4 = [bool(qcent(qc4, p, "texlate").get("metrics")) for p in PAPERS]
    has_5 = [bool((qc.get(f"2609.{p}") or {}).get("metrics")) for p in PAPERS]
    resid_a = [qcget(qc4, p, "residual_en_eff", "agent") for p in PAPERS]
    resid_4 = [qcget(qc4, p, "residual_en_eff", "texlate") for p in PAPERS]
    resid_5 = [qcget5(p, "residual_en_eff") for p in PAPERS]
    ng_a = [qcget(qc4, p, "top_ngram_rep", "agent") for p in PAPERS]
    ng_4 = [qcget(qc4, p, "top_ngram_rep", "texlate") for p in PAPERS]
    ng_5 = [qcget5(p, "top_ngram_rep") for p in PAPERS]
    a1.bar(x - w, resid_a, w, color=C_AGENT, label="agent")
    a1.bar(x, resid_4, w, color=C_V4, label="texlate v4")
    a1.bar(x + w, resid_5, w, color=C_V5, label="texlate v5")
    for xi, (ha, h4, h5) in enumerate(zip(has_a, has_4, has_5)):
        if not ha:
            a1.text(
                xi - w,
                0.8,
                "n/a",
                ha="center",
                fontsize=8.5,
                color=fv.NEUTRALS["baseline"],
                rotation=90,
            )
        if not (h4 and h5):
            a1.text(
                xi + w / 2,
                0.8,
                "n/a",
                ha="center",
                fontsize=8.5,
                color=fv.NEUTRALS["baseline"],
                rotation=90,
            )
    a1.set_ylabel("残英有效行 / 篇")
    a1.set_ylim(0, 30)
    a1.set_xticks(x)
    a1.set_xticklabels(PAPERS, rotation=45, ha="right", fontsize=8.5)
    a1.set_xlabel("arXiv 2609.xxxxx")
    a1.set_title("A · 残英有效行（低好）", loc="left", fontsize=10.5)
    a1.legend(fontsize=10)
    a2.bar(x - w, ng_a, w, color=C_AGENT)
    a2.bar(x, ng_4, w, color=C_V4)
    a2.bar(x + w, ng_5, w, color=C_V5)
    for xi, (ha, h4, h5) in enumerate(zip(has_a, has_4, has_5)):
        if not ha:
            a2.text(
                xi - w,
                1.6,
                "n/a",
                ha="center",
                fontsize=8.5,
                color=fv.NEUTRALS["baseline"],
                rotation=90,
            )
        if not (h4 and h5):
            a2.text(
                xi + w / 2,
                1.6,
                "n/a",
                ha="center",
                fontsize=8.5,
                color=fv.NEUTRALS["baseline"],
                rotation=90,
            )
    a2.annotate(
        "≈10 次之",
        xy=(8 - w, ng_a[8]),
        xytext=(8 - 2.1, 14),
        fontsize=8.5,
        color=fv.NEUTRALS["baseline"],
        arrowprops=dict(arrowstyle="-", lw=0.6, color=fv.NEUTRALS["vmist"]),
    )
    a2.set_ylabel("退化重复分 / 篇")
    a2.set_ylim(0, 60)
    a2.set_xticks(x)
    a2.set_xticklabels(PAPERS, rotation=45, ha="right", fontsize=8.5)
    a2.set_xlabel("arXiv 2609.xxxxx")
    a2.set_title("B · ngram 退化重复（低好）", loc="left", fontsize=10.5)
    fig.text(
        0.5,
        0.012,
        "柱 = 每篇 zh PDF 抽文闸指标｜n/a = 无 zh.pdf（partial/fault），A 面 agent 近零=真零分（十篇皆有产物）｜"
        "B 面 agent 19506≈55 最大退化点｜v5≈v4 ±1–2 内持平｜2026-09-28",
        ha="center",
        fontsize=8,
        color=fv.NEUTRALS["baseline"],
    )
    fig.tight_layout(rect=[0, 0.05, 1, 1])
    fig.savefig(CH / "arms-quality.png", dpi=220, bbox_inches="tight")
    plt.close(fig)
    wrote.append("arms-quality.png")

    print("wrote:", *wrote, sep="\n  ")


if __name__ == "__main__":
    main()
