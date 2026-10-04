"""ops.status_panel 面板节叶 —— sec_* 各节渲染 + SECTIONS 目录
（status_panel.py 拆分叶）。

门面回引名单见 ``ops.status_panel._LEAF_EXPORTS``。
"""

from __future__ import annotations

import collections
import datetime as dt
import glob
import json
import os
import re
import subprocess
import time
from pathlib import Path

from ops.status_panel.collect import (
    _kernel_index,
    gw_status,
    milestones,
    n200_stats,
    scorecard_data,
    tasks,
)
from ops.status_panel.env import (
    BENCH_ROOT,
    C_CLEAN,
    C_FAIL,
    C_INFO,
    C_PART,
    C_PURPLE,
    C_SKIP,
    N200_PID,
    REPO,
    RUNS_DIR,
    SESSIONS_GLOB,
    STALE_TASK_SECONDS,
    STATUS_COLOR,
    STATUS_ZH,
    TASK_STATUS_COLOR,
    TASK_STATUS_ZH,
)
from ops.status_panel.frag import (
    badge,
    chip,
    hbar,
    minibar,
    stacked,
    table,
)
from ops.status_panel.util import (
    cached,
    esc,
    fmt_age,
    fmt_dur,
    pid_alive,
    run_cmd,
)

# ---------- page sections


def sec_chips() -> str:
    chips: list[str] = []
    sc = scorecard_data()
    gate_ok = sc["gate"] == "PASS"
    chips.append(
        chip(
            "M2 联合 PDF",
            f"{sc['pdf_pct']:.2f}%",
            f"{sc['pdf_n']}/{sc['cells']} · 门槛 ≥90% {sc['gate']}",
            "good" if gate_ok else "bad",
        )
    )
    chips.append(
        chip(
            "clean 率",
            f"{sc['clean_pct']:.2f}%",
            f"{sc['clean_n']}/{sc['cells']}",
        )
    )
    st = n200_stats()
    if st["total"]:
        chips.append(
            chip(
                "n200 进度",
                f"{st['done']}/{st['total']}",
                f"{st['done'] / st['total'] * 100:.0f}% · 已跑 {fmt_dur(st['elapsed'])}",
            )
        )
    else:
        chips.append(chip("n200 进度", "—", "未发现 realn200/e2e run 目录"))
    c = st["chunks"]
    if c["chunks"]:
        ok_ph = not c["leftover_ph"] and not c["fault"]
        chips.append(
            chip(
                "chunk 通过",
                f"{c['ok'] / c['chunks'] * 100:.2f}%",
                f"残留占位符 {c['leftover_ph']}",
                "good" if ok_ph else "bad",
            )
        )
    df_tmp = run_cmd(["df", "-h", "/tmp"], 5).splitlines()  # noqa: S108 —— 监控对象即 /tmp 挂载
    if len(df_tmp) > 1:
        pct = int(re.search(r"(\d+)%", df_tmp[1]).group(1))
        chips.append(
            chip(
                "tmpfs /tmp",
                f"{pct}%",
                f"剩 {df_tmp[1].split()[3]}",
                "bad" if pct >= 80 else "",
            )
        )
    load = Path("/proc/loadavg").read_text().split()
    chips.append(chip("负载", load[0], f"5m {load[1]} · 15m {load[2]}"))
    gw = gw_status()
    chips.append(
        chip(
            "翻译网关",
            "在线" if gw.startswith("可达") else "离线",
            f"{gw} · swe-2-medium",
            "good" if gw.startswith("可达") else "bad",
        )
    )
    return "<div class='chips'>" + "".join(chips) + "</div>"


def sec_milestones() -> str:
    steps = []
    for name, zh, state in milestones():
        cls = {"done": "ms-done", "active": "ms-act", "pending": "ms-pend"}[state]
        extra = ""
        if name == "M2":
            sc = scorecard_data()
            extra = (
                f"<div class='msx'>联合 pdf {sc['pdf_pct']:.2f}% "
                f"(门≥90%) "
                + (
                    badge("PASS", C_CLEAN)
                    if sc["gate"] == "PASS"
                    else badge("FAIL", C_FAIL)
                )
                + "</div>"
            )
        steps.append(
            f"<div class='ms {cls}'><div class='msn'>{esc(name)}</div>"
            f"<div class='mss'>{esc(zh)}</div>{extra}</div>"
        )
    return "<div class='msrow'>" + "<div class='msarr'>→</div>".join(steps) + "</div>"


