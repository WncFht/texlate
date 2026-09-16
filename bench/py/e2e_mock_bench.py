#!/usr/bin/env python3
r"""e2e mock bench — corpus39 全量 mock 翻译 → ctex 注入 → 双引擎编译基线（M0 出口判据）。

产品路径版（2026-09-15 起）：解析/翻译/注入/编译全走 ``texlate.*`` 正式实现
（texlate.e2e.{pipe_condition,base_condition}；翻译 = XlatPipeline(MockTranslator)
+ L0 校验器）。旧 miniscanner+BUG1–5 补丁链已退役——patch 全部进 texlate.latex。

每工程条件（attribution 设计来自 tmp/exp/e2e/pipeline.py）:
  base-xel : 原样复制 → xelatex（zh 失败时区分"原文就挂"vs"管线引入"）
  pipe-xel : normalize → mock 翻译 → prepare_chinese(ctex) → xelatex → judge
  pipe-tec : 同上 → tectonic
  base-tec : 原样复制 → tectonic（**仅当 pipe-tec 非 clean 时补跑**，归因用）
  pipeB-xel: pipe-xel + Mode B 幻觉破坏（~30% 块丢/造占位符 → 校验链须 100% 捕获）
  pipeC-xel: pipe-xel + Mode C 位置扰动（~10% 占位符挪位 → 量化 splice 鲁棒性）

路由先行：`route_project`（\documentstyle → reject；仍跑 base-xel 实证拒绝正确性）。
fault_chunks/leftover_ph 即管线 bug 信号（应零）。

用法:
  python3 bench/py/e2e_mock_bench.py [--only SUBSTR] [--conditions base-xel,...]
      [--limit N] [--timeout SEC] [--tag NAME]
产出: bench/results/e2emock-<tag>-<date>/{records.jsonl,results.json,matrix.md,summary.md}
工作区: bench/work_e2emock/<cond>/<safe_id>/（gitignored 重产物）
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

import benchlib

from texlate.compile.engine import engine_for, route_project
from texlate.compile.inject import InjectRejectError, find_main_tex, prepare_chinese
from texlate.compile.normalize import normalize_project
from texlate.e2e import base_condition, pipe_condition
from texlate.latex.api import parse_file
from texlate.latex.placeholder import PH_RX
from texlate.latex.reconstruct import reconstruct
from texlate.validate.l0 import validate_pair
from texlate.xlat.pipeline import ChunkIn, MockTranslator, XlatPipeline, chunk_to_in
from texlate.xlat.placeholders import decode_newlines, is_placeholder_only

CORPUS = ROOT / "bench/corpus"
WORK = ROOT / "bench/work_e2emock"
RESULTS_DIR_DEFAULT = "e2emock-corpus39"

# ---------------------------------------------------------------- Mode B/C
# docs/10 §B5: Mode B 幻觉 mock (译文丢/造占位符 → 校验链编译前 100% 捕获);
# Mode C 位置扰动 mock (随机挪 ~10% 占位符 → 量化 splice 鲁棒性)。
# 扰动决策 = f(段内容哈希) → 确定性可复现, 批/单块/阶梯重试同决策。

MODE_B_RATE = 30  # 每段 ~30% 注一次幻觉破坏
MODE_C_RATE = 10  # 每占位符 ~10% 挪位
_NUM_LINE_RX = re.compile(r"^(\[\d+\])\s?(.*)$", re.DOTALL)


def _h(*parts: str) -> int:
    return int.from_bytes(hashlib.blake2s("|".join(parts).encode()).digest()[:4], "big")


def _unwrap_seg(user: str) -> str:
    """单块/阶梯/corrector 调用面里恢复被译段原文.

    translate_fn 收到的是 encode_newlines 后文本 (retry.py ``ctx.encoded``),
    重试尾部拼 ``\\n\\n[previous_validation_error]\\n...``; corrector =
    ``[Original]\\n{original}\\n[Translation]...`` (original 是未编码原文)。
    """
    if user.startswith("[Original]\n"):
        return user[len("[Original]\n") :].split("\n[Translation]", 1)[0]
    return user.split("\n\n[previous_validation_error]", 1)[0].split(
        "\n\n[compile_error]", 1
    )[0]


def _canon(seg: str) -> str:
    """段原文归一: 编码形态剥回 \\n——ladder 各阶段 (encoded / corrector raw)
    对同块得到同一哈希输入, 破坏决策跨重试一致."""
    return decode_newlines(seg)


def _plan_b(seg: str) -> str | None:
    """Mode B: 该段是否注破坏 + 哪种 (丢占位符 / 造占位符)."""
    canon = _canon(seg)
    if is_placeholder_only(canon.strip()):
        return None  # 纯占位符块路由不走 translator, 无从注入
    h = _h("B", canon)
    if h % 100 >= MODE_B_RATE:
        return None
    if PH_RX.search(canon) and (h >> 8) & 1:
        return "drop_ph"
    return "fabricate_ph"


def _apply_b(out: str, seg: str, kind: str) -> tuple[str, str]:
    """对译文段执行破坏, 返回 (破坏后文本, 细节)."""
    canon = _canon(seg)
    if kind == "drop_ph":
        ms = list(PH_RX.finditer(out))
        if not ms:
            kind = "fabricate_ph"
        else:
            m = ms[_h("Bi", canon) % len(ms)]
            return out[: m.start()] + out[m.end() :], f"drop {m.group(0)}"
    # fabricate: 源 chunk 占位符编号是 0..k, 9xx 永不与真占位符碰撞
    tag = f"[[MATH_9{_h('Bt', canon) % 90 + 10}]]"
    pos = _h("Bp", canon) % (len(out) + 1)
    sp = out.find(" ", pos)
    pos = sp + 1 if sp >= 0 else len(out)
    return f"{out[:pos]}{tag}{out[pos:]}", f"fab {tag}@{pos}"


def _apply_c(out: str, seg: str) -> tuple[str, int]:
    """Mode C: 每占位符 ~10% 概率挪到段内随机字符位 (multiset 不变 → L0 静默).

    按 token 值定位 (chunk 内占位符名唯一); 插入点 = 不在任何占位符 span 内
    的随机字符边界——可落词中, 模拟真实幻觉错位。落回原位不计 moved。
    """
    canon = _canon(seg)
    ms = list(PH_RX.finditer(out))
    flagged = [
        m.group(0)
        for i, m in enumerate(ms)
        if _h("C", canon, str(i)) % 100 < MODE_C_RATE
    ]
    moved = 0
    for k, ph in enumerate(flagged):
        j = out.find(ph)
        if j < 0:
            continue
        out = out[:j] + out[j + len(ph) :]
        spans = [m.span() for m in PH_RX.finditer(out)]
        allowed = [
            p for p in range(len(out) + 1) if all(not a <= p < b for a, b in spans)
        ]
        if not allowed:
            out += ph
            continue
        pos = allowed[_h("Cp", canon, str(k)) % len(allowed)]
        out = out[:pos] + ph + out[pos:]
        moved += pos != j
    return out, moved


def _is_batch_user(lines_u: list[str]) -> bool:
    """与 MockTranslator 批判别同口径: 全部非空行都是 ``[n] `` 前缀."""
    return bool(lines_u) and all(_NUM_LINE_RX.match(ln) for ln in lines_u if ln.strip())


class SabotageTranslator(MockTranslator):
    """Mode B: mock 译文上叠加幻觉破坏 (丢/造占位符); events 逐次记账."""

    def __init__(self, **kw: object) -> None:
        super().__init__(**kw)
        self.events: list[dict] = []

    async def translate(self, *, user: str, response_format=None, **kw):
        raw = await super().translate(user=user, response_format=response_format, **kw)
        if response_format is not None:
            return raw
        lines_u, lines_o = user.split("\n"), raw.split("\n")
        if _is_batch_user(lines_u) and len(lines_u) == len(lines_o):
            for i, lu in enumerate(lines_u):
                mu = _NUM_LINE_RX.match(lu)
                if not mu:
                    continue
                seg = mu.group(2)
                kind = _plan_b(seg)
                if not kind:
                    continue
                mo = _NUM_LINE_RX.match(lines_o[i])
                body = mo.group(2) if mo else lines_o[i]
                new, detail = _apply_b(body, seg, kind)
                lines_o[i] = f"{mo.group(1)} {new}" if mo else new
                self.events.append({"seg": seg, "kind": kind, "detail": detail})
            return "\n".join(lines_o)
        seg = _unwrap_seg(user)
        kind = _plan_b(seg)
        if kind:
            raw, detail = _apply_b(raw, seg, kind)
            self.events.append({"seg": seg, "kind": kind, "detail": detail})
        return raw


class PerturbTranslator(MockTranslator):
    """Mode C: mock 译文上叠加占位符挪位 (multiset 保持 → 过 L0 后 splice 错位)."""

    def __init__(self, **kw: object) -> None:
        super().__init__(**kw)
        self.events: list[dict] = []

    async def translate(self, *, user: str, response_format=None, **kw):
        raw = await super().translate(user=user, response_format=response_format, **kw)
        if response_format is not None:
            return raw
        lines_u, lines_o = user.split("\n"), raw.split("\n")
        if _is_batch_user(lines_u) and len(lines_u) == len(lines_o):
            for i, lu in enumerate(lines_u):
                mu = _NUM_LINE_RX.match(lu)
                if not mu:
                    continue
                seg = mu.group(2)
                mo = _NUM_LINE_RX.match(lines_o[i])
                body = mo.group(2) if mo else lines_o[i]
                new, n_moved = _apply_c(body, seg)
                if n_moved:
                    lines_o[i] = f"{mo.group(1)} {new}" if mo else new
                    self.events.append({"seg": seg, "moved": n_moved})
            return "\n".join(lines_o)
        seg = _unwrap_seg(user)
        raw, n_moved = _apply_c(raw, seg)
        if n_moved:
            self.events.append({"seg": seg, "moved": n_moved})
        return raw


def _seg_of(r_source: str, seg: str) -> bool:
    """事件段 ↔ 块: 段可能是 encoded 全段/行切片 (batch+ladder) 或原文 (corrector)."""
    dec = decode_newlines(seg)
    return (
        r_source in (seg, dec)
        or (len(dec) > 8 and dec in r_source)
        or (len(seg) > 8 and seg in r_source)
    )


def translate_tree(root: Path, translator: MockTranslator) -> dict:
    """mock_translate_tree 同构: 换注入 translator + 带出逐块结果 (Mode B/C 归因).

    产品面走同一批 API (parse_file → chunk_to_in → XlatPipeline+L0 →
    reconstruct → 写回); fault 块不 splice (回退原文)。
    """
    scans: list[tuple[Path, object]] = []
    chunks: list[ChunkIn] = []
    fault_files: list[str] = []
    for f in sorted(root.rglob("*.tex")):
        try:
            res = parse_file(f, flatten=False)
        except Exception:
            fault_files.append(f.name)
            continue
        idx = len(scans)
        scans.append((f, res))
        chunks.extend(chunk_to_in(c, chunk_id=f"{idx}:{c.id}") for c in res.chunks)

    pipe = XlatPipeline(
        translator,
        validator=lambda s, z: validate_pair(s, z).feedback(),
    )
    results = asyncio.run(pipe.run(chunks))
    by_file: dict[int, dict[int, str]] = {}
    n_fault = 0
    for r in results:
        fidx, cid = (int(x) for x in r.chunk_id.split(":", 1))
        if r.status == "ok":
            by_file.setdefault(fidx, {})[cid] = r.translation
        else:
            n_fault += 1

    n_files = 0
    n_leftover = 0
    for idx, (f, res) in enumerate(scans):
        trans = by_file.get(idx)
        if not trans:
            continue
        zh = reconstruct(res, trans)
        f.write_text(zh, encoding="utf-8")
        n_files += 1
        n_leftover += len(PH_RX.findall(zh))
    return {
        "files": n_files,
        "chunks": len(chunks),
        "fault_chunks": n_fault,
        "fault_files": fault_files,
        "leftover_ph": n_leftover,
        "results": results,
    }


def _compile_judge(work: Path, main_rel: str, eng_name: str, timeout: float) -> dict:
    """e2e._compile_judge 同形状 (benchlib.judge_dict 单源, expect_cjk=True)."""
    kw: dict = {"halt_on_error": False} if eng_name == "xelatex" else {}
    res = engine_for(eng_name, **kw).compile(
        work, main_rel, timeout=timeout, sandbox=True
    )
    return benchlib.judge_dict(res, expect_cjk=True)


def pipe_mode_condition(
    work: Path, eng_name: str, main_rel: str, timeout: float, mode: str
) -> dict:
    """pipe_condition 变体: mock_translate_tree → translate_tree(Mode B/C translator).

    Mode B 逐块结局: caught (校验链拦下→原文回退) / recovered (阶梯修回干净)
    / escaped (校验放行且译文带破坏残留——真逃逸, 门槛 = 0)。
    Mode C: 挪位天然过 L0, 记账 moved + 落到 splice 的块数 (spliced)。
    """
    rec: dict = {"engine": eng_name}
    rec["normalize"] = normalize_project(work, eng_name, main_rel)
    tr = SabotageTranslator() if mode == "B" else PerturbTranslator()
    rec["translate"] = translate_tree(work, tr)
    # 事件归因 → 逐块结局
    results = rec["translate"].pop("results")
    src_ph = lambda s: sorted(PH_RX.findall(s))  # noqa: E731
    ledger: dict = {"events": len(tr.events), "sabotaged": 0, "moved": 0}
    if mode == "B":
        ledger.update({"caught": 0, "recovered": 0, "escaped": 0, "escaped_ids": []})
    else:
        ledger.update({"spliced": 0, "dropped": 0})
    for r in results:
        evs = [e for e in tr.events if _seg_of(r.source, e["seg"])]
        if not evs:
            continue
        ledger["sabotaged"] += 1
        ledger["moved"] += sum(e.get("moved", 0) for e in evs)
        if mode == "B":
            if r.status != "ok":
                ledger["caught"] += 1  # fault/skipped → 原文回退
            elif src_ph(r.translation) != src_ph(r.source):
                ledger["escaped"] += 1
                ledger["escaped_ids"].append(r.chunk_id)
            else:
                ledger["recovered"] += 1
        elif r.status == "ok":
            ledger["spliced"] += 1  # 挪位译文进了文档 → 编译判存活
        else:
            ledger["dropped"] += 1
    rec["sabotage"] = ledger
    try:
        rec["inject"] = prepare_chinese(work, main_rel)
    except InjectRejectError as e:
        rec["status"] = "reject"
        rec["reject_at"] = "inject"
        rec["verdict"] = {"status": "reject", "reasons": [e.reason]}
        return rec
    rec.update(_compile_judge(work, main_rel, eng_name, timeout))
    return rec


# ---------------------------------------------------------------- 条件执行
def run_condition(
    cond: str, src: Path, sid: str, main_rel: str, timeout: float
) -> dict:
    """单条件：复制 → (pipe/pipeB/pipeC: 管线变体 | base: 原样) → compile → judge。"""
    engine_name = "xelatex" if cond.endswith("xel") else "tectonic"
    dst = WORK / cond / sid
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


def list_projects() -> list[str]:
    """corpus39 叶目录：直接含 .tex 的顶层目，或 hep-th/math 下的二级目。"""
    out = []
    for p in sorted(CORPUS.iterdir()):
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


def run_project(rel: str, conditions: list[str], timeout: float) -> dict:
    src = CORPUS / rel
    sid = safe_id(rel)
    rec: dict = {"id": rel}
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
    }
    for cond in conditions:
        if cond == "base-tec":
            continue  # 条件性补跑——pipe-tec 非 clean 时再跑
        rec[cond] = run_condition(cond, src, sid, main_rel, timeout)
    if "base-tec" in conditions:
        pt = rec.get("pipe-tec", {}).get("verdict", {}).get("status")
        if pt is not None and pt != "clean":
            rec["base-tec"] = run_condition("base-tec", src, sid, main_rel, timeout)
    return rec


# ---------------------------------------------------------------- 报告
def _status(rec: dict, cond: str) -> str:
    c = rec.get(cond)
    if c is None:
        return "·"
    return c.get("verdict", {}).get("status", "?")


def write_reports(results: dict, out_dir: Path) -> None:
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
        cells = [_status(rec, c) for c in conds]
        route = rec.get("route", {})
        flag = "reject" if route.get("reject") else ""
        rows.append((rel, rec.get("main", "?"), flag, *cells))
    matrix = [
        "| 工程 | main | 路由 | " + " | ".join(conds) + " |",
        "| --- | --- | --- |" + " --- |" * len(conds),
    ]
    matrix.extend("| " + " | ".join(str(x) for x in r) + " |" for r in rows)
    (out_dir / "matrix.md").write_text("\n".join(matrix) + "\n", encoding="utf-8")

    lines = ["# e2e mock bench — corpus39", ""]
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
            "spliced": 0,
            "dropped": 0,
        }
        esc_ids: list[str] = []
        for _rel, c in recs:
            led = c.get("sabotage", {})
            for k in tot:
                tot[k] += led.get(k, 0)
            esc_ids.extend(led.get("escaped_ids", []))
        lines.append(f"## Mode {mode} 台账 ({cond})")
        if mode == "B":
            gate = "PASS" if tot["escaped"] == 0 else "FAIL"
            lines.append(
                f"- 注入破坏块 {tot['sabotaged']}（事件 {tot['events']}）→ "
                f"caught {tot['caught']} / recovered {tot['recovered']} / "
                f"**escaped {tot['escaped']}** — 门槛 escaped==0: **{gate}**"
            )
            if esc_ids:
                lines.append(f"- escaped chunk ids: {esc_ids}")
        else:
            statuses = [c.get("verdict", {}).get("status") for _r, c in recs]
            dist = {s: statuses.count(s) for s in sorted(set(statuses))}
            lines.append(
                f"- 挪位 {tot['moved']} 处 / 涉块 {tot['sabotaged']} → "
                f"进 splice {tot['spliced']} / 回退 {tot['dropped']}；"
                f"编译 verdict 分布 {dist}"
            )
            # 存活率: Mode A (pipe-xel 同 commit 基线) 出 pdf 的篇 → C 仍出 pdf
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
                cst = _status(results[rel], cond)
                if cst in ("clean", "partial"):
                    survived += 1
                else:
                    broke.append(rel)
            if base_pdf:
                lines.append(
                    f"- 存活率 vs pipe-xel 基线: {survived}/{base_pdf} 篇出 pdf"
                    + (f"（退化: {broke}）" if broke else "")
                )
        lines.append("")
    (out_dir / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, help="substring filter on project id")
    ap.add_argument("--conditions", default="base-xel,pipe-xel,pipe-tec,base-tec")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--timeout", type=float, default=240.0)
    ap.add_argument("--tag", default=RESULTS_DIR_DEFAULT)
    ap.add_argument("--date", default=str(datetime.now(UTC).date()))
    args = ap.parse_args()

    conditions = [c.strip() for c in args.conditions.split(",") if c.strip()]
    out_dir = ROOT / "bench/results" / f"{args.tag}-{args.date}"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "results.json"
    rec_path = out_dir / "records.jsonl"
    # records.jsonl 是 append 真账（行在=done，末行胜）；results.json 为
    # 兼容旧 run 目录的兜底种子 + 逐篇快照。
    results = (
        benchlib.load_records(rec_path)
        if rec_path.exists()
        else (json.loads(out_path.read_text()) if out_path.exists() else {})
    )

    projects = list_projects()
    for idx, rel in enumerate(projects):
        if args.only and args.only not in rel:
            continue
        if args.limit is not None and idx >= args.limit:
            break
        print(f"===== [{idx}/{len(projects)}] {rel} conds={conditions}", flush=True)
        rec = run_project(rel, conditions, args.timeout)
        if rel in results:
            results[rel].update(rec)
        else:
            results[rel] = rec
        benchlib.append_jsonl(rec_path, results[rel])
        out_path.write_text(json.dumps(results, ensure_ascii=False, indent=1))
        write_reports(results, out_dir)
        stat = {c: _status(rec, c) for c in conditions}
        print(f"  -> {stat}", flush=True)
    print(f"done -> {out_dir}", flush=True)


if __name__ == "__main__":
    main()
