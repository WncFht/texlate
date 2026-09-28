// ContextMenu —— 自定义右键菜单（exp/ss-ctxmenu/ContextMenu.tsx 移植落地）。
// 行为锁定项（spike 实证矩阵，逐行对应）：
//  * contextmenu 拦截 + 选区快照 → Portal→body fixed（pane 内 transform/
//    overflow 不咬 fixed）→ placeMenu/placeSubmenu 视口钳位翻边。
//  * 子菜单 hover-intent 150ms 开 / 300ms 斜移宽限关；DOM 嵌在父项 li 内
//    （pointerleave 白捡 hover 通道，免三角算法）；ArrowRight 进
//    ArrowLeft 出；递归 MenuLevel。
//  * 关单三通道：Esc(capture+stopImmediatePropagation——抢先于 document
//    已注册 bubble 阶 Esc) / 外点 pointerdown / scroll capture；回焦开单
//    前焦点；开单期恰好 3 个 document 监听。
//  * 两处已修缺陷保留（勿回退）：
//    (a) 本层处理过的 nav 键一律 stopPropagation——子菜单 ul 是父 li 后代，
//        keydown 沿 DOM 上冒会再过一遍祖先 ul 委托；
//    (b) 垂直换轨（ArrowUp/Down/Home/End）同步 setSubIdx(-1)——键盘移到
//        兄弟项=本层子菜单失焦，不留 stale-open + aria-expanded 残影。
// 落地增量（spike 之上）：
//  * CtxOpen 扩展 hit?/cmd? —— 宿主在 snapshot() 里挂 hitctx/cmdctx 快照；
//  * opts.bypass —— Shift+右键放出原生菜单；
//  * opts.onOpen/onClose —— FloatBar 互斥闸 + Esc 栈记账；
//  * menuItemsFor —— cmdreg → CtxItem[] 桥（SECTION_ORDER 分段插 sep，
//    enableWhen → disabled 不 hidden，title 走 i18n t-path 解析）。

import { createSignal, For, onCleanup, onMount, Show } from "solid-js";
import { Portal } from "solid-js/web";
import { currentLang, tPath } from "../i18n";
import type { Command, Registry } from "./cmd/cmdreg";
import { MENU_LABELS, SECTION_ORDER, type CmdCtx } from "./cmd/commands";
import type { HitCtx } from "./cmd/hitctx";

/** 菜单贴视口的边距 / 首帧估宽 / 单项估高（onMount 前防出屏用） */
export const MENU_MARGIN = 4;
const EST_W = 220;
const ITEM_H = 28;

/** 子菜单开合节拍：150ms 开（hover-intent 防抖）/ 300ms 关（斜移宽限） */
export const SUB_OPEN_DELAY = 150;
export const SUB_CLOSE_DELAY = 300;

/** 开单快照——contextmenu 事件时刻的指针位 / 选中文本 / 目标元素。
    hit/cmd 由宿主 snapshot() 扩展挂上（hitctx 快照 + 谓词扁平袋）。 */
export interface CtxOpen {
    x: number;
    y: number;
    selection: string;
    target: EventTarget | null;
    /** 宿主注入：命中语境快照（snapshotHit 产物） */
    hit?: HitCtx;
    /** 宿主注入：命令上下文（makeCmdCtx 产物——菜单项 action 的 ctx） */
    cmd?: CmdCtx;
}

export interface CtxItem {
    id: string;
    label?: string;
    hint?: string;
    disabled?: boolean;
    checked?: boolean;
    danger?: boolean;
    sep?: boolean;
    children?: CtxItem[];
    action?(o: CtxOpen): void;
}

export interface Placed {
    left: number;
    top: number;
    flipX: boolean;
    flipY: boolean;
}

const estH = (items: CtxItem[]) => items.length * ITEM_H + 10;

const vw = () => window.innerWidth;
const vh = () => window.innerHeight;

/**
 * 一级菜单落点：默认光标右下展开；右/下放不下→翻到光标另一侧；
 * 翻完仍出界（菜单比光标侧空间还宽）→ 硬钳回视口。
 * 不变式（fuzz 验证）：w+2m<=vw 且 h+2m<=vh 时结果必落 [m, vw-w-m]×[m, vh-h-m]。
 */
