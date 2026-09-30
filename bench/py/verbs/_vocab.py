"""Status vocabulary — the verbs' single source of truth.

Verbatim lift of benchlib's status tables (benchlib dies with the Wave-F
deletion gate; verbs must not import it). Keep semantics identical —
triage 票口径、rundiff 迁移序、gate 覆盖闸全部钉这张表。

跨叶共享词表（DONE/RETRIABLE/STATUS_RANK/TERMINAL_WORDS）一律别名
``kernel.events`` 单源——verbs→kernel 合法且词表是全栈最不该漂的口径；
本叶自有词（OK/SKIP/RESCUED/COMPILED/errors_sig）仍在此声明。
"""

from kernel import events

BENCH_ERROR_STATUS = "bench_error"

#: 记录状态词汇：ok 系不出票; skip 系 (上游断/policy 拒) 不计入 attempted。
OK_STATUS = {"ok", "clean", "done"}
SKIP_STATUS = {
    "skip",
    "skipped",
    "reject",
    "rejected",
    "upstream_fail",
    # e2e_real 旧账遗留词（LEGACY_ARM_MAP 流入 triage 同口径）
    "skipped_oversize",
    BENCH_ERROR_STATUS,
}
#: fixloop 救援成功的终态 (含带伤出 pdf)。
RESCUED_STATUS = {
    "ok",
    "clean",
    "acceptable_pdf",
    "best_effort_pdf",
    "dirty_pdf",
    "partial",
}
#: fixloop 终态词 → core 单 (规则面之外的引擎缺口)。单源 kernel/events.py。
TERMINAL_WORDS = events.TERMINAL_WORDS

#: 状态序数表 (高=好): fixloop_degraded 跨段退化判定与 rundiff 逐格迁移共用;
#: 表外词 (skip/error/...) 一律按 -1 计。单源 kernel/events.py。
STATUS_RANK = events.STATUS_RANK

#: 落账即 done（skip/error 可重试）。单源 kernel/events.py。
DONE_STATUS = events.STATUS_DONE
RETRIABLE_STATUS = events.STATUS_RETRIABLE

#: gate_scorecard fix 覆盖门槛——真编译结果集（reject/skip 格的 fixloop 不计）。
COMPILED_STATUS = {"fail", "partial", "clean"}


def errors_sig(errors: list) -> str:
    """errors[0] → ``cat:pay`` 签名（triage 契约：ok 级无 sig）。"""
    if not isinstance(errors, (list, tuple)) or not errors:
        return ""
    e0 = errors[0]
    if not isinstance(e0, dict):
        return ""
    cat = str(e0.get("cat") or e0.get("code") or "error")
    pay = str(e0.get("payload") or "")
    return f"{cat}:{pay}".rstrip(":")
