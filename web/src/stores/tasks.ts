// 任务列表/活动任务 store —— solid store 承载 §2 快照 + SSE 增量。

import { createStore, produce } from "solid-js/store";
import {
    api,
    ApiError,
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

/**
 * chunk 事件 items[] 只带变化段——按 seq 覆盖合并进 dense 数组；
 * 越界空洞补 pending 占位，非法 seq（<0）丢弃。
 */
export function mergeChunkItems(prev: ChunkItem[], delta: ChunkItem[]): ChunkItem[] {
    const next = prev.slice();
    for (const it of delta) {
        if (!Number.isInteger(it.seq) || it.seq < 0) continue;
        while (next.length < it.seq) next.push({ seq: next.length, status: "pending" });
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

const [state, setState] = createStore<TasksState>({ tasks: [], loaded: false, live: {} });
const channels = new Map<string, TaskChannel>();

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

export const taskStore = {
    state,

    async refresh() {
        try {
            const res = await api.tasks();
            const list = Array.isArray(res) ? res : (res.tasks ?? []);
            setState({ tasks: list, loaded: true, loadError: undefined });
            for (const t of list) if (!isTerminal(t.status)) taskStore.watch(t.task_id);
        } catch (e) {
            setState({ loaded: true, loadError: e instanceof Error ? e.message : String(e) });
        }
    },

    /** 订阅任务 SSE；幂等（重复调用复用同一 channel） */
    watch(taskId: string): TaskChannel {
        const existing = channels.get(taskId);
        if (existing && !existing.closed) return existing;
        setState("live", taskId, (l) => l ?? freshLive());
        // 重连（旧 channel 已 closed）也先回到 reconnecting，等 onopen 翻 live
        setState("live", taskId, "transport", "reconnecting");
        const ch = openTaskEvents(taskId, {
            transport: (s) => setState("live", taskId, "transport", s),
            snapshot: (s) => {
                upsertTask(s);
                if (isTerminal(s.status)) channels.delete(taskId);
            },
            stage: (e) => {
                setState("live", taskId, "stage", e);
                setState("live", taskId, "stages", (ss) => [...ss, e]);
                setState("tasks", (t) => t.task_id === taskId, (t) => ({
                    ...t,
                    status: e.stage,
                    stage: e.stage,
                    progress: e.progress,
                    message: e.message,
                }));
            },
            chunk: (e) => {
                setState("live", taskId, "chunk", e);
                setState("live", taskId, "chunkItems", (items) =>
                    mergeChunkItems(items, e.items),
                );
            },
            log: (e) => setState("live", taskId, "logs", (ls) => [...ls.slice(-499), e]),
            warning: (e) => setState("live", taskId, "warnings", (ws) => [...ws, e]),
            error: (e) => setState("live", taskId, "error", e),
            done: (e) => {
                // DELETE 端点的收尾帧——本任务行已删，别回填成 "deleted" 僵尸行
                if (e.status === "deleted") {
                    setState("tasks", (list) =>
                        list.filter((t) => t.task_id !== taskId),
                    );
                    setState(
                        "live",
                        produce((l) => {
                            delete l[taskId];
                        }),
                    );
                    channels.delete(taskId);
                    return;
                }
                const status = e.status;
                setState("live", taskId, "done", e);
                setState("tasks", (t) => t.task_id === taskId, (t) => ({
                    ...t,
                    status,
                    progress: 100,
                    artifacts: e.artifacts,
                }));
                channels.delete(taskId);
            },
        });
        channels.set(taskId, ch);
        return ch;
    },

    unwatch(taskId: string) {
        channels.get(taskId)?.close();
        channels.delete(taskId);
    },

    /** 本地补丁任务行（retry 后乐观更新；SSE snapshot 随后来覆盖为准） */
    patch(taskId: string, p: Partial<TaskSnapshot>) {
        setState("tasks", (t) => t.task_id === taskId, (t) => ({ ...t, ...p }));
    },

    /** 删除任务：先 DELETE 后端（404 视为已删同样本地移除），再清 SSE/列表/live */
    async remove(taskId: string) {
        try {
            await api.deleteTask(taskId);
        } catch (e) {
            if (!(e instanceof ApiError && e.status === 404)) throw e;
        }
        taskStore.unwatch(taskId);
        setState("tasks", (list) => list.filter((t) => t.task_id !== taskId));
        setState(
            "live",
            produce((l) => {
                delete l[taskId];
            }),
        );
    },

    /** retry 复用同一 task_id：清掉上一轮 SSE 痕迹再重新订阅 */
    resetLive(taskId: string) {
        taskStore.unwatch(taskId);
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
