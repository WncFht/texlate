// citeTranslate —— 引用文献翻译编排层（纯逻辑，无 JSX）。
// 规格：docs/dev/projects/ux-impl-2026-09-22/cite-translate 实现文档。
//
// 三件面：
//   ① 状态机——createRefStatus（SSE 帧参考归约器，cardbutton.py 移植）+
//      refViewOf（行投影：taskByArxiv 行 + live 帧面 → chip 视图态）。
//      行投影是主路（4.3% 任务零事件帧，纯 SSE 永不收敛——行状态兜底必须）；
//      归约器供帧流宿主（卡脚按钮若要接 live 帧逐帧喂）与测试面。
//   ② 提交——createCiteTranslate 工厂：单条 submit（202/200/409/401/429/400
//      六路分派）+ 批量 submitAll（new 臂串行 await，429 即停）+ preflight
//      三桶（GET /api/tasks 一拍，双侧 canonRefId 归一——免钉版重提的幽灵
//      202 行）+ 凭证门（has_api_key===false / 401 → onNeedAuth 内联回调）。
//   ③ i18n——ctText：t.citeTran / t.cite 扩展键安全取键（键未合入前双语
//      兜底直渲）；键清单=CT_I18N 两份表，整合期照抄进 zh.ts/en.ts。
//
// 幂等：api.translate 内部 createFp("translate",{arxivId,body},byok)——fp
// 天然含 arxivId，每条独立 Idempotency-Key（绝不跨条目复用：同 key 异 id
// 会回旧行，V5 实证）。401 补 key 重发同 fp 换新 key（ApiError 已结案）。
//
// 观测：回包 task_id 一律 taskStore.track(taskId,{arxivId})——wanted(pin:false)
// 登记 + intents 竞态桥（列表行物化前 taskByArxiv 已可解）。批任务不开独立
// SSE（MAX_SSE_TASKS=3 硬顶）——槽空时 transport 自分配，槽满骑共享列表
// 3s 轮询，面板行不显示位次（queue_position 仅单任务快照有）。

import {
    api,
    ApiError,
    apiErrText,
    isFailed,
    isTerminal,
    type ByokHeaders,
    type TaskSnapshot,
    type TaskStage,
    type TaskStatus,
    type TranslateOptions,
    type TranslateResponse,
} from "../api/client";
import { taskStore, type TaskLive } from "../stores/tasks";
import { toast, type ToastAction } from "../stores/toastStore";
import { tLane } from "../i18n";
import { canonRefId, type BibEntry } from "./citations";
import { readerHashWithFrom } from "./tasknav";

// ---------------------------------------------------------------- i18n 键面
// 整合期合入 zh.ts/en.ts 的键清单（两份表同键）；合入前经 ctText 双语兜底。

const CT_CITE_ZH = {
    translate: "翻译此文",
    queued: "排队中",
    translating: "翻译中",
    openZh: "打开译文",
    retryRef: "重试",
    authNeed: "需要 API Key",
} as const;
const CT_CITE_EN: Record<keyof typeof CT_CITE_ZH, string> = {
    translate: "Translate",
    queued: "Queued",
    translating: "Translating",
    openZh: "Open translation",
    retryRef: "Retry",
    authNeed: "API key required",
};

