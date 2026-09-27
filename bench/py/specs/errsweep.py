"""errsweep — the error-sediment sweep as a kernel run (§6 Phase 3).

Wraps the docs/dev/errsweep-runbook.md protocol in kernel mechanics:
the worktree/prompt/env plumbing that scripts/errsweep.sh used to do in
bash becomes cells — the agent session itself is one subprocess cell.

    bench run errsweep             # today's sweep, foreground
    bench run errsweep --detach    # same, detached

Layout (single item, serial chain):

- ``prep``  — fail-closed gates before anything spawns: runbook sha256
  must equal RUNBOOK_SHA256 (the spec is a contract over one runbook
  version — edit the runbook → re-validate → bump the pin), errsweep.env
  must exist (agent creds), claude+git+uv binaries must resolve. Then
  the worktree: ``errsweep/<run-date>`` branch into
  ``~/.local/state/texlate/errsweep-wt-<date>`` (reused when present —
  same-day reruns never stack).
- ``sweep`` — ``claude -p`` inside the worktree with the runbook prompt
  and errsweep.env creds injected (CLAUDECODE stripped), 6h fuse, log at
  derived/sweep.log. rc 0->ok, 124->timeout, else fail.
- ``post``  — the objective post-check (agent self-report doesn't count):
  ``Ruleset.load()`` inside the worktree + report copy present at
  ``~/.local/state/texlate/errsweep-<date>-report.md``.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import time
from pathlib import Path

from kernel import paths
from kernel.spec import Param, Spec, Stage

REPO = Path(__file__).resolve().parents[3]
RUNBOOK = REPO / "docs" / "dev" / "errsweep-runbook.md"
RUNBOOK_SHA256 = "75d893116c44fd492ab4500e327a2f50b53e17c49d8902cb4f06089eb119df62"

PROMPT = (
    "你是 texlate errsweep agent，今天是 {date}，工作目录是分支 "
    "errsweep/{date} 的隔离 worktree。完整工作指令在 "
    "docs/dev/errsweep-runbook.md——先通读再开工。要点：soak run 在 "
    "bench store {bench_root}/runs/soak/<date>/<slug>/ 下（--add-dir "
    "已授权读）；签名榜跑 `bench triage soak/<date>/<slug>` 落 run 的 "
    "derived/tickets.jsonl；回放副本放 {replay}；报告除随分支提交外复制"
    "一份到 {state}/errsweep-{date}-report.md。"
)

# env keys whose values are injected into the agent subprocess — read
# from ~/.config/texlate/errsweep.env; never logged, never emitted.
_ENV_FILE = Path.home() / ".config" / "texlate" / "errsweep.env"
_STRIP_ENV = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT")


def _state_dir() -> Path:
    return Path.home() / ".local" / "state" / "texlate"


def _run_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k not in _STRIP_ENV}
    try:
        for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        pass
    return env


def _paths(ctx) -> dict:
    date = ctx.rundir.date
    state = _state_dir()
    return {
        "date": date,
        "state": state,
        "worktree": state / f"errsweep-wt-{date}",
        "branch": f"errsweep/{date}",
        "replay": state / f"replay-{date}",
    }


def _prep(ctx):
    p = _paths(ctx)
    # runbook version stamp — fail closed on drift (the spec is a
    # contract over this exact runbook; drift means re-validate first)
    try:
        sha = hashlib.sha256(RUNBOOK.read_bytes()).hexdigest()
    except OSError:
        ctx.emit_note(f"runbook unreadable: {RUNBOOK}", level="warn")
        return "fail"
    if sha != RUNBOOK_SHA256:
        ctx.emit_note(
            f"runbook sha drifted ({sha[:12]}… != pinned "
            f"{RUNBOOK_SHA256[:12]}…) — re-validate the spec against the "
            "new runbook, then bump RUNBOOK_SHA256",
            level="warn",
        )
        return "fail"
    missing = [b for b in ("claude", "git", "uv") if shutil.which(b) is None]
    if missing:
        ctx.emit_note(f"missing binaries: {', '.join(missing)}", level="warn")
        return "fail"
    if not _ENV_FILE.is_file():
        ctx.emit_note(f"agent creds env absent: {_ENV_FILE}", level="warn")
        return "fail"

    p["replay"].mkdir(parents=True, exist_ok=True)
    wt, br = p["worktree"], p["branch"]
    reused = wt.is_dir()
    if not reused:
        has_branch = (
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(REPO),
                    "show-ref",
                    "--verify",
                    "--quiet",
                    f"refs/heads/{br}",
                ]
            ).returncode
            == 0
        )
        cmd = (
            ["git", "-C", str(REPO), "worktree", "add", str(wt), br]
            if has_branch
            else ["git", "-C", str(REPO), "worktree", "add", str(wt), "-b", br, "HEAD"]
        )
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            ctx.emit_note(f"git worktree add failed: {r.stderr.strip()}", level="warn")
            return "error"
    ctx.emit(
        {
            "stage": "prep",
            "metric": "sweep_prep",
            "worktree": str(wt),
            "branch": br,
            "reused": int(reused),
            "replay": str(p["replay"]),
            "runbook_sha": sha[:16],
        }
    )
    return "ok"


def _sweep(ctx):
    p = _paths(ctx)
    wt = p["worktree"]
    if not wt.is_dir():
        return "error"
    log = ctx.rundir.derived() / "sweep.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    prompt = PROMPT.format(
        date=p["date"],
        root=REPO,
        bench_root=paths.root(),
        replay=p["replay"],
        state=p["state"],
    )
    timeout_s = int(ctx.params.get("timeout_s", 6 * 3600))
    t0 = time.time()
    with open(log, "w", encoding="utf-8") as lf:
        try:
            r = subprocess.run(
                [
                    "timeout",
                    f"{timeout_s}s",
                    "claude",
                    "-p",
                    prompt,
                    "--dangerously-skip-permissions",
                    "--add-dir",
                    str(Path.home() / ".texlate"),
                    "--add-dir",
                    str(REPO),
                    "--add-dir",
                    str(paths.root()),
                ],
                cwd=wt,
                env=_run_env(),
                stdout=lf,
                stderr=subprocess.STDOUT,
                timeout=timeout_s + 120,
            )
            rc = r.returncode
        except subprocess.TimeoutExpired:
            rc = 124
    dur = round(time.time() - t0, 1)
    ctx.emit(
        {
            "stage": "sweep",
            "metric": "sweep_agent",
            "rc": rc,
            "dur_s": dur,
            "log": str(log),
        }
    )
    if rc == 0:
        return "ok"
    if rc == 124:
        return {"status": "fail", "cat": "timeout"}
    return "fail"


def _post(ctx):
    p = _paths(ctx)
    wt = p["worktree"]
    r = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-c",
            ("from texlate.compile.fixloop.ruleset import Ruleset; Ruleset.load()"),
        ],
        cwd=wt if wt.is_dir() else REPO,
        capture_output=True,
        text=True,
        timeout=300,
    )
    ruleset_ok = r.returncode == 0
    report = p["state"] / f"errsweep-{p['date']}-report.md"
    ctx.emit(
        {
            "stage": "post",
            "metric": "sweep_post",
            "ruleset_ok": int(ruleset_ok),
            "report_copy": int(report.is_file()),
            "ruleset_err": (r.stderr or "")[-400:] if not ruleset_ok else None,
        }
    )
    if not ruleset_ok:
        ctx.emit_note(
            "post-check: Ruleset.load FAIL — sweep may have poisoned the ruleset",
            level="warn",
        )
    return "ok" if ruleset_ok else "fail"


spec = Spec(
    kind="errsweep",
    eval=True,
    items=[{"id": "sweep"}],
    params={"timeout_s": Param(type=int, default=6 * 3600)},
    stages=[
        Stage(
            "prep",
            _prep,
            status_class={"ok": "terminal", "fail": "terminal", "error": "retriable"},
        ),
        Stage(
            "sweep",
            _sweep,
            needs=[("prep", {"ok"})],
            status_class={"ok": "terminal", "fail": "terminal", "error": "retriable"},
        ),
        Stage(
            "post",
            _post,
            needs=[("sweep", {"ok", "fail"})],
            status_class={"ok": "terminal", "fail": "terminal", "error": "retriable"},
        ),
    ],
)
