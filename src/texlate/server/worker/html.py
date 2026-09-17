"""``PipelineWorker._Html``——arxiv_html 链：fetch → DOM-chunk → translate → 序列化 DOM。

对位 ``_run_tex`` 的无编译变体：产物 = sanitize + URL 绝对化的 en/zh
序列化 DOM + dual.json（dom 视图锚点页），无 TeX 编译/fixloop/share
对账臂。``data-chunk`` 锚由 ``arxiv.html.marked_html`` 同源枚举注入——
块 key 与 chunks 行 ``chunk_id``、``HtmlDoc.blocks`` 严格 1:1。
"""

from __future__ import annotations

import json
import re
import shutil
from typing import TYPE_CHECKING, Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup

if TYPE_CHECKING:
    from bs4.element import Tag

import texlate.server.worker as _w
from texlate.arxiv.cache import SourceCache
from texlate.arxiv.fetch import _valid_id, normalize_arxiv_id
from texlate.arxiv.html import (
    HtmlDoc,
    HtmlFetchError,
    HtmlNotAvailableError,
    doc_chunks,
    reinsert,
)
from texlate.arxiv.ratelimit import RateLimiter
from texlate.server.store import TERMINAL_STATUSES
from texlate.xlat.state import atomic_json

from ._common import (
    PROGRESS,
    TaskCtx,
    _StageError,
)

#: sanitize 剥除的活性内容 tag（script/iframe/表单件——媒体与样式保留：
#: object.ltx_graphics 是 arXiv 图形载体，<style> 固化 ltx_* 排版）
_DROP_TAGS = (
    "script",
    "noscript",
    "template",
    "iframe",
    "form",
    "button",
    "dialog",
    "select",
)

#: href/src 系属性的危险 scheme——``data:`` 仅剥非 image（img src 内嵌
#: 位图是合法形态）；第二道防线在前端 DOMPurify（DomPane 双保险）
_BAD_SCHEME_RX = re.compile(r"^\s*(?:javascript|vbscript)\s*:", re.IGNORECASE)
_DATA_URI_RX = re.compile(r"^\s*data\s*:", re.IGNORECASE)

_URL_ATTRS = ("href", "src", "action", "poster", "data", "xlink:href")


def _bad_url(el_name: str, url: str) -> bool:
    """危险 scheme 判：js/vbs 全禁；data: 仅 ``<img>`` 的 ``data:image/`` 放行。"""
    if _BAD_SCHEME_RX.match(url):
        return True
    return bool(
        _DATA_URI_RX.match(url)
        and not (el_name == "img" and url.lstrip().lower().startswith("data:image/"))
    )


def _abs_srcset(el_name: str, srcset: str, base_url: str) -> str:
    """Srcset 候选表逐条过 scheme 检查 + 相对化（``url [desc]`` 逗号分隔）。"""
    out = []
    for cand in srcset.split(","):
        parts = cand.strip().split()
        if not parts:
            continue
        url, *desc = parts
        if _bad_url(el_name, url):
            continue  # 危险 scheme 整条候选剔除
        if not url.startswith(("http://", "https://", "#", "mailto:")):
            url = urljoin(base_url, url)
        out.append(" ".join([url, *desc]))
    return ", ".join(out)


def _attached_to(soup: BeautifulSoup, el: Tag) -> bool:
    """锚元素是否仍在 ``soup`` 活树内——clear 摘出的死节点需重查。"""
    node: Tag | BeautifulSoup = el
    while node.parent is not None:
        node = node.parent
    return node is soup


def _resolved_version(html: str, base: str) -> int | None:
    """canonical/self-link 里的 ``/abs/{base}vN`` → 钉版号（best-effort）。"""
    m = re.search(rf"arxiv\.org/(?:abs|html)/{re.escape(base)}v(\d+)", html)
    return int(m.group(1)) if m else None


