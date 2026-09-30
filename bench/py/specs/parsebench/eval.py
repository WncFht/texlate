r"""specs.parsebench.eval — 双 stage + spec 装配叶 (parsebench 拆分叶).

``pb_probe`` 湖格分类 + extracted 枚举计量（纯读零湖写，ok 的 metrics
带免 parse 拓扑）；``pb_eval`` needs pb_probe.ok——逐文件测量全量走
per-paper subprocess worker（thread executor 下 ``signal.signal`` 抛
ValueError，30s/文件 SIGALRM 超时是口径本体）。

worker argv 自查: ``__file__`` 在本叶内指向自身——父侧拉起
``python <path> --worker`` 的目标是包入口 ``parsebench/__main__.py``
(带 _BENCH_PY sys.path 立起 + _worker_cli 派发), 故用
``Path(__file__).resolve().with_name("__main__.py")`` 取同包入口,
承单件期「argv 指 parsebench.py 门面」语义。
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from kernel import lake
from kernel.spec import SC_OK_PARTIAL, Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs.parsebench.items import _catalog, _items, _select
from specs.parsebench.topology import (
    find_roots,
    is_non_utf8,
    paper_tags,
    rglob_tex,
)
from texlate.textutil import decode_tex

TIMEOUT_S = 30


def _gate(
    status: str, code: str, cat: str, payload, metrics: dict | None = None
) -> dict:
    """status + 单条 errors + 可选 metrics——sig 由内核 errors[0]
    cat:pay 自动合成（errors[].cat 是自由归因标签非事件 cat，非白名单
    词安全；终态 cat 只来自内核异常映射，这里恒为 None）。"""
    out = {
        "status": status,
        "code": code,
        "errors": [{"code": code, "cat": cat, "payload": payload}],
    }
    if metrics:
        out["metrics"] = metrics
    return out


def _probe(ctx) -> dict:
    """湖格分类 + extracted 枚举计量（纯读零湖写——catalog 状态先分类）。

    ok 的 metrics 除枚举计数外带**免 parse 拓扑**（roots/docclass/multi_doc/
    tags/non_utf8）——roles/primary/orphan_tex 要 parse 才知道，归
    pb_eval 的 worker 域（dossier 的 roles 落点位随之从 probe 挪到
    eval，文件头已注记）。
    """
    cell = lake.cell_dir(ctx.idc)
    st = _catalog().state(ctx.idc)
    metrics: dict = {
        "catalog": st,
        "item": dict(ctx.cell.get("params") or {}),
    }
    if not cell.is_dir():
        return _gate("skip", "absent", "probe", ctx.idc, metrics)
    meta_path = cell / "meta.json"
    has_raw = (cell / "raw").exists()
    has_ext = (cell / "extracted").is_dir()
    if not meta_path.exists() and not has_raw and not has_ext:
        # 空锚 dir——register 为 skeleton 撒的种子：种子不是损坏格。
        return _gate("skip", "skeleton", "probe", "empty anchor dir", metrics)
    if has_raw and not has_ext:
        # raw tier only——合法残缺层终态（旧式这批不在 extracted/ 扫描面）。
        return _gate("partial", "raw_only", "probe", "raw tier only", metrics)
    if st == "empty":
        # catalog 已登记零载荷答案——durable 终态不反复试。
        return _gate(
            "partial", "empty_payload", "probe", "recorded zero-payload", metrics
        )
    if not lake.is_complete(ctx.idc):
        # 载荷在场但 torn（meta 缺/数不符/failed 残格）——可水化修。
        return _gate(
            "error", "torn", "probe", f"incomplete cell (catalog={st})", metrics
        )

    ext = cell / "extracted"
    if not ext.is_dir():
        ext = cell
    try:
        tex_files = sorted(rglob_tex(ext))
        all_files = [p for p in ext.rglob("*") if p.is_file()]
        roots = find_roots(tex_files)
        non_utf8 = [p for p in tex_files if is_non_utf8(p)]
        stripped = "\n".join(
            benchlib.strip_comments(decode_tex(p.read_bytes())) for p in tex_files
        )
        metrics.update(
            {
                "n_tex": len(tex_files),
                "n_files": len(all_files),
                "tex_bytes": sum(p.stat().st_size for p in tex_files),
                "total_bytes": sum(p.stat().st_size for p in all_files),
            }
        )
    except (OSError, UnicodeError) as e:
        return _gate("error", "read_fail", "probe", f"{type(e).__name__}: {e}", metrics)
    metrics.update(
        {
            "roots": [
                {
                    "file": str(r["file"].relative_to(ext)),
                    "cmd": r["cmd"],
                    "class": r["class"],
                    "options": r["options"],
                }
                for r in roots
            ],
            "multi_doc": len(roots) > 1,
            "rootless": not roots,
            "docclass": roots[0]["class"] if roots else None,
            "docclass_options": roots[0]["options"] if roots else None,
            "non_utf8_files": [str(p.relative_to(ext)) for p in sorted(non_utf8)],
            "tags": paper_tags(roots, stripped, non_utf8),
        }
    )
    return {"status": "ok", "metrics": metrics}


def _read_json(p: Path) -> dict | None:
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _read_rows(p: Path) -> list[dict]:
    """容忍截尾坏行的 JSONL 读入——worker 被杀时末行可半写。"""
    rows = []
    try:
        fh = p.open(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    with fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue  # 截尾坏行——丢弃不毁账
            if isinstance(e, dict):
                rows.append(e)
    return rows


def _tot(rows: list[dict]) -> dict:
    """cell 级 ``aggregate()`` 同式小计——键名与旧 tot[*] 一一对应，
    derive verb Σ 即得语料合计（lens 不分摊：逐行 _lens 在 files[] 里，
    分位数由 derive 重组）。"""
    ok = [f for f in rows if f.get("ok")]
    meas = [f for f in ok if "measure_error" not in f]
    recon = {"strict": 0, "normalized": 0, "diverged": 0}
    chunks = leaked = 0
    res_c = res_p = orph = bug1 = 0
    hits: dict[str, int] = {}
    warn: dict[str, int] = {}
    for f in meas:
        ident = f.get("identity")
        if ident in recon:
            recon[ident] += 1
        lk = f["leak"]
        chunks += lk["n_translatable"]
        leaked += lk["n_leaked"]
        for k, v in lk["hits"].items():
            hits[k] = hits.get(k, 0) + v
        res_c += f["fake"]["residue_chunk_ph"]
        res_p += f["fake"]["residue_protect_ph"]
        orph += f["fake"]["n_orphan_chunks"]
        bug1 += f["bug1_ph_tail"]
    for f in rows:
        for k, v in (f.get("warn_kinds") or {}).items():
            warn[k] = warn.get(k, 0) + v
    return {
        "files": len(rows),
        "ok": len(ok),
        "error": len(rows) - len(ok),
        "measure_error": len(ok) - len(meas),
        "strict": recon["strict"],
        "normalized": recon["normalized"],
        "diverged": recon["diverged"],
        "chunks": chunks,
        "leaked_chunks": leaked,
        "hits": hits,
        "warn_kinds": warn,
        "residue_chunk_ph": res_c,
        "residue_protect_ph": res_p,
        "orphan_chunks": orph,
        "bug1_ph_tail": bug1,
    }


def _eval(ctx) -> dict:
    """逐文件测量 = per-paper subprocess worker。

    ``is_complete`` 闸在 ``src_path`` 前（complete 格 hydrate 恒
    fast-path——测量 run 全程零湖写）。worker 产物契约：
    ``paper.json``（拓扑先行）+ ``files.jsonl``（逐行 flush 残留即真账）。
    """
    metrics: dict = {}
    if not lake.is_complete(ctx.idc):
        return _gate(
            "skip",
            "lake_incomplete",
            "upstream",
            "cell incomplete between probe and eval",
            metrics,
        )
    src = ctx.src_path()
    if src is None:
        return _gate("skip", "no_src", "upstream", "src projection failed", metrics)
    try:
        # 盘上实数是 outer timeout 与 rows 比对的权威——upstream_rec 的
        # metrics 在跨 run blob 下只回 marker，靠它会缩死外层闸。
        n_tex_disk = len(rglob_tex(src))
    except OSError as e:
        return _gate("error", "enum_fail", "eval", f"{type(e).__name__}: {e}", metrics)
    wd = ctx.paper_dir() / "pb_eval"
    if wd.exists():
        shutil.rmtree(wd)
    wd.mkdir(parents=True)
    timeout_s = int(ctx.params.get("timeout_s") or TIMEOUT_S)
    outer = timeout_s * max(n_tex_disk, 1) * 2 + 300
    argv = [
        sys.executable,
        # worker 目标是 parsebench/__main__.py——带 sys.path 立起 + _worker_cli
        # 派发（单件期 argv 指 parsebench.py 门面，包化后等价物即 __main__）。
        str(Path(__file__).resolve().with_name("__main__.py")),
        "--worker",
        str(src),
        str(wd),
        ctx.idc,
        str(timeout_s),
    ]
    t0 = time.monotonic()
    killed = False
    rc: int | None = None
    err_tail = ""
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=outer)
        rc = cp.returncode
        err_tail = (cp.stderr or "")[-600:]
    except subprocess.TimeoutExpired as e:
        killed = True
        err = e.stderr
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        err_tail = (err or "")[-600:]
    dur = round(time.monotonic() - t0, 1)

    rows = _read_rows(wd / "files.jsonl")
    paper = _read_json(wd / "paper.json")
    n_tex = int((paper or {}).get("n_tex") or n_tex_disk)

    metrics.update(
        {
            "n_tex": n_tex,
            "n_files": len(rows),  # ≡ 旧 files.jsonl 行数贡献（分母守恒锚）
            "seconds": dur,
            "timeout_s": timeout_s,
            "outer_s": outer,
            "worker_rc": rc,
            "worker_killed": killed,
        }
    )
    if paper is not None:
        for k in (
            "roots",
            "multi_doc",
            "rootless",
            "primary_root",
            "docclass",
            "docclass_options",
            "non_utf8_files",
            "tags",
            "orphan_tex",
            "roles",
            "covered_n",
            "reach_source",
            "tex_bytes",
            "total_bytes",
        ):
            metrics[k] = paper.get(k)
        metrics["n_files_all"] = paper.get("n_files")

    if killed:
        # C 级悬挂兜底杀——有残留行即批中断 partial，零行即 error。
        status = "partial" if rows else "error"
        out = _gate(
            status,
            "worker_timeout",
            "timeout",
            f"killed at outer {outer}s (n_tex={n_tex})",
            metrics,
        )
    elif rc != 0 or paper is None:
        # worker 崩/输出不可读——残留行兜 partial；拓扑已产但零行兜
        # fail（「有 tex 零测量行」终态）；连拓扑都没有 = error。
        if rows:
            status = "partial"
        elif paper is not None:
            status = "fail"
        else:
            status = "error"
        out = _gate(
            status,
            "worker_crash",
            "worker_crash",
            f"rc={rc} {err_tail}".strip()[:400],
            metrics,
        )
    elif n_tex == 0:
        status = "clean"  # paper 零 .tex——census no_mtree→clean 同式
        out = {"status": status, "metrics": metrics}
    elif not rows:
        status = "fail"  # 有 tex 但零测量行产出
        out = _gate(status, "no_rows", "eval", f"n_tex={n_tex} but zero rows", metrics)
    elif len(rows) < n_tex:
        status = "partial"  # 批中断（worker 正常退但行数亏——截尾/写损）
        out = _gate(status, "rows_short", "eval", f"{len(rows)}/{n_tex} rows", metrics)
    else:
        status = "ok"
        out = {"status": status, "metrics": metrics}

    if rows:
        metrics["tot"] = _tot(rows)
        metrics["files"] = rows  # >4KB 自动 $blob offload 到 run derived/blobs
    return out


# ---------------------------------------------------------------- spec

spec = Spec(
    kind="parsebench",
    params={
        "n": Param(int, default=0),
        "seed": Param(int, default=42),
        "ids": Param(str, default="", fp=False),
        "layers": Param(str, default="core", fp=False),
        "only": Param(str, default="", fp=False),
        "timeout_s": Param(int, default=TIMEOUT_S, fp=True),  # 口径参数
    },
    items=_items,
    select=_select,
    freeze_plan=True,
    executor="thread",
    env_probes=["python"],
    code_deps=[
        "src/texlate/latex",
        "src/texlate/textutil",
        "bench/py/specs/_benchlite.py",
        "bench/py/specs/_leak.py",
        "bench/py/specs/parsebench/measure.py",
        "bench/py/specs/parsebench/topology.py",
        "bench/py/specs/parsebench/worker.py",
        "bench/py/specs/parsebench/items.py",
        "bench/py/specs/parsebench/eval.py",
    ],
    lake=True,
    prefetch=False,  # 测量 run 零湖写——is_complete 闸恒在 src_path 前
    eval=False,  # canon 门保留（spec.eval 的 raw-idc 直通是 mixed-id 重演面）
    same_id_serial=True,
    stages=[
        Stage(
            "pb_probe",
            _probe,
            status_class=SC_OK_PARTIAL,
        ),
        Stage(
            "pb_eval",
            _eval,
            needs=[("pb_probe", {"ok"})],
            eval=True,
            # 唯一字母表（ok/partial/clean/fail + 双 retriable）——不为单点造预设。
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "clean": "terminal",
                "fail": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
    ],
)
