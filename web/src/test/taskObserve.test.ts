// @vitest-environment jsdom
// B2 任务观测面：pollListWanted 整表归并（外来在跑行自动 wanted + 消失行
// 收敛/pin 行保留）、track/intents 竞态桥（双侧 canon + TTL 60s + dropTask
// 反清 + pin 不踩）、activeCount 口径（interrupted 属终态不计）、完成通知
// 恰一次（SSE done / snapshot 终态+迟到 done / 存量不报 / 轮询路收敛 /
// deleted 静默 / retry rearm）与 Notification 显示门。
// jsdom 环境：toastStore 依赖 window.setTimeout（node 下 notifyDone 早退）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    snapshot: vi.fn(),
    deleteTask: vi.fn(),
    openTaskEvents: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const { clientModuleMock } = await import("./_taskkit");
    return clientModuleMock(importOriginal, mocks);
});

import { POLL_INTERVAL_MS, taskStore } from "../stores/tasks";
import { toast } from "../stores/toastStore";
import { snap as fakeSnap } from "./fakes";
import {
    channelOf,
    handlersOf,
    mkChannel,
    mkSnap,
    openedFor,
    trackWatches,
} from "./_taskkit";

const snap = mkSnap();

const used: string[] = [];
trackWatches(used, taskStore);

/** 竞态桥本体——测试隔离清桶用（facade 只读面 cast 回 Map） */
const intentsMap = () =>
    taskStore.intents as unknown as Map<string, { taskId: string }>;

beforeEach(() => {
    vi.useFakeTimers();
    mocks.tasks.mockReset().mockResolvedValue([]);
    mocks.snapshot
        .mockReset()
        .mockImplementation((id: string) =>
            Promise.resolve(snap(id, "translating")),
        );
    mocks.deleteTask.mockReset().mockResolvedValue(undefined);
    mocks.openTaskEvents.mockReset().mockImplementation(() => mkChannel());
    intentsMap().clear();
    toast.clear();
});

afterEach(() => {
    vi.restoreAllMocks();
    vi.clearAllTimers();
    vi.useRealTimers();
    toast.clear();
});

describe("pollListWanted 整表归并", () => {
    it("外来在跑行随拍自动 wanted 并入表（reader 停留期盲区修复）", async () => {
        mocks.tasks.mockImplementation(() =>
            Promise.resolve([
                snap("m1", "translating", 50),
                snap("m2", "translating", 40),
                snap("m3", "translating", 30),
                snap("m4", "translating", 20),
            ]),
        );
        used.push("m1", "m2", "m3", "m4");
        await taskStore.refresh();
        expect(openedFor(mocks)).toEqual(["m1", "m2", "m3"]); // m4 溢出→列表轮询

        // 下一拍响应多出外部新任务 x1（别处提交）——整表归并落行+登记观测
        mocks.tasks.mockImplementation(() =>
            Promise.resolve([
                snap("m1", "translating", 50),
                snap("m2", "translating", 40),
                snap("m3", "translating", 30),
                snap("m4", "translating", 20),
                snap("x1", "queued", 5),
            ]),
        );
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(taskStore.task("x1")?.status).toBe("queued");
        used.push("x1");

        // 已入观测面——后续状态推进靠共享轮询归并（非一次性快照）
        mocks.tasks.mockImplementation(() =>
            Promise.resolve([
                snap("m1", "translating", 50),
                snap("m2", "translating", 40),
                snap("m3", "translating", 30),
                snap("m4", "translating", 20),
                snap("x1", "translating", 6),
            ]),
        );
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(taskStore.task("x1")?.status).toBe("translating");
    });

    it("消失行收敛：非 pin 行即删；pin 行保留（自有通道管 404 生命周期）", async () => {
        mocks.tasks.mockImplementation(() =>
            Promise.resolve([
                snap("k1", "translating", 50),
                snap("k2", "translating", 40),
                snap("k3", "translating", 30),
                snap("k4", "translating", 20),
            ]),
        );
        used.push("k1", "k2", "k3", "k4", "pk");
        await taskStore.refresh();
        taskStore.watch("pk"); // pin——无行也可 watch，抢占 SSE 槽
        const pkChIdx = openedFor(mocks).indexOf("pk");
        expect(pkChIdx).toBeGreaterThanOrEqual(0);

        // 响应里没有 pk 也没有 k4：k4（非 pin）按已删收敛，pk（pin）保留观测
        mocks.tasks.mockImplementation(() =>
            Promise.resolve([
                snap("k1", "translating", 50),
                snap("k2", "translating", 40),
                snap("k3", "translating", 30),
            ]),
        );
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(taskStore.task("k4")).toBeUndefined();
        // pk 的 SSE 通道未被整表归并拆散（pin 的 404 走探活/快照路）
        expect(channelOf(mocks, pkChIdx).close).not.toHaveBeenCalled();
    });
});

