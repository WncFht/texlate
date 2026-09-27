"""Report task progress to the status-panel task board.

Writes $TEXLATE_BENCH_ROOT/state/status-panel/tasks.d/<slug>.json
atomically; the panel at http://127.0.0.1:8766/ renders it in the
任务看板 section. Any agent/script can call this — stdlib only.

Examples:
    python3 bench/py/task_ping.py realn200 --status running \
        --done 57 --total 200 --note "xlat arm" --owner texlate-e8
    python3 bench/py/task_ping.py realn200 --finish --note "all pdf"
    python3 bench/py/task_ping.py realn200 --remove
    python3 bench/py/task_ping.py --list
"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    from kernel import paths as _kpaths

    TASKS_DIR = _kpaths.status_panel_dir() / "tasks.d"
except Exception:  # kernel.paths is stdlib-only; fallback mirrors it
    TASKS_DIR = (
        Path(
            os.environ.get(
                "TEXLATE_BENCH_ROOT", Path.home() / ".local" / "share" / "texlate-bench"
            )
        ).expanduser()
        / "state"
        / "status-panel"
        / "tasks.d"
    )
STATUSES = ("starting", "running", "blocked", "done", "failed")


def slugify(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", name).strip("-").lower()
    return slug[:64] or "task"


def task_path(name: str) -> Path:
    return TASKS_DIR / f"{slugify(name)}.json"


def load(name: str) -> dict:
    try:
        return json.loads(task_path(name).read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def report(args: argparse.Namespace) -> Path:
    TASKS_DIR.mkdir(parents=True, exist_ok=True)
    path = task_path(args.name)
    data = load(args.name)
    data["name"] = args.name
    if args.finish:
        data["status"] = "done"
        if data.get("total"):
            data["done"] = data["total"]
        args.status = None
    for key in ("status", "done", "total", "note", "owner", "pid"):
        val = getattr(args, key, None)
        if val is not None:
            data[key] = val
    data.setdefault("status", "running")
    data.setdefault("owner", os.environ.get("TEXLATE_AGENT") or getpass.getuser())
    data["ts"] = time.time()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False) + "\n")
    os.replace(tmp, path)
    return path


def list_tasks() -> int:
    files = sorted(TASKS_DIR.glob("*.json")) if TASKS_DIR.exists() else []
    if not files:
        print("(no tasks)")
        return 0
    now = time.time()
    for f in files:
        try:
            t = json.loads(f.read_text())
        except (OSError, json.JSONDecodeError):
            print(f"{f.stem}: unreadable")
            continue
        prog = (
            f"{t.get('done', 0)}/{t['total']}"
            if t.get("total")
            else str(t.get("done", "-"))
        )
        age = int(now - t.get("ts", now))
        print(
            f"{t.get('name', f.stem):<28} {t.get('status', '?'):<9} "
            f"{prog:<10} {age // 60}m ago  {t.get('owner', '?')}  "
            f"{t.get('note', '')}"
        )
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("name", nargs="?", help="task name (slugified)")
    ap.add_argument("--status", choices=STATUSES)
    ap.add_argument("--done", type=int)
    ap.add_argument("--total", type=int)
    ap.add_argument("--note")
    ap.add_argument("--owner", help="default: $TEXLATE_AGENT or user")
    ap.add_argument("--pid", type=int, help="owning long-run pid (optional)")
    ap.add_argument("--finish", action="store_true", help="mark done")
    ap.add_argument("--remove", action="store_true", help="delete entry")
    ap.add_argument("--list", action="store_true", help="list tasks")
    args = ap.parse_args()

    if args.list:
        return list_tasks()
    if not args.name:
        ap.error("name required (or --list)")
    if args.remove:
        task_path(args.name).unlink(missing_ok=True)
        print(f"removed {args.name}")
        return 0
    path = report(args)
    print(f"task '{args.name}' -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
