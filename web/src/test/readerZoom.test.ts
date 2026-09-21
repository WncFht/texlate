// @vitest-environment jsdom
// Reader 缩放持久化落地回归：reading.zoom 恢复后必须应用到新挂载的
// PdfPane handle——usePDFSlick 初值恒 page-width，不落 handle 就只有
// Toolbar select 显示变了。PdfPane/HtmlPane 桩掉（pdfjs 不进 jsdom）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
    interface StubHandle {
        setScale?: ReturnType<typeof vi.fn>;
        setScaleValue?: ReturnType<typeof vi.fn>;
        setFontSize?: ReturnType<typeof vi.fn>;
    }
    const paneHandles: Record<string, StubHandle> = {};
    // 桩组件：同步读 props 即够（solid/reactivity 把 props 读当响应式误报，
    // 桩无重挂语义）——onReady 走 microtask 模拟真实 pane 的异步上报。
    // 两桩分列缩放面：PdfPane 是 setScale/setScaleValue；HtmlPane 镜像
    // ChunkPaneHandle（setFontSize，无 setScaleValue）——applyZoomTo 按
    // setScaleValue 有无分派，混桩会让 html 缩放支路永远走 pdf 臂。
    const base = (side: string) => ({
        side,
        el: document.createElement("div"),
        pages: () => [] as { page: number; top: number; height: number }[],
        gotoPage: vi.fn(),
        capture: vi.fn(),
        jump: vi.fn(),
        scrollTopFor: () => null as number | null,
        openFind: vi.fn(),
    });
    const stub =
        (extra: Record<string, unknown>) =>
        (props: { side: string; onReady?(h: unknown): void }) => {
            // eslint-disable-next-line solid/reactivity -- 测试桩同步读 props，无需追踪
            const { side, onReady } = props;
            const h = { ...base(side), ...extra };
            paneHandles[side] = h as StubHandle;
            queueMicrotask(() => onReady?.(h));
            return h.el;
        };
    const pdfStub = stub({
        slick: null,
        numPages: () => 3,
        pageNumber: () => 1,
        setScaleValue: vi.fn(),
        setScale: vi.fn(),
    });
    const htmlStub = stub({ setFontSize: vi.fn() });
    return {
        snapshot: vi.fn(),
        reader: vi.fn(),
        files: vi.fn(),
        putPosition: vi.fn(),
        paneHandles,
        pdfStub,
        htmlStub,
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

vi.mock("../reader/PdfPane", () => ({ default: mocks.pdfStub }));
vi.mock("../reader/HtmlPane", () => ({ default: mocks.htmlStub }));

import { render } from "solid-js/web";
import Reader from "../pages/Reader";
import { zoomToFontPx } from "../reader/paneUtils";

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
        for (const call of mocks.paneHandles.original!.setScaleValue!.mock.calls) {
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

    it("view=html → 缩放走 setFontSize 档位（zoomToFontPx），不碰 setScaleValue", async () => {
        mocks.reader.mockResolvedValue({ ...INFO, view: "html" });
        // html 视图成立需 dual.chunks 非空（view.ts resolveReaderView）
        vi.stubGlobal(
            "fetch",
            vi.fn().mockResolvedValue({
                ok: true,
                json: async () => ({
                    version: 2,
                    documents: {},
                    chunks: [{ seq: 0, en: "a", zh: "甲" }],
                }),
            }),
        );
        dispose = render(
            () => Reader({ taskId: "t_zoom", nav: vi.fn() }),
            document.body,
        );

        await vi.waitFor(() => {
            const px = zoomToFontPx("150%");
            expect(
                mocks.paneHandles.original?.setFontSize,
            ).toHaveBeenCalledWith(px);
            expect(
                mocks.paneHandles.translated?.setFontSize,
            ).toHaveBeenCalledWith(px);
        });
        // html 臂：handle 无 setScaleValue —— 有即说明桩型/分派双双错位
        expect(mocks.paneHandles.original?.setScaleValue).toBeUndefined();
        expect(mocks.paneHandles.original?.setScale).toBeUndefined();
    });
});
