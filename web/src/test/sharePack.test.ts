// @vitest-environment jsdom
// Reader 终态「分享本译文」：canShare 渲染门 + 成功态 + 按 code 映射的可读错误。
// PdfPane/HtmlPane 打桩隔离 pdfjs/katex；api 层打点走 vi.mock（同 homeByok.test）。

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
import { ApiError, type ReaderInfo, type TaskSnapshot } from "../api/client";
import Reader from "../pages/Reader";
import { taskStore } from "../stores/tasks";
import { t } from "../i18n";

const TID = "t_share";

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

describe("Reader「分享本译文」渲染门", () => {
    it("done + arxiv 源 + pdf 视图 → 分享横幅与按钮出现", async () => {
        mount();
        await settle();
        expect(q(".share-banner")).not.toBeNull();
        expect(shareBtn()?.textContent).toContain(t.reader.shareBtn);
    });

    it("partial + pdf 视图 → 分享钮在结果横幅的 rp-actions 内", async () => {
        mocks.snapshot.mockResolvedValue(snap({ status: "partial" }));
        mount();
        await settle();
        expect(q(".result-banner .rp-actions .share-btn")).not.toBeNull();
        // done 专属横幅不出（partial 的分享在结果横幅里）
        expect(q(".share-banner")).toBeNull();
    });

    it("done + reader 404（doc 类任务）→ 产物面板内出现分享钮", async () => {
        mocks.snapshot.mockResolvedValue(snap({ kind: "docx" }));
        mocks.reader.mockRejectedValue(new ApiError(404, "dual.json 未产出"));
        mount();
        await settle();
        expect(q(".result-panel .share-btn")).not.toBeNull();
    });

    it("kind=share → 无分享钮也无横幅（导入产物不自包）", async () => {
        mocks.snapshot.mockResolvedValue(snap({ kind: "share" }));
        mount();
        await settle();
        expect(shareBtn()).toBeNull();
        expect(q(".share-banner")).toBeNull();
    });

    it("无 arxiv_id → 无分享钮（不参与共享寻址）", async () => {
        mocks.snapshot.mockResolvedValue(snap({ arxiv_id: undefined }));
        mount();
        await settle();
        expect(shareBtn()).toBeNull();
        expect(q(".share-banner")).toBeNull();
    });

    it("fault + files 视图 → 结果面板无分享钮", async () => {
        mocks.snapshot.mockResolvedValue(snap({ status: "fault" }));
        mocks.reader.mockRejectedValue(new ApiError(404, "dual.json 未产出"));
        mount();
        await settle();
        expect(q(".result-panel")).not.toBeNull();
        expect(shareBtn()).toBeNull();
    });
});

describe("Reader「分享本译文」调用与结果态", () => {
    it("点击成功 → sharePack 调一次，展示 share_key 且按钮消失", async () => {
        mocks.sharePack.mockResolvedValue({
            share_key: "s-250114787-zh-ab12", // gitleaks:allow —— 测试 fixture 假 key
            url: "s-250114787-zh-ab12.share.zip",
            bytes: 20480,
        });
        mount();
        await settle();
        clickShare();
        // 成功前补点：busy 门拦截，仍只调一次
        clickShare();
        await settle();
        expect(mocks.sharePack).toHaveBeenCalledTimes(1);
        expect(mocks.sharePack).toHaveBeenCalledWith(TID);
        expect(q(".share-ok")?.textContent).toContain("s-250114787-zh-ab12");
        expect(shareBtn()).toBeNull();
    });

    it("409 invalid_state → 可读错误「任务未终态」", async () => {
        mocks.sharePack.mockRejectedValue(
            new ApiError(409, "任务状态 translating：仅 done/partial 终态可打包", "invalid_state"),
        );
        mount();
        await settle();
        clickShare();
        await settle();
        expect(q(".share-err")?.textContent).toContain(t.reader.shareErrState);
        expect(shareBtn()).not.toBeNull(); // 失败后可再试
    });

    it("422 share_pack_rejected → 「该任务不可共享」", async () => {
        mocks.sharePack.mockRejectedValue(
            new ApiError(422, "任务无 arxiv_id（不参与共享寻址）", "share_pack_rejected"),
        );
        mount();
        await settle();
        clickShare();
        await settle();
        expect(q(".share-err")?.textContent).toContain(t.reader.shareErrRejected);
    });

    it("422 share_pack_artifacts → 「产物未齐」并附服务端 detail", async () => {
        mocks.sharePack.mockRejectedValue(
            new ApiError(422, "缺必需产物: ['zh-src.zip']", "share_pack_artifacts"),
        );
        mount();
        await settle();
        clickShare();
        await settle();
        const err = q(".share-err")?.textContent ?? "";
        expect(err).toContain(t.reader.shareErrArtifacts);
        expect(err).toContain("zh-src.zip");
    });
});
