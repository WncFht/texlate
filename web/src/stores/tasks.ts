// 任务列表/活动任务 store —— solid store 承载 §2 快照 + SSE 增量。

import { createStore, produce } from "solid-js/store";
import {
    api,
    ApiError,
    forgetTaskEvents,
    isTerminal,
    openTaskEvents,
    type ChunkItem,
    type ChunkEvent,
    type DoneEvent,
    type LogEvent,
    type StageEvent,
    type TaskChannel,
    type TaskErrorEvent,
    type TaskSnapshot,
    type TransportState,
    type WarningEvent,
} from "../api/client";

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
    transport: TransportState;
}

//: 病态 seq 上限——超大 seq 帧防填洞 OOM（真实 chunks 量阶远低）
export const MAX_CHUNK_SEQ = 100_000;

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
    const cap = limit == null ? MAX_CHUNK_SEQ : Math.min(limit, MAX_CHUNK_SEQ);
    const next = prev.slice();
    for (const it of delta) {
        if (!Number.isInteger(it.seq) || it.seq < 0 || it.seq > cap) continue;
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

//: 同源 HTTP/1.1 每域 6 连接上限——SSE 每任务常开一条，占满则 API/PDF
//: 拉取全排队假死；窗口外非终态任务降级 interval 轮询 snapshot
export const MAX_SSE_TASKS = 3;
export const POLL_INTERVAL_MS = 3000;

const freshLive = (): TaskLive => ({
    stages: [],
    chunkItems: [],
    logs: [],
    warnings: [],
    transport: "reconnecting",
});

function upsertTask(snap: TaskSnapshot) {
    setState("tasks", (list) => {
        const i = list.findIndex((t) => t.task_id === snap.task_id);
        if (i < 0) return [snap, ...list];
        const next = [...list];
        next[i] = { ...next[i], ...snap };
        return next;
    });
}

/** 终态收敛：释放 append-only 缓冲（logs/stages 会话内单调增长）；
 * done/chunk/chunkItems/warnings/error 留给终态面板与棋盘格 */
function settleLive(taskId: string) {
    if (!state.live[taskId]) return;
    setState("live", taskId, "logs", []);
    setState("live", taskId, "stages", []);
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

/** 任务行已删（本地 remove / 服务端 deleted 帧 / 轮询 404）——观测+状态+水位线全清 */
function dropTask(taskId: string) {
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
    if (pollers.has(taskId)) return;
    const tick = async () => {
        try {
            const s = await api.snapshot(taskId);
            if (!wanted.has(taskId)) return; // 已摘除——迟到响应不回写
            upsertTask(s);
            if (isTerminal(s.status)) {
                settleLive(taskId);
                unwant(taskId);
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
                if (sseIds.has(id)) {
                    stopPoll(id);
                    ensureChannel(id);
                } else {
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
    setState("live", taskId, (l) => l ?? freshLive());
    // 重连（旧 channel 已 closed）也先回到 reconnecting，等 onopen 翻 live
    setState("live", taskId, "transport", "reconnecting");
    const ch = openTaskEvents(taskId, {
        transport: (s) => setState("live", taskId, "transport", s),
        snapshot: (s) => {
            upsertTask(s);
            if (isTerminal(s.status)) {
                settleLive(taskId);
                unwant(taskId);
                rebalance();
            }
        },
        stage: (e) => {
            setState("live", taskId, "stage", e);
            setState("live", taskId, "stages", (ss) => [...ss, e]);
            setState(
                "tasks",
                (t) => t.task_id === taskId,
                (t) => ({
                    ...t,
                    status: e.stage,
                    stage: e.stage,
                    progress: e.progress,
                    message: e.message,
                }),
            );
        },
        chunk: (e) => {
            setState("live", taskId, "chunk", e);
            setState("live", taskId, "chunkItems", (items) =>
                mergeChunkItems(items, e.items, e.total),
            );
        },
        log: (e) =>
            setState("live", taskId, "logs", (ls) => [...ls.slice(-499), e]),
        warning: (e) =>
            setState("live", taskId, "warnings", (ws) => [...ws, e]),
        error: (e) => setState("live", taskId, "error", e),
        done: (e) => {
            // DELETE 端点的收尾帧——本任务行已删，别回填成 "deleted" 僵尸行
            if (e.status === "deleted") {
                dropTask(taskId);
                rebalance();
                return;
            }
            setState("live", taskId, "done", e);
            const status = e.status;
            setState(
                "tasks",
                (t) => t.task_id === taskId,
                (t) => ({
                    ...t,
                    status,
                    progress: 100,
                    artifacts: e.artifacts,
                }),
            );
            settleLive(taskId);
            unwant(taskId);
            rebalance();
        },
    });
    channels.set(taskId, ch);
    return ch;
}

/** 轮询态任务的 watch 返回值——SSE 槽被更高优先级占满时的降级句柄 */
function pollHandle(taskId: string): TaskChannel {
    return {
        close: () => taskStore.unwatch(taskId),
        get closed() {
            return !wanted.has(taskId);
        },
    };
}

export const taskStore = {
    state,

    async refresh() {
        try {
            const res = await api.tasks();
            const list = Array.isArray(res) ? res : (res.tasks ?? []);
            setState({ tasks: list, loaded: true, loadError: undefined });
            const ids = new Set(list.map((t) => t.task_id));
            for (const t of list) {
                if (!isTerminal(t.status)) {
                    if (!wanted.has(t.task_id))
                        wanted.set(t.task_id, { pin: false });
                } else if (wanted.has(t.task_id)) {
                    // 列表回终态（done 帧可能未到/已丢）——收敛并摘除
                    settleLive(t.task_id);
                    unwant(t.task_id);
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

    /** 订阅任务（pin=聚焦优先占 SSE 槽；幂等——重复调用复用同一 channel） */
    watch(taskId: string): TaskChannel {
        wanted.set(taskId, { pin: true });
        rebalance();
        return channels.get(taskId) ?? pollHandle(taskId);
    },

    unwatch(taskId: string) {
        unwant(taskId);
        rebalance();
    },

    /** 本地补丁任务行（retry 后乐观更新；SSE snapshot 随后来覆盖为准） */
    patch(taskId: string, p: Partial<TaskSnapshot>) {
        setState(
            "tasks",
            (t) => t.task_id === taskId,
            (t) => ({ ...t, ...p }),
        );
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
