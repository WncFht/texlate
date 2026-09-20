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
//   - 拉取期 veil + 失败态重试钮（不再与真空态同文案）

import {
    createEffect,
    createSignal,
    onCleanup,
    onMount,
    Show,
    untrack,
} from "solid-js";

import type { DocId } from "./alignment";
import { sanitizeDomHtml } from "./sanitize";
import { externalLinksBlank } from "./paneUtils";
import {
    bindChunkGeom,
    makeChunkPaneHandle,
    raf,
    type ChunkPaneHandle,
} from "./sync";
import { errText } from "../api/client";
import { t } from "../i18n";

export type DomPaneHandle = ChunkPaneHandle;

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
/** 分片落地时间盒——与 HtmlPane 挂载同口径，片间让帧保对侧窗格可交互 */
const MOUNT_SLICE_MS = 40;

function fixupRelativeUrls(root: HTMLElement): void {
    for (const el of root.querySelectorAll<HTMLElement>(
        "[src^='/'], [href^='/']",
    )) {
        for (const attr of ["src", "href"] as const) {
            const v = el.getAttribute(attr);
            if (v?.startsWith("/"))
                el.setAttribute(attr, `${ARXIV_ORIGIN}${v}`);
        }
    }
}

export default function DomPane(props: Props) {
    let scrollEl!: HTMLDivElement;
    let bodyEl!: HTMLDivElement;
    const [phase, setPhase] = createSignal<"loading" | "ready" | "error">(
        "loading",
    );
    const [errMsg, setErrMsg] = createSignal("");
    const geom = bindChunkGeom(
        () => scrollEl,
        () => bodyEl,
    );

    const handle = makeChunkPaneHandle({
        side: untrack(() => props.side),
        scroller: () => scrollEl,
        body: () => bodyEl,
        geom,
    });

    let disposed = false;
    let ac: AbortController | null = null;

    const load = async () => {
        ac?.abort();
        const ctl = (ac = new AbortController());
        setPhase("loading");
        setErrMsg("");
        try {
            const res = await fetch(props.url, { signal: ctl.signal });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const raw = await res.text();
            // 产物是完整 HTML 文档——只取 <body> 内文进 pane，头壳（arxiv
            // 的 nav/meta/link）丢弃。ltx_page 主容器及以下才是论文本体。
            const doc = new DOMParser().parseFromString(raw, "text/html");
            const page = doc.querySelector(".ltx_page_main") ?? doc.body;
            if (disposed) return;
            const tmp = document.createElement("div");
            tmp.innerHTML = sanitizeDomHtml(page.innerHTML);
            // 修复管道在 detached tmp 上整跑一遍——querySelectorAll 不覆盖
            // 根自身，改到落地后逐片跑会漏顶层节点
            fixupRelativeUrls(tmp);
            externalLinksBlank(tmp);
            // 分片落地：1-3MB 产物一次 innerHTML 冻结主线程数百 ms——顶层
            // 节点按时间盒分批 append，首片落地撤 veil，余下后台续渲，
            // 全部落完才 rebind（锚集合此时才完整）
            const nodes = [...tmp.childNodes];
            bodyEl.replaceChildren();
            let i = 0;
            while (i < nodes.length && !disposed && !ctl.signal.aborted) {
                const deadline = performance.now() + MOUNT_SLICE_MS;
                do {
                    bodyEl.append(nodes[i++]);
                } while (i < nodes.length && performance.now() < deadline);
                setPhase("ready"); // 首片落地即撤 veil
                if (i < nodes.length) {
                    await new Promise<void>((r) => raf(() => r()));
                }
            }
            if (disposed || ctl.signal.aborted) return;
            geom.rebind();
            setPhase("ready");
        } catch (e) {
            // 重试先 abort 在途——旧请求的回包不再落盘
            if (
                disposed ||
                (e instanceof DOMException && e.name === "AbortError")
            )
                return;
            setErrMsg(errText(e));
            setPhase("error");
        }
    };

    onMount(async () => {
        await load();
        if (!disposed) props.onReady?.(handle);
    });
    onCleanup(() => {
        disposed = true;
        ac?.abort();
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
            <Show when={phase() === "loading"}>
                <div class="pane-veil">
                    <div
                        class="spinner"
                        role="status"
                        aria-label={t.pane.loading}
                    />
                </div>
            </Show>
            <Show when={phase() === "error"}>
                <div
                    class="pane-veil pane-error"
                    style={{ "flex-direction": "column", gap: "8px" }}
                >
                    <span>
                        {t.pane.loadFailed}
                        {errMsg()}
                    </span>
                    <button
                        type="button"
                        class="btn-ghost"
                        onClick={() => void load()}
                    >
                        {t.reader.retry}
                    </button>
                </div>
            </Show>
        </div>
    );
}
