// ActiveLine —— Home 进行中提示行：导航线索而非任务列表——一行字指路
// #/tasks；首个进行中任务挂标题与进度给上下文。

import { createMemo, Show } from "solid-js";
import { isTerminal } from "../api/client";
import { t } from "../i18n";
import { taskStore } from "../stores/tasks";

export default function ActiveLine() {
    /** 进行中任务（提示行）：首个挂标题给上下文，点行进 #/tasks */
    const activeTasks = createMemo(() =>
        taskStore.state.tasks.filter((x) => !isTerminal(x.status)),
    );
    const firstActive = () => activeTasks()[0];

    return (
        <Show when={activeTasks().length > 0}>
            <a class="home-active" href="#/tasks">
                <span>
                    {t.home.activeLine.replace(
                        "{n}",
                        String(activeTasks().length),
                    )}
                </span>
                <Show when={firstActive()}>
                    {(fa) => (
                        <span class="home-active-first">
                            {fa().title || fa().arxiv_id || fa().task_id}
                            <Show when={fa().progress > 0}>
                                {" "}
                                {fa().progress}%
                            </Show>
                        </span>
                    )}
                </Show>
                <span class="home-active-more">{t.home.activeMore} →</span>
            </a>
        </Show>
    );
}
