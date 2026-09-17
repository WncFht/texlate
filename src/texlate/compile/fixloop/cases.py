"""cases — ``cases.jsonl`` 沉淀: 失败案例结构化落盘 → triage → 回放三门验证。

docs/08 §5.5 (L312-330) 的沉淀机制::

    每格跑完 → cases.jsonl {corpus, cond, engine, rounds[cat/pay/rule/result],
                            verdict, log_excerpt}
    verdict ∈ {unfixable, stuck, dirty_pdf} → triage queue
        → 三类补丁: a) taxonomy 新行  b) rules 新条目  c) filemap.overrides
    回放验证 (入库门槛):
      ① 本格重跑: 新规则必须把 fail 修到 pdf
      ② 全语料回归: 不得把任何 clean 格改脏 (no-regression gate)
      ③ status: proposed → active; fires/rescues 计数回填 stats
"""

from __future__ import annotations

import fcntl
import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.compile.fixloop.engine import Engine, Ruleset

__all__ = [
    "CaseSink",
    "ReplayResult",
    "load_cases",
    "replay_all",
    "replay_case",
    "stats_backfill",
    "triage",
]

# 进 triage 队列的 verdict (docs/08:319); max_rounds/no_errors_no_pdf 同为未救回
_TRIAGE_VERDICTS = (
    "unfixable:",
    "stuck",
    "dirty_pdf",
    "max_rounds",
    "no_errors_no_pdf",
)


class CaseSink:
    """``cases.jsonl`` 追加写入口 (每格一条)。"""

    def __init__(self, path: Path | str) -> None:
        """Jsonl 落点 (父目录写时自建)。"""
        self.path = Path(path)
        self._lock = threading.Lock()

    def record(
        self,
        cell: dict[str, Any],
        *,
        corpus_id: str | None = None,
        cond: str | None = None,
        engine: str | None = None,
    ) -> dict[str, Any]:
        """Cell → 结构化 case 记录并落盘 (jsonl 追加, utf-8)。"""
        rec = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "corpus": corpus_id or cell.get("project"),
            "cond": cond or cell.get("cond"),
            "engine": engine or cell.get("engine"),
            "main": cell.get("main"),
            "verdict": cell.get("verdict"),
            "final_pdf": cell.get("final_pdf"),
            "final_errors": cell.get("final_errors"),
            "started_fail": cell.get("started_fail"),
            "rounds": [
                {
                    "round": r.get("round"),
                    "cat": r.get("category"),
                    "pay": r.get("payload"),
                    "pdf": r.get("pdf"),
                    "n_errors": r.get("n_errors"),
                    "warnings": r.get("warnings") or [],
                }
                for r in cell.get("rounds") or []
            ],
            "actions": [
                {
                    "round": a.get("round"),
                    "rule": a.get("rule"),
                    "result": a.get("detail"),
                }
                for a in cell.get("actions") or []
            ],
            "installed": cell.get("installed") or [],
            # 「看见/拒修」面: actions/rules_fired 的互补——when 命中但
            # cond/applied 败阵的规则 (loop 相; precheck 败阵本就在 actions)。
            "rules_declined": cell.get("rules_declined") or [],
            "decline_notes": cell.get("decline_notes") or [],
            "advisories": cell.get("advisories") or [],
            "log_excerpt": cell.get("log_excerpt") or "",
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(rec, ensure_ascii=False) + "\n"
        # 线程锁防同进程交错、flock 防跨进程截断——bench 并行/多 worker 可共享同一 cases.jsonl。
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                f.write(line)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        return rec


def load_cases(path: Path | str) -> list[dict[str, Any]]:
    """读 cases.jsonl; 不存在 → []。"""
    p = Path(path)
    if not p.exists():
        return []
    return [
        json.loads(ln)
        for ln in p.read_text(encoding="utf-8").splitlines()
        if ln.strip()
    ]


