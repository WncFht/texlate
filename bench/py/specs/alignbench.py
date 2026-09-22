r"""alignbench spec — B7 锚点保留评测（原 ``bench/py/alignbench.py`` 的 spec 化）。

测量面不变：pypdf 提双侧 named destinations → 同名锚点配对 → 保留率 +
最大权值单调链（阅读器滚动同步质量上限，保留率 <95% 本身即 zh 编译完整性
探针）。格模型重做——一 (论文, rel pdf) 对子一格，eval 全格（id 免 canon，
eval_records 车道），``same_id_serial`` 串行同 paper 格共享
``paper_dir/_texmf`` 冷 usertree + ``workspace()/en`` 编译备忘。

对子来源双道（旧四源压成二）：
  manifest  ``TEXLATE_ALIGN_PAIRS`` env → pairs.jsonl 每行 {id,a,b,kind?,meta}
            —— 旧 --pairs 原义；任意 id 直收（eval 免 canon）。
  vault     ``vault_meta``(arm=real,variant=-,zone=primary,verdict=verified)
            → leaf_dir 下非点 ``*.pdf`` 逐 rel 一格——旧 --e2e-real 的正身：
            zh 产物 = 保险库已验叶（源 run verdict 元数据从 records 侧带）；
            en 侧不再读旧 work 树，每篇格内现编（``src_path()`` 湖投影 →
            copy_mutating → XelatexEngine+usertree，一次编译供全篇各 rel 格
            复用——旧 --rescue-en 的常态化形态）。湖格 skeleton → ``no_src``
            覆盖格；湖补水后同键自然升配对。
            ``up=vlt-<asset_sha[:12]>``：zh 叶任一重 harvest → 新格键重测，
            dedup 口径钉在产物字节而非 run 名上。``fp_input`` 同 sha。

状态映射（status_class 逐格声明；audit 三件套之 status 映射）：
  verdict ok          → ``ok``
  verdict low         → ``fail`` + sig=low_retention（保留率 < 门槛=测量判负）
  verdict degraded    → ``clean`` + metrics.all_degraded=1（A 侧零锚点=无
                        hyperref 工程，退化路径合法终态，不算低保留）
  verdict invalid_pdf → ``reject`` + errors[0].cat=upstream-lost（编译段垃圾
                        产物——stub/截断 PDF，对应 leg 上游已计 FAIL）
  unpaired            → ``clean`` + metrics.unpaired_reason（no_en_pdf:
                        en 编译完成但该 rel 无产物——确定性终态）
  zh 叶丢失/rel 不在  → ``skip``（retriable——vault restore/重 harvest 可回）
  湖格 skeleton       → ``skip`` + unpaired_reason=no_src（retriable——湖补
                        水后应重测，不是「无事可测」）
  en 编译例外         → ``error``（retriable；marker 备忘同 run 不重试，
                        跨 run workspace 换新重编）
  analyze_pair 例外   → ``error``（retriable——旧记 done-error 行，新口径
                        改 retriable，是刻意的 status 迁移）

done 定义（audit 三件套之二）：每格恰一条终态/可重试行；测量分母 =
verdict∈{ok,low,degraded,invalid_pdf} 格数；覆盖分母 = unpaired_reason
非空格数；两桶并集 = 全格数（分母守恒对拍：无静默丢格——旧循环里
``a_map.get(rel) is None → continue`` 的隐式跳过改为 no_en_pdf 覆盖格显式化，
en 编译只在 b 侧有 pdf 的 rel 上发生）。meta 键（product_arm 固定 'real'、
zh/en_compile_verdict、src_run、rel）随车进 metrics——low-retention 归因
（blame 列）同旧 b7-attribution-2026-09-16 口径。

参数面：``ids``/``only``/``lane``/``n``/``seed`` 为 select 闸（fp=False）；
``min_retention``/``timeout``/``en_compile`` 进 fp（测量语义旋钮）。
"""
from __future__ import annotations

import contextlib
import json
import os
import random
import re
import shutil
import sys
from collections import Counter
from pathlib import Path

try:
    import pypdf as _pypdf

    _PYPDF_V = _pypdf.__version__
