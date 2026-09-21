// @vitest-environment jsdom
// Home 表单临时 API Key：填了 → translate 第三参 byok 透传 + 提交成功即清；
// 空/纯空白 → 不带 byok（per-request 语义，不落 settings store）。

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    health: vi.fn(),
    getSettings: vi.fn(),
    putSettings: vi.fn(),
    providers: vi.fn(),
    translate: vi.fn(),
}));

// vi.mock 提升限制——工厂体内再引 _homekit（顶层 import 进不了 hoisted 作用域）
// buildApiModule 的 HOME_API_DEFAULTS 兜底 upload/shareImport/discoverSearch
// 等未声明成员——此前 ...mod.api 穿透会打真 fetch
vi.mock("../api/client", async (importOriginal) =>
    (await import("./_homekit")).buildApiModule(
        await importOriginal<typeof import("../api/client")>(),
        mocks,
    ),
);

import Home from "../pages/Home";
import {
    flush,
    FM_OPTS,
    mountHome,
    resetHomeMocks,
    type,
} from "./_homekit";

beforeEach(() => resetHomeMocks(mocks));

describe("Home 临时 API Key（per-request BYOK）", () => {
    it("填 key 提交 → translate 带 {apiKey}，成功后清空输入", async () => {
        const { nav, input, key, form } = mountHome(Home);
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
        const { input, form } = mountHome(Home);
        type(input, "2501.14787");

        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());

        expect(mocks.translate).toHaveBeenCalledWith("2501.14787", FM_OPTS, undefined);
    });

    it("纯空白 key 视同未填 → 不透传", async () => {
        const { input, key, form } = mountHome(Home);
        type(input, "2501.14787");
        type(key, "   ");

        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());

        expect(mocks.translate).toHaveBeenCalledWith("2501.14787", FM_OPTS, undefined);
    });

    it("临时 key 不触碰 settings store（纯 per-request，不发 PUT）", async () => {
        const { input, key, form } = mountHome(Home);
        type(input, "2501.14787");
        type(key, "sk-temp-2");

        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());
        await flush();

        expect(mocks.putSettings).not.toHaveBeenCalled();
    });
});