def triage(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """过滤进 triage 队列的 case (verdict ∈ unfixable/stuck/dirty_pdf 等)。"""
    return [
        c
        for c in cases
        if any(str(c.get("verdict") or "").startswith(v) for v in _TRIAGE_VERDICTS)
    ]


# ════════════════════════════════════════════════════════════════
# 回放验证三门 (docs/08:324-327)
# ════════════════════════════════════════════════════════════════


@dataclass(slots=True)
class ReplayResult:
    """单格回放结果 + 门①②判定。"""

    corpus: str | None
    cond: str | None
    verdict_before: str | None
    verdict_after: str | None
    final_pdf: bool
    gate1_rescued: bool  # ① 本格重跑: started_fail 且终出 pdf
    floor_restored: bool = False  # 底板兜回过 = 树被打死只剩入口产物
    regressed: bool = False  # ② 曾 clean 的格被改脏 (batch 层回填)


def replay_case(
    case: dict[str, Any],
    proj: Path,
    engine: Engine,
    ruleset: Ruleset | None = None,
) -> ReplayResult:
    """门①: 用当前规则库重跑该 case 的工程, fail 格须被修到出 pdf。"""
    from texlate.compile.fixloop.engine import fixloop  # noqa: PLC0415  # 循环依赖隔离

    cell = fixloop(
        proj,
        engine,
        ruleset=ruleset,
        corpus_id=case.get("corpus"),
        cond=case.get("cond"),
    )
    return ReplayResult(
        corpus=case.get("corpus"),
        cond=case.get("cond"),
        verdict_before=case.get("verdict"),
        verdict_after=cell.get("verdict"),
        final_pdf=bool(cell.get("final_pdf")),
        gate1_rescued=bool(case.get("started_fail")) and bool(cell.get("final_pdf")),
        floor_restored=bool(cell.get("floor_restored")),
    )


def replay_all(
    cases: list[dict[str, Any]],
    resolve_proj: Callable[[dict[str, Any]], Path | None],
    engine_factory: Callable[[dict[str, Any]], Engine],
    ruleset: Ruleset | None = None,
) -> list[ReplayResult]:
    """批量回放 + 门②: 任何「曾 clean」的格不得被改脏。

    ``resolve_proj(case)`` 把 corpus id 映到工程目录 (None → 跳过该格);
    ``engine_factory(case)`` 按 case 的 engine 字段造引擎实例。
    """
    results: list[ReplayResult] = []
    pairs: list[tuple[dict[str, Any], ReplayResult]] = []
    for case in cases:
        proj = resolve_proj(case)
        if proj is None or not Path(proj).exists():
            continue
        res = replay_case(case, Path(proj), engine_factory(case), ruleset)
        results.append(res)
        pairs.append((case, res))
    for case, res in pairs:
        was_clean = case.get("verdict") in ("clean", "acceptable_pdf")
        res.regressed = was_clean and (
            res.verdict_after not in ("clean", "acceptable_pdf")
            # 底板兜回说明树被规则打死只剩入口快照——verdict 被兜住也算退化
            or res.floor_restored
        )
    return results


def stats_backfill(raw: dict[str, Any], cells: list[dict[str, Any]]) -> dict[str, Any]:
    """门③: fires/rescued_cells 计数回填 + ``proposed → active`` 建议。

    输入是 ``load_yaml()`` 出来的 rules dict (纯数据), 返回更新后的同构
    dict —— 不写盘 (子集解析器只读; 落 yaml 由人工/工具链完成)。
    规则: fires>0 且所在格有 rescued → status proposed → active。
    """
    fires: dict[str, int] = {}
    rescued: dict[str, set[tuple[str, str]]] = {}
    for cell in cells:
        # 双 schema: fixloop cell 用 "project", load_cases 记录用 "corpus"
        key = (
            str(cell.get("project") or cell.get("corpus")),
            str(cell.get("cond")),
        )
        for a in cell.get("actions") or []:
            rid = a.get("rule")
            if not rid:
                continue
            fires[rid] = fires.get(rid, 0) + 1
            if cell.get("final_pdf"):
                rescued.setdefault(rid, set()).add(key)
    for rule in raw.get("rules") or []:
        rid = rule.get("id")
        st = rule.setdefault("stats", {})
        st["fires"] = fires.get(rid, 0)
        st["rescued_cells"] = len(rescued.get(rid, ()))
        if st.get("status") == "proposed" and st["fires"] and st["rescued_cells"]:
            st["status_suggested"] = "active"  # 人工确认后才转正, 不自动改 status
    return raw