def sec_tasks() -> str:
    ts = tasks()
    hint = (
        "<div class='cap'>上报：<code>python3 bench/py/ops/task_ping.py "
        "&lt;名&gt; --status running --done N --total M --note …"
        "</code> · 完结 <code>--finish</code> · 撤下 <code>--remove</code>"
        "（看板目录 $TEXLATE_BENCH_ROOT/state/status-panel/tasks.d）</div>"
    )
    if not ts:
        return hint + "<div class='prow'>看板为空</div>"
    rows = []
    now = time.time()
    for t in ts:
        status = t.get("status", "?")
        stale = (
            status in ("starting", "running", "blocked")
            and now - t.get("ts", now) > STALE_TASK_SECONDS
        )
        total, done = t.get("total") or 0, t.get("done") or 0
        prog = minibar(done, total) if total else esc(done)
        sb = badge(
            TASK_STATUS_ZH.get(status, status), TASK_STATUS_COLOR.get(status, C_SKIP)
        )
        if stale:
            sb += " " + badge("静默>15m", C_PART)
        note = str(t.get("note") or "")[:60]
        rows.append(
            [
                f"<b>{esc(t.get('name', '?'))}</b>",
                esc(t.get("owner", "?")),
                prog,
                sb,
                esc(fmt_age(t.get("ts", now))),
                esc(note),
            ]
        )
    return table(["任务", "属主", "进度", "状态", "上报", "备注"], rows) + hint


