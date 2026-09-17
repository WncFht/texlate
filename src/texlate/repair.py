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
  跨引擎重试取优；``_ruleset_with_baseline`` 把运行时 baseline
  树注入 restore_support_from_src（worker ``ctx.base_dir`` /
  e2e ``_baseline_snapshot`` 两源同一注入件）
- E2 批（2026-09-17 自 ``e2e`` 下沉）：env judge 可译性判定
  （``_env_judge_one``/``_env_judge_all`` + 目标谓词 ``unknown_env_of``）
  + L2 回灌机械（``_l2_parse``/``_expand_tokens``/``_chunk_spans``/
  ``_resolve_fidx``/``_L2Attr``/``_l2_localize``/``_retranslate_hits``/
  ``_resplice``，配 ``_TreeRun``/``_split_cid`` 与开关/上限常量）+
  glossary confine kernel ``_resolve_glossary_path``（相对路径 +
  ``..`` 拒 + resolve-jail）——两臂同一实现
- C6 批（2026-09-17 残余收编）：``_ENV_NO_FIXLOOP``/``_ENV_FIXLOOP_LLM``
  env 名常量补齐（e2e 本地常量 + worker 裸字面量双源归一）、
  ``embed_tounicode_quiet``（ToUnicode 注入 best-effort 壳）、
  ``consume_engine_flags``（fixloop ``engine_flags`` 消费尾：
  dropped→``cross_engine_retry``，applied→审计 note）、
  ``l2_repair_round``（L2 阶梯骨架——``retranslate``/``recompile``/
  ``checkpoint`` 三钩两臂注入，e2e ``_l2_repair``/worker
  ``_l2_repair_zh`` 转 wrapper）
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.compile.cjkmap import embed_cjk_mappings
from texlate.compile.fixloop.engine import Ruleset, fixloop
from texlate.compile.inject import InjectRejectError, prepare_chinese
from texlate.compile.judge import judge
from texlate.latex.placeholder import CHUNK_RX, PH_RX
from texlate.latex.reconstruct import (
    _LATIN_ITEM_RX,
    _PAR_RUN_RX,
    _seg_join,
    reconstruct,
    unicode_math_fix,
)
from texlate.latex.tables import (
    ARG_TRANSPARENT_ENVS,
    MATH_ENVS,
    PROTECTED_ENVS,
    VERBATIM_ENVS,
)
from texlate.textutil import safe_is_file, safe_resolve
from texlate.validate import l2 as l2_mod
from texlate.xlat import prompts as xlat_prompts

if TYPE_CHECKING:
    import re
    from collections.abc import Callable, Iterable, Sequence

    from texlate.compile.engine import CompRes, Engine
    from texlate.compile.fixloop.engine import LlmHook
    from texlate.compile.judge import Verdict
    from texlate.latex.model import Chunk, ScanResult
    from texlate.xlat.pipeline import ChunkIn, XlatPipeline

log = logging.getLogger(__name__)

VERDICT_RANK = {"clean": 3, "partial": 2, "fail": 1, "reject": 0}

#: L2 回灌默认每文档重译上限（spec ≤10，参数化入口 ``l2_max_chunks``）
L2_MAX_CHUNKS = 10
#: 错误行 → 最近 chunk 的归因距离上限（字符）；超出按基建错处理，不耗 LLM
_L2_ATTR_WINDOW = 4000
#: L2 单次回灌最多消费的 log 错误条数
_L2_MAX_ERRORS = 50
#: ``_expand_tokens`` 递归深度保险丝（自引用 token 不死循环）
_EXPAND_MAX_DEPTH = 32
#: env judge 输入截断（长 env 体只喂前 N 字符）
_ENV_JUDGE_MAX_CHARS = 2000
#: 环境开关
_ENV_NO_L2 = "TEXLATE_NO_L2"
_ENV_ENV_JUDGE = "TEXLATE_ENV_JUDGE"
_ENV_NO_FIXLOOP = "TEXLATE_NO_FIXLOOP"
#: fixloop ``escalate_llm`` 钩开关——默认值两臂有意不同（e2e opt-in False /
#: worker BYOK 默认 True，见 ``_llm_hook_pack``），本常量只单源名字
_ENV_FIXLOOP_LLM = "TEXLATE_FIXLOOP_LLM"