const CT_TRAN_ZH = {
    refs: "文献",
    panelTitle: "引用文献",
    close: "关闭",
    translateAll: "翻译全部",
    idArxiv: "arXiv",
    idDoi: "DOI",
    idNone: "无 id",
    confirmTitle: "翻译引用文献",
    counts: "共 {total} 篇可翻译：{n_new} 篇新任务，{n_active} 篇已在队列，{n_done} 篇已有译文",
    waitEta: "串行处理，预计全部完成约需 {lo}–{hi}",
    hint: "已译文献不重复排队；任务在后台运行，可随时离开",
    cta: "翻译 {n} 篇",
    ctaAllDone: "全部已有译文",
    warnBig: "一次提交 {n} 篇将占用队列约 {lo}–{hi}——建议分批或先译高优先",
    toastQueued: "已加入队列",
    toastDone: "已有译文",
    toastView: "查看",
    toastQuota: "配额已满",
    toastBatchQuota: "已提交 {k}/{n}，配额已满",
    toastAuth: "缺少 API Key——输入后继续提交",
    authPlaceholder: "输入 API Key 后重试",
    authSubmit: "用此 Key 继续",
    authCancel: "取消",
    compiling: "编译中",
    failedChunks: "{n} 段失败",
    authKeyCta: "输 Key 重试",
    preflightBusy: "统计中…",
    submitBusy: "提交中…",
} as const;
const CT_TRAN_EN: Record<keyof typeof CT_TRAN_ZH, string> = {
    refs: "Refs",
    panelTitle: "References",
    close: "Close",
    translateAll: "Translate all",
    idArxiv: "arXiv",
    idDoi: "DOI",
    idNone: "no id",
    confirmTitle: "Translate references",
    counts: "{total} translatable: {n_new} new, {n_active} already queued, {n_done} already translated",
    waitEta: "Processed serially — all done in ~{lo}–{hi}",
    hint: "Translated papers are skipped; tasks run in background",
    cta: "Translate {n}",
    ctaAllDone: "All translated",
    warnBig:
        "Submitting {n} at once occupies the queue ~{lo}–{hi} — consider a smaller batch",
    toastQueued: "Queued",
    toastDone: "Already translated",
    toastView: "View",
    toastQuota: "Quota exhausted",
    toastBatchQuota: "Submitted {k}/{n} — quota exhausted",
    toastAuth: "API key required — enter it to continue",
    authPlaceholder: "Enter API key to retry",
    authSubmit: "Continue with this key",
    authCancel: "Cancel",
    compiling: "Compiling",
    failedChunks: "{n} chunks failed",
    authKeyCta: "Enter key & retry",
    preflightBusy: "Counting…",
    submitBusy: "Submitting…",
};

export type CiteTranKey = keyof typeof CT_TRAN_ZH;
export type CiteChipKey = keyof typeof CT_CITE_ZH;

/**
 * cite-translate 文案统一取键口：`cite.xxx` 走 t.cite 扩展段，其余走
 * t.citeTran 新组——键未落地时按 currentLang 双语兜底（类型面不报错的
 * 运行期取键，与 tasks.ts notifyTpl 同手法）。
 */
export function ctText(
    key: CiteTranKey | `cite.${CiteChipKey}`,
    vars?: Record<string, string | number>,
): string {
    if (key.startsWith("cite."))
        return tLane(
            "cite",
            key.slice(5),
            { zh: CT_CITE_ZH, en: CT_CITE_EN },
            vars,
        );
    return tLane("citeTran", key, { zh: CT_TRAN_ZH, en: CT_TRAN_EN }, vars);
}

// ---------------------------------------------------------------- 状态机
// cardbutton.py 移植（ct-card-states 实证）：带环非 DAG——终态帧后再见
// stage 帧 = retry 新轮（同 task_id 同 append-only 事件流，无轮次标记）。

export type RefPhase = "idle" | "queued" | "running" | "done" | "failed";

const RUN_STAGES: ReadonlySet<string> = new Set([
    "fetching",
    "parsing",
    "translating",
    "compiling",
]);
/** 交付桶——partial=降级交付归 done 相（徽标区分 failed_chunks） */
const DONE_OK: ReadonlySet<string> = new Set(["done", "partial"]);

/** translating 段内插值（与 server _translate_progress 同式 band） */
export function translateBandPct(done: number, total: number): number {
    return Math.min(85, 25 + Math.floor((60 * done) / Math.max(1, total)));
}

/**
 * SSE 帧 → 卡钮状态归约器（参考实现；帧逐次喂入，run_id 自增标记轮次）。
 * 两路入口：SSE 帧（feedStage/feedChunk/feedDone）或行快照（feedSnapshot）。
 */
export interface RefStatus {
    phase: RefPhase;
    status: TaskStatus | undefined;
    stage: TaskStage | undefined;
    /** band 锚点（最近 stage 帧 progress；终态钉 100 / 败终态冻结末值） */
    anchor: number;
    done: number;
    total: number;
    failed: number;
    queuePos: number | undefined;
    /** 终态→stage 回边计数（retry 新轮复位 pct 的挂钩） */
    runId: number;
}

