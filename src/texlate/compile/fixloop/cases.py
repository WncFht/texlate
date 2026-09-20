"""cases — ``cases.jsonl`` 沉淀: 失败案例结构化落盘 → triage → 回放三门验证。

docs/spec/compile.md (L312-330) 的沉淀机制::

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

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.textutil import append_jsonl

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.compile.fixloop.engine import Engine, LlmHook, Ruleset, RunFn

__all__ = [
    "CaseSink",
    "ReplayResult",
    "load_cases",
    "proj_resolver",
    "replay_all",
    "replay_case",
    "stats_backfill",
    "triage",
    "xelatex_factory",
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
            # REJECT 决策面: gate/loop 相 REJECT 不进 actions 列——verdict
            # ``reject:<rid>`` 的结构化名单, 与 rules_fired 分工不重叠。
            "gate_fired": cell.get("gate_fired") or [],
            "decline_notes": cell.get("decline_notes") or [],
            "advisories": cell.get("advisories") or [],
            "log_excerpt": cell.get("log_excerpt") or "",
        }
        # 线程锁防同进程交错、flock 防跨进程截断——bench 并行/多 worker 可共享同一 cases.jsonl。
        with self._lock:
            append_jsonl(self.path, rec)
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


def replay_case(  # noqa: PLR0913 -- 驱动面穿透 (fixloop 开关面同构)
    case: dict[str, Any],
    proj: Path,
    engine: Engine | None = None,
    ruleset: Ruleset | None = None,
    *,
    engine_name: str | None = None,
    main_rel: str | None = None,
    runner: RunFn | None = None,
    case_sink: CaseSink | None = None,
    compile_timeout: float | None = None,
    llm_hook: LlmHook | None = None,
    engine_wrap: Callable[[Engine], Engine] | None = None,
    inject: Callable[[Path, str | None], None] | None = None,
    driver: Callable[[dict[str, Any], Path], dict[str, Any]] | None = None,
) -> ReplayResult:
    """门①: 用当前规则库重跑该 case 的工程, fail 格须被修到出 pdf。

    驱动面与 ``stage_fixloop`` 接线同构: ``runner``/``case_sink``/
    ``compile_timeout``/``llm_hook`` 直透 ``fixloop()``; ``engine_name``/
    ``main_rel`` 缺省各回落 case 记录的 engine/main——回放复现记账
    口径而非重新探测。``engine_wrap`` 是引擎包装钩 (ResProxy/NoSandbox
    类 ``Engine→Engine``); ``inject`` 在 fixloop 前对 ``(proj, 实效
    main_rel)`` 跑一次 (``prepare_chinese`` 式注入——重建树上重放 ctex
    的挂点)。``driver`` 是 cell 级全控驱动 ``(case, proj) -> cell``:
    给定时以上旋钮全归它自理 (engine 也可缺席), 供要 texmf runner/
    baseline 注入等完整接线的驱动方。
    """
    eff_main = main_rel or case.get("main")
    if driver is not None:
        cell = driver(case, Path(proj))
    else:
        if engine is None:
            msg = "replay_case: engine 与 driver 至少给一个"
            raise TypeError(msg)
        from texlate.compile.fixloop.engine import (  # noqa: PLC0415  # 循环依赖隔离
            fixloop,
        )

        eng = engine_wrap(engine) if engine_wrap is not None else engine
        if inject is not None:
            inject(Path(proj), eff_main)
        cell = fixloop(
            proj,
            eng,
            ruleset=ruleset,
            engine_name=engine_name or case.get("engine"),
            main_rel=eff_main,
            corpus_id=case.get("corpus"),
            cond=case.get("cond"),
            llm_hook=llm_hook,
            runner=runner,
            case_sink=case_sink,
            compile_timeout=compile_timeout,
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
    engine_factory: Callable[[dict[str, Any]], Engine] | None = None,
    ruleset: Ruleset | None = None,
    *,
    driver: Callable[[dict[str, Any], Path], dict[str, Any]] | None = None,
    **fixloop_kw: Any,  # noqa: ANN401 -- replay_case 旋钮透传, 键集由其签名定
) -> list[ReplayResult]:
    """批量回放 + 门②: 任何「曾 clean」的格不得被改脏。

    ``resolve_proj(case)`` 把 corpus id 映到工程目录 (None → 跳过该格;
    ``proj_resolver(root)`` 是规范实现); ``engine_factory(case)`` 按 case
    造引擎实例 (``xelatex_factory(...)`` 是规范实现)——``driver`` 给定时
    免 engine_factory, 每格直 ``driver(case, proj) -> cell``。
    ``**fixloop_kw`` 透传 ``replay_case`` 驱动面 (``engine_name``/
    ``main_rel``/``runner``/``case_sink``/``compile_timeout``/
    ``engine_wrap``/``inject`` 等)。
    """
    if driver is None and engine_factory is None:
        msg = "replay_all: engine_factory 与 driver 至少给一个"
        raise ValueError(msg)
    results: list[ReplayResult] = []
    pairs: list[tuple[dict[str, Any], ReplayResult]] = []
    for case in cases:
        proj = resolve_proj(case)
        if proj is None or not Path(proj).exists():
            continue
        eng = engine_factory(case) if engine_factory is not None else None
        res = replay_case(case, Path(proj), eng, ruleset, driver=driver, **fixloop_kw)
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


# ════════════════════════════════════════════════════════════════
# canonical 驱动件 — runbook「照抄 stage_fixloop 接线」的 src 侧落点
# ════════════════════════════════════════════════════════════════


def proj_resolver(root: Path | str) -> Callable[[dict[str, Any]], Path | None]:
    """Canonical ``resolve_proj``: ``case → <root>/<corpus>`` 工程目录。

    corpus id 混存 raw (``cat/id``)/canon/单层 safe (``cat--id``) 诸形——
    verbatim 先行, 两种替换形各探一次, 首个存在的目录胜出; 诸形皆无 →
    返回 verbatim 形 (缺席格由 ``replay_all`` 的 exists() 闸跳过, 语义不变)。
    """
    root_path = Path(root)

    def _resolve(case: dict[str, Any]) -> Path | None:
        corpus = str(case.get("corpus") or "")
        if not corpus:
            return None
        for name in dict.fromkeys(
            (corpus, corpus.replace("/", "--"), corpus.replace("--", "/"))
        ):
            cand = root_path / name
            if cand.is_dir():
                return cand
        return root_path / corpus

    return _resolve


def xelatex_factory(
    *,
    texmf_root: Path | str | None = None,
    repository: str | None = None,
    halt_on_error: bool = True,
) -> Callable[[dict[str, Any]], Engine]:
    """Canonical ``engine_factory``: 每 case 造一台 ``XelatexEngine``。

    ``texmf_root`` 给定时逐格独占 ``<texmf_root>/<safe corpus>`` usertree
    (并行回放 tlmgr install 不互踩); None → 引擎缺省树。binary/sandbox/
    filemap 等其余旋钮走 ``XelatexEngine`` 自身面, 不在此展开。
    """

    def _make(case: dict[str, Any]) -> Engine:
        from texlate.compile.engine import (  # noqa: PLC0415  # 引擎边界: 用到才付引擎栈导入
            XelatexEngine,
        )

        texmf = (
            Path(texmf_root) / str(case.get("corpus") or "unnamed").replace("/", "--")
            if texmf_root is not None
            else None
        )
        return XelatexEngine(
            halt_on_error=halt_on_error, texmfhome=texmf, repository=repository
        )

    return _make
