// 共享类型 —— §2 端点体/事件帧的类型面 + ApiError + 终态判定。
// client.ts 门面对外再导出；本文件不含运行时请求逻辑。

import type { Alignment, Pos } from "../reader/alignment";

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
    /** 任务创建时的用户入参 options（服务端已摘内部审计键）——try-html 透传源 */
    options?: Record<string, unknown>;
    /** 生效术语表路径（config_json.glossary） */
    glossary?: string;
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
        /** 取源通道：eprint=LaTeX 主链（默认）| html=arXiv HTML 降级链 */
        source?: "eprint" | "html";
        /** 完成后打包 .share.zip 社区缓存包（shared-cache.md §6 opt-in） */
        share_pack?: boolean;
        /** 服务端白名单外键原样透传（try-html 克隆任务用） */
        [key: string]: unknown;
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

/** PUT /task/{id}/reader/position 的载荷——「要留存」的阅读态 */
export type ReaderKeep = ReadingState;

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

/** GET /task/{id}/chunks 分页行（流式预览/延迟载入用） */
export interface TaskChunkRow {
    seq: number;
    kind: string;
    status: string;
    en: string;
    zh: string;
}

export interface TaskChunksPage {
    chunks: TaskChunkRow[];
    total: number;
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
    /** PUT 响应回执：服务端丢弃的未识别字段名（be 侧白名单外静默丢） */
    ignored?: string[];
    [k: string]: unknown;
}

export interface Provider {
    id: string;
    name?: string;
    base_url?: string;
    model?: string;
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
