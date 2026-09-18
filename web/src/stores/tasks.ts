// 任务列表/活动任务 store —— solid store 承载 §2 快照 + SSE 增量。

import { createStore, produce, reconcile } from "solid-js/store";
import {
    api,
    ApiError,
    forgetTaskEvents,
    isTerminal,
    liveSeqWatermark,
    openTaskEvents,
    type ChunkItem,
    type ChunkEvent,
    type DoneEvent,
    type FixloopRound,
    type LogEvent,
    type StageEvent,
    type TaskChannel,
    type TaskErrorEvent,
    type TaskSnapshot,
    type TransportState,
    type WarningEvent,
} from "../api/client";

/** fixloop 修复循环 live 面：round 帧逐轮累积，done 帧落定 verdict/floor_restored */
export interface FixloopLive {
    rounds: FixloopRound[];
    verdict?: string;
    floor_restored?: boolean;
    done: boolean;
}

/** L2 校验重译 live 面：整帧存，phase 缺省按 done 归一 */
export interface L2Live {
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
    l2?: L2Live;
    transport: TransportState;
}

//: 病态 seq 上限——超大 seq 帧防填洞 OOM（真实 chunks 量阶远低）
export const MAX_CHUNK_SEQ = 100_000;

/** chunk delta 单段合法性（seq 整数、0≤seq≤cap）——merge/增量写共用口径 */
function chunkItemOk(it: ChunkItem, cap: number): boolean {
    return Number.isInteger(it.seq) && it.seq >= 0 && it.seq <= cap;
}

const chunkCap = (limit?: number) =>
    limit == null ? MAX_CHUNK_SEQ : Math.min(limit, MAX_CHUNK_SEQ);

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
    const cap = chunkCap(limit);
    const next = prev.slice();
    for (const it of delta) {
        if (!chunkItemOk(it, cap)) continue;
        while (next.length < it.seq)
            next.push({ seq: next.length, status: "pending" });
        next[it.seq] = it;
    }
    return next;
}

interface TasksState {
    tasks: TaskSnapshot[];
    loaded: boolean;
    loadError?: string;
    live: Record<string, TaskLive>;
}

const [state, setState] = createStore<TasksState>({
    tasks: [],
    loaded: false,
    live: {},
});
const channels = new Map<string, TaskChannel>();
const pollers = new Map<string, ReturnType<typeof setInterval>>();
/** 观测意愿集：pin=显式 watch（reader 聚焦）优先占 SSE 槽 */
const wanted = new Map<string, { pin: boolean }>();
/**
 * 服务端终结的 SSE（readyState CLOSED ≈ HTTP 错——404 删行/5xx）：
 * ensureChannel 不得复活它们——复活即 404 重连循环（M6）。探活/轮询
 * 兜底在 probeAfterClose；resetLive（retry 新轮）与 dropTask 清除。
 */
const sseDead = new Set<string>();
/** watch 句柄按任务缓存——幂等 watch 返回同一对象（close→unwatch 语义） */
const watchHandles = new Map<string, TaskChannel>();

//: 同源 HTTP/1.1 每域 6 连接上限——SSE 每任务常开一条，占满则 API/PDF
//: 拉取全排队假死；窗口外非终态任务降级 interval 轮询 snapshot
export const MAX_SSE_TASKS = 3;
export const POLL_INTERVAL_MS = 3000;

const freshLive = (): TaskLive => ({
    stages: [],
    chunkItems: [],
    logs: [],
    warnings: [],
    transport: "connecting",
});

function ensureLive(taskId: string): void {
    setState("live", taskId, (l) => l ?? freshLive());
}

/**
 * 字段级写回行——行对象引用不变，TaskList 的 <For> 不整行重挂（M9）。
 * reconcile 对对象节点 in-place 合并：新增键落位、缺席键清 undefined
 * （快照语义——服务端不发即无此值）、等值叶不触写。
 */
