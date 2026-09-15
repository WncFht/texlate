// 任务列表/活动任务 store —— solid store 承载 §2 快照 + SSE 增量。

import { createStore } from "solid-js/store";
import {
    api,
    isTerminal,
    openTaskEvents,
    type ChunkEvent,
    type DoneEvent,
    type LogEvent,
    type StageEvent,
    type TaskChannel,
    type TaskErrorEvent,
    type TaskSnapshot,
    type WarningEvent,
} from "../api/client";

export interface TaskLive {
    stage?: StageEvent;
    chunk?: ChunkEvent;
    logs: LogEvent[];
    warnings: WarningEvent[];
    error?: TaskErrorEvent;
    done?: DoneEvent;
}

interface TasksState {
    tasks: TaskSnapshot[];
    loaded: boolean;
    loadError?: string;
    live: Record<string, TaskLive>;
}

const [state, setState] = createStore<TasksState>({ tasks: [], loaded: false, live: {} });
const channels = new Map<string, TaskChannel>();

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
        setState("live", taskId, (l) => l ?? { logs: [], warnings: [] });
        const ch = openTaskEvents(taskId, {
            snapshot: (s) => {
                upsertTask(s);
                if (isTerminal(s.status)) channels.delete(taskId);
            },
            stage: (e) => {
                setState("live", taskId, "stage", e);
                setState("tasks", (t) => t.task_id === taskId, (t) => ({
                    ...t,
                    status: e.stage,
                    stage: e.stage,
                    progress: e.progress,
                    message: e.message,
                }));
            },
            chunk: (e) => setState("live", taskId, "chunk", e),
            log: (e) => setState("live", taskId, "logs", (ls) => [...ls.slice(-499), e]),
            warning: (e) => setState("live", taskId, "warnings", (ws) => [...ws, e]),
            error: (e) => setState("live", taskId, "error", e),
            done: (e) => {
                setState("live", taskId, "done", e);
                setState("tasks", (t) => t.task_id === taskId, (t) => ({
                    ...t,
                    status: e.status,
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

    live(taskId: string): TaskLive | undefined {
        return state.live[taskId];
    },

    task(taskId: string): TaskSnapshot | undefined {
        return state.tasks.find((t) => t.task_id === taskId);
    },
};
