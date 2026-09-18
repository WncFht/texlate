// @vitest-environment jsdom
// Reader 分享块补角：sharePack.test.ts 已盖主路径，本文件补——
// 门：活动态/cancelled/needs_auth 无钮；错：share_pack_failed、映射外 code、
// 无 code、非 ApiError、409 无 code、空 detail；busy 态禁用；失败后重试点击。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    snapshot: vi.fn(),
    files: vi.fn(),
    reader: vi.fn(),
    sharePack: vi.fn(),
    cancel: vi.fn(),
    retry: vi.fn(),
    putPosition: vi.fn(),
    openTaskEvents: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: {
            ...mod.api,
            snapshot: mocks.snapshot,
            files: mocks.files,
            reader: mocks.reader,
            sharePack: mocks.sharePack,
            cancel: mocks.cancel,
            retry: mocks.retry,
            putPosition: mocks.putPosition,
        },
        openTaskEvents: mocks.openTaskEvents,
    };
});

vi.mock("../reader/PdfPane", () => ({
    default: () => {
        const el = document.createElement("div");
        el.className = "pdf-pane-stub";
        return el;
    },
}));
vi.mock("../reader/HtmlPane", () => ({
    default: () => {
        const el = document.createElement("div");
        el.className = "html-pane-stub";
        return el;
    },
}));

import { render } from "solid-js/web";
import {
    ApiError,
    type ReaderInfo,
    type SharePackResponse,
    type TaskSnapshot,
} from "../api/client";
import Reader from "../pages/Reader";
import { taskStore } from "../stores/tasks";
import { t } from "../i18n";

const TID = "t_share_edge";

const flush = () => new Promise((r) => setTimeout(r, 0));
const settle = async () => {
    for (let i = 0; i < 8; i++) await flush();
};

let dispose: (() => void) | undefined;

const snap = (over: Partial<TaskSnapshot> = {}): TaskSnapshot => ({
    task_id: TID,
    kind: "arxiv",
    status: "done",
    progress: 100,
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
    arxiv_id: "2501.14787",
    ...over,
});

const PDF_READER: ReaderInfo = {
    view: "pdf",
    documents: {
        original: { version: "v-en", pages: 3, url: `/api/files/${TID}/en.pdf` },
        translated: { version: "v-zh", pages: 4, url: `/api/files/${TID}/zh.pdf` },
    },
    reading: null,
};

function mount() {
    const nav = vi.fn();
    dispose = render(() => Reader({ taskId: TID, nav }), document.body);
    return { nav };
}

const q = <T extends Element>(sel: string) => document.body.querySelector<T>(sel);
const shareBtn = () => q<HTMLButtonElement>(".share-btn");
const clickShare = () =>
    shareBtn()?.dispatchEvent(new MouseEvent("click", { bubbles: true }));

beforeEach(() => {
    for (const m of Object.values(mocks)) m.mockReset();
    mocks.snapshot.mockResolvedValue(snap());
    mocks.files.mockResolvedValue({ artifacts: {} });
    mocks.reader.mockResolvedValue(PDF_READER);
    mocks.cancel.mockResolvedValue(undefined);
    mocks.putPosition.mockResolvedValue(undefined);
    mocks.openTaskEvents.mockReturnValue({ close: vi.fn(), closed: false });
    // dual.json 拉取：404 → dual=null（pdf 视图不受其影响）
    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.resolve(new Response("{}", { status: 404 }))),
    );
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    taskStore.unwatch(TID);
    document.body.innerHTML = "";
    vi.unstubAllGlobals();
});

describe("分享钮渲染门——补充状态组合", () => {
    it("translating（活动态）→ 进度视图，无任何分享钮", async () => {
        mocks.snapshot.mockResolvedValue(
            snap({ status: "translating", stage: "translating", progress: 40 }),
        );
        mount();
        await settle();
        expect(q(".task-progress")).not.toBeNull();
        expect(shareBtn()).toBeNull();
        expect(q(".share-banner")).toBeNull();
    });

    it("cancelled + pdf 视图 → 结果横幅挂 rp-actions 但无分享钮", async () => {
        mocks.snapshot.mockResolvedValue(snap({ status: "cancelled" }));
        mount();
        await settle();
        expect(q(".result-banner .rp-actions")).not.toBeNull();
        expect(shareBtn()).toBeNull();
    });

    it("needs_auth → auth 输入行在、分享钮缺席", async () => {
        mocks.snapshot.mockResolvedValue(snap({ status: "needs_auth" }));
        mount();
        await settle();
        expect(q(".auth-key-input")).not.toBeNull();
        expect(shareBtn()).toBeNull();
    });
});