export function placeMenu(
    x: number,
    y: number,
    w: number,
    h: number,
    vw_: number,
    vh_: number,
    m = MENU_MARGIN,
): Placed {
    let left = x;
    let top = y;
    let flipX = false;
    let flipY = false;
    if (x + w + m > vw_) {
        left = x - w;
        flipX = true;
    }
    if (y + h + m > vh_) {
        top = y - h;
        flipY = true;
    }
    left = Math.min(Math.max(m, left), Math.max(m, vw_ - w - m));
    top = Math.min(Math.max(m, top), Math.max(m, vh_ - h - m));
    return { left, top, flipX, flipY };
}

export interface AnchorRect {
    left: number;
    top: number;
    right: number;
    bottom: number;
}

/**
 * 子菜单落点：贴父项右缘（-2px 重叠消 1px 缝），右溢出→翻父项左侧；
 * 顶对齐父项（-4 抵消 menu padding），下溢出→上收，再硬钳。
 */
export function placeSubmenu(
    a: AnchorRect,
    w: number,
    h: number,
    vw_: number,
    vh_: number,
    m = MENU_MARGIN,
): Placed {
    let left = a.right - 2;
    let top = a.top - 4;
    let flipX = false;
    if (left + w + m > vw_) {
        left = a.left - w + 2;
        flipX = true;
    }
    if (top + h + m > vh_) top = vh_ - h - m;
    left = Math.min(Math.max(m, left), Math.max(m, vw_ - w - m));
    top = Math.max(m, top);
    return { left, top, flipX, flipY: false };
}

const ENABLED = ":scope > li[role='menuitem']:not([aria-disabled='true'])";

interface LevelProps {
    items: CtxItem[];
    open: CtxOpen;
    onClose(): void;
    /** 首帧估算落点 + onMount 实测重放共用（传入时固化锚/点） */
    place(w: number, h: number): Placed;
    sub?: boolean;
    onArrowLeft?(): void;
    /** 子菜单 ul 自身 pointerenter——通知父级取消排定的关闭计时 */
    onSubEnter?(): void;
    autofocus?: boolean;
}

