"""worker.compile.splice — zh 工程物化叶 (worker.compile 域缝叶)。

译文 splice 回 ``zh/`` 源码树 + ctex 注入 + ``zh-src.zip`` 登记，
以及 fixloop/logfix 改动回灌 ``zh/`` 的镜像同步件（``_sync_fixed_sources``
+ ``_seq_mark_scrub``）；``_delivered_map`` 是 chunks 表 → 交付映射
单源，``_seq_marks_on`` 是 seq 锚三级闸。
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from typing import TYPE_CHECKING, Any

from texlate.compile.inject import (
    InjectRejectError,
    prepare_chinese,
)
from texlate.compile.judge import (
    paired_slot_diff,
)
from texlate.latex.placeholder import PH_RX
from texlate.latex.reconstruct import (
    reconstruct,
    seq_mark_issues,
    strip_seq_marks,
)
from texlate.pipecore import (
    delivered_db,
)
from texlate.server.worker._common import (
    _FIXLOOP_SRC_EXTS,
    _SENTINELS,
    _new_usage_meter,
    _translator_clients,
    chunk_db_id,
    opt_bool,
)
from texlate.server.worker.share import _share_sourced
from texlate.textutil import env_flag
from texlate.textutil.osutil import (
    ENV_NO_RESID_SWEEP,
    ENV_NO_SEQ_MARKS,
    translator_mode,
)
from texlate.xlat.resid import sweep_tree

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from texlate.server.worker._common import TaskCtx
    from texlate.xlat.client import ChatClient

log = logging.getLogger(__name__)


def _seq_marks_on(options: dict[str, Any]) -> bool:
    """seq_marks 三级闸：``options`` 显式 > ``TEXLATE_NO_SEQ_MARKS`` env（缺省开）。"""
    return opt_bool(
        options, "seq_marks", lambda: not env_flag(ENV_NO_SEQ_MARKS, default=False)
    )


def _seq_mark_scrub(rel: str, suffix: str, src: bytes) -> bytes:
    """``.tex`` 回灌件的 seq 锚失衡 lint——BDC/EMC 不配平或 MCID 重复时剥全锚。

    fixloop 改写可能拆散 BDC/EMC 对或复制出重复 MCID（fileset_relocate
    同锚双份）；剥锚换编译面干净，锚面降级模糊匹配（pdf.js 对失衡本就
    容忍，此处是双保险不阻断）。
    """
    if suffix != ".tex" or b"TLXC" not in src:
        return src
    issues = seq_mark_issues(src.decode("utf-8", errors="replace"))
    if not issues:
        return src
    log.warning("seq marks imbalanced in %s (%s); stripped", rel, "; ".join(issues))
    return strip_seq_marks(src.decode("utf-8", errors="replace")).encode("utf-8")


def _sync_fixed_sources(work: Path, zh: Path) -> int:
    """Fixloop 改动回灌：``work`` 内 TeX 输入层文件 → ``zh/`` 镜像（含删除）。

    copytree 起点两侧一致，分叉只来自 fixloop 改写/落包/隔离——按
    ``_FIXLOOP_SRC_EXTS`` 同步并删除 ``zh/`` 侧多余源文件（rename 隔离
    类规则的删除语义）；``_*`` 前缀**目录**（_tect_out/_minted-*）与
    哨兵不进——顶层 ``_*.tex`` 这类下划线文件名是合法源件照常镜像。
    返回变更文件数。
    """
    keep: set[str] = set()
    n = 0
    for f in work.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(work)
        if (
            len(rel.parts) > 1 and rel.parts[0].startswith("_")
        ) or f.name in _SENTINELS:
            continue
        if f.suffix.lower() not in _FIXLOOP_SRC_EXTS:
            continue
        keep.add(rel.as_posix())
        dst = zh / rel
        src = _seq_mark_scrub(rel.as_posix(), f.suffix.lower(), f.read_bytes())
        if not dst.is_file() or dst.read_bytes() != src:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(src)
            n += 1
    for f in zh.rglob("*"):
        if not f.is_file():
            continue
        rel = f.relative_to(zh)
        # 排除口径 = ``_`` 前缀目录——copy 侧同口径故 keep 永不覆盖该类
        # 子树，删侧同排除防 zh/ 自带的产物目录（_tect_out 等）被当多余
        # 源清掉；顶层 ``_*`` 文件与常规模源件同走 keep 比对
        if (
            len(rel.parts) > 1 and rel.parts[0].startswith("_")
        ) or f.name in _SENTINELS:
            continue
        if f.suffix.lower() in _FIXLOOP_SRC_EXTS and rel.as_posix() not in keep:
            f.unlink()
            n += 1
    return n


def _delivered_map(rows: Iterable[dict[str, Any]]) -> dict[str, str]:
    """``all_chunks`` 行 → ``{chunk_id: 译文}`` 交付映射（``delivered_db`` 口径）。

    ``isinstance(str)`` 判与 ``zh_slot`` 同口径——TEXT 列可落 BLOB 等非
    str 腐格，放行进 splice/logfix 重译会把字节料写进 .tex 源树。
    """
    return {
        r["chunk_id"]: r["translation"]
        for r in rows
        if delivered_db(r["status"], r["translation"])
        and isinstance(r["translation"], str)
    }


class _CompileSplice:
    """zh 工程物化 mixin：译文 splice + ctex 注入 + zh-src.zip 登记。"""

    def _build_zh(self, ctx: TaskCtx) -> None:
        """回写 zh 工程：按 chunks 表译文 splice + ctex 注入 + zip 登记。"""
        self._abort_if_cancelled(ctx)
        if (ctx.zh_dir / ".splice-done").is_file():
            return
        if ctx.zh_dir.exists():
            shutil.rmtree(ctx.zh_dir)
        shutil.copytree(ctx.base_dir, ctx.zh_dir)
        rows = self._on_loop(self._all_chunks, ctx)
        trans = self._env_judge_filter(ctx, _delivered_map(rows), rows)
        marks_on = _seq_marks_on(ctx.options())
        # moving-arg 全量放行（废 .tex 面 RX 闸）：hyperref 常经 .cls/.sty 传递
        # 加载，.tex 扫描必漏检——漏检时同 MCID 被 .toc 重放成双 BDC，命中又
        # 误杀全部标题/图题锚。实证注入仅换 pdfstring 期 hyperref
        # "removing \special" 警告、编译无害（4 任务 zh.pdf 均产出）；目录/
        # 页眉重放出的重复 occurrence 由读侧 seqpos dedupe 收敛。
        n_files = 0
        seq0 = 0
        for rel, res in ctx.scans.items():
            self._abort_if_cancelled(ctx)  # 逐文件 reconstruct——大工程秒级段
            cur0 = seq0
            seq0 += len(res.chunks)  # 无条件累计——跳译文件 seq 仍占位
            by_int: dict[int, str] = {}
            for c in res.chunks:
                cid = chunk_db_id(rel, c.span.start, c.span.end)
                zh = trans.get(cid)
                if zh is not None:
                    by_int[c.id] = zh
            if not by_int:
                continue
            out = reconstruct(
                res,
                by_int,
                mark_seq0=cur0 if marks_on else None,
                mark_moving=marks_on,
            )
            if marks_on and (issues := seq_mark_issues(out)):
                self._log(ctx, f"seqmarks {rel} 失衡({'; '.join(issues)})——剥锚降级")
                out = strip_seq_marks(out)
            if notes := paired_slot_diff(res.vtex, out, rel):
                self._log(ctx, f"slotdiff {rel}: {'; '.join(notes)}")
            (ctx.zh_dir / rel).write_text(out, encoding="utf-8", newline="")
            ctx.leftover_ph += len(PH_RX.findall(out))
            n_files += 1
        self._log(ctx, f"splice: {n_files} files rewritten")
        self._abort_if_cancelled(ctx)  # 清扫臂烧 BYOK token——先核取消再烧
        self._resid_sweep(ctx)
        try:
            info = prepare_chinese(ctx.zh_dir, ctx.main_rel)
        except InjectRejectError:
            # F3 降级交付：译文已 splice——zh-src.zip 先落盘，再由
            # run() 归 partial+reject_at=inject（不落 .splice-done，
            # resume 重打重拒同态收敛）
            self._zip_zh(ctx)
            raise
        self._log(ctx, f"inject: {info}")
        # zip 先于哨兵：崩在 zip 里时 resume 会因无哨兵重建 zh/ 重打，
        # 反序则哨兵在、产物登记永远缺席
        self._zip_zh(ctx)
        (ctx.zh_dir / ".splice-done").write_text("", encoding="utf-8", newline="")

    def _resid_sweep(self, ctx: TaskCtx) -> None:
        """Splice 后 zh 树残英清扫补译——``resid.sweep_tree`` 的 worker 旁路接线。

        守门序与 ``_llm_hook_pack`` 同构：``_share_sourced``（零 token 承诺，
        共享字节须逐字一致）→ ``options.resid_sweep`` 显式关 →
        ``TEXLATE_NO_RESID_SWEEP`` → 无 BYOK ``api_key``/mock 形态不给裸
        env-key client（BYOK 计费面边界）。``cache=None``——段缓存 DB 读写
        有 loop 线程亲和（conn 单写者纪律），``_build_zh`` 在 ``_to_thread``
        工作线程上，``uniq`` run 内去重已覆盖同树重复段。清扫任何失败只留
        warning——残英段维持英文交付，不阻断编译链。
        """
        if _share_sourced(ctx):
            return
        opt = ctx.options().get("resid_sweep")
        if opt is not None and (
            opt is False or str(opt).strip().lower() in ("0", "false", "no", "off")
        ):
            return
        if env_flag(ENV_NO_RESID_SWEEP, default=False):
            return
        if self._translator_factory is None and (
            not ctx.secrets.api_key or translator_mode() == "mock"
        ):
            return
        clients: list[ChatClient] = []
        usage: dict[str, Any] | None = None
        try:
            if self._translator_factory is not None:
                tr = self._translator_factory(ctx)
                clients = _translator_clients(tr)
                usage = self._meter_usage(clients)
            else:
                usage, sink = _new_usage_meter()
                tr = self._resolve_translator(ctx, sink=sink, retry=False)
            metrics = self._run_ephemeral(
                clients, lambda: sweep_tree(ctx.zh_dir, tr)
            )
        except Exception:
            self._log(ctx, "resid_sweep 失败——残英段维持原文")
            log.warning("resid_sweep failed", exc_info=True)
        else:
            if metrics["spans"]:
                self._log(
                    ctx,
                    "resid_sweep: "
                    f"{metrics['replaced']}/{metrics['spans']} spans 补译"
                    f"（{metrics['kept_en']} 留原）",
                )
        finally:
            self._teardown_bypass(ctx, usage, clients, label="resid_sweep")

    def _zip_zh(self, ctx: TaskCtx) -> None:
        """``zh/`` → zh-src.zip 登记（fixloop 回灌后重打复用同一函数）。"""
        zip_path = ctx.root / "zh-src.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in sorted(ctx.zh_dir.rglob("*"), key=lambda p: p.as_posix()):
                self._abort_if_cancelled(ctx)
                if f.is_file() and f.name not in _SENTINELS:
                    zf.write(f, f.relative_to(ctx.zh_dir).as_posix())
        self._register(ctx, "zh_src_zip", "zh-src.zip")
