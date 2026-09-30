r"""parsebench — ``texlate.latex`` 产品管线语料评测器 (docs/spec/benchmark.md §B1) 的 Spec v2 移植。

对 ``bench/corpus/manifest*.jsonl`` 框架内每篇湖格做逐 .tex 测量：
decode_tex + flatten_inputs + parse_file（产品路径）→ parse ok/error/ms、
chunk 字符 median/p90/max、6 族泄漏正则命中与逐条 examples、identity
往返三档（strict/normalized/diverged + first_diff + quick_ratio）、
fake-translation splice 残留（chunk_ph/protect_ph）与孤儿 chunk、
vtex_vs_src 展开足迹、bug1 ph_tail 探针、warn_kinds、unresolved_inputs；
论文级 roots/multi_doc/primary/roles(root|input_reached|orphan|no_root)/
路由标签{reject,xelatex,minted,non-utf8,no-hyperref}/non_utf8/flatten 覆盖。

两 stage（census 先例的 probe+eval 对）：

- ``pb_probe``  — 湖格分类 + extracted 枚举计量（**纯读零湖写**——catalog
  先分类再读盘，``empty`` 锚 dir 会伪装成可枚举空树）。ok=extracted 完整
  可读且已枚举；partial=raw_only / 已登记 empty_payload（合法残缺层
  终态永不重测——旧口径这批论文不在 extracted/ 扫描面，同义「不进
  files.jsonl」）；skip=cell 缺席/skeleton 锚（后续水化可救）；
  error=meta torn/读异常。
- ``pb_eval``   — needs pb_probe.ok；逐文件测量全量走 **per-paper
  subprocess worker**：thread executor 下 ``signal.signal`` 抛
  ValueError，而 30s/文件的 SIGALRM 超时是口径本体——worker 主线程内
  SIGALRM 合法，父侧 outer timeout = timeout_s×n_tex×2+300 兜底
  C 级悬挂（sre 检查点外的真死循环）。ok=全部文件测完（行级
  ok=False 的 parse fail 是测量结果不是 cell 失败）；clean=paper 零
  .tex；partial=批中断（worker 被杀/崩时 files.jsonl 已有残留行——
  行在=测成的旧续跑语义在 cell 内复刻）；fail=拓扑已产但零测量行；
  skip=两 stage 间 extracted 消失；error=worker 崩/输出不可读/零行被杀。

覆盖率口径换代（对拍差集显式锚记）：v1 flatten 可达集经
``flatten_mod._read_file`` monkeypatch 收集——thread executor 下并发互毒。
v2 改读 ``res.inputs``（parse_file 自己登记的 ``(vpos, resolved realpath)``
输入事件流，``isabs`` 过滤即本次展开实际拉入集）——**失 v1
``top_dir=pdir`` 论文顶层兜底一维**：parse_file 按 v1 ``parse_one`` 原样
不传 top_dir 以保测量口径，同一 res 的 inputs 即新 reach 口径；
``metrics.reach_source="res.inputs"`` 锚记换代面。resolved 项是
``Path.resolve()`` realpath——身份集比较一律 resolve() 对齐（symlink
父目录下 abspath 会错配成全 orphan）。

- **EPOCH**：forever-dedup 下「重测一代」的唯一结构杠杆——模块常量折进
  ``variant``（本 spec 无 arm/variant 业务轴），换代=改 EPOCH。旧
  ``--rerun``/``vtex_len`` 换代戳在 v2 无对应物（cli 无 --recode）；
  ``fp_input=blob_sha256|main_tex_sha256`` 接 byte-drift 的 stale 标记职责。
- **report 不是 stage**：files.jsonl/papers.json/summary.md 聚合（Wilson
  CI / cluster bootstrap B=2000 seed=20260915 / frame 加权三口径）归
  derive 分析动词读 eval_records+records 重建——needs 是 per-cell
  边表达不了全语料聚合。分母守恒：Σcells ``metrics.n_files`` ≡ 旧
  files.jsonl 行数；``metrics.tot.*`` 逐键与旧 ``aggregate()`` 同名
  同式，Σ 即旧 ``tot[*]``；terminal eval cell 数 ≡ papers.json 行数。
- **measure_error 纪律原样**：判定层异常是行级 flag 不判 parse fail；
  cell 仍按测成数定 status。
- ``prefetch=False``：测量 run 零湖写——probe/eval 都以 ``is_complete``
  先闸，complete 格 ``src_path`` 走 hydrate fast-path 永不触发水化写。
- **item params 带 manifest 全字段**（stratum_cell/cluster_id/yymm/era/
  archive/cat_group/layer/channel/n_tex/n_files/bytes/mech_tags）——derive
  verb 加权/簇 bootstrap 重建原料；未声明 Param 故不进 fp（``cell_fp``
  只数 spec.params 声明位）。
"""

from __future__ import annotations

import difflib
import json
import math
import os
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
import traceback
from pathlib import Path

