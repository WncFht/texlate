import { For } from "solid-js";

interface Props<T extends string> {
    options: { value: T; label: string }[];
    value: T;
    onChange(v: T): void;
    ariaLabel?: string;
}

export default function Segmented<T extends string>(props: Props<T>) {
    // radio 组语义：方向键循环切换，Home/End 跳首尾（U15），roving tabindex
    /** 现值下标；现值越表（options 外旧值）回落 0——首项兜底可聚焦/可漫游 */
    const curIdx = () => {
        const i = props.options.findIndex((o) => o.value === props.value);
        return i < 0 ? 0 : i;
    };
    const onKeyDown = (e: KeyboardEvent) => {
        const opts = props.options;
        if (!opts.length) return; // 空组：%0=NaN 会漏进 onChange(undefined)
        const cur = opts.findIndex((o) => o.value === props.value);
        const base = cur < 0 ? 0 : cur;
        let next = -1;
        if (e.key === "ArrowRight" || e.key === "ArrowDown")
            next = (base + 1) % opts.length;
        else if (e.key === "ArrowLeft" || e.key === "ArrowUp")
            next = (base - 1 + opts.length) % opts.length;
        else if (e.key === "Home") next = 0;
        else if (e.key === "End") next = opts.length - 1;
        // 现值越表（cur<0）时导航键照常发 onChange——移动即选中，顺带愈合取值
        if (next < 0 || (cur >= 0 && next === cur)) return;
        e.preventDefault();
        props.onChange(opts[next].value);
        (
            (e.currentTarget as HTMLElement).children[next] as HTMLElement
        )?.focus();
    };

    return (
        <div
            class="segmented"
            role="radiogroup"
            aria-label={props.ariaLabel}
            onKeyDown={onKeyDown}
        >
            <For each={props.options}>
                {(opt) => (
                    <button
                        type="button"
                        role="radio"
                        class="segmented-item"
                        classList={{ on: props.value === opt.value }}
                        aria-checked={props.value === opt.value}
                        tabIndex={props.options[curIdx()] === opt ? 0 : -1}
                        onClick={() => props.onChange(opt.value)}
                    >
                        {opt.label}
                    </button>
                )}
            </For>
        </div>
    );
}