function MenuLevel(props: LevelProps) {
    let ul!: HTMLUListElement;
    // eslint-disable-next-line solid/reactivity -- 菜单位置是开菜单那拍的快照，不随 props 重排
    const [pos, setPos] = createSignal(props.place(EST_W, estH(props.items)));
    const [subIdx, setSubIdx] = createSignal(-1);
    const [anchor, setAnchor] = createSignal<AnchorRect | null>(null);
    let subLi: HTMLElement | undefined;
    let openT = 0;
    let closeT = 0;
    const clearT = () => {
        clearTimeout(openT);
        clearTimeout(closeT);
    };
    onCleanup(clearT);

    onMount(() => {
        // 实测重排：估算位只是首帧防出屏，真宽/高出来后重放同一 place
        setPos(props.place(ul.offsetWidth, ul.offsetHeight));
        if (props.autofocus)
            queueMicrotask(() =>
                ul.querySelector<HTMLElement>(ENABLED)?.focus(),
            );
    });

    // 根级专享：Esc/外点/滚动监听仅开单期挂（bindMenuDismiss 同构成本面）
    onMount(() => {
        if (props.sub) return;
        const onKeyDoc = (e: KeyboardEvent) => {
            if (e.key !== "Escape") return;
            // capture+stopImmediatePropagation：抢先于 document 上已注册的
            // bubble 阶 Esc（ReaderView keymap 等）——见 FindBar 实证注释
            e.stopImmediatePropagation();
            props.onClose();
        };
        const onDown = (e: Event) => {
            if (!ul.contains(e.target as Node)) props.onClose();
        };
        // 右键把焦点锚 scrollIntoView——开单后 ~100ms 才落的程序化 scroll
        // 非用户滚动，无差别关单=即开即杀（实证 ~104ms）；宽限外真人滚动
        // 照常即关
        const t0 = performance.now();
        const onScroll = () => {
            if (performance.now() - t0 < 250) return;
            props.onClose();
        };
        document.addEventListener("keydown", onKeyDoc, true);
        document.addEventListener("pointerdown", onDown);
        // scroll 不冒泡——capture 才能兜住 pane 内滚动容器（DomPane/HtmlPane）
        document.addEventListener("scroll", onScroll, {
            capture: true,
            passive: true,
        });
        onCleanup(() => {
            document.removeEventListener("keydown", onKeyDoc, true);
            document.removeEventListener("pointerdown", onDown);
            document.removeEventListener("scroll", onScroll, {
                capture: true,
            });
        });
    });

    const openSub = (i: number, li: HTMLElement, immediate: boolean) => {
        clearT();
        const go = () => {
            subLi = li;
            setAnchor(li.getBoundingClientRect());
            setSubIdx(i);
        };
        if (immediate) go();
        else openT = window.setTimeout(go, SUB_OPEN_DELAY);
    };
    const closeSubSoon = () => {
        clearT();
        closeT = window.setTimeout(() => setSubIdx(-1), SUB_CLOSE_DELAY);
    };

    const pick = (it: CtxItem) => {
        it.action?.(props.open);
        props.onClose();
    };

    const onKey = (e: KeyboardEvent) => {
        const rows = [...ul.querySelectorAll<HTMLElement>(ENABLED)];
        const idx = rows.indexOf(document.activeElement as HTMLElement);
        const li = idx >= 0 ? rows[idx] : undefined;
        const it = li ? props.items[Number(li.dataset.i)] : undefined;
        const focusRow = (n: number) => rows[n]?.focus();
        // 本层处理过的键一律 stopPropagation——子菜单 ul 是父 li 的后代，
        // keydown 沿 DOM 上冒会逐个祖先 ul 再过一遍本委托（cancelBubble 截
        // 断 walkUpTree）；不截的话子菜单内 ArrowDown 会被根级重排到首项。
        // 垂直换轨同步 setSubIdx(-1)：键盘移到兄弟项=本层子菜单失焦，与
        // pointerenter 换轨同义，不留 stale-open + aria-expanded 残影。
        switch (e.key) {
            case "ArrowDown":
                e.preventDefault();
                e.stopPropagation();
                setSubIdx(-1);
                focusRow(idx < 0 ? 0 : (idx + 1) % rows.length);
                return;
            case "ArrowUp":
                e.preventDefault();
                e.stopPropagation();
                setSubIdx(-1);
                focusRow(idx <= 0 ? rows.length - 1 : idx - 1);
                return;
            case "Home":
                e.preventDefault();
                e.stopPropagation();
                setSubIdx(-1);
                focusRow(0);
                return;
            case "End":
                e.preventDefault();
                e.stopPropagation();
                setSubIdx(-1);
                focusRow(rows.length - 1);
                return;
            case "ArrowRight":
                if (li && it?.children) {
                    e.preventDefault();
                    e.stopPropagation();
                    openSub(Number(li.dataset.i), li, true);
                    queueMicrotask(() =>
                        li
                            .querySelector<HTMLElement>(
                                ":scope > .ctx-sub " + ENABLED.slice(7),
                            )
                            ?.focus(),
                    );
                }
                return;
            case "ArrowLeft":
                if (props.sub && props.onArrowLeft) {
                    e.preventDefault();
                    e.stopPropagation(); // 别让父级 ul 的委托处理重复吃
                    props.onArrowLeft();
                }
                return;
            case "Enter":
            case " ":
                if (li) {
                    e.preventDefault();
                    e.stopPropagation();
                    li.click();
                }
                return;
            case "Tab":
                props.onClose();
                return;
        }
    };

    return (
        <ul
            ref={(n) => (ul = n)}
            class={props.sub ? "ctx-menu ctx-sub" : "ctx-menu"}
            role="menu"
            style={{ left: `${pos().left}px`, top: `${pos().top}px` }}
            onKeyDown={onKey}
            onPointerEnter={() => props.onSubEnter?.()}
            on:contextmenu={(e) => e.preventDefault()}
        >
            <For each={props.items}>
                {(it, i) =>
                    it.sep ? (
                        <li role="separator" class="ctx-sep" />
                    ) : (
                        <li
                            role="menuitem"
                            tabIndex={-1}
                            data-i={i()}
                            data-id={it.id}
                            classList={{
                                "ctx-item": true,
                                danger: !!it.danger,
                            }}
                            aria-disabled={it.disabled || undefined}
                            aria-haspopup={it.children ? "menu" : undefined}
                            aria-expanded={
                                it.children ? subIdx() === i() : undefined
                            }
                            onPointerEnter={(e) => {
                                if (it.disabled || !it.children) {
                                    // 兄弟项：开着谁关谁（原生菜单语义=即时换轨）
                                    clearT();
                                    setSubIdx(-1);
                                    return;
                                }
                                clearT();
                                openSub(i(), e.currentTarget, false);
                            }}
                            onPointerLeave={(e) => {
                                // 进嵌套子菜单不触发本 li 的 leave（子孙算内部）
                                if (
                                    subIdx() === i() &&
                                    !e.currentTarget.contains(
                                        e.relatedTarget as Node | null,
                                    )
                                )
                                    closeSubSoon();
                            }}
                            onClick={(e) => {
                                if (it.disabled) return;
                                if (it.children) {
                                    if (subIdx() === i()) setSubIdx(-1);
                                    else openSub(i(), e.currentTarget, true);
                                } else pick(it);
                            }}
                        >
                            <span class="ctx-check">
                                {it.checked ? "✓" : ""}
                            </span>
                            <span class="ctx-label">{it.label}</span>
                            <Show when={it.hint}>
                                <kbd class="ctx-hint">{it.hint}</kbd>
                            </Show>
                            <Show when={it.children}>
                                <span class="ctx-sub-arrow">▸</span>
                            </Show>
                            <Show when={it.children && subIdx() === i()}>
                                <MenuLevel
                                    sub
                                    items={it.children ?? []}
                                    open={props.open}
                                    onClose={props.onClose}
                                    place={(w, h) =>
                                        placeSubmenu(
                                            anchor()!,
                                            w,
                                            h,
                                            vw(),
                                            vh(),
                                        )
                                    }
                                    onArrowLeft={() => {
                                        setSubIdx(-1);
                                        queueMicrotask(() => subLi?.focus());
                                    }}
                                    onSubEnter={clearT}
                                />
                            </Show>
                        </li>
                    )
                }
            </For>
        </ul>
    );
}

