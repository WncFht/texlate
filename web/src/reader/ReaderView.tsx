// ReaderView —— 终态三模式阅读器：Toolbar + 横幅槽 + 双栏窗格。
// pane 机制全体内聚：同步引擎（split + 双 handle 就位才建）、模式切换保位置
// （pendingJump 补偿）、位置持久化（1s 防抖 + 卸载/pagehide 冲刷）、>500px
// 漂移跳回、缩放落地（pdf 走 setScale；html/dom 走 setFontSize 档位）、
// Ctrl/Cmd+F 路由到活动窗格 findbar、1/2/3·s·[/]·? 键盘面、分栏拖拽 divider。
//
// mode/syncing/zoom/active/swapped 五个信号属页面态——loadReader 的 reading
// 恢复与 retry 后模式保留都要求它们比本组件长寿，由 Reader 持有、经 props
// 值+setter 读写；下方别名使迁移过来的逻辑与拆分前逐字一致。
//
// U3：两侧 PaneSlot 常驻挂载、隐藏侧 display:none——split↔单栏不再重挂
// PdfPane（pdf.js RO 自愈重排）；hidden 侧 handle 仍在 handles() 里，
// 位置捕获/同步只认 paneVisible 一侧。

import {
    createEffect,
    createMemo,
    createSignal,
    For,
    onCleanup,
    onMount,
    Show,
    type JSX,
    untrack,
} from "solid-js";
import {
    api,
    type DualJson,
    type FileKind,
    type ReaderInfo,
    type ReadingState,
    type TaskStatus,
} from "../api/client";
import Toolbar, { type DownloadItem, type Mode } from "../components/Toolbar";
import { bindMenuDismiss } from "../components/menuNav";
import { createPositionMapper, type DocId, type Pos } from "./alignment";
import { annotFileName, zoomToFontPx } from "./paneUtils";
import { capturePos, jumpTo, scrollTopFor, SyncEngine } from "./sync";
import type { PaneHandle } from "./PdfPane";
import type { HtmlPaneHandle } from "./HtmlPane";
import type { DomPaneHandle } from "./DomPane";
import PaneSlot, { type AnyHandle } from "./PaneSlot";
import GuidePane from "./GuidePane";
import type { ReaderViewState } from "./view";
import { t } from "../i18n";

const JUMPBACK_PX = 500;
const SAVE_DEBOUNCE_MS = 1000;
/** 分栏拖拽比例上下限（15%–85%），dblclick 回 50/50 */
const SPLIT_MIN = 0.15;
const SPLIT_MAX = 0.85;

// putPosition 契约已补全（ReaderKeep=ReadingState 含 swapped，keepalive 透传项在
// rest.ts 签名上）——直接调 api，不再需要本地宽类型别名

interface Props {
    taskId: string;
    /** 已解析的阅读视图（调用方保证 ∈ pdf/html/dom） */
    view: ReaderViewState;
    info: ReaderInfo | null;
    /** undefined = dual.json 未拉完；null = 无文件/拉取失败 */
    dual: DualJson | null | undefined;
    status: TaskStatus | undefined;
    title: string;
    /** arXiv 任务 → 顶栏原文直达链 */
    arxivId?: string;
    downloads: DownloadItem[];
    mode: Mode;
    setMode(m: Mode): void;
    syncing: boolean;
    setSyncing(on: boolean): void;
    zoom: string;
    setZoom(z: string): void;
    active: DocId;
    setActive(d: DocId): void;
    swapped: boolean;
    onSwap(): void;
    /** 非干净终态横幅（ResultBody 槽，自门控） */
    banner?: JSX.Element;
    /** done 态分享弹层内容（调用方判定可分享才给——有值即出工具栏分享钮） */
    sharePanel?: JSX.Element;
    onRetry(): void;
    onCancel(): void;
    onBack(): void;
    /** 窗格 PDF metadata Title 上报（Reader 层拼顶栏兜底标题） */
    onDocTitle?(side: DocId, title: string): void;
}

