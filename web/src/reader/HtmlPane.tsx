// HtmlPane —— 降级视图（upload_pdf MinerU markdown / 编译失败但译文在库）。
// marked 渲染 + KaTeX auto-render；[data-chunk] 块当"页"用，chunk 对严格 1:1
// （seq 直映），同步复用 SyncEngine —— 比 PDF 锚更准（§5.4）。
//
// marked/katex（~300KB）只服务本视图——dynamic import 挪出 pdf/dom 常用路
// （P1）；css 同捆进本 chunk。拉取/解析期给 veil，不白屏。

import { createEffect, createSignal, onCleanup, onMount, Show, untrack } from "solid-js";

import type { DocId, Pos } from "./alignment";
import { escapeHtml, sanitizeHtml } from "./sanitize";
import { externalLinksBlank } from "./paneUtils";
import {
    bindChunkGeom,
    capturePos,
    jumpTo,
    scrollTopFor,
    type PageGeom,
    type PaneLike,
} from "./sync";
import type { DualChunk } from "../api/client";
import { t } from "../i18n/zh";

export interface HtmlPaneHandle extends PaneLike {
    gotoPage?(n: number): void;
    capture(): Pos;
    jump(pos: Pos): void;
    scrollTopFor(pos: Pos): number | null;
    /** html/dom 缩放落点：正文字号（px） */
    setFontSize?(px: number): void;
}

interface Props {
    side: DocId;
    chunks: DualChunk[];
    active?: boolean;
    onReady?(h: HtmlPaneHandle): void;
    onDispose?(h: HtmlPaneHandle): void;
    onActivate?(): void;
    onScroll?(): void;
}

function chunkText(c: DualChunk, side: DocId): string {
    return (side === "original" ? c.en : c.zh) ?? c.en ?? c.zh ?? "";
}

export default function HtmlPane(props: Props) {
    let scrollEl!: HTMLDivElement;
    let bodyEl!: HTMLDivElement;
    const [ready, setReady] = createSignal(false);
    const geom = bindChunkGeom(
        () => scrollEl,
        () => bodyEl,
    );

    const handle: HtmlPaneHandle = {
        side: untrack(() => props.side),
        get el() {
            return scrollEl;
        },
        pages(): PageGeom[] {
            return geom.pages();
        },
        capture() {
            return capturePos(this);
        },
        // 页码 = chunk 序：跳到第 n 段顶
        gotoPage(n) {
            jumpTo(this, { page: n, fraction: 0, viewport: 0 });
        },
        jump(pos) {
            jumpTo(this, pos);
        },
        scrollTopFor(pos) {
            return scrollTopFor(this, pos);
        },
        setFontSize(px) {
            bodyEl.style.fontSize = `${px}px`;
        },
    };

    let disposed = false;
    onMount(async () => {
        const [{ marked }, { default: renderMathInElement }] = await Promise.all([
            import("marked"),
            import("katex/contrib/auto-render"),
            import("katex/dist/katex.min.css"),
        ]);
        if (disposed) return;
        // marked.parse 输出为 string（无异步扩展）；译文是 LLM 生成物，内联
        // HTML 原样透传——注入前过 DOMPurify，再跑 KaTeX（产物不经 sanitize）。
        const html = props.chunks
            .map((c) => {
                const md = chunkText(c, props.side);
                // 单 chunk 解析失败降级为转义原文——不炸整页（坏数据面之一）
                let inner: string;
                try {
                    inner = sanitizeHtml(marked.parse(md, { async: false }) as string);
                } catch {
                    inner = `<p>${escapeHtml(md)}</p>`;
                }
                const seq = Number.isInteger(c.seq) ? c.seq : escapeHtml(String(c.seq));
                return `<section class="chunk" data-chunk="${seq}">${inner}</section>`;
            })
            .join("");
        bodyEl.innerHTML = html || `<p class="chunk-empty">${t.reader.chunkEmpty}</p>`;
        externalLinksBlank(bodyEl);
        try {
            renderMathInElement(bodyEl, {
                delimiters: [
                    { left: "$$", right: "$$", display: true },
                    { left: "\\[", right: "\\]", display: true },
                    { left: "\\(", right: "\\)", display: false },
                    { left: "$", right: "$", display: false },
                ],
                throwOnError: false, // 单公式失败原样显示源码，不炸整页
            });
        } catch {
            /* KaTeX 整体失败时保留纯文本 */
        }
        geom.rebind();
        setReady(true);
        props.onReady?.(handle);
    });
    onCleanup(() => {
        disposed = true;
        geom.dispose();
        props.onDispose?.(handle);
    });

    createEffect(() => {
        const el = scrollEl;
        const l = () => props.onScroll?.();
        el.addEventListener("scroll", l, { passive: true });
        onCleanup(() => el.removeEventListener("scroll", l));
    });

    return (
        <div
            ref={(el) => (scrollEl = el)}
            class="pane pane-html"
            tabindex="0"
            classList={{ active: !!props.active }}
            data-side={props.side}
            onPointerDown={() => props.onActivate?.()}
        >
            <div ref={(el) => (bodyEl = el)} class="pane-html-body" />
            <Show when={!ready()}>
                <div class="pane-veil">
                    <div class="spinner" role="status" aria-label={t.pane.loading} />
                </div>
            </Show>
        </div>
    );
}
