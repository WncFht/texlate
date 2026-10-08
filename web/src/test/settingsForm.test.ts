// @vitest-environment jsdom
// Settings 表单行为：saving 门防重入（Enter 隐式提交不走 disabled 按钮）、
// concurrency 夹取口径同 Home（1–16）、任务策略面不再外发任何端点/凭据键。

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    getSettings: vi.fn(),
    putSettings: vi.fn(),
    getChannels: vi.fn(),
    getChannelPresets: vi.fn(),
}));

// vi.mock 工厂收敛到 _taskkit.clientModuleMock——mocks 全键进 api 覆写
vi.mock("../api/client", async (importOriginal) => {
    const { clientModuleMock } = await import("./_taskkit");
    return clientModuleMock(importOriginal, mocks);
});

import Settings from "../pages/Settings";
import { flush } from "./_taskkit";
import { resetHomeMocks, type } from "./_homekit";
import { mountToBody } from "./helpers";

function mount() {
    mountToBody(() => Settings());
    const form =
        document.body.querySelector<HTMLFormElement>("form.settings-form");
    if (!form) throw new Error("settings form missing");
    const num =
        form.querySelector<HTMLInputElement>('[name="concurrency"]') ??
        form.querySelector<HTMLInputElement>('input[type="number"]');
    if (!num) throw new Error("fields missing");
    return { form, num };
}

function submit(form: HTMLFormElement) {
    form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
    );
}

beforeEach(() => {
    // 统一复位 + channels 空视图走 _homekit（Settings 页挂 ChannelsPanel——
    // onMount 拉 getChannels/getChannelPresets，缺桩会穿透真 fetch）
    resetHomeMocks(mocks);
    mocks.getSettings.mockResolvedValue({
        target_lang: "zh-CN",
        concurrency: 3,
        engine: "auto",
        context_guidance: true,
    });
    mocks.putSettings.mockResolvedValue({});
});
// 挂载摘除+body 清场由 helpers.ts 顶层 afterEach 兜底——本文件无文件级清理

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

    it("concurrency 空白 → 不送 concurrency 字段（空串后端 int() 会 400）", async () => {
        const { form, num } = mount();
        await flush();
        type(num, "");

        submit(form);
        await vi.waitFor(() => expect(mocks.putSettings).toHaveBeenCalled());

        const sent = mocks.putSettings.mock.calls[0][0] as Record<
            string,
            unknown
        >;
        expect("concurrency" in sent).toBe(false);
    });

    it("任务策略面回归闸：PUT 载荷不含任何端点/凭据键", async () => {
        const { form } = mount();
        await flush();

        submit(form);
        await vi.waitFor(() => expect(mocks.putSettings).toHaveBeenCalled());

        const sent = mocks.putSettings.mock.calls[0][0] as Record<
            string,
            unknown
        >;
        expect(sent).toEqual(
            expect.objectContaining({
                target_lang: "zh-CN",
                engine: "auto",
                context_guidance: true,
            }),
        );
        for (const k of [
            "api_key",
            "base_url",
            "model",
            "dialect",
            "clear_api_key",
        ]) {
            expect(k in sent).toBe(false);
        }
    });
});
