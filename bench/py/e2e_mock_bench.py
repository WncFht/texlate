#!/usr/bin/env python3
r"""e2e mock bench — corpus39 全量 mock 翻译 → ctex 注入 → 双引擎编译基线（M0 出口判据）。

产品路径版（2026-09-15 起）：解析/翻译/注入/编译全走 ``texlate.*`` 正式实现
（texlate.e2e.{pipe_condition,base_condition}；翻译 = XlatPipeline(MockTranslator)
+ L0 校验器）。旧 miniscanner+BUG1–5 补丁链已退役——patch 全部进 texlate.latex。

每工程条件（attribution 设计来自 tmp/exp/e2e/pipeline.py）:
  base-xel : 原样复制 → xelatex（zh 失败时区分"原文就挂"vs"管线引入"）
  pipe-xel : normalize → mock 翻译 → prepare_chinese(ctex) → xelatex → judge
             → 非 clean 时 L2 回灌 + fixloop（产品完整修复链）
  pipe-tec : 同上 → tectonic
  base-tec : 原样复制 → tectonic（pipe-tec 非 clean 时归因补跑；
             pipe-tec 不在 --conditions 时按显式请求直跑）
  pipeB-xel: pipe-xel + Mode B 幻觉破坏（~30% 块丢/造占位符 → 校验链须 100% 捕获）
  pipeC-xel: pipe-xel + Mode C 位置扰动（~10% 占位符挪位 → 量化 splice 鲁棒性）

pipeB/pipeC 与 pipe 走**同一条 compile 尾段**（precheck + L2 回灌 + fixloop
+ inject reject→partial 口径——修复段 = ``pipecore.repair_chain`` 单件）——
verdict 跨臂可比；破坏记账只在翻译层叠加，尾段修复语义与产品路径一致。

路由先行：`route_project`（\documentstyle → reject；仍跑 base-xel 实证拒绝正确性）。
fault_chunks/leftover_ph 即管线 bug 信号（应零）。

用法:
  uv run python bench/py/e2e_mock_bench.py [--only SUBSTR] [--conditions base-xel,...]
      [--limit N] [--timeout SEC] [--tag NAME]
      [--corpus bench/corpus] [--layers core,hot] [--sample N --seed S]
      [--ids id1,id2]
产出: bench/results/e2emock-<tag>-<date>/{records.jsonl,results.json,matrix.md,summary.md,sample.json}
工作区: bench/work_e2emock/<cond>/<safe_id>/（gitignored 重产物；
  非默认 corpus 时隔离到 work_e2emock/<corpus名>/ 下防跨语料同 id 互踩）

--corpus 两种布局自动识别：bench/corpus 两级叶目录（默认）| corpus
manifest*.jsonl + {id}/extracted/（有 manifest 即走 v3 枚举，只收 extracted
在盘条目；--layers 过滤层，默认全部在盘层）。
"""

from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
#: TEXLATE_SRC 可指向冻结快照目录（内含 texlate/ 包）——长 bench 期间 src/
#: 被并行代理实时改动时隔离用（同 e2e_real_bench 约定）。
sys.path.insert(0, os.environ.get("TEXLATE_SRC", str(ROOT / "src")))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # specs.* 同目录包

import benchlib

from texlate import repair_l2 as repair_mod
from texlate.compile.engine import route_project
from texlate.compile.inject import InjectRejectError, find_main_tex, prepare_chinese
from texlate.compile.normalize import normalize_project
from texlate.e2e import base_condition, pipe_condition
from texlate.latex.placeholder import PH_RX
from texlate.pipecore import (
    PipeJob,
    RepairPolicy,
    baseline_snapshot,
    compile_judge_tail,
    delivered,
    probe_report,
    repair_chain,
    translate_tree_run,
)
from texlate.pipecore import (
    scan_tree as _scan_tree,
)
from texlate.repair import embed_tounicode_quiet
from texlate.textutil import env_flag
from texlate.validate.l0 import validate_pair
from texlate.xlat.pipeline import MockTranslator

