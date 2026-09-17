// ChunkPreview —— translating 阶段的已译段落流式预览（U1）。
// api.taskChunks 轮询（2.5s 一拍）拉头部窗口内的已译 chunk，纯文本滚动
// 列表——不走 HtmlPane 全渲染，控成本。契约（fe-live 侧 client 方法）：
//   api.taskChunks(taskId, offset?, limit?)
//     → {chunks:[{seq,kind,status,en,zh}],total}
// 方法未就位时整块缺席（优雅降级，等契约落地自动生效）。

import { createSignal, For, onCleanup, onMount, Show } from "solid-js";
import { api } from "../api/client";
import { t } from "../i18n/zh";

export interface PreviewChunk {
    seq: number;
    kind?: string;
    status?: string;
    en?: string;
    zh?: string;
}

export interface ChunksPage {
    chunks: PreviewChunk[];
    total: number;
}

type TaskChunks = (
    taskId: string,
    offset?: number,
    limit?: number,
) => Promise<ChunksPage>;

const POLL_MS = 2500;
/** 头 N 段窗口——预览定位在文档开头，任务再大负载也有界 */
const WINDOW = 60;
const CHAR_CAP = 500;

const taskChunks = () =>
    (api as { taskChunks?: TaskChunks }).taskChunks;

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

    const tick = async () => {
        const fn = taskChunks();
        if (!fn) return;
        try {
            const page = await fn(props.taskId, 0, WINDOW);
            setTotal(page.total);
            setChunks(
                page.chunks.filter((c) => typeof c.zh === "string" && c.zh.trim()),
            );
        } catch {
            /* 端点未就位/网络抖动——下拍再试 */
        }
    };

    onMount(() => {
        void tick();
        const id = window.setInterval(() => void tick(), POLL_MS);
        onCleanup(() => window.clearInterval(id));
    });

    return (
        <Show when={chunks().length > 0}>
            <section
                class="chunk-preview"
                aria-label={t.progress.preview}
            >
                <p class="cp-head muted">
                    {t.progress.preview} · {chunks().length}/
                    {total()}
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