/**
 * 右键菜单本体——Portal→body 挂载（pane 内 transform/overflow 不咬 fixed）。
 * 复开单=重挂载（宿主侧 Show keyed 保证），position 随 props.open 快照。
 */
export default function ContextMenu(props: {
    open: CtxOpen;
    items: CtxItem[];
    onClose(): void;
    autofocus?: boolean;
}) {
    return (
        <Portal>
            <MenuLevel
                items={props.items}
                open={props.open}
                onClose={props.onClose}
                autofocus={props.autofocus ?? true}
                place={(w, h) =>
                    placeMenu(props.open.x, props.open.y, w, h, vw(), vh())
                }
            />
        </Portal>
    );
}

export interface CtxMenuOpts {
    /** 开单快照扩展——宿主在此挂 hitctx/cmdctx；返回 null =  veto
        （不拦默认、不开单，原生菜单照常） */
    snapshot?(e: MouseEvent, base: CtxOpen): Partial<CtxOpen> | null;
    /** 返回 true → 完全放行（Shift+右键 = 原生菜单） */
    bypass?(e: MouseEvent): boolean;
    /** 开单后回调（FloatBar 互斥：菜单开时浮条收） */
    onOpen?(o: CtxOpen): void;
    /** 关单回调（Esc/外点/滚动/选取/host close 全通道汇此） */
    onClose?(): void;
}

/**
 * 宿主钩子：容器挂 on:contextmenu={ctx.onContextMenu}（.panes 级委托——
 * pane 重渲染免重绑），视图层放 {ctx.menu()}。开单时快照
 * getSelection() 文本（空的照样开——项可自行 disabled）；关单回焦
 * 开单前焦点（Esc/点选同路）。
 */
