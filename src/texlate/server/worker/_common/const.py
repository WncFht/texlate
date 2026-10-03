"""常量表与表驱动小件域（自 ``_common`` 出叶）。

进度刻度 ``PROGRESS``、日志/缓存 flush 阈值、``KIND_URL``↔``URL_KIND``
产物 kind 双向映射（+``artifact_urls`` 快照生成）、fetch 终态白名单
``_FETCH_NO_RETRY``、哨兵面（``_SENTINELS``/``.compile-done`` verdict
读写）、splice 失效派生 kind 名单、probe 聚合截断/``dep_seen`` 三值标签、
fixloop 回灌扩展名白名单，及 chunks 行 ``_row_status_snap`` 对账快照。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from texlate.arxiv.fetch import AcquireStatus

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from texlate.server.store import Store

#: 进度刻度（§2.2：fetching 3→9 / parsing 9→25 / translating 25→85 /
#: compiling 90→99 / 终态 100）
PROGRESS = {
    "fetching": (3, 9),
    "parsing": (9, 25),
    "translating": (25, 85),
    "compiling": (90, 99),
}

#: chunk 落盘批量 flush 阈值（§3.4.2：每 8 块或 500ms）
_FLUSH_N = 8

_FLUSH_MS = 0.5

#: files.kind → URL kind（§2.3 白名单表）
KIND_URL = {
    "src_tar": "src.tar",
    "en_pdf": "en.pdf",
    "zh_pdf": "zh.pdf",
    "dual_pdf": "dual.pdf",
    "dual_json": "dual.json",
    "zh_src_zip": "zh-src.zip",
    "compile_log": "compile.log",
    "md_zip": "md",
    "zh_docx": "zh.docx",
    "zh_epub": "zh.epub",
    "src_html": "src.html",
    "en_html": "en.html",
    "zh_html": "zh.html",
    "share_zip": "share.zip",
}

#: URL kind → files.kind（反查）
URL_KIND = {v: k for k, v in KIND_URL.items()}


def artifact_urls(store: Store, task_id: str) -> dict[str, str]:
    """Files 行 → ``{db_kind: /api/files/{id}/{url_kind}}``（done 事件/快照共用面）。

    与 ``KIND_URL`` 同址共置——web 层快照（``routers/tasks``）与 worker
    终态帧（``_Events._artifact_urls``）消费的是同一映射，单源防漂移。
    未登记的 kind 按原名透传（``get(kind, kind)``）——新产物 kind 进库
    而未进 ``KIND_URL`` 时 URL 面照发不炸。
    """
    return {
        kind: f"/api/files/{task_id}/{KIND_URL.get(kind, kind)}"
        for kind in store.files(task_id)
    }


#: fetch 失败中重试无意义的终态
_FETCH_NO_RETRY = frozenset(
    {
        AcquireStatus.PDF_ONLY,
        AcquireStatus.UNKNOWN_FORMAT,
        AcquireStatus.TOO_LARGE,
        AcquireStatus.NOT_FOUND,
    }
)

#: 任务树内哨兵文件（断点恢复用，不进 zh-src.zip / fixloop 回灌）
_SENTINELS = frozenset({".fetch-done", ".base-done", ".splice-done", ".compile-done"})

#: ``.compile-done`` 载荷合法值——judge 终态三词；旧版空件/脏值读出 None
_COMPILE_VERDICTS = frozenset({"clean", "partial", "fail"})


def _write_compile_done(zh_dir: Path, status: str) -> None:
    """``.compile-done`` 哨兵带 verdict 载荷落盘。

    resume 重放终态判定不靠 ``has_pdf`` 猜（c32920 实证：verdict=fail 的
    死层 pdf 曾被哨兵 resume 直接计 ok→done 交付）。
    """
    (zh_dir / ".compile-done").write_text(status, encoding="utf-8", newline="")


def _compile_done_verdict(zh_dir: Path) -> str | None:
    """哨兵载荷 → verdict；空件（旧版）/脏值/不可读 → None 走复测臂。"""
    try:
        s = (zh_dir / ".compile-done").read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return s if s in _COMPILE_VERDICTS else None


#: splice 失效即作废的派生产物 kind——zh/ 及其下游（译文快照/编译物/
#: 降级包/已发布 share.zip 镜像）全随译文变更过期；en_pdf（base/ 编译）
#: 与 src_tar 不依赖 chunks，保留
_SPLICE_STALE_KINDS = (
    "zh_pdf",
    "zh_src_zip",
    "dual_json",
    "compile_log",
    "md_zip",
    "share_zip",
)


def _row_status_snap(rows: Iterable[dict[str, Any]]) -> dict[str, tuple[str, str]]:
    """Chunks 行 → ``{chunk_id: (status, translation)}`` 快照——splice 失效对账面。

    ``translate._translate_prep``/``_invalidate_splice`` 与 share 臂
    ``_stage_share_apply`` 三处同款的单源；BLOB/None 格统一
    ``str(... or "")`` coerce。
    """
    return {
        r["chunk_id"]: (str(r["status"]), str(r["translation"] or "")) for r in rows
    }


#: probe diff 聚合行的列表截断上限（一条行不刷屏，超出记 +N）
_PROBE_LIST_CAP = 8

#: ``dep_seen`` 三值 → missing 复核标签：recorded=曾被 .fls/.mk 记录（路径/
#: 时序问题，勿装包）；unseen=真缺失（fixloop install_file 候选）；
#: n/a=引擎未产依赖记录，不可判
_PROBE_SEEN_TAG: dict[bool | None, str] = {
    True: "recorded",
    False: "unseen",
    None: "n/a",
}

#: fixloop 回灌 zh/ 的 TeX 输入层扩展名——rewrite 目标面 + ctan_fetch
#: 平铺落盘面 + install_sysfont 可能投放的字体文件；编译产物
#: （aux/log/pdf/_tect_out/）不在列
_FIXLOOP_SRC_EXTS = frozenset(
    {
        ".tex",
        ".ltx",
        ".latex",
        ".sty",
        ".cls",
        ".bib",
        ".bst",
        ".def",
        ".cfg",
        ".clo",
        ".fd",
        ".tfm",
        ".vf",
        ".enc",
        ".map",
        ".pro",
        ".bbl",
        ".ist",
        ".ins",
        ".dtx",
        ".otf",
        ".ttf",
        ".ttc",
        ".pfb",
        ".afm",
    }
)