#: 静态环境表（已知语义的 env 不问 judge——体是否可译已由表决定）
_KNOWN_ENVS = MATH_ENVS | VERBATIM_ENVS | PROTECTED_ENVS | ARG_TRANSPARENT_ENVS


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


def _ruleset_with_baseline(baseline: Path) -> Ruleset:
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
    should_cancel: Callable[[], bool] | None = None,
) -> CrossRetry | None:
    """消费 dropped ``engine_flags``：tectonic→xelatex 重试 → ``CrossRetry``/None。

    触发条件（两臂同一契约）：有 dropped flag ∧ 当前引擎是 tectonic ∧
    ``xelatex`` 在 route 候选 ∧ 当前判定低于 clean。dropped 多为
    shell-escape 需求——tectonic 沙箱不收 → 换 xelatex 带全量请求 flag
    经 ``compile(flags=…)`` seam 重编，复判严格更优才 ``adopted``。

    ``make_engine`` 由调用侧注入（构造旋钮曾两臂分歧，2026-09-17 裁决
    统一为 best-effort ``halt_on_error=False``——retry 是交付路径终末
    重编非轮内分类编译；测试面仍可经 ``engine_factory`` 注入）。
    """
    if not dropped or engine_name != "tectonic" or "xelatex" not in route_engines:
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
    should_cancel: Callable[[], bool] | None = None,
) -> tuple[CrossRetry | None, str | None]:
    """Fixloop ``engine_flags`` 消费尾：dropped→跨引擎重试，applied→note。

    dropped 多为 shell-escape 需求——tectonic 沙箱不收 → 换 xelatex 带
    ``probe_flags``+``flags`` 合并去重后的全量请求经 ``compile(flags=…)``
    seam 重编取优（机械在 ``cross_engine_retry``）。``status_of`` 惰性取
    incumbent 判据——worker 臂仅 dropped 路径需要，flags-only 不白费一轮
    judge。返回 ``(CrossRetry 或 None, 审计 note 或 None)``——两臂各接
    自家报告形态（e2e ``tail["verdict"]["notes"]`` / worker summary+log
    行）；note 一律贴换编后的终态上，换臂不丢审计痕迹。
    """
    if dropped:
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
            should_cancel=should_cancel,
        )
        return xr, f"engine_flags unsupported on {engine_name}: {dropped}"
    if flags:
        return None, f"engine_flags applied via CLI seam: {flags}"
    return None, None


# ---------------------------------------------------------------- 运行态/env judge


@dataclass
class _TreeRun:
    """``_translate_tree`` 的内部运行态——splice 后供 L2 回灌复用。"""

    scans: list[tuple[Path, ScanResult]]
    trans: dict[int, dict[int, str]]  # fidx → {chunk.id: 译文}
    chunk_ins: dict[str, ChunkIn]  # "fidx:cid" → ChunkIn（带 ph_fragments）
    pipe: XlatPipeline


def _split_cid(chunk_id: str) -> tuple[int, int]:
    """``"fidx:cid"`` → (fidx, cid)。"""
    a, _, b = chunk_id.partition(":")
    return int(a), int(b)


def unknown_env_of(chunk: Chunk) -> str | None:
    """静态表外 env 名——体可译性未定的 env 返名，已知/无 env 返 None。

    ``_env_judge_all`` 目标选择谓词（e2e ``_env_judge_pass`` 与 worker
    ``_env_judge_filter`` 同一闸）。
    """
    env_name = (chunk.env or "").strip()
    return env_name if env_name and env_name not in _KNOWN_ENVS else None