export function useContextMenu(
    build: (o: CtxOpen) => CtxItem[],
    opts: CtxMenuOpts = {},
) {
    const [o, setO] = createSignal<CtxOpen | null>(null);
    let prev: Element | null = null;
    const onContextMenu = (e: MouseEvent) => {
        if (opts.bypass?.(e)) return; // Shift+右键 → 原生菜单
        const base: CtxOpen = {
            x: e.clientX,
            y: e.clientY,
            selection: window.getSelection()?.toString() ?? "",
            target: e.target,
        };
        const ext = opts.snapshot?.(e, base);
        if (ext === null) return; // 宿主 veto——不拦默认行为
        e.preventDefault();
        prev = document.activeElement;
        const next = { ...base, ...ext };
        setO(next);
        opts.onOpen?.(next);
    };
    const close = () => {
        if (o() === null) return; // 幂等——重复关单不重复回焦/回调
        setO(null);
        (prev as HTMLElement | null)?.focus?.();
        prev = null;
        opts.onClose?.();
    };
    const menu = () => (
        <Show when={o()} keyed>
            {(v) => <ContextMenu open={v} items={build(v)} onClose={close} />}
        </Show>
    );
    return { onContextMenu, menu, close, isOpen: () => o() !== null };
}

// ---------------------------------------------------------------- cmdreg 桥

/** 命令显示名：title 作 i18n key 解析 → MENU_LABELS 镜像 → id 兜底。 */
export function cmdLabel(c: { id: string; title: string }): string {
    const hit = tPath(c.title);
    if (hit) return hit;
    const mirror = MENU_LABELS[c.id];
    if (mirror) return mirror[currentLang()];
    return c.id;
}

export interface MenuBuildOpts {
    /** 命令 → 显示名覆写（动态文案——cite.jump 按 targetKind 换词） */
    label?(cmd: Command<CmdCtx>, ctx: CmdCtx): string | undefined;
    /** 命令 → hint 覆写；缺省取 cmd.keys[0] */
    hint?(cmd: Command<CmdCtx>, ctx: CmdCtx): string | undefined;
    /** run 抛错出口（action 已 catch——Promise rejection 不外溢） */
    onError?(cmd: Command<CmdCtx>, err: unknown): void;
}

/**
 * Registry + CmdCtx → CtxItem[]：visible 集按 SECTION_ORDER 分段、段间插
 * sep；enableWhen 不过 → disabled（不 hidden——menu-spec chunk.retx 语义）；
 * action = runUnchecked + onError 兜底。未列入 SECTION_ORDER 的 sec 按注册
 * 序追加在尾段之后。
 */
export function menuItemsFor(
    reg: Registry<CmdCtx>,
    ctx: CmdCtx,
    opts: MenuBuildOpts = {},
): CtxItem[] {
    const vis = reg.visible(ctx);
    if (!vis.length) return [];
    const groups = new Map<string, Command<CmdCtx>[]>();
    for (const c of vis) {
        const sec = c.sec ?? "";
        const g = groups.get(sec);
        if (g) g.push(c);
        else groups.set(sec, [c]);
    }
    const orderedSecs = [
        ...SECTION_ORDER.filter((s) => groups.has(s)),
        ...[...groups.keys()].filter(
            (s) => !(SECTION_ORDER as readonly string[]).includes(s),
        ),
    ];
    const items: CtxItem[] = [];
    let gi = 0;
    for (const sec of orderedSecs) {
        if (gi++ > 0) items.push({ id: `sep-${sec}`, sep: true });
        for (const c of groups.get(sec)!) {
            items.push({
                id: c.id,
                label: opts.label?.(c, ctx) ?? cmdLabel(c),
                hint: opts.hint?.(c, ctx) ?? c.keys?.[0],
                disabled: !reg.isEnabled(c, ctx),
                action: () => {
                    void reg
                        .runUnchecked(c.id, ctx)
                        .catch((e) => opts.onError?.(c, e));
                },
            });
        }
    }
    return items;
}
