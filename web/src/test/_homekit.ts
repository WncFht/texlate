// Home 页测试共享夹具（对齐 tests/_fixloopkit.py 约定；vite include
// `src/**/*.test.ts` 不会把本文件当测试跑）。
//
// vi.mock 提升限制：hoisted 工厂不能引用本模块的顶层 import，故各文件
// 仍自留 vi.hoisted mocks 字面量，工厂体内 `await import("./_homekit")`
// 取 buildApiModule 组装模块形——本文件也不得静态 import 任何经
// ../api/client 的应用模块（否则 vi.mock 工厂内加载本模块时成环）。

import { render } from "solid-js/web";
import { afterEach, vi, type Mock } from "vitest";
import type { Component } from "solid-js";

/** translate/upload/shareImport 共用回执（queued 建行形，t_…0f01） */
export const RESP = {
    task_id: "t_0000000000000f01",
    status: "queued",
    events_url: "/api/task/t_0000000000000f01",
    reader_url: "/api/task/t_0000000000000f01/reader",
};

export const flush = () => new Promise((r) => setTimeout(r, 0));

// collectOptions 恒写 front_matter（UI 态即意图）——translate fields /
// upload fields.options 共用的 options 形
export const FM_OPTS = {
    options: {
        front_matter: { abstract: true, title: true, author: false },
    },
};

/** Home 面 api 成员的兜底桩返回值——未声明成员不得穿透 ...mod.api 打真
 *  fetch（settingsStore.refresh 的 providers 轮询即一例真泄漏） */
const HOME_API_DEFAULTS: Record<string, () => unknown> = {
    tasks: () => [],
    health: () => ({ ok: true, version: "t", compilers: {} }),
    getSettings: () => ({ has_api_key: false }),
    putSettings: () => ({}),
    providers: () => ({ providers: [] }),
    translate: () => RESP,
    upload: () => RESP,
    shareImport: () => RESP,
    discoverSearch: () => [],
};

/**
 * 在 `vi.mock("../api/client", async (io) => ...)` 工厂体内调用：
 *   vi.mock("../api/client", async (io) =>
 *       (await import("./_homekit")).buildApiModule(await io(), mocks));
 * mocks 缺口的 Home 面成员自动补桩（见上），防真 fetch 穿透。
 */
export function buildApiModule(
    mod: typeof import("../api/client"),
    mocks: Record<string, Mock>,
) {
    const api = { ...mod.api } as Record<string, unknown>;
    for (const [name, dflt] of Object.entries(HOME_API_DEFAULTS)) {
        api[name] =
            mocks[name] ??
            vi.fn().mockImplementation(() => Promise.resolve(dflt()));
    }
    for (const [name, m] of Object.entries(mocks)) api[name] = m;
    return { ...mod, api };
}

/** beforeEach 统一复位 + 默认值（各文件只声明自己要断言的成员） */
export function resetHomeMocks(mocks: Record<string, Mock>) {
    for (const m of Object.values(mocks)) m.mockReset();
    // api.tasks 返裸数组（非 {tasks} 信封——rest.ts 翻页已拍平）
    mocks.tasks?.mockResolvedValue([]);
    mocks.health?.mockResolvedValue({ ok: true, version: "t", compilers: {} });
    mocks.getSettings?.mockResolvedValue({ has_api_key: false });
    mocks.putSettings?.mockResolvedValue({});
    mocks.providers?.mockResolvedValue({ providers: [] });
    mocks.translate?.mockResolvedValue(RESP);
    mocks.upload?.mockResolvedValue(RESP);
    mocks.shareImport?.mockResolvedValue(RESP);
    mocks.discoverSearch?.mockResolvedValue([]);
}

let dispose: (() => void) | undefined;

/** 挂载 Home 并返回全集选择器（各文件按需解构） */
export function mountHome(Home: Component<{ nav: (hash: string) => void }>) {
    const nav = vi.fn();
    dispose = render(() => Home({ nav }), document.body);
    const q = <T extends Element>(sel: string) =>
        document.body.querySelector<T>(sel);
    const input = q<HTMLInputElement>(".arxiv-input");
    const key = q<HTMLInputElement>('.task-opts input[type="password"]');
    const form = q<HTMLFormElement>("form");
    const file = q<HTMLInputElement>('input[type="file"]');
    const upBtn = q<HTMLButtonElement>("form button.btn-ghost");
    if (!input || !key || !form || !file || !upBtn)
        throw new Error("form elements missing");
    return { nav, input, key, form, file, upBtn };
}

/** 中途卸载（在飞请求落地不劫持路由等用例）——幂等 */
export function unmountHome() {
    dispose?.();
    dispose = undefined;
}

export function type(el: HTMLInputElement, v: string) {
    el.value = v;
    el.dispatchEvent(new Event("input", { bubbles: true }));
}

/** 隐藏 file input 选文件（jsdom 无 DataTransfer 构造需求，直接灌 files） */
export function pick(el: HTMLInputElement, f: File | File[]) {
    Object.defineProperty(el, "files", {
        value: Array.isArray(f) ? f : [f],
        configurable: true,
    });
    el.dispatchEvent(new Event("change", { bubbles: true }));
}

// 顶层 afterEach 在导入文件收集期绑定到该文件根 suite——勿挪进 mountHome
//（it 内注册会绑到过期 suite 并逐次叠加）。node 环境文件（如 idempotency）
// 只 import RESP 时无 document——guard 兜底。
afterEach(() => {
    unmountHome();
    if (typeof document !== "undefined") document.body.innerHTML = "";
});
