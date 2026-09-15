// Reader —— 阅读器外壳 + 任务进度视图（任务状态机驱动页面流转，§5.2）。
// 活动状态 → 阶段步进 + 段落棋盘格 + 日志抽屉；终态 → 三模式阅读器。
// 双栏：每侧按 doc.version keyed 重挂（usePDFSlick 无清理，§5.1 坑）。

import { createEffect, createMemo, createSignal, onCleanup, onMount, Show, For } from "solid-js";
import {
    api,
    isTerminal,
    type DualJson,
    type FileKind,
    type FileManifest,
    type ReaderInfo,
    type TaskSnapshot,
    type TaskStage,
} from "../api/client";
import { taskStore } from "../stores/tasks";
import Toolbar, { type DownloadItem, type Mode } from "../components/Toolbar";
import ProgressGrid from "../components/ProgressGrid";
import PdfPane, { type PaneHandle } from "../reader/PdfPane";
import HtmlPane, { type HtmlPaneHandle } from "../reader/HtmlPane";
import { createPositionMapper, type DocId, type Pos } from "../reader/alignment";
import { capturePos, jumpTo, scrollTopFor, SyncEngine } from "../reader/sync";
import { t } from "../i18n/zh";

const STAGES: TaskStage[] = ["fetching", "parsing", "translating", "compiling"];
const JUMPBACK_PX = 500;
const SAVE_DEBOUNCE_MS = 1000;
const DOWNLOAD_ORDER: FileKind[] = [
    "zh.pdf",
    "en.pdf",
    "dual.pdf",
    "dual.json",
    "zh-src.zip",
    "compile.log",
    "md",
    "src.tar",
];

type AnyHandle = PaneHandle | HtmlPaneHandle;

