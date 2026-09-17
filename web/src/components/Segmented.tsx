import { For } from "solid-js";

interface Props<T extends string> {
    options: { value: T; label: string }[];
    value: T;
    onChange(v: T): void;
    ariaLabel?: string;
}

export default function Segmented<T extends string>(props: Props<T>) {
    // radio 组语义：方向键循环切换，roving tabindex
    const onKeyDown = (e: KeyboardEvent) => {
        const opts = props.options;
        const cur = opts.findIndex((o) => o.value === props.value);
        let next = -1;
        if (e.key === "ArrowRight" || e.key === "ArrowDown")
            next = (cur + 1) % opts.length;
        else if (e.key === "ArrowLeft" || e.key === "ArrowUp")
            next = (cur - 1 + opts.length) % opts.length;
        if (next < 0 || next === cur) return;
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
                        tabIndex={props.value === opt.value ? 0 : -1}
                        onClick={() => props.onChange(opt.value)}
                    >
                        {opt.label}
                    </button>
                )}
            </For>
        </div>
    );
}
