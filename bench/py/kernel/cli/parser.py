"""kernel.cli.parser — argparse 树构建叶 (kernel.cli 拆分叶).

``_build_parser`` 是全 CLI 唯一的参数树：init/run/plan/status 顶动词 +
vault/ledger/lake/cache/spec 五个嵌套子动词组 + derive/sweep/prune/
backup/doctor/fsck + ``verbs.REGISTRY`` 自注册分析动词 (有 ``add_args``
的动词自挂参数)。``_add_runlike_flags`` 是 run/plan 共享旗标组
(with_exec 分野：run 多 --resume/--jobs/--detach)。

门面回引名单见 ``kernel.cli._LEAF_EXPORTS``; monkeypatch 锚点归本叶。
"""

from __future__ import annotations

import argparse

from kernel import vault
from kernel.cli.verbs import _lazy_verb, _verb_registry


def _add_runlike_flags(sp, *, with_exec: bool) -> None:
    sp.add_argument("--date", help="run date YYYY-MM-DD (default: UTC today)")
    sp.add_argument("--slug", help="run slug (default: kind, uniquified)")
    sp.add_argument(
        "--param",
        action="append",
        default=[],
        help="spec param k=v (repeatable)",
    )
    sp.add_argument(
        "--replan", action="store_true", help="re-enumerate the frozen plan"
    )
    sp.add_argument(
        "--max-cost",
        type=float,
        default=None,
        help="run-level budget fuse in USD (paid runs: required)",
    )
    sp.add_argument(
        "--regen",
        action="store_true",
        help="request paid-byte regeneration — folds into"
        " --allow-regen (needs --sel + --max-cost + --yes)",
    )
    sp.add_argument("--sel", help="cell selector expression")
    sp.add_argument(
        "--yes", action="store_true", help="confirm destructive/paid actions"
    )
    sp.add_argument(
        "--allow-regen",
        action="store_true",
        help="the only door past the regen gate (§3.6)",
    )
    if with_exec:
        sp.add_argument(
            "--resume",
            action="store_true",
            help="reuse the run dir; done-set continues",
        )
        sp.add_argument(
            "--jobs", type=int, default=4, help="cell executor parallelism (default 4)"
        )
        sp.add_argument(
            "--detach",
            action="store_true",
            help="re-exec detached under locks/detach.lock (R22)",
        )


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bench",
        description="texlate bench — trizone-ledger kernel CLI (§2.1)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the $TEXLATE_BENCH_ROOT zone layout")

    sp = sub.add_parser("run", help="run a spec through the kernel")
    sp.add_argument("spec", help="spec file path or name under bench/py/specs/")
    sp.add_argument("params", nargs="*", help="extra spec params as k=v")
    _add_runlike_flags(sp, with_exec=True)

    sp = sub.add_parser("plan", help="dry-run quote: 5 dedup buckets + regen list")
    sp.add_argument("spec", help="spec file path or name under bench/py/specs/")
    sp.add_argument("params", nargs="*", help="extra spec params as k=v")
    _add_runlike_flags(sp, with_exec=False)

    sp = sub.add_parser("status", help="index reads: runs / cell state / tail")
    sp.add_argument("--run", help="cells whose last_run is RUN")
    sp.add_argument("--id", help="cell state + vault copies for an id")
    sp.add_argument("--tail", type=int, default=None, help="last N ledger events")

    vp = sub.add_parser("vault", help="paid-bytes zone verbs")
    vsub = vp.add_subparsers(dest="vsub", required=True)
    sp = vsub.add_parser("verify", help="three-tier vault check")
    sp.add_argument("--level", default="stat", choices=["stat", "sample", "full"])
    sp = vsub.add_parser("restore", help="vault -> work materialization")
    sp.add_argument("idc")
    sp.add_argument("--arm", required=True)
    sp.add_argument("--variant", default="-")
    sp.add_argument("--altseq", default=None)
    sp.add_argument("--dest", required=True)
    sp.add_argument("--mode", default="copy", choices=["copy", "link"])
    sp = vsub.add_parser("adopt", help="orphan bytes -> quarantine")
    sp.add_argument("dir")
    sp.add_argument("--idc", required=True)
    sp.add_argument("--arm", default="-")
    sp.add_argument("--variant", default="-")
    sp.add_argument("--kind", default="zh", choices=sorted(vault.KINDS))
    sp.add_argument("--reason", default="orphan")
    sp = vsub.add_parser("tombstone", help="register lost bytes")
    sp.add_argument("idc")
    sp.add_argument("--arm", required=True)
    sp.add_argument("--variant", default="-")
    sp.add_argument("--kind", required=True, choices=sorted(vault.KINDS))
    sp.add_argument("--reason", required=True)
    sp.add_argument("--lost-run", default="")
    sp = vsub.add_parser("seed", help="Phase-2 zh-store byte census -> vault")
    sp.add_argument("--manifest", required=True, help="zh-store manifest.jsonl")
    sp.add_argument("--bytes-root", required=True, help="zh-store payload root")
    sp.add_argument("--dry", action="store_true")
    sp = vsub.add_parser(
        "slim",
        help="shrink committed splice leaves to final pdf + "
        "arm json + logs (P3 retention)",
    )
    sp.add_argument("--idc", default=None, help="limit to one id")
    sp.add_argument("--dry", action="store_true")
    sp = vsub.add_parser(
        "cas-link",
        help="hardlink committed leaf files ≥256KiB through "
        "the CAS (retroverb; harvest links new writes)",
    )
    sp.add_argument(
        "--kind",
        default=None,
        choices=sorted(vault.KINDS),
        help="limit to one asset kind",
    )
    sp.add_argument("--idc", default=None, help="limit to one id")
    sp.add_argument("--dry", action="store_true")
    sp = vsub.add_parser(
        "rekey",
        help="intact src-variant paid kinds -> dst-variant "
        "keyspace (default zh,state; free-regen kinds "
        "excluded on purpose)",
    )
    sp.add_argument(
        "--from",
        dest="src",
        required=True,
        help="source variant (e.g. '-' legacy namespace)",
    )
    sp.add_argument(
        "--to", dest="dst", required=True, help="destination variant (e.g. 'v1')"
    )
    sp.add_argument("--arm", default=None, help="limit to one arm")
    sp.add_argument("--idc", default=None, help="limit to one id")
    sp.add_argument("--kinds", default=None, help="comma list, default zh,state")
    sp.add_argument("--dry", action="store_true")

    lp = sub.add_parser("ledger", help="event ledger verbs")
    lsub = lp.add_subparsers(dest="lsub", required=True)
    sp = lsub.add_parser("import", help="import bench.db / jsonl / scan dir")
    sp.add_argument("path")
    sp.add_argument("--run", default=None, help="run name for jsonl files")
    sp.add_argument("--dry", action="store_true")
    sp.add_argument(
        "--manifest", default=None, help="zh-store manifest path (with --bytes-root)"
    )
    sp.add_argument(
        "--bytes-root", default=None, help="zh-store payload root (with --manifest)"
    )
    sp = lsub.add_parser("ingest", help="external writer lane (run='external')")
    sp.add_argument(
        "--external", required=True, help="jsonl file written by an external tool"
    )
    sp.add_argument("--run", default=None, help="run name (default 'external')")
    sp.add_argument("--dry", action="store_true")
    lsub.add_parser("rebuild-index", help="wipe + replay the derived index")
    lsub.add_parser("tail-ingest", help="incremental index catch-up")

    kp = sub.add_parser("lake", help="lazy corpus lake verbs")
    ksub = kp.add_subparsers(dest="ksub", required=True)
    ksub.add_parser("status", help="catalog + capacity summary")
    sp = ksub.add_parser("evict", help="LRU evict toward freed bytes")
    sp.add_argument(
        "--to-free", required=True, help="bytes to free (K/M/G/T suffix ok)"
    )
    sp = ksub.add_parser(
        "evict-done",
        help="evict cells whose paid zh is vaulted "
        "(layoutqc-ok+real-arm zh, or soak-era terminal ok/clean + '-' arm zh)",
    )
    sp.add_argument(
        "--keep-raw",
        action="store_true",
        help="keep the raw/ canonical layer (state raw_only)",
    )
    sp.add_argument("--dry", action="store_true")
    sp = ksub.add_parser("register", help="manifest cells (skeleton rows)")
    sp.add_argument("ids", nargs="*")
    sp.add_argument(
        "--manifests",
        nargs="+",
        default=None,
        help="manifest*.jsonl files or dirs to bulk-seed from",
    )
    sp.add_argument("--dry", action="store_true")
    sp = ksub.add_parser(
        "pin", help="pin cells against eviction (PINNED marker + catalog pinned field)"
    )
    sp.add_argument("ids", nargs="+")
    sp.add_argument(
        "--source", default="arxiv", help="lake source namespace (default arxiv)"
    )
    sp = ksub.add_parser("unpin", help="lift a cell's pin")
    sp.add_argument("ids", nargs="+")
    sp.add_argument("--source", default="arxiv")
    sp = ksub.add_parser("absorb", help="CAS-ify an on-disk corpus tree into the lake")
    sp.add_argument(
        "--root", required=True, help="legacy corpus dir (e.g. bench/corpus)"
    )
    sp.add_argument(
        "--manifests",
        nargs="*",
        default=None,
        help="manifests for the manifested flag (files or dirs)",
    )
    sp.add_argument("--source", default="arxiv")
    sp.add_argument("--dry", action="store_true")

    cp = sub.add_parser("cache", help="global segment-cache verbs (§3.9)")
    csub = cp.add_subparsers(dest="csub", required=True)
    csub.add_parser("status", help="bucket count/bytes/cap + malformed")
    sp = csub.add_parser("evict", help="LRU evict buckets (or enforce cap)")
    sp.add_argument(
        "--to-free",
        default=None,
        help="bytes to free (K/M/G/T suffix ok); omit to "
        "enforce the TEXLATE_CACHE_CAP_GB cap",
    )
    sp = csub.add_parser(
        "rebuild",
        help="vault/state -> bucket(s): replay stored "
        "xlat-state results through segment_key",
    )
    sp.add_argument("--prompt-version", required=True)
    sp.add_argument("--base-url", required=True)
    sp.add_argument("--model", required=True)
    sp.add_argument("--lang", default="zh")
    sp.add_argument(
        "--glossary-json", default=None, help="JSON literal for the glossary key dim"
    )
    sp.add_argument("--context", default="")
    sp.add_argument("--dry", action="store_true")

    sp = sub.add_parser("derive", help="re-run report/projection for a run")
    sp.add_argument("--run", required=True)
    sp.add_argument(
        "--out", default=None, help="output dir (default: run derived/projected)"
    )

    sp = sub.add_parser("sweep", help="the reaper (§2.4)")
    sp.add_argument(
        "--light", action="store_true", help="fast version (the write-command pre-pass)"
    )

    sp = sub.add_parser("prune", help="reduce a run dir to a keep-list")
    sp.add_argument("--run", required=True)
    sp.add_argument(
        "--keep",
        required=True,
        help="comma list: report,events,spec,env,plan,cases,invocations,work,derived",
    )

    sub.add_parser("backup", help="minimal backup tar under backup/")

    sp = sub.add_parser("doctor", help="kernel health checks")
    sp.add_argument(
        "--fix", action="store_true", help="repair what is safely repairable"
    )
    sp.add_argument(
        "--switch-ok",
        action="store_true",
        help="drain gate: kernel idle + no in-flight writers",
    )

    sp = sub.add_parser("fsck", help="deeper consistency check")
    sp.add_argument(
        "--defer-edges", action="store_true", help="skip dangling from_run edge checks"
    )

    spp = sub.add_parser("spec", help="spec authoring helpers")
    ssub = spp.add_subparsers(dest="ssub", required=True)
    ssub.add_parser("list", help="list bench/py/specs/*.py")

    for vname, (_vleaf, vhelp) in _verb_registry().items():
        vsp = sub.add_parser(vname, help=vhelp)
        vmod, _verr = _lazy_verb(vname)
        if vmod is not None and hasattr(vmod, "add_args"):
            vmod.add_args(vsp)

    return p
