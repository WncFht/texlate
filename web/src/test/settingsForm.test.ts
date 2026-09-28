// @vitest-environment jsdom
// Settings 表单行为：saving 门防重入（Enter 隐式提交不走 disabled 按钮）、
// concurrency 夹取口径同 Home（1–16）、标量字段 trim 后再 PUT。

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    getSettings: vi.fn(),
    putSettings: vi.fn(),
    providers: vi.fn(),
    testSettings: vi.fn(),
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
    // 优先 [name=] 稳定口（同 model 字段先例）；Settings.tsx 的
    // api_key/base_url/concurrency 尚未挂 name 属性——挂上后本查询自动走
    // name 路，目前落到 input-type 唯一性兜底
    const num =
        form.querySelector<HTMLInputElement>('[name="concurrency"]') ??
        form.querySelector<HTMLInputElement>('input[type="number"]');
    const url =
        form.querySelector<HTMLInputElement>('[name="base_url"]') ??
        form.querySelector<HTMLInputElement>('input[type="url"]');
    const pwd =
        form.querySelector<HTMLInputElement>('[name="api_key"]') ??
        form.querySelector<HTMLInputElement>('input[type="password"]');
    // model 字段随预设态在 input/select 间切换——name 属性做稳定查询口
    const modelInput = form.querySelector<HTMLInputElement>('[name="model"]');
    if (!num || !url || !pwd || !modelInput) throw new Error("fields missing");
    return { form, num, url, pwd, modelInput };
}

function submit(form: HTMLFormElement) {
    form.dispatchEvent(
        new Event("submit", { bubbles: true, cancelable: true }),
    );
}

beforeEach(() => {
    // 统一复位 + providers 空表走 _homekit；getSettings/putSettings 覆写本文件值
    resetHomeMocks(mocks);
    mocks.getSettings.mockResolvedValue({
        has_api_key: false,
        base_url: "https://gw/v1",
        model: "m0",
        target_lang: "zh-CN",
        concurrency: 3,
        engine: "auto",
        context_guidance: true,
    });
    mocks.putSettings.mockResolvedValue({ has_api_key: false });
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

    it("base_url/model/api_key trim 后送出；空 api_key 不送字段", async () => {
        const { form, url, pwd, modelInput } = mount();
        await flush();
        type(url, "  https://gw2/v1  ");
        // providers mock 为空 → 自定义态 → model 是自由 input
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
        const sent = mocks.putSettings.mock.calls[0][0] as Record<
            string,
            unknown
        >;
        expect("api_key" in sent).toBe(false);
    });
});