export default function Reader(props: { taskId: string; nav(to: string): void }) {
    const [task, setTask] = createSignal<TaskSnapshot | null>(null);
    const [info, setInfo] = createSignal<ReaderInfo | null>(null);
    const [dual, setDual] = createSignal<DualJson | null>(null);
    const [manifest, setManifest] = createSignal<FileManifest | null>(null);
    const [mode, setMode] = createSignal<Mode>("split");
    const [syncing, setSyncing] = createSignal(true);
    const [zoom, setZoom] = createSignal("page-width");
    const [active, setActive] = createSignal<DocId>("original");
    const [swapped, setSwapped] = createSignal(false);
    const [pageNums, setPageNums] = createSignal<Record<DocId, number>>({
        original: 1,
        translated: 1,
    });
    const [drift, setDrift] = createSignal<Partial<Record<DocId, boolean>>>({});
    const [fatal, setFatal] = createSignal("");
    const [handles, setHandles] = createSignal<Partial<Record<DocId, AnyHandle>>>({});

    let engine: SyncEngine | null = null;
    let pendingJump: { from: DocId; pos: Pos } | null = null;
    const restoredSides = new Set<DocId>();
    let saveTimer = 0;

    // ---------- 数据装载 ----------

    const loadReader = async () => {
        try {
            const [r, files] = await Promise.all([
                api.reader(props.taskId),
                api.files(props.taskId).catch(() => null),
            ]);
            setInfo(r);
            setManifest(files);
            // dual.json 同时提供 alignment 兜底与 chunks（HTML 视图必需）
            const dj = await fetch(api.fileUrl(props.taskId, "dual.json"))
                .then((res) => (res.ok ? (res.json() as Promise<DualJson>) : null))
                .catch(() => null);
            setDual(dj);
            const rd = r.reading;
            if (rd) {
                if (rd.mode) setMode(rd.mode);
                if (rd.sync !== undefined) setSyncing(rd.sync);
                if (rd.zoom) setZoom(rd.zoom);
                if (rd.active) setActive(rd.active);
            }
        } catch (e) {
            setFatal(e instanceof Error ? e.message : String(e));
        }
    };

    onMount(async () => {
        try {
            const snap = await api.snapshot(props.taskId);
            setTask(snap);
            if (isTerminal(snap.status)) {
                await loadReader();
            } else {
                taskStore.watch(props.taskId);
            }
        } catch (e) {
            setFatal(e instanceof Error ? e.message : String(e));
        }
    });

    // SSE：任务在 store 里被 watch；终态到达 → 装阅读器
    createEffect(() => {
        const done = taskStore.live(props.taskId)?.done;
        if (done && !info()) void loadReader();
        const snap = taskStore.task(props.taskId);
        if (snap) setTask(snap);
    });

    onCleanup(() => {
        engine?.dispose();
        window.clearTimeout(saveTimer);
    });

    // ---------- 同步引擎 ----------

    const pageCounts = createMemo(() => {
        const i = info();
        const d = dual();
        if (!i) return { original: 1, translated: 1 };
        if (i.view === "html") {
            const n = Math.max(d?.chunks?.length ?? 1, 1);
            return { original: n, translated: n };
        }
        return {
            original: i.documents.original.pages,
            translated: i.documents.translated.pages,
        };
    });

    const mapper = createMemo(() =>
        createPositionMapper(dual()?.alignment ?? info()?.alignment, pageCounts()),
    );

    /** split + 两侧 handle 就位 → 建引擎；否则销毁（handles() 是响应源） */
    createEffect(() => {
        engine?.dispose();
        engine = null;
        if (mode() !== "split") return;
        const a = handles().original;
        const b = handles().translated;
        if (!a || !b) return;
        const e = new SyncEngine(a, b, mapper());
        e.syncing = syncing();
        engine = e;
        onCleanup(() => e.dispose());
    });

    const setSync = (on: boolean) => {
        setSyncing(on);
        if (engine) {
            engine.syncing = on;
            if (on) {
                const src = handles()[active()] ?? handles().original;
                if (src) engine.alignNow(src);
            }
        }
        if (!on) updateDrift();
    };

    // ---------- 模式切换保位置（texglot planModeChange） ----------

    const planModeChange = (next: Mode) => {
        if (next === mode()) return;
        const src = handles()[active()] ?? handles().original ?? handles().translated;
        if (src) pendingJump = { from: src.side, pos: capturePos(src) };
        setMode(next);
    };

    const paneReady = (side: DocId, h: AnyHandle) => {
        setHandles((prev) => ({ ...prev, [side]: h }));
        if (pendingJump) {
            // 模式切换补偿：对侧位置映射过来
            const { from, pos } = pendingJump;
            pendingJump = null;
            const target = from === side ? pos : mapper()(pos, from);
            requestAnimationFrame(() => h.jump(target));
        } else if (!restoredSides.has(side)) {
            const saved = info()?.reading?.positions?.[side];
            if (saved) queueMicrotask(() => h.jump(saved));
        } else if (engine?.syncing && side !== active()) {
            engine.alignNow(handles()[active()] ?? h);
        }
        restoredSides.add(side);
    };

    const paneDisposed = (side: DocId, h: AnyHandle) =>
        setHandles((prev) => {
            if (prev[side] !== h) return prev;
            const next = { ...prev };
            delete next[side];
            return next;
        });

    const paneVisible = (side: DocId) => mode() === "split" || mode() === side;

    // ---------- 位置持久化 + >500px 跳回 ----------

    const persistPosition = () => {
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(() => {
            const positions: Partial<Record<DocId, Pos>> = {};
            for (const side of ["original", "translated"] as const) {
                const h = handles()[side];
                if (h && paneVisible(side)) positions[side] = capturePos(h);
            }
            void api
                .putPosition(props.taskId, {
                    positions,
                    active: active(),
                    mode: mode(),
                    zoom: zoom(),
                    sync: syncing(),
                })
                .catch(() => undefined);
        }, SAVE_DEBOUNCE_MS);
    };

    /** 同步关闭时：任一侧与"对侧映射来的期望位置"漂移 >500px → 显示跳回按钮 */
    const updateDrift = () => {
        if (mode() !== "split" || syncing()) {
            setDrift({});
            return;
        }
        const next: Partial<Record<DocId, boolean>> = {};
        for (const side of ["original", "translated"] as const) {
            const me = handles()[side];
            const otherSide: DocId = side === "original" ? "translated" : "original";
            const src = handles()[otherSide];
            if (!me || !src) continue;
            const expected = scrollTopFor(me, mapper()(capturePos(src), otherSide));
            next[side] = expected !== null && Math.abs(me.el.scrollTop - expected) > JUMPBACK_PX;
        }
        setDrift(next);
    };

    const jumpBack = (side: DocId) => {
        const me = handles()[side];
        const otherSide: DocId = side === "original" ? "translated" : "original";
        const src = handles()[otherSide];
        if (!me || !src) return;
        jumpTo(me, mapper()(capturePos(src), otherSide));
        setDrift((d) => ({ ...d, [side]: false }));
        persistPosition();
    };

    const onUserScroll = () => {
        persistPosition();
        updateDrift();
    };

    // ---------- 缩放 / 页码 / 下载 ----------

    const applyZoom = (z: string) => {
        setZoom(z);
        for (const side of ["original", "translated"] as const) {
            const h = handles()[side] as PaneHandle | undefined;
            if (!h?.setScaleValue) continue;
            if (z.endsWith("%")) h.setScale(Number(z.slice(0, -1)) / 100);
            else h.setScaleValue(z);
        }
        persistPosition();
    };

    const gotoPage = (n: number) => {
        const h = handles()[active()] as PaneHandle | undefined;
        h?.gotoPage?.(n);
    };

    const downloads = createMemo<DownloadItem[]>(() => {
        const m = manifest();
        if (!m) return [];
        return DOWNLOAD_ORDER.filter((k) => k in m.artifacts).map((kind) => ({
            kind,
            label: t.files[kind] ?? kind,
            url: api.fileUrl(props.taskId, kind, { download: true }),
        }));
    });

    const docUrl = (side: DocId) => {
        const i = info();
        if (!i) return "";
        const doc = i.documents[side];
        const kind: FileKind = side === "original" ? "en.pdf" : "zh.pdf";
        // 优先服务端给的 url；否则按 files 约定拼（带版本校验防旧版，§2.3）
        return doc.url || api.fileUrl(props.taskId, kind, { version: doc.version });
    };

    const title = () => task()?.title || task()?.arxiv_id || props.taskId;
    const isPdf = () => info()?.view !== "html";
    const live = () => taskStore.live(props.taskId);
    const activeTask = () => {
        const s = task();
        return !!s && !isTerminal(s.status);
    };

    // ---------- 渲染 ----------

    const renderPane = (side: DocId) => {
        const version = () => info()?.documents[side].version ?? "pending";
        return (
            <div class="pane-slot">
                <Show when={version()} keyed>
                    {(_v) =>
                        isPdf() ? (
                            <PdfPane
                                url={docUrl(side)}
                                side={side}
                                active={active() === side}
                                onReady={(h) => paneReady(side, h)}
                                onDispose={(h) => paneDisposed(side, h)}
                                onPageChange={(p) => setPageNums((s) => ({ ...s, [side]: p }))}
                                onActivate={() => setActive(side)}
                                onScroll={onUserScroll}
                            />
                        ) : (
                            <HtmlPane
                                side={side}
                                chunks={dual()?.chunks ?? []}
                                active={active() === side}
                                onReady={(h) => paneReady(side, h)}
                                onDispose={(h) => paneDisposed(side, h)}
                                onActivate={() => setActive(side)}
                                onScroll={onUserScroll}
                            />
                        )
                    }
                </Show>
                <Show when={drift()[side]}>
                    <button type="button" class="jump-back" onClick={() => jumpBack(side)}>
                        ⌖ {t.reader.jumpBack}
                    </button>
                </Show>
            </div>
        );
    };

    return (
        <div class="reader">
            <Show when={fatal()}>
                <main class="reader-fatal">
                    <p>{fatal()}</p>
                    <button type="button" class="btn-ghost" onClick={() => props.nav("#/")}>
                        ← {t.reader.back}
                    </button>
                </main>
            </Show>

            {/* 进行中：阶段步进 + 棋盘格 + 日志抽屉 */}
            <Show when={!fatal() && activeTask()}>
                <main class="task-progress">
                    <h1 class="tp-title">{title()}</h1>
                    <ol class="stage-stepper">
                        <For each={STAGES}>
                            {(s) => {
                                const cur = () => task()?.stage ?? task()?.status;
                                const idx = () => STAGES.indexOf(cur() as TaskStage);
                                return (
                                    <li
                                        classList={{
                                            done: STAGES.indexOf(s) < idx(),
                                            on: cur() === s,
                                        }}
                                    >
                                        {t.status[s]}
                                    </li>
                                );
                            }}
                        </For>
                    </ol>
                    <div class="tp-bar">
                        <i style={{ width: `${task()?.progress ?? 0}%` }} />
                    </div>
                    <Show when={task()?.message}>
                        <p class="muted">{task()!.message}</p>
                    </Show>
                    <Show when={live()?.chunk}>
                        {(c) => (
                            <ProgressGrid
                                total={c().total}
                                done={c().done}
                                cached={c().cached}
                                failed={c().failed}
                                items={c().items}
                            />
                        )}
                    </Show>
                    <Show when={(live()?.warnings.length ?? 0) > 0}>
                        <ul class="warn-list">
                            <For each={live()!.warnings}>
                                {(w) => (
                                    <li>
                                        [{w.code}] {w.message}
                                    </li>
                                )}
                            </For>
                        </ul>
                    </Show>
                    <Show when={live()?.error}>
                        {(e) => (
                            <p class="form-error">
                                [{e().code}] {e().message}
                            </p>
                        )}
                    </Show>
                    <details class="log-drawer">
                        <summary>{t.progress.log}</summary>
                        <pre>
                            <For each={live()?.logs ?? []}>{(l) => l.line + "\n"}</For>
                        </pre>
                    </details>
                    <div class="tp-actions">
                        <button
                            type="button"
                            class="btn-ghost"
                            onClick={() => void api.cancel(props.taskId)}
                        >
                            {t.reader.cancel}
                        </button>
                    </div>
                </main>
            </Show>

            {/* 终态：阅读器（左右互换走 CSS row-reverse，逻辑侧不变） */}
            <Show when={!fatal() && !activeTask() && info()}>
                <Toolbar
                    title={title()}
                    status={task()?.status}
                    mode={mode()}
                    syncing={syncing()}
                    zoom={zoom()}
                    page={pageNums()[active()]}
                    numPages={pageCounts()[active()]}
                    active={active()}
                    swapped={swapped()}
                    downloads={downloads()}
                    onMode={planModeChange}
                    onSync={setSync}
                    onZoom={applyZoom}
                    onGotoPage={gotoPage}
                    onSwap={() => setSwapped((v) => !v)}
                    onActiveSide={setActive}
                    onRetry={() => void api.retry(props.taskId)}
                    onCancel={() => void api.cancel(props.taskId)}
                    onBack={() => props.nav("#/")}
                />
                <div class="panes" classList={{ swapped: swapped(), single: mode() !== "split" }}>
                    <Show when={paneVisible("original")}>{renderPane("original")}</Show>
                    <Show when={paneVisible("translated")}>{renderPane("translated")}</Show>
                </div>
            </Show>

            <Show when={!fatal() && !activeTask() && !info()}>
                <main class="reader-fatal">
                    <p class="muted">{t.reader.loading}</p>
                </main>
            </Show>
        </div>
    );
}