export function createRefStatus() {
    const s: RefStatus = {
        phase: "idle",
        status: undefined,
        stage: undefined,
        anchor: 0,
        done: 0,
        total: 0,
        failed: 0,
        queuePos: undefined,
        runId: 0,
    };
    let terminalSeen = false;
    const newRun = () => {
        if (!terminalSeen) return;
        terminalSeen = false;
        s.runId += 1;
        s.done = s.total = s.failed = 0;
    };
    const self = {
        state: s,
        /** stage 帧：终态后再见 = retry 新轮（复位计数器） */
        feedStage(stage: TaskStage, progress: number) {
            newRun();
            s.status = s.stage = stage;
            s.anchor = progress;
            s.phase = "running";
            s.queuePos = undefined;
        },
        /** chunk 帧：不带 progress 字段——只喂计数器，translating 插值在 pct */
        feedChunk(done: number, total: number, failed = 0) {
            s.done = done;
            s.total = total;
            s.failed = failed;
        },
        feedDone(status: TaskStatus) {
            s.status = status;
            terminalSeen = true;
            s.stage = undefined;
            s.phase = DONE_OK.has(status) ? "done" : "failed";
            if (DONE_OK.has(status)) s.anchor = 100;
        },
        /** 行快照（snapshot/列表轮询——零事件帧任务的唯一收敛路） */
        feedSnapshot(row: TaskSnapshot) {
            const st = row.status;
            if (RUN_STAGES.has(st)) {
                newRun();
                s.status = s.stage = st as TaskStage;
                s.anchor = row.progress ?? 0;
                s.phase = "running";
            } else if (st === "queued") {
                s.status = st;
                s.phase = "queued";
                s.queuePos = row.queue_position;
            } else if (isTerminal(st)) {
                s.status = st;
                terminalSeen = true;
                s.phase = DONE_OK.has(st) ? "done" : "failed";
                s.anchor = DONE_OK.has(st) ? 100 : (row.progress ?? 0);
            }
            const c = row.counters;
            if (c) {
                s.done = c.done ?? s.done;
                s.total = c.total ?? s.total;
                s.failed = c.failed ?? s.failed;
            }
        },
        /** band 映射：queued=0 / done=100 / failed=冻结锚点 / translating 插值 */
        get pct(): number {
            if (s.phase === "done") return 100;
            if (s.phase === "idle" || s.phase === "queued") return 0;
            if (s.phase === "failed") return s.anchor;
            if (s.stage === "translating")
                return translateBandPct(s.done, s.total);
            return s.anchor;
        },
        view() {
            return {
                phase: s.phase,
                pct: self.pct,
                queuePosition: s.queuePos,
                failed: s.failed,
                status: s.status,
                runId: s.runId,
            };
        },
    };
    return self;
}
export type RefStatusReducer = ReturnType<typeof createRefStatus>;

// ---------------------------------------------------- 行投影（组件主路）

/** chip 视图相：五态机 + needs_auth 单列（输 key CTA 不交状态机） */
export type RefChipPhase = RefPhase | "needsAuth";

export interface RefView {
    phase: RefChipPhase;
    /** 0-100；行路直读 progress 列（服务端同 band 口径，无需本地插值） */
    pct: number;
    taskId: string | undefined;
    status: TaskStatus | undefined;
    queuePos: number | undefined;
    /** partial 徽标——chunk 帧/live.done stats/行 counters 三路取失败数 */
    failedChunks: number;
    /** running 细分（编译中 vs 翻译中粗相标签用） */
    stage: TaskStage | undefined;
}

/**
 * 行状态兜底投影（规格 §A：4.3% 任务零事件帧——行状态是必须面，SSE 帧
 * 只是增量补强）。row=taskByArxiv 命中行（含 intents 合成占位 queued 行），
 * live=taskStore.live(row.task_id)（在槽任务的 stage/chunk/done 帧面）。
 * retry 回边天然覆盖：resetLive 清 done + stage 帧 patch 行 status——行投影
 * 每拍重算，无状态残件。
 */
