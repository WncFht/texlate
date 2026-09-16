// @vitest-environment jsdom
// Home 临时 API Key 补角：homeByok.test.ts 已盖 translate 路径，本文件补——
// upload/shareImport 两路 byok 第三参透传 + 成功即清；失败保留字段值（可重试）；
// 全程不发 PUT settings（per-request 不落盘）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
            upload: mocks.upload,
            shareImport: mocks.shareImport,
        },
    };
});

import { render } from "solid-js/web";
import { ApiError } from "../api/client";
import Home from "../pages/Home";

const RESP = {
    task_id: "t_0000000000000f01",
    status: "queued",
    events_url: "/api/task/t_0000000000000f01",
    reader_url: "/api/task/t_0000000000000f01/reader",
};

const flush = () => new Promise((r) => setTimeout(r, 0));

let dispose: (() => void) | undefined;

function mount() {
    const nav = vi.fn();
    dispose = render(() => Home({ nav }), document.body);
    const input = document.body.querySelector<HTMLInputElement>(".arxiv-input");
    const key = document.body.querySelector<HTMLInputElement>(
        '.task-opts input[type="password"]',
    );
    const form = document.body.querySelector<HTMLFormElement>("form");
    const file = document.body.querySelector<HTMLInputElement>('input[type="file"]');
    if (!input || !key || !form || !file) throw new Error("form elements missing");
    return { nav, input, key, form, file };
}

function type(el: HTMLInputElement, v: string) {
    el.value = v;
    el.dispatchEvent(new Event("input", { bubbles: true }));
}

/** 隐藏 file input 选文件（jsdom 无 DataTransfer 构造需求，直接灌 files） */
function pick(el: HTMLInputElement, f: File) {
    Object.defineProperty(el, "files", { value: [f], configurable: true });
    el.dispatchEvent(new Event("change", { bubbles: true }));
}

beforeEach(() => {
    for (const m of Object.values(mocks)) m.mockReset();
    mocks.tasks.mockResolvedValue({ tasks: [] });
    mocks.health.mockResolvedValue({ ok: true, version: "t", compilers: {} });
    mocks.getSettings.mockResolvedValue({ has_api_key: false });
    mocks.providers.mockResolvedValue({ providers: [] });
    mocks.translate.mockResolvedValue(RESP);
    mocks.upload.mockResolvedValue(RESP);
    mocks.shareImport.mockResolvedValue(RESP);
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
});

describe("Home 临时 API Key——上传两路", () => {
    it(".tex + key → api.upload 第三参 {apiKey}；成功后清字段、跳 reader", async () => {
        const { nav, key, file } = mount();
        type(key, "sk-up-1");
        const f = new File(["tex-src"], "paper.tex");
        pick(file, f);

        await vi.waitFor(() => expect(mocks.upload).toHaveBeenCalled());
        await flush();

        // 未开任务选项 → fields 参缺席
        expect(mocks.upload).toHaveBeenCalledWith(f, undefined, { apiKey: "sk-up-1" });
        expect(mocks.shareImport).not.toHaveBeenCalled();
        expect(key.value).toBe("");
        expect(nav).toHaveBeenCalledWith("#/reader/t_0000000000000f01");
    });

    it(".share.zip + key → api.shareImport 带 key；成功后清字段", async () => {
        const { nav, key, file } = mount();
        type(key, "sk-sh-1");
        const f = new File(["zip-bytes"], "bundle.share.zip");
        pick(file, f);

        await vi.waitFor(() => expect(mocks.shareImport).toHaveBeenCalled());
        await flush();

        expect(mocks.shareImport).toHaveBeenCalledWith(f, undefined, {
            apiKey: "sk-sh-1",
        });
        expect(mocks.upload).not.toHaveBeenCalled();
        expect(key.value).toBe("");
        expect(nav).toHaveBeenCalledWith("#/reader/t_0000000000000f01");
    });

    it("上传不填 key → byok 参 undefined", async () => {
        const { file } = mount();
        const f = new File(["tex-src"], "paper.tex");
        pick(file, f);

        await vi.waitFor(() => expect(mocks.upload).toHaveBeenCalled());

        expect(mocks.upload).toHaveBeenCalledWith(f, undefined, undefined);
    });

    it("上传失败 → key 字段保留（仅成功即清），错误文案可见", async () => {
        mocks.upload.mockRejectedValue(new ApiError(500, "server exploded"));
        const { key, file } = mount();
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
        const { input, key, form } = mount();
        type(input, "2501.14787");
        type(key, "sk-keep-2");

        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());
        await flush();

        expect(key.value).toBe("sk-keep-2");
    });

    it("上传两路的临时 key 均不触碰 settings（putSettings 零调用）", async () => {
        const { key, file } = mount();
        type(key, "sk-nosettings");
        pick(file, new File(["zip-bytes"], "a.share.zip"));

        await vi.waitFor(() => expect(mocks.shareImport).toHaveBeenCalled());
        await flush();

        expect(mocks.putSettings).not.toHaveBeenCalled();
    });
});
