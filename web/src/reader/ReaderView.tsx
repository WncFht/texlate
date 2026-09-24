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
    type KeptRef,
    type ReaderInfo,
    type ReadingState,
    type TaskStatus,
} from "../api/client";
import Toolbar, { type DownloadItem, type Mode } from "../components/Toolbar";
import { bindMenuDismiss } from "../components/menuNav";
import {
    createPositionMapper,
    other,
    type Alignment,
    type DocId,
    type Pos,
} from "./alignment";
import { nearestSeq, seqPairs, seqPos } from "./pdfseqpos";
import { annotFileName, zoomToFontPx } from "./paneUtils";
import { capturePos, jumpTo, scrollTopFor, SyncEngine } from "./sync";
import { buildCiteIndex, type BibEntry, type RefMeta } from "./citations";
import { NavStack } from "./navstack";
import type { PaneHandle } from "./PdfPane";
import type { HtmlPaneHandle } from "./HtmlPane";
import type { DomPaneHandle } from "./DomPane";
import PaneSlot, { type AnyHandle } from "./PaneSlot";
import GuidePane from "./GuidePane";
import type { ReaderViewState } from "./view";
import { taskStore } from "../stores/tasks";
import { toast } from "../stores/toastStore";
import { keptRefs } from "../stores/keptRefs";
import { settingsStore } from "../stores/settings";
import { fmt, t } from "../i18n";
import { attachReaderKeys } from "./keymap";
import { Registry } from "./cmd/cmdreg";
import {
    makeCmdCtx,
    registerCommands,
    type CmdCtx,
    type CmdDeps,
} from "./cmd/commands";
import {
    snapshotHit,
    type HitCtx,
    type PaneSide,
} from "./cmd/hitctx";
import {
    cmdLabel,
    menuItemsFor,
    useContextMenu,
} from "./ContextMenu";
import { FloatBar, type FloatBarApi, type FloatBarItem } from "./FloatBar";
import { collapseSelection, hasLiveSelection } from "./sel/selection";
import { segmentDoc, type SegSide, type SentMark } from "./sel/sentseg";
import { makeCursor, type Cursor } from "./sel/cursor";
import { chunkUntranslated } from "./markdown";
import CiteCard, { CiteCardBody } from "./CiteCard";
import { registerFindUsages } from "./features/findusages";
import {
    registerCopyLatex,
    type CopyLatexPane,
} from "./features/copylatex";
import { registerCiteTranslate } from "./features/citetranslate";
import {
    attachSentAlign,
    registerSentAlign,
    type SentAlignPane,
} from "./features/sentalign";
import RefsPanel from "./RefsPanel";
import { fromParamOf } from "./tasknav";

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
    /** 程序导航静音计数——引用跳转/镜像/栈回放窗口内抑 drift 重算；
        navMuteUntil 是同窗口给 SyncEngine 的时间戳（对象持有——
        引擎重建后新实例读同一截止点） */
    let navHolds = 0;
    const navMuteUntil = { at: 0 };
    /** dst 侧 handle 缺席时的待镜像 {dest,pair}——paneReady/重试补投
        （每侧一槽，新镜像覆盖旧的，last-wins） */
    const pendingMirror = new Map<DocId, { dest: unknown; pair: number }>();
    /** 镜像跳配对号——cite 跳每发一次 +1，双侧栈同号入栈；↩/↪ 命中
        pair 项时对侧栈顶同号即联动（见 navBack/navFwd） */
    let navPairSeq = 0;
    /** 每侧一栈：named-dest 跳转压栈（滚动永不入栈）；sioyek 回写语义 */
    const navStacks: Record<DocId, NavStack> = {
        original: new NavStack(),
        translated: new NavStack(),
    };
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
        gotoPage(Math.min(total, Math.max(1, cur + d)));
    };

    // ---------- sel-system：命令注册表 + 命中快照 + 右键菜单/划词浮条 +
    // Esc 层栈 + 句游标（cmd/sel 内核 Wave B 的 Wave C/D 挂载契约） ----------

    /** menu-spec 18 命令注册表——deps 不进 registerCommands（run 读
        ctx.deps），逐命中经 makeCmdCtx 注入 */
    const reg = new Registry<CmdCtx>();
    registerCommands(reg, {});
    // find-usages lane 自注册（menu-spec 外项）——open 按 hit 解命中侧
    // handle 直开 usages 卡；无 openUsagesFor 的 pane 静默 no-op
    registerFindUsages(reg, {
        open: (c) => {
            const h = handles()[sideOfHit(c.hit)];
            if (h && "openUsagesFor" in h)
                h.openUsagesFor?.(
                    c.hit.cite.targetEl ?? c.hit.cite.targetId,
                    c.hit.cite.anchorEl,
                );
        },
    });

    // copy-latex lane：math/chunk/sel 三命令 + document 级公式点击委托。
    // cardOpen/closeCard 并进 layerOpen/closeLayer 的 'cite' 层 +
    // FloatBar suppressed 名单（LatexCard 自带 Esc capture 先杀事件——
    // 栈层只承担「开着」的可见性判定）
    const clPanes = (): CopyLatexPane[] => {
        const out: CopyLatexPane[] = [];
        for (const side of ["original", "translated"] as const) {
            const h = handles()[side];
            if (!h) continue;
            out.push({
                kind: props.view,
                bodyEl: "bodyEl" in h ? h.bodyEl() : undefined,
                side: side === "translated" ? "zh" : "en",
            });
        }
        // live-pane 无 .pane 壳（paneSide=null 盲区）——zh 侧身份显式给
        const live = liveBodyEl();
        if (live) out.push({ kind: "live", bodyEl: live, side: "zh" });
        return out;
    };
    const cl = registerCopyLatex(reg, {
        taskId: () => props.taskId,
        panes: clPanes,
        dual: () => dual(),
        toastOk: (m) => toast.ok(m),
        toastErr: (m) => toast.err(m),
    });

    // sent-align lane：会话 attach + sent.gotoPeer 命令注册。
    // paneReady/paneDisposed/settings.sentAlign 翻转三处都调
    // sa.syncPanes()——bodyEl 同体免重挂，enabled 假则全剥注入标引
    const saPanes = (): SentAlignPane[] => {
        const out: SentAlignPane[] = [];
        // live-pane 列头——attach 内 want 同侧后写胜，真 zh pane 在场时
        // live 只作候补（live 独占 zh 侧时才实际挂载）
        const live = liveBodyEl();
        if (live) out.push({ kind: "live", side: "zh", bodyEl: live });
        for (const side of ["original", "translated"] as const) {
            const h = handles()[side];
            if (!h) continue;
            const saSide = side === "translated" ? "zh" : "en";
            if ("bodyEl" in h && typeof h.bodyEl === "function") {
                out.push({
                    kind: props.view,
                    side: saSide,
                    bodyEl: h.bodyEl(),
                    scroller: h.el,
                    capture: () => capturePos(h),
                });
            } else {
                // pdf 窗格无 DOM 体——DOM→PDF 跳转目标 + PDF 点击源
                // （seqAtPoint：TLXC 锚命中优先，未命中 nearestSeq 兜底）
                out.push({
                    kind: "pdf",
                    side: saSide,
                    clickEl: (() => {
                        try {
                            return h.el;
                        } catch {
                            return undefined;
                        }
                    })(),
                    posAtPoint: (x, y) =>
                        "posAtPoint" in h
                            ? (h.posAtPoint?.(x, y) ?? null)
                            : null,
                    seqAtPoint: (x, y) => {
                        if ("seqAtPoint" in h) {
                            const s = h.seqAtPoint?.(x, y);
                            if (s != null) return s;
                        }
                        const p =
                            "posAtPoint" in h
                                ? h.posAtPoint?.(x, y)
                                : null;
                        // 距离闸 1.0=只收同页锚——稀疏 seqpos（老任务
                        // 无 TLXC 标）下防点击被吸到跨页孤锚，超距落回
                        // jumpPosToPdf 比例旧路
                        return p
                            ? nearestSeq(seqposMap(), saSide, p, 1)
                            : null;
                    },
                });
            }
        }
        return out;
    };
    const sa = attachSentAlign({
        panes: saPanes,
        enabled: () => settingsStore.sentAlign(),
        deps: {
            navBegin: () => onNavBegin(),
            recordJump: (dst, pre, post) => {
                if (!pre || !post || samePos(pre, post)) return;
                navStacks[
                    dst === "zh" ? "translated" : "original"
                ].recordJump(pre, post, ++navPairSeq);
            },
            mapPos: (pos, from) =>
                mapper()(pos, from === "zh" ? "translated" : "original"),
            pdfDest: (dst, pos) => {
                const h =
                    handles()[dst === "zh" ? "translated" : "original"];
                return h && "posDest" in h
                    ? (h.posDest?.(pos) ?? Promise.resolve(null))
                    : Promise.resolve(null);
            },
            pdfJump: (dst, dest) => {
                const h =
                    handles()[dst === "zh" ? "translated" : "original"];
                return Promise.resolve(
                    h && "mirrorDest" in h
                        ? (h.mirrorDest?.(dest) ?? null)
                        : null,
                );
            },
            pdfFlash: (dst, pos) => {
                const h =
                    handles()[dst === "zh" ? "translated" : "original"];
                if (h && "flashAtPos" in h) h.flashAtPos?.(pos);
            },
            // seq 臂：seqpos 直锚（Option B 服务端注入的消费口）
            seqPos: (seq, side) => seqPos(seqposMap(), seq, side),
            seqOfChunk: (key) => seqOf().get(key) ?? null,
            pdfFlashSeq: (dst, seq, pos) => {
                const h =
                    handles()[dst === "zh" ? "translated" : "original"];
                if (h && "flashSeq" in h) h.flashSeq?.(seq, pos);
                else if (h && "flashAtPos" in h && pos)
                    h.flashAtPos?.(pos);
            },
        },
    });
    const saReg = registerSentAlign(reg, { session: sa.session });
    // 开关翻转 → 差异重扫（关=剥光 .ens/.zhs 标引，开=重注入）
    createEffect(() => {
        settingsStore.sentAlign();
        sa.syncPanes();
    });
    /** 在飞重译 seq 集——经 PaneSlot 与 HtmlPane 共享（hitctx
        chunk.pending 与按钮防抖读同一份才实时） */
    const retxPending = new Set<number>();
    /** FloatBar 控制器 + 最后一次 itemsFor 的 ctx（onAction 复用同快照） */
    let barApi: FloatBarApi | null = null;
    let barCtx: CmdCtx | null = null;
    /** 双侧分句表（原位重灌——cursor.otherSents 持同引用才不失效） +
        句游标/观察器登记 */
    const sents: Record<DocId, SentMark[]> = {
        original: [],
        translated: [],
    };
    const cursors: Partial<Record<DocId, Cursor>> = {};
    const segMOs = new Map<DocId, MutationObserver>();
    const segTimers = new Map<DocId, number>();
    let liveEl: HTMLDivElement | undefined;
    /** 菜单级引用卡（右键 cite.card / 'c' 键路开卡）——锚 rect + 命中快照 */
    const [menuCard, setMenuCard] = createSignal<{
        rect: DOMRect;
        hit: HitCtx;
    } | null>(null);

    /** hit.paneSide → DocId；panes 内非 pane 目标落活动侧 */
    const sideOfHit = (hit: HitCtx): DocId =>
        hit.paneSide === "en"
            ? "original"
            : hit.paneSide === "zh"
              ? "translated"
              : active();

    /** 本侧文本宿主（dom/html 的 bodyEl 挂点）；pdf/缺席 → null */
    const bodyOf = (side: DocId): HTMLElement | null => {
        const h = handles()[side];
        return h && "bodyEl" in h && typeof h.bodyEl === "function"
            ? h.bodyEl()
            : null;
    };

    /** live-pane 文本宿主——LivePane 挂在 TaskProgress（.panes 外、非
        handles() 体系），partial 共屏/同页时经 DOM 现查（copy-latex
        zh 盲区兜底与 sent-align 的 live 侧登记共用此源） */
    const liveBodyEl = (): HTMLElement | null =>
        document.querySelector<HTMLElement>(".live-pane .pane-html-body");

    /** GET /reader 顶层 seqpos——seq 级双侧 Pos（服务端懒算缓存）。
        mapper landmarks 合流与 sent-align seq 臂共用此源 */
    const seqposMap = createMemo(() => info()?.seqpos ?? {});

    /** chunk_id→seq 映射（dom 键）+ seq 串直解（html 键）双登记 */
    const seqOf = createMemo(() => {
        const m = new Map<string, number>();
        for (const c of dual()?.chunks ?? []) {
            if (c.chunk_id) m.set(c.chunk_id, c.seq);
            m.set(String(c.seq), c.seq);
        }
        return m;
    });

    /** chunk 文本解析：dual 行优先（raw en/zh——chunkSideText 的 en 回退会
        谎报 hasZh）；dom 链无行则退对侧 pane 同键块 textContent */
    const chunkText = (key: string, lang: PaneSide): string | null => {
        const row = (dual()?.chunks ?? []).find(
            (c) => String(c.seq) === key || c.chunk_id === key,
        );
        if (row) {
            const raw = lang === "en" ? row.en : row.zh;
            return raw?.trim() || null;
        }
        const body = bodyOf(lang === "en" ? "original" : "translated");
        const sel = `[data-chunk="${key.replace(/(["\\])/g, "\\$1")}"]`;
        return body?.querySelector(sel)?.textContent?.trim() || null;
    };

    /** zh 未译外部判定（en 侧命中无从看 badge——按 chunks 行补） */
    const zhUntranslated = (key: string): boolean => {
        const row = (dual()?.chunks ?? []).find(
            (c) => String(c.seq) === key || c.chunk_id === key,
        );
        return row ? chunkUntranslated(row) : false;
    };

    /** hit 侧 named-dest 集（pdf dests() 预扫子集；dom/html 侧 undefined——
        只查命中侧防对侧 pdf 同名 dest 谎报 targetExists） */
    const destsOfHit = (target: Element | null) => {
        const raw = target?.closest(".pane")?.getAttribute("data-side");
        const side: DocId = raw === "translated" ? "translated" : "original";
        const h = handles()[side];
        return h && "dests" in h ? h.dests?.() : undefined;
    };

    /** 事件时刻命中快照：双侧 bodies + 目标就近宿主（跨 pane 选区并集）；
        caps 基底 discover 常驻，快照后按 hit 侧补丁 nav/find/retx */
    const snap = (target: Element | null): HitCtx => {
        const bodies: Element[] = [];
        for (const s of ["original", "translated"] as const) {
            const b = bodyOf(s);
            if (b) bodies.push(b);
        }
        const extra = target?.closest?.(
            ".pane-html-body, .textLayer, .pane-body",
        );
        if (extra && !bodies.includes(extra)) bodies.push(extra);
        const hit = snapshotHit(target, undefined, {
            bodies: bodies.length ? bodies : undefined,
            seqOf: seqOf(),
            pending: retxPending,
            chunkText,
            zhUntranslated,
            citeIndex: citeIndex(),
            dests: destsOfHit(target),
            caps: { discover: true, linkScheme: true },
        });
        const side = sideOfHit(hit);
        const h = handles()[side];
        hit.caps.navBack = navStacks[side].canBack();
        hit.caps.navFwd = navStacks[side].canFwd();
        hit.caps.findInPane = !!h && "openFind" in h;
        hit.caps.retx = canRetranslate() && hit.view === "html";
        // assist 恒 false（无端点）；linkScheme 真——#/reader/{id}?seq=N
        // 已入 App.parseHash，chunk.copyLink 产物回本阅读器可消费
        return hit;
    };

    /** 命中侧依赖面——openFind/nav/citeJump/retx 全绑 hit 侧 handle */
    const depsFor = (hit: HitCtx): CmdDeps => {
        const staticSide = sideOfHit(hit);
        return {
            openFind: (q) => {
                const h = handles()[staticSide];
                if (h && "openFind" in h) h.openFind(q);
            },
            navBack: () => navBack(staticSide),
            navFwd: () => navFwd(staticSide),
            citeCard: () => openMenuCard(hit),
            citeJump: () => jumpToCite(hit),
            discoverOverview: (id) => api.discoverOverview(id),
            retranslate: (seq) => retxSeq(seq, hit),
            chunkText,
            chunkLink: (chunk) =>
                chunk.intSeq != null
                    ? `${window.location.origin}${window.location.pathname}#/reader/${props.taskId}?seq=${chunk.intSeq}`
                    : null,
            toastOk: (m) => toast.ok(m),
            toastErr: (m) => toast.err(m),
        };
    };

    /** cite → BibEntry：citeIndex 三形命中（hitctx 同口径）→ 合成兜底
        （entryText/arxiv/doi 来自 hitctx 已抽字段） */
    const citeLookup = (bibkey: string | null): BibEntry | undefined =>
        !bibkey
            ? undefined
            : (citeIndex().lookup(bibkey) ??
              citeIndex().lookup(bibkey.replace(/^bib\./, "")) ??
              citeIndex().lookup(`cite.${bibkey}`));
    const citeEntryOf = (
        cite: HitCtx["cite"],
    ): Pick<BibEntry, "label" | "text" | "arxivId" | "doi"> => {
        const e = citeLookup(cite.bibkey);
        return (
            e ?? {
                label: "",
                text: cite.entryText ?? "",
                arxivId: cite.arxivId ?? undefined,
                doi: cite.doi ?? undefined,
            }
        );
    };
    /** kept/meta 键——与 PdfPane citeKey 同口径（entry.key ?? bibkey） */
    const citeKeyOf = (cite: HitCtx["cite"]): string =>
        citeLookup(cite.bibkey)?.key ?? cite.bibkey ?? cite.targetId ?? "";
    const citeKeepPayload = (cite: HitCtx["cite"]): KeptRef => {
        const e = citeEntryOf(cite);
        return {
            label: e.label || undefined,
            text: e.text || undefined,
            arxivId: e.arxivId,
            doi: e.doi,
            meta: citeMeta(citeKeyOf(cite)),
        };
    };

    /** 跳至引用目标——dom 走 jumpAnchor（record=true：onNavBegin+
        onDestJump 全链）；pdf 走包装版 goToDestination（navChain 串行+
        死链预检+压栈+镜像）；html 兜底 scrollIntoView + 同口径记账 */
    const jumpToCite = (hit: HitCtx) => {
        const side = sideOfHit(hit);
        const h = handles()[side];
        const id = hit.cite.targetId;
        if (!h || !id) return;
        if ("jumpAnchor" in h && typeof h.jumpAnchor === "function") {
            h.jumpAnchor(id);
            return;
        }
        const ls = (h as PaneHandle).slick?.linkService;
        if (ls) {
            void ls.goToDestination(id);
            return;
        }
        const tel = hit.cite.targetEl;
        if (tel instanceof HTMLElement) {
            onNavBegin();
            const pre = capturePos(h);
            tel.scrollIntoView({ block: "start" });
            onDestJump(side, id, pre, capturePos(h));
        }
    };

    /** 单段重译——复用 HtmlPane [data-retx] 钮全链（pending/poll/repaint
        都在 pane 内）；命中侧优先，对侧兜底 */
    const retxSeq = (seq: number, hit: HitCtx) => {
        for (const s of [sideOfHit(hit), other(sideOfHit(hit))]) {
            const btn = bodyOf(s)?.querySelector<HTMLButtonElement>(
                `button.chunk-retx[data-retx="${seq}"]`,
            );
            if (btn && !btn.disabled) {
                btn.click();
                return;
            }
        }
        toast.err(t.live.retxFail);
    };

    const openMenuCard = (hit: HitCtx) => {
        const a = hit.cite.anchorEl;
        if (!a) return;
        const rect = a.getClientRects()[0] ?? a.getBoundingClientRect();
        setMenuCard({ rect, hit });
    };

    // ---------- 划词浮条 + 右键菜单（.panes 容器级委托，pane 重渲免重绑） ----------

    const selAnchorEl = (): Element | null => {
        const n = document.getSelection()?.anchorNode ?? null;
        if (!n) return null;
        return n.nodeType === 3 ? n.parentElement : (n as Element);
    };

    /** 条钮集：锚须在 pane/live-pane 内；enabled+bar 前 5 项，ctx 留存
        供 onAction 复用（与展示同一份快照） */
    const barItemsFor = (_range: Range): FloatBarItem[] => {
        const aEl = selAnchorEl();
        if (!aEl?.closest?.(".pane, .live-pane")) {
            barCtx = null;
            return [];
        }
        const hit = snap(aEl);
        const cmd = makeCmdCtx(hit, depsFor(hit));
        barCtx = cmd;
        return reg
            .enabled(cmd)
            .filter((c) => c.bar)
            .slice(0, 5)
            .map((c) => ({
                id: c.id,
                label: cmdLabel(c),
                hint: c.keys?.[0],
            }));
    };

    const barAction = (id: string) => {
        const cmd = barCtx;
        if (!cmd) return;
        void reg
            .runUnchecked(id, cmd)
            .catch(() => toast.err(t.menu.actionFailed));
    };

    /** RO 目标：panes 容器 + 双侧滚动宿主（pane 拉宽/字体回流全量重估） */
    const barObserveEls = () => {
        const out: (Element | null)[] = [panesEl];
        for (const s of ["original", "translated"] as const) {
            try {
                out.push(handles()[s]?.el ?? null);
            } catch {
                out.push(null); // pdf slick 拆解期 getter 抛
            }
        }
        return out;
    };

    /** cite.jump 动态文案：按 targetKind 换目标名（menu-spec 注） */
    const citeJumpLabel = (hit: HitCtx): string => {
        const name =
            hit.cite.targetKind === "bib"
                ? t.menu.cite.targetBib
                : hit.cite.targetKind === "figure"
                  ? t.menu.cite.targetFigure
                  : hit.cite.targetKind === "table"
                    ? t.menu.cite.targetTable
                    : hit.cite.targetKind === "equation"
                      ? t.menu.cite.targetEquation
                      : hit.cite.targetKind === "theorem"
                        ? t.menu.cite.targetTheorem
                        : hit.cite.targetKind === "section"
                          ? t.menu.cite.targetSection
                          : t.menu.cite.targetOther;
        return fmt(t.menu.cite.jumpTo, { target: name });
    };

    const ctxm = useContextMenu(
        (o) =>
            o.cmd
                ? menuItemsFor(reg, o.cmd, {
                      label: (c, cctx) =>
                          c.id === "cite.jump"
                              ? citeJumpLabel(cctx.hit)
                              : undefined,
                      onError: () => toast.err(t.menu.actionFailed),
                  })
                : [],
        {
            snapshot: (e, _base) => {
                let target = e.target as Element | null;
                const inScope = (el: Element | null): el is Element =>
                    !!el &&
                    (panesEl.contains(el) || !!el.closest(".live-pane"));
                // pdf 命中面退化回补：右键焦点 scrollIntoView 会把 e.target
                // 从 linkAnnotation 锚挤成 textLayer span（注层重建期甚至落
                // 到 pane 外 HTML）——同点元素栈里捞真锚顶替
                const altAnchor = () =>
                    document
                        .elementsFromPoint(e.clientX, e.clientY)
                        .find(
                            (el) =>
                                inScope(el) &&
                                el.matches(
                                    "section.linkAnnotation a[href^='#']",
                                ),
                        ) ?? null;
                // .panes 容器级委托——pane 外（顶栏/横幅/导读）放出原生菜单；
                // live-pane 在 .panes 外由 document 级监听转送进来
                if (!inScope(target)) target = altAnchor();
                if (!inScope(target)) return null;
                if (target.closest(".guide")) return null;
                let hit = snap(target);
                if (target.closest(".pane-pdf") && !hit.cite.anchorEl) {
                    const alt = altAnchor();
                    if (alt && alt !== target) {
                        target = alt;
                        hit = snap(alt);
                    }
                }
                const cmd = makeCmdCtx(hit, depsFor(hit));
                // 可见命令为空 → veto 不拦（原生菜单照常）
                if (!reg.visible(cmd).length) return null;
                return { hit, cmd, target };
            },
            bypass: (e) => e.shiftKey, // Shift+右键 = 原生菜单
            // FloatBar 互斥：开单/关单都重估展示闸（allowShow 保锚重现）
            onOpen: () => barApi?.refresh(),
            onClose: () => barApi?.refresh(),
        },
    );

    // ---------- Esc 层栈（keymap 缺省栈经 isOpen/close 回调接本面） ----------

    /** pane 级 Esc 面聚合：escOpen 任一为真 / escClose 双侧广播
        （DomPane 'cite' 卡 / PdfPane 'cite'+'find'+'info' 各管各层） */
    const forEachEsc = (m: "escOpen" | "escClose", layer: string): boolean => {
        let any = false;
        for (const s of ["original", "translated"] as const) {
            const h = handles()[s] as PaneHandle | DomPaneHandle | undefined;
            const fn = h?.[m];
            if (typeof fn !== "function") continue;
            const r = (fn as (layer: string) => unknown).call(h, layer);
            if (m === "escOpen") any = !!r || any;
        }
        return any;
    };

    const layerOpen = (l: string): boolean => {
        switch (l) {
            case "help":
                return helpOpen();
            case "menu":
                return ctxm.isOpen() || shareOpen();
            case "cite":
                return (
                    menuCard() != null ||
                    cl.cardOpen() ||
                    refsOpen() ||
                    forEachEsc("escOpen", "cite")
                );
            case "find":
                return forEachEsc("escOpen", "find");
            case "info":
                return forEachEsc("escOpen", "info");
            case "sel":
                return hasLiveSelection(document);
            default:
                return false;
        }
    };

    const closeLayer = (l: string) => {
        switch (l) {
            case "help":
                setHelpOpen(false);
                return;
            case "menu":
                // ctxm 关单自带回焦；share 弹层回焦分享钮（menuNav 同义）
                if (ctxm.isOpen()) ctxm.close();
                else {
                    setShareOpen(false);
                    shareBtnEl?.focus();
                }
                return;
            case "cite":
                if (menuCard() != null) {
                    setMenuCard(null);
                    return;
                }
                // copy-latex 卡 / 文献面板同层归并（各件自带 Esc capture 先
                // 杀事件——走到这里说明事件漏出或程序化 closeLayer 调用）
                if (cl.cardOpen()) {
                    cl.closeCard();
                    return;
                }
                if (refsOpen()) {
                    setRefsOpen(false);
                    return;
                }
                forEachEsc("escClose", "cite");
                return;
            case "find":
            case "info":
                forEachEsc("escClose", l);
                return;
            case "sel":
                collapseSelection(document);
                return;
        }
    };

    /** pdf.js 批注编辑器态聚合——双侧任一为真即占（keymap 占有判定） */
    const pdfjsAgg = () => {
        let armed = false;
        let selected = false;
        for (const s of ["original", "translated"] as const) {
            const st = (handles()[s] as PaneHandle | undefined)
                ?.pdfjsState?.();
            if (st) {
                armed = armed || st.armed;
                selected = selected || st.selected;
            }
        }
        return { armed, selected };
    };

    /** 键位命令路：选区锚 → hitctx → cmdreg（未注册 id 自然 no-op） */
    const runKeyCmd = (id: string) => {
        const hit = snap(selAnchorEl() ?? document.body);
        void reg
            .run(id, makeCmdCtx(hit, depsFor(hit)))
            .catch(() => toast.err(t.menu.actionFailed));
    };

    /** 'c' 键落在 cite 锚上：卡可填开卡，否则跳目标 */
    const openCiteAtFocus = () => {
        const hit = snap(document.activeElement);
        const cmd = makeCmdCtx(hit, depsFor(hit));
        if (hit.cite.cardFillable) void reg.run("cite.card", cmd);
        else void reg.run("cite.jump", cmd);
    };

    const dispatchAction = (action: string) => {
        switch (action) {
            case "ui:find": {
                const h = handles()[active()];
                if (h && "openFind" in h) h.openFind();
                return;
            }
            case "ui:help":
                setHelpOpen((v) => !v);
                return;
            case "ui:sync":
                setSync(!syncing());
                return;
            case "nav:back":
                navBack(active());
                return;
            case "nav:fwd":
                navFwd(active());
                return;
            case "page:-1":
                stepPage(-1);
                return;
            case "page:+1":
                stepPage(1);
                return;
            case "mode:1":
                planModeChange("split");
                return;
            case "mode:2":
                planModeChange("translated");
                return;
            case "mode:3":
                planModeChange("original");
                return;
            case "mode:4":
                planModeChange("guide");
                return;
            case "sel:copy":
                runKeyCmd("sel.copy");
                return;
            case "sel:xlat":
                runKeyCmd("sel.xlat"); // 未注册——sel-translate lane 挂点
                return;
            case "sel:lookup":
                runKeyCmd("sel.find");
                return;
            case "cite:open":
                openCiteAtFocus();
                return;
            default:
                return; // noop:sel / esc:* / pass / pdfjs:own ——栈内已消化
        }
    };

    // 键盘面：attachReaderKeys 单分发器（Esc 层栈/输入区豁免/Alt+←→/
    // pdfjs 占有/键表 11 步管线——替换原手排 switch）。
    onMount(() => {
        const keys = attachReaderKeys({
            act: (kind, detail) => {
                if (kind !== "dispatch") return;
                const a = (detail as { action?: string } | undefined)?.action;
                if (a) dispatchAction(a);
            },
            isOpen: layerOpen,
            close: closeLayer,
            hasSelection: () => hasLiveSelection(document),
            onCite: (tgt) =>
                !!(tgt as Element | null)?.closest?.(
                    "a[href^='#bib.'], a[href^='#cite.'], a.cite-ref, .ltx_cite",
                ),
            pdfjs: pdfjsAgg,
        });
        onCleanup(() => keys.dispose());
    });

    // ---------- 句游标（v 进入；dom/html 双侧各一，pdf 侧不建） ----------

    const segSideOf = (side: DocId): SegSide =>
        side === "translated" ? "zh" : "en";

    /** 重分句：旧 .sb 全摘再 segmentDoc 重钉，数组原位换血
        （cursor.otherSents 持引用——换新数组会让对侧查找失真） */
    const resegment = (side: DocId) => {
        const body = bodyOf(side);
        if (!body) return;
        for (const el of body.querySelectorAll(".sb")) el.remove();
        const marks = segmentDoc(body, segSideOf(side));
        sents[side].length = 0;
        sents[side].push(...marks);
    };

    /** 游标本体：ctor 自挂的 bubble 监听摘掉换 CAPTURE 重挂——模态内按键
        须先于 bubble 阶的 keymap 吃掉（'['双发、Esc 错塌 sel 两坑由此免）；
        浮层在场时模式内按键让路给层内导航 */
    const ensureCursor = (side: DocId) => {
        if (cursors[side] || !sents[side].length) return;
        const h = handles()[side];
        const body = bodyOf(side);
        if (!h || !body) return;
        const cur = makeCursor({
            pane: h.el, // ChunkPaneHandle.el = .pane 滚动宿主
            body,
            sents: sents[side],
            otherSents: sents[other(side)],
            live: liveEl ?? null,
            variant: "roving",
        });
        cur.dispose(); // 摘 ctor 自挂的 bubble 监听——换 capture 重挂
        const onKey = (e: KeyboardEvent): string | null => {
            // 浮层在场（菜单/帮助/引用卡/信息/分享/查找条）→ 层内键盘导航优先；
            // find 在 ESC_ORDER 序位高于 sel——findbar 开着时 Esc 先收条而非退模态
            if (
                cur.state.mode !== "idle" &&
                (ctxm.isOpen() ||
                    shareOpen() ||
                    helpOpen() ||
                    layerOpen("cite") ||
                    layerOpen("find") ||
                    layerOpen("info"))
            )
                return null;
            return cur.onKey(e);
        };
        document.addEventListener("keydown", onKey, true);
        cursors[side] = {
            ...cur,
            dispose: () =>
                document.removeEventListener("keydown", onKey, true),
        };
    };

    const dropCursor = (side: DocId) => {
        cursors[side]?.dispose();
        delete cursors[side];
        sents[side].length = 0;
    };

    /** 游标重建：chunkFirst 快照在 ctor 建——sents 换血后必须重造，
        否则 ]/[ 跳块按旧表落错句 */
    const rebuildCursor = (side: DocId) => {
        const cur = cursors[side];
        if (cur) {
            if (cur.state.mode !== "idle") cur.exit(false);
            cur.dispose();
            delete cursors[side];
        }
        ensureCursor(side);
    };

    /** body 观察：childList 直子级变化（HtmlPane retx replaceWith /
        LivePane insertBefore / DomPane 分片 append 全落这层）→ 120ms
        防抖重分句；.sb 钉在块内部不触发本层——自环天然免 */
    const watchBody = (side: DocId, body: HTMLElement) => {
        segMOs.get(side)?.disconnect();
        const mo = new MutationObserver(() => {
            window.clearTimeout(segTimers.get(side));
            segTimers.set(
                side,
                window.setTimeout(() => {
                    resegment(side);
                    rebuildCursor(side); // DOM 换血后 marker 全换，模态内退模态保命
                }, 120),
            );
        });
        mo.observe(body, { childList: true });
        segMOs.set(side, mo);
    };

    /** pane 挂点三件套：bodyEl 在场才分段/观察/建游标（pdf 侧不建） */
    const wireSelPane = (side: DocId) => {
        const body = bodyOf(side);
        if (!body) return;
        resegment(side);
        watchBody(side, body);
        ensureCursor(side);
    };
    const unwireSelPane = (side: DocId) => {
        segMOs.get(side)?.disconnect();
        segMOs.delete(side);
        window.clearTimeout(segTimers.get(side));
        segTimers.delete(side);
        dropCursor(side);
    };

    // pagehide 冲刷：关 tab/退导航时防抖窗口内的最后位置，
    // keepalive 让请求活到发出为止（普通 fetch 随页面销毁被掐）
    onMount(() => {
        const onHide = () => saveNow({ keepalive: true });
        window.addEventListener("pagehide", onHide);
        onCleanup(() => window.removeEventListener("pagehide", onHide));
    });

    // 后台回前台补一拍任务面：reader 停留期间槽外任务只靠共享列表
    // 轮询（无轮询集时整面停摆），回前台即刻校准徽标/任务行——
    // ttl=0 恒刷（lastFreshAt 门在 ensureFresh 内，节拍天然去重）
    onMount(() => {
        const onVis = () => {
            if (!document.hidden) void taskStore.ensureFresh(0);
        };
        document.addEventListener("visibilitychange", onVis);
        onCleanup(() => document.removeEventListener("visibilitychange", onVis));
    });

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
            if (t?.closest?.(".live-pane"))
                ctxm.onContextMenu(e as MouseEvent);
        };
        document.addEventListener("contextmenu", onCtx);
        onCleanup(() => document.removeEventListener("contextmenu", onCtx));
    });

    onCleanup(() => {
        engine?.dispose();
        if (driftRaf) window.cancelAnimationFrame(driftRaf);
        // sel-system：双侧游标/观察器/分句表卸载（幂等——paneDisposed 可能已清）
        for (const s of ["original", "translated"] as const)
            unwireSelPane(s);
        // Wave C lanes：copy-latex 委托/卡、sent-align 会话+命令、
        // cite-translate 两命令全卸（注册面幂等——重挂不叠）
        cl.dispose();
        sa.dispose();
        saReg.dispose();
        ctf.dispose();
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

    const mapper = createMemo(() => {
        const al = dual()?.alignment ?? info()?.alignment;
        const sp = seqPairs(seqposMap());
        if (!sp.length) return createPositionMapper(al, pageCounts());
        // seq pairs 合流 landmarks——kind:"pages"（或无 alignment）需
        // 翻牌才生效（createPositionMapper 的 useLandmarks 闸）；旧
        // pairs 保留，mapper 内部按两侧各自排序（浮动体出序诚实成结）
        const merged: Alignment = {
            kind: al?.kind === "pages" || !al ? "landmarks" : al.kind,
            heights: al?.heights,
            regions: al?.regions,
            pairs: [...(al?.pairs ?? []), ...sp],
        };
        return createPositionMapper(merged, pageCounts());
    });

    /** split + 两侧 handle 就位 → 建引擎；否则销毁（handles() 是响应源）。
     *  syncing 不参与本 effect——开/关同步不再整台引擎重挂（滚动监听重绑是白烧） */
    createEffect(() => {
        engine?.dispose();
        engine = null;
        if (mode() !== "split") return;
        const a = handles().original;
        const b = handles().translated;
        if (!a || !b) return;
        const e = new SyncEngine(a, b, mapper(), () => navMuteUntil.at);
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

    // ---------- 引用索引 + 跳回栈 + 双栏镜像 ----------

    /** dual.json ph → bibkey 索引；无 ph 时 size=0（卡片走 dest 懒抽取） */
    const citeIndex = createMemo(() => buildCiteIndex(dual()));
    const [refMeta, setRefMeta] = createSignal<Record<string, RefMeta>>({});
    const citeMeta = (key: string) => refMeta()[key];

    // cite-translate lane：cite.translate/cite.refsAll 两命令 + 顶栏
    // 「文献」钮 + RefsPanel 宿主。onNeedAuth 在面板未开时暂存 retry——
    // RefsPanel 挂载自登记 authHost 时由下方包装回放进内联 key 框
    const [refsOpen, setRefsOpen] = createSignal(false);
    let pendingAuth: ((apiKey: string) => Promise<void>) | undefined;
    const ctf = registerCiteTranslate(reg, {
        citeIndex: () => citeIndex(),
        citeMeta,
        task: () => taskStore.task(props.taskId),
        openRefsPanel: () => setRefsOpen(true),
        onNeedAuth: (retry) => {
            pendingAuth = retry;
            setRefsOpen(true);
        },
    });
    const innerSetAuthHost = ctf.ct.setAuthHost.bind(ctf.ct);
    ctf.ct.setAuthHost = (host) => {
        innerSetAuthHost(host);
        if (host && pendingAuth) {
            const r = pendingAuth;
            pendingAuth = undefined;
            host(r);
        }
    };

    // L2 远端增强：文档打开即批量查（S2 scholarphi「打开即批拉、hover 零
    // 等待」同款）——有 arXiv/DOI 线索的条目才送上游；失败静默降级
    createEffect(() => {
        const idx = citeIndex();
        setRefMeta({});
        const refs = idx
            .entries()
            .filter((e) => e.arxivId || e.doi)
            .map((e) => ({ key: e.key, arxivId: e.arxivId, doi: e.doi }));
        if (!refs.length) return;
        void api
            .refsLookup(refs)
            // eslint-disable-next-line solid/reactivity -- .then 投递期读 citeIndex() 判迟到是有意的
            .then((res) => {
                if (citeIndex() !== idx) return; // 文档已换——丢弃迟到回包
                setRefMeta(res.meta ?? {});
            })
            .catch(() => undefined);
    });

    /** 程序导航窗口开始：drift 计数与引擎时间戳各起一拍，
        600ms 自释放——回声窗口覆盖「跳转+镜像+rAF 合帧」全程 */
    const onNavBegin = () => {
        navHolds++;
        navMuteUntil.at = performance.now() + 600;
        window.setTimeout(() => {
            navHolds--;
        }, 600);
    };

    /** 跳前≈跳后判同——dest 已在视口内的点击不产生栈项（幻影 entry 会
        截断前进栈）。fraction/viewport 双阈值容 capture 像素抖动 */
    const samePos = (a: Pos, b: Pos): boolean =>
        a.page === b.page &&
        Math.abs(a.fraction - b.fraction) < 0.002 &&
        Math.abs((a.viewport ?? 0) - (b.viewport ?? 0)) < 0.01;

    /** 镜像到 dst 侧：handle 缺席挂 pendingMirror（paneReady 补投）；
        失败且仍 split 时留 1200ms 重试——dst 重挂窗口期丢镜像比
        晚到镜像更伤。成功且有位移才记 dst 栈（同 pair 入栈供联动回跳） */
    const mirrorTo = (
        dstSide: DocId,
        dest: unknown,
        tries: number,
        pair: number,
    ): void => {
        const dh = handles()[dstSide];
        if (!dh) {
            pendingMirror.set(dstSide, { dest, pair });
            return;
        }
        onNavBegin(); // dst 滚动回声窗
        void (async () => {
            let r: { pre: Pos; post: Pos } | null | undefined;
            try {
                if ("mirrorDest" in dh && dh.mirrorDest) {
                    r = await dh.mirrorDest(dest);
                } else if (
                    "gotoAnchor" in dh &&
                    dh.gotoAnchor &&
                    typeof dest === "string"
                ) {
                    r = dh.gotoAnchor(dest);
                }
            } catch {
                r = null;
            }
            if (r) {
                pendingMirror.delete(dstSide);
                if (!samePos(r.pre, r.post))
                    navStacks[dstSide].recordJump(r.pre, r.post, pair);
                // 镜像落定后的余波回声（图像/字体晚载的二次滚）再补一拍
                navMuteUntil.at = performance.now() + 250;
                return;
            }
            if (mode() === "split" && tries > 0) {
                const item = { dest, pair };
                pendingMirror.set(dstSide, item);
                window.setTimeout(() => {
                    // 槽位已被新镜像/paneReady 覆盖即放弃——只重试自己的项
                    if (pendingMirror.get(dstSide) !== item) return;
                    pendingMirror.delete(dstSide);
                    mirrorTo(dstSide, dest, tries - 1, pair);
                }, 1200);
            }
        })();
    };

    /** named-dest 跳落定：本侧压栈（pre≈post 幻影跳不记）；split 下同侧
        镜像对侧（dst 栈也记，两侧各自的 ↩ 都能回到自己跳前的位置）。
        镜像条件只管 split——syncing 无关（cite 跳是刻意导航不是滚动传播）；
        同步引擎的回声已由 navMuteUntil 窗口吞掉，syncing off 时引擎本就短路 */
    const onDestJump = (side: DocId, dest: unknown, pre: Pos, post: Pos) => {
        const pair = ++navPairSeq;
        if (!samePos(pre, post)) navStacks[side].recordJump(pre, post, pair);
        if (mode() !== "split") return;
        mirrorTo(other(side), dest, 2, pair);
    };

    const navBack = (side: DocId) => {
        const h = handles()[side];
        if (!h) return;
        onNavBegin();
        const r = navStacks[side].back(capturePos(h));
        if (!r && fromTask) {
            returnToSrc();
            return;
        }
        if (r) h.jump(r.pos);
        // 成对回跳：对侧栈顶是同一镜像跳 → 一起回（各自回自己跳前位）
        if (r?.pair !== undefined && mode() === "split") {
            const bs = other(side);
            const bh = handles()[bs];
            if (bh && navStacks[bs].topPair() === r.pair) {
                const rb = navStacks[bs].back(capturePos(bh));
                if (rb) bh.jump(rb.pos);
            }
        }
        persistPosition();
    };
    const navFwd = (side: DocId) => {
        const h = handles()[side];
        if (!h) return;
        onNavBegin();
        const r = navStacks[side].fwd(capturePos(h));
        if (r) h.jump(r.pos);
        // 成对前跳：对侧前进票是同一镜像跳 → 一起前
        if (r?.pair !== undefined && mode() === "split") {
            const bs = other(side);
            const bh = handles()[bs];
            if (bh && navStacks[bs].nextPair() === r.pair) {
                const rb = navStacks[bs].fwd(capturePos(bh));
                if (rb) bh.jump(rb.pos);
            }
        }
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
            // saveNow 必须在 setMode 前——进 guide 后双栏 display:none、
            // paneVisible 全 false，positions 空表早退，pending 防抖存盘
            // 会被白清；guide 模式本身不落库（回程位置走 guideReturn）
            saveNow();
            window.clearTimeout(saveTimer);
            saveTimer = 0;
            setMode(next);
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
            const target: DocId = next === "split" ? other(from) : next;
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

    /** 深链 seq（chunk.copyLink 产物回本阅读器 #/reader/{id}?seq=N）——
        hash 一次性快照；pdf 视图 chunk 序≠页序不落（deepSeqTarget 判空） */
    const deepSeq = (() => {
        const m = /[?&]seq=(\d+)/.exec(window.location.hash);
        return m ? Number(m[1]) : null;
    })();
    /** seq → chunk 序 Pos（[data-chunk] 文档序页 + 顶分位 0）；
        晚到 dual（info 先渲）/seq 不在档 → null 落回 saved 恢复 */
    const deepSeqTarget = (): Pos | null => {
        if (deepSeq == null || props.view === "pdf") return null;
        const chunks = dual()?.chunks ?? [];
        const i = chunks.findIndex((c) => c.seq === deepSeq);
        return i >= 0 ? { page: i + 1, fraction: 0 } : null;
    };

    /** 跨任务回程票：#/reader/{id}?from={src}——chip 跳带来的源任务 id */
    const fromTask = (() => {
        const f = fromParamOf(window.location.hash);
        // eslint-disable-next-line solid/reactivity -- keyed Match 按 taskId 整树重挂，挂载拍快照是有意的
        return f && f !== props.taskId ? f : null;
    })();
    const returnToSrc = () => {
        if (fromTask) location.hash = `#/reader/${fromTask}`;
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
            // 深链优先于服务端恢复位——#/reader/{id}?seq=N 是显式意图
            const ds = deepSeqTarget();
            const saved = ds ? null : info()?.reading?.positions?.[side];
            const target = ds ?? saved;
            if (target) queueMicrotask(() => h.jump(target));
        } else if (engine?.syncing && side !== active()) {
            engine.alignNow(handles()[active()] ?? h);
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
            const otherSide = other(side);
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
        const otherSide = other(side);
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
            // 程序导航窗口内不重算 drift——cite 跳双侧同动，跳后 drift
            // 必是程序位移的假象（导航栈语义优先于漂移钮，§8-Q5 裁决）
            if (navHolds === 0) updateDrift();
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

    const HELP_ITEMS: [string, string][] = [
        ["1 / 2 / 3", t.reader.helpModes],
        ["4", t.reader.helpGuide],
        ["S", t.reader.helpSync],
        ["[ / ]", t.reader.helpPages],
        ["Ctrl+F", t.reader.helpFind],
        ["Backspace", t.reader.helpNavBack],
        ["Alt+←/→", t.reader.helpNavHist],
        ["V", t.reader.helpCursor],
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
                    apiRef={(a) => (barApi = a)}
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
