// PdfPane —— usePDFSlick 封装，向 SyncEngine 暴露 PaneLike 几何接口。
// 规格须知（§5.1）：usePDFSlick 不做实例清理，url 变化会叠第二个实例——
// 因此本组件由调用方按 doc.version 整体重挂（keyed），绝不原位换 url。
//
// 侧件布局：左 rail（缩略图/大纲/附件/查找/信息）+ 侧栏 + 主视区。
// thumbs 容器常驻 DOM 是硬约束——usePDFSlick 构造期 untrack 读 thumbs 元素，
// 晚挂载则 thumbnailViewer 永不创建（pdfslick#136，见 PaneSidebar 头注）。

import { createEffect, createSignal, onCleanup, Show, untrack } from "solid-js";
import { usePDFSlick } from "@pdfslick/solid";
import type { PDFSlick } from "@pdfslick/core";
import "@pdfslick/solid/dist/pdf_viewer.css";

import type { DocId, Pos } from "./alignment";
import { capturePos, jumpTo, scrollTopFor, type PageGeom, type PaneLike } from "./sync";
import { ensurePdfjsWorker } from "../pdfjs";
import PaneSidebar from "./PaneSidebar";
import FindBar from "./FindBar";
import DocInfo from "./DocInfo";

export interface PaneHandle extends PaneLike {
    readonly slick: PDFSlick | null;
    numPages(): number;
    pageNumber(): number;
    gotoPage(n: number): void;
    setScaleValue(v: string): void;
    setScale(v: number): void;
    capture(): Pos;
    jump(pos: Pos): void;
    scrollTopFor(pos: Pos): number | null;
    /** 打开本窗格查找条（Ctrl+F 由上层路由到活动窗格） */
    openFind(): void;
}

interface Props {
    url: string;
    side: DocId;
    /** 「下载带批注副本」文件名（Reader 按 taskId+side 拼好传入） */
    annotName?: string;
    active?: boolean;
    onReady?(h: PaneHandle): void;
    onDispose?(h: PaneHandle): void;
    onPageChange?(page: number, numPages: number): void;
    onActivate?(): void;
    onScroll?(): void;
}

interface PdfPageViewLike {
    div?: HTMLElement;
}

export default function PdfPane(props: Props) {
    ensurePdfjsWorker();
    const {
        pdfSlick,
        pdfSlickStore,
        viewerRef,
        thumbsRef,
        PDFSlickViewer,
        PDFSlickThumbnails,
        isDocumentLoaded,
        error,
    } =
        // url 刻意非追踪：组件按 doc.version keyed 重挂，绝不在位换 url（§5.1）
        usePDFSlick(untrack(() => props.url), {
            scaleValue: "page-width",
            getDocumentParams: {
                cMapUrl: "/pdfjs/cmaps/",
                cMapPacked: true,
                standardFontDataUrl: "/pdfjs/standard_fonts/",
                wasmUrl: "/pdfjs/wasm/",
            },
        });

    const viewer = () => pdfSlick()?.viewer;

    const [findOpen, setFindOpen] = createSignal(false);
    const [infoOpen, setInfoOpen] = createSignal(false);
    let findInput: HTMLInputElement | undefined;

    const openFind = () => {
        setFindOpen(true);
        props.onActivate?.();
        queueMicrotask(() => findInput?.focus());
    };

    const handle: PaneHandle = {
        side: untrack(() => props.side),
        get el() {
            const v = viewer();
            if (!v) throw new Error("PdfPane: viewer not mounted");
            return v.container;
        },
        get slick() {
            return pdfSlick();
        },
        pages(): PageGeom[] {
            const views = (viewer() as unknown as { _pages?: PdfPageViewLike[] })?._pages ?? [];
            const out: PageGeom[] = [];
            views.forEach((v, i) => {
                if (v?.div) out.push({ page: i + 1, top: v.div.offsetTop, height: v.div.offsetHeight });
            });
            return out;
        },
        numPages: () => pdfSlickStore.numPages ?? 0,
        pageNumber: () => pdfSlickStore.pageNumber ?? 1,
        gotoPage: (n) => pdfSlick()?.gotoPage(n),
        setScaleValue: (v) => {
            const s = pdfSlick();
            if (s) s.currentScaleValue = v;
        },
        setScale: (v) => {
            const s = pdfSlick();
            if (s) s.currentScale = v;
        },
        capture() {
            return capturePos(this);
        },
        jump(pos) {
            jumpTo(this, pos);
        },
        scrollTopFor(pos) {
            return scrollTopFor(this, pos);
        },
        openFind,
    };

    // 文档加载完成 → 等 pages 就位（_pages[].div 齐全）后上报 handle
    let readyNotified = false;
    let rafId = 0;
    createEffect(() => {
        if (!isDocumentLoaded() || readyNotified) return;
        const waitPages = () => {
            const s = pdfSlick();
            const views = (s?.viewer as unknown as { _pages?: PdfPageViewLike[] })?._pages;
            if (s && views?.length && views.every((v) => v?.div)) {
                readyNotified = true;
                props.onReady?.(handle);
                return;
            }
            rafId = requestAnimationFrame(waitPages);
        };
        waitPages();
    });
    onCleanup(() => cancelAnimationFrame(rafId));
    onCleanup(() => props.onDispose?.(handle));

    // 页码上报（pdfjs pagechanging → store.pageNumber）
    createEffect(() => {
        const n = pdfSlickStore.pageNumber;
        if (typeof n === "number") props.onPageChange?.(n, pdfSlickStore.numPages ?? 0);
    });

    // 用户滚动 → 上层做位置持久化/漂移检测（同步引擎自己在容器上挂监听）
    createEffect(() => {
        const s = pdfSlick();
        if (!s) return;
        const el = s.viewer.container;
        const l = () => props.onScroll?.();
        el.addEventListener("scroll", l, { passive: true });
        onCleanup(() => el.removeEventListener("scroll", l));
    });

    return (
        <div
            class="pane pane-pdf"
            classList={{ active: !!props.active }}
            data-side={props.side}
            onPointerDown={() => props.onActivate?.()}
        >
            <PaneSidebar
                slick={pdfSlick}
                store={pdfSlickStore}
                thumbsRef={thumbsRef}
                Thumbs={PDFSlickThumbnails}
                onOpenFind={openFind}
                onToggleInfo={() => setInfoOpen((v) => !v)}
                annotName={props.annotName}
            />
            <div class="pane-body">
                <PDFSlickViewer viewerRef={viewerRef} store={pdfSlickStore} />
                <FindBar
                    slick={pdfSlick}
                    open={findOpen()}
                    inputRef={(el) => (findInput = el)}
                    onClose={() => setFindOpen(false)}
                />
                <Show when={infoOpen()}>
                    <DocInfo store={pdfSlickStore} onClose={() => setInfoOpen(false)} />
                </Show>
                <Show when={!isDocumentLoaded() && !error()}>
                    <div class="pane-veil">
                        <div class="spinner" aria-label="加载 PDF" />
                    </div>
                </Show>
                <Show when={error()}>
                    {(e) => <div class="pane-veil pane-error">PDF 加载失败：{String(e())}</div>}
                </Show>
            </div>
        </div>
    );
}
