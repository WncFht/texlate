// features/findusages —— find-usages lane 交互层（fu-popover-spike
// FigPane 委托/时序的产品化移植，pane 无关）。
//
//   registerFindUsages(reg, opts) —— 右键菜单 cite.usages 命令
//       （when=cite.targetExists，sec=cite；run 经 opts.open 出口——
//       宿主把 hit.cite.targetEl/targetId+anchorEl 转成 pane 开卡）。
//   attachUsages(pane, deps) —— pane 内三触发委托 + ADR-0021 时序：
//       hover dwell 150ms / tap 点击 / contextmenu（直开卡，拦 ctxm）/
//       :focus-visible 键盘开卡；关卡宽限 350ms、scrollGrace 600ms、
//       Esc 还焦点 suppressFocusOpenFor 一次性旗标、Tab 直送卡内首项。
//
// 唤起面门限（spec 唤起面表）：
//   hover/tap/focus 仅进 figure|table|bib（eq/sec/thm 入链稀——
//   eq 21%/sec 28%，强入口不值，仅 contextmenu/菜单到）；contextmenu
//   全类。锚元素（a[href^='#']/.cite-ref/.ltx_cite）一律让行——cite
//   卡/跳转/ctxm 菜单各保语义，usages 不抢。
//
// 卡渲染在宿主：ctl 只产 UsagesOpen 载荷经 deps.open 上抛，宿主把信号
// 喂给 <UsagesCard>（onCardEnter/onCardLeave 回接 ctl 续命，onClose→
// ctl.close(true) 走 Esc 还焦通路）。

import type { Command, Registry } from "../cmd/cmdreg";
import type { CmdCtx } from "../cmd/commands";
import { fillPairZh, type UsageEntry, type UsageIndex } from "../cite/usages";

const OPEN_DELAY = 150;
const CLOSE_DELAY = 350;
/** 开卡后滚动宽限——tap/focus 引发的程序滚不当用户滚杀卡 */
const SCROLL_GRACE = 600;

// ------------------------------------------------------------------ 命令

export interface FindUsagesOpts {
    /** cite.usages 执行出口：宿主按 hit.cite 解析 pane 并开卡
        （dom: paneHandle.openUsagesFor(targetEl ?? targetId, anchorEl)）。
        缺省 → 命令可见但静默 no-op（谓词兜底安全）。 */
    open?(c: CmdCtx): void;
}

/** 注册 cite.usages（幂等——重挂先摘同名）。返回 reg 供链式。 */
export function registerFindUsages(
    reg: Registry<CmdCtx>,
    opts: FindUsagesOpts = {},
): Registry<CmdCtx> {
    if (reg.get("cite.usages")) reg.unregister("cite.usages");
    const cmd: Command<CmdCtx> = {
        id: "cite.usages",
        title: "menu.cite.usages",
        sec: "cite",
        // other 桶（page.N/Doc-Start/Item.N）不出「查找引用」——那些是
        // 页码/杂链非学术引用；bib/figure/table/equation/section/theorem 全收
        when: "cite.targetExists && cite.targetKind != 'other'",
        run: (c) => opts.open?.(c),
    };
    reg.register(cmd);
    return reg;
}

// ------------------------------------------------------------------ 委托

/** 宿主 pane 最小面——scrollEl/focus/scroll 委托挂点 */
export interface UsagesPaneLike {
    /** 滚动容器（scrollEl：scroll/focusin/focusout/keydown 挂点） */
    el: HTMLElement;
    bodyEl(): HTMLElement;
}

/** 索引供给面——UsageIndex 天然满足；html 臂可给 cite-map 适配源 */
export interface UsagesSource {
    forEl(el: Element | null): UsageEntry | undefined;
    forId(id: string): UsageEntry | undefined;
}

export interface UsagesOpen {
    /** 卡锚 rect（figcaption 优先 + 视口夹取已完成） */
    rect: { left: number; right: number; top: number; bottom: number };
    entry: UsageEntry;
    /** 触发元素——Esc 关卡的还焦点目标 */
    trigger: HTMLElement;
    via: "hover" | "tap" | "contextmenu" | "focus" | "command";
}

export interface UsagesDeps {
    /** 本侧索引（懒取——load() 完成后才有值） */
    source(): UsagesSource | undefined;
    /** 开卡载荷出口 */
    open(p: UsagesOpen): void;
    /** 关卡出口（宿主清信号；timers/还焦点 ctl 自管） */
    close(): void;
    /** 开卡前哨——宿主清互斥卡（CiteCard） */
    onWillOpen?(): void;
    /** zh 配对索引（dom 臂跨 pane 对）——缺席=不配 zh 行 */
    pairIndex?(): UsageIndex | undefined;
}

