// pdfTheme —— Blender 与 app 主题的接线层。
//
// 主题模型(Zotero 同构):PdfPageTheme = {background, foreground,
// invertImages?};亮暗两个独立槽位——dark 槽挂 {--paper,--ink} 深色对,
// light 槽为 null(原样透传,白底论文即本色)。日后加 sepia 只扩槽位表。
//
// 免 fork 接入:不 patch 原型(PDFPageProxy 未导出、getContext 全局补丁
// 会把 pdf.js 内部 scratch canvas 也套住),而是按 pdfPage 实例拦
// render()——viewer._pages[].pdfPage 与缩略图共享同一 PDFPageProxy
// (document.getPage 缓存),一处补丁同时覆盖主页渲染与缩略图。
// 主题切换路径:setTheme 换色板 + pageView.reset() + viewer.update()
// 原位重渲,与 Zotero 的 page.reset()/pdfViewer.update() 同构。

import { createSignal, untrack } from "solid-js";
import type { PDFSlick } from "@pdfslick/core";
import { Blender, type PdfPageTheme } from "./blender";

// data-theme 是全站唯一权威态(index.html 预置 + settings.applyTheme 落,
// auto 档系统翻转也走这里)——MutationObserver 让两条更新路径并成一条信号
const [resolvedTheme, setResolvedTheme] = createSignal<string>(
    typeof document !== "undefined"
        ? document.documentElement.dataset.theme || "light"
        : "light",
);
if (typeof MutationObserver !== "undefined") {
    new MutationObserver(() =>
        setResolvedTheme(document.documentElement.dataset.theme || "light"),
    ).observe(document.documentElement, {
        attributes: true,
        attributeFilter: ["data-theme"],
    });
}
export { resolvedTheme };

// 色板从 CSS token 现取——palette 调参时 PDF 侧自动跟随,不另存副本
export function currentPdfTheme(): PdfPageTheme | null {
    if (resolvedTheme() !== "dark") return null;
    const cs = getComputedStyle(document.documentElement);
    const background = cs.getPropertyValue("--paper").trim();
    const foreground = cs.getPropertyValue("--ink").trim();
    if (!background || !foreground) return null;
    return { background, foreground };
}

const blenders = new WeakMap<CanvasRenderingContext2D, Blender>();
const PATCHED = Symbol("texlate-render-patched");

interface PdfPageLike {
    render(params: {
        canvasContext?: CanvasRenderingContext2D;
        viewport?: { width: number; height: number };
    }): unknown;
    [PATCHED]?: boolean;
}

// 实例级补丁:拦 pdfPage.render,把 canvasContext 套进 Blender。
// 每次渲染都按当前主题重建/换色——zoom、虚拟化滚动重渲自动吃到最新主题。
export function patchPdfPage(pg: PdfPageLike) {
    if (pg[PATCHED]) return;
    pg[PATCHED] = true;
    const orig = pg.render.bind(pg);
    pg.render = (params) => {
        // pdf.js 命令式调用,非 tracked scope——untrack 显式取当下主题
        const theme = untrack(currentPdfTheme);
        const ctx = params?.canvasContext;
        if (
            theme &&
            ctx &&
            !(ctx as CanvasRenderingContext2D & { skipBlender?: boolean })
                .skipBlender
        ) {
            let b = blenders.get(ctx);
            if (!b) {
                b = new Blender(ctx, theme);
                blenders.set(ctx, b);
            } else {
                b.setTheme(theme);
            }
            const vp = params.viewport;
            b.pageWidth = vp?.width ?? ctx.canvas.width;
            b.pageHeight = vp?.height ?? ctx.canvas.height;
        }
        return orig(params);
    };
}

interface PageViewLike {
    pdfPage?: PdfPageLike;
    reset(opts?: Record<string, boolean>): void;
}
interface ThumbViewLike {
    pdfPage?: PdfPageLike;
    reset(): void;
}
interface ViewerLike {
    _pages?: PageViewLike[];
    update(): void;
}
interface ThumbViewerLike {
    _thumbnails?: ThumbViewLike[];
    forceRendering(): boolean;
}

// 主题切换:全页 reset(INITIAL) + viewer.update() 重渲可见页;
// 缩略图 reset 保留旧图(pdfslick 的 reset 不清 img)直到新渲覆盖,
// forceRendering 逐次排队——每调一次只取一个最高优先级
export function applyPdfTheme(slick: PDFSlick | null | undefined) {
    const viewer = slick?.viewer as unknown as ViewerLike | undefined;
    if (!viewer?._pages) return;
    for (const pv of viewer._pages) {
        if (pv?.pdfPage) patchPdfPage(pv.pdfPage);
        pv?.reset?.({ keepTextLayer: true });
    }
    const tv = slick?.thumbnailViewer as unknown as ThumbViewerLike | undefined;
    for (const t of tv?._thumbnails ?? []) {
        if (t?.pdfPage) patchPdfPage(t.pdfPage);
        t?.reset?.();
    }
    viewer.update();
    if (tv) while (tv.forceRendering()) {
        /* 逐次排队可见缩略图,直到没有可渲的 */
    }
}
