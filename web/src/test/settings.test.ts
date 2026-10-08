import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    getSettings: vi.fn(),
    putSettings: vi.fn(),
    getChannels: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: {
            ...mod.api,
            getSettings: mocks.getSettings,
            putSettings: mocks.putSettings,
            getChannels: mocks.getChannels,
        },
    };
});

import { ApiError } from "../api/client";
import { settingsStore } from "../stores/settings";
import { EMPTY_CHANNELS } from "./_homekit";

const CHANNELS_VIEW = {
    channels: [
        {
            id: "ch-1",
            name: "主渠道",
            preset: "custom",
            base_url: "https://x",
            protocol: "auto",
            models: [],
            priority: 1,
            max_concurrency: null,
            enabled: true,
            has_api_key: true,
            key_env: "",
            has_env_key: false,
        },
    ],
    route: { channel_id: "auto", model: "" },
    active_id: "ch-1",
    active_model: "m1",
};

beforeEach(() => {
    mocks.getSettings.mockReset();
    mocks.putSettings.mockReset();
    mocks.getChannels.mockReset().mockResolvedValue(EMPTY_CHANNELS);
});

describe("settingsStore（设置读写 + 渠道凭证门）", () => {
    // 本用例必须居首——store 是模块级单例，refresh 一旦成功 settings
    // 即非 null，失败臂的 settings()==null 断言就再不可达
    it("refresh：getSettings 失败仍放 loaded（Settings 页不停空表单）", async () => {
        mocks.getSettings.mockRejectedValue(new Error("down"));

        await settingsStore.refresh();

        expect(settingsStore.loaded()).toBe(true);
        expect(settingsStore.settings()).toBeNull();
    });

    it("refresh：GET settings + channels 同帧拉，channels 非 403 失败不阻塞", async () => {
        mocks.getSettings.mockResolvedValue({ target_lang: "zh-CN" });
        mocks.getChannels.mockRejectedValueOnce(new Error("down"));

        await settingsStore.refresh();

        expect(settingsStore.loaded()).toBe(true);
        expect(settingsStore.settings()?.target_lang).toBe("zh-CN");
        // 非 403 失败不动渠道面——保留旧视图也不置形态闸（store 单例，
        // 上一用例已写入 EMPTY_CHANNELS，stale-keep 即设计语义）
        expect(settingsStore.channelsOff()).toBe(false);
    });

    it('hasCredential/routedModel：active_id 决议口径（无渠道 → false/""）', async () => {
        mocks.getSettings.mockResolvedValue({});
        mocks.getChannels.mockResolvedValueOnce(CHANNELS_VIEW);
        await settingsStore.refresh();
        expect(settingsStore.hasCredential()).toBe(true);
        expect(settingsStore.routedModel()).toBe("m1");

        mocks.getChannels.mockResolvedValueOnce(EMPTY_CHANNELS);
        await settingsStore.refresh();
        expect(settingsStore.hasCredential()).toBe(false);
        expect(settingsStore.routedModel()).toBe("");
    });

    it("save 普通字段：响应合并进既有 settings（局部更新不丢字段）", async () => {
        mocks.getSettings.mockResolvedValue({
            target_lang: "zh-CN",
            engine: "auto",
        });
        await settingsStore.refresh();

        mocks.putSettings.mockResolvedValue({
            target_lang: "en",
            engine: "auto",
        });
        await settingsStore.save({ target_lang: "en" });

        expect(settingsStore.settings()?.target_lang).toBe("en");
        expect(settingsStore.settings()?.engine).toBe("auto");
    });

    it("save：回执带 ignored 落 store；下轮回执缺席时归零不挂留", async () => {
        mocks.getSettings.mockResolvedValue({ target_lang: "zh-CN" });
        await settingsStore.refresh();

        mocks.putSettings.mockResolvedValueOnce({
            target_lang: "zh-CN",
            ignored: ["mystery_key"],
        });
        await settingsStore.save({ target_lang: "zh-CN" });
        expect(settingsStore.settings()?.ignored).toEqual(["mystery_key"]);

        // 第二轮响应无 ignored 字段——浅合并会挂留旧值，归一 ?? [] 兜底
        mocks.putSettings.mockResolvedValueOnce({ target_lang: "zh-CN" });
        await settingsStore.save({ target_lang: "zh-CN" });
        expect(settingsStore.settings()?.ignored).toEqual([]);
    });

    // 本用例必须居末——403 会把 channelsOff 钉成 true（store 单例态不回滚），
    // 影响后续用例的 hasCredential 口径
    it("channels 403（server 形态）：channelsOff 置位，hasCredential 不闸（undefined）", async () => {
        mocks.getSettings.mockResolvedValue({});
        mocks.getChannels.mockRejectedValueOnce(
            new ApiError(403, "server 形态不提供渠道面"),
        );

        await settingsStore.refresh();

        expect(settingsStore.channelsOff()).toBe(true);
        expect(settingsStore.channels()).toBeNull();
        expect(settingsStore.hasCredential()).toBeUndefined();
        expect(settingsStore.routedModel()).toBe("");
    });
});
