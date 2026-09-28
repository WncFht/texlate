// Reader —— 阅读器外壳 + 任务编排（任务状态机驱动页面流转，§5.2）。
// 本层只管数据装载 / SSE 桥 / 重试与换链降级 / 分享打包 / 页面流转；
// 进行中 → TaskProgress，终态可读 → ReaderView（同步/持久化/窗格机制全在
// reader/ 子组件内），无阅读视图的终态 → 结果面板 / 产物下载面板。

import {
    createEffect,
    createMemo,
    createSignal,
    For,
    onCleanup,
    onMount,
    Show,
} from "solid-js";
import {
    api,
    ApiError,
    errText,
    isTerminal,
    REQUEST_TIMEOUT_MS,
    type DualJson,
    type FileKind,
    type FileManifest,
    type ReaderInfo,
    type TaskSnapshot,
} from "../api/client";
import { keptRefs } from "../stores/keptRefs";
import { taskStore } from "../stores/tasks";
import { downloadItems } from "../taskFiles";
import { mergeResultStats } from "../taskStats";
import ProgressGrid from "../components/ProgressGrid";
import type { DownloadItem, Mode } from "../components/Toolbar";
import type { DocId } from "../reader/alignment";
import { buildCiteIndex } from "../reader/citations";
import { resolveReaderView } from "../reader/view";
import ReaderView from "../reader/ReaderView";
import TaskProgress from "../reader/TaskProgress";
import ResultBody, { RESULT_TEXT } from "../reader/ResultBody";
import ShareBlock, { createSharePack } from "../reader/ShareBlock";
import { createHtmlFallback, createTaskRetry } from "../reader/taskActions";
import { t } from "../i18n";

