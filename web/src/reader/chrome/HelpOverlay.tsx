// HelpOverlay —— 「?」键位帮助浮层：kbd-help 卡 + HELP_ITEMS 键面表。
// 宿主侧 <Show when={helpOpen()}> 门控挂载——open 信号仅喂聚焦 effect
// （逐字保留打开拍聚焦语义）。

import { createEffect, For } from "solid-js";
import { t } from "../../i18n";

export default function HelpOverlay(props: {
    open(): boolean;
    onClose(): void;
}) {
    const HELP_ITEMS: [string, string][] = [
        ["1 / 2 / 3", t.reader.helpModes],
        ["4", t.reader.helpGuide],
        ["S", t.reader.helpSync],
        ["[ / ]", t.reader.helpPages],
        ["Ctrl+F", t.reader.helpFind],
        ["Backspace", t.reader.helpNavBack],
        ["Alt+←/→", t.reader.helpNavHist],
        ["⌘+Click / Ctrl+Click", t.reader.helpInspect],
        ["V", t.reader.helpCursor],
        ["?", t.reader.helpHelp],
    ];

    // 帮助浮层打开时聚焦卡片本体——键盘用户随即 Esc/点击之外有焦点落点；
    // 卡片是唯一可聚焦物，Tab 拦下即闭环（无内部控件可循环）
    let helpCard!: HTMLDivElement;
    createEffect(() => {
        if (props.open()) queueMicrotask(() => helpCard?.focus());
    });
    const onHelpKey = (e: KeyboardEvent) => {
        if (e.key === "Tab") e.preventDefault();
    };

    return (
        <div
            class="kbd-help"
            role="dialog"
            aria-modal="true"
            aria-label={t.reader.helpTitle}
            onClick={() => props.onClose()}
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
    );
}
