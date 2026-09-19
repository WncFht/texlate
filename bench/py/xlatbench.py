#!/usr/bin/env python3
r"""xlatbench — B4a 翻译硬契约回归跑分器 (gwbench 扶正版).

对 3033 网关免费集模型跑分层抽样 LaTeX 段落翻译, 逐调用过 L0 validator
+ 三条增强判定, 产出 results.jsonl; report 子命令聚合排序表.

样例池 (docs/10 §B4a): corpus manifest.jsonl 按 ``--where k=v`` 切层
(如 layer=core), ``--docs N`` 跨 cluster 轮转取 N 篇 (seed 定簇内序),
每篇 locate() 定主 tex → 候选 chunk (300–1200 字符且含占位符) 按
context-kind 分桶, 每桶等距取 ``--per-kind`` 个; 尾部挂 S1–S4 合成压力
(与 bench/fixtures/xlat-traps.tex @Xn 遮蔽输出逐字一致, test_bench_regression
assert_xlat 钉住产品口径).

判定口径 (E22 定案, docs/05 §E22):
  hard_ok = validator.ok ∧ 无丢占位符 ∧ 无造占位符 ∧ 无丢脆弱命令
  ph_order 降为软信号 (合法中文换序占违例 ~95%), 单独记录不计硬失败.
  cs_dropped = src 中脆弱命令 (\ /\,/\;/\:/\!/~) 在 zh 计数变少 —— 升硬
  判据, 抓 "\ "+中文熔成 \和 这类未定义 cs 的编译炸弹.

2026-09-15: validator 从 tmp/exp/rule-validator (gitignored 脚手架) 切到
产品版 texlate.validate.l0.validate_pair —— 规则集与 E22 基线口径可能
有漂移, 跨版本对拍前先确认判据等价. 每条 rec 落 prompt_sha 供 prompt
回归分口径; ``rejudge`` 子命令对存量 results.jsonl 按现口径重判对拍.

用法 (import texlate.* 产品代码, 必须 uv venv):
  uv run python bench/py/xlatbench.py run --models swe-2-medium,glm-5-2 \
      [--runs 2] [--samples N] [--manifest P] [--where layer=core] \
      [--docs 0] [--per-kind 8] [--seed 0] [--out DIR] [--resume]
  uv run python bench/py/xlatbench.py report DIR [DIR...] [--md OUT.md]
  uv run python bench/py/xlatbench.py rejudge DIR [DIR...]  # 存量重判
  uv run python bench/py/xlatbench.py samples [抽样选项]    # 列出样例池
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import benchlib

from texlate.arxiv.locate import locate
from texlate.latex import parse_file
from texlate.latex.placeholder import PH_RX
from texlate.validate.l0 import validate_pair

REPO = Path(__file__).resolve().parents[2]

BASE = os.environ.get("TEXLATE_BASE_URL", "http://127.0.0.1:3033")
KEY = os.environ.get("TEXLATE_API_KEY", "")
TIMEOUT = 240
GAP_S = 1.0
MAX_TOKENS = 8192
RETRY_MAX_TOKENS = 32768

SYSTEM = (
    "You are a LaTeX academic translator. Translate prose to Chinese. "
    "Tokens like [[MATH_1]] are opaque placeholders — keep them verbatim "
    "in output, never translate or invent new ones. Preserve all LaTeX "
    "commands. Output only the translation."
)
PROMPT_SHA = hashlib.sha256(SYSTEM.encode()).hexdigest()[:12]

# 脆弱命令: 单字符/短控制序列, 丢了肉眼难查但影响排版
FRAGILE_CS_RX = re.compile(r"\\[ ,;:!]|~")
# zh 中残留英文散文词 (>=4 字母单词, 排除占位符/LaTeX 命令)
EN_WORD_RX = re.compile(r"[A-Za-z]{4,}")
CS_RX = re.compile(r"\\[a-zA-Z]+")

DEFAULT_MANIFEST = REPO / "bench" / "corpus" / "manifest.jsonl"

# 合成压力样例: 与 bench/fixtures/xlat-traps.tex @X1–@X4 遮蔽输出逐字一致
# (产品口径 —— BIB_/HREF_/URL_ 全局跨类编号), test_bench_regression.assert_xlat
# 钉住 parser 侧; 改任一边先跑该测试对拍.
SYNTHETIC = [
    {
        "name": "S1-bibitem-lead",
        "src": (
            "[[BIB_1]] Vaswani et al.\\ \\href[[HREF_2]]{introduced the "
            "Transformer}, demonstrating that attention alone suffices when "
            "the hidden dimension satisfies [[MATH_3]]; earlier work by "
            "Bahdanau, Cho, and Bengio [[CITE_4]] and the survey of Luong "
            "and Manning [[CITE_5]] had already hinted at this."
        ),
    },
    {
        "name": "S2-multikey-cite",
        "src": (
            "Subsequent analyses [[CITE_6]] refined this bound using "
            "[[MATH_7]] and argued, following the framework of [[CITE_8]], "
            "that the variance term dominates in the small-sample regime "
            "[[MATH_9]]."
        ),
    },
    {
        "name": "S3-verbatim-pct",
        "src": (
            "The implementation is available at [[URL_10]] and reproduces "
            "the baseline of [[CITE_11]] within [[MATH_12]] relative error, "
            "using the estimator described in [[REF_13]]."
        ),
    },
    {
        "name": "S4-dense-math",
        "src": (
            "Setting [[MATH_14]] yields [[MATH_15]], and substituting "
            "[[MATH_16]] into [[MATH_17]] gives the desired contraction "
            "whenever [[MATH_18]] holds [[CITE_19]]."
        ),
    },
]


def load_manifest(path: Path, where: list[str]) -> list[dict]:
    """manifest.jsonl → doc 行; ``--where k=v`` 逐项等值过滤 (值一律按 str 比)."""
    docs = benchlib.read_jsonl(path)
    for w in where:
        k, sep, v = w.partition("=")
        if not sep:
            print(f"  [skip] --where {w!r} 非 k=v 形", file=sys.stderr)
            continue
        docs = [d for d in docs if str(d.get(k)) == v]
    return docs


def pick_docs(docs: list[dict], n: int, seed: int) -> list[dict]:
    """跨 cluster 轮转取 n 篇 (seed 定簇内序) —— 覆盖优先于簇内重复."""
    if n <= 0 or n >= len(docs):
        return docs
    rng = random.Random(seed)
    pools: list[list[dict]] = []
    by_cluster: dict[str, list[dict]] = {}
    for d in docs:
        key = str(d.get("cluster_id") or d.get("stratum_cell") or "?")
        by_cluster.setdefault(key, []).append(d)
    for key in sorted(by_cluster):
        pool = by_cluster[key]
        rng.shuffle(pool)
        pools.append(pool)
    out: list[dict] = []
    while len(out) < n:
        progressed = False
        for pool in pools:
            if pool and len(out) < n:
                out.append(pool.pop())
                progressed = True
        if not progressed:
            break
    return out


def _main_tex(entry: Path) -> Path | None:
    """corpus 条目 → 主 tex 绝对路径 (locate 定位, 失败回退唯一 .tex)."""
    ext = entry / "extracted"
    if not ext.is_dir():
        return None
    res = locate(ext, arxiv_id=entry.name)
    if res.main:
        return ext / res.main
    texs = sorted(ext.rglob("*.tex"))
    return texs[0] if texs else None


def build_samples(
    manifest: Path,
    where: list[str],
    docs_n: int,
    per_kind: int,
    seed: int,
    limit: int | None = None,
) -> list[dict]:
    """manifest 切层 → 跨簇选篇 → 候选 chunk 按 kind 分桶等距抽样 + 合成样例."""
    root = manifest.parent
    docs = pick_docs(load_manifest(manifest, where), docs_n, seed)
    by_kind: dict[str, list[dict]] = {}
    for d in docs:
        main = _main_tex(root / d["id"])
        if main is None:
            print(f"  [skip] {d['id']} 无主 tex", file=sys.stderr)
            continue
        try:
            res = parse_file(main, flatten=True)
        except Exception as e:
            print(f"  [skip] {d['id']} parse fail: {e}", file=sys.stderr)
            continue
        i = 0
        for c in res.chunks:
            if 300 <= len(c.content) <= 1200 and PH_RX.search(c.content):
                kind = c.context or "para"
                by_kind.setdefault(kind, []).append(
                    {
                        "name": f"{d['id']}#{i}",
                        "doc": d["id"],
                        "kind": kind,
                        "src": c.content,
                        "synthetic": False,
                    }
                )
                i += 1
    out: list[dict] = []
    for kind in sorted(by_kind):
        pool = by_kind[kind]
        step = max(1, len(pool) // per_kind)
        out.extend(pool[::step][:per_kind])
    out.extend(
        {**s, "synthetic": True, "doc": "synthetic", "kind": "stress"}
        for s in SYNTHETIC
    )
    if limit and limit < len(out):
        real = [s for s in out if not s["synthetic"]]
        syn = [s for s in out if s["synthetic"]]
        keep_real = max(1, limit - len(syn))
        step = max(1, len(real) // keep_real)
        out = real[::step][:keep_real] + syn
        out = out[:limit]
    return out


def call_once(model: str, user: str, max_tokens: int) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    req = urllib.request.Request(  # noqa: S310 — bench 探针, URL 固定本地网关
        BASE + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {KEY}",
        },
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:  # noqa: S310 — 同上
            payload = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {
            "http": e.code,
            "error": e.read()[:500].decode("utf-8", "replace"),
            "seconds": round(time.time() - t0, 2),
        }
    except Exception as e:
        return {
            "http": -1,
            "error": str(e)[:500],
            "seconds": round(time.time() - t0, 2),
        }
    dt = time.time() - t0
    choices = payload.get("choices") or []
    if not choices:
        return {
            "http": 200,
            "seconds": round(dt, 2),
            "content": "",
            "error": f"missing choices: {str(payload)[:200]}",
        }
    ch = choices[0]
    msg = ch["message"]
    usage = payload.get("usage", {})
    return {
        "http": 200,
        "seconds": round(dt, 2),
        "finish": ch.get("finish_reason"),
        "content": msg.get("content") or "",
        "reasoning_len": len(msg.get("reasoning_content") or ""),
        "tok_in": usage.get("prompt_tokens"),
        "tok_out": usage.get("completion_tokens"),
        "tok_cached": (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
    }


def judge(src: str, zh: str) -> dict:
    """契约判定. hard_ok 按 E22: validator 无 error ∧ ph 无丢/造 ∧ cs 无丢失."""
    rep = validate_pair(src, zh)
    ph_src = PH_RX.findall(src)
    ph_zh = PH_RX.findall(zh)
    ph_missing = sorted(set(ph_src) - set(ph_zh))
    ph_invented = sorted(set(ph_zh) - set(ph_src))
    ph_order = ph_src == ph_zh  # 序守恒 —— 软信号, 不计硬失败
    fragile_src = len(FRAGILE_CS_RX.findall(src))
    fragile_zh = len(FRAGILE_CS_RX.findall(zh))
    cs_dropped = fragile_zh < fragile_src
    validator_ok = rep.ok
    hard_ok = validator_ok and not ph_missing and not ph_invented and not cs_dropped
    zh_clean = CS_RX.sub(" ", PH_RX.sub(" ", zh))
    en_residue = len(EN_WORD_RX.findall(zh_clean))
    return {
        "hard_ok": hard_ok,
        "validator_ok": validator_ok,
        "validator_issues": [f"{i.severity}:{i.rule}:{i.message}" for i in rep.issues],
        "ph_missing": ph_missing,
        "ph_invented": ph_invented,
        "ph_order_ok": ph_order,
        "cs_dropped": cs_dropped,
        "fragile_src": fragile_src,
        "fragile_zh": fragile_zh,
        "en_residue_words": en_residue,
        "zh_len": len(zh),
    }


def _samples_from_args(args: argparse.Namespace) -> list[dict]:
    return build_samples(
        Path(args.manifest),
        args.where,
        args.docs,
        args.per_kind,
        args.seed,
        limit=args.samples or None,
    )


def cmd_samples(args: argparse.Namespace) -> None:
    samples = _samples_from_args(args)
    for s in samples:
        print(
            f"{s['name']:24} kind={s['kind']:12} len={len(s['src']):5} "
            f"ph={len(PH_RX.findall(s['src']))} doc={s['doc']}"
        )
    print(f"total {len(samples)}")


def cmd_run(args: argparse.Namespace) -> None:
    samples = _samples_from_args(args)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    done: set[tuple[str, int, str]] = set()
    if args.resume and (outdir / "results.jsonl").exists():
        for r in benchlib.iter_jsonl(outdir / "results.jsonl"):
            # 只跳成功出译文的记录 —— http 错误/空响应留待补跑
            if r.get("http") == 200 and r.get("content"):
                done.add((r["model"], r["run"], r["sample"]))
        print(f"resume: {len(done)} 已有结果将跳过")
    fp = (outdir / "results.jsonl").open("a")
    models = [m.strip() for m in args.models.split(",")]
    print(f"samples={len(samples)} runs={args.runs} models={models}")

    for model in models:
        for run in range(args.runs):
            for s in samples:
                if (model, run, s["name"]) in done:
                    continue
                t0 = time.time()
                r = call_once(model, s["src"], MAX_TOKENS)
                if r.get("http") == 429:
                    # 网关本地限流: 至多额外等 3 次指数退避补一枪
                    for attempt in range(3):
                        time.sleep(args.gap * (2 ** (attempt + 1)))
                        r = call_once(model, s["src"], MAX_TOKENS)
                        if r.get("http") != 429:
                            break
                    r["retry_429"] = True
                if r.get("finish") == "length" and not r.get("content"):
                    time.sleep(args.gap)
                    r = call_once(model, s["src"], RETRY_MAX_TOKENS)
                    r["retried_32k"] = True
                rec = {
                    "model": model,
                    "run": run,
                    "sample": s["name"],
                    "doc": s["doc"],
                    "kind": s["kind"],
                    "prompt_sha": PROMPT_SHA,
                    **r,
                }
                if r.get("http") == 200 and r.get("content"):
                    rec["judge"] = judge(s["src"], r["content"])
                    rec["src"] = s["src"]
                fp.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fp.flush()
                j = rec.get("judge") or {}
                print(
                    f"  {model:22} r{run} {s['name']:22} "
                    f"{r.get('seconds', 0):6.1f}s http={r.get('http')} "
                    f"hard={j.get('hard_ok')} ord={j.get('ph_order_ok')} "
                    f"rsn={r.get('reasoning_len')}"
                )
                time.sleep(max(0, args.gap - (time.time() - t0)))
    fp.close()
    print(f"done -> {outdir / 'results.jsonl'}")


def cmd_rejudge(args: argparse.Namespace) -> None:
    """存量 results.jsonl 按现口径重判 —— validator/judge 升级后新旧 hard_ok 对拍."""
    for d in args.dirs:
        src_f = Path(d) / "results.jsonl"
        out_f = Path(d) / "results.rejudged.jsonl"
        recs = benchlib.read_jsonl(src_f)
        per_model: dict[str, list[int]] = {}
        flips: list[str] = []
        with out_f.open("w", encoding="utf-8") as fp:
            for r in recs:
                if r.get("http") == 200 and r.get("content") and r.get("src"):
                    j_old = r.get("judge") or {}
                    # 现口径 hard_ok; E22 时代 judge 的硬判字段名是 ok
                    old = j_old.get("hard_ok", j_old.get("ok"))
                    new = judge(r["src"], r["content"])
                    r["judge_old"] = r.get("judge")
                    r["judge"] = new
                    st = per_model.setdefault(r["model"], [0, 0, 0])
                    st[0] += 1
                    st[1] += int(bool(old))
                    st[2] += int(new["hard_ok"])
                    if old is not None and bool(old) != new["hard_ok"]:
                        flips.append(
                            f"{r['model']} {r['sample']} r{r['run']}: "
                            f"{old}->{new['hard_ok']}"
                        )
                fp.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"== {d}")
        for m, (n, old_ok, new_ok) in sorted(per_model.items()):
            print(
                f"  {m:22} hard_ok {old_ok}/{n} -> {new_ok}/{n} ({new_ok - old_ok:+d})"
            )
        for f_ in flips[:20]:
            print(f"  flip {f_}")
        if len(flips) > 20:
            print(f"  ... +{len(flips) - 20} more flips")
        print(f"  wrote {out_f}")


def _med(xs: list[float]) -> float:
    return statistics.median(xs) if xs else 0.0


def _p95(xs: list[float]) -> float:
    if not xs:
        return 0.0
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(len(xs) * 0.95))]


def aggregate(dirs: list[str]) -> tuple[dict[str, dict], list[dict]]:
    """读各 DIR/results.jsonl → (逐模型聚合, 失败清单)."""
    rows: dict[str, dict] = {}
    fails: list[dict] = []
    for d in dirs:
        for r in benchlib.iter_jsonl(Path(d) / "results.jsonl"):
            m = r["model"]
            st = rows.setdefault(
                m,
                {
                    "n": 0,
                    "hard_ok": 0,
                    "http_err": 0,
                    "empty": 0,
                    "ph_miss": 0,
                    "ph_inv": 0,
                    "ord_bad": 0,
                    "cs_drop": 0,
                    "v_err": 0,
                    "v_warn": 0,
                    "retried": 0,
                    "lat": [],
                    "rsn": [],
                    "tin": [],
                    "tout": [],
                    "tck": [],
                },
            )
            st["n"] += 1
            if r.get("retried_32k"):
                st["retried"] += 1
            if r.get("http") != 200:
                st["http_err"] += 1
                fails.append(
                    {
                        "model": m,
                        "sample": r["sample"],
                        "run": r["run"],
                        "why": f"http {r.get('http')} {str(r.get('error'))[:80]}",
                    }
                )
                continue
            if not r.get("content"):
                st["empty"] += 1
                fails.append(
                    {
                        "model": m,
                        "sample": r["sample"],
                        "run": r["run"],
                        "why": "empty content"
                        + (f" ({str(r.get('error'))[:60]})" if r.get("error") else ""),
                    }
                )
                continue
            j = r.get("judge") or {}
            st["lat"].append(r.get("seconds", 0))
            st["rsn"].append(r.get("reasoning_len", 0))
            st["tin"].append(r.get("tok_in") or 0)
            st["tout"].append(r.get("tok_out") or 0)
            st["tck"].append(r.get("tok_cached") or 0)
            for i in j.get("validator_issues") or []:
                if i.startswith("error:"):
                    st["v_err"] += 1
                else:
                    st["v_warn"] += 1
            if j.get("hard_ok"):
                st["hard_ok"] += 1
            else:
                why = []
                if j.get("ph_missing"):
                    st["ph_miss"] += len(j["ph_missing"])
                    why.append("miss:" + ",".join(j["ph_missing"]))
                if j.get("ph_invented"):
                    st["ph_inv"] += len(j["ph_invented"])
                    why.append("inv:" + ",".join(j["ph_invented"]))
                if j.get("cs_dropped"):
                    st["cs_drop"] += 1
                    why.append(f"cs {j.get('fragile_src')}→{j.get('fragile_zh')}")
                errs = [
                    i
                    for i in (j.get("validator_issues") or [])
                    if i.startswith("error:")
                ]
                why.extend(
                    e[6:].split(":")[0] + ":" + e[6:].split(":", 2)[-1][:60]
                    for e in errs
                )
                fails.append(
                    {
                        "model": m,
                        "sample": r["sample"],
                        "run": r["run"],
                        "why": "; ".join(why) or "?",
                        "src": r.get("src"),
                        "zh": r.get("content"),
                    }
                )
            if j.get("ph_order_ok") is False:
                st["ord_bad"] += 1
    return rows, fails


def cmd_report(args: argparse.Namespace) -> None:
    rows, fails = aggregate(args.dirs)
    lines = [
        (
            "| model | n | hard_ok | ph_miss | ph_inv | cs_drop | ord_soft | "
            "http_err | lat p50/p95 | rsn p50/p95 | in_tok med | out_tok med | "
            "cached med |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    agg = {}
    for m, s in sorted(
        rows.items(), key=lambda kv: -kv[1]["hard_ok"] / max(kv[1]["n"], 1)
    ):
        pct = f"{s['hard_ok'] / s['n'] * 100:.0f}%" if s["n"] else "–"
        lines.append(
            f"| {m} | {s['n']} | {s['hard_ok']} ({pct}) | {s['ph_miss']} | "
            f"{s['ph_inv']} | {s['cs_drop']} | {s['ord_bad']} | "
            f"{s['http_err']} | {_med(s['lat']):.1f}/{_p95(s['lat']):.1f}s | "
            f"{_med(s['rsn']):.0f}/{_p95(s['rsn']):.0f}ch | "
            f"{_med(s['tin']):.0f} | {_med(s['tout']):.0f} | "
            f"{_med(s['tck']):.0f} |"
        )
        agg[m] = {
            k: (
                v
                if not isinstance(v, list)
                else {
                    "p50": _med(v),
                    "p95": _p95(v),
                    "min": min(v) if v else 0,
                    "max": max(v) if v else 0,
                }
            )
            for k, v in s.items()
        }
        agg[m]["hard_rate"] = s["hard_ok"] / s["n"] if s["n"] else None
    table = "\n".join(lines)
    print(table)
    print("\n## 失败现场\n")
    for f in fails:
        print(f"- {f['model']} {f['sample']} run{f['run']}: {f['why']}")
    out = Path(args.dirs[0])
    (out / "models.json").write_text(
        json.dumps({"models": agg, "fails": fails}, ensure_ascii=False, indent=2)
    )
    if args.md:
        Path(args.md).write_text(table + "\n")
    print(f"\nwrote {out / 'models.json'}")


def _add_sampling_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--samples", type=int, default=0, help="总样例上限 (0=不限)")
    p.add_argument(
        "--manifest",
        default=str(DEFAULT_MANIFEST),
        help="corpus manifest.jsonl 路径",
    )
    p.add_argument(
        "--where",
        action="append",
        default=[],
        help="manifest 行等值过滤 k=v (可重复, 如 --where layer=core)",
    )
    p.add_argument(
        "--docs",
        type=int,
        default=0,
        help="跨 cluster 轮转取 N 篇 (0=过滤后全部)",
    )
    p.add_argument(
        "--per-kind",
        type=int,
        default=8,
        help="每种 context-kind 等距抽样上限",
    )
    p.add_argument("--seed", type=int, default=0, help="簇内选篇种子")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--models", required=True, help="逗号分隔")
    p_run.add_argument("--runs", type=int, default=2)
    _add_sampling_args(p_run)
    p_run.add_argument("--out", required=True)
    p_run.add_argument("--gap", type=float, default=GAP_S)
    p_run.add_argument("--resume", action="store_true")
    p_run.set_defaults(fn=cmd_run)
    p_rep = sub.add_parser("report")
    p_rep.add_argument("dirs", nargs="+")
    p_rep.add_argument("--md", default=None)
    p_rep.set_defaults(fn=cmd_report)
    p_rej = sub.add_parser("rejudge")
    p_rej.add_argument("dirs", nargs="+")
    p_rej.set_defaults(fn=cmd_rejudge)
    p_ls = sub.add_parser("samples")
    _add_sampling_args(p_ls)
    p_ls.set_defaults(fn=cmd_samples)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
