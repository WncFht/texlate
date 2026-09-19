// Tasks —— 任务台账页：TaskList 整件（搜索/四桶筛选/行内臂/批量清理），
// 页壳只出标题与加载失败态；刷新走 ensureFresh 共享 TTL。

import { onMount, Show } from "solid-js";
import { taskStore } from "../stores/tasks";
import TaskList from "../components/TaskList";
import { t } from "../i18n";

export default function Tasks(props: { nav(to: string): void }) {
    onMount(() => void taskStore.ensureFresh());

    return (
        <main class="page">
            <h1 class="page-title">
                {t.home.tasks}
                <Show
                    when={
                        taskStore.state.loaded &&
                        taskStore.state.tasks.length > 0
                    }
                >
                    <span class="task-count">
                        {taskStore.state.tasks.length}
                    </span>
                </Show>
            </h1>
            <Show when={taskStore.state.loadError}>
                {(err) => (
                    <p class="form-error">
                        {t.home.loadFailed}：{err()}{" "}
                        <button
                            type="button"
                            class="btn-ghost"
                            onClick={() => void taskStore.refresh()}
                        >
                            {t.home.retry}
                        </button>
                    </p>
                )}
            </Show>
            {/* 未加载完成先骨架——防闪「还没有任务」空态 */}
            <Show
                when={taskStore.state.loaded}
                fallback={
                    <div class="skel-rows" aria-hidden="true">
                        <i />
                        <i />
                        <i />
                    </div>
                }
            >
                <TaskList
                    tasks={taskStore.state.tasks}
                    onOpen={(taskId) => props.nav(`#/reader/${taskId}`)}
                />
            </Show>
        </main>
    );
}
