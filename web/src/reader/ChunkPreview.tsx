// ChunkPreview —— translating 阶段的已译段落流式预览（U1）。
// chunkPoll 共享轮询页（与 LivePane 同拍同请求）取头窗内的已译 chunk，
// 纯文本滚动列表——不走 HtmlPane 全渲染，控成本。端点未就位/网络抖动由
// chunkPoll 吞掉下拍再试，本组件只消费页数据。

import { createSignal, For, onCleanup, onMount, Show } from "solid-js";
import type { TaskChunksPage } from "../api/client";
import { subscribeChunks } from "./chunkPoll";
import { t } from "../i18n";

export interface PreviewChunk {
    seq: number;
    kind?: string;
    status?: string;
    en?: string;
    zh?: string;
}

/** 头 N 段窗口——预览定位在文档开头，任务再大负载也有界 */
const WINDOW = 60;
const CHAR_CAP = 500;

/** 一段译文 → 单行预览文本（空白塌缩 + 500 字截断） */
export function previewText(zh: string | undefined): string {
    if (typeof zh !== "string") return "";
    const flat = zh.replace(/\s+/g, " ").trim();
    return flat.length > CHAR_CAP ? `${flat.slice(0, CHAR_CAP)}…` : flat;
}

interface Props {
    taskId: string;
}

export default function ChunkPreview(props: Props) {
    const [chunks, setChunks] = createSignal<PreviewChunk[]>([]);
    const [total, setTotal] = createSignal(0);

    const onPage = (page: TaskChunksPage) => {
        setTotal(page.total);
        // 共享轮询拉的是 0..CHUNK_WINDOW 整窗——预览只取头窗段
        setChunks(
            page.chunks
                .slice(0, WINDOW)
                .filter((c) => typeof c.zh === "string" && c.zh.trim()),
        );
    };

    onMount(() => {
        const unsub = subscribeChunks(props.taskId, onPage);
        onCleanup(unsub);
    });

    return (
        <Show when={chunks().length > 0}>
            <section class="chunk-preview" aria-label={t.progress.preview}>
                <p class="cp-head muted">
                    {t.progress.preview} · {chunks().length}/{total()}
                </p>
                <div class="cp-list">
                    <For each={chunks()}>
                        {(c) => (
                            <div class="cp-item">
                                <span class="cp-meta muted">
                                    #{c.seq + 1}
                                    <Show when={c.kind}>
                                        {(k) => <i class="cp-kind">{k()}</i>}
                                    </Show>
                                </span>
                                <p class="cp-text">{previewText(c.zh)}</p>
                            </div>
                        )}
                    </For>
                </div>
            </section>
        </Show>
    );
}