# worker 裸跑 ``python specs/x.py --worker`` 时 bench/py 不在
# sys.path——先立起才够得着 specs.*（load_spec 径下幂等）。
_BENCH_PY = str(Path(__file__).resolve().parents[1])
if _BENCH_PY not in sys.path:
    sys.path.insert(0, _BENCH_PY)

from kernel import lake, paths
from kernel.spec import EVAL_LAYERS, SC_OK_PARTIAL, Param, Spec, Stage

from specs import _bootstrap

_bootstrap.ensure()

from specs import _benchlite as benchlib
from specs import _select as _sel  # run 期收窄单源（ids/layers/only/n 管道）
from specs._leak import LEAK_PATTERNS
from texlate.latex import (
    flatten_inputs,
    parse_file,
    reconstruct,
    validate_result,
)
from texlate.textutil import decode_tex

ROOT = Path(__file__).resolve().parents[3]
CORPUS = Path(os.environ.get("TEXLATE_CORPUS", str(ROOT / "bench/corpus")))

#: 测量届别——折进 variant；想全量重测一代（产品码换代后）就改它，
#: forever-dedup 按新 cell 键自然放行。
EPOCH = "v1"

TIMEOUT_S = 30


class ParseTimeout(Exception):
    """SIGALRM 触发的解析超时——只在 worker 主线程合法（thread executor
    下 ``signal.signal`` 本身即 ValueError，这就是 subprocess 存在的理由）。"""


def _alarm(signum, frame):
    raise ParseTimeout


# ---------------------------------------------------------------- 工具


def is_non_utf8(path: Path) -> bool:
    """含 0x80+ 字节且 UTF-8 decode 失败 → 非 UTF-8."""
    b = path.read_bytes()
    if not any(x > 0x7F for x in b):
        return False
    try:
        b.decode("utf-8")
    except UnicodeDecodeError:
        return True
    return False


DOCCLASS_RX = re.compile(
    r"\\(documentclass|documentstyle)\s*(?:\[([^\]]*)\])?\s*\{([^}]*)\}",
    re.DOTALL,
)


def find_roots(tex_files: list[Path]) -> list[dict]:
    """剥注释后含 \\documentclass/\\documentstyle 的文件 → 根."""
    roots = []
    for p in sorted(tex_files):
        try:
            tex = decode_tex(p.read_bytes())
        except OSError:
            continue
        m = DOCCLASS_RX.search(benchlib.strip_comments(tex))
        if m:
            roots.append(
                {
                    "file": p,
                    "cmd": m.group(1),
                    "class": m.group(3).strip(),
                    # 选项内可穿插注释剥除后残留的换行 (2308.07483) → 归一化
                    "options": re.sub(r"\s+", " ", m.group(2) or "").strip(),
                }
            )
    return roots


def percentile(sorted_vals: list[int], q: float) -> int | None:
    """最近秩分位: idx=ceil(q*n)-1."""
    if not sorted_vals:
        return None
    return sorted_vals[max(0, math.ceil(q * len(sorted_vals)) - 1)]


PH_TOKEN_RX = re.compile(r"\[\[[A-Z_]+_\d+\]\]")


def ph_tail_risk(res) -> int:
    r"""BUG1 回归计数 (docs/spec/latex-pipeline.md): 占位符 body 以 `\letters` 结尾且其后继字符
    是字母 → 展开后命令吞掉后继字母, token 合并. 扫描域 = protected_tex +
    ph bodies + chunk contents (嵌套占位符的全部可见位置)."""
    blob = (
        res.protected_tex
        + "\n"
        + "\n".join(res.ph_map.values())
        + "\n"
        + "\n".join(c.content for c in res.chunks)
    )
    n = 0
    for m in PH_TOKEN_RX.finditer(blob):
        body = res.ph_map.get(m.group(0), "")
        if re.search(r"\\[a-zA-Z]+$", body) and blob[m.end() : m.end() + 1].isalpha():
            n += 1
    return n


# ---------------------------------------------------------------- 判定 (docs/spec/corpus.md 口径, 产品 API 版)


def parse_one(path: Path, timeout_s: int) -> dict:
    """api.parse_file（产品路径）+ SIGALRM 超时——**仅 worker 主线程可跑**。

    gullet 自解析 \\input 内联——vtex = 展开机产出；``flat`` 仍由
    flatten_inputs 算出供 vtex_vs_src 对照（展开足迹 = vtex 与 flatten
    输出的差异）。返回 {ok,res,flat,ms}|{ok,error,ms}.
    """
    t0 = time.perf_counter()
    signal.signal(signal.SIGALRM, _alarm)
    signal.alarm(timeout_s)
    try:
        orig = decode_tex(path.read_bytes())
        flat = flatten_inputs(orig, str(path.parent), str(path.parent))
        res = parse_file(str(path))
        ms_ = (time.perf_counter() - t0) * 1000
        return {"ok": True, "res": res, "flat": flat, "ms": round(ms_, 1)}
    except ParseTimeout:
        return {"ok": False, "error": f"Timeout(>{timeout_s}s)", "ms": timeout_s * 1000}
    except Exception as e:
        ms_ = (time.perf_counter() - t0) * 1000
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "ms": round(ms_, 1)}
    finally:
        signal.alarm(0)


