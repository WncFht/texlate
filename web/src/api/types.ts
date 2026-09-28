// 共享类型 —— §2 端点体/事件帧的类型面 + ApiError + 终态判定。
// client.ts 门面对外再导出；本文件不含运行时请求逻辑。

/** 任务状态词表（唯一事实源）——TaskStatus 联合由此派生；
    i18n status 段与测试词表对本表迭代而非各维护一份手抄数组 */
export const TASK_STATUSES = [
    "queued",
    "fetching",
    "parsing",
    "translating",
    "compiling",
    "done",
    "partial",
    "fault",
    "cancelled",
    "interrupted",
    "needs_auth",
] as const;

export type TaskStatus = (typeof TASK_STATUSES)[number];

export type TaskStage = "fetching" | "parsing" | "translating" | "compiling";

/** 已知任务类型词表——服务端可发词表外 kind（新通道先行），
    TaskKind 保留 `| string` 尾 */
export const TASK_KINDS = [
    "arxiv",
    "arxiv_html",
    "upload_tex",
    "upload_pdf",
    "docx",
    "epub",
    "share",
] as const;

export type TaskKind = (typeof TASK_KINDS)[number] | string;

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
    /** 单任务 snapshot 缺席；/tasks 列表行发显式 null（DB 列可空） */
    stage?: TaskStage | null;
    message?: string;
    title?: string;
    /** 同 stage：列表行 null（上传类无 arxiv 源），单任务 snapshot 缺席 */
    arxiv_id?: string | null;
    /** /tasks 列表行恒发（DB NOT NULL DEFAULT ''）；单任务 snapshot 不携带 */
    source_name?: string;
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
    /** 排队位次（1 基）——status=queued 时由服务端按入队序给出，其余状态缺席 */
    queue_position?: number;
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

export interface FixloopRound {
    round: number;
    n_errors?: number;
    category?: string;
    sec?: number;
    died?: boolean;
}

/**
 * fixloop SSE 帧：
 * - ``phase="round"``：循环进行中的逐轮增量帧（round 携带本轮结果）
 * - ``phase="done"``：收尾帧，``cell`` 为完整修复单元（rounds/actions/verdict…）
 * - 无 ``phase``：旧版服务端落的裸 cell（只在结束时发一帧）——按 done 处理，
 *   rounds/verdict 等键平铺在顶层
 */
export interface FixloopEvent {
    phase?: "round" | "done";
    round?: FixloopRound;
    cell?: {
        rounds?: FixloopRound[];
        verdict?: string;
        floor_restored?: boolean;
        actions?: unknown[];
        [k: string]: unknown;
    };
    rounds?: FixloopRound[];
    verdict?: string;
    floor_restored?: boolean;
    [k: string]: unknown;
}

/**
 * L2 重译 SSE 帧：``phase`` 缺省视为 done（旧帧只发一次结果负载）。
 * done 帧平铺统计键（enabled/errors/retranslated/fallback）。
 */
export interface L2Event {
    phase?: "start" | "progress" | "done";
    message?: string;
    enabled?: boolean;
    errors?: number;
    retranslated?: number;
    fallback?: number;
    [k: string]: unknown;
}

export interface WarningEvent {
    code: string;
    message: string;
}

export interface TaskErrorEvent {
    code: ErrorCode;
    message: string;
    /** error 帧恒带 stage 键：row.stage 缺席时服务端发显式 null（emit.py/runner.py 两处同） */
    stage?: TaskStage | null;
    retryable: boolean;
    /** wire 恒发 null（emit.py error 帧 chunk_seq=None 占位）——声明纠错防按非空假设消费 */
    chunk_seq?: number | null;
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
        /** 完成后打包 .share.zip 社区缓存包（2026-09-16-shared-cache.md §6 opt-in） */
        share_pack?: boolean;
        /** preamble 前置内容翻译开关（摘要/标题/作者各自独立） */
        front_matter?: {
            abstract?: boolean;
            title?: boolean;
            author?: boolean;
        };
        /** 服务端白名单外键原样透传（try-html 克隆任务用） */
        [key: string]: unknown;
    };
}