function upsertTask(snap: TaskSnapshot) {
    const i = state.tasks.findIndex((t) => t.task_id === snap.task_id);
    if (i < 0) {
        setState("tasks", (list) => [snap, ...list]);
        return;
    }
    setState("tasks", i, reconcile(snap));
}

/** 终态收敛：释放 append-only 缓冲（logs/stages 会话内单调增长）；
 * done/chunk/chunkItems/warnings/error 留给终态面板与棋盘格；
 * fixloop/l2 同属终态面板材料——不清 */
function settleLive(taskId: string) {
    if (!state.live[taskId]) return;
    setState("live", taskId, "logs", []);
    setState("live", taskId, "stages", []);
}

/**
 * 终态收敛统一入口：合成 done 兜底 + settleLive + unwant。
 *
 * 非 done 帧探到终态时真实 done 帧可能永不到达——SSE snapshot(seq=0)
 * 恒先于重放段的 done 上电线，client 收终态即 close()，done 被丢在
 * 线路上；轮询/探活路径本就没有 done 帧。live.done 缺席 → Reader 的
 * `done && !info()` → loadReader 永不触发 → 终态任务永卡 loading。
 * snapshot.artifacts 与 done.artifacts 同源（server `_artifacts`）；
 * stats 缺键由 counters/usage 兜底（taskStats.mergeResultStats）。
 */
function convergeTerminal(taskId: string, s: TaskSnapshot) {
    ensureLive(taskId);
    if (!state.live[taskId]?.done)
        setState("live", taskId, "done", {
            status: s.status,
            // 拷一份再入 store——s.artifacts 与 reconcile 后的行 artifacts
            // 共用底层节点，直接写入会让后续 reconcile 改穿到 live.done
            artifacts: { ...(s.artifacts ?? {}) },
            stats: {},
        });
    settleLive(taskId);
    unwant(taskId);
}

function closeChannel(taskId: string) {
    const ch = channels.get(taskId);
    channels.delete(taskId);
    ch?.close();
}

function stopPoll(taskId: string) {
    const t = pollers.get(taskId);
    if (t !== undefined) {
        clearInterval(t);
        pollers.delete(taskId);
    }
}

/** 纯摘除观测意愿 + 关通道停轮询；调用方按需补 rebalance */
function unwant(taskId: string) {
    wanted.delete(taskId);
    closeChannel(taskId);
    stopPoll(taskId);
}

/** 任务行已删（本地 remove / 服务端 deleted 帧 / 轮询 404 / SSE 探活 404）——观测+状态+水位线全清 */
function dropTask(taskId: string) {
    sseDead.delete(taskId);
    watchHandles.delete(taskId);
    unwant(taskId);
    forgetTaskEvents(taskId);
    setState("tasks", (list) => list.filter((t) => t.task_id !== taskId));
    setState(
        "live",
        produce((l) => {
            delete l[taskId];
        }),
    );
}

function startPoll(taskId: string) {
    ensureLive(taskId);
    setState("live", taskId, "transport", "polling");
    if (pollers.has(taskId)) return;
    const tick = async () => {
        try {
            const s = await api.snapshot(taskId);
            if (!wanted.has(taskId)) return; // 已摘除——迟到响应不回写
            upsertTask(s);
            if (isTerminal(s.status)) {
                convergeTerminal(taskId, s);
                rebalance();
            }
        } catch (e) {
            if (e instanceof ApiError && e.status === 404) {
                dropTask(taskId);
                rebalance();
            }
            // 其余错误下轮再试
        }
    };
    pollers.set(
        taskId,
        setInterval(() => void tick(), POLL_INTERVAL_MS),
    );
    void tick();
}

/**
 * SSE 被服务端终结（探活兜底，M6）：snapshot 一次定去留——
 * 404 → 行已删 dropTask；终态 → 收敛摘除；仍在跑 → 降级轮询接着盯
 * （SSE 不再复活）；探活本身失败 → 轮询让 tick 侧慢慢判。
 */
