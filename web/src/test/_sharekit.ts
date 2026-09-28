// _sharekit —— Reader「分享本译文」测试共享脚手架（sharePack/sharePackEdge
// 双生夹具归一；_* 前缀 = 测试内件，vite include 只收 *.test.ts）。
// jsdom 专属：顶层引 solid-js/web、helper 触 document——仅限带
// `// @vitest-environment jsdom` 头的文件 import（同 _taskdom 约束）。
// vi.mock 提升限制同 _taskkit：hoisted 工厂内经 `await import("./_sharekit")`
// 取用；本件不得静态 import 任何经 ../api/client 的应用模块（Reader 组件、
// taskStore 一律调用方注入）——否则在 api/client mock 工厂内成环、被测面
// 绑到真 api（store 侧 mock 全哑火，见 _taskkit 头注）。

import type { Component } from "solid-js";
import { render } from "solid-js/web";
import { afterEach, vi, type Mock } from "vitest";
import type { ReaderInfo, TaskSnapshot } from "../api/client";
import { snap } from "./fakes";
import { flush, mkChannel } from "./_taskkit";

/** 分享族 mock 面——各文件 vi.hoisted mocks 字面量须同形（键名即 api 成员名，
 *  openTaskEvents 是顶层导出，clientModuleMock 按键名分流） */
export interface ShareMocks {
    snapshot: Mock;
    files: Mock;
    reader: Mock;
    sharePack: Mock;
    cancel: Mock;
    retry: Mock;
    putPosition: Mock;
    openTaskEvents: Mock;
}

/** unwatch 能力面——调用方注入 taskStore（本件静态引会与 vi.mock 工厂成环） */
export interface Unwatcher {
    unwatch(taskId: string): void;
}

/**
 * PdfPane/HtmlPane 桩组件工厂（隔离 pdfjs/katex）：
 *   vi.mock("../reader/PdfPane", async () => ({
 *       default: (await import("./_sharekit")).mkPaneStub("pdf-pane-stub"),
 *   }));
 */
export const mkPaneStub = (className: string) => () => {
    const el = document.createElement("div");
    el.className = className;
    return el;
};

/** pdf 视图 ReaderInfo——双栏 3/4 页，文件 URL 按 tid 参数化 */
export const shareReaderInfo = (tid: string): ReaderInfo => ({
    view: "pdf",
    documents: {
        original: {
            version: "v-en",
            pages: 3,
            url: `/api/files/${tid}/en.pdf`,
        },
        translated: {
            version: "v-zh",
            pages: 4,
            url: `/api/files/${tid}/zh.pdf`,
        },
    },
    reading: null,
});

/** 分享族快照桩：fakes.snap 归一 status↔progress，补 arxiv_id（canShare 门要） */
export const shareSnap = (
    tid: string,
    over: Partial<TaskSnapshot> = {},
): TaskSnapshot => snap(tid, { arxiv_id: "2501.14787", ...over });

/** beforeEach 统一复位 + 默认回执；fetch 桩 404 → dual.json 缺席（pdf 视图不受影响） */
export function resetShareMocks(mocks: ShareMocks, tid: string) {
    for (const m of Object.values(mocks)) m.mockReset();
    mocks.snapshot.mockResolvedValue(shareSnap(tid));
    mocks.files.mockResolvedValue({ artifacts: {} });
    mocks.reader.mockResolvedValue(shareReaderInfo(tid));
    mocks.cancel.mockResolvedValue(undefined);
    mocks.putPosition.mockResolvedValue(undefined);
    mocks.openTaskEvents.mockReturnValue(mkChannel());
    // dual.json 拉取：404 → dual=null
    vi.stubGlobal(
        "fetch",
        vi.fn(() => Promise.resolve(new Response("{}", { status: 404 }))),
    );
}

// ---- DOM 打点 ----

export const q = <T extends Element>(sel: string) =>
    document.body.querySelector<T>(sel);
export const shareBtn = () => q<HTMLButtonElement>(".share-btn");
export const clickShare = () =>
    shareBtn()?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
// 分享块住工具栏弹层里——先点 .tb-share 开层，.share-btn 才在 DOM
export const openShare = () =>
    q<HTMLButtonElement>(".tb-share")?.dispatchEvent(
        new MouseEvent("click", { bubbles: true }),
    );

/** 8 拍宏任务——Reader 挂载/点击的 promise 链沉降 */
export const settle = async () => {
    for (let i = 0; i < 8; i++) await flush();
};

// ---- 挂载/卸载（dispose 集中管，同 _homekit mountHome/unmountHome 形） ----

let dispose: (() => void) | undefined;

/** 挂载 Reader 返 {nav}——组件由调用方注入（静态引会与 api/client mock 成环） */
export function mountReader(
    Reader: Component<{ taskId: string; nav(to: string): void }>,
    tid: string,
) {
    const nav = vi.fn();
    dispose = render(() => Reader({ taskId: tid, nav }), document.body);
    return { nav };
}

/** 中途卸载——幂等 */
export function unmountReader() {
    dispose?.();
    dispose = undefined;
}

/**
 * 文件顶层调用一次注册 afterEach：卸 Reader + 摘 watch + 清 DOM/global 桩。
 * store 注入 taskStore；文件级额外清理（如 navigator.clipboard 还原）另起
 * afterEach 叠加即可。
 */
export function trackShareTeardown(store: Unwatcher, tid: string) {
    afterEach(() => {
        unmountReader();
        store.unwatch(tid);
        document.body.innerHTML = "";
        vi.unstubAllGlobals();
    });
}
