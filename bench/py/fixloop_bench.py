#!/usr/bin/env python3
r"""
fixloop_bench.py — M2 前置测量: 产品化 fixloop 引擎在 corpus_v2 40 篇无偏样本上的救回率.

底材: bench/results/compilebench-corpusv2-2026-09-15/sample.json (seed=20260915,
分层抽样 40 篇) + 同目录 cells.json 的 baseline 双引擎 verdict 做对拍.

每篇 × 每引擎一格: 拷贝 extracted/ → work_fixloop_v2/{pid}/{eng}/, 跑产品化
``texlate.compile.fixloop.fixloop`` (编译→logparse→taxonomy→规则修复→重编,
≤meta.loop.max_rounds=8 轮, 引擎 compile 240s/轮上限).

环境口径 (与 baseline 可比 + fixloop 需要装包能力):
  xelatex  : XelatexEngine(halt_on_error=True, texmfhome=work/{pid}/_texmf)
             —— 每篇独立冷 usertree (对齐 baseline 冷 TEXMF 语义), 装包走
             tlmgr --usermode 落该树; init-usertree 由引擎自动补
  tectonic : TectonicEngine(bundle=TECTONIC_BUNDLE_PIN) —— docs/08 §4.1 pin,
             与 rules.yaml filemap.version_guard epoch (2022-07-14) 配套;
             install_file 由 fixloop 注入 CtanFetcher (tlnet 拉包 cwd 平铺)
  sandbox  : compile(sandbox=False) —— 对齐 compilebench_v2 (env paranoid
             flags 但无 sandbox-exec); 且 _texmf 在 wdir 外, sandbox-exec
             白名单不含它会断 usermode 读写
  runner   : run_tool 规则 (updmap-user 等) 注入带 TEXMFHOME/VAR/CONFIG 的
             env —— 否则 fixloop 默认 subprocess 继承裸 os.environ, 会写
             用户真 ~/Library/texmf (污染 + 冷口径失效)
  filemap  : texlive.tlpdb 离线索引 (ctan.py 同款 oracle) —— `tlmgr search
             --global` 逐查询远端会吃镜像 round-robin 抖动 (2026-09-15 实测
             挂出假 "no package provides"); 索引一次性拉取后常驻
             ~/.texlate/cache/filemap.json, 同一份仓库知识无偏差
  mirror   : 所有 tlnet 访问钉 tuna (本机直连实测通; mirror.ctan.org 不通)。
             xelatex usertree `option repository` 逐篇钉; CtanFetcher mirror=TUNA

路由: route_project(prefer="xelatex") 只做记录与 reject 标注; 双引擎格都跑
(全量矩阵 + 回归数据, 非 fallback-only)。reject (\\documentstyle) 论文仍跑
xelatex 格验证 gate 规则真实点火。

产出 (bench/results/fixloop-corpusv2-2026-09-15/):
  cases.jsonl  fixloop 原生 case 沉淀 (CaseSink, triage 原料)
  cells.jsonl  逐格明细 (paper×engine, 含 rounds/actions/installed/verdict)
  cells.json   逐篇聚合 (baseline verdict + route + 双引擎 cell)
  summary.md   救回率 / 类别×救回矩阵 / 规则命中分布 / 未救回清单

用法:
  uv run python bench/py/fixloop_bench.py              # 跑样本 (可断点续跑)
  uv run python bench/py/fixloop_bench.py --only 1404  # 子集调试
  uv run python bench/py/fixloop_bench.py --report     # 只重算 cells+summary
Deps: uv venv (import texlate.*); 网络 (tlmgr --global / tlnet / tectonic bundle).
"""

import argparse
import contextlib
import json
import os
import shutil
import subprocess
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from pathlib import Path

from texlate.compile import (
    TectonicEngine,
    XelatexEngine,
    child_env,
    find_tool,
    route_project,
    run_process,
)
from texlate.compile.engine import TECTONIC_BUNDLE_PIN
from texlate.compile.fixloop import (
    CaseSink,
    CtanFetcher,
    TlpdbIndex,
    fixloop,
    load_ruleset,
)