async function probeAfterClose(taskId: string) {
    try {
        const s = await api.snapshot(taskId);
        if (!wanted.has(taskId)) return;
        upsertTask(s);
        if (isTerminal(s.status)) {
            convergeTerminal(taskId, s);
        } else {
            startPoll(taskId);
        }
    } catch (e) {
        if (!wanted.has(taskId)) return;
        if (e instanceof ApiError && e.status === 404) dropTask(taskId);
        else startPoll(taskId);
    }
    rebalance();
}

/** pin 优先、其后按任务 updated_at 新→旧占 SSE 槽 */
function orderedWanted(): string[] {
    const tasks = state.tasks;
    return [...wanted.keys()].sort((a, b) => {
        const pa = wanted.get(a)?.pin ? 1 : 0;
        const pb = wanted.get(b)?.pin ? 1 : 0;
        if (pa !== pb) return pb - pa;
        return (
            (tasks.find((t) => t.task_id === b)?.updated_at ?? 0) -
            (tasks.find((t) => t.task_id === a)?.updated_at ?? 0)
        );
    });
}

// 同步派发防护：handler 内 unwant→rebalance 可嵌套（测试假 EventSource
// 同步派发；浏览器里 ES 事件恒异步，本守卫仅兜测试面）——脏标记重跑
let rebalancing = false;
let rebalanceDirty = false;

/** SSE 槽分配：前 MAX_SSE_TASKS 个 wanted 开 EventSource，其余降级轮询 */
function rebalance() {
    if (rebalancing) {
        rebalanceDirty = true;
        return;
    }
    rebalancing = true;
    try {
        do {
            rebalanceDirty = false;
            const ids = orderedWanted();
            const sseIds = new Set(ids.slice(0, MAX_SSE_TASKS));
            for (const id of ids) {
                if (!wanted.has(id)) continue; // 派发中被摘除
                if (sseIds.has(id) && !sseDead.has(id)) {
                    stopPoll(id);
                    ensureChannel(id);
                } else {
                    // 槽外 / SSE 已被服务端终结——轮询通道
                    closeChannel(id);
                    startPoll(id);
                }
            }
        } while (rebalanceDirty);
    } finally {
        rebalancing = false;
    }
}

