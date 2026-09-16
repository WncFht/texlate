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
export type TaskKind = "arxiv" | "upload_tex" | "upload_pdf" | "docx" | "epub" | string;

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
    /** task_usage 行（有 LLM 调用记录才带） */
    usage?: {
        model?: string;
        calls?: number;
        prompt_tokens?: number;
        completion_tokens?: number;
        latency_s?: number;
    };
}

export interface StageEvent {
    stage: TaskStage;
    progress: number;
    message: string;
    at: number;
}

export type ChunkStatus = "ok" | "fallback_orig" | "failed" | "pending" | string;

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
    | "zh.epub";

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

export type ReaderView = "pdf" | "html";

export interface ReadingState {
    positions?: Partial<Record<"original" | "translated", Pos>>;
    active?: "original" | "translated";
    mode?: "original" | "translated" | "split";
    zoom?: string;
    sync?: boolean;
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

function byokHeaders(byok?: ByokHeaders): Record<string, string> {
    const h: Record<string, string> = {};
    if (byok?.apiKey) h["X-Texlate-Key"] = byok.apiKey;
    if (byok?.baseUrl) h["X-Texlate-Base-URL"] = byok.baseUrl;
    if (byok?.model) h["X-Texlate-Model"] = byok.model;
    if (byok?.idempotencyKey) h["Idempotency-Key"] = byok.idempotencyKey;
    return h;
}

export const api = {
    health: () => request<Health>("/health"),
    providers: () => request<Provider[] | { providers: Provider[] }>("/providers"),
    tasks: (status?: string) =>
        request<TaskSnapshot[] | { tasks: TaskSnapshot[] }>(
            `/tasks${status ? `?status=${encodeURIComponent(status)}` : ""}`,
        ),

    translate(arxivId: string, body?: TranslateOptions, byok?: ByokHeaders) {
        return request<TranslateResponse>(`/arxiv/${encodeURIComponent(arxivId)}/translate`, {
            method: "POST",
            headers: { "content-type": "application/json", ...byokHeaders(byok) },
            body: JSON.stringify(body ?? {}),
        });
    },

    upload(file: File, fields?: { target_lang?: string; model?: string; main?: string; options?: object }) {
        const fd = new FormData();
        fd.append("file", file);
        if (fields?.target_lang) fd.append("target_lang", fields.target_lang);
        if (fields?.model) fd.append("model", fields.model);
        if (fields?.main) fd.append("main", fields.main);
        if (fields?.options) fd.append("options", JSON.stringify(fields.options));
        return request<TranslateResponse>("/upload", { method: "POST", body: fd });
    },

    /** .share.zip 共享包导入（model/lang/arxiv_id 由包内 manifest 自描述） */
    shareImport(file: File, options?: object) {
        const fd = new FormData();
        fd.append("file", file);
        if (options) fd.append("options", JSON.stringify(options));
        return request<TranslateResponse>("/share/import", { method: "POST", body: fd });
    },

    snapshot: (taskId: string) => request<TaskSnapshot>(`/task/${taskId}`),
    cancel: (taskId: string) => request(`/task/${taskId}/cancel`, { method: "POST" }),
    deleteTask: (taskId: string) =>
        request<void>(`/task/${taskId}`, { method: "DELETE" }),
    // needs_auth 任务重试必须重带 X-Texlate-Key（BYOK 经 headers 透传）
    retry: (taskId: string, body?: { main?: string; options?: object }, byok?: ByokHeaders) =>
        request<TranslateResponse>(`/task/${taskId}/retry`, {
            method: "POST",
            headers: { "content-type": "application/json", ...byokHeaders(byok) },
            body: JSON.stringify(body ?? {}),
        }),

    files: (taskId: string) => request<FileManifest>(`/files/${taskId}`),
    fileUrl(taskId: string, kind: FileKind, opts?: { download?: boolean; version?: string }) {
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
        request<{ ok: boolean; detail?: string; models?: string[] }>("/settings/test", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(s ?? {}),
        }),
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
export function landingHash(res: Pick<TranslateResponse, "task_id" | "reader_url">): string {
    const m = res.reader_url?.match(/\/task\/([A-Za-z0-9_-]+)\/reader/);
    return `#/reader/${m?.[1] ?? res.task_id}`;
}

/**
 * 订阅任务 SSE。浏览器 EventSource 自带断线重连 + Last-Event-ID 重放；
 * 终态（done 事件或 snapshot 已是终态）自动关闭，不再重连。
 */
export function openTaskEvents(taskId: string, h: TaskEventHandlers): TaskChannel {
    const es = new EventSource(`${BASE}/task/${taskId}`);
    let closed = false;

    const on = <T>(type: string, fn: (data: T, seq: number) => void) =>
        es.addEventListener(type, (ev) => {
            try {
                fn(JSON.parse((ev as MessageEvent).data) as T, Number((ev as MessageEvent).lastEventId) || 0);
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
    es.onerror = () => {
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
