#!/usr/bin/env python3
r"""qualdrift — judge 漂移哨兵：frozen 钉集定期复判 + qualfreeze 门禁 + 历史账。

回答的问题：**尺子动没动**。judge 模型（swe-2-max，网关后端可静默换版）
随时间漂移会把「翻译质量变化」和「判分口径变化」混进同一组数字——
每次 frozen-300 回归前的哨兵复判把这两者拆开：钉集的 ``zh`` 冻结在
manifest 里，复判只过 judge 不重翻，任何分布漂移只能来自 judge 侧。

机制（全部复用既有件，本脚本只是编排）：

  1. ``qualbench run --source manifest --manifest frozen300.jsonl``
     ——钉集只含 {paper,chunk_id,kind,model,zh,src}，judge 重新打分；
  2. ``qualfreeze check --baseline <基线 records> --new <本次 records>
     --frozen <钉集>`` ——四个分布信号（stated100 KS、flag 率 z-test、
     per-kind 均值 Δ、contested 率 Δ），阈值与回归门禁同套；
  3. 门禁 JSON 摘要追加 ``--history``（默认
     bench/results/qualdrift-history.jsonl）——跨次趋势一眼可读。

子命令：

  run      跑一轮哨兵（步骤 1-3）；exit 镜像门禁：0=pass · 3=drift ·
           2=usage error。``--mock-judge`` 离线自检（drift 必然 pass，
           只验证编排链）。
  history  打印历史账趋势表（ts/verdict/KS-D/KS-p/kind 最大 |Δ|/
           contested Δ/flag 漂移清单）。

用法:
  uv run python bench/py/qualdrift.py run \
      --baseline bench/results/qualbase-2026-09-18/records.jsonl \
      --frozen bench/results/qualbase-2026-09-18/frozen300.jsonl \
      --concurrency 4
  uv run python bench/py/qualdrift.py history
依赖: 纯 stdlib + benchlib；qualbench/qualfreeze 以子进程方式调用
（``sys.executable`` 继承 uv venv）。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUALBENCH = Path(__file__).with_name("qualbench.py")
QUALFREEZE = Path(__file__).with_name("qualfreeze.py")
DEFAULT_HISTORY = ROOT / "bench/results/qualdrift-history.jsonl"

# 门禁阈值——与 frozen-300 回归批同套（leader 定，用户裁决项④同口径）。
DEFAULT_THRESHOLDS = {
    "ks_alpha": 0.05,
    "flag_alpha": 0.01,
    "kind_delta": 5.0,
    "contested_delta": 0.10,
}


def _run(cmd: list[str], log) -> int:
    log.write("$ " + " ".join(cmd) + "\n")
    log.flush()
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )
    assert proc.stdout is not None
    for line in proc.stdout:
        log.write(line)
    return proc.wait()


def cmd_run(a: argparse.Namespace) -> int:
    out = Path(a.out) if a.out else ROOT / f"bench/results/qualdrift-{a.date}"
    out.mkdir(parents=True, exist_ok=True)
    history = Path(a.history)
    with (out / "run.log").open("w") as log:
        jm = "mock-judge" if a.mock_judge else a.judge_model
        qb = [
            sys.executable,
            str(QUALBENCH),
            "run",
            "--source",
            "manifest",
            "--manifest",
            str(a.frozen),
            "--judge-model",
            jm,
            "--second-model",
            a.second_model,
            "--concurrency",
            str(a.concurrency),
            "--judge-timeout",
            str(a.judge_timeout),
            "--out",
            str(out),
            "--tag",
            "qualdrift",
            "--date",
            a.date,
        ]
        if a.base_url:
            qb += ["--base-url", a.base_url]
        if a.api_key:
            qb += ["--api-key", a.api_key]
        if a.mock_judge:
            qb.append("--mock-judge")
        rc = _run(qb, log)
        if rc != 0:
            print(f"qualbench failed rc={rc} — see {out}/run.log", file=sys.stderr)
            return 2
        records = out / "records.jsonl"
        qf = [
            sys.executable,
            str(QUALFREEZE),
            "check",
            "--baseline",
            str(a.baseline),
            "--new",
            str(records),
            "--frozen",
            str(a.frozen),
            "--out",
            str(out / "gate_report.json"),
            "--ks-alpha",
            str(a.ks_alpha),
            "--flag-alpha",
            str(a.flag_alpha),
            "--kind-delta",
            str(a.kind_delta),
            "--contested-delta",
            str(a.contested_delta),
        ]
        rc = _run(qf, log)
    report = json.loads((out / "gate_report.json").read_text())
    entry = _history_entry(report, a, out)
    history.parent.mkdir(parents=True, exist_ok=True)
    with history.open("a") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    print(
        f"verdict={entry['verdict']} ks_p={entry['ks_p']} "
        f"kind_max|Δ|={entry['kind_max_abs_delta']} "
        f"contested_Δ={entry['contested_delta']} → {history}"
    )
    return rc


def _history_entry(report: dict, a: argparse.Namespace, out: Path) -> dict:
    checks = report.get("checks", {})
    ks = checks.get("stated100_ks", {})
    kinds = checks.get("kind_means", {}).get("per_kind", {})
    contested = checks.get("contested_rate", {})
    flags = checks.get("flag_rates", {}).get("per_flag", {})
    counts = report.get("counts", {})
    flag_drifts = [
        f"{k}:{v.get('diff', 0):+.3f}"
        for k, v in flags.items()
        if isinstance(v, dict) and v.get("drift")
    ]
    kind_deltas = {k: v.get("delta") for k, v in kinds.items() if isinstance(v, dict)}
    return {
        "ts": datetime.now(UTC).isoformat(timespec="seconds"),
        "out": str(out),
        "judge_model": a.judge_model if not a.mock_judge else "mock-judge",
        "verdict": report.get("verdict"),
        "ks_d": ks.get("D"),
        "ks_p": ks.get("p_value"),
        "kind_deltas": kind_deltas,
        "kind_max_abs_delta": max(
            (abs(d) for d in kind_deltas.values() if d is not None),
            default=None,
        ),
        "contested_delta": contested.get("diff"),
        "flag_drifts": flag_drifts,
        "n_new": counts.get("n_new_used"),
        "n_baseline": counts.get("n_base_used"),
    }


def cmd_history(a: argparse.Namespace) -> int:
    path = Path(a.history)
    if not path.exists():
        print(f"no history at {path}", file=sys.stderr)
        return 2
    for line in path.read_text().splitlines():
        e = json.loads(line)
        fd = ",".join(e.get("flag_drifts") or []) or "-"
        kd = e.get("kind_max_abs_delta")
        print(
            f"{e['ts']}  {e['verdict'] or '?':<10} "
            f"ksD={e.get('ks_d')} ksP={e.get('ks_p')} "
            f"kind|Δ|max={kd if kd is None else round(kd, 2)} "
            f"contestedΔ={e.get('contested_delta')} flags={fd}"
        )
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser("run", help="跑一轮 judge 漂移哨兵")
    p_run.add_argument(
        "--baseline",
        default=str(ROOT / "bench/results/qualbase-2026-09-18/records.jsonl"),
        help="基线 records.jsonl（钉集评分的参照分布）",
    )
    p_run.add_argument(
        "--frozen",
        default=str(ROOT / "bench/results/qualbase-2026-09-18/frozen300.jsonl"),
        help="qualfreeze freeze 产出的钉集 manifest",
    )
    p_run.add_argument("--judge-model", default="swe-2-max")
    p_run.add_argument("--second-model", default="swe-2-high")
    p_run.add_argument("--base-url", default=None, help="缺省走 qualbench 自带默认/env")
    p_run.add_argument("--api-key", default=None)
    p_run.add_argument("--concurrency", type=int, default=4)
    p_run.add_argument("--judge-timeout", type=float, default=300.0)
    p_run.add_argument("--mock-judge", action="store_true", help="离线编排自检")
    p_run.add_argument("--out", default=None)
    p_run.add_argument("--history", default=str(DEFAULT_HISTORY))
    p_run.add_argument("--date", default=str(datetime.now(UTC).date()))
    for k, v in DEFAULT_THRESHOLDS.items():
        p_run.add_argument(f"--{k.replace('_', '-')}", type=float, default=v)
    p_run.set_defaults(fn=cmd_run)

    p_h = sub.add_parser("history", help="打印漂移历史账")
    p_h.add_argument("--history", default=str(DEFAULT_HISTORY))
    p_h.set_defaults(fn=cmd_history)

    args = ap.parse_args()
    raise SystemExit(args.fn(args))


if __name__ == "__main__":
    main()