function ensureChannel(taskId: string): TaskChannel {
    const existing = channels.get(taskId);
    if (existing && !existing.closed) return existing;
    ensureLive(taskId);
    // 首连/重建都先报 connecting——reconnecting 专指传输错误后的自动重连
    setState("live", taskId, "transport", "connecting");
    const ch = openTaskEvents(taskId, {
        transport: (s) => {
            setState("live", taskId, "transport", s);
            // 服务端终拒（404 等 readyState=CLOSED）：仍 wanted 说明非本侧
            // 主动关——标记 sseDead 防 rebalance 复活，探活定去留
            if (s === "closed" && wanted.has(taskId) && !sseDead.has(taskId)) {
                sseDead.add(taskId);
                void probeAfterClose(taskId);
            }
        },
        resync: () => {
            // 重放缺口：水位线已被 client 重置——清 chunk 派生态（不可信），
            // 拉 snapshot 对齐任务面；SSE 仍活着，不降轮询
            if (!wanted.has(taskId)) return;
            setState("live", taskId, "chunk", undefined);
            setState("live", taskId, "chunkItems", []);
            void api
                .snapshot(taskId)
                .then((s) => {
                    if (!wanted.has(taskId)) return;
                    upsertTask(s);
                    if (isTerminal(s.status)) {
                        convergeTerminal(taskId, s);
                        rebalance();
                    }
                })
                .catch((e: unknown) => {
                    if (e instanceof ApiError && e.status === 404) {
                        dropTask(taskId);
                        rebalance();
                    }
                });
        },
        snapshot: (s) => {
            upsertTask(s);
            if (isTerminal(s.status)) {
                convergeTerminal(taskId, s);
                rebalance();
            }
        },
        stage: (e) => {
            setState("live", taskId, "stage", e);
            setState("live", taskId, "stages", (ss) => [...ss, e]);
            // 字段级补丁——行引用不变，<For> 不整行重挂（M9）
            const i = state.tasks.findIndex((t) => t.task_id === taskId);
            if (i >= 0) {
                setState("tasks", i, "status", e.stage);
                setState("tasks", i, "stage", e.stage);
                setState("tasks", i, "progress", e.progress);
                setState("tasks", i, "message", e.message);
            }
        },
        chunk: (e) => {
            setState("live", taskId, "chunk", e);
            // 增量写：只动帧携带的 seq——ProgressGrid 按格订阅，
            // 免每帧 slice+全量重建（P2）；越界空洞补 pending 占位
            const cap = chunkCap(e.total);
            for (const it of e.items) {
                if (!chunkItemOk(it, cap)) continue;
                const len = state.live[taskId]?.chunkItems.length ?? 0;
                for (let s = len; s < it.seq; s++) {
                    setState("live", taskId, "chunkItems", s, {
                        seq: s,
                        status: "pending",
                    });
                }
                setState("live", taskId, "chunkItems", it.seq, it);
            }
        },
        log: (e) =>
            setState("live", taskId, "logs", (ls) => [...ls.slice(-499), e]),
        warning: (e) =>
            setState("live", taskId, "warnings", (ws) => [...ws, e]),
        error: (e) => setState("live", taskId, "error", e),
        fixloop: (e) => {
            if (e.phase === "round") {
                const r = e.round;
                if (!r) return;
                setState("live", taskId, "fixloop", (f) => {
                    const cur = f ?? { rounds: [], done: false };
                    const rounds = cur.rounds.slice();
                    const i = rounds.findIndex((x) => x.round === r.round);
                    if (i >= 0) rounds[i] = r;
                    else rounds.push(r);
                    return { ...cur, rounds };
                });
                return;
            }
            // done 帧：cell 兼容旧服务端裸 cell（rounds/verdict 平铺顶层）
            const cell = e.cell ?? e;
            setState("live", taskId, "fixloop", (f) => ({
                rounds: cell.rounds ?? f?.rounds ?? [],
                verdict: cell.verdict,
                floor_restored: cell.floor_restored,
                done: true,
            }));
        },
        l2: (e) =>
            setState("live", taskId, "l2", {
                phase: e.phase ?? "done",
                message: e.message,
                enabled: e.enabled,
                errors: e.errors,
                retranslated: e.retranslated,
                fallback: e.fallback,
            }),
        done: (e) => {
            // DELETE 端点的收尾帧——本任务行已删，别回填成 "deleted" 僵尸行
            if (e.status === "deleted") {
                dropTask(taskId);
                rebalance();
                return;
            }
            setState("live", taskId, "done", e);
            const status = e.status;
            const i = state.tasks.findIndex((t) => t.task_id === taskId);
            if (i >= 0) {
                setState("tasks", i, "status", status);
                setState("tasks", i, "progress", 100);
                // 拷一份——e.artifacts 已随 live.done 入 store，同对象入
                // 第二路径会共用节点，后续 reconcile 会改穿 live.done
                setState("tasks", i, "artifacts", { ...e.artifacts });
            }
            settleLive(taskId);
            unwant(taskId);
            rebalance();
        },
    });
    channels.set(taskId, ch);
    return ch;
}

