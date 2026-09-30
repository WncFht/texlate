"""worker.compile.en — en.pdf 臂叶 (worker.compile 域缝叶)。

原文侧编译链：``build-en`` 一次性树 copytree + seq 锚 identity 注锚
+ 编译 + fixloop 基建救援 + 截断残件判定（``_en_died``）+ en 侧
错误签名基线快照（``_en_err_sigs`` 供 zh L2 归因）。
"""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING

from texlate.compile.judge import (
    log_died_mid_doc,
)
from texlate.latex.reconstruct import (
    reconstruct,
    seq_mark_issues,
    strip_seq_marks,
)
from texlate.repair_l2 import (
    err_signatures,
    err_signatures_text,
)
from texlate.server.worker.compile.splice import _seq_marks_on

if TYPE_CHECKING:
    from pathlib import Path

    from texlate.compile.engine import (
        CompRes,
    )
    from texlate.server.worker._common import TaskCtx


class _CompileEn:
    """en.pdf 臂 mixin：原文编译 + 注锚 + 残件闸 + 错误签名基线。"""

    def _compile_en(self, ctx: TaskCtx) -> None:
        """en.pdf：base/ 拷贝编译 + fixloop 基建救援；失败只记 warning（不阻塞译文链）。

        原文无译文伤——L2 不归此臂；不出 pdf 时 fixloop 修基建（缺包/字体/
        工具链）再登记。修复只动 ``build-en`` 一次性树，不回灌 ``base/``
        （``base`` 是 zh 重建与 fixloop baseline 的 pristine 源）。
        """
        self._abort_if_cancelled(ctx)
        if self._has_pdf(ctx, "en_pdf"):
            return
        work = ctx.root / "build-en"
        if work.exists():
            shutil.rmtree(work)
        shutil.copytree(ctx.base_dir, work)
        self._en_mark_inject(ctx, work)
        rep = self._probe_target(ctx, work)
        eng = self._engine(ctx)
        res = eng.compile(
            work,
            ctx.main_rel,
            timeout=self._compile_timeout,
            sandbox=True,
            flags=rep.flags if rep else None,
            should_cancel=ctx.cancel_flag.is_set,
        )
        # eng.compile 是原子段（无插桩点）——跑完即收敛，后续 diff/登记是白费
        self._abort_if_cancelled(ctx)
        self._probe_diff(ctx, rep, res)
        # en 首编错误签名快照 → zh L2 归因基线：源生错签名不归 chunk
        # （fixloop_en 前置取——救回前全量；救回修复的源生错 zh 侧同样
        # 修得动，留在基线里不会误豁免译文伤）
        ctx.en_err_sigs = err_signatures(res)
        if (not res.has_pdf or self._en_died(res)) and self._fixloop_enabled(ctx):
            res = self._fixloop_en(
                ctx,
                work,
                eng,
                res,
                probe_flags=[str(f) for f in (rep.flags if rep else [])],
            )
        if res.has_pdf and res.pdf is not None:
            shutil.copyfile(res.pdf, ctx.root / "en.pdf")
            self._register(ctx, "en_pdf", "en.pdf")
            if self._en_died(res):
                self._warning(
                    ctx,
                    "en_compile",
                    "原文编译中途死亡，en.pdf 为截断残件（fixloop 未救回）",
                )
        else:
            self._warning(
                ctx,
                "en_compile",
                f"原文编译未出 pdf（{res.log.first_error or res.stdout_tail[:120]}）",
            )

    def _en_mark_inject(self, ctx: TaskCtx, work: Path) -> None:
        """en.pdf 注锚：identity reconstruct。

        translations=None → 原文逐字节，只叠 /TLXC marked-content——seq
        口径与 _build_zh 同序累计，双侧 seq 对位一致。谓词拒绝/失衡文件
        剥锚留原文，注锚异常不挡编译。
        """
        marks_on = _seq_marks_on(ctx.options())
        if not marks_on or not ctx.scans:
            return
        seq0 = 0
        n_marked = 0
        for rel, res in ctx.scans.items():
            cur0 = seq0
            seq0 += len(res.chunks)  # 无条件累计——与 zh 侧同序保 seq 对位
            if not res.chunks:
                continue
            try:
                out = reconstruct(res, None, mark_seq0=cur0, mark_moving=True)
            except Exception as e:  # noqa: BLE001 -- 注锚失败=原样编译
                self._log(ctx, f"seqmarks-en {rel} 注锚异常({e})——原样编译")
                continue
            if issues := seq_mark_issues(out):
                self._log(
                    ctx,
                    f"seqmarks-en {rel} 失衡({'; '.join(issues)})——剥锚降级",
                )
                out = strip_seq_marks(out)
            (work / rel).write_text(out, encoding="utf-8")
            n_marked += 1
        self._log(ctx, f"seqmarks-en: {n_marked} files marked")

    def _en_died(self, res: CompRes) -> bool:
        """en.pdf 截断收编闸判定。

        e116 实证：en 编译 35 页死亡、残件 pdf 因 ``has_pdf`` 非空被无条件
        登记。``Output written`` 截断照印不可信，可信信号 = 致命中止签名
        （``judge.log_died_mid_doc`` 单源，含 ``makes 100 errors`` 硬顶）
        ∪ 外部截杀/超时（``killed_signal``/``timed_out`` 无签名残件）。
        出 pdf 但死了 → 照样进 fixloop 救；救不回登记时记 warning。
        """
        return bool(res.has_pdf) and (
            bool(log_died_mid_doc(self._log_text_of(res)))
            or res.killed_signal is not None
            or bool(res.timed_out)
        )

    def _en_err_sigs(self, ctx: TaskCtx) -> set[str]:
        """基线错误签名集（en 侧）——``_compile_en`` 已快照则直取，否则回扫 ``build-en`` 残存 .log。

        resume/dedup 路径 en 不重编但签名仍要。
        """
        if ctx.en_err_sigs:
            return ctx.en_err_sigs
        work = ctx.root / "build-en"
        if work.is_dir():
            for lf in sorted(work.rglob("*.log")):
                try:
                    text = lf.read_text(errors="replace")
                except OSError:
                    continue
                ctx.en_err_sigs = err_signatures_text(text, project_root=work)
                if ctx.en_err_sigs:
                    break
        return ctx.en_err_sigs
