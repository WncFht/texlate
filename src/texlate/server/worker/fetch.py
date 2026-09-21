"""``PipelineWorker._Fetch``——fetching 段：arxiv 获取/upload 物化/复用命中。"""

from __future__ import annotations

import shutil
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

from texlate.arxiv.cache import (
    SourceCache,
)
from texlate.arxiv.fetch import (
    AcquireStatus,
)
from texlate.arxiv.ratelimit import RateLimiter
from texlate.arxiv.unpack import unpack_sniffed
from texlate.pipecore import front_matter_of
from texlate.server.store import TERMINAL_STATUSES
from texlate.server.upload import (
    _classify_upload,
    _safe_name,
    unpack_zip,
)
from texlate.server.worker import seams

from ._common import (
    _FETCH_NO_RETRY,
    PROGRESS,
    TaskCtx,
    _StageError,
    cache_key_for,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

    from texlate.arxiv.fetch import Fetcher


class _Fetch:
    """fetching 段 mixin：arxiv 获取/upload 物化/复用命中。"""

    async def _stage_fetch(self, ctx: TaskCtx) -> None:
        """fetching：源树就绪 + src.tar 登记（哨兵 .fetch-done 幂等）。"""
        if (ctx.src_dir / ".fetch-done").is_file():
            return
        self._stage(ctx, "fetching", "取源", PROGRESS["fetching"][0])
        if ctx.row["kind"] in ("arxiv", "share"):
            await self._to_thread(ctx, self._fetch_arxiv)
        elif ctx.row["kind"] == "arxiv_html":
            await self._to_thread(ctx, self._fetch_html)
        else:
            await self._to_thread(ctx, self._fetch_upload)
        if ctx.reuse_hit is not None:
            # dedup 命中——不落哨兵：崩溃在终态写入前时 resume 重跑
            # fetch 重查 dedup，等幂
            if self._current_status(ctx) in TERMINAL_STATUSES:
                return
            hit = ctx.reuse_hit
            if await self._to_thread(ctx, self._materialize_reuse, hit):
                self._finish_reuse(ctx, hit)
                return
            # 命中行产物在拷贝前被并发清空（delete_task 竞态）——零物化
            # 判 done 是假交付；熔断 dedup（reuse_dead 挡二次命中同腐行）
            # 回退自跑——entry 还在 SourceCache，重跑 acquire 是 HIT 廉价路径
            self._log(ctx, f"reuse: 任务 {hit['id']} 产物零物化——回退自跑")
            ctx.reuse_hit = None
            ctx.reuse_dead = True
            refetch = (
                self._fetch_html
                if ctx.row["kind"] == "arxiv_html"
                else self._fetch_arxiv
            )
            await self._to_thread(ctx, refetch)
        if ctx.options().get("reuse_hit") is not None:
            # 本跑自产——上轮的 reuse 标记随产物来历失效即摘。先于哨兵落盘：
            # 崩在两步之间时 resume 无哨兵重跑 fetch（dedup 重查等幂）；反序
            # 则哨兵在、本段被早返跳过——自产产物永挂命中来历
            self.store.update_fields(
                ctx.task_id,
                options_json=ctx.update_options(lambda o: o.pop("reuse_hit", None)),
            )
        (ctx.src_dir / ".fetch-done").write_text("", encoding="utf-8")
        self._stage(ctx, "fetching", "取源完成", PROGRESS["fetching"][1])
        self._check_cancelled(ctx)

    def _fetch_arxiv(self, ctx: TaskCtx) -> None:
        """``acquire_source`` → extracted → ``src/``；raw blob → ``src.tar``。"""
        self._abort_if_cancelled(ctx)
        arxiv_id = str(ctx.row["arxiv_id"])
        with self._borrow_fetcher() as (fetcher, cache):
            res = seams.acquire_source(
                arxiv_id,
                fetcher=fetcher,
                # 注入 fetcher 臂 yield 的 cache 可 None——acquire_source
                # 必用实体 SourceCache，惰性兜底（html 臂不取即零构造）
                cache=cache or self._source_cache(),
            )
            self._abort_if_cancelled(ctx)  # 网络段跑完先收敛——拷贝/登记是白费
            if res.status not in (AcquireStatus.OK, AcquireStatus.HIT):
                code = (
                    "no_latex_source"
                    if res.status
                    in (AcquireStatus.PDF_ONLY, AcquireStatus.UNKNOWN_FORMAT)
                    else "arxiv_fetch"
                )
                raise _StageError(
                    code,
                    res.detail or res.status.value,
                    retryable=res.status not in _FETCH_NO_RETRY,
                )
            assert res.entry is not None  # noqa: S101 -- ok/hit 必有 entry
            entry = res.entry
            fields: dict[str, Any] = {
                "arxiv_id": f"{entry.arxiv_id}v{entry.resolved_version}",
                "title": str(entry.meta.get("title") or ""),
            }
            fields.update(self._arxiv_meta_fields(ctx, arxiv_id, fetcher=fetcher))
            self._on_loop(self.store.update_fields, ctx.task_id, **fields)
            if self._post_resolve_reuse(ctx, entry.arxiv_id, entry.resolved_version):
                return  # 钉版键命中已完成任务——产物物化由 _stage_fetch 接管
            self._abort_if_cancelled(ctx)
            if ctx.src_dir.exists():
                shutil.rmtree(ctx.src_dir)
            shutil.copytree(entry.extracted_dir, ctx.src_dir)
            raw = entry.raw_path
            if raw is not None and raw.is_file():
                shutil.copyfile(raw, ctx.root / "src.tar")
                self._register(ctx, "src_tar", "src.tar")
            for w in res.warnings:
                self._log(ctx, f"fetch warn: {w}")

    def _source_cache(self) -> SourceCache:
        """``self._src_cache`` 缺省 ``data_dir/src-cache``——惰性建并回填。

        首调建默认实例并回填 ``self._src_cache``，后调同实例复用——
        ``RateLimiter`` 状态文件与 ``acquire_source`` 钉版缓存同根。
        """
        if self._src_cache is None:
            self._src_cache = SourceCache(self.data_dir / "src-cache")
        return self._src_cache

    @contextmanager
    def _borrow_fetcher(self) -> Iterator[tuple[Fetcher, SourceCache | None]]:
        """Fetch 臂 fetcher/cache 借还：yield ``(fetcher, cache)``。

        ``self._fetcher`` 注入时归调用方所有——出块不 ``close``，此时
        ``cache`` 原样回 ``self._src_cache``（可 ``None``：html 臂唯一
        cache 用途是自建 fetcher 的 RateLimiter 状态文件，注入时建默认
        SourceCache 是死构造——``acquire_source`` 臂按需
        ``_source_cache()`` 自取）。未注入则自建
        ``seams.Fetcher(RateLimiter(cache.root/"ratelimit.json"))``，
        出块随任务关连接池（own/close 纪律同原双臂——
        ``TestFetcherOwnership``）。
        """
        own = self._fetcher is None
        cache = self._src_cache
        fetcher = self._fetcher
        if own:
            cache = self._source_cache()
            fetcher = seams.Fetcher(RateLimiter(cache.root / "ratelimit.json"))
        try:
            yield fetcher, cache
        finally:
            # 自建实例随任务关连接池；注入的 self._fetcher 归调用方所有
            if own:
                fetcher.close()

    def _arxiv_meta_fields(
        self, ctx: TaskCtx, arxiv_id: str, *, fetcher: Fetcher
    ) -> dict[str, Any]:
        """``fetch_metadata`` → ``arxiv_categories`` 的 ``options_json`` 增量字段。

        cache meta.json 无 categories——单独 Atom/OAI 拉一次喂 glossary
        category 层；best-effort：挂了/meta 空/cats 空一律 ``{}``，只丢
        该层术语不拦主链（eprint/html 两臂同口径）。命中经 ``set_option``
        同步 ``ctx.row`` 内存面——防 ``_build_base`` 写回丢键；落库
        ``update_fields`` 归调用点（``fields`` 合并其它列一笔写）。
        """
        try:
            meta = seams.fetch_metadata(arxiv_id, fetcher=fetcher)
        except Exception as e:  # noqa: BLE001 -- 元数据臂不拦主链
            self._log(ctx, f"arxiv meta: {type(e).__name__}: {e}")
            return {}
        if meta is None:
            return {}
        cats = [
            c for c in dict.fromkeys([meta.primary_category, *meta.categories]) if c
        ]
        if not cats:
            return {}
        return {"options_json": ctx.set_option("arxiv_categories", cats)}

    def _post_resolve_reuse(
        self,
        ctx: TaskCtx,
        arxiv_id: str,
        version: int | None,
        *,
        source: str = "eprint",
    ) -> bool:
        """#74：latest-alias 任务 fetch 定版后按钉版键二次 dedup + re-key。

        入队时 ``id``（无版本）与 ``id@vN`` 产不同 cache_key 材料——enqueue
        的 ``find_reusable`` 拿 alias 键查不到钉版完成的产物。定版后补查
        钉版键：命中 → ``ctx.reuse_hit`` 置位（``_stage_fetch`` 物化产物）；
        未命中且无同键 ACTIVE 任务 → 本行 re-key 成钉版形，让后来的
        ``id@vN`` 请求 enqueue 即命中（双向补齐 dedup 面）。

        跳过条件：非 arxiv 系任务（share 必须走 ``_share_apply`` 对账链，
        不得吃 reuse 捷径；upload/doc 无钉版概念）；``prefer=fresh``；
        无 cache_key（fresh 撞键降级行）；键形同（本就钉版）。re-key 撞
        ACTIVE 唯一索引 → 放弃 re-key 保留 alias 键（无妨——对方任务覆盖
        钉版方向）。``source`` 透传 ``cache_key_for``——html 链的钉版键
        与 eprint 分桶（enqueue 侧同口径）。
        """
        if ctx.row["kind"] not in ("arxiv", "arxiv_html"):
            return False
        stored = str(ctx.row.get("cache_key") or "")
        if not stored or str(ctx.options().get("prefer") or "reuse") == "fresh":
            return False
        resolved_key = cache_key_for(
            arxiv_id=arxiv_id,
            version=version,
            model=str(ctx.row["model"]),
            target_lang=str(ctx.row["target_lang"]),
            api_key=ctx.secrets.api_key,
            source=source,
            front_matter=front_matter_of(ctx.options()),
        )
        if resolved_key == stored:
            return False
        # reuse_dead：上轮命中物化零产物（hit 行被并发清空）——回退自跑
        # 时同一腐行还会被 find_reusable 返回，熔断查臂直走 re-key
        hit = (
            None
            if ctx.reuse_dead
            else self._on_loop(self.store.find_reusable, resolved_key)
        )
        if hit is not None:
            ctx.reuse_hit = hit
            return True
        if self._on_loop(self.store.find_active_by_cache_key, resolved_key) is None:
            try:
                self._on_loop(
                    self.store.update_fields, ctx.task_id, cache_key=resolved_key
                )
            except sqlite3.IntegrityError:
                return False
            ctx.row["cache_key"] = resolved_key
        return False

    def _materialize_reuse(self, ctx: TaskCtx, hit: dict[str, Any]) -> int:
        """把命中任务的 files 产物物理拷进本任务目录并登记（worker 线程）。

        下载面按 ``tasks/{id}/{path}`` 解析——只建行不拷文件会让产物
        链接 404。盘上缺失的产物跳过（文件面以实拷为准）。返回实拷
        产物数——0 = 命中行已被并发清空，``_stage_fetch`` 回退自跑。
        """
        hit_root = self.data_dir / "tasks" / str(hit["id"])
        n = 0
        for kind, f in self._on_loop(self.store.files, str(hit["id"])).items():
            self._abort_if_cancelled(ctx)
            rel = Path(str(f["path"]))
            src = hit_root / rel
            dst = ctx.root / rel
            if (
                rel.is_absolute()
                or ".." in rel.parts
                or not dst.resolve().is_relative_to(ctx.root.resolve())
            ):
                self._log(ctx, f"reuse: 路径越界跳过 {rel}")
                continue
            if not src.is_file():
                self._log(ctx, f"reuse: 产物缺失跳过 {rel}")
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copyfile(src, dst)
            except OSError:
                # is_file→copyfile 间被并发清空（delete_task 竞态 TOCTOU）
                # ——按缺失跳过；n=0 落既有零物化熔断臂回退自跑
                self._log(ctx, f"reuse: 产物拷贝失败跳过 {rel}")
                continue
            self._register(ctx, kind, rel.as_posix())
            n += 1
        return n

    def _finish_reuse(self, ctx: TaskCtx, hit: dict[str, Any]) -> None:
        """post-resolve dedup 收尾：产物拷贝 + done 终态 + done 事件（loop 线程）。

        cancel 竞态守卫同 ``_fail``——行已入终态则整条跳过（cancel 路径
        已发 done），不复活用户取消的任务。
        """
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return
        self._log(ctx, f"reuse: 命中任务 {hit['id']} 产物（post-resolve dedup）")
        # find_reusable 只回 done 行（partial 降级交付不克隆——毒传播先例
        # t_f74894ebc691aaf4）。终态恒 done，无 error_json 镜像。
        upd: dict[str, Any] = {"progress": 100}
        if hit.get("main_tex"):
            upd["main_tex"] = str(hit["main_tex"])
        if hit.get("title") and not ctx.row.get("title"):
            upd["title"] = str(hit["title"])
        # 行级持久化 reuse 命中标记——事后 share 打包端点据以拒自包（命中
        # 任务的生效术语表不可知，错标 glossary_hash 比不打包更糟）。真跑
        # 取源落 .fetch-done 时摘除（标记只描述当前产物的来历）。
        upd["options_json"] = ctx.set_option("reuse_hit", str(hit["id"]))
        self.store.update_fields(ctx.task_id, **upd)
        self._finish_terminal(ctx, "done")

    def _upload_files(self, ctx: TaskCtx) -> list[Path]:
        """``upload/`` 全件名序枚举——无 payload 回空表（失败口径归调用方）。"""
        return sorted((ctx.root / "upload").glob("*"))

    def _first_upload(
        self, ctx: TaskCtx, *, stage: str, code: str = "internal"
    ) -> Path | None:
        """``upload/`` 首件；空载 ``_fail`` 后回 ``None``——调用方 ``return`` 即够。"""
        uploads = self._upload_files(ctx)
        if not uploads:
            self._fail(
                ctx, code, "upload payload missing", retryable=False, stage=stage
            )
            return None
        return uploads[0]

    def _fetch_upload(self, ctx: TaskCtx) -> None:
        """upload_tex：解包 ``upload/`` blob → ``src/``；原文登记 src_tar。

        判据级联单源在 ``upload._classify_upload``（与路由层 ``sniff_upload``
        同一份序：``%PDF`` → ``PK`` → tar/single_gz → text → unknown）——
        本段只做 kind → 解包器分派不自持魔数序：zip+tar polyglot 在路由
        侧判 zip，此处同判走 ``unpack_zip``，不再被 ``sniff`` 抢道成 tar。
        """
        self._abort_if_cancelled(ctx)
        uploads = self._upload_files(ctx)
        if not uploads:
            msg = "upload payload missing"
            raise _StageError(code="internal", message=msg)
        blob_path = uploads[0]
        data = blob_path.read_bytes()
        ctx.src_dir.mkdir(parents=True, exist_ok=True)
        warnings: list[str] = []
        kind, s = _classify_upload(data, blob_path.name)
        if kind == "zip":
            warnings = unpack_zip(data, ctx.src_dir)
        elif kind in ("tar", "single_gz"):
            assert s is not None  # noqa: S101 -- tar/single 臂恒带解压载荷
            res = unpack_sniffed(s, ctx.src_dir, stem_hint=blob_path.name)
            warnings = res.warnings
        elif kind == "text":
            (ctx.src_dir / _safe_name(blob_path.name)).write_bytes(data)
        else:  # pdf/unknown——路由层已分流/拒收，漏到 fetch 侧即不支持
            msg = f"unrecognized upload format: {blob_path.name}"
            raise _StageError(code="unsupported_format", message=msg)
        for w in warnings:
            self._log(ctx, f"unpack: {w}")
        self._register(ctx, "src_tar", f"upload/{blob_path.name}")
