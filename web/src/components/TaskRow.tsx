// TaskRow —— 单行任务卡（TaskList 的 <For> 行体）。自 TaskList.tsx 拆出。

import { Show, type Setter } from "solid-js";
import type { TaskError, TaskSnapshot } from "../api/client";
import { api, isTerminal } from "../api/client";
import { isDocKind } from "../taskFiles";
import { menuTriggerKey } from "./menuNav";
import RetryMenu from "./RetryMenu";
import TaskDownloads from "./TaskDownloads";
import { t } from "../i18n";

const MIN = 60_000;
const HOUR = 3_600_000;
const DAY = 86_400_000;

/** 相对时间：7 天内用 t.time 模板，超出回退日期；now 由调用方 60s tick 驱动 */
function fmtRel(ts: number, now: number): string {
    const ms = ts < 1e12 ? ts * 1000 : ts;
    const diff = now - ms;
    const n = (v: number, tpl: string) => tpl.replace("{n}", String(v));
    if (diff < MIN) return t.time.justNow;
    if (diff < HOUR) return n(Math.floor(diff / MIN), t.time.minAgo);
    if (diff < DAY) return n(Math.floor(diff / HOUR), t.time.hourAgo);
    if (diff < 7 * DAY) return n(Math.floor(diff / DAY), t.time.dayAgo);
    return new Date(ms).toLocaleDateString();
}

/** 行内 ↻ 重试臂：终态可重跑的状态集（needs_auth 缺 key，走 ⚙ 设置链接） */
export const RETRYABLE = new Set([
    "fault",
    "partial",
    "cancelled",
    "interrupted",
]);

/**
 * 单行任务卡——<For> 行体抽出：↻ 菜单 wrap/trigger ref 收成行内局部量
 * 随行生灭（旧父级 Map 按 task_id 登记 + 行卸载 delete 的账本省掉）；
 * 父级只下传谓词信号（arm/busy/menu-open 判定）与动作回调。
 */