export default function ReaderView(props: Props) {
    // 页面态信号的本地别名——以下同步/持久化逻辑与拆分前逐字一致
    const info = () => props.info;
    const dual = () => props.dual;
    const mode = () => props.mode;
    const syncing = () => props.syncing;
    const zoom = () => props.zoom;
    const active = () => props.active;
    const swapped = () => props.swapped;
    const setMode = (m: Mode) => props.setMode(m);
    const setSyncing = (on: boolean) => props.setSyncing(on);
    const setZoom = (z: string) => props.setZoom(z);
    const setActive = (d: DocId) => props.setActive(d);

    const [pageNums, setPageNums] = createSignal<Record<DocId, number>>({
        original: 1,
        translated: 1,
    });
    const [drift, setDrift] = createSignal<Partial<Record<DocId, boolean>>>({});
    const [handles, setHandles] = createSignal<
        Partial<Record<DocId, AnyHandle>>
    >({});
    const [helpOpen, setHelpOpen] = createSignal(false);
    const [shareOpen, setShareOpen] = createSignal(false);
    const [splitPct, setSplitPct] = createSignal(0.5);
    let sharePop: HTMLDivElement | undefined;
    let shareBtnEl: HTMLButtonElement | undefined;

    let engine: SyncEngine | null = null;
    let pendingJump: { from: DocId; pos: Pos } | null = null;
    /** 进 guide 时抓的活侧位置——隐藏期 scrollTop 读 0/写无效（实测 chromium），
        出 guide 须用这张回程票对齐，不能吃 capturePos 的 0 值 */
    let guideReturn: { from: DocId; pos: Pos } | null = null;
    const restoredSides = new Set<DocId>();
    let saveTimer = 0;
    let driftRaf = 0;
    let panesEl!: HTMLDivElement;

    // 分享弹层 dismiss：外部 pointerdown 收 / Escape 收+焦点回分享钮（menuNav 共享件）
    bindMenuDismiss({
        open: shareOpen,
        close: () => setShareOpen(false),
        wrap: () => sharePop,
        trigger: () => shareBtnEl,
    });

    const stepPage = (d: number) => {
        const cur = pageNums()[active()] ?? 1;
        const total = pageCounts()[active()] || 1;
        const n = Math.min(total, Math.max(1, cur + d));
        handles()[active()]?.gotoPage?.(n);
    };

    // 键盘面：1/2/3 模式、s 同步、[/] 翻页（段）、? 帮助浮层。
    // 输入控件/编辑区聚焦时不抢键；Ctrl/Cmd+F 路由到活动窗格 findbar。
    onMount(() => {
        const onKey = (e: KeyboardEvent) => {
            if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
                const h = handles()[active()];
                if (h && "openFind" in h) {
                    e.preventDefault();
                    h.openFind();
                }
                return;
            }
            if (e.ctrlKey || e.metaKey || e.altKey) return;
            const tgt = e.target as HTMLElement | null;
            const tag = tgt?.tagName;
            if (
                tag === "INPUT" ||
                tag === "TEXTAREA" ||
                tag === "SELECT" ||
                tgt?.isContentEditable
            )
                return;
            switch (e.key) {
                case "1":
                    planModeChange("split");
                    break;
                case "2":
                    planModeChange("translated");
                    break;
                case "3":
                    planModeChange("original");
                    break;
                case "4":
                    planModeChange("guide");
                    break;
                case "s":
                case "S":
                    setSync(!syncing());
                    break;
                case "[":
                    stepPage(-1);
                    break;
                case "]":
                    stepPage(1);
                    break;
                case "?":
                    setHelpOpen((v) => !v);
                    break;
                case "Escape":
                    if (helpOpen()) {
                        setHelpOpen(false);
                        e.preventDefault();
                    }
                    break;
                default:
                    return;
            }
        };
        document.addEventListener("keydown", onKey);
        onCleanup(() => document.removeEventListener("keydown", onKey));
    });

    // pagehide 冲刷：关 tab/退导航时防抖窗口内的最后位置，
    // keepalive 让请求活到发出为止（普通 fetch 随页面销毁被掐）
    onMount(() => {
        const onHide = () => saveNow({ keepalive: true });
        window.addEventListener("pagehide", onHide);
        onCleanup(() => window.removeEventListener("pagehide", onHide));
    });

    // pane 外窄区（分栏条/jump-back/占位 veil）的滚轮 → 活动窗格滚动口；
    // pane 内 chrome 由 PdfPane 自己的 wheel 转发处理，guide/文档区走原生路径
    onMount(() => {
        const onWheel = (e: WheelEvent) => {
            if (e.ctrlKey || e.metaKey) return;
            const t = e.target as Element | null;
            if (!t || t.closest(".pane") || t.closest(".guide")) return;
            let el: HTMLElement | undefined;
            try {
                el = handles()[active()]?.el;
            } catch {
                return; // 拆解期 slick 已空
            }
            if (!el) return;
            const k = e.deltaMode === 1 ? 16 : 1;
            el.scrollTop += e.deltaY * k;
            el.scrollLeft += e.deltaX * k;
        };
        panesEl.addEventListener("wheel", onWheel, { passive: true });
        onCleanup(() => panesEl.removeEventListener("wheel", onWheel));
    });

    onCleanup(() => {
        engine?.dispose();
        if (driftRaf) window.cancelAnimationFrame(driftRaf);
        // 卸载冲刷：防抖窗口内离开（重试回进度视图/返回列表/切任务）不丢最后一段阅读位置
        if (saveTimer) {
            window.clearTimeout(saveTimer);
            saveTimer = 0;
            saveNow();
        }
    });

    // ---------- 同步引擎 ----------

    const pageCounts = createMemo(() => {
        const i = info();
        const d = dual();
        if (!i) return { original: 1, translated: 1 };
        if (i.view === "html") {
            const n = Math.max(d?.chunks?.length ?? 1, 1);
            return { original: n, translated: n };
        }
        // dom 与 pdf 同路：dom 的 "pages" = 锚定 chunk 数（worker 写进
        // documents.*.pages），不进 dual.chunks 分支
        return {
            original: i.documents.original?.pages ?? 1,
            translated: i.documents.translated?.pages ?? 1,
        };
    });

    const mapper = createMemo(() =>
        createPositionMapper(
            dual()?.alignment ?? info()?.alignment,
            pageCounts(),
        ),
    );

    /** split + 两侧 handle 就位 → 建引擎；否则销毁（handles() 是响应源）。
     *  syncing 不参与本 effect——开/关同步不再整台引擎重挂（滚动监听重绑是白烧） */
    createEffect(() => {
        engine?.dispose();
        engine = null;
        if (mode() !== "split") return;
        const a = handles().original;
        const b = handles().translated;
        if (!a || !b) return;
        const e = new SyncEngine(a, b, mapper());
        e.syncing = untrack(syncing);
        engine = e;
        onCleanup(() => e.dispose());
    });

    // syncing 只写运行中引擎的标志位（引擎缺席时由上面建机路径带初值）
    createEffect(() => {
        if (engine) engine.syncing = syncing();
    });

    const setSync = (on: boolean) => {
        setSyncing(on);
        if (engine) {
            engine.syncing = on;
            if (on) {
                const src = handles()[active()] ?? handles().original;
                if (src) engine.alignNow(src);
            }
        }
        if (!on) updateDrift();
        persistPosition();
    };

    // ---------- 模式切换保位置（texglot planModeChange） ----------

    const planModeChange = (next: Mode) => {
        if (next === mode()) return;
        if (next === "guide") {
            // 导读不是文档侧——不查 handles()[target]、不改 active；
            // pendingJump 也不留脏值（位置职责由 guideReturn 接管）
            if (!props.arxivId) return;
            const src =
                handles()[active()] ??
                handles().original ??
                handles().translated;
            guideReturn =
                src && paneVisible(src.side)
                    ? { from: src.side, pos: capturePos(src) }
                    : null;
            pendingJump = null;
            setMode(next);
            persistPosition();
            return;
        }
        // 出 guide 的回程票优先（隐藏期活侧 scrollTop 读 0——见 guideReturn 注释）
        const ticket = mode() === "guide" ? guideReturn : null;
        guideReturn = null;
        const src = ticket
            ? null
            : (handles()[active()] ??
              handles().original ??
              handles().translated);
        const from = ticket?.from ?? src?.side;
        const pos = ticket?.pos ?? (src ? capturePos(src) : null);
        if (from && pos) {
            // 目标侧：split → 当前隐藏的对侧；单栏 → next 对应侧
            const target: DocId =
                next === "split"
                    ? from === "original"
                        ? "translated"
                        : "original"
                    : next;
            const dst = handles()[target];
            if (dst) {
                // 目标窗格仍在挂载态（U3 后单栏切换两侧俱在）——立即跳，
                // 不留 pendingJump 污染下次挂载
                const to = from === target ? pos : mapper()(pos, from);
                requestAnimationFrame(() => dst.jump(to));
            } else {
                pendingJump = { from, pos };
            }
        }
        setMode(next);
        // 单栏下活动侧跟随可见侧——页码/翻页键/批注都对准可见窗格
        if (next !== "split") setActive(next as DocId);
        persistPosition();
    };

    const paneReady = (side: DocId, h: AnyHandle) => {
        setHandles((prev) => ({ ...prev, [side]: h }));
        if (pendingJump) {
            // 模式切换补偿：对侧位置映射过来
            const { from, pos } = pendingJump;
            pendingJump = null;
            const target = from === side ? pos : mapper()(pos, from);
            requestAnimationFrame(() => h.jump(target));
        } else if (!restoredSides.has(side)) {
            const saved = info()?.reading?.positions?.[side];
            if (saved) queueMicrotask(() => h.jump(saved));
        } else if (engine?.syncing && side !== active()) {
            engine.alignNow(handles()[active()] ?? h);
        }
        restoredSides.add(side);
    };

    const paneDisposed = (side: DocId, h: AnyHandle) =>
        setHandles((prev) => {
            if (prev[side] !== h) return prev;
            const next = { ...prev };
            delete next[side];
            return next;
        });

    const paneVisible = (side: DocId) => mode() === "split" || mode() === side;

    // ---------- 位置持久化 + >500px 跳回 ----------

    const saveNow = (opts?: { keepalive?: boolean }) => {
        const positions: Partial<Record<DocId, Pos>> = {};
        for (const side of ["original", "translated"] as const) {
            const h = handles()[side];
            if (!h || !paneVisible(side)) continue;
            try {
                positions[side] = capturePos(h);
            } catch {
                /* 拆解期 slick 已空——跳过该侧 */
            }
        }
        // 无可写位置（窗格未挂/已卸）不发——空表会覆盖服务端已存位置
        if (Object.keys(positions).length === 0) return;
        const state: ReadingState = {
            positions,
            active: active(),
            mode: mode(),
            zoom: zoom(),
            sync: syncing(),
            swapped: swapped(),
            document_version: info()?.documents.translated?.version,
        };
        void api.putPosition(props.taskId, state, opts).catch(() => undefined);
    };

    const persistPosition = () => {
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(saveNow, SAVE_DEBOUNCE_MS);
    };

    /** 同步关闭时：任一侧与"对侧映射来的期望位置"漂移 >500px → 显示跳回按钮 */
    const updateDrift = () => {
        if (mode() !== "split" || syncing()) {
            setDrift({});
            return;
        }
        const next: Partial<Record<DocId, boolean>> = {};
        for (const side of ["original", "translated"] as const) {
            const me = handles()[side];
            const otherSide: DocId =
                side === "original" ? "translated" : "original";
            const src = handles()[otherSide];
            if (!me || !src) continue;
            const expected = scrollTopFor(
                me,
                mapper()(capturePos(src), otherSide),
            );
            next[side] =
                expected !== null &&
                Math.abs(me.el.scrollTop - expected) > JUMPBACK_PX;
        }
        setDrift(next);
    };

    const jumpBack = (side: DocId) => {
        const me = handles()[side];
        const otherSide: DocId =
            side === "original" ? "translated" : "original";
        const src = handles()[otherSide];
        if (!me || !src) return;
        jumpTo(me, mapper()(capturePos(src), otherSide));
        setDrift((d) => ({ ...d, [side]: false }));
        persistPosition();
    };

    // 滚动侧记集合，rAF 里一次采样——同帧双侧都滚（同步回声带 user scroll
    // 语义时）两侧页码都回写，不是只留最后进事件的一侧
    const scrolledSides = new Set<DocId>();

    const onUserScroll = (side: DocId) => {
        persistPosition();
        scrolledSides.add(side);
        // 双侧滚动+程序化回声每事件都进来——合帧到一次几何采样
        if (driftRaf) return;
        driftRaf = window.requestAnimationFrame(() => {
            driftRaf = 0;
            const sides = [...scrolledSides];
            scrolledSides.clear();
            // 滚动侧页码回写（dom/html 无 pdfjs pagechanging 事件，走 capturePos；
            // 几何缓存已在，成本近零；pdf 侧与 onPageChange 同源一致）
            for (const s of sides) {
                const h = handles()[s];
                if (!h) continue;
                try {
                    const p = capturePos(h).page;
                    if (p !== pageNums()[s])
                        setPageNums((prev) => ({ ...prev, [s]: p }));
                } catch {
                    /* 拆解期 slick 已空 */
                }
            }
            updateDrift();
        });
    };

    // ---------- 缩放 / 页码 ----------

    /** 缩放值落单个窗格：pdf → setScale/setScaleValue；html/dom → setFontSize 档位 */
    const applyZoomTo = (h: AnyHandle | undefined, z: string) => {
        if (!h || !z) return;
        const ph = h as PaneHandle;
        if (ph.setScaleValue) {
            if (z.endsWith("%")) ph.setScale(Number(z.slice(0, -1)) / 100);
            else ph.setScaleValue(z);
            return;
        }
        (h as HtmlPaneHandle | DomPaneHandle).setFontSize?.(zoomToFontPx(z));
    };

    // zoom × handles 响应式落地：usePDFSlick 初值恒 page-width（§5.1 坑），
    // reading.zoom 恢复、窗格 keyed 重挂、用户改缩放三路共用——在 paneReady
    // 里手工补赶不上 setInfo→setZoom 之间的 await 窗口
    createEffect(() => {
        const z = zoom();
        for (const side of ["original", "translated"] as const) {
            applyZoomTo(handles()[side], z);
        }
    });

    const applyZoom = (z: string) => {
        setZoom(z);
        persistPosition();
    };

    const gotoPage = (n: number) => {
        handles()[active()]?.gotoPage?.(n);
    };

    const docUrl = (side: DocId) => {
        const i = info();
        const doc = i?.documents[side];
        if (!i || !doc) return "";
        // side→kind 映射按 view 分：dom 链产物是 {en|zh}.html
        const kind: FileKind =
            i.view === "dom"
                ? side === "original"
                    ? "en.html"
                    : "zh.html"
                : side === "original"
                  ? "en.pdf"
                  : "zh.pdf";
        // 优先服务端给的 url；否则按 files 约定拼（带版本校验防旧版，§2.3）
        return (
            doc.url || api.fileUrl(props.taskId, kind, { version: doc.version })
        );
    };

    const isPdf = () => props.view !== "html" && props.view !== "dom";

    // ---------- 分栏拖拽 divider ----------

    const onDividerDown = (e: PointerEvent) => {
        e.preventDefault();
        const bar = e.currentTarget as HTMLElement;
        bar.setPointerCapture(e.pointerId);
        // 拖拽全程 panesEl 几何不变——rect 只读一次，不随 pointermove 反复强制 layout
        const r = panesEl.getBoundingClientRect();
        const move = (ev: PointerEvent) => {
            if (r.width <= 0) return;
            const frac = (ev.clientX - r.left) / r.width;
            // DOM 序恒 original|divider|translated；swapped 仅视觉翻转
            // （row-reverse）——指针越靠右 original 槽越小，取反
            const logical = swapped() ? 1 - frac : frac;
            setSplitPct(Math.min(SPLIT_MAX, Math.max(SPLIT_MIN, logical)));
        };
        const up = () => {
            bar.removeEventListener("pointermove", move);
            bar.removeEventListener("pointerup", up);
            bar.removeEventListener("pointercancel", up);
        };
        bar.addEventListener("pointermove", move);
        bar.addEventListener("pointerup", up);
        bar.addEventListener("pointercancel", up);
    };

    // ---------- 渲染 ----------

    /** 单段重译只在干净/部分终态开放（html 视图内由 HtmlPane 挂钮） */
    const canRetranslate = () =>
        props.status === "done" || props.status === "partial";

    const renderSlot = (side: DocId) => (
        <PaneSlot
            side={side}
            view={props.view}
            version={info()?.documents[side]?.version || undefined}
            url={docUrl(side)}
            chunks={dual()?.chunks ?? []}
            taskId={props.taskId}
            canRetranslate={canRetranslate()}
            annotName={annotFileName(props.taskId, side)}
            active={active() === side}
            hidden={!paneVisible(side)}
            grow={
                mode() === "split"
                    ? side === "original"
                        ? splitPct()
                        : 1 - splitPct()
                    : undefined
            }
            drift={drift()[side]}
            onReady={(h) => paneReady(side, h)}
            onDispose={(h) => paneDisposed(side, h)}
            onPageChange={(p) => setPageNums((s) => ({ ...s, [side]: p }))}
            onActivate={() => setActive(side)}
            onScroll={() => onUserScroll(side)}
            onJumpBack={() => jumpBack(side)}
            onDocTitle={(ti) => props.onDocTitle?.(side, ti)}
        />
    );

    const HELP_ITEMS: [string, string][] = [
        ["1 / 2 / 3", t.reader.helpModes],
        ["4", t.reader.helpGuide],
        ["S", t.reader.helpSync],
        ["[ / ]", t.reader.helpPages],
        ["Ctrl+F", t.reader.helpFind],
        ["?", t.reader.helpHelp],
    ];

    // 帮助浮层打开时聚焦卡片本体——键盘用户随即 Esc/点击之外有焦点落点；
    // 卡片是唯一可聚焦物，Tab 拦下即闭环（无内部控件可循环）
    let helpCard!: HTMLDivElement;
    createEffect(() => {
        if (helpOpen()) queueMicrotask(() => helpCard?.focus());
    });
    const onHelpKey = (e: KeyboardEvent) => {
        if (e.key === "Tab") e.preventDefault();
    };

    return (
        <>
            {/* 终态阅读器（左右互换走 CSS row-reverse，逻辑侧不变） */}
            <div class="tb-host">
                <Toolbar
                    title={props.title}
                    status={props.status}
                    mode={mode()}
                    syncing={syncing()}
                    zoom={zoom()}
                    page={pageNums()[active()]}
                    numPages={pageCounts()[active()]}
                    downloads={props.downloads}
                    arxivId={props.arxivId}
                    pageUnit={isPdf() ? undefined : t.reader.pageUnitChunk}
                    onMode={planModeChange}
                    onSync={setSync}
                    onZoom={applyZoom}
                    onGotoPage={gotoPage}
                    onSwap={() => props.onSwap()}
                    onRetry={() => props.onRetry()}
                    onCancel={() => props.onCancel()}
                    onBack={() => props.onBack()}
                    onHelp={() => setHelpOpen(true)}
                    onShare={
                        props.sharePanel
                            ? () => setShareOpen((v) => !v)
                            : undefined
                    }
                    shareOpen={shareOpen()}
                    shareBtnRef={(el) => (shareBtnEl = el)}
                />
                <Show when={shareOpen()}>
                    <div
                        class="share-pop"
                        ref={(el) => (sharePop = el)}
                        role="dialog"
                        aria-label={t.reader.shareBtn}
                    >
                        {props.sharePanel}
                    </div>
                </Show>
            </div>
            {props.banner}
            <div
                class="panes"
                ref={(el) => (panesEl = el)}
                classList={{
                    swapped: swapped(),
                    single: mode() !== "split",
                    guide: mode() === "guide",
                }}
            >
                {renderSlot("original")}
                <Show when={mode() === "split"}>
                    <div
                        class="pane-divider"
                        role="separator"
                        aria-orientation="vertical"
                        aria-label={t.reader.splitDivider}
                        title={t.reader.splitDividerTip}
                        style={{
                            cursor: "col-resize",
                            flex: "none",
                            width: "5px",
                            "margin-inline": "-2px",
                            "z-index": 7,
                        }}
                        onPointerDown={onDividerDown}
                        onDblClick={() => setSplitPct(0.5)}
                    />
                </Show>
                {renderSlot("translated")}
                <Show when={mode() === "guide"}>
                    <GuidePane arxivId={props.arxivId} />
                </Show>
            </div>
            <Show when={helpOpen()}>
                <div
                    class="kbd-help"
                    role="dialog"
                    aria-modal="true"
                    aria-label={t.reader.helpTitle}
                    onClick={() => setHelpOpen(false)}
                    onKeyDown={onHelpKey}
                >
                    <div
                        class="kbd-help-card"
                        ref={(el) => (helpCard = el)}
                        tabIndex={-1}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <h2 class="rp-status">{t.reader.helpTitle}</h2>
                        <dl class="kbd-help-list">
                            <For each={HELP_ITEMS}>
                                {([k, d]) => (
                                    <div class="kbd-help-row">
                                        <dt>
                                            <kbd>{k}</kbd>
                                        </dt>
                                        <dd>{d}</dd>
                                    </div>
                                )}
                            </For>
                        </dl>
                    </div>
                </div>
            </Show>
        </>
    );
}
