// TaskProgress —— 进行中任务的整页进度视图：transport 徽标 + 阶段步进 +
// 进度条 + 统计条 + 阶段时间线 + 段落棋盘格 + 警告/错误 + 日志抽屉 + 取消。
// 纯展示件：数据全走 props，秒表（elapsed 走时源）为组件私态。

import { createEffect, createSignal, For, onCleanup, Show } from "solid-js";
import type { TaskSnapshot, TaskStage } from "../api/client";
import type { TaskLive } from "../stores/tasks";
import ProgressGrid from "../components/ProgressGrid";
import { fmtClock, fmtElapsed } from "./timefmt";
import { t } from "../i18n/zh";

const STAGES: TaskStage[] = ["fetching", "parsing", "translating", "compiling"];

interface Props {
    /** 任务快照（store 补丁/SSE 帧实时刷新） */
    task: TaskSnapshot | null;
    /** SSE 增量面（transport/chunk/stages/logs/warnings/error/done） */
    live: TaskLive | undefined;
    title: string;
    onCancel(): void;
}

export default function TaskProgress(props: Props) {
    // 已用时秒表的走时源（created_at 为 epoch 秒）
    const [now, setNow] = createSignal(Date.now());
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    onCleanup(() => window.clearInterval(tick));

    /** 统计条：chunk 帧优先，快照 counters 兜底；tokens 只有快照带 */
    const progStats = () => {
        const c = props.live?.chunk;
        const k = props.task?.counters;
        return {
            done: c?.done ?? k?.done ?? 0,
            total: c?.total ?? k?.total ?? 0,
            cached: c?.cached ?? k?.cached ?? 0,
            failed: c?.failed ?? k?.failed ?? 0,
            tokens: k?.tokens ?? 0,
        };
    };
    const elapsed = () => {
        const ca = props.task?.created_at;
        return ca ? Math.max(0, now() / 1000 - ca) : 0;
    };

    let logPre: HTMLPreElement | undefined;
    let logDrawer: HTMLDetailsElement | undefined;
    const scrollLog = () => {
        if (logDrawer?.open && logPre) logPre.scrollTop = logPre.scrollHeight;
    };
    // 新日志落地后贴底（For 渲染先于 effect，scrollHeight 已是新值）
    createEffect(() => {
        void props.live?.logs.length;
        scrollLog();
    });

    return (
        <main class="task-progress">
            <h1 class="tp-title">{props.title}</h1>
            <Show when={props.live?.transport && props.live!.transport !== "live"}>
                <p class="transport-badge" role="status">
                    {props.live!.transport === "closed"
                        ? t.progress.closed
                        : t.progress.reconnecting}
                </p>
            </Show>
            <ol class="stage-stepper">
                <For each={STAGES}>
                    {(s) => {
                        const cur = () => props.task?.stage ?? props.task?.status;
                        const idx = () => STAGES.indexOf(cur() as TaskStage);
                        return (
                            <li
                                classList={{
                                    done: STAGES.indexOf(s) < idx(),
                                    on: cur() === s,
                                }}
                            >
                                {t.status[s] ?? s}
                            </li>
                        );
                    }}
                </For>
            </ol>
            <div class="tp-bar">
                <i style={{ width: `${props.task?.progress ?? 0}%` }} />
            </div>
            <Show when={props.task?.message}>
                <p class="muted">{props.task!.message}</p>
            </Show>
            <dl class="stat-strip">
                <div class="stat">
                    <dt>{t.progress.doneChunks}</dt>
                    <dd class="stat-num">
                        {progStats().done}/{progStats().total}
                    </dd>
                </div>
                <div class="stat">
                    <dt>{t.progress.cached}</dt>
                    <dd class="stat-num">{progStats().cached}</dd>
                </div>
                <div class="stat">
                    <dt>{t.progress.failed}</dt>
                    <dd class="stat-num">{progStats().failed}</dd>
                </div>
                <div class="stat">
                    <dt>{t.progress.tokens}</dt>
                    <dd class="stat-num">{progStats().tokens}</dd>
                </div>
                <div class="stat">
                    <dt>{t.progress.elapsed}</dt>
                    <dd class="stat-num">{fmtElapsed(elapsed())}</dd>
                </div>
            </dl>
            <Show when={(props.live?.stages.length ?? 0) > 0}>
                <ol class="stage-timeline">
                    <For each={props.live!.stages}>
                        {(e) => (
                            <li>
                                <time class="tl-time">{fmtClock(e.at)}</time>
                                <span class="tl-stage">
                                    {t.status[e.stage] ?? e.stage}
                                </span>
                                <Show when={e.message}>
                                    <span class="tl-msg muted">{e.message}</span>
                                </Show>
                            </li>
                        )}
                    </For>
                </ol>
            </Show>
            <Show when={props.live?.chunk}>
                {(c) => (
                    <ProgressGrid
                        total={c().total}
                        done={c().done}
                        cached={c().cached}
                        failed={c().failed}
                        items={props.live?.chunkItems ?? []}
                    />
                )}
            </Show>
            <Show when={(props.live?.warnings.length ?? 0) > 0}>
                <p class="warn-title muted">{t.progress.warnings}</p>
                <ul class="warn-list">
                    <For each={props.live!.warnings}>
                        {(w) => (
                            <li>
                                [{w.code}] {w.message}
                            </li>
                        )}
                    </For>
                </ul>
            </Show>
            <Show when={props.live?.error}>
                {(e) => (
                    <p class="form-error">
                        [{e().code}] {e().message}
                    </p>
                )}
            </Show>
            <details class="log-drawer" ref={(el) => (logDrawer = el)} onToggle={scrollLog}>
                <summary>{t.progress.log}</summary>
                <pre ref={(el) => (logPre = el)}>
                    <For each={props.live?.logs ?? []}>{(l) => l.line + "\n"}</For>
                </pre>
            </details>
            <div class="tp-actions">
                <button type="button" class="btn-ghost" onClick={() => props.onCancel()}>
                    {t.reader.cancel}
                </button>
            </div>
        </main>
    );
}
