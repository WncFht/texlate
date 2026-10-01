"""``texlate.pipecore.chain`` — 修复链编排叶（``pipecore`` 拆分叶）。

``baseline_snapshot``：翻前 pristine 树快照 → fixloop ``baseline_dir``
注入件；``repair_chain``：precheck 预检 → logfix 回灌 → fixloop 三级直铺
编排——顺序是设计约束（precheck 先消 missing_file 基建失败，logfix 先于
fixloop 防 resplice 冲掉 regex_rewrite），三个 ``*_job`` 件各自吞崩
成 error dict，修复臂崩不毁主报告。

门面回引名单见 ``texlate.pipecore._LEAF_EXPORTS``。
monkeypatch 锚点：setattr patch 须指本叶，指门面无效。
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from texlate.pipecore._logfix import logfix_job
from texlate.pipecore.fixloop import fixloop_job
from texlate.pipecore.policy import RepairPolicy, precheck_reject
from texlate.pipecore.tail import compile_judge_tail, precheck_job
from texlate.repair import ENV_NO_FIXLOOP, ENV_NO_LOGFIX

if TYPE_CHECKING:
    from texlate.compile.engine import CompRes
    from texlate.pipecore.tail import PipeJob
    from texlate.repair import TreeRun

log = logging.getLogger(__name__)


def baseline_snapshot(
    work: Path, *, enabled: bool
) -> tempfile.TemporaryDirectory | None:
    """翻前快照 → fixloop ``baseline_dir``（normalize 后/翻译前的 pristine 树）。

    e2e ``_baseline_snapshot``/worker ``ctx.base_dir`` 同位——原地翻译臂
    无常驻 base，``restore_support_from_src``/``slot_arg_revert`` 要它
    逐字节复原被写脏的 support 件。快照落系统 tempdir 防污染
    ``scan_tree``/编译枚举；``enabled=False``（fixloop 关）跳过省一次
    全树 copytree；copytree 失败降级 ``None``（修复臂旁路件，不该砸死
    主链）。

    返回的 ``TemporaryDirectory`` 是生命周期令牌——快照根在
    ``Path(td.name)/"base"``；调用方持有到修复链收敛（局部变量持到
    函数返回即随帧清理，也可 ``td.cleanup()`` 显式收）。
    """
    if not enabled:
        return None
    td = tempfile.TemporaryDirectory(prefix="texlate-baseline-")
    base = Path(td.name) / "base"
    try:
        shutil.copytree(work, base)
    except (OSError, shutil.Error) as e:
        log.warning("baseline snapshot failed (%s) → fixloop 无 baseline", e)
        return None
    return td


def repair_chain(  # noqa: PLR0913 -- 修复链开关面穿透 + 三级阶梯直铺
    rec: dict,
    job: PipeJob,
    run: TreeRun,
    res: CompRes,
    *,
    expect_cjk: bool,
    logfix_on: bool | None,
    fixloop_on: bool | None,
    logfix_max_chunks: int,
) -> CompRes:
    """非 clean 后的修复链：precheck 预检 → logfix 回灌 → fixloop；reports 直写 ``rec``。

    顺序是设计约束：precheck（装缺件，fixloop 第 0 招独立相）先消
    missing_file 类基建失败——它们进 logfix 归因面只会把块拖去重译/回退
    （``t_f74894ebc691aaf4`` algpseudocodex 实证）；logfix 回灌先于
    fixloop——fixloop 的 regex_rewrite 会被 logfix resplice 冲掉。
    三个 ``*_job`` 件各自吞崩成 error dict——修复臂崩不毁主报告。
    fixloop 只在仍非 clean 时跑。返回最新 ``CompRes`` 供 ToUnicode
    注入判产物。``engine_fn``/``route_engines``/``baseline_dir``/``sink``
    全收进 ``job``——e2e 构造时透传自家 ``e2e.engine_for`` 全局名保
    monkeypatch 缝（conftest RecordingEngine）。
    """
    policy = RepairPolicy.resolve(fixloop_on=fixloop_on, logfix_on=logfix_on)
    fl, logfix = policy.fixloop, policy.logfix
    sink = job.sink

    # —— 第 0 招：precheck 预检 (装缺件/解嵌套 tar/收割构建 flag) ——
    # precheck 相全是增量件不碰 .tex 源——对 resplice 安全。装上缺件或
    # 收割到 engine_flags 才重编 (空转省一发编译)；clean 即收工。
    # reject:<rid> 不重编不跑 logfix——路由拒绝交 fixloop 复现 + 跨引擎消费。
    pre_reject = False
    if fl:
        sink.event("stage", {"stage": "precheck"})
        pre = precheck_job(job)
        rec["precheck"] = pre
        pre_reject = precheck_reject(pre)
        pre_flags = [str(f) for f in pre.get("engine_flags") or []]
        if not pre_reject and (pre.get("installed") or pre_flags):
            pre_tail, res = compile_judge_tail(
                job,
                expect_cjk=expect_cjk,
                flags=pre_flags or None,
            )
            rec.update(pre_tail)
            if rec["status"] == "clean":
                return res

    if logfix and not pre_reject:
        sink.event("stage", {"stage": "logfix"})
        logfix_rep, res, logfix_tail = logfix_job(job, run, res, logfix_max_chunks)
        rec["logfix"] = logfix_rep
        if logfix_tail is not None:
            rec.update(logfix_tail)
    elif not logfix:
        rec["logfix"] = {"enabled": False, "reason": ENV_NO_LOGFIX}
    else:
        rec["logfix"] = {"enabled": False, "reason": "precheck_reject"}

    if rec["status"] != "clean" and fl:
        sink.event("stage", {"stage": "fixloop"})
        fl_rep, fl_tail, res = fixloop_job(
            job,
            res,
            timeout=job.timeout,
            expect_cjk=expect_cjk,
        )
        rec["fixloop"] = fl_rep
        if fl_tail is not None:
            rec.update(fl_tail)
    elif rec["status"] != "clean":
        rec["fixloop"] = {"enabled": False, "reason": ENV_NO_FIXLOOP}
    return res
