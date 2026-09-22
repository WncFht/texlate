r"""soak — 生产翻译链单 spec 化（Phase-4 Wave-A2 旗舰件）。

ingest → parse → xlat(paid) → compile → fixloop(paid) 单 run 内串行——
``same_id_serial`` 把同一篇的五个 cell 钉在同一 worker 按 plan 序执行，
论文间跨 ``--jobs`` 并行。取代旧「5 run/日」stagerun 管线（续跑语义经
ledger 而非共享 work/ 目录）。

逐格口径移植自 stage_{ingest,parse,xlat,compile,fixloop}.py：

- ingest：catalog 状态机 → ``ctx.src_path()`` 硬链接场——**先按
  catalog state 分类再调 src_path**（``empty`` 态的 cell 目录会经
  src_path 投影成伪 ok 树）。fetch_fn=None：湖外抓取归 corpus
  builders（Wave-E），本 spec 只消费已在湖/可自愈的格。
- parse：route → ``.zh-build`` 暂存 → normalize → scan_tex_tree →
  swap_in ``zh.-`` + ``zh.-/parse.json``（随树进 vault，跨 run 消费
  者另读 ``upstream_rec("parse").metrics``）。
- xlat：zh.- → ``.zh-xlat`` 暂存 → XlatPipeline(session 桥接网关) →
  swap_in + ``state.-/``（StateStore + xlat-detail.jsonl）+
  ``zh.-/.xlat-arm.json`` provenance marker。``AuthTrippedError`` →
  ``PaidAbortCell``（fail + auth_dead + auth_tripped，§3.6 对拍单列）。
- compile：zh.- → splice.- 重建 → inject → judge；base 归因臂折进
  ``metrics.base``（一格一 compile_base 观测——旧 2-record 口径的
  2→1 折叠白名单项）。
- fixloop：**恒自 zh.- 重建 splice.-**（rerun-only 语义——上波就地
  变异不进新轮，2211.04482 脏 splice 实证）；on 谓词不中的格回
  ``ok`` + ``metrics.fixloop_ran=False``——这是 DONE 终态让
  §3.5 harvest 把付费 zh.-/state.- 字节封进 vault 的命门（skip 是
  retriable 不触发 harvest，付费字节会整批滞留 work/）。

执行器：全 stage ``thread``——kernel 按 executor 分组**串行**跑
（``for ex, group in by_exec.items()``），混 executor 会把链拆成两波
让下游集体 needs-skip；``process`` 被 run() 明拒（env/meter 不可
pickle）。xlat 的 async 编排由 fn 内 ``asyncio.run`` 自持。
"""
from __future__ import annotations

import asyncio
import contextlib
import functools
import json
import os
import random
import shutil
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# src/ 不在 `bench` 入口的 sys.path 上（kernel 惰性 import texlate.*）——
# specs/_sabotage.py 同款自举；TEXLATE_SRC 冻结快照语义一致。
sys.path.insert(
    0,
    os.environ.get(
        "TEXLATE_SRC", str(Path(__file__).resolve().parents[3] / "src")
    ),
)

import benchlib
import quality_proxies as qp
from kernel import events, idnorm, lake, paths, vault
from kernel import paid as paidmod
from kernel.spec import EVAL_LAYERS, Param, Spec, Stage

from specs import _fixloop as flb  # 冷 usertree 引擎配方单源
from specs._shared import (
    DEFAULT_BASE_URL,
    DEFAULT_MODEL,
    PaidEscape,
    SessionClient,
    SessionTranslator,
    TimedTranslator,
    devin_factory,
)
from specs._xlat_async import translate_tree_async
from texlate.compile.engine import XelatexEngine, engine_for, route_project
from texlate.compile.fixloop import CaseSink, Ruleset, fixloop
from texlate.compile.fixloop.llm_hook import make_llm_hook
from texlate.compile.inject import (
    InjectRejectError,
    classify_no_main,
    find_main_tex,
    prepare_chinese,
)
from texlate.compile.normalize import normalize_project
from texlate.latex.api import scan_tex_tree
from texlate.pipecore import delivered
from texlate.pipecore import scan_tree as _scan_tree
from texlate.repair import ResProxy
from texlate.validate.l0 import validate_pair
from texlate.xlat.glossary import LOCAL_GLOSSARY_NAME, Glossary
from texlate.xlat.pipeline import (
    AuthTrippedError,
    GatewayTranslator,
    PipelineConfig,
)
from texlate.xlat.placeholders import collect_doc_placeholders
from texlate.xlat.prompts import PROMPT_VERSION

ROOT = Path(__file__).resolve().parents[3]
CORPUS = Path(os.environ.get("TEXLATE_CORPUS", str(ROOT / "bench/corpus")))

#: lake catalog 中「自带或可免费自愈字节」的态——hydrated/pinned 直读，
#: raw_only 经 hydrate() 本地重解包零网络回 hydrated。
_HYDRATABLE = frozenset({"hydrated", "pinned", "raw_only"})

#: fmt 死路词表（本路径永不可解——reject 的 manifest_dead_end 系）。
_BAD_FMTS = frozenset({"stub", "pdf", "error"})

