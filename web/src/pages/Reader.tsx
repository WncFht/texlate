// Reader —— 阅读器外壳 + 任务进度视图（任务状态机驱动页面流转，§5.2）。
// 活动状态 → 阶段步进 + 段落棋盘格 + 日志抽屉；终态 → 三模式阅读器。
// 双栏：每侧按 doc.version keyed 重挂（usePDFSlick 无清理，§5.1 坑）。

import { createEffect, createMemo, createSignal, onCleanup, onMount, Show, For } from "solid-js";
import {
    api,
    ApiError,
    isTerminal,
    landingHash,
    type DualJson,
    type FileKind,
    type FileManifest,
    type ReaderInfo,
    type SharePackResponse,
    type TaskSnapshot,
    type TaskStage,
} from "../api/client";
import { taskStore } from "../stores/tasks";
import { downloadItems } from "../taskFiles";
import { mergeResultStats } from "../taskStats";
import Toolbar, { type DownloadItem, type Mode } from "../components/Toolbar";
import ProgressGrid from "../components/ProgressGrid";
import PdfPane, { type PaneHandle } from "../reader/PdfPane";
import HtmlPane, { type HtmlPaneHandle } from "../reader/HtmlPane";
import DomPane, { type DomPaneHandle } from "../reader/DomPane";
import { createPositionMapper, type DocId, type Pos } from "../reader/alignment";
import { annotFileName } from "../reader/paneUtils";
import { capturePos, jumpTo, scrollTopFor, SyncEngine } from "../reader/sync";
import { resolveReaderView } from "../reader/view";
import { t } from "../i18n/zh";

const STAGES: TaskStage[] = ["fetching", "parsing", "translating", "compiling"];
const JUMPBACK_PX = 500;
const SAVE_DEBOUNCE_MS = 1000;

type AnyHandle = PaneHandle | HtmlPaneHandle | DomPaneHandle;