export function refViewOf(
    row: TaskSnapshot | undefined,
    live?: TaskLive | undefined,
): RefView {
    if (!row) {
        return {
            phase: "idle",
            pct: 0,
            taskId: undefined,
            status: undefined,
            queuePos: undefined,
            failedChunks: 0,
            stage: undefined,
        };
    }
    const st = row.status;
    const stage = live?.stage?.stage ?? row.stage ?? undefined;
    const failedChunks =
        live?.chunk?.failed ??
        live?.done?.stats?.chunks_failed ??
        row.counters?.failed ??
        0;
    const base = {
        taskId: row.task_id,
        status: st,
        queuePos: st === "queued" ? row.queue_position : undefined,
        failedChunks,
        stage,
    };
    if (st === "queued") return { ...base, phase: "queued", pct: 0 };
    if (DONE_OK.has(st)) return { ...base, phase: "done", pct: 100 };
    if (st === "needs_auth") return { ...base, phase: "needsAuth", pct: 0 };
    if (isFailed(st))
        return { ...base, phase: "failed", pct: row.progress ?? 0 };
    return { ...base, phase: "running", pct: row.progress ?? 0 };
}

// ---------------------------------------------------------------- ETA 带
// 服务时长实测（4391 条）：p50=47s / p90=236s——串行队列 N 篇 ETA=N×[47,236]。

export const REF_ETA_LO_S = 47;
export const REF_ETA_HI_S = 236;
/** n_new>15 触发 warn_big 警示条（p90 批量即 22min–1.8h 串行） */
export const REF_WARN_BIG = 15;

/** (n_active+n_new) 篇串行 ETA 区间（秒） */
export function estimateEta(n: number): { lo: number; hi: number } {
    return { lo: n * REF_ETA_LO_S, hi: n * REF_ETA_HI_S };
}

/**
 * 秒 → 紧凑时段串（对齐实测文案表）：<90s→"47s"；<50min→"{m}min"（round）；
 * 其余 → "{h}h" 一位小数去 .0（3540s→"1h"、5896s→"1.6h"、14160s→"3.9h"）。
 */
export function fmtEta(sec: number): string {
    if (sec < 90) return `${Math.round(sec)}s`;
    if (sec < 3000) return `${Math.round(sec / 60)}min`;
    const h = (sec / 3600).toFixed(1).replace(/\.0$/, "");
    return `${h}h`;
}

// ---------------------------------------------------------------- 提交编排

/** 可译条目面（面板行/卡脚共用——id 已解析 arxivId） */
export interface RefItem {
    /** 解析出的 arXiv id（原样；canon 归一在内部做） */
    arxivId: string;
    entry?: BibEntry;
}

/** 单条提交回执——七态分派结果（组件按 kind 渲后续） */
export type CiteSubmitOutcome =
    | { kind: "queued"; taskId: string }
    | { kind: "done"; taskId: string }
    /** 409 duplicate_active / 200 reused 非 done（needs_auth 等）——指向回包行 */
    | { kind: "existing"; taskId: string; status?: TaskStatus }
    | { kind: "auth"; retry(apiKey: string): Promise<CiteSubmitOutcome> }
    | { kind: "quota" }
    | { kind: "error"; message: string };

export interface PreflightRow<I extends RefItem = RefItem> {
    item: I;
    row: TaskSnapshot;
}

/** preflight 三桶（done 已译 / active 在队 / fresh 新） */
export interface PreflightBuckets<I extends RefItem = RefItem> {
    done: PreflightRow<I>[];
    active: PreflightRow<I>[];
    fresh: I[];
    counts: { total: number; done: number; active: number; fresh: number };
}

export interface BatchOutcome {
    /** 202 新入队数 */
    submitted: number;
    /** 200/409 收编数（已有任务，不算新提交） */
    absorbed: number;
    /** 失败明细（400/网络错等——429/401 走 stoppedBy） */
    failed: { arxivId: string; message: string }[];
    /** 半途截断原因——配额即停（已提交 submitted 条）/ 凭证门 */
    stoppedBy?: "quota" | "auth";
}

