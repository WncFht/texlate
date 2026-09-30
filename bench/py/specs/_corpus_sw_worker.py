"""corpus_sw HF 子进程叶——_hf_* 派发管道 + --worker 体（uv env 裸跑）。

``_hf_argv`` 以 ``__file__`` 自指——worker 子进程跑的是本叶（``python
specs/_corpus_sw_worker.py --worker ...``），本叶自带 sys.path 前奏与
``__main__`` 派发，与父链 spec 装载零互依。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

# worker 裸跑 ``python specs/x.py --worker`` 时 bench/py 不在
# sys.path——先立起才够得着 specs.*（load_spec 径下幂等）。
_BENCH_PY = str(Path(__file__).resolve().parents[1])
if _BENCH_PY not in sys.path:
    sys.path.insert(0, _BENCH_PY)
from specs import _bootstrap

_bootstrap.ensure()

from specs import _corpus_common as cc
from specs._corpus_sw_base import SHARD_URL, yymm_recent

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
    cc.atomic_write_text(out, json.dumps({"rows": md.num_rows, "rgs": rgs}))
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
    cc.atomic_write_text(out, "".join(json.dumps(x) + "\n" for x in rows))
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


if __name__ == "__main__":
    sys.exit(_worker_cli(sys.argv))
