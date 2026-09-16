// PaneSidebar —— 窗格左侧窄 icon 栏 + 缩略图/大纲/附件三 tab（hjfy/pdf.js 侧栏对等件）。
// 每窗格独立一份：split 下两侧各自缩略图/大纲/附件，语义各自对本侧文档。
//
// 挂载约束（关键）：usePDFSlick 的构造 effect 以 `untrack(thumbs)` 一次性读走
// 缩略图容器——组件首渲染时元素必须已存在，否则 thumbnailViewer 永不创建。
// 因此 PDFSlickThumbnails 常驻挂载、用 CSS（.off → display:none）控可见性；
// 隐藏期 PDFThumbnailView 的 div 照常进 DOM，只是不渲染图；再次显示时
// 组件内 resize observer → forceRendering → 补渲可见缩略图。

import { createSignal, For, Show, untrack } from "solid-js";
import type {
    PDFSlick,
    PDFSlickState,
    PDFSlickThumbnails,
    TPDFDocumentOutline,
} from "@pdfslick/solid";
import { t } from "../i18n/zh";
import { fmtBytes, outlineColor } from "./paneUtils";

export type SideTab = "thumbs" | "outline" | "attach";

interface Props {
    slick(): PDFSlick | null;
    store: PDFSlickState;
    thumbsRef(el: HTMLElement): void;
    /** usePDFSlick 回传的 PDFSlickThumbnails 组件（绑定同一 store） */
    Thumbs: typeof PDFSlickThumbnails;
    onOpenFind(): void;
    onToggleInfo(): void;
}

/** 递归大纲节点：caret 折叠 + 标题点击跳 dest / 开外链 */
function OutlineItem(props: { item: TPDFDocumentOutline[number]; slick: PDFSlick | null }) {
    const item = untrack(() => props.item);
    const [open, setOpen] = createSignal(true);
    const kids = () => item.items ?? [];
    const clickable = () => !!(item.dest || item.url);

    const go = () => {
        if (item.url) {
            // item.url 是 pdfjs 已消毒的安全链接；unsafeUrl（可能是 javascript:）一律不碰
            window.open(item.url, "_blank", "noopener,noreferrer");
            return;
        }
        if (item.dest) {
            // dest 为命名串或显式数组；linkService 负责解析与跳转
            void props.slick?.linkService.goToDestination(item.dest).catch(() => undefined);
        }
    };

    return (
        <li>
            <div class="ol-row">
                <button
                    type="button"
                    class="ol-caret"
                    classList={{ off: !kids().length }}
                    aria-label={open() ? t.pane.collapse : t.pane.expand}
                    aria-expanded={kids().length ? open() : undefined}
                    disabled={!kids().length}
                    onClick={() => setOpen((v) => !v)}
                >
                    {kids().length ? (open() ? "▾" : "▸") : ""}
                </button>
                <button
                    type="button"
                    class="ol-item"
                    disabled={!clickable()}
                    style={{
                        "font-weight": item.bold ? "700" : undefined,
                        "font-style": item.italic ? "italic" : undefined,
                        color: outlineColor(item.color),
                    }}
                    onClick={go}
                >
                    {item.title || "—"}
                </button>
            </div>
            <Show when={kids().length && open()}>
                <ul class="ol-list">
                    <For each={kids()}>
                        {(child) => <OutlineItem item={child} slick={props.slick} />}
                    </For>
                </ul>
            </Show>
        </li>
    );
}

