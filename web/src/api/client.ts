// API client —— 对齐 docs/research/product/web-layer.md §2。
// Base /api；错误一律 {detail, code?}；SSE 走原生 EventSource
// （浏览器自动带 Last-Event-ID 重放，§2.2 的重连语义天然满足）。

import type { Alignment, Pos } from "../reader/alignment";

const BASE = "/api";

export type TaskStatus =
    | "queued"
    | "fetching"
    | "parsing"
    | "translating"
    | "compiling"
    | "done"
    | "partial"
    | "fault"
    | "cancelled"
    | "interrupted"
    | "needs_auth";

export type TaskStage = "fetching" | "parsing" | "translating" | "compiling";
export type TaskKind =
    | "arxiv"
    | "arxiv_html"
    | "upload_tex"
    | "upload_pdf"
    | "docx"
    | "epub"
    | "share"
    | string;

export type ErrorCode =
    | "arxiv_fetch"
    | "no_latex_source"
    | "pdf_wrapper"
    | "parse"
    | "provider_auth"
    | "provider_rate"
    | "provider_timeout"
    | "provider_error"
    | "validate"
    | "placeholder_mismatch"
    | "compile"
    | "fixloop_exhausted"
    | "internal"
    | "auth_required"
    | "unsupported_format"
    | string;

export interface TaskCounters {
    total?: number;
    done?: number;
    cached?: number;
    failed?: number;
    tokens?: number;
}

export interface TaskError {
    code: ErrorCode;
    message: string;
    retryable?: boolean;
}

/** task_usage 行（有 LLM 调用记录才带） */
export interface TaskUsage {
    model?: string;
    calls?: number;
    prompt_tokens?: number;
    completion_tokens?: number;
    latency_s?: number;
}

export interface TaskSnapshot {
    task_id: string;
    kind: TaskKind;
    status: TaskStatus;
    progress: number;
    created_at: number;
    updated_at: number;
    stage?: TaskStage;
    message?: string;
    title?: string;
    arxiv_id?: string;
    target_lang?: string;
    model?: string;
    counters?: TaskCounters;
    warnings?: string[];
    error?: TaskError | null;
    artifacts?: Record<string, string>;
    last_seq?: number;
    usage?: TaskUsage;
}

export interface StageEvent {
    stage: TaskStage;
    progress: number;
    message: string;
    at: number;
}

export type ChunkStatus =
    "ok" | "fallback_orig" | "failed" | "pending" | string;

export interface ChunkItem {
    seq: number;
    status: ChunkStatus;
    error_code?: ErrorCode;
}

export interface ChunkEvent {
    done: number;
    total: number;
    cached: number;
    failed: number;
    items: ChunkItem[];
}

export interface LogEvent {
    line: string;
}

export interface WarningEvent {
    code: string;
    message: string;
}

export interface TaskErrorEvent {
    code: ErrorCode;
    message: string;
    stage?: TaskStage;
    retryable: boolean;
    chunk_seq?: number;
}

export interface DoneStats {
    tokens?: number;
    seconds?: number;
    chunks_failed?: number;
    [k: string]: unknown;
}

export interface DoneEvent {
    /** "deleted" 非任务行状态——DELETE 端点对在听的 SSE 流补发的收尾帧 */
    status: TaskStatus | "deleted";
    artifacts: Record<string, string>;
    stats: DoneStats;
}

export interface TranslateOptions {
    model?: string;
    target_lang?: string;
    glossary?: string;
    options?: {
        context_guidance?: boolean;
        concurrency?: number;
        engine?: string;
        prefer?: "reuse" | "fresh";
        /** 取源通道：eprint=LaTeX 主链（默认）| html=arXiv HTML 降级链 */
        source?: "eprint" | "html";
        /** 完成后打包 .share.zip 社区缓存包（shared-cache.md §6 opt-in） */
        share_pack?: boolean;
    };
}

export interface ByokHeaders {
    apiKey?: string;
    baseUrl?: string;
    model?: string;
    idempotencyKey?: string;
}

