r"""stage_ingest.py — stagerun ``ingest`` stage：corpus_v3 物化副本 → work/{id}/src/。

已物化条目 copytree；未物化记 stub 记录（IA 拉取实现归数据侧——可拉取相
记 skip `ia_fetch_unwired` 下轮重试，stub/pdf/error 格式或无 item 记
reject）。契约见 stagerun.py 模块 docstring。
"""

from __future__ import annotations

import shutil
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import TYPE_CHECKING

import stagerun_lib as sl

from texlate.compile.inject import find_main_tex

if TYPE_CHECKING:
    import argparse
    from pathlib import Path


def _ingest_copy(pid: str, out_dir: Path) -> dict:
    """已物化条目：corpus_v3/{id}/extracted/ → work/{id}/src/。"""
    t0 = time.monotonic()
    rec = sl.base_rec(pid, "ingest", "-")
    src_corp = sl.CORPUS / pid / "extracted"
    dst = sl.workdir(out_dir, pid) / "src"
    if not src_corp.is_dir():
        rec["errors"] = [
            {"code": "no_extracted", "cat": "ingest", "payload": str(src_corp)}
        ]
        rec["status"] = "error"
        return sl.finish_rec(rec, t0)
    if dst.exists():
        shutil.rmtree(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src_corp, dst)
    n_files = sum(1 for p in dst.rglob("*") if p.is_file())
    main = find_main_tex(dst)
    rec["status"] = "ok"
    rec["metrics"] = {
        "n_files": n_files,
        "main_tex_guess": main.relative_to(dst).as_posix() if main else None,
        "source": "cache",
        "sha256_ok": None,
    }
    return sl.finish_rec(rec, t0)


def _missing_rec(entry: dict) -> dict:
    """未物化条目的 stub 记录。

    IA 拉取实现归数据侧（见 stagerun.py docstring）：可拉取相（有 item/member）
    记 skip `ia_fetch_unwired` 留下轮重试；stub/pdf/error 格式或无
    item 的记 reject（本路径永不可解）。metrics 四键与 cache 路径同形。
    """
    t0 = time.monotonic()
    pid, fmt, ch = entry["id"], entry.get("format"), entry.get("channel")
    r = sl.base_rec(pid, "ingest", "-")
    r["metrics"] = {
        "n_files": 0,
        "main_tex_guess": None,
        "source": "ia" if entry.get("item") else None,
        "sha256_ok": None,
    }
    if fmt in ("stub", "pdf", "error") or not entry.get("item"):
        r["status"] = "reject"
        code = (
            f"{fmt}_format"
            if fmt in ("stub", "pdf", "error")
            else ("eprint_fetch_unwired" if ch == "arxiv_eprint" else "no_item")
        )
        # cat=code：sig 要能分流 stub_format/eprint_fetch_unwired 等
        r["errors"] = [{"code": code, "cat": code, "payload": entry.get("member")}]
    else:
        r["status"] = "skip"
        # cat=code 同 reject 约定；payload 只到 item 级——triage sig 按 IA
        # item 聚类（一个 tar 一个工单），member 由 id 回 manifest 查。
        r["errors"] = [
            {
                "code": "ia_fetch_unwired",
                "cat": "ia_fetch_unwired",
                "payload": f"item={entry['item']}",
            }
        ]
    return sl.finish_rec(r, t0)


def stage_ingest(
    args: argparse.Namespace,
    out_dir: Path,
    ids: list[str],
    entries: list[dict],
    log: sl.RecLog,
) -> None:
    by_id = {e["id"]: e for e in entries}
    cached, missing = [], []
    for pid in ids:
        if log.is_done(pid, "-", recode=args.recode) and not args.rerun:
            continue
        if (sl.CORPUS / pid / "extracted").is_dir():
            cached.append(pid)
        else:
            missing.append(by_id.get(pid) or {"id": pid})
    print(
        f"ingest: {len(cached)} cached + {len(missing)} unmaterialized "
        f"(jobs={args.jobs})",
        flush=True,
    )
    done_n = 0
    for e in missing:
        r = _missing_rec(e)
        log.append(r)
        done_n += 1
        print(f"  [{done_n}] {r['id']} -> {r['status']}", flush=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = {ex.submit(_ingest_copy, pid, out_dir): pid for pid in cached}
        for fut in as_completed(futs):
            try:
                r = fut.result()
            except Exception as e:
                r = sl.crash_rec(futs[fut], "ingest", "-", e, time.monotonic())
            log.append(r)
            done_n += 1
            print(f"  [{done_n}] {r['id']} -> {r['status']}", flush=True)