def sec_n200() -> str:
    st = n200_stats()
    done, total = st["done"], st["total"]
    if not total:
        return "<div class='prow'>runs 表无 e2e_real/realn200 run——批尚未启动。</div>"
    if st["rate_ps"] is not None:
        rate = st["rate_ps"] * 3600
        basis = f"近{fmt_dur(st['rate_span'])}均速"
    else:
        rate = done / st["elapsed"] * 3600 if st["elapsed"] > 0 else 0
        basis = "全程均速"
    eta_s = (total - done) / (rate / 3600) if rate > 0 else 0
    eta_at = dt.datetime.now(tz=dt.UTC).astimezone() + dt.timedelta(seconds=eta_s)
    conc = st["meta"].get("concurrency")
    pid, note = N200_PID, "钉选"
    if not pid_alive(pid):
        # pgrep 模式跟随 run slug（bench run 命令行带 --slug）；run_cmd
        # 无输出哨兵是 "(exit N, no output)"——probe[0] 会是 "(exit"
        # 而非空，须 isdigit 兜底否则 int() 崩坏整节。
        slug = str(st.get("dir") or "").rsplit("/", 1)[-1] or "e2e"
        pat = f"bench.*{re.escape(slug)}"
        probe = run_cmd(["pgrep", "-f", pat], 5).split()
        pid, note = (
            (int(probe[0]), "自动发现")
            if probe and probe[0].isdigit()
            else (0, "未发现")
        )
    alive = pid and pid_alive(pid)
    parts = [
        f"<div class='prow'><b>{done}</b> / {total} 篇 "
        f"({done / total * 100:.1f}%) — 速率 {rate:.1f} 篇/时({basis}) · "
        f"并发 {conc if conc is not None else '?'} · "
        f"已跑 {fmt_dur(st['elapsed'])} · 预计剩余 {fmt_dur(eta_s)} "
        f"(约 {eta_at.strftime('%m-%d %H:%M')}) · "
        f"runner pid {pid or '-'}({note}) "
        + (badge("存活", C_CLEAN) if alive else badge("已退出", C_FAIL))
        + " · 网关 "
        + badge(gw_status(), C_CLEAN if gw_status().startswith("可达") else C_FAIL)
        + f" · 最后写入 {fmt_age(st['mtime'])}</div>"
    ]
    if st["in_flight"]:
        parts.append(
            "<div class='prow'>正在处理："
            + " ".join(f"<code>{esc(i)}</code>" for i in st["in_flight"])
            + f" · 队列待跑 {len(st['queued'])} 篇"
            + (
                "（下批 "
                + " ".join(f"<code>{esc(i)}</code>" for i in st["queued"][:4])
                + "…）"
                if st["queued"]
                else ""
            )
            + "</div>"
        )
    funnel = [
        ("采样", total, C_SKIP),
        ("已产出记录", done, C_INFO),
        ("翻译执行", st["xlat_exec"], C_PURPLE),
        ("pipe-xel 出 PDF", st["pdf_pipe"], C_PART),
        ("联合 PDF(+fixloop)", st["pdf_union"], C_CLEAN),
    ]
    parts.append(
        "<div class='cap'>阶段漏斗</div>"
        + "".join(hbar(k, v, total, c) for k, v, c in funnel)
    )
    parts.append(
        "<div class='cap'>逐篇状态（按完成序）</div>"
        "<div class='strip'>"
        + "".join(
            f"<i style='background:{STATUS_COLOR.get(s, C_SKIP)}' "
            f"title='{esc(i)} · {esc(STATUS_ZH.get(s, s))}'></i>"
            for i, s in st["strip"]
        )
        + "</div>"
    )
    order = ["clean", "partial", "fail"]
    parts.append(
        "<div class='cap'>编译判分</div>"
        + stacked(
            [(STATUS_ZH.get(k, k), st["top"].get(k, 0), STATUS_COLOR[k]) for k in order]
            + [(k, v, C_SKIP) for k, v in st["top"].most_common() if k not in order],
            done,
        )
    )
    c = st["chunks"]
    if c["chunks"]:
        parts.append(
            "<div class='cap'>翻译 chunk</div>"
            + stacked(
                [
                    ("通过", c["ok"], C_CLEAN),
                    ("部分", c["partial"], C_PART),
                    ("故障", c["fault"], C_FAIL),
                    ("跳过", c["skipped"], C_SKIP),
                ],
                c["chunks"],
            )
            + f"<div class='prow'>残留占位符 leftover_ph = "
            f"<b>{c['leftover_ph']}</b>（硬门=0）· "
            f"翻译累计 {st['xlat_secs'] / 60:.0f} 分钟</div>"
        )
    if st["fix"]:
        parts.append(
            "<div class='cap'>fixloop 修复臂 vs base 直编对照"
            f"（各 {sum(st['fix'].values())} 格）</div>"
            "<div class='two'>"
            + stacked(
                [
                    (STATUS_ZH.get(k, k), v, STATUS_COLOR.get(k, C_SKIP))
                    for k, v in st["fix"].most_common()
                ],
                sum(st["fix"].values()),
            )
            + stacked(
                [
                    (STATUS_ZH.get(k, k), v, STATUS_COLOR.get(k, C_SKIP))
                    for k, v in st["base"].most_common()
                ],
                sum(st["base"].values()),
            )
            + "</div>"
        )
    if st["reasons"]:
        mx = st["reasons"].most_common(1)[0][1]
        parts.append(
            "<div class='cap'>非 clean 原因</div>"
            + "".join(hbar(k, v, mx, C_FAIL) for k, v in st["reasons"].most_common(8))
        )
    return "".join(parts)