def scan_chunks(res) -> dict:
    """泄漏判据 (docs/spec/corpus.md): 可译 chunk 命中六组正则任一 → 记 hit."""
    per_chunk = []
    hits = dict.fromkeys(LEAK_PATTERNS, 0)
    leaked = 0
    for c in res.chunks:
        found = [name for name, rx in LEAK_PATTERNS.items() if rx.search(c.content)]
        if found:
            leaked += 1
            for f in found:
                hits[f] += 1
            per_chunk.append(
                {"context": c.context, "leaks": found, "snippet": c.content[:120]}
            )
    return {
        "n_translatable_chunks": len(res.chunks),
        "n_leaked": leaked,
        "hits": hits,
        "examples": per_chunk[:5],
    }


def orphan_chunk_ids(res) -> int:
    """chunk 的占位符在任何可及位置都见不到 → 内容被静默丢弃."""
    blob = (
        res.protected_tex
        + "\n"
        + "\n".join(res.ph_map.values())
        + "\n"
        + "\n".join(c.content for c in res.chunks)
    )
    orphans = 0
    for c in res.chunks:
        if f"[[CHUNK_{c.id}]]" not in blob:
            orphans += 1
    return orphans


def classify_recon(orig: str, recon: str) -> tuple[str, float, int]:
    """identity 三档 (docs/spec/corpus.md): strict 逐字节 / normalized 仅空白 / diverged."""
    if orig == recon:
        return "strict", 1.0, -1

    def norm(s):
        return re.sub(r"\s+", " ", s).strip()

    if norm(orig) == norm(recon):
        return "normalized", 1.0, -1
    i = 0
    n = min(len(orig), len(recon))
    while i < n and orig[i] == recon[i]:
        i += 1
    ratio = difflib.SequenceMatcher(None, orig, recon).quick_ratio()
    return "diverged", round(ratio, 4), i


def fake_translation(chunk, idx: int) -> str:
    """占位译文: 保留全部内嵌占位符 (契约面), 正文替换为全角标记."""
    keep = re.findall(r"\[\[[A-Z_]+_\d+\]\]", chunk.content)
    return f"【假译文{idx}】" + "".join(keep)


def rebuild_metrics(res) -> dict:
    """identity 重建 + fake-translation splice 残留 + 孤儿 chunk (docs/spec/corpus.md)."""
    recon_identity = reconstruct(res)
    translated = {c.id: fake_translation(c, i) for i, c in enumerate(res.chunks)}
    recon_fake = reconstruct(res, translated)
    residue_chunk = len(re.findall(r"\[\[CHUNK_\d+\]\]", recon_fake))
    residue_prot = len(re.findall(r"\[\[[A-Z_]+_\d+\]\]", recon_fake))
    return {
        "recon_identity": recon_identity,
        "recon_fake": recon_fake,
        "residue_chunk_ph": residue_chunk,
        "residue_protect_ph": residue_prot,
        "n_orphan_chunks": orphan_chunk_ids(res),
    }


# ---------------------------------------------------------------- 路由标签

RX_EPS_PS = re.compile(
    r"\.eps\b|pstricks|\\begin\{pspicture\}|"
    r"\\usepackage(?:\[[^\]]*\])?\{pst[-a-z]*",
    re.IGNORECASE,
)
RX_MINTED = re.compile(
    r"\\begin\{minted\}|\\inputminted|\\mint(?:inline)?\b|"
    r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*minted"
)
RX_HYPERREF = re.compile(
    r"\\(?:usepackage|RequirePackage)(?:\[[^\]]*\])?\{[^}]*hyperref"
)


def paper_tags(roots: list[dict], stripped_blob: str, non_utf8: list) -> list[str]:
    tags = []
    if any(r["cmd"] == "documentstyle" for r in roots):
        tags.append("reject")  # LaTeX 2.09 \documentstyle
    if RX_EPS_PS.search(stripped_blob):
        tags.append("xelatex")  # .eps/pstricks → 非 pdflatex 路由
    if RX_MINTED.search(stripped_blob):
        tags.append("minted")  # 需 -shell-escape
    if non_utf8:
        tags.append("non-utf8")
    if not RX_HYPERREF.search(stripped_blob):
        tags.append("no-hyperref")
    return tags


# ---------------------------------------------------------------- 逐文件评测


def is_tex(p: Path) -> bool:
    """大小写不敏感 .tex 判定——野语料存在 .TEX 古早文件
    (corpus 实测: 0707.2108/pmeyerxi.TEX, 0806.0433/*.TEX)."""
    return p.is_file() and p.suffix.lower() == ".tex"


