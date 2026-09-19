import {
    createEffect,
    createMemo,
    createSignal,
    For,
    onCleanup,
    onMount,
    Show,
} from "solid-js";
import type { FileManifest, TaskError, TaskSnapshot } from "../api/client";
import { api, isTerminal } from "../api/client";
import { taskStore } from "../stores/tasks";
import { downloadItems, isDocKind } from "../taskFiles";
import { fmtBytes } from "../reader/paneUtils";
import { bindMenuDismiss, menuRoving, menuTriggerKey } from "./menuNav";
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

/** 「未完成」筛选桶：终态里非 done 的全部 */
const FAILED_SET = new Set([
    "fault",
    "partial",
    "cancelled",
    "interrupted",
    "needs_auth",
]);

/** 行内 ↻ 重试臂：终态可重跑的状态集（needs_auth 缺 key，走 ⚙ 设置链接） */
const RETRYABLE = new Set(["fault", "partial", "cancelled", "interrupted"]);

/** ↻ 迷你菜单引擎子项：null=auto（options 不带 engine 键，后端按已存决议） */
const RETRY_ENGINES: { key: string | null; label: string }[] = [
    { key: null, label: t.home.engineAuto },
    { key: "tectonic", label: "tectonic" },
    { key: "xelatex", label: "xelatex" },
    { key: "pdflatex", label: "pdflatex" },
];

/**
 * ↻ 重试迷你菜单本体——仅打开期挂载，dismiss 监听（外点/Escape）随
 * 组件生灭不占全局；roving/Tab 走 menuNav 共享契约。
 * onPick(undefined)=裸重试、null=auto、字符串=指定引擎。
 */
function RetryMenu(props: {
    wrap(): HTMLElement | undefined;
    trigger(): HTMLElement | undefined;
    onClose(): void;
    onPick(engine?: string | null): void;
}) {
    bindMenuDismiss({
        open: () => true,
        close: () => props.onClose(),
        wrap: () => props.wrap(),
        trigger: () => props.trigger(),
    });
    return (
        <span
            class="retry-menu"
            role="menu"
            onKeyDown={(e) => menuRoving(e, props.onClose)}
        >
            <button
                type="button"
                role="menuitem"
                tabIndex={-1}
                class="retry-item"
                onClick={() => props.onPick()}
            >
                {t.home.retry}
            </button>
            <For each={RETRY_ENGINES}>
                {(eng) => (
                    <button
                        type="button"
                        role="menuitem"
                        tabIndex={-1}
                        class="retry-item"
                        onClick={() => props.onPick(eng.key)}
                    >
                        {t.home.retryAs.replace("{engine}", eng.label)}
                    </button>
                )}
            </For>
        </span>
    );
}

/**
 * 终态任务行内产物下载：折叠钮展开直链清单。snapshot.artifacts（SSE
 * done 帧带过）优先；列表行缺 artifacts 时懒拉 files manifest——
 * 但只在用户意图明确后（悬停/聚焦预取，点开必然已发），避免列表
 * 挂载即每行一请求的 N 突发。
 * 快捷臂必须落在 .task-row <a> 之外——a 内嵌 interactive 非法。
 */
