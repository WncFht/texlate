// PdfPane —— usePDFSlick 封装，向 SyncEngine 暴露 PaneLike 几何接口。
// 规格须知（§5.1）：usePDFSlick 不做实例清理，url 变化会叠第二个实例——
// 因此本组件由调用方按 doc.version 整体重挂（keyed），绝不原位换 url。
//
// 侧件布局：左 rail（缩略图/大纲/附件/查找/信息）+ 侧栏 + 主视区。
// thumbs 容器常驻 DOM 是硬约束——usePDFSlick 构造期 untrack 读 thumbs 元素，
// 晚挂载则 thumbnailViewer 永不创建（pdfslick#136，见 PaneSidebar 头注）。
//
// 拆分面：PaneHandle/Props 契约在 pdfHandle.ts；DOM 纯工具在 pdfDom.ts；
// idle 扫描五表在 pdfDestScan.ts（createDestScan）；sent-align 闪/染双轨+
// 落定揭示闪在 pdfSeqFx.ts（createSeqFx）；Inspect/本体反查在
// pdfInspect.ts（createPdfInspect）；卡族+DOM 委托在 pdfCards.ts
// （usePdfCards）；nav 队列+goToDestination 劫持+mirrorDest 在
// pdfNav.ts（createPdfNav）。工厂全部 getter 注入、owner 顶层调用；
// handle 前向引用统一 getHandle() 惰性解。

import {
    createEffect,
    createSignal,
    onCleanup,
    onMount,
    Show,
    untrack,
} from "solid-js";
import { usePDFSlick } from "@pdfslick/solid";
import "@pdfslick/solid/dist/pdf_viewer.css";

