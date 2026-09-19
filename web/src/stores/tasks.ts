// 任务列表/活动任务 store —— solid store 承载 §2 快照 + SSE 增量。
// 拆分层（C3）：帧→live 归约在 liveFrames.ts（纯函数），观测通道编排
//（wanted/SSE 槽/轮询/探活）在 taskTransport.ts——本层是状态面与门面：
// tasks 行 reconcile/patch、TaskLive 写入、终态收敛、公开 API。

import { createStore, produce, reconcile } from "solid-js/store";
import {
    api,
    ApiError,
    forgetTaskEvents,
    isTerminal,
    liveSeqWatermark,
    type TaskChannel,
    type TaskSnapshot,
} from "../api/client";
import {
    chunkCap,
    chunkItemOk,
    foldFixloop,
    normalizeL2,
    type TaskLive,
} from "./liveFrames";
import { createTransport } from "./taskTransport";

// 门面再导出：live 面类型与传输调参常量是 store 公开面的一部分——
// 消费方（TaskProgress/tests）从 tasks.ts 单点拿，不追内部文件布局
export type { TaskLive } from "./liveFrames";
export {
    MAX_SSE_TASKS,
    POLL_INTERVAL_MS,
} from "./taskTransport";

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
    tp.unwant(taskId);
}

/** 任务行已删（本地 remove / 服务端 deleted 帧 / 轮询 404 / SSE 探活 404）——观测+状态+水位线全清 */
function dropTask(taskId: string) {
    tp.drop(taskId);
    forgetTaskEvents(taskId);
    setState("tasks", (list) => list.filter((t) => t.task_id !== taskId));
    setState(
        "live",
        produce((l) => {
            delete l[taskId];
        }),
    );
}

// 帧→状态归约 handlers（transport/resync 两键是传输自留地，不在此表）。
// 需 unwant/rebalance 的帧（snapshot/done 终态沿、deleted 帧）经 tp 回调——
// tp 在此对象字面量求值后才赋值，handler 体执行时已在位（惰性闭包）。
const tp = createTransport({
    tasks: () => state.tasks,
    ensureLive,
    setTransport: (taskId, s) =>
        setState("live", taskId, "transport", s),
    upsertTask,
    onTerminal: convergeTerminal,
    onDrop: dropTask,
    clearChunkLive: (taskId) => {
        setState("live", taskId, "chunk", undefined);
        setState("live", taskId, "chunkItems", []);
    },
    frameHandlers: (taskId) => ({
        snapshot: (s) => {
            upsertTask(s);
            if (isTerminal(s.status)) {
                convergeTerminal(taskId, s);
                tp.rebalance();
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
            const next = foldFixloop(state.live[taskId]?.fixloop, e);
            if (next !== null) setState("live", taskId, "fixloop", next);
        },
        l2: (e) => setState("live", taskId, "l2", normalizeL2(e)),
        done: (e) => {
            // DELETE 端点的收尾帧——本任务行已删，别回填成 "deleted" 僵尸行
            if (e.status === "deleted") {
                dropTask(taskId);
                tp.rebalance();
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
            tp.unwant(taskId);
            tp.rebalance();
        },
    }),
});

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
                    if (!tp.wanted.has(t.task_id))
                        tp.wanted.set(t.task_id, { pin: false });
                } else if (tp.wanted.has(t.task_id)) {
                    // 列表回终态（done 帧可能未到/已丢）——收敛并摘除
                    convergeTerminal(t.task_id, t);
                }
            }
            // 列表里消失的非 pin 任务（别处已删）——停止观测；pin 的留着
            // （reader 可能在 retry 间隙，新快照未到）
            for (const [id, w] of [...tp.wanted]) {
                if (!ids.has(id) && !w.pin) tp.unwant(id);
            }
            tp.rebalance();
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
        return tp.watch(taskId);
    },

    /** 摘除观测（幂等公开）：close() 句柄与显式调用等价 */
    unwatch(taskId: string) {
        tp.unwatch(taskId);
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
        tp.rebalance();
    },

    /** retry 复用同一 task_id：清掉上一轮 SSE 痕迹再重新订阅（seq 水位线保留——旧轮重放帧照丢） */
    resetLive(taskId: string) {
        tp.revive(taskId); // 新轮给 SSE 一次复活机会
        tp.unwant(taskId); // watchHandles 保留——watch() 复用同一句柄
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