_ON_PRED: dict[str, object] = {
    "fail": lambda c: c.get("status") == "fail",
    "nonclean": lambda c: c.get("status") in {"fail", "partial"},
    "misschar": lambda c: benchlib.misschar_partial(
        c.get("status"), (c.get("metrics") or {}).get("verdict") or {}
    ),
    "clean": lambda c: c.get("status") == "clean",
    # reject/skip 无有效 splice 树——post-judge 编译被拒英文树会虚增
    # union-pdf（1e 审计 +414 phantom 上限）；error(harness 崩) 树态不定同排。
    "all": lambda c: c.get("status") not in {"reject", "skip", "error"},
}


# ---------------------------------------------------------------- 小件共用


def _swap_in(stage_dir: Path, dst: Path) -> None:
    """暂存树 → dst 的 rename 接力（stagerun_lib.swap_in 同式，就地一份
    不引删除单文件）。"""
    old = stage_dir.with_name(f"{stage_dir.name}-old")
    if dst.exists():
        if old.exists():
            shutil.rmtree(old)
        os.rename(dst, old)
    os.rename(stage_dir, dst)
    if old.exists():
        shutil.rmtree(old)


def _rebuild(zh: Path, splice: Path) -> None:
    """zh.- → splice.- 原样重建（stagerun_lib.rebuild_splice 同式）。"""
    if splice.exists():
        shutil.rmtree(splice)
    shutil.copytree(zh, splice, ignore=benchlib.copytree_ignore())


def _ensure_kind(ctx, kind: str) -> Path | None:
    """本 run 的 mutates-kind 读径：同 run 上游产物优先，缺席则 vault
    restore(mode="copy") 物化全部已封 kind（0444 融合树的 可写副本
    口径——消费方可能要改）。无完好 vault 副本 → None。"""
    d = ctx.upstream_asset_dir(kind)
    if d is not None:
        return d
    with contextlib.suppress(vault.VaultError):
        vault.restore(ctx.idc, ctx.arm, ctx.variant, ctx.paper_dir(),
                      mode="copy")
    return ctx.upstream_asset_dir(kind)


def _xlat_marker(zh: Path) -> dict | None:
    """``zh.-/.xlat-arm.json`` → dict；zh/ marker 缺席 → None。"""
    p = zh / ".xlat-arm.json"
    if not zh.is_dir() or not p.exists():
        return None
    try:
        doc = json.loads(p.read_text())
    except (json.JSONDecodeError, OSError):
        return None
    return doc if isinstance(doc, dict) else None


_DONE_STS = tuple(sorted(events.STATUS_DONE))

#: IN 位串只插占位符个数（模块级常量）——值仍全参数化。
_LAST_DONE_SQL = (
    "SELECT run,seq,id,idc,arm,up,variant,stage,status,cat,sig,code,"  # noqa: S608
    "fp,dur_s,metrics,errors,ts FROM records "
    "WHERE idc=? AND arm=? AND up=? AND variant=? AND stage=? "
    f"AND status IN ({','.join('?' * len(_DONE_STS))}) "
    "ORDER BY rowid DESC LIMIT 1"
)


