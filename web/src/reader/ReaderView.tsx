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
//
// 本文件是 composition root：各子系统在 host/ 下按依赖序实例化
// （paneRegistry→registry→derives→navPosition→syncZoom→modeSwitch→
// citeLane→selCommands→sentAlignHost→cursorHost→layers），paneReady/
// paneDisposed 是有意设计的七路扇出编排枢纽（pendingJump→deepSeq→saved→
// engine.alignNow→pendingMirror 补投→wireSelPane→sa.syncPanes）——归入任一
// hook 会反向污染其依赖面，故留根部。

import { createSignal, onCleanup, onMount, Show, type JSX } from "solid-js";
import {
    api,
    type DualJson,
    type FileKind,
    type ReaderInfo,
    type TaskStatus,
} from "../api/client";
import Toolbar, { type DownloadItem, type Mode } from "./chrome/Toolbar";
import { bindMenuDismiss } from "../components/menuNav";
import type { DocId } from "./logic/alignment";
import { annotFileName } from "./logic/paneUtils";
import PaneSlot, { type AnyHandle } from "./panes/PaneSlot";
import GuidePane from "./panes/GuidePane";
import type { ReaderViewState } from "./logic/view";
import { taskStore } from "../stores/tasks";
import { keptRefs } from "../stores/keptRefs";
import { settingsStore } from "../stores/settings";
import { t } from "../i18n";
import { FloatBar } from "./chrome/FloatBar";
import CiteCard, { CiteCardBody } from "./cards/CiteCard";
import RefsPanel from "./cards/RefsPanel";
import HelpOverlay from "./chrome/HelpOverlay";
import { createPaneRegistry } from "./host/paneRegistry";
import { createCmdRegistry } from "./host/registry";
import { createDerives } from "./host/derives";
import { createNavPosition } from "./host/navPosition";
import { createSyncZoom } from "./host/syncZoom";
import { createModeSwitch } from "./host/modeSwitch";
import { createCiteLane } from "./host/citeLane";
import { createSelCommands } from "./host/selCommands";
import { createSentAlignHost } from "./host/sentAlignHost";
import { createCursorHost } from "./host/cursorHost";
import { createLayers } from "./host/layers";

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

    const [helpOpen, setHelpOpen] = createSignal(false);
    const [shareOpen, setShareOpen] = createSignal(false);
    let sharePop: HTMLDivElement | undefined;
    let shareBtnEl: HTMLButtonElement | undefined;
    let panesEl!: HTMLDivElement;
    let liveEl: HTMLDivElement | undefined;

    // 分享弹层 dismiss：外部 pointerdown 收 / Escape 收+焦点回分享钮（menuNav 共享件）
    bindMenuDismiss({
        open: shareOpen,
        close: () => setShareOpen(false),
        wrap: () => sharePop,
        trigger: () => shareBtnEl,
    });

    /** 单段重译只在干净/部分终态开放（html 视图内由 HtmlPane 挂钮） */
    const canRetranslate = () =>
        props.status === "done" || props.status === "partial";

    // ---------- host hooks（依赖序实例化；各簇 store 边随身） ----------

    const {
        handles,
        setHandles,
        restoredSides,
        sideOfHit,
        bodyOf,
        liveBodyEl,
        paneVisible,
    } = createPaneRegistry({ mode, active });
    const { reg } = createCmdRegistry({ handles, sideOfHit });
    const { seqposMap, seqOf, seqLenOf, pageCounts, mapper, citeIndex } =
        createDerives({ info, dual });
    const {
        pageNums,
        setPageNums,
        drift,
        navStacks,
        navMuteUntil,
        navPairSeq,
        pendingMirror,
        onNavBegin,
        samePos,
        mirrorTo,
        onDestJump,
        navBack,
        navFwd,
        deepSeqTarget,
        fromTask,
        returnToSrc,
        saveNow,
        persistPosition,
        clearSaveTimer,
        flushSave,
        updateDrift,
        jumpBack,
        onUserScroll,
    } = createNavPosition({
        handles,
        paneVisible,
        mapper,
        info,
        dual,
        view: () => props.view,
        taskId: () => props.taskId,
        mode,
        active,
        syncing,
        zoom,
        swapped,
    });
    const {
        engine,
        setSync,
        applyZoom,
        gotoPage,
        stepPage,
        splitPct,
        setSplitPct,
        onDividerDown,
    } = createSyncZoom({
        handles,
        mode,
        syncing,
        setSyncing,
        zoom,
        setZoom,
        active,
        swapped,
        mapper,
        pageCounts,
        pageNums,
        navMuteUntil,
        updateDrift,
        persistPosition,
        panesEl: () => panesEl,
    });
    const { pendingJump, planModeChange } = createModeSwitch({
        mode,
        setMode,
        setActive,
        active,
        arxivId: () => props.arxivId,
        handles,
        paneVisible,
        mapper,
        saveNow,
        clearSaveTimer,
        persistPosition,
    });
    const {
        citeMeta,
        citeEntryOf,
        citeKeyOf,
        citeKeepPayload,
        menuCard,
        setMenuCard,
        openMenuCard,
        jumpToCite,
        retxSeq,
        refsOpen,
        setRefsOpen,
        ctf,
    } = createCiteLane({
        reg,
        citeIndex,
        handles,
        sideOfHit,
        bodyOf,
        taskId: () => props.taskId,
        onNavBegin,
        onDestJump,
    });
    const {
        retxPending,
        cl,
        ctxm,
        barItemsFor,
        barAction,
        barObserveEls,
        barApiRef,
        runKeyCmd,
        openCiteAtFocus,
    } = createSelCommands({
        reg,
        handles,
        sideOfHit,
        bodyOf,
        liveBodyEl,
        view: () => props.view,
        taskId: () => props.taskId,
        dual,
        seqOf,
        citeIndex,
        navStacks,
        navBack,
        navFwd,
        openMenuCard,
        jumpToCite,
        retxSeq,
        canRetranslate,
        panesEl: () => panesEl,
    });
    const { sa } = createSentAlignHost({
        reg,
        handles,
        liveBodyEl,
        view: () => props.view,
        seqposMap,
        seqOf,
        seqLenOf,
        mapper,
        navStacks,
        navPairSeq,
        onNavBegin,
        samePos,
    });
    const { wireSelPane, unwireSelPane } = createCursorHost({
        handles,
        bodyOf,
        liveEl: () => liveEl,
        ctxm,
        shareOpen,
        helpOpen,
        // layers 是最大扇入最后实例化——本簇键位回调只运行期触达，
        // 晚期绑定闭包跨过去（初始化序无害）
        layerOpen: (l) => hostLayers.layerOpen(l),
    });
    const hostLayers = createLayers({
        handles,
        active,
        syncing,
        helpOpen,
        setHelpOpen,
        shareOpen,
        setShareOpen,
        shareBtnEl: () => shareBtnEl,
        ctxm,
        menuCard,
        setMenuCard,
        cl,
        refsOpen,
        setRefsOpen,
        setSync,
        navBack,
        navFwd,
        stepPage,
        planModeChange,
        runKeyCmd,
        openCiteAtFocus,
        panesEl: () => panesEl,
        mirrorTo,
        navPairSeq,
    });
    const { forEachEsc } = hostLayers;

    // 冷进 reader（深链/刷新）settings 可能从未加载——Home 才 refresh。
    // 不补的话 cite-translate 凭证门 hasApiKey() 恒 undefined 恒放行，
    // 无 key 点击白造一行 needs_auth 死任务才等到 CTA 收口
    if (!settingsStore.loaded()) void settingsStore.refresh();

    // pane 外窄区（分栏条/jump-back/占位 veil）的滚轮 → 活动窗格滚动口；
    // pane 内 chrome 由 PdfPane 自己的 wheel 转发处理，guide/文档区走原生路径
    onMount(() => {
        const onWheel = (e: WheelEvent) => {
            if (e.ctrlKey || e.metaKey) return;
            const tgt = e.target as Element | null;
            if (!tgt || tgt.closest(".pane") || tgt.closest(".guide")) return;
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

    // live-pane（TaskProgress 宿主，.panes 外）右键 → 命令菜单同一委托；
    // snapshot 内 veto 已放宽 live 目标（见 ctxm.snapshot 注释）
    onMount(() => {
        const onCtx = (e: Event) => {
            const t = e.target as Element | null;
            if (t?.closest?.(".live-pane")) ctxm.onContextMenu(e as MouseEvent);
        };
        document.addEventListener("contextmenu", onCtx);
        onCleanup(() => document.removeEventListener("contextmenu", onCtx));
    });

    // 各簇清理由所属 hook 自持（engine/driftRaf/游标/cl/sa/ctf 各归各）；
    // 根部只留防抖存盘冲刷——其余子系统已在上方实例化时注册过自家 onCleanup
    onCleanup(() => flushSave());

    const paneReady = (side: DocId, h: AnyHandle) => {
        setHandles((prev) => ({ ...prev, [side]: h }));
        if (pendingJump.cur) {
            // 模式切换补偿：对侧位置映射过来
            const { from, pos } = pendingJump.cur;
            pendingJump.cur = null;
            const target = from === side ? pos : mapper()(pos, from);
            requestAnimationFrame(() => h.jump(target));
        } else if (!restoredSides.has(side)) {
            // 深链优先于服务端恢复位——#/reader/{id}?seq=N 是显式意图
            const ds = deepSeqTarget();
            const saved = ds ? null : info()?.reading?.positions?.[side];
            const target = ds ?? saved;
            if (target) queueMicrotask(() => h.jump(target));
        } else if (engine()?.syncing && side !== active()) {
            engine()?.alignNow(handles()[active()] ?? h);
        }
        restoredSides.add(side);
        // 待镜像补投：引用跳转在 dst 窗格重挂窗口期发起——此刻 handle 就位
        const pd = pendingMirror.get(side);
        if (pd !== undefined) {
            pendingMirror.delete(side);
            mirrorTo(side, pd.dest, 2, pd.pair);
        }
        // sel-system 挂点：bodyEl 在场才分段/观察/建游标（pdf 侧空转）
        wireSelPane(side);
        // sent-align：新 pane 就位重扫（重挂后注入标引要补回）
        sa.syncPanes();
    };

    const paneDisposed = (side: DocId, h: AnyHandle) => {
        if (handles()[side] === h) unwireSelPane(side);
        setHandles((prev) => {
            if (prev[side] !== h) return prev;
            const next = { ...prev };
            delete next[side];
            return next;
        });
        // sent-align：handle 摘表后重扫——旧 bodyEl 引用不再挂在 panes()
        sa.syncPanes();
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

    // ---------- 渲染 ----------

    const renderSlot = (side: DocId) => (
        <PaneSlot
            side={side}
            view={props.view}
            version={info()?.documents[side]?.version || undefined}
            url={docUrl(side)}
            chunks={dual()?.chunks ?? []}
            taskId={props.taskId}
            canRetranslate={canRetranslate()}
            retxPending={retxPending}
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
            citeIndex={citeIndex()}
            citeMeta={citeMeta}
            onTranslateRef={(entry) => ctf.translateEntry(entry)}
            refStatusOf={(id) => taskStore.taskByArxiv(id)}
            navDepth={() => ({
                back: navStacks[side].canBack(),
                fwd: navStacks[side].canFwd(),
            })}
            onNavBack={() => navBack(side)}
            onNavFwd={() => navFwd(side)}
            onReady={(h) => paneReady(side, h)}
            onDispose={(h) => paneDisposed(side, h)}
            onPageChange={(p) => setPageNums((s) => ({ ...s, [side]: p }))}
            onActivate={() => setActive(side)}
            onScroll={() => onUserScroll(side)}
            onJumpBack={() => jumpBack(side)}
            onNavBegin={onNavBegin}
            onDestJump={(d, pre, post) => onDestJump(side, d, pre, post)}
            onDocTitle={(ti) => props.onDocTitle?.(side, ti)}
        />
    );

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
                    onRefs={ctf.openPanel}
                    refsTotal={ctf.refsTotal()}
                    refsCount={ctf.refsCount()}
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
                {/* 文献翻译面板（cite-translate lane——顶栏「文献」钮 /
                    cite.refsAll / 凭证门暂存回放三面同开） */}
                <Show when={refsOpen()}>
                    <RefsPanel
                        {...ctf.panelProps()}
                        onClose={() => setRefsOpen(false)}
                    />
                </Show>
            </div>
            <Show when={fromTask}>
                <button
                    type="button"
                    class="tb-btn"
                    style={{
                        position: "fixed",
                        top: "56px",
                        left: "12px",
                        "z-index": 28,
                    }}
                    title={taskStore.task(fromTask!)?.title ?? fromTask!}
                    onClick={returnToSrc}
                >
                    ← {t.reader.back} ·{" "}
                    {(taskStore.task(fromTask!)?.title ?? fromTask!).slice(
                        0,
                        24,
                    )}
                </button>
            </Show>
            {props.banner}
            <div
                class="panes"
                ref={(el) => (panesEl = el)}
                classList={{
                    swapped: swapped(),
                    single: mode() !== "split",
                    guide: mode() === "guide",
                }}
                on:contextmenu={ctxm.onContextMenu}
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
            {/* sel-system 挂载面：右键菜单（Portal→body）/ 划词浮条
                （settings 开关，默认开）/ 菜单级引用卡 / 句游标 aria-live */}
            {ctxm.menu()}
            <Show when={settingsStore.floatbar()}>
                <FloatBar
                    itemsFor={barItemsFor}
                    onAction={barAction}
                    suppressed={() =>
                        ctxm.isOpen() ||
                        shareOpen() ||
                        helpOpen() ||
                        menuCard() != null ||
                        cl.cardOpen() ||
                        refsOpen() ||
                        // pane 侧 cite 层（UsagesCard 等 escOpen 申报者）
                        forEachEsc("escOpen", "cite")
                    }
                    observeEls={barObserveEls}
                    apiRef={barApiRef}
                />
            </Show>
            <Show when={menuCard()} keyed>
                {(c) => (
                    <CiteCard rect={c.rect} onClose={() => setMenuCard(null)}>
                        <CiteCardBody
                            entry={citeEntryOf(c.hit.cite)}
                            meta={() => citeMeta(citeKeyOf(c.hit.cite))}
                            kept={keptRefs.isKept(citeKeyOf(c.hit.cite))}
                            onToggleKeep={() =>
                                keptRefs.toggle(
                                    props.taskId,
                                    citeKeyOf(c.hit.cite),
                                    citeKeepPayload(c.hit.cite),
                                )
                            }
                            onJump={() => {
                                const hit = c.hit;
                                setMenuCard(null);
                                jumpToCite(hit);
                            }}
                            onTranslate={() =>
                                ctf.translateEntry({
                                    key: citeKeyOf(c.hit.cite),
                                    arxivId: citeEntryOf(c.hit.cite).arxivId,
                                })
                            }
                            refTask={(id) => taskStore.taskByArxiv(id)}
                        />
                    </CiteCard>
                )}
            </Show>
            <div
                class="sr-only"
                aria-live="polite"
                ref={(el) => (liveEl = el)}
            />
            <Show when={helpOpen()}>
                <HelpOverlay
                    open={helpOpen}
                    onClose={() => setHelpOpen(false)}
                />
            </Show>
        </>
    );
}