CORPUS = ROOT / "bench/corpus"
WORK = ROOT / "bench/work_e2emock"
RESULTS_DIR_DEFAULT = "e2emock-corpus39"

# ---------------------------------------------------------------- Mode B/C
# 注入层唯一事实源 = specs/_sabotage.py（translators_bench 台账臂同引；
# 决策 = f(段内容哈希) 确定性可复现）。下行为 re-export——``emb.X`` 面
# 不变（test_sabotage_arms 钉 _plan_b/_apply_*）；``translate_tree`` 与
# ``_scan_tree`` 留在本文件（fuzz spy 钉 ``emb._scan_tree`` 属性查找）。
from specs._sabotage import (
    DIRTY_SIGS,
    MODE_B_RATE,
    MODE_C_RATE,
    PerturbTranslator,
    SabotageTranslator,
    _NUM_LINE_RX,
    _apply_b,
    _apply_c,
    _canon,
    _dirty_hits,
    _h,
    _is_batch_user,
    _plan_b,
    _seg_of,
    _unwrap_seg,
)


def translate_tree(
    root: Path, translator: MockTranslator, *, env_judge: bool = False
) -> tuple[dict, repair_mod.TreeRun, list]:
    """``pipecore.translate_tree_run`` 薄壳 + 带出逐块 results（Mode B/C 归因账本用）。

    扫描段经 ``scan_fn`` 透传本模块 ``_scan_tree`` 绑定——文件名四门
    （dotfile/``.rtx.tex``/``.code.tex``/无散文 support）单源在
    ``pipecore.scan_tree``，fuzz spy 打 ``emb._scan_tree`` 即中；
    validator 同产品臂 L0 ``validate_pair`` 全量规则。返回
    ``(stats, TreeRun, 逐块 ChunkResult)``——TreeRun 与 pipe 臂同一
    运行态形状供归因账本/L2 回灌复用。
    """
    return translate_tree_run(
        root,
        translator=translator,
        env_judge=env_judge,
        scan_fn=_scan_tree,
        validator=lambda s, z: validate_pair(s, z).feedback(),
    )


def _probe_flags_of(work: Path, main_rel: str) -> tuple[str, ...]:
    """``probe_report`` 的旗标投影：声明侧编译旗标（minted→-shell-escape 等）。

    e2e ``_probe_flags_of`` 同款旁路语义——探针崩只空旗标返回，不阻塞编译。
    """
    rep = probe_report(work, main_rel)
    return tuple(rep.flags) if rep is not None else ()


