// @vitest-environment jsdom
// Reader 终态「分享本译文」：canShare 渲染门 + 成功态 + 按 code 映射的可读错误。
// 夹具归一 _sharekit（同 sharePackEdge.test.ts）；navigator.clipboard 还原为文件级附加 afterEach。

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
    const { clientModuleMock } = await import("./_taskkit");
    return clientModuleMock(importOriginal, mocks);
});

vi.mock("../reader/PdfPane", async () => ({
    default: (await import("./_sharekit")).mkPaneStub("pdf-pane-stub"),
}));
vi.mock("../reader/HtmlPane", async () => ({
    default: (await import("./_sharekit")).mkPaneStub("html-pane-stub"),
}));

import { ApiError, type TaskSnapshot } from "../api/client";
import Reader from "../pages/Reader";
import { taskStore } from "../stores/tasks";
import { t } from "../i18n";
import {
    clickShare,
    mountReader,
    openShare,
    q,
    resetShareMocks,
    settle,
    shareBtn,
    shareSnap,
    trackShareTeardown,
} from "./_sharekit";

const TID = "t_share";

// navigator.clipboard 覆写还原点（own 描述符缺席 → delete 还原原型/缺席态）
const origClipboard = Object.getOwnPropertyDescriptor(navigator, "clipboard");

// 夹具全在 _sharekit——本文件只留 TID 绑定别名
const snap = (over: Partial<TaskSnapshot> = {}): TaskSnapshot =>
    shareSnap(TID, over);
const mount = () => mountReader(Reader, TID);

beforeEach(() => resetShareMocks(mocks, TID));
trackShareTeardown(taskStore, TID);

// vi.unstubAllGlobals 不撤 defineProperty 的 navigator.clipboard 桩——文件级附加清理
afterEach(() => {
    if (origClipboard)
        Object.defineProperty(navigator, "clipboard", origClipboard);
    else delete (navigator as { clipboard?: unknown }).clipboard;
});

describe("Reader「分享本译文」渲染门", () => {
    it("done + arxiv 源 + pdf 视图 → 工具栏分享钮，点开弹层出打包钮", async () => {
        mount();
        await settle();
        expect(q(".tb-share")).not.toBeNull();
        openShare();
        expect(q(".share-pop")).not.toBeNull();
        expect(shareBtn()?.textContent).toContain(t.reader.shareBtn);
    });

    it("partial + pdf 视图 → 分享钮在结果横幅的 rp-actions 内", async () => {
        mocks.snapshot.mockResolvedValue(snap({ status: "partial" }));
        mount();
        await settle();
        expect(q(".result-banner .rp-actions .share-btn")).not.toBeNull();
        // done 专属弹层不出（partial 的分享在结果横幅里）
        expect(q(".tb-share")).toBeNull();
        expect(q(".share-pop")).toBeNull();
    });

    it("done + reader 404（doc 类任务）→ 产物面板内出现分享钮", async () => {
        mocks.snapshot.mockResolvedValue(snap({ kind: "docx" }));
        mocks.reader.mockRejectedValue(new ApiError(404, "dual.json 未产出"));
        mount();
        await settle();
        expect(q(".result-panel .share-btn")).not.toBeNull();
    });

    it("kind=share → 无分享钮也无弹层（导入产物不自包）", async () => {
        mocks.snapshot.mockResolvedValue(snap({ kind: "share" }));
        mount();
        await settle();
        expect(shareBtn()).toBeNull();
        expect(q(".tb-share")).toBeNull();
    });

    it("kind=arxiv_html → 无分享钮也无弹层（HTML 源不参与共享寻址）", async () => {
        mocks.snapshot.mockResolvedValue(snap({ kind: "arxiv_html" }));
        mount();
        await settle();
        expect(shareBtn()).toBeNull();
        expect(q(".tb-share")).toBeNull();
    });

    it("无 arxiv_id → 无分享钮（不参与共享寻址）", async () => {
        mocks.snapshot.mockResolvedValue(snap({ arxiv_id: undefined }));
        mount();
        await settle();
        expect(shareBtn()).toBeNull();
        expect(q(".tb-share")).toBeNull();
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
        openShare();
        clickShare();
        // 成功前补点：busy 门拦截，仍只调一次
        clickShare();
        await settle();
        expect(mocks.sharePack).toHaveBeenCalledTimes(1);
        expect(mocks.sharePack).toHaveBeenCalledWith(TID);
        expect(q(".share-ok")?.textContent).toContain("s-250114787-zh-ab12");
        expect(shareBtn()).toBeNull();

        // .share-copy 两分支：clipboard 缺席 → 静默不装已复制；
        // 在席 → writeText(share_key) + 标签翻【已复制】
        const copyBtn = () => q<HTMLButtonElement>(".share-copy");
        copyBtn()?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        await settle();
        expect(copyBtn()?.textContent).toBe(t.reader.copy);

        const writeText = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, "clipboard", {
            value: { writeText },
            configurable: true,
        });
        copyBtn()?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        await settle();
        expect(writeText).toHaveBeenCalledWith("s-250114787-zh-ab12");
        expect(copyBtn()?.textContent).toBe(t.reader.copied);
    });

    it("409 invalid_state → 可读错误「任务未终态」", async () => {
        mocks.sharePack.mockRejectedValue(
            new ApiError(
                409,
                "任务状态 translating：仅 done/partial 终态可打包",
                "invalid_state",
            ),
        );
        mount();
        await settle();
        openShare();
        clickShare();
        await settle();
        expect(q(".share-err")?.textContent).toContain(t.reader.shareErrState);
        expect(shareBtn()).not.toBeNull(); // 失败后可再试
    });

    it("422 share_pack_rejected → 「该任务不可共享」", async () => {
        mocks.sharePack.mockRejectedValue(
            new ApiError(
                422,
                "任务无 arxiv_id（不参与共享寻址）",
                "share_pack_rejected",
            ),
        );
        mount();
        await settle();
        openShare();
        clickShare();
        await settle();
        expect(q(".share-err")?.textContent).toContain(
            t.reader.shareErrRejected,
        );
    });

    it("422 share_pack_artifacts → 「产物未齐」并附服务端 detail", async () => {
        mocks.sharePack.mockRejectedValue(
            new ApiError(
                422,
                "缺必需产物: ['zh-src.zip']",
                "share_pack_artifacts",
            ),
        );
        mount();
        await settle();
        openShare();
        clickShare();
        await settle();
        const err = q(".share-err")?.textContent ?? "";
        expect(err).toContain(t.reader.shareErrArtifacts);
        expect(err).toContain("zh-src.zip");
    });
});
