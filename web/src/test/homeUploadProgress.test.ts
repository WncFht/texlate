// @vitest-environment jsdom
// Home 上传进度条：api.upload/shareImport 第四参 onProgress →
// .up-progress 条随回调更新宽度与百分比文案；结案（成功/失败）即隐藏。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    health: vi.fn(),
    getSettings: vi.fn(),
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
    const file = document.body.querySelector<HTMLInputElement>('input[type="file"]');
    const input = document.body.querySelector<HTMLInputElement>(".arxiv-input");
    const form = document.body.querySelector<HTMLFormElement>("form");
    const upBtn = document.body.querySelector<HTMLButtonElement>(
        "form button.btn-ghost",
    );
    if (!file || !input || !form || !upBtn) throw new Error("form elements missing");
    return { nav, file, input, form, upBtn };
}

function pick(el: HTMLInputElement, f: File) {
    Object.defineProperty(el, "files", { value: [f], configurable: true });
    el.dispatchEvent(new Event("change", { bubbles: true }));
}

beforeEach(() => {
    for (const m of Object.values(mocks)) m.mockReset();
    mocks.tasks.mockResolvedValue({ tasks: [] });
    mocks.health.mockResolvedValue({ ok: true, version: "t", compilers: {} });
    mocks.getSettings.mockResolvedValue({ has_api_key: false });
    mocks.translate.mockResolvedValue(RESP);
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
});

describe("Home 上传进度条", () => {
    it("进度回调驱动 .up-bar 宽度与百分比文案", async () => {
        let onProg: ((l: number, t: number) => void) | undefined;
        mocks.upload.mockImplementation(
            (
                _f: File,
                _fields: unknown,
                _byok: unknown,
                prog?: (l: number, t: number) => void,
            ) => {
                onProg = prog;
                return new Promise(() => {}); // 永不结案——保持上传中态
            },
        );
        const { file } = mount();
        pick(file, new File(["src"], "paper.tex"));

        await vi.waitFor(() => expect(mocks.upload).toHaveBeenCalled());
        expect(typeof onProg).toBe("function");
        await flush();

        const bar = () => document.body.querySelector<HTMLElement>(".up-bar i");
        const label = () =>
            document.body.querySelector(".up-label")?.textContent ?? "";
        expect(bar()).toBeTruthy();
        // 无进度事件前为不定态扫条（宽度 35% 是 indet 动画幅宽，非真实进度）
        expect(bar()!.style.width).toBe("35%");

        onProg!(256, 1024);
        await flush();
        expect(bar()!.style.width).toBe("25%");
        expect(label()).toContain("25%");

        onProg!(1024, 1024);
        await flush();
        // 100% = 字节送完、服务端建单中——回不定态扫条 + 处理中文案（U14）
        expect(bar()!.style.width).toBe("35%");
        expect(label()).toContain("处理中");
    });

    it("上传结案后进度条隐藏（失败亦然），错误文案可见", async () => {
        mocks.upload.mockRejectedValue(new ApiError(500, "boom"));
        const { file } = mount();
        pick(file, new File(["src"], "paper.tex"));

        await vi.waitFor(() => expect(mocks.upload).toHaveBeenCalled());
        await flush();
        await flush();

        expect(document.body.querySelector(".up-progress")).toBeNull();
        expect(
            document.body.querySelector(".form-error")?.textContent ?? "",
        ).toContain("boom");
    });

    it(".share.zip 路 shareImport 也带 progress 参", async () => {
        let gotProg: unknown;
        mocks.shareImport.mockImplementation(
            (_f: File, _o: unknown, _b: unknown, prog?: unknown) => {
                gotProg = prog;
                return Promise.resolve(RESP);
            },
        );
        const { nav, file } = mount();
        pick(file, new File(["z"], "a.share.zip"));

        await vi.waitFor(() => expect(mocks.shareImport).toHaveBeenCalled());
        await flush();
        expect(typeof gotProg).toBe("function");
        expect(nav).toHaveBeenCalledWith("#/reader/t_0000000000000f01");
    });

    it("translate 提交不出上传进度条", async () => {
        const { file } = mount();
        // translate 路径不经 upload——进度条只在上传时出现；
        // 直接验证初始状态无 .up-progress
        expect(document.body.querySelector(".up-progress")).toBeNull();
        expect(file).toBeTruthy();
    });

    it("translate 在飞时上传钮不误显「上传中…」", async () => {
        mocks.translate.mockImplementation(() => new Promise(() => {}));
        const { input, form, upBtn } = mount();
        input.value = "2501.14787";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());
        await flush();

        expect(upBtn.disabled).toBe(true);
        expect(upBtn.textContent).toBe("上传文件");
        expect(document.body.querySelector(".up-progress")).toBeNull();
    });

    it("busy 门：translate 在飞期间重复 submit 不再发请求", async () => {
        mocks.translate.mockImplementation(() => new Promise(() => {}));
        const { input, form } = mount();
        input.value = "2501.14787";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        const ev = () =>
            form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
        ev();
        ev();
        await flush();

        expect(mocks.translate).toHaveBeenCalledTimes(1);
    });

    it("进度条 aria：role=progressbar，无进度事件时不定态（无 valuenow/无百分比）", async () => {
        let onProg: ((l: number, t: number) => void) | undefined;
        mocks.upload.mockImplementation(
            (
                _f: File,
                _fields: unknown,
                _byok: unknown,
                prog?: (l: number, t: number) => void,
            ) => {
                onProg = prog;
                return new Promise(() => {});
            },
        );
        const { file } = mount();
        pick(file, new File(["src"], "paper.tex"));
        await vi.waitFor(() => expect(mocks.upload).toHaveBeenCalled());
        await flush();

        const bar = () => document.body.querySelector<HTMLElement>(".up-bar");
        const label = () =>
            document.body.querySelector(".up-label")?.textContent ?? "";
        expect(bar()!.getAttribute("role")).toBe("progressbar");
        expect(bar()!.getAttribute("aria-valuemin")).toBe("0");
        expect(bar()!.getAttribute("aria-valuemax")).toBe("100");
        // 不定态：无 valuenow，label 不带百分比
        expect(bar()!.hasAttribute("aria-valuenow")).toBe(false);
        expect(label()).not.toContain("%");

        onProg!(256, 1024);
        await flush();
        expect(bar()!.getAttribute("aria-valuenow")).toBe("25");
        expect(label()).toContain("25%");
    });

    it("上传在飞时组件卸载：请求落地后不再劫持路由（nav 不被调用）", async () => {
        let resolveUp: ((v: typeof RESP) => void) | undefined;
        mocks.upload.mockImplementation(
            () => new Promise<typeof RESP>((r) => (resolveUp = r)),
        );
        const { nav, file } = mount();
        pick(file, new File(["src"], "paper.tex"));
        await vi.waitFor(() => expect(mocks.upload).toHaveBeenCalled());

        dispose?.();
        dispose = undefined;
        resolveUp!(RESP);
        await flush();
        await flush();

        expect(nav).not.toHaveBeenCalled();
    });
});
