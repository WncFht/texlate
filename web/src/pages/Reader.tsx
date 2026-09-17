// Reader —— 阅读器外壳 + 任务编排（任务状态机驱动页面流转，§5.2）。
// 本层只管数据装载 / SSE 桥 / 重试与换链降级 / 分享打包 / 页面流转；
// 进行中 → TaskProgress，终态可读 → ReaderView（同步/持久化/窗格机制全在
// reader/ 子组件内），无阅读视图的终态 → 结果面板 / 产物下载面板。

import { createEffect, createMemo, createSignal, For, onMount, Show } from "solid-js";
import {
    api,
    ApiError,
    isTerminal,
    landingHash,
    type DualJson,
    type FileManifest,
    type ReaderInfo,
    type TaskSnapshot,
} from "../api/client";
import { taskStore } from "../stores/tasks";
import { downloadItems } from "../taskFiles";
import { mergeResultStats } from "../taskStats";
import type { DownloadItem, Mode } from "../components/Toolbar";
import type { DocId } from "../reader/alignment";
import { resolveReaderView } from "../reader/view";
import ReaderView from "../reader/ReaderView";
import TaskProgress from "../reader/TaskProgress";
import ResultBody, { type RetryError } from "../reader/ResultBody";
import ShareBlock, { createSharePack } from "../reader/ShareBlock";
import { t } from "../i18n/zh";

