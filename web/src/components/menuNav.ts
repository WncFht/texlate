// menuNav —— ARIA menu 交互契约共享件：menuitem ↑↓/Home/End roving、
// Tab 顺走收菜单、外部 pointerdown 收、Escape 收+焦点回触发钮、触发钮
// ArrowDown 开菜单聚焦首项。Toolbar 下载菜单与 TaskList ↻ 重试菜单共用。

import { createEffect, onCleanup } from "solid-js";

const ITEMS = "[role='menuitem']";

/** menu 容器 onKeyDown：方向键/Home/End 在 menuitem 间循环聚焦；Tab 顺走收菜单 */
export function menuRoving(e: KeyboardEvent, onTab: () => void): void {
    const items = [
        ...(e.currentTarget as HTMLElement).querySelectorAll<HTMLElement>(
            ITEMS,
        ),
    ];
    if (!items.length) return;
    const idx = items.indexOf(document.activeElement as HTMLElement);
    let next: number;
    if (e.key === "ArrowDown") next = idx < 0 ? 0 : (idx + 1) % items.length;
    else if (e.key === "ArrowUp")
        next = idx <= 0 ? items.length - 1 : idx - 1;
    else if (e.key === "Home") next = 0;
    else if (e.key === "End") next = items.length - 1;
    else if (e.key === "Tab") {
        onTab();
        return;
    } else return;
    e.preventDefault();
    items[next]?.focus();
}

/**
 * 触发钮 onKeyDown：ArrowDown → open() 且菜单渲染后聚焦首项
 * （ARIA menu button 模式）；root 给菜单挂载容器。
 */
export function menuTriggerKey(
    e: KeyboardEvent,
    open: () => void,
    root: () => HTMLElement | undefined,
): void {
    if (e.key !== "ArrowDown") return;
    e.preventDefault();
    open();
    queueMicrotask(() =>
        root()?.querySelector<HTMLElement>(ITEMS)?.focus(),
    );
}

/**
 * dismiss 监听（须在组件作用域调用）：菜单打开时外部 pointerdown 收；
 * Escape 收且焦点回触发钮。监听只在 open() 期间挂——菜单从不打开的
 * 组件不再为 document 级 listener 付全生命周期成本。
 */
export function bindMenuDismiss(opts: {
    open(): boolean;
    close(): void;
    wrap(): HTMLElement | undefined;
    trigger(): HTMLElement | undefined;
}): void {
    createEffect(() => {
        if (!opts.open()) return;
        const onDown = (e: PointerEvent) => {
            const w = opts.wrap();
            if (w && !w.contains(e.target as Node)) opts.close();
        };
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") {
                opts.close();
                opts.trigger()?.focus();
            }
        };
        document.addEventListener("pointerdown", onDown);
        document.addEventListener("keydown", onKey);
        onCleanup(() => {
            document.removeEventListener("pointerdown", onDown);
            document.removeEventListener("keydown", onKey);
        });
    });
}
