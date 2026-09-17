// DomPane —— arxiv_html 链阅读窗格。
// 与 HtmlPane 同 PaneLike 契约：
//   pages() = [data-chunk] 元素 offsetTop/height —— 页面几何即 chunk 序，
//   seq 双侧 1:1（worker emit 在两侧 DOM 注入同一 data-chunk 标记），
//   SyncEngine/drift/position 持久化全部原样复用。
//
// 与 HtmlPane 的差异：渲染源是序列化 DOM 产物而非 dual.json chunks——
//   - 无 marked/KaTeX：MathML 浏览器原生渲染（arXiv 服务端 LaTeXML 产物直出）
//   - fetch 产物 → DOMPurify dom profile → innerHTML
//   - 服务端 emit 已 _sanitize_dom + absolutize，这里是第二道防线：
//     sanitize + 兜底把漏网的相对 URL 补到 arxiv.org origin

import { createEffect, onCleanup, onMount, untrack } from "solid-js";

import type { DocId, Pos } from "./alignment";
import { sanitizeDomHtml } from "./sanitize";
import {
    bindChunkGeom,
    capturePos,
    jumpTo,
    scrollTopFor,
    type PageGeom,
    type PaneLike,
} from "./sync";
import { t } from "../i18n/zh";

export interface DomPaneHandle extends PaneLike {
    gotoPage?(n: number): void;
    capture(): Pos;
    jump(pos: Pos): void;
    scrollTopFor(pos: Pos): number | null;
}

interface Props {
    side: DocId;
    /** /api/files/{taskId}/{en|zh}.html（带 ?version=sha256 校验，docUrl 拼） */
    url: string;
    active?: boolean;
    onReady?(h: DomPaneHandle): void;
    onDispose?(h: DomPaneHandle): void;
    onActivate?(): void;
    onScroll?(): void;
}

/** 服务端 absolutize 的漏网兜底——相对路径一律归 arxiv.org origin。 */
const ARXIV_ORIGIN = "https://arxiv.org";

function fixupRelativeUrls(root: HTMLElement): void {
    for (const el of root.querySelectorAll<HTMLElement>("[src^='/'], [href^='/']")) {
        for (const attr of ["src", "href"] as const) {
            const v = el.getAttribute(attr);
            if (v?.startsWith("/")) el.setAttribute(attr, `${ARXIV_ORIGIN}${v}`);
        }
    }
}

export default function DomPane(props: Props) {
    let scrollEl!: HTMLDivElement;
    let bodyEl!: HTMLDivElement;
    const geom = bindChunkGeom(
        () => scrollEl,
        () => bodyEl,
    );

    const handle: DomPaneHandle = {
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

    let disposed = false;
    const ac = new AbortController();
    onMount(async () => {
        // 产物是完整 HTML 文档——只取 <body> 内文进 pane，头壳（arxiv
        // 的 nav/meta/link）丢弃。ltx_page 主容器及以下才是论文本体。
        try {
            const res = await fetch(props.url, { signal: ac.signal });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const raw = await res.text();
            const doc = new DOMParser().parseFromString(raw, "text/html");
            const page = doc.querySelector(".ltx_page_main") ?? doc.body;
            if (disposed) return;
            bodyEl.innerHTML = sanitizeDomHtml(page.innerHTML);
            fixupRelativeUrls(bodyEl);
            geom.rebind();
        } catch {
            if (disposed) return;
            // 拉取/解析失败降级空态文案——不炸整页（HtmlPane 单 chunk
            // 失败同款策略）
            bodyEl.innerHTML = `<p class="chunk-empty">${t.reader.chunkEmpty}</p>`;
            geom.rebind();
        }
        props.onReady?.(handle);
    });
    onCleanup(() => {
        disposed = true;
        ac.abort();
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
            class="pane pane-html pane-dom"
            tabindex="0"
            classList={{ active: !!props.active }}
            data-side={props.side}
            onPointerDown={() => props.onActivate?.()}
        >
            {/* pane-html-body 复用 HtmlPane 排版样式；ltx_* 类样式由 worker
                emit 时内联固化进产物 <style>，产物自足 */}
            <div ref={(el) => (bodyEl = el)} class="pane-html-body" />
        </div>
    );
}