export interface CiteTranslateDeps {
    /** 翻译体透传源（当前任务的 model/target_lang/glossary/options——
        M10 口径，options.idempotency_key 摘除） */
    body?(): TranslateOptions | undefined;
    /** per-request BYOK（inline key 输入后由工厂记忆进 sessionKey） */
    byok?(): ByokHeaders | undefined;
    /** 凭证门判据——settingsStore.settings()?.has_api_key（===false 才闸；
        undefined=未加载不闸，交给 401 回执面） */
    hasApiKey?(): boolean | undefined;
    /**
     * 401/has_api_key=false → 内联 key 面板回调节点。retry(key) 重发同
     * 请求（同 fp 新 idem key）；缺省 = err toast 指设置页。
     */
    onNeedAuth?(retry: (apiKey: string) => Promise<void>): void;
    nav?(to: string): void;
    /** toast 注入点（测试 spy；缺省 toast store）。action 形与
        ToastAction 同构（href 直跳 / onClick 回调二选一） */
    toastOk?(text: string, action?: ToastAction): void;
    toastErr?(text: string): void;
    /** 观测登记（缺省 taskStore.track） */
    track?(taskId: string, arxivId: string): void;
    /** 测试缝——任务列表（缺省 api.tasks） */
    listTasks?(): Promise<TaskSnapshot[]>;
    /** 测试缝——POST translate（缺省 api.translate：fp 含 arxivId，
        每条独立 Idempotency-Key） */
    postTranslate?(
        arxivId: string,
        body: TranslateOptions,
        byok?: ByokHeaders,
    ): Promise<TranslateResponse>;
}

const OPEN_HASH = (taskId: string) => readerHashWithFrom(taskId);

export interface CiteTranslate {
    submit(
        arxivId: string,
        opts?: { apiKey?: string; quiet?: boolean },
    ): Promise<CiteSubmitOutcome>;
    submitAll(
        items: readonly RefItem[],
        opts?: { apiKey?: string },
    ): Promise<BatchOutcome>;
    preflight<I extends RefItem>(
        items: readonly I[],
    ): Promise<PreflightBuckets<I>>;
    /** 会话级 key——401/门后用户输入的 key 记忆，后续提交自动重带 */
    sessionKey(): string | undefined;
    setSessionKey(k: string): void;
    /** 当前会话是否可免 key 直发（stored key 或已收 sessionKey） */
    keyReady(): boolean;
    /**
     * 内联 key 面板宿主热挂/摘（RefsPanel 挂载期间自登记为宿主——批内
     * 401/门收 key 走面板内联框而非工厂默认面；摘传 undefined）。返回
     * 当前生效宿主（挂载判断用）。
     */
    setAuthHost(
        host?: (retry: (apiKey: string) => Promise<void>) => void,
    ): void;
    estimateEta: typeof estimateEta;
    fmtEta: typeof fmtEta;
}

