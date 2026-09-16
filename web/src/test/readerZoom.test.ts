// @vitest-environment jsdom
// Reader 缩放持久化落地回归：reading.zoom 恢复后必须应用到新挂载的
// PdfPane handle——usePDFSlick 初值恒 page-width，不落 handle 就只有
// Toolbar select 显示变了。PdfPane/HtmlPane 桩掉（pdfjs 不进 jsdom）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
    interface StubHandle {
        setScale: ReturnType<typeof vi.fn>;
        setScaleValue: ReturnType<typeof vi.fn>;
    }
    const paneHandles: Record<string, StubHandle> = {};
    // 桩组件：同步读 props 即够（solid/reactivity 把 props 读当响应式误报，
    // 桩无重挂语义）——onReady 走 microtask 模拟真实 pane 的异步上报
    const paneStub = (props: { side: string; onReady?(h: unknown): void }) => {
        // eslint-disable-next-line solid/reactivity -- 测试桩同步读 props，无需追踪
        const { side, onReady } = props;
        const h = {
            side,
            el: document.createElement("div"),
            slick: null,
            pages: () => [] as { page: number; top: number; height: number }[],
            numPages: () => 3,
            pageNumber: () => 1,
            gotoPage: vi.fn(),
            setScaleValue: vi.fn(),
            setScale: vi.fn(),
            capture: vi.fn(),
            jump: vi.fn(),
            scrollTopFor: () => null,
            openFind: vi.fn(),
        };
        paneHandles[side] = h;
        queueMicrotask(() => onReady?.(h));
        return h.el;
    };
    return {
        snapshot: vi.fn(),
        reader: vi.fn(),
        files: vi.fn(),
        putPosition: vi.fn(),
        paneHandles,
        paneStub,
    };
});

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: {
            ...mod.api,
            snapshot: mocks.snapshot,
            reader: mocks.reader,
            files: mocks.files,
            putPosition: mocks.putPosition,
        },
    };
});

vi.mock("../reader/PdfPane", () => ({ default: mocks.paneStub }));
vi.mock("../reader/HtmlPane", () => ({ default: mocks.paneStub }));

import { render } from "solid-js/web";
import Reader from "../pages/Reader";

let dispose: (() => void) | undefined;

const SNAP = {
    task_id: "t_zoom",
    kind: "arxiv",
    status: "done",
    progress: 100,
    created_at: 1_700_000_000,
    updated_at: 1_700_000_000,
};

const INFO = {
    view: "pdf",
    documents: {
        original: { version: "v-en", pages: 3, url: "/o.pdf" },
        translated: { version: "v-zh", pages: 3, url: "/z.pdf" },
    },
    reading: { mode: "split", zoom: "150%", sync: true },
};

beforeEach(() => {
    mocks.snapshot.mockReset().mockResolvedValue(SNAP);
    mocks.reader.mockReset().mockResolvedValue(INFO);
    mocks.files.mockReset().mockResolvedValue({ artifacts: {} });
    mocks.putPosition.mockReset().mockResolvedValue(undefined);
    for (const k of Object.keys(mocks.paneHandles)) delete mocks.paneHandles[k];
    // dual.json 拉取：本用例走 info.alignment，dual 缺席即 null
    vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }),
    );
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
    vi.unstubAllGlobals();
});

describe("Reader 缩放恢复落地", () => {
    it("reading.zoom=150% → 两侧窗格挂载即收 setScale(1.5)", async () => {
        dispose = render(
            () => Reader({ taskId: "t_zoom", nav: vi.fn() }),
            document.body,
        );

        await vi.waitFor(() => {
            expect(mocks.paneHandles.original?.setScale).toHaveBeenCalledWith(1.5);
            expect(mocks.paneHandles.translated?.setScale).toHaveBeenCalledWith(1.5);
        });
        // % 值走 setScale；setScaleValue 至多被初值 page-width 命中
        // （zoom 恢复前的挂载首帧），不带别的命名值
        for (const call of mocks.paneHandles.original!.setScaleValue.mock.calls) {
            expect(call[0]).toBe("page-width");
        }
    });

    it("命名缩放值 → setScaleValue 直传", async () => {
        mocks.reader.mockResolvedValue({
            ...INFO,
            reading: { mode: "split", zoom: "page-fit", sync: true },
        });
        dispose = render(
            () => Reader({ taskId: "t_zoom", nav: vi.fn() }),
            document.body,
        );

        await vi.waitFor(() => {
            expect(mocks.paneHandles.original?.setScaleValue).toHaveBeenCalledWith(
                "page-fit",
            );
        });
    });
});