def sec_kernel() -> str:
    """Trizone-ledger kernel feed — index.sqlite projections + lock
    sentinels + run heartbeats (the v2 supply; the pre-v2 collectors
    below still feed the legacy panel sections)."""
    parts = []
    flags = []
    if (BENCH_ROOT / "PAUSE").exists():
        flags.append(badge("PAUSE", C_FAIL))
    if (BENCH_ROOT / "locks" / "AUTH_DEAD").exists():
        flags.append(badge("AUTH_DEAD", C_FAIL))
    if (BENCH_ROOT / ".kernel-active").exists():
        flags.append(badge("kernel-active", C_INFO))
    parts.append(
        "<div class='prow'>栅栏 "
        + (" ".join(flags) if flags else badge("无闸", C_CLEAN))
        + "</div>"
    )
    ev = BENCH_ROOT / "ledger" / "events.jsonl"
    if ev.exists():
        st = ev.stat()
        parts.append(
            f"<div class='prow'>ledger events.jsonl "
            f"{st.st_size / 1048576:.1f} MiB · 最后写入 {fmt_age(st.st_mtime)}</div>"
        )
    conn = _kernel_index()
    if conn is None:
        return "".join(parts) + "<div class='prow'>index.sqlite 尚未建立</div>"
    try:
        meta = {r[0]: r[1] for r in conn.execute("SELECT key, value FROM meta")}
        dirty = (BENCH_ROOT / "ledger" / ".index-dirty").exists()
        parts.append(
            f"<div class='prow'>index sealed_gen "
            f"<b>{esc(meta.get('sealed_gen', '0'))}</b> · watermark "
            f"{esc(meta.get('watermark', '0'))} · "
            + (badge("dirty", C_FAIL) if dirty else badge("sealed", C_CLEAN))
            + "</div>"
        )
        # 最近 run + heartbeat 活性（heartbeat 文件 15s 一拍）
        rows = conn.execute(
            "SELECT run, kind, ts_start FROM runs ORDER BY ts_start DESC LIMIT 8"
        ).fetchall()
        if rows:
            trs = []
            for run, kind, ts in rows:
                # run = kind/date/slug — heartbeat lives at that path
                hb = BENCH_ROOT / "runs" / str(run) / "heartbeat"
                hb_age = fmt_age(hb.stat().st_mtime) if hb.exists() else "—"
                trs.append(
                    [
                        f"<code>{esc(run)}</code>",
                        esc(kind),
                        esc(fmt_age(ts or 0)),
                        esc(hb_age),
                    ]
                )
            parts.append(table(["run", "kind", "起跑", "心跳"], trs))
        mix = conn.execute(
            "SELECT status, COUNT(*) FROM cells GROUP BY status"
        ).fetchall()
        if mix:
            total = sum(n for _, n in mix)
            parts.append(
                "<div class='cap'>cells 状态面（末条胜）</div>"
                + stacked(
                    [(s, n, STATUS_COLOR.get(s, C_SKIP)) for s, n in mix],
                    total,
                )
            )
        held = conn.execute(
            "SELECT COUNT(*) FROM claims c1 WHERE op='acquire' AND rowid=("
            "SELECT MAX(rowid) FROM claims c2 WHERE "
            "c2.idc=c1.idc AND c2.arm=c1.arm AND c2.variant=c1.variant)"
        ).fetchone()[0]
        if held:
            parts.append(f"<div class='prow'>claims 持有 <b>{held}</b></div>")
    finally:
        conn.close()
    # lake catalog — last-wins state counts
    cat = BENCH_ROOT / "lake" / "corpus" / "catalog.jsonl"
    if cat.is_file():
        states: dict[str, int] = {}
        try:
            for line in cat.read_bytes().splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                idc, state = row.get("idc"), row.get("state")
                if isinstance(idc, str):
                    states[idc] = state or "?"
        except (OSError, json.JSONDecodeError):
            pass
        counts = collections.Counter(states.values())
        if counts:
            parts.append(
                "<div class='cap'>lake catalog</div>"
                + stacked(
                    [
                        (s, n, C_INFO if s == "hydrated" else C_SKIP)
                        for s, n in counts.most_common()
                    ],
                    sum(counts.values()),
                )
            )
    return "".join(parts)


def sec_jobs() -> str:
    out = run_cmd(["ps", "-eo", "pid,etime,%cpu,%mem,args", "--sort", "pid"], 5)
    keep = re.compile(
        r"bench/py/|e2e_real_bench|stagerun|texlate web|status_panel|compilebench"
    )
    drop = re.compile(r"vscode-server|jedi|pylint|lsp_server|ps -eo|grep")
    rows = []
    for line in out.splitlines()[1:]:
        if not (keep.search(line) and not drop.search(line)):
            continue
        f = line.split(None, 4)
        if len(f) < 5:
            continue
        cmd = f[4]
        m = re.search(
            r"(e2e_real_bench\.py --tag \w+|texlate web.*port \d+|"
            r"status_panel\.py|stagerun[^ ]*|compilebench[^ ]*|"
            r"bench/py/[\w./]+)",
            cmd,
        )
        short = m.group(0) if m else cmd[-60:]
        rows.append(
            [
                esc(f[0]),
                esc(f[1]),
                esc(f[2]),
                esc(f[3]),
                f"<code>{esc(short)}</code>",
            ]
        )
    if not rows:
        return "<div class='prow'>没有在跑的 bench 进程</div>"
    return table(["pid", "已运行", "%cpu", "%mem", "命令"], rows)


