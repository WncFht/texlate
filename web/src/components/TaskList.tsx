import {
    createMemo,
    createSignal,
    For,
    onCleanup,
    Show,
} from "solid-js";
import type { FileManifest, TaskError, TaskSnapshot } from "../api/client";
import { api, isTerminal } from "../api/client";
import { taskStore } from "../stores/tasks";
import { downloadItems, isDocKind } from "../taskFiles";
import { t } from "../i18n";

interface Props {
    tasks: TaskSnapshot[];
    onOpen(taskId: string): void;
}

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

type Filter = "all" | "active" | "done" | "failed";

/** 「异常」筛选桶：终态里非 done 的全部 */
const FAILED_SET = new Set([
    "fault",
    "partial",
    "cancelled",
    "interrupted",
    "needs_auth",
]);

/** 行内 ↻ 重试臂：终态可重跑的状态集（needs_auth 缺 key，走 ⚙ 设置链接） */
const RETRYABLE = new Set([
    "fault",
    "partial",
    "cancelled",
    "interrupted",
]);

/** ↻ 迷你菜单引擎子项：null=auto（options 不带 engine 键，后端按已存决议） */
const RETRY_ENGINES: { key: string | null; label: string }[] = [
    { key: null, label: t.home.engineAuto },
    { key: "tectonic", label: "tectonic" },
    { key: "xelatex", label: "xelatex" },
    { key: "pdflatex", label: "pdflatex" },
];

/**
 * 终态任务行内产物下载：折叠钮展开直链清单。snapshot.artifacts（SSE
 * done 帧带过）优先；列表行缺 artifacts 时懒拉 files manifest——
 * 但只在用户意图明确后（悬停/聚焦预取，点开必然已发），避免列表
 * 挂载即每行一请求的 N 突发。
 * 锚点必须落在 .task-row <button> 之外——button 内嵌 interactive 非法。
 */
function TaskDownloads(props: { task: TaskSnapshot }) {
    const [open, setOpen] = createSignal(false);
    const [manifest, setManifest] = createSignal<FileManifest | null>(null);
    const [fetching, setFetching] = createSignal(false);
    let tried = false;

    /** 幂等懒拉：首悬停/聚焦即预热，点开时多半已就绪 */
    const ensure = () => {
        if (tried || props.task.artifacts) return;
        tried = true;
        setFetching(true);
        api.files(props.task.task_id)
            .then(setManifest)
            .catch(() => setManifest(null))
            .finally(() => setFetching(false));
    };

    const items = () => {
        const snap = props.task.artifacts;
        if (snap) return downloadItems(snap);
        const m = manifest();
        if (!m) return [];
        return downloadItems(
            Object.fromEntries(
                Object.entries(m.artifacts).map(([k, e]) => [k, e.url]),
            ),
        );
    };

    return (
        <>
            <button
                type="button"
                class="task-dlt"
                aria-expanded={open()}
                title={t.home.dlTitle}
                aria-label={t.home.dlTitle}
                onPointerEnter={ensure}
                onFocus={ensure}
                onClick={() => {
                    ensure();
                    setOpen((v) => !v);
                }}
            >
                ⬇
            </button>
            <Show when={open()}>
                <span class="task-dls">
                    <For each={items()}>
                        {(d) => (
                            <a class="task-dl" href={d.url} download="">
                                {d.label}
                            </a>
                        )}
                    </For>
                    <Show when={!items().length}>
                        <span class="task-dl-empty">
                            {fetching() ? t.home.dlLoading : t.home.dlNone}
                        </span>
                    </Show>
                </span>
            </Show>
        </>
    );
}

