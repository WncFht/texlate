// @vitest-environment jsdom
// Home 临时 API Key 补角：homeByok.test.ts 已盖 translate 路径，本文件补——
// upload/shareImport 两路 byok 第三参透传 + 成功即清；失败保留字段值（可重试）；
// 全程不发 PUT settings（per-request 不落盘）。

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    health: vi.fn(),
    getSettings: vi.fn(),
    putSettings: vi.fn(),
    providers: vi.fn(),
    translate: vi.fn(),
    upload: vi.fn(),
    shareImport: vi.fn(),
}));

// vi.mock 提升限制——工厂体内再引 _homekit（顶层 import 进不了 hoisted 作用域）
vi.mock("../api/client", async (importOriginal) =>
    (await import("./_homekit")).buildApiModule(
        await importOriginal<typeof import("../api/client")>(),
        mocks,
    ),
);

import { ApiError } from "../api/client";
import Home from "../pages/Home";
import { flush, FM_OPTS, mountHome, pick, resetHomeMocks, type } from "./_homekit";

beforeEach(() => resetHomeMocks(mocks));

describe("Home 临时 API Key——上传两路", () => {
    it(".tex + key → api.upload 第三参 {apiKey}；成功后清字段、跳 reader", async () => {
        const { nav, key, file } = mountHome(Home);
        type(key, "sk-up-1");
        const f = new File(["tex-src"], "paper.tex");
        pick(file, f);

        await vi.waitFor(() => expect(mocks.upload).toHaveBeenCalled());
        await flush();

        // front_matter 恒显式写（UI 态即意图）→ fields 恒在场；
        // 第四参是上传进度回调（XHR 路开关）
        expect(mocks.upload).toHaveBeenCalledWith(
            f,
            {
                model: undefined,
                target_lang: undefined,
                main: undefined,
                ...FM_OPTS,
            },
            { apiKey: "sk-up-1" },
            expect.any(Function),
        );
        expect(mocks.shareImport).not.toHaveBeenCalled();
        expect(key.value).toBe("");
        expect(nav).toHaveBeenCalledWith("#/reader/t_0000000000000f01");
    });

    it(".share.zip + key → api.shareImport 带 key；成功后清字段", async () => {
        const { nav, key, file } = mountHome(Home);
        type(key, "sk-sh-1");
        const f = new File(["zip-bytes"], "bundle.share.zip");
        pick(file, f);

        await vi.waitFor(() => expect(mocks.shareImport).toHaveBeenCalled());
        await flush();

        expect(mocks.shareImport).toHaveBeenCalledWith(
            f,
            FM_OPTS.options,
            { apiKey: "sk-sh-1" },
            expect.any(Function),
        );
        expect(mocks.upload).not.toHaveBeenCalled();
        expect(key.value).toBe("");
        expect(nav).toHaveBeenCalledWith("#/reader/t_0000000000000f01");
    });

    it("上传不填 key → byok 参 undefined", async () => {
        const { file } = mountHome(Home);
        const f = new File(["tex-src"], "paper.tex");
        pick(file, f);

        await vi.waitFor(() => expect(mocks.upload).toHaveBeenCalled());

        expect(mocks.upload).toHaveBeenCalledWith(
            f,
            {
                model: undefined,
                target_lang: undefined,
                main: undefined,
                ...FM_OPTS,
            },
            undefined,
            expect.any(Function),
        );
    });

    it("上传失败 → key 字段保留（仅成功即清），错误文案可见", async () => {
        mocks.upload.mockRejectedValue(new ApiError(500, "server exploded"));
        const { key, file } = mountHome(Home);
        type(key, "sk-keep");
        pick(file, new File(["tex-src"], "paper.tex"));

        await vi.waitFor(() => expect(mocks.upload).toHaveBeenCalled());
        await flush();

        expect(key.value).toBe("sk-keep");
        expect(
            document.body.querySelector(".form-error")?.textContent ?? "",
        ).toContain("server exploded");
    });

    it("translate 失败同样保留 key（同一份清空契约）", async () => {
        mocks.translate.mockRejectedValue(new ApiError(500, "boom"));
        const { input, key, form } = mountHome(Home);
        type(input, "2501.14787");
        type(key, "sk-keep-2");

        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());
        await flush();

        expect(key.value).toBe("sk-keep-2");
    });

    it("上传两路的临时 key 均不触碰 settings（putSettings 零调用）", async () => {
        const { key, file } = mountHome(Home);
        type(key, "sk-nosettings");
        pick(file, new File(["zip-bytes"], "a.share.zip"));

        await vi.waitFor(() => expect(mocks.shareImport).toHaveBeenCalled());
        await flush();

        expect(mocks.putSettings).not.toHaveBeenCalled();
    });
});
