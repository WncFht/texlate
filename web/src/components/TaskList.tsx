import { For, Show } from "solid-js";
import type { TaskError, TaskSnapshot } from "../api/client";
import { isTerminal } from "../api/client";
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

export default function TaskList(props: Props) {
    // 终态 fault/partial 的 error 徽标内容
    const errOf = (task: TaskSnapshot): TaskError | null => {
        if (task.status !== "fault" && task.status !== "partial") return null;
        return task.error ?? null;
    };

    return (
        <div class="task-list">
            <Show when={props.tasks.length === 0}>
                <p class="muted">{t.home.empty}</p>
            </Show>
            <For each={props.tasks}>
                {(task) => (
                    <button type="button" class="task-row" onClick={() => props.onOpen(task.task_id)}>
                        <span class="task-title">{task.title || task.arxiv_id || task.task_id}</span>
                        <span class={`task-status st-${task.status}`}>
                            {t.status[task.status] ?? task.status}
                        </span>
                        <span class="task-time">{fmtRel(task.created_at)}</span>
                        <span class="task-meta muted">
                            <span class="task-kind">{t.kind[task.kind] ?? task.kind}</span>
                            <Show when={!isTerminal(task.status)}>
                                <span>{t.status[task.stage ?? task.status]}</span>
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
                                classList={{ done: isTerminal(task.status) && task.status === "done" }}
                            />
                        </span>
                    </button>
                )}
            </For>
        </div>
    );
}
