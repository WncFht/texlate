#!/usr/bin/env python3
r"""preflight_batch.py — loop 批前置自检（stagerun 大批量前一票闸）。

仿 e2e_real_bench.preflight 的「src 全量 import walk + 无网 mock 链」，
加批量特有的资源面：磁盘余量 / corpus_v3 manifest / TeX 工具链 / 网关认证。
stagerun 启动时自带的 preflight 只含前两项，本脚本是其超集。

    uv run python bench/py/preflight_batch.py                 # 全项（含网关）
    uv run python bench/py/preflight_batch.py --no-net        # 离线（跳网关）
    uv run python bench/py/preflight_batch.py --min-free-gb 80

退出码：任一 FAIL → 1；全 ok/warn/skip → 0。
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import pkgutil
import shutil
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: 同 stagerun/e2e_real_bench 惯例——TEXLATE_SRC 可指冻结快照隔离 churn。
sys.path.insert(0, os.environ.get("TEXLATE_SRC", str(ROOT / "src")))

BENCH = ROOT / "bench"
CORPUS = BENCH / "corpus_v3"
GATEWAY_DEFAULT = os.environ.get("TEXLATE_BASE_URL", "http://127.0.0.1:3033")
TOOLS = ("xelatex", "tectonic", "pdftotext")

FAILS: list[str] = []


def rep(level: str, name: str, detail: str = "") -> None:
    """level ∈ ok / warn / FAIL / skip；FAIL 计一票。"""
    if level == "FAIL":
        FAILS.append(name)
    print(f"{level:<4} {name:<18} {detail}", flush=True)


def check_imports() -> None:
    """texlate 全量 import walk——被并行代理改半截的源码树在这就拦下。"""
    try:
        import texlate
    except Exception as e:
        rep("FAIL", "import-walk", f"texlate 包本体导入失败: {e!r}")
        return
    errs, n = [], 0
    for m in pkgutil.walk_packages(texlate.__path__, "texlate."):
        n += 1
        try:
            importlib.import_module(m.name)
        except Exception as e:
            errs.append(f"{m.name}: {e!r}")
    if errs:
        rep(
            "FAIL",
            "import-walk",
            f"{len(errs)}/{n} 模块失败 — " + " | ".join(errs[:5]),
        )
    else:
        rep("ok", "import-walk", f"{n} modules")


def check_mock_chain() -> None:
    """无网过一遍 mock 翻译链——e2e_real_bench.preflight 同构。"""
    try:
        from texlate.latex.api import parse_tex
        from texlate.validate.l0 import validate_pair
        from texlate.xlat.pipeline import (
            MockTranslator,
            XlatPipeline,
            chunk_to_in,
        )

        async def go() -> list:
            scans = parse_tex(
                "\\documentclass{article}\n\\begin{document}\n"
                "Hello world $x^2$.\n\\end{document}\n"
            )
            chunks = [
                chunk_to_in(c, chunk_id=f"0:{c.id}", ph_map=scans.ph_map)
                for c in scans.chunks
            ]
            pipe = XlatPipeline(
                MockTranslator(),
                validator=lambda s, z: validate_pair(s, z).feedback(),
            )
            return await pipe.run(chunks)

        results = asyncio.run(go())
    except Exception as e:
        rep("FAIL", "mock-chain", repr(e))
        return
    bad = [r for r in results if r.status == "fault"]
    if bad:
        rep("FAIL", "mock-chain", f"{len(bad)}/{len(results)} chunks fault")
    elif not results:
        rep("warn", "mock-chain", "0 chunks——链条没炸但没产出，关注")
    else:
        rep("ok", "mock-chain", f"{len(results)} chunks")


def check_disk(min_gb: float) -> None:
    free_gb = shutil.disk_usage(BENCH).free / 2**30
    if free_gb < min_gb:
        rep(
            "FAIL",
            "disk",
            f"free={free_gb:.0f}G < {min_gb:.0f}G @ {BENCH}"
            "（存量 1259 work 树 ~20G / 5000 gate ~80G 量级）",
        )
    else:
        rep("ok", "disk", f"free={free_gb:.0f}G @ {BENCH}")


def check_manifest(layers: list[str]) -> None:
    try:
        import benchlib

        rows = benchlib.load_manifest_rows(CORPUS, sorted(layers))
    except Exception as e:
        rep("FAIL", "corpus-manifest", repr(e))
        return
    if not rows:
        rep("FAIL", "corpus-manifest", f"0 行（layers={','.join(layers)}）")
        return
    n_ext = sum(1 for e in rows if (CORPUS / str(e.get("id")) / "extracted").is_dir())
    rep(
        "ok",
        "corpus-manifest",
        f"{len(rows)} 行 / extracted 在盘 {n_ext}（layers={','.join(layers)}）",
    )


def check_tools() -> None:
    missing = [t for t in TOOLS if shutil.which(t) is None]
    if missing:
        rep("FAIL", "tex-toolchain", f"不在 PATH: {', '.join(missing)}")
    else:
        rep("ok", "tex-toolchain", " ".join(TOOLS))


def _get_json(url: str, key: str = "", timeout: float = 8.0) -> dict:
    req = urllib.request.Request(url)  # noqa: S310 — bench 自检，端点固定内网
    if key:
        req.add_header("Authorization", f"Bearer {key}")
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — 同上
        return json.loads(r.read().decode("utf-8", "replace"))


def check_gateway(base: str, key: str, model: str) -> None:
    """直连（非隧道）/v1/models 认证——401 静默全败是设计稿点名的头号洞。"""
    url = f"{base.rstrip('/')}/v1/models"
    try:
        data = _get_json(url, key)
    except urllib.error.HTTPError as e:
        rep(
            "FAIL",
            "gateway-auth",
            f"GET {url} -> HTTP {e.code}（401/403=key 失效，整批会变假数据）",
        )
        return
    except Exception as e:
        rep("FAIL", "gateway-auth", f"GET {url} -> {e!r:.140}")
        return
    ids = [
        str(m["id"])
        for m in (data or {}).get("data") or []
        if isinstance(m, dict) and m.get("id")
    ]
    if not ids:
        rep("warn", "gateway-auth", f"200 但模型表为空/形状异常: {str(data)[:120]}")
    elif model in ids:
        rep("ok", "gateway-auth", f"{len(ids)} models, {model} 在列")
    else:
        rep("warn", "gateway-auth", f"{len(ids)} models，{model} 不在列——real 臂不可跑")


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="preflight_batch.py", description=__doc__.splitlines()[0]
    )
    ap.add_argument("--layers", default="core,booster,hot")
    ap.add_argument(
        "--min-free-gb",
        type=float,
        default=50.0,
        help="bench/ 所在盘最小余量（loop ~20G / gate ~80G）",
    )
    ap.add_argument("--no-net", action="store_true", help="跳过网关网络项")
    ap.add_argument(
        "--base-url", default=GATEWAY_DEFAULT, help="直连网关（禁 loopback）"
    )
    ap.add_argument("--api-key", default=os.environ.get("TEXLATE_API_KEY", ""))
    ap.add_argument("--model", default="swe-2-medium")
    args = ap.parse_args()

    print(
        f"preflight_batch: TEXLATE_SRC={os.environ.get('TEXLATE_SRC') or str(ROOT / 'src')}",
        flush=True,
    )
    check_imports()
    check_mock_chain()
    check_disk(args.min_free_gb)
    check_manifest([s.strip() for s in args.layers.split(",") if s.strip()])
    check_tools()
    if args.no_net:
        rep("skip", "gateway-auth", "--no-net")
    else:
        check_gateway(args.base_url, args.api_key, args.model)
    print(f"== {'FAIL x' + str(len(FAILS)) if FAILS else 'all pass'}", flush=True)
    sys.exit(1 if FAILS else 0)


if __name__ == "__main__":
    main()
