import { For, Show } from "solid-js";
import type { TaskSnapshot } from "../api/client";
import { isTerminal } from "../api/client";
import { t } from "../i18n/zh";

interface Props {
    tasks: TaskSnapshot[];
    onOpen(taskId: string): void;
}

function fmtTime(ts: number): string {
    const d = new Date(ts * (ts < 1e12 ? 1000 : 1));
    return d.toLocaleString();
}

export default function TaskList(props: Props) {
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
                        <span class="task-time">{fmtTime(task.created_at)}</span>
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
