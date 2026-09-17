// ReaderView —— 终态三模式阅读器：Toolbar + 横幅槽 + 双栏窗格。
// pane 机制全体内聚：同步引擎（split + 双 handle 就位才建）、模式切换保位置
// （pendingJump 补偿）、位置持久化（1s 防抖 + 卸载冲刷）、>500px 漂移跳回、
// 缩放落地（usePDFSlick 初值恒 page-width 的 §5.1 坑走 zoom×handles effect）、
// Ctrl/Cmd+F 路由到活动窗格 findbar。
//
// mode/syncing/zoom/active/swapped 五个信号属页面态——loadReader 的 reading
// 恢复与 retry 后模式保留都要求它们比本组件长寿，由 Reader 持有、经 props
// 值+setter 读写；下方别名使迁移过来的逻辑与拆分前逐字一致。

import {
    createEffect,
    createMemo,
    createSignal,
    onCleanup,
    onMount,
    Show,
    type JSX,
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
import { createPositionMapper, type DocId, type Pos } from "./alignment";
import { annotFileName } from "./paneUtils";
import { capturePos, jumpTo, scrollTopFor, SyncEngine } from "./sync";
import type { PaneHandle } from "./PdfPane";
import PaneSlot, { type AnyHandle } from "./PaneSlot";
import type { ReaderViewState } from "./view";

const JUMPBACK_PX = 500;
const SAVE_DEBOUNCE_MS = 1000;

interface Props {
    taskId: string;
    /** 已解析的阅读视图（调用方保证 ∈ pdf/html/dom） */
    view: ReaderViewState;
    info: ReaderInfo | null;
    /** undefined = dual.json 未拉完；null = 无文件/拉取失败 */
    dual: DualJson | null | undefined;
    status: TaskStatus | undefined;
    title: string;
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
    /** done 态分享提示横幅（自门控） */
    shareBanner?: JSX.Element;
    onRetry(): void;
    onCancel(): void;
    onBack(): void;
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
    const [handles, setHandles] = createSignal<Partial<Record<DocId, AnyHandle>>>({});

    let engine: SyncEngine | null = null;
    let pendingJump: { from: DocId; pos: Pos } | null = null;
    const restoredSides = new Set<DocId>();
    let saveTimer = 0;
    let driftRaf = 0;

    // Ctrl/Cmd+F → 活动窗格的 findbar（PDF 侧；HTML 侧无 openFind，放行给浏览器原生查找）
    onMount(() => {
        const onKey = (e: KeyboardEvent) => {
            if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "f") return;
            const h = handles()[active()];
            if (h && "openFind" in h) {
                e.preventDefault();
                h.openFind();
            }
        };
        document.addEventListener("keydown", onKey);
        onCleanup(() => document.removeEventListener("keydown", onKey));
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
        createPositionMapper(dual()?.alignment ?? info()?.alignment, pageCounts()),
    );

    /** split + 两侧 handle 就位 → 建引擎；否则销毁（handles() 是响应源） */
    createEffect(() => {
        engine?.dispose();
        engine = null;
        if (mode() !== "split") return;
        const a = handles().original;
        const b = handles().translated;
        if (!a || !b) return;
        const e = new SyncEngine(a, b, mapper());
        e.syncing = syncing();
        engine = e;
        onCleanup(() => e.dispose());
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
        const src = handles()[active()] ?? handles().original ?? handles().translated;
        if (src) {
            const from = src.side;
            const pos = capturePos(src);
            // 目标侧：split → 当前隐藏的对侧；单栏 → next 对应侧
            const target: DocId =
                next === "split" ? (from === "original" ? "translated" : "original") : next;
            const dst = handles()[target];
            if (dst) {
                // 目标窗格仍在挂载态（split→单栏留下的一侧），paneReady 不会再火——
                // 立即跳，不留 pendingJump 污染下次挂载
                const to = from === target ? pos : mapper()(pos, from);
                requestAnimationFrame(() => dst.jump(to));
            } else {
                pendingJump = { from, pos };
            }
        }
        setMode(next);
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

    const saveNow = () => {
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
        // swapped 字段后于 ReadingState 落地——宽类型携带，服务端列已收
        const state: ReadingState & { swapped?: boolean } = {
            positions,
            active: active(),
            mode: mode(),
            zoom: zoom(),
            sync: syncing(),
            swapped: swapped(),
            document_version: info()?.documents.translated?.version,
        };
        void api.putPosition(props.taskId, state).catch(() => undefined);
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
            const otherSide: DocId = side === "original" ? "translated" : "original";
            const src = handles()[otherSide];
            if (!me || !src) continue;
            const expected = scrollTopFor(me, mapper()(capturePos(src), otherSide));
            next[side] = expected !== null && Math.abs(me.el.scrollTop - expected) > JUMPBACK_PX;
        }
        setDrift(next);
    };

    const jumpBack = (side: DocId) => {
        const me = handles()[side];
        const otherSide: DocId = side === "original" ? "translated" : "original";
        const src = handles()[otherSide];
        if (!me || !src) return;
        jumpTo(me, mapper()(capturePos(src), otherSide));
        setDrift((d) => ({ ...d, [side]: false }));
        persistPosition();
    };

    const onUserScroll = () => {
        persistPosition();
        // 双侧滚动+程序化回声每事件都进来——合帧到一次几何采样
        if (driftRaf) return;
        driftRaf = window.requestAnimationFrame(() => {
            driftRaf = 0;
            updateDrift();
        });
    };

    // ---------- 缩放 / 页码 ----------

    /** 缩放值落单个窗格：% → setScale；命名值 → setScaleValue；HTML 侧无接口跳过 */
    const applyZoomTo = (h: AnyHandle | undefined, z: string) => {
        const ph = h as PaneHandle | undefined;
        if (!z || !ph?.setScaleValue) return;
        if (z.endsWith("%")) ph.setScale(Number(z.slice(0, -1)) / 100);
        else ph.setScaleValue(z);
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
        return doc.url || api.fileUrl(props.taskId, kind, { version: doc.version });
    };

    const isDom = () => props.view === "dom";
    const isPdf = () => props.view !== "html" && props.view !== "dom";

    // ---------- 渲染 ----------

    const renderSlot = (side: DocId) => (
        <PaneSlot
            side={side}
            view={props.view}
            version={info()?.documents[side]?.version || undefined}
            url={docUrl(side)}
            chunks={dual()?.chunks ?? []}
            annotName={annotFileName(props.taskId, side)}
            active={active() === side}
            drift={drift()[side]}
            onReady={(h) => paneReady(side, h)}
            onDispose={(h) => paneDisposed(side, h)}
            onPageChange={(p) => setPageNums((s) => ({ ...s, [side]: p }))}
            onActivate={() => setActive(side)}
            onScroll={onUserScroll}
            onJumpBack={() => jumpBack(side)}
        />
    );

    return (
        <>
            {/* 终态阅读器（左右互换走 CSS row-reverse，逻辑侧不变） */}
            <Toolbar
                title={props.title}
                status={props.status}
                mode={mode()}
                syncing={syncing()}
                zoom={zoom()}
                page={pageNums()[active()]}
                numPages={pageCounts()[active()]}
                active={active()}
                swapped={swapped()}
                downloads={props.downloads}
                canGotoPage={isPdf() || isDom()}
                canZoom={isPdf()}
                onMode={planModeChange}
                onSync={setSync}
                onZoom={applyZoom}
                onGotoPage={gotoPage}
                onSwap={() => props.onSwap()}
                onActiveSide={setActive}
                onRetry={() => props.onRetry()}
                onCancel={() => props.onCancel()}
                onBack={() => props.onBack()}
            />
            {props.banner}
            {props.shareBanner}
            <div class="panes" classList={{ swapped: swapped(), single: mode() !== "split" }}>
                <Show when={paneVisible("original")}>{renderSlot("original")}</Show>
                <Show when={paneVisible("translated")}>{renderSlot("translated")}</Show>
            </div>
        </>
    );
}