function TaskDownloads(props: { task: TaskSnapshot }) {
    const [open, setOpen] = createSignal(false);
    const [manifest, setManifest] = createSignal<FileManifest | null>(null);
    const [fetching, setFetching] = createSignal(false);
    let tried = false;

    /** 幂等懒拉：首悬停/聚焦即预热，点开时多半已就绪；失败不留死闸可重试 */
    const ensure = () => {
        if (tried || props.task.artifacts) return;
        tried = true;
        setFetching(true);
        api.files(props.task.task_id)
            .then(setManifest)
            .catch(() => {
                tried = false;
                setManifest(null);
            })
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

/**
 * 「删除已结束任务」确认框——docker prune 式：明说删什么、可选范围、
 * 显式确认，替代旧的工具行两击臂（按钮文案当确认太隐晦）。
 * 焦点默认落取消钮防 Enter 误触；busy 期禁取消（删除已在飞）。
 */
function PurgeDialog(props: {
    doneCount: number;
    failedCount: number;
    busy: boolean;
    onCancel(): void;
    onConfirm(sel: { done: boolean; failed: boolean }): void;
}) {
    const [selDone, setSelDone] = createSignal(true);
    const [selFailed, setSelFailed] = createSignal(true);
    const n = () =>
        (selDone() ? props.doneCount : 0) +
        (selFailed() ? props.failedCount : 0);
    let cancelBtn: HTMLButtonElement | undefined;
    onMount(() => {
        cancelBtn?.focus();
        const esc = (e: KeyboardEvent) => {
            if (e.key === "Escape" && !props.busy) props.onCancel();
        };
        document.addEventListener("keydown", esc);
        onCleanup(() => document.removeEventListener("keydown", esc));
    });
    return (
        <div
            class="purge-veil"
            onClick={(e) => {
                if (e.target === e.currentTarget && !props.busy) {
                    props.onCancel();
                }
            }}
        >
            <div
                class="purge-box"
                role="alertdialog"
                aria-modal="true"
                aria-label={t.home.purgeTitle}
            >
                <h2 class="purge-title">{t.home.purgeTitle}</h2>
                <p class="purge-desc">{t.home.purgeDesc}</p>
                <div class="purge-opts">
                    <label class="purge-opt">
                        <input
                            type="checkbox"
                            checked={selDone()}
                            disabled={props.busy || props.doneCount === 0}
                            onChange={(e) =>
                                setSelDone(e.currentTarget.checked)
                            }
                        />
                        {t.home.purgeScopeDone.replace(
                            "{n}",
                            String(props.doneCount),
                        )}
                    </label>
                    <label class="purge-opt">
                        <input
                            type="checkbox"
                            checked={selFailed()}
                            disabled={props.busy || props.failedCount === 0}
                            onChange={(e) =>
                                setSelFailed(e.currentTarget.checked)
                            }
                        />
                        {t.home.purgeScopeFailed.replace(
                            "{n}",
                            String(props.failedCount),
                        )}
                    </label>
                </div>
                <div class="purge-foot">
                    <button
                        type="button"
                        class="btn-ghost purge-cancel"
                        ref={(el) => (cancelBtn = el)}
                        disabled={props.busy}
                        onClick={() => props.onCancel()}
                    >
                        {t.home.cancel}
                    </button>
                    <button
                        type="button"
                        class="btn-primary purge-confirm"
                        disabled={props.busy || n() === 0}
                        onClick={() =>
                            props.onConfirm({
                                done: selDone(),
                                failed: selFailed(),
                            })
                        }
                    >
                        {props.busy
                            ? t.home.purgeBusy
                            : t.home.purgeDo.replace("{n}", String(n()))}
                    </button>
                </div>
            </div>
        </div>
    );
}

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
    // ↻ 重试迷你菜单：打开的 task_id（null=全收）；wrap/trigger ref 按行登记
    // ——Escape 焦点回正确行的钮、外点判定圈在本行 span 内
    const [retryMenu, setRetryMenu] = createSignal<string | null>(null);
    const retryWraps = new Map<string, HTMLElement>();
    const retryBtns = new Map<string, HTMLButtonElement>();
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
            .catch(() => setEstBytes(null));
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
            if (FAILED_SET.has(x.status)) c.failed++;
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

    const termCount = createMemo(
        () => props.tasks.filter((x) => isTerminal(x.status)).length,
    );

    // 终态 fault/partial 的 error 徽标内容
    const errOf = (task: TaskSnapshot): TaskError | null => {
        if (task.status !== "fault" && task.status !== "partial") return null;
        return task.error ?? null;
    };

    const confirmDelete = async (task: TaskSnapshot) => {
        if (!isTerminal(task.status) || deleting() !== null || cleaning()) {
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

    /** 清理中间文件：POST /tasks/slim——只清 workdir 未登记字节
     *  （产物/记录全留），非破坏操作不需要确认；结果落 notice 行。 */
    const slimAll = async () => {
        if (cleaning() || deleting() !== null || acting() !== null) return;
        setCleaning(true);
        setDelError("");
        setNotice("");
        try {
            const r = await api.slimTasks();
            setEstBytes(0); // 预估失效——刚清完下拍近乎为 0
            setNotice(
                r.freed_bytes > 0
                    ? t.home.slimFreed.replace("{size}", fmtBytes(r.freed_bytes))
                    : t.home.slimNone,
            );
        } catch (e) {
            setDelError(e instanceof Error ? e.message : String(e));
        } finally {
            setCleaning(false);
        }
    };

    /** 删除已结束：确认框选定范围后逐行走 taskStore.remove（复用 404 容忍
     *  与 dropTask 清理）。删的是产物+记录本身，非瘦身——busy 期对话框
     *  保持开着让用户看见在删，结束才收。 */
    const purge = async (sel: { done: boolean; failed: boolean }) => {
        if (cleaning() || deleting() !== null || acting() !== null) return;
        setCleaning(true);
        setDelError("");
        setNotice("");
        let n = 0;
        try {
            for (const task of props.tasks) {
                const hit =
                    (task.status === "done" && sel.done) ||
                    (FAILED_SET.has(task.status) && sel.failed);
                if (!hit) continue;
                try {
                    await taskStore.remove(task.task_id);
                    n++;
                } catch {
                    setDelError(t.home.delFailed);
                }
            }
            if (n) {
                setNotice(t.home.purgeDone.replace("{n}", String(n)));
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
                                <Show when={!cleaning() && (estBytes() ?? 0) > 0}>
                                    <span class="menu-hint">
                                        {t.home.maintSlimEst.replace(
                                            "{size}",
                                            fmtBytes(estBytes()!),
                                        )}
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
                                    {t.home.purgeN.replace(
                                        "{n}",
                                        String(termCount()),
                                    )}
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
            <For each={visible()}>
                {(task) => {
                    // 行卸载（过滤/删除/整表收敛）即释放登记的行 DOM——
                    // ref 只 set 不 delete 会把已移除行的元素挂在 Map 里
                    onCleanup(() => {
                        retryWraps.delete(task.task_id);
                        retryBtns.delete(task.task_id);
                    });
                    return (
                        <div class="task-wrap">
                            {/* 真链接 href——中键/复制链接/新标签打开可用；
                                onOpen 仍走 hash 路由（同值单 hashchange） */}
                            <a
                                class="task-row"
                                href={`#/reader/${task.task_id}`}
                                onClick={() => props.onOpen(task.task_id)}
                            >
                                <span class="task-title">
                                    {task.title ||
                                        task.arxiv_id ||
                                        task.task_id}
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
                                            {t.status[
                                                task.stage ?? task.status
                                            ] ??
                                                task.stage ??
                                                task.status}
                                        </span>
                                    </Show>
                                    {/* 同 arXiv id 重复任务靠 model 区分 */}
                                    <Show when={task.model}>
                                        <span class="task-model">
                                            {task.model}
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
                                    {/* 窄屏换位副本：≤480px 时 .task-time 隐藏、
                                    时间落到 meta 行保住可见（responsive.css） */}
                                    <span class="task-time-m">
                                        {fmtRel(task.created_at, now())}
                                    </span>
                                </span>
                                <span
                                    class="task-bar"
                                    role="progressbar"
                                    aria-label={
                                        task.title ||
                                        task.arxiv_id ||
                                        task.task_id
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
                            </a>
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
                                <span
                                    class="task-retry"
                                    ref={(el) => {
                                        retryWraps.set(task.task_id, el);
                                    }}
                                >
                                    <button
                                        type="button"
                                        class="task-act"
                                        ref={(el) => {
                                            retryBtns.set(task.task_id, el);
                                        }}
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
                                        onKeyDown={(e) =>
                                            menuTriggerKey(
                                                e,
                                                () =>
                                                    setRetryMenu(task.task_id),
                                                () =>
                                                    retryWraps.get(
                                                        task.task_id,
                                                    ),
                                            )
                                        }
                                    >
                                        ↻
                                    </button>
                                    <Show when={retryMenu() === task.task_id}>
                                        <RetryMenu
                                            wrap={() =>
                                                retryWraps.get(task.task_id)
                                            }
                                            trigger={() =>
                                                retryBtns.get(task.task_id)
                                            }
                                            onClose={() => setRetryMenu(null)}
                                            onPick={(eng) =>
                                                void retryTask(task, eng)
                                            }
                                        />
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
                                classList={{
                                    busy: deleting() === task.task_id,
                                    arm: arm() === task.task_id,
                                }}
                                disabled={
                                    !isTerminal(task.status) ||
                                    deleting() !== null ||
                                    cleaning()
                                }
                                title={
                                    arm() === task.task_id
                                        ? t.home.delConfirm
                                        : !isTerminal(task.status)
                                          ? t.home.delBusy
                                          : deleting() !== null
                                            ? t.home.delWait
                                            : t.home.delTip
                                }
                                aria-label={t.home.del}
                                onClick={() => void confirmDelete(task)}
                            >
                                {arm() === task.task_id ? t.home.delArm : "✕"}
                            </button>
                        </div>
                    );
                }}
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