export interface TranslateResponse {
    task_id: string;
    status: TaskStatus;
    cache?: string;
    reused?: boolean;
    events_url: string;
    /** 仅产 dual.json 的 kind 下发；docx/epub（无对照阅读器）字段缺席 */
    reader_url?: string;
}

/** POST /task/{id}/share/pack 200 体（§6 事后打包） */
export interface SharePackResponse {
    share_key: string;
    /** 服务端共享目录内的扁平包文件名——非可点 URL，给其他实例 import 用 */
    url: string;
    bytes: number;
}

export type FileKind =
    | "en.pdf"
    | "zh.pdf"
    | "dual.pdf"
    | "dual.json"
    | "src.tar"
    | "zh-src.zip"
    | "compile.log"
    | "md"
    | "zh.docx"
    | "zh.epub"
    | "en.html"
    | "zh.html"
    | "src.html";

/** db kind → URL kind（files manifest / snapshot.artifacts / done.artifacts 的键均为 db kind） */
export const DB_TO_URL_KIND: Record<string, FileKind> = {
    en_pdf: "en.pdf",
    zh_pdf: "zh.pdf",
    dual_pdf: "dual.pdf",
    dual_json: "dual.json",
    src_tar: "src.tar",
    zh_src_zip: "zh-src.zip",
    compile_log: "compile.log",
    md_zip: "md",
    zh_docx: "zh.docx",
    zh_epub: "zh.epub",
    en_html: "en.html",
    zh_html: "zh.html",
    src_html: "src.html",
};

export interface FileEntry {
    bytes: number;
    sha256: string;
    created_at: number;
    /** 服务端直接给的下载路径（/api/files/{id}/{url_kind}） */
    url: string;
}

export interface FileManifest {
    artifacts: Record<string, FileEntry>;
}

export interface ReaderDoc {
    version: string;
    pages: number;
    url: string;
}

export type ReaderView = "pdf" | "html" | "dom";

export interface ReadingState {
    positions?: Partial<Record<"original" | "translated", Pos>>;
    active?: "original" | "translated";
    mode?: "original" | "translated" | "split";
    zoom?: string;
    sync?: boolean;
    /** 双栏左右互换（reader 布局态，随阅读位置同持久化） */
    swapped?: boolean;
    /** zh.pdf sha256——不符服务端 409（防旧版位置回灌，§2.5） */
    document_version?: string;
}

export interface ReaderInfo {
    view?: ReaderView;
    /** 哪侧缺哪侧不写：md_zip 路径必缺 translated，en_pdf 缺则 original 缺 */
    documents: {
        original?: ReaderDoc;
        translated?: ReaderDoc;
    };
    alignment?: Alignment;
    reading?: ReadingState | null;
}

export interface DualChunk {
    seq: number;
    src_file?: string;
    en?: string;
    zh?: string;
    kind?: string;
}

export interface DualJson {
    version: number;
    /** 与 ReaderInfo.documents 同规则：哪侧无产物哪侧缺省 */
    documents: {
        original?: { version: string; pages: number };
        translated?: { version: string; pages: number };
    };
    alignment?: Alignment;
    chunks?: DualChunk[];
}

export interface Settings {
    has_api_key?: boolean;
    /** PUT 伪字段：true → 清除服务端已存 api_key（settings.save 弹化为 ""） */
    clear_api_key?: boolean;
    base_url?: string;
    model?: string;
    target_lang?: string;
    glossary?: string;
    engine?: string;
    concurrency?: number;
    [k: string]: unknown;
}

export interface Provider {
    id: string;
    name?: string;
    base_url?: string;
    models?: string[];
    [k: string]: unknown;
}

export interface Health {
    ok: boolean;
    version?: string;
    compilers?: Record<string, unknown>;
    data_dir?: string;
}

