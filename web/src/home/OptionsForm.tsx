// OptionsForm —— Home 任务选项表单区：常用组 +「高级」折叠组渲染。
// 行描述（label/hint/控件形/信号绑定）由 options.ts 的 optCommon/optAdv
// 出——本件只留控件渲染（optControl/optRow）与折叠组 JSX。

import { For, type JSX, Show } from "solid-js";
import Segmented from "../components/Segmented";
import { t } from "../i18n";
import type { HomeOptions, OptRow } from "./options";

/** 单 options 行的控件部分——label/span 由调用点统一渲染 */
const optControl = (row: OptRow): JSX.Element => {
    if (row.kind === "seg") {
        return (
            <Segmented
                options={[
                    ...(row.defaultLabel
                        ? [{ value: "", label: row.defaultLabel() }]
                        : []),
                    ...row.choices,
                ]}
                value={row.get()}
                onChange={(v) => row.set(v)}
                ariaLabel={row.label}
            />
        );
    }
    if (row.kind === "textarea") {
        return (
            <textarea
                rows={row.rows ?? 3}
                value={row.get()}
                onInput={(e) => row.set(e.currentTarget.value)}
            />
        );
    }
    return (
        <input
            type={row.type ?? "text"}
            min={row.min}
            max={row.max}
            autocomplete={row.type === "password" ? "off" : undefined}
            value={row.get()}
            placeholder={row.placeholder?.()}
            onInput={(e) => row.set(e.currentTarget.value)}
        />
    );
};

/** 单行 label+控件渲染——两组共用；seg 行内嵌按钮，label 元素让位 div */
const optRow = (row: OptRow) => {
    const hint = () => (typeof row.hint === "function" ? row.hint() : row.hint);
    const inner = (
        <>
            <span>
                {row.label}
                <Show when={hint()}>
                    <em class="muted">{hint()}</em>
                </Show>
            </span>
            {optControl(row)}
        </>
    );
    return row.kind === "seg" ? (
        <div class="opt-cell" classList={{ span2: !!row.span2 }}>
            {inner}
        </div>
    ) : (
        <label classList={{ span2: !!row.span2 }}>{inner}</label>
    );
};

export default function OptionsForm(props: { opts: HomeOptions }) {
    return (
        <details class="task-opts">
            <summary>{t.home.options}</summary>
            <div class="opts-grid">
                <For each={props.opts.optCommon}>{optRow}</For>
            </div>
            <details class="opts-adv">
                <summary>{t.home.optsAdvanced}</summary>
                <div class="opts-grid">
                    <For each={props.opts.optAdv}>{optRow}</For>
                </div>
            </details>
        </details>
    );
}
