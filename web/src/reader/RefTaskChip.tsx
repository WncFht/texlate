// RefTaskChip —— 文献条目翻译任务状态钮（卡内脚部与文献表面板行共用）。
// 状态机相（行投影 refViewOf——4.3% 零事件帧任务的兜底主路）：
//   idle     → 「翻译此文」钮（onTranslate 缺位时不出钮——无 id 行同口径）
//   queued   → 「排队中」chip（queue_position 不进文案——批行无位次字段）
//   running  → 「翻译中/编译中」粗相（百分比不渲染——done/total 失真 11.3pt
//              实证；粗相即规格面，pct 留 title 提示）
//   done     → 「打开译文」<a href=#/reader/{id}>（partial 同相+失败角标）
//   failed   → 「↻ 重试」（fault/cancelled/interrupted；默认 api.retry
//              同 task_id 续跑——retry 同事件流，行投影自动翻相）
//   needsAuth→ 「输 Key」CTA（默认跳 reader 页——ResultBody needs_auth
//              内联 key 面板已就位；宿主可覆写 onAuth 走面板内联框）

import { createSignal, Show } from "solid-js";
import { api, apiErrText, type TaskSnapshot } from "../api/client";
import { taskStore } from "../stores/tasks";
import { toast } from "../stores/toastStore";
import { ctText, refViewOf, type RefView } from "./citeTranslate";
import { readerHashWithFrom } from "./tasknav";
import type { TaskLive } from "../stores/liveFrames";

interface Props {
    /** 条目解析出的 arXiv id（原样——双侧 canon 归一在 taskByArxiv 内） */
    arxivId: string;
    /** 行访问器（缺省 taskStore.taskByArxiv——canon 匹配+intents 桥） */
    task?(): TaskSnapshot | undefined;
    /** live 帧面（缺省 taskStore.live(row.task_id)——在槽任务补强进度） */
    live?(): TaskLive | undefined;
    /** idle 点击——宿主提交通道（citeTranslate.submit 包装）；返回 Promise
        期间 chip 自锁 busy 防双击 */
    onTranslate?(): void | Promise<unknown>;
    /** needs_auth CTA（缺省跳 #/reader/{taskId} 用既有 authKey 面板） */
    onAuth?(taskId: string): void;
    /** failed ↻ 重试（缺省 api.retry + patch + resetLive——taskActions
        同口径；needs_auth 行勿走此路——key 必须重带请求头） */
    retry?(taskId: string): void | Promise<unknown>;
}

export default function RefTaskChip(props: Props) {
    const [busy, setBusy] = createSignal(false);

    const row = () => props.task?.() ?? taskStore.taskByArxiv(props.arxivId);
    const view = (): RefView =>
        refViewOf(row(), props.live?.() ?? liveOf(row()));
    const liveOf = (r: TaskSnapshot | undefined) =>
        r ? taskStore.live(r.task_id) : undefined;

    /** 默认重试：同 task_id 续跑（retry 同事件流复用——行 status patch 回
        queued 后 live/stage 帧自然推相；resetLive 清上轮终态残件） */
    const retryDefault = async (taskId: string) => {
        try {
            const res = await api.retry(taskId);
            taskStore.patch(taskId, {
                status: res.status,
                stage: undefined,
                message: undefined,
                error: null,
                progress: 0,
            });
            taskStore.resetLive(taskId);
        } catch (e) {
            toast.err(apiErrText(e));
        }
    };

    const onClick = () => {
        const v = view();
        if (v.phase === "idle") {
            if (!props.onTranslate || busy()) return;
            setBusy(true);
            void Promise.resolve(props.onTranslate()).finally(() =>
                setBusy(false),
            );
        } else if (v.phase === "failed" && v.taskId) {
            if (busy()) return;
            setBusy(true);
            void Promise.resolve(
                (props.retry ?? retryDefault)(v.taskId),
            ).finally(() => setBusy(false));
        } else if (v.phase === "needsAuth" && v.taskId) {
            (
                props.onAuth ??
                ((id) => (location.hash = readerHashWithFrom(id)))
            )(v.taskId);
        }
    };

    const label = (): string => {
        const v = view();
        switch (v.phase) {
            case "queued":
                return ctText("cite.queued");
            case "running":
                return v.stage === "compiling"
                    ? ctText("compiling")
                    : ctText("cite.translating");
            case "done":
                return ctText("cite.openZh");
            case "failed":
                return `↻ ${ctText("cite.retryRef")}`;
            case "needsAuth":
                return ctText("authKeyCta");
            default:
                return ctText("cite.translate");
        }
    };

    return (
        <Show
            when={view().phase !== "idle" || props.onTranslate}
            fallback={null}
        >
            <Show
                when={view().phase === "done" && view().taskId}
                fallback={
                    <button
                        type="button"
                        class="ref-task-chip"
                        classList={{
                            [`is-${view().phase}`]: true,
                            busy: busy(),
                        }}
                        disabled={
                            busy() ||
                            view().phase === "queued" ||
                            view().phase === "running"
                        }
                        title={
                            view().phase === "running"
                                ? `${view().pct}%`
                                : undefined
                        }
                        onClick={onClick}
                    >
                        {label()}
                        <Show when={view().phase === "queued"}>…</Show>
                    </button>
                }
            >
                {/* 可读终态——done/partial 归「打开译文」链接；partial 附
                    failed_chunks 角标（降级交付语义） */}
                <a
                    class="ref-task-chip is-done"
                    href={readerHashWithFrom(view().taskId ?? "")}
                >
                    {label()}
                    <Show when={view().failedChunks > 0}>
                        <span class="ref-chip-badge">
                            {ctText("failedChunks", {
                                n: view().failedChunks,
                            })}
                        </span>
                    </Show>
                </a>
            </Show>
        </Show>
    );
}
