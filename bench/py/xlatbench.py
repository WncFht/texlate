#!/usr/bin/env python3
r"""xlatbench — B4a 翻译硬契约回归跑分器 (gwbench 扶正版).

对 3003 网关免费集模型跑分层抽样 LaTeX 段落翻译, 逐调用过 L0 validator
+ 三条增强判定, 产出 results.jsonl; report 子命令聚合排序表.

样例池与 tmp/exp/gwbench/bench_free.py 逐字节一致 (36 真实 chunk 等距抽
+ S1-S4 合成压力 = 40 样例), 与 E22 的 338 调用基线同口径可互相对拍.

判定口径 (E22 定案, docs/research/gateway/free-model-ranking.md §6):
  hard_ok = validator.ok ∧ 无丢占位符 ∧ 无造占位符 ∧ 无丢脆弱命令
  ph_order 降为软信号 (合法中文换序占违例 ~95%), 单独记录不计硬失败.
  cs_dropped = src 中脆弱命令 (\ /\,/\;/\:/\!/~) 在 zh 计数变少 —— 升硬
  判据, 抓 "\ "+中文熔成 \和 这类未定义 cs 的编译炸弹.

用法 (import texlate.* 产品代码, 必须 uv venv):
  uv run python bench/py/xlatbench.py run --models swe-2-medium,glm-5-2 \
      [--runs 2] [--samples N] [--out DIR] [--resume]
  uv run python bench/py/xlatbench.py report DIR [DIR...] [--md OUT.md]
  uv run python bench/py/xlatbench.py samples          # 列出样例池
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tmp" / "exp" / "rule-validator"))

import rule_validator

from texlate.latex import parse_file
from texlate.latex.placeholder import PH_RX

BASE = "http://127.0.0.1:3003"
KEY = "240127"
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

# 脆弱命令: 单字符/短控制序列, 丢了肉眼难查但影响排版
FRAGILE_CS_RX = re.compile(r"\\[ ,;:!]|~")
# zh 中残留英文散文词 (>=4 字母单词, 排除占位符/LaTeX 命令)
EN_WORD_RX = re.compile(r"[A-Za-z]{4,}")
CS_RX = re.compile(r"\\[a-zA-Z]+")

# 分层语料: 覆盖 article/IEEEtran/elsarticle/amsart-thesis/ATLAS-bib/数论
CORPUS_PICKS = [
    ("1706.03762/ms.tex", 6),
    ("2305.14335/main.tex", 6),
    ("2609.09529/Frobenius_Galois_of_Substructural_Logic.tex", 6),
    ("1111.4914/PhDThesis.tex", 6),
    ("1207.7214/TheATLASJulyPaper.tex", 6),
    ("1507.02284/sieve.tex", 6),
]

SYNTHETIC = [
    {
        "name": "S1-bibitem-lead",
        "src": (
            "[[BIBITEM_1]] Vaswani et al.\\ \\href{https://arxiv.org/abs/1706.03762}"
            "{introduced the Transformer}, demonstrating that attention alone "
            "suffices when the hidden dimension satisfies [[MATH_3]]; earlier "
            "work by Bahdanau, Cho, and Bengio [[CITE_2]] and the survey of "
            "Luong and Manning [[CITE_5]] had already hinted at this."
        ),
    },
    {
        "name": "S2-multikey-cite",
        "src": (
            "Subsequent analyses [[CITE_4]] refined this bound using "
            "[[MATH_7]] and argued, following the framework of [[CITE_9]], "
            "that the variance term dominates in the small-sample regime "
            "[[MATH_8]]."
        ),
    },
    {
        "name": "S3-verbatim-pct",
        "src": (
            "The implementation is available at "
            "\\url{https://example.org/repo%20texlate} and reproduces the "
            "baseline of [[CITE_1]] within [[MATH_2]] relative error, using "
            "the estimator described in [[REF_3]]."
        ),
    },
    {
        "name": "S4-dense-math",
        "src": (
            "Setting [[MATH_1]] yields [[MATH_2]], and substituting "
            "[[MATH_3]] into [[MATH_4]] gives the desired contraction "
            "whenever [[MATH_5]] holds [[CITE_6]]."
        ),
    },
]


def build_samples(corpus: Path, limit: int | None = None) -> list[dict]:
    """分层抽样: 每篇等距取 k 个 300-1200 字符且含占位符的 chunk + 合成样例."""
    out: list[dict] = []
    for rel, k in CORPUS_PICKS:
        path = corpus / rel
        if not path.exists():
            print(f"  [skip] {rel} 不存在", file=sys.stderr)
            continue
        res = parse_file(path, flatten=True)
        cands = [
            c
            for c in res.chunks
            if 300 <= len(c.content) <= 1200 and PH_RX.search(c.content)
        ]
        if not cands:
            continue
        step = max(1, len(cands) // k)
        chosen = cands[::step][:k]
        for i, c in enumerate(chosen):
            out.append(
                {
                    "name": f"{path.parent.name}#{i}",
                    "doc": rel,
                    "kind": c.context,
                    "src": c.content,
                    "synthetic": False,
                }
            )
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
    ch = payload["choices"][0]
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
    rep = rule_validator.validate_pair(src, zh)
    ph_src = PH_RX.findall(src)
    ph_zh = PH_RX.findall(zh)
    ph_missing = sorted(set(ph_src) - set(ph_zh))
    ph_invented = sorted(set(ph_zh) - set(ph_src))
    ph_order = ph_src == ph_zh  # 序守恒 —— 软信号, 不计硬失败
    fragile_src = len(FRAGILE_CS_RX.findall(src))
    fragile_zh = len(FRAGILE_CS_RX.findall(zh))
    cs_dropped = fragile_zh < fragile_src
    validator_ok = bool(rep.ok)
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


def cmd_samples(args: argparse.Namespace) -> None:
    samples = build_samples(REPO / "bench" / "corpus")
    for s in samples:
        print(
            f"{s['name']:24} kind={s['kind']:12} len={len(s['src']):5} "
            f"ph={len(PH_RX.findall(s['src']))} doc={s['doc']}"
        )
    print(f"total {len(samples)}")


def cmd_run(args: argparse.Namespace) -> None:
    samples = build_samples(REPO / "bench" / "corpus", limit=args.samples or None)
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    done: set[tuple[str, int, str]] = set()
    if args.resume and (outdir / "results.jsonl").exists():
        for line in (outdir / "results.jsonl").read_text().splitlines():
            if line.strip():
                r = json.loads(line)
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
        for line in (Path(d) / "results.jsonl").read_text().splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
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
                        "why": "empty content",
                    }
                )
                continue
            j = r.get("judge") or {}
            st["lat"].append(r.get("seconds", 0))
            st["rsn"].append(r.get("reasoning_len", 0))
            st["tin"].append(r.get("tok_in") or 0)
            st["tout"].append(r.get("tok_out") or 0)
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
            "http_err | lat p50/p95 | rsn p50/p95 | in_tok med | out_tok med |"
        ),
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
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
            f"{_med(s['tin']):.0f} | {_med(s['tout']):.0f} |"
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_run = sub.add_parser("run")
    p_run.add_argument("--models", required=True, help="逗号分隔")
    p_run.add_argument("--runs", type=int, default=2)
    p_run.add_argument("--samples", type=int, default=0)
    p_run.add_argument("--out", required=True)
    p_run.add_argument("--gap", type=float, default=GAP_S)
    p_run.add_argument("--resume", action="store_true")
    p_run.set_defaults(fn=cmd_run)
    p_rep = sub.add_parser("report")
    p_rep.add_argument("dirs", nargs="+")
    p_rep.add_argument("--md", default=None)
    p_rep.set_defaults(fn=cmd_report)
    p_ls = sub.add_parser("samples")
    p_ls.set_defaults(fn=cmd_samples)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