def _last_done(ctx, stage: str) -> dict | None:
    """末条 DONE 账·跨全 run——``_needs_eval`` 的 dedup-look-through 同域。

    ``ctx.upstream_rec`` 是 run∪foreign_runs 域：run2 里 run1 的 compile
    DONE 行出域（本 run 那行是 dedup 非 DONE）——on 谓词/expect_cjk/
    engine_resolved 这些「上游账」判读必须读全域，否则跨 run 续跑全部
    看成 None 走歪（fixloop 永不修/expect_cjk 恒 True）。
    """
    idx = ctx.index
    if idx is None:
        return None
    row = idx.conn.execute(
        _LAST_DONE_SQL,
        (ctx.idc, ctx.arm, ctx.up, ctx.variant, stage, *_DONE_STS),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    for col in ("metrics", "errors"):
        v = d.get(col)
        if isinstance(v, str):
            with contextlib.suppress(ValueError):
                d[col] = json.loads(v)
        d[col] = ctx._unblob(d[col])
    return d


def _main_rel(ctx, tree: Path) -> str | None:
    """main_rel 三段式：parse 账 metrics → zh.-/parse.json → find_main_tex。"""
    rec = _last_done(ctx, "parse")
    m = ((rec or {}).get("metrics") or {}).get("main_rel")
    if m:
        return str(m)
    zh = ctx.upstream_asset_dir("zh")
    pj = (zh / "parse.json") if zh is not None else None
    if pj is not None and pj.is_file():
        try:
            doc = json.loads(pj.read_text())
            if doc.get("main_rel"):
                return str(doc["main_rel"])
        except (json.JSONDecodeError, OSError):
            pass
    found = find_main_tex(tree)
    return found.relative_to(tree).as_posix() if found else None


def _engine(ctx, root: Path) -> str:
    """engine 三段式：params ≠ auto → parse 账 engine_resolved → route 兜底。"""
    eng = str(ctx.params.get("engine") or "xelatex")
    if eng != "auto":
        return eng
    rec = _last_done(ctx, "parse")
    m = ((rec or {}).get("metrics") or {}).get("engine_resolved")
    if m:
        return str(m)
    try:
        return route_project(root, prefer="xelatex").engines[0]
    except Exception:
        return "xelatex"


def _gate(status: str, code: str, cat: str, payload,
          metrics: dict | None = None) -> dict:
    """stagerun gate_rec 的 return-dict 版：status + 单条 errors +
    可选 metrics；sig 由内核 errors[0] cat:pay 自动合成。"""
    out = {
        "status": status,
        "code": code,
        "errors": [{"code": code, "cat": cat, "payload": payload}],
    }
    if metrics:
        out["metrics"] = metrics
    return out


# ---------------------------------------------------------------- items/select


def _corpus_rows() -> list[dict]:
    """manifest*.jsonl 全行（eval 层剔除 + 同 id 首见胜）。

    行字段随 cell 全量携带：id/layer/cat_group/format/channel/item/
    member + fp_input=blob_sha256|main_tex_sha256。
    """
    rows: list[dict] = []
    seen: set[str] = set()
    for mp in sorted(CORPUS.glob("manifest*.jsonl")):
        for row in benchlib.iter_jsonl(mp):
            if not isinstance(row, dict):
                continue
            pid = row.get("id")
            if not pid or pid in seen:
                continue
            if row.get("layer") in EVAL_LAYERS:
                continue  # holdout 层只进 eval spec（spec.eval 门）
            seen.add(pid)
            rows.append(
                {
                    "id": str(pid),
                    "layer": row.get("layer"),
                    "cat_group": row.get("cat_group"),
                    "format": row.get("format"),
                    "channel": row.get("channel"),
                    "item": row.get("item"),
                    "member": row.get("member"),
                    "fp_input": row.get("blob_sha256")
                    or row.get("main_tex_sha256"),
                }
            )
    return rows


_ITEMS: list[dict] | None = None


def _items() -> list[dict]:
    """materialize-once item 源——compile_checks 物化进 spec.items。"""
    global _ITEMS  # noqa: PLW0603
    if _ITEMS is None:
        _ITEMS = _corpus_rows()
    return _ITEMS


@functools.cache
def _canon(raw: str):
    return idnorm.canon_id(str(raw))


_CAT_MEMO: dict = {"sig": None, "cat": None}


def _catalog() -> lake.LakeCatalog:
    """mtime+size 签名缓存的 catalog 投影——在飞 hydrate 写行即失效重载。"""
    p = paths.lake_catalog_path()
    try:
        st = p.stat()
        sig = (st.st_mtime_ns, st.st_size)
    except OSError:
        sig = None
    if sig != _CAT_MEMO["sig"] or _CAT_MEMO["cat"] is None:
        _CAT_MEMO["cat"] = lake.LakeCatalog.load()
        _CAT_MEMO["sig"] = sig
    return _CAT_MEMO["cat"]


def _sampleable(item: dict) -> bool:
    """--n 抽样池谓词：catalog 标可水化态，或未登记但盘上完整（seed 湖）。"""
    res = _canon(item["id"])
    if not res.ok or not res.idc:
        return False
    st = _catalog().state(res.idc)
    if st in _HYDRATABLE:
        return True
    if st in ("failed", "empty"):
        return False
    return lake.is_complete(res.idc)


def _sample_ids(layers: set[str], needle: str, n: int, seed: int) -> set[str]:
    """分层不区分地 seeded 抽 n 个 canon id（benchlib.pick_sample 的湖版）。"""
    pool = []
    for it in _items():
        if layers and str(it.get("layer") or "") not in layers:
            continue
        res = _canon(it["id"])
        idc = res.idc if res.ok and res.idc else str(it["id"])
        if needle and needle not in idc:
            continue
        if not _sampleable(it):
            continue
        if res.ok and res.idc:
            pool.append(res.idc)
    pool = sorted(set(pool))
    rng = random.Random(seed)
    return set(rng.sample(pool, min(n, len(pool))))


def _select(item: dict, rp: dict) -> bool:
    """G1 plan-filter：--ids 直选（canon 双拼写归一，bypass layers）→
    --layers（缺省 core）→ --only canon 子串 → --n/--seed 湖内抽样。"""
    ids_p = str(rp.get("ids") or "").strip()
    raw = str(item.get("id") or "")
    res = _canon(raw)
    idc = res.idc if res.ok and res.idc else raw
    if ids_p:
        want: set[str] = set()
        for tok0 in ids_p.split(","):
            tok = tok0.strip()
            if not tok:
                continue
            want.add(tok)
            r = _canon(tok)
            if r.ok and r.idc:
                want.add(r.idc)
        return raw in want or idc in want
    layers = {
        s.strip() for s in str(rp.get("layers") or "core").split(",") if s.strip()
    }
    if layers and str(item.get("layer") or "") not in layers:
        return False
    only = str(rp.get("only") or "").strip()
    needle = ""
    if only:
        r = _canon(only)
        needle = r.idc if r.ok and r.idc else only
        if needle not in idc:
            return False
    n = int(rp.get("n") or 0)
    if n > 0:
        seed = int(rp.get("seed") or 0)
        return idc in _sample_ids(layers, needle, n, seed)
    return True


# ---------------------------------------------------------------- stage: ingest


def _ingest(ctx) -> dict:
    """catalog 状态机分类 → src_path 物化；四键 metrics 同旧口径。

    cat=code 旧约——sig 要能分流 stub_format/eprint_fetch_unwired 等
    （旧世界 errors[0].cat 就是 code 字符串本身）。cat=ingest 只留给
    no_extracted torn 格。
    """
    cell = ctx.cell
    fmt = cell.get("format")
    ch = cell.get("channel")
    item = cell.get("item")
    member = cell.get("member")
    metrics = {"n_files": 0, "main_tex_guess": None,
               "source": "ia" if item else None, "sha256_ok": None}

    st = _catalog().state(ctx.idc)
    complete = lake.is_complete(ctx.idc)
    if not complete:
        # fmt 死路只在缺字节时判（旧式：extracted 在场者不看 manifest
        # format 标签）；catalog state 再真也救不回 stub/pdf/error 伪条目。
        if fmt in _BAD_FMTS:
            c = f"{fmt}_format"
            return _gate("reject", c, c, member, metrics)
        if st == "failed":
            # manifest_dead_end 系：catalog 判死的格 reject。
            return _gate("reject", "catalog_failed", "catalog_failed",
                         member, metrics)
        if st == "empty":
            # 空载荷格——src_path() 会把它投影成伪 ok 空树，先截。
            return _gate("reject", "empty_payload", "empty_payload",
                         member, metrics)

    src = ctx.src_path()
    if src is not None:
        main = find_main_tex(src)
        metrics.update(
            {
                "n_files": sum(1 for p in src.rglob("*") if p.is_file()),
                "main_tex_guess": (
                    main.relative_to(src).as_posix() if main else None
                ),
                "source": "lake",
            }
        )
        return {"status": "ok", "metrics": metrics}
    # src_path None 且 catalog 声称有货 = torn 湖格（raw/extracted 双缺，
    # fetch_fn 未接）——error；未登记/不可水化态走 skip 分类树。
    if complete or st in _HYDRATABLE:
        return _gate("error", "no_extracted", "ingest", ctx.idc, metrics)
    if not item:
        c = "eprint_fetch_unwired" if ch == "arxiv_eprint" else "no_item"
        return _gate("skip", c, c, member, metrics)
    return _gate("skip", "ia_fetch_unwired", "ia_fetch_unwired",
                 f"item={item}", metrics)


# ---------------------------------------------------------------- stage: parse


def _parse(ctx) -> dict:
    """route(src) → .zh-build 暂存 → find_main → normalize → scan →
    zh.-/ + zh.-/parse.json（_parse_job 的 ctx 版平移）。

    parse.json 双落点：``paper_dir/parse.json``（旧 ``wid/parse.json``
    同位，本 run 诊断面）+ ``zh.-/parse.json``（随树封 vault——跨 run
    的 main_rel/engine_resolved 消费面；route_reject 不出 zh.- 树，
    与旧式 zh/ 缺席同义）。
    """
    src = ctx.src_path()
    if src is None:
        return _gate("skip", "no_src", "upstream",
                     "lake cell materialization failed")
    paper = ctx.paper_dir()
    pj_root = paper / "parse.json"
    stage = paper / ".zh-build"

    def _write_doc(doc: dict) -> None:
        text = json.dumps(doc, ensure_ascii=False, indent=1)
        pj_root.write_text(text, encoding="utf-8")
        zh = ctx.upstream_asset_dir("zh")
        if zh is not None:
            (zh / "parse.json").write_text(text, encoding="utf-8")

    metrics: dict = {}
    route = route_project(src)
    metrics["route"] = {
        "engines": route.engines,
        "reject": route.reject,
        "reasons": route.reasons,
        "non_utf8": route.non_utf8,
        "latex209_suspect": route.latex209_suspect,
    }
    doc: dict = {"id": ctx.idc, "route": metrics["route"]}
    if route.reject:
        doc["status"] = "reject"
        if stage.exists():
            shutil.rmtree(stage)
        _write_doc(doc)
        return _gate("reject", "route_reject", "route", route.reject,
                     metrics)

    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(src, stage, ignore=benchlib.copytree_ignore())

    main = find_main_tex(stage)
    if main is None:
        sub = classify_no_main(stage)
        doc["status"] = "reject"
        doc["no_main_sub"] = sub
        zh = ctx.asset_dir("zh")
        _swap_in(stage, zh)  # zh.- 在场=未归一化原料树（旧式同形）
        _write_doc(doc)
        metrics["no_main_sub"] = sub
        return _gate("reject", "no_main_tex", "parse", sub or "", metrics)
    main_rel = main.relative_to(stage).as_posix()
    eng = str(ctx.params.get("engine") or "xelatex")
    if eng == "auto":
        eng = route.engines[0] if route.engines else "xelatex"
    norm = normalize_project(stage, eng, main_rel)
    doc.update(
        {"main_rel": main_rel, "engine_resolved": eng, "normalize": norm}
    )
    metrics.update(
        {"main_rel": main_rel, "engine_resolved": eng, "normalize": norm}
    )

    scan = scan_tex_tree(stage)
    files: list[dict] = []
    warn_kinds: dict[str, int] = {}
    unresolved: list[str] = []
    n_chunks = 0
    parse_fail = [f"{rel}: {exc!r:.160}" for rel, exc in scan.fault]
    support = sorted(scan.support)
    for _abs, rel, res in scan.parsed:
        ws = [
            {"kind": w.kind, "pos": w.pos, "detail": w.detail}
            for w in res.warnings
        ]
        for w in res.warnings:
            warn_kinds[w.kind] = warn_kinds.get(w.kind, 0) + 1
        ins = [name for _pos, name in res.inputs]
        unresolved.extend(f"{rel}:{n}" for n in ins)
        n_chunks += len(res.chunks)
        files.append(
            {
                "rel": rel,
                "n_chunks": len(res.chunks),
                "chunk_kinds": sorted({c.context for c in res.chunks}),
                "warnings": ws,
                "inputs": ins,
            }
        )
    doc.update(
        {
            "status": "ok",
            "files": files,
            "parse_fail": parse_fail,
            "support_files": support,
            "totals": {
                "tex_files": len(files),
                "support_files": len(support),
                "chunks": n_chunks,
                "warn_kinds": dict(sorted(warn_kinds.items())),
                "unresolved": unresolved,
            },
        }
    )
    zh = ctx.asset_dir("zh")
    _swap_in(stage, zh)
    _write_doc(doc)
    metrics.update(
        {
            "tex_files": len(files),
            "support_files": len(support),
            "chunks": n_chunks,
            "warn_kinds": doc["totals"]["warn_kinds"],
            "n_unresolved": len(unresolved),
            "parse_fail": parse_fail,
        }
    )
    out = {"status": "ok", "metrics": metrics}
    if parse_fail:
        out["errors"] = [
            {"code": "parse_file", "cat": "parse", "payload": p}
            for p in parse_fail[:10]
        ]
    return out


# ---------------------------------------------------------------- stage: xlat
#
# SessionClient/TimedTranslator/SessionTranslator/PaidEscape 单源在
# specs/_shared.py——Wave-C e2e_real/qualbench 复用同一桥。


def _xlat(ctx) -> dict:
    """zh.- → .zh-xlat 暂存翻译 → swap_in + state.- 明细 + marker。

    全程「真网关」语义（soak 即 real 臂）：术语表注入 + term/leak 指标
    恒开；oversize_cap 恒生效（配额闸）。
    """
    zh = _ensure_kind(ctx, "zh")
    if zh is None or not (zh / "parse.json").exists():
        return _gate("skip", "no_parse_tree", "upstream",
                     "zh.-/ or zh.-/parse.json missing")
    cat_group = ctx.cell.get("cat_group") or ""
    src = ctx.src_path()  # local 术语层锚（glossary.local.yaml 在论文树）
    session = ctx.gateway()
    if not ctx.params.get("no_probe"):
        session.probe_model()  # GatewayChat 无 probe_model → 门检后即 True

    client = SessionClient(session)
    translator = TimedTranslator(
        GatewayTranslator(client, str(ctx.params["model"]))
    )
    cfg = PipelineConfig(concurrency=int(ctx.params["concurrency"]))
    seg = ctx.seg_cache(
        prompt_version=PROMPT_VERSION,
        base_url=DEFAULT_BASE_URL,
        model=str(ctx.params["model"]),
        lang="zh",
        glossary=cat_group,
    )

    def _glossary_fn(chunks: list) -> Glossary:
        return Glossary.load(
            user_path=qp._NO_USER_GLOSSARY,
            local_path=(src / LOCAL_GLOSSARY_NAME) if src else None,
            categories=[cat_group],
            placeholders=collect_doc_placeholders(
                c.content for c in chunks
            ),
        )

    def _post_run(pipe) -> None:
        if pipe.state is None:
            return
        # term_dict 落盘（state.-/term_dict.json）——观测件不毁账。
        with contextlib.suppress(Exception):
            pipe.state.save_maps(term_dict=pipe._doc_glossary)

    state_dir = ctx.asset_dir("state")
    staging = ctx.paper_dir() / ".zh-xlat"
    if staging.exists():
        shutil.rmtree(staging)
    shutil.copytree(zh, staging, ignore=benchlib.copytree_ignore())

    try:
        stats, results = asyncio.run(
            translate_tree_async(
                staging,
                translator,
                state_dir,
                cfg,
                oversize_cap=int(ctx.params["oversize_cap"]),
                glossary_fn=_glossary_fn,
                scan_fn=_scan_tree,
                validator=lambda s, z: validate_pair(s, z).feedback(),
                post_run=_post_run,
                cache=seg,
            )
        )
    except PaidEscape as e:
        # 拆舱：mid-flight 付费族异常（PAUSE 中启/abort/budget/越闸
        # PaidAbortCell）原样交内核映射——绝不落成终态 fail 假账。
        raise e.orig from e
    except AuthTrippedError as e:
        # 篇内连续 auth-fail 熔断 = 凭证死透——PaidAbortCell 映
        # fail+auth_dead+auth_tripped（旧 error→fail 改判对拍单列）。
        msg = f"{ctx.idc}: auth circuit tripped ({e})"
        raise paidmod.PaidAbortCell(msg) from e

    # req_timing 三分拆（口径注记：chat_s = session.request 全程含
    # paid_slot 排队——旧「纯 HTTP 时延」义不存在于 session 桥；
    # backoff_s = GatewayTranslator span − 线时；sem_wait_s 恒 0，
    # 全局闸角色由 paid_slot 顶掉且其等待计入 chat_s）。
    stats["req_timing"] = {
        "calls": translator.calls,
        "chat_calls": client.chat_calls,
        "chat_s": round(client.chat_s, 1),
        "backoff_s": round(max(0.0, translator.span_s - client.chat_s), 1),
        "sem_wait_s": 0.0,
        "span_s": round(translator.span_s, 1),
    }

    metrics = {"translate": stats}
    if stats.get("oversize"):
        shutil.rmtree(staging, ignore_errors=True)
        return _gate(
            "reject", "oversize", "xlat",
            f"src_chars={stats['src_chars']}", metrics,
        )

    # 逐块明细（triage/契约审计原料）——随 state.- 进 vault。
    detail = state_dir / "xlat-detail.jsonl"
    with detail.open("w", encoding="utf-8") as fh:
        for r in results:
            benchlib.write_jsonl(
                fh,
                {
                    "chunk_id": r.chunk_id,
                    "status": r.status,
                    "attempts": r.attempts,
                    "batched": r.batched,
                    "skipped": r.fell_back,
                    "error_kind": r.error_kind,
                    "skip_reason": r.skip_reason,
                    "warnings": r.warnings,
                },
            )
    (staging / ".xlat-arm.json").write_text(
        json.dumps(
            {
                "arm": ctx.arm,
                "model": str(ctx.params["model"]),
                "ts": datetime.now(UTC).isoformat(),
            },
            ensure_ascii=False,
        )
    )
    _swap_in(staging, zh)

    stats.update(qp.scan_leak([(r.chunk_id, r.source or "")
                               for r in results]))
    delivered_rows = [
        (r.chunk_id, r.source or "", r.translation or "")
        for r in results
        if delivered(r)
    ]
    try:
        td = qp.rebuild_term_dict(
            cat_group or None,
            [s for _c, s, _t in delivered_rows],
            (src / LOCAL_GLOSSARY_NAME) if src else None,
        )
        stats.update(qp.score_terms(delivered_rows, td))
    except Exception as e:  # 观测件不毁账——重建失败记 note 不落 error 格
        stats.update(
            {
                "term_applicable": None,
                "term_hit": None,
                "term_hit_rate": None,
                "term_misses": [],
                "term_dict_size": None,
                "term_note": f"rebuild_failed:{type(e).__name__}",
            }
        )

    n_bad = stats["fault"] + stats["skipped"]
    if stats["leftover_ph"] > 0:
        return _gate("fail", "leftover_ph", "xlat",
                     str(stats["leftover_ph"]), metrics)
    if stats["chunks"] and n_bad == stats["chunks"]:
        return _gate("fail", "all_chunks_bad", "xlat",
                     str(stats["chunks"]), metrics)
    if n_bad or stats["fault_files"]:
        return _gate(
            "partial", "chunks_bad", "xlat",
            f"fault={stats['fault']} skipped={stats['skipped']}", metrics,
        )
    return {"status": "ok", "metrics": metrics}


# ---------------------------------------------------------------- stage: compile


def _compile_judge(
    work: Path, main_rel: str, eng_name: str, timeout: float, *,
    expect_cjk: bool,
) -> dict:
    """best-effort 编译 + judge → {compile, verdict, status}。"""
    kw = {"halt_on_error": False} if eng_name == "xelatex" else {}
    res = engine_for(eng_name, **kw).compile(
        work, main_rel, timeout=timeout, sandbox=True
    )
    return benchlib.judge_dict(res, expect_cjk=expect_cjk)


def _compile(ctx) -> dict:
    """splice.- 重建 + inject + judge；base 臂折进 metrics.base。

    base 先跑（src 直编归因臂）——zh 臂半途门控时本格仍带齐 base
    观测（旧两臂独立任务等价的覆盖面守恒）。
    """
    metrics: dict = {}
    timeout = float(ctx.params["timeout"])

    # ---- base 归因臂（src 原样直编，不 normalize 不 inject） -------------
    src = ctx.src_path()
    if src is not None:
        bmain = find_main_tex(src)
        if bmain is None:
            metrics["base"] = {
                "status": "reject",
                "code": "no_main_tex",
                "cat": "compile",
                "payload": classify_no_main(src) or "",
            }
        else:
            b_rel = bmain.relative_to(src).as_posix()
            bdir = ctx.paper_dir() / "build-base"
            if bdir.exists():
                shutil.rmtree(bdir)
            shutil.copytree(src, bdir, ignore=benchlib.copytree_ignore())
            b_eng = _engine(ctx, src)
            b_tail = _compile_judge(
                bdir, b_rel, b_eng, timeout, expect_cjk=False
            )
            metrics["base"] = {
                "engine": b_eng,
                "main_rel": b_rel,
                **b_tail,
            }

    # ---- zh 臂 ------------------------------------------------------------
    zh = _ensure_kind(ctx, "zh")
    marker_doc = _xlat_marker(zh) if zh is not None else None
    if marker_doc is None:
        return _gate("skip", "not_translated", "upstream",
                     "zh.- missing or no .xlat-arm.json", metrics)
    metrics["xlat_ts"] = marker_doc.get("ts")
    splice = ctx.asset_dir("splice")
    _rebuild(zh, splice)
    main_rel = _main_rel(ctx, splice)
    if not main_rel:
        return _gate("reject", "no_main_tex", "compile",
                     classify_no_main(splice) or "", metrics)
    eng = _engine(ctx, splice)
    metrics["engine"] = eng
    metrics["main_rel"] = main_rel
    try:
        metrics["inject"] = prepare_chinese(splice, main_rel)
    except InjectRejectError as e:
        metrics["verdict"] = {"status": "reject", "reasons": [e.reason]}
        return _gate("reject", "inject_reject", "inject", e.reason, metrics)
    # 0-chunk 主文档（includepdf 壳）无译文产出 → 不期待 CJK；
    # xlat 账缺席时保守默认 True。记入 metrics 供 fixloop 复判同口径。
    # 跨 run 域：xlat 本 run dedup 时 DONE 底账在前 run。
    xr = _last_done(ctx, "xlat")
    _tr = ((xr or {}).get("metrics") or {}).get("translate") or {}
    expect_cjk = _tr.get("chunks") != 0
    metrics["expect_cjk"] = expect_cjk
    tail = _compile_judge(splice, main_rel, eng, timeout,
                          expect_cjk=expect_cjk)
    metrics.update(tail)
    v = tail["verdict"]
    if v["status"] in ("clean", "partial"):
        pdf = splice / Path(main_rel).with_suffix(".pdf")
        if not pdf.is_file():
            pdfs = [p for p in splice.glob("*.pdf") if p.is_file()]
            pdf = max(pdfs, key=lambda p: p.stat().st_mtime) if pdfs else None
        if pdf is not None:
            with contextlib.suppress(Exception):
                metrics["landmark"] = qp.landmark_metrics(pdf, splice)
    out = {"status": v["status"], "metrics": metrics,
           "sig": benchlib.verdict_sig(v, tail["compile"].get("first_error"))}
    if v["status"] not in ("clean", "partial"):
        out["errors"] = [
            {
                "code": v.get("category") or "compile_fail",
                "cat": v.get("category"),
                "payload": v.get("payload"),
            }
        ]
    elif v.get("category"):
        out["errors"] = [
            {
                "code": v["category"],
                "cat": v["category"],
                "payload": v.get("payload"),
            }
        ]
    return out


# ---------------------------------------------------------------- stage: fixloop


class _CaseBridge(CaseSink):
    """CaseSink → ctx.emit_case 桥：record 行形状逐字保留进 cases 账道；
    文件落点 /dev/null（ledger+cases.jsonl 已由内核原子写，双重落盘
    只会留两份漂移面）。"""

    def __init__(self, ctx) -> None:
        super().__init__(os.devnull)
        self._ctx = ctx

    def record(self, cell, **kw):
        rec = super().record(cell, **kw)
        self._ctx.emit_case(rec)
        return rec


def _fixloop(ctx) -> dict:
    """compile 非 clean 格修复：恒自 zh.- 重建 splice.-（rerun-only），
    冷 usertree + Ruleset + ResProxy + post 复判同 compile 刻度。"""
    t0 = time.monotonic()
    # on 谓词读域 = _needs_eval 同域（跨全 run 末条 DONE）——本 run
    # upstream_rec 在 compile dedup 的续跑 run 里返 None，会误判成
    # 「无修必要」白放行。
    comp_rec = _last_done(ctx, "compile") or {}
    want = _ON_PRED[str(ctx.params.get("on") or "fail")]
    if not want(comp_rec):
        # on 谓词不中 = 「本轮无修必要」——ok + ran=False 终态触发
        # §3.5 harvest，把上游付费字节封进 vault；skip 是 retriable
        # 会让 zh.-/state.- 滞留 work/ 等 sweep/adopt 捞。
        return {
            "status": "ok",
            "metrics": {
                "mode": ctx.params.get("on"),
                "fixloop_ran": False,
                "on_gate": comp_rec.get("status"),
                "compile_fp": benchlib.compile_fp(comp_rec)
                if comp_rec else None,
            },
        }

    zh = _ensure_kind(ctx, "zh")
    marker_doc = _xlat_marker(zh) if zh is not None else None
    if marker_doc is None:
        return _gate("skip", "not_translated", "upstream",
                     "zh.- missing or no .xlat-arm.json")
    splice = ctx.asset_dir("splice")
    _rebuild(zh, splice)
    main_rel = _main_rel(ctx, splice)
    if not main_rel:
        return _gate("error", "no_main_tex", "fixloop",
                     classify_no_main(splice) or "")
    metrics: dict = {"splice_rebuilt": True}
    try:
        metrics["inject"] = prepare_chinese(splice, main_rel)
    except InjectRejectError as e:
        metrics["verdict"] = {"status": "reject", "reasons": [e.reason]}
        return _gate("reject", "inject_reject", "inject", e.reason, metrics)

    texmf = ctx.paper_dir() / "_texmf"
    if texmf.exists():
        shutil.rmtree(texmf)  # 冷启动——防半成品 usertree 偏暖
    eng = flb._make_engine("xelatex", texmf, splice)
    # baseline_dir 逐格注入：params 在共享 flb.RS 上无法按 pid 注入，
    # 故每格 Ruleset.load() 后按 transform 名注入 src/ 原件树。
    src = ctx.src_path()
    rs = flb.RS
    if src is not None and src.is_dir():
        rs = Ruleset.load()
        for rule in rs.rules:
            act = rule.raw.get("action") or {}
            if act.get("kind") == "builtin_transform" and act.get(
                "function"
            ) in {"restore_support_from_src", "slot_arg_revert"}:
                act.setdefault("params", {})["baseline_dir"] = str(src)
    timeout = float(ctx.params["timeout"])
    llm_hook = None
    if ctx.params.get("llm"):
        llm_hook = make_llm_hook(
            translator=SessionTranslator(
                ctx.gateway(), str(ctx.params["model"])
            )
        )
    try:
        proxy = ResProxy(eng)
        cell = fixloop(
            splice,
            proxy,
            ruleset=rs,
            engine_name="xelatex",
            main_rel=main_rel,
            corpus_id=ctx.idc,
            cond="fixloop",
            runner=flb._texmf_runner(texmf),
            case_sink=_CaseBridge(ctx),
            llm_hook=llm_hook,
            compile_timeout=timeout,
        )
        fix_last = proxy.last
    except PaidEscape as e:
        raise e.orig from e  # 拆舱交内核——harness_crash 兜底绝不收付费族
    except Exception as e:
        cell = {
            "project": ctx.idc,
            "engine": "xelatex",
            "verdict": f"harness_crash:{type(e).__name__}",
            "log_excerpt": str(e)[:500],
            "rounds": [],
            "actions": [],
        }
        fix_last = None
    cell_wall = round(time.monotonic() - t0, 1)
    # post 复判吃 fixloop 末轮 CompRes——与产品侧 res = fix_last or
    # first 同口径；兜底 fresh-compile 仅早退/崩溃/主档错位形。
    if fix_last is not None and cell.get("main") == main_rel:
        res = fix_last
        post_src = "fixloop_last"
    else:
        jeng = XelatexEngine(
            halt_on_error=False, texmfhome=texmf, repository=flb.TUNA_TLNET
        )
        res = jeng.compile(splice, main_rel, timeout=timeout, sandbox=False)
        post_src = "fresh_compile"
    expect_cjk = (comp_rec.get("metrics") or {}).get("expect_cjk", True)
    tail = benchlib.judge_dict(res, expect_cjk=expect_cjk)

    rounds = cell.get("rounds") or []
    fv = str(cell.get("verdict") or "?")
    fcat, fpay = benchlib.fixloop_attr(rounds, fv, cell.get("final_cat"))
    v = tail["verdict"]
    csb = comp_rec.get("status")
    tail["regressed"] = benchlib.STATUS_RANK.get(
        str(v["status"] or ""), -1
    ) < benchlib.STATUS_RANK.get(str(csb or ""), -1)
    actions = cell.get("actions") or []
    metrics.update(
        {
            "mode": ctx.params.get("on"),
            "fixloop_ran": True,
            "compile_status_before": csb,
            "compile_fp": benchlib.compile_fp(comp_rec)
            if comp_rec else None,
            "fixloop_verdict": fv,
            "final_cat": fcat,
            "rounds": len(rounds),
            "n_actions": len(actions),
            "rules_fired": list(
                dict.fromkeys(
                    str(a["rule"]) for a in actions if a.get("rule")
                )
            ),
            "gate_fired": list(cell.get("gate_fired") or []),
            "installed": cell.get("installed") or [],
            "floor_restored": bool(cell.get("floor_restored")),
            "fixloop_wall_s": cell_wall,
            "post_src": post_src,
            "post": tail,
        }
    )
    out = {"status": v["status"], "metrics": metrics,
           "sig": benchlib.fixloop_sig(fv, fcat, fpay)}
    if v["status"] != "clean":
        out["errors"] = [{"code": fv, "cat": fcat, "payload": fpay}]
    return out


# ---------------------------------------------------------------- spec


spec = Spec(
    kind="soak",
    params={
        "n": Param(int, default=0),
        "seed": Param(int, default=42),
        "ids": Param(str, default="", fp=False),
        "layers": Param(str, default="core", fp=False),
        "only": Param(str, default="", fp=False),
        "on": Param(
            str, default="fail",
            choices=["fail", "nonclean", "misschar", "clean", "all"],
            fp=False,
        ),
        "engine": Param(
            str, default="xelatex",
            choices=["auto", "xelatex", "tectonic"], fp=True,
        ),
        "concurrency": Param(int, default=10, fp=True),
        "timeout": Param(float, default=240.0, fp=True),
        "oversize_cap": Param(int, default=benchlib.MAX_TOTAL_CHARS,
                              fp=True),
        "model": Param(str, default=DEFAULT_MODEL, fp=True),
        "llm": Param(bool, default=False, fp=True),
        "no_probe": Param(bool, default=False, fp=False),
    },
    items=_items,
    select=_select,
    freeze_plan=True,
    executor="thread",
    env_probes=["xelatex", "tlmgr", "tectonic"],
    code_deps=[
        "src/texlate/compile",
        "src/texlate/latex",
        "src/texlate/textutil",
        "src/texlate/xlat",
        "src/texlate/pipecore.py",
        "src/texlate/validate",
    ],
    lake=True,
    prefetch=True,
    fetch_fn=None,
    lake_source="arxiv",
    same_id_serial=True,
    dedup_key=("idc", "arm", "variant"),
    gateway_factory=devin_factory(),
    stages=[
        Stage(
            "ingest",
            _ingest,
            status_class={
                "ok": "terminal",
                "reject": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
        Stage(
            "parse",
            _parse,
            needs=[("ingest", {"ok"})],
            mutates=["zh"],
            status_class={
                "ok": "terminal",
                "reject": "terminal",
                "skip": "upstream",
                "error": "retriable",
            },
        ),
        Stage(
            "xlat",
            _xlat,
            needs=[("parse", {"ok"})],
            paid=True,
            mutates=["zh", "state"],
            dedup_key=("idc", "arm", "variant"),
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "reject": "terminal",
                "skip": "upstream",
                "error": "retriable",
            },
        ),
        Stage(
            "compile",
            _compile,
            needs=[("xlat", {"ok", "partial"})],
            mutates=["splice"],
            status_class={
                "ok": "terminal",
                "clean": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "reject": "terminal",
                "dirty_pdf": "terminal",
                "skip": "upstream",
                "error": "retriable",
            },
        ),
        Stage(
            "fixloop",
            _fixloop,
            needs=[("compile", {"clean", "partial"})],
            on={"compile": {"fail", "dirty_pdf"}},
            paid=True,
            mutates=["splice"],
            dedup_key=("idc", "arm", "variant"),
            status_class={
                "ok": "terminal",
                "clean": "terminal",
                "partial": "terminal",
                "fail": "terminal",
                "reject": "terminal",
                "dirty_pdf": "terminal",
                "skip": "upstream",
                "error": "retriable",
            },
        ),
    ],
)
