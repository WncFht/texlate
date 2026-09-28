// _taskkit —— taskStore/TaskList 测试共享脚手架（tests/_fixloopkit.py 同款
// 约定：_* 前缀 = 测试内件，不进被测面，vite test include 只收 *.test.ts）。
// vi.mock 工厂被 vitest 提升、不能引用本文件顶层 import——工厂内经
// `await import("./_taskkit")` 取用（动态 import 是唯一通路）。
// 本件保持 node-env 可引：不得静态 import solid-js/web / 组件树（顶层求值
// 触 window）；TaskList 渲染臂在 _taskdom.ts（jsdom 专属文件才引）。
// 同 _homekit 约定：不得静态 import 任何经 ../api/client 的应用模块——
// 本件在 api/client 的 vi.mock 工厂内被 await，静态引 tasks.ts 会成环、
// 让 tasks.ts 绑到真 api（store 侧 mock 全哑火）；要 store 的件一律由
// 调用方注入（trackWatches 的 store 参）。
//
// 现收养方：liveFixes / taskListUx / taskListFilter；同构脚手架在
// liveFixloop / readerUnmount / liveReading / tasksWatch 等文件仍是本地
// 副本，后续波次平移到此（跨包文件未在本轮权属内）。

import { afterEach, vi, type Mock } from "vitest";
import type {
    TaskChannel,
    TaskEventHandlers,
    TaskSnapshot,
} from "../api/client";
/** unwatch 能力面——调用方注入 taskStore（本件不得静态引 stores，成环见头注） */
export interface Unwatcher {
    unwatch(taskId: string): void;
}

/** 一拍宏任务——Solid 渲染/微任务链沉降 */
export const flush = () => new Promise((r) => setTimeout(r, 0));

// snap(id, over) 归一到共享 fakes.ts（status↔progress 耦合同源：done→100
// 否则 40）——本件不再私存一份快照桩
export { snap } from "./fakes";

/**
 * live 族快照桩工厂：mkSnap(over?) → (id, status, updated) 签名。
 * done 归一 progress=100 否则 40；updated=0 回基线戳（live 族文件同口径）。
 */
export const mkSnap =
    (over: Partial<TaskSnapshot> = {}) =>
    (
        id: string,
        status: TaskSnapshot["status"],
        updated = 0,
    ): TaskSnapshot => ({
        task_id: id,
        kind: "arxiv",
        status,
        progress: status === "done" ? 100 : 40,
        created_at: 1_700_000_000,
        updated_at: updated || 1_700_000_000,
        ...over,
    });

/**
 * ../api/client vi.mock 工厂共用件：importOriginal 直接传入（工厂内 await
 * 解析），mocks 按键名分流——openTaskEvents 是顶层导出，其余进 api 覆写。
 * 用法：`vi.mock("../api/client", (o) => kit.clientModuleMock(o, mocks))`。
 */
export const clientModuleMock = async <M extends { api: object }>(
    importOriginal: () => Promise<M>,
    mocks: Record<string, unknown>,
    topKeys: readonly string[] = ["openTaskEvents"],
) => {
    const mod = await importOriginal();
    const api: Record<string, unknown> = { ...mod.api };
    const top: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(mocks)) {
        if (topKeys.includes(k)) top[k] = v;
        else api[k] = v;
    }
    return { ...mod, api, ...top };
};

/** openTaskEvents 通道桩：closed 随 close() 翻转（生产 TaskChannel 同语义） */
export const mkChannel = (): TaskChannel & { close: Mock } => {
    const ch = {
        closed: false,
        close: vi.fn(() => {
            ch.closed = true;
        }),
    };
    return ch;
};

// ---- openTaskEvents mock 访问件：各文件 hoisted mocks 对象作参传入 ----

export const handlersOf = (
    mocks: { openTaskEvents: Mock },
    i: number,
): TaskEventHandlers =>
    mocks.openTaskEvents.mock.calls[i]?.[1] as TaskEventHandlers;

export const channelOf = (mocks: { openTaskEvents: Mock }, i: number) =>
    mocks.openTaskEvents.mock.results[i]?.value as TaskChannel & {
        close: Mock;
    };

export const openedFor = (mocks: { openTaskEvents: Mock }) =>
    mocks.openTaskEvents.mock.calls.map((c) => c[0] as string);

/**
 * afterEach 统一摘 watch：used 桶收集的 taskId 全 unwatch 并清桶（幂等）。
 * store 由调用方注入（taskStore）——本件静态引它会与 vi.mock 工厂成环。
 * 在文件顶层调用一次即注册；计时器复位等其他清理仍归各文件 afterEach。
 */
export const trackWatches = (used: string[], store: Unwatcher) => {
    afterEach(() => {
        for (const id of used) store.unwatch(id);
        used.length = 0;
    });
};
