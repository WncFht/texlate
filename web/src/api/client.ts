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
export type TaskKind = "arxiv" | "upload_tex" | "upload_pdf";

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
}

export interface DoneEvent {
    status: TaskStatus;
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
    reader_url: string;
}

export type FileKind =
    | "en.pdf"
    | "zh.pdf"
    | "dual.pdf"
    | "dual.json"
    | "src.tar"
    | "zh-src.zip"
    | "compile.log"
    | "md";

export interface FileEntry {
    bytes: number;
    sha256: string;
    created_at: number;
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
}

export interface ReaderInfo {
    view?: ReaderView;
    documents: {
        original: ReaderDoc;
        translated: ReaderDoc;
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
    documents: {
        original: { version: string; pages: number };
        translated: { version: string; pages: number };
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
        try {
            const body = await res.json();
            if (typeof body?.detail === "string") detail = body.detail;
            if (typeof body?.code === "string") code = body.code;
        } catch {
            /* 非 JSON 错误体 */
        }
        throw new ApiError(res.status, detail, code);
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

    snapshot: (taskId: string) => request<TaskSnapshot>(`/task/${taskId}`),
    cancel: (taskId: string) => request(`/task/${taskId}/cancel`, { method: "POST" }),
    retry: (taskId: string, body?: { main?: string; options?: object }) =>
        request<TranslateResponse>(`/task/${taskId}/retry`, {
            method: "POST",
            headers: { "content-type": "application/json" },
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
    testSettings: () => request<{ ok: boolean; detail?: string }>("/settings/test", { method: "POST" }),
};

export interface TaskEventHandlers {
    snapshot?: (s: TaskSnapshot) => void;
    stage?: (e: StageEvent) => void;
    chunk?: (e: ChunkEvent) => void;
    log?: (e: LogEvent) => void;
    warning?: (e: WarningEvent) => void;
    error?: (e: TaskErrorEvent) => void;
    done?: (e: DoneEvent) => void;
    /** 连接层错误（EventSource 自动重连中也会触发） */
    transport?: (ev: Event) => void;
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
    es.onerror = (ev) => {
        if (es.readyState === EventSource.CLOSED) close();
        h.transport?.(ev);
    };

    function close() {
        if (!closed) {
            closed = true;
            es.close();
        }
    }

    return {
        close,
        get closed() {
            return closed;
        },
    };
}
