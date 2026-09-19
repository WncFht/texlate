// @vitest-environment jsdom
// Home 表单临时 API Key：填了 → translate 第三参 byok 透传 + 提交成功即清；
// 空/纯空白 → 不带 byok（per-request 语义，不落 settings store）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    health: vi.fn(),
    getSettings: vi.fn(),
    putSettings: vi.fn(),
    providers: vi.fn(),
    translate: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: {
            ...mod.api,
            tasks: mocks.tasks,
            health: mocks.health,
            getSettings: mocks.getSettings,
            putSettings: mocks.putSettings,
            providers: mocks.providers,
            translate: mocks.translate,
        },
    };
});

import { render } from "solid-js/web";
import Home from "../pages/Home";

const flush = () => new Promise((r) => setTimeout(r, 0));

// collectOptions 恒写 front_matter（UI 态即意图）——裸提交的 options 形
const FM_OPTS = {
    options: {
        front_matter: { abstract: true, title: true, author: false },
    },
};

let dispose: (() => void) | undefined;

function mount() {
    const nav = vi.fn();
    dispose = render(() => Home({ nav }), document.body);
    const input = document.body.querySelector<HTMLInputElement>(".arxiv-input");
    const key = document.body.querySelector<HTMLInputElement>(
        '.task-opts input[type="password"]',
    );
    const form = document.body.querySelector<HTMLFormElement>("form");
    if (!input || !key || !form) throw new Error("form elements missing");
    return { nav, input, key, form };
}

function type(el: HTMLInputElement, v: string) {
    el.value = v;
    el.dispatchEvent(new Event("input", { bubbles: true }));
}

beforeEach(() => {
    mocks.tasks.mockReset().mockResolvedValue({ tasks: [] });
    mocks.health.mockReset().mockResolvedValue({ ok: true, version: "t", compilers: {} });
    mocks.getSettings.mockReset().mockResolvedValue({ has_api_key: false });
    mocks.putSettings.mockReset();
    mocks.providers.mockReset().mockResolvedValue({ providers: [] });
    mocks.translate.mockReset().mockResolvedValue({
        task_id: "t_0000000000000f01",
        status: "queued",
        events_url: "/api/task/t_0000000000000f01",
        reader_url: "/api/task/t_0000000000000f01/reader",
    });
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
});

describe("Home 临时 API Key（per-request BYOK）", () => {
    it("填 key 提交 → translate 带 {apiKey}，成功后清空输入", async () => {
        const { nav, input, key, form } = mount();
        type(input, "2501.14787");
        type(key, "sk-temp-1");

        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());
        await flush();

        expect(mocks.translate).toHaveBeenCalledWith("2501.14787", FM_OPTS, {
            apiKey: "sk-temp-1",
        });
        expect(nav).toHaveBeenCalledWith("#/reader/t_0000000000000f01");
        expect(key.value).toBe("");
    });

    it("不填 key → byok 参 undefined（现状不变）", async () => {
        const { input, form } = mount();
        type(input, "2501.14787");

        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());

        expect(mocks.translate).toHaveBeenCalledWith("2501.14787", FM_OPTS, undefined);
    });

    it("纯空白 key 视同未填 → 不透传", async () => {
        const { input, key, form } = mount();
        type(input, "2501.14787");
        type(key, "   ");

        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());

        expect(mocks.translate).toHaveBeenCalledWith("2501.14787", FM_OPTS, undefined);
    });

    it("临时 key 不触碰 settings store（纯 per-request，不发 PUT）", async () => {
        const { input, key, form } = mount();
        type(input, "2501.14787");
        type(key, "sk-temp-2");

        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());
        await flush();

        expect(mocks.putSettings).not.toHaveBeenCalled();
    });
});