async def _env_judge_one(pipe: XlatPipeline, chunk: Chunk, env_name: str) -> bool:
    """单 env 可译性判定（docs/08 §1.5）：0 温/16 tok/3 试/解析失败 fail-open。"""
    system = xlat_prompts.env_judge_system_prompt(pipe.cfg.src_lang, pipe.cfg.tgt_lang)
    user = (
        f"\\begin{{{env_name}}}\n"
        f"{chunk.content[:_ENV_JUDGE_MAX_CHARS]}\n\\end{{{env_name}}}"
    )
    for _ in range(xlat_prompts.ENV_JUDGE_RETRIES):
        try:
            raw = await pipe.translator.translate(
                system=system,
                user=user,
                temperature=xlat_prompts.ENV_JUDGE_TEMPERATURE,
                max_tokens=xlat_prompts.ENV_JUDGE_MAX_TOKENS,
            )
            return xlat_prompts.parse_env_judge_answer(raw)
        except Exception as e:  # noqa: BLE001 -- judge 是旁路臂，异常→宁翻勿漏
            log.debug("env judge call failed (%s) → retry", e)
            continue
    return True


async def _env_judge_all(
    pipe: XlatPipeline, targets: list[tuple[str, Chunk, str]]
) -> dict[str, bool]:
    """逐条判定未知 env 块（顺序跑——mock/单文件路径，量小）。"""
    out: dict[str, bool] = {}
    for cid, chunk, env_name in targets:
        out[cid] = await _env_judge_one(pipe, chunk, env_name)
    return out


# ---------------------------------------------------------------- L2 回灌


def _l2_parse(res: CompRes) -> l2_mod.L2Verdict:
    """CompRes → L2Verdict：log 文本优先，缺席/空文件/读失败退 stdout_tail。

    被杀编译留 0 字节 ``.log``——``exists()`` 判据下 0 错返回 L2 臂
    静默空转（engine.parse_log 同款修复，worker 共享本函数同愈）。
    """
    text = ""
    if res.log_path is not None:
        with suppress(OSError):
            text = res.log_path.read_text(encoding="utf-8", errors="replace")
    if text or res.stdout_tail:
        return l2_mod.parse_log_text(text or res.stdout_tail, project_root=res.workdir)
    return l2_mod.L2Verdict(log_missing=True)


def _expand_tokens(
    res: ScanResult, tokmap: dict[str, str], text: str, _depth: int = 0
) -> str:
    r"""``[[X_n]]`` 递归展开到落盘形态（与 reconstruct.expand 同优先级）。

    ``tokmap`` = ``{"[[CHUNK_k]]": unicode_math_fix(zh)}``——译文本位；
    未译 chunk 回落 ``chunks[k].content``，typed ph 走 ``ph_map``。
    已译且 context 非 para/item 的 ``[[CHUNK_n]]`` 展开后同样压 ``\n\n``→``\n``
    （reconstruct.expand 的 ``short_arg`` 同则）——缺这步 ``_chunk_spans`` 的
    ``find`` 必对不上落盘字节，块在 L2 二次归因里整片消失。字面/ph 交错段
    接缝同走 ``_seg_join``（``\cs`` 尾 + 字母头补空格）——本函数只服务
    译文落盘文件，``reconstruct`` 侧 ``glue_latin`` 恒真。
    """
    if _depth > _EXPAND_MAX_DEPTH:
        return text

    def rep(m: re.Match[str]) -> str:
        tok = m.group(0)
        body = tokmap.get(tok)
        if body is None:
            body = res.ph_map.get(tok)
        cm = CHUNK_RX.fullmatch(tok)
        if body is None and cm:
            idx = int(cm.group(1))
            if 0 <= idx < len(res.chunks):
                body = res.chunks[idx].content
        if body is None:
            return tok
        out = _expand_tokens(res, tokmap, body, _depth + 1)
        if cm and tok in tokmap:
            idx = int(cm.group(1))
            if 0 <= idx < len(res.chunks) and res.chunks[idx].context not in (
                "para",
                "item",
            ):
                out = _PAR_RUN_RX.sub("\n", out)
        return out

    segs: list[str] = []
    pos = 0
    for m in PH_RX.finditer(text):
        segs.append(text[pos : m.start()])
        segs.append(rep(m))
        pos = m.end()
    segs.append(text[pos:])
    return _seg_join(segs)