export function createCiteTranslate(
    deps: CiteTranslateDeps = {},
): CiteTranslate {
    const post =
        deps.postTranslate ??
        ((id: string, body: TranslateOptions, byok?: ByokHeaders) =>
            api.translate(id, body, byok));
    const list = deps.listTasks ?? (() => api.tasks());
    const track =
        deps.track ??
        ((taskId: string, arxivId: string) =>
            taskStore.track(taskId, { arxivId }));
    const toastOk =
        deps.toastOk ??
        ((text: string, action?: ToastAction) =>
            toast.ok(text, action ? { action } : {}));
    const toastErr = deps.toastErr ?? ((text: string) => toast.err(text));
    const nav = deps.nav ?? ((to: string) => (location.hash = to));
    /** 「查看」动作：宿主给了 nav 走 onClick 回调（测试可断言），缺省 href */
    const viewAction = (tid: string): ToastAction =>
        deps.nav
            ? {
                  label: ctText("toastView"),
                  onClick: () => nav(OPEN_HASH(tid)),
              }
            : { label: ctText("toastView"), href: OPEN_HASH(tid) };

    let sessionKey: string | undefined;
    /** 内联 key 面板宿主——面板挂载期覆盖 deps.onNeedAuth（批内 401 收
        key 走面板内联框）；undefined 回落 deps 宿主/兜底 toast */
    let authHost:
        ((retry: (apiKey: string) => Promise<void>) => void) | undefined;

    /** 401/凭证门统一出面口：有宿主交宿主（带续跑回调），无宿主 err toast */
    const fireNeedAuth = (retry: (apiKey: string) => Promise<void>) => {
        const host = authHost ?? deps.onNeedAuth;
        if (host) host(retry);
        else toastErr(ctText("toastAuth"));
    };

    /** 翻译体：当前任务全量透传（M10），删 idempotency_key（服务端按它
        dedup——带过去会把新任务吞成旧任务命中） */
    const buildBody = (): TranslateOptions => {
        const b = deps.body?.() ?? {};
        const options: Record<string, unknown> = {
            ...(b.options ?? {}),
        };
        delete options.idempotency_key;
        return {
            model: b.model,
            target_lang: b.target_lang,
            glossary: b.glossary,
            options,
        };
    };

    const byokFor = (apiKey?: string): ByokHeaders | undefined => {
        const key = apiKey ?? sessionKey;
        const base = deps.byok?.() ?? {};
        return key
            ? { ...base, apiKey: key }
            : base.apiKey
              ? base
              : Object.keys(base).length
                ? base
                : undefined;
    };

    const keyReady = () => deps.hasApiKey?.() !== false || !!sessionKey;

    /**
     * 单条提交（内部——quiet 时压 toast，批量路自担汇总条）。
     * apiKey 缺省走 sessionKey→deps.byok() 链。
     */
    const submitRaw = async (
        arxivId: string,
        apiKey: string | undefined,
        quiet: boolean,
    ): Promise<CiteSubmitOutcome> => {
        try {
            const res = await post(arxivId, buildBody(), byokFor(apiKey));
            const tid = res.task_id;
            track(tid, arxivId);
            if (res.reused === true) {
                // 200 reused：done|partial → 可读终态；needs_auth 等 →
                // 收编指向既有行（补 key 走该行 retry 通道，不重建行）
                if (res.status === "done" || res.status === "partial") {
                    if (!quiet) toastOk(ctText("toastDone"), viewAction(tid));
                    return { kind: "done", taskId: tid };
                }
                return { kind: "existing", taskId: tid, status: res.status };
            }
            // 202 cache:miss / cache:idempotent
            if (!quiet) toastOk(ctText("toastQueued"), viewAction(tid));
            return { kind: "queued", taskId: tid };
        } catch (e) {
            const ae = e instanceof ApiError ? e : null;
            // 409 duplicate_active——静默收编为「已在队列」，指向回包
            // task_id（覆盖 interrupted 占键槽/别名归一同行情形）
            if (ae?.status === 409) {
                const tid = ae.taskId ?? ae.detail.match(/t_[0-9a-f]{16}/)?.[0];
                if (tid) {
                    track(tid, arxivId);
                    return { kind: "existing", taskId: tid };
                }
            }
            // 401 auth_required（server 形态匿名写）→ 内联 key 面板回调
            if (ae && (ae.status === 401 || ae.code === "auth_required")) {
                const retry = async (key: string) => {
                    sessionKey = key;
                    return submitRaw(arxivId, key, quiet);
                };
                fireNeedAuth(async (k) => {
                    await retry(k);
                });
                return { kind: "auth", retry };
            }
            // 429 quota_exceeded
            if (ae?.status === 429 || ae?.code === "quota_exceeded") {
                if (!quiet) toastErr(ctText("toastQuota"));
                return { kind: "quota" };
            }
            // 400 invalid id 不该发生（本地已校验）+ 其余错误兜底
            const message = apiErrText(e);
            if (!quiet) toastErr(message);
            return { kind: "error", message };
        }
    };

    const submit: CiteTranslate["submit"] = (arxivId, opts = {}) => {
        const apiKey = opts.apiKey ?? sessionKey;
        // 凭证门（§E）：has_api_key===false 且无 per-request key → 先出
        // 内联 key 框，不裸发（local 无 key 提交会静默产 Mock 译文毒化
        // 段缓存——67% 段毒化实证，prefer=fresh 救不回）
        if (!keyReady() && !apiKey) {
            const retry = async (key: string) => {
                sessionKey = key;
                return submitRaw(arxivId, key, opts.quiet ?? false);
            };
            fireNeedAuth(async (k) => {
                await retry(k);
            });
            return Promise.resolve({ kind: "auth", retry });
        }
        return submitRaw(arxivId, apiKey, opts.quiet ?? false);
    };

    /**
     * 批量灌队：仅 new 臂逐条串行 await（保序；~1.2ms/条实测——提交从不是
     * 瓶颈）。每条独立 Idempotency-Key（api.translate fp 含 arxivId 天然
     * 隔离）。429 即停 + toast 已提交 k/N；401/门 → onNeedAuth 收 key 后续
     * 跑剩余臂（retry 回调即续跑）。
     */
    const submitAll: CiteTranslate["submitAll"] = async (items, opts = {}) => {
        const out: BatchOutcome = { submitted: 0, absorbed: 0, failed: [] };
        const apiKey = opts.apiKey ?? sessionKey;
        if (!keyReady() && !apiKey) {
            out.stoppedBy = "auth";
            fireNeedAuth(async (k) => {
                sessionKey = k;
                await submitAll(items, { apiKey: k });
            });
            return out;
        }
        for (let i = 0; i < items.length; i++) {
            const o = await submitRaw(items[i].arxivId, apiKey, true);
            if (o.kind === "queued") out.submitted += 1;
            else if (o.kind === "done" || o.kind === "existing")
                out.absorbed += 1;
            else if (o.kind === "quota") {
                out.stoppedBy = "quota";
                toastErr(
                    ctText("toastBatchQuota", {
                        k: out.submitted,
                        n: items.length,
                    }),
                );
                break;
            } else if (o.kind === "auth") {
                // 401 半途：收 key 后从断点续跑（已发的不重发）
                out.stoppedBy = "auth";
                const rest = items.slice(i);
                fireNeedAuth(async (k) => {
                    sessionKey = k;
                    await submitAll(rest, { apiKey: k });
                });
                break;
            } else {
                out.failed.push({
                    arxivId: items[i].arxivId,
                    message: o.message,
                });
            }
        }
        return out;
    };

    /**
     * preflight 三桶——1 拍 GET /api/tasks（实测 ~2ms），双侧 canonRefId
     * 归一 arxiv_id 匹配。不可省：bare-id 对已 done 钉版行重提会产幽灵
     * 202 行（REST find_reusable 查裸键错失钉版键），preflight 直接免掉。
     * 桶归属：done|partial→done；非终态→active；needs_auth→active（撞键
     * 重提只会收编回该行——补 key 走 retry，不是新任务）；其余败终态
     * （fault/cancelled/interrupted）→fresh（重提真建行）。多行同 arxiv
     * 取档与 taskByArxiv 同序：可读终态 > 在跑 > 败终态，同档 updated_at 最新。
     */
    const preflight: CiteTranslate["preflight"] = async (items) => {
        const rows = await list();
        const byCanon = new Map<string, TaskSnapshot[]>();
        for (const r of rows) {
            if (!r.arxiv_id) continue;
            const k = canonRefId(r.arxiv_id);
            if (!k) continue;
            const arr = byCanon.get(k) ?? [];
            arr.push(r);
            byCanon.set(k, arr);
        }
        const rankOf = (r: TaskSnapshot): number =>
            DONE_OK.has(r.status) ? 2 : isTerminal(r.status) ? 0 : 1;
        const best = (cands: TaskSnapshot[]): TaskSnapshot => {
            let b = cands[0];
            for (const r of cands) {
                const rb = rankOf(b);
                const rr = rankOf(r);
                if (
                    rr > rb ||
                    (rr === rb && (r.updated_at ?? 0) > (b.updated_at ?? 0))
                )
                    b = r;
            }
            return b;
        };
        const buckets: PreflightBuckets<(typeof items)[number]> = {
            done: [],
            active: [],
            fresh: [],
            counts: { total: items.length, done: 0, active: 0, fresh: 0 },
        };
        for (const item of items) {
            const k = canonRefId(item.arxivId);
            const cands = k ? byCanon.get(k) : undefined;
            const row = cands?.length ? best(cands) : undefined;
            if (!row) {
                buckets.fresh.push(item);
            } else if (DONE_OK.has(row.status)) {
                buckets.done.push({ item, row });
            } else if (!isTerminal(row.status) || row.status === "needs_auth") {
                buckets.active.push({ item, row });
            } else {
                buckets.fresh.push(item);
            }
        }
        buckets.counts.done = buckets.done.length;
        buckets.counts.active = buckets.active.length;
        buckets.counts.fresh = buckets.fresh.length;
        return buckets;
    };

    return {
        submit,
        submitAll,
        preflight,
        sessionKey: () => sessionKey,
        setSessionKey: (k) => {
            sessionKey = k || undefined;
        },
        keyReady,
        setAuthHost: (host) => {
            authHost = host;
        },
        estimateEta,
        fmtEta,
    };
}