export default function Reader(props: { taskId: string; nav(to: string): void }) {
    const [task, setTask] = createSignal<TaskSnapshot | null>(null);
    const [info, setInfo] = createSignal<ReaderInfo | null>(null);
    // undefined = dual.json 未拉完；null = 无文件/拉取失败（view.ts 三态语义）
    const [dual, setDual] = createSignal<DualJson | null | undefined>(undefined);
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
    // reader 404 于终态任务：doc 类任务无 dual.json（设计如此）→ 产物下载面板
    const [readerGone, setReaderGone] = createSignal(false);
    const [retrying, setRetrying] = createSignal(false);
    const [retryError, setRetryError] = createSignal<{
        status: number;
        code?: string;
        message: string;
    } | null>(null);
    // needs_auth 结果面板的内联 API Key 输入（重试随 X-Texlate-Key 透传）
    const [authKey, setAuthKey] = createSignal("");
    // §6 事后共享：done/partial + 非 share 导入 + 有 arxiv 源 → 可打 .share.zip
    const [shareBusy, setShareBusy] = createSignal(false);
    const [shareResult, setShareResult] = createSignal<SharePackResponse | null>(null);
    const [shareError, setShareError] = createSignal<{
        code?: string;
        message: string;
    } | null>(null);
    // 已用时秒表的走时源（created_at 为 epoch 秒）
    const [now, setNow] = createSignal(Date.now());
    const tick = window.setInterval(() => setNow(Date.now()), 1000);
    onCleanup(() => window.clearInterval(tick));

    let engine: SyncEngine | null = null;
    let pendingJump: { from: DocId; pos: Pos } | null = null;
    const restoredSides = new Set<DocId>();
    let saveTimer = 0;

    // ---------- 数据装载 ----------

    const loadReader = async () => {
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

    onCleanup(() => {
        engine?.dispose();
        // 卸载冲刷：防抖窗口内离开（返回列表/切任务）不丢最后一段阅读位置
        if (saveTimer) {
            window.clearTimeout(saveTimer);
            saveTimer = 0;
            saveNow();
        }
    });

    // Ctrl/Cmd+F → 活动窗格的 findbar（PDF 侧；HTML 侧无 openFind，放行给浏览器原生查找）
    onMount(() => {
        const onKey = (e: KeyboardEvent) => {
            if (!(e.ctrlKey || e.metaKey) || e.key.toLowerCase() !== "f") return;
            const h = handles()[active()];
            if (h && "openFind" in h) {
                e.preventDefault();
                h.openFind();
            }
        };
        document.addEventListener("keydown", onKey);
        onCleanup(() => document.removeEventListener("keydown", onKey));
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
        // dom 与 pdf 同路：dom 的 "pages" = 锚定 chunk 数（worker 写进
        // documents.*.pages），不进 dual.chunks 分支
        return {
            original: i.documents.original?.pages ?? 1,
            translated: i.documents.translated?.pages ?? 1,
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
        persistPosition();
    };

    // ---------- 模式切换保位置（texglot planModeChange） ----------

    const planModeChange = (next: Mode) => {
        if (next === mode()) return;
        const src = handles()[active()] ?? handles().original ?? handles().translated;
        if (src) {
            const from = src.side;
            const pos = capturePos(src);
            // 目标侧：split → 当前隐藏的对侧；单栏 → next 对应侧
            const target: DocId =
                next === "split" ? (from === "original" ? "translated" : "original") : next;
            const dst = handles()[target];
            if (dst) {
                // 目标窗格仍在挂载态（split→单栏留下的一侧），paneReady 不会再火——
                // 立即跳，不留 pendingJump 污染下次挂载
                const to = from === target ? pos : mapper()(pos, from);
                requestAnimationFrame(() => dst.jump(to));
            } else {
                pendingJump = { from, pos };
            }
        }
        setMode(next);
        persistPosition();
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

    const saveNow = () => {
        const positions: Partial<Record<DocId, Pos>> = {};
        for (const side of ["original", "translated"] as const) {
            const h = handles()[side];
            if (!h || !paneVisible(side)) continue;
            try {
                positions[side] = capturePos(h);
            } catch {
                /* 拆解期 slick 已空——跳过该侧 */
            }
        }
        // 无可写位置（窗格未挂/已卸）不发——空表会覆盖服务端已存位置
        if (Object.keys(positions).length === 0) return;
        void api
            .putPosition(props.taskId, {
                positions,
                active: active(),
                mode: mode(),
                zoom: zoom(),
                sync: syncing(),
                document_version: info()?.documents.translated?.version,
            })
            .catch(() => undefined);
    };

    const persistPosition = () => {
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(saveNow, SAVE_DEBOUNCE_MS);
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

    /** 缩放值落单个窗格：% → setScale；命名值 → setScaleValue；HTML 侧无接口跳过 */
    const applyZoomTo = (h: AnyHandle | undefined, z: string) => {
        const ph = h as PaneHandle | undefined;
        if (!z || !ph?.setScaleValue) return;
        if (z.endsWith("%")) ph.setScale(Number(z.slice(0, -1)) / 100);
        else ph.setScaleValue(z);
    };

    // zoom × handles 响应式落地：usePDFSlick 初值恒 page-width（§5.1 坑），
    // reading.zoom 恢复、窗格 keyed 重挂、用户改缩放三路共用——在 paneReady
    // 里手工补赶不上 setInfo→setZoom 之间的 await 窗口
    createEffect(() => {
        const z = zoom();
        for (const side of ["original", "translated"] as const) {
            applyZoomTo(handles()[side], z);
        }
    });

    const applyZoom = (z: string) => {
        setZoom(z);
        persistPosition();
    };

    const gotoPage = (n: number) => {
        handles()[active()]?.gotoPage?.(n);
    };

    const downloads = createMemo<DownloadItem[]>(() => {
        const m = manifest();
        if (!m) return [];
        // manifest.artifacts → db kind→url 同形状，排序/标签/直链走 taskFiles
        return downloadItems(
            Object.fromEntries(Object.entries(m.artifacts).map(([k, e]) => [k, e.url])),
        );
    });

    const docUrl = (side: DocId) => {
        const i = info();
        const doc = i?.documents[side];
        if (!i || !doc) return "";
        // side→kind 映射按 view 分：dom 链产物是 {en|zh}.html
        const kind: FileKind =
            i.view === "dom"
                ? side === "original"
                    ? "en.html"
                    : "zh.html"
                : side === "original"
                  ? "en.pdf"
                  : "zh.pdf";
        // 优先服务端给的 url；否则按 files 约定拼（带版本校验防旧版，§2.3）
        return doc.url || api.fileUrl(props.taskId, kind, { version: doc.version });
    };

    const title = () => task()?.title || task()?.arxiv_id || props.taskId;
    // html 视图需 dual.json chunks 到位才成立；登记 html 却无渲染材料 → empty 空态；
    // readerGone（doc 类任务）→ files 产物面板
    const view = () => resolveReaderView(info(), dual(), readerGone());
    const isDom = () => view() === "dom";
    const isPdf = () => view() !== "html" && view() !== "dom";
    const live = () => taskStore.live(props.taskId);
    const activeTask = () => {
        const s = task();
        return !!s && !isTerminal(s.status);
    };

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
            // 同 id 重跑：清产物快照 + 清上一轮 SSE 痕迹，界面回到进度视图
            setInfo(null);
            setDual(undefined);
            setManifest(null);
            setReaderGone(false);
            pendingJump = null;
            restoredSides.clear();
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
            setShareResult(null);
            setShareError(null);
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
    const [htmlBusy, setHtmlBusy] = createSignal(false);
    const [htmlErr, setHtmlErr] = createSignal("");
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

    const SHARE_ERR_TEXT: Record<string, string> = {
        share_pack_rejected: t.reader.shareErrRejected,
        share_pack_artifacts: t.reader.shareErrArtifacts,
        share_pack_failed: t.reader.shareErrFailed,
    };

    /** code → 可读文案；映射外的错回退服务端 detail */
    const shareErrText = (ae: ApiError | null, e: unknown) => {
        const detail = ae?.detail ?? (e instanceof Error ? e.message : String(e));
        const mapped =
            ae?.status === 409 ? t.reader.shareErrState : SHARE_ERR_TEXT[ae?.code ?? ""];
        return mapped ? (detail ? `${mapped}（${detail}）` : mapped) : detail;
    };

    const onSharePack = async () => {
        if (shareBusy() || shareResult()) return;
        setShareBusy(true);
        setShareError(null);
        try {
            setShareResult(await api.sharePack(props.taskId));
        } catch (e) {
            const ae = e instanceof ApiError ? e : null;
            setShareError({ code: ae?.code, message: shareErrText(ae, e) });
        } finally {
            setShareBusy(false);
        }
    };

    /** 分享块：按钮 → 成功态（share_key + 共享目录提示）/ 可读错误。自门控 canShare */
    const renderShareBlock = () => (
        <Show when={canShare()}>
            <span class="share-pack">
                <Show
                    when={!shareResult()}
                    fallback={
                        <span class="share-ok">
                            {t.reader.shareOk}
                            <code class="share-key">{shareResult()!.share_key}</code>
                            <span class="muted">{t.reader.shareOkHint}</span>
                        </span>
                    }
                >
                    <button
                        type="button"
                        class="tb-btn share-btn"
                        disabled={shareBusy()}
                        title={t.reader.shareBtnTip}
                        onClick={() => void onSharePack()}
                    >
                        {shareBusy() ? t.reader.shareBusy : t.reader.shareBtn}
                    </button>
                </Show>
                <Show when={shareError()}>
                    {(e) => (
                        <span class="form-error share-err">
                            [{e().code ?? "share_pack"}] {e().message}
                        </span>
                    )}
                </Show>
            </span>
        </Show>
    );

    // ---------- 进度视图 / 结果面板的数据加工 ----------

    /** 终态非 done → 结果面板/横幅的状态键；done 或进行中 → null */
    const resultStatus = () => {
        const s = task()?.status;
        return s && isTerminal(s) && s !== "done" ? s : null;
    };

    const RESULT_TEXT: Record<string, string> = {
        fault: t.reader.resultFault,
        partial: t.reader.resultPartial,
        cancelled: t.reader.resultCancelled,
        interrupted: t.reader.resultInterrupted,
        needs_auth: t.reader.resultNeedsAuth,
    };


    const pad2 = (n: number) => String(n).padStart(2, "0");
    const fmtClock = (at: number) => {
        const d = new Date(at * 1000);
        return `${pad2(d.getHours())}:${pad2(d.getMinutes())}:${pad2(d.getSeconds())}`;
    };
    const fmtElapsed = (sec: number) => {
        const s = Math.max(0, Math.floor(sec));
        const m = Math.floor(s / 60);
        const h = Math.floor(m / 60);
        return h > 0 ? `${h}:${pad2(m % 60)}:${pad2(s % 60)}` : `${m}:${pad2(s % 60)}`;
    };

    /** 统计条：chunk 帧优先，快照 counters 兜底；tokens 只有快照带 */
    const progStats = () => {
        const c = live()?.chunk;
        const k = task()?.counters;
        return {
            done: c?.done ?? k?.done ?? 0,
            total: c?.total ?? k?.total ?? 0,
            cached: c?.cached ?? k?.cached ?? 0,
            failed: c?.failed ?? k?.failed ?? 0,
            tokens: k?.tokens ?? 0,
        };
    };
    const elapsed = () => {
        const ca = task()?.created_at;
        return ca ? Math.max(0, now() / 1000 - ca) : 0;
    };

    /** 结果面板统计：done.stats 优先 + 快照 counters/usage 兜底（taskStats.ts） */
    const resultStats = () =>
        mergeResultStats(live()?.done?.stats, task()?.counters, task()?.usage);

    let logPre: HTMLPreElement | undefined;
    let logDrawer: HTMLDetailsElement | undefined;
    const scrollLog = () => {
        if (logDrawer?.open && logPre) logPre.scrollTop = logPre.scrollHeight;
    };
    // 新日志落地后贴底（For 渲染先于 effect，scrollHeight 已是新值）
    createEffect(() => {
        void live()?.logs.length;
        scrollLog();
    });

    /** 终态面板主体：状态文案 + 错误 + 警告 + 统计 + 重试（横幅与整页共用） */
    const renderResultBody = (st: string) => (
        <>
            <h2 class="rp-status">{RESULT_TEXT[st] ?? t.status[st] ?? st}</h2>
            <Show when={task()?.error}>
                {(e) => (
                    <p class="form-error">
                        [{e().code}] {e().message}
                        {e().retryable ? t.reader.retryable : ""}
                    </p>
                )}
            </Show>
            <Show when={retryError()}>
                {(e) => (
                    <p class="form-error" role="alert">
                        [{e().code ?? "retry"}] {e().message}
                        <Show when={e().status === 401 || e().code === "auth_required"}>
                            {" "}
                            {t.reader.retryHintAuth}
                        </Show>
                    </p>
                )}
            </Show>
            <Show when={(task()?.warnings?.length ?? 0) > 0}>
                <ul class="warn-list">
                    <For each={task()!.warnings}>{(w) => <li>{w}</li>}</For>
                </ul>
            </Show>
            <Show when={resultStats()}>
                {(s) => (
                    <dl class="stat-strip">
                        <Show when={s().tokens != null}>
                            <div class="stat">
                                <dt>{t.reader.statsTokens}</dt>
                                <dd class="stat-num">{s().tokens}</dd>
                            </div>
                        </Show>
                        <Show when={s().prompt != null}>
                            <div class="stat">
                                <dt>{t.reader.statsPrompt}</dt>
                                <dd class="stat-num">{s().prompt}</dd>
                            </div>
                        </Show>
                        <Show when={s().completion != null}>
                            <div class="stat">
                                <dt>{t.reader.statsCompletion}</dt>
                                <dd class="stat-num">{s().completion}</dd>
                            </div>
                        </Show>
                        <Show when={s().calls != null}>
                            <div class="stat">
                                <dt>{t.reader.statsCalls}</dt>
                                <dd class="stat-num">{s().calls}</dd>
                            </div>
                        </Show>
                        <Show when={s().latency != null}>
                            <div class="stat">
                                <dt>{t.reader.statsLatency}</dt>
                                <dd class="stat-num">{fmtElapsed(s().latency ?? 0)}</dd>
                            </div>
                        </Show>
                        <Show when={s().seconds != null}>
                            <div class="stat">
                                <dt>{t.reader.statsSeconds}</dt>
                                <dd class="stat-num">{fmtElapsed(s().seconds ?? 0)}</dd>
                            </div>
                        </Show>
                        <Show when={s().failed != null}>
                            <div class="stat">
                                <dt>{t.reader.statsFailed}</dt>
                                <dd class="stat-num">{s().failed}</dd>
                            </div>
                        </Show>
                    </dl>
                )}
            </Show>
            <div class="rp-actions">
                <Show when={st === "needs_auth"}>
                    <input
                        type="password"
                        class="auth-key-input"
                        placeholder={t.reader.authKeyPlaceholder}
                        value={authKey()}
                        disabled={retrying()}
                        onInput={(e) => setAuthKey(e.currentTarget.value)}
                    />
                </Show>
                <button
                    type="button"
                    class="tb-btn"
                    disabled={retrying()}
                    onClick={() => void onRetry()}
                >
                    {retrying() ? t.reader.retrying : t.reader.retry}
                </button>
                <Show when={canTryHtml()}>
                    <button
                        type="button"
                        class="tb-btn"
                        disabled={htmlBusy()}
                        title={t.reader.tryHtmlHint}
                        onClick={() => void onTryHtml()}
                    >
                        {htmlBusy() ? t.reader.retrying : t.reader.tryHtml}
                    </button>
                </Show>
                <Show when={htmlErr()}>
                    {(m) => (
                        <p class="form-error" role="alert">
                            {m()}
                        </p>
                    )}
                </Show>
                <Show when={st === "needs_auth"}>
                    <span class="muted">{t.reader.retryHintAuth}</span>
                </Show>
                {renderShareBlock()}
            </div>
        </>
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

    const renderPane = (side: DocId) => {
        // keyed Show 的 when 不许 ""(falsy 联合只收 false|null|undefined)→ || undefined
        const version = () => info()?.documents[side]?.version || undefined;
        return (
            <div class="pane-slot">
                {/* 三层：dom → DomPane（序列化 DOM 产物）/ html → HtmlPane
                    （chunks→marked）/ pdf → PdfPane。dom 与 pdf 同按
                    doc.version keyed 重挂——重译后旧产物不留残影；
                    document 缺侧（该侧无产物）→ 占位 veil */}
                <Show
                    when={!isDom()}
                    fallback={
                        <Show
                            when={version()}
                            keyed
                            fallback={
                                <div class="pane-veil pane-empty">
                                    <p class="muted">{t.reader.docMissing}</p>
                                </div>
                            }
                        >
                            {(_v) => (
                                <DomPane
                                    side={side}
                                    url={docUrl(side)}
                                    active={active() === side}
                                    onReady={(h) => paneReady(side, h)}
                                    onDispose={(h) => paneDisposed(side, h)}
                                    onActivate={() => setActive(side)}
                                    onScroll={onUserScroll}
                                />
                            )}
                        </Show>
                    }
                >
                    <Show
                        when={isPdf()}
                        fallback={
                            <HtmlPane
                                side={side}
                                chunks={dual()?.chunks ?? []}
                                active={active() === side}
                                onReady={(h) => paneReady(side, h)}
                                onDispose={(h) => paneDisposed(side, h)}
                                onActivate={() => setActive(side)}
                                onScroll={onUserScroll}
                            />
                        }
                    >
                        <Show
                            when={version()}
                            keyed
                            fallback={
                                <div class="pane-veil pane-empty">
                                    <p class="muted">{t.reader.docMissing}</p>
                                </div>
                            }
                        >
                            {(_v) => (
                                <PdfPane
                                    url={docUrl(side)}
                                    side={side}
                                    annotName={annotFileName(props.taskId, side)}
                                    active={active() === side}
                                    onReady={(h) => paneReady(side, h)}
                                    onDispose={(h) => paneDisposed(side, h)}
                                    onPageChange={(p) =>
                                        setPageNums((s) => ({ ...s, [side]: p }))
                                    }
                                    onActivate={() => setActive(side)}
                                    onScroll={onUserScroll}
                                />
                            )}
                        </Show>
                    </Show>
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
                    <Show when={live()?.transport && live()!.transport !== "live"}>
                        <p class="transport-badge" role="status">
                            {t.progress.reconnecting}
                        </p>
                    </Show>
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
                                        {t.status[s] ?? s}
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
                    <Show when={(live()?.stages.length ?? 0) > 0}>
                        <ol class="stage-timeline">
                            <For each={live()!.stages}>
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
                    <Show when={live()?.chunk}>
                        {(c) => (
                            <ProgressGrid
                                total={c().total}
                                done={c().done}
                                cached={c().cached}
                                failed={c().failed}
                                items={live()?.chunkItems ?? []}
                            />
                        )}
                    </Show>
                    <Show when={(live()?.warnings.length ?? 0) > 0}>
                        <p class="warn-title muted">{t.progress.warnings}</p>
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
                    <details class="log-drawer" ref={(el) => (logDrawer = el)} onToggle={scrollLog}>
                        <summary>{t.progress.log}</summary>
                        <pre ref={(el) => (logPre = el)}>
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
            <Show
                when={
                    !fatal() &&
                    !activeTask() &&
                    (view() === "pdf" || view() === "html" || view() === "dom")
                }
            >
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
                    canGotoPage={isPdf() || isDom()}
                    onMode={planModeChange}
                    onSync={setSync}
                    onZoom={applyZoom}
                    onGotoPage={gotoPage}
                    onSwap={() => setSwapped((v) => !v)}
                    onActiveSide={setActive}
                    onRetry={() => void onRetry()}
                    onCancel={() => void api.cancel(props.taskId)}
                    onBack={() => props.nav("#/")}
                />
                {/* 有产物的非干净终态（partial 等）：横幅提示，不挡阅读 */}
                <Show when={resultStatus()}>
                    <section class={`result-banner st-${resultStatus()}`}>
                        {renderResultBody(resultStatus()!)}
                    </section>
                </Show>
                {/* done 且无结果横幅：§6 完成后提示分享（partial 的分享钮在结果横幅内） */}
                <Show when={task()?.status === "done" && canShare()}>
                    <section class="result-banner share-banner">
                        <span class="rp-status">{t.reader.shareBanner}</span>
                        {renderShareBlock()}
                    </section>
                </Show>
                <div class="panes" classList={{ swapped: swapped(), single: mode() !== "split" }}>
                    <Show when={paneVisible("original")}>{renderPane("original")}</Show>
                    <Show when={paneVisible("translated")}>{renderPane("translated")}</Show>
                </div>
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
                        {renderShareBlock()}
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