export default function PaneSidebar(props: Props) {
    const [tab, setTab] = createSignal<SideTab | null>(null);
    const toggle = (k: SideTab) => setTab((cur) => (cur === k ? null : k));

    const outline = () => props.store.documentOutline;
    const attachments = () => Array.from(props.store.attachments.values());

    const downloadAtt = (a: { filename: string; content: Uint8Array }) =>
        props.slick()?.openOrDownloadData(a.content, a.filename);

    const TABS: { key: SideTab; icon: string; label: string }[] = [
        { key: "thumbs", icon: "▦", label: t.pane.thumbs },
        { key: "outline", icon: "☰", label: t.pane.outline },
        { key: "attach", icon: "⧉", label: t.pane.attach },
    ];

    return (
        <>
            <nav class="pane-rail" aria-label={t.pane.rail}>
                <For each={TABS}>
                    {(b) => (
                        <button
                            type="button"
                            class="rail-btn"
                            classList={{ on: tab() === b.key }}
                            title={b.label}
                            aria-label={b.label}
                            aria-pressed={tab() === b.key}
                            onClick={() => toggle(b.key)}
                        >
                            {b.icon}
                        </button>
                    )}
                </For>
                <span class="rail-sep" aria-hidden="true" />
                <button
                    type="button"
                    class="rail-btn"
                    title={`${t.pane.find}（Ctrl+F）`}
                    aria-label={t.pane.find}
                    onClick={() => props.onOpenFind()}
                >
                    ⌕
                </button>
                <button
                    type="button"
                    class="rail-btn"
                    title={t.pane.info}
                    aria-label={t.pane.info}
                    onClick={() => props.onToggleInfo()}
                >
                    ⓘ
                </button>
            </nav>
            {/* aside 常驻 DOM（hidden 控显隐），保证 thumbs 容器在构造期已就位 */}
            <aside class="pane-side" hidden={!tab()}>
                <div class="side-fill side-thumbs" classList={{ off: tab() !== "thumbs" }}>
                    <props.Thumbs thumbsRef={props.thumbsRef} store={props.store}>
                        {(th) => (
                            <button
                                type="button"
                                class="thumb-btn"
                                classList={{ loaded: th.loaded }}
                                page-number={th.pageNumber}
                                onClick={() => props.slick()?.gotoPage(th.pageNumber)}
                            >
                                <Show
                                    when={th.src}
                                    fallback={
                                        <span
                                            class="thumb-ph"
                                            style={{
                                                width: `${th.width}px`,
                                                height: `${th.height}px`,
                                            }}
                                        />
                                    }
                                >
                                    {(src) => (
                                        <img
                                            src={src()}
                                            width={th.width}
                                            height={th.height}
                                            alt=""
                                        />
                                    )}
                                </Show>
                                <span class="thumb-num">{th.pageLabel ?? th.pageNumber}</span>
                            </button>
                        )}
                    </props.Thumbs>
                </div>
                <Show when={tab() === "outline"}>
                    <div class="side-fill side-body">
                        <Show
                            when={outline()?.length ? outline() : null}
                            keyed
                            fallback={<p class="side-empty muted">{t.pane.noOutline}</p>}
                        >
                            {(items) => (
                                <ul class="ol-list ol-root">
                                    <For each={items}>
                                        {(item) => (
                                            <OutlineItem item={item} slick={props.slick()} />
                                        )}
                                    </For>
                                </ul>
                            )}
                        </Show>
                    </div>
                </Show>
                <Show when={tab() === "attach"}>
                    <div class="side-fill side-body">
                        <Show
                            when={attachments().length ? attachments() : null}
                            keyed
                            fallback={<p class="side-empty muted">{t.pane.noAttach}</p>}
                        >
                            {(list) => (
                                <ul class="att-list">
                                    <For each={list}>
                                        {(a) => (
                                            <li>
                                                <button
                                                    type="button"
                                                    class="att-item"
                                                    title={a.filename}
                                                    onClick={() => downloadAtt(a)}
                                                >
                                                    <span class="att-name">{a.filename}</span>
                                                    <span class="att-size muted">
                                                        {fmtBytes(a.content.length)}
                                                    </span>
                                                </button>
                                            </li>
                                        )}
                                    </For>
                                </ul>
                            )}
                        </Show>
                    </div>
                </Show>
            </aside>
        </>
    );
}
