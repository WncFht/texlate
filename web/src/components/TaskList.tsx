import {
    createEffect,
    createMemo,
    createSignal,
    For,
    onCleanup,
    Show,
} from "solid-js";
import type { TaskSnapshot, TaskStatus } from "../api/client";
import { api, errText, isTerminal } from "../api/client";
import { taskStore } from "../stores/tasks";
import { fmtBytes } from "../reader/paneUtils";
import { bindMenuDismiss, menuRoving, menuTriggerKey } from "./menuNav";
import PurgeDialog from "./PurgeDialog";
import TaskRow, { RETRYABLE } from "./TaskRow";
import { fmt, t } from "../i18n";

interface Props {
    tasks: TaskSnapshot[];
    onOpen(taskId: string): void;
}

type Filter = "all" | "active" | "done" | "failed";

/** 「未完成」筛选桶：终态里非 done 的全部——由 TERMINAL 派生不另立清单
 *  （TaskRow RETRYABLE = 本桶 − needs_auth；单源待 hoist 到 api/types.ts） */
const isFailed = (s: TaskStatus): boolean => isTerminal(s) && s !== "done";

export default function TaskList(props: Props) {
    const [deleting, setDeleting] = createSignal<string | null>(null);
    const [delError, setDelError] = createSignal("");
    const [notice, setNotice] = createSignal("");
    const [filter, setFilter] = createSignal<Filter>("all");
    const [query, setQuery] = createSignal("");
    const [acting, setActing] = createSignal<string | null>(null);
    const [cleaning, setCleaning] = createSignal(false);
    // 删除两击确认：第一击 arm ~3.2s（超时自动复位），第二击才执行
    const [arm, setArm] = createSignal<string | null>(null);
    let armTimer = 0;
    const armOnce = (key: string) => {
        setArm(key);
        window.clearTimeout(armTimer);
        armTimer = window.setTimeout(() => setArm(null), 3200);
    };
    const disarm = () => {
        window.clearTimeout(armTimer);
        setArm(null);
    };
    // ↻ 重试迷你菜单：打开的 task_id（null=全收）；wrap/trigger ref
    // 随 TaskRow 收进行内局部量（Escape 回焦/外点判定契约不变）
    const [retryMenu, setRetryMenu] = createSignal<string | null>(null);
    // 「清理 ▾」维护菜单 + 删除确认框；estBytes=slim dry-run 预估（开菜单懒拉）
    const [maintOpen, setMaintOpen] = createSignal(false);
    const [purgeOpen, setPurgeOpen] = createSignal(false);
    const [estBytes, setEstBytes] = createSignal<number | null>(null);
    let estTried = false;
    let maintWrap: HTMLSpanElement | undefined;
    let maintBtn: HTMLButtonElement | undefined;
    bindMenuDismiss({
        open: maintOpen,
        close: () => setMaintOpen(false),
        wrap: () => maintWrap,
        trigger: () => maintBtn,
    });
    createEffect(() => {
        if (!maintOpen() || estTried) return;
        estTried = true;
        api.slimTasks({ dry: true })
            .then((r) => setEstBytes(r.freed_bytes))
            .catch(() => {
                estTried = false; // 失败不锁死——下次开菜单重拉 dry-run
                setEstBytes(null);
            });
    });
    // fmtRel 60s tick——相对时间随墙钟刷新，不靠任务事件顺带更新
    const [now, setNow] = createSignal(Date.now());
    const tick = setInterval(() => setNow(Date.now()), 60_000);
    onCleanup(() => {
        clearInterval(tick);
        window.clearTimeout(armTimer);
    });

    const FILTERS: { value: Filter; label: string }[] = [
        { value: "all", label: t.home.fAll },
        { value: "active", label: t.home.fActive },
        { value: "done", label: t.home.fDone },
        { value: "failed", label: t.home.fFailed },
    ];

    /** 各筛选桶容量——chip 计数徽（扫一眼知有没有活） */
    const counts = createMemo(() => {
        const c = { all: props.tasks.length, active: 0, done: 0, failed: 0 };
        for (const x of props.tasks) {
            if (!isTerminal(x.status)) c.active++;
            if (x.status === "done") c.done++;
            if (isFailed(x.status)) c.failed++;
        }
        return c;
    });

    /**
     * 可见行 = 筛选桶 ∩ 搜索子串；活动任务恒置顶（pin 分组），组内按
     * created_at 新→旧。<For> 按行引用 diff——store 侧 reconcile/patch
     * 保引用（M9），这里排序只挪 DOM 不重挂行。
     */
    const visible = createMemo(() => {
        const q = query().trim().toLowerCase();
        const f = filter();
        const list = props.tasks.filter((task) => {
            if (f === "active" && isTerminal(task.status)) return false;
            if (f === "done" && task.status !== "done") return false;
            if (f === "failed" && !isFailed(task.status)) return false;
            if (q) {
                const hay =
                    `${task.title ?? ""} ${task.arxiv_id ?? ""} ${task.task_id}`.toLowerCase();
                if (!hay.includes(q)) return false;
            }
            return true;
        });
        return list.sort((a, b) => {
            const ta = isTerminal(a.status) ? 1 : 0;
            const tb = isTerminal(b.status) ? 1 : 0;
            if (ta !== tb) return ta - tb;
            return b.created_at - a.created_at;
        });
    });

    const termCount = createMemo(
        () => props.tasks.filter((x) => isTerminal(x.status)).length,
    );

    /** 任一互斥操作在途（行内取消/重试 acting、删除 deleting、清理 cleaning）——
     *  slim/purge/删除入口共用一把锁，防并行提交互相踩 */
    const busy = () => cleaning() || deleting() !== null || acting() !== null;

    const confirmDelete = async (task: TaskSnapshot) => {
        if (!isTerminal(task.status) || busy()) {
            return;
        }
        if (arm() !== task.task_id) {
            armOnce(task.task_id);
            return;
        }
        disarm();
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

    /** 行内 ⏻：取消在途任务——终态由 SSE/轮询回推，不做本地乐观写 */
    const cancelTask = async (task: TaskSnapshot) => {
        if (isTerminal(task.status) || acting() !== null) return;
        if (!window.confirm(t.progress.cancelConfirm)) return;
        setActing(task.task_id);
        setDelError("");
        try {
            await api.cancel(task.task_id);
        } catch (e) {
            setDelError(errText(e));
        } finally {
            setActing(null);
        }
    };

    /** 行内 ↻：retry 复用 task_id——resetLive 清上轮痕迹重订阅，refresh 拉新快照。
     *  engine 三态：undefined=裸重试（沿用已存 engine_resolved）；null=auto
     *  （options 不带 engine 键）；字符串=指定引擎重决议。 */
    const retryTask = async (task: TaskSnapshot, engine?: string | null) => {
        if (!RETRYABLE.has(task.status) || acting() !== null) return;
        setActing(task.task_id);
        setRetryMenu(null);
        setDelError("");
        try {
            await (engine === undefined
                ? api.retry(task.task_id)
                : api.retry(task.task_id, {
                      options: engine === null ? {} : { engine },
                  }));
            taskStore.resetLive(task.task_id);
            void taskStore.refresh();
        } catch (e) {
            setDelError(errText(e));
        } finally {
            setActing(null);
        }
    };

    /** 清理中间文件：POST /tasks/slim——只清 workdir 未登记字节
     *  （产物/记录全留），非破坏操作不需要确认；结果落 notice 行。 */
    const slimAll = async () => {
        if (busy()) return;
        setCleaning(true);
        setDelError("");
        setNotice("");
        try {
            const r = await api.slimTasks();
            setEstBytes(0); // 预估失效——刚清完下拍近乎为 0
            setNotice(
                r.freed_bytes > 0
                    ? fmt(t.home.slimFreed, { size: fmtBytes(r.freed_bytes) })
                    : t.home.slimNone,
            );
        } catch (e) {
            setDelError(errText(e));
        } finally {
            setCleaning(false);
        }
    };

    /** 删除已结束：确认框选定范围后逐行走 taskStore.remove（复用 404 容忍
     *  与 dropTask 清理）。删的是产物+记录本身，非瘦身——busy 期对话框
     *  保持开着让用户看见在删，结束才收。 */
    const purge = async (sel: { done: boolean; failed: boolean }) => {
        if (busy()) return;
        setCleaning(true);
        setDelError("");
        setNotice("");
        let n = 0;
        try {
            for (const task of props.tasks) {
                const hit =
                    (task.status === "done" && sel.done) ||
                    (isFailed(task.status) && sel.failed);
                if (!hit) continue;
                try {
                    await taskStore.remove(task.task_id);
                    n++;
                } catch {
                    setDelError(t.home.delFailed);
                }
            }
            if (n) {
                setNotice(fmt(t.home.purgeDone, { n }));
            }
        } finally {
            setCleaning(false);
            setPurgeOpen(false);
        }
    };

    return (
        <div class="task-list">
            <div class="task-tools">
                <input
                    class="task-search"
                    type="search"
                    placeholder={t.home.search}
                    aria-label={t.home.searchLabel}
                    value={query()}
                    onInput={(e) => setQuery(e.currentTarget.value)}
                />
                <div class="task-chips" role="group" aria-label={t.home.tasks}>
                    <For each={FILTERS}>
                        {(f) => (
                            <button
                                type="button"
                                class="task-chip"
                                classList={{ on: filter() === f.value }}
                                aria-pressed={filter() === f.value}
                                onClick={() => setFilter(f.value)}
                            >
                                {f.label}
                                <span class="chip-n">{counts()[f.value]}</span>
                            </button>
                        )}
                    </For>
                </div>
                {/* 「清理 ▾」维护菜单——安全项（清中间文件）直接跑并出结果，
                    破坏项（删已结束）收进确认框；预估字节开菜单时 dry-run 懒拉 */}
                <span class="task-maint" ref={(el) => (maintWrap = el)}>
                    <button
                        type="button"
                        class="task-clean"
                        ref={(el) => (maintBtn = el)}
                        aria-haspopup="menu"
                        aria-expanded={maintOpen()}
                        title={t.home.maintTip}
                        onClick={() => setMaintOpen((v) => !v)}
                        onKeyDown={(e) =>
                            menuTriggerKey(
                                e,
                                () => setMaintOpen(true),
                                () => maintWrap,
                            )
                        }
                    >
                        {t.home.maint} ▾
                    </button>
                    <Show when={maintOpen()}>
                        <span
                            class="retry-menu maint-menu"
                            role="menu"
                            onKeyDown={(e) =>
                                menuRoving(e, () => setMaintOpen(false))
                            }
                        >
                            <button
                                type="button"
                                role="menuitem"
                                tabIndex={-1}
                                class="retry-item maint-slim"
                                disabled={cleaning()}
                                title={t.home.slimTip}
                                onClick={() => {
                                    setMaintOpen(false);
                                    void slimAll();
                                }}
                            >
                                {cleaning()
                                    ? t.home.slimBusy
                                    : t.home.maintSlim}
                                <Show
                                    when={!cleaning() && (estBytes() ?? 0) > 0}
                                >
                                    <span class="menu-hint">
                                        {fmt(t.home.maintSlimEst, {
                                            size: fmtBytes(estBytes()!),
                                        })}
                                    </span>
                                </Show>
                            </button>
                            <button
                                type="button"
                                role="menuitem"
                                tabIndex={-1}
                                class="retry-item danger maint-purge"
                                disabled={termCount() === 0 || cleaning()}
                                title={t.home.purgeTip}
                                onClick={() => {
                                    setMaintOpen(false);
                                    setPurgeOpen(true);
                                }}
                            >
                                {t.home.maintPurge}
                                <span class="menu-hint">
                                    {fmt(t.home.purgeN, { n: termCount() })}
                                </span>
                            </button>
                        </span>
                    </Show>
                </span>
            </div>
            <Show when={props.tasks.length === 0}>
                <p class="task-empty">{t.home.empty}</p>
            </Show>
            <Show when={props.tasks.length > 0 && visible().length === 0}>
                <p class="task-empty">{t.home.searchEmpty}</p>
            </Show>
            {/* 行体已抽为 TaskRow——谓词信号直传、行内 ↻ ref 自理 */}
            <For each={visible()}>
                {(task) => (
                    <TaskRow
                        task={task}
                        now={now}
                        acting={acting}
                        deleting={deleting}
                        cleaning={cleaning}
                        arm={arm}
                        retryMenu={retryMenu}
                        setRetryMenu={setRetryMenu}
                        onOpen={props.onOpen}
                        onCancel={cancelTask}
                        onRetry={retryTask}
                        onDelete={confirmDelete}
                    />
                )}
            </For>
            <Show when={delError()}>
                <p class="task-del-err" role="alert">
                    {delError()}
                </p>
            </Show>
            <Show when={notice()}>
                <p class="task-note">{notice()}</p>
            </Show>
            <Show when={purgeOpen()}>
                <PurgeDialog
                    doneCount={counts().done}
                    failedCount={counts().failed}
                    busy={cleaning()}
                    onCancel={() => setPurgeOpen(false)}
                    onConfirm={(sel) => void purge(sel)}
                />
            </Show>
        </div>
    );
}