export default function TaskList(props: Props) {
    const [deleting, setDeleting] = createSignal<string | null>(null);
    const [delError, setDelError] = createSignal("");
    const [filter, setFilter] = createSignal<Filter>("all");
    const [query, setQuery] = createSignal("");
    const [acting, setActing] = createSignal<string | null>(null);
    const [cleaning, setCleaning] = createSignal(false);
    // ↻ 重试迷你菜单：打开的 task_id（null=全收）
    const [retryMenu, setRetryMenu] = createSignal<string | null>(null);
    // fmtRel 60s tick——相对时间随墙钟刷新，不靠任务事件顺带更新
    const [now, setNow] = createSignal(Date.now());
    const tick = setInterval(() => setNow(Date.now()), 60_000);
    onCleanup(() => clearInterval(tick));

    const FILTERS: { value: Filter; label: string }[] = [
        { value: "all", label: t.home.fAll },
        { value: "active", label: t.home.fActive },
        { value: "done", label: t.home.fDone },
        { value: "failed", label: t.home.fFailed },
    ];

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
            if (f === "failed" && !FAILED_SET.has(task.status)) return false;
            if (q) {
                const hay =
                    `${task.title ?? ""} ${task.arxiv_id ?? ""} ${task.task_id}`.toLowerCase();
                if (!hay.includes(q)) return false;
            }
            return true;
        });
        return [...list].sort((a, b) => {
            const ta = isTerminal(a.status) ? 1 : 0;
            const tb = isTerminal(b.status) ? 1 : 0;
            if (ta !== tb) return ta - tb;
            return b.created_at - a.created_at;
        });
    });

    const doneCount = createMemo(
        () => props.tasks.filter((x) => x.status === "done").length,
    );

    // 终态 fault/partial 的 error 徽标内容
    const errOf = (task: TaskSnapshot): TaskError | null => {
        if (task.status !== "fault" && task.status !== "partial") return null;
        return task.error ?? null;
    };

    const confirmDelete = async (task: TaskSnapshot) => {
        if (!isTerminal(task.status) || deleting() !== null) return;
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

    /** 行内 ⏻：取消在途任务——终态由 SSE/轮询回推，不做本地乐观写 */
    const cancelTask = async (task: TaskSnapshot) => {
        if (isTerminal(task.status) || acting() !== null) return;
        setActing(task.task_id);
        setDelError("");
        try {
            await api.cancel(task.task_id);
        } catch (e) {
            setDelError(e instanceof Error ? e.message : String(e));
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
            setDelError(e instanceof Error ? e.message : String(e));
        } finally {
            setActing(null);
        }
    };

    /** 批量清理已完成：逐行走 taskStore.remove（复用 404 容忍与 dropTask 清理） */
    const cleanDone = async () => {
        if (cleaning() || deleting() !== null || acting() !== null) return;
        if (!window.confirm(t.home.cleanDoneConfirm)) return;
        setCleaning(true);
        setDelError("");
        try {
            for (const task of props.tasks) {
                if (task.status !== "done") continue;
                try {
                    await taskStore.remove(task.task_id);
                } catch {
                    setDelError(t.home.delFailed);
                }
            }
        } finally {
            setCleaning(false);
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
                            </button>
                        )}
                    </For>
                </div>
                <button
                    type="button"
                    class="task-clean"
                    disabled={cleaning() || doneCount() === 0}
                    onClick={() => void cleanDone()}
                >
                    {cleaning() ? t.home.cleanDoneBusy : t.home.cleanDone}
                </button>
            </div>
            <Show when={props.tasks.length === 0}>
                <p class="task-empty">{t.home.empty}</p>
            </Show>
            <Show when={props.tasks.length > 0 && visible().length === 0}>
                <p class="task-empty">{t.home.searchEmpty}</p>
            </Show>
            <For each={visible()}>
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
                            <span class="task-time">
                                {fmtRel(task.created_at, now())}
                            </span>
                            <span class="task-meta muted">
                                <span
                                    class="task-kind"
                                    classList={{
                                        "k-doc": isDocKind(task.kind),
                                    }}
                                >
                                    {t.kind[task.kind] ?? task.kind}
                                </span>
                                <Show when={!isTerminal(task.status)}>
                                    <span>
                                        {t.status[task.stage ?? task.status] ??
                                            task.stage ??
                                            task.status}
                                    </span>
                                </Show>
                                <Show when={errOf(task)}>
                                    {(e) => (
                                        <span
                                            class="task-err"
                                            title={e().message}
                                        >
                                            [{e().code}]
                                        </span>
                                    )}
                                </Show>
                            </span>
                            <span
                                class="task-bar"
                                role="progressbar"
                                aria-label={
                                    task.title || task.arxiv_id || task.task_id
                                }
                                aria-valuenow={task.progress}
                                aria-valuemin={0}
                                aria-valuemax={100}
                            >
                                <i
                                    style={{ width: `${task.progress}%` }}
                                    classList={{
                                        done: task.status === "done",
                                        fail: task.status === "fault",
                                        dead:
                                            task.status === "cancelled" ||
                                            task.status === "interrupted",
                                    }}
                                />
                            </span>
                        </button>
                        {/* 行内快捷臂（U8）：在途 ⏻ 取消；可重试终态 ↻；
                            needs_auth 缺 key——↻ 原地打转，给 ⚙ 设置入口 */}
                        <Show when={!isTerminal(task.status)}>
                            <button
                                type="button"
                                class="task-act"
                                disabled={acting() !== null}
                                title={t.home.cancelTip}
                                aria-label={t.home.cancelTask}
                                onClick={() => void cancelTask(task)}
                            >
                                ⏻
                            </button>
                        </Show>
                        <Show when={task.status === "needs_auth"}>
                            <a
                                class="task-act"
                                href="#/settings"
                                title={t.home.authTip}
                                aria-label={t.home.goSettings}
                            >
                                ⚙
                            </a>
                        </Show>
                        <Show when={RETRYABLE.has(task.status)}>
                            <span class="task-retry">
                                <button
                                    type="button"
                                    class="task-act"
                                    disabled={acting() !== null}
                                    title={t.home.retryTip}
                                    aria-label={t.home.retry}
                                    aria-haspopup="menu"
                                    aria-expanded={
                                        retryMenu() === task.task_id
                                    }
                                    onClick={() =>
                                        setRetryMenu((v) =>
                                            v === task.task_id
                                                ? null
                                                : task.task_id,
                                        )
                                    }
                                >
                                    ↻
                                </button>
                                <Show when={retryMenu() === task.task_id}>
                                    <span class="retry-menu" role="menu">
                                        <button
                                            type="button"
                                            role="menuitem"
                                            class="retry-item"
                                            onClick={() =>
                                                void retryTask(task)
                                            }
                                        >
                                            {t.home.retry}
                                        </button>
                                        <For each={RETRY_ENGINES}>
                                            {(eng) => (
                                                <button
                                                    type="button"
                                                    role="menuitem"
                                                    class="retry-item"
                                                    onClick={() =>
                                                        void retryTask(
                                                            task,
                                                            eng.key,
                                                        )
                                                    }
                                                >
                                                    {t.home.retryAs.replace(
                                                        "{engine}",
                                                        eng.label,
                                                    )}
                                                </button>
                                            )}
                                        </For>
                                    </span>
                                </Show>
                            </span>
                        </Show>
                        <Show when={task.artifacts?.share_zip}>
                            <a
                                class="task-act"
                                href={api.fileUrl(
                                    task.task_id,
                                    "share.zip",
                                    { download: true },
                                )}
                                download=""
                                title={t.home.shareZipTip}
                                aria-label={t.home.shareZip}
                            >
                                ⤓
                            </a>
                        </Show>
                        <Show when={isTerminal(task.status)}>
                            <TaskDownloads task={task} />
                        </Show>
                        <button
                            type="button"
                            class="task-del"
                            classList={{ busy: deleting() === task.task_id }}
                            disabled={
                                !isTerminal(task.status) || deleting() !== null
                            }
                            title={
                                !isTerminal(task.status)
                                    ? t.home.delBusy
                                    : deleting() !== null
                                      ? t.home.delWait
                                      : t.home.delTip
                            }
                            aria-label={t.home.del}
                            onClick={() => void confirmDelete(task)}
                        >
                            ✕
                        </button>
                    </div>
                )}
            </For>
            <Show when={delError()}>
                <p class="task-del-err" role="alert">
                    {delError()}
                </p>
            </Show>
        </div>
    );
}
