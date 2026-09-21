r"""bench 共享小件——records jsonl 读写 / corpus manifest / 编译侧公共常量。

设计约束：**纯 stdlib、模块级零 IO**——import 本文件不依赖 texlate.*
（judge_dict 内延迟 import），system python3 与 `uv run` 下皆可载。

records 契约（docs/research/product/2026-09-16-hardening-notes.md §6）：
每篇/每格一行 append——行在盘上 = done，续跑即按 key 跳过。
"""

from __future__ import annotations

import functools
import hashlib
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path

try:
    import fcntl
except ImportError:  # 无 fcntl 平台（win 等）→ append_jsonl 退化为无锁
    fcntl = None  # type: ignore[assignment]

#: tlnet 镜像统一钉 tuna——mirror.ctan.org round-robin 本机不通
#:（fixloop_bench/compilebench_v3 2026-09-15 实测；usertree `option repository`
#: 逐篇钉住 → tlmgr install 不吃镜像抖动）。引擎子进程 child_env 不透传
#: *_PROXY → 必须直连可达镜像。
TUNA_TLNET = "https://mirrors.tuna.tsinghua.edu.cn/CTAN/systems/texlive/tlnet"

#: copytree 进工作区时剔除的编译副产物/平台垃圾（compilebench_v2/v3、
#: fixloop_bench 三处同源；v3 另剔 "_texmf" 冷 usertree 残留）。
_IGNORE_BASE = (
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


def copytree_ignore(*extra: str):
    """编译工作区 copytree 的 ignore 回调；``extra`` 追加库级剔除项。"""
    return shutil.ignore_patterns(*_IGNORE_BASE, *extra)


def safe_id(rel: str) -> str:
    """工程 id（可含 ``archive/id`` 斜杠）→ 单层工作区目录名。"""
    return rel.replace("/", "--")


def canon_id(pid: str) -> str:
    """论文 id 规范形：``--`` → ``/``——``safe_id`` 的逆。

    arXiv id 本体永不含 ``--``（旧式 ``archive/YYMMNNN`` 的 archive 只带
    单 ``-``，新式 ``YYMM.NNNNN`` 无 dash），故 ``--`` 必为 safe_id 单层
    目录名的回流拼写（从 ``work/`` 目名拷进 ``--ids``）。归一幂等：输出
    无 ``--``，再调不变。``math--0408287``/``math/0408287`` 归同一规范形
    → 同 records 键、同 workdir、单任务（loop1 实证 65 对双拼写并存，
    fixloop --rerun 同 wid 并发互 rmtree 罩 post 复判的根因）。
    原 ``stagerun_lib.canon_id`` 下沉单源——harvest/qualbench 等
    stdlib-only 消费方免 import stagerun 内核。
    """
    return str(pid).replace("--", "/")


# ---------------------------------------------------------------- records
def iter_jsonl(path: Path, *, on_bad="skip", errors: str = "replace"):
    """逐行 yield 解析值；空行跳过，坏 json 行按 ``on_bad`` 处置。

    append 账的 kill 截尾是常态——容忍坏行保住续跑。``on_bad``：
    ``"skip"`` 静默跳（默认）；``"warn"`` 读完向 stderr 汇总一行
    （triage 口径）；callable 逐坏行回调 ``on_bad(raw_line, exc)``。
    ``errors`` 透传 decode——默认 ``"replace"`` 截尾多字节留 U+FFFD
    → 坏行按 ``on_bad`` 跳；``"strict"`` 炸 UnicodeDecodeError（需硬
    失败口径的调用方自钉）。
    """
    bad = 0
    for raw in path.read_text(encoding="utf-8", errors=errors).splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as e:
            bad += 1
            if callable(on_bad):
                on_bad(raw, e)
    if bad and on_bad == "warn":
        print(f"  warn: {path.name} 跳过 {bad} 行坏 json", file=sys.stderr)


def read_jsonl(path: Path) -> list[dict]:
    """jsonl → list[dict]（不存在 → 空表）。"""
    return list(iter_jsonl(path)) if path.exists() else []


def write_jsonl(fh, rec: dict) -> None:
    """持有句柄上写一行 + flush（per-item 落盘粒度）。"""
    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
    fh.flush()


def append_jsonl(path: Path, rec: dict) -> None:
    """一次性 open-append-close（无长驻句柄的调用点用）；父目录缺席自建。

    写临界区经 ``flock`` 串行化——bench 并行/多 worker 共享同一账文件时
    防行交错；无 fcntl 平台退化为无锁。canonical 件 =
    ``texlate.textutil.jsonl.append_jsonl``——本模块纯 stdlib 约束
    （``qualbench`` 臂零 texlate 依赖）就地镜像同构实现。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def atomic_write_text(path: Path, text: str) -> None:
    """整文件写：同目录 mkstemp 随机缀 ``.<name>.<rand>.tmp`` 落盘后
    ``os.replace``——截尾只留 tmp 不伤旧文件。

    随机后缀防同路径并发撞名（``texlate.xlat.state.atomic_json`` 同式）——
    固定 ``.tmp`` 名在两写者同发时会互踩（先 replace 者后被另一方的
    unlink/replace 误伤）。
    """
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def atomic_write(path: Path, data: bytes | str, *, mode: int | None = 0o600) -> None:
    """mkstemp 随机 tmp + 写 + chmod + ``os.replace`` 原子落盘。

    ``texlate.textutil.osutil.atomic_write`` 的同构镜像（canonical 件在
    osutil——本模块纯 stdlib 约束就地复刻，``e2e_real_bench._atomic_write``
    等 bench 侧写点走本函数）。tmp 名带随机后缀防同路径并发撞名，异常
    清 tmp 不留尸；``os.replace`` 跨平台原子覆盖。``mode=None`` 跳过
    chmod（沿用 mkstemp 0600/umask 口径的调用方）——注意与楼上
    ``atomic_write_text`` 的 mkstemp 直写形并存，勿互套。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        if isinstance(data, str):
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(data)
        else:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
        if mode is not None:
            Path(tmp).chmod(mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def latest_by(items, keyfn, valfn=None) -> dict:
    """``keyfn`` 末条胜去重 → {key: item}（dict 插序 = 首见键序）。

    ``valfn`` 指定时存 ``valfn(item)`` 代替 item 本体——末位索引这类
    派生值去重（``enumerate`` + ``valfn=lambda t: t[0]``）。
    """
    out = {}
    for item in items:
        out[keyfn(item)] = valfn(item) if valfn else item
    return out


def rec_key(rec: dict) -> tuple[str, str, str]:
    """stagerun/triage 账键 (id, arm, upstream)——resume 追加同键新行、末条胜。"""
    return (
        str(rec.get("id")),
        str(rec.get("arm") or "-"),
        str(rec.get("upstream") or ""),
    )


def load_records(path: Path, key: str = "id") -> dict[str, dict]:
    """append 账 → {key: rec} 末行胜（rerun 重记同 id 自然覆盖）。"""
    return latest_by(
        (r for r in iter_jsonl(path) if isinstance(r, dict) and key in r),
        lambda r: str(r[key]),
    )


def latest_records(
    path, *, arm: str | None = None, upstream: str | None = None
) -> dict[str, dict]:
    """records jsonl → ``{canon_id: 末条记录}``（按 append 行序后者胜）。

    摊平口径：每篇只留最新一条——「每篇终态」消费面单源（harvest
    clean_ids、stage_fixloop 候选捞格同源两处）。要 (id,arm,upstream)
    三元键并存/多臂格的走 ``stagerun_lib.load_latest``；要行级去向账
    的走 gate_scorecard.scan_records（口径差异有意保留，勿互套）。

    ``arm``/``upstream`` 精确匹配过滤（``None`` 不限）；``upstream``
    缺字段按 ``""`` 计——stage_fixloop ``--xlat-arm`` 捞格同口径
    （arm_mismatch skip 格 upstream 为空，自然滤除）。非 dict / 缺
    ``id`` 的行跳过（iter_jsonl 坏行同口径——append 账容忍截尾）。
    键经 ``canon_id`` 归一：flat 拼写存量账按规范形命中（同
    ``stagerun_lib._rec_key`` 键面）。
    """
    fp = Path(path)
    if not fp.is_file():
        return {}

    def _want(r) -> bool:
        return (
            isinstance(r, dict)
            and bool(r.get("id"))
            and (arm is None or r.get("arm") == arm)
            and (upstream is None or str(r.get("upstream") or "") == upstream)
        )

    return latest_by(
        (r for r in iter_jsonl(fp) if _want(r)),
        lambda r: canon_id(str(r["id"])),
    )


def seed_run_records(rec_path: Path, out_path: Path, *, on_bad_seed=None) -> dict:
    """records.jsonl→results.json 回退种子：append 账优先，账空回退快照。

    ``load_records`` 读 ``rec_path``（不存在 → ``{}``）；结果为空且
    ``out_path``（results.json）存在时读快照兜底——空 records 曾把有快照的
    旧目录判成全量重跑（scout-e2ereal §7）。快照坏 JSON/不可读时按空种子
    起步不炸启动；``on_bad_seed`` 非 None 时以异常实例回调
    （``(OSError, json.JSONDecodeError)``——e2e_real_bench 打印 WARNING
    行，e2e_mock_bench 静默不传）。快照解析出非 dict 同样按空计。

    e2e_mock_bench.seed_results / e2e_real_bench.amain 同型下沉单源。
    """
    results = load_records(rec_path) if rec_path.exists() else {}
    if not results and out_path.exists():
        try:
            loaded = json.loads(out_path.read_text())
        except (OSError, json.JSONDecodeError) as e:
            if on_bad_seed is not None:
                on_bad_seed(e)
            loaded = {}
        results = loaded if isinstance(loaded, dict) else {}
    return results


def cond_status(rec: dict, cond: str) -> str:
    """report 矩阵格：``cond`` 臂缺席 → ``"·"``，否则其 ``verdict.status``（缺 → ``"?"``）。

    e2e_mock_bench._v / e2e_real_bench._v 逐字节同源下沉——results.json
    旧格式种子行缺 cond 键是常态，``rec.get(cond)`` 宽容读。
    """
    c = rec.get(cond)
    if c is None:
        return "·"
    return c.get("verdict", {}).get("status", "?")


# ---------------------------------------------------------------- status 词汇
#: 各消费方原表原样下沉——口径不对称是既有行为（triage 认 legacy 词
#: gate_scorecard 不认），单源≠拉齐。
BENCH_ERROR_STATUS = "bench_error"

#: 记录状态词汇：ok 系不出票; skip 系 (上游断/policy 拒) 不计入 attempted。
OK_STATUS = {"ok", "clean", "done"}
SKIP_STATUS = {
    "skip",
    "skipped",
    "reject",
    "rejected",
    "upstream_fail",
    # e2e_real 旧账遗留词（LEGACY_ARM_MAP 流入 triage 同口径）
    "skipped_oversize",
    BENCH_ERROR_STATUS,
}
#: fixloop 救援成功的终态 (含带伤出 pdf)。
RESCUED_STATUS = {
    "ok",
    "clean",
    "acceptable_pdf",
    "best_effort_pdf",
    "dirty_pdf",
    "partial",
}
#: fixloop 终态词 → core 单 (规则面之外的引擎缺口)。
TERMINAL_WORDS = {"stuck", "max_rounds"}

#: 状态序数表 (高=好): fixloop_degraded 跨段退化判定与 rundiff 逐格迁移共用;
#: 表外词 (skip/error/...) 一律按 -1 计。
STATUS_RANK = {"clean": 3, "ok": 3, "partial": 2, "fail": 1, "reject": 0}

#: stagerun resume 谓词终态集——落账即 done（skip/error 可重试）。
DONE_STATUS = {"ok", "partial", "clean", "fail", "reject", "fault", "dirty_pdf"}
RETRIABLE_STATUS = {"skip", "error"}

#: gate_scorecard fix 覆盖门槛——真编译结果集（reject/skip 格的 fixloop 不计）。
COMPILED_STATUS = {"fail", "partial", "clean"}


# ---------------------------------------------------------------- 签名合成
def errors_sig(errors: list[dict]) -> str:
    """errors[0] → ``cat:pay`` 签名（triage 契约：ok 级无 sig）。"""
    if not isinstance(errors, (list, tuple)) or not errors:
        return ""
    e0 = errors[0]
    if not isinstance(e0, dict):
        return ""
    cat = str(e0.get("cat") or e0.get("code") or "error")
    pay = str(e0.get("payload") or "")
    return f"{cat}:{pay}".rstrip(":")


def fixloop_attr(rounds, fv=None, final_cat=None):
    """fixloop 归因 (cat, pay) = verdict 所结算的末个正规轮。

    salvage 哨兵 (``"salvage": true``；旧 schema 无标——尾巴 cat 空且
    verdict 非 clean 系即哨兵，因 clean/no_errors_no_pdf 之外的 verdict
    只在非空 cat 轮结算) 不占归因槽。末轮 pay 空不回填旧轮——回填会把
    已修轮的签名贴上来 (2609.19664: r2 latin 已装，r3-r5 ``other:None``
    streak 触 stuck, 回填 latin 成 ``stuck:latin`` 误桶)。
    """
    rds = [rd for rd in (rounds or []) if isinstance(rd, dict)]
    last = rds[-1] if rds else {}
    if len(rds) > 1 and (
        last.get("salvage")
        or (
            not (last.get("category") or last.get("cat"))
            and str(fv or "") not in {"clean", "no_errors_no_pdf"}
        )
    ):
        last = rds[-2]
    fcat = last.get("category") or last.get("cat") or final_cat
    fpay = last.get("pay") or last.get("payload") or ""
    return fcat, fpay


def fixloop_sig(fv, fcat=None, fpay=None) -> str:
    """fixloop verdict → 记录 sig：裸 ``unfixable:``/终态词补 final_cat，
    再拼归因轮 payload（stagerun._fixloop_one / triage.legacy_records
    同源两处；fcat/fpay 口径 ``fixloop_attr``）。"""
    sig = str(fv)
    if sig.startswith("unfixable:"):
        if fcat and str(fcat) not in sig:
            sig = f"{sig}:{fcat}"
    elif sig in TERMINAL_WORDS and fcat:
        # stuck streak 签 {cat}:{pay} 的头半——cat 进桶键分 stuck 机制面
        sig = f"{sig}:{fcat}"
    if fpay:
        sig = f"{sig}:{fpay}"
    return sig


# ---------------------------------------------------------------- 记录指纹
def _strkey(d):
    """dict 键一律 str 化——混合类型键下 ``sort_keys`` 排序即 TypeError。"""
    return {str(k): v for k, v in d.items()} if isinstance(d, dict) else d


def compile_fp(c: dict) -> str:
    """compile 记录身份指纹（sha256[:16]）——verdict 决定字段的稳定摘要。

    fixloop 记录新鲜度校验的比对料单源：写侧 ``stage_fixloop`` 落
    ``metrics.compile_fp``，读侧 ``gate_scorecard.pick_final`` 比对——
    compile 重跑 status 不变但 sig/first_error 已换（同态陈旧）时，
    ``compile_status_before`` 状态等值放行、指纹不等即拦。
    计时字段（seconds/dur_s）不入——逐跑恒变而非 verdict 语义。
    """
    m = c.get("metrics")
    if not isinstance(m, dict):
        m = {}
    comp = m.get("compile")
    if not isinstance(comp, dict):
        comp = {}
    v = m.get("verdict")
    if not isinstance(v, dict):
        v = {}
    blob = json.dumps(
        [
            c.get("status"),
            c.get("sig"),
            c.get("code"),
            comp.get("first_error"),
            v.get("category"),
            v.get("payload"),
            _strkey(v.get("error_cats")),
            _strkey(m.get("taxonomy")),
        ],
        ensure_ascii=False,
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


# ---------------------------------------------------------------- run_meta
def parse_iso(s):
    """ISO 串 → datetime；不可解 → None（run_meta 字段容错共用）。"""
    try:
        return datetime.fromisoformat(str(s))
    except (ValueError, TypeError):
        return None


def load_run_meta(results_dir: Path, *, strict: bool = False, default=None):
    """``results_dir/run_meta.json`` → 解析值（union schema 读径归一）。

    stagerun 形 ``{created_at,started_at,invocations,finished_at,git_rev}`` 与
    e2e 形 ``{seed,code,layers,...,ended_at,end_reason}`` 共用此读径——字段
    不校验，解析结果原样返回（形状归消费方判）。

    缺文件 → ``default``；坏 JSON → ``strict`` 原样抛 JSONDecodeError
    （stagerun 写方口径：腐 meta 不静默吞），否则 ``default``。``default``
    为 callable 时仅缺席才调用——惰性默认值（git_rev 这类付代价的）。
    """
    mp = results_dir / "run_meta.json"
    if not mp.exists():
        return default() if callable(default) else default
    try:
        return json.loads(mp.read_text())
    except json.JSONDecodeError:
        if strict:
            raise
        return default() if callable(default) else default


def meta_window(meta: dict):
    """run_meta → (t0, t1)：started_at → finished_at|ended_at|completed_at。

    e2e 词 ``ended_at``（``completed_at`` 兜底）与 stagerun ``finished_at``
    在此并轨；不可解端 → None（消费方回退 dur_s 求和口径）。
    """
    return (
        parse_iso(meta.get("started_at")),
        parse_iso(
            meta.get("finished_at") or meta.get("ended_at") or meta.get("completed_at")
        ),
    )


# ---------------------------------------------------------------- manifest
def manifest_paths(corpus: Path, layers) -> list[tuple[str, Path]]:
    """corpus 分层 manifest → [(layer, path)]：core→manifest.jsonl，
    其余→manifest_{layer}.jsonl；不存在的层跳过。"""
    out = []
    for layer in layers:
        fp = corpus / (
            "manifest.jsonl" if layer == "core" else f"manifest_{layer}.jsonl"
        )
        if fp.exists():
            out.append((layer, fp))
    return out


def load_manifest_rows(corpus: Path, layers) -> list[dict]:
    """分层 manifest → [{...,"layer": layer}]；行缺 layer 字段时补所在层。"""
    rows: list[dict] = []
    for layer, fp in manifest_paths(corpus, layers):
        for rec in read_jsonl(fp):
            rec.setdefault("layer", layer)
            rows.append(rec)
    return rows


def manifest_layers(corpus: Path) -> list[str]:
    """磁盘在册的全部层名：manifest.jsonl→core、manifest_X.jsonl→X。"""
    out = []
    for fp in sorted(corpus.glob("manifest*.jsonl")):
        if fp.name == "manifest.jsonl":
            out.append("core")
        elif fp.name.startswith("manifest_"):
            out.append(fp.stem.removeprefix("manifest_"))
    return out


def corpus_ids(corpus: Path) -> set[str]:
    """全层 id 并集——去重/qc 单源；新层入库即自动入集，勿再硬编码层清单。"""
    return {r["id"] for r in load_manifest_rows(corpus, manifest_layers(corpus))}


# 仅评测层（held-out）：在册但不得进 dev bench 默认枚举——dev==eval 隔离闸。
# 评测走显式 ``--layers holdout``；去重仍走 corpus_ids（含 holdout）。
EVAL_ONLY_LAYERS = frozenset({"holdout"})


def dev_layers(corpus: Path) -> list[str]:
    """dev 可枚举层 = 在盘层 − EVAL_ONLY_LAYERS。"""
    return [la for la in manifest_layers(corpus) if la not in EVAL_ONLY_LAYERS]


# ---------------------------------------------------------------- compile
def judge_dict(res, *, expect_cjk: bool) -> dict:
    """CompileResult → {compile, verdict, status, l2_attr, taxonomy}——
    ``texlate.e2e._compile_judge`` 同形状（bench 侧复刻点收敛：
    e2e_real/e2e_mock/stagerun 共用）。

    ``l2_attr`` = L2 log 归因载荷（canonical 键——``L2Verdict.attribution_dict``
    单源：逐条 ``{kind,file,line,head,log_line}`` hits + ``warn_by_class``），
    stagerun 落 ``metrics.l2_attr`` / fixloop post 落 ``metrics.post.l2_attr``，
    供 records 离线按类聚类 warning/error。产品侧 ``_tail_dict`` 有意不带
    （单跑报告走 ``rec["l2"]`` 修复链报告，键名不同不撞）。

    ``taxonomy`` = fixloop 内部分类器对本次编译 log 的二级分类
    ``{cat, pay}``（M1 物化，still-manual-audit-2026-09-17）——records 侧
    聚合桶 (other/errors>3/syntax) 由 dossier/triage 直读细分。
    """
    from texlate.compile.judge import judge
    from texlate.repair_l2 import _l2_parse

    v = judge(res, expect_cjk=expect_cjk)
    return {
        "compile": {
            "ok": res.ok,
            "timed_out": res.timed_out,
            "seconds": round(res.seconds, 2),
            "passes": res.passes,
            "rc": res.rc,
            "killed_signal": res.killed_signal,
            "pdf_bytes": res.pdf_bytes,
            "first_error": res.log.first_error,
        },
        "verdict": {
            "status": v.status,
            "reasons": v.reasons,
            "notes": v.notes,
            "n_errors": v.n_errors,
            "category": v.category,
            "payload": v.payload,
            "error_cats": v.error_cats,
            "error_pay": v.error_pay,
            "cjk_chars": v.cjk_chars,
            "missing_chars": v.missing_chars,
            "warnings_hit": v.warnings_hit,
        },
        "status": v.status,
        "l2_attr": _l2_parse(res).attribution_dict(),
        "taxonomy": _taxonomy_of(res),
    }


@functools.lru_cache(maxsize=1)
def _fixloop_rs():
    """fixloop Ruleset 懒载单例——taxonomy 物化逐格调，yaml 只解一次。"""
    from texlate.compile.fixloop import Ruleset

    return Ruleset.load()


def _taxonomy_of(res) -> dict:
    """CompileResult → fixloop taxonomy ``{cat, pay}`` (first_error 二级类)。"""
    try:
        from texlate.compile.fixloop.engine import _report_of

        rs = _fixloop_rs()
        rep = _report_of(res, rs.warn_patterns)
        cat, pay = rs.taxonomy.classify(
            rep, timed_out=bool(getattr(res, "timed_out", False))
        )
    except Exception:
        return {"cat": None, "pay": None}  # advisory 字段——分类故障不毁卷宗
    return {"cat": cat, "pay": pay}


_RE_MISSING_FILE = re.compile(r"File `([^']+)' not found")
_RE_MISSING_CHAR = re.compile(r"missing_character[×x](\d+)")


def verdict_sig(verdict: dict, first_error: str | None = None) -> str:
    """compile verdict 块 → 聚类 sig（stagerun records 与 triage legacy 降级单源）。

    cat 以 ``verdict.category`` 为准——此时 ``verdict.payload`` 是同字段对配，
    直接拼。cat 模糊（None/clean/other）时退 reasons 头抠 cat；派生 cat 不拼
    ``verdict.payload``（它配的是原 cat，拼上即错配），missing_file /
    missing_character 走正则从 first_error/reasons 回补 payload。

    ``error_cats``（judge 逐错误行构成）在场且众数 cat 错误量**严格大于**
    首错 cat 时 sig 改挂众数——首错遮 bulk 纠偏（quant-ph/9703040:110 错
    108×syntax，category 却是自恢复的 illegal_unit）；平票仍归
    首错（TeX 级联中首错是因果上游）。众数 payload 取 ``error_pay`` 首见值。
    cat 不在构成中（derived meta 词 killed_by_signal/no_pdf 等 verdict 级
    归因）不比众数——构成外恒 0 票会被任意众数顶包洗掉根因。

    裁决 2026-09-17（overseer）：sig 只担 dominant-error 分桶——missing_char
    等 warning 派生信号不并入（混进 error sig 是 phantom-payload 类 bug 温床）；
    misschar 检索走 ``verdict.missing_chars`` / ``warn:missing_chars`` reason。
    """
    vstatus = verdict.get("status")
    if vstatus in ("clean", None):
        return ""
    fe = first_error if isinstance(first_error, str) else ""
    cat = verdict.get("category")
    raw = verdict.get("reasons")
    if isinstance(raw, str):
        raw = [raw]
    elif not isinstance(raw, (list, tuple)):
        raw = []
    reasons = [str(r).strip() for r in raw if str(r).strip()]
    derived = cat in (None, "clean", "other")
    if derived:
        if any(r.startswith("missing_character") for r in reasons):
            cat = "missing_character"
        elif reasons:
            head = reasons[0]
            cat = (
                head.split("=", 1)[1].split(":")[0]
                if head.startswith("first_error=")
                else head.split()[0]
            )
    if not cat:
        return f"verdict:{vstatus}"
    pay = None if derived else verdict.get("payload")
    if not pay:
        if cat == "missing_file":
            m = _RE_MISSING_FILE.search(fe)
            pay = m.group(1) if m else ""
        elif cat == "missing_character":
            m = _RE_MISSING_CHAR.search(" ".join(reasons))
            pay = f"x{m.group(1)}" if m else ""
    cats = verdict.get("error_cats")
    if isinstance(cats, dict):
        bulk = {
            k: n
            for k, n in cats.items()
            if isinstance(k, str)
            and isinstance(n, int)
            and not isinstance(n, bool)
            and n > 0
        }
        dom = max(bulk, key=bulk.get) if bulk else None
        # 构成外 cat（derived meta 词：killed_by_signal/no_pdf/missing_character
        # 等 verdict 级归因）bulk.get 恒 0，不拦则任意众数顶包洗掉根因——只有
        # cat 真在错误行构成中才比（derived first_error=X 的 X 照常参与）。
        if dom is not None and cat in bulk and dom != cat and bulk[dom] > bulk[cat]:
            pays = verdict.get("error_pay")
            dpay = pays.get(dom) if isinstance(pays, dict) else None
            return f"{dom}:{dpay if isinstance(dpay, str) else ''}".rstrip(":")
    return f"{cat}:{pay or ''}".rstrip(":")


# ---------------------------------------------------------------- 语料抽样
def pick_sample(entries: list[dict], corpus: Path, n: int, seed: int) -> list[str]:
    """分层不区分地随机抽 n 个 id（``corpus/{id}/extracted/`` 在盘者）；排序返回。

    e2e_real_bench.pick_sample 单源（★6 下沉）——corpus 由调用方传入
    （benchlib 无 CORPUS 常量）。``random.Random(seed)`` 是复现语义非密码学。
    """
    avail = [e["id"] for e in entries if (corpus / e["id"] / "extracted").is_dir()]
    avail = sorted(set(avail))
    rng = random.Random(seed)
    picked = rng.sample(avail, min(n, len(avail)))
    return sorted(picked)


# ---------------------------------------------------------------- 产码印章
@functools.lru_cache(maxsize=1)
def code_stamp() -> str:
    """产码印章：``snap-<sha256[:12]>`` 或 ``<sha>``/``<sha>-dirty``。

    记进每格 record——parse/splice 层修复落地后旧格 tex 是陈字节
    （0707.3950 实证：resume 谓词把全 ok 格整篇 carry-over，postfix 臂编译
    打修复前文件，mtime 取证才识破）。``--recode`` 按印章差异强制重跑；
    chunk 级 state 缓存仍在，重翻免费、parse/splice/compile 走新码。

    ``TEXLATE_SRC`` 指向的冻结快照根带 ``snapshot-manifest.txt`` 时，印章
    钉 manifest 字节（``snap-`` 形态）而非 live repo——bench 期间 repo 被
    无关 commit/dirty 不再把全格误判 stale（反之快照换字节 manifest 换
    哈希，陈旧格必被 ``--recode`` 抓到）。无 manifest 回退 repo 戳。

    e2e_real_bench._code_stamp 单源（★6 下沉）——进程内一次（lru_cache），
    repo 根按本文件位置算（``bench/py/benchlib.py`` → parents[2]）。
    dirty 判据盖 ``src/texlate`` 与 ``bench/py`` 两树——harness 自身演化
    （stage_* / benchlib / scorecard 未提交改动）同样产陈记录。
    """
    src_env = os.environ.get("TEXLATE_SRC")
    if src_env:
        manifest = Path(src_env) / "snapshot-manifest.txt"
        if manifest.is_file():
            digest = hashlib.sha256(manifest.read_bytes()).hexdigest()
            return f"snap-{digest[:12]}"
    repo = Path(__file__).resolve().parents[2]
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            [  # noqa: S607
                "git",
                "status",
                "--porcelain",
                "--",
                "src/texlate",
                "bench/py",
            ],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}{'-dirty' if dirty else ''}"


# ---------------------------------------------------------------- 批脚本公共件
#: iclr_*/daily_arxiv 系批脚本的 stderr 时间戳日志/凭据 env/fetch 脚手架——
#: 原逐脚本就地抄的同型件下沉于此（stdlib-only，httpx 脚本亦可载）。


def log(msg: str) -> None:
    """stderr 时间戳日志行——脱管批（setsid nohup + run.log）共用形。"""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", file=sys.stderr, flush=True)


#: paper-search skill 的 ``.env``——OpenAlex/OpenReview 凭据读取口径
#: （iclr_map/iclr_pdf 原各拷一份）。
ENV_FP = Path.home() / ".claude/skills/paper-search/.env"


def load_env(path: Path = ENV_FP) -> dict[str, str]:
    """``.env`` → dict：``K=V`` 行切首等号，无 ``=`` 行跳过。"""
    return dict(
        ln.strip().split("=", 1) for ln in path.read_text().splitlines() if "=" in ln
    )


def rss_preflight(ua: dict[str, str], feed: str = "cs.CL") -> None:
    """rss.arxiv.org 健康探针——不通 ``sys.exit(3)`` 中止，不进 fetch 烧预算。

    daily_arxiv.preflight / iclr_fetch.preflight 同型下沉：urllib 30s 一发 +
    ``<rss`` 魔数校验（代理截获会返非 RSS 登录页，净连但语义无货同拦）。
    """
    import urllib.error
    import urllib.request

    try:
        req = urllib.request.Request(f"https://rss.arxiv.org/rss/{feed}", headers=ua)
        with urllib.request.urlopen(req, timeout=30) as r:  # noqa: S310 固定 https 端点
            body = r.read(400)
    except (urllib.error.URLError, OSError) as e:
        log(f"preflight FAILED: rss.arxiv.org unreachable ({e}) — 检查代理")
        sys.exit(3)
    if b"<rss" not in body[:400]:
        log("preflight FAILED: rss.arxiv.org 返回非 RSS——检查代理")
        sys.exit(3)


def fetch_done(status_fp: Path, *, id_key: str = "id") -> dict[str, str]:
    """fetch 状态账 jsonl → ``{id: 末条 status}``（仅终态行）——续跑跳过单源。

    daily_arxiv._fetch_done / iclr_fetch._fetch_done 同型下沉。终态集 =
    ``AcquireStatus`` 的成功/不可修类（error/budget/parked 留可重试）。
    ``id_key`` 适配异名账键（iclr_fetch 账用 ``arxiv_id``）。
    """
    from texlate.arxiv.fetch import AcquireStatus  # 迟绑——模块级零 texlate 约束

    terminal = {
        AcquireStatus.OK.value,
        AcquireStatus.PDF_ONLY.value,
        AcquireStatus.UNKNOWN_FORMAT.value,
        AcquireStatus.NOT_FOUND.value,
        AcquireStatus.TOO_LARGE.value,
        AcquireStatus.UNPACK_ERROR.value,
    }
    done: dict[str, str] = {}
    if not status_fp.exists():
        return done
    for r in iter_jsonl(status_fp):
        if isinstance(r, dict) and r.get(id_key):
            done[str(r[id_key])] = str(r.get("status"))
    return {k: v for k, v in done.items() if v in terminal}


def materialize_entry(entry_dir: Path, dst: Path) -> None:
    """fetch 缓存条目 → ``corpus/{id}``：rmtree 旧树 + copytree ``os.link``。

    硬链接而非拷贝——缓存条目即语料内容，双视图零额外空间；缓存清理后
    语料仍持有数据（daily_arxiv._materialize 单源；iclr_fetch 复制时丢落
    ``copy_function`` 属回归——此处复原同口径）。
    """
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(entry_dir, dst, copy_function=os.link)


# ---------------------------------------------------------------- 统计/文本小件
def quantile(xs, q: float, *, presorted: bool = False):
    """最近秩分位（ceil-rank）：``s[max(0, math.ceil(q*n)-1)]``；空输入 → ``None``。

    ``presorted=True`` 时 ``xs`` 按已升序处理跳过重排——
    parsebench.percentile 的 ``sorted_vals`` 契约、validbench._pct.q /
    alignbench._pct_vals.q / parsebench CI 上界等已排序站点直传。
    q ≤ 1 时 ``ceil(q*n) ≤ n`` 天然不越界（旧站点附带的 ``min(n-1, …)``
    clamp 冗余）；q=0 → 首元素。floor-index（gullet_bench/v2_diff 系）、
    round-over-(n-1)、插值系分位口径有意保留勿互套。
    """
    s = xs if presorted else sorted(xs)
    n = len(s)
    if n == 0:
        return None
    return s[max(0, math.ceil(q * n) - 1)]


def strip_comments(tex: str) -> str:
    r"""去注释：``\X`` 先吃两字符（``\%`` 不触发，``\\%`` 后 % 仍是注释），
    裸 ``%`` 删到行尾（保留换行）。不感知 verbatim。

    原 iclr_sections / parsebench / corpus.build_corpus_v3 三处逐字节同源
    副本下沉单源——verbatim 内 ``%`` 误剥是既有口径（仅用于主文件定位/
    路由标签场景），勿擅加 verbatim 感知。
    """
    out, i, n = [], 0, len(tex)
    while i < n:
        c = tex[i]
        if c == "\\":
            out.append(tex[i : i + 2])
            i += 2
            continue
        if c == "%":
            k = tex.find("\n", i)
            if k < 0:
                break
            out.append("\n")
            i = k + 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


# ---------------------------------------------------------------- 配额/auth 闸
#: 单篇可翻译总字符上限——超过记 skipped_oversize/oversize 终态不烧配额
#:（B5 首轮保守闸；e2e_real_bench.MAX_TOTAL_CHARS 单源，★6 下沉）。
MAX_TOTAL_CHARS = 250_000

#: 连续「全 auth 败」论文数熔断阈值——凭证中途死透时停跑不空烧
#:（probe 只探开局；篇内阈值块熔断由 AuthTrippedError 即停，本闸兜的是
#: 篇均不足阈值块、逐篇全 401 的慢速失血）。erb._AUTH_DEAD_STREAK 单源。
AUTH_DEAD_STREAK = 2


# ---------------------------------------------------------------- verdict 谓词
def misschar_partial(status, verdict: dict) -> bool:
    """缺字窄口：``partial`` ∧ ``missing_chars>0`` —— missing_char_fix 可修子集。

    stagerun._on_misschar / e2e_real_bench._want_fix 的 misschar 判定单源
    （★6 收敛）；其余 warning 级 partial 不进 fixloop（partial→fail 回退
    教训——fixloop 的 halt_on_error 编译只会丢已有 PDF）。
    """
    return status == "partial" and (verdict.get("missing_chars") or 0) > 0


# ---------------------------------------------------------------- 启动自检
async def preflight() -> list[str]:
    """起 bench 前的一致性检查——0 网络，烧配额前拦下半成品源码树。

    2026-09-15 实证：`src/texlate/` 被并行代理 mid-refactor 时，l0/placeholders
    引用未定义名（``_no_comments``/``mask_comments``）——导入面正常但调用即
    NameError，整批 chunk 静默 skipped。模块在进程启动加载一次即冻结，
    因此"启动时全量导入 + 无网走一遍 mock 链"即可免疫运行期被改。

    e2e_real_bench.preflight 单源（★6 下沉）——texlate.* 全部函数内延迟
    import（benchlib 模块级零 texlate 依赖不破；调用方须已把 src/ 上
    sys.path，stagerun_lib/erb 顶部各有一份 TEXLATE_SRC 惯例）。
    """
    import importlib
    import pkgutil

    import texlate
    from texlate.latex.api import parse_tex
    from texlate.validate.l0 import validate_pair
    from texlate.xlat.pipeline import (
        MockTranslator,
        XlatPipeline,
        chunk_to_in,
    )

    errs: list[str] = []
    for m in pkgutil.walk_packages(texlate.__path__, "texlate."):
        try:
            importlib.import_module(m.name)
        except Exception as e:
            errs.append(f"import {m.name}: {e!r}")

    try:
        scans = parse_tex(
            "\\documentclass{article}\n\\begin{document}\nHello world $x^2$.\n"
            "\\end{document}\n"
        )
        chunks = [
            chunk_to_in(c, chunk_id=f"0:{c.id}", ph_map=scans.ph_map)
            for c in scans.chunks
        ]
        pipe = XlatPipeline(
            MockTranslator(),
            validator=lambda s, z: validate_pair(s, z).feedback(),
        )
        results = await pipe.run(chunks)
        if any(r.status == "fault" for r in results):
            errs.append("mock chain: fault chunk in self-check")
    except Exception as e:
        errs.append(f"mock chain: {e!r}")
    return errs
