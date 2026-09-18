#!/usr/bin/env python3
r"""nightwatch — 长跑批巡检：单次跑一遍，收编全部监控面出一份报告。

收编面：
  1. gwpilot 队列：bench/queue/*.jsonl 任务清单 × bench/work_gwpilot/state/
     <stem>.state.json 进度 × gwpilot 进程活性 × 任务日志最新写入。无 state
     文件 → 报「进度面缺失」；state 标 running 而进程死 → DEAD。
  2. 活跃 run 停滞判（bench/results/ 下 24h 内有动静的目录），两层分离：
       ledger 层 = records/*.jsonl ∪ 顶层 records.jsonl/cases.jsonl——整篇
                   完成粒度，append 节奏天然慢；
       detail 层 = run 子树全体文件最新 mtime——chunk/日志推进粒度。
     两层分离是 09-18 rt1 实证：ledger 7h 无 append 不一定是死批——detail 还在
     推进就是 ACTIVE(ledger-lag)；两层都停 >--stall-min（默认 25min）且宿主
     进程活着 → STALLED；fresh 但找不到宿主 → NO-OWNER（多为已完批，列出不报警）。
  3. 孤儿 fd 判（09-18 rt1 实证坑）：宿主进程持有指向 "(deleted)" 的结果文件
     句柄——append 全进已删 inode，路径侧文件冻在旧快照，进程退出即丢账。
     检出即 CRITICAL，报告附抢救命令（cp /proc/<pid>/fd/<n> <落盘>；读该 fd
     得全文含实时增量，可见文件只是它的旧前缀——今日实证 84 vs 925 行）。
  4. task_ping 看板：status-panel/tasks.d/*.json 汇总；running 超 6h 标
     STALE；条面带 pid 且 pid 已死标 DEAD。
  5. 进程面：/proc 扫 texlate 相关长跑（bench/py 脚本/stagerun/gwpilot/
     pytest/e2e/texlate web），列 pid+etime+命令（api-key 脱敏）。

用法：

  python3 bench/py/nightwatch.py              # 报告到 stdout
  python3 bench/py/nightwatch.py --save       # + 落 bench/results/nightwatch/<ts>.md
  python3 bench/py/nightwatch.py --json       # 机器可读（供 diff/告警接线）

周期挂法（本脚本单次跑完即退、自身无需 setsid；挂周期任务产出报告序列即可，
对齐 09-17 「长跑脱管 + 文件面监控」纪律）：

  # crontab -e ——每 10 分钟一份巡检报告
  */10 * * * * cd ~/src/texlate && python3 bench/py/nightwatch.py --save \
      >> bench/results/nightwatch/cron.log 2>&1

  # 或 systemd --user timer / 车队 CronCreate 周期任务跑同一行。
  # 报告序列可 diff 看增量；--json 供 leader 接告警/看板。

纯 stdlib；系统 python3 直跑，不依赖 venv/三方包/外部命令（进程面走 /proc）。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

PY_DIR = Path(__file__).resolve().parent
ROOT = PY_DIR.parents[1]
RESULTS = ROOT / "bench" / "results"
QUEUE_DIR = ROOT / "bench" / "queue"
GWPILOT_WORK = ROOT / "bench" / "work_gwpilot"
TASKS_D = RESULTS / "status-panel" / "tasks.d"
OUT_DIR = RESULTS / "nightwatch"

#: run 扫描跳过——status-panel/nightwatch 是监控自身产出（常新、非批）；gwpilot
#: 的 run.log 只在任务切换时 append，长任务期间 stagnant 属正常（队列节管）。
SKIP_RUN_DIRS = {"status-panel", "nightwatch", "gwpilot"}

#: ledger 账文件名（run 顶层）；records/ 下所有 *.jsonl 都算 ledger。
LEDGER_TOP_NAMES = ("records.jsonl", "cases.jsonl")

#: 进程面匹配：texlate 相关长跑命令行特征。
PROC_RE = re.compile(
    r"bench/py/|stagerun|gwpilot|e2e_real|e2e_mock|qualbench|fixloop_bench|"
    r"texlate\s+web|pytest|uv run texlate|uv run python bench"
)
#: 只读探针不进进程面（巡检/观察动作本身不该像批跑）。
_PROBE_RE = re.compile(
    r"^\S*(sed|grep|awk|cat|tail|head|find|ls|wc|sort|stat|cp|diff|jq)\b"
)
#: 显示命令提取锚点——剥掉 bash -c wrapper/shell-snapshot 前缀留真命令。
_ANCHOR_RE = re.compile(
    r"(uv run \S|pytest |bench/py/|bash tmp/|nohup |setsid |python3? \S*texlate|texlate web)"
)
_REDACT_RE = re.compile(
    r"(--api-key|--key|--bg-key|api_key=|token=|GWPILOT_BG_KEY=)\s*\S+"
)
_BOARD_STALE_S = 6 * 3600
_WALK_CAP = 60_000  # 单 run 子树文件数上限——超出截断并在报告注明


def _redact(cmd: str) -> str:
    return _REDACT_RE.sub(lambda m: m.group(1) + "***", cmd)


def _display_cmd(cmd: str) -> str:
    """bash -c wrapper（harness shell-snapshot 前缀）→ 剥到首个真命令锚点。"""
    m = _ANCHOR_RE.search(cmd)
    return cmd[m.start() :] if m else cmd


def _fmt_age(age_s: float | None) -> str:
    if age_s is None:
        return "-"
    age_s = max(age_s, 0.0)  # 扫描期间新写入的文件 mtime 可略超前于 now
    if age_s < 120:
        return f"{age_s:.0f}s"
    if age_s < 7200:
        return f"{age_s / 60:.0f}min"
    return f"{age_s / 3600:.1f}h"


def _fmt_etime(age_s: float) -> str:
    h, rem = divmod(int(age_s), 3600)
    return f"{h}h{rem // 60:02d}m" if h else f"{rem // 60}m{rem % 60:02d}s"


def _count_lines(path: Path, cap: int = 512 << 20) -> int:
    """二进制行数（rb 分块）；cap 防疯子文件。"""
    n = 0
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                n += chunk.count(b"\n")
                if f.tell() > cap:
                    return -n  # 负数 = 截断估值
    except OSError:
        return -1
    return n


# ---------------------------------------------------------------- 进程面


def iter_procs() -> list[dict]:
    """/proc 扫描 → [{pid, etime_s, cmd}]；竞态退出的跳过。"""
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
        hz = os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError):
        uptime, hz = 0.0, 100
    out = []
    for p in Path("/proc").iterdir():
        if not p.name.isdigit():
            continue
        try:
            cmd = (
                (p / "cmdline")
                .read_bytes()
                .replace(b"\0", b" ")
                .decode("utf-8", "replace")
                .strip()
            )
            if not cmd:
                continue
            stat = (p / "stat").read_bytes()
            rest = stat[stat.rindex(b")") + 2 :].split()
            etime = max(0.0, uptime - int(rest[19]) / hz)  # field 22 = starttime
            out.append({"pid": int(p.name), "etime_s": etime, "cmd": cmd})
        except (OSError, ValueError, IndexError):
            continue
    return out


def texlate_procs(procs: list[dict]) -> list[dict]:
    me = os.getpid()
    return [
        p
        for p in procs
        if p["pid"] != me
        and PROC_RE.search(p["cmd"])
        and not _PROBE_RE.match(_display_cmd(p["cmd"]))
    ]


def orphan_fds(pid: int) -> list[dict]:
    """进程持有的「已删文件」fd → [{fd, path, lines}]；只报本仓路径下的。

    lines 是读 /proc/<pid>/fd/<n> 的快照行数（读 fd = 新文件描述，offset 0，
    拿到的是含实时 append 的全量——这正是孤儿账的抢救入口）。
    """
    out = []
    try:
        fds = list(Path(f"/proc/{pid}/fd").iterdir())
    except OSError:
        return out
    for fd in fds:
        try:
            target = os.readlink(fd)
        except OSError:
            continue
        if target.endswith(" (deleted)") and str(ROOT) in target:
            orig = target[: -len(" (deleted)")]
            lines = _count_lines(Path(f"/proc/{pid}/fd/{fd.name}"))
            out.append({"fd": int(fd.name), "path": orig, "lines": lines})
    return out


def pid_alive(pid: int) -> bool:
    return pid > 0 and Path(f"/proc/{pid}").exists()


# ---------------------------------------------------------------- gwpilot 队列


def _load_queue(path: Path) -> tuple[list[dict], int]:
    """→ (任务行, 坏行数)。与 gwpilot._load_queue 同口径但不 SystemExit。"""
    tasks, bad = [], 0
    try:
        text = path.read_text()
    except OSError:
        return tasks, -1
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            t = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(t, dict) and t.get("id"):
            tasks.append(t)
        else:
            bad += 1
    return tasks, bad


def queue_section(now: float, procs: list[dict]) -> tuple[list[str], dict]:
    lines: list[str] = ["## gwpilot 队列", ""]
    data: dict = {"queues": [], "pilots": []}

    pilots = [p for p in procs if "gwpilot" in p["cmd"]]
    if pilots:
        for p in pilots:
            lines.append(
                f"- gwpilot 进程: pid={p['pid']} etime={_fmt_etime(p['etime_s'])}"
                f" — `{_redact(_display_cmd(p['cmd']))[:160]}`"
            )
            data["pilots"].append({"pid": p["pid"], "etime_s": p["etime_s"]})
    else:
        lines.append("- **gwpilot 进程不在跑**")

    queues = sorted(QUEUE_DIR.glob("*.jsonl")) if QUEUE_DIR.is_dir() else []
    if not queues:
        lines.append("- 无 bench/queue/*.jsonl")
    for q in queues:
        tasks, bad = _load_queue(q)
        state_path = GWPILOT_WORK / "state" / f"{q.stem}.state.json"
        try:
            state = json.loads(state_path.read_text())
            state_age = round(now - state_path.stat().st_mtime, 1)
        except (OSError, json.JSONDecodeError):
            state, state_age = None, None
        entry = {"queue": q.name, "tasks": len(tasks)}
        lines.append(f"### `{q.relative_to(ROOT)}` — {len(tasks)} 任务")
        if bad == -1:
            lines.append("- ⚠ 队列文件不可读")
        elif bad:
            lines.append(f"- ⚠ 坏行 {bad} 条")
        if state is None:
            lines.append("- **队列进度面缺失**（无 state 文件——尚未被 gwpilot 消费）")
            entry["state"] = "missing"
        else:
            counts: dict[str, int] = {}
            rows = []
            for t in tasks:
                st = state.get(t["id"], {})
                status = st.get("status", "pending")
                counts[status] = counts.get(status, 0) + 1
                rows.append(
                    f"| {t['id']} | {status} | {st.get('attempts', '-')} | "
                    f"{_fmt_age(now - st['ended']) if st.get('ended') else '-'} "
                    f"| {st.get('rc', '-') if status != 'running' else '-'} |"
                )
            lines.append(
                f"- 进度: {' / '.join(f'{k} {v}' for k, v in sorted(counts.items()))}"
                f"（state 文件 {_fmt_age(state_age)}前更新）"
            )
            lines += [
                "",
                "| id | status | attempts | ended | rc |",
                "| --- | --- | --- | --- | --- |",
                *rows,
                "",
            ]
            entry["state"] = counts
        log_dir = GWPILOT_WORK / "logs" / q.stem
        if log_dir.is_dir():
            try:
                logs = sorted(log_dir.glob("*.log"), key=lambda f: -f.stat().st_mtime)
            except OSError:
                logs = []
            if logs:
                lines.append(
                    f"- 最新任务日志 `{logs[0].name}`:"
                    f" {_fmt_age(now - logs[0].stat().st_mtime)}前写入"
                )
        lines.append("")
        data["queues"].append(entry)
    return lines, data


# ---------------------------------------------------------------- run 巡检


def _prefilter_mtime(d: Path) -> float | None:
    """浅层最新 mtime（d 自身 + depth1 + records/* + work/*）——24h 粗筛。"""
    newest: float | None = None

    def see(m: float) -> None:
        nonlocal newest
        if newest is None or m > newest:
            newest = m

    try:
        see(d.stat().st_mtime)
        for e in os.scandir(d):
            try:
                see(e.stat().st_mtime)
            except OSError:
                continue
    except OSError:
        return newest
    for sub in (d / "records", d / "work"):
        try:
            for e in os.scandir(sub):
                try:
                    see(e.stat().st_mtime)
                except OSError:
                    continue
        except OSError:
            continue
    return newest


def _deep_mtime(d: Path, skip: set[Path]) -> tuple[float | None, int, bool]:
    """run 子树全体文件最新 mtime（ledger 文件除外）。→ (mtime, nfiles, capped)"""
    newest: float | None = None
    n = 0
    stack = [d]
    while stack:
        cur = stack.pop()
        try:
            it = list(os.scandir(cur))
        except OSError:
            continue
        for e in it:
            ep = Path(e.path)
            try:
                if e.is_dir(follow_symlinks=False):
                    stack.append(ep)
                    continue
                if ep in skip:
                    continue
                n += 1
                m = e.stat().st_mtime
                if newest is None or m > newest:
                    newest = m
            except OSError:
                continue
            if n > _WALK_CAP:
                return newest, n, True
    return newest, n, False


def run_section(
    now: float, procs: list[dict], stall_s: float, active_s: float
) -> tuple[list[str], dict]:
    lines: list[str] = ["## 活跃 run 巡检", ""]
    data: dict = {"runs": []}
    if not RESULTS.is_dir():
        lines.append("- bench/results/ 不存在")
        return lines, data

    for d in sorted(RESULTS.iterdir()):
        if not d.is_dir() or d.name in SKIP_RUN_DIRS:
            continue
        pre = _prefilter_mtime(d)
        if pre is None or now - pre > active_s:
            continue

        # ledger 层
        ledger: list[Path] = []
        rec_dir = d / "records"
        if rec_dir.is_dir():
            ledger += sorted(rec_dir.glob("*.jsonl"))
        ledger += [f for f in (d / n for n in LEDGER_TOP_NAMES) if f.exists()]
        # skip 集含原始+resolved 两形——scandir 产出非 resolved 路径，symlink
        # 父目录下两者会错配（ledger 漏进 detail 层 → 两级判据失效）
        ledger_set = set(ledger) | {f.resolve() for f in ledger}
        rec_infos = []
        ledger_newest: float | None = None
        for f in ledger:
            try:
                st = f.stat()
            except OSError:
                continue
            rec_infos.append(
                {
                    "file": str(f.relative_to(d)),
                    "lines": _count_lines(f),
                    "mtime": st.st_mtime,
                }
            )
            if ledger_newest is None or st.st_mtime > ledger_newest:
                ledger_newest = st.st_mtime

        # detail 层（全体非 ledger 文件最新 mtime）
        det_newest, det_files, capped = _deep_mtime(d, ledger_set)

        ledger_age = now - ledger_newest if ledger_newest else None
        det_age = now - det_newest if det_newest else None

        # 宿主进程：--dir <本目录> 是写方强匹配；裸子串（--state-root 读者）
        # 降级。stagerun-rt1 实证：qualbench --state-root 读方 cmdline 更长会
        # 抢走 owner 显示。路径后禁止 [\w./-]——否则 rt1-backup 会撞上 rt1。
        rel = str(d.relative_to(ROOT))
        tail = r"(?![\w./-])"
        strong = [
            p
            for p in procs
            if re.search(rf"--dir[ =]{re.escape(rel)}{tail}", p["cmd"])
            or re.search(rf"--dir[ =]{re.escape(str(d))}{tail}", p["cmd"])
        ]
        weak = [
            p
            for p in procs
            if p not in strong and (rel in p["cmd"] or str(d) in p["cmd"])
        ]
        owners = strong or weak
        # uv run 包装与真 worker 常成对——优先非包装（持 fd 干活的那个），
        # 同级取 etime 长者。
        owner = min(
            owners,
            key=lambda p: (p["cmd"].startswith("uv run "), -p["etime_s"]),
            default=None,
        )

        # 孤儿 fd 扫所有关联进程（含弱匹配读方——孤儿句柄不分读写角色）
        orphans = []
        for p in strong + weak:
            for o in orphan_fds(p["pid"]):
                if str(d) in o["path"] or rel in o["path"]:
                    o["pid"] = p["pid"]
                    orphans.append(o)

        verdicts: list[str] = []
        if orphans:
            verdicts.append("**ORPHANED_FD**")
        if owner is None:
            verdicts.append("NO-OWNER")
        elif det_age is not None and det_age <= stall_s:
            verdicts.append("ACTIVE")
            if ledger_age is not None and ledger_age > stall_s:
                verdicts.append(f"ledger-lag {_fmt_age(ledger_age)}（明细在推进）")
        elif ledger_age is not None and ledger_age <= stall_s:
            verdicts.append("ACTIVE")
        else:
            verdicts.append(f"**STALLED>{_fmt_age(stall_s)}**")

        # 无关痛痒的 NO-OWNER 目录（无 ledger 无孤儿——多为昨日已完批产物）
        # 折成一行，不铺 ### 块。
        if owner is None and not rec_infos and not orphans:
            data["runs"].append(
                {"dir": d.name, "verdicts": verdicts, "detail_age_s": det_age}
            )
            lines.append(f"- `{d.name}` — NO-OWNER, detail {_fmt_age(det_age)}前")
            continue

        lines.append(f"### `{d.name}` — {' '.join(verdicts)}")
        lines.extend(
            f"- ledger `{ri['file']}`: {ri['lines']} 行,"
            f" 末次 append {_fmt_age(now - ri['mtime'])}前"
            for ri in rec_infos
        )
        if not rec_infos:
            lines.append("- 无 ledger 账文件")
        files_note = f">{_WALK_CAP} 文件（截断）" if capped else f"{det_files} 文件"
        lines.append(f"- detail: 最新文件 {_fmt_age(det_age)}前（{files_note}）")
        if owner:
            tag = "" if owner in strong else " (弱匹配——读方/引用方)"
            lines.append(
                f"- owner: pid={owner['pid']} etime={_fmt_etime(owner['etime_s'])}"
                f"{tag} — `{_redact(_display_cmd(owner['cmd']))[:140]}`"
            )
        for o in orphans:
            vis = next(
                (ri["lines"] for ri in rec_infos if str(d / ri["file"]) == o["path"]),
                "?",
            )
            lines.append(
                f"- ⚠ pid {o['pid']} fd{o['fd']} → `{o['path']}` **(deleted)**:"
                f" 孤儿已含 {o['lines']} 行（可见文件 {vis} 行）——"
                f"抢救 `cp /proc/{o['pid']}/fd/{o['fd']} <落盘>`"
            )
        lines.append("")
        data["runs"].append(
            {
                "dir": d.name,
                "verdicts": verdicts,
                "ledger": rec_infos,
                "ledger_age_s": ledger_age,
                "detail_age_s": det_age,
                "owner_pid": owner["pid"] if owner else None,
                "orphans": orphans,
            }
        )
    if not data["runs"]:
        lines.append("- 24h 内无活跃 run")
    return lines, data


# ---------------------------------------------------------------- task_ping 看板


def board_section(now: float, procs: list[dict]) -> tuple[list[str], dict]:
    lines: list[str] = ["## task_ping 看板", ""]
    data: dict = {"tasks": []}
    files = sorted(TASKS_D.glob("*.json")) if TASKS_D.is_dir() else []
    if not files:
        lines.append("- (无任务条目)")
        return lines, data
    lines += [
        "| name | status | 进度 | 更新于 | owner | note |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for f in files:
        try:
            t = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            lines.append(f"| {f.stem} | unreadable | | | | |")
            continue
        name = t.get("name", f.stem)
        age = now - t.get("ts", now)
        prog = (
            f"{t.get('done', 0)}/{t['total']}"
            if t.get("total")
            else str(t.get("done", "-"))
        )
        flags = ""
        stale = False
        if t.get("status") == "running":
            pid = t.get("pid")
            pid_live = bool(pid) and pid_alive(int(pid))
            # 交叉验证：pid 活 / 无 pid 但有活进程 cmdline 含名（gwpilot 这类
            # 只在任务切换时 ping、无中途心跳的条目靠这条兜住不算 STALE）
            named_live = any(name in p["cmd"] for p in procs)
            if pid and not pid_live:
                flags += " **pid DEAD**"
            elif age > _BOARD_STALE_S and not (pid_live or named_live):
                flags += " **STALE**"
                stale = True
        lines.append(
            f"| {name} | {t.get('status', '?')}{flags} | {prog}"
            f" | {_fmt_age(age)}前 | {t.get('owner', '?')} | {t.get('note', '')} |"
        )
        data["tasks"].append(
            {
                "name": name,
                "status": t.get("status"),
                "age_s": round(age, 1),
                "stale": stale,
            }
        )
    lines.append("")
    return lines, data


# ---------------------------------------------------------------- 进程面表


def proc_section(procs: list[dict]) -> tuple[list[str], dict]:
    lines = ["## 进程面", "", "| pid | etime | cmd |", "| --- | --- | --- |"]
    lines.extend(
        f"| {p['pid']} | {_fmt_etime(p['etime_s'])}"
        f" | `{_redact(_display_cmd(p['cmd']))[:160]}` |"
        for p in sorted(procs, key=lambda x: -x["etime_s"])
    )
    lines.append("")
    return lines, {
        "procs": [{"pid": p["pid"], "etime_s": round(p["etime_s"], 1)} for p in procs]
    }


# ---------------------------------------------------------------- 汇总


def verdict_section(data: dict) -> list[str]:
    lines = ["## 结论", ""]
    fired = False
    for r in data.get("runs", []):
        vs = " ".join(r["verdicts"])
        if "ORPHANED_FD" in vs:
            lines.append(
                f"- **CRITICAL** `{r['dir']}`: 结果文件被 unlink 后进程仍在写已删"
                f" inode——进程退出即丢账。抢救命令见上节 ⚠ 行（读 fd 得全量含增量）。"
            )
            fired = True
        if "STALLED" in vs:
            lines.append(
                f"- **STALLED** `{r['dir']}`: ledger/detail 两层写面均停超阈值，"
                f"宿主仍活——查其 stdout/日志。"
            )
            fired = True
    pilots = data.get("pilots") or []
    for q in data.get("queues") or []:
        st = q.get("state")
        if isinstance(st, dict) and st.get("running") and not pilots:
            lines.append(
                f"- **DEAD** 队列 `{q['queue']}` state 标 running"
                f" 但无 gwpilot 进程——任务死在路上。"
            )
            fired = True
    stale_board = [t["name"] for t in data.get("tasks", []) if t.get("stale")]
    if stale_board:
        lines.append(
            f"- 看板 STALE（running 超 {_BOARD_STALE_S // 3600}h 且无活体互证）: "
            + ", ".join(stale_board)
        )
    if not fired:
        lines.append("- 无停滞/孤儿/死批告警。")
    return lines


# ---------------------------------------------------------------- main


def build_report(stall_min: float, active_h: float) -> tuple[str, dict]:
    now = time.time()
    procs_all = iter_procs()
    procs = texlate_procs(procs_all)
    stall_s, active_s = stall_min * 60, active_h * 3600

    out: list[str] = [
        f"# nightwatch 巡检 {time.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        f"- 停滞阈值 {stall_min:.0f}min；活跃窗 {active_h:.0f}h；repo `{ROOT}`",
        "",
    ]
    data: dict = {"ts": now}
    sec, d = proc_section(procs)
    out += sec
    data.update(d)
    sec, d = queue_section(now, procs_all)
    out += sec
    data.update(d)
    sec, d = run_section(now, procs, stall_s, active_s)
    out += sec
    data.update(d)
    sec, d = board_section(now, procs)
    out += sec
    data.update(d)
    out += verdict_section(data)
    return "\n".join(out) + "\n", data


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__.splitlines()[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--save", action="store_true", help="报告落 bench/results/nightwatch/"
    )
    ap.add_argument("--json", action="store_true", help="stdout 出机器可读 JSON")
    ap.add_argument("--stall-min", type=float, default=25.0, help="停滞阈值（分钟）")
    ap.add_argument("--active-hours", type=float, default=24.0, help="活跃窗（小时）")
    args = ap.parse_args()

    report, data = build_report(args.stall_min, args.active_hours)
    print(json.dumps(data, ensure_ascii=False, indent=1) if args.json else report)

    if args.save:
        OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUT_DIR / f"{time.strftime('%Y%m%d-%H%M%S')}.md"
        path.write_text(report, encoding="utf-8")
        print(f"saved -> {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