def rglob_tex(d: Path) -> list[Path]:
    return [p for p in d.rglob("*") if is_tex(p)]


def file_metrics(
    path: Path,
    rel: str,
    paper: str,
    role: str,
    non_utf8: bool,
    timeout_s: int,
    *,
    cached: dict | None = None,
) -> dict:
    """单文件评测全字段——``cached`` 复用拓扑段的 root 解析结果（同一次
    parse 不跑两遍；wall_ms 即该次计时）。"""
    entry = {
        "file": rel,
        "paper_id": paper,
        "role": role,  # root / input_reached / orphan / no_root
        "size": path.stat().st_size,
        "non_utf8": non_utf8,
    }
    r = cached if cached is not None else parse_one(path, timeout_s)
    entry["ok"] = r["ok"]
    entry["wall_ms"] = r["ms"]
    if not r["ok"]:
        entry["error"] = r["error"]
        entry["vtex_len"] = None  # 旧 schema 戳字段随行保留（行级口径锚）
        return entry

    res = r["res"]
    entry["n_chunks"] = len(res.chunks)
    entry["n_placeholders"] = len(res.ph_map)
    entry["vtex_len"] = len(res.vtex)

    try:
        lens = sorted(len(c.content) for c in res.chunks)
        entry["chunk_chars_median"] = statistics.median(lens) if lens else None
        entry["chunk_chars_p90"] = percentile(lens, 0.9)
        entry["chunk_chars_max"] = lens[-1] if lens else None
        entry["_lens"] = lens  # 聚合用, 随行落盘（derive 重组分位保真）

        # scan/validate warnings 分类计数 (泄漏类 bug 第一手线索)
        wk: dict[str, int] = {}
        for w in res.warnings:
            wk[w.kind] = wk.get(w.kind, 0) + 1
        for w in validate_result(res):
            wk[w.kind] = wk.get(w.kind, 0) + 1
        entry["warn_kinds"] = wk
        # res.inputs 混合语义: resolved 记 realpath, 漏网记原始名——isabs 过滤
        entry["unresolved_inputs"] = [
            name for _pos, name in res.inputs if not os.path.isabs(name)
        ]

        lk = scan_chunks(res)  # 6 组正则 (docs/spec/corpus.md), chunk 命中任一即泄漏
        entry["leak"] = {
            "n_translatable": lk["n_translatable_chunks"],
            "n_leaked": lk["n_leaked"],
            "rate": (
                round(lk["n_leaked"] / lk["n_translatable_chunks"], 4)
                if lk["n_translatable_chunks"]
                else None
            ),
            "hits": {k: v for k, v in lk["hits"].items() if v},
            # 逐条归因素材 (≤5/file): context/hits/snippet
            "examples": lk["examples"],
        }
        entry["leak_hits"] = sorted(entry["leak"]["hits"])

        rb = rebuild_metrics(res)  # identity + fake-translation 重建
        # recon 重建的是 res.vtex（展开后虚拟文本）→ 对比基准同侧
        status, ratio, first_diff = classify_recon(res.vtex, rb["recon_identity"])
        entry["identity"] = status
        entry["recon"] = {
            "quick_ratio": ratio,
            "first_diff_at": first_diff,
        }
        # 展开足迹: vtex vs 展平源 (strict = 展开机对本文件无净改动)
        entry["vtex_vs_src"] = classify_recon(r["flat"], res.vtex)[0]
        entry["fake"] = {
            "residue_chunk_ph": rb["residue_chunk_ph"],
            "residue_protect_ph": rb["residue_protect_ph"],
            "n_orphan_chunks": rb["n_orphan_chunks"],
        }
        entry["bug1_ph_tail"] = ph_tail_risk(res)
    except Exception as exc:
        # 判定层异常不判 parse 失败 (api.parse_file 已返回), 单列桶归因——
        # 统计分母用 measured=ok 且 measure_error 缺席的文件
        entry["measure_error"] = f"{type(exc).__name__}: {exc}"
    return entry


# ---------------------------------------------------------------- worker（per-paper subprocess）