def sec_sessions() -> str:
    rows = []
    for path in sorted(glob.glob(SESSIONS_GLOB)):
        try:
            s = json.loads(Path(path).read_text())
        except (OSError, json.JSONDecodeError):
            continue
        pid = s.get("pid", 0)
        alive = isinstance(pid, int) and pid_alive(pid)
        status = s.get("status", "?")
        scls = {"busy": C_INFO, "idle": C_CLEAN, "shell": C_PART}.get(status, C_SKIP)
        rows.append(
            (
                {"busy": 0, "idle": 1}.get(status, 2),
                [
                    f"<b>{esc(s.get('name') or s.get('sessionId', '?')[:12])}</b>",
                    badge(status, scls),
                    esc(pid),
                    badge("存活", C_CLEAN) if alive else badge("僵死", C_FAIL),
                    esc(
                        fmt_age(s.get("updatedAt", 0) / 1000)
                        if s.get("updatedAt")
                        else "-"
                    ),
                    f"<code>{esc(s.get('cwd', '?').replace(os.path.expanduser('~') + '/', '~/'))}</code>",
                ],
            )
        )
    rows = [r for _, r in sorted(rows, key=lambda t: t[0])]
    return (
        table(["会话", "状态", "pid", "进程", "活跃", "目录"], rows)
        if rows
        else "无会话文件"
    )


def sec_reports() -> str:
    """runs/ 三层 walk（kind/date/slug）→ 最近 12 个 run + 摘要行。"""
    dirs = (
        [d for d in RUNS_DIR.glob("*/*/*") if d.is_dir()] if RUNS_DIR.is_dir() else []
    )
    dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    rows = []
    for d in dirs[:12]:
        title = ""
        for cand in (
            "report.md",
            "derived/report.md",
            "summary.md",
            "README.md",
            "REPORT.md",
        ):
            f = d / cand
            if f.exists():
                for raw_ln in f.read_text(errors="replace").splitlines():
                    ln = raw_ln.strip().lstrip("#").strip()
                    if ln:
                        title = ln[:90]
                        break
                break
        if not title:
            files = sorted(p.name for p in d.iterdir() if p.is_file())[:3]
            title = "产物: " + ", ".join(files) + ("…" if len(files) == 3 else "")
        rows.append(
            [
                esc(fmt_age(d.stat().st_mtime)),
                f"<code>{esc('/'.join(d.parts[-3:]))}</code>",
                esc(title),
            ]
        )
    return table(["更新", "run", "摘要"], rows)


def sec_scorecard() -> str:
    sc = scorecard_data()
    parts = [
        f"<div class='prow'>cells <b>{sc['cells']}</b> · "
        f"union pdf <b>{sc['pdf_n']}</b> ({sc['pdf_pct']:.2f}%) · "
        f"end-state pdf <b>{sc['end_pdf_n']}</b> ({sc['end_pdf_pct']:.2f}%) · "
        f"clean <b>{sc['clean_n']}</b> ({sc['clean_pct']:.2f}%) · "
        "门≥90%: union "
        + (
            badge("PASS", C_CLEAN)
            if sc["gate"] == "PASS"
            else badge(sc["gate"], C_FAIL)
        )
        + " end-state "
        + (
            badge("PASS", C_CLEAN)
            if sc["end_gate"] == "PASS"
            else badge(sc["end_gate"], C_FAIL)
        )
        + (
            f" · 剔除 reject(n={sc['excl']['n']}): pdf {sc['excl']['pdf']}% "
            f"clean {sc['excl']['clean']}%"
            if sc["excl"]
            else ""
        )
        + "</div>"
    ]
    parts.append(
        "<div class='gatebar'><div class='gfill' "
        f"style='width:{min(sc['pdf_pct'], 100):.2f}%'></div>"
        "<div class='gmark' style='left:90%'></div>"
        f"<span class='gtxt'>pdf {sc['pdf_pct']:.2f}% ｜ 竖线=90% 门</span></div>"
    )
    if sc["end_state"]:
        mx = max(n for _, n in sc["end_state"])
        parts.append(
            "<div class='cap'>终态分布</div>"
            + "".join(
                hbar(
                    k,
                    n,
                    mx,
                    C_CLEAN
                    if "clean" in k
                    else C_PART
                    if "partial" in k
                    else C_FAIL
                    if ("fail" in k or "reject" in k)
                    else C_SKIP,
                )
                for k, n in sc["end_state"]
            )
        )
    if sc["top_sigs"]:
        mx = sc["top_sigs"][0][1]
        parts.append(
            "<div class='cap'>非 clean 标记 top</div>"
            + "".join(hbar(k, n, mx, C_INFO) for k, n in sc["top_sigs"][:12])
        )
    return "".join(parts)