ROOT = Path("~/src/texlate").expanduser().resolve()
CORPUS = ROOT / "bench/corpus_v2"
WORK = ROOT / "bench/work_fixloop_v2"
BASE = ROOT / "bench/results/compilebench-corpusv2-2026-09-15"
OUT = ROOT / "bench/results/fixloop-corpusv2-2026-09-15"
SAMPLE = BASE / "sample.json"
BASE_CELLS = BASE / "cells.json"

JOBS = 4
RS = load_ruleset()

#: tlnet 镜像钉选: 引擎子进程 (child_env) 不透传 *_PROXY → 直连; 本机直连实测
#: tuna/aliyun/sjtug 通、mirror.ctan.org round-robin 不通 (2026-09-15)。
#: usertree `option repository` 逐篇钉住 → tlmgr install 不再吃镜像抖动。
TUNA_TLNET = "https://mirrors.tuna.tsinghua.edu.cn/CTAN/systems/texlive/tlnet"

# ---------------- 引擎包装 ----------------


class _NoSandbox:
    """``compile(sandbox=False)`` 的 Engine 委托 (其余方法/属性透传).

    fixloop 的 ``eng.compile(wdir, main, passes=...)`` 调用面不变;
    ``ctan_fetch`` 注入经 __setattr__ 落到内层引擎 (fixloop._wire_engine)。
    """

    def __init__(self, eng: object) -> None:
        object.__setattr__(self, "_eng", eng)

    def __getattr__(self, k: str) -> object:
        return getattr(self._eng, k)

    def __setattr__(self, k: str, v: object) -> None:
        setattr(self._eng, k, v)

    def compile(self, wdir: Path, main: str, passes: int = 2) -> object:
        return self._eng.compile(wdir, main, passes=passes, sandbox=False)


# file→pkg oracle: 不用 `tlmgr search --global` (逐查询远端 tlpdb, 镜像 round-robin
# 实测会挂 → 假 "no package provides") —— 换 texlive.tlpdb 离线索引 (ctan.py 同款
# oracle, 一次性 ~2.8MB 下载后 ~/.texlate/cache/filemap.json 常驻)。同一份远端
# 仓库知识, 与环境冷热无关, 不引入测量偏差。
@lru_cache(maxsize=1)
def _index() -> TlpdbIndex | None:
    """惰性构建/装载共享 tlpdb 索引 (tuna 镜像); 失败返回 None → filemap 回退 tlmgr。"""
    try:
        return TlpdbIndex.ensure(mirror=TUNA_TLNET)
    except Exception:  # 索引不可用 → 回退 tlmgr search
        return None


def _texmf_env(texmf: Path) -> dict[str, str]:
    """usertree 三件套 env (与 XelatexEngine._env 的同名字典构造)."""
    return child_env(
        {
            "TEXMFHOME": str(texmf / "home"),
            "TEXMFVAR": str(texmf / "var"),
            "TEXMFCONFIG": str(texmf / "config"),
        }
    )


def _init_usertree(texmf: Path) -> None:
    """冷 usertree 预置: init-usertree + 钉 tuna 镜像 (写到本篇 usertree tlpdb).

    引擎 install_file 见到 tlpdb 已存在会跳过自建; 先钉镜像保证后续
    ``tlmgr --usermode install`` 不吃 mirror.ctan.org 的 round-robin 抖动。
    """
    tlmgr = find_tool("tlmgr")
    if tlmgr is None:
        return
    for sub in ("home", "var", "config"):
        (texmf / sub).mkdir(parents=True, exist_ok=True)
    env = _texmf_env(texmf)
    if not (texmf / "home" / "tlpkg" / "texlive.tlpdb").exists():
        run_process(
            [tlmgr, "--usermode", "init-usertree"],
            cwd=Path.cwd(),
            env=env,
            timeout=60,
        )
    run_process(
        [tlmgr, "--usermode", "option", "repository", TUNA_TLNET],
        cwd=Path.cwd(),
        env=env,
        timeout=30,
    )


