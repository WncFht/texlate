// 任务列表/活动任务 store —— solid store 承载 §2 快照 + SSE 增量。
// 拆分层（C3）：帧→live 归约在 liveFrames.ts（纯函数），观测通道编排
//（wanted/SSE 槽/轮询/探活）在 taskTransport.ts——本层是状态面与门面：
// tasks 行 reconcile/patch、TaskLive 写入、终态收敛、公开 API。

import { batch } from "solid-js";
import { createStore, produce, reconcile } from "solid-js/store";
import {
    api,
    ApiError,
    forgetTaskEvents,
    isTerminal,
    liveSeqWatermark,
    type ChunkItem,
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
export { MAX_SSE_TASKS, POLL_INTERVAL_MS } from "./taskTransport";

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

/**
 * /api/tasks 列表行是 TaskSnapshot 子集（缺 artifacts/warnings/usage/
 * queue_position/options/glossary）——reconcile 快照语义会把缺席键清
 * undefined，从现行行继承防清缺（refresh 与共享列表轮询共用）。
 */
function inheritRich(
    s: TaskSnapshot,
    cur: TaskSnapshot | undefined,
): TaskSnapshot {
    if (!cur) return s;
    return {
        ...s,
        artifacts: s.artifacts ?? cur.artifacts,
        warnings: s.warnings ?? cur.warnings,
        usage: s.usage ?? cur.usage,
        queue_position: s.queue_position ?? cur.queue_position,
        options: s.options ?? cur.options,
        glossary: s.glossary ?? cur.glossary,
    };
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
    setTransport: (taskId, s) => setState("live", taskId, "transport", s),
    upsertTask,
    onTerminal: convergeTerminal,
    onDrop: dropTask,
    // 非 pin 观测面共享列表轮询：一拍 /api/tasks 归并——与 refresh 同
    // 水位口径（现行行更新则列表旧读不回退），消失=已删按轮询 404 收敛
    pollListWanted: async (ids) => {
        const list = await api.tasks();
        const byId = new Map(list.map((t) => [t.task_id, t]));
        const curById = new Map(state.tasks.map((r) => [r.task_id, r]));
        let dirty = false;
        for (const id of ids) {
            if (!tp.wanted.has(id)) continue; // 拍间被摘除——迟到响应不回写
            const s = byId.get(id);
            if (!s) {
                dropTask(id);
                dirty = true;
                continue;
            }
            const cur = curById.get(id);
            if (
                cur !== undefined &&
                Math.max(liveSeqWatermark(id), cur.last_seq ?? 0) >
                    (s.last_seq ?? 0)
            )
                continue;
            upsertTask(inheritRich(s, cur));
            if (isTerminal(s.status)) {
                convergeTerminal(id, s);
                dirty = true;
            }
        }
        if (dirty) tp.rebalance();
    },
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
            batch(() => {
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
            });
        },
        chunk: (e) => {
            batch(() => {
                setState("live", taskId, "chunk", e);
                // 一帧一次 produce：空洞补齐+落位先在 draft 上算完再统一
                // 落盘——跳到 seq=N 时逐格 setState 是 N 笔写（seq 上限
                // 100k 即病态放大）；produce 仍只触达被写 index 的订阅，
                // ProgressGrid 按格订阅的 P2 语义不破
                const cap = chunkCap(e.total);
                setState(
                    "live",
                    taskId,
                    "chunkItems",
                    produce((items: ChunkItem[]) => {
                        for (const it of e.items) {
                            if (!chunkItemOk(it, cap)) continue;
                            while (items.length < it.seq)
                                items.push({
                                    seq: items.length,
                                    status: "pending",
                                });
                            items[it.seq] = it;
                        }
                    }),
                );
            });
        },
        log: (e) => {
            // 追加写不拷全表（编译爆发期逐条派发，slice(-499) 每条 O(500)
            // 分配+For 全表 diff）；满 600 才一次性截回 500，摊薄截断成本
            const len = state.live[taskId]?.logs.length ?? 0;
            if (len >= 600) {
                setState("live", taskId, "logs", (ls) => [
                    ...ls.slice(-499),
                    e,
                ]);
            } else {
                setState("live", taskId, "logs", len, e);
            }
        },
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
            const status = e.status; // 窄化在闭包外——batch 内不继承 narrowing
            batch(() => {
                setState("live", taskId, "done", e);
                const i = state.tasks.findIndex((t) => t.task_id === taskId);
                if (i >= 0) {
                    setState("tasks", i, "status", status);
                    setState("tasks", i, "progress", 100);
                    // 拷一份——e.artifacts 已随 live.done 入 store，同对象入
                    // 第二路径会共用节点，后续 reconcile 会改穿 live.done
                    setState("tasks", i, "artifacts", { ...e.artifacts });
                }
                settleLive(taskId);
            });
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
                        : inheritRich(t, cur),
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
