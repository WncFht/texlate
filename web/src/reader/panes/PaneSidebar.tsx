// PaneSidebar —— 窗格左侧窄 icon 栏 + 缩略图/大纲/附件三 tab（hjfy/pdf.js 侧栏对等件）。
// 每窗格独立一份：split 下两侧各自缩略图/大纲/附件，语义各自对本侧文档。
//
// 挂载约束（关键）：usePDFSlick 的构造 effect 以 `untrack(thumbs)` 一次性读走
// 缩略图容器——组件首渲染时元素必须已存在，否则 thumbnailViewer 永不创建。
// 因此 PDFSlickThumbnails 常驻挂载、用 CSS（.off → display:none）控可见性；
// 隐藏期 PDFThumbnailView 的 div 照常进 DOM，只是不渲染图；再次显示时
// 组件内 resize observer → forceRendering → 补渲可见缩略图。

import {
    createEffect,
    createSignal,
    For,
    type JSX,
    onCleanup,
    Show,
    untrack,
} from "solid-js";
import { AnnotationEditorType } from "pdfjs-dist";
import type {
    PDFSlick,
    PDFSlickState,
    PDFSlickThumbnails,
    TPDFDocumentOutline,
} from "@pdfslick/solid";
import { t } from "../../i18n";
import { fmtBytes } from "../../taskFiles";
import { outlineColor } from "../logic/paneUtils";

export type SideTab = "thumbs" | "outline" | "attach";

interface Props {
    slick(): PDFSlick | null;
    store: PDFSlickState;
    thumbsRef(el: HTMLElement): void;
    /** usePDFSlick 回传的 PDFSlickThumbnails 组件（绑定同一 store） */
    Thumbs: typeof PDFSlickThumbnails;
    onOpenFind(): void;
    /** 暴露 rail ⌕ 钮给宿主——findbar 关闭时焦点回触发源 */
    findBtnRef?(el: HTMLButtonElement): void;
    onToggleInfo(): void;
    /** 「下载带批注副本」文件名（缺省按 store.filename 派生） */
    annotName?: string;
}

