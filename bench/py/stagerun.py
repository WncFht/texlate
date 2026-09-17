#!/usr/bin/env python3
r"""stagerun.py — 分阶段批量驱动（batch-hardening §3 执行层）。

每阶段一子命令、独立 executor、append 式 records jsonl、按 (id, arm, upstream)
resume。论文流过 DAG 靠 ``work/{id}/`` 中间产物树而非内存对象。

    stagerun.py ingest  --layers core,booster        # corpus_v3 已物化副本 → work/{id}/src/
    stagerun.py parse   --n 3 --tag smoke            # → records/parse.jsonl + work/{id}/parse.json + zh/
    stagerun.py xlat    --arm mock --n 3 --tag smoke # → records/xlat.jsonl + zh/(译) + xlat-{arm}.jsonl
    stagerun.py compile --arm zh --n 3 --tag smoke   # → records/compile.jsonl + splice/
    stagerun.py compile --arm base --tag smoke       # → build-base/（原文直编归因臂）
    stagerun.py fixloop --on fail --tag smoke        # → records/fixloop.jsonl + cases.jsonl + splice/(修复)

work/{id}/ 契约（``--tag T`` → ``bench/results/stagerun-T-<date>/``）：

    src/              ingest：corpus_v3/{id}/extracted/ 原样副本（永不改——
                      compile --arm base 的「原文直编」归因基准）
    zh/               parse：src/ 副本 + route + normalize + 逐文件 parse_file
                      （归一化英文树）；xlat：就地翻译写回（splice 含在
                      translate_tree 内）。``zh/.xlat-arm.json`` 记录最近
                      一次翻译臂——compile zh 据此判 provenance。
    parse.json        parse 产物：main_rel / engine_resolved / route /
                      normalize stats / 逐文件 {chunks,warnings,inputs}
    xlat-{arm}.jsonl  xlat 逐块明细（chunk_id/status/attempts/warnings/...）
    splice/           compile --arm zh：zh/ 副本 + prepare_chinese(ctex) +
                      xelatex 产物原地。fixloop 就地修复此树（≈规格 §1 的
                      「zh/(repaired)」——物理落点是 splice/）。
    build-base/       compile --arm base：src/ 副本直编（无 normalize/inject）
    _texmf/           fixloop 每篇冷 usertree（tlmgr --usermode 装包落点）

resume 语义：records/{stage}.jsonl 里 (id, arm, upstream) 已记且 status ∉
{skip, error} 的格跳过；skip（上游门未过）/error（harness 崩）自动重试。
--rerun 全强制。compile --arm zh 另核 xlat 换代：同臂重译重建 zh/ 后
marker.ts 变，末条 metrics.xlat_ts 不符（含旧记缺印）即重编不吃陈记。
zh/ 与 splice/ 是臂间共享树：real 臂翻译会覆盖 mock 产物
（records 按臂分记、marker 记 provenance，compile --xlat-arm 可钉住预期）。

id 规范形：``--ids`` 收 safe_id flat 拼写（``work/`` 目名 ``math--X``）自动
归一回 ``math/X``——``canon_id`` 是 safe_id 逆；records 账键同口径 canon，
flat 存量账按规范形命中 resume。同 wid 任务去重（``dedup_wids``）：双拼写
撞名对坍缩成单任务，不再并发同树互 rmtree（loop1 实证 65 对并存，
``math--0408287`` 复判被罩的根因）。

与规格 §1/§3 的有意偏差（目录归谁写）：
  - zh/ 由 parse 建（normalize 必须有落点；src/ 留生料给 base 臂）；
    §1 图把 zh/ 画在 xlat 下——物理上 zh/ 是跨阶段共享演化的产品树。
  - parse.json 记 chunk 元数据（kind/span/文件归属）而非正文——reconstruct
    要 ScanResult（pieces/ph_map/macros），序列化不划算；xlat 重扫 ~1-3s/篇。
  - compile --post l2 留了旗标位但未接线：L2 回灌要 TreeRun 内存态 +
    编译尾段，跨 stage 文件协议暂不支持（TODO 同 T2 auth 熔断——见 §4 横切洞）。
  - channel=arxiv_eprint 缺 extracted 的条目 ingest 记 reject
    （eprint_fetch_unwired）——规格 §2 说逐篇 API 仅作旁路，未铺。
  - ingest 的 IA 拉取是 stub：未物化但具 item/member 的条目记 skip
    （ia_fetch_unwired，下轮自动重试），stub/pdf/error 格式记 reject。
    具体实现归数据侧（复用 build_corpus_v3 的 scan + item-index.csv
    成员级单抽）——本文件只保 records/work/{id}/src/ 契约。

executor：ingest ThreadPool(IO) / parse ProcessPool(CPU，pickle 边界=路径)
/ xlat asyncio（--sem 全局信号量压网关 in-flight，默认 4=gwcap 硬闸；--jobs
控制同时在翻的论文数）/ compile+fixloop ThreadPool(subprocess)。

模块布局（★6 拆包）：本文件只留 CLI——kernel 归 ``stagerun_lib``
（records 账/resume 谓词/run_meta/选样 + TEXLATE_SRC 路径设置），五支
stage 驱动各归 ``stage_{ingest,parse,xlat,compile,fixloop}.py``；
通用件单源在 ``benchlib``（pick_sample/code_stamp/preflight/
MAX_TOTAL_CHARS/AUTH_DEAD_STREAK/misschar_partial）——不再经
``e2e_real_bench`` 转手。原 ``stagerun.*`` 公开名全部经下方 re-export
保持可达。

用法（smoke，离线）：
  uv run python bench/py/stagerun.py parse --n 3 --tag smoke
  uv run python bench/py/stagerun.py xlat --arm mock --n 3 --tag smoke
  uv run python bench/py/stagerun.py compile --arm zh --n 3 --tag smoke
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import UTC, datetime

import benchlib
import stagerun_lib as sl
from stage_compile import stage_compile
from stage_fixloop import stage_fixloop
from stage_ingest import stage_ingest
from stage_parse import stage_parse
from stage_xlat import stage_xlat

# ---------------------------------------------------------------- 兼容 re-export
# 拆包前 stagerun.* 可达的名字全部保留（无外部 importer，按契约面保名）。
CORPUS = sl.CORPUS
DONE_STATUS = sl.DONE_STATUS
RETRIABLE_STATUS = sl.RETRIABLE_STATUS
STAGES = sl.STAGES
RecLog = sl.RecLog
select_ids = sl.select_ids
canon_id = sl.canon_id
dedup_wids = sl.dedup_wids
load_latest = sl.load_latest
make_sig = sl.make_sig
base_rec = sl.base_rec
finish_rec = sl.finish_rec
crash_rec = sl.crash_rec
git_rev = sl.git_rev
touch_run_meta = sl.touch_run_meta
mark_run_finished = sl.mark_run_finished
out_dir_of = sl.out_dir_of
workdir = sl.workdir
_rec_key = sl._rec_key
_code_stamp = sl._code_stamp
_new_run_meta = sl._new_run_meta


# ================================================================ main
def _add_shared(p: argparse.ArgumentParser, jobs: int) -> None:
    p.add_argument("--ids", default=None, help="逗号分隔显式 id（smoke 用）")
    p.add_argument(
        "--layers", default="core", help="core / core,booster / core,booster,hot"
    )
    p.add_argument("--n", type=int, default=0, help="抽样式量；0=全集")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--only", default=None, help="id 子串过滤")
    p.add_argument("--jobs", type=int, default=jobs)
    p.add_argument("--tag", default="stagerun", help="结果目 stagerun-{tag}-{date}")
    p.add_argument("--dir", default=None, help="显式结果目（覆盖 --tag/--date）")
    p.add_argument("--date", default=str(datetime.now(UTC).date()))
    p.add_argument("--rerun", action="store_true", help="无视 records 重跑")
    p.add_argument(
        "--recode",
        action="store_true",
        help="产码印章（record.code=HEAD sha±dirty）不符/缺印的格重跑——splice/parse 层修复验证用",
    )
    p.add_argument(
        "--upstream", default=None, help="上游可收 status CSV（默认各 stage 自定）"
    )
    p.add_argument("--time-budget", type=float, default=0.0, help="秒；0=不限")
    p.add_argument(
        "--no-preflight",
        action="store_true",
        help="跳过启动自检（全量 import+mock 链）",
    )


def main() -> None:
    ap = argparse.ArgumentParser(
        prog="stagerun.py", description=__doc__.splitlines()[0]
    )
    sub = ap.add_subparsers(dest="stage", required=True)

    p_ing = sub.add_parser(
        "ingest", help="manifest→copytree → work/{id}/src/（IA 拉取 stub，归数据侧）"
    )
    _add_shared(p_ing, 8)

    p_par = sub.add_parser(
        "parse", help="route+normalize+parse_file → parse.json + zh/"
    )
    _add_shared(p_par, 6)
    p_par.add_argument(
        "--engine",
        default="xelatex",
        choices=["auto", "xelatex", "tectonic"],
        help="normalize 目标引擎",
    )

    p_xl = sub.add_parser("xlat", help="XlatPipeline → zh/ 就地翻译 + 逐块明细")
    _add_shared(p_xl, 4)
    p_xl.add_argument(
        "--arm",
        required=True,
        choices=["mock", "real", "sabotage-b", "sabotage-c", "perturb"],
    )
    p_xl.add_argument("--sem", type=int, default=4, help="全局网关信号量（gwcap 硬闸）")
    p_xl.add_argument(
        "--concurrency", type=int, default=10, help="单篇 pipeline 内部 worker 数"
    )
    p_xl.add_argument("--model", default="swe-2-medium")
    p_xl.add_argument("--base-url", default="http://100.105.212.52:3003")
    p_xl.add_argument("--api-key", default="240127")
    p_xl.add_argument("--no-probe", action="store_true")

    p_cp = sub.add_parser("compile", help="splice+inject+compile+judge（zh|base）")
    _add_shared(p_cp, 4)
    p_cp.add_argument("--arm", required=True, choices=["zh", "base"])
    p_cp.add_argument(
        "--engine", default="xelatex", choices=["auto", "xelatex", "tectonic"]
    )
    p_cp.add_argument(
        "--xlat-arm", default=None, help="钉住 zh/ 期望的 xlat 臂（防陈旧树）"
    )
    p_cp.add_argument("--timeout", type=float, default=240.0)
    p_cp.add_argument(
        "--post",
        default="none",
        choices=["none", "l2"],
        help="l2 回灌（暂 stub——需 TreeRun 内存态）",
    )

    p_fx = sub.add_parser("fixloop", help="compile 非 clean 格 → fixloop+CaseSink")
    _add_shared(p_fx, 4)
    p_fx.add_argument(
        "--on",
        default="fail",
        choices=["fail", "nonclean", "misschar", "clean", "all"],
        help="目标格选择：fail(默认)/nonclean/misschar(缺字 partial 窄口)/clean(幂等探针)/all",
    )
    p_fx.add_argument("--timeout", type=float, default=240.0)
    p_fx.add_argument(
        "--xlat-arm",
        default=None,
        help="候选 compile 记录限该 upstream 臂（多臂 append 序互覆时按臂捞）",
    )
    p_fx.add_argument(
        "--llm",
        action="store_true",
        help="escalate_llm 规则接 LLM 修复钩（默认关；网关走 TEXLATE_* env/默认）",
    )

    args = ap.parse_args()
    out_dir = sl.out_dir_of(args)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "records").mkdir(exist_ok=True)
    (out_dir / "work").mkdir(exist_ok=True)
    gi = out_dir / ".gitignore"
    if not gi.exists():
        gi.write_text(
            "work/\n", encoding="utf-8"
        )  # 重产物树不进库（对齐 bench/work_*/ 惯例）
    sl.touch_run_meta(out_dir, args)

    entries = benchlib.load_manifest_rows(
        sl.CORPUS, sorted(set(args.layers.split(",")))
    )
    # cat 透传（wiring §4）：xlat real 臂的术语表注入 + term 指标重建共用
    # {canon_id: cat_group}——manifest 装载本就发生在驱动入口，stage 内不再现查。
    args.cat_map = {
        sl.canon_id(str(e["id"])): str(e.get("cat_group") or "")
        for e in entries
        if e.get("id")
    }
    # select_ids 已 canon 归一；dedup_wids 是同 wid 单任务闸（撞名对并发 =
    # 同树互 rmtree——math--0408287 复判被罩实证），五 stage 共此入口。
    ids = sl.dedup_wids(sl.select_ids(entries, args, args.stage))
    print(
        f"== {args.stage} n={len(ids)} layers={args.layers} seed={args.seed} -> {out_dir}",
        flush=True,
    )

    if not args.no_preflight:
        errs = asyncio.run(benchlib.preflight())
        if errs:
            print("preflight FAILED — 源码树不一致，拒绝跑:", flush=True)
            for e in errs:
                print(f"  {e}", flush=True)
            sys.exit(2)
        print("preflight ok", flush=True)

    log = sl.RecLog(out_dir / "records" / f"{args.stage}.jsonl")
    try:
        if args.stage == "ingest":
            stage_ingest(args, out_dir, ids, entries, log)
        elif args.stage == "parse":
            stage_parse(args, out_dir, ids, log)
        elif args.stage == "xlat":
            stage_xlat(
                args,
                out_dir,
                ids,
                log,
                sl.load_latest(out_dir / "records" / "parse.jsonl"),
            )
        elif args.stage == "compile":
            if args.post == "l2":
                print(
                    "note: --post l2 未接线（需 TreeRun 内存态；TODO 见 docstring）",
                    flush=True,
                )
            stage_compile(
                args,
                out_dir,
                ids,
                log,
                sl.load_latest(out_dir / "records" / "xlat.jsonl"),
            )
        elif args.stage == "fixloop":
            stage_fixloop(args, out_dir, ids, log)
    finally:
        log.close()
        sl.mark_run_finished(out_dir)
    print(f"done -> {out_dir}/records/{args.stage}.jsonl", flush=True)


if __name__ == "__main__":
    main()
