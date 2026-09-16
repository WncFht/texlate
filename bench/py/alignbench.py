#!/usr/bin/env python3
r"""alignbench — B7 锚点保留基准 harness（docs/10 §B7 产品化）.

tmp/exp/align-probe/dest_probe.py 扶正：pypdf 提双侧 named destinations →
同名锚点配对 → 保留率 + 最大权值单调链（对照阅读器滚动同步的质量上限，
docs/05 §3-18 方案的前提条件；保留率 <95% 本身即 zh 编译完整性探针）。

用法:
  uv run --with pypdf python bench/py/alignbench.py --pairs pairs.jsonl [--check]
  uv run --with pypdf python bench/py/alignbench.py --a-dir A --b-dir B
  uv run --with pypdf python bench/py/alignbench.py --selftest
  uv run --with pypdf python bench/py/alignbench.py --e2e-real bench/work_e2ereal \
      --records bench/results/e2e-real-*-*/results.json [--rescue-en --corpus C]

对子来源四选一:
  --pairs         jsonl 清单, 每行 {"id","a","b","kind"?} —— B3/B5 编译产物登记
  --a-dir/--b-dir 两棵产物树按 *.pdf 相对路径配对 (e2e workBase↔work 型布局)
  --selftest      pypdf 合成对子 (keep/shift/drop/degraded 四案) 无语料冒烟,
                  自含断言不进 --check 门槛语义
  --e2e-real      e2e_real_bench 产物树 + run records 配对——zh 侧按 union
                  口径优先 pipe-fix/{sid}、缺路径回落 pipe-xel/{sid}（docs/10
                  §B5 增补: union 取较优者——pipe-fix 复判失败的 main.pdf 已
                  被引擎先 unlink, 不存在陈旧误标）；en 侧 base-xel 优先、
                  base-rescue 兜底。每对携带 {product_arm,en_arm,
                  zh_compile_verdict,en_compile_verdict} 元数据进结果行——
                  low-retention 联判编译 verdict（partial/fail = 编译截断
                  而非「壳没译」，b7-attribution-2026-09-16 归因结论固化）。
  --rescue-en     配 --e2e-real：b 侧有 PDF 而 base-xel 无 PDF 的工程（en
                  编译在本机环境挂——缺包类），复制 corpus extracted →
                  work/base-rescue/{sid}/ 用 fixloop usertree (_texmf/{sid})
                  重编译 en 基线，--jobs 并发 xelatex。verdict 落
                  OUT/rescue.jsonl。

产出 (docs/10 §统一产出契约): OUT/{pairs.jsonl,cells.json,summary.md}

门槛 (--check, docs/10 §B7): 有 hyperref 锚点侧的对子保留率 ≥95%;
双侧无锚点对 (无 hyperref 工程 ~31%) 走退化路径不崩; 无 pair 级异常.
单侧 PDF 不可解析记 invalid_pdf verdict——编译段垃圾产物 (kill 截断/stub),
对应 leg 在 B3/B5 已计 FAIL, 不占 no_pair_errors 门但单列显著报告.
退出码 0/1.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import math
import os
import re
import shutil
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

try:
    from pypdf import PdfReader
except ImportError:
    sys.exit("pypdf 不在依赖内 — 用 uv run --with pypdf python bench/py/alignbench.py")

import benchlib

ROOT = Path(__file__).resolve().parents[2]
BENCH = ROOT / "bench"

PAGE_ANCHOR_RX = re.compile(r"^page\.\d+$")
MIN_RETENTION = 0.95


# ---------------------------------------------------------------- 锚点提取
def _dest_page(r: PdfReader, dest: object) -> int | None:
    try:
        return r.get_destination_page_number(dest)
    except Exception:  # 坏 dest 当作缺失锚点
        return None


def extract_dests(path: Path) -> dict:
    """{name: {"page","yfrac","fit"}} + 页数; page.N 页码锚点单列不计入."""
    r = PdfReader(str(path))
    heights = []
    for p in r.pages:
        mb = p.mediabox
        heights.append(float(mb.height) or 792.0)
    out = {}
    fits = Counter()
    n_page_anchor = 0
    for name, dest in r.named_destinations.items():
        if PAGE_ANCHOR_RX.match(name):
            n_page_anchor += 1
            continue
        page = _dest_page(r, dest)
        if page is None or page < 0:
            continue
        fit = str(dest.get("/Type", "?"))
        top = dest.get("/Top")
        yfrac = None
        if top is not None and page < len(heights):
            yfrac = float(top) / heights[page]
        out[name] = {"page": page, "yfrac": yfrac, "fit": fit}
        fits[fit] += 1
    return {
        "dests": out,
        "npages": len(r.pages),
        "fits": dict(fits),
        "n_page_anchor": n_page_anchor,
    }


# ---------------------------------------------------------------- 类别与权重
def category(name: str) -> str:
    n = name.lower()
    if n.startswith(
        ("section", "subsection", "subsubsection", "chapter", "part", "paragraph")
    ):
        return "section"
    if n.startswith(("figure", "fig", "table", "tab")):
        return "figtable"
    if n.startswith(("equation", "eq")):
        return "equation"
    if n.startswith("cite"):
        return "cite"
    if n.startswith(("footnote", "hfootnote")):
        return "footnote"
    return "other"


# docs/10 §B7: section 12 / 图表 10 / equation 4 / cite 2 (page.* 排除等效权 0)
WEIGHT = {
    "section": 12,
    "figtable": 10,
    "equation": 4,
    "cite": 2,
    "footnote": 1,
    "other": 1,
}


# ---------------------------------------------------------------- 单调链 DP
def order_key(d: dict) -> tuple[float, float]:
    """阅读序 key: 页号 + 页内自顶向下位置 (yfrac 越大越靠前)."""
    y = d["yfrac"] if d["yfrac"] is not None else 1.0
    return (d["page"], -y)


def max_weight_chain(commons: list[tuple[str, dict, dict]]) -> dict:
    """按 A 序排序, 找 B key 非降的最大权子序列. O(n²) DP."""
    items = sorted(commons, key=lambda t: order_key(t[1]))
    n = len(items)
    bkeys = [order_key(it[2]) for it in items]
    wts = [WEIGHT[category(it[0])] for it in items]
    dp = wts[:]  # dp[i] = 以 i 结尾的最优链权
    par = [-1] * n
    for i in range(n):
        bi = bkeys[i]
        for j in range(i):
            if bkeys[j] <= bi and dp[j] + wts[i] > dp[i]:
                dp[i] = dp[j] + wts[i]
                par[i] = j
    if n == 0:
        return {"n": 0, "chain_n": 0, "w": 0, "chain_w": 0, "names": []}
    i_best = max(range(n), key=lambda i: dp[i])
    chain = []
    i = i_best
    while i >= 0:
        chain.append(items[i][0])
        i = par[i]
    chain.reverse()
    return {
        "n": n,
        "chain_n": len(chain),
        "w": sum(wts),
        "chain_w": dp[i_best],
        "names": chain,
    }


def hist(vals: list[float]) -> dict:
    c = Counter(vals)
    return {str(k): c[k] for k in sorted(c)}


# ---------------------------------------------------------------- 对子分析
def _with_meta(pair: dict, row: dict) -> dict:
    """对子 meta（arm/verdict 标注）并入结果行——键名与核心字段不冲突。"""
    row.update(pair.get("meta") or {})
    return row


def _blame(row: dict) -> str:
    """low-retention 归因列：联判 zh 侧编译 verdict（attribution-2026-09-16）。

    fail → 编译截断（百错上限后锚点全灭）；partial → 编译 partial（warning 级
    判据，锚点缺失仍先计编译段）；clean → 编译干净仍丢锚点，splice/xlat 真问题。
    """
    zv = row.get("zh_compile_verdict")
    if zv == "fail":
        return "zh_compile_fail"
    if zv == "partial":
        return "zh_compile_partial"
    if zv == "clean":
        return "shell_loss"
    if zv == "reject":
        return "inject_reject"
    return "unknown"


def _invalid_pdf(pair: dict, side: str, exc: Exception) -> dict:
    """单侧 PDF 不可解析 → invalid_pdf verdict.

    语义: 这是编译段垃圾产物(超时 kill 留 stub/截断写), 不是 harness 异常——
    对应 leg 在 B3/B5 已计 FAIL, B7 不重复惩罚; 单列 n_invalid 显著报告。
    """
    return _with_meta(
        pair,
        {
            "kind": pair["kind"],
            "id": pair["id"],
            "a": str(pair["a"]),
            "b": str(pair["b"]),
            "verdict": "invalid_pdf",
            "invalid_side": side,
            "detail": f"{type(exc).__name__}: {exc}",
        },
    )


def analyze_pair(pair: dict, min_retention: float) -> dict:
    try:
        ea = extract_dests(pair["a"])
    except Exception as e:  # 编译段垃圾产物 —— 非 harness 异常
        return _invalid_pdf(pair, "a", e)
    try:
        eb = extract_dests(pair["b"])
    except Exception as e:
        return _invalid_pdf(pair, "b", e)
    da, db = ea["dests"], eb["dests"]
    names_a, names_b = set(da), set(db)
    common = sorted(names_a & names_b)
    only_a = names_a - names_b
    only_b = names_b - names_a

    page_diffs = []
    y_diffs = []
    cat_counter = Counter(category(n) for n in common)
    lost_cat = Counter(category(n) for n in only_a)
    commons_t = []
    for n in common:
        pa, pb = da[n], db[n]
        page_diffs.append(pb["page"] - pa["page"])
        if (
            pa["page"] == pb["page"]
            and pa["yfrac"] is not None
            and pb["yfrac"] is not None
        ):
            y_diffs.append(round(pb["yfrac"] - pa["yfrac"], 4))
        commons_t.append((n, pa, pb))

    chain = max_weight_chain(commons_t)
    pd_sorted = sorted(page_diffs)

    def pct(p: float) -> float | None:
        if not pd_sorted:
            return None
        k = min(len(pd_sorted) - 1, max(0, round((p / 100) * (len(pd_sorted) - 1))))
        return pd_sorted[k]

    retention = (len(common) / len(da)) if da else None
    if not da:
        verdict = "degraded"  # A 侧无锚点 (无 hyperref 工程) → 退化路径
    elif retention < min_retention:
        verdict = "low"
    else:
        verdict = "ok"

    return _with_meta(
        pair,
        {
            "kind": pair["kind"],
            "id": pair["id"],
            "a": str(pair["a"]),
            "b": str(pair["b"]),
            "verdict": verdict,
            "pages_a": ea["npages"],
            "pages_b": eb["npages"],
            "dests_a": len(da),
            "dests_b": len(db),
            "page_anchors_a": ea["n_page_anchor"],
            "page_anchors_b": eb["n_page_anchor"],
            "common": len(common),
            "only_a": len(only_a),
            "only_b": len(only_b),
            "retention": retention,
            "cat_common": dict(cat_counter),
            "cat_lost_a": dict(lost_cat),
            "page_diff": {
                "min": pd_sorted[0] if pd_sorted else None,
                "p25": pct(25),
                "median": pct(50),
                "p75": pct(75),
                "p90": pct(90),
                "max": pd_sorted[-1] if pd_sorted else None,
                "mean": round(sum(page_diffs) / len(page_diffs), 2)
                if page_diffs
                else None,
                "dist": hist(page_diffs),
            },
            "y_diff_samepage": {
                "n": len(y_diffs),
                "mean": round(sum(y_diffs) / len(y_diffs), 4) if y_diffs else None,
                "abs_mean": round(sum(abs(y) for y in y_diffs) / len(y_diffs), 4)
                if y_diffs
                else None,
            },
            "chain": {
                "n_common": chain["n"],
                "chain_n": chain["chain_n"],
                "w_total": chain["w"],
                "w_chain": chain["chain_w"],
                "n_ratio": round(chain["chain_n"] / chain["n"], 4)
                if chain["n"]
                else None,
                "w_ratio": round(chain["chain_w"] / chain["w"], 4)
                if chain["w"]
                else None,
            },
            # 丢锚点全量名单 —— §B7-4 连锅端案例 (\label/\bibitem 随 chunk 移动)
            # 归因入口; 确认机制后应沉淀为 bench/fixtures B2 断言
            "lost_a": sorted(only_a),
            "new_b": sorted(only_b),
            "fits_a": ea["fits"],
            "fits_b": eb["fits"],
        },
    )


# ---------------------------------------------------------------- 对子来源
def pairs_from_manifest(path: Path) -> list[dict]:
    pairs = []
    for ln, row in enumerate(benchlib.iter_jsonl(path), 1):
        if not (row.get("a") and row.get("b")):
            continue
        a, b = Path(row["a"]), Path(row["b"])
        pairs.append(
            {
                "kind": row.get("kind", "manifest"),
                "id": row.get("id") or a.stem,
                "a": a,
                "b": b,
                "meta": {
                    k: v for k, v in row.items() if k not in {"id", "a", "b", "kind"}
                },
            }
        )
        if not a.exists() or not b.exists():
            print(
                f"  warn {path.name}:{ln} {pairs[-1]['id']}: a/b 不存在",
                file=sys.stderr,
            )
    return pairs


def pairs_from_dirs(a_dir: Path, b_dir: Path, kind: str) -> list[dict]:
    """B 侧每份 *.pdf 按相对路径在 A 侧找同名对子."""
    pairs = []
    for b in sorted(b_dir.rglob("*.pdf")):
        rel = b.relative_to(b_dir)
        a = a_dir / rel
        if not a.exists():
            print(f"  warn {rel}: A 侧无对应 PDF, 跳过", file=sys.stderr)
            continue
        pid = str(rel.parent) if str(rel.parent) != "." else b.stem
        pairs.append({"kind": kind, "id": pid, "a": a, "b": b})
    return pairs


# ---------------------------------------------------------------- e2e-real 对子
def load_records_any(path: Path) -> dict[str, dict]:
    """run records → {id: rec}：results.json(dict) 或 records.jsonl(append 账)。"""
    if path.suffix == ".jsonl":
        return benchlib.load_records(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        return data
    return {str(r["id"]): r for r in data}


def _verdict_of(rec: dict, arm: str) -> str | None:
    return ((rec.get(arm) or {}).get("verdict") or {}).get("status")


def _arm_pdfs(work: Path, arms: list[str], sid: str) -> dict[str, tuple[str, Path]]:
    """{relpath: (arm, pdf_path)}——低优先级臂先扫，高优先级覆写同 rel。"""
    found: dict[str, tuple[str, Path]] = {}
    for arm in reversed(arms):
        d = work / arm / sid
        if not d.is_dir():
            continue
        for pdf in sorted(d.rglob("*.pdf")):
            found[pdf.relative_to(d).as_posix()] = (arm, pdf)
    return found


def e2e_real_pairs(
    work: Path,
    records: dict[str, dict],
    *,
    rescue_arm: str = "base-rescue",
    rescue_verdicts: dict[str, str] | None = None,
) -> tuple[list[dict], list[dict]]:
    """e2e_real_bench 产物树 → 对子 + 逐工程覆盖率记录。

    union 口径（docs/10 §B5 增补）：zh 侧 relpath 级 [pipe-fix, pipe-xel] 递减
    优先级（pipe-fix 仅当该工程 record 里实际跑过）；en 侧 [base-xel,
    base-rescue]。返回 (pairs, coverage)；coverage 每行 {id,b_arm,zh_verdict,
    n_pairs,unpaired_reason}——无法成对的原因显式化。
    """
    rescue_verdicts = rescue_verdicts or {}
    pairs: list[dict] = []
    coverage: list[dict] = []
    for pid, rec in sorted(records.items()):
        sid = benchlib.safe_id(pid)
        has_fix = isinstance(rec.get("pipe-fix"), dict)
        b_arms = ["pipe-fix", "pipe-xel"] if has_fix else ["pipe-xel"]
        b_map = _arm_pdfs(work, b_arms, sid)
        a_map = _arm_pdfs(work, ["base-xel", rescue_arm], sid)
        cov = {
            "id": pid,
            "b_arms": b_arms,
            "pipe_xel_verdict": _verdict_of(rec, "pipe-xel"),
            "pipe_fix_verdict": _verdict_of(rec, "pipe-fix"),
            "base_xel_verdict": _verdict_of(rec, "base-xel"),
            "rescue_verdict": rescue_verdicts.get(pid),
            "n_b_pdf": len(b_map),
            "n_a_pdf": len(a_map),
        }
        if not b_map:
            cov["unpaired_reason"] = "no_zh_pdf"
            coverage.append(cov)
            continue
        main = rec.get("main")
        main_rel = Path(main).with_suffix(".pdf").as_posix() if main else None
        n_paired = 0
        for rel, (b_arm, b_path) in sorted(b_map.items()):
            a_hit = a_map.get(rel)
            if a_hit is None:
                continue
            a_arm, a_path = a_hit
            n_paired += 1
            en_verdict = (
                _verdict_of(rec, "base-xel")
                if a_arm == "base-xel"
                else rescue_verdicts.get(pid)
            )
            # 唯一且可读的对子 id：main 用裸 pid，其余带 relpath 防同 id 撞车
            # （同 sid 根级多个 pdf 时 resume dedup 会静默丢对子）
            if rel == main_rel:
                pair_id = pid
            elif "/" in rel:
                pair_id = f"{pid}/{rel[:-4]}"
            else:
                pair_id = f"{pid}:{rel[:-4]}"
            pairs.append(
                {
                    "kind": "e2e-real",
                    "id": pair_id,
                    "a": a_path,
                    "b": b_path,
                    "meta": {
                        "product_arm": b_arm,
                        "en_arm": a_arm,
                        "zh_compile_verdict": _verdict_of(rec, b_arm),
                        "en_compile_verdict": en_verdict,
                        "pipe_xel_verdict": _verdict_of(rec, "pipe-xel"),
                        "pipe_fix_verdict": _verdict_of(rec, "pipe-fix"),
                        "base_xel_verdict": _verdict_of(rec, "base-xel"),
                        "rel": rel,
                    },
                }
            )
        cov["n_pairs"] = n_paired
        if not n_paired:
            cov["unpaired_reason"] = "no_en_pdf"
        coverage.append(cov)
    return pairs, coverage


# ---------------------------------------------------------------- en 基线补编译
def rescue_en_baselines(
    work: Path,
    records: dict[str, dict],
    corpus: Path,
    out: Path,
    *,
    jobs: int = 4,
    timeout: float = 240.0,
    rescue_arm: str = "base-rescue",
) -> list[dict]:
    """b 侧有 PDF 而 base-xel 无 PDF → 用 fixloop usertree 重编译 en 基线。

    归因结论（b7-attribution-2026-09-16）：archbox texlive 缺老包时 en 基线
    先死，pipe-fix 的 usertree 装包后 zh 反而 clean——en 侧借同一 usertree
    补编译补齐对子。产物落 ``work/base-rescue/{sid}/``（gitignored 重产物），
    verdict 行落 ``out/rescue.jsonl``。幂等：main pdf 已存在即跳过。
    """
    # 延迟 import + src 路径注入：pypdf-only 路径（pairs/dirs/selftest）不触
    sys.path.insert(0, os.environ.get("TEXLATE_SRC", str(ROOT / "src")))
    from texlate.compile.engine import XelatexEngine
    from texlate.compile.judge import judge

    work = work.resolve()
    corpus = corpus.resolve()

    prior = {r["id"]: r for r in benchlib.read_jsonl(out / "rescue.jsonl")}
    targets = []
    for pid, rec in sorted(records.items()):
        sid = benchlib.safe_id(pid)
        has_fix = isinstance(rec.get("pipe-fix"), dict)
        b_map = _arm_pdfs(
            work, ["pipe-fix", "pipe-xel"] if has_fix else ["pipe-xel"], sid
        )
        a_map = _arm_pdfs(work, ["base-xel"], sid)
        main = rec.get("main")
        if not b_map or not main:
            continue
        # zh 有 main 产物而 en 基线缺 main.pdf 才补——a 侧有图片 pdf 不算覆盖
        main_rel = Path(main).with_suffix(".pdf").as_posix()
        if main_rel not in b_map or main_rel in a_map:
            continue
        if not (corpus / pid / "extracted").is_dir():
            print(f"  rescue skip {pid}: corpus extracted/ 缺失", file=sys.stderr)
            continue
        targets.append((pid, sid, main))

    todo = [
        t
        for t in targets
        if not (work / rescue_arm / t[1] / Path(t[2]).with_suffix(".pdf")).exists()
    ]
    print(
        f"rescue-en: {len(targets)} candidates, {len(todo)} to compile",
        file=sys.stderr,
    )

    def _one(pid: str, sid: str, main: str) -> dict:
        wdir = work / rescue_arm / sid
        if wdir.exists():
            shutil.rmtree(wdir)
        shutil.copytree(
            corpus / pid / "extracted", wdir, ignore=benchlib.copytree_ignore()
        )
        # TEXMFHOME 进子进程 env——必须绝对路径（xelatex cwd=wdir，相对路径
        # 会在 wdir 下解析→静默找不到包，2026-09-16 rescue 全军覆没于此）
        texmf = (work / "_texmf" / sid).resolve()
        eng = XelatexEngine(
            halt_on_error=False, texmfhome=texmf if texmf.is_dir() else None
        )
        try:
            res = eng.compile(wdir, main, timeout=timeout, sandbox=False)
            v = judge(res, expect_cjk=False)
            return {
                "id": pid,
                "arm": rescue_arm,
                "texmf": texmf.is_dir(),
                "verdict": v.status,
                "pdf": res.pdf_bytes,
                "seconds": round(res.seconds, 1),
                "first_error": res.log.first_error,
            }
        except Exception as e:
            return {
                "id": pid,
                "arm": rescue_arm,
                "verdict": "error",
                "error": repr(e)[:300],
            }

    rows = list(prior.values())
    with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
        futs = {ex.submit(_one, pid, sid, main): pid for pid, sid, main in todo}
        for fut in concurrent.futures.as_completed(futs):
            row = fut.result()
            rows.append(row)
            benchlib.append_jsonl(out / "rescue.jsonl", row)
            print(f"  rescue {row['id']}: {row.get('verdict')}", file=sys.stderr)
    return rows


# ---------------------------------------------------------------- selftest
def _selftest_pdf(path: Path, dests: list[tuple[str, int]], npages: int) -> None:
    """合成 PDF: npages 空白页 + [(name,page)] named destinations (FitH y=顶)."""
    from pypdf import PdfWriter
    from pypdf.generic import Destination, Fit

    w = PdfWriter()
    for _ in range(npages):
        w.add_blank_page(width=612, height=792)
    for name, page in dests:
        w.add_named_destination_object(
            Destination(
                name, w.pages[page].indirect_reference, Fit.fit_horizontally(792.0)
            )
        )
    with path.open("wb") as fh:
        w.write(fh)


def selftest(workdir: Path, min_retention: float) -> list[dict]:
    """四案断言: keep 全保留 / shift 整移保序 / drop 丢锚点检出 / degraded 退化."""
    workdir.mkdir(parents=True, exist_ok=True)
    base = [(f"section.{i}", i - 1) for i in range(1, 5)] + [
        (f"figure.{i}", i + 1) for i in range(1, 4)
    ]
    cases = {
        # B 原样 → 期望 ret=1.0 verdict=ok
        "keep": (base, base, 6),
        # B 整体 +1 页 → ret=1.0, page_diff 全 1, 链仍单调
        "shift": (base, [(n, p + 1) for n, p in base], 7),
        # B 丢 2 section + figure.1 挪到末页 → ret<0.95 verdict=low, 链反映断点
        "drop": (
            base,
            [(n, p) for n, p in base if n not in {"section.2", "section.3", "figure.1"}]
            + [("figure.1", 6)],
            7,
        ),
        # 双侧无锚点 → degraded 不崩
        "degraded": ([], [], 4),
        # B 侧 15B stub (kill 截断编译产物) → invalid_pdf(b), 不炸对子
        "corrupt": (base, "STUB", 6),
    }
    results = []
    for tag, (da, db, npages) in cases.items():
        a, b = workdir / f"st_{tag}_a.pdf", workdir / f"st_{tag}_b.pdf"
        _selftest_pdf(a, da, npages)
        if db == "STUB":
            b.write_bytes(b"%PDF-1.7\n%\xe4\xf0\xed\xf8\n")  # 15B kill 截断 stub
        else:
            _selftest_pdf(b, db, npages)
        res = analyze_pair(
            {"kind": "selftest", "id": f"selftest/{tag}", "a": a, "b": b}, min_retention
        )
        results.append(res)

    fails = []
    by_id = {r["id"].split("/")[1]: r for r in results}
    if by_id["keep"]["retention"] != 1.0 or by_id["keep"]["verdict"] != "ok":
        fails.append("keep: 期望 ret=1.0/ok")
    if by_id["shift"]["retention"] != 1.0 or by_id["shift"]["page_diff"]["median"] != 1:
        fails.append("shift: 期望 ret=1.0 且 page_diff 全 1")
    dr = by_id["drop"]
    if (
        dr["verdict"] != "low"
        or dr["retention"] is None
        or dr["retention"] >= min_retention
    ):
        fails.append("drop: 期望 verdict=low 且 ret<门槛")
    if not {"section.2", "section.3"} <= set(dr["lost_a"]):
        fails.append("drop: lost_a 未含丢掉的锚点名")
    dg = by_id["degraded"]
    if dg["verdict"] != "degraded" or dg["retention"] is not None:
        fails.append("degraded: 期望 verdict=degraded 且 ret=None")
    cp = by_id["corrupt"]
    if cp["verdict"] != "invalid_pdf" or cp["invalid_side"] != "b":
        fails.append("corrupt: 期望 verdict=invalid_pdf 且 side=b")
    return results, fails


# ---------------------------------------------------------------- 聚合/报告
def _pct_vals(vals: list[float]) -> dict:
    if not vals:
        return {}
    s = sorted(vals)

    def q(x: float) -> float:
        return s[max(0, math.ceil(x * len(s)) - 1)]

    return {
        "n": len(s),
        "min": s[0],
        "p50": q(0.50),
        "mean": round(sum(s) / len(s), 4),
        "p95": q(0.95),
        "max": s[-1],
    }


def aggregate(results: list[dict], min_retention: float) -> dict:
    errors = [r for r in results if "error" in r]
    invalid = [r for r in results if r.get("verdict") == "invalid_pdf"]
    ok_results = [
        r for r in results if "error" not in r and r.get("verdict") != "invalid_pdf"
    ]
    degraded = [r for r in ok_results if r["verdict"] == "degraded"]
    hyper = [r for r in ok_results if r["verdict"] != "degraded"]
    low = [r for r in hyper if r["verdict"] == "low"]

    by_kind = {}
    for r in ok_results:
        k = by_kind.setdefault(r["kind"], {"n": 0, "degraded": 0, "low": 0, "rets": []})
        k["n"] += 1
        k["degraded"] += r["verdict"] == "degraded"
        k["low"] += r["verdict"] == "low"
        if r["retention"] is not None:
            k["rets"].append(r["retention"])
    for k in by_kind.values():
        k["retention"] = _pct_vals(k.pop("rets"))

    for r in low:  # low-retention 联判编译 verdict（pipefix 口径）
        r["blame"] = _blame(r)
    blame_tally = dict(Counter(r["blame"] for r in low))

    gates = {
        "no_pair_errors": not errors,
        "hyperref_retention": all(
            r["retention"] >= min_retention for r in hyper if r["retention"] is not None
        ),
        # 退化路径: 双侧无锚点 → 正常出 degraded verdict (不崩不出错)
        "degraded_path_ok": all(
            r["retention"] is None and r["dests_a"] == 0 for r in degraded
        ),
    }
    return {
        "n_pairs": len(results),
        "n_error": len(errors),
        "n_invalid": len(invalid),
        "n_degraded": len(degraded),
        "n_hyperref": len(hyper),
        "n_low": len(low),
        "retention": _pct_vals(
            [r["retention"] for r in hyper if r["retention"] is not None]
        ),
        "chain_w_ratio": _pct_vals(
            [r["chain"]["w_ratio"] for r in hyper if r["chain"]["w_ratio"] is not None]
        ),
        "by_kind": by_kind,
        "blame_tally": blame_tally,
        "low_pairs": [
            {
                "id": r["id"],
                "retention": r["retention"],
                "lost": r["lost_a"][:10],
                "blame": r["blame"],
                "product_arm": r.get("product_arm"),
                "zh_compile_verdict": r.get("zh_compile_verdict"),
                "pipe_xel_verdict": r.get("pipe_xel_verdict"),
                "pipe_fix_verdict": r.get("pipe_fix_verdict"),
            }
            for r in low
        ],
        "invalid_pairs": [
            {"id": r["id"], "side": r["invalid_side"], "detail": r["detail"]}
            for r in invalid
        ],
        "error_pairs": [{"id": r["id"], "error": r["error"]} for r in errors],
        "min_retention": min_retention,
        "gates": gates,
        "gates_pass": all(gates.values()),
    }


def write_summary(out: Path, results: list[dict], cells: dict, wall_s: float) -> str:
    g = cells["gates"]
    lines = ["# alignbench — B7 锚点保留基准\n"]
    lines.append(
        f"- date: {datetime.now(UTC):%Y-%m-%d %H:%M}Z · wall {wall_s:.1f}s "
        f"· 门槛 retention ≥ {cells['min_retention']}"
    )
    lines.append(
        f"- pairs: {cells['n_pairs']} (hyperref {cells['n_hyperref']} · "
        f"degraded {cells['n_degraded']} · low {cells['n_low']} · "
        f"invalid {cells.get('n_invalid', 0)} · error {cells['n_error']})"
    )
    ret = cells["retention"]
    if ret:
        lines.append(
            f"- retention: min {ret['min']} · p50 {ret['p50']} · mean {ret['mean']}"
        )
    cw = cells["chain_w_ratio"]
    if cw:
        lines.append(f"- chain w_ratio: min {cw['min']} · p50 {cw['p50']}")
    lines.append(
        f"- **gates**: no_errors={'✅' if g['no_pair_errors'] else '❌'} · "
        f"retention≥{cells['min_retention']}={'✅' if g['hyperref_retention'] else '❌'} · "
        f"degraded_ok={'✅' if g['degraded_path_ok'] else '❌'}\n"
    )

    lines.append("## 逐对明细\n")
    lines.append(
        "| pair | kind | verdict | arm | zh_v | dests a→b | common | ret "
        "| Δp med | chain w |"
    )
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in results:
        if "error" in r:
            lines.append(
                f"| {r['id']} | {r['kind']} | ERROR | - | - | - | - | - | - | - |"
            )
            continue
        arm = r.get("product_arm") or "-"
        zv = r.get("zh_compile_verdict") or "-"
        if r["verdict"] == "invalid_pdf":
            lines.append(
                f"| {r['id']} | {r['kind']} | invalid({r['invalid_side']}) "
                f"| {arm} | {zv} | - | - | - | - | - |"
            )
            continue
        ret_s = f"{r['retention']:.3f}" if r["retention"] is not None else "n/a"
        wr = r["chain"]["w_ratio"]
        lines.append(
            f"| {r['id']} | {r['kind']} | {r['verdict']} | {arm} | {zv} "
            f"| {r['dests_a']}→{r['dests_b']} | {r['common']} | {ret_s} "
            f"| {r['page_diff']['median']} | {wr if wr is None else f'{wr:.3f}'} |"
        )
    lines.append("")

    if cells["low_pairs"]:
        lines.append("## 保留率不达标对（zh 编译完整性探针 + 编译 verdict 联判）\n")
        if cells.get("blame_tally"):
            tally = " · ".join(
                f"{k}×{v}" for k, v in sorted(cells["blame_tally"].items())
            )
            lines.append(f"blame 分布: {tally}\n")
        lines.extend(
            f"- `{r['id']}` ret={r['retention']:.3f} blame={r.get('blame')} "
            f"arm={r.get('product_arm')} zh_v={r.get('zh_compile_verdict')} "
            f"(pipe-xel={r.get('pipe_xel_verdict')} "
            f"pipe-fix={r.get('pipe_fix_verdict')}) lost={r['lost']}"
            for r in cells["low_pairs"]
        )
        lines.append("")
    lost_any = [(r["id"], r["lost_a"]) for r in results if r.get("lost_a")]
    if lost_any:
        lines.append("## 丢锚点归因入口（→ fixtures B2 沉淀）\n")
        for pid, lost in lost_any[:20]:
            lines.append(f"- `{pid}`: {', '.join(lost[:12])}")
        lines.append("")
    if cells["error_pairs"]:
        lines.append("## 异常对\n")
        lines.extend(f"- `{r['id']}`: {r['error']}" for r in cells["error_pairs"])
        lines.append("")
    if cells.get("invalid_pairs"):
        lines.append("## 不可解析 PDF 对（编译段垃圾产物，B3/B5 已计 FAIL）\n")
        lines.extend(
            f"- `{r['id']}` side={r['side']}: {r['detail']}"
            for r in cells["invalid_pairs"]
        )
        lines.append("")
    text = "\n".join(lines)
    (out / "summary.md").write_text(text + "\n", encoding="utf-8")
    return text


# ---------------------------------------------------------------- main
def main() -> None:
    ap = argparse.ArgumentParser(description="B7 alignbench — 锚点保留基准")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--pairs", type=Path, help="jsonl 对子清单 {id,a,b,kind?}")
    src.add_argument("--a-dir", type=Path, help="A 侧 (en/基线) 产物树")
    src.add_argument("--selftest", action="store_true", help="合成对子冒烟")
    src.add_argument(
        "--e2e-real",
        type=Path,
        metavar="WORK",
        help="e2e_real_bench 产物树根 (bench/work_e2ereal)，配 --records",
    )
    ap.add_argument("--b-dir", type=Path, help="B 侧 (zh/变体) 产物树")
    ap.add_argument(
        "--kind", default="dir-pair", help="--a-dir/--b-dir 模式的 kind 标签"
    )
    ap.add_argument(
        "--records",
        type=Path,
        help="--e2e-real: run 的 results.json / records.jsonl（arm verdict 来源）",
    )
    ap.add_argument(
        "--corpus",
        type=Path,
        default=BENCH / "corpus_v3",
        help="--rescue-en 的 extracted/ 来源",
    )
    ap.add_argument(
        "--rescue-en",
        action="store_true",
        help="--e2e-real: base-xel 无 PDF 的工程用 fixloop usertree 补编译 en",
    )
    ap.add_argument("--jobs", type=int, default=4, help="--rescue-en xelatex 并发")
    ap.add_argument("--timeout", type=float, default=240.0, help="编译超时秒")
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--min-retention", type=float, default=MIN_RETENTION)
    ap.add_argument("--check", action="store_true", help="门槛断言, 失败退出码 1")
    args = ap.parse_args()

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    tag = "selftest" if args.selftest else ("e2ereal" if args.e2e_real else "pairs")
    out = args.out or (BENCH / "results" / f"alignbench-{tag}-{today}")
    out = out if out.is_absolute() else Path.cwd() / out
    out.mkdir(parents=True, exist_ok=True)

    t0 = time.perf_counter()
    selftest_fails = None
    pairs_path = out / "pairs.jsonl"
    if args.selftest:
        results, selftest_fails = selftest(out / "_selftest", args.min_retention)
        with pairs_path.open("w", encoding="utf-8") as fh:
            for r in results:
                benchlib.write_jsonl(fh, r)
    else:
        coverage = None
        if args.pairs:
            pairs = pairs_from_manifest(args.pairs)
        elif args.e2e_real:
            if not args.records:
                ap.error("--e2e-real 需配 --records")
            e2e_work = args.e2e_real.resolve()
            records = load_records_any(args.records)
            rescue_verdicts: dict[str, str] = {}
            if args.rescue_en:
                for row in rescue_en_baselines(
                    e2e_work,
                    records,
                    args.corpus,
                    out,
                    jobs=args.jobs,
                    timeout=args.timeout,
                ):
                    rescue_verdicts[row["id"]] = row.get("verdict")
            pairs, coverage = e2e_real_pairs(
                e2e_work, records, rescue_verdicts=rescue_verdicts
            )
            (out / "coverage.jsonl").write_text(
                "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in coverage),
                encoding="utf-8",
            )
        else:
            if not args.b_dir:
                ap.error("--a-dir 需配 --b-dir")
            pairs = pairs_from_dirs(args.a_dir, args.b_dir, args.kind)
        print(f"pairs: {len(pairs)}", file=sys.stderr)
        # pairs.jsonl append 真账：存量行按 (kind,id) 续跑跳过
        results = benchlib.read_jsonl(pairs_path)
        done = {f"{r.get('kind')}|{r.get('id')}" for r in results}
        if done:
            print(f"resume: {len(done)} prior rows kept", file=sys.stderr)
        with pairs_path.open("w", encoding="utf-8") as fh:
            for r in results:  # 压实重写存量行后继续 append
                benchlib.write_jsonl(fh, r)
            for p in pairs:
                if f"{p['kind']}|{p['id']}" in done:
                    continue
                try:
                    res = analyze_pair(p, args.min_retention)
                except Exception as e:  # 单对失败不拖垮整批
                    res = {
                        "kind": p["kind"],
                        "id": p["id"],
                        "error": f"{type(e).__name__}: {e}",
                    }
                results.append(res)
                benchlib.write_jsonl(fh, res)
                if "error" in res:
                    print(
                        f"[{res['kind']}] {res['id']}: ERROR {res['error']}",
                        file=sys.stderr,
                    )
                elif res["verdict"] == "invalid_pdf":
                    print(
                        f"[{res['kind']}] {res['id']}: invalid_pdf "
                        f"side={res['invalid_side']} {res['detail']}",
                        file=sys.stderr,
                    )
                else:
                    ret = (
                        f"{res['retention']:.3f}"
                        if res["retention"] is not None
                        else "n/a"
                    )
                    print(
                        f"[{res['kind']:12s}] {res['id']:28s} {res['verdict']:8s} "
                        f"dests {res['dests_a']}→{res['dests_b']} ret={ret} "
                        f"Δp med={res['page_diff']['median']} "
                        f"chain w={res['chain']['w_ratio']}",
                        file=sys.stderr,
                    )

    cells = aggregate(results, args.min_retention)
    cells["meta"] = {
        "out": str(out),
        "date": today,
        "min_retention": args.min_retention,
        "source": "selftest"
        if args.selftest
        else (
            f"e2e-real {args.e2e_real} records={args.records}"
            if args.e2e_real
            else str(args.pairs or f"{args.a_dir} ↔ {args.b_dir}")
        ),
        "selftest_fails": selftest_fails,
    }
    wall_s = time.perf_counter() - t0

    (out / "cells.json").write_text(
        json.dumps(cells, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    # 归因视图：每对一行 {verdict,retention,arm,编译 verdict 联判,丢失类别}
    with (out / "attribution.jsonl").open("w", encoding="utf-8") as fh:
        for r in results:
            benchlib.write_jsonl(
                fh,
                {
                    k: r.get(k)
                    for k in (
                        "id",
                        "kind",
                        "verdict",
                        "retention",
                        "blame",
                        "product_arm",
                        "en_arm",
                        "zh_compile_verdict",
                        "en_compile_verdict",
                        "pipe_xel_verdict",
                        "pipe_fix_verdict",
                        "base_xel_verdict",
                        "rel",
                        "pages_a",
                        "pages_b",
                        "dests_a",
                        "dests_b",
                        "common",
                        "only_a",
                        "cat_lost_a",
                        "invalid_side",
                        "detail",
                        "error",
                    )
                    if k in r
                },
            )
    text = write_summary(out, results, cells, wall_s)
    print("\n" + text)
    print(f"wrote {out}/{{pairs.jsonl,cells.json,summary.md}}")

    if selftest_fails is not None:
        if selftest_fails:
            print("SELFTEST FAIL:", *selftest_fails, sep="\n  ")
            sys.exit(1)
        print("SELFTEST PASS")
    if args.check and not cells["gates_pass"]:
        print("GATE FAIL", [k for k, v in cells["gates"].items() if not v])
        sys.exit(1)


if __name__ == "__main__":
    main()