export default function Reader(props: { taskId: string; nav(to: string): void }) {
    const [task, setTask] = createSignal<TaskSnapshot | null>(null);
    const [info, setInfo] = createSignal<ReaderInfo | null>(null);
    // undefined = dual.json 未拉完；null = 无文件/拉取失败（view.ts 三态语义）
    const [dual, setDual] = createSignal<DualJson | null | undefined>(undefined);
    const [manifest, setManifest] = createSignal<FileManifest | null>(null);
    // 五个阅读态信号留在页面层：reading 恢复写它们，retry 后 Reader 不卸载、
    // 用户上次模式选择随之保留（ReaderView 经 props 读写同一份）
    const [mode, setMode] = createSignal<Mode>("split");
    const [syncing, setSyncing] = createSignal(true);
    const [zoom, setZoom] = createSignal("page-width");
    const [active, setActive] = createSignal<DocId>("original");
    const [swapped, setSwapped] = createSignal(false);
    const [fatal, setFatal] = createSignal("");
    // reader 404 于终态任务：doc 类任务无 dual.json（设计如此）→ 产物下载面板
    const [readerGone, setReaderGone] = createSignal(false);
    const [retrying, setRetrying] = createSignal(false);
    const [retryError, setRetryError] = createSignal<RetryError | null>(null);
    // needs_auth 结果面板的内联 API Key 输入（重试随 X-Texlate-Key 透传）
    const [authKey, setAuthKey] = createSignal("");
    const [htmlBusy, setHtmlBusy] = createSignal(false);
    const [htmlErr, setHtmlErr] = createSignal("");
    // §6 事后共享：done/partial + 非 share 导入 + 有 arxiv 源 → 可打 .share.zip
    const share = createSharePack(() => props.taskId);

    // loadReader 一次性闸：readerGone/无 reader 数据的终态任务上，SSE
    // effect 每次 store 更新都重入——标志位挡住（onRetry 复位后重开）
    let readerRequested = false;

    // ---------- 数据装载 ----------

    const loadReader = async () => {
        if (readerRequested) return;
        readerRequested = true;
        // manifest 独立落地：doc 任务 reader 404 属预期，但下载清单必须
        // 到位——曾与 reader 同 Promise.all，reader 先拒则 manifest 永不设置
        void api
            .files(props.taskId)
            .then(setManifest)
            .catch(() => undefined);
        try {
            const r = await api.reader(props.taskId);
            setInfo(r);
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
                const rds = rd as typeof rd & { swapped?: boolean };
                if (typeof rds.swapped === "boolean") setSwapped(rds.swapped);
            }
        } catch (e) {
            // 终态任务无 reader 数据 → reader 404 属预期，交给结果/产物面板；其余仍 fatal
            const s = task()?.status;
            if (e instanceof ApiError && e.status === 404 && s && isTerminal(s)) {
                setReaderGone(true);
            } else {
                setFatal(e instanceof Error ? e.message : String(e));
            }
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

    // ---------- 页面流转派生 ----------

    const title = () => task()?.title || task()?.arxiv_id || props.taskId;
    // html 视图需 dual.json chunks 到位才成立；登记 html 却无渲染材料 → empty 空态；
    // readerGone（doc 类任务）→ files 产物面板
    const view = () => resolveReaderView(info(), dual(), readerGone());
    const live = () => taskStore.live(props.taskId);
    const activeTask = () => {
        const s = task();
        return !!s && !isTerminal(s.status);
    };

    const downloads = createMemo<DownloadItem[]>(() => {
        const m = manifest();
        if (!m) return [];
        // manifest.artifacts → db kind→url 同形状，排序/标签/直链走 taskFiles
        return downloadItems(
            Object.fromEntries(Object.entries(m.artifacts).map(([k, e]) => [k, e.url])),
        );
    });

    /** 终态非 done → 结果面板/横幅的状态键；done 或进行中 → null */
    const resultStatus = () => {
        const s = task()?.status;
        return s && isTerminal(s) && s !== "done" ? s : null;
    };

    /** 结果面板统计：done.stats 优先 + 快照 counters/usage 兜底（taskStats.ts） */
    const resultStats = () =>
        mergeResultStats(live()?.done?.stats, task()?.counters, task()?.usage);

    // ---------- 重试（终态 → 同 id 重入队，§3.3） ----------

    const onRetry = async () => {
        if (retrying()) return;
        setRetrying(true);
        setRetryError(null);
        try {
            // needs_auth：重试必须重带 X-Texlate-Key（server 401 auth_required）
            const res = await api.retry(
                props.taskId,
                undefined,
                authKey() ? { apiKey: authKey() } : undefined,
            );
            if (res.task_id !== props.taskId) {
                props.nav(`#/reader/${res.task_id}`);
                return;
            }
            // 同 id 重跑：清产物快照 + 清上一轮 SSE 痕迹，界面回到进度视图；
            // pendingJump/restoredSides 随 ReaderView 卸载自然销毁，无需手清
            setInfo(null);
            setDual(undefined);
            setManifest(null);
            setReaderGone(false);
            readerRequested = false;
            setTask((cur) =>
                cur
                    ? {
                          ...cur,
                          status: res.status,
                          stage: undefined,
                          message: undefined,
                          error: null,
                          progress: 0,
                      }
                    : cur,
            );
            // 先于 resetLive 补丁列表行——否则 SSE 生效前 effect 会用旧终态回盖 task()
            taskStore.patch(props.taskId, {
                status: res.status,
                stage: undefined,
                message: undefined,
                error: null,
                progress: 0,
            });
            taskStore.resetLive(props.taskId);
            setAuthKey(""); // 已用毕即弃，不留在组件态
            // 重跑换产物——上一轮打包结果作废
            share.reset();
        } catch (e) {
            const ae = e instanceof ApiError ? e : null;
            setRetryError({
                status: ae?.status ?? 0,
                code: ae?.code,
                message: ae?.detail ?? (e instanceof Error ? e.message : String(e)),
            });
        } finally {
            setRetrying(false);
        }
    };

    // ---------- arXiv HTML 通道降级（F 桶取源失败 → 换链新任务） ----------

    // 取源段失败才可换链：编译/翻译段故障 html 链救不了，误示好过滥示。
    // 新任务而非 retry：kind 是建行定死的列字段，retry 端点不换 kind——
    // 换链必须新任务（kind 不同 cache_key 不同，不与原任务撞 dedup）
    const HTML_FALLBACK_CODES: ReadonlySet<string> = new Set([
        "arxiv_fetch",
        "no_latex_source",
        "pdf_wrapper",
    ]);
    const canTryHtml = () => {
        const s = task();
        return (
            s?.kind === "arxiv" &&
            !!s.arxiv_id &&
            HTML_FALLBACK_CODES.has(s.error?.code ?? "")
        );
    };
    const onTryHtml = async () => {
        const s = task();
        if (!s?.arxiv_id || htmlBusy()) return;
        setHtmlBusy(true);
        setHtmlErr("");
        try {
            const res = await api.translate(s.arxiv_id, {
                model: s.model,
                target_lang: s.target_lang,
                options: { source: "html" },
            });
            props.nav(landingHash(res));
        } catch (e) {
            setHtmlErr(e instanceof ApiError ? e.detail : String(e));
        } finally {
            setHtmlBusy(false);
        }
    };

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

    /** 终态面板主体：状态文案 + 错误 + 警告 + 统计 + 重试（横幅与整页共用） */
    const renderResultBody = (st: string) => (
        <ResultBody
            st={st}
            task={task()}
            retryError={retryError()}
            retrying={retrying()}
            authKey={authKey()}
            onAuthKey={setAuthKey}
            onRetry={() => void onRetry()}
            canTryHtml={canTryHtml()}
            htmlBusy={htmlBusy()}
            htmlErr={htmlErr()}
            onTryHtml={() => void onTryHtml()}
            stats={resultStats()}
            share={renderShare()}
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
                    <button type="button" class="btn-ghost" onClick={() => props.nav("#/")}>
                        ← {t.reader.back}
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
                    onRetry={() => void onRetry()}
                    onCancel={() => void api.cancel(props.taskId)}
                    onBack={() => props.nav("#/")}
                    banner={
                        // 有产物的非干净终态（partial 等）：横幅提示，不挡阅读
                        <Show when={resultStatus()}>
                            <section class={`result-banner st-${resultStatus()}`}>
                                {renderResultBody(resultStatus()!)}
                            </section>
                        </Show>
                    }
                    shareBanner={
                        // done 且无结果横幅：§6 完成后提示分享
                        // （partial 的分享钮在结果横幅内）
                        <Show when={task()?.status === "done" && canShare()}>
                            <section class="result-banner share-banner">
                                <span class="rp-status">{t.reader.shareBanner}</span>
                                {renderShare()}
                            </section>
                        </Show>
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
