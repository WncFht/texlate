r"""quality — S5 质量面代理指标的 rescore spec（quality_proxies 后算驱动的 v2 形态）。

对**既有 run 的账**重算 leak/term/landmark 三族指标——纯本地零付费。
item = index records 里资格格的**源 credential 复刻**（arm/up 逐字，
variant = ``{src_variant}@{EPOCH}`` 测量代际——``@`` 后缀给 forever-
dedup 留重跑门：指标逻辑变了 bump EPOCH 即新一轮测量）。

资格集（旧 process_run 枚举口径逐字平移）：

- ``qxlat``：records stage='xlat' 末条 DONE 且 status∈{ok,partial,fail}
  全臂收（fail 也算——leak 是 parse 质量面不依赖译文）；
- ``qcompile``：stage∈{compile,base} 且 status∈{clean,partial}。
  旧 ``arm∈{zh,base}`` 过滤的语义载体是「zh 编译树 vs base 编译树」
  两个产物角色——v2 里角色由 stage 名承担（compile=zh 产物、
  e2e_real base=英文基线产物），arm 是 credential 坐标不是目录名，
  故按 stage+status 枚举（对既有数据与旧过滤逐格等价：旧 compile
  行 arm 本来就只有 zh/base）。

item 携带 ``stage`` 字段走 kernel 单 stage 路由（kernel.py:276
``wanted`` 过滤）——一个 item 只物化一个 cell，无空转 cell 占账。

读径：``ctx.upstream_rec`` 按本 cell variant 查不到源 variant 的账，
故资格复核经 ``specs._shared._last_done`` 显式传 ``variant=src_variant``
（全域末条 DONE 行投影、fail/clean/partial 全在 STATUS_DONE 内）。资产经
``vault.restore`` 物化（**绝不复读活树**——replay-mutex-window
教训）；vault 目录名为 ``{kind}.{arm}[@{variant}]``（``_work_dirname``，
``'-'`` variant 省略 ``@`` 段）。

term 口径：``TERM_ARMS={'real'}`` 臂门逐字保留——soak v2 cell arm='-'
是「恒真臂」匿名形态，rescore 里保守置 null（soak 内联接线已覆盖其
term 面；rescore 是给未接线 run 的后门）。持久化 term_dict.json 优先
于重建（真实注入表 > 假设表），``rebuild_term=False`` 禁重建兜底。

分母守恒：终态质量行数 = 资格 records 数；逐格分母（leak_total/
term_applicable/n_expected）由同一字节输入恒等；metrics 子树名
``translate.*``/``landmark.*`` 与键集逐字保留（缺键=null 语义差异
会静默改聚合分母）。
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import sqlite3
from typing import TYPE_CHECKING

import pypdf  # 版本敏感（dossier：跨机 landmark 口径）→ 版本记 metrics

if TYPE_CHECKING:
    from pathlib import Path

from kernel import idnorm, paths, vault
from kernel.spec import Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

from specs import _qmetrics as qm
from specs._shared import _DONE_STS, _last_done

EPOCH = "v1"

_XLAT_STAGE = "xlat"
_XLAT_ELIGIBLE = ("ok", "partial", "fail")
_COMPILE_STAGES = ("compile", "base")
_COMPILE_ELIGIBLE = ("clean", "partial")

# ---------------------------------------------------------------- items/select


def _src_items() -> list[dict]:
    """资格 records 末条胜投影 → 单 stage 路由 item。

    全域枚举（不分 run——「credential 的当前最好状态」即测量对象；
    ``run`` selector 按 src_run 收窄）。逐格指纹 = 源行身份+状态+fp，
    上游重测/状态翻转即新测量代际。
    """
    db = paths.index_path()
    if not db.is_file():
        return []
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT run,idc,arm,up,variant,stage,status,fp FROM records "  # noqa: S608
            f"WHERE stage IN ('xlat','compile','base') "
            f"AND status IN ({','.join('?' * len(_DONE_STS))}) "
            "ORDER BY rowid",
            _DONE_STS,
        ).fetchall()
    finally:
        con.close()
    latest: dict[tuple, dict] = {}
    for run, idc, arm, up, variant, stage, status, fp in rows:
        latest[(idc, arm, up, variant, stage)] = {
            "run": run,
            "idc": idc,
            "arm": arm,
            "up": up,
            "variant": variant,
            "stage": stage,
            "status": status,
            "fp": fp,
        }
    items = []
    for rec in latest.values():
        stage, status = rec["stage"], rec["status"]
        if stage == _XLAT_STAGE:
            if status not in _XLAT_ELIGIBLE:
                continue
            qstage = "qxlat"
        elif stage in _COMPILE_STAGES and status in _COMPILE_ELIGIBLE:
            qstage = "qcompile"
        else:
            continue
        src_variant = rec["variant"] or "-"
        ident = (
            "|".join(str(rec[k]) for k in ("run", "idc", "arm", "up", "stage"))
            + f"|{src_variant}|{status}|{rec['fp']}"
        )
        items.append(
            {
                "id": rec["idc"],
                "arm": rec["arm"] or "-",
                "up": rec["up"] or "-",
                "variant": f"{src_variant}@{EPOCH}",
                "stage": qstage,
                "fp_input": hashlib.sha256(ident.encode()).hexdigest(),
                "params": {
                    "src_run": rec["run"],
                    "src_stage": stage,
                    "src_status": status,
                    "src_variant": src_variant,
                },
            }
        )
    return items


def _select(item: dict, rp: dict) -> bool:
    """``run`` selector：src_run 子串收窄；``ids``：canon 双侧归一直选。"""
    want_run = str(rp.get("run") or "").strip()
    if want_run and want_run not in str(
        (item.get("params") or {}).get("src_run") or ""
    ):
        return False
    ids_p = str(rp.get("ids") or "").strip()
    if ids_p:
        want: set[str] = set()
        for raw_tok in ids_p.split(","):
            tok = raw_tok.strip()
            if not tok:
                continue
            want.add(tok)
            res = idnorm.canon_id(tok)
            if res.ok and res.idc:
                want.add(res.idc)
        if str(item.get("id")) not in want:
            return False
    return True


# ---------------------------------------------------------------- 源账复核
# ``_last_done`` 共享实现收 specs/_shared.py——本 spec 的 ctx.variant 带
# @EPOCH 后缀查不了源账，调用点恒显式传 ``variant=src_variant``。


def _gate(status: str, code: str, cat: str, payload) -> dict:
    """soak._gate 同款：status + 单条 errors；sig 由内核 errors[0] cat:pay
    自动合成。"""
    return {
        "status": status,
        "code": code,
        "errors": [{"code": code, "cat": cat, "payload": payload}],
    }


# ---------------------------------------------------------------- stages


def _qxlat(ctx):
    """state.{arm}[@{src_variant}]/state.json → translate.{leak_*,term_*}。"""
    src_variant = str(ctx.params.get("src_variant") or "-")
    rec = _last_done(ctx, _XLAT_STAGE, src_variant)
    if rec is None or rec["status"] not in _XLAT_ELIGIBLE:
        return _gate(
            "skip",
            "src_ineligible",
            "upstream",
            f"xlat last-done {None if rec is None else rec['status']}",
        )
    dest = ctx.paper_dir()
    try:
        vault.restore(ctx.idc, ctx.arm, src_variant, dest, mode="link")
    except vault.VaultError:
        return _gate(
            "skip",
            "state_missing",
            "asset",
            f"no intact copy ({ctx.idc},{ctx.arm},{src_variant})",
        )
    sdir = dest / vault._work_dirname("state", ctx.arm, src_variant)
    # 持久化 term_dict（真实注入表）优先于重建假设表
    term_dict = None
    tdp = sdir / "term_dict.json"
    if tdp.is_file():
        with contextlib.suppress(OSError, ValueError):
            td = json.loads(tdp.read_text(encoding="utf-8"))
            if isinstance(td, dict):
                term_dict = td
    cat_group = None
    local = None
    if ctx.arm in qm.TERM_ARMS:
        cat_group = _cat_groups().get(ctx.idc)
        src = ctx.src_path()
        local = (src / qm.LOCAL_GLOSSARY_NAME) if src else None
    patch, miss = qm.xlat_metrics(
        sdir,
        ctx.arm,
        cat_group,
        local,
        term_dict=term_dict,
        allow_rebuild=bool(ctx.params.get("rebuild_term", True)),
    )
    if patch is None:
        cat = "asset" if not str(miss).startswith("state_bad") else "parse"
        status = "error" if str(miss).startswith("state_bad") else "skip"
        return _gate(status, str(miss), cat, f"{sdir}")
    ctx.emit(
        {
            "metrics": {
                **patch,
                "src": {
                    "run": ctx.params.get("src_run"),
                    "status": ctx.params.get("src_status"),
                    "arm": ctx.arm,
                    "variant": src_variant,
                },
            }
        }
    )
    return "ok"


def _splice_cred(ctx, src_variant: str) -> tuple[str, str] | None:
    """本 idc 的 splice 持有 credential——优先 (up,src_variant) →
    (arm,src_variant) → 最高 zone 序完好副本。

    旧 work/{id}/splice/ 是 last-writer-wins，importer 把幸存字节归到
    translator arm（'real'）credential 下而非 compile 行自报 arm
    （zh/base）——故 credential 必须按 vault 实查，不能照抄 records
    arm。无产物 pdf 的 splice 副本（fig-only/pdf-less 残壳）先被
    _copy_product_ok 闸掉——compile_metrics 拿不到 pdf 的 cred 不能发。
    选中的 credential 记入 metrics.asset 供归因审计。
    """
    try:
        cands = [
            m
            for m in vault.query(ctx.idc)
            if m.get("bytes_ok")
            and "splice" in (m.get("files") or {})
            and vault._copy_product_ok(m, "splice")[0]  # noqa: SLF001
        ]
    except vault.VaultError:
        return None
    if not cands:
        return None
    rank = {"primary": 0, "alt": 1, "quar": 2, "pending": 3}

    def key(m):
        arm, var = m.get("arm") or "-", m.get("variant") or "-"
        pref_up = 0 if (arm, var) == (ctx.up, src_variant) else 1
        pref_arm = 0 if (arm, var) == (ctx.arm, src_variant) else 1
        return (
            pref_up,
            pref_arm,
            rank.get(str(m.get("zone") or "pending"), 4),
            str(m.get("altseq") or "0"),
        )

    best = min(cands, key=key)
    return (best.get("arm") or "-", best.get("variant") or "-")


def _main_rel(ctx, rec: dict, dest: Path, cred: tuple[str, str]) -> str | None:
    """main_rel 三段式：compile 账 metrics → 恢复树 zh 层 parse.json →
    build_dir find_main_tex。"""
    m = (rec.get("metrics") or {}).get("main_rel")
    if isinstance(m, str) and m:
        return m
    zh = dest / vault._work_dirname("zh", cred[0], cred[1])
    pj = zh / "parse.json"
    if pj.is_file():
        try:
            doc = json.loads(pj.read_text(encoding="utf-8"))
            if doc.get("main_rel"):
                return str(doc["main_rel"])
        except (json.JSONDecodeError, OSError):
            pass
    return None


def _qcompile(ctx):
    """splice.{arm}[@{variant}]/ 编译树 + pdf → landmark.*。"""
    src_stage = str(ctx.params.get("src_stage") or "compile")
    src_variant = str(ctx.params.get("src_variant") or "-")
    rec = _last_done(ctx, src_stage, src_variant)
    if rec is None or rec["status"] not in _COMPILE_ELIGIBLE:
        return _gate(
            "skip",
            "src_ineligible",
            "upstream",
            f"{src_stage} last-done {None if rec is None else rec['status']}",
        )
    cred = _splice_cred(ctx, src_variant)
    if cred is None:
        return _gate(
            "skip",
            "splice_missing",
            "asset",
            f"no intact splice credential for {ctx.idc}",
        )
    dest = ctx.paper_dir()
    try:
        vault.restore(ctx.idc, cred[0], cred[1], dest, mode="link")
    except vault.VaultError:
        return _gate(
            "skip",
            "splice_missing",
            "asset",
            f"restore ({ctx.idc},{cred[0]},{cred[1]}) failed",
        )
    build_dir = dest / vault._work_dirname("splice", cred[0], cred[1])
    patch, miss = qm.compile_metrics(build_dir, _main_rel(ctx, rec, dest, cred))
    if patch is None:
        status = "error" if str(miss).startswith("landmark_bad") else "skip"
        return _gate(status, str(miss), "asset", f"{build_dir}")
    ctx.emit(
        {
            "metrics": {
                **patch,
                "asset": {"arm": cred[0], "variant": cred[1]},
                "src": {
                    "run": ctx.params.get("src_run"),
                    "stage": src_stage,
                    "status": ctx.params.get("src_status"),
                },
                "pypdf": getattr(pypdf, "__version__", None),
            }
        }
    )
    return "ok"


# ---------------------------------------------------------------- spec

_cat_groups_cache: dict | None = None


def _cat_groups() -> dict:
    global _cat_groups_cache  # noqa: PLW0603
    if _cat_groups_cache is None:
        _cat_groups_cache = qm.load_cat_groups()
    return _cat_groups_cache


spec = Spec(
    kind="quality",
    eval=True,
    params={
        "run": Param(str, default=""),
        "ids": Param(str, default="", fp=False),
        "rebuild_term": Param(bool, default=True, fp=True),
    },
    items=_src_items,
    select=_select,
    freeze_plan=True,
    code_deps=[
        "src/texlate/align",
        "src/texlate/xlat/glossary.py",
        "src/texlate/textutil.py",
    ],
    stages=[
        Stage(
            "qxlat",
            _qxlat,
            status_class={
                "ok": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
        Stage(
            "qcompile",
            _qcompile,
            status_class={
                "ok": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
    ],
)
