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
def iter_jsonl(path: Path):
    """逐行 yield dict；空行跳过，**不可解码行跳过**（append 账的 kill 截尾
    是常态——容忍坏行保住续跑）。"""
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


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


def done_keys(path: Path, key: str = "id") -> set:
    """records.jsonl 已落行的 key 集——续跑跳过谓词。"""
    return {str(r[key]) for r in iter_jsonl(path) if key in r}


def load_records(path: Path, key: str = "id") -> dict[str, dict]:
    """append 账 → {key: rec} 末行胜（rerun 重记同 id 自然覆盖）。"""
    out: dict[str, dict] = {}
    for r in iter_jsonl(path):
        if key in r:
            out[str(r[key])] = r
    return out


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