def _topology(
    src: Path, tex_files: list[Path], paper_id: str, timeout_s: int
) -> tuple[dict, dict, dict, set]:
    """analyze_paper v2：roots + reach(res.inputs 口径) + roles + 路由标签。

    返回 (paper_dict, parsed_cache, roles, non_utf8_realpaths)。
    ``parsed_cache`` = {realpath: parse_one 结果}——root 的解析结果直接喂
    file loop 复用（同一次 parse 不跑两遍）。身份集一律 ``Path.resolve()``
    realpath——``res.inputs`` 的 resolved 项就是 realpath，abspath 在
    symlink 父目录下会错配成全 orphan。
    """
    rpaths = {p: str(p.resolve()) for p in tex_files}
    all_files = [p for p in src.rglob("*") if p.is_file()]
    non_utf8_rp = {rpaths[p] for p in tex_files if is_non_utf8(p)}

    roots = find_roots(tex_files)
    stripped_blob = "\n".join(
        benchlib.strip_comments(decode_tex(p.read_bytes())) for p in tex_files
    )

    # reach = 各根 parse 的 res.inputs resolved 集并集 (multi_doc 并集口径)；
    # 根 parse 崩 → 该根只贡献自身（v1 flatten_reach 吞异常同义）。
    reach_by_root: dict[str, set[str]] = {}
    parsed: dict[str, dict] = {}
    covered: set[str] = set()
    for r in roots:
        rp = str(Path(r["file"]).resolve())
        pr = parse_one(r["file"], timeout_s)
        parsed[rp] = pr
        reach = {rp}
        if pr.get("ok"):
            for _pos, name in pr["res"].inputs:
                if os.path.isabs(name):
                    reach.add(name)
        reach_by_root[rp] = reach
        covered |= reach

    primary = None
    if roots:
        # 主文件 = reach 触及最多的根 (multi_doc 的代表), 平手取路径短者
        primary = max(
            roots,
            key=lambda r: (
                len(reach_by_root[str(Path(r["file"]).resolve())]),
                -len(str(r["file"])),
            ),
        )["file"]

    roles: dict[str, str] = {}
    for p in tex_files:
        rel = p.relative_to(src).as_posix()
        rp = rpaths[p]
        if not roots:
            role = "no_root"
        elif rp in reach_by_root:
            role = "root"
        elif rp in covered:
            role = "input_reached"
        else:
            role = "orphan"
        roles[rel] = role

    paper = {
        "id": paper_id,
        "n_tex": len(tex_files),
        "n_files": len(all_files),
        "tex_bytes": sum(p.stat().st_size for p in tex_files),
        "total_bytes": sum(p.stat().st_size for p in all_files),
        "roots": [
            {
                "file": str(r["file"].relative_to(src)),
                "cmd": r["cmd"],
                "class": r["class"],
                "options": r["options"],
            }
            for r in roots
        ],
        "multi_doc": len(roots) > 1,
        "rootless": not roots,
        "primary_root": str(primary.relative_to(src)) if primary else None,
        "docclass": roots[0]["class"] if roots else None,
        "docclass_options": roots[0]["options"] if roots else None,
        "non_utf8_files": [
            p.relative_to(src).as_posix() for p in tex_files if rpaths[p] in non_utf8_rp
        ],
        "tags": paper_tags(roots, stripped_blob, sorted(non_utf8_rp)),
        "orphan_tex": [
            p.relative_to(src).as_posix()
            for p in tex_files
            if roots and rpaths[p] not in covered
        ],
        "roles": roles,
        "covered_n": len(covered),
        "reach_source": "res.inputs",
    }
    return paper, parsed, roles, non_utf8_rp


def _worker_run(src: Path, wd: Path, paper_id: str, timeout_s: int) -> int:
    """子进程测量体：paper.json 先行（拓扑件在 kill 下幸存），files.jsonl
    逐行 flush（被杀后残留行仍是真账——cell 内复刻旧「行在=测成」语义）。"""
    tex_files = sorted(rglob_tex(src))
    paper, parsed, roles, non_utf8_rp = _topology(src, tex_files, paper_id, timeout_s)
    (wd / "paper.json").write_text(
        json.dumps(paper, ensure_ascii=False), encoding="utf-8"
    )
    with (wd / "files.jsonl").open("w", encoding="utf-8") as fh:
        for p in tex_files:
            rel = p.relative_to(src).as_posix()
            rp = str(p.resolve())
            e = file_metrics(
                p,
                rel,
                paper_id,
                roles[rel],
                rp in non_utf8_rp,
                timeout_s,
                cached=parsed.get(rp),
            )
            benchlib.write_jsonl(fh, e)
            fh.flush()
    return 0


def _worker_cli() -> int:
    """``--worker <srcdir> <workdir> <paper_id> <timeout_s>`` 入口。"""
    if len(sys.argv) != 6 or sys.argv[1] != "--worker":
        print(
            "usage: parsebench.py --worker <srcdir> <workdir> <paper_id> <timeout_s>",
            file=sys.stderr,
        )
        return 2
    try:
        return _worker_run(
            Path(sys.argv[2]),
            Path(sys.argv[3]),
            sys.argv[4],
            int(sys.argv[5]),
        )
    except Exception:
        traceback.print_exc()
        return 1


# ---------------------------------------------------------------- items/select