/** 递归大纲节点：caret 折叠 + 标题点击跳 dest / 开外链 */
function OutlineItem(props: {
    item: TPDFDocumentOutline[number];
    slick: PDFSlick | null;
}) {
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
            void props.slick?.linkService
                .goToDestination(item.dest)
                .catch(() => undefined);
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
                        {(child) => (
                            <OutlineItem item={child} slick={props.slick} />
                        )}
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

    // 高亮批注开关：store.annotationEditorMode 由 setAnnotationEditorMode 回写，可直接读
    const annotOn = () =>
        props.store.annotationEditorMode === AnnotationEditorType.HIGHLIGHT;
    const toggleAnnot = () =>
        props
            .slick()
            ?.setAnnotationEditorMode(
                annotOn()
                    ? AnnotationEditorType.NONE
                    : AnnotationEditorType.HIGHLIGHT,
            );

    const [hasAnnot, setHasAnnot] = createSignal(false);
    const [saving, setSaving] = createSignal(false);

    // annotationStorage 不进 store 响应式面——挂 pdf.js 自带的 onAnnotationEditor
    // 钩子（viewer/pdfslick 均未占用）：有 editor 批注时回传类型串，最后一个被删时回 null
    createEffect(() => {
        const s = props.slick();
        // pdf.js 类型把该钩子字段声明为 null，实为可赋值 callback——收窄成本地形状
        const storage = props.store.numPages
            ? (s?.document?.annotationStorage as unknown as
                  | {
                        onAnnotationEditor:
                            ((type: string | null) => void) | null;
                    }
                  | undefined)
            : undefined;
        if (!storage) return;
        const cb = (type: string | null) => setHasAnnot(type !== null);
        storage.onAnnotationEditor = cb;
        onCleanup(() => {
            if (storage.onAnnotationEditor === cb)
                storage.onAnnotationEditor = null;
        });
    });

    const annotFile = () => {
        if (props.annotName) return props.annotName;
        const base = (props.store.filename ?? "document").replace(
            /\.pdf$/i,
            "",
        );
        return `${base}-annotated.pdf`;
    };

    const saveAnnot = async () => {
        const s = props.slick();
        const dm = s?.downloadManager;
        if (!s?.document || !dm || !hasAnnot() || saving()) return;
        setSaving(true);
        try {
            const data = (await s.document.saveDocument()).slice(0);
            dm.downloadData(data, annotFile(), "application/pdf");
        } finally {
            setSaving(false);
        }
    };

    // rail 图标用 inline SVG——⧉⌕ 等冷僻 unicode 在缺字形字体下出 tofu。
    // feather 风格：24 网格 stroke=currentColor，尺寸内联不需要 CSS 配合。
    const RI = (props: { children: JSX.Element }) => (
        <svg
            viewBox="0 0 24 24"
            width="15"
            height="15"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
            aria-hidden="true"
        >
            {props.children}
        </svg>
    );

    const TABS: { key: SideTab; icon: JSX.Element; label: string }[] = [
        {
            key: "thumbs",
            icon: (
                <RI>
                    <rect x="3" y="3" width="7" height="7" rx="1" />
                    <rect x="14" y="3" width="7" height="7" rx="1" />
                    <rect x="14" y="14" width="7" height="7" rx="1" />
                    <rect x="3" y="14" width="7" height="7" rx="1" />
                </RI>
            ),
            label: t.pane.thumbs,
        },
        {
            key: "outline",
            icon: (
                <RI>
                    <line x1="8" y1="6" x2="21" y2="6" />
                    <line x1="8" y1="12" x2="21" y2="12" />
                    <line x1="8" y1="18" x2="21" y2="18" />
                    <line x1="3" y1="6" x2="3.01" y2="6" />
                    <line x1="3" y1="12" x2="3.01" y2="12" />
                    <line x1="3" y1="18" x2="3.01" y2="18" />
                </RI>
            ),
            label: t.pane.outline,
        },
        {
            key: "attach",
            icon: (
                <RI>
                    <path d="m21.44 11.05-9.19 9.19a6 6 0 0 1-8.49-8.49l8.57-8.57A4 4 0 1 1 18 8.84l-8.59 8.57a2 2 0 0 1-2.83-2.83l8.49-8.48" />
                </RI>
            ),
            label: t.pane.attach,
        },
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
                    ref={(el) => props.findBtnRef?.(el)}
                    title={`${t.pane.find}（Ctrl+F）`}
                    aria-label={t.pane.find}
                    onClick={() => props.onOpenFind()}
                >
                    <RI>
                        <circle cx="11" cy="11" r="8" />
                        <line x1="21" y1="21" x2="16.65" y2="16.65" />
                    </RI>
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
                <button
                    type="button"
                    class="rail-btn"
                    classList={{ on: annotOn() }}
                    title={annotOn() ? t.pane.annotOffTip : t.pane.annotTip}
                    aria-label={t.pane.annot}
                    aria-pressed={annotOn()}
                    onClick={toggleAnnot}
                >
                    ✎
                </button>
                <button
                    type="button"
                    class="rail-btn"
                    disabled={!hasAnnot() || saving()}
                    title={
                        hasAnnot() ? t.pane.annotSave : t.pane.annotSaveEmpty
                    }
                    aria-label={t.pane.annotSave}
                    onClick={() => void saveAnnot()}
                >
                    ⬇
                </button>
            </nav>
            {/* aside 常驻 DOM（hidden 控显隐），保证 thumbs 容器在构造期已就位 */}
            <aside class="pane-side" hidden={!tab()}>
                <div
                    class="side-fill side-thumbs"
                    classList={{ off: tab() !== "thumbs" }}
                >
                    <props.Thumbs
                        thumbsRef={props.thumbsRef}
                        store={props.store}
                    >
                        {(th) => (
                            <button
                                type="button"
                                class="thumb-btn"
                                classList={{ loaded: th.loaded }}
                                page-number={th.pageNumber}
                                onClick={() =>
                                    props.slick()?.gotoPage(th.pageNumber)
                                }
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
                                <span class="thumb-num">
                                    {th.pageLabel ?? th.pageNumber}
                                </span>
                            </button>
                        )}
                    </props.Thumbs>
                </div>
                <Show when={tab() === "outline"}>
                    <div class="side-fill side-body">
                        <Show
                            when={outline()?.length ? outline() : null}
                            keyed
                            fallback={
                                <p class="side-empty muted">
                                    {t.pane.noOutline}
                                </p>
                            }
                        >
                            {(items) => (
                                <ul class="ol-list ol-root">
                                    <For each={items}>
                                        {(item) => (
                                            <OutlineItem
                                                item={item}
                                                slick={props.slick()}
                                            />
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
                            fallback={
                                <p class="side-empty muted">
                                    {t.pane.noAttach}
                                </p>
                            }
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
                                                    onClick={() =>
                                                        downloadAtt(a)
                                                    }
                                                >
                                                    <span class="att-name">
                                                        {a.filename}
                                                    </span>
                                                    <span class="att-size muted">
                                                        {fmtBytes(
                                                            a.content.length,
                                                        )}
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