export interface UsagesCtl {
    /** 命令/外部开卡路：目标元素或目标 id；anchor 给卡锚位 */
    openFor(target: Element | string | null, anchor?: Element | null): boolean;
    /** 关卡；refocus=true 走 Esc 还焦通路（suppressFocusOpenFor 防复开） */
    close(refocus?: boolean): void;
    /** 宿主卡 hoverable 续命回接 */
    cardEnter(): void;
    cardLeave(): void;
    isOpen(): boolean;
    /** figure/table/.ltx_bibitem 注 tabindex=0（内容落地后调） */
    armTargets(root: HTMLElement): void;
    dispose(): void;
}

/** hover/tap/focus 强入口只放浮动体+文献条目（eq/sec/thm 仅右键） */
const HOVERABLE = new Set<UsageEntry["target"]["kind"]>([
    "figure",
    "table",
    "bib",
]);

/** 触屏 tap 放宽集——指针设备 tap 无 ⌘-Inspect 等价物，eq/thm 的 tap
    归 usages 开卡（section 仍拒：全节容器祖先爬升误吸太宽） */
const TAPABLE = new Set<UsageEntry["target"]["kind"]>([
    "figure",
    "table",
    "bib",
    "equation",
    "theorem",
]);

export function attachUsages(
    pane: UsagesPaneLike,
    deps: UsagesDeps,
): UsagesCtl {
    let openTimer = 0;
    let closeTimer = 0;
    let curHost: HTMLElement | null = null;
    let curTrigger: HTMLElement | null = null;
    let cardOpen = false;
    let scrollGraceUntil = 0;
    // 最近一手是触屏点按——click 的 TAPABLE 放宽判据（pointerdown capture
    // 快照；键盘 focus/程序派发 click 不吃放宽）
    let lastTouch = false;
    // Esc 还焦点抑制旗：浏览器把「键盘输入后的程序 focus()」也判
    // :focus-visible（Chromium/Firefox 双引擎实测）——不抑制则 Esc 关卡后
    // focusin 立刻复开。一次性：下一个 focusin（无论目标）消费掉。
    let suppressFocusOpenFor: HTMLElement | null = null;

    const clearCardTimers = () => {
        window.clearTimeout(openTimer);
        window.clearTimeout(closeTimer);
        openTimer = closeTimer = 0;
    };

    const doClose = (refocus = false) => {
        clearCardTimers();
        const trig = curTrigger;
        curTrigger = null;
        curHost = null;
        if (!cardOpen) return;
        cardOpen = false;
        deps.close();
        // Esc 关卡通路：焦点还给触发元素——preventScroll 防还焦点滚动
        // 复活 hover 路径（spike 缺陷 2：focus() 默认 scrollIntoView 把
        // 内容移位到静止指针下 → pointerover 重命中 → 关卡被复活）。
        if (
            refocus &&
            trig &&
            trig.isConnected &&
            trig !== document.activeElement
        ) {
            suppressFocusOpenFor = trig;
            trig.focus({ preventScroll: true });
        }
    };

    /** 卡锚 rect：figcaption 优先（巨型 figure 包围盒底部常出视口）。
        夹入视口——1900px 浮动体滚动中段时两头都不在屏内，不夹则卡渲
        0 可见像素（spike 缺陷 1 修复）。 */
    const anchorRect = (host: HTMLElement) => {
        const cap = host.querySelector("figcaption");
        const r = (cap ?? host).getBoundingClientRect();
        const vh = window.innerHeight;
        const top = Math.min(Math.max(r.top, 0), vh);
        const bottom = Math.min(Math.max(r.bottom, top), vh);
        return { left: r.left, right: r.right, top, bottom };
    };

    const fire = (
        entry: UsageEntry,
        trigger: HTMLElement,
        rect: UsagesOpen["rect"],
        via: UsagesOpen["via"],
    ) => {
        deps.onWillOpen?.();
        // 滞留的 armClose 必须在显式开前清算——否则序列为「焦点迁出旧
        // 触发元(armClose 排程)→mousedown 新目标→click 开卡」时，旧定时
        // 器到点把刚开的卡杀掉（⌘-Inspect 实测：Esc 还焦的 cite 触发元
        // focusout→armClose，350ms 后吞掉 inspect 开的 usages 卡）
        window.clearTimeout(closeTimer);
        closeTimer = 0;
        curHost = entry.target.el ?? null;
        curTrigger = trigger;
        scrollGraceUntil = performance.now() + SCROLL_GRACE;
        cardOpen = true;
        fillPairZh(entry, deps.pairIndex?.());
        deps.open({ rect, entry, trigger, via });
    };

    /** 事件目标 → 可索引条目（上爬首个带索引 id 祖先） */
    const entryOf = (t: EventTarget | null): UsageEntry | undefined =>
        deps.source()?.forEl(t as Element | null);

    const armOpen = (fn: () => void) => {
        window.clearTimeout(openTimer);
        openTimer = window.setTimeout(() => {
            openTimer = 0; // 发后即清零——同锚复悬才能再武装
            fn();
        }, OPEN_DELAY);
    };
    const armClose = () => {
        window.clearTimeout(closeTimer); // 重入必须撤旧定时器
        closeTimer = window.setTimeout(() => doClose(), CLOSE_DELAY);
    };

    /** 锚/引用链面让行：cite 卡 + 跳转 + ctxm 各保语义 */
    const onAnchor = (t: EventTarget | null): boolean =>
        (t as Element | null)?.closest?.("a") != null ||
        (t as Element | null)?.closest?.(".cite-ref, .ltx_cite") != null;

    const onOver = (e: PointerEvent) => {
        if (e.pointerType === "touch") return;
        if (onAnchor(e.target)) return;
        const entry = entryOf(e.target);
        const host = entry?.target.el ?? null;
        if (!entry || !host || !HOVERABLE.has(entry.target.kind)) return;
        if (host === curHost) {
            // 同目标复悬只续不关；卡未开且定时器已逝要补武装
            window.clearTimeout(closeTimer);
            if (!cardOpen && !openTimer)
                armOpen(() => {
                    if (!entry.target.el?.isConnected) return;
                    fire(
                        entry,
                        entry.target.el,
                        anchorRect(entry.target.el),
                        "hover",
                    );
                });
            return;
        }
        clearCardTimers();
        curHost = host;
        armOpen(() => {
            if (!host.isConnected) return;
            fire(entry, host, anchorRect(host), "hover");
        });
    };
    const onOut = (e: PointerEvent) => {
        const rel = e.relatedTarget as Element | null;
        if (rel?.closest?.(".usage-card")) return;
        // 宿主内部子节点间移动（img↔caption）不出关卡
        const from = entryOf(e.target)?.target.el ?? null;
        const to = rel ? (entryOf(rel)?.target.el ?? null) : null;
        if (from && from === to) return;
        if (from || cardOpen) {
            window.clearTimeout(openTimer);
            armClose();
        }
    };
    const onClick = (e: MouseEvent) => {
        if ((e.target as Element | null)?.closest?.(".usage-card")) return;
        if (onAnchor(e.target)) {
            // 点击引用锚——cite/跳成语义在宿主；usages 卡开着则收
            if (cardOpen) doClose();
            return;
        }
        const entry = entryOf(e.target);
        const host = entry?.target.el ?? null;
        const kindOk =
            entry != null &&
            (HOVERABLE.has(entry.target.kind) ||
                (lastTouch && TAPABLE.has(entry.target.kind)));
        if (!entry || !host || !kindOk) {
            if (cardOpen) doClose(); // 点正文空白即收卡
            return;
        }
        // tap/点击浮动体或文献条目=立即开卡（同锚复点不关）
        fire(entry, host, anchorRect(host), "tap");
    };
    const onContextMenu = (e: MouseEvent) => {
        if (e.shiftKey) return; // ctxm 同款 bypass——power user 原生菜单
        if (onAnchor(e.target)) return; // cite 锚走 ctxm 菜单（cite.usages）
        const entry = entryOf(e.target);
        const host = entry?.target.el ?? null;
        if (!entry || !host) return;
        // 浮动体/eq/sec/thm 右键直开卡——拦 ctxm（preventDefault+
        // stopPropagation 双断，.panes 上的菜单委托收不到）
        e.preventDefault();
        e.stopPropagation();
        fire(entry, host, anchorRect(host), "contextmenu");
    };
    const onFocusIn = (e: FocusEvent) => {
        const t = e.target as HTMLElement | null;
        if (suppressFocusOpenFor) {
            const s = suppressFocusOpenFor;
            suppressFocusOpenFor = null; // 一次性消费
            if (t === s) return; // 程序还焦点——不当作键盘到达
        }
        if (onAnchor(t)) return;
        const entry = entryOf(t);
        const host = entry?.target.el ?? null;
        if (!entry || !host || !HOVERABLE.has(entry.target.kind)) return;
        if (!(t instanceof HTMLElement) || !t.matches(":focus-visible")) return; // 指针点击引发的 focus 不出卡
        fire(entry, host, anchorRect(host), "focus");
    };
    const onFocusOut = (e: FocusEvent) => {
        const rel = e.relatedTarget as Element | null;
        if (rel?.closest?.(".usage-card")) return;
        if (!entryOf(e.target) && !cardOpen) return;
        armClose();
    };
    // 卡 DOM 序远离触发元——触发元上 Tab 直接把焦点送进卡内首项
    const onKeyDown = (e: KeyboardEvent) => {
        if (e.key !== "Tab" || e.shiftKey) return;
        if (!cardOpen || document.activeElement !== curTrigger) return;
        const el = pane.el.querySelector<HTMLElement>(
            ".usage-card button, .usage-card a[href]",
        );
        if (!el) return;
        e.preventDefault();
        el.focus();
    };
    const onScroll = () => {
        if (cardOpen && performance.now() >= scrollGraceUntil) doClose();
    };

    const bodyEl = pane.bodyEl();
    const onPointerDown = (e: Event) => {
        lastTouch = (e as PointerEvent).pointerType === "touch";
    };
    bodyEl.addEventListener("pointerdown", onPointerDown, true);
    bodyEl.addEventListener("pointerover", onOver);
    bodyEl.addEventListener("pointerout", onOut);
    bodyEl.addEventListener("click", onClick);
    bodyEl.addEventListener("contextmenu", onContextMenu);
    pane.el.addEventListener("focusin", onFocusIn);
    pane.el.addEventListener("focusout", onFocusOut);
    pane.el.addEventListener("keydown", onKeyDown);
    pane.el.addEventListener("scroll", onScroll, { passive: true });

    return {
        openFor(target, anchor) {
            const src = deps.source();
            if (!src) return false;
            const entry =
                typeof target === "string"
                    ? src.forId(target)
                    : src.forEl(target);
            if (!entry) return false;
            const host = entry.target.el;
            const a = anchor as HTMLElement | null;
            const rect = a?.isConnected
                ? (() => {
                      const r =
                          a.getClientRects()[0] ?? a.getBoundingClientRect();
                      const vh = window.innerHeight;
                      const top = Math.min(Math.max(r.top, 0), vh);
                      return {
                          left: r.left,
                          right: r.right,
                          top,
                          bottom: Math.min(Math.max(r.bottom, top), vh),
                      };
                  })()
                : host?.isConnected
                  ? anchorRect(host)
                  : null;
            if (!rect) return false;
            fire(entry, a?.isConnected ? a : (host ?? a)!, rect, "command");
            return true;
        },
        close: doClose,
        cardEnter() {
            window.clearTimeout(closeTimer);
        },
        cardLeave() {
            window.clearTimeout(closeTimer);
            closeTimer = window.setTimeout(() => doClose(), CLOSE_DELAY);
        },
        isOpen: () => cardOpen,
        armTargets(root) {
            for (const el of root.querySelectorAll<HTMLElement>(
                "figure, .ltx_bibitem",
            ))
                if (el.tabIndex < 0) el.tabIndex = 0;
            // ⌘-Inspect 揭示预标：可索引目标宿主全量 .insp-t——armed 期纯
            // CSS 出描边（eq/sec/thm 的「可检视」提示无他途）
            const src = deps.source() as { entries?: UsageEntry[] } | undefined;
            for (const e of src?.entries ?? []) {
                const el = e.target.el;
                if (el && root.contains(el)) el.classList.add("insp-t");
            }
        },
        dispose() {
            clearCardTimers();
            bodyEl.removeEventListener("pointerdown", onPointerDown, true);
            bodyEl.removeEventListener("pointerover", onOver);
            bodyEl.removeEventListener("pointerout", onOut);
            bodyEl.removeEventListener("click", onClick);
            bodyEl.removeEventListener("contextmenu", onContextMenu);
            pane.el.removeEventListener("focusin", onFocusIn);
            pane.el.removeEventListener("focusout", onFocusOut);
            pane.el.removeEventListener("keydown", onKeyDown);
            pane.el.removeEventListener("scroll", onScroll);
        },
    };
}
