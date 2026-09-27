"""corpus_sw — scholarweave/arxiv-latex (HF) 通道适配器 + dev_recent 层 builder。

``bench/py/corpus/build_sw_layer.py`` 的 spec 化移植：scholarweave 是唯一免费
的 2025+ 批量 LaTeX 源（47 个 parquet 分片、~9.6GB/片、按月续更），行组
yymm_id 有序——footer 统计圈出近期行组，列投影 range-GET 免整片下载。

单 item（``corpus-sw``）串行五段链，每段对应旧子命令：

- ``footers``   分片 footer → durable/sw/footers/{n}.json + footers.json
- ``pool``      近期行组 [id,yymm_id,categories,license] 列投影 → pool.jsonl
- ``assign``    三层分流：sw 臂 ~1 行组/月组内采样；eprint 臂按月均匀切
                holdout/dev_recent id 清单 → assign_*.jsonl（durable，
                layers spec 经 metrics 里的路径做 ids_file 输入）
- ``rehydrate`` 行组级 latex 列 → FILE: 拆包 → lake.hydrate 逐 id 落格 +
                manifest_dev_recent.jsonl 追加（repo-tracked 选择层）
- ``report``    manifest 聚合 → metrics

湖格契约（不变式，下游编译 spec 的消费谓词）：channel=hf_scholarweave,
item=分片名, member=id, raw/raw.tar.gz=重打包文本树, meta
figures_stripped:true（无二进制图——编译臂走 \\includegraphics stub 而非
missing_file 膨胀）+ catalog row regen_cost=network（raw 是重打包树，
驱逐永不先逐它）。

HF 纪律：pyarrow/fsspec 不在项目 venv——所有 HF 触网动作走 env 白名单
{PATH,HOME} 的 ``uv run --with pyarrow --with "fsspec[http]" python
<本文件> --worker`` 子进程（代理 env 泄漏 → SSL EOF 前科，本机+archbox
双实证）。worker 子命令见 ``_worker_cli``；父进程从不 import 这两个包。

断点/续跑：footers/pool_parts/assign_* 全在 ``lake/durable/sw/``（跨 run
存活——ctx.workspace() 是 run 级 scratch）；rehydrate done 集 =
manifest_dev_recent ids ∪ 其他 manifest ids ∪ 已 complete 湖格，逐 rg
成功才推进；hydrate 到 manifest 追加之间的崩溃窗由「complete 但未上榜 →
从 meta.json 重建行」自愈。

蓄意 delta（相对 build_sw_layer.py）：
- meta.features 减配为 {docclasses, docstyle, docstyle_opts, docclass_opts,
  tex_roots, non_utf8}——tex_roots 口径逐字节同源（同 DOCCLASS_RX + 同
  strip_comments），保 main_tex_sha256 语义；input_depth/flags_*/
  signatures 的机器（FLAG_RX/eval_signatures/input_depth 依赖网）未移植，
  无任何下游读 features。
- taken 集 = manifest*.jsonl ids ∪ 湖格 complete 判定（双侧 canon 归一——
  mixed-id-forms 前科）；旧 corpus_ids 只读 manifest。
- raw 落 ``{cell}/raw/raw.tar.gz``（新湖规范——_populate_from_raw 单 tar
  直解），旧式 cell 根 raw.tar.gz 归 importer 管。
- footers.json 始终是「已缓存分片的最大编目」；--shards 收窄只作用于
  抓取与 pool/rehydrate 行组过滤，不把编目写窄。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tarfile
import time
from collections import Counter, defaultdict
from pathlib import Path

# worker 裸跑 ``python specs/x.py --worker`` 时 bench/py 不在
# sys.path——先立起才够得着 specs.*（load_spec 径下幂等）。
_BENCH_PY = str(Path(__file__).resolve().parents[1])
if _BENCH_PY not in sys.path:
    sys.path.insert(0, _BENCH_PY)

from kernel import fsutil, idnorm, lake, paths
from kernel.spec import Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

ROOT = Path(__file__).resolve().parents[3]
CORPUS = Path(os.environ.get("TEXLATE_CORPUS", str(ROOT / "bench/corpus")))
MANIFEST_OUT = CORPUS / "manifest_dev_recent.jsonl"

SHARDS = 47
DATASET = "scholarweave/arxiv-latex"
SHARD_URL = (
    "https://huggingface.co/datasets/"
    + DATASET
    + "/resolve/main/arxiv_part_{:04d}.parquet"
)
CHANNEL = "hf_scholarweave"
LAYER = "dev_recent"
PICK_REASON = "dev_recent_sw"
RG_ATTEMPTS = 3

# cat_group 词表对齐 frame（primary_cat 前缀 → 8 组；2501+ 只见现代类目）
_CAT_GROUP = {
    "eess": "eess-stat-etc",
    "stat": "eess-stat-etc",
    "nucl-ex": "nucl",
    "nucl-th": "nucl",
    "quant-ph": "quant-ph",
}
_HEP_PHYS = {"hep-ph", "hep-th", "hep-ex", "hep-lat", "gr-qc", "physics"}
_GROUPS = {"cs", "math", "cond-mat", "astro-ph"}

FILE_MARK = re.compile(r"^={10,}\r?\nFILE: (.+?)\r?\n={10,}\r?\n", re.MULTILINE)
DOCCLASS_RX = re.compile(
    r"\\(documentclass|documentstyle)\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}",
    re.DOTALL,
)
TEXT_EXT = {
    ".tex",
    ".sty",
    ".cls",
    ".bbl",
    ".bib",
    ".txt",
    ".def",
    ".clo",
    ".cfg",
    ".ltx",
    ".dtx",
    ".ins",
    ".fd",
    ".bst",
    ".mf",
    ".mac",
}

# ---------------------------------------------------------------- 小工具


def _sw() -> Path:
    """durable builder zone——跨 run 存活的 footers/pool_parts/assign_*。"""
    return paths.lake_durable_dir() / "sw"


def _canon(raw) -> str:
    """双侧归一：canon 可解 → idc，否则原样（mixed-id-forms 前科）。"""
    res = idnorm.canon_id(str(raw))
    return res.idc if res.ok and res.idc else str(raw)


def _iter_jsonl(path: Path):
    """容忍截尾坏行的 JSONL 逐行读。"""
    try:
        with open(path, encoding="utf-8") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue
    except OSError:
        return


def _atomic_text(path: Path, text: str) -> None:
    fsutil.atomic_write(path, text.encode("utf-8"))


def strip_comments(tex: str) -> str:
    r"""去注释：``\X`` 先吃两字符，裸 ``%`` 删到行尾（保留换行）。不感知
    verbatim——benchlib 同源副本（benchlib 死在 Wave-F，新 spec 不引它）。"""
    out, i, n = [], 0, len(tex)
    while i < n:
        c = tex[i]
        if c == "\\":
            out.append(tex[i : i + 2])
            i += 2
            continue
        if c == "%":
            k = tex.find("\n", i)
            if k < 0:
                break
            out.append("\n")
            i = k + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def yymm_recent(yymm_id: str | None, min_yymm: str) -> bool:
    """yymm_id 前 4 位 ∈ [min_yymm, 2699]——裸词表比较会把 "9xxx" 旧年代和
    非数字前缀放进来。"""
    s = (yymm_id or "")[:4]
    return s.isdigit() and int(min_yymm) <= int(s) <= 2699


def cat_group_of(categories: str) -> str:
    """sw categories 首类 → frame cat_group 词表。"""
    pc = (categories or "").split()[0] if categories else ""
    if pc in _CAT_GROUP:
        return _CAT_GROUP[pc]
    base = pc.split(".", 1)[0]
    if base in _HEP_PHYS:
        return "hep-phys"
    if base in _GROUPS:
        return base
    return "other"


def shard_name(n: int) -> str:
    return f"arxiv_part_{n:04d}.parquet"


def split_files(latex: str) -> dict[str, str]:
    """==== FILE: 标记拆包 → {relpath: text}（首个标记前内容丢弃）。"""
    out: dict[str, str] = {}
    marks = list(FILE_MARK.finditer(latex))
    for idx, m in enumerate(marks):
        name = m.group(1).strip()
        end = marks[idx + 1].start() if idx + 1 < len(marks) else len(latex)
        body = latex[m.end() : end]
        # 路径消毒：禁绝对路径/../；重名追加序号
        parts = [p for p in name.replace("\\", "/").split("/") if p not in ("", ".")]
        if not parts or any(p == ".." for p in parts):
            name = f"file_{idx}"
        else:
            name = "/".join(parts)
        base, n = name, 2
        while name in out:
            stem, dot, suf = base.rpartition(".")
            name = f"{stem}_{n}{dot}{suf}" if dot else f"{base}_{n}"
            n += 1
        out[name] = body
    return out


def _reduced_features(files: dict[str, str]) -> dict:
    """减配形态特征：docclasses/docstyle*/tex_roots/non_utf8。

    tex_roots 与 build_corpus_v3._texts_features 同口径（剥注释后含
    \\documentclass/\\documentstyle 的 .tex relpath）——main_tex_sha256
    的唯一消费点。input_depth/flags*/signatures 未移植（见模块 doc）。
    """
    tex_texts = {p: t for p, t in files.items() if Path(p).suffix.lower() == ".tex"}
    blob_txt = strip_comments("\n".join(tex_texts.values()))
    dcls_ms = list(DOCCLASS_RX.finditer(blob_txt))
    roots = sorted(
        p for p, t in tex_texts.items() if DOCCLASS_RX.search(strip_comments(t))
    )
    return {
        "docclasses": sorted({m.group(3).strip() for m in dcls_ms}),
        "docstyle": any(m.group(1) == "documentstyle" for m in dcls_ms),
        "docstyle_opts": sorted(
            o.strip()
            for m in dcls_ms
            if m.group(1) == "documentstyle" and m.group(2)
            for o in m.group(2).split(",")
            if o.strip()
        ),
        "docclass_opts": sorted(
            o.strip()
            for m in dcls_ms
            if m.group(1) == "documentclass" and m.group(2)
            for o in m.group(2).split(",")
            if o.strip()
        ),
        "tex_roots": roots,
        # parquet latex 列已是合法 str——旧口径（重读 extracted 树 decode
        # 探测）在本通道恒 False，字段保留只为 schema 对齐。
        "non_utf8": False,
    }


# ---------------------------------------------------------------- HF 子进程
#
# 父进程永远不 import pyarrow/fsspec——它们只活在 uv 临时环境里的 --worker
# 进程中。env 白名单 {PATH,HOME}：代理变量泄漏即 SSL EOF（可复现前科）。


def _hf_env() -> dict:
    return {
        "PATH": os.environ.get("PATH", ""),
        "HOME": os.environ.get("HOME", ""),
    }


def _hf_argv(*wargs) -> list[str]:
    return [
        "uv",
        "run",
        "--with",
        "pyarrow",
        "--with",
        "fsspec[http]",
        "python",
        str(Path(__file__).resolve()),
        "--worker",
        *[str(w) for w in wargs],
    ]


def _hf_run(wargs, timeout_s: int):
    """一次 worker 调用 → (rc, stderr_tail)。TimeoutExpired → rc=124。"""
    try:
        cp = subprocess.run(
            _hf_argv(*wargs),
            env=_hf_env(),
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        return cp.returncode, (cp.stderr or "")[-600:]
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    except OSError as e:
        return 127, f"{type(e).__name__}: {e}"


# ---------------------------------------------------------------- worker 体
# （只在 uv env 里跑——import gate 在函数内，缺包 = 显式失败非静默 skip）


def _w_footer(shard: int, out: Path) -> int:
    """一分片 footer → {rows, rgs:[{i,rows,ymin,ymax,mb}]} 写 out.json。"""
    import fsspec
    import pyarrow.parquet as pq

    with fsspec.open(SHARD_URL.format(shard), "rb") as f:
        md = pq.ParquetFile(f).metadata
    cidx = next(
        i for i in range(md.num_columns) if md.schema.column(i).name == "yymm_id"
    )
    rgs = []
    for i in range(md.num_row_groups):
        rg = md.row_group(i)
        try:
            st = rg.column(cidx).statistics
            rgs.append(
                {
                    "i": i,
                    "rows": rg.num_rows,
                    "ymin": st.min,
                    "ymax": st.max,
                    "mb": round(rg.total_byte_size / 1e6, 1),
                }
            )
        except Exception:
            rgs.append({"i": i, "rows": rg.num_rows, "ymin": "", "ymax": ""})
    _atomic_text(out, json.dumps({"rows": md.num_rows, "rgs": rgs}))
    return 0


def _w_pool(shard: int, rg: int, min_yymm: str, out: Path) -> int:
    """一行组 [id,yymm_id,categories,license] 列投影 → 过滤后 rows jsonl。"""
    import fsspec
    import pyarrow.parquet as pq

    cols = ["id", "yymm_id", "categories", "license"]
    with fsspec.open(SHARD_URL.format(shard), "rb") as f:
        t = pq.ParquetFile(f).read_row_group(rg, columns=cols)
    rows = [
        {
            "id": r["id"],
            "yymm_id": r["yymm_id"],
            "cats": r["categories"],
            "lic": r["license"],
            "shard": shard,
            "rg": rg,
        }
        for r in t.to_pylist()
        if yymm_recent(r["yymm_id"], min_yymm)
    ]
    _atomic_text(out, "".join(json.dumps(x) + "\n" for x in rows))
    return 0


def _w_rgrows(shard: int, rg: int, want_file: Path, out: Path) -> int:
    """一行组全列（含 latex）→ 只留 want 集内 id 的行 jsonl。"""
    import fsspec
    import pyarrow.parquet as pq

    want = {
        x.strip()
        for x in want_file.read_text(encoding="utf-8").splitlines()
        if x.strip()
    }
    cols = [
        "id",
        "yymm_id",
        "categories",
        "license",
        "version",
        "created",
        "update_date",
        "latex",
    ]
    with fsspec.open(SHARD_URL.format(shard), "rb") as f:
        t = pq.ParquetFile(f).read_row_group(rg, columns=cols)
    rows = [r for r in t.to_pylist() if r["id"] in want]
    with open(out, "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
            fh.flush()
    return 0


def _worker_cli(argv: list) -> int:
    """``--worker footer <shard> <out>`` /
    ``--worker pool <shard> <rg> <min_yymm> <out>`` /
    ``--worker rgrows <shard> <rg> <want_file> <out>``。"""
    if len(argv) < 2 or argv[1] != "--worker":
        sys.stderr.write(
            "usage: corpus_sw.py --worker footer <shard> <out> | "
            "pool <shard> <rg> <min_yymm> <out> | "
            "rgrows <shard> <rg> <want_file> <out>\n"
        )
        return 2
    op = argv[2]
    try:
        if op == "footer" and len(argv) == 5:
            return _w_footer(int(argv[3]), Path(argv[4]))
        if op == "pool" and len(argv) == 7:
            return _w_pool(int(argv[3]), int(argv[4]), argv[5], Path(argv[6]))
        if op == "rgrows" and len(argv) == 7:
            return _w_rgrows(int(argv[3]), int(argv[4]), Path(argv[5]), Path(argv[6]))
    except ImportError as e:
        sys.stderr.write(f"import gate: {e}\n")
        return 3
    except Exception as e:
        sys.stderr.write(f"worker {op}: {type(e).__name__}: {e}\n")
        return 1
    sys.stderr.write(f"bad worker args: {argv[1:]}\n")
    return 2


# ---------------------------------------------------------------- corpus 账


def _manifest_ids(path: Path) -> set[str]:
    """一 manifest 文件的 canon id 集。"""
    return {_canon(r["id"]) for r in _iter_jsonl(path) if r.get("id")}


def _all_manifest_ids() -> set[str]:
    """bench/corpus/manifest*.jsonl 全行 canon id 并集（taken 一翼）。"""
    out: set[str] = set()
    for mp in sorted(CORPUS.glob("manifest*.jsonl")):
        out |= _manifest_ids(mp)
    return out


def _manifest_row(meta: dict, pid: str, ext: Path | None) -> dict:
    """cell meta (+extracted 树可选) → manifest_dev_recent 行。

    ext=None 时 main_tex_sha256 从 meta.features.tex_roots 单根判定；
    重建路径（湖格在、行不在）与正常路径同一份字段装配。
    """
    roots = (meta.get("features") or {}).get("tex_roots") or []
    main_sha = None
    if ext is not None and len(roots) == 1 and (ext / roots[0]).exists():
        main_sha = hashlib.sha256((ext / roots[0]).read_bytes()).hexdigest()
    return {
        "id": pid,
        "era": meta.get("era"),
        "archive": None,
        "yymm": meta.get("yymm"),
        "cluster_id": meta.get("cluster_id"),
        "layer": LAYER,
        "channel": CHANNEL,
        "item": meta.get("item"),
        "member": pid,
        "blob_sha256": meta.get("raw_sha256"),
        "main_tex_sha256": main_sha,
        "stratum_cell": meta.get("stratum_cell"),
        "cat_group": meta.get("cat_group"),
        "license_class": None,
        "format": "tar",
        "n_files": meta.get("n_files"),
        "n_tex": meta.get("tex_files"),
        "bytes": meta.get("bytes"),
        "pick_reason": PICK_REASON,
        "figures_stripped": True,
    }


# ---------------------------------------------------------------- stages


def _shard_set(ctx) -> set[int] | None:
    raw = str(ctx.params.get("shards") or "").strip()
    if not raw:
        return None
    out = set()
    for tok in raw.split(","):
        t = tok.strip()
        if t:
            out.add(int(t))
    return out or None


def _footers(ctx):
    """47 分片 footer 编目 → durable/sw/footers/{n}.json + footers.json。

    分片缓存存在即跳过（跨 run 增量）；footers.json 每次按盘上缓存全集
    重写——shards 收窄只少抓，不写窄编目。
    """
    if shutil.which("uv") is None:
        return {"status": "error", "errors": [{"cat": "env", "msg": "uv not on PATH"}]}
    sw = _sw()
    fdir = sw / "footers"
    fdir.mkdir(parents=True, exist_ok=True)
    want = _shard_set(ctx) or set(range(1, SHARDS + 1))
    fetched = cached = 0
    for n in sorted(want):
        if not 1 <= n <= SHARDS:
            continue
        out = fdir / f"{n:04d}.json"
        if out.exists():
            cached += 1
            continue
        rc, tail = _hf_run(("footer", n, out), timeout_s=300)
        if rc != 0 or not out.exists():
            ctx.emit(
                {
                    "stage": "footers",
                    "metric": "sw_footer",
                    "shard": n,
                    "rc": rc,
                    "err": tail,
                }
            )
            return {
                "status": "error",
                "errors": [
                    {"cat": "upstream", "msg": f"footer {n:04d} rc={rc}: {tail}"}
                ],
                "metrics": {"shard": n, "fetched": fetched, "cached": cached},
            }
        fetched += 1
        ctx.emit({"stage": "footers", "metric": "sw_footer", "shard": n, "rc": 0})
    cat = {}
    for fp in sorted(fdir.glob("*.json")):
        try:
            cat[int(fp.stem)] = json.loads(fp.read_text())
        except (OSError, ValueError):
            continue
    _atomic_text(sw / "footers.json", json.dumps(cat, indent=1) + "\n")
    min_yymm = str(ctx.params.get("min_yymm") or "2501")
    recent = sum(
        1
        for s in cat.values()
        for r in s["rgs"]
        if yymm_recent(r.get("ymax"), min_yymm)
    )
    return {
        "status": "ok",
        "metrics": {
            "shards": len(cat),
            "fetched": fetched,
            "cached": cached,
            "recent_rgs": recent,
            "footers": str(sw / "footers.json"),
        },
    }


def _recent_rgs(cat: dict, min_yymm: str, shard_set: set[int] | None) -> list[dict]:
    out = [
        {"shard": int(sn), **r}
        for sn, s in cat.items()
        for r in s["rgs"]
        if yymm_recent(r.get("ymax"), min_yymm)
        and (shard_set is None or int(sn) in shard_set)
    ]
    return sorted(out, key=lambda x: (x["ymin"], x["shard"], x["i"]))


def _pool(ctx):
    """近期行组列投影 → durable/sw/pool_parts/{s}_{i}.jsonl + pool.jsonl。"""
    sw = _sw()
    fp = sw / "footers.json"
    if not fp.exists():
        return {"status": "error", "errors": [{"cat": "env", "msg": f"missing {fp}"}]}
    if shutil.which("uv") is None:
        return {"status": "error", "errors": [{"cat": "env", "msg": "uv not on PATH"}]}
    cat = json.loads(fp.read_text())
    min_yymm = str(ctx.params.get("min_yymm") or "2501")
    rgs = _recent_rgs(cat, min_yymm, _shard_set(ctx))
    rg_cap = int(ctx.params.get("rg_limit") or 0)
    if rg_cap > 0:
        rgs = rgs[:rg_cap]
    pdir = sw / "pool_parts"
    pdir.mkdir(parents=True, exist_ok=True)
    n_rows = fetched = cached = 0
    lines: list[str] = []
    for ent in rgs:
        sn, i = ent["shard"], ent["i"]
        cache = pdir / f"{sn:04d}_{i:03d}.jsonl"
        if not cache.exists():
            rc, tail = _hf_run(("pool", sn, i, min_yymm, cache), timeout_s=600)
            if rc != 0 or not cache.exists():
                ctx.emit(
                    {
                        "stage": "pool",
                        "metric": "sw_pool_rg",
                        "shard": sn,
                        "rg": i,
                        "rc": rc,
                        "err": tail,
                    }
                )
                return {
                    "status": "error",
                    "errors": [
                        {"cat": "upstream", "msg": f"pool {sn:04d}/{i} rc={rc}: {tail}"}
                    ],
                    "metrics": {"n_rows": n_rows, "fetched": fetched, "cached": cached},
                }
            fetched += 1
        else:
            cached += 1
        part = [ln for ln in cache.read_text().splitlines() if ln.strip()]
        lines.extend(part)
        n_rows += len(part)
        ctx.emit(
            {
                "stage": "pool",
                "metric": "sw_pool_rg",
                "shard": sn,
                "rg": i,
                "rows": len(part),
            }
        )
    _atomic_text(sw / "pool.jsonl", "\n".join(lines) + ("\n" if lines else ""))
    return {
        "status": "ok",
        "metrics": {
            "n_rows": n_rows,
            "rgs": len(rgs),
            "fetched": fetched,
            "cached": cached,
            "pool": str(sw / "pool.jsonl"),
        },
    }


def _assign(ctx):
    """三层分流：sw 臂 ~1 行组/月组内采样 + eprint 臂 holdout/dev_recent。"""
    sw = _sw()
    pool_path = sw / "pool.jsonl"
    if not pool_path.exists():
        return {
            "status": "error",
            "errors": [{"cat": "env", "msg": f"missing {pool_path}"}],
        }
    rng = random.Random(int(ctx.params.get("seed") or 42))
    n_sw = int(ctx.params.get("n_sw") or 1200)
    n_ho = int(ctx.params.get("n_ep_holdout") or 300)
    n_dr = int(ctx.params.get("n_ep_devrecent") or 300)
    pool = [r for r in _iter_jsonl(pool_path) if r.get("id")]
    taken = _all_manifest_ids()
    pool = [r for r in pool if _canon(r["id"]) not in taken]
    by_month: dict[str, list[dict]] = defaultdict(list)
    for r in pool:
        by_month[r["yymm_id"][:4]].append(r)
    months = sorted(by_month)
    if not months:
        return {
            "status": "error",
            "errors": [{"cat": "empty", "msg": "pool has no months"}],
            "metrics": {"pool": len(pool)},
        }

    # 脱水臂：每月 1 个行组（rg 是该月内连续 id 段），组内均匀采样
    sw_picks: list[dict] = []
    used_ids: set[str] = set()
    per_month = max(1, round(n_sw / len(months)))
    for m in months:
        rows = by_month[m]
        rgs = sorted({(r["shard"], r["rg"]) for r in rows})
        pick_rg = rng.choice(rgs)
        cand = [r for r in rows if (r["shard"], r["rg"]) == pick_rg]
        rng.shuffle(cand)
        for r in cand[:per_month]:
            used_ids.add(r["id"])
            sw_picks.append(
                {
                    "id": r["id"],
                    "yymm": m,
                    "cat_group": cat_group_of(r["cats"]),
                    "shard": r["shard"],
                    "rg": r["rg"],
                }
            )

    # eprint 臂：剩余全池按月分层均匀切 holdout/dev_recent 两段
    ep_pool = [r for r in pool if r["id"] not in used_ids]
    ep_by_month: dict[str, list[dict]] = defaultdict(list)
    for r in ep_pool:
        ep_by_month[r["yymm_id"][:4]].append(r)
    for v in ep_by_month.values():
        rng.shuffle(v)
    per_m_ho = max(1, n_ho // len(months))
    per_m_dr = max(1, n_dr // len(months))
    ho: list[dict] = []
    dr: list[dict] = []
    for m in months:
        cand = ep_by_month.get(m, [])
        ho.extend(
            {"id": r["id"], "yymm": m, "cat_group": cat_group_of(r["cats"])}
            for r in cand[:per_m_ho]
        )
        dr.extend(
            {"id": r["id"], "yymm": m, "cat_group": cat_group_of(r["cats"])}
            for r in cand[per_m_ho : per_m_ho + per_m_dr]
        )
    rng.shuffle(ho)
    rng.shuffle(dr)
    ho, dr = ho[:n_ho], dr[:n_dr]

    out_sw = sw / "assign_sw.jsonl"
    out_ho = sw / "assign_holdout.jsonl"
    out_dr = sw / "assign_dev_recent.jsonl"
    _atomic_text(
        out_sw, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in sw_picks)
    )
    _atomic_text(out_ho, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in ho))
    _atomic_text(out_dr, "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in dr))
    return {
        "status": "ok",
        "metrics": {
            "pool": len(pool),
            "months": len(months),
            "month_first": months[0],
            "month_last": months[-1],
            "n_sw": len(sw_picks),
            "n_ep_holdout": len(ho),
            "n_ep_devrecent": len(dr),
            "assign_sw": str(out_sw),
            "assign_holdout": str(out_ho),
            "assign_dev_recent": str(out_dr),
        },
    }


def _meta_extra(
    r: dict, files: dict[str, str], sha: str, blob_n: int, tex_n: int
) -> dict:
    """湖格 meta.json 的 fetch_fn 贡献——hydrate 自管 idc/source/n_files/
    hydrated_at/run_seq，这里给其余全字段（含 figures_stripped 契约）。"""
    pid = r["id"]
    yymm = r["yymm_id"][:4]
    cg = cat_group_of(r["categories"])
    return {
        "arxiv_id": pid,
        "resolved_version": None,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "era": "new" if "." in pid else "old",
        "archive": None,
        "yymm": yymm,
        "cluster_id": f"SW-{yymm}",
        "year_band": "f_2025plus",
        "layer": LAYER,
        "stratum_cell": f"sw|{yymm}",
        "cat_group": cg,
        "license_class": None,
        "license": r.get("license"),
        "categories": r.get("categories"),
        "channel": CHANNEL,
        "item": shard_name(r["shard"]),
        "member": pid,
        "raw_sha256": sha,
        "raw_file": "raw.tar.gz",
        "format": "tar",
        "tex_files": tex_n,
        "bytes": blob_n,
        "figures_stripped": True,
        "sw": {
            "shard": r["shard"],
            "rg": r["rg"],
            "update_date": r.get("update_date"),
            "version": r.get("version"),
        },
        "features": _reduced_features(files),
        "pick_reason": PICK_REASON,
        "source": CHANNEL,
    }


def _fetch_for(r: dict, files: dict[str, str]):
    """行 + 拆包结果 → lake.hydrate 的 fetch_fn（extracted/ + raw/ 双写）。"""

    def fetch(_idc: str, stage: Path) -> dict:
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w:gz") as tf:
            for name, text in files.items():
                data = text.encode("utf-8", "replace")
                ti = tarfile.TarInfo(name)
                ti.size = len(data)
                tf.addfile(ti, io.BytesIO(data))
        blob = buf.getvalue()
        sha = hashlib.sha256(blob).hexdigest()
        raw = stage / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        (raw / "raw.tar.gz").write_bytes(blob)
        ext = stage / "extracted"
        ext.mkdir(parents=True, exist_ok=True)
        for name, text in files.items():
            fp = ext / name
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(text, encoding="utf-8", errors="replace")
        tex_n = sum(1 for p in files if p.lower().endswith(".tex"))
        return _meta_extra(r, files, sha, len(blob), tex_n)

    return fetch


def _rehydrate(ctx):
    """assign_sw picks → 逐 rg worker 抽 latex → lake.hydrate 落格 + manifest。

    断点口径：done=dev_recent manifest ids；taken=其余 manifest ids；
    complete 湖格未上榜 → meta 重建行（崩溃窗自愈）。n_err>0 → error
    （retriable——done 集让下次 run 只补缺口）。
    """
    sw = _sw()
    apath = sw / "assign_sw.jsonl"
    if not apath.exists():
        return {
            "status": "error",
            "errors": [{"cat": "env", "msg": f"missing {apath}"}],
        }
    if shutil.which("uv") is None:
        return {"status": "error", "errors": [{"cat": "env", "msg": "uv not on PATH"}]}
    picks = [p for p in _iter_jsonl(apath) if p.get("id")]
    done = _manifest_ids(MANIFEST_OUT) if MANIFEST_OUT.exists() else set()
    taken = _all_manifest_ids()  # 含 done——manifest 过的 id 一律不碰
    by_rg: dict[tuple[int, int], list[dict]] = defaultdict(list)
    n_done = n_taken = 0
    for p in picks:
        idc = _canon(p["id"])
        if idc in taken:
            if idc in done:
                n_done += 1
            else:
                n_taken += 1
            continue
        by_rg[(p["shard"], p["rg"])].append(p)

    MANIFEST_OUT.parent.mkdir(parents=True, exist_ok=True)
    limit = int(ctx.params.get("limit") or 0)
    ws = ctx.workspace() / "rgrows"
    ws.mkdir(parents=True, exist_ok=True)
    run_seq = getattr(ctx.rundir, "run_seq", 0) or 0
    cat = lake.LakeCatalog.load()
    n_ok = n_skip = n_err = n_heal = 0
    stop = False
    with MANIFEST_OUT.open("a", encoding="utf-8") as mf:
        for (sn, rgi), plist in sorted(by_rg.items()):
            pending: list[dict] = []
            for p in plist:
                idc = _canon(p["id"])
                if lake.is_complete(idc):
                    # 湖格在、manifest 行不在（hydrate→append 崩溃窗）：
                    # meta.json 重建行直接补账，不碰网络。
                    meta = {}
                    with contextlib.suppress(OSError, ValueError):
                        meta = json.loads(
                            (lake.cell_dir(idc) / "meta.json").read_text(
                                encoding="utf-8"
                            )
                        )
                    row = _manifest_row(meta, p["id"], lake.cell_dir(idc) / "extracted")
                    mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                    mf.flush()
                    n_heal += 1
                else:
                    pending.append(p)
            if pending:
                want_f = ws / f"want_{sn:04d}_{rgi:03d}.txt"
                want_f.write_text(
                    "".join(p["id"] + "\n" for p in pending), encoding="utf-8"
                )
                rows_f = ws / f"rg_{sn:04d}_{rgi:03d}.jsonl"
                ok_rg = False
                for attempt in range(RG_ATTEMPTS):
                    rc, tail = _hf_run(
                        ("rgrows", sn, rgi, want_f, rows_f), timeout_s=1800
                    )
                    if rc == 0 and rows_f.exists():
                        ok_rg = True
                        break
                    ctx.emit(
                        {
                            "stage": "rehydrate",
                            "metric": "sw_rg_retry",
                            "shard": sn,
                            "rg": rgi,
                            "attempt": attempt + 1,
                            "rc": rc,
                            "err": tail,
                        }
                    )
                    if attempt + 1 < RG_ATTEMPTS:
                        time.sleep(15 * (attempt + 1))
                if not ok_rg:
                    n_err += len(pending)
                    ctx.emit(
                        {
                            "stage": "rehydrate",
                            "metric": "sw_rg_fail",
                            "shard": sn,
                            "rg": rgi,
                            "lost": len(pending),
                        }
                    )
                    continue
                rows = {r["id"]: r for r in _iter_jsonl(rows_f) if r.get("id")}
                for p in pending:
                    r = rows.get(p["id"])
                    if r is None:
                        n_skip += 1
                        continue
                    r["shard"] = sn
                    r["rg"] = rgi
                    files = split_files(r["latex"] or "")
                    if not any(pf.lower().endswith(".tex") for pf in files):
                        n_skip += 1
                        continue
                    idc = _canon(p["id"])
                    try:
                        d = lake.hydrate(
                            idc,
                            fetch_fn=_fetch_for(r, files),
                            source="arxiv",
                            run_seq=run_seq,
                        )
                    except Exception as e:
                        ctx.emit(
                            {
                                "stage": "rehydrate",
                                "metric": "sw_cell_err",
                                "id": p["id"],
                                "err": f"{type(e).__name__}: {e}",
                            }
                        )
                        n_err += 1
                        continue
                    if d is None or not lake.is_complete(idc):
                        n_err += 1
                        continue
                    # raw 是重打包文本树（非网络可再生的零成本件）——
                    # catalog 标 regen_cost=network，驱逐永不先逐 raw。
                    base = cat.rows().get(idc) or {}
                    layers = sorted(set(base.get("layers") or []) | {LAYER})
                    channels = sorted(set(base.get("channels") or []) | {CHANNEL})
                    # 写死 "hydrated"——本 cat 实例在段头 load，hydrate 内部
                    # 是自己的实例；拿陈旧 state() 会把刚落的行打回 absent。
                    cat.set(
                        idc,
                        "hydrated",
                        source="arxiv",
                        regen_cost="network",
                        layers=layers,
                        channels=channels,
                    )
                    meta = {}
                    with contextlib.suppress(OSError, ValueError):
                        meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
                    row = _manifest_row(meta, p["id"], d / "extracted")
                    mf.write(json.dumps(row, ensure_ascii=False) + "\n")
                    mf.flush()
                    n_ok += 1
            ctx.emit(
                {
                    "stage": "rehydrate",
                    "metric": "sw_rg",
                    "shard": sn,
                    "rg": rgi,
                    "ok": n_ok,
                    "skip": n_skip,
                    "err": n_err,
                    "heal": n_heal,
                }
            )
            if limit and n_ok >= limit:
                stop = True
                break
    status = "error" if n_err else "ok"
    return {
        "status": status,
        "metrics": {
            "picks": len(picks),
            "n_ok": n_ok,
            "n_skip": n_skip,
            "n_err": n_err,
            "n_heal": n_heal,
            "n_done": n_done,
            "n_taken": n_taken,
            "rgs": len(by_rg),
            "limit_hit": int(stop),
            "manifest": str(MANIFEST_OUT),
        },
    }


def _report(ctx):
    """manifest_dev_recent.jsonl 聚合 → metrics（恒 ok——真账由上游段背）。"""
    rows = list(_iter_jsonl(MANIFEST_OUT)) if MANIFEST_OUT.exists() else []
    months = Counter(r.get("yymm") for r in rows)
    cats = Counter(r.get("cat_group") for r in rows)
    ctx.emit(
        {
            "stage": "report",
            "metric": "sw_report",
            "n": len(rows),
            "months": dict(sorted(months.items())),
            "cats": dict(cats.most_common()),
        }
    )
    return {
        "status": "ok",
        "metrics": {
            "n_rows": len(rows),
            "months": dict(sorted(months.items())),
            "cat_groups": dict(cats.most_common()),
            "sum_mb": round(sum(r.get("bytes") or 0 for r in rows) / 1e6, 1),
            "sum_tex": sum(r.get("n_tex") or 0 for r in rows),
            "manifest": str(MANIFEST_OUT),
        },
    }


spec = Spec(
    kind="corpus_sw",
    # eval=True：item id 非 canon（"corpus-sw" 是 builder 单元不是 arxiv id）
    # ——非 eval spec 会过 canon_id 把它当 invalid 丢掉（errsweep 同款）。
    eval=True,
    items=[{"id": "corpus-sw"}],
    params={
        "n_sw": Param(type=int, default=1200),
        "n_ep_holdout": Param(type=int, default=300),
        "n_ep_devrecent": Param(type=int, default=300),
        "min_yymm": Param(type=str, default="2501"),
        "seed": Param(type=int, default=42),
        # 试运行闸（fp=False：限流旋钮不进指纹）
        "limit": Param(type=int, default=0, fp=False),
        "shards": Param(type=str, default="", fp=False),
        "rg_limit": Param(type=int, default=0, fp=False),
    },
    stages=[
        Stage(
            "footers", _footers, status_class={"ok": "terminal", "error": "retriable"}
        ),
        Stage(
            "pool",
            _pool,
            needs=[("footers", {"ok"})],
            status_class={"ok": "terminal", "error": "retriable"},
        ),
        Stage(
            "assign",
            _assign,
            needs=[("pool", {"ok"})],
            status_class={"ok": "terminal", "error": "retriable"},
        ),
        Stage(
            "rehydrate",
            _rehydrate,
            needs=[("assign", {"ok"})],
            status_class={"ok": "terminal", "error": "retriable"},
        ),
        # needs 闸只认 DONE 行（_needs_eval statuses=STATUS_DONE）——
        # retriable error 永远喂不饱 accept，故 report 只接 ok；部分失败的
        # 面由 rehydrate 自己的 error+metrics 背，下轮 run 续跑收敛后
        # report 自然放行。
        Stage(
            "report",
            _report,
            needs=[("rehydrate", {"ok"})],
            status_class={"ok": "terminal", "error": "retriable"},
        ),
    ],
    lake=True,
    prefetch=False,  # builder 段内自管 hydrate——预取器对本 spec 无的放矢
    lake_source="arxiv",
)

if __name__ == "__main__":
    sys.exit(_worker_cli(sys.argv))