export default function TaskRow(props: {
    task: TaskSnapshot;
    now(): number;
    acting(): string | null;
    deleting(): string | null;
    cleaning(): boolean;
    arm(): string | null;
    retryMenu(): string | null;
    setRetryMenu: Setter<string | null>;
    onOpen(taskId: string): void;
    onCancel(task: TaskSnapshot): void;
    onRetry(task: TaskSnapshot, engine?: string | null): void;
    onDelete(task: TaskSnapshot): void;
}) {
    // 终态 fault/partial 的 error 徽标内容
    const errOf = (x: TaskSnapshot): TaskError | null => {
        if (x.status !== "fault" && x.status !== "partial") return null;
        return x.error ?? null;
    };
    // ↻ 菜单 wrap/trigger——行内局部 ref：Escape 回焦本行触发钮、外点
    // 判定圈在本行 span 内；行卸载（过滤/删除/整表收敛）随组件生灭释放
    let retryWrap: HTMLElement | undefined;
    let retryBtn: HTMLButtonElement | undefined;
    return (
        <div class="task-wrap">
            {/* 真链接 href——中键/复制链接/新标签打开可用；
                onOpen 仍走 hash 路由（同值单 hashchange） */}
            <a
                class="task-row"
                href={`#/reader/${props.task.task_id}`}
                onClick={() => props.onOpen(props.task.task_id)}
            >
                <span class="task-title">
                    {props.task.title ||
                        props.task.arxiv_id ||
                        props.task.task_id}
                </span>
                <span class={`task-status st-${props.task.status}`}>
                    {t.status[props.task.status] ?? props.task.status}
                </span>
                <span class="task-time">
                    {fmtRel(props.task.created_at, props.now())}
                </span>
                <span class="task-meta muted">
                    <span
                        class="task-kind"
                        classList={{
                            "k-doc": isDocKind(props.task.kind),
                        }}
                    >
                        {t.kind[props.task.kind] ?? props.task.kind}
                    </span>
                    <Show when={!isTerminal(props.task.status)}>
                        <span>
                            {t.status[props.task.stage ?? props.task.status] ??
                                props.task.stage ??
                                props.task.status}
                        </span>
                    </Show>
                    {/* 同 arXiv id 重复任务靠 model 区分 */}
                    <Show when={props.task.model}>
                        <span class="task-model">{props.task.model}</span>
                    </Show>
                    <Show when={errOf(props.task)}>
                        {(e) => (
                            <span class="task-err" title={e().message}>
                                [{e().code}]
                            </span>
                        )}
                    </Show>
                    {/* 窄屏换位副本：≤480px 时 .task-time 隐藏、
                    时间落到 meta 行保住可见（responsive.css） */}
                    <span class="task-time-m">
                        {fmtRel(props.task.created_at, props.now())}
                    </span>
                </span>
                <span
                    class="task-bar"
                    role="progressbar"
                    aria-label={
                        props.task.title ||
                        props.task.arxiv_id ||
                        props.task.task_id
                    }
                    aria-valuenow={props.task.progress}
                    aria-valuemin={0}
                    aria-valuemax={100}
                >
                    <i
                        style={{ width: `${props.task.progress}%` }}
                        classList={{
                            done: props.task.status === "done",
                            fail: props.task.status === "fault",
                            dead:
                                props.task.status === "cancelled" ||
                                props.task.status === "interrupted",
                        }}
                    />
                </span>
            </a>
            {/* 行内快捷臂（U8）：在途 ⏻ 取消；可重试终态 ↻；
            needs_auth 缺 key——↻ 原地打转，给 ⚙ 设置入口 */}
            <Show when={!isTerminal(props.task.status)}>
                <button
                    type="button"
                    class="task-act"
                    disabled={props.acting() !== null}
                    title={t.home.cancelTip}
                    aria-label={t.home.cancelTask}
                    onClick={() => void props.onCancel(props.task)}
                >
                    ⏻
                </button>
            </Show>
            <Show when={props.task.status === "needs_auth"}>
                <a
                    class="task-act"
                    href="#/settings"
                    title={t.home.authTip}
                    aria-label={t.home.goSettings}
                >
                    ⚙
                </a>
            </Show>
            <Show when={RETRYABLE.has(props.task.status)}>
                <span
                    class="task-retry"
                    ref={(el) => (retryWrap = el)}
                >
                    <button
                        type="button"
                        class="task-act"
                        ref={(el) => (retryBtn = el)}
                        disabled={props.acting() !== null}
                        title={t.home.retryTip}
                        aria-label={t.home.retry}
                        aria-haspopup="menu"
                        aria-expanded={props.retryMenu() === props.task.task_id}
                        onClick={() =>
                            props.setRetryMenu(
                                props.retryMenu() === props.task.task_id
                                    ? null
                                    : props.task.task_id,
                            )
                        }
                        onKeyDown={(e) =>
                            menuTriggerKey(
                                e,
                                () => props.setRetryMenu(props.task.task_id),
                                () => retryWrap,
                            )
                        }
                    >
                        ↻
                    </button>
                    <Show when={props.retryMenu() === props.task.task_id}>
                        <RetryMenu
                            wrap={() => retryWrap}
                            trigger={() => retryBtn}
                            onClose={() => props.setRetryMenu(null)}
                            onPick={(eng) =>
                                void props.onRetry(props.task, eng)
                            }
                        />
                    </Show>
                </span>
            </Show>
            <Show when={props.task.artifacts?.share_zip}>
                <a
                    class="task-act"
                    href={api.fileUrl(props.task.task_id, "share.zip", {
                        download: true,
                    })}
                    download=""
                    title={t.home.shareZipTip}
                    aria-label={t.home.shareZip}
                >
                    ⤓
                </a>
            </Show>
            <Show when={isTerminal(props.task.status)}>
                <TaskDownloads task={props.task} />
            </Show>
            <button
                type="button"
                class="task-del"
                classList={{
                    busy: props.deleting() === props.task.task_id,
                    arm: props.arm() === props.task.task_id,
                }}
                disabled={
                    !isTerminal(props.task.status) ||
                    props.deleting() !== null ||
                    props.cleaning()
                }
                title={
                    props.arm() === props.task.task_id
                        ? t.home.delConfirm
                        : !isTerminal(props.task.status)
                          ? t.home.delBusy
                          : props.deleting() !== null
                            ? t.home.delWait
                            : t.home.delTip
                }
                aria-label={t.home.del}
                onClick={() => void props.onDelete(props.task)}
            >
                {props.arm() === props.task.task_id ? t.home.delArm : "✕"}
            </button>
        </div>
    );
}
