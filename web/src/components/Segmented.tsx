import { For } from "solid-js";

interface Props<T extends string> {
    options: { value: T; label: string }[];
    value: T;
    onChange(v: T): void;
    ariaLabel?: string;
}

export default function Segmented<T extends string>(props: Props<T>) {
    return (
        <div class="segmented" role="tablist" aria-label={props.ariaLabel}>
            <For each={props.options}>
                {(opt) => (
                    <button
                        type="button"
                        role="tab"
                        class="segmented-item"
                        classList={{ on: props.value === opt.value }}
                        aria-selected={props.value === opt.value}
                        onClick={() => props.onChange(opt.value)}
                    >
                        {opt.label}
                    </button>
                )}
            </For>
        </div>
    );
}