except ImportError:
    _PYPDF_V = None

from kernel import fsutil, idnorm, vault
from kernel.spec import Param, Spec, Stage

from specs import _benchlite as benchlib

ROOT = Path(__file__).resolve().parents[3]

EPOCH = "v1"
MIN_RETENTION = 0.95
PAGE_ANCHOR_RX = re.compile(r"^page\.\d+$")

#: 旧 --a-dir/--b-dir 树配对的正身=manifest 行（调用方自配路径）；
#: 旧 --selftest 的正身=manifest 喂合成对子（spec 不自产 fixture——
#: 评测器冒烟由 manifest 道承担， lanes 常量化便于 select）。
LANES = ("vault", "manifest")


# ---------------------------------------------------------------- 锚点提取（逐行移植）
def _dest_page(r, dest) -> int | None:
    try:
        return r.get_destination_page_number(dest)
    except Exception:  # 坏 dest 当作缺失锚点
        return None


def extract_dests(path: Path) -> dict:
    """{name: {"page","yfrac","fit"}} + 页数; page.N 页码锚点单列不计入."""
    from pypdf import PdfReader

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


# docs/spec/benchmark.md §B7: section 12 / 图表 10 / equation 4 / cite 2 (page.* 排除等效权 0)
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


# ---------------------------------------------------------------- 对子分析（逐行移植）
def analyze_pair(a: Path, b: Path, min_retention: float) -> dict:
    """en/基线 a ↔ zh/变体 b 一对 → 测量行（verdict + 全字段）。"""
    try:
        ea = extract_dests(a)
    except Exception as e:  # 编译段垃圾产物 —— 非 harness 异常
        return {
            "verdict": "invalid_pdf",
            "invalid_side": "a",
            "detail": f"{type(e).__name__}: {e}",
        }
    try:
        eb = extract_dests(b)
    except Exception as e:
        return {
            "verdict": "invalid_pdf",
            "invalid_side": "b",
            "detail": f"{type(e).__name__}: {e}",
        }
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

    return {
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
        # 丢锚点全量名单 —— §B7-4 连锅端案例归因入口; 确认机制后应沉淀
        # bench/fixtures B2 断言（fixture_assert spec 的入库口）
        "lost_a": sorted(only_a),
        "new_b": sorted(only_b),
        "fits_a": ea["fits"],
        "fits_b": eb["fits"],
    }