def _texmf_runner(texmf: Path):
    """run_tool 规则 (updmap-user/mktextfm) 的子进程 env 须指向本篇 usertree。"""

    def run(
        argv: list[str], timeout: int, wdir: Path
    ) -> tuple[int | None, str, float, bool]:
        env = dict(os.environ)
        env.update(
            {
                "TEXMFHOME": str(texmf / "home"),
                "TEXMFVAR": str(texmf / "var"),
                "TEXMFCONFIG": str(texmf / "config"),
            }
        )
        t0 = time.time()
        try:
            p = subprocess.run(  # fixloop 动作原语, argv 无 shell
                argv,
                cwd=str(wdir),
                env=env,
                timeout=timeout,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                errors="replace",
                check=False,
            )
            return p.returncode, p.stdout or "", time.time() - t0, False
        except subprocess.TimeoutExpired as e:
            out = e.stdout or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            return None, out, time.time() - t0, True
        except OSError as e:
            return None, f"{type(e).__name__}: {e}", time.time() - t0, False

    return run


def _make_engine(name: str, texmf: Path, wdir: Path) -> _NoSandbox:
    if name == "xelatex":
        _init_usertree(texmf)
        eng = XelatexEngine(halt_on_error=True, texmfhome=texmf)
        idx = _index()
        if idx is not None:
            # 实例遮蔽 filemap: install_file 内部 self.filemap 调用也走索引
            eng.filemap = idx.query
    else:
        eng = TectonicEngine(bundle=TECTONIC_BUNDLE_PIN)
        # 预注入 ctan_fetch (同 _wire_engine 配方, 但 mirror 钉 tuna);
        # fixloop 见到非 None 即跳过自带注入
        vg = RS.filemap_cfg.get("version_guard") or {}
        eng.ctan_fetch = CtanFetcher(
            wdir,
            index=_index(),
            overrides=RS.filemap_cfg.get("overrides") or {},
            epoch=(str(vg["texlive_format_epoch"]) if vg.get("enabled") else None),
            mirror=TUNA_TLNET,
        )
    return _NoSandbox(eng)


# ---------------- 单篇执行 ----------------

IGNORE = shutil.ignore_patterns(
    "_tect_out",
    "*.aux",
    "*.log",
    "*.out",
    "*.toc",
    "*.lof",
    "*.lot",
    "*.fls",
    "*.fdb_latexmk",
    "*.synctex*",
    "*.blg",
    "texput.*",
    "missfont.log",
    ".DS_Store",
    "__pycache__",
)

ENGINES = ("xelatex", "tectonic")


def run_paper(p: dict, todo_engines: tuple[str, ...]) -> list[dict]:
    """对一篇跑剩余引擎格 → cell 记录列表 (每格一条)."""
    pid = p["id"]
    src = CORPUS / pid / "extracted"
    if not src.is_dir():
        return [
            {
                "paper_id": pid,
                "engine": e,
                "verdict": "no_source",
                "error": "extracted missing",
            }
            for e in todo_engines
        ]
    texmf = WORK / pid / "_texmf"
    sink = CaseSink(OUT / "cases.jsonl")
    cells = []
    for eng_name in todo_engines:
        if eng_name == "xelatex" and texmf.exists():
            shutil.rmtree(texmf)  # 重跑须从零冷启动, 防半成品 usertree 偏暖
        wdir = WORK / pid / eng_name
        if wdir.exists():
            shutil.rmtree(wdir)
        shutil.copytree(src, wdir, ignore=IGNORE)
        eng = _make_engine(eng_name, texmf, wdir)
        t0 = time.time()
        try:
            cell = fixloop(
                wdir,
                eng,
                ruleset=RS,
                engine_name=eng_name,
                corpus_id=pid,
                cond="fixloop",
                runner=_texmf_runner(texmf) if eng_name == "xelatex" else None,
                case_sink=sink,
            )
        except Exception as e:  # 格子崩溃记 verdict 不炸整批
            cell = {
                "project": pid,
                "engine": eng_name,
                "verdict": f"harness_crash:{type(e).__name__}",
                "log_excerpt": str(e)[:500],
                "rounds": [],
                "actions": [],
                "final_pdf": False,
            }
        cell["wall_s"] = round(time.time() - t0, 1)
        cell["paper_id"] = pid
        cell["band"] = p["band"]
        cell["tags"] = p["tags"]
        cells.append(cell)
    return cells