def _chunk_spans(
    text: str, res: ScanResult, trans: dict[int, str]
) -> dict[int, tuple[int, int] | None]:
    """各 chunk 在当前文件中的 ``[s, e)`` 区间（文档序贪心 find）。

    cjk_glue_fix 可能在译文里插空格 → find 失败的块给 ``None``，位置由
    前后块锚定（归因是启发式，丢块可接受）。
    """
    tokmap = {
        f"[[CHUNK_{cid}]]": _LATIN_ITEM_RX.sub(r"\\item ", unicode_math_fix(zh))
        for cid, zh in trans.items()
    }
    spans: dict[int, tuple[int, int] | None] = {}
    cur = 0
    for c in res.chunks:
        # 走 token 入口——短参折叠只在 rep 见到 [[CHUNK_n]] 时发生（同 reconstruct）
        body = _expand_tokens(res, tokmap, f"[[CHUNK_{c.id}]]")
        if not body:
            continue
        i = text.find(body, cur)
        if i < 0:
            i = text.find(body)  # 乱序兜底（pieces 保序，正常不该走到）
        if i < 0:
            spans[c.id] = None
            continue
        spans[c.id] = (i, i + len(body))
        cur = i + len(body)
    return spans


def _resolve_fidx(token: str, run: _TreeRun, work: Path) -> int | None:
    """Log 里的文件名 token → scans 下标（相对/``./``/绝对路径三形态）。"""
    t = token.strip()
    while t.startswith("./"):
        t = t[2:]
    for i, (f, _res) in enumerate(run.scans):
        rel = f.relative_to(work).as_posix()
        if t == rel or t.endswith("/" + rel) or rel.endswith("/" + t):
            return i
    try:
        rel2 = Path(t).resolve().relative_to(work.resolve()).as_posix()
    except (OSError, ValueError):
        return None
    for i, (f, _res) in enumerate(run.scans):
        if f.relative_to(work).as_posix() == rel2:
            return i
    return None


@dataclass
class _L2Attr:
    """L2 归因底账：每文件 文本/行偏移/chunk 区间 三表（惰性建）。"""

    run: _TreeRun
    work: Path
    texts: dict[int, str] = field(default_factory=dict)
    line_off: dict[int, list[int]] = field(default_factory=dict)
    spans: dict[int, dict[int, tuple[int, int] | None]] = field(default_factory=dict)

    def file_state(self, fidx: int) -> None:
        """惰性建文件文本/行偏移/chunk 区间三表。"""
        if fidx in self.texts:
            return
        f, sres = self.run.scans[fidx]
        self.texts[fidx] = f.read_text(encoding="utf-8", errors="replace")
        offs = [0]
        for ln in self.texts[fidx].splitlines(keepends=True):
            offs.append(offs[-1] + len(ln))
        self.line_off[fidx] = offs
        self.spans[fidx] = _chunk_spans(
            self.texts[fidx], sres, self.run.trans.get(fidx) or {}
        )

    def attribute(self, fidx: int, tex_line: int) -> int | None:
        """行号 → 字节偏移 → 所在/最近 chunk.id。

        顺序读取不变量：TeX 报 ``l.NNN`` 时还没读到该行之后——起点落在
        错误行行尾之后的块不可能是肇事者（repro-2501：preamble 错被
        forward-fallback 错归给首个正文块）。runaway/EOF 类报的父文件
        续行位由 ``attr_error`` 的 ``eof_file`` 改派兜住，不经此路。
        """
        offs = self.line_off[fidx]
        if not (1 <= tex_line <= len(offs) - 1):
            return None
        off = offs[tex_line - 1]
        line_end = offs[tex_line]
        best_cid, best_gap = None, _L2_ATTR_WINDOW + 1
        for cid, sp in self.spans[fidx].items():
            if sp is None:
                continue
            s, e = sp
            if s <= off < e:
                return cid
            if s >= line_end:
                continue
            gap = max(s - off, off - e, 0)
            if gap < best_gap:
                best_cid, best_gap = cid, gap
        return best_cid if best_gap <= _L2_ATTR_WINDOW else None

    def attr_error(self, err: l2_mod.LogError) -> tuple[int, list[int]] | None:
        """单条 log 错误 → (fidx, chunk.id 列表)；不可归因 → None。"""
        # runaway/EOF 错（eof_file 非 None）：报位是父文件 ``\input`` 续行，
        # 真肇事文件是 ``)`` 刚弹出的那个——行号属父文件须丢弃，归肇事
        # 文件整体（块多时任归 EOF 侧末块——runaway 的参数起点在文件尾）
        eof = err.eof_file is not None
        src_tok = (
            err.eof_file
            or err.tex_file
            or (err.file_stack[-1] if err.file_stack else None)
        )
        fidx = _resolve_fidx(src_tok, self.run, self.work) if src_tok else None
        if fidx is None:
            return None  # 肇事文件不在产物树——错怪父文件不如不归因
        self.file_state(fidx)
        sres = self.run.scans[fidx][1]
        if not eof and err.tex_line is not None:
            cid = self.attribute(fidx, err.tex_line)
            return (fidx, [cid] if cid is not None else [])
        if len(sres.chunks) <= L2_MAX_CHUNKS:
            return (fidx, [c.id for c in sres.chunks])
        if eof and sres.chunks:
            return (fidx, [sres.chunks[-1].id])
        return (fidx, [])


