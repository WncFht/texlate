// taskTransport —— 每任务观测通道编排：wanted 意愿集 + SSE 槽分配
//（MAX_SSE_TASKS，同源 HTTP/1.1 每域 6 连接上限——SSE 每任务常开
// 一条，占满则 API/PDF 拉取全排队假死）+ 槽外/死槽轮询降级 +
// 服务端终拒（404 等 readyState=CLOSED）探活兜底。
//
// 自 tasks.ts 拆出：传输层只管「谁被盯、走 SSE 还是轮询、死了怎么收」；
// 帧→状态归约经 hooks 回注 store 侧（本层不认 TaskLive 形状）。

import {
    api,
    ApiError,
    isTerminal,
    openTaskEvents,
    type TaskChannel,
    type TaskEventHandlers,
    type TaskSnapshot,
    type TransportState,
} from "../api/client";

export const MAX_SSE_TASKS = 3;
export const POLL_INTERVAL_MS = 3000;

/** 传输→store 回注点：状态读写与帧归约全在 store 侧，本层只调钩子 */
export interface TransportHooks {
    tasks(): TaskSnapshot[];
    ensureLive(taskId: string): void;
    setTransport(taskId: string, s: TransportState): void;
    upsertTask(snap: TaskSnapshot): void;
    /** 探到终态（snapshot 帧/轮询/探活三路共用）：合成 done + 收敛 + unwant */
    onTerminal(taskId: string, s: TaskSnapshot): void;
    /** 任务已删（本地 remove/deleted 帧/轮询 404/探活 404）：状态面全清 */
    onDrop(taskId: string): void;
    /**
     * 非 pin 观测面的共享列表轮询一拍——store 侧一次 /api/tasks 整表归并
     * （水位防回退 + 终态收敛 + 外来非终态行自动 wanted(pin:false) +
     * 非 pin 消失行即删），替代每任务各开 snapshot 轮询。
     * ids（拍发起时的 listPolled 快照）仅作传输侧空集短路依据，
     * store 实现按整表归并可忽略之。
     */
    pollListWanted(ids: readonly string[]): Promise<void>;
    /** resync 帧清 chunk 派生态——水位线已被 client 重置，累积值不可信 */
    clearChunkLive(taskId: string): void;
    /**
     * 帧→状态归约 handlers：snapshot/stage/chunk/log/warning/error/
     * fixloop/l2/done 由 store 供（需 unwant/rebalance 时经 transport
     * 实例回调）；transport/resync 由本层自持（是纯传输关切）。
     */
    frameHandlers(taskId: string): TaskEventHandlers;
}

export interface TaskTransport {
    /** pin 优先的观测意愿集——refresh/watch 直接读写 */
    readonly wanted: Map<string, { pin: boolean }>;
    watch(taskId: string): TaskChannel;
    unwatch(taskId: string): void;
    /** 纯摘除观测意愿 + 关通道停轮询；调用方按需补 rebalance */
    unwant(taskId: string): void;
    /** 传输侧全清（sseDead/watchHandles/wanted/通道/轮询）——状态面归调用方 */
    drop(taskId: string): void;
    /** retry 新轮：清服务端终拒标记，给 SSE 一次复活机会 */
    revive(taskId: string): void;
    rebalance(): void;
}

