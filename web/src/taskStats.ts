// 终态结果面板统计合成 —— done 帧 stats 优先、快照 counters/usage 兜底。
// usage（task_usage 聚合行）提供调用次数/prompt/completion/latency 细分；
// 老任务无 usage 行时退回总 tokens，stat 行各自独立缺席。

import type { DoneStats, TaskCounters, TaskUsage } from "./api/client";

export interface ResultStats {
    tokens?: number;
    seconds?: number;
    failed?: number;
    calls?: number;
    prompt?: number;
    completion?: number;
    latency?: number;
    /** 分阶段耗时（done.stats.stage_seconds：fetch/parse/translate/compile → 秒） */
    stageSeconds?: Record<string, number>;
    /** fixloop 判定串（done.stats.fixloop = cell.verdict） */
    fixloop?: string;
    /** L2 校验摘要（done.stats.l2 = {enabled,errors,retranslated,fallback}） */
    l2?: {
        enabled?: boolean;
        errors?: number;
        retranslated?: number;
        fallback?: number;
    };
}

/** 全字段缺席 → null（调用侧不渲染 stat-strip） */
export function mergeResultStats(
    stats?: DoneStats,
    counters?: TaskCounters,
    usage?: TaskUsage,
): ResultStats | null {
    const out: ResultStats = {
        tokens: stats?.tokens ?? counters?.tokens,
        seconds: stats?.seconds,
        failed: stats?.chunks_failed ?? counters?.failed,
        stageSeconds: stats?.stage_seconds as
            Record<string, number> | undefined,
        fixloop: typeof stats?.fixloop === "string" ? stats.fixloop : undefined,
        l2: stats?.l2 as ResultStats["l2"],
        calls: usage?.calls,
        prompt: usage?.prompt_tokens,
        completion: usage?.completion_tokens,
        latency: usage?.latency_s,
    };
    return Object.values(out).every((v) => v == null) ? null : out;
}