def _l2_localize(
    work: Path, run: _TreeRun, res: CompRes
) -> tuple[dict[str, dict[str, Any]], int]:
    """编译 log → ``{chunk_id: {file,line,head}}`` 归因表 + 错误总数。

    定位链：``eof_file``（runaway/EOF 错——报位是父文件续行，改派 ``)``
    刚弹出的肇事文件，行号丢弃）> ``tex_file``（file:line: 格式）> 文件栈
    **最内层**（``l.NNN`` 只对 TeX 正在读的文件有意义——栈里更深的
    ``.sty``/``.cls`` 错是基建问题，不归 chunk）。``tex_line`` → 字节偏移
    → 所在 chunk；不在任何块内则取最近块（≤ ``_L2_ATTR_WINDOW``，且起点
    越过错误行行尾的块被顺序读取不变量排除）。无行号错误按文件级
    归因——仅当该文件 chunk 数 ≤ ``L2_MAX_CHUNKS`` 才全收。
    """
    verdict = _l2_parse(res)
    if verdict.log_missing or not verdict.errors:
        return {}, verdict.n_errors
    st = _L2Attr(run, work)
    hits: dict[str, dict[str, Any]] = {}
    for err in verdict.errors[:_L2_MAX_ERRORS]:
        got = st.attr_error(err)
        if got is None:
            continue
        fidx, cids = got
        for cid in cids:
            key = f"{fidx}:{cid}"
            if key not in hits:
                rel = run.scans[fidx][0].relative_to(work).as_posix()
                hits[key] = {"file": rel, "line": err.tex_line, "head": err.head}
    return hits, verdict.n_errors


async def _retranslate_hits(
    run: _TreeRun, hits: dict[str, dict[str, Any]], cap: int
) -> dict[str, Any]:
    """逐块重译（单发）+ 结果入账；返回报告 dict（``_`` 前缀内部键）。"""
    rep: dict[str, Any] = {
        "retranslated": [],
        "reverted_l0": [],
        "kept_transport_err": [],
        "over_cap": [],
    }
    changed: set[str] = rep.setdefault("_changed", set())
    adopted: set[str] = rep.setdefault("_adopted", set())
    tried = 0
    for cid, info in hits.items():
        if tried >= cap:
            rep["over_cap"].append(cid)
            continue
        ci = run.chunk_ins.get(cid)
        if ci is None:
            continue
        tried += 1
        fidx, ccid = _split_cid(cid)
        loc = f"{info['file']}:{info['line']}" if info["line"] else info["file"]
        r = await run.pipe.retranslate_chunk(ci, f"{info['head']}\n(at {loc})")
        if r is None:
            rep["kept_transport_err"].append(cid)
            continue
        if r.status == "ok":
            run.trans.setdefault(fidx, {})[ccid] = r.translation
            rep["retranslated"].append(cid)
            adopted.add(cid)
        else:
            # 重译产物仍不过 L0 → 回落原文（spec: 再不过 → fallback 原文）
            run.trans.get(fidx, {}).pop(ccid, None)
            rep["reverted_l0"].append(cid)
        changed.add(cid)
    return rep


