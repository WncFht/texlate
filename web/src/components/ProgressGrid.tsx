// 段落棋盘格 —— hjfy 式逐段可视：ok 绿 / fallback 黄 / failed 红 / 未到灰。
// items 是 dense 数组：下标即 seq，缺位一律 pending。
//
// 粒度设计（P2）：cells 由 total 派生的定长下标表 + <Index> 按位复用；
// 每格独立 memo 读 items[i].status——chunk 帧只触达被写动的格，
// 不再每帧 O(total) slice+全量重建（5000 段 × 5000 帧的教训）。

import { createMemo, Index } from "solid-js";
import type { ChunkItem } from "../api/client";
import { t } from "../i18n/zh";

interface Props {
    total: number;
    done: number;
    cached?: number;
    failed?: number;
    items?: ChunkItem[]; // dense：index = seq，已是累积态
    /** 失败格点击（seq 回传）——缺省则无交互 */
    onCellClick?: (seq: number) => void;
}

const STATUS_CLASS: Record<string, string> = {
    ok: "cell-ok",
    fallback_orig: "cell-fallback",
    failed: "cell-failed",
};

export default function ProgressGrid(props: Props) {
    // 定长下标表——total 不变即引用不变，<Index> 行零重建
    const idxs = createMemo(() =>
        Array.from({ length: Math.max(0, props.total) }, (_, i) => i),
    );

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
                <Index each={idxs()}>
                    {(i) => {
                        // 每格只订 items[i()]——store 侧增量写哪格哪格才重算
                        const cls = createMemo(
                            () =>
                                STATUS_CLASS[
                                    props.items?.[i()]?.status ?? "pending"
                                ] ?? "cell-pending",
                        );
                        const failed = () => cls() === "cell-failed";
                        return (
                            <i
                                class={cls()}
                                classList={{ clickable: failed() && !!props.onCellClick }}
                                title={
                                    failed()
                                        ? (props.items?.[i()]?.error_code ??
                                          "failed")
                                        : undefined
                                }
                                onClick={() =>
                                    failed() && props.onCellClick?.(i())
                                }
                            />
                        );
                    }}
                </Index>
            </div>
        </div>
    );
}