def pipe_mode_condition(
    work: Path,
    eng_name: str,
    main_rel: str,
    timeout: float,
    mode: str,
    *,
    env_judge: bool | None = None,
    l2_on: bool | None = None,
    fixloop_on: bool | None = None,
    l2_max_chunks: int = repair_mod.L2_MAX_CHUNKS,
    route_engines: list[str] | None = None,
) -> dict:
    """pipe_condition 变体：翻译层换 Mode B/C 破坏 translator，其余全链同产品臂。

    Mode B 逐块结局：caught (校验链拦下→原文回退) / recovered (阶梯修回干净)
    / escaped (校验放行且译文占位符 multiset 破坏残留)；dirty = 交付块 zh
    命中协议回显签名（multiset 可对而载荷脏，escaped 的内容通道盲区，
    repro-2410b）——门槛 = escaped==0 AND dirty==0。
    armed = 交付块 src 自带协议签名（src_legit）：裸包含下 echo 与忠实译文
    不可区分，armed channel 是 dirty 判定的结构性盲区——只观测不进门槛。
    dirty/armed 按全 delivered 块记账（内容通道与破坏选择正交——真模型
    parrot 可在非破坏块回显）；zh 命中按签名集合划分：zh−src = dirty
    （判定性 echo，进门槛）；zh∩src = ambig（armed 块上的不可判定命中，
    armed_zh 计数）。caught/recovered/escaped 仍为 sabotage 口径；
    by_kind 各桶是 sabotaged 块上的交叉表（含 armed 列）。
    Mode C: 挪位天然过 L0, 记账 moved + 落到 splice 的块数 (spliced)。
    编译尾段 = ``pipe_condition`` 同一条链：首编 → ``pipecore.repair_chain``
    （precheck → L2 回灌 → fixloop），inject 拒绝同口径 ``partial``——
    verdict 与 pipe 臂直接可比。
    """
    rec: dict = {"engine": eng_name}
    rec["normalize"] = normalize_project(work, eng_name, main_rel)
    tr = SabotageTranslator() if mode == "B" else PerturbTranslator()
    ej = (
        env_flag(repair_mod.ENV_ENV_JUDGE, default=False)
        if env_judge is None
        else env_judge
    )
    # baseline 快照在翻译写回前抓（e2e._baseline_snapshot 同位：normalize 过的
    # 英文 pristine 树 → fixloop restore_support_from_src 的复原源）；fixloop
    # 关时跳过省一次全树 copytree。_td 须活到修复链收敛——局部绑定持到
    # 函数返回即随帧清理，快照寿命=修复链全程。
    fl = RepairPolicy.resolve(fixloop_on=fixloop_on).fixloop
    _td = baseline_snapshot(work, enabled=fl)
    baseline_dir = Path(_td.name) / "base" if _td is not None else None
    stats, run, results = translate_tree(work, tr, env_judge=ej)
    rec["translate"] = stats
    # 事件归因 → 逐块结局；env_judge 回落的块视同未进 splice（防 escaped 虚报）
    reverted = set(stats["env_judge"].get("reverted") or ())
    src_ph = lambda s: sorted(PH_RX.findall(s))  # noqa: E731
    ledger: dict = {"events": len(tr.events), "sabotaged": 0, "moved": 0}
    if mode == "B":
        ledger.update(
            {
                "caught": 0,
                "recovered": 0,
                "escaped": 0,
                "dirty": 0,
                "armed": 0,
                "armed_zh": 0,
                "escaped_ids": [],
                "escaped_detail": [],
                "dirty_ids": [],
                "dirty_detail": [],
                "armed_ids": [],
                "armed_detail": [],
                "by_kind": {},
            }
        )
    else:
        ledger.update({"spliced": 0, "dropped": 0})
    for r in results:
        # 交付谓词与 splice 同口径：``delivered`` 放行 partial（旧 spliced_ok
        # 严卡 ok 把脏 partial 记成 caught——连 escaped 都不进的反向漏账）。
        is_delivered = delivered(r) and r.chunk_id not in reverted
        if mode == "B":
            # 内容通道度量按全 delivered 块记账（非仅 sabotaged）：armed =
            # src 自带签名 → 同形 echo 裸包含不可判定；dirty = zh 命中中
            # src 解释不了的签名（判定性 echo）。
            zh_hits = _dirty_hits(r.translation) if is_delivered else []
            src_legit = _dirty_hits(r.source) if is_delivered else []
            ambig = [s for s in zh_hits if s in src_legit]
            hits = [s for s in zh_hits if s not in src_legit]
            if src_legit:
                ledger["armed"] += 1
                ledger["armed_ids"].append(r.chunk_id)
                ledger["armed_zh"] += bool(ambig)
                ledger["armed_detail"].append(
                    {"chunk": r.chunk_id, "src_legit": src_legit, "ambig": ambig}
                )
            if hits:
                ledger["dirty"] += 1
                ledger["dirty_ids"].append(r.chunk_id)
                ledger["dirty_detail"].append(
                    {"chunk": r.chunk_id, "hits": hits, "ambig": ambig}
                )
        evs = [e for e in tr.events if _seg_of(r.source, e["seg"])]
        if not evs:
            continue
        ledger["sabotaged"] += 1
        ledger["moved"] += sum(e.get("moved", 0) for e in evs)
        if mode == "B":
            kinds = "+".join(sorted({e.get("kind", "?") for e in evs}))
            bk = ledger["by_kind"].setdefault(
                kinds,
                {"caught": 0, "recovered": 0, "escaped": 0, "dirty": 0, "armed": 0},
            )
            if is_delivered and src_legit:
                bk["armed"] += 1
            if is_delivered and hits:
                bk["dirty"] += 1
            if not is_delivered:
                ledger["caught"] += 1  # fault/skipped/env回落 → 原文回退
                bk["caught"] += 1
            elif src_ph(r.translation) != src_ph(r.source):
                ledger["escaped"] += 1
                bk["escaped"] += 1
                ledger["escaped_ids"].append(r.chunk_id)
                src_m, zh_m = Counter(src_ph(r.source)), Counter(src_ph(r.translation))
                ledger["escaped_detail"].append(
                    {
                        "chunk": r.chunk_id,
                        "kinds": kinds,
                        "details": [e.get("detail") for e in evs],
                        "lost": sorted((src_m - zh_m).elements()),
                        "extra": sorted((zh_m - src_m).elements()),
                    }
                )
            else:
                ledger["recovered"] += 1
                bk["recovered"] += 1
        elif is_delivered:
            ledger["spliced"] += 1  # 挪位译文进了文档 → 编译判存活
        else:
            ledger["dropped"] += 1
    rec["sabotage"] = ledger
    try:
        rec["inject"] = prepare_chinese(work, main_rel)
    except InjectRejectError as e:
        # 与 pipe_condition 同口径：策略拒绝 → partial (F3), reject_at 审计
        rec["status"] = "partial"
        rec["reject_at"] = "inject"
        rec["verdict"] = {"status": "partial", "reasons": [e.reason]}
        return rec
    job = PipeJob(
        work,
        main_rel,
        eng_name,
        timeout,
        probe_flags=_probe_flags_of(work, main_rel),
    )
    # 0-chunk 主文档不期待 CJK (与 pipe_condition 同口径，F 桶假阳修)
    expect_cjk = stats.get("chunks") != 0
    tail, res = compile_judge_tail(job, expect_cjk=expect_cjk)
    rec.update(tail)

    if rec["status"] != "clean":
        # 修复链 = pipecore.repair_chain 单件（precheck → L2 回灌 → fixloop，
        # 与 pipe_condition 同一条链；开关 RepairPolicy 决议，baseline_dir
        # 喂 restore_support_from_src）
        res = repair_chain(
            rec,
            job,
            run,
            res,
            expect_cjk=expect_cjk,
            l2_on=l2_on,
            fixloop_on=fl,
            l2_max_chunks=l2_max_chunks,
            route_engines=route_engines,
            baseline_dir=baseline_dir,
        )
    # ToUnicode 注入在修复链收敛之后 (pipe_condition 同位，worker 同口径)
    if res.has_pdf and res.pdf is not None:
        rec["tounicode_fonts"] = embed_tounicode_quiet(res.pdf)
    return rec