# ---------------- 汇总 ----------------

# fixloop verdict → baseline 可比层
TIER = {
    "clean": "clean",
    "acceptable_pdf": "clean~",  # pdf 且残留错 ≤3
    "dirty_pdf": "pdf~",
    "stuck": "fail",
    "max_rounds": "fail",
    "no_errors_no_pdf": "fail",
    "no_main_tex": "fail",
    "no_source": "fail",
}
GOOD = {"clean", "acceptable_pdf"}  # 可交付层
PDFY = {"clean", "acceptable_pdf", "dirty_pdf"}  # 出了 pdf 层


def tier_of(cell: dict) -> str:
    v = str(cell.get("verdict") or "")
    if v.startswith(("reject:", "unfixable:", "harness_crash:")):
        return "reject" if v.startswith("reject:") else "fail"
    if v in TIER:
        return TIER[v]
    return "fail"


def load_baseline() -> dict[str, dict]:
    """baseline cells.json → {(pid, eng): {verdict, category}} + 路由标签."""
    if not BASE_CELLS.exists():
        return {}
    d = json.loads(BASE_CELLS.read_text())
    out = {}
    for p in d["papers"]:
        for eng, r in (p.get("engines") or {}).items():
            out[(p["id"], eng)] = {
                "verdict": r.get("verdict"),
                "category": r.get("category"),
            }
    return out