describe("track / intents / taskByArxiv", () => {
    it("track 登记竞态桥：行未物化时合成 queued 占位行", () => {
        used.push("n1");
        taskStore.track("n1", { arxivId: "2301.00001v2" });
        const row = taskStore.taskByArxiv("2301.00001");
        expect(row?.task_id).toBe("n1");
        expect(row?.status).toBe("queued");
        expect(taskStore.taskStatusOf("2301.00001")).toBe("queued");
    });

    it("canon 双侧归一：URL/arXiv: 前缀、vN、class、大小写、safe-id 同键", () => {
        used.push("c1", "c2", "c3");
        taskStore.track("c1", { arxivId: "arXiv:2301.00003" });
        expect(
            taskStore.taskByArxiv("https://arxiv.org/abs/2301.00003v2")
                ?.task_id,
        ).toBe("c1");
        // 服务端历史行保留 class+大小写——两侧过 canon 后同键
        taskStore.track("c2", { arxivId: "math.GT/0309136" });
        expect(taskStore.taskByArxiv("math/0309136")?.task_id).toBe("c2");
        expect(taskStore.taskByArxiv("MATH.GT/0309136v1")?.task_id).toBe("c2");
        // benchlib safe_id 回流形 + DOI 前缀形
        taskStore.track("c3", { arxivId: "hep-th--9901001" });
        expect(taskStore.taskByArxiv("HEP-TH/9901001")?.task_id).toBe("c3");
        expect(
            taskStore.taskByArxiv(
                "https://doi.org/10.48550/arXiv.hep-th/9901001",
            )?.task_id,
        ).toBe("c3");
        // 无关/坏输入不误配
        expect(taskStore.taskByArxiv("1234.99999")).toBeUndefined();
        expect(taskStore.taskByArxiv("")).toBeUndefined();
    });

    it("行物化后返回真行；多行同 arxiv 取档 done|partial > 在跑 > 败终态", async () => {
        used.push("rk-d", "rk-a", "rk-f");
        taskStore.track("rk-a", { arxivId: "2301.00006" });
        mocks.tasks.mockResolvedValue([
            fakeSnap("rk-d", {
                status: "done",
                arxiv_id: "2301.00006",
                updated_at: 100,
            }),
            fakeSnap("rk-a", {
                status: "translating",
                arxiv_id: "2301.00006",
                updated_at: 200,
            }),
            fakeSnap("rk-f", {
                status: "fault",
                arxiv_id: "2301.00006",
                updated_at: 300,
            }),
        ]);
        await taskStore.refresh();
        // 真行压过竞态桥占位；可读终态优先于在跑/败终态
        expect(taskStore.taskByArxiv("2301.00006")?.task_id).toBe("rk-d");
        // done 行转 fault（retry 失败后重列）→ 在跑行顶上
        taskStore.patch("rk-d", { status: "fault" });
        expect(taskStore.taskByArxiv("2301.00006")?.task_id).toBe("rk-a");
    });

    it("intents TTL 60s：过期即不再桥接（惰性过期+清桶）", async () => {
        used.push("ttl1");
        taskStore.track("ttl1", { arxivId: "2301.00007" });
        expect(taskStore.taskByArxiv("2301.00007")?.task_id).toBe("ttl1");
        await vi.advanceTimersByTimeAsync(61_000); // Date.now 随假钟走
        expect(taskStore.taskByArxiv("2301.00007")).toBeUndefined();
        expect(intentsMap().size).toBe(0);
    });

    it("track 不踩既有 pin 标记：watch 后 track 同 id 仍占 SSE 槽", () => {
        used.push("pw");
        taskStore.watch("pw");
        taskStore.track("pw", { arxivId: "2301.00008" });
        expect(openedFor(mocks)).toEqual(["pw"]);
        // 幂等复用——channel 未重建未关闭
        expect(mocks.openTaskEvents).toHaveBeenCalledTimes(1);
        expect(channelOf(mocks, 0).close).not.toHaveBeenCalled();
    });

    it("任务删除反向清竞态桥——TTL 内也不再合成幽灵行", async () => {
        used.push("rm1");
        taskStore.track("rm1", { arxivId: "2301.00009" });
        await taskStore.remove("rm1");
        expect(taskStore.taskByArxiv("2301.00009")).toBeUndefined();
        expect(intentsMap().size).toBe(0);
    });
});

