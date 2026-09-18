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
  跨引擎重试取优；``ruleset_with_baseline`` 把运行时 baseline
  树注入 restore_support_from_src（worker ``ctx.base_dir`` /
  e2e ``_baseline_snapshot`` 两源同一注入件）
- E2 批（2026-09-17 自 ``e2e`` 下沉）：glossary confine kernel
  ``resolve_glossary_path``（相对路径 + ``..`` 拒 + resolve-jail）
  留置本文件——两臂同一实现
- C6 批（2026-09-17 残余收编）：``ENV_NO_FIXLOOP``/``ENV_FIXLOOP_LLM``
  env 名常量补齐（e2e 本地常量 + worker 裸字面量双源归一）、
  ``embed_tounicode_quiet``（ToUnicode 注入 best-effort 壳）、
  ``consume_engine_flags``（fixloop ``engine_flags`` 消费尾：
  dropped→``cross_engine_retry``，applied→审计 note）
- C4 批（2026-09-18，reaudit 拆分）：env judge 可译性判定 + L2 回灌
  机械 + ``TreeRun``/``split_cid`` 运行态整簇迁 ``repair_l2.py``——
  消费面直取叶子模块，本文件不回引
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.cjkmap import embed_cjk_mappings
from texlate.compile.fixloop.engine import Ruleset, fixloop
from texlate.compile.judge import judge
from texlate.textutil import safe_is_file, safe_resolve

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence

    from texlate.compile.engine import CompRes, Engine
    from texlate.compile.fixloop.engine import LlmHook
    from texlate.compile.judge import Verdict

log = logging.getLogger(__name__)

VERDICT_RANK = {"clean": 3, "partial": 2, "fail": 1, "reject": 0}

#: 环境开关
ENV_NO_FIXLOOP = "TEXLATE_NO_FIXLOOP"
#: fixloop ``escalate_llm`` 钩开关——默认值两臂有意不同（e2e opt-in False /
#: worker BYOK 默认 True，见 ``_llm_hook_pack``），本常量只单源名字
ENV_FIXLOOP_LLM = "TEXLATE_FIXLOOP_LLM"


def log_text_of(res: CompRes) -> str:
    """``CompRes`` → log 全文（``.log`` 非空优先、``stdout_tail`` 兜底）。

    被杀编译会留 0 字节 ``.log``——``exists()`` 判据下空文件返空串会
    让 missing-char 等只存在于 stdout 的信号静默丢失；缺席/空文件/读
    失败一律退 ``stdout_tail``。
    """
    text = getattr(res, "log_text", "") or ""
    if not text and res.log_path is not None:
        with suppress(OSError):
            text = res.log_path.read_text(encoding="utf-8", errors="replace")
    return text or res.stdout_tail or ""


def embed_tounicode_quiet(
    pdf: Path,
    *,
    embed_fn: Callable[[Path], int] = embed_cjk_mappings,
    on_error: Callable[[Exception], None] | None = None,
) -> int:
    """``embed_cjk_mappings`` best-effort 壳：后处理崩不拖管线，返注入字体数。

    e2e ``_embed_tounicode`` 与 worker ``_Compile._embed_tounicode`` 同位件——
    成功计数两臂各自记（e2e 进 ``tounicode_fonts`` 报告键，worker 补
    ``self._log`` 行），失败统一静默降级 0。``embed_fn`` 默认直调；e2e 臂
    显式传自家模块全局名，保 ``monkeypatch.setattr(e2e, "embed_cjk_mappings",
    …)`` 测试缝（test_e2e_wiring 三钉）。``on_error`` 是可选失败钩子——
    worker 臂借此把异常落任务日志（e2e 仅 debug 留痕）。
    """
    try:
        return embed_fn(pdf)
    except Exception as e:  # 产物后处理失败不该 fault 整链
        log.debug("tounicode embed failed", exc_info=True)
        if on_error is not None:
            on_error(e)
        return 0


