// liveFrames —— SSE 帧 → TaskLive 派生态的纯归约件。
// 自 tasks.ts 拆出：帧折叠（chunk delta 合并 / fixloop 轮次 upsert /
// logfix 归一）与传输编排无相互依赖，vitest 可绕开 store 直测归约层。

import type {
    ChunkEvent,
    ChunkItem,
    DoneEvent,
    FixloopEvent,
    FixloopRound,
    LogfixEvent,
    LogEvent,
    StageEvent,
    TaskErrorEvent,
    TransportState,
    WarningEvent,
} from "../api/client";

/** fixloop 修复循环 live 面：round 帧逐轮累积，done 帧落定 verdict/floor_restored */
export interface FixloopLive {
    rounds: FixloopRound[];
    verdict?: string;
    floor_restored?: boolean;
    done: boolean;
}

/** logfix 校验重译 live 面：整帧存，phase 缺省按 done 归一 */
export interface LogfixLive {
    phase: string;
    message?: string;
    enabled?: boolean;
    errors?: number;
    retranslated?: number;
    fallback?: number;
}

export interface TaskLive {
    stage?: StageEvent;
    /** 阶段事件历史（按到达序，阶段时间线用） */
    stages: StageEvent[];
    chunk?: ChunkEvent;
    /** dense 数组：index=seq，跨 chunk 帧累积合并（棋盘格数据源） */
    chunkItems: ChunkItem[];
    logs: LogEvent[];
    warnings: WarningEvent[];
    error?: TaskErrorEvent;
    done?: DoneEvent;
    fixloop?: FixloopLive;
    logfix?: LogfixLive;
    transport: TransportState;
}

//: 病态 seq 上限——超大 seq 帧防填洞 OOM（真实 chunks 量阶远低）
export const MAX_CHUNK_SEQ = 100_000;

/** chunk delta 单段合法性（seq 整数、0≤seq≤cap）——merge/增量写共用口径 */
export function chunkItemOk(it: ChunkItem, cap: number): boolean {
    return Number.isInteger(it.seq) && it.seq >= 0 && it.seq <= cap;
}

export const chunkCap = (limit?: number) =>
    limit == null ? MAX_CHUNK_SEQ : Math.min(limit, MAX_CHUNK_SEQ);

/**
 * chunk delta 合并的 mutating 核——mergeChunkItems 的规则直接落在已有
 * 数组上：非法 seq（<0/非整数/>cap）丢弃、越界空洞补 pending 占位、
 * 按 seq 落位。produce draft 调用方（tasks.ts 帧归约）省一次 slice。
 */
export function mergeChunkItemsInto(
    items: ChunkItem[],
    delta: ChunkItem[],
    cap: number,
): void {
    for (const it of delta) {
        if (!chunkItemOk(it, cap)) continue;
        while (items.length < it.seq)
            items.push({ seq: items.length, status: "pending" });
        items[it.seq] = it;
    }
}

/**
 * chunk 事件 items[] 只带变化段——按 seq 覆盖合并进 dense 数组；
 * 越界空洞补 pending 占位。非法 seq（<0/非整数/>limit/>MAX_CHUNK_SEQ）
 * 丢弃；limit 传 e.total——0/1 基两种约定下 seq>total 均越界。
 */
export function mergeChunkItems(
    prev: ChunkItem[],
    delta: ChunkItem[],
    limit?: number,
): ChunkItem[] {
    const next = prev.slice();
    mergeChunkItemsInto(next, delta, chunkCap(limit));
    return next;
}

/**
 * fixloop 帧折叠：round 帧按 round.round upsert 进 rounds；done 帧落定
 * verdict/floor_restored（cell 兼容旧服务端裸 cell 平铺顶层）。
 * 非法 round 帧（phase="round" 却无 round 载荷）返回 null——折叠层
 * 不物化空面板，调用方跳过写。
 */
export function foldFixloop(
    prev: FixloopLive | undefined,
    e: FixloopEvent,
): FixloopLive | null {
    if (e.phase === "round") {
        const r = e.round;
        if (!r) return null;
        const cur = prev ?? { rounds: [], done: false };
        const rounds = cur.rounds.slice();
        const i = rounds.findIndex((x) => x.round === r.round);
        if (i >= 0) rounds[i] = r;
        else rounds.push(r);
        return { ...cur, rounds };
    }
    const cell = e.cell ?? e;
    return {
        rounds: cell.rounds ?? prev?.rounds ?? [],
        verdict: cell.verdict,
        floor_restored: cell.floor_restored,
        done: true,
    };
}

/** logfix 帧归一：phase 缺省按 done（旧服务端只发一次结果负载） */
export function normalizeLogfix(e: LogfixEvent): LogfixLive {
    return {
        phase: e.phase ?? "done",
        message: e.message,
        enabled: e.enabled,
        errors: e.errors,
        retranslated: e.retranslated,
        fallback: e.fallback,
    };
}