export class ApiError extends Error {
    constructor(
        public status: number,
        public detail: string,
        public code?: string,
        /** 结构化 task_id（409 duplicate_active 等错误体附带） */
        public taskId?: string,
    ) {
        super(detail);
        this.name = "ApiError";
    }
}

/** 上传进度回调（loaded/total 字节——lengthComputable 才发） */
export type UploadProgress = (loaded: number, total: number) => void;

async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${BASE}${path}`, init);
    if (!res.ok) {
        let detail = res.statusText;
        let code: string | undefined;
        let taskId: string | undefined;
        try {
            const body = await res.json();
            if (typeof body?.detail === "string") detail = body.detail;
            if (typeof body?.code === "string") code = body.code;
            if (typeof body?.task_id === "string") taskId = body.task_id;
        } catch {
            /* 非 JSON 错误体 */
        }
        throw new ApiError(res.status, detail, code, taskId);
    }
    if (res.status === 204) return undefined as T;
    const ct = res.headers.get("content-type") ?? "";
    return (ct.includes("json") ? res.json() : res.text()) as Promise<T>;
}

/**
 * XHR 版 request——fetch 无上传进度事件，带 onProgress 的 multipart
 * 提交走此路。响应解析口径与 request 一致（JSON 错误体 → ApiError，
 * 网络层失败 → TypeError：createRequest 按「未决」留 idem key）。
 */
function xhrRequest<T>(
    path: string,
    init: RequestInit,
    onProgress?: UploadProgress,
): Promise<T> {
    return new Promise<T>((resolve, reject) => {
        const xhr = new XMLHttpRequest();
        xhr.open(init.method ?? "POST", `${BASE}${path}`);
        const headers = (init.headers ?? {}) as Record<string, string>;
        for (const [k, v] of Object.entries(headers))
            xhr.setRequestHeader(k, v);
        if (onProgress) {
            xhr.upload.onprogress = (e: ProgressEvent) => {
                if (e.lengthComputable && e.total > 0)
                    onProgress(e.loaded, e.total);
            };
        }
        xhr.onload = () => {
            const ct = xhr.getResponseHeader("content-type") ?? "";
            let body: unknown = xhr.responseText;
            if (ct.includes("json") && xhr.responseText) {
                try {
                    body = JSON.parse(xhr.responseText);
                } catch {
                    /* 非 JSON 体按原文 */
                }
            }
            if (xhr.status >= 200 && xhr.status < 300) {
                resolve((xhr.status === 204 ? undefined : body) as T);
                return;
            }
            let detail = xhr.statusText || `HTTP ${xhr.status}`;
            let code: string | undefined;
            let taskId: string | undefined;
            if (body && typeof body === "object") {
                const b = body as Record<string, unknown>;
                if (typeof b.detail === "string") detail = b.detail;
                if (typeof b.code === "string") code = b.code;
                if (typeof b.task_id === "string") taskId = b.task_id;
            }
            reject(new ApiError(xhr.status, detail, code, taskId));
        };
        xhr.onerror = () => reject(new TypeError("failed to fetch"));
        xhr.onabort = () => reject(new TypeError("upload aborted"));
        xhr.send((init.body as XMLHttpRequestBodyInit | null) ?? null);
    });
}

function byokHeaders(byok?: ByokHeaders): Record<string, string> {
    const h: Record<string, string> = {};
    if (byok?.apiKey) h["X-Texlate-Key"] = byok.apiKey;
    if (byok?.baseUrl) h["X-Texlate-Base-URL"] = byok.baseUrl;
    if (byok?.model) h["X-Texlate-Model"] = byok.model;
    if (byok?.idempotencyKey) h["Idempotency-Key"] = byok.idempotencyKey;
    return h;
}

/**
 * Idempotency-Key 生命周期——「提交意图」粒度。
 *
 * server `_create_and_enqueue` 按 options.idempotency_key 去重（同 tenant 命中
 * 直返 202 {cache:"idempotent"}，不建行不入队；任务删除后 key 可复用）。
 * key 绑定提交内容指纹：请求未决（网络层失败，服务端可能已收单）期间同参
 * 重发/双击并发复用同 key；拿到任何 HTTP 响应（成功或错误）即结案，其后
 * 同参提交视为新意图、生成新 key。byok.idempotencyKey 显式传入时透传，
 * 不插手生命周期。
 */
const pendingCreate = new Map<string, string>();

function newKey(): string {
    const c = globalThis.crypto;
    if (c?.randomUUID) return c.randomUUID();
    // http://LAN 等非安全上下文无 randomUUID——getRandomValues 不受限
    if (c?.getRandomValues) {
        const b = c.getRandomValues(new Uint8Array(16));
        return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

function intentSettle(fp: string, key: string): void {
    // 守卫：同 fp 已被后续调用换新 key 时，旧在飞调用的结案不得误删新条目
    if (pendingCreate.get(fp) === key) pendingCreate.delete(fp);
}

/** 提交内容指纹——apiKey 是凭证不是意图，改 key 重试仍复用同一 idem key */
function createFp(kind: string, payload: unknown, byok?: ByokHeaders): string {
    const semantics = byok
        ? { baseUrl: byok.baseUrl, model: byok.model }
        : null;
    return JSON.stringify([kind, payload, semantics]);
}

function fileFp(file: File): string {
    return `${file.name}:${file.size}:${file.lastModified}`;
}

/**
 * create 三路（translate/upload/shareImport）共用：生成/复用/结案 Idempotency-Key。
 * onProgress 仅在 multipart 上传路传入（fetch 无上传进度 → xhrRequest）；
 * JSON 路恒走 fetch。
 */
async function createRequest<T>(
    fp: string,
    path: string,
    init: RequestInit,
    onProgress?: UploadProgress,
): Promise<T> {
    const headers = { ...(init.headers as Record<string, string> | undefined) };
    const send = (i: RequestInit) =>
        onProgress ? xhrRequest<T>(path, i, onProgress) : request<T>(path, i);
    if (headers["Idempotency-Key"]) return send(init);
    const key = pendingCreate.get(fp) ?? newKey();
    pendingCreate.set(fp, key);
    headers["Idempotency-Key"] = key;
    try {
        const res = await send({ ...init, headers });
        intentSettle(fp, key);
        return res;
    } catch (e) {
        // ApiError = 服务端已回话 → 结案；TypeError/AbortError = 未决 → 留 key 待重发
        if (e instanceof ApiError) intentSettle(fp, key);
        throw e;
    }
}

export const api = {
    health: () => request<Health>("/health"),
    providers: () =>
        request<Provider[] | { providers: Provider[] }>("/providers"),
    tasks: (status?: string) =>
        request<TaskSnapshot[] | { tasks: TaskSnapshot[] }>(
            `/tasks${status ? `?status=${encodeURIComponent(status)}` : ""}`,
        ),

    translate(arxivId: string, body?: TranslateOptions, byok?: ByokHeaders) {
        return createRequest<TranslateResponse>(
            createFp("translate", { arxivId, body: body ?? null }, byok),
            `/arxiv/${encodeURIComponent(arxivId)}/translate`,
            {
                method: "POST",
                headers: {
                    "content-type": "application/json",
                    ...byokHeaders(byok),
                },
                body: JSON.stringify(body ?? {}),
            },
        );
    },

    upload(
        file: File,
        fields?: {
            target_lang?: string;
            model?: string;
            main?: string;
            options?: object;
        },
        byok?: ByokHeaders,
        onProgress?: UploadProgress,
    ) {
        const fd = new FormData();
        fd.append("file", file);
        if (fields?.target_lang) fd.append("target_lang", fields.target_lang);
        if (fields?.model) fd.append("model", fields.model);
        if (fields?.main) fd.append("main", fields.main);
        if (fields?.options)
            fd.append("options", JSON.stringify(fields.options));
        return createRequest<TranslateResponse>(
            createFp(
                "upload",
                { file: fileFp(file), fields: fields ?? null },
                byok,
            ),
            "/upload",
            { method: "POST", headers: byokHeaders(byok), body: fd },
            onProgress,
        );
    },

    /** .share.zip 共享包导入（model/lang/arxiv_id 由包内 manifest 自描述） */
    shareImport(
        file: File,
        options?: object,
        byok?: ByokHeaders,
        onProgress?: UploadProgress,
    ) {
        const fd = new FormData();
        fd.append("file", file);
        if (options) fd.append("options", JSON.stringify(options));
        return createRequest<TranslateResponse>(
            createFp(
                "shareImport",
                { file: fileFp(file), options: options ?? null },
                byok,
            ),
            "/share/import",
            { method: "POST", headers: byokHeaders(byok), body: fd },
            onProgress,
        );
    },

    /** 终态任务事后打 .share.zip 入共享目录（§6；幂等——已打过直返同 share_key） */
    sharePack: (taskId: string) =>
        request<SharePackResponse>(`/task/${taskId}/share/pack`, {
            method: "POST",
        }),

    snapshot: (taskId: string) => request<TaskSnapshot>(`/task/${taskId}`),
    cancel: (taskId: string) =>
        request(`/task/${taskId}/cancel`, { method: "POST" }),
    deleteTask: (taskId: string) =>
        request<void>(`/task/${taskId}`, { method: "DELETE" }),
    // needs_auth 任务重试必须重带 X-Texlate-Key（BYOK 经 headers 透传）
    retry: (
        taskId: string,
        body?: { main?: string; options?: object },
        byok?: ByokHeaders,
    ) =>
        request<TranslateResponse>(`/task/${taskId}/retry`, {
            method: "POST",
            headers: {
                "content-type": "application/json",
                ...byokHeaders(byok),
            },
            body: JSON.stringify(body ?? {}),
        }),

    files: (taskId: string) => request<FileManifest>(`/files/${taskId}`),
    fileUrl(
        taskId: string,
        kind: FileKind,
        opts?: { download?: boolean; version?: string },
    ) {
        const q = new URLSearchParams();
        if (opts?.download) q.set("download", "1");
        if (opts?.version) q.set("version", opts.version);
        const qs = q.toString();
        return `${BASE}/files/${taskId}/${kind}${qs ? `?${qs}` : ""}`;
    },

    reader: (taskId: string) => request<ReaderInfo>(`/task/${taskId}/reader`),
    putPosition(taskId: string, state: ReadingState) {
        return request<void>(`/task/${taskId}/reader/position`, {
            method: "PUT",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(state),
        });
    },

    getSettings: () => request<Settings>("/settings"),
    putSettings: (s: Settings) =>
        request<Settings>("/settings", {
            method: "PUT",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(s),
        }),
    // body 可带 base_url/api_key/model 覆盖——测表单现值而非已存配置
    testSettings: (s?: Settings) =>
        request<{ ok: boolean; detail?: string; models?: string[] }>(
            "/settings/test",
            {
                method: "POST",
                headers: { "content-type": "application/json" },
                body: JSON.stringify(s ?? {}),
            },
        ),
};

export type TransportState = "live" | "reconnecting" | "closed";

export interface TaskEventHandlers {
    snapshot?: (s: TaskSnapshot) => void;
    stage?: (e: StageEvent) => void;
    chunk?: (e: ChunkEvent) => void;
    log?: (e: LogEvent) => void;
    warning?: (e: WarningEvent) => void;
    error?: (e: TaskErrorEvent) => void;
    done?: (e: DoneEvent) => void;
    /** 传输层状态：open→live / error→reconnecting（closed 为彻底断开） */
    transport?: (state: TransportState) => void;
}

export interface TaskChannel {
    close(): void;
    readonly closed: boolean;
}

const TERMINAL: ReadonlySet<TaskStatus> = new Set([
    "done",
    "partial",
    "fault",
    "cancelled",
    "interrupted",
    "needs_auth",
]);

export function isTerminal(status: TaskStatus): boolean {
    return TERMINAL.has(status);
}

/**
 * translate/upload 202 → 落地 hash 路由。reader_url 可能缺席（doc 类任务
 * 无 dual.json）——此时回 task_id 拼详情面：#/reader/:id 即任务详情页，
 * 在途出进度、终态无 reader 自动落产物下载面板，不 404 不白屏。
 */
export function landingHash(
    res: Pick<TranslateResponse, "task_id" | "reader_url">,
): string {
    const m = res.reader_url?.match(/\/task\/([A-Za-z0-9_-]+)\/reader/);
    return `#/reader/${m?.[1] ?? res.task_id}`;
}

