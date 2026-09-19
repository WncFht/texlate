// TaskProgress —— 进行中任务的整页进度视图：transport 徽标 + 排队位次 +
// 阶段步进 + 进度条 + ETA + 统计条 + 阶段时间线（含每段耗时）+ 段落棋盘格 +
// fixloop/L2 面板 + 警告/错误 + 日志抽屉 + 取消。
// 纯展示件：数据全走 props，秒表（elapsed 走时源）为组件私态。

import { createEffect, createSignal, For, onCleanup, Show } from "solid-js";
import type { TaskSnapshot, TaskStage } from "../api/client";
import type { TaskLive } from "../stores/tasks";
import ProgressGrid from "../components/ProgressGrid";
import ChunkPreview from "./ChunkPreview";
import LivePane from "./LivePane";
import { fmtClock, fmtElapsed } from "./timefmt";
import { t } from "../i18n";

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

    /** 翻译段 ETA：done≥2 起步；基准用 translating 段首入点，缺则总 elapsed */
    const etaSec = () => {
        if (props.task?.status !== "translating") return null;
        const { done, total } = progStats();
        if (done < 2 || done >= total) return null;
        const marks = props.live?.stages ?? [];
        const t0 = [...marks]
            .reverse()
            .find((s) => s.stage === "translating")?.at;
        const base = t0 != null ? Math.max(1, now() / 1000 - t0) : elapsed();
        return (base * (total - done)) / done;
    };
    const etaText = () => {
        const s = etaSec();
        if (s == null) return "";
        return s < 60
            ? t.progress.etaUnder1
            : t.progress.etaMin.replace("{n}", String(Math.ceil(s / 60)));
    };

    let logPre: HTMLPreElement | undefined;
    let logDrawer: HTMLDetailsElement | undefined;
    // 棋盘格失败格点击 → 日志命中行号（null=无命中/未跳转）
    const [logHit, setLogHit] = createSignal<number | null>(null);
    const scrollLog = () => {
        if (logHit() !== null) return; // 命中定位在位——不抢滚回底部
        if (logDrawer?.open && logPre) logPre.scrollTop = logPre.scrollHeight;
    };
    // 新日志落地后贴底（For 渲染先于 effect，scrollHeight 已是新值）
    createEffect(() => {
        void props.live?.logs.length;
        scrollLog();
    });
    // 命中行越出日志面（resetLive 清空/截断）→ 释放 autoscroll
    createEffect(() => {
        const i = logHit();
        if (i != null && i >= (props.live?.logs.length ?? 0)) setLogHit(null);
    });
    // 用户手动滚回底部 → 命中使命完成，恢复贴底跟随
    createEffect(() => {
        const el = logPre;
        if (!el) return;
        const onScroll = () => {
            if (
                logHit() !== null &&
                el.scrollTop + el.clientHeight >= el.scrollHeight - 4
            )
                setLogHit(null);
        };
        el.addEventListener("scroll", onScroll, { passive: true });
        onCleanup(() => el.removeEventListener("scroll", onScroll));
    });
    createEffect(() => {
        const i = logHit();
        if (i == null) return;
        logPre?.querySelectorAll(".log-line")[i]?.scrollIntoView({
            block: "center",
        });
    });

    /** 失败格点击：开抽屉 + 匹配 seq/错误码行高亮定位；无匹配只开抽屉 */
    const jumpLog = (seq: number) => {
        const code = props.live?.chunkItems[seq]?.error_code;
        const needles = [
            `seq=${seq}`,
            `seq:${seq}`,
            `seq ${seq}`,
            `chunk ${seq}`,
            `chunk #${seq}`,
            `#${seq}`,
        ];
        if (code) needles.push(code);
        // 边界匹配：needle 尾部是数字——后随数字即他人 seq（"seq=1" 不得
        // 命中 "seq=12"/"seq=100"）
        const esc = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
        const re = new RegExp(`(?:${needles.map(esc).join("|")})(?!\\d)`);
        const lines = props.live?.logs ?? [];
        const hit = lines.findIndex((l) => re.test(l.line));
        setLogHit(hit >= 0 ? hit : null);
        if (logDrawer) logDrawer.open = true;
    };

    // transport 四态徽标（connecting/polling 由 fe-live 侧 transport 契约扩展；
    // live 正常不显示）。宽转 string——契约字段落地前后都能编
    const transportText = () => {
        switch (props.live?.transport as string | undefined) {
            case "connecting":
                return t.progress.connecting;
            case "polling":
                return t.progress.polling;
            case "closed":
                return t.progress.closed;
            default:
                return t.progress.reconnecting;
        }
    };

    return (
        <main class="task-progress">
            <h1 class="tp-title">{props.title}</h1>
            <Show
                when={props.live?.transport && props.live!.transport !== "live"}
            >
                <p
                    class={`transport-badge ${props.live!.transport}`}
                    role="status"
                >
                    {transportText()}
                </p>
            </Show>
            <Show
                when={
                    props.task?.status === "queued" &&
                    props.task.queue_position != null
                }
            >
                <p class="queue-badge" role="status">
                    {t.progress.queuePos.replace(
                        "{n}",
                        String(props.task!.queue_position),
                    )}
                </p>
            </Show>
            <ol class="stage-stepper">
                <For each={STAGES}>
                    {(s) => {
                        const cur = () =>
                            props.task?.stage ?? props.task?.status;
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
            <div
                class="tp-bar"
                role="progressbar"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(props.task?.progress ?? 0)}
                aria-label={t.progress.chunks}
            >
                <i style={{ width: `${props.task?.progress ?? 0}%` }} />
            </div>
            <Show when={props.task?.message}>
                <p class="muted">{props.task!.message}</p>
            </Show>
            <Show when={etaSec() != null}>
                <p class="tp-eta muted">{etaText()}</p>
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
                        {(e, i) => {
                            // 相邻事件 .at 相减得段耗时；末段随秒表走 live elapsed
                            const dur = () => {
                                const ss = props.live?.stages ?? [];
                                const nxt = ss[i() + 1];
                                const end = nxt ? nxt.at : now() / 1000;
                                return Math.max(0, end - e.at);
                            };
                            return (
                                <li>
                                    <time class="tl-time">
                                        {fmtClock(e.at)}
                                    </time>
                                    <span class="tl-stage">
                                        {t.status[e.stage] ?? e.stage}
                                    </span>
                                    <span class="tl-dur muted">
                                        {fmtElapsed(dur())}
                                    </span>
                                    <Show when={e.message}>
                                        <span class="tl-msg muted">
                                            {e.message}
                                        </span>
                                    </Show>
                                </li>
                            );
                        }}
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
                        onCellClick={jumpLog}
                    />
                )}
            </Show>
            {/* 翻译段流式预览：已译 chunk 只读列表（taskChunks 轮询，
                组件未随阶段离开即停） */}
            <Show
                when={
                    props.task?.status === "translating" && props.task.task_id
                }
            >
                {(id) => <ChunkPreview taskId={id()} />}
            </Show>
            {/* === live reading === 边译边读：已译段全渲染面板（LivePane 经
                chunkPoll 共享轮询累积补丁；compiling 段 chunks 已冻结——
                frozen 补末拍后退订停轮询；终态切走即卸） */}
            <Show
                when={
                    (props.task?.status === "translating" ||
                        props.task?.status === "compiling") &&
                    props.task.task_id
                }
            >
                {(id) => (
                    <LivePane
                        taskId={id()}
                        frozen={props.task?.status === "compiling"}
                    />
                )}
            </Show>
            {/* fixloop 修复循环：compiling 段帧起即见——逐轮增量 + done 后
                verdict 徽标 + floor_restored 提示（终态面板复看同一 live 面） */}
            <Show when={props.live?.fixloop}>
                {(f) => (
                    <section class="fx-panel" aria-label={t.progress.fixloop}>
                        <p class="fx-title muted">
                            {t.progress.fixloop}
                            <Show when={!f().done}>
                                <span class="fx-spin" aria-hidden="true" />
                                {t.progress.fxRunning}
                            </Show>
                        </p>
                        <ol class="fx-rounds">
                            <For each={f().rounds}>
                                {(r) => (
                                    <li>
                                        {t.progress.fxRound.replace(
                                            "{n}",
                                            String(r.round),
                                        )}
                                        {r.n_errors != null &&
                                            ` · ${t.progress.fxErrors.replace("{n}", String(r.n_errors))}`}
                                        {r.category != null &&
                                            ` · ${r.category}`}
                                        {r.sec != null &&
                                            ` · ${r.sec.toFixed(1)}s`}
                                        {r.died === true &&
                                            ` · ${t.progress.fxDied}`}
                                    </li>
                                )}
                            </For>
                        </ol>
                        <Show when={f().done}>
                            <p class="fx-verdict">
                                <span class="fx-badge">
                                    {f().verdict ?? "—"}
                                </span>
                                <Show when={f().floor_restored}>
                                    <span class="fx-floor muted">
                                        {t.progress.fxFloor}
                                    </span>
                                </Show>
                            </p>
                        </Show>
                    </section>
                )}
            </Show>
            {/* L2 校验重译：start/progress 帧 → 进行态行；done 帧 → 统计行 */}
            <Show when={props.live?.l2}>
                {(l) => (
                    <section class="fx-panel" aria-label={t.progress.l2}>
                        <p class="fx-title muted">
                            {t.progress.l2}
                            <Show when={l().phase !== "done"}>
                                <span class="fx-spin" aria-hidden="true" />
                            </Show>
                        </p>
                        <Show
                            when={l().phase === "done"}
                            fallback={
                                <p class="fx-note muted">
                                    {l().message ?? t.progress.l2Running}
                                </p>
                            }
                        >
                            <p class="fx-note muted">
                                {t.progress.l2Errors} {l().errors ?? 0} ·{" "}
                                {t.progress.l2Retranslated}{" "}
                                {l().retranslated ?? 0} ·{" "}
                                {t.progress.l2Fallback} {l().fallback ?? 0}
                            </p>
                        </Show>
                    </section>
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
            <details
                class="log-drawer"
                ref={(el) => (logDrawer = el)}
                onToggle={scrollLog}
            >
                <summary>{t.progress.log}</summary>
                <pre ref={(el) => (logPre = el)}>
                    <For each={props.live?.logs ?? []}>
                        {(l, i) => (
                            <span
                                class="log-line"
                                classList={{ hit: i() === logHit() }}
                            >
                                {l.line + "\n"}
                            </span>
                        )}
                    </For>
                </pre>
            </details>
            <div class="tp-actions">
                <button
                    type="button"
                    class="btn-ghost"
                    onClick={() => props.onCancel()}
                >
                    {t.reader.cancel}
                </button>
            </div>
        </main>
    );
}