def sec_resources() -> str:
    df_tmp = run_cmd(["df", "-h", "/tmp"], 5).splitlines()  # noqa: S108
    free = run_cmd(["free", "-g"], 5).splitlines()
    load = Path("/proc/loadavg").read_text().split()
    parts = []
    if len(df_tmp) > 1:
        f = df_tmp[1].split()
        pct = int(re.search(r"(\d+)%", df_tmp[1]).group(1))
        parts.append(
            "<div class='cap'>/tmp（usrquota tmpfs，EDQUOT 风险点）</div>"
            + hbar(
                f"/tmp {f[2]}/{f[1]}",  # noqa: S108 —— 监控对象即 /tmp 挂载
                pct,
                100,
                C_FAIL if pct >= 80 else C_PART if pct >= 60 else C_CLEAN,
                f"% · 剩 {f[3]}",
            )
        )
    if len(free) > 1:
        f = free[1].split()
        parts.append(
            "<div class='cap'>内存 GiB</div>"
            + hbar(
                f"已用 {f[2]}/{f[1]}", int(f[2]), int(f[1]), C_INFO, f"G · 可用 {f[6]}G"
            )
        )
    df_repo = run_cmd(["df", "-h", str(REPO)], 5).splitlines()

    def du() -> str:
        try:
            return run_cmd(["du", "-shx", str(REPO)], 30).split()[0]
        except (subprocess.TimeoutExpired, IndexError):
            return "?"

    if len(df_repo) > 1:
        f = df_repo[1].split()
        pct = int(re.search(r"(\d+)%", df_repo[1]).group(1))
        parts.append(
            "<div class='cap'>仓库盘</div>"
            + hbar(
                f"fs {f[2]}/{f[1]}",
                pct,
                100,
                C_FAIL if pct >= 90 else C_PART if pct >= 75 else C_CLEAN,
                f"% · 仓体 {cached('du', 600, du)}",
            )
        )
    parts.append(
        f"<div class='prow'>loadavg {load[0]} / {load[1]} / {load[2]} "
        f"（{load[3]} tasks）</div>"
    )
    return "".join(parts)


def sec_ledger() -> str:
    files = sorted(glob.glob(str(REPO / "docs/research/overseer-*.md")))
    if not files:
        return "无 overseer-*.md"
    path = Path(files[-1])
    tail = path.read_text(errors="replace").splitlines()[-18:]
    return (
        f"<div class='cap'>{esc(path.name)} 尾部</div>"
        f"<pre>{esc(chr(10).join(tail))}</pre>"
    )


SECTIONS = [
    ("里程碑", sec_milestones),
    ("trizone kernel", sec_kernel),
    ("任务看板（agent 上报）", sec_tasks),
    ("实时跑批 · realn200", sec_n200),
    ("M2 门 · scorecard", sec_scorecard),
    ("在跑进程", sec_jobs),
    ("舰队花名册", sec_sessions),
    ("最新产出 runs/", sec_reports),
    ("资源", sec_resources),
    ("台账摘要", sec_ledger),
]