/**
 * 每任务已见 seq 水位线（module 级，跨 channel 重建存活）。
 *
 * retry/重开订阅时新 EventSource 不带 Last-Event-ID，服务端
 * ``events_since(task_id, 0)`` 全量重放落盘事件（retry 不清
 * task_events）——含上一轮 done 帧，照单全收会把新 channel 当场关掉、
 * 本轮真实事件无人监听（live 假死）。水位线丢弃 ``seq<=wm`` 的非
 * snapshot 帧；snapshot 帧 seq=0 恒放行（每连现场合成、不落盘）。
 * EventSource 自动重连带 Last-Event-ID 的服务端重放也被同一去重罩住。
 * 任务删除时由 {@link forgetTaskEvents} 清——retry/unwatch 均不清。
 */
const seqWatermark = new Map<string, number>();

/** 任务删除（remove/服务端 deleted 帧）才清其 seq 水位线 */
export function forgetTaskEvents(taskId: string): void {
    seqWatermark.delete(taskId);
}

/**
 * 订阅任务 SSE。浏览器 EventSource 自带断线重连 + Last-Event-ID 重放；
 * 终态（done 事件或 snapshot 已是终态）自动关闭，不再重连。
 */
export function openTaskEvents(
    taskId: string,
    h: TaskEventHandlers,
): TaskChannel {
    const es = new EventSource(`${BASE}/task/${taskId}`);
    let closed = false;

    const on = <T>(type: string, fn: (data: T, seq: number) => void) =>
        es.addEventListener(type, (ev) => {
            const msg = ev as MessageEvent;
            const seq = Number(msg.lastEventId) || 0;
            const wm = seqWatermark.get(taskId) ?? 0;
            if (seq !== 0 && seq <= wm) return; // 重放/重连重复帧——丢弃
            if (seq > wm) seqWatermark.set(taskId, seq); // 坏帧也推进，防毒化回放
            try {
                fn(JSON.parse(msg.data) as T, seq);
            } catch {
                /* 忽略坏帧 */
            }
        });

    on("snapshot", (s: TaskSnapshot) => {
        h.snapshot?.(s);
        if (isTerminal(s.status)) close();
    });
    on("stage", (e: StageEvent) => h.stage?.(e));
    on("chunk", (e: ChunkEvent) => h.chunk?.(e));
    on("log", (e: LogEvent) => h.log?.(e));
    on("warning", (e: WarningEvent) => h.warning?.(e));
    on("error", (e: TaskErrorEvent) => h.error?.(e));
    on("done", (e: DoneEvent) => {
        h.done?.(e);
        close();
    });
    es.onopen = () => h.transport?.("live");
    es.onerror = (ev) => {
        // 具名 `event: error` 帧以 type=error 的 MessageEvent 派发，会连带
        // 触发 onerror——带 data 的是业务错误帧（已走 on("error")），真·传输
        // 层失败是裸 Event
        if ("data" in ev || ev instanceof MessageEvent) return;
        if (es.readyState === EventSource.CLOSED) close();
        else h.transport?.("reconnecting");
    };

    function close() {
        if (!closed) {
            closed = true;
            es.close();
            h.transport?.("closed");
        }
    }

    return {
        close,
        get closed() {
            return closed;
        },
    };
}