export function createTransport(hooks: TransportHooks): TaskTransport {
    const channels = new Map<string, TaskChannel>();
    const pollers = new Map<string, ReturnType<typeof setInterval>>();
    /**
     * 非 pin 观测面共享列表轮询集——槽外任务不再每任务各开 snapshot
     * 轮询（N 任务 N 请求/3s），归并成一拍 /api/tasks 由 store 侧归并
     */
    const listPolled = new Set<string>();
    let listPollTimer: ReturnType<typeof setInterval> | undefined;
    let listInFlight = false;
    /** 观测意愿集：pin=显式 watch（reader 聚焦）优先占 SSE 槽 */
    const wanted = new Map<string, { pin: boolean }>();
    /**
     * 服务端终结的 SSE（readyState CLOSED ≈ HTTP 错——404 删行/5xx）：
     * ensureChannel 不得复活它们——复活即 404 重连循环（M6）。探活/轮询
     * 兜底在 probeAfterClose；revive（retry 新轮）与 drop 清除。
     */
    const sseDead = new Set<string>();
    /** watch 句柄按任务缓存——幂等 watch 返回同一对象（close→unwatch 语义） */
    const watchHandles = new Map<string, TaskChannel>();

    // 同步派发防护：handler 内 unwant→rebalance 可嵌套（测试假 EventSource
    // 同步派发；浏览器里 ES 事件恒异步，本守卫仅兜测试面）——脏标记重跑
    let rebalancing = false;
    let rebalanceDirty = false;

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

    async function tickList() {
        if (listInFlight) return;
        const ids = [...listPolled];
        if (!ids.length) return;
        listInFlight = true;
        try {
            await hooks.pollListWanted(ids);
        } catch {
            /* 抖动下拍再试——与 per-task tick 同策略 */
        } finally {
            listInFlight = false;
        }
    }

    /** 集合非空才挂共享定时器；首个任务入集即补一拍（与原 startPoll 的 void tick() 同语义） */
    function syncListPoll() {
        if (listPolled.size && listPollTimer === undefined) {
            listPollTimer = setInterval(
                () => void tickList(),
                POLL_INTERVAL_MS,
            );
            void tickList();
        } else if (!listPolled.size && listPollTimer !== undefined) {
            clearInterval(listPollTimer);
            listPollTimer = undefined;
        }
    }

    /** 非 pin 任务入共享列表轮询（ensureLive/transport 标 polling 与 startPoll 同口径） */
    function listPoll(taskId: string) {
        stopPoll(taskId);
        hooks.ensureLive(taskId);
        hooks.setTransport(taskId, "polling");
        listPolled.add(taskId);
    }

    function unwant(taskId: string) {
        wanted.delete(taskId);
        listPolled.delete(taskId);
        closeChannel(taskId);
        stopPoll(taskId);
        syncListPoll();
    }

    function drop(taskId: string) {
        sseDead.delete(taskId);
        watchHandles.delete(taskId);
        unwant(taskId);
    }

    /**
     * snapshot 一拍定去留（tick/probeAfterClose/resync 三路共用归约）：
     * 拍间摘除 → 迟到响应不回写——成功与失败两路同口径守卫；
     * 终态 → onTerminal，404 → onDrop，其余错误吞下轮再试。
     * 返回是否收敛（终态/404）——rebalance 策略归调用方：
     * probe 恒补一拍（SSE 死槽刚让出），tick/resync 仅收敛时。
     */
    async function settleSnapshot(taskId: string): Promise<boolean> {
        try {
            const s = await api.snapshot(taskId);
            if (!wanted.has(taskId)) return false; // 已摘除——迟到响应不回写
            hooks.upsertTask(s);
            if (!isTerminal(s.status)) return false;
            hooks.onTerminal(taskId, s);
            return true;
        } catch (e) {
            if (!wanted.has(taskId)) return false; // 迟到 404 同口径不回写
            if (!(e instanceof ApiError && e.status === 404)) return false;
            hooks.onDrop(taskId);
            return true;
        }
    }

    function startPoll(taskId: string) {
        hooks.ensureLive(taskId);
        hooks.setTransport(taskId, "polling");
        if (pollers.has(taskId)) return;
        const tick = async () => {
            if (await settleSnapshot(taskId)) rebalance();
        };
        pollers.set(
            taskId,
            setInterval(() => void tick(), POLL_INTERVAL_MS),
        );
        void tick();
    }

    /**
     * SSE 被服务端终结（探活兜底，M6）：snapshot 一次定去留——
     * 404 → 行已删 drop；终态 → 收敛摘除；仍在跑/探活失败 → 交尾部
     * rebalance 降级（pin 走独轮询，非 pin 进共享列表轮询；SSE 不复活）。
     * 尾部 rebalance 恒补一拍——死槽让位/升级回收都在此收口。
     */
    async function probeAfterClose(taskId: string) {
        await settleSnapshot(taskId);
        rebalance();
    }

    /** pin 优先、其后按任务 updated_at 新→旧占 SSE 槽 */
    function orderedWanted(): string[] {
        // 比较器内 tasks.find 是 O(w·log w·m)——先摊成 Map 一次 O(m)
        const upd = new Map(
            hooks.tasks().map((t) => [t.task_id, t.updated_at ?? 0]),
        );
        return [...wanted.keys()].sort((a, b) => {
            const pa = wanted.get(a)?.pin ? 1 : 0;
            const pb = wanted.get(b)?.pin ? 1 : 0;
            if (pa !== pb) return pb - pa;
            return (upd.get(b) ?? 0) - (upd.get(a) ?? 0);
        });
    }

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
                        listPolled.delete(id);
                        stopPoll(id);
                        ensureChannel(id);
                    } else {
                        // 槽外 / SSE 已被服务端终结——pin 走每任务独轮询
                        // （聚焦面要 404→drop 精度），非 pin 进共享列表轮询
                        closeChannel(id);
                        if (wanted.get(id)?.pin) {
                            listPolled.delete(id);
                            startPoll(id);
                        } else {
                            listPoll(id);
                        }
                    }
                }
            } while (rebalanceDirty);
            syncListPoll();
        } finally {
            rebalancing = false;
        }
    }

    function ensureChannel(taskId: string): TaskChannel {
        const existing = channels.get(taskId);
        if (existing && !existing.closed) return existing;
        hooks.ensureLive(taskId);
        // 首连/重建都先报 connecting——reconnecting 专指传输错误后的自动重连
        hooks.setTransport(taskId, "connecting");
        const ch = openTaskEvents(taskId, {
            transport: (s) => {
                hooks.setTransport(taskId, s);
                // 服务端终拒（404 等 readyState=CLOSED）：仍 wanted 说明非
                // 本侧主动关——标记 sseDead 防 rebalance 复活，探活定去留
                if (
                    s === "closed" &&
                    wanted.has(taskId) &&
                    !sseDead.has(taskId)
                ) {
                    sseDead.add(taskId);
                    void probeAfterClose(taskId);
                }
            },
            resync: () => {
                // 重放缺口：水位线已被 client 重置——清 chunk 派生态（不可信），
                // 拉 snapshot 对齐任务面；SSE 仍活着，不降轮询
                if (!wanted.has(taskId)) return;
                hooks.clearChunkLive(taskId);
                void settleSnapshot(taskId).then((settled) => {
                    if (settled) rebalance();
                });
            },
            ...hooks.frameHandlers(taskId),
        });
        channels.set(taskId, ch);
        return ch;
    }

    const tp: TaskTransport = {
        wanted,

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
                    close: () => tp.unwatch(taskId),
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

        unwant,
        drop,

        revive(taskId: string) {
            sseDead.delete(taskId);
        },

        rebalance,
    };
    return tp;
}
