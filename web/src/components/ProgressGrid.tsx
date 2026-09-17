// 段落棋盘格 —— hjfy 式逐段可视：ok 绿 / fallback 黄 / failed 红 / 未到灰。
// items 是 dense 累积数组：下标即 seq，缺位一律 pending。

import { createMemo, For } from "solid-js";
import type { ChunkItem } from "../api/client";
import { t } from "../i18n/zh";

interface Props {
    total: number;
    done: number;
    cached?: number;
    failed?: number;
    items?: ChunkItem[]; // dense：index = seq，已是累积态
}

const STATUS_CLASS: Record<string, string> = {
    ok: "cell-ok",
    fallback_orig: "cell-fallback",
    failed: "cell-failed",
};

export default function ProgressGrid(props: Props) {
    const cells = createMemo(() => {
        const items = props.items;
        const out: string[] = [];
        for (let i = 0; i < Math.max(0, props.total); i++) {
            out.push(items?.[i]?.status ?? "pending");
        }
        return out;
    });

    return (
        <div class="progress-grid-wrap">
            <div class="progress-grid-meta">
                <span>
                    {t.progress.doneChunks} {props.done}/{props.total}
                </span>
                <span>
                    {t.progress.cached} {props.cached ?? 0}
                </span>
                <span classList={{ bad: (props.failed ?? 0) > 0 }}>
                    {t.progress.failed} {props.failed ?? 0}
                </span>
            </div>
            <div
                class="progress-grid"
                role="img"
                aria-label={`${t.progress.chunks} ${props.done}/${props.total}`}
            >
                <For each={cells()}>
                    {(status) => (
                        <i class={STATUS_CLASS[status] ?? "cell-pending"} />
                    )}
                </For>
            </div>
        </div>
    );
}