export const taskStore = {
    state,

    async refresh() {
        try {
            const list = await api.tasks();
            const byId = new Map(state.tasks.map((r) => [r.task_id, r]));
            // 列表行是请求发起时刻的旧读——在飞 SSE 事件已推进的行会被
            // reconcile 回退；行 last_seq 落后于已消费 seq（SSE 水位线∪
            // 行内 last_seq）→ store 现行行顶替。offset 翻页在并发插入
            // 下可能重复见行——task_id 去重兜底
            const seen = new Set<string>();
            const merged: TaskSnapshot[] = [];
            for (const t of list) {
                if (seen.has(t.task_id)) continue;
                seen.add(t.task_id);
                const cur = byId.get(t.task_id);
                merged.push(
                    cur !== undefined &&
                        Math.max(
                            liveSeqWatermark(t.task_id),
                            cur.last_seq ?? 0,
                        ) > (t.last_seq ?? 0)
                        ? cur
                        : t,
                );
            }
            // reconcile 按 task_id 匹配：在册行字段级合并（引用不变，
            // <For> 行不重挂）；新行插入、消失行移除——一次原子替换
            setState("tasks", reconcile(merged, { key: "task_id" }));
            setState("loaded", true);
            setState("loadError", undefined);
            const ids = new Set(merged.map((t) => t.task_id));
            for (const t of merged) {
                if (!isTerminal(t.status)) {
                    if (!wanted.has(t.task_id))
                        wanted.set(t.task_id, { pin: false });
                } else if (wanted.has(t.task_id)) {
                    // 列表回终态（done 帧可能未到/已丢）——收敛并摘除
                    convergeTerminal(t.task_id, t);
                }
            }
            // 列表里消失的非 pin 任务（别处已删）——停止观测；pin 的留着
            // （reader 可能在 retry 间隙，新快照未到）
            for (const [id, w] of [...wanted]) {
                if (!ids.has(id) && !w.pin) unwant(id);
            }
            rebalance();
        } catch (e) {
            setState({
                loaded: true,
                loadError: e instanceof Error ? e.message : String(e),
            });
        }
    },

    /**
     * 订阅任务（pin=聚焦优先占 SSE 槽；幂等——重复调用复用同一句柄）。
     * 句柄 close() 恒等于 unwatch：SSE 与轮询双轨同一 detach 语义（M2）。
     */
    watch(taskId: string): TaskChannel {
        wanted.set(taskId, { pin: true });
        rebalance();
        let h = watchHandles.get(taskId);
        if (!h) {
            h = {
                close: () => taskStore.unwatch(taskId),
                get closed() {
                    return !wanted.has(taskId);
                },
            };
            watchHandles.set(taskId, h);
        }
        return h;
    },

    /** 摘除观测（幂等公开）：close() 句柄与显式调用等价 */
    unwatch(taskId: string) {
        unwant(taskId);
        rebalance();
    },

    /** 本地补丁任务行（retry 后乐观更新；SSE snapshot 随后来覆盖为准）。
     *  逐字段写——行引用保持（M9）；undefined 值跳过（patch 只带要改的键） */
    patch(taskId: string, p: Partial<TaskSnapshot>) {
        const i = state.tasks.findIndex((t) => t.task_id === taskId);
        if (i < 0) return;
        for (const [k, v] of Object.entries(p)) {
            if (v === undefined) continue;
            (setState as (...a: unknown[]) => void)("tasks", i, k, v);
        }
    },

    /** 删除任务：先 DELETE 后端（404 视为已删同样本地移除），再清 SSE/列表/live */
    async remove(taskId: string) {
        try {
            await api.deleteTask(taskId);
        } catch (e) {
            if (!(e instanceof ApiError && e.status === 404)) throw e;
        }
        dropTask(taskId);
        rebalance();
    },

    /** retry 复用同一 task_id：清掉上一轮 SSE 痕迹再重新订阅（seq 水位线保留——旧轮重放帧照丢） */
    resetLive(taskId: string) {
        sseDead.delete(taskId); // 新轮给 SSE 一次复活机会
        unwant(taskId);
        setState("live", taskId, freshLive());
        taskStore.watch(taskId);
    },

    live(taskId: string): TaskLive | undefined {
        return state.live[taskId];
    },

    task(taskId: string): TaskSnapshot | undefined {
        return state.tasks.find((t) => t.task_id === taskId);
    },
};
