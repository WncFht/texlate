#!/usr/bin/env python3
r"""wave.py — 修复波一体化编排壳（runbook_loop.md §1-§5 的波次面封装）。

三子命令，全部只做编排壳——选样/对账/记分逻辑一律 subprocess 调既有
脚本（mech_ids / rerun-wave.sh / rundiff / dossier / gate_scorecard），
本文件零重实现：

  wave.py run IDS.txt --stage chain              # id 集开波（dry-run 预览）
  wave.py run --mech B01,W45 --plus-random 20    # 机制标签外部 join → ids
  wave.py run --rule illegal_unit --stage deep   # rules.yaml mechanisms: 反查
  wave.py run IDS.txt --go                       # 前台真跑（长波用打印的 setsid 行）
  wave.py postmortem RUN_DIR [--workspace W]     # rundiff + dossier join + sig 分簇
  wave.py scorecard [RUN_DIR] [--save]           # gate_scorecard --json + 快照 diff

波次工作区 bench/results/wave-<tag>-<date>/（--workspace 覆盖）：

  ids.txt               本波 id 集（每行一个 slash 形，rerun-wave.sh 同口径）
  before/records/       开波前 records 快照——postmortem 的 rundiff A 侧
  wave.json             波次元数据（selector/run_dir/stage/argv/created）
  rundiff.md            postmortem 对账（rundiff 原文）
  postmortem.{md,json}  postmortem 汇总产出
  run.log               建议的脱管日志落点（setsid 行里已拼好）

纪律（与 rerun-wave.sh 头注 / runbook §0§2 同源）：
  - 单写者：同结果目只允许一个 stagerun 进程——run 开头 pgrep 检查，
    撞车拒开波（先于快照，防 append 撕半边）。
  - 脱管：估时 >30min 必须 setsid 脱离任务系统（harness 看门狗专杀后台
    批）。本壳 dry-run 打印现成 setsid 命令行，**不替用户点火**；--go
    是前台跑，等价 rerun-wave.sh --go。
  - runbook §0 前置（gw-health.sh / preflight_batch.py / src 快照）属
    人工确认，本壳不代跑；stagerun 自带 import+mock 链 preflight 在每条
    命令起跑时仍生效。

纯 stdlib。python 子进程用 sys.executable——`uv run` 下 dossier 吃到
texlate.* 读侧 taxonomy，系统 python3 下各脚本按自有约定降级。
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

PY_DIR = Path(__file__).resolve().parent
ROOT = PY_DIR.parents[1]
RESULTS = ROOT / "bench" / "results"
MECH_IDS = PY_DIR / "mech_ids.py"
RUNDIFF = PY_DIR / "rundiff.py"
DOSSIER = PY_DIR / "dossier.py"
SCORECARD = PY_DIR / "gate_scorecard.py"
RERUN_SH = ROOT / "tmp" / "rerun-wave.sh"

#: pgrep 绝对路径（S607）；找不到退裸名交 PATH 解析。
_PGREP = shutil.which("pgrep") or "pgrep"

#: rerun-wave.sh --stage 的四档口径原样透传。
WAVE_STAGES = ("fixloop", "compile", "chain", "deep")
#: added 格里值得进 dossier join 的坏终态。
_BAD_END = {"fail", "error", "reject", "dirty_pdf"}
#: postmortem 清单渲染上限（全量见 postmortem.json）。
_MAX_LIST = 50


# ---------------------------------------------------------------- 公共件


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """子进程统一入口；stderr 继承（各脚本自有人读输出面）。"""
    return subprocess.run(cmd, cwd=ROOT, **kw)


def _json_run(cmd: list[str]) -> dict:
    """subprocess → stdout JSON；退出码非零连 stderr 一起报出。"""
    r = _run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr)
        print(f"!! 子命令失败 rc={r.returncode}: {shlex.join(cmd)}", file=sys.stderr)
        raise SystemExit(r.returncode)
    return json.loads(r.stdout)


def _newest_stagerun() -> Path | None:
    """缺省 run 目：stagerun-loop* 最新者优先（loop 是主战场），
    否则任意 stagerun-* 最新者——与 rerun-wave.sh 钉 loop1 的默认同向。"""
    dirs = [d for d in RESULTS.glob("stagerun-*") if (d / "records").is_dir()]
    loops = [d for d in dirs if d.name.startswith("stagerun-loop")]
    pool = loops or dirs
    return max(pool, key=lambda d: d.stat().st_mtime) if pool else None


def _resolve_run_dir(arg: str | None) -> Path | None:
    if arg:
        return Path(arg)
    return _newest_stagerun()


def _stagerun_alive(run_dir: Path) -> list[str]:
    """同目在跑 stagerun 的 pid 表（rerun-wave.sh 单写者闸同 pattern）。"""
    r = subprocess.run(
        [_PGREP, "-f", f"stagerun.py.*{run_dir.name}"],
        capture_output=True,
        text=True,
    )
    return r.stdout.split() if r.returncode == 0 else []


def _read_ids_file(path: Path) -> list[str]:
    """ids 文件 → 有序去重 id 表；每行一个或逗号分隔，空白/# 注释忽略
    （rerun-wave.sh 内嵌解析器同口径）。"""
    ids: list[str] = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        ids.extend(x.strip() for x in line.split(",") if x.strip())
    return list(dict.fromkeys(ids))


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "-" for c in text).strip("-")


def _utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _records_dir_of(run_dir: Path) -> Path:
    """run 目或 records/ 目都收 → records/ 路径。"""
    return run_dir if run_dir.name == "records" else run_dir / "records"


# ---------------------------------------------------------------- run


def _resolve_workspace(args, ids_src_desc: str) -> Path:
    """工作区落点：--workspace 直给；否则 bench/results/wave-<tag>-<date>，
    撞名（同日同 tag 再开波）自动 -2/-3 续号——before/ 快照不可覆写。"""
    if args.workspace:
        return Path(args.workspace)
    tag = _slug(args.tag or ids_src_desc) or "wave"
    date = str(datetime.now(UTC).date())
    base = RESULTS / f"wave-{tag}-{date}"
    ws, n = base, 2
    while ws.exists():
        ws = Path(f"{base}-{n}")
        n += 1
    return ws


def _snapshot(run_dir: Path, ws: Path) -> Path:
    """records/*.jsonl + run_meta.json → ws/before/（rundiff A 侧契约：
    只要 ``<dir>/records/*.jsonl`` 在位即可作 DIR_A）。"""
    before = ws / "before"
    rec_snap = before / "records"
    rec_snap.mkdir(parents=True, exist_ok=True)
    n = 0
    for f in sorted((run_dir / "records").glob("*.jsonl")):
        shutil.copy2(f, rec_snap / f.name)
        n += 1
    meta = run_dir / "run_meta.json"
    if meta.exists():
        shutil.copy2(meta, before / "run_meta.json")
    print(f"snapshot: {n} records 文件 -> {rec_snap}", flush=True)
    return before


def _write_meta(ws: Path, meta: dict) -> None:
    (ws / "wave.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )


def _detach_hint(go_cmd: list[str], ws: Path, run_dir: Path) -> None:
    # 全部 flush=True——与子进程直写 stdout 的输出保持时序（管道下 print 块缓冲）。
    print(
        "== 脱管点火（runbook §2：估时 >30min 必须 setsid，勿挂任务系统后台）==",
        flush=True,
    )
    print(
        f"  setsid nohup {shlex.join(go_cmd)} >> {ws}/run.log 2>&1 < /dev/null &",
        flush=True,
    )
    print(
        f"  真 pid: pgrep -f 'stagerun.py.*{run_dir.name}'  （setsid fork，$! 是 wrapper）",
        flush=True,
    )
    print(
        "  监控: kill -0 <pid> + records 行数；看板 task_ping.py <slug> --status running --pid <pid>",
        flush=True,
    )
    print(
        f"  波后: uv run python bench/py/wave.py postmortem {run_dir} --workspace {ws}",
        flush=True,
    )


def cmd_run(args) -> int:
    run_dir = _resolve_run_dir(args.dir)
    if run_dir is None or not (run_dir / "records").is_dir():
        print(
            f"!! run 目无 records/：{run_dir}（--dir 指定或先开 loop 批）",
            file=sys.stderr,
        )
        return 2
    run_dir = run_dir.resolve()
    alive = _stagerun_alive(run_dir)
    if alive:
        print(
            f"!! 单写者闸：{run_dir.name} 已有 stagerun pid={alive} 在跑——拒开波",
            file=sys.stderr,
        )
        return 1

    # ---- id 集解析（mech/rule 走 mech_ids.py 外部 join；文件直读归一）
    mech_tags = [t for t in (args.mech or "").split(",") if t.strip()]
    if args.ids_file and (mech_tags or args.rule):
        print("!! ids-file 与 --mech/--rule 互斥", file=sys.stderr)
        return 2
    if not args.ids_file and not mech_tags and not args.rule:
        print("!! 需要 ids-file 或 --mech/--rule 选择器", file=sys.stderr)
        return 2

    src_desc = (
        Path(args.ids_file).stem
        if args.ids_file
        else "-".join([*(["rule", args.rule] if args.rule else []), *mech_tags])
    )
    ws = _resolve_workspace(args, src_desc)
    if (ws / "before").exists():
        print(
            f"!! {ws} 已有 before/ 快照（覆写毁 postmortem A 侧）——换 --workspace/--tag",
            file=sys.stderr,
        )
        return 2
    ws.mkdir(parents=True, exist_ok=True)
    ids_out = ws / "ids.txt"

    selector: dict = {}
    if args.ids_file:
        ids = _read_ids_file(Path(args.ids_file))
        ids_out.write_text("\n".join(ids) + "\n", encoding="utf-8")
        selector = {"ids_file": args.ids_file}
    else:
        cmd = [sys.executable, str(MECH_IDS), *mech_tags]
        if args.rule:
            cmd += ["--rule", args.rule]
        if args.plus_random:
            cmd += ["--plus-random", str(args.plus_random), "--seed", str(args.seed)]
        if args.validate:
            cmd += ["--validate"]
        cmd += ["--out", str(ids_out)]
        r = _run(cmd)
        if r.returncode != 0:
            return r.returncode
        ids = _read_ids_file(ids_out)
        selector = {
            "mech": mech_tags,
            "rule": args.rule,
            "plus_random": args.plus_random,
            "seed": args.seed,
        }
    if not ids:
        print("!! 解析出 0 个 id——未快照未开波", file=sys.stderr)
        return 2
    print(f"ids: {len(ids)} -> {ids_out}", flush=True)

    _snapshot(run_dir, ws)
    cmd = [
        "bash",
        str(RERUN_SH),
        "--ids-file",
        str(ids_out),
        "--dir",
        str(run_dir),
        "--stage",
        args.stage,
        "--xlat-arm",
        args.xlat_arm,
        "--jobs",
        str(args.jobs),
    ]
    if args.split:
        cmd.append("--split")
    _write_meta(
        ws,
        {
            "created": _utcnow(),
            "run_dir": str(run_dir),
            "n_ids": len(ids),
            "selector": selector,
            "stage": args.stage,
            "xlat_arm": args.xlat_arm,
            "jobs": args.jobs,
            "split": bool(args.split),
            "argv": sys.argv,
        },
    )

    print(
        "== runbook §0 前置自查（本壳不代跑）：gw-health.sh / "
        "preflight_batch.py / src 快照按需先行",
        flush=True,
    )
    go_cmd = [*cmd, "--go"]
    if not args.go:
        r = _run(cmd)  # rerun-wave.sh 缺省 dry-run：分类 + 将跑命令
        if r.returncode != 0:
            return r.returncode
        _detach_hint(go_cmd, ws, run_dir)
        print("== dry-run 完毕（--go 前台真跑，或上面 setsid 行脱管）", flush=True)
        return 0
    print(
        "== --go 前台跑；长波更稳的姿势是上面这条 setsid（中断可重跑同命令续）",
        flush=True,
    )
    _detach_hint(go_cmd, ws, run_dir)
    return _run(go_cmd).returncode


# ---------------------------------------------------------------- postmortem


def _find_workspace(run_dir: Path) -> Path | None:
    """最近一个 wave.json 指向本 run 目的工作区。"""
    found = []
    for meta_f in RESULTS.glob("*/wave.json"):
        try:
            meta = json.loads(meta_f.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        if meta.get("run_dir") and Path(meta["run_dir"]).name == run_dir.name:
            found.append(meta_f.parent)
    return max(found, key=lambda d: d.stat().st_mtime) if found else None


def _scope_lists(stage_diff: dict, ids: set[str] | None) -> dict:
    """rundiff --json 的单 stage 块 → 按波次 id 集过滤的四清单。
    ids=None 不过滤（ad-hoc baseline 模式）。"""
    out = {}
    for k in ("degraded", "improved", "added", "removed", "same"):
        entries = stage_diff.get(k) or []
        if ids is None:
            out[k] = entries
        else:
            out[k] = [e for e in entries if e.get("id") in ids]
    return out


def _endstate_dist(scoped: dict) -> Counter:
    """波次格在 B 侧的末态分布（same/improved/degraded/added 的 b 值）。"""
    c = Counter()
    for k in ("same", "improved", "degraded", "added"):
        for e in scoped[k]:
            c[str(e.get("b") or "?")] += 1
    return c


def _dossier_join(targets: list[dict], run_dir: Path, top: int) -> list[dict]:
    """degraded/坏 added 格逐 id 调 dossier.py --json 取签名面。"""
    out = []
    for e in targets[:top]:
        rid = e["id"]
        row = {
            "id": rid,
            "a": e.get("a"),
            "b": e.get("b"),
            "sig_b": e.get("sig_b") or e.get("sig"),
        }
        r = _run(
            [sys.executable, str(DOSSIER), rid, "--run", str(run_dir), "--json"],
            capture_output=True,
            text=True,
        )
        if r.returncode != 0:
            row["dossier_error"] = (r.stderr or "").strip().splitlines()[-1:]
            out.append(row)
            continue
        try:
            d = json.loads(r.stdout)
        except json.JSONDecodeError:
            row["dossier_error"] = ["dossier 输出非 JSON"]
            out.append(row)
            continue
        sig = d.get("signature") or {}
        ev = d.get("evidence") or {}
        tax = ev.get("first_error_taxonomy") or {}
        row.update(
            {
                "sig_bucketed": sig.get("sig_bucketed"),
                "fix_class_hint": sig.get("fix_class_hint"),
                "first_error": ev.get("first_error_line"),
                "first_error_taxonomy": (
                    f"{tax.get('category')}:{tax.get('payload')}" if tax else None
                ),
            }
        )
        out.append(row)
    return out


def _md_list(lines: list[str], title: str, entries: list[dict], fmt) -> None:
    lines += [f"### {title} ({len(entries)})", ""]
    if not entries:
        lines += ["无。", ""]
        return
    for e in entries[:_MAX_LIST]:
        lines.append(f"- `{e.get('id')}` {fmt(e)}")
    if len(entries) > _MAX_LIST:
        lines.append(f"- … 其余 {len(entries) - _MAX_LIST} 条见 postmortem.json")
    lines.append("")


def _render_pm(
    run_dir: Path,
    baseline: Path,
    ws: Path | None,
    scope_n: int | None,
    rd: dict,
    scoped: dict,
    clusters: dict,
    dossiers: list[dict],
) -> str:
    lines = [
        f"# wave postmortem — {baseline.name} → {run_dir.name}",
        "",
        f"- generated: {_utcnow()}",
        f"- run: `{run_dir}` ｜ baseline: `{baseline}`",
    ]
    if ws:
        lines.append(f"- workspace: `{ws}`")
    lines.append(
        f"- wave-scope: {scope_n} ids"
        if scope_n is not None
        else "- wave-scope: 全量（无 ids.txt，ad-hoc 对账）"
    )
    lines.append("")

    lines += ["## 迁移总览（rundiff 全量口径）", ""]
    for stage, d in rd["stages"].items():
        c = d["counts"]
        lines.append(
            f"- {stage}: same {c['same']} · improved {c['improved']}"
            f" · degraded {c['degraded']} · added {c['added']} · removed {c['removed']}"
        )
    lines.append("")

    for stage, sc in scoped.items():
        lines += [f"## {stage}（波次范围）", ""]
        dist = _endstate_dist(sc)
        if dist:
            lines.append(
                "- 波后末态: " + " ".join(f"{s}={n}" for s, n in dist.most_common())
            )
            lines.append("")
        _md_list(
            lines,
            "degraded",
            sc["degraded"],
            lambda e: (
                f"{e.get('a')} → {e.get('b')}"
                + (f" — `{e.get('sig_b')}`" if e.get("sig_b") else "")
            ),
        )
        _md_list(
            lines,
            "improved",
            sc["improved"],
            lambda e: (
                f"{e.get('a')} → {e.get('b')}"
                + (f" — `{e.get('sig_a')}`" if e.get("sig_a") else "")
            ),
        )
        _md_list(
            lines,
            "added",
            sc["added"],
            lambda e: (
                f"{e.get('b')}" + (f" — `{e.get('sig')}`" if e.get("sig") else "")
            ),
        )
        _md_list(
            lines,
            "removed",
            sc["removed"],
            lambda e: (
                f"{e.get('a')}" + (f" — `{e.get('sig')}`" if e.get("sig") else "")
            ),
        )

    lines += ["## sig 分簇（degraded 按 sig_b / added 按 sig）", ""]
    for stage, ctr in clusters.items():
        if not ctr:
            continue
        lines.append(f"### {stage}")
        lines.append("")
        for s, n in ctr.most_common(20):
            lines.append(f"- {n:4d}  `{s}`")
        lines.append("")

    if dossiers:
        lines += ["## dossier join（degraded + 坏 added）", ""]
        lines.append("| id | 迁移 | sig | bucket | first_error taxonomy | fix hint |")
        lines.append("| --- | --- | --- | --- | --- | --- |")
        for d in dossiers:
            lines.append(
                "| {id} | {a}→{b} | `{sig}` | `{bk}` | {tax} | {hint} |".format(
                    id=d["id"],
                    a=d.get("a") or "∅",
                    b=d.get("b") or "?",
                    sig=d.get("sig_b") or "",
                    bk=d.get("sig_bucketed") or "",
                    tax=d.get("first_error_taxonomy") or "",
                    hint=d.get("fix_class_hint") or d.get("dossier_error") or "",
                )
            )
        lines.append("")

    lines += [
        "## 产物",
        "",
        "- `rundiff.md` — rundiff 原文（全量矩阵+清单）",
        "- `postmortem.json` — 本报告机读底账（含 scoped 全清单与 dossier 行）",
        "",
    ]
    return "\n".join(lines)


def cmd_postmortem(args) -> int:
    run_dir = _resolve_run_dir(args.run_dir)
    if run_dir is None or not (run_dir / "records").is_dir():
        print(f"!! run 目无 records/：{run_dir}", file=sys.stderr)
        return 2
    run_dir = run_dir.resolve()

    ws = Path(args.workspace).resolve() if args.workspace else _find_workspace(run_dir)
    if args.baseline:
        baseline = Path(args.baseline).resolve()
    elif ws and (ws / "before" / "records").is_dir():
        baseline = ws / "before"
    else:
        baseline = None
    if baseline is None or not (baseline / "records").is_dir():
        print(
            "!! 无 A 侧基线：--baseline <含 records/ 的目录>，"
            "或 --workspace 指向 wave run 落的工作区（含 before/records/）",
            file=sys.stderr,
        )
        return 2
    out_dir = Path(args.out_dir).resolve() if args.out_dir else (ws or run_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    ids: set[str] | None = None
    if args.ids:
        ids = set(_read_ids_file(Path(args.ids)))
    elif ws and (ws / "ids.txt").is_file():
        ids = set(_read_ids_file(ws / "ids.txt"))

    rd_cmd = [sys.executable, str(RUNDIFF), str(baseline), str(run_dir)]
    if args.deep:
        rd_cmd.append("--deep")
    rd = _json_run([*rd_cmd, "--json"])
    rd_md = _run(rd_cmd, capture_output=True, text=True)
    if rd_md.returncode == 0:
        (out_dir / "rundiff.md").write_text(rd_md.stdout, encoding="utf-8")

    scoped = {s: _scope_lists(d, ids) for s, d in rd["stages"].items()}
    clusters = {
        s: Counter(
            str(e.get("sig_b") or e.get("sig") or "(none)")
            for e in [*sc["degraded"], *sc["added"]]
        )
        for s, sc in scoped.items()
    }
    targets = [
        e
        for sc in scoped.values()
        for e in [
            *sc["degraded"],
            *[x for x in sc["added"] if x.get("b") in _BAD_END],
        ]
    ]
    dossiers = (
        [] if args.no_dossier else _dossier_join(targets, run_dir, args.dossier_top)
    )

    payload = {
        "generated": _utcnow(),
        "run": str(run_dir),
        "baseline": str(baseline),
        "workspace": str(ws) if ws else None,
        "scope_n": len(ids) if ids is not None else None,
        "rundiff": rd,
        "scoped": scoped,
        "clusters": {s: c.most_common() for s, c in clusters.items()},
        "dossiers": dossiers,
    }
    (out_dir / "postmortem.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    md = _render_pm(
        run_dir,
        baseline,
        ws,
        len(ids) if ids is not None else None,
        rd,
        scoped,
        clusters,
        dossiers,
    )
    (out_dir / "postmortem.md").write_text(md + "\n", encoding="utf-8")

    # stdout 速览：全量计数 + 波次 degraded/坏 added 头部
    for stage, d in rd["stages"].items():
        c = d["counts"]
        print(
            f"{stage}: same {c['same']} · improved {c['improved']}"
            f" · degraded {c['degraded']} · +{c['added']} -{c['removed']}"
        )
    n_deg = sum(len(sc["degraded"]) for sc in scoped.values())
    print(f"波次 degraded 计 {n_deg}（dossier join {len(dossiers)} 条）")
    print(f"→ {out_dir}/postmortem.md / postmortem.json / rundiff.md")
    return 0


# ---------------------------------------------------------------- scorecard


#: (label, json 路径)——快照 diff 跟踪的标量面。
_SC_PATHS = [
    ("cells", ("cells",)),
    ("end pdf", ("end_state", "pdf")),
    ("end pdf%", ("end_state", "pdf_pct")),
    ("end clean", ("end_state", "clean")),
    ("end clean%", ("end_state", "clean_pct")),
    ("end gate need", ("end_state", "gate", "need")),
    ("union pdf", ("union", "pdf")),
    ("union pdf%", ("union", "pdf_pct")),
    ("union clean", ("union", "clean")),
    ("union clean%", ("union", "clean_pct")),
    ("union gate need", ("union", "gate", "need")),
    ("union lift pdf", ("lift", "pdf")),
    ("union lift clean", ("lift", "clean")),
    ("orphan_fix", ("orphan_fix",)),
    ("floor_restored", ("floor_restored",)),
]


def _dig(d: dict, path: tuple):
    cur = d
    for k in path:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur


def _sc_diff(prev: dict, cur: dict) -> dict:
    """两版 gate_scorecard --json 的标量/分布/top_sigs delta。"""
    scalars = {}
    for label, path in _SC_PATHS:
        a, b = _dig(prev, path), _dig(cur, path)
        if a != b:
            scalars[label] = {"prev": a, "now": b}
    dists = {}
    for sec in ("end_state", "union"):
        da = (prev.get(sec) or {}).get("dist") or {}
        db = (cur.get(sec) or {}).get("dist") or {}
        delta = {
            k: {"prev": da.get(k, 0), "now": db.get(k, 0)}
            for k in sorted(set(da) | set(db))
            if da.get(k, 0) != db.get(k, 0)
        }
        if delta:
            dists[sec] = delta
    sa = dict(prev.get("top_sigs") or [])
    sb = dict(cur.get("top_sigs") or [])
    sigs = {
        "new": sorted(set(sb) - set(sa)),
        "gone": sorted(set(sa) - set(sb)),
        "moved": {
            s: {"prev": sa[s], "now": sb[s]}
            for s in sorted(set(sa) & set(sb))
            if sa[s] != sb[s]
        },
    }
    return {"scalars": scalars, "dist": dists, "top_sigs": sigs}


def _render_sc_diff(prev_path: Path | None, cur: dict, diff: dict | None) -> str:
    e, u = cur["end_state"], cur["union"]
    lines = [
        f"records: {cur['records_dir']}",
        (
            f"cells={cur['cells']}  pdf={e['pdf']} ({e['pdf_pct']}%)"
            f"  clean={e['clean']} ({e['clean_pct']}%)   [end-state]"
        ),
        (
            f"union:  pdf={u['pdf']} ({u['pdf_pct']}%)"
            f"  clean={u['clean']} ({u['clean_pct']}%)   [best-of]"
        ),
    ]
    for tag, g in (("end-state-pdf", e["gate"]), ("union-pdf", u["gate"])):
        state = "PASS" if g["pass"] else f"need +{g['need']}"
        lines.append(f"gate {tag} >=90%: {state}")
    if prev_path is None:
        lines.append("（无历史快照——--save 建基线后才有 diff）")
        return "\n".join(lines)
    lines.append(f"\nvs {prev_path.name}:")
    if not diff["scalars"] and not diff["dist"]:
        lines.append("  标量面与分布面无变化")
    for label, d in diff["scalars"].items():
        a, b = d["prev"], d["now"]
        delta = ""
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            delta = f"  (Δ{b - a:+g})"
        lines.append(f"  {label}: {a} → {b}{delta}")
    for sec, delta in diff["dist"].items():
        lines.append(f"  {sec}.dist:")
        for k, d in delta.items():
            lines.append(
                f"    {k}: {d['prev']} → {d['now']}  (Δ{d['now'] - d['prev']:+d})"
            )
    sg = diff["top_sigs"]
    for tag, vals in (("new sigs", sg["new"]), ("gone sigs", sg["gone"])):
        if vals:
            more = f" +{len(vals) - 8}more" if len(vals) > 8 else ""
            lines.append(f"  {tag}: {', '.join(vals[:8])}{more}")
    if sg["moved"]:
        lines.append("  moved sigs:")
        for s, d in list(sg["moved"].items())[:10]:
            lines.append(f"    {s}: {d['prev']} → {d['now']}")
    return "\n".join(lines)


def cmd_scorecard(args) -> int:
    run_dir = _resolve_run_dir(args.dir)
    if run_dir is None:
        print("!! 找不到 stagerun-* run 目", file=sys.stderr)
        return 2
    run_dir = run_dir.resolve()
    rec_dir = _records_dir_of(run_dir)
    if not rec_dir.is_dir():
        print(f"!! 无 records/：{rec_dir}", file=sys.stderr)
        return 2

    cur = _json_run([sys.executable, str(SCORECARD), str(rec_dir), "--json"])
    hist_dir = (
        Path(args.history_dir) if args.history_dir else run_dir / "scorecard-history"
    )
    prev_path = Path(args.prev) if args.prev else None
    if prev_path is None and hist_dir.is_dir():
        snaps = sorted(hist_dir.glob("*.json"))
        prev_path = snaps[-1] if snaps else None
    prev = None
    if prev_path and prev_path.is_file():
        try:
            prev = json.loads(prev_path.read_text())
        except (json.JSONDecodeError, OSError):
            prev = None
    diff = _sc_diff(prev, cur) if prev else None

    if args.save:
        hist_dir.mkdir(parents=True, exist_ok=True)
        dest = hist_dir / f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json"
        dest.write_text(
            json.dumps(cur, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"snapshot -> {dest}", file=sys.stderr)

    if args.as_json:
        print(
            json.dumps(
                {
                    "current": cur,
                    "prev": str(prev_path) if prev_path else None,
                    "diff": diff,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
    else:
        print(_render_sc_diff(prev_path, cur, diff))
    return 0


# ---------------------------------------------------------------- cli


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="wave.py",
        description=(__doc__ or "").strip().splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="\n".join((__doc__ or "").strip().splitlines()[4:21]),
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_run = sub.add_parser(
        "run", help="id 集开波：快照 + rerun-wave.sh dry-run/前台 + 脱管命令行"
    )
    p_run.add_argument("ids_file", nargs="?", help="id 文件（每行一个/逗号分隔）")
    p_run.add_argument(
        "--mech", default=None, help="机制 tag CSV（B01,W45）走 mech_ids.py"
    )
    p_run.add_argument(
        "--rule", default=None, help="rules.yaml 规则名 → mechanisms: 反查"
    )
    p_run.add_argument("--plus-random", type=int, default=0, metavar="N")
    p_run.add_argument("--seed", type=int, default=42)
    p_run.add_argument(
        "--validate", action="store_true", help="mech_ids --validate 透传"
    )
    p_run.add_argument(
        "--stage",
        default="fixloop",
        choices=WAVE_STAGES,
        help="rerun-wave.sh 档位（默认 fixloop）",
    )
    p_run.add_argument(
        "--dir", default=None, help="目标 run 目（缺省最新 stagerun-loop*）"
    )
    p_run.add_argument("--xlat-arm", default="mock")
    p_run.add_argument("--jobs", type=int, default=8)
    p_run.add_argument(
        "--split", action="store_true", help="rerun-wave.sh --split 透传"
    )
    p_run.add_argument("--tag", default=None, help="工作区 tag（缺省由选择器推导）")
    p_run.add_argument("--workspace", default=None, help="显式工作区目录")
    p_run.add_argument(
        "--go", action="store_true", help="前台真跑（缺省 dry-run + 打印 setsid 行）"
    )

    p_pm = sub.add_parser(
        "postmortem", help="波后对账：rundiff + dossier join + sig 分簇"
    )
    p_pm.add_argument(
        "run_dir", nargs="?", default=None, help="run 目（缺省最新 loop）"
    )
    p_pm.add_argument("--workspace", default=None, help="wave run 落的工作区")
    p_pm.add_argument(
        "--baseline", default=None, help="显式 A 侧（含 records/ 的目录）"
    )
    p_pm.add_argument(
        "--ids", default=None, help="显式波次 id 文件（覆盖工作区 ids.txt）"
    )
    p_pm.add_argument("--deep", action="store_true", help="rundiff --deep 透传")
    p_pm.add_argument("--dossier-top", type=int, default=30, help="dossier join 上限")
    p_pm.add_argument("--no-dossier", action="store_true", help="跳过 dossier join")
    p_pm.add_argument("--out-dir", default=None, help="产出目录（缺省工作区/run 目）")

    p_sc = sub.add_parser(
        "scorecard", help="gate_scorecard --json 包装 + 历史快照 diff"
    )
    p_sc.add_argument("dir", nargs="?", default=None, help="run 目或 records/ 目")
    p_sc.add_argument(
        "--save", action="store_true", help="快照存 <run>/scorecard-history/"
    )
    p_sc.add_argument("--prev", default=None, help="显式前次快照路径")
    p_sc.add_argument("--history-dir", default=None, help="快照目录覆盖")
    p_sc.add_argument("--json", action="store_true", dest="as_json", help="机读输出")

    args = ap.parse_args(argv)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "postmortem":
        return cmd_postmortem(args)
    if args.cmd == "scorecard":
        return cmd_scorecard(args)
    return 2


if __name__ == "__main__":
    sys.exit(main())