import {
    capturePos,
    jumpTo,
    onPaneScroll,
    scrollTopFor,
    type PageGeom,
} from "../logic/sync";
import { type PdfDocLike } from "../cite/citations";
import CiteCard, { CiteCardBody } from "../cards/CiteCard";
import UsagesCard from "../cards/UsagesCard";
import { MARKED_SEL, seqOfMarkedSpan } from "../pdf/pdfmarks";
import { ensurePdfjsWorker } from "../../pdfjs";
import {
    applyPdfTheme,
    currentPdfTheme,
    patchPdfDocument,
    patchPdfPage,
} from "../pdf/pdfTheme";
import PaneSidebar from "./PaneSidebar";
import FindBar from "./FindBar";
import DocInfo from "./DocInfo";
import { t } from "../../i18n";
import {
    type PaneHandle,
    type PdfPageViewLike,
    type Props,
} from "../pdf/pdfHandle";
import { attachWheelForward, type PdfPageDivOf } from "../pdf/pdfDom";
import { createDestScan } from "../pdf/pdfDestScan";
import { createSeqFx } from "../pdf/pdfSeqFx";
import { createPdfInspect } from "../pdf/pdfInspect";
import { usePdfCards } from "../pdf/pdfCards";
import { createPdfNav } from "../pdf/pdfNav";

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
        usePDFSlick(
            untrack(() => props.url),
            {
                scaleValue: "page-width",
                getDocumentParams: {
                    cMapUrl: "/pdfjs/cmaps/",
                    cMapPacked: true,
                    standardFontDataUrl: "/pdfjs/standard_fonts/",
                    wasmUrl: "/pdfjs/wasm/",
                },
            },
        );

    const viewer = () => pdfSlick()?.viewer;
    const pdfDoc = () =>
        (pdfSlick()?.document ?? null) as unknown as PdfDocLike | null;
    const pageDivOf: PdfPageDivOf = (page) =>
        (viewer() as unknown as { _pages?: PdfPageViewLike[] })?._pages?.[
            page - 1
        ]?.div;

    const [findOpen, setFindOpen] = createSignal(false);
    const [infoOpen, setInfoOpen] = createSignal(false);
    let paneEl!: HTMLDivElement;
    let findInput: HTMLInputElement | undefined;
    // findbar 关闭焦点回触发源（rail ⌕ 钮；Ctrl+F 开时同样是它承接，一致可预期）
    let findBtn: HTMLButtonElement | undefined;

    // idle 渐进扫描五表（destNames/destSites/destPos/destPoint/seqPageMap）
    // ——abort 仍在本组件 onCleanup 触发
    const scan = createDestScan({
        currentPage: () => viewer()?.currentPageNumber,
        pdfDoc,
    });
    const { destNames, destSites } = scan;

    // seq → 已渲染 markedContent span 集——handle.seqEls 与 seqFx 注入同源
    const seqEls = (seq: number): HTMLElement[] => {
        const c = viewer()?.container;
        if (!c) return [];
        return [...c.querySelectorAll<HTMLElement>(MARKED_SEL)].filter(
            (el) => seqOfMarkedSpan(el) === seq,
        );
    };

    // sent-align 闪/染双轨 + 落定揭示闪（saFlashAt/saTintReq 私态在厂内）
    const fx = createSeqFx({
        viewer,
        seqEls,
        pageDiv: pageDivOf,
        destPoint: scan.destPoint,
        pdfDoc,
    });
    const { reapplyTint, ...fxSlice } = fx;

    // Inspect/本体反查——openCard/openUsagesFor 取 cards 的活引用
    // （cards 后建，事件期调用时 TDZ 已解）
    const inspect = createPdfInspect({
        viewer,
        destPos: scan.destPos,
        destSites: scan.destSites,
        destPoint: scan.destPoint,
        pageDiv: pageDivOf,
        openCard: (a) => cards.openCard(a),
        openUsagesFor: (t, a, at) => cards.openUsagesFor(t, a, at),
    });

    // 悬浮卡族 + DOM 委托（use* 契约——本行即 owner 内同步调用点）
    const cards = usePdfCards({
        viewer,
        paneEl: () => paneEl,
        pdfSlick,
        isDocumentLoaded,
        pdfDoc,
        destNames: scan.destNames,
        destSites: scan.destSites,
        destPoint: scan.destPoint,
        pageDiv: pageDivOf,
        citeIndex: () => props.citeIndex,
        citeMeta: (key) => props.citeMeta?.(key),
        destAtPoint: (x, y, tol) => inspect.destAtPoint(x, y, tol),
    });
    const {
        card,
        ucard,
        usageJumps,
        curAnchor,
        openUsagesFor,
        citeKey,
        keepPayload,
        closeCard,
        closeUcard,
        closeAll,
    } = cards;

    // nav 队列 + goToDestination 劫持 + mirrorDest——handle 前向引用
    // 走 getHandle() 惰性解（原 this 语义）
    const nav = createPdfNav({
        pdfSlick,
        isDocumentLoaded,
        pdfDoc,
        getHandle: () => handle,
        destNames: scan.destNames,
        closeAll,
        onNavBegin: () => props.onNavBegin?.(),
        onDestJump: (dest, pre, post) => props.onDestJump?.(dest, pre, post),
        flashDest: fxSlice.flashDest,
    });

    // 页面几何缓存：滚动路径高频调 pages()，_pages[].div 的 offsetTop/Height
    // 只在缩放/旋转/换文档时变化——eventBus 事件 + 容器 RO 失效
    let geomCache: PageGeom[] | null = null;
    const invalidateGeom = () => {
        geomCache = null;
    };

    const openFind = (query?: string) => {
        setFindOpen(true);
        props.onActivate?.();
        queueMicrotask(() => {
            // query 注入：FindBar 的 query 是内部 signal，不改文件的前提
            // 下经「DOM value + 原生 input 事件」喂——Solid 委托 onInput
            // 走 document 监听，bubbles 事件即触发 setQuery→emitDebounced
            if (query != null && findInput) {
                findInput.value = query;
                findInput.dispatchEvent(new Event("input", { bubbles: true }));
            }
            findInput?.focus();
            if (query != null) findInput?.select();
        });
    };

    const closeFind = () => {
        setFindOpen(false);
        findBtn?.focus();
    };

    /** pdf.js 批注选中态快照——editingstateschanged.details
        .hasSelectedEditor 边扫边存（keymap 占有判定的实时面） */
    let edSelected = false;

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
            if (geomCache) return geomCache;
            const views =
                (viewer() as unknown as { _pages?: PdfPageViewLike[] })
                    ?._pages ?? [];
            const out: PageGeom[] = [];
            views.forEach((v, i) => {
                if (v?.div)
                    out.push({
                        page: i + 1,
                        top: v.div.offsetTop,
                        height: v.div.offsetHeight,
                    });
            });
            geomCache = out;
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
        escOpen: (l) =>
            l === "cite"
                ? card() != null || ucard() != null
                : l === "find"
                  ? findOpen()
                  : l === "info"
                    ? infoOpen()
                    : false,
        escClose: (l) => {
            if (l === "cite") {
                closeCard();
                closeUcard();
            } else if (l === "find") {
                // 与 FindBar 内部 close 同协议——findbarclose 清命中高亮，
                // 仅 setFindOpen(false) 会把高亮留在 textLayer 上
                pdfSlick()?.eventBus.dispatch("findbarclose", {});
                closeFind();
            } else if (l === "info") setInfoOpen(false);
        },
        pdfjsState: () => ({
            armed: (pdfSlickStore.annotationEditorMode ?? 0) !== 0,
            selected: edSelected,
        }),
        seqEls,
        seqPage: (seq) => scan.seqPageMap.get(seq)?.page ?? null,
        seqAtPoint: (x, y) => {
            const c = viewer()?.container;
            if (!c) return null;
            // markedContent span 或其内层文本片——closest 上爬取锚宿主
            const sp = c.ownerDocument
                .elementFromPoint(x, y)
                ?.closest<HTMLElement>(MARKED_SEL);
            if (!sp || !c.contains(sp)) return null;
            return seqOfMarkedSpan(sp);
        },
        posAtPoint: (x, y) => {
            const c = viewer()?.container;
            if (!c) return null;
            const pg = c.ownerDocument
                .elementFromPoint(x, y)
                ?.closest<HTMLElement>("[data-page-number]");
            if (!pg || !c.contains(pg)) return null;
            const page = Number(pg.getAttribute("data-page-number"));
            if (!Number.isFinite(page) || page < 1) return null;
            const r = pg.getBoundingClientRect();
            return {
                page,
                fraction:
                    r.height > 0
                        ? Math.min(Math.max((y - r.top) / r.height, 0), 1)
                        : 0,
                x:
                    r.width > 0
                        ? Math.min(Math.max((x - r.left) / r.width, 0), 1)
                        : 0,
            };
        },
        ...fxSlice,
        ...inspect,
        openUsagesFor,
        mirrorDest: nav.mirrorDest,
        dests: () => destNames,
        async posDest(pos) {
            const doc = pdfDoc();
            if (!doc) return null;
            try {
                const page = await doc.getPage(pos.page);
                // view=[x1,y1,x2,y2] 用户空间盒（bottom-up 点制）；
                // getViewport({scale:1}).height 同值——view 直读优先
                const view = (page as unknown as { view?: number[] }).view;
                const h =
                    view && view.length >= 4
                        ? view[3] - view[1]
                        : page.getViewport({ scale: 1 }).height;
                if (!(h > 0)) return null;
                // XYZ dest：[页0基, {name:'XYZ'}, x, y, zoom]——x/zoom
                // null 保持现状；fraction 是 top-down 分位 → bottom-up y。
                // y 上抬 0.18*可见高——pdf.js 把 dest 点贴到视口顶，
                // 多留这段让目标行停在与 capturePos 一致的 ~20% 焦点线；
                // 可见高是 CSS px，dest y 是 PDF 单位底向上，要除当前
                // 缩放换算
                const scale =
                    (viewer() as unknown as { currentScale?: number })
                        ?.currentScale ?? 1;
                const visH =
                    scale > 0
                        ? (viewer()?.container.clientHeight ?? 0) / scale
                        : 0;
                const y0 = view && view.length >= 4 ? view[1]! : 0;
                const y = Math.min(
                    y0 + (1 - pos.fraction) * h + 0.18 * visH,
                    y0 + h,
                );
                return [pos.page - 1, { name: "XYZ" }, null, y, null];
            } catch {
                return null;
            }
        },
    };

    // 文档加载完成 → 等 pages 就位（_pages[].div 齐全）后上报 handle
    let readyNotified = false;
    let rafId = 0;
    createEffect(() => {
        if (!isDocumentLoaded() || readyNotified) return;
        const waitPages = () => {
            const s = pdfSlick();
            const views = (
                s?.viewer as unknown as {
                    _pages?: (PdfPageViewLike & {
                        pdfPage?: Parameters<typeof patchPdfPage>[0];
                    })[];
                }
            )?._pages;
            if (s && views?.length && views.every((v) => v?.div)) {
                // 文档级 getPage 补丁根治懒赋值时序洞;view 级补扫
                // 覆盖补丁落地前已取出的页;主题 effect 重渲兜底
                patchPdfDocument(
                    s.document as Parameters<typeof patchPdfDocument>[0],
                );
                for (const v of views) if (v?.pdfPage) patchPdfPage(v.pdfPage);
                readyNotified = true;
                props.onReady?.(handle);
                // dest 预扫走 idle——不占就绪路径
                const d = pdfDoc();
                if (d)
                    scan.scanDests(
                        d,
                        (d as unknown as { numPages?: number }).numPages ??
                            pdfSlickStore.numPages ??
                            0,
                    );
                return;
            }
            rafId = requestAnimationFrame(waitPages);
        };
        waitPages();
    });
    onCleanup(() => cancelAnimationFrame(rafId));
    onCleanup(() => scan.abort());
    onCleanup(() => props.onDispose?.(handle));

    // 纸面色板 ↔ PDF 页渲染:色板身份(bg|fg|invert)变化 → applyPdfTheme
    // 全页 reset + 原位重渲;osDark 与 paperTheme 两路信号经
    // currentPdfTheme 收敛为单一身份键,选板与 auto/none 系统翻转同路。
    // 首挂载恰为 null(原样透传)时不动——默认渲出的就是对的
    let prevPaletteKey = "";
    createEffect(() => {
        const s = pdfSlick();
        if (!s || !isDocumentLoaded()) return;
        const th = currentPdfTheme();
        const key = th
            ? `${th.background}|${th.foreground}|${!!th.invertImages}`
            : "";
        if (key === prevPaletteKey) return;
        prevPaletteKey = key;
        applyPdfTheme(s);
    });

    // 几何缓存失效线：pdf.js 布局变化走 eventBus，容器尺寸走 RO；
    // 同轨订 editingstateschanged——keymap 的 pdfjs().selected 数据源
    createEffect(() => {
        const s = pdfSlick();
        if (!s) return;
        const bus = s.eventBus;
        for (const ev of [
            "scalechanging",
            "rotationchanging",
            "pagesinit",
            "pagesdestroy",
        ]) {
            bus.on(ev, invalidateGeom);
        }
        // details={isEditing,isEmpty,hasSomethingToUndo/Redo,hasSelectedEditor,
        // hasSelectedText}（pdfjs-dist 实证）；防御两形——details 缺失时直读
        const onEdState = (e: object) => {
            const d = e as {
                details?: { hasSelectedEditor?: boolean };
                hasSelectedEditor?: boolean;
            };
            edSelected = !!(
                d.details?.hasSelectedEditor ?? d.hasSelectedEditor
            );
        };
        bus.on("editingstateschanged", onEdState);
        // textLayer 懒渲/重渲把锚 span 整棵换掉——存活悬停按 saTintReq
        // 补染（懒渲页现形后 peer 色不该缺席；saTint 内已滤零尺寸壳）
        bus.on("textlayerrendered", reapplyTint);
        const ro =
            typeof ResizeObserver === "function"
                ? new ResizeObserver(invalidateGeom)
                : null;
        ro?.observe(s.viewer.container);
        onCleanup(() => {
            for (const ev of [
                "scalechanging",
                "rotationchanging",
                "pagesinit",
                "pagesdestroy",
            ]) {
                bus.off(ev, invalidateGeom);
            }
            bus.off("editingstateschanged", onEdState);
            bus.off("textlayerrendered", reapplyTint);
            ro?.disconnect();
        });
    });

    // usePDFSlick 无实例清理（§5.1）——卸载时亲手拆：unbindEvents 停
    // window/eventBus 监听，loadingTask.destroy() 杀 worker 解析态。
    // document 未落地（在途加载）时订 store 首个 setState 补刀——订阅
    // 不设上限：slick 不暴露 loadingTask 句柄，这是捕获迟到文档的唯一
    // 钩子；加载失败整条引用环（worker promise→store→listener→s）随
    // promise 释放即可被 GC，超时退订反而留出「到得比超时晚」的泄漏窗
    onCleanup(() => {
        const s = pdfSlick();
        if (!s) return;
        try {
            s.unbindEvents();
        } catch {
            /* 半初始化实例上解绑可能抛——不挡销毁 */
        }
        const destroyDoc = () => {
            const d = s.document;
            if (d) void d.loadingTask.destroy().catch(() => undefined);
        };
        if (s.document) {
            destroyDoc();
            return;
        }
        const unsub = s.store.subscribe(() => {
            if (!s.document) return;
            unsub();
            destroyDoc();
        });
    });

    // 文档标题上报：store.title 由 _parseDocumentInfo 落定（metadata.info.Title）——
    // 空串不上报，调用方留 arxiv_id 兜底
    createEffect(() => {
        const title = pdfSlickStore.title;
        if (title) props.onDocTitle?.(title);
    });

    // 页码上报（pdfjs pagechanging → store.pageNumber）
    createEffect(() => {
        const n = pdfSlickStore.pageNumber;
        if (typeof n === "number")
            props.onPageChange?.(n, pdfSlickStore.numPages ?? 0);
    });

    // 用户滚动 → 上层做位置持久化/漂移检测（同步引擎自己在容器上挂监听）
    createEffect(() => {
        const s = pdfSlick();
        if (!s) return;
        onPaneScroll(s.viewer.container, () => props.onScroll?.());
    });

    // chrome 区滚轮转发——语义注释在 pdfDom.attachWheelForward 头顶
    onMount(() => {
        onCleanup(attachWheelForward(paneEl, () => viewer()?.container));
    });

    return (
        <div
            ref={(el) => (paneEl = el)}
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
                findBtnRef={(el) => (findBtn = el)}
                onToggleInfo={() => setInfoOpen((v) => !v)}
                annotName={props.annotName}
            />
            <div class="pane-body">
                <PDFSlickViewer viewerRef={viewerRef} store={pdfSlickStore} />
                <Show when={card()}>
                    {(c) => (
                        <CiteCard
                            rect={c().rect}
                            onClose={closeCard}
                            onCardEnter={cards.onCardEnter}
                            onCardLeave={cards.onCiteCardLeave}
                        >
                            <CiteCardBody
                                entry={c().entry}
                                // meta 走活访问器——远端回包晚于开卡时
                                // props.citeMeta 才填好，快照会永久缺字段
                                meta={() => {
                                    const en = c().entry;
                                    return en
                                        ? props.citeMeta?.(en.key)
                                        : undefined;
                                }}
                                loading={c().loading}
                                notFound={c().notFound}
                                kept={props.citeKept?.(citeKey(c()))}
                                onShowUsages={
                                    destNames.has(c().dest) ||
                                    destSites.get(c().dest)?.length
                                        ? () =>
                                              openUsagesFor(
                                                  c().dest,
                                                  curAnchor(),
                                              )
                                        : undefined
                                }
                                usagesCount={destSites.get(c().dest)?.length}
                                onToggleKeep={
                                    props.onToggleKeep
                                        ? () =>
                                              props.onToggleKeep?.(
                                                  citeKey(c()),
                                                  keepPayload(c()),
                                              )
                                        : undefined
                                }
                                onTranslate={
                                    props.onTranslateRef
                                        ? () =>
                                              props.onTranslateRef?.(
                                                  c().entry ?? {
                                                      key: citeKey(c()),
                                                      order: 0,
                                                      label: "",
                                                      text: "",
                                                  },
                                              )
                                        : undefined
                                }
                                refTask={props.refStatusOf}
                                onJump={() => {
                                    const ls = pdfSlick()?.linkService;
                                    if (ls) void ls.goToDestination(c().dest);
                                    closeCard();
                                }}
                            />
                        </CiteCard>
                    )}
                </Show>
                <Show when={ucard()}>
                    {(u) => (
                        <UsagesCard
                            rect={u().rect}
                            entry={u().entry}
                            onClose={closeUcard}
                            onCardEnter={cards.onCardEnter}
                            onCardLeave={cards.onUsageCardLeave}
                            onJump={(s) => {
                                const j = usageJumps()[s.order];
                                const ls = pdfSlick()?.linkService;
                                // XYZ dest：y=annot 顶（bottom-up 用户空间），
                                // 落定后引用行贴视口顶
                                if (j && ls)
                                    void ls.goToDestination([
                                        j.page - 1,
                                        { name: "XYZ" },
                                        null,
                                        j.y,
                                        null,
                                    ]);
                                closeUcard();
                            }}
                            onJumpTarget={() => {
                                const ls = pdfSlick()?.linkService;
                                if (ls)
                                    void ls.goToDestination(
                                        u().entry.target.id,
                                    );
                                closeUcard();
                            }}
                        />
                    )}
                </Show>
                <FindBar
                    slick={pdfSlick}
                    open={findOpen()}
                    inputRef={(el) => (findInput = el)}
                    onClose={closeFind}
                />
                <Show when={infoOpen()}>
                    <DocInfo
                        store={pdfSlickStore}
                        onClose={() => setInfoOpen(false)}
                    />
                </Show>
                <Show when={!isDocumentLoaded() && !error()}>
                    <div class="pane-veil">
                        <div
                            class="spinner"
                            role="status"
                            aria-label={t.pane.pdfLoading}
                        />
                    </div>
                </Show>
                <Show when={error()}>
                    {(e) => (
                        <div
                            class="pane-veil pane-error"
                            style={{ "flex-direction": "column", gap: "8px" }}
                        >
                            <span>
                                {t.pane.pdfError}
                                {String(e())}
                            </span>
                            <Show when={props.onReload}>
                                <button
                                    type="button"
                                    class="btn-ghost"
                                    onClick={() => props.onReload?.()}
                                >
                                    {t.reader.retry}
                                </button>
                            </Show>
                        </div>
                    )}
                </Show>
            </div>
        </div>
    );
}