def _corpus_rows() -> list[dict]:
    """manifest*.jsonl 全行（eval 层剔除 + 同 id 首见胜）→ item 源。

    行字段：id/layer/variant=EPOCH/fp_input=blob|main_tex sha 拼 +
    params={manifest 加权/归因全字段}（未声明 Param 不进 fp——cell_fp
    只数 spec.params 声明位）。
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
            sha = "|".join(
                x for x in (row.get("blob_sha256"), row.get("main_tex_sha256")) if x
            )
            rows.append(
                {
                    "id": str(pid),
                    "layer": row.get("layer"),
                    "variant": EPOCH,
                    "fp_input": sha or None,
                    "params": {
                        k: row.get(k)
                        for k in (
                            "stratum_cell",
                            "cluster_id",
                            "yymm",
                            "era",
                            "archive",
                            "cat_group",
                            "layer",
                            "channel",
                            "n_tex",
                            "n_files",
                            "bytes",
                            "mech_tags",
                        )
                    },
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
    """--n 抽样池谓词：**extracted 字节在场**（旧式「盘上可扫论文」同义——
    catalog 标 hydrated/pinned，或未登记但盘上完整）。raw_only 不在池：
    probe 判 partial 终态不可测，抽中即浪费样本位。"""
    res = _sel.canon_res(item["id"])
    if not res.ok or not res.idc:
        return False
    st = _catalog().state(res.idc)
    if st in ("hydrated", "pinned"):
        return True
    if st in ("failed", "empty", "raw_only", "skeleton", "hydrating", "evicted"):
        return False
    return lake.is_complete(res.idc)


def _sample_ids(layers: set[str], needle: str, n: int, seed: int) -> set[str]:
    """分层不区分地 seeded 抽 n 个 canon id（soak 同式 sorted-pool）。"""
    pool = []
    for it in _items():
        if layers and str(it.get("layer") or "") not in layers:
            continue
        res = _sel.canon_res(it["id"])
        idc = res.idc if res.ok and res.idc else str(it["id"])
        if needle and needle not in idc:
            continue
        if not _sampleable(it):
            continue
        if res.ok and res.idc:
            pool.append(res.idc)
    pool = sorted(set(pool))
    return _sel.seeded(pool, n, seed)


def _n_sample(ctx: _sel.Ctx) -> bool:
    return ctx.idc in _sample_ids(ctx.layers, ctx.needle, ctx.n, ctx.seed)


def _select(item: dict, rp: dict) -> bool:
    """G1 plan-filter：--ids 直选（canon 双拼写归一，bypass layers）→
    --layers（缺省 core）→ --only canon 子串 → --n/--seed 可测格抽样。"""
    return _sel.select(
        item, rp, ids="decisive", layers="core", only="canon", sample=_n_sample
    )


# ---------------------------------------------------------------- stage fns


def _gate(
    status: str, code: str, cat: str, payload, metrics: dict | None = None
) -> dict:
    """status + 单条 errors + 可选 metrics——sig 由内核 errors[0]
    cat:pay 自动合成（errors[].cat 是自由归因标签非事件 cat，非白名单
    词安全；终态 cat 只来自内核异常映射，这里恒为 None）。"""
    out = {
        "status": status,
        "code": code,
        "errors": [{"code": code, "cat": cat, "payload": payload}],
    }
    if metrics:
        out["metrics"] = metrics
    return out


def _probe(ctx) -> dict:
    """湖格分类 + extracted 枚举计量（纯读零湖写——catalog 状态先分类）。

    ok 的 metrics 除枚举计数外带**免 parse 拓扑**（roots/docclass/multi_doc/
    tags/non_utf8）——roles/primary/orphan_tex 要 parse 才知道，归
    pb_eval 的 worker 域（dossier 的 roles 落点位随之从 probe 挪到
    eval，文件头已注记）。
    """
    cell = lake.cell_dir(ctx.idc)
    st = _catalog().state(ctx.idc)
    metrics: dict = {
        "catalog": st,
        "item": dict(ctx.cell.get("params") or {}),
    }
    if not cell.is_dir():
        return _gate("skip", "absent", "probe", ctx.idc, metrics)
    meta_path = cell / "meta.json"
    has_raw = (cell / "raw").exists()
    has_ext = (cell / "extracted").is_dir()
    if not meta_path.exists() and not has_raw and not has_ext:
        # 空锚 dir——register 为 skeleton 撒的种子：种子不是损坏格。
        return _gate("skip", "skeleton", "probe", "empty anchor dir", metrics)
    if has_raw and not has_ext:
        # raw tier only——合法残缺层终态（旧式这批不在 extracted/ 扫描面）。
        return _gate("partial", "raw_only", "probe", "raw tier only", metrics)
    if st == "empty":
        # catalog 已登记零载荷答案——durable 终态不反复试。
        return _gate(
            "partial", "empty_payload", "probe", "recorded zero-payload", metrics
        )
    if not lake.is_complete(ctx.idc):
        # 载荷在场但 torn（meta 缺/数不符/failed 残格）——可水化修。
        return _gate(
            "error", "torn", "probe", f"incomplete cell (catalog={st})", metrics
        )

    ext = cell / "extracted"
    if not ext.is_dir():
        ext = cell
    try:
        tex_files = sorted(rglob_tex(ext))
        all_files = [p for p in ext.rglob("*") if p.is_file()]
        roots = find_roots(tex_files)
        non_utf8 = [p for p in tex_files if is_non_utf8(p)]
        stripped = "\n".join(
            benchlib.strip_comments(decode_tex(p.read_bytes())) for p in tex_files
        )
        metrics.update(
            {
                "n_tex": len(tex_files),
                "n_files": len(all_files),
                "tex_bytes": sum(p.stat().st_size for p in tex_files),
                "total_bytes": sum(p.stat().st_size for p in all_files),
            }
        )
    except (OSError, UnicodeError) as e:
        return _gate("error", "read_fail", "probe", f"{type(e).__name__}: {e}", metrics)
    metrics.update(
        {
            "roots": [
                {
                    "file": str(r["file"].relative_to(ext)),
                    "cmd": r["cmd"],
                    "class": r["class"],
                    "options": r["options"],
                }
                for r in roots
            ],
            "multi_doc": len(roots) > 1,
            "rootless": not roots,
            "docclass": roots[0]["class"] if roots else None,
            "docclass_options": roots[0]["options"] if roots else None,
            "non_utf8_files": [str(p.relative_to(ext)) for p in sorted(non_utf8)],
            "tags": paper_tags(roots, stripped, non_utf8),
        }
    )
    return {"status": "ok", "metrics": metrics}


def _read_json(p: Path) -> dict | None:
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _read_rows(p: Path) -> list[dict]:
    """容忍截尾坏行的 JSONL 读入——worker 被杀时末行可半写。"""
    rows = []
    try:
        fh = p.open(encoding="utf-8", errors="replace")
    except OSError:
        return rows
    with fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue  # 截尾坏行——丢弃不毁账
            if isinstance(e, dict):
                rows.append(e)
    return rows


def _tot(rows: list[dict]) -> dict:
    """cell 级 ``aggregate()`` 同式小计——键名与旧 tot[*] 一一对应，
    derive verb Σ 即得语料合计（lens 不分摊：逐行 _lens 在 files[] 里，
    分位数由 derive 重组）。"""
    ok = [f for f in rows if f.get("ok")]
    meas = [f for f in ok if "measure_error" not in f]
    recon = {"strict": 0, "normalized": 0, "diverged": 0}
    chunks = leaked = 0
    res_c = res_p = orph = bug1 = 0
    hits: dict[str, int] = {}
    warn: dict[str, int] = {}
    for f in meas:
        ident = f.get("identity")
        if ident in recon:
            recon[ident] += 1
        lk = f["leak"]
        chunks += lk["n_translatable"]
        leaked += lk["n_leaked"]
        for k, v in lk["hits"].items():
            hits[k] = hits.get(k, 0) + v
        res_c += f["fake"]["residue_chunk_ph"]
        res_p += f["fake"]["residue_protect_ph"]
        orph += f["fake"]["n_orphan_chunks"]
        bug1 += f["bug1_ph_tail"]
    for f in rows:
        for k, v in (f.get("warn_kinds") or {}).items():
            warn[k] = warn.get(k, 0) + v
    return {
        "files": len(rows),
        "ok": len(ok),
        "error": len(rows) - len(ok),
        "measure_error": len(ok) - len(meas),
        "strict": recon["strict"],
        "normalized": recon["normalized"],
        "diverged": recon["diverged"],
        "chunks": chunks,
        "leaked_chunks": leaked,
        "hits": hits,
        "warn_kinds": warn,
        "residue_chunk_ph": res_c,
        "residue_protect_ph": res_p,
        "orphan_chunks": orph,
        "bug1_ph_tail": bug1,
    }


def _eval(ctx) -> dict:
    """逐文件测量 = per-paper subprocess worker。

    ``is_complete`` 闸在 ``src_path`` 前（complete 格 hydrate 恒
    fast-path——测量 run 全程零湖写）。worker 产物契约：
    ``paper.json``（拓扑先行）+ ``files.jsonl``（逐行 flush 残留即真账）。
    """
    metrics: dict = {}
    if not lake.is_complete(ctx.idc):
        return _gate(
            "skip",
            "lake_incomplete",
            "upstream",
            "cell incomplete between probe and eval",
            metrics,
        )
    src = ctx.src_path()
    if src is None:
        return _gate("skip", "no_src", "upstream", "src projection failed", metrics)
    try:
        # 盘上实数是 outer timeout 与 rows 比对的权威——upstream_rec 的
        # metrics 在跨 run blob 下只回 marker，靠它会缩死外层闸。
        n_tex_disk = len(rglob_tex(src))
    except OSError as e:
        return _gate("error", "enum_fail", "eval", f"{type(e).__name__}: {e}", metrics)
    wd = ctx.paper_dir() / "pb_eval"
    if wd.exists():
        shutil.rmtree(wd)
    wd.mkdir(parents=True)
    timeout_s = int(ctx.params.get("timeout_s") or TIMEOUT_S)
    outer = timeout_s * max(n_tex_disk, 1) * 2 + 300
    argv = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--worker",
        str(src),
        str(wd),
        ctx.idc,
        str(timeout_s),
    ]
    t0 = time.monotonic()
    killed = False
    rc: int | None = None
    err_tail = ""
    try:
        cp = subprocess.run(argv, capture_output=True, text=True, timeout=outer)
        rc = cp.returncode
        err_tail = (cp.stderr or "")[-600:]
    except subprocess.TimeoutExpired as e:
        killed = True
        err = e.stderr
        if isinstance(err, bytes):
            err = err.decode("utf-8", "replace")
        err_tail = (err or "")[-600:]
    dur = round(time.monotonic() - t0, 1)

    rows = _read_rows(wd / "files.jsonl")
    paper = _read_json(wd / "paper.json")
    n_tex = int((paper or {}).get("n_tex") or n_tex_disk)

    metrics.update(
        {
            "n_tex": n_tex,
            "n_files": len(rows),  # ≡ 旧 files.jsonl 行数贡献（分母守恒锚）
            "seconds": dur,
            "timeout_s": timeout_s,
            "outer_s": outer,
            "worker_rc": rc,
            "worker_killed": killed,
        }
    )
    if paper is not None:
        for k in (
            "roots",
            "multi_doc",
            "rootless",
            "primary_root",
            "docclass",
            "docclass_options",
            "non_utf8_files",
            "tags",
            "orphan_tex",
            "roles",
            "covered_n",
            "reach_source",
            "tex_bytes",
            "total_bytes",
        ):
            metrics[k] = paper.get(k)
        metrics["n_files_all"] = paper.get("n_files")

    if killed:
        # C 级悬挂兜底杀——有残留行即批中断 partial，零行即 error。
        status = "partial" if rows else "error"
        out = _gate(
            status,
            "worker_timeout",
            "timeout",
            f"killed at outer {outer}s (n_tex={n_tex})",
            metrics,
        )
    elif rc != 0 or paper is None:
        # worker 崩/输出不可读——残留行兜 partial；拓扑已产但零行兜
        # fail（「有 tex 零测量行」终态）；连拓扑都没有 = error。
        if rows:
            status = "partial"
        elif paper is not None:
            status = "fail"
        else:
            status = "error"
        out = _gate(
            status,
            "worker_crash",
            "worker_crash",
            f"rc={rc} {err_tail}".strip()[:400],
            metrics,
        )
    elif n_tex == 0:
        status = "clean"  # paper 零 .tex——census no_mtree→clean 同式
        out = {"status": status, "metrics": metrics}
    elif not rows:
        status = "fail"  # 有 tex 但零测量行产出
        out = _gate(status, "no_rows", "eval", f"n_tex={n_tex} but zero rows", metrics)
    elif len(rows) < n_tex:
        status = "partial"  # 批中断（worker 正常退但行数亏——截尾/写损）
        out = _gate(status, "rows_short", "eval", f"{len(rows)}/{n_tex} rows", metrics)
    else:
        status = "ok"
        out = {"status": status, "metrics": metrics}

    if rows:
        metrics["tot"] = _tot(rows)
        metrics["files"] = rows  # >4KB 自动 $blob offload 到 run derived/blobs
    return out


# ---------------------------------------------------------------- spec

spec = Spec(
    kind="parsebench",
    params={
        "n": Param(int, default=0),
        "seed": Param(int, default=42),
        "ids": Param(str, default="", fp=False),
        "layers": Param(str, default="core", fp=False),
        "only": Param(str, default="", fp=False),
        "timeout_s": Param(int, default=TIMEOUT_S, fp=True),  # 口径参数
    },
    items=_items,
    select=_select,
    freeze_plan=True,
    executor="thread",
    env_probes=["python"],
    code_deps=[
        "src/texlate/latex",
        "src/texlate/textutil",
        "bench/py/specs/_benchlite.py",
        "bench/py/specs/_leak.py",
    ],
    lake=True,
    prefetch=False,  # 测量 run 零湖写——is_complete 闸恒在 src_path 前
    eval=False,  # canon 门保留（spec.eval 的 raw-idc 直通是 mixed-id 重演面）
    same_id_serial=True,
    stages=[
        Stage(
            "pb_probe",
            _probe,
            status_class=SC_OK_PARTIAL,
        ),
        Stage(
            "pb_eval",
            _eval,
            needs=[("pb_probe", {"ok"})],
            eval=True,
            # 唯一字母表（ok/partial/clean/fail + 双 retriable）——不为单点造预设。
            status_class={
                "ok": "terminal",
                "partial": "terminal",
                "clean": "terminal",
                "fail": "terminal",
                "skip": "retriable",
                "error": "retriable",
            },
        ),
    ],
)

if __name__ == "__main__":
    raise SystemExit(_worker_cli())