def _blame(row: dict) -> str:
    """low-retention 归因列：联判 zh 侧编译 verdict（attribution-2026-09-16）。

    fail → 编译截断；partial → 编译 partial；clean → 编译干净仍丢锚点，
    splice/xlat 真问题；reject → inject_reject。
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


# ---------------------------------------------------------------- items：vault 道
def _verdict_meta(idx, idcs: list[str]) -> dict[str, dict]:
    """批量取 zh/en 编译 verdict 元数据（records 面，末条胜行口径）。

    新 trizone 里 zh 产物来自 stagerun/e2e 类 run：``compile`` 段 arm=zh
    up=real 是 zh 编译 verdict，arm=base 是 en 基线 verdict，``fixloop``
    段是 pipe-fix 对应腿。任一缺失 → None（meta 是归因材料，非配对前提）。
    """
    if not idcs:
        return {}
    out: dict[str, dict] = {i: {} for i in idcs}
    ph = ",".join("?" * len(idcs))
    sql = (
        "SELECT idc,arm,up,stage,status,ts FROM records "  # noqa: S608
        f"WHERE idc IN ({ph}) AND stage IN ('compile','fixloop') "
        "ORDER BY ts"  # IN 列表占位符参数化，仅长度动态
    )
    try:
        rows = idx.conn.execute(sql, idcs).fetchall()
    except Exception:
        return out
    for idc, arm, up, stage, status, _ts in rows:
        m = out.setdefault(str(idc), {})
        if stage == "fixloop":
            m["pipe_fix_verdict"] = status
        elif arm == "zh" or up == "real":
            m["zh_compile_verdict"] = status
        elif arm == "base":
            m["en_compile_verdict"] = status
    return out


def _vault_items() -> list[dict]:
    """verified primary splice 叶 → 逐 zh pdf rel 一格 + 零产物覆盖格。"""
    try:
        from kernel.index import Index
    except ImportError:
        return []
    try:
        idx = Index()
    except Exception:  # bench root 未初始化 —— 空道不炸 plan
        return []
    try:
        rows = idx.conn.execute(
            "SELECT idc,sha FROM vault_meta WHERE arm='real' AND variant='-' "
            "AND zone='primary' AND verdict='verified'"
        ).fetchall()
        meta_map = _verdict_meta(
            idx, [str(r[0]) for r in rows]
        )
    except Exception:
        return []
    items: list[dict] = []
    for idc0, sha in rows:
        idc = str(idc0)
        leaf = vault.leaf_dir("primary", "splice", idc, "real")
        up = f"vlt-{str(sha or '')[:12]}"
        meta = meta_map.get(idc) or {}
        pdfs = []
        if leaf.is_dir():
            pdfs = sorted(
                p.relative_to(leaf).as_posix()
                for p in leaf.rglob("*.pdf")
                if not p.name.startswith(".")
            )
        if not pdfs:
            items.append({
                "id": idc,
                "up": up,
                "variant": f"nocov@{EPOCH}",
                "lane": "vault",
                "fp_input": str(sha or ""),
                "params": {"unpaired_reason": "no_zh_pdf", **meta},
            })
            continue
        items.extend({
            "id": idc,
            "up": up,
            "variant": f"{rel[:-4]}@{EPOCH}",
            "lane": "vault",
            "fp_input": str(sha or ""),
            "params": {"rel": rel, **meta},
        } for rel in pdfs)
    return items


# ---------------------------------------------------------------- items：manifest 道
def _manifest_items() -> list[dict]:
    """``TEXLATE_ALIGN_PAIRS`` jsonl {id,a,b,kind?,meta} → 每行一格。"""
    env = os.environ.get("TEXLATE_ALIGN_PAIRS", "").strip()
    if not env:
        return []
    path = Path(env)
    if not path.is_file():
        print(f"  warn TEXLATE_ALIGN_PAIRS={env}: 不存在", file=sys.stderr)
        return []
    items = []
    for ln, row in enumerate(benchlib.iter_jsonl(path), 1):
        if not (row.get("a") and row.get("b")):
            continue
        pid = str(row.get("id") or Path(row["a"]).stem)
        fp_in = ""
        try:
            sa, sb = Path(row["a"]).stat(), Path(row["b"]).stat()
            fp_in = f"{sa.st_size}:{sa.st_mtime_ns}|{sb.st_size}:{sb.st_mtime_ns}"
        except OSError:
            print(f"  warn {path.name}:{ln} {pid}: a/b 不存在", file=sys.stderr)
        items.append({
            "id": pid,
            "up": "-",
            "variant": f"{Path(row['a']).stem}@{EPOCH}",
            "lane": "manifest",
            "fp_input": fp_in,
            "params": {
                "a": str(row["a"]),
                "b": str(row["b"]),
                "kind": row.get("kind", "manifest"),
                "meta": {
                    k: v
                    for k, v in row.items()
                    if k not in {"id", "a", "b", "kind"}
                },
            },
        })
    return items


def _items() -> list[dict]:
    return _vault_items() + _manifest_items()


_ITEMS: list[dict] | None = None


def _items_cached() -> list[dict]:
    global _ITEMS  # noqa: PLW0603
    if _ITEMS is None:
        _ITEMS = _items()
    return _ITEMS


def _sample_ids(n: int, seed: int) -> set[str]:
    """论文级 seeded 抽样（样本 n 篇 → 该篇全部 rel 格保留）。"""
    pool = sorted({str(it["id"]) for it in _items_cached()})
    rng = random.Random(seed)
    return set(rng.sample(pool, min(n, len(pool))))


def _select(item: dict, rp: dict) -> bool:
    """run 期收窄：lane → ids（raw/canon 双侧）→ only 子串 → n/seed 抽样。"""
    lanes = {
        s.strip()
        for s in str(rp.get("lane") or "vault,manifest").split(",")
        if s.strip()
    }
    if lanes and str(item.get("lane")) not in lanes:
        return False
    raw = str(item.get("id") or "")
    ids_p = str(rp.get("ids") or "").strip()
    if ids_p:
        want: set[str] = set()
        for tok0 in ids_p.split(","):
            tok = tok0.strip()
            if not tok:
                continue
            want.add(tok)
            r = idnorm.canon_id(tok)
            if r.ok and r.idc:
                want.add(r.idc)
        if raw not in want and raw.replace("--", "/") not in want:
            return False
    only = str(rp.get("only") or "").strip()
    if only and only not in raw:
        return False
    n = int(rp.get("n") or 0)
    if n > 0:
        seed = int(rp.get("seed") or 0)
        return raw in _sample_ids(n, seed)
    return True


# ---------------------------------------------------------------- en 基线格内编译
_EN_MARKER = ".align_en.json"


def _texmf(pdir: Path) -> Path:
    """冷 usermode texmf 三件套——同 paper 格共享（same_id_serial 串行防互踩）。"""
    tm = pdir / "_texmf"
    for sub in ("home", "var", "config"):
        (tm / sub).mkdir(parents=True, exist_ok=True)
    return tm


def _ensure_en(ctx) -> tuple[Path | None, dict]:
    """en 侧编译备忘：``workspace()/en`` + marker 一次编译全篇 rel 格复用。

    返回 (en_root|None, info)；info 携带 unpaired_reason/en_compile_verdict。
    """
    ws = ctx.workspace()
    en_root = ws / "en"
    marker = en_root / _EN_MARKER
    if marker.is_file():
        try:
            info = json.loads(marker.read_text(encoding="utf-8"))
            return en_root, {"en_compile_verdict": info.get("verdict"),
                             "en_rescued": 0}
        except (OSError, ValueError):
            pass  # marker 腐 → 重编
    if not ctx.params.get("en_compile", True):
        return None, {"unpaired_reason": "en_compile_off"}
    src = ctx.src_path()
    if src is None:
        return None, {"unpaired_reason": "no_src"}
    if en_root.exists():
        shutil.rmtree(en_root)  # 无 marker 的存量 = 上次半途崩——重投
    fsutil.copy_mutating(src, en_root)
    # 入口 tex：records 带不来的走 find_main_tex 探测（旧 rec.main 正身）
    from texlate.compile.mainfile import find_main_tex

    main = find_main_tex(en_root)
    if main is None:
        return None, {"unpaired_reason": "no_main_tex"}
    main_rel = main.relative_to(en_root).as_posix()
    from texlate.compile.engine import XelatexEngine
    from texlate.compile.judge import judge

    texmf = _texmf(ctx.paper_dir())
    eng = XelatexEngine(
        halt_on_error=False, texmfhome=texmf,
        repository=benchlib.TUNA_TLNET)
    timeout = float(ctx.params.get("timeout") or 240.0)
    env_extra = {
        "TEXMFHOME": str(texmf / "home"),
        "TEXMFVAR": str(texmf / "var"),
        "TEXMFCONFIG": str(texmf / "config"),
    }
    res = eng.compile(
        en_root, main_rel, passes=2, timeout=timeout,
        sandbox=False, env_extra=env_extra)
    v = judge(res, expect_cjk=False)
    info = {
        "verdict": v.status,
        "main_rel": main_rel,
        "pdf_bytes": res.pdf_bytes,
        "seconds": round(res.seconds, 1),
        "first_error": res.log.first_error,
        "error_cats": v.error_cats,
    }
    with contextlib.suppress(OSError):
        # marker 落不下只损同 run 备忘，不损测量
        marker.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")
    return en_root, {"en_compile_verdict": v.status, "en_rescued": 1,
                     "en_main_rel": main_rel,
                     "en_compile_s": info["seconds"]}


# ---------------------------------------------------------------- 格函数
def _al_pair(ctx):
    """一对 (a,b) 锚点保留测量格。"""
    p = ctx.params
    min_ret = float(p.get("min_retention") or MIN_RETENTION)
    lane = str(ctx.cell.get("lane") or "vault")
    meta: dict = {}
    a = b = None
    if lane == "manifest":
        a, b = Path(str(p["a"])), Path(str(p["b"]))
        meta = dict(p.get("meta") or {})
        meta["kind"] = p.get("kind") or "manifest"
    else:
        meta = {
            "kind": "e2e-real",
            "product_arm": "real",
            "zh_compile_verdict": p.get("zh_compile_verdict"),
            "en_compile_verdict": p.get("en_compile_verdict"),
            "pipe_xel_verdict": p.get("zh_compile_verdict"),
            "pipe_fix_verdict": p.get("pipe_fix_verdict"),
        }
        rel = str(p.get("rel") or "")
        if not rel:
            return {"status": "clean",
                    "metrics": {"unpaired_reason": p.get("unpaired_reason")
                                or "no_zh_pdf", **meta}}
        meta["rel"] = rel
        leaf = vault.leaf_dir("primary", "splice", ctx.idc, "real")
        b = leaf / rel
        if not b.is_file():
            # 叶被 evict / rel 消失 → retriable（restore 可回）
            return {"status": "skip",
                    "metrics": {"unpaired_reason": "zh_leaf_lost", **meta}}
        en_root, info = _ensure_en(ctx)
        meta.update({k: v for k, v in info.items() if v is not None})
        if en_root is None:
            return {"status": "skip" if info.get("unpaired_reason") == "no_src"
                    else "clean",
                    "metrics": {**meta}}
        a = en_root / rel
        if not a.is_file():
            return {"status": "clean",
                    "metrics": {"unpaired_reason": "no_en_pdf", **meta}}
    try:
        row = analyze_pair(a, b, min_ret)
    except Exception as e:
        return {
            "status": "error",
            "errors": [{"cat": "exception",
                        "msg": f"{type(e).__name__}: {e}"[:300]}],
            "metrics": meta,
        }
    row.update(meta)
    if _PYPDF_V:
        row["pypdf"] = _PYPDF_V
    verdict = row["verdict"]
    if verdict == "invalid_pdf":
        row["blame"] = "invalid_pdf"
        return {
            "status": "reject",
            "errors": [{"cat": "upstream-lost",
                        "msg": f"invalid_pdf side={row['invalid_side']}: "
                               f"{row['detail']}"[:300]}],
            "metrics": row,
        }
    if verdict == "low":
        row["blame"] = _blame(row)
        return {"status": "fail", "sig": "low_retention", "metrics": row}
    if verdict == "degraded":
        row["all_degraded"] = 1
        return {"status": "clean", "metrics": row}
    return {"status": "ok", "metrics": row}


# ---------------------------------------------------------------- spec
spec = Spec(
    kind="alignbench",
    params={
        "ids": Param(str, default="", fp=False),
        "only": Param(str, default="", fp=False),
        "lane": Param(str, default="vault,manifest", fp=False),
        "n": Param(int, default=0),
        "seed": Param(int, default=0),
        "min_retention": Param(float, default=MIN_RETENTION),
        "timeout": Param(float, default=240.0),
        "en_compile": Param(bool, default=True),
    },
    items=_items_cached,
    select=_select,
    stages=[
        Stage(
            "al_pair",
            _al_pair,
            status_class={
                "ok": "terminal",
                "fail": "terminal",
                "clean": "terminal",
                "reject": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
            eval=True,  # 测量行进 eval_records 道
        ),
    ],
    freeze_plan=True,
    executor="thread",
    same_id_serial=True,  # 同 paper 格共享 _texmf/workspace/en——串行防互踩
    lake=True,
    eval=True,  # manifest 任意 id 免 canon 闸；e2e id 本来即 canon
    env_probes=["xelatex", "tlmgr"],
    code_deps=[
        # 被测/测具面进 fp：en 编译链（引擎+judge+入口探测）+本 spec 自身
        # 自动计；pypdf 属 site-packages 无法钉仓内路径——版本随行进 metrics。
        "src/texlate/compile/engine",
        "src/texlate/compile/judge.py",
        "src/texlate/compile/mainfile.py",
        "src/texlate/compile/logparse.py",
    ],
)