def _resplice(run: _TreeRun, work: Path, main_rel: str, fidxs: set[int]) -> list[str]:
    """受影响文件 reconstruct 重写；主文件重跑 ``prepare_chinese`` 补 ctex。"""
    main_path = work / main_rel
    rewritten: list[str] = []
    touched_main = False
    for fidx in sorted(fidxs):
        f, res = run.scans[fidx]
        f.write_text(reconstruct(res, run.trans.get(fidx) or {}), encoding="utf-8")
        rewritten.append(f.relative_to(work).as_posix())
        touched_main = touched_main or f == main_path
    if touched_main:
        # 首注已过——同文件重注不会再触发 \documentstyle 拒绝
        with suppress(InjectRejectError):
            prepare_chinese(work, main_rel)
    return rewritten


def l2_repair_round(  # noqa: PLR0913 -- 阶梯钩子面穿透两臂同一契约
    run: _TreeRun,
    work: Path,
    main_rel: str,
    res: CompRes,
    cap: int,
    *,
    retranslate: Callable[
        [_TreeRun, dict[str, dict[str, Any]], int], dict[str, Any]
    ],
    recompile: Callable[[], tuple[CompRes, Verdict]],
    checkpoint: Callable[[], None] | None = None,
) -> tuple[dict[str, Any], CompRes, Verdict | None]:
    """L2 回灌一轮骨架：归因 → 重译 → resplice → 重编 → 余孽回落原文。

    ``retranslate``/``recompile`` 两臂注入——e2e 包 ``asyncio.run(
    _retranslate_hits)`` + ``_compile_judge``（tail dict 臂侧合成）；
    worker 包 client aclose 同 loop 纪律 + ``eng.compile``+``judge``。
    ``checkpoint`` 是 cancel 轮询点（worker ``_abort_if_cancelled``
    同位三处：重译前/后、首编后），缺省无操作。
    返回 (l2 报告, 最新 CompRes, 新 Verdict 或 None=未重编)。
    """
    rep: dict[str, Any] = {"enabled": True, "cap": cap}
    hits, n_err = _l2_localize(work, run, res)
    rep["errors"] = n_err
    rep["hits"] = hits
    last_res = res
    if not hits:
        rep["note"] = "no chunk-level attribution"
        return rep, last_res, None
    if checkpoint is not None:
        checkpoint()
    retr = retranslate(run, hits, cap)
    if checkpoint is not None:
        checkpoint()
    changed: set[str] = retr.pop("_changed")
    adopted: set[str] = retr.pop("_adopted")
    rep.update(retr)
    if not changed:
        rep["note"] = "no chunk changed"
        return rep, last_res, None

    rep["rewritten"] = _resplice(
        run, work, main_rel, {_split_cid(c)[0] for c in changed}
    )
    res2, v2 = recompile()
    if checkpoint is not None:
        checkpoint()
    last_res = res2
    rep["recompiled"] = v2.status
    if v2.status == "clean":
        return rep, last_res, v2

    # 重编仍不过：本轮"重译过且仍被点名"的块回落原文；
    # 其余归因（含已回落原文仍犯错的——那是源级问题）记名留 fixloop。
    hits2, _ = _l2_localize(work, run, res2)
    still_bad = sorted(set(hits2) & adopted)
    rep["fallback_src"] = still_bad
    rep["unresolved"] = sorted(set(hits2) - adopted)
    if still_bad:
        for cid in still_bad:
            fidx, ccid = _split_cid(cid)
            run.trans.get(fidx, {}).pop(ccid, None)
        rep["fallback_rewritten"] = _resplice(
            run, work, main_rel, {_split_cid(c)[0] for c in still_bad}
        )
        # 回落态即交付树——补一次裸编：fixloop 关/崩/reject 时不再有
        # 代验兜底，zh-src.zip 不能装未验证树（audit fallback_unverified）
        res3, v3 = recompile()
        rep["fallback_verdict"] = v3.status
        last_res, v2 = res3, v3
    return rep, last_res, v2


# ---------------------------------------------------------------- glossary confine


def _resolve_glossary_path(
    gpath: str, glossary_dir: str, base_dir: Path
) -> Path | None:
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