export default function Reader(props: {
    taskId: string;
    nav(to: string): void;
}) {
    const [task, setTask] = createSignal<TaskSnapshot | null>(null);
    const [info, setInfo] = createSignal<ReaderInfo | null>(null);
    // undefined = dual.json 未拉完；null = 无文件/拉取失败（view.ts 三态语义）
    const [dual, setDual] = createSignal<DualJson | null | undefined>(
        undefined,
    );
    const [manifest, setManifest] = createSignal<FileManifest | null>(null);
    // 五个阅读态信号留在页面层：reading 恢复写它们，retry 后 Reader 不卸载、
    // 用户上次模式选择随之保留（ReaderView 经 props 读写同一份）
    const [mode, setMode] = createSignal<Mode>("split");
    const [syncing, setSyncing] = createSignal(true);
    const [zoom, setZoom] = createSignal("page-width");
    const [active, setActive] = createSignal<DocId>("original");
    const [swapped, setSwapped] = createSignal(false);
    const [fatal, setFatal] = createSignal("");
    // 终态横幅折叠：partial/fault 的结果条占纵向空间大，用户可收成细条
    const [bannerFold, setBannerFold] = createSignal(false);
    // reader 404 于终态任务：doc 类任务无 dual.json（设计如此）→ 产物下载面板
    const [readerGone, setReaderGone] = createSignal(false);
    // §6 事后共享：done/partial + 非 share 导入 + 有 arxiv 源 → 可打 .share.zip
    const share = createSharePack(() => props.taskId);
    // 终态编排（retry/HTML 换链）——reader/taskActions 工厂，信号内聚在件内
    const retry = createTaskRetry({
        taskId: () => props.taskId,
        nav: (to) => props.nav(to),
        onAccepted: (status) => {
            // 同 id 重跑：清产物快照 + 清上一轮 SSE 痕迹，界面回到进度视图；
            // pendingJump/restoredSides 随 ReaderView 卸载自然销毁，无需手清
            setInfo(null);
            setDual(undefined);
            setManifest(null);
            setReaderGone(false);
            setBannerFold(false);
            readerRequested = false;
            setTask((cur) =>
                cur
                    ? {
                          ...cur,
                          status,
                          stage: undefined,
                          message: undefined,
                          error: null,
                          progress: 0,
                      }
                    : cur,
            );
            // 重跑换产物——上一轮打包结果作废
            share.reset();
        },
    });
    const html = createHtmlFallback({ task, nav: (to) => props.nav(to) });

    // loadReader 一次性闸：readerGone/无 reader 数据的终态任务上，SSE
    // effect 每次 store 更新都重入——标志位挡住（onRetry 复位后重开）
    let readerRequested = false;

    // ---------- 数据装载 ----------

    const loadReader = async () => {
        if (readerRequested) return;
        readerRequested = true;
        try {
            // manifest 先行：dual.json 的 sha256 在里面——带 ?version= 的
            // 内容寻址 URL 可命中浏览器/中间缓存，重复打开不再全量重拉。
            // manifest 失败则退无版本直拉（no_store 大文件，行为同旧版）
            const m = await api.files(props.taskId).catch(() => null);
            setManifest(m);
            const dualSha = m?.artifacts["dual_json"]?.sha256;
            const dualUrl = api.fileUrl(props.taskId, "dual.json", {
                version: dualSha || undefined,
            });
            // reader 与 dual.json 无相互依赖——并行省 1 RTT
            // （dual.json 同时提供 alignment 兜底与 chunks，HTML 视图必需）
            const [r, dj] = await Promise.all([
                api.reader(props.taskId),
                fetch(dualUrl, {
                    signal: AbortSignal.timeout?.(REQUEST_TIMEOUT_MS) ?? null,
                })
                    .then((res) =>
                        res.ok ? (res.json() as Promise<DualJson>) : null,
                    )
                    .catch(() => null),
            ]);
            setInfo(r);
            setDual(dj);
            const rd = r.reading;
            if (rd) {
                if (rd.mode) setMode(rd.mode);
                if (rd.sync !== undefined) setSyncing(rd.sync);
                if (rd.zoom) setZoom(rd.zoom);
                if (rd.active) setActive(rd.active);
                if (typeof rd.swapped === "boolean") setSwapped(rd.swapped);
            }
            // 窄屏（≤640px）无已存偏好 → 默认单栏译文（U14；分栏在手机上不可读）
            if (
                !rd?.mode &&
                typeof window.matchMedia === "function" &&
                window.matchMedia("(max-width: 640px)").matches
            )
                setMode("translated");
        } catch (e) {
            // 终态任务无 reader 数据 → reader 404 属预期，交给结果/产物面板；其余仍 fatal
            const s = task()?.status;
            if (
                e instanceof ApiError &&
                e.status === 404 &&
                s &&
                isTerminal(s)
            ) {
                setReaderGone(true);
            } else {
                setFatal(errText(e));
            }
        }
    };

    const boot = async () => {
        try {
            const snap = await api.snapshot(props.taskId);
            setTask(snap);
            if (isTerminal(snap.status)) {
                await loadReader();
            } else {
                taskStore.watch(props.taskId);
            }
        } catch (e) {
            setFatal(errText(e));
        }
    };

    /** fatal 死路页重试：清闸重走装载（U7） */
    const reload = () => {
        setFatal("");
        readerRequested = false;
        void boot();
    };

    onMount(() => {
        void boot();
        // kept refs（M4）：reader mount 即取回——CiteCard ★ 态与
        // refs.bib 下载项都消费这份快照；App 按 taskId keyed 重挂本页
        void keptRefs.load(props.taskId);
    });

    // 卸载摘 pin：watch 的 SSE 槽/pin 意愿不随组件消失自动释放（M2）
    onCleanup(() => taskStore.unwatch(props.taskId));

    // SSE：任务在 store 里被 watch；终态到达 → 装阅读器
    createEffect(() => {
        const done = taskStore.live(props.taskId)?.done;
        if (done && !info()) void loadReader();
        const snap = taskStore.task(props.taskId);
        if (snap) setTask(snap);
    });

    // ---------- document.title（U9 进度可见 / U10 后台完成闪烁） ----------

    const baseTitle = document.title;
    let flashTimer = 0;
    const stopFlash = () => {
        if (flashTimer) {
            window.clearInterval(flashTimer);
            flashTimer = 0;
        }
    };

    const computeTitle = () => {
        const s = task();
        if (!s) return baseTitle;
        return activeTask()
            ? `${Math.round(s.progress)}% · ${title()}`
            : title();
    };

    createEffect(() => {
        if (flashTimer) return; // 闪烁期标题归闪灯管
        document.title = computeTitle();
    });

    // 活动 → 终态的迁移在后台 tab 发生 → 标题闪【完成】；回前台/卸载即停。
    // SSE done 帧与轮询降级两路都走 status 翻转，单点判定迁移沿。
    let wasActive = false;
    const startFlash = () => {
        if (flashTimer) return;
        let on = false;
        flashTimer = window.setInterval(() => {
            on = !on;
            // 标题每次现取——闪烁期 task.title/PDF 标题可能才到，别定格在
            // 启动瞬间的 taskId 兜底上
            const name = title();
            document.title = on ? `【${t.status.done}】${name}` : name;
        }, 1000);
    };
    createEffect(() => {
        if (activeTask()) {
            wasActive = true;
            return;
        }
        if (
            wasActive &&
            task() &&
            isTerminal(task()!.status) &&
            document.hidden
        )
            startFlash();
        wasActive = false;
    });

    onMount(() => {
        const onVis = () => {
            if (document.hidden) return;
            stopFlash();
            document.title = computeTitle();
        };
        document.addEventListener("visibilitychange", onVis);
        onCleanup(() =>
            document.removeEventListener("visibilitychange", onVis),
        );
    });

    onCleanup(() => {
        stopFlash();
        document.title = baseTitle;
    });

    // ---------- 页面流转派生 ----------

    // 顶栏标题兜底链：task.title → PDF metadata Title → arxiv_id → taskId
    const [docTitles, setDocTitles] = createSignal<
        Partial<Record<DocId, string>>
    >({});
    const pdfTitle = () => docTitles().original || docTitles().translated || "";
    const title = () =>
        task()?.title || pdfTitle() || task()?.arxiv_id || props.taskId;
    // html 视图需 dual.json chunks 到位才成立；登记 html 却无渲染材料 → empty 空态；
    // readerGone（doc 类任务）→ files 产物面板
    const view = () => resolveReaderView(info(), dual(), readerGone());
    const live = () => taskStore.live(props.taskId);
    const activeTask = () => {
        const s = task();
        return !!s && !isTerminal(s.status);
    };

    // cite 图谱规模：refs.bib 下载项的现身闸之一（M4）——buildCiteIndex
    // 吃 dual 三态信号，未拉完/拉失败都归 0
    const citeSize = createMemo(() => buildCiteIndex(dual()).size);
    const downloads = createMemo<DownloadItem[]>(() => {
        const m = manifest();
        // manifest 拉取失败（loadReader 吞错置 null）时退 done.artifacts/
        // 快照 artifacts——三者同形状（db kind→url），缺一层不该让下载清单全空
        const arts: Record<string, string> = m
            ? Object.fromEntries(
                  Object.entries(m.artifacts).map(([k, e]) => [k, e.url]),
              )
            : (live()?.done?.artifacts ?? task()?.artifacts ?? {});
        const items = downloadItems(arts);
        // refs.bib（M4）：有引用图谱或有收藏即有义；空集服务端也兜底出空
        // bib。kind 走 "refs.bib" as FileKind——FileKind 联合不扩，保持
        // api.fileUrl 对真实 manifest kind 诚实
        if (citeSize() > 0 || keptRefs.count() > 0)
            items.push({
                kind: "refs.bib" as FileKind,
                label: t.files["refs.bib"],
                url: api.refsBibUrl(props.taskId, { download: true }),
            });
        return items;
    });

    /** 终态非 done → 结果面板/横幅的状态键；done 或进行中 → null */
    const resultStatus = () => {
        const s = task()?.status;
        return s && isTerminal(s) && s !== "done" ? s : null;
    };

    /** done 但带 warnings（keyless mock_translator 等）→ 阅读器内常驻
        横幅（M1）——与 resultStatus 互斥拼成横幅状态键 */
    const doneWarnings = () => {
        const s = task();
        return s?.status === "done" && (s.warnings?.length ?? 0) > 0;
    };

    /** 结果面板统计：done.stats 优先 + 快照 counters/usage 兜底（taskStats.ts） */
    const resultStats = () =>
        mergeResultStats(live()?.done?.stats, task()?.counters, task()?.usage);

    // ---------- 事后共享打包（POST /task/{id}/share/pack，§6） ----------

    /** 可分享：done/partial 终态 + 非 share 导入产物（不自包）+ 有 arxiv 源（寻址必需） */
    const canShare = () => {
        const s = task();
        return (
            !!s &&
            (s.status === "done" || s.status === "partial") &&
            s.kind !== "share" &&
            s.kind !== "arxiv_html" &&
            !!s.arxiv_id
        );
    };

    /** 分享块：按钮 → 成功态（share_key + 共享目录提示）/ 可读错误。自门控 canShare */
    const renderShare = () => (
        <ShareBlock
            when={canShare()}
            busy={share.busy()}
            result={share.result()}
            error={share.error()}
            onPack={() => void share.pack()}
        />
    );

    /** partial/fault 的段落棋盘格——settleLive 保留 chunkItems，直接复用（U11） */
    const gridSlot = () => {
        const c = live()?.chunk;
        const items = live()?.chunkItems ?? [];
        if (!c || !items.length) return undefined;
        return (
            <ProgressGrid
                total={c.total}
                done={c.done}
                cached={c.cached}
                failed={c.failed}
                items={items}
            />
        );
    };

    /** 终态面板主体：状态文案 + 错误 + 警告 + 统计 + 重试（横幅与整页共用）。
        done 态（warnings 横幅）不注 share 槽——工具栏 sharePanel 已覆盖 */
    const renderResultBody = (st: string) => (
        <ResultBody
            st={st}
            task={task()}
            retryError={retry.retryError()}
            retrying={retry.retrying()}
            authKey={retry.authKey()}
            onAuthKey={retry.setAuthKey}
            onRetry={() => void retry.run()}
            canTryHtml={html.can()}
            htmlBusy={html.htmlBusy()}
            htmlErr={html.htmlErr()}
            onTryHtml={() => void html.run()}
            stats={resultStats()}
            grid={gridSlot()}
            share={st === "done" ? undefined : renderShare()}
        />
    );

    /** 产物下载清单（doc 任务面板与有产物的非干净终态共用） */
    const renderDownloads = () => (
        <Show when={downloads().length > 0}>
            <ul class="file-list">
                <For each={downloads()}>
                    {(d) => (
                        <li>
                            <a href={d.url} download="">
                                {d.label}
                            </a>
                        </li>
                    )}
                </For>
            </ul>
        </Show>
    );

    // ---------- 渲染 ----------

    return (
        <div class="reader">
            <Show when={fatal()}>
                <main class="reader-fatal">
                    <p>{fatal()}</p>
                    <button
                        type="button"
                        class="tb-btn"
                        onClick={() => props.nav("#/")}
                    >
                        ← {t.reader.back}
                    </button>
                    <button type="button" class="btn-ghost" onClick={reload}>
                        {t.reader.retry}
                    </button>
                </main>
            </Show>

            {/* 进行中：阶段步进 + 棋盘格 + 日志抽屉 */}
            <Show when={!fatal() && activeTask()}>
                <TaskProgress
                    task={task()}
                    live={live()}
                    title={title()}
                    onCancel={() => void api.cancel(props.taskId)}
                    onBack={() => props.nav("#/")}
                />
            </Show>

            {/* 终态：阅读器（Toolbar + 横幅槽 + 双栏，pane 机制在 ReaderView） */}
            <Show
                when={
                    !fatal() &&
                    !activeTask() &&
                    (view() === "pdf" || view() === "html" || view() === "dom")
                }
            >
                <ReaderView
                    taskId={props.taskId}
                    view={view()}
                    info={info()}
                    dual={dual()}
                    status={task()?.status}
                    title={title()}
                    arxivId={task()?.arxiv_id ?? undefined}
                    downloads={downloads()}
                    mode={mode()}
                    setMode={setMode}
                    syncing={syncing()}
                    setSyncing={setSyncing}
                    zoom={zoom()}
                    setZoom={setZoom}
                    active={active()}
                    setActive={setActive}
                    swapped={swapped()}
                    onSwap={() => setSwapped((v) => !v)}
                    onRetry={() => void retry.run()}
                    onCancel={() => void api.cancel(props.taskId)}
                    onBack={() => props.nav("#/")}
                    onDocTitle={(side, ti) =>
                        setDocTitles((m) => ({ ...m, [side]: ti }))
                    }
                    banner={
                        // 有产物的非干净终态（partial 等）：横幅提示，可收成细条；
                        // 重试入口在工具栏（非 done 终态）仍可达，折叠不丢动作。
                        // done+warnings（M1 mock_translator 等）也借此槽常驻
                        <Show
                            when={
                                resultStatus() ??
                                (doneWarnings() ? "done" : null)
                            }
                        >
                            {(st) => (
                                <section
                                    class={`result-banner st-${st()}`}
                                    classList={{ folded: bannerFold() }}
                                >
                                    <Show
                                        when={!bannerFold()}
                                        fallback={
                                            <button
                                                type="button"
                                                class="rb-fold-line"
                                                title={t.reader.resultExpand}
                                                onClick={() =>
                                                    setBannerFold(false)
                                                }
                                            >
                                                <span>
                                                    {RESULT_TEXT[st()] ??
                                                        t.status[st()] ??
                                                        st()}
                                                </span>
                                                <span class="rb-fold-hint">
                                                    {t.reader.resultExpand} ⌄
                                                </span>
                                            </button>
                                        }
                                    >
                                        {renderResultBody(st())}
                                        <button
                                            type="button"
                                            class="rb-fold"
                                            aria-label={t.reader.resultFold}
                                            title={t.reader.resultFold}
                                            onClick={() => setBannerFold(true)}
                                        >
                                            ⌃ {t.reader.resultFold}
                                        </button>
                                    </Show>
                                </section>
                            )}
                        </Show>
                    }
                    sharePanel={
                        // done 专属分享弹层（partial 的分享钮在结果横幅内）：
                        // 有值 → ReaderView 出工具栏分享钮 + 弹层
                        task()?.status === "done" && canShare() ? (
                            <>
                                <p class="share-pop-text">
                                    {t.reader.shareBanner}
                                </p>
                                {renderShare()}
                            </>
                        ) : undefined
                    }
                />
            </Show>

            {/* 无阅读视图的终态（fault/cancelled/interrupted/needs_auth、reader 404、
                登记 html 却无 chunks）：整页结果面板取代空态；有产物附下载清单 */}
            <Show
                when={
                    !fatal() &&
                    !activeTask() &&
                    resultStatus() &&
                    (view() === "files" || view() === "empty")
                }
            >
                <main class="result-panel-wrap">
                    <section class={`result-panel st-${resultStatus()}`}>
                        {renderResultBody(resultStatus()!)}
                        {renderDownloads()}
                        <button
                            type="button"
                            class="btn-ghost"
                            onClick={() => props.nav("#/")}
                        >
                            ← {t.reader.back}
                        </button>
                    </section>
                </main>
            </Show>

            {/* done 却无阅读视图：doc 类任务（files）出产物下载面板——下载清单
                为空（manifest 也没拉到）或登记 html 却无 chunks（empty）回退空态 */}
            <Show
                when={
                    !fatal() &&
                    !activeTask() &&
                    !resultStatus() &&
                    (view() === "files" || view() === "empty")
                }
            >
                <main class="result-panel-wrap">
                    <section class="result-panel">
                        <Show
                            when={downloads().length > 0}
                            fallback={<p class="muted">{t.reader.notReady}</p>}
                        >
                            <h2 class="rp-status">{t.reader.filesTitle}</h2>
                            <p class="muted">{t.reader.filesHint}</p>
                            {renderDownloads()}
                        </Show>
                        {renderShare()}
                        <button
                            type="button"
                            class="btn-ghost"
                            onClick={() => props.nav("#/")}
                        >
                            ← {t.reader.back}
                        </button>
                    </section>
                </main>
            </Show>

            <Show when={!fatal() && !activeTask() && view() === "loading"}>
                <main class="reader-fatal">
                    <p class="muted">{t.reader.loading}</p>
                </main>
            </Show>
        </div>
    );
}
