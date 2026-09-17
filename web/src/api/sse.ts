// SSE 面 —— 任务事件流订阅（§2.2）。EventSource 自带断线重连 +
// Last-Event-ID 重放；终态自动关流。client.ts 门面对外再导出。

import {
    isTerminal,
    type ChunkEvent,
    type DoneEvent,
    type LogEvent,
    type StageEvent,
    type TaskErrorEvent,
    type TaskSnapshot,
    type WarningEvent,
} from "./types";

const BASE = "/api";

/**
 * 传输层状态机：
 *  connecting    —— 首连尚未 open（初订/重建途中）
 *  live          —— EventSource open
 *  reconnecting  —— 传输错误后浏览器自动重连在途
 *  polling       —— SSE 槽外/服务端终结后的降级轮询（store 置，非本层发）
 *  closed        —— 彻底断开（终态收尾/服务端 HTTP 错误终拒/主动 close）
 */
export type TransportState =
    | "live"
    | "connecting"
    | "reconnecting"
    | "polling"
    | "closed";

export interface TaskEventHandlers {
    snapshot?: (s: TaskSnapshot) => void;
    stage?: (e: StageEvent) => void;
    chunk?: (e: ChunkEvent) => void;
    log?: (e: LogEvent) => void;
    warning?: (e: WarningEvent) => void;
    error?: (e: TaskErrorEvent) => void;
    done?: (e: DoneEvent) => void;
    /**
     * 服务端检出重放缺口（last_id 落已淘汰区段）发的 resync 帧——
     * 本层已重置 seq 水位线；上层应拉 snapshot 对齐状态面。
     */
    resync?: () => void;
    /** 传输层状态：见 TransportState 状态机注释 */
    transport?: (state: TransportState) => void;
}

export interface TaskChannel {
    close(): void;
    readonly closed: boolean;
}

/**
 * 每任务已见 seq 水位线（module 级，跨 channel 重建存活）。
 *
 * retry/重开订阅时新 EventSource 不带 Last-Event-ID，服务端
 * ``events_since(task_id, 0)`` 全量重放落盘事件（retry 不清
 * task_events）——含上一轮 done 帧，照单全收会把新 channel 当场关掉、
 * 本轮真实事件无人监听（live 假死）。水位线丢弃 ``seq<=wm`` 的非
 * snapshot 帧；snapshot 帧 seq=0 恒放行（每连现场合成、不落盘）。
 * EventSource 自动重连带 Last-Event-ID 的服务端重放也被同一去重罩住。
 * 任务删除时由 {@link forgetTaskEvents} 清——retry/unwatch 均不清。
 */
const seqWatermark = new Map<string, number>();

/** 任务删除（remove/服务端 deleted 帧）才清其 seq 水位线 */
export function forgetTaskEvents(taskId: string): void {
    seqWatermark.delete(taskId);
}

/** 任务已消费事件 seq 水位线（refresh 拒列表旧读回退用——0 = 未见过事件） */
export function liveSeqWatermark(taskId: string): number {
    return seqWatermark.get(taskId) ?? 0;
}

/**
 * 订阅任务 SSE。浏览器 EventSource 自带断线重连 + Last-Event-ID 重放；
 * 终态（done 事件或 snapshot 已是终态）自动关闭，不再重连。
 */
export function openTaskEvents(
    taskId: string,
    h: TaskEventHandlers,
): TaskChannel {
    const es = new EventSource(`${BASE}/task/${taskId}`);
    let closed = false;

    const on = <T>(type: string, fn: (data: T, seq: number) => void) =>
        es.addEventListener(type, (ev) => {
            const msg = ev as MessageEvent;
            const seq = Number(msg.lastEventId) || 0;
            const wm = seqWatermark.get(taskId) ?? 0;
            if (seq !== 0 && seq <= wm) return; // 重放/重连重复帧——丢弃
            if (seq > wm) seqWatermark.set(taskId, seq); // 坏帧也推进，防毒化回放
            try {
                fn(JSON.parse(msg.data) as T, seq);
            } catch {
                /* 忽略坏帧 */
            }
        });

    on("snapshot", (s: TaskSnapshot) => {
        h.snapshot?.(s);
        if (isTerminal(s.status)) close();
    });
    on("stage", (e: StageEvent) => h.stage?.(e));
    on("chunk", (e: ChunkEvent) => h.chunk?.(e));
    on("log", (e: LogEvent) => h.log?.(e));
    on("warning", (e: WarningEvent) => h.warning?.(e));
    on("error", (e: TaskErrorEvent) => h.error?.(e));
    // 重放缺口信号（服务端检出 last_id 落淘汰区段时合成）：水位线重置
    // 到该帧 seq——其后的流是新基线；上层拉 snapshot 补缺口段的状态
    on("resync", (_d: Record<string, never>, seq: number) => {
        seqWatermark.set(taskId, seq);
        h.resync?.();
    });
    on("done", (e: DoneEvent) => {
        h.done?.(e);
        close();
    });
    es.onopen = () => h.transport?.("live");
    es.onerror = (ev) => {
        // 具名 `event: error` 帧以 type=error 的 MessageEvent 派发，会连带
        // 触发 onerror——带 data 的是业务错误帧（已走 on("error")），真·传输
        // 层失败是裸 Event
        if ("data" in ev || ev instanceof MessageEvent) return;
        if (es.readyState === EventSource.CLOSED) close();
        else h.transport?.("reconnecting");
    };

    function close() {
        if (!closed) {
            closed = true;
            es.close();
            h.transport?.("closed");
        }
    }

    return {
        close,
        get closed() {
            return closed;
        },
    };
}
