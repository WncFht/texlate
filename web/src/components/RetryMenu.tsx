// RetryMenu —— ↻ 重试迷你菜单：TaskList 行内重试臂的引擎选择子项。
// 自 TaskList.tsx 拆出（组件抽取）。

import { For } from "solid-js";
import { bindMenuDismiss, menuRoving } from "./menuNav";
import { t } from "../i18n";

/** ↻ 迷你菜单引擎子项：null=auto（options 不带 engine 键，后端按已存决议） */
const RETRY_ENGINES: { key: string | null; label: string }[] = [
    { key: null, label: t.home.engineAuto },
    { key: "tectonic", label: "tectonic" },
    { key: "xelatex", label: "xelatex" },
    { key: "pdflatex", label: "pdflatex" },
];

/**
 * ↻ 重试迷你菜单本体——仅打开期挂载，dismiss 监听（外点/Escape）随
 * 组件生灭不占全局；roving/Tab 走 menuNav 共享契约。
 * onPick(undefined)=裸重试、null=auto、字符串=指定引擎。
 */
export default function RetryMenu(props: {
    wrap(): HTMLElement | undefined;
    trigger(): HTMLElement | undefined;
    onClose(): void;
    onPick(engine?: string | null): void;
}) {
    bindMenuDismiss({
        open: () => true,
        close: () => props.onClose(),
        wrap: () => props.wrap(),
        trigger: () => props.trigger(),
    });
    return (
        <span
            class="retry-menu"
            role="menu"
            onKeyDown={(e) => menuRoving(e, props.onClose)}
        >
            <button
                type="button"
                role="menuitem"
                tabIndex={-1}
                class="retry-item"
                onClick={() => props.onPick()}
            >
                {t.home.retry}
            </button>
            <For each={RETRY_ENGINES}>
                {(eng) => (
                    <button
                        type="button"
                        role="menuitem"
                        tabIndex={-1}
                        class="retry-item"
                        onClick={() => props.onPick(eng.key)}
                    >
                        {t.home.retryAs.replace("{engine}", eng.label)}
                    </button>
                )}
            </For>
        </span>
    );
}