describe("分享错误码映射——补充分支", () => {
    it("500 share_pack_failed → 「共享打包失败」+ 服务端 detail 括注", async () => {
        mocks.sharePack.mockRejectedValue(
            new ApiError(500, "磁盘已满", "share_pack_failed"),
        );
        mount();
        await settle();
        clickShare();
        await settle();
        const err = q(".share-err")?.textContent ?? "";
        expect(err).toContain("[share_pack_failed]");
        expect(err).toContain(t.reader.shareErrFailed);
        expect(err).toContain("磁盘已满");
    });

    it("映射外 code（internal）→ 回退原文 detail，不带映射文案", async () => {
        mocks.sharePack.mockRejectedValue(new ApiError(500, "db locked", "internal"));
        mount();
        await settle();
        clickShare();
        await settle();
        const err = q(".share-err")?.textContent ?? "";
        expect(err).toContain("[internal] db locked");
        expect(err).not.toContain(t.reader.shareErrFailed);
        expect(err).not.toContain(t.reader.shareErrRejected);
    });

    it("无 code 的 ApiError → 缺省 [share_pack] 前缀 + 原文 detail", async () => {
        mocks.sharePack.mockRejectedValue(new ApiError(502, "bad gateway"));
        mount();
        await settle();
        clickShare();
        await settle();
        expect(q(".share-err")?.textContent).toContain("[share_pack] bad gateway");
    });

    it("非 ApiError（网络型 TypeError）→ [share_pack] + e.message", async () => {
        mocks.sharePack.mockRejectedValue(new TypeError("network down"));
        mount();
        await settle();
        clickShare();
        await settle();
        expect(q(".share-err")?.textContent).toContain("[share_pack] network down");
    });

    it("409 无 code → 按状态码映射「任务未终态」", async () => {
        mocks.sharePack.mockRejectedValue(new ApiError(409, "仍在 translating"));
        mount();
        await settle();
        clickShare();
        await settle();
        const err = q(".share-err")?.textContent ?? "";
        expect(err).toContain(t.reader.shareErrState);
        expect(err).toContain("仍在 translating");
    });

    it("detail 为空串 → 只出映射文案、不加空括注", async () => {
        mocks.sharePack.mockRejectedValue(
            new ApiError(422, "", "share_pack_rejected"),
        );
        mount();
        await settle();
        clickShare();
        await settle();
        const err = q(".share-err")?.textContent ?? "";
        expect(err).toBe(`[share_pack_rejected] ${t.reader.shareErrRejected}`);
    });
});

describe("分享 busy 态与失败后重试", () => {
    it("打包未落地 → 钮禁用且文案切 shareBusy；落地后出成功态", async () => {
        let resolveShare: (v: SharePackResponse) => void = () => {};
        mocks.sharePack.mockReturnValue(
            new Promise<SharePackResponse>((r) => {
                resolveShare = r;
            }),
        );
        mount();
        await settle();
        clickShare();
        await settle();
        const btn = shareBtn();
        expect(btn?.disabled).toBe(true);
        expect(btn?.textContent).toContain(t.reader.shareBusy);
        resolveShare({ share_key: "s-busy-1", url: "s-busy-1.share.zip", bytes: 1 });
        await settle();
        expect(q(".share-ok")?.textContent).toContain("s-busy-1");
        expect(shareBtn()).toBeNull();
    });

    it("失败后钮留场可再点 → sharePack 再调一次；成功后错误清空", async () => {
        mocks.sharePack
            .mockRejectedValueOnce(new ApiError(500, "boom", "share_pack_failed"))
            .mockResolvedValue({ share_key: "s-retry-2", url: "u", bytes: 1 });
        mount();
        await settle();
        clickShare();
        await settle();
        expect(q(".share-err")).not.toBeNull();
        clickShare();
        await settle();
        expect(mocks.sharePack).toHaveBeenCalledTimes(2);
        expect(q(".share-ok")?.textContent).toContain("s-retry-2");
        expect(q(".share-err")).toBeNull();
    });
});
