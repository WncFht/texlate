"""修复臂共享低层件——``e2e`` 与 ``server.worker`` 双编排器的单源层。

refactor-audit-2026-09-17 ★1 收口：两臂各自保留编排（报告形状、事件、
回灌副作用不同），以下四件同型逻辑只在此维护一份：

- ``log_text_of``：``CompRes`` → 日志全文（``.log`` 非空优先、
  ``stdout_tail`` 兜底——tectonic 常无 .log；与 ``engine.parse_log``
  同口径：空文件/读失败一律退 tail，空 .log 直返空串会把只存在于
  stdout 的 missing-char 信号静默丢掉）
- ``ResProxy``：``Engine`` 透传代理，记末次 ``CompRes``（fixloop
  轮内重编的终判原料）
- ``fixloop_cell_parts``：fixloop cell → ``(逐轮摘要, setup 动作)``——
  ``rounds`` 与 ``actions`` 按 round 归并的共享机械
- ``run_fixloop`` / ``cross_engine_retry`` / ``VERDICT_RANK``：
  fixloop 调用包装与 dropped ``engine_flags`` 的 tectonic→xelatex
  跨引擎重试取优
"""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from texlate.compile.fixloop.engine import fixloop
from texlate.compile.judge import judge

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from pathlib import Path

    from texlate.compile.engine import CompRes, Engine
    from texlate.compile.fixloop.engine import LlmHook
    from texlate.compile.judge import Verdict

VERDICT_RANK = {"clean": 3, "partial": 2, "fail": 1, "reject": 0}


def log_text_of(res: CompRes) -> str:
    """``CompRes`` → log 全文（``.log`` 非空优先、``stdout_tail`` 兜底）。

    被杀编译会留 0 字节 ``.log``——``exists()`` 判据下空文件返空串会
    让 missing-char 等只存在于 stdout 的信号静默丢失；缺席/空文件/读
    失败一律退 ``stdout_tail``。
    """
    text = ""
    if res.log_path is not None:
        with suppress(OSError):
            text = res.log_path.read_text(encoding="utf-8", errors="replace")
    return text or res.stdout_tail or ""


class ResProxy:
    """``Engine`` 透传代理：转发 Protocol 面 + 记末次 ``CompRes``。

    ``__setattr__`` 透传到内层——fixloop ``_wire_engine`` 会给 tectonic
    注入 ``ctan_fetch`` callable，必须落到真引擎实例上；``_inner``/
    ``last`` 两键保留在代理自身（读侧经实例 attr 命中，不走转发）。
    """

    def __init__(self, inner: Engine) -> None:
        """包一层引擎。"""
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "last", None)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 -- 代理转发面天然 Any
        """未命中的 attr 转发到内层引擎。"""
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:  # noqa: ANN401 -- 同上
        """``_inner``/``last`` 写代理自身，其余写穿到内层引擎。"""
        if name in {"_inner", "last"}:
            object.__setattr__(self, name, value)
        else:
            setattr(self._inner, name, value)

    def compile(self, *args: Any, **kwargs: Any) -> CompRes:  # noqa: ANN401
        """转发 compile 并记录 CompRes（fixloop 每轮重编都过这里）。"""
        res: CompRes = self._inner.compile(*args, **kwargs)
        object.__setattr__(self, "last", res)
        return res