def report(papers_meta: list[dict]) -> None:
    cells = [
        json.loads(ln)
        for ln in (OUT / "cells.jsonl").read_text().splitlines()
        if ln.strip()
    ]
    base = load_baseline()
    meta_by_id = {p["id"]: p for p in papers_meta}
    by_paper: dict[str, dict[str, dict]] = defaultdict(dict)
    for c in cells:
        by_paper[c["paper_id"]][c["engine"]] = c

    doc = {
        "meta": {
            "date": time.strftime("%Y-%m-%d %H:%M"),
            "corpus": str(CORPUS),
            "work": str(WORK),
            "texmf_mode": "per-paper cold usertree (tlmgr --usermode)",
            "tectonic_bundle": TECTONIC_BUNDLE_PIN,
            "rules": str(RS.path),
            "max_rounds": RS.max_rounds(),
        },
        "papers": [],
    }
    for pid in sorted(by_paper):
        pm = meta_by_id.get(pid, {})
        src = CORPUS / pid / "extracted"
        route = {"engines": [], "reject": None, "reasons": [], "non_utf8": False}
        if src.is_dir():
            with contextlib.suppress(Exception):
                r = route_project(src, prefer="xelatex")
                route = {
                    "engines": r.engines,
                    "reject": r.reject,
                    "reasons": r.reasons,
                    "non_utf8": r.non_utf8,
                }
        doc["papers"].append(
            {
                "id": pid,
                "band": pm.get("band"),
                "tags": pm.get("tags", []),
                "route": route,
                "baseline": {e: base.get((pid, e), {}) for e in ENGINES},
                "cells": by_paper[pid],
            }
        )
    (OUT / "cells.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, default=str) + "\n"
    )

    # ---- summary.md ----
    lines = []
    lines.append("# fixloop bench — corpus_v2 40 篇无偏样本 × 产品化规则库")
    lines.append("")
    lines.append(f"- 日期: {doc['meta']['date']}")
    lines.append(
        f"- 规则库: `{RS.path}` ({len(RS.rules)} 规则, max_rounds={RS.max_rounds()})"
    )
    lines.append(
        "- 口径: 每篇独立冷 `_texmf` usertree (xelatex) / pin bundle+ctan_fetch "
        "(tectonic); 无 sandbox-exec; fixloop 直跑 (无 normalize/inject 前置)"
    )
    lines.append(
        "- 对照: baseline = compilebench-corpusv2 同批样本原文直编 (clean/pdf~/FAIL)"
    )
    lines.append("")

    # §1 总救回率 (per engine + union)
    lines.append("## 1. 总救回率")
    lines.append("")
    lines.append(
        "| 引擎 | n | baseline clean/pdf~/FAIL | fixloop clean/ok~/dirty/fail/rej "
        "| FAIL→pdf | FAIL→clean层 |"
    )
    lines.append("|---|---|---|---|---|---|")
    for eng in ENGINES:
        cs = [c for c in cells if c["engine"] == eng]
        n = len(cs)
        bvc = Counter(
            (base.get((c["paper_id"], eng)) or {}).get("verdict", "?") for c in cs
        )
        fvc = Counter(tier_of(c) for c in cs)
        fail_cells = [
            c
            for c in cs
            if (base.get((c["paper_id"], eng)) or {}).get("verdict") == "FAIL"
        ]
        n_fail = len(fail_cells)
        resc_pdf = sum(1 for c in fail_cells if c.get("verdict") in PDFY)
        resc_good = sum(1 for c in fail_cells if c.get("verdict") in GOOD)
        lines.append(
            f"| {eng} | {n} | {bvc.get('clean', 0)}/{bvc.get('pdf~', 0)}/"
            f"{bvc.get('FAIL', 0)} | {fvc.get('clean', 0)}/{fvc.get('clean~', 0)}/"
            f"{fvc.get('pdf~', 0)}/{fvc.get('fail', 0)}/{fvc.get('reject', 0)} | "
            f"{resc_pdf}/{n_fail} | {resc_good}/{n_fail} |"
        )
    # union
    n_papers = len(by_paper)
    base_union_pdf = sum(
        1
        for pid in by_paper
        if any((base.get((pid, e)) or {}).get("pdf") for e in ENGINES)
        or any(
            (base.get((pid, e)) or {}).get("verdict") in ("clean", "pdf~")
            for e in ENGINES
        )
    )
    fl_union_pdf = sum(
        1
        for pid, cells_d in by_paper.items()
        if any(c.get("verdict") in PDFY for c in cells_d.values())
    )
    fl_union_good = sum(
        1
        for pid, cells_d in by_paper.items()
        if any(c.get("verdict") in GOOD for c in cells_d.values())
    )
    lines.append("")
    lines.append(
        f"**union (任一引擎)**: baseline pdf {base_union_pdf}/{n_papers} "
        f"→ fixloop pdf {fl_union_pdf}/{n_papers}, clean层 "
        f"{fl_union_good}/{n_papers}"
    )
    lines.append("")

    # §2 baseline verdict × fixloop verdict 矩阵 (per engine)
    lines.append("## 2. baseline → fixloop 转移矩阵")
    lines.append("")
    for eng in ENGINES:
        cs = [c for c in cells if c["engine"] == eng]
        lines.append(f"### {eng}")
        lines.append("")
        lines.append("| baseline \\ fixloop | clean | ok~ | pdf~ | fail | reject |")
        lines.append("|---|---|---|---|---|---|")
        for bv in ("clean", "pdf~", "FAIL", "no_main_tex", "no_source", None):
            sub = [
                c
                for c in cs
                if (base.get((c["paper_id"], eng)) or {}).get("verdict") == bv
            ]
            if not sub:
                continue
            t = Counter(tier_of(c) for c in sub)
            lines.append(
                f"| {bv} ({len(sub)}) | {t.get('clean', 0)} | "
                f"{t.get('clean~', 0)} | {t.get('pdf~', 0)} | {t.get('fail', 0)} |"
                f" {t.get('reject', 0)} |"
            )
        lines.append("")

    # §3 baseline 首错类别 × 救回 (FAIL 格)
    lines.append("## 3. baseline 失败类别 × 救回 (仅 baseline=FAIL 格)")
    lines.append("")
    lines.append("| 类别 | 引擎 | 格数 | 出pdf | clean层 | 未救回 paper (终态类别) |")
    lines.append("|---|---|---|---|---|---|")
    cat_eng: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for c in cells:
        b = base.get((c["paper_id"], c["engine"])) or {}
        if b.get("verdict") == "FAIL":
            cat_eng[(b.get("category") or "?", c["engine"])].append(c)
    for (cat, eng), cs in sorted(cat_eng.items(), key=lambda kv: -len(kv[1])):
        npdf = sum(1 for c in cs if c.get("verdict") in PDFY)
        ngood = sum(1 for c in cs if c.get("verdict") in GOOD)
        left = [
            f"{c['paper_id']}({c.get('final_cat') or c.get('verdict')})"
            for c in cs
            if c.get("verdict") not in PDFY
        ]
        lines.append(
            f"| {cat} | {eng} | {len(cs)} | {npdf} | {ngood} | "
            f"{'; '.join(left[:8]) or '—'} |"
        )
    lines.append("")

    # §4 规则命中分布 + 装包榜
    lines.append("## 4. 规则命中分布 (actions 计数; round=0 precheck, -1 gate)")
    lines.append("")
    lines.append("| 规则 | xelatex | tectonic | 所在格出pdf数 |")
    lines.append("|---|---|---|---|")
    rule_hit: dict[str, Counter] = defaultdict(Counter)
    rule_resc: dict[str, set] = defaultdict(set)
    for c in cells:
        for a in c.get("actions") or []:
            rid = a.get("rule")
            if not rid:
                continue
            rule_hit[rid][c["engine"]] += 1
            if c.get("verdict") in PDFY:
                rule_resc[rid].add((c["paper_id"], c["engine"]))
    for r in RS.rules:
        h = rule_hit.get(r.id, Counter())
        lines.append(
            f"| {r.id} ({r.phase}) | {h.get('xelatex', 0)} | "
            f"{h.get('tectonic', 0)} | {len(rule_resc.get(r.id, ()))} |"
        )
    lines.append("")
    inst = Counter(
        f for c in cells for f in (c.get("installed") or []) if c["engine"] == "xelatex"
    )
    if inst:
        lines.append("### xelatex 装包榜 (tlmgr --usermode, file 级)")
        lines.append("")
        lines.append("| 文件 | 格数 |")
        lines.append("|---|---|")
        for f, n in inst.most_common(30):
            lines.append(f"| {f} | {n} |")
        lines.append("")

    # §5 未救回清单
    lines.append("## 5. 未救回格 (verdict 非 clean/ok~/dirty, 按终态类别聚类)")
    lines.append("")
    lines.append("| paper | eng | verdict | 终态cat | 轮数 | log_excerpt |")
    lines.append("|---|---|---|---|---|---|")
    dead = [c for c in cells if c.get("verdict") not in PDFY]
    for c in sorted(dead, key=lambda c: (str(c.get("final_cat") or ""), c["paper_id"])):
        exc = (c.get("log_excerpt") or "").replace("\n", " ")[:140]
        lines.append(
            f"| {c['paper_id']} | {c['engine']} | {c.get('verdict')} | "
            f"{c.get('final_cat') or '—'} | {len(c.get('rounds') or [])} | {exc} |"
        )
    lines.append("")

    # §6 回归检查
    lines.append("## 6. 回归 (baseline 已出 pdf → fixloop 反而无 pdf)")
    lines.append("")
    reg = [
        c
        for c in cells
        if c.get("verdict") not in PDFY
        and (base.get((c["paper_id"], c["engine"])) or {}).get("verdict")
        in ("clean", "pdf~")
    ]
    if reg:
        lines.append("| paper | eng | baseline | fixloop verdict |")
        lines.append("|---|---|---|---|")
        for c in reg:
            bv = (base.get((c["paper_id"], c["engine"])) or {}).get("verdict")
            lines.append(f"| {c['paper_id']} | {c['engine']} | {bv} | {c['verdict']} |")
    else:
        lines.append("无。")
    lines.append("")

    # §7 逐格明细
    lines.append("## 7. 逐格明细")
    lines.append("")
    lines.append(
        "| paper | band | tags | route | xel: base→fix(轮/装包) | tec: base→fix |"
    )
    lines.append("|---|---|---|---|---|---|")
    for p in doc["papers"]:
        pid = p["id"]
        route_s = p["route"]["reject"] or "/".join(p["route"]["engines"]) or "—"
        row = [
            pid,
            str(p.get("band")),
            ",".join(t for t in p.get("tags", []) if t != "no-hyperref") or "—",
            route_s,
        ]
        for eng in ENGINES:
            c = p["cells"].get(eng, {})
            bv = (p["baseline"].get(eng) or {}).get("verdict", "?")
            v = c.get("verdict", "—")
            extra = (
                f"{len(c.get('rounds') or [])}r/{len(c.get('installed') or [])}i"
                if c
                else ""
            )
            row.append(f"{bv}→{v} {extra}".strip())
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    (OUT / "summary.md").write_text("\n".join(lines) + "\n")
    print(f"report -> {OUT}/summary.md, cells.json ({len(by_paper)} papers)")


