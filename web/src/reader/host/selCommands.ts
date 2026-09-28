// host/selCommands —— sel-system 命令消费面：命中快照 snap + 依赖面
// depsFor + 划词浮条（itemsFor/onAction/observeEls）+ 右键菜单委托 ctxm +
// copy-latex lane + 键位命令路（runKeyCmd/openCiteAtFocus）。
//
// ctxm.snapshot 的 altAnchor/inScope/pdf 退化回补是实测修过的命中逻辑，
// 逐字保序。live-pane DOM 现查是架构妥协（LivePane 在 TaskProgress 内、
// 无 handle）——勿「顺手修复」。

import { onCleanup } from "solid-js";
import { api, type DualJson } from "../../api/client";
import type { DocId } from "../logic/alignment";
import type { NavStack } from "../logic/navstack";
import type { AnyHandle } from "../panes/PaneSlot";
import type { ReaderViewState } from "../logic/view";
import type { Registry } from "../cmd/cmdreg";
import { makeCmdCtx, type CmdCtx, type CmdDeps } from "../cmd/commands";
import { snapshotHit, type HitCtx, type PaneSide } from "../cmd/hitctx";
import { cmdLabel, menuItemsFor, useContextMenu } from "../chrome/ContextMenu";
import type { FloatBarApi, FloatBarItem } from "../chrome/FloatBar";
import { chunkUntranslated } from "../logic/markdown";
import type { CiteIndex } from "../cite/citations";
import { registerCopyLatex, type CopyLatexPane } from "../features/copylatex";
import { toast } from "../../stores/toastStore";
import { fmt, t } from "../../i18n";

export function createSelCommands(deps: {
    reg: Registry<CmdCtx>;
    handles(): Partial<Record<DocId, AnyHandle>>;
    sideOfHit(hit: HitCtx): DocId;
    bodyOf(side: DocId): HTMLElement | null;
    liveBodyEl(): HTMLElement | null;
    view(): ReaderViewState;
    taskId(): string;
    dual(): DualJson | null | undefined;
    seqOf(): Map<string, number>;
    citeIndex(): CiteIndex;
    navStacks: Record<DocId, NavStack>;
    navBack(side: DocId): void;
    navFwd(side: DocId): void;
    openMenuCard(hit: HitCtx): void;
    jumpToCite(hit: HitCtx): void;
    retxSeq(seq: number, hit: HitCtx): void;
    canRetranslate(): boolean;
    panesEl(): HTMLDivElement;
}) {
    const {
        reg,
        handles,
        sideOfHit,
        bodyOf,
        liveBodyEl,
        view,
        taskId,
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
        panesEl,
    } = deps;

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
                kind: view(),
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
        taskId: () => taskId(),
        panes: clPanes,
        dual: () => dual(),
        toastOk: (m) => toast.ok(m),
        toastErr: (m) => toast.err(m),
    });

    /** 在飞重译 seq 集——经 PaneSlot 与 HtmlPane 共享（hitctx
        chunk.pending 与按钮防抖读同一份才实时） */
    const retxPending = new Set<number>();
    /** FloatBar 控制器 + 最后一次 itemsFor 的 ctx（onAction 复用同快照） */
    let barApi: FloatBarApi | null = null;
    let barCtx: CmdCtx | null = null;

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
                    ? `${window.location.origin}${window.location.pathname}#/reader/${taskId()}?seq=${chunk.intSeq}`
                    : null,
            toastOk: (m) => toast.ok(m),
            toastErr: (m) => toast.err(m),
        };
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
        const out: (Element | null)[] = [panesEl()];
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
                    (panesEl().contains(el) || !!el.closest(".live-pane"));
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

    onCleanup(() => cl.dispose());

    return {
        retxPending,
        cl,
        ctxm,
        barItemsFor,
        barAction,
        barObserveEls,
        barApiRef: (a: FloatBarApi | null) => {
            barApi = a;
        },
        runKeyCmd,
        openCiteAtFocus,
    };
}