export interface ByokHeaders {
    apiKey?: string;
    baseUrl?: string;
    model?: string;
    dialect?: string;
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

/** POST /tasks/slim 200 体——瘦身只删未登记字节，产物/记录全留 */
export interface SlimReport {
    /** 实际有字节释放的任务数 */
    slimmed: number;
    freed_bytes: number;
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
    | "src.html"
    | "share.zip";

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
    share_zip: "share.zip",
};

export interface FileEntry {
    /** DB 列可空——缺失产物登记记 NULL（worker/emit.py _register 同旧口径） */
    bytes: number | null;
    sha256: string | null;
    created_at: number;
    /** 服务端直接给的下载路径（/api/files/{id}/{url_kind}） */
    url: string;
}

export interface FileManifest {
    artifacts: Record<string, FileEntry>;
}

// ---------- reader 线形（§5.3/§5.4 位置模型） ----------
// Pos/Alignment 等是服务端序列化的载荷形状（reader info / dual.json /
// position 持久化），归 API 契约层；reader/logic/alignment.ts 的
// createPositionMapper/PosMap 是消费这些形状的本地映射逻辑。

export interface Pos {
    page: number;
    fraction: number;
    /** 页宽分位列位（seqpos 锚行左缘 / posAtPoint 点击 x）——双栏
        阅读序键 (page,col,fraction) 的 col 源：x>=0.45 → 右栏；
        缺席（旧数据/滚动位）→ 0 */
    x?: number;
    /** 锚行右缘页宽分位（seqpos v11+）——宽行（TOC/通栏标题/多栏合并
        行）点击 x 落右半时供同行 snap 判栏，缺席 → 无幅面信息 */
    x1?: number;
    /** 焦点行距视口顶部的比例（跨页跳转后锚点停在屏幕同一高度） */
    viewport?: number;
}

export interface RegionCoord {
    page: number;
    start: number;
    end: number;
}

export interface AlignmentPair {
    id?: string;
    original: Pos;
    translated: Pos;
}

export interface AlignmentRegion {
    id?: string;
    original: RegionCoord;
    translated: RegionCoord;
}

export interface Alignment {
    kind: "landmarks" | "pages" | string;
    heights?: { original?: number[]; translated?: number[] };
    pairs?: AlignmentPair[];
    regions?: AlignmentRegion[];
}

export interface ReaderDoc {
    version: string;
    pages: number;
    url: string;
}

// Kind 后缀避让同名组件 ReaderView（reader/ReaderView.tsx）——类型/组件撞名
// 在 import 列表与类型位置并列时读性差
export type ReaderViewKind = "pdf" | "html" | "dom";

export interface ReadingState {
    positions?: Partial<Record<"original" | "translated", Pos>>;
    active?: "original" | "translated";
    /** guide 不出现在持久化值里（guide 态 positions 恒空、saveNow 不写），
        但 saveNow 组装本类型时 mode() 取值域含它——类型面同步放宽 */
    mode?: "original" | "translated" | "split" | "guide";
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
    view?: ReaderViewKind;
    /** 哪侧缺哪侧不写：md_zip 路径必缺 translated，en_pdf 缺则 original 缺 */
    documents: {
        original?: ReaderDoc;
        translated?: ReaderDoc;
    };
    alignment?: Alignment;
    /** seq 级双侧 Pos（服务端 seqpos.json 懒算产物，{seq:{o,t}}）——
        顶层独立键不进 alignment（dual()?.alignment 优先级会盖掉注入值，
        前端经 pdfseqpos.ts 自行消费）；不可算任务缺席/{} */
    seqpos?: Record<string, { o?: Pos; t?: Pos }>;
    reading?: ReadingState | null;
}

export interface DualChunk {
    seq: number;
    /** 服务端 chunk_id 投影（data-chunk 锚值如 S1.p4/b5）——dom 视图
        data-chunk key→seq 映射的数据面；旧产物缺席 */
    chunk_id?: string;
    src_file?: string;
    en?: string;
    zh?: string;
    kind?: string;
    /** 段状态（ok/fallback_orig/failed…）——新版 dual.json 起携带，旧文件缺席时按 zh 是否为空推断 */
    status?: string;
    /** ``[[TYPE_n]]`` → 原文 LaTeX 体（eprint 链 dual.json 起携带）——
     *  阅读面反查掩码渲真公式/引用；缺席（旧产物/html 链/live 轮询行）
     *  时 token 降级成样式 chip */
    ph?: Record<string, string>;
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
    /** 服务端 chunk_id 投影（同 DualChunk.chunk_id——缺席=旧版服务端） */
    chunk_id?: string;
    kind: string;
    status: string;
    en: string;
    zh: string;
    /** DB 行暂不携带（ph 只进 dual.json）——类型留位，服务端补列即通 */
    ph?: Record<string, string>;
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
    /** LLM 网关方言：auto（按 host 推导）|openai|anthropic|responses */
    dialect?: string;
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

// ---------- discover：alphaXiv 公共面只读代理（机会型增强，字段以服务端实测为准） ----------

/** feed/搜索共用的卡片形状（服务端透传 alphaxiv 原字段） */
export interface DiscoverPaper {
    id?: string;
    paper_group_id?: string;
    /** arXiv id —— 翻译入口与 alphaxiv 链接的锚 */
    universal_paper_id?: string;
    canonical_id?: string;
    title?: string;
    abstract?: string;
    /** feed 卡一句话导读（en） */
    feed_description?: string;
    /** 首页缩略图（thumbnails.assets.alphaxiv.org） */
    image_url?: string;
    topics?: string[];
    github_stars?: number;
    github_url?: string;
    publication_date?: string;
    authors?: unknown;
    organization_info?: unknown;
    paper_summary?: { summary?: string; feedDescription?: string } & Record<
        string,
        unknown
    >;
    metrics?: {
        visits_count?: { all?: number; last_7_days?: number };
        total_votes?: number;
        public_total_votes?: number;
    } & Record<string, unknown>;
}

export interface DiscoverFeed {
    papers?: DiscoverPaper[];
    page?: number;
}

/** /api/discover/search 行——alphaxiv 快搜建议 */
export interface DiscoverHit {
    link?: string;
    paperId?: string;
    title?: string;
    snippet?: string;
}

/** overview.summary 六件套卡（实测字段；feedDescription 可为 null） */
export interface AxSummary {
    summary?: string;
    feedDescription?: string | null;
    originalProblem?: string[];
    solution?: string[];
    keyInsights?: string[];
    results?: string[];
    [k: string]: unknown;
}

/** overview.citations 行——带 justification 的相关论文（alphaxiv 图内已解析） */
export interface AxCitation {
    title?: string;
    /** 未翻译字段（en 原样） */
    fullCitation?: string;
    justification?: string;
    alphaxivLink?: string;
    [k: string]: unknown;
}

/**
 * /api/discover/overview —— 机会型 AI 导读：未收录/未生成恒
 * ``{available:false}``（非错误）；命中时 zh 优先 en 兜底。
 */
export interface AxOverview {
    available: boolean;
    lang?: string;
    arxiv_id?: string;
    alphaxiv_url?: string;
    title?: string | null;
    abstract?: string | null;
    summary?: AxSummary | null;
    /** 完整导读 blog markdown */
    overview?: string | null;
    citations?: AxCitation[] | null;
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

/** 异常 → 展示字符串：Error 取 message，其余 String() */
export const errText = (e: unknown): string =>
    e instanceof Error ? e.message : String(e);

/** ApiError 取服务端 detail，其余同 errText——UI 报错统一入口 */
export const apiErrText = (e: unknown): string =>
    e instanceof ApiError ? e.detail : errText(e);

/** 上传进度回调（loaded/total 字节——lengthComputable 才发） */
export type UploadProgress = (loaded: number, total: number) => void;

// ---------- refs：文献条目远端元数据代理（引用悬浮卡 L2 增强） ----------

export interface RefLookupItem {
    key: string;
    arxivId?: string;
    doi?: string;
}

/** 服务端 refs 代理回包的单条元数据——字段缺位即无（前端缺位隐藏） */
export interface RefMeta {
    title?: string;
    authors?: string[];
    year?: number;
    venue?: string;
    citationCount?: number;
    tldr?: string;
    arxivId?: string;
    doi?: string;
}

export interface RefsLookupResponse {
    /** bibkey → 元数据；解析不到的 key 缺席 */
    meta: Record<string, RefMeta>;
    /** true = 上游部分/全部失败——已尽力返回，前端不报错 */
    degraded?: boolean;
}

// ---------- kept refs：文献收藏（CiteCard ☆ → refs.bib 导出 keys 子集） ----------

/** kept_refs 单条快照——payload 自含即真相：text/meta 是收藏时刻看到的
 *  版本，key（bibkey 或 dom 链 bib.bibN 序数）漂移后导出仍走快照。
 *  服务端 payload ≤64KB/条。 */
export interface KeptRef {
    label?: string;
    text?: string;
    arxivId?: string;
    doi?: string;
    /** 收藏时刻的 L2 元数据快照（meta 缺位/迟到也可能为空） */
    meta?: RefMeta;
}

/** GET /task/{id}/refs/kept 回包 */
export interface KeptRefsResponse {
    kept: Record<string, KeptRef>;
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

/** 终态中的失败桶（终态 − done）——计数/过滤/清理/重试共用这一份判定；
    可重试集 = isFailed − needs_auth（缺 key 走设置而非重试） */
export function isFailed(status: TaskStatus): boolean {
    return isTerminal(status) && status !== "done";
}
