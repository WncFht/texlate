// 段落棋盘格 —— hjfy 式逐段可视：ok 绿 / fallback 黄 / failed 红 / 未到灰。
// SSE chunk 事件只带变化的 items[]，本组件按 seq 折叠成 seq→status 图。

import { createMemo, For, Show } from "solid-js";
import type { ChunkItem } from "../api/client";
import { t } from "../i18n/zh";

interface Props {
    total: number;
    done: number;
    cached?: number;
    failed?: number;
    items?: ChunkItem[]; // 增量帧；也接受累计全量
}

const STATUS_CLASS: Record<string, string> = {
    ok: "cell-ok",
    fallback_orig: "cell-fallback",
    failed: "cell-failed",
};

export default function ProgressGrid(props: Props) {
    const cells = createMemo(() => {
        const map = new Map<number, string>();
        for (const it of props.items ?? []) map.set(it.seq, it.status);
        return Array.from({ length: Math.max(0, props.total) }, (_, i) => map.get(i) ?? "pending");
    });

    return (
        <div class="progress-grid-wrap">
            <div class="progress-grid-meta">
                <span>
                    {t.progress.doneChunks} {props.done}/{props.total}
                </span>
                <Show when={props.cached}>
                    <span>
                        {t.progress.cached} {props.cached}
                    </span>
                </Show>
                <Show when={props.failed}>
                    <span class="bad">
                        {t.progress.failed} {props.failed}
                    </span>
                </Show>
            </div>
            <div class="progress-grid" role="img" aria-label={t.progress.chunks}>
                <For each={cells()}>
                    {(status) => <i class={STATUS_CLASS[status] ?? "cell-pending"} title={status} />}
                </For>
            </div>
        </div>
    );
}