def fixloop_cell_parts(
    cell: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fixloop cell → ``(rounds 摘要行, setup 前置动作)``。

    ``actions`` 按 ``str(round)`` 归并（一轮可多条），取首条的
    rule/detail 作该轮代表；``round=0/-1`` 是 precheck/gate 动作单列
    ``setup``；salvage 轮的 action 键为 ``"salvage"``，须按
    ``r["salvage"]`` 标记对齐。
    """
    by_round: dict[str, list[dict[str, Any]]] = {}
    for a in cell.get("actions") or []:
        by_round.setdefault(str(a.get("round")), []).append(a)
    rounds = []
    for r in cell.get("rounds") or []:
        acts = by_round.get("salvage" if r.get("salvage") else str(r.get("round")), [])
        head = acts[0] if acts else {}
        rounds.append(
            {
                "round": r.get("round"),
                "cat": r.get("category"),
                "pay": r.get("payload"),
                "pdf": bool(r.get("pdf")),
                "n_errors": r.get("n_errors"),
                "rule": head.get("rule"),
                "result": head.get("detail"),
            }
        )
    setup = [
        {"rule": a.get("rule"), "result": a.get("detail")}
        for a in cell.get("actions") or []
        if a.get("round") in (0, -1)
    ]
    return rounds, setup


def run_fixloop(
    work: Path,
    engine: Engine,
    *,
    engine_name: str,
    llm_hook: LlmHook | None = None,
    compile_timeout: float | None = None,
    **kw: Any,  # noqa: ANN401 -- fixloop 开关面透传，键集由 fixloop 签名定
) -> tuple[dict[str, Any], CompRes | None]:
    """``ResProxy`` 包装 + ``fixloop()`` 调用 + 末次 ``CompRes`` 取回。

    ``**kw`` 透传 fixloop 的其余开关面（``ruleset``/``corpus_id``/
    ``cond``/``case_sink`` 等，worker 臂使用）。异常不吞——两臂各自
    决定兜底形态（e2e 产 error dict、worker 记日志返回原 res）。
    """
    proxy = ResProxy(engine)
    cell = fixloop(
        work,
        proxy,
        engine_name=engine_name,
        llm_hook=llm_hook,
        compile_timeout=compile_timeout,
        **kw,
    )
    return cell, proxy.last


@dataclass(slots=True)
class CrossRetry:
    """跨引擎重试结果：``adopted`` 表示 xelatex 复判严格更优被采用。"""

    res: CompRes
    verdict: Verdict
    info: dict[str, Any]
    adopted: bool


def cross_engine_retry(  # noqa: PLR0913 -- 开关面穿透两臂同一契约
    *,
    engine_name: str,
    route_engines: Iterable[str],
    current_status: str,
    work: Path,
    main_rel: str,
    timeout: float | None,
    flags: Sequence[str] | None,
    dropped: Sequence[str],
    expect_cjk: bool,
    make_engine: Callable[[], Engine],
) -> CrossRetry | None:
    """消费 dropped ``engine_flags``：tectonic→xelatex 重试 → ``CrossRetry``/None。

    触发条件（两臂同一契约）：有 dropped flag ∧ 当前引擎是 tectonic ∧
    ``xelatex`` 在 route 候选 ∧ 当前判定低于 clean。dropped 多为
    shell-escape 需求——tectonic 沙箱不收 → 换 xelatex 带全量请求 flag
    经 ``compile(flags=…)`` seam 重编，复判严格更优才 ``adopted``。

    ``make_engine`` 由调用侧注入（引擎构造旋钮两臂不同：e2e 沿主编译
    best-effort，worker 对齐 fixloop 轮内首错口径；测试面同缝）。
    """
    if not dropped or engine_name != "tectonic" or "xelatex" not in route_engines:
        return None
    if VERDICT_RANK.get(current_status, 0) >= VERDICT_RANK["clean"]:
        return None
    xres = make_engine().compile(
        work, main_rel, timeout=timeout, sandbox=True, flags=flags
    )
    xv = judge(xres, expect_cjk=expect_cjk, log_text=log_text_of(xres))
    info = {
        "engine": "xelatex",
        "status": xv.status,
        "reason": f"engine_flags {dropped} tectonic 不支持 → 换 xelatex",
    }
    return CrossRetry(
        res=xres,
        verdict=xv,
        info=info,
        adopted=VERDICT_RANK.get(xv.status, 0) > VERDICT_RANK.get(current_status, 0),
    )
