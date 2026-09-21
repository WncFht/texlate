// @vitest-environment jsdom
// Home 上传进度条：api.upload/shareImport 第四参 onProgress →
// .up-progress 条随回调更新宽度与百分比文案；结案（成功/失败）即隐藏。

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    health: vi.fn(),
    getSettings: vi.fn(),
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
import { t } from "../i18n";
import {
    flush,
    mountHome,
    pick,
    resetHomeMocks,
    RESP,
    unmountHome,
} from "./_homekit";

beforeEach(() => resetHomeMocks(mocks));

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
        const { file } = mountHome(Home);
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
        expect(label()).toContain(t.home.processing);
    });

    it("上传结案后进度条隐藏（失败亦然），错误文案可见", async () => {
        mocks.upload.mockRejectedValue(new ApiError(500, "boom"));
        const { file } = mountHome(Home);
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
        const { nav, file } = mountHome(Home);
        pick(file, new File(["z"], "a.share.zip"));

        await vi.waitFor(() => expect(mocks.shareImport).toHaveBeenCalled());
        await flush();
        expect(typeof gotProg).toBe("function");
        expect(nav).toHaveBeenCalledWith("#/reader/t_0000000000000f01");
    });

    it("translate 在飞时上传钮不误显「上传中…」", async () => {
        mocks.translate.mockImplementation(() => new Promise(() => {}));
        const { input, form, upBtn } = mountHome(Home);
        input.value = "2501.14787";
        input.dispatchEvent(new Event("input", { bubbles: true }));
        form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));

        await vi.waitFor(() => expect(mocks.translate).toHaveBeenCalled());
        await flush();

        expect(upBtn.disabled).toBe(true);
        expect(upBtn.textContent).toBe(t.home.upload);
        expect(document.body.querySelector(".up-progress")).toBeNull();
    });

    it("busy 门：translate 在飞期间重复 submit 不再发请求", async () => {
        mocks.translate.mockImplementation(() => new Promise(() => {}));
        const { input, form } = mountHome(Home);
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
        const { file } = mountHome(Home);
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
        const { nav, file } = mountHome(Home);
        pick(file, new File(["src"], "paper.tex"));
        await vi.waitFor(() => expect(mocks.upload).toHaveBeenCalled());

        unmountHome();
        resolveUp!(RESP);
        await flush();
        await flush();

        expect(nav).not.toHaveBeenCalled();
    });
});
