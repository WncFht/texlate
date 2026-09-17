r"""bench 共享小件——records jsonl 读写 / corpus_v3 manifest / 编译侧公共常量。

设计约束：**纯 stdlib、模块级零 IO**——import 本文件不依赖 texlate.*
（judge_dict 内延迟 import），system python3 与 `uv run` 下皆可载。

records 契约（docs/research/product/2026-09-16-batch-hardening-design.md §6）：
每篇/每格一行 append——行在盘上 = done，续跑即按 key 跳过。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
from datetime import datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
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
def iter_jsonl(path: Path, *, on_bad="skip", errors: str = "strict"):
    """逐行 yield 解析值；空行跳过，坏 json 行按 ``on_bad`` 处置。

    append 账的 kill 截尾是常态——容忍坏行保住续跑。``on_bad``：
    ``"skip"`` 静默跳（默认）；``"warn"`` 读完向 stderr 汇总一行
    （triage 口径）；callable 逐坏行回调 ``on_bad(raw_line, exc)``。
    ``errors`` 透传 decode——``"strict"`` 截尾多字节炸 UnicodeDecodeError
    （gate/benchlib 原口径），``"replace"`` 留 U+FFFD 续跑（triage 口径）。
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
    return latest_by((r for r in iter_jsonl(path) if key in r), lambda r: str(r[key]))


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
    if not errors:
        return ""
    cat = str(errors[0].get("cat") or errors[0].get("code") or "error")
    pay = str(errors[0].get("payload") or "")
    return f"{cat}:{pay}".rstrip(":")


def fixloop_sig(fv, fcat=None, fpay=None) -> str:
    """fixloop verdict → 记录 sig：裸 ``unfixable:`` 补 final_cat，再拼末轮非空
    payload（stagerun._fixloop_one / triage.legacy_records 同源两处）。"""
    sig = str(fv)
    if sig.startswith("unfixable:") and fcat and str(fcat) not in sig:
        sig = f"{sig}:{fcat}"
    if fpay:
        sig = f"{sig}:{fpay}"
    return sig


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


# ---------------------------------------------------------------- compile
def judge_dict(res, *, expect_cjk: bool) -> dict:
    """CompileResult → {compile, verdict, status}——``texlate.e2e._compile_judge``
    同形状（bench 侧复刻点收敛：e2e_real/e2e_mock/stagerun 共用）。"""
    from texlate.compile.judge import judge

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
            "cjk_chars": v.cjk_chars,
            "missing_chars": v.missing_chars,
            "warnings_hit": v.warnings_hit,
        },
        "status": v.status,
    }


_RE_MISSING_FILE = re.compile(r"File `([^']+)' not found")
_RE_MISSING_CHAR = re.compile(r"missing_character[×x](\d+)")


def verdict_sig(verdict: dict, first_error: str | None = None) -> str:
    """compile verdict 块 → 聚类 sig（stagerun records 与 triage legacy 降级单源）。

    cat 以 ``verdict.category`` 为准——此时 ``verdict.payload`` 是同字段对配，
    直接拼。cat 模糊（None/clean/other）时退 reasons 头抠 cat；派生 cat 不拼
    ``verdict.payload``（它配的是原 cat，拼上即错配），missing_file /
    missing_character 走正则从 first_error/reasons 回补 payload。
    """
    vstatus = verdict.get("status")
    if vstatus in ("clean", None):
        return ""
    cat = verdict.get("category")
    reasons = [str(r).strip() for r in (verdict.get("reasons") or []) if str(r).strip()]
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
            m = _RE_MISSING_FILE.search(first_error or "")
            pay = m.group(1) if m else ""
        elif cat == "missing_character":
            m = _RE_MISSING_CHAR.search(" ".join(reasons))
            pay = f"x{m.group(1)}" if m else ""
    return f"{cat}:{pay or ''}".rstrip(":")
