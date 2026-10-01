"""worker.compile.artifacts — 交付产物叶 (worker.compile 域缝叶)。

编译尾段产出物：``dual.json``（documents 版本/pages + 页级 alignment
+ chunks + ph 反查表 + seqpos 预算）、``md.zip`` 降级产物（双语
markdown 包）与 zh.pdf ToUnicode cmap 补嵌。
"""

from __future__ import annotations

import zipfile
from typing import TYPE_CHECKING, Any

from texlate.repair import (
    embed_tounicode_quiet,
)
from texlate.server.upload import (
    _md_member,
    pdf_pages,
)
from texlate.server.worker import seams
from texlate.server.worker._common import (
    zh_slot,
)
from texlate.server.worker.html import (
    _dual_chunk_row,
)
from texlate.xlat.state import atomic_json

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.server.store import Store
    from texlate.server.worker._common import TaskCtx


class _CompileArtifacts:
    """交付产物 mixin：dual.json/md.zip 落盘登记 + ToUnicode 补嵌。"""

    if TYPE_CHECKING:
        # 组合根 ``worker._Core.__init__`` 注入的共享态契约
        store: Store

    def _embed_tounicode(self, ctx: TaskCtx, pdf: Path) -> None:
        """``repair.embed_tounicode_quiet`` 委托——失败经 ``on_error`` 落任务日志。"""
        n = embed_tounicode_quiet(
            pdf,
            on_error=lambda e: self._log(
                ctx, f"tounicode embed failed: {type(e).__name__}: {e}"
            ),
        )
        if n:
            self._log(ctx, f"tounicode: {n} 个 GB1 CJK 字体补 ToUnicode cmap")

    def _build_dual(self, ctx: TaskCtx) -> None:
        """dual.json（§5.4）：documents 版本/pages + 页级 alignment + chunks。

        调用方 ``_to_thread`` 起（pdf_pages/build_alignment 扫
        content stream 是 CPU 重活）——store 读一律 ``_on_loop`` 回弹。
        """
        self._abort_if_cancelled(ctx)
        files = self._on_loop(self.store.files, ctx.task_id)
        doc: dict[str, Any] = {"version": 1, "documents": {}, "chunks": []}
        en = files.get("en_pdf")
        zh = files.get("zh_pdf")
        if en:
            doc["documents"]["original"] = {
                "version": en.get("sha256") or "",
                "pages": pdf_pages(ctx.root / en["path"]),
            }
        if zh:
            doc["documents"]["translated"] = {
                "version": zh.get("sha256") or "",
                "pages": pdf_pages(ctx.root / zh["path"]),
            }
        # named-dest 单调链锚点同步（texlate.align）；缺侧/无公共锚 → 同页映射
        doc["alignment"] = (
            seams.build_alignment(ctx.root / en["path"], ctx.root / zh["path"])
            if en and zh
            else {"kind": "pages"}
        )
        # 占位符 → 原文体表：eprint 链 chunk 文本带 ``[[TYPE_n]]`` 掩码——
        # 阅读面（HtmlPane md 渲染）要 ph 反查真实公式/引用再渲 KaTeX。
        # scans 缺场（resume 直进编译段）尽力重解析；拿不到就缺省——
        # 前端对无 ph 的 token 降级成样式 chip，不挡 dual 落盘。
        if not ctx.scans:
            try:
                _rows, ctx.scans = self._parse_all(ctx)
            except Exception as e:  # noqa: BLE001 -- 源已清/重解析失败不挡落盘
                self._log(ctx, f"dual ph reparse failed: {e}")
        frag_of: dict[str, dict[str, str]] = {}
        if ctx.scans:
            try:
                frag_of = self._ph_frag_map(ctx)
            except Exception as e:  # noqa: BLE001
                self._log(ctx, f"dual ph frag map failed: {e}")
        for r in self._on_loop(self._all_chunks, ctx):
            # 行投影与 html 链 ``_build_dual_html`` 同件——zh 位
            # coerce/非 ok 留空口径在 ``_dual_chunk_row`` docstring
            ch = _dual_chunk_row(r)
            ph = frag_of.get(r["chunk_id"])
            if ph:
                ch["ph"] = ph
            doc["chunks"].append(ch)
        atomic_json(ctx.root / "dual.json", doc)
        self._register(ctx, "dual_json", "dual.json")
        # seqpos 预算：reader 首开的懒算峰（39pp 实测 ~11s pypdf CMap
        # 重解析）挪进编译尾段——此处本就在 _to_thread 里，首开即缓存命中
        try:
            from texlate.server.seqpos import seqpos_for_task  # noqa: PLC0415

            seqpos_for_task(ctx.root, doc)
        except Exception as e:  # noqa: BLE001 -- 对位是增强件，失败不挡交付
            self._log(ctx, f"seqpos precompute failed: {e}")

    def _build_md_zip(self, ctx: TaskCtx) -> None:
        """md.zip 降级产物（§5.4）：编译彻底失败但译文在库 → 双语 markdown 包。

        ``view:"html"`` 的登记物——HtmlPane 实读 dual.json ``chunks``，本包
        是同数据的可下载形态（按 ``src_file`` 章节化、seq 锚注释保留 1:1
        对账位）。零译文不产：登记了而 chunks 无料会让前端落 empty 态。
        只在 ``_stage_compile`` 无 pdf 终态分支调用，此处 dual.json 已落。
        """
        self._abort_if_cancelled(ctx)
        rows = self._on_loop(self._all_chunks, ctx)
        # 同 dual.json zh 位口径——非 ok/非 str 译文行不算译文载荷，
        # zh 槽全空即「零译文不产」
        if not rows or not any(zh_slot(r) for r in rows):
            return
        by_file: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            by_file.setdefault(str(r["src_file"]), []).append(r)
        seen: set[str] = set()
        with zipfile.ZipFile(ctx.root / "md.zip", "w", zipfile.ZIP_DEFLATED) as zf:
            for src_file in sorted(by_file):
                parts = [
                    f"<!-- chunk:{r['seq']} kind:{r['kind']} -->\n\n"
                    f"{r['src_text']}\n\n---\n\n"
                    f"{zh_slot(r)}\n"
                    for r in sorted(by_file[src_file], key=lambda x: int(x["seq"]))
                ]
                zf.writestr(_md_member(src_file, seen), "\n".join(parts))
        self._register(ctx, "md_zip", "md.zip")
        self._log(ctx, f"md.zip: {sum(len(v) for v in by_file.values())} chunks")
