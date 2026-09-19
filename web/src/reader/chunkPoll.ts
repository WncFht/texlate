// chunkPoll —— api.taskChunks 每任务单轮询器。translating 期 ChunkPreview
//（头窗预览）与 LivePane（全窗增量渲染）此前各自 setInterval 同端点双拉；
// 合并成一份 2.5s 拍分发给订阅者——引用计数归零即停。
// 每拍固定拉 0..CHUNK_WINDOW 整窗（与 server CHUNKS_PAGE_MAX 同值，
// 是各消费者的窗口上界）；in-flight 闸防慢响应叠拍；最新页缓存让
// 迟到的订阅者即取即得，不必干等下一拍。

import { api, type TaskChunksPage } from "../api/client";

const POLL_MS = 2500;
/** 拉取窗上限——与 server CHUNKS_PAGE_MAX（500）同值，一页拉全量段 */
export const CHUNK_WINDOW = 500;

type Cb = (page: TaskChunksPage) => void;

interface Poller {
    subs: Set<Cb>;
    timer: number;
    /** 在飞请求——叠拍/补拍归并到同一 promise，调用方 await 即等到真分发 */
    inFlight?: Promise<void>;
    last?: TaskChunksPage;
}

const pollers = new Map<string, Poller>();

function tick(taskId: string): Promise<void> {
    const p = pollers.get(taskId);
    if (!p) return Promise.resolve();
    if (p.inFlight) return p.inFlight;
    const run = (async () => {
        try {
            const page = await api.taskChunks(taskId, 0, CHUNK_WINDOW);
            p.last = page;
            for (const cb of [...p.subs]) cb(page);
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
        };
        pollers.set(taskId, p);
    }
    const poller = p;
    poller.subs.add(cb);
    if (poller.last) cb(poller.last);
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

/** 单发补拍：抓一页分发给当前订阅者并刷新缓存（冻结收尾/手动刷新用） */
export function pollChunksOnce(taskId: string): Promise<void> {
    return tick(taskId);
}