class _Html:
    """arxiv_html 链 mixin：fetch/parse/emit 三臂 + resume/scans 桥接。"""

    # ------------------------------------------------------------ fetching 臂

    def _fetch_html(self, ctx: TaskCtx) -> None:
        """``GET /html/{id}`` → ``src/index.html`` + HtmlDoc + 钉版字段。

        与 ``_fetch_arxiv`` 同构但更薄：无 e-print 解包、无 raw blob tar——
        源产物即 ``src/index.html``（``src_html`` 槽位登记）。版本解析：
        ``fetch_html`` 不暴露 resolved URL，从 canonical/self-link 反推
        vN（``_resolved_version`` best-effort——拿不到则键保持 alias 形，
        dedup 语义与入队键一致不劣化）。HtmlDoc 在 fetch 臂预解析：
        早验文档结构 + title 字段，``_parse_html``/``_html_doc`` 复用。
        """
        self._abort_if_cancelled(ctx)
        arxiv_id = str(ctx.row["arxiv_id"])
        base, pin = normalize_arxiv_id(arxiv_id)
        if not _valid_id(base) or (pin is not None and pin < 1):
            raise _StageError(code="arxiv_fetch", message=f"bad arxiv id: {arxiv_id!r}")
        cache = self._src_cache or SourceCache(self.data_dir / "src-cache")
        own = self._fetcher is None
        fetcher = self._fetcher or _w.Fetcher(
            RateLimiter(cache.root / "ratelimit.json")
        )
        try:
            try:
                html = _w.fetch_html(base, version=pin, fetcher=fetcher)
            except HtmlNotAvailableError as e:
                # 404/stub——无 HTML 是终态事实，重试无意义
                raise _StageError(
                    code="no_html_source", message=str(e), retryable=False
                ) from e
            except HtmlFetchError as e:
                raise _StageError(
                    code="arxiv_fetch", message=str(e), retryable=True
                ) from e
            doc = _w.parse_arxiv_html(html, arxiv_id=base)
            ctx.html_doc = doc
            ver = pin or _resolved_version(html, base)
            fields: dict[str, Any] = {
                "arxiv_id": f"{base}v{ver}" if ver else base,
                "title": doc.title,
            }
            # categories 喂 glossary category 层——eprint 臂同口径 best-effort
            try:
                meta = _w.fetch_metadata(arxiv_id, fetcher=fetcher)
            except Exception as e:  # noqa: BLE001 -- 元数据臂不拦主链
                self._log(ctx, f"arxiv meta: {type(e).__name__}: {e}")
                meta = None
            if meta is not None:
                cats = [
                    c
                    for c in dict.fromkeys([meta.primary_category, *meta.categories])
                    if c
                ]
                if cats:
                    opts = ctx.options()
                    opts["arxiv_categories"] = cats
                    ctx.row["options_json"] = json.dumps(opts, ensure_ascii=False)
                    fields["options_json"] = ctx.row["options_json"]
            self._on_loop(self.store.update_fields, ctx.task_id, **fields)
            if self._post_resolve_reuse(ctx, base, ver, source="html"):
                return  # 钉版键命中已完成任务——产物物化由 _stage_fetch 接管
            if ctx.src_dir.exists():
                shutil.rmtree(ctx.src_dir)
            ctx.src_dir.mkdir(parents=True, exist_ok=True)
            (ctx.src_dir / "index.html").write_text(html, encoding="utf-8")
            self._register(ctx, "src_html", "src/index.html")
        finally:
            # 自建实例随任务关连接池；注入的 self._fetcher 归调用方所有
            if own:
                fetcher.close()

    # ------------------------------------------------------------ parsing 臂

    def _html_doc(self, ctx: TaskCtx) -> HtmlDoc:
        """HtmlDoc 单例：fetch 预解析命中，否则 ``src/index.html`` 惰性重解析（resume）。"""
        self._abort_if_cancelled(ctx)
        if ctx.html_doc is None:
            html = (ctx.src_dir / "index.html").read_text(encoding="utf-8")
            ctx.html_doc = _w.parse_arxiv_html(html, arxiv_id=str(ctx.row["arxiv_id"]))
        return ctx.html_doc

    def _parse_html(self, ctx: TaskCtx) -> list[dict[str, Any]]:
        """HtmlDoc → chunk 行（``insert_chunks`` 契约同 ``_parse_all``）。

        ``src_file`` 恒 ``"index.html"``；``byte_start/byte_end`` 用块在
        ``doc.blocks`` 的序位充位（DOM 块无字节区间——仅占列）。
        ``chunk_id`` = ``HtmlBlock.key``——与 emit 侧 ``data-chunk`` 锚、
        DomPane 几何序严格同源 1:1。``kind`` 已由 ``doc_chunks`` 经
        ``normalize_kind`` 归一（bibitem/figure 等 support 块不产行）。
        """
        self._abort_if_cancelled(ctx)
        doc = self._html_doc(ctx)
        ordinal = {b.key: i for i, b in enumerate(doc.blocks)}
        rows: list[dict[str, Any]] = []
        for ci in doc_chunks(doc):
            i = ordinal.get(ci.chunk_id, 0)
            rows.append(
                {
                    "seq": len(rows),
                    "chunk_id": ci.chunk_id,
                    "src_file": "index.html",
                    "byte_start": i,
                    "byte_end": i,
                    "kind": ci.kind,
                    "src_text": ci.content,
                }
            )
        return rows

    # ------------------------------------------------------------ scans/frag 桥

    async def _ensure_scans(self, ctx: TaskCtx) -> None:
        """Resume 桥：html 链无 ``ScanResult``——补的是 ``ctx.html_doc``。"""
        if ctx.row["kind"] != "arxiv_html":
            await super()._ensure_scans(ctx)
            return
        if ctx.html_doc is None:
            await self._to_thread(ctx, self._html_doc)

    def _ph_frag_map(self, ctx: TaskCtx) -> dict[str, dict[str, str]]:
        """``chunk_id → ph_fragments`` 的 DOM 版（块内 token→原 HTML 片段）。

        ``_stage_translate`` 零改动靠本覆盖：repair 臂
        ``recover_copied_tokens`` 对 ``[[MATH_n]]`` 等 token 的抄回
        修复与 TeX 路同口径武装。
        """
        if ctx.row["kind"] != "arxiv_html":
            return super()._ph_frag_map(ctx)
        doc = ctx.html_doc
        if doc is None:
            return {}
        return {b.key: dict(b.ph) for b in doc.blocks if b.ph}

    # ------------------------------------------------------------ emitting 段

    async def _run_html(self, ctx: TaskCtx) -> None:
        """arxiv_html 主链（对位 ``_run_tex``）：fetch → parse → translate → emit。

        无 share 对账臂（HTML chunk 与 share 包的 TeX chunk 不对版——
        共享寻址不接 DOM 链）、无编译/fixloop。
        """
        ctx.root.mkdir(parents=True, exist_ok=True)
        await self._stage_fetch(ctx)
        if ctx.reuse_hit is not None:
            return
        await self._stage_parse(ctx)
        await self._stage_translate(ctx)
        await self._stage_emit_html(ctx)

    async def _stage_emit_html(self, ctx: TaskCtx) -> None:
        """Compiling 对位段：序列化 en/zh DOM + dual.json + 终态。

        进度刻度复用 ``PROGRESS["compiling"]``（90→99）——前端步进枚举
        改名成本远大于收益，message 层区分（"生成阅读页"）。
        """
        self._stage(ctx, "compiling", "生成阅读页", PROGRESS["compiling"][0])
        await self._to_thread(ctx, self._emit_html_dom)
        self._check_cancelled(ctx)
        await self._to_thread(ctx, self._build_dual_html)
        if self._current_status(ctx) in TERMINAL_STATUSES:
            return  # cancel 竞态守卫同 _stage_compile
        failed = self.store.chunk_counts(ctx.task_id)["failed"]
        status, err = (
            ("done", None)
            if failed == 0
            else (
                "partial",
                {
                    "code": "translate",
                    "message": "有块级失败，译文 HTML 部分生成",
                    "retryable": True,
                },
            )
        )
        self.store.transition(
            ctx.task_id,
            status,
            progress=100,
            error=err,
            force=True,
            message="完成" if status == "done" else "部分完成",
        )
        self.bus.publish(
            ctx.task_id,
            "done",
            {
                "status": status,
                "artifacts": self._artifact_urls(ctx),
                "stats": self._stats(ctx),
            },
        )

    def _emit_html_dom(self, ctx: TaskCtx) -> None:
        """序列化双侧 DOM 产物（worker 线程）。

        ``marked_html`` 同源枚举注 ``data-chunk`` → 双侧 sanitize +
        URL 绝对化；zh 侧每 ``[data-chunk=chunk_id]`` 元素内文换
        ``reinsert(translation)``——fallback/failed 块落 ``src_text``
        （token 回插后等价原文片段，降级语义同 TeX 路 splice）。
        """
        self._abort_if_cancelled(ctx)
        html = (ctx.src_dir / "index.html").read_text(encoding="utf-8")
        marked = _w.marked_html(html)
        # ph 片段取自 marked 文档再解析——note 等被标记元素进片段时自带
        # data-chunk：宿主块回插还原的 note 副本仍带锚，footnote 译文
        # 换子树才找得到（用 parse 期 ph_map 则还原件无锚，note 行全 missed）
        ph_map = _w.parse_arxiv_html(marked).ph_map
        base_url = f"https://arxiv.org/html/{ctx.row['arxiv_id']}/"
        en = BeautifulSoup(marked, "lxml")
        self._sanitize_dom(en, base_url)
        (ctx.root / "en.html").write_text(str(en), encoding="utf-8")
        self._register(ctx, "en_html", "en.html")
        zh = BeautifulSoup(marked, "lxml")
        self._sanitize_dom(zh, base_url)
        # 一遍 find_all 建锚索引——逐行 zh.find 是 O(块×树) 全扫；
        # setdefault 保 first-match（footnote 包装层内可嵌同锚元素，
        # find 的文档序首个语义不能变）
        zh_index: dict[str, Any] = {}
        for el in zh.find_all(attrs={"data-chunk": True}):
            zh_index.setdefault(str(el["data-chunk"]), el)
        missed = 0
        for r in self._on_loop(self.store.all_chunks, ctx.task_id):
            self._abort_if_cancelled(ctx)  # 逐行回插轮询——大块数是秒级段
            key = str(r["chunk_id"])
            el = zh_index.get(key)
            if el is not None and not _attached_to(zh, el):
                # 宿主块 clear 会把锚元素整棵摘出，reinsert 还原的副本
                # 才是活锚（footnote 场景）——活树重查并回填索引
                el = zh.find(attrs={"data-chunk": key})
                if el is not None:
                    zh_index[key] = el
            if el is None:
                missed += 1  # 合成键在一次 marked_html 内稳定——缺失=契约违反
                continue
            text = str(r["translation"] or r["src_text"] or "")
            frag = BeautifulSoup(reinsert(text, ph_map), "html.parser")
            target = el
            if "ltx_note" in (el.get("class") or []):
                # footnote 锚注在整个 note span 上，译文只覆盖 content 子树——
                # 整 clear 会连 mark/触发包装一起丢（点击展开 UX 失效）
                target = el.find(class_="ltx_note_content") or el
            target.clear()
            for node in list(frag.contents):
                target.append(node)
        if missed:
            self._log(ctx, f"emit: {missed} 块无 data-chunk 锚——译文未回插")
        (ctx.root / "zh.html").write_text(str(zh), encoding="utf-8")
        self._register(ctx, "zh_html", "zh.html")

    def _sanitize_dom(self, soup: BeautifulSoup, base_url: str) -> None:
        """产物 DOM 服务端净化 + URL 绝对化（DomPane DOMPurify 是第一道防线之配）。

        剥活性内容（``_DROP_TAGS`` + ``on*`` 事件属性 + 危险 scheme
        URL）；``src``/``href`` 系相对路径经 ``urljoin`` 绝对化到
        ``arxiv.org/html/{id}/``——图仍热链 arXiv，离线降级 alt 文本。
        """
        for tag in soup.find_all(list(_DROP_TAGS)):
            tag.decompose()
        for el in soup.find_all():
            for attr in list(el.attrs):
                if attr.lower().startswith("on"):
                    del el[attr]
            for attr in _URL_ATTRS:
                v = el.get(attr)
                if not isinstance(v, str) or not v:
                    continue
                if _bad_url(el.name, v):
                    del el[attr]
                elif not v.startswith(("http://", "https://", "#", "mailto:")):
                    el[attr] = urljoin(base_url, v)
            srcset = el.get("srcset")
            if isinstance(srcset, str) and srcset.strip():
                el["srcset"] = _abs_srcset(el.name, srcset, base_url)

    def _build_dual_html(self, ctx: TaskCtx) -> None:
        """dual.json html 变体（对位 ``_build_dual``）。

        ``documents.{original,translated}`` = ``{version: sha256, pages:
        n_blocks}``——``pages`` 承载标记块数喂 ReaderDoc.pages；
        ``alignment`` 恒 ``{"kind": "pages"}``：``[data-chunk]`` 序双侧
        1:1，mapper 的 pages 退化臂即同序映射。``chunks`` 段与 tex 路
        同构（all_chunks 行直出）。
        """
        self._abort_if_cancelled(ctx)
        files = self._on_loop(self.store.files, ctx.task_id)
        rows = self._on_loop(self.store.all_chunks, ctx.task_id)
        doc: dict[str, Any] = {"version": 1, "documents": {}, "chunks": []}
        n_pages = len(self._html_doc(ctx).blocks)
        en = files.get("en_html")
        zh = files.get("zh_html")
        if en:
            doc["documents"]["original"] = {
                "version": en.get("sha256") or "",
                "pages": n_pages,
            }
        if zh:
            doc["documents"]["translated"] = {
                "version": zh.get("sha256") or "",
                "pages": n_pages,
            }
        doc["alignment"] = {"kind": "pages"}
        doc["chunks"] = [
            {
                "seq": r["seq"],
                "src_file": r["src_file"],
                "en": r["src_text"],
                # TEXT 列动态类型可落 BLOB——非 str 译文按空 coerce，
                # 不让单格 atomic_json TypeError 挡掉 dual.json 落盘
                "zh": r["translation"] if isinstance(r["translation"], str) else "",
                "kind": r["kind"],
            }
            for r in rows
        ]
        atomic_json(ctx.root / "dual.json", doc)
        self._register(ctx, "dual_json", "dual.json")
