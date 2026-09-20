// TaskDownloads —— 终态任务行内产物下载折叠臂。自 TaskList.tsx 拆出。

import { createSignal, For, Show } from "solid-js";
import type { FileManifest, TaskSnapshot } from "../api/client";
import { api } from "../api/client";
import { downloadItems } from "../taskFiles";
import { t } from "../i18n";

/**
 * 终态任务行内产物下载：折叠钮展开直链清单。snapshot.artifacts（SSE
 * done 帧带过）优先；列表行缺 artifacts 时懒拉 files manifest——
 * 但只在用户意图明确后（悬停/聚焦预取，点开必然已发），避免列表
 * 挂载即每行一请求的 N 突发。
 * 快捷臂必须落在 .task-row <a> 之外——a 内嵌 interactive 非法。
 */
export default function TaskDownloads(props: { task: TaskSnapshot }) {
    const [open, setOpen] = createSignal(false);
    const [manifest, setManifest] = createSignal<FileManifest | null>(null);
    const [fetching, setFetching] = createSignal(false);
    let tried = false;

    /** 幂等懒拉：首悬停/聚焦即预热，点开时多半已就绪；失败不留死闸可重试 */
    const ensure = () => {
        if (tried || props.task.artifacts) return;
        tried = true;
        setFetching(true);
        api.files(props.task.task_id)
            .then(setManifest)
            .catch(() => {
                tried = false;
                setManifest(null);
            })
            .finally(() => setFetching(false));
    };

    const items = () => {
        const snap = props.task.artifacts;
        if (snap) return downloadItems(snap);
        const m = manifest();
        if (!m) return [];
        return downloadItems(
            Object.fromEntries(
                Object.entries(m.artifacts).map(([k, e]) => [k, e.url]),
            ),
        );
    };

    return (
        <>
            <button
                type="button"
                class="task-dlt"
                aria-expanded={open()}
                title={t.home.dlTitle}
                aria-label={t.home.dlTitle}
                onPointerEnter={ensure}
                onFocus={ensure}
                onClick={() => {
                    ensure();
                    setOpen((v) => !v);
                }}
            >
                ⬇
            </button>
            <Show when={open()}>
                <span class="task-dls">
                    <For each={items()}>
                        {(d) => (
                            <a class="task-dl" href={d.url} download="">
                                {d.label}
                            </a>
                        )}
                    </For>
                    <Show when={!items().length}>
                        <span class="task-dl-empty">
                            {fetching() ? t.home.dlLoading : t.home.dlNone}
                        </span>
                    </Show>
                </span>
            </Show>
        </>
    );
}