# ---------------------------------------------------------------- 条件执行
def run_condition(
    cond: str,
    src: Path,
    sid: str,
    main_rel: str,
    timeout: float,
    work: Path | None = None,
) -> dict:
    """单条件：复制 → (pipe/pipeB/pipeC: 管线变体 | base: 原样) → compile → judge。"""
    work = WORK if work is None else work
    engine_name = "xelatex" if cond.endswith("xel") else "tectonic"
    dst = work / cond / sid
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    if cond.startswith("pipeB-"):
        return pipe_mode_condition(dst, engine_name, main_rel, timeout, "B")
    if cond.startswith("pipeC-"):
        return pipe_mode_condition(dst, engine_name, main_rel, timeout, "C")
    if cond.startswith("pipe"):
        return pipe_condition(dst, engine_name, main_rel, timeout)
    return base_condition(dst, engine_name, main_rel, timeout)


def _v3_layers(corpus: Path) -> list[str]:
    """corpus dev 可枚举层——benchlib.dev_layers 单源（holdout 仅评测层排除，
    评测走显式 --layers）。"""
    return benchlib.dev_layers(corpus)


def list_projects(
    corpus: Path | None = None, layers: set[str] | None = None
) -> list[str]:
    """工程枚举。

    corpus39 布局（默认）：直接含 .tex 的顶层目，或 hep-th/math 下的二级目。
    corpus 布局（manifest*.jsonl 存在）：manifest 条目里 extracted/ 在盘者，
    ``--layers`` 可过滤层（默认全部在盘层）。
    """
    corpus = CORPUS if corpus is None else corpus
    if _v3_layers(corpus):
        rows = benchlib.load_manifest_rows(
            corpus, sorted(layers) if layers else _v3_layers(corpus)
        )
        return sorted(
            {
                e["id"]
                for e in rows
                if (corpus / e["id"] / "extracted").is_dir()
                or any((corpus / e["id"]).glob("*.tex"))  # v1 层裸布局
            }
        )
    out = []
    for p in sorted(corpus.iterdir()):
        if not p.is_dir():
            continue
        if any(p.glob("*.tex")):
            out.append(p.name)
        else:
            out.extend(
                f"{p.name}/{d.name}"
                for d in sorted(p.iterdir())
                if d.is_dir() and any(d.glob("*.tex"))
            )
    return out