# ---------------- 主流程 ----------------


def main() -> None:
    # --out 重绑后 run_paper/report 经全局读新目录 (v2 整改批次);
    # 模块级单例配置, noqa 保留直白写法
    global OUT  # noqa: PLW0603
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--jobs", type=int, default=JOBS)
    ap.add_argument("--only", default="")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--out",
        default=str(OUT),
        help="结果目录 (默认 fixloop-corpusv2-*; 整改批次用 fixloop-v2-*)",
    )
    args = ap.parse_args()
    OUT = Path(args.out).expanduser().resolve()

    sample = json.loads(SAMPLE.read_text())
    papers = sample["papers"]
    if args.only:
        pats = [s.strip() for s in args.only.split(",") if s.strip()]
        papers = [p for p in papers if any(s in p["id"] for s in pats)]
    if args.limit:
        papers = papers[: args.limit]

    OUT.mkdir(parents=True, exist_ok=True)
    if args.report:
        report(papers)
        return

    # 断点续跑: cells.jsonl 已有 (pid, engine) 跳过
    done = set()
    cells_path = OUT / "cells.jsonl"
    if cells_path.exists():
        for ln in cells_path.read_text().splitlines():
            if ln.strip():
                c = json.loads(ln)
                done.add((c["paper_id"], c["engine"]))
    tasks = []
    for p in papers:
        todo = tuple(e for e in ENGINES if (p["id"], e) not in done)
        if todo:
            tasks.append((p, todo))
    print(f"{len(tasks)} papers with remaining cells (jobs={args.jobs})", flush=True)
    WORK.mkdir(parents=True, exist_ok=True)

    with cells_path.open("a") as cj, ThreadPoolExecutor(args.jobs) as ex:
        futs = {ex.submit(run_paper, p, todo): p for p, todo in tasks}
        for fut in as_completed(futs):
            p = futs[fut]
            try:
                cells = fut.result()
            except Exception as e:
                print(f"[{p['id']}] CRASH {e}", flush=True)
                continue
            for c in cells:
                cj.write(json.dumps(c, ensure_ascii=False, default=str) + "\n")
            cj.flush()
            xv = next((c for c in cells if c["engine"] == "xelatex"), {}).get(
                "verdict", "-"
            )
            tv = next((c for c in cells if c["engine"] == "tectonic"), {}).get(
                "verdict", "-"
            )
            print(f"[{p['id']}] xel={xv} tec={tv}", flush=True)

    report(papers)


if __name__ == "__main__":
    main()
