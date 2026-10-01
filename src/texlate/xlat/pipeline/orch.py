"""pipeline 编排域（自 ``pipeline`` 出叶）：WorkItem + 队列编排/worker/暖缓存 + ``XlatPipeline`` 组合根。

``_XlatOrch`` 是主编排 mixin——``run()`` 序章（续跑装载/路由/物化）→
``_drain``（首发单飞暖前缀缓存 → N worker 消费 queue，哨兵收尾）→
auth 熔断收尾。``XlatPipeline`` 是组合根：继承五个域 mixin 不添实现。
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, NamedTuple, cast

from texlate.chunk import ChunkIn
from texlate.xlat import placeholders
from texlate.xlat.authgate import AuthGate, AuthTrippedError, _kind_of
from texlate.xlat.batch import batch_member_overhead, pack_batches, split_long_chunk
from texlate.xlat.client import HTTP_UNAUTHORIZED
from texlate.xlat.pipeline.batch import _XlatBatch
from texlate.xlat.pipeline.ledger import _FatalLedger, _XlatLedger
from texlate.xlat.pipeline.materialize import _XlatMaterialize
from texlate.xlat.pipeline.single import _XlatSingle
from texlate.xlat.pipeline.types import ChunkResult, PipelineConfig

if TYPE_CHECKING:
    from collections.abc import Callable

    from texlate.xlat.glossary import Glossary
    from texlate.xlat.pipeline.translator import Translator
    from texlate.xlat.state import StateStore

log = logging.getLogger(__name__)

#: ``WorkItem.payload`` 的 kind↔形态 union——``single`` 载荷即 ``ChunkIn``；
#: ``batch`` 是 ``(批序号, members)``；``split`` 是 ``(父块, pieces)``。
WorkPayload = ChunkIn | tuple[int, list[ChunkIn]] | tuple[ChunkIn, list[ChunkIn]]


class WorkItem(NamedTuple):
    """工作单元 tagged union——``kind`` + 命名 accessor 是生产侧唯一解码点。

    tuple 形为存量两元解包/下标消费面（``for k, payload in items``、
    ``it[0]``）保兼容；``payload`` 位序语义只经本类 accessor 读——
    ``payload[0]`` 在 ``batch`` 是批序号、``split`` 是父块、``single``
    载荷即块本身。新增 item 种类只改本类 + ``_process`` 一处。

    - ``batch``：``(seq, members)``
    - ``split``：``(parent, pieces)``——片段译文合并后按父 id 记账
    - ``single``：``ChunkIn``
    """

    kind: str  # "batch" | "split" | "single"
    payload: WorkPayload  # tagged union 载荷形态随 kind 变，accessor 各自收窄

    @property
    def seq(self) -> int:
        """``batch`` 批序号。"""
        return cast("tuple[int, list[ChunkIn]]", self.payload)[0]

    @property
    def members(self) -> list[ChunkIn]:
        """``batch`` 成员列表。"""
        return list(cast("tuple[int, list[ChunkIn]]", self.payload)[1])

    @property
    def parent(self) -> ChunkIn:
        """``split`` 父块（记账 id 属主）。"""
        return cast("tuple[ChunkIn, list[ChunkIn]]", self.payload)[0]

    @property
    def pieces(self) -> list[ChunkIn]:
        """``split`` 片段序列。"""
        return list(cast("tuple[ChunkIn, list[ChunkIn]]", self.payload)[1])

    @property
    def chunk(self) -> ChunkIn:
        """``single`` 载荷块。"""
        return cast("ChunkIn", self.payload)

    def affected(self) -> list[ChunkIn]:
        """本单元覆盖的 ChunkIn（auth 闸/worker crash 兜底记账用）。"""
        if self.kind == "batch":
            return self.members
        if self.kind == "split":
            return [self.parent]
        return [self.chunk]


class _XlatOrch:
    """asyncio.Queue 编排 mixin（实例状态由 ``XlatPipeline.__init__`` 初始化）。"""

    def __init__(  # noqa: PLR0913 -- 依赖注入面（docs/spec/translate.md 可插拔点全集）
        self,
        translator: Translator,
        *,
        config: PipelineConfig | None = None,
        glossary: Glossary | None = None,
        state: StateStore | None = None,
        validator: Callable[[str, str], str] | None = None,
        cache: dict[str, str] | None = None,
        on_result: Callable[[ChunkResult], None] | None = None,
    ) -> None:
        """组装编排器；`state`/`cache`/`validator`/`on_result` 均可选。"""
        self.translator = translator
        self.cfg = config or PipelineConfig()
        self.glossary = glossary
        self.state = state
        self.validator = validator or (lambda s, z: placeholders.diff(s, z).describe())
        self.cache = cache
        self.on_result = on_result
        #: auth 熔断闸（``run()`` 每次开头重置；跨论文熔断靠调用方读它累计）
        self.auth_gate = AuthGate(self.cfg.auth_fail_threshold)
        self._doc_glossary: dict[str, str] = {}
        self._paper_ctx = ""
        self._ph_manifest = ""
        self._prompts: dict[tuple[str, bool, bool], str] = {}

    # ------------------------------------------------------------ 主编排

    async def _process(self, item: WorkItem) -> list[ChunkResult]:
        """统一工作单元执行（warmup 与 worker 共用）。

        item 形态：`WorkItem("batch", (序号，[ChunkIn]))` / `("single", ChunkIn)` /
        `("split", (父 ChunkIn, [片段...]))`——拆分块内部逐段走阶梯、译文合并
        后按父 id 记账（state/续跑只见父 id，不见片段 id）。
        """
        if item.kind == "batch":
            bid, members = f"batch_{item.seq:04d}", item.members
            try:
                return await self._one_batch(members, bid)
            except Exception as e:  # noqa: BLE001 -- worker 绝不让一批炸全队
                return [
                    self._skip(c, f"batch crash: {e}", bid, kind=_kind_of(e))
                    for c in members
                ]
        if item.kind == "split":
            parent, pieces = item.parent, item.pieces
            translations: list[str] = []
            warnings: list[str] = []
            kinds: list[str] = []
            attempts = 0
            worst = "ok"
            for piece in pieces:
                try:
                    r = await self._one_chunk(piece)
                except Exception as e:  # noqa: BLE001 -- 片段崩不拖全块
                    r = self._skip(piece, f"split piece crash: {e}", kind=_kind_of(e))
                translations.append(r.translation)
                warnings += r.warnings
                kinds.append(r.error_kind)
                attempts += r.attempts
                if r.status in ("fault", "skipped"):
                    worst = "fault"
                elif r.status == "partial" and worst == "ok":
                    worst = "partial"
            merged = " ".join(translations)
            status = worst if worst != "ok" else "ok"
            if status == "fault":
                # 保 skipped⇒translation==source 簿记不变量（D2）——merged 半成品
                # 折进 warnings 留诊断（对齐 fallback_orig 的 best_zh 口径）
                warnings.append(f"best-effort zh (unspliced): {merged[:200]}")
            return [
                ChunkResult(
                    chunk_id=parent.chunk_id,
                    source=parent.content,
                    translation=parent.content if status == "fault" else merged,
                    kind=parent.kind,
                    status=status,
                    skip_reason="split piece(s) failed" if status == "fault" else "",
                    attempts=attempts,
                    warnings=warnings,
                    error_kind=(
                        "auth" if "auth" in kinds else next((k for k in kinds if k), "")
                    ),
                )
            ]
        c = item.chunk
        try:
            return [await self._one_chunk(c)]
        except Exception as e:  # noqa: BLE001 -- 同上
            return [self._skip(c, f"chunk crash: {e}", kind=_kind_of(e))]

    def _load_resumed(
        self, fatal: _FatalLedger
    ) -> tuple[set[str], dict[str, ChunkResult]]:
        """续跑装载：state → (completed 集合，chunk_id→ChunkResult)。"""
        if self.state is None:
            return set(), {}
        completed, recs = self.state.load()
        # completed 只认 ok/partial：skipped/fault（三振回退原文、网关抖动 skip）
        # 在续跑里必须重试——否则一次瞬时失败会把该块永久冻结成英文原文。
        # state.json 里 completed 仍记全部已尝试块（审计口径不变），过滤只在
        # 编排侧生效；重试结果经 record() 追加覆盖 done_map。
        done_map: dict[str, ChunkResult] = {}
        for cid, rec in recs.items():
            res = ChunkResult.from_record(rec)
            # warning 时代落盘的 ok 残留（zh 带源外占位符）→ 就地降 fault，
            # 不进 completed → 本轮重翻自愈；否则旧档会把字面 [[X_n]] 带进 splice。
            self._ledger_intercepts(fatal, res)
            done_map[cid] = res
        completed = {
            cid
            for cid in completed
            if cid in done_map and done_map[cid].status in ("ok", "partial")
        }
        return completed, done_map

    def _route_chunks(
        self,
        chunks: list[ChunkIn],
        completed: set[str],
        done_map: dict[str, ChunkResult],
        fatal: _FatalLedger,
    ) -> tuple[list[ChunkIn], list[WorkItem]]:
        """路由输入块 → (pending, split_items)。

        completed 直跳过；纯占位符直落盘；超 hard_limit 的原子块切成 split
        工作单元（译文按父 id 合并记账，state/续跑只见父 id）。
        """
        pending: list[ChunkIn] = []
        split_items: list[WorkItem] = []
        for c in chunks:
            cid = c.chunk_id
            prev = done_map.get(cid)
            if cid in completed and prev is not None:
                if prev.source == c.content:
                    continue
                # parse 漂移下同 id 命中陈旧记录——其译文的 [[X_n]] 在新
                # ph_map 缺席 → splice 留字面残留（n100 实测 1524 例）。
                # 按未命中重翻自愈；丢出 done_map 防异常路径把旧译文当结果。
                log.warning(
                    "chunk %s source drifted (recorded %dB != current %dB) → re-translate",
                    cid,
                    len(prev.source),
                    len(c.content),
                )
                del done_map[cid]
            if placeholders.is_placeholder_only(c.content.strip()):
                r = self._passthrough_result(c)
                done_map[cid] = r
                # 与 _collect 同构的账本调用（拦截网 + record + emit）——
                # BaseException 收 fatal 由 run() 序章尾统一重抛，
                # Exception 档行为不变。
                self._ledger_outcome(fatal, r)
                continue
            if "[[BIB_" in c.content:
                # 用户裁决①：[[BIB_]]（\bibitem/bibliography 占位）块=文献域，
                # 约定留英不送翻——直通 zh=src，占位符链下游照常还原。
                # zh≡src 使各拦截网 diff 恒空，intercept 形同虚设但账本调用与
                # placeholder_only 路保持同构（计量/auth 闸口径一致）。
                r = self._passthrough_result(c, warnings=["bib_passthrough"])
                done_map[cid] = r
                self._ledger_outcome(fatal, r)
                continue
            pieces = split_long_chunk(c.content, max_chars=self.cfg.hard_limit)
            if len(pieces) > 1:
                subs = [
                    ChunkIn(f"{cid}~{i}", p, c.kind, ph_fragments=c.ph_fragments)
                    for i, p in enumerate(pieces)
                ]
                split_items.append(WorkItem("split", (c, subs)))
            else:
                pending.append(c)
        return pending, split_items

    def _build_work_items(
        self,
        pending: list[ChunkIn],
        split_items: list[WorkItem],
    ) -> list[WorkItem]:
        """全量装箱：`WorkItem("batch",(序号，[ChunkIn])) | ("single",ChunkIn) | split`。

        不分 short/long——产线对账批质量 ≥ 单发（per-placeholder 错率 0.32%
        vs 8.93%），全量入批只为削 ``n_req × ~2.9s`` 固定开销。batch 按 kind
        分组再装箱——一批共用 ``members[0].kind`` 的 system prompt，混 kind
        会让 caption/abstract 等专属条款错配到 para 头上。装箱吃
        ``concurrency`` 做 K 量化等大对齐（batchmodel-2026-09-18 §8）；
        装箱退化成单成员的组走 ``single`` 阶梯路径（比一发批协议多 corrector/
        slots/repair 全套修复臂）。
        """
        by_kind: dict[str, list[ChunkIn]] = {}
        for c in pending:
            by_kind.setdefault(c.kind, []).append(c)
        work_items: list[WorkItem] = []
        seq = 0
        for grp_chunks in by_kind.values():  # dict 保 insertion 序——批次确定性
            contents = [c.content for c in grp_chunks]
            for grp in pack_batches(
                contents,
                max_chars=self.cfg.batch_max_chars,
                max_items=self.cfg.batch_max_items,
                min_chars=self.cfg.batch_min_chars,
                overheads=[batch_member_overhead(t) for t in contents],
                workers=self.cfg.concurrency,
            ):
                if len(grp) == 1:
                    work_items.append(WorkItem("single", grp_chunks[grp[0]]))
                else:
                    work_items.append(
                        WorkItem("batch", (seq, [grp_chunks[j] for j in grp]))
                    )
                    seq += 1
        return work_items + split_items

    async def _worker(
        self,
        queue: asyncio.Queue[WorkItem | None],
        done_map: dict[str, ChunkResult],
        fatal: _FatalLedger,
    ) -> None:
        """消费循环：哨兵退出；item 级 crash 兜底成 skipped。

        worker 不死——否则 queue.join() 死等 + done_map 缺口在 run() 末行
        炸 KeyError。BaseException 族（KI/SE/GE）同样不可任 worker 带其
        死掉：sentinel 与 worker 一一对应，死者那份无人消费，join() 死锁
        （E3）。记入 ``fatal`` 降级成 skipped 后继续消费；``fatal`` 已挂
        时只吃不做排空到 sentinel——提前 return 会让剩余项无人 task_done，
        join() 照样死等——由 _drain 收敛后重抛。
        """
        while True:
            item = await queue.get()
            try:
                if item is None:
                    return
                if fatal:
                    # 致命异常已挂：排空队列项保 join 会计，不再发翻译请求
                    continue
                if self.auth_gate.tripped:
                    # auth 闸已断：剩余块不再发请求，直接按 auth 失败记账
                    results = [
                        self._skip(c, "auth circuit open", kind="auth")
                        for c in item.affected()
                    ]
                else:
                    try:
                        results = await self._process(item)
                    except Exception as e:
                        # _process 各分支已兜底；真逃逸（bug/中断）也要把受影响
                        # 块记成 skipped 而不是拖死整个消费循环。
                        log.exception("worker item crashed")
                        results = [
                            self._skip(c, f"worker crash: {e}", kind=_kind_of(e))
                            for c in item.affected()
                        ]
                    except BaseException as e:  # 收账转 _drain 重抛
                        log.exception("worker item crashed fatally")
                        fatal.append(e)
                        results = [
                            self._skip(c, f"worker crash: {e}", kind=_kind_of(e))
                            for c in item.affected()
                        ]
                self._collect(results, done_map, fatal)
            finally:
                queue.task_done()

    async def _drain(
        self,
        work_items: list[WorkItem | tuple[str, WorkPayload]],
        done_map: dict[str, ChunkResult],
    ) -> None:
        """首发单飞暖前缀缓存 → N worker 消费 queue（哨兵收尾）。

        入队统一成 ``WorkItem``——存量 tuple 形工作单元在此收口归一，
        下游 ``_process``/``affected()`` 只见命名访问面。
        """
        if not work_items:
            return
        queue: asyncio.Queue[WorkItem | None] = asyncio.Queue()
        for item in work_items:
            queue.put_nowait(item if isinstance(item, WorkItem) else WorkItem(*item))

        # 首发单飞暖前缀缓存，再并发其余（docs/spec/translate.md warmup 模式）
        fatal = _FatalLedger()
        first = await queue.get()
        if first is not None:
            try:
                results = await self._process(first)
            except Exception as e:  # 与 _worker 同兜底口径
                log.exception("warmup item crashed")
                results = [
                    self._skip(c, f"warmup crash: {e}", kind=_kind_of(e))
                    for c in first.affected()
                ]
            self._collect(results, done_map, fatal)
        queue.task_done()

        for _ in range(self.cfg.concurrency):
            queue.put_nowait(None)
        workers = [
            asyncio.create_task(self._worker(queue, done_map, fatal))
            for _ in range(self.cfg.concurrency)
        ]
        try:
            await queue.join()
        finally:
            # cancel/异常撕开 join 时 worker 仍在飞——不收尸就揣着半开
            # client 游离；cancel + gather 收敛（return_exceptions 防
            # CancelledError 自 gather 再抛一次盖掉原异常链）
            for w in workers:
                if not w.done():
                    w.cancel()
            await asyncio.gather(*workers, return_exceptions=True)
        fatal.raise_first()

    async def run(self, chunks: list[ChunkIn]) -> list[ChunkResult]:
        """跑完整篇。返回与输入同序的结果表。

        连续 ``cfg.auth_fail_threshold`` 块 auth 类失败（401/403）→ 抛
        ``AuthTrippedError`` 让论文 fault——凭证失效时绝不把整篇静默写成
        fallback 原文（T2：n100 里 401 逐块吞成 skipped→任务假 done）。
        """
        self.auth_gate = AuthGate(self.cfg.auth_fail_threshold)
        # 序章账本：_load_resumed/_route_chunks 的 interceptor/auth_gate/_emit
        # 调用点与 _collect 同款收账——BaseException 在此统一重抛，先于
        # state.start()/队列编排，免得上半段收账下半段无人抛。
        fatal = _FatalLedger()
        completed, done_map = self._load_resumed(fatal)
        pending, split_items = self._route_chunks(chunks, completed, done_map, fatal)
        fatal.raise_first()

        if self.state is not None:
            self.state.start(len(chunks))
        # 术语表物化吃全量 chunks 而非仅 pending——续跑时已完成块同样参与
        # 文档级过滤，保证 system prompt 与全新跑逐字节一致（缓存命中口径）。
        auto_terms = await self._auto_glossary(chunks, pending)
        self._materialize(list(chunks), auto_terms)

        await self._drain(self._build_work_items(pending, split_items), done_map)

        if self.state is not None:
            self.state.finish()
        if self.auth_gate.tripped:
            msg = (
                f"auth circuit open: {self.auth_gate.consecutive} consecutive "
                "auth failures (401/403) — check credentials"
            )
            raise AuthTrippedError(msg, status=HTTP_UNAUTHORIZED)
        return [done_map[c.chunk_id] for c in chunks]


class XlatPipeline(
    _XlatOrch,
    _XlatMaterialize,
    _XlatSingle,
    _XlatBatch,
    _XlatLedger,
):
    """asyncio.Queue 编排：分桶 → 装箱 → N worker → 阶梯 → 对账 → 落盘。

    `validator(src, zh) -> str` 可注入 rules 全量规则（返回空串=通过）；
    缺省 = 占位符对账。`state` 给了就断点续跑 + 逐块落盘；`cache` 是
    段级缓存 dict（调用方负责 file_cache_key 维度的装载/落盘）。
    """