describe("activeCount 徽标口径", () => {
    it("非终态五态计数（done/fault/interrupted 等终态不计）", async () => {
        mocks.tasks.mockResolvedValue([
            snap("ac1", "queued", 60),
            snap("ac2", "translating", 50),
            snap("ac3", "compiling", 40),
            snap("ac4", "done", 30),
            snap("ac5", "interrupted", 20),
            snap("ac6", "fault", 10),
        ]);
        used.push("ac1", "ac2", "ac3");
        await taskStore.refresh();
        expect(taskStore.activeCount()).toBe(3);
    });
});

describe("完成通知（恰一次）", () => {
    it("SSE done 帧 → toast 一次：key 幂等 + 查看 action 跳 reader", async () => {
        mocks.tasks.mockResolvedValue([
            fakeSnap("n1", { status: "translating", title: "Paper A" }),
        ]);
        used.push("n1");
        await taskStore.refresh();
        handlersOf(mocks, 0).done?.({
            status: "done",
            artifacts: {},
            stats: {},
        });
        expect(toast.toasts()).toHaveLength(1);
        const t0 = toast.toasts()[0];
        expect(t0?.kind).toBe("ok");
        expect(t0?.key).toBe("texlate-n1");
        expect(t0?.text).toContain("Paper A");
        expect(t0?.action?.href).toBe("#/reader/n1");
    });

    it("snapshot 终态先行 + 迟到 done 帧 → 恰一次（双写点守卫）", async () => {
        mocks.tasks.mockResolvedValue([
            fakeSnap("n2", { status: "translating" }),
        ]);
        used.push("n2");
        await taskStore.refresh();
        const h = handlersOf(mocks, 0);
        // snapshot 帧先报终态——convergeTerminal 合成 done 并发通知
        h.snapshot?.(fakeSnap("n2", { status: "done" }));
        expect(toast.toasts()).toHaveLength(1);
        // 真实 done 帧迟到——hadDone 守卫拒重发，live.done 仍换成真帧
        h.done?.({
            status: "done",
            artifacts: { dual: "x" },
            stats: { tokens: 1 },
        });
        expect(toast.toasts()).toHaveLength(1);
        expect(taskStore.live("n2")?.done?.stats.tokens).toBe(1);
    });

    it("refresh 首见终态的存量行不报（未 wanted 不 converge）", async () => {
        mocks.tasks.mockResolvedValue([
            fakeSnap("n3", { status: "done" }),
            fakeSnap("n4", { status: "fault" }),
        ]);
        await taskStore.refresh();
        expect(toast.toasts()).toHaveLength(0);
    });

    it("轮询路终态（槽外任务经共享列表收敛）→ 报一次", async () => {
        mocks.tasks.mockImplementation(() =>
            Promise.resolve([
                snap("p1", "translating", 50),
                snap("p2", "translating", 40),
                snap("p3", "translating", 30),
                snap("p4", "translating", 20),
            ]),
        );
        used.push("p1", "p2", "p3", "p4");
        await taskStore.refresh(); // p4 溢出→共享列表轮询
        mocks.tasks.mockImplementation(() =>
            Promise.resolve([
                snap("p1", "translating", 50),
                snap("p2", "translating", 40),
                snap("p3", "translating", 30),
                fakeSnap("p4", { status: "done", title: "P4" }),
            ]),
        );
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(
            toast.toasts().filter((x) => x.key === "texlate-p4"),
        ).toHaveLength(1);
        // 后续拍里终态行仍在列表——收敛过且已摘除，不再重报
        await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS);
        expect(
            toast.toasts().filter((x) => x.key === "texlate-p4"),
        ).toHaveLength(1);
    });

    it("deleted 收尾帧静默不报", async () => {
        mocks.tasks.mockResolvedValue([
            fakeSnap("n5", { status: "translating" }),
        ]);
        used.push("n5");
        await taskStore.refresh();
        handlersOf(mocks, 0).done?.({
            status: "deleted",
            artifacts: {},
            stats: {},
        });
        expect(toast.toasts()).toHaveLength(0);
        expect(taskStore.task("n5")).toBeUndefined();
    });

    it("retry 新轮：resetLive 清 done rearm——第二个 done 再报一次", async () => {
        mocks.tasks.mockResolvedValue([
            fakeSnap("n6", { status: "translating", title: "P6" }),
        ]);
        used.push("n6");
        await taskStore.refresh();
        const okSpy = vi.spyOn(toast, "ok");
        handlersOf(mocks, 0).done?.({
            status: "done",
            artifacts: {},
            stats: {},
        });
        expect(okSpy).toHaveBeenCalledTimes(1);
        // retry 同款序：patch 回 queued + resetLive（taskActions.retry）
        taskStore.patch("n6", { status: "queued", progress: 0 });
        taskStore.resetLive("n6");
        // merge 语义不清缺席键——显式清后 live.done 必须不在场（rearm）
        expect(taskStore.live("n6")?.done).toBeUndefined();
        handlersOf(mocks, 1).done?.({
            status: "done",
            artifacts: {},
            stats: {},
        });
        expect(okSpy).toHaveBeenCalledTimes(2); // 新轮再报一次
        // 同 key 入栈刷新而非叠新条
        expect(toast.toasts()).toHaveLength(1);
    });

    it("isFailed 终态走 err 变体", async () => {
        mocks.tasks.mockResolvedValue([
            fakeSnap("n8", { status: "translating", title: "P8" }),
        ]);
        used.push("n8");
        await taskStore.refresh();
        const errSpy = vi.spyOn(toast, "err");
        handlersOf(mocks, 0).done?.({
            status: "fault",
            artifacts: {},
            stats: {},
        });
        expect(errSpy).toHaveBeenCalledTimes(1);
        expect(toast.toasts()[0]?.kind).toBe("err");
        expect(toast.toasts()[0]?.key).toBe("texlate-n8");
    });

    it("显示门：document.hidden + 已授权 → Notification（tag 幂等）不走 toast", async () => {
        mocks.tasks.mockResolvedValue([
            fakeSnap("n7", { status: "translating", title: "P7" }),
        ]);
        used.push("n7");
        await taskStore.refresh();
        const created: { body: string; tag?: string }[] = [];
        class FakeNotification {
            static permission = "granted";
            onclick: (() => void) | null = null;
            constructor(body: string, opts?: { tag?: string }) {
                created.push({ body, tag: opts?.tag });
            }
        }
        const prevHidden = Object.getOwnPropertyDescriptor(document, "hidden");
        Object.defineProperty(document, "hidden", {
            value: true,
            configurable: true,
        });
        (globalThis as Record<string, unknown>).Notification = FakeNotification;
        try {
            handlersOf(mocks, 0).done?.({
                status: "done",
                artifacts: {},
                stats: {},
            });
        } finally {
            delete (globalThis as Record<string, unknown>).Notification;
            if (prevHidden)
                Object.defineProperty(document, "hidden", prevHidden);
            else delete (document as unknown as Record<string, unknown>).hidden;
        }
        expect(created).toHaveLength(1);
        expect(created[0]?.tag).toBe("texlate-n7");
        expect(created[0]?.body).toContain("P7");
        expect(toast.toasts()).toHaveLength(0);
    });
});