class ResProxy:
    """``Engine`` 透传代理：转发 Protocol 面 + 记末次 ``CompRes``。

    ``__setattr__`` 透传到内层——fixloop ``_wire_engine`` 会给 tectonic
    注入 ``ctan_fetch`` callable，必须落到真引擎实例上；``_inner``/
    ``last``/``_should_cancel`` 三键保留在代理自身（读侧经实例 attr
    命中，不走转发）。
    """

    def __init__(
        self, inner: Engine, should_cancel: Callable[[], bool] | None = None
    ) -> None:
        """包一层引擎；``should_cancel`` 是 worker 取消旗标轮询钩。"""
        object.__setattr__(self, "_inner", inner)
        object.__setattr__(self, "last", None)
        object.__setattr__(self, "_should_cancel", should_cancel)

    def __getattr__(self, name: str) -> Any:  # noqa: ANN401 -- 代理转发面天然 Any
        """未命中的 attr 转发到内层引擎。"""
        return getattr(self._inner, name)

    def __setattr__(self, name: str, value: Any) -> None:  # noqa: ANN401 -- 同上
        """``_inner``/``last``/``_should_cancel`` 写代理自身，其余写穿。"""
        if name in {"_inner", "last", "_should_cancel"}:
            object.__setattr__(self, name, value)
        else:
            setattr(self._inner, name, value)

    def compile(self, *args: Any, **kwargs: Any) -> CompRes:  # noqa: ANN401
        """转发 compile 并记录 CompRes（fixloop 每轮重编都过这里）。

        ``should_cancel`` 已置位直接抛 ``CancelledError``（轮内不再点
        火新编译）；否则透传给引擎做进程级轮询杀树。
        """
        sc = self._should_cancel
        if sc is not None:
            if sc():
                raise asyncio.CancelledError
            kwargs.setdefault("should_cancel", sc)
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


def run_fixloop(  # noqa: PLR0913 -- 开关面穿透两臂同一契约
    work: Path,
    engine: Engine,
    *,
    engine_name: str,
    llm_hook: LlmHook | None = None,
    compile_timeout: float | None = None,
    should_cancel: Callable[[], bool] | None = None,
    **kw: Any,  # noqa: ANN401 -- fixloop 开关面透传，键集由 fixloop 签名定
) -> tuple[dict[str, Any], CompRes | None]:
    """``ResProxy`` 包装 + ``fixloop()`` 调用 + 末次 ``CompRes`` 取回。

    ``**kw`` 透传 fixloop 的其余开关面（``ruleset``/``corpus_id``/
    ``cond``/``case_sink`` 等，worker 臂使用）。异常不吞——两臂各自
    决定兜底形态（e2e 产 error dict、worker 记日志返回原 res）。
    ``should_cancel`` 双落：``fixloop`` 轮顶轮询 + ``ResProxy.compile``
    注入引擎进程级杀树。
    """
    proxy = ResProxy(engine, should_cancel)
    cell = fixloop(
        work,
        proxy,
        engine_name=engine_name,
        llm_hook=llm_hook,
        compile_timeout=compile_timeout,
        should_cancel=should_cancel,
        **kw,
    )
    return cell, proxy.last


def ruleset_with_baseline(baseline: Path) -> Ruleset:
    """加载默认 ruleset 并把 ``baseline`` 注入 restore_support_from_src 的 params。

    ``baseline_dir`` 是运行时路径（任务级 pristine base 树——worker 传
    ``ctx.base_dir``，e2e 传 ``_baseline_snapshot`` 的译前快照），
    ``_substitute`` 只展开 ``{payload}`` 模板，故按 transform 名直接
    改写加载后的规则 raw dict。规则行未落地时为空转 no-op。
    """
    rs = Ruleset.load()
    for rule in rs.rules:
        act = rule.raw.get("action") or {}
        if (
            act.get("kind") == "builtin_transform"
            and act.get("function") == "restore_support_from_src"
        ):
            act.setdefault("params", {})["baseline_dir"] = str(baseline)
    return rs


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
    reject_route: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> CrossRetry | None:
    """消费 dropped ``engine_flags``/``reject_route``：tectonic→xelatex 重试 → ``CrossRetry``/None。

    触发条件（两臂同一契约）：有 dropped flag ∨ fixloop 显式路由
    xelatex（``reject_route`` 令牌，biber/biblatex 版本错配、pstricks
    等 tectonic 死路签名）∧ 当前引擎是 tectonic ∧ ``xelatex`` 在
    route 候选 ∧ 当前判定低于 clean。dropped 多为 shell-escape
    需求——tectonic 沙箱不收 → 换 xelatex 带全量请求 flag 经
    ``compile(flags=…)`` seam 重编，复判严格更优才 ``adopted``。

    ``make_engine`` 由调用侧注入（构造旋钮曾两臂分歧，2026-09-17 裁决
    统一为 best-effort ``halt_on_error=False``——retry 是交付路径终末
    重编非轮内分类编译；测试面仍可经 ``engine_factory`` 注入）。
    """
    routed = reject_route == "xelatex"
    if (
        not (dropped or routed)
        or engine_name != "tectonic"
        or "xelatex" not in route_engines
    ):
        return None
    if VERDICT_RANK.get(current_status, 0) >= VERDICT_RANK["clean"]:
        return None
    xres = make_engine().compile(
        work,
        main_rel,
        timeout=timeout,
        sandbox=True,
        flags=flags,
        should_cancel=should_cancel,
    )
    xv = judge(xres, expect_cjk=expect_cjk, log_text=log_text_of(xres))
    why = (
        f"engine_flags {dropped} tectonic 不支持"
        if dropped
        else f"fixloop route {reject_route}"
    )
    info = {
        "engine": "xelatex",
        "status": xv.status,
        "reason": f"{why} → 换 xelatex",
        "adopted": VERDICT_RANK.get(xv.status, 0) > VERDICT_RANK.get(current_status, 0),
    }
    return CrossRetry(
        res=xres,
        verdict=xv,
        info=info,
        adopted=VERDICT_RANK.get(xv.status, 0) > VERDICT_RANK.get(current_status, 0),
    )


