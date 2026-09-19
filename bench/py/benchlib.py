r"""bench 共享小件——records jsonl 读写 / corpus_v3 manifest / 编译侧公共常量。

设计约束：**纯 stdlib、模块级零 IO**——import 本文件不依赖 texlate.*
（judge_dict 内延迟 import），system python3 与 `uv run` 下皆可载。

records 契约（docs/research/product/2026-09-16-batch-hardening-design.md §6）：
每篇/每格一行 append——行在盘上 = done，续跑即按 key 跳过。
"""

from __future__ import annotations

import functools
import hashlib
import json
import os
import random
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

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
    """一次性 open-append-close（无长驻句柄的调用点用）。"""
    with path.open("a", encoding="utf-8") as fh:
        write_jsonl(fh, rec)


def atomic_write_text(path: Path, text: str) -> None:
    """整文件写：同目录 .tmp 落盘后 replace——截尾只留 .tmp 不伤旧文件。"""
    tmp = path.with_name(f"{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


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


# ---------------------------------------------------------------- status 词汇
#: 各消费方原表原样下沉——口径不对称是既有行为（triage 认 legacy 词
#: gate_scorecard 不认），单源≠拉齐。
BENCH_ERROR_STATUS = "bench_error"

#: 记录状态词汇: ok 系不出票; skip 系(上游断/policy 拒)不计入 attempted。
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
    已修轮的签名贴上来 (2609.19664: r2 latin 已装, r3-r5 ``other:None``
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
    """corpus_v3 分层 manifest → [(layer, path)]：core→manifest.jsonl，
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
    ``{cat, pay}``（M1 物化, still-manual-audit-2026-09-17）——records 侧
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
    """fixloop Ruleset 懒载单例——taxonomy 物化逐格调, yaml 只解一次。"""
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
    首错 cat 时 sig 改挂众数——首错遮 bulk 纠偏（quant-ph/9703040：110 错
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
