// chunkPoll —— api.taskChunks 每任务单轮询器。translating 期预览与
// LivePane（全窗增量渲染）此前各自 setInterval 同端点双拉；
// 合并成一份 2.5s 拍分发给订阅者——引用计数归零即停。
//
// 增量拉取（2026-09-19 性能版）：SSE 活着时 chunkItems 已带各 seq 状态，
// 轮询只为取文本——每拍只拉「status 变了」的脏 seq（?seqs= 定点端点），
// 首拍照常全量（未见 seq 皆脏）、无变化零请求、compiling 冻结期零流量。
// SSE 降级（transport!=live / chunkItems 空）回退旧整窗拉取保正确性。
// in-flight 闸防慢响应叠拍；最新累积页缓存让迟到的订阅者即取即得。

import {
    api,
    type TaskChunkRow,
    type TaskChunksPage,
} from "../api/client";
import { taskStore } from "../stores/tasks";

const POLL_MS = 2500;
/** 拉取窗上限——与 server CHUNKS_PAGE_MAX（500）同值，一页拉全量段 */
export const CHUNK_WINDOW = 500;

type Cb = (page: TaskChunksPage) => void;

interface Poller {
    subs: Set<Cb>;
    timer: number;
    /** 在飞请求——叠拍/补拍归并到同一 promise，调用方 await 即等到真分发 */
    inFlight?: Promise<void>;
    /** 已下发行的累积缓存（seq→row）：增量拍补进、整页拍重建 */
    cache: Map<number, TaskChunkRow>;
    /** 各 seq 已下发的 status——同状态不重拉（en 不可变，zh 随状态翻转） */
    seen: Map<number, string>;
    /** 最近一拍的 total（整页重建与增量补全后的一致视图分发用） */
    total: number;
}

const pollers = new Map<string, Poller>();

/** cache → 分发页：seq 升序全量视图（消费者按页语义合并，不缺行） */
function pageOf(p: Poller): TaskChunksPage {
    return {
        chunks: [...p.cache.values()].sort((a, b) => a.seq - b.seq),
        total: p.total,
    };
}

function tick(taskId: string, forceFull = false): Promise<void> {
    const p = pollers.get(taskId);
    if (!p) return Promise.resolve();
    if (p.inFlight) return p.inFlight;
    const run = (async () => {
        try {
            const live = taskStore.live(taskId);
            const items = live?.chunkItems ?? [];
            // 增量道：SSE 在线且已知块状态——只拉状态翻转的 seq；
            // 未见过的 pending 也算脏（首拍把全窗文本拉齐，含未译段原文）
            const delta =
                !forceFull &&
                live?.transport === "live" &&
                items.length > 0;
            if (delta) {
                const dirty: number[] = [];
                for (const it of items) {
                    if (!it || !Number.isInteger(it.seq)) continue;
                    if (p.seen.get(it.seq) !== it.status) dirty.push(it.seq);
                }
                if (!dirty.length) return; // 本拍零变化——不发请求
                const page = await api.taskChunksSeqs(
                    taskId,
                    dirty.slice(0, CHUNK_WINDOW),
                );
                for (const r of page.chunks) {
                    p.cache.set(r.seq, r);
                    p.seen.set(r.seq, r.status);
                }
                p.total = page.total;
            } else {
                // 整页道：降级/补拍/终态冲刷——服务端为真源，重建缓存
                const page = await api.taskChunks(taskId, 0, CHUNK_WINDOW);
                p.cache.clear();
                p.seen.clear();
                for (const r of page.chunks) {
                    p.cache.set(r.seq, r);
                    p.seen.set(r.seq, r.status);
                }
                p.total = page.total;
            }
            const out = pageOf(p);
            for (const cb of [...p.subs]) cb(out);
        } catch {
            /* 端点未就位/网络抖动——下拍再试 */
        }
    })();
    p.inFlight = run;
    return run.finally(() => {
        p.inFlight = undefined;
    });
}

/**
 * 订阅任务 chunks 轮询页：有缓存页立即回放（无则立取一拍），其后每
 * 2.5s 一拍。返回幂等退订函数——最后一个订阅者退订即停轮询。
 */
export function subscribeChunks(taskId: string, cb: Cb): () => void {
    let p = pollers.get(taskId);
    if (!p) {
        p = {
            subs: new Set(),
            timer: window.setInterval(() => void tick(taskId), POLL_MS),
            cache: new Map(),
            seen: new Map(),
            total: 0,
        };
        pollers.set(taskId, p);
    }
    const poller = p;
    poller.subs.add(cb);
    if (poller.cache.size) cb(pageOf(poller));
    else void tick(taskId);
    let done = false;
    return () => {
        if (done) return;
        done = true;
        poller.subs.delete(cb);
        if (poller.subs.size === 0) {
            window.clearInterval(poller.timer);
            pollers.delete(taskId);
        }
    };
}

/** 单发补拍：整窗强拉一次分发给当前订阅者并刷新缓存（冻结收尾/手动刷新用） */
export function pollChunksOnce(taskId: string): Promise<void> {
    return tick(taskId, true);
}