def consume_engine_flags(  # noqa: PLR0913 -- 开关面穿透两臂同一契约
    *,
    engine_name: str,
    route_engines: Iterable[str],
    status_of: Callable[[], str],
    work: Path,
    main_rel: str,
    timeout: float | None,
    probe_flags: Iterable[str],
    flags: Sequence[str],
    dropped: Sequence[str],
    expect_cjk: bool,
    make_engine: Callable[[], Engine],
    reject_route: str | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[CrossRetry | None, str | None]:
    """Fixloop ``engine_flags``/``reject_route`` 消费尾：跨引擎重试或审计 note。

    dropped 多为 shell-escape 需求、``reject_route`` 是 fixloop 的显式
    路由令牌（REJECT note 的 ``route=`` 提出，biber/biblatex 错配等
    tectonic 死路签名）——两臂合一：tectonic 收不起的诉求由 xelatex
    带 ``probe_flags``+``flags`` 合并去重后的全量请求经 ``compile(flags=…)``
    seam 重编取优（机械在 ``cross_engine_retry``）。``status_of`` 惰性取
    incumbent 判据——仅换编路径需要，flags-only 不白费一轮 judge。
    返回 ``(CrossRetry 或 None, 审计 note 或 None)``——两臂各接自家报告
    形态（e2e ``tail["verdict"]["notes"]`` / worker summary+log 行）；
    note 一律贴换编后的终态上，换臂不丢审计痕迹。
    """
    if dropped or reject_route == "xelatex":
        xr = cross_engine_retry(
            engine_name=engine_name,
            route_engines=route_engines,
            current_status=status_of(),
            work=work,
            main_rel=main_rel,
            timeout=timeout,
            flags=list(dict.fromkeys([*probe_flags, *flags])) or None,
            dropped=dropped,
            expect_cjk=expect_cjk,
            make_engine=make_engine,
            reject_route=reject_route,
            should_cancel=should_cancel,
        )
        note = (
            f"engine_flags unsupported on {engine_name}: {dropped}"
            if dropped
            else f"fixloop reject_route={reject_route} on {engine_name}"
        )
        return xr, note
    if flags:
        return None, f"engine_flags applied via CLI seam: {flags}"
    return None, None


# ---------------------------------------------------------------- glossary confine


def resolve_glossary_path(gpath: str, glossary_dir: str, base_dir: Path) -> Path | None:
    """``_glossary_path`` 的静默版：同一 confine 解析，不告警。

    供 ``_make_cache`` 这类「只想知道生效文件」的调用方用——告警仍由
    ``_glossary_path``（``_make_glossary`` 路）发，不双发。

    ``options.glossary`` 是未校验请求面输入，e-print tar 还可在 base/ 植
    symlink 环——resolve/lstat 的 ``OSError``/``RuntimeError``/``ValueError``
    三族一律收敛为 None（``safe_resolve``/``safe_is_file`` 口径）。
    """
    rel = Path(gpath)
    if rel.is_absolute() or ".." in rel.parts:
        return None
    roots = [safe_resolve(base_dir)]
    if glossary_dir:
        with suppress(OSError, RuntimeError, ValueError):
            roots.append(safe_resolve(Path(glossary_dir).expanduser()))
    for base in roots:
        if base is None:
            continue
        cand = safe_resolve(base / rel)
        if cand is not None and cand.is_relative_to(base) and safe_is_file(cand):
            return cand
    return None
