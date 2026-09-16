// HtmlPane —— 降级视图（upload_pdf MinerU markdown / 编译失败但译文在库）。
// marked 渲染 + KaTeX auto-render；[data-chunk] 块当"页"用，chunk 对严格 1:1
// （seq 直映），同步复用 SyncEngine —— 比 PDF 锚更准（§5.4）。

import { createEffect, onCleanup, onMount, untrack } from "solid-js";
import { marked } from "marked";
import renderMathInElement from "katex/contrib/auto-render";
import "katex/dist/katex.min.css";

import type { DocId, Pos } from "./alignment";
import { sanitizeHtml } from "./sanitize";
import { capturePos, jumpTo, scrollTopFor, type PageGeom, type PaneLike } from "./sync";
import type { DualChunk } from "../api/client";

export interface HtmlPaneHandle extends PaneLike {
    gotoPage?(n: number): void;
    capture(): Pos;
    jump(pos: Pos): void;
    scrollTopFor(pos: Pos): number | null;
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

    const handle: HtmlPaneHandle = {
        side: untrack(() => props.side),
        get el() {
            return scrollEl;
        },
        pages(): PageGeom[] {
            return [...bodyEl.querySelectorAll<HTMLElement>("[data-chunk]")].map((el, i) => ({
                page: i + 1,
                top: el.offsetTop,
                height: el.offsetHeight,
            }));
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
    };

    onMount(() => {
        // marked.parse 输出为 string（无异步扩展）；译文是 LLM 生成物，内联
        // HTML 原样透传——注入前过 DOMPurify，再跑 KaTeX（产物不经 sanitize）。
        const html = props.chunks
            .map(
                (c) =>
                    `<section class="chunk" data-chunk="${c.seq}">` +
                    sanitizeHtml(
                        marked.parse(chunkText(c, props.side), { async: false }) as string,
                    ) +
                    `</section>`,
            )
            .join("");
        bodyEl.innerHTML = html || `<p class="chunk-empty">（无内容）</p>`;
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
        props.onReady?.(handle);
    });
    onCleanup(() => props.onDispose?.(handle));

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
            classList={{ active: !!props.active }}
            data-side={props.side}
            onPointerDown={() => props.onActivate?.()}
        >
            <div ref={(el) => (bodyEl = el)} class="pane-html-body" />
        </div>
    );
}
