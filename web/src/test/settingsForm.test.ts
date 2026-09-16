// @vitest-environment jsdom
// Settings 表单行为：saving 门防重入（Enter 隐式提交不走 disabled 按钮）、
// concurrency 夹取口径同 Home（1–16）、标量字段 trim 后再 PUT。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    getSettings: vi.fn(),
    putSettings: vi.fn(),
    providers: vi.fn(),
    testSettings: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: {
            ...mod.api,
            getSettings: mocks.getSettings,
            putSettings: mocks.putSettings,
            providers: mocks.providers,
            testSettings: mocks.testSettings,
        },
    };
});

import { render } from "solid-js/web";
import Settings from "../pages/Settings";

const flush = () => new Promise((r) => setTimeout(r, 0));
let dispose: (() => void) | undefined;

function mount() {
    dispose = render(() => Settings(), document.body);
    const form = document.body.querySelector<HTMLFormElement>("form.settings-form");
    if (!form) throw new Error("settings form missing");
    const num = form.querySelector<HTMLInputElement>('input[type="number"]');
    const url = form.querySelector<HTMLInputElement>('input[type="url"]');
    const pwd = form.querySelector<HTMLInputElement>('input[type="password"]');
    const modelInput = form.querySelector<HTMLInputElement>(
        'input[list="provider-models"]',
    );
    if (!num || !url || !pwd || !modelInput) throw new Error("fields missing");
    return { form, num, url, pwd, modelInput };
}

function type(el: HTMLInputElement, v: string) {
    el.value = v;
    el.dispatchEvent(new Event("input", { bubbles: true }));
}

function submit(form: HTMLFormElement) {
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
}

beforeEach(() => {
    for (const m of Object.values(mocks)) m.mockReset();
    mocks.getSettings.mockResolvedValue({
        has_api_key: false,
        base_url: "https://gw/v1",
        model: "m0",
        target_lang: "zh-CN",
        concurrency: 3,
        engine: "auto",
        context_guidance: true,
    });
    mocks.providers.mockResolvedValue({ providers: [] });
    mocks.putSettings.mockResolvedValue({ has_api_key: false });
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
});

describe("Settings 表单提交", () => {
    it("saving 门：PUT 未决期间重复提交只发一次", async () => {
        mocks.putSettings.mockImplementation(() => new Promise(() => {}));
        const { form } = mount();
        await flush();

        submit(form);
        submit(form);
        submit(form);
        await flush();

        expect(mocks.putSettings).toHaveBeenCalledTimes(1);
    });

    it("concurrency 99 → 夹到 16（与 Home 选项口径一致）", async () => {
        const { form, num } = mount();
        await flush();
        type(num, "99");

        submit(form);
        await vi.waitFor(() => expect(mocks.putSettings).toHaveBeenCalled());

        expect(mocks.putSettings).toHaveBeenCalledWith(
            expect.objectContaining({ concurrency: 16 }),
        );
    });

    it("base_url/model/api_key trim 后送出；空 api_key 不送字段", async () => {
        const { form, url, pwd, modelInput } = mount();
        await flush();
        type(url, "  https://gw2/v1  ");
        type(modelInput, "  m2  ");
        type(pwd, "  sk-trim  ");

        submit(form);
        await vi.waitFor(() => expect(mocks.putSettings).toHaveBeenCalled());

        expect(mocks.putSettings).toHaveBeenCalledWith(
            expect.objectContaining({
                base_url: "https://gw2/v1",
                model: "m2",
                api_key: "sk-trim",
            }),
        );
    });

    it("api_key 全空白 → 不带 api_key 字段", async () => {
        const { form, pwd } = mount();
        await flush();
        type(pwd, "   ");

        submit(form);
        await vi.waitFor(() => expect(mocks.putSettings).toHaveBeenCalled());

        expect(mocks.putSettings).toHaveBeenCalledWith(
            expect.not.objectContaining({ api_key: expect.anything() }),
        );
        const sent = mocks.putSettings.mock.calls[0][0] as Record<string, unknown>;
        expect("api_key" in sent).toBe(false);
    });
});