safe_id = benchlib.safe_id


def run_project(
    rel: str,
    conditions: list[str],
    timeout: float,
    corpus: Path | None = None,
    work: Path | None = None,
) -> dict:
    corpus = CORPUS if corpus is None else corpus
    work = WORK if work is None else work
    src = corpus / rel
    if (src / "extracted").is_dir():
        src = src / "extracted"  # corpus 布局：{id}/extracted/ 是源码根
    sid = safe_id(rel)
    rec: dict = {"id": rel}
    meta_p = src.parent / "meta.json" if src.name == "extracted" else None
    if meta_p is not None and meta_p.exists():
        rec["layer"] = json.loads(meta_p.read_text()).get("layer")
    main_path = find_main_tex(src)
    if main_path is None:
        rec["error"] = "no main tex"
        return rec
    main_rel = main_path.relative_to(src).as_posix()
    rec["main"] = main_rel
    route = route_project(src)
    rec["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    for cond in conditions:
        if cond == "base-tec":
            continue  # 见下——pipe-tec 在条件集时归因补跑，缺席时直跑
        rec[cond] = run_condition(cond, src, sid, main_rel, timeout, work)
    if "base-tec" in conditions:
        # pipe-tec 缺席时按显式请求直跑——旧口径 ``pt is not None`` 前置使
        # 请求的 base-tec 静默整臂跳过、零产出。
        pt = rec.get("pipe-tec", {}).get("verdict", {}).get("status")
        if "pipe-tec" not in conditions or pt not in (None, "clean"):
            rec["base-tec"] = run_condition(
                "base-tec", src, sid, main_rel, timeout, work
            )
    return rec


# ---------------------------------------------------------------- 报告
def _v(rec: dict, cond: str) -> str:
    c = rec.get(cond)
    if c is None:
        return "·"
    return c.get("verdict", {}).get("status", "?")


def write_reports(results: dict, out_dir: Path, corpus_name: str = "corpus39") -> None:
    cond_order = (
        "base-xel",
        "pipe-xel",
        "pipe-tec",
        "base-tec",
        "pipeB-xel",
        "pipeB-tec",
        "pipeC-xel",
        "pipeC-tec",
    )
    conds = [c for c in cond_order if any(r.get(c) for r in results.values())]
    rows = []
    for rel, rec in sorted(results.items()):
        cells = [_v(rec, c) for c in conds]
        route = rec.get("route", {})
        flag = "reject" if route.get("reject") else ""
        rows.append((rel, rec.get("main", "?"), flag, *cells))
    matrix = [
        "| 工程 | main | 路由 | " + " | ".join(conds) + " |",
        "| --- | --- | --- |" + " --- |" * len(conds),
    ]
    matrix.extend("| " + " | ".join(str(x) for x in r) + " |" for r in rows)
    (out_dir / "matrix.md").write_text("\n".join(matrix) + "\n", encoding="utf-8")

    lines = [f"# e2e mock bench — {corpus_name}", ""]
    for cond in conds:
        ran = [r[cond] for r in results.values() if r.get(cond)]
        clean = sum(1 for r in ran if r["verdict"]["status"] == "clean")
        lines.append(f"- **{cond}**: clean {clean}/{len(ran)}")
    lines.append("")
    # 归因：pipe 失败 ∧ base clean = 管线引入
    for eng in ("xel", "tec"):
        introduced = []
        for rel, rec in sorted(results.items()):
            p = rec.get(f"pipe-{eng}", {}).get("verdict", {}).get("status")
            b = rec.get(f"base-{eng}", {}).get("verdict", {}).get("status")
            if p not in (None, "clean") and b == "clean":
                introduced.append(rel)
        lines.append(f"- pipe-{eng} 失败且 base-{eng} clean（管线引入）: {introduced}")
    # Mode B/C 台账
    for mode, cond in (("B", "pipeB-xel"), ("C", "pipeC-xel")):
        recs = [(rel, r[cond]) for rel, r in sorted(results.items()) if r.get(cond)]
        if not recs:
            continue
        tot = {
            "events": 0,
            "sabotaged": 0,
            "moved": 0,
            "caught": 0,
            "recovered": 0,
            "escaped": 0,
            "dirty": 0,
            "armed": 0,
            "armed_zh": 0,
            "spliced": 0,
            "dropped": 0,
        }
        esc_ids: list[str] = []
        dirty_ids: list[str] = []
        armed_ids: list[str] = []
        for _rel, c in recs:
            led = c.get("sabotage", {})
            for k in tot:
                tot[k] += led.get(k, 0)
            esc_ids.extend(led.get("escaped_ids", []))
            dirty_ids.extend(led.get("dirty_ids", []))
            armed_ids.extend(led.get("armed_ids", []))
        lines.append(f"## Mode {mode} 台账 ({cond})")
        if mode == "B":
            gate = "PASS" if tot["escaped"] == 0 and tot["dirty"] == 0 else "FAIL"
            lines.append(
                f"- 注入破坏块 {tot['sabotaged']}（事件 {tot['events']}）→ "
                f"caught {tot['caught']} / recovered {tot['recovered']} / "
                f"**escaped {tot['escaped']}**"
            )
            lines.append(
                f"- dirty {tot['dirty']}（交付 zh 命中协议回显签名且 src 不含——"
                f"multiset 可对而载荷脏，escaped 的内容通道盲区）"
            )
            lines.append(
                f"- armed {tot['armed']}（交付块 src 自带协议签名——同形 echo "
                f"与忠实译文裸包含不可区分，结构性盲区只观测不进门槛；"
                f"其中 zh 同命中 {tot['armed_zh']} 块不可判定）"
            )
            lines.append(f"- 门槛 escaped==0 AND dirty==0: **{gate}**")
            if esc_ids:
                lines.append(f"- escaped chunk ids: {esc_ids}")
            if dirty_ids:
                lines.append(f"- dirty chunk ids: {dirty_ids}")
            if armed_ids:
                lines.append(f"- armed chunk ids: {armed_ids}")
        else:
            statuses = [c.get("verdict", {}).get("status") for _r, c in recs]
            dist = {s: statuses.count(s) for s in sorted(set(statuses))}
            lines.append(
                f"- 挪位 {tot['moved']} 处 / 涉块 {tot['sabotaged']} → "
                f"进 splice {tot['spliced']} / 回退 {tot['dropped']}；"
                f"编译 verdict 分布 {dist}"
            )
            # 存活率：Mode A (pipe-xel 同 commit 基线) 出 pdf 的篇 → C 仍出 pdf
            base_pdf = survived = 0
            broke: list[str] = []
            for rel, _c in recs:
                a = (
                    results.get(rel, {})
                    .get("pipe-xel", {})
                    .get("verdict", {})
                    .get("status")
                )
                if a not in ("clean", "partial"):
                    continue
                base_pdf += 1
                cst = _v(results[rel], cond)
                if cst in ("clean", "partial"):
                    survived += 1
                else:
                    broke.append(rel)
            if base_pdf:
                lines.append(
                    f"- 存活率 vs pipe-xel 基线：{survived}/{base_pdf} 篇出 pdf"
                    + (f"（退化：{broke}）" if broke else "")
                )
        lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def seed_results(rec_path: Path, out_path: Path) -> dict:
    """records.jsonl append 账优先（行在=done 末行胜）；账空（不存在/全坏行）
    → results.json 快照兜底；快照也坏 → 空。"""
    results = benchlib.load_records(rec_path) if rec_path.exists() else {}
    if not results and out_path.exists():
        try:
            loaded = json.loads(out_path.read_text())
        except (OSError, json.JSONDecodeError):
            loaded = {}
        results = loaded if isinstance(loaded, dict) else {}
    return results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="substring filter on project id")
    ap.add_argument("--conditions", default="base-xel,pipe-xel,pipe-tec,base-tec")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=240.0)
    ap.add_argument("--tag", default=RESULTS_DIR_DEFAULT)
    ap.add_argument("--date", default=str(datetime.now(UTC).date()))
    ap.add_argument(
        "--corpus",
        default=str(CORPUS),
        help="语料根：bench/corpus 两级叶目录 | corpus（manifest+{id}/extracted）",
    )
    ap.add_argument(
        "--layers",
        default=None,
        help="corpus 层过滤，逗号分隔（默认全部在盘 manifest 层）",
    )
    ap.add_argument("--ids", default=None, help="显式 id 逗号列表（跳过枚举 + 抽样）")
    ap.add_argument("--sample", type=int, default=None, help="枚举内 seed 随机抽 N 篇")
    ap.add_argument("--seed", type=int, default=42, help="--sample 随机种子")
    args = ap.parse_args()

    corpus = Path(args.corpus)
    if not corpus.is_absolute():
        corpus = ROOT / corpus
    layers = (
        {s.strip() for s in args.layers.split(",") if s.strip()}
        if args.layers
        else None
    )
    # 非默认语料隔一层工作区——跨语料同 id（如 hep-th/9901001）不互踩
    work = WORK if corpus == CORPUS else WORK / corpus.name

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    out_dir = ROOT / "bench/results" / f"{args.tag}-{args.date}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    rec_path = out_dir / "records.jsonl"
    # records.jsonl 是 append 真账（行在=done，末行胜）；results.json 为
    # 兼容旧 run 目录的兜底种子 + 逐篇快照。
    results = seed_results(rec_path, out_path)

    projects = list_projects(corpus, layers)
    if args.ids:
        projects = sorted(i.strip() for i in args.ids.split(",") if i.strip())
    elif args.sample is not None:
        rng = random.Random(args.seed)
        projects = sorted(rng.sample(projects, min(args.sample, len(projects))))
    (out_dir / "sample.json").write_text(
        json.dumps(
            {
                "corpus": str(corpus),
                "layers": sorted(layers) if layers else _v3_layers(corpus) or None,
                "sample": args.sample,
                "seed": args.seed,
                "ids": projects,
            },
            ensure_ascii=False,
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    for idx, rel in enumerate(projects):
        if args.only and args.only not in rel:
            continue
        if args.limit is not None and idx >= args.limit:
            break
        print(f"===== [{idx}/{len(projects)}] {rel} conds={conditions}", flush=True)
        try:
            rec = run_project(rel, conditions, args.timeout, corpus, work)
        except Exception as e:
            # 单篇崩不炸整批（e2e_real bench_error 同口径）
            rec = {"id": rel, "status": "bench_error", "error": repr(e)[:400]}
        merged = results.get(rel) or {}
        merged.update(rec)
        if "status" not in rec:
            # 成功 rec 无顶格 status——清掉上次 bench_error 残键防粘滞
            merged.pop("status", None)
            merged.pop("error", None)
        results[rel] = merged
        benchlib.append_jsonl(rec_path, results[rel])
        benchlib.atomic_write_text(
            out_path, json.dumps(results, ensure_ascii=False, indent=1)
        )
        write_reports(results, out_dir, corpus.name)
        stat = {c: _v(rec, c) for c in conditions}
        print(f"  -> {stat}", flush=True)
    print(f"done -> {out_dir}", flush=True)


if __name__ == "__main__":
    main()
