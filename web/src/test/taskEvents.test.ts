// openTaskEvents：seq 水位线去重（retry 全量重放不毒化新一轮）、
// 具名 error 帧不污染 transport、断线重连 dedup——假 EventSource 直测。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
    forgetTaskEvents,
    openTaskEvents,
    type DoneEvent,
    type StageEvent,
    type TaskErrorEvent,
    type TaskSnapshot,
    type TransportState,
} from "../api/client";
import { snap as fakeSnap } from "./fakes";

type Listener = (ev: Event) => void;

/** 浏览器 EventSource 语义替身：addEventListener + on<type> 同一事件都喂
 * （具名 `event: error` 帧会连带触发 onerror——真实 DOM 行为） */
class FakeEventSource {
    static readonly CONNECTING = 0;
    static readonly OPEN = 1;
    static readonly CLOSED = 2;
    static instances: FakeEventSource[] = [];

    readyState = FakeEventSource.CONNECTING;
    onopen: ((ev: Event) => unknown) | null = null;
    onerror: ((ev: Event) => unknown) | null = null;
    onmessage: ((ev: Event) => unknown) | null = null;
    private listeners = new Map<string, Set<Listener>>();

    constructor(public readonly url: string) {
        FakeEventSource.instances.push(this);
    }
    addEventListener(type: string, fn: Listener) {
        let set = this.listeners.get(type);
        if (!set) this.listeners.set(type, (set = new Set()));
        set.add(fn);
    }
    removeEventListener(type: string, fn: Listener) {
        this.listeners.get(type)?.delete(fn);
    }
    close() {
        this.readyState = FakeEventSource.CLOSED;
    }

    /** 服务端推一帧（event:<type> / id:<id> / data:json） */
    push(type: string, data: unknown, id = "") {
        const ev = new MessageEvent(type, {
            data: JSON.stringify(data),
            lastEventId: id,
        });
        for (const fn of this.listeners.get(type) ?? []) fn(ev);
        const prop = {
            open: this.onopen,
            error: this.onerror,
            message: this.onmessage,
        }[type];
        prop?.(ev);
    }
    /** 传输层失败——裸 Event（无 data），区别于具名 error 帧 */
    fail() {
        this.onerror?.(new Event("error"));
    }
    open() {
        this.readyState = FakeEventSource.OPEN;
        this.onopen?.(new Event("open"));
    }
}

// (status) 签名保留——progress 恒 50、时间戳钉 1（帧只读 status，值不参与断言）
const snap = (status: TaskSnapshot["status"]): TaskSnapshot =>
    fakeSnap("t1", { status, progress: 50, created_at: 1, updated_at: 1 });

const stage = (progress: number): StageEvent => ({
    stage: "translating",
    progress,
    message: `p${progress}`,
    at: 0,
});

const doneEv: DoneEvent = { status: "done", artifacts: {}, stats: {} };

const last = () => FakeEventSource.instances.at(-1)!;

beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("EventSource", FakeEventSource);
});

afterEach(() => {
    vi.unstubAllGlobals();
    forgetTaskEvents("t1");
    forgetTaskEvents("t2");
});

describe("openTaskEvents（seq 水位线去重）", () => {
    it("snapshot 帧 seq=0 恒放行（每连现场合成、非落盘）", () => {
        const snaps: string[] = [];
        openTaskEvents("t1", { snapshot: (s) => snaps.push(s.status) });
        last().push("snapshot", snap("translating"), "0");
        last().push("snapshot", snap("compiling"), "0");
        expect(snaps).toEqual(["translating", "compiling"]);
    });

    it("断线重连服务端重发 seq≤已见 的帧——同 channel 内去重", () => {
        const seen: number[] = [];
        openTaskEvents("t1", { stage: (e) => seen.push(e.progress) });
        const es = last();
        es.push("stage", stage(10), "1");
        es.push("stage", stage(20), "2");
        es.push("stage", stage(10), "1"); // 重放重复帧
        es.push("stage", stage(20), "2");
        es.push("stage", stage(30), "3");
        expect(seen).toEqual([10, 20, 30]);
    });

    it("retry 重放不毒化：旧轮全量事件（含 done）重放被水位线丢弃，本轮新事件照达", () => {
        const h1 = { done: vi.fn(), stage: vi.fn() };
        const ch1 = openTaskEvents("t1", h1);
        const es1 = last();
        es1.push("snapshot", snap("translating"), "0");
        es1.push("stage", stage(10), "1");
        es1.push("done", doneEv, "5");
        expect(h1.done).toHaveBeenCalledTimes(1);
        expect(ch1.closed).toBe(true);

        // resetLive→watch：新 EventSource 不带 Last-Event-ID → 服务端全量重放
        const h2 = { done: vi.fn(), stage: vi.fn(), snapshot: vi.fn() };
        const ch2 = openTaskEvents("t1", h2);
        const es2 = last();
        es2.push("snapshot", snap("translating"), "0");
        es2.push("stage", stage(10), "1"); // 旧轮重放——丢弃
        es2.push("done", doneEv, "5"); // 旧 done 重放——丢弃，不得关 channel
        es2.push("stage", stage(15), "6"); // 本轮新事件——照达
        expect(h2.snapshot).toHaveBeenCalledTimes(1);
        expect(h2.done).not.toHaveBeenCalled();
        expect(h2.stage).toHaveBeenCalledTimes(1);
        expect(h2.stage).toHaveBeenCalledWith(stage(15));
        expect(ch2.closed).toBe(false);
    });

    it("forgetTaskEvents（任务删除）清水位线——同 seq 帧可再次送达", () => {
        const seen: number[] = [];
        openTaskEvents("t1", { stage: (e) => seen.push(e.progress) });
        last().push("stage", stage(10), "1");
        forgetTaskEvents("t1");
        last().push("stage", stage(10), "1");
        expect(seen).toEqual([10, 10]);
    });

    it("不同 task_id 水位线独立", () => {
        const s1: number[] = [];
        const s2: number[] = [];
        openTaskEvents("t1", { stage: (e) => s1.push(e.progress) });
        openTaskEvents("t2", { stage: (e) => s2.push(e.progress) });
        const [es1, es2] = FakeEventSource.instances;
        es1.push("stage", stage(10), "3");
        es2.push("stage", stage(99), "3"); // 同 seq 不同任务——不互丢
        expect(s1).toEqual([10]);
        expect(s2).toEqual([99]);
    });
});

describe("openTaskEvents（error 帧 / transport）", () => {
    it("具名 event:error 帧走 h.error，不触发 transport=reconnecting", () => {
        const errs: TaskErrorEvent[] = [];
        const transports: TransportState[] = [];
        openTaskEvents("t1", {
            error: (e) => errs.push(e),
            transport: (s) => transports.push(s),
        });
        const es = last();
        es.open();
        es.push(
            "error",
            { code: "provider_error", message: "x", retryable: true },
            "3",
        );
        expect(errs).toEqual([
            { code: "provider_error", message: "x", retryable: true },
        ]);
        expect(transports).toEqual(["live"]); // 无 reconnecting
    });

    it("真·传输层失败（裸 Event）仍按 readyState 报 reconnecting/closed", () => {
        const transports: TransportState[] = [];
        const ch = openTaskEvents("t1", {
            transport: (s) => transports.push(s),
        });
        const es = last();
        es.readyState = FakeEventSource.OPEN;
        es.fail();
        expect(transports).toEqual(["reconnecting"]);
        es.readyState = FakeEventSource.CLOSED;
        es.fail();
        expect(transports).toEqual(["reconnecting", "closed"]);
        expect(ch.closed).toBe(true);
    });
});
