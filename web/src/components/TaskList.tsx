import { createResource, createSignal, For, Show } from "solid-js";
import type { TaskError, TaskSnapshot } from "../api/client";
import { api, isTerminal } from "../api/client";
import { taskStore } from "../stores/tasks";
import { downloadItems, isDocKind } from "../taskFiles";
import { t } from "../i18n/zh";

interface Props {
    tasks: TaskSnapshot[];
    onOpen(taskId: string): void;
}

const MIN = 60_000;
const HOUR = 3_600_000;
const DAY = 86_400_000;

/** 相对时间：7 天内用 t.time 模板，超出回退日期 */
function fmtRel(ts: number): string {
    const ms = ts < 1e12 ? ts * 1000 : ts;
    const diff = Date.now() - ms;
    const n = (v: number, tpl: string) => tpl.replace("{n}", String(v));
    if (diff < MIN) return t.time.justNow;
    if (diff < HOUR) return n(Math.floor(diff / MIN), t.time.minAgo);
    if (diff < DAY) return n(Math.floor(diff / HOUR), t.time.hourAgo);
    if (diff < 7 * DAY) return n(Math.floor(diff / DAY), t.time.dayAgo);
    return new Date(ms).toLocaleDateString();
}

/**
 * doc 类任务（docx/epub）行内产物直链：snapshot.artifacts（SSE 在途带过）
 * 优先，无则懒拉 files manifest；无产物（fault/拉取失败/在途）不渲染。
 * 锚点必须落在 .task-row <button> 之外——button 内嵌 interactive 非法。
 */
function DocDownloads(props: { task: TaskSnapshot }) {
    const [manifest] = createResource(
        () => (props.task.artifacts ? null : props.task.task_id),
        (id) => api.files(id).catch(() => null),
    );
    const items = () => {
        const snap = props.task.artifacts;
        if (snap) return downloadItems(snap);
        const m = manifest();
        if (!m) return [];
        return downloadItems(
            Object.fromEntries(Object.entries(m.artifacts).map(([k, e]) => [k, e.url])),
        );
    };
    return (
        <Show when={items().length > 0}>
            <span class="task-dls" title={t.home.dlTitle}>
                <For each={items()}>
                    {(d) => (
                        <a class="task-dl" href={d.url} download="">
                            {d.label}
                        </a>
                    )}
                </For>
            </span>
        </Show>
    );
}

export default function TaskList(props: Props) {
    const [deleting, setDeleting] = createSignal<string | null>(null);
    const [delError, setDelError] = createSignal("");

    // 终态 fault/partial 的 error 徽标内容
    const errOf = (task: TaskSnapshot): TaskError | null => {
        if (task.status !== "fault" && task.status !== "partial") return null;
        return task.error ?? null;
    };

    const confirmDelete = async (task: TaskSnapshot) => {
        if (!isTerminal(task.status) || deleting()) return;
        if (!window.confirm(t.home.delConfirm)) return;
        setDeleting(task.task_id);
        setDelError("");
        try {
            await taskStore.remove(task.task_id);
            // 防御：若正开着该任务的 Reader，跳回首页（列表只在首页渲染，正常不可达）
            if (window.location.hash.startsWith(`#/reader/${task.task_id}`)) {
                window.location.hash = "#/";
            }
        } catch {
            setDelError(t.home.delFailed);
        } finally {
            setDeleting(null);
        }
    };

    return (
        <div class="task-list">
            <Show when={props.tasks.length === 0}>
                <p class="muted">{t.home.empty}</p>
            </Show>
            <For each={props.tasks}>
                {(task) => (
                    <div class="task-wrap">
                        <button
                            type="button"
                            class="task-row"
                            onClick={() => props.onOpen(task.task_id)}
                        >
                            <span class="task-title">
                                {task.title || task.arxiv_id || task.task_id}
                            </span>
                            <span class={`task-status st-${task.status}`}>
                                {t.status[task.status] ?? task.status}
                            </span>
                            <span class="task-time">{fmtRel(task.created_at)}</span>
                            <span class="task-meta muted">
                                <span
                                    class="task-kind"
                                    classList={{ "k-doc": isDocKind(task.kind) }}
                                >
                                    {t.kind[task.kind] ?? task.kind}
                                </span>
                                <Show when={!isTerminal(task.status)}>
                                    <span>
                                        {t.status[task.stage ?? task.status] ??
                                            (task.stage ?? task.status)}
                                    </span>
                                </Show>
                                <Show when={errOf(task)}>
                                    {(e) => (
                                        <span class="task-err" title={e().message}>
                                            [{e().code}]
                                        </span>
                                    )}
                                </Show>
                            </span>
                            <span
                                class="task-bar"
                                role="progressbar"
                                aria-valuenow={task.progress}
                                aria-valuemin={0}
                                aria-valuemax={100}
                            >
                                <i
                                    style={{ width: `${task.progress}%` }}
                                    classList={{
                                        done: isTerminal(task.status) && task.status === "done",
                                    }}
                                />
                            </span>
                        </button>
                        <Show when={isDocKind(task.kind) && isTerminal(task.status)}>
                            <DocDownloads task={task} />
                        </Show>
                        <button
                            type="button"
                            class="task-del"
                            disabled={!isTerminal(task.status) || deleting() === task.task_id}
                            title={isTerminal(task.status) ? t.home.delTip : t.home.delBusy}
                            aria-label={t.home.del}
                            onClick={() => void confirmDelete(task)}
                        >
                            ✕
                        </button>
                    </div>
                )}
            </For>
            <Show when={delError()}>
                <p class="task-del-err">{delError()}</p>
            </Show>
        </div>
    );
}
