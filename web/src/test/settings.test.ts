import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    getSettings: vi.fn(),
    putSettings: vi.fn(),
    providers: vi.fn(),
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
        },
    };
});

import { settingsStore } from "../stores/settings";

beforeEach(() => {
    mocks.getSettings.mockReset();
    mocks.putSettings.mockReset();
    mocks.providers.mockReset().mockResolvedValue({ providers: [] });
});

describe("settingsStore（BYOK 设置读写）", () => {
    it("refresh：GET settings 落 store，providers 失败不阻塞", async () => {
        mocks.getSettings.mockResolvedValue({
            has_api_key: true,
            base_url: "https://x",
            model: "m",
        });
        mocks.providers.mockRejectedValueOnce(new Error("down"));

        await settingsStore.refresh();

        expect(settingsStore.loaded()).toBe(true);
        expect(settingsStore.settings()?.has_api_key).toBe(true);
        expect(settingsStore.providers()).toEqual([]);
    });

    it("save({clear_api_key:true})：伪字段透传 PUT，响应 has_api_key=false 落 store", async () => {
        mocks.getSettings.mockResolvedValue({
            has_api_key: true,
            base_url: "https://x",
            model: "m",
        });
        await settingsStore.refresh();
        expect(settingsStore.settings()?.has_api_key).toBe(true);

        mocks.putSettings.mockResolvedValue({
            has_api_key: false,
            base_url: "https://x",
            model: "m",
        });
        await settingsStore.save({ clear_api_key: true });

        expect(mocks.putSettings).toHaveBeenCalledWith({ clear_api_key: true });
        expect(settingsStore.settings()?.has_api_key).toBe(false);
        expect(settingsStore.settings()?.base_url).toBe("https://x");
    });

    it("save 普通字段：响应合并进既有 settings（局部更新不丢字段）", async () => {
        mocks.getSettings.mockResolvedValue({
            has_api_key: true,
            base_url: "https://x",
            model: "m",
            target_lang: "zh-CN",
        });
        await settingsStore.refresh();

        mocks.putSettings.mockResolvedValue({
            has_api_key: true,
            base_url: "https://x",
            model: "m2",
            target_lang: "zh-CN",
        });
        await settingsStore.save({ model: "m2" });

        expect(settingsStore.settings()?.model).toBe("m2");
        expect(settingsStore.settings()?.target_lang).toBe("zh-CN");
    });
});
