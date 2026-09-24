// REST 面 —— §2 JSON/上传端点。错误一律 {detail, code?} → ApiError。
// client.ts 门面对外再导出。

import { createFp, fileFp, intentKey, intentSettle } from "./idem";
import {
    ApiError,
    type AxOverview,
    type ByokHeaders,
    type DiscoverFeed,
    type DiscoverHit,
    type FileKind,
    type FileManifest,
    type Health,
    type KeptRef,
    type KeptRefsResponse,
    type Provider,
    type ReaderInfo,
    type ReaderKeep,
    type RefLookupItem,
    type RefsLookupResponse,
    type Settings,
    type SharePackResponse,
    type SlimReport,
    type TaskChunksPage,
    type TaskSnapshot,
    type TranslateOptions,
    type TranslateResponse,
    type UploadProgress,
} from "./types";

const BASE = "/api";

/** 默认请求超时——health 挂起→首页恒「检测中」之类的裸挂收敛到 15s。
 *  request() 内留有 init?.signal 覆盖臂，但 api.* 公开面无任一方法透传
 *  init——现状全量调用都吃此默认（上传不走此路——xhrRequest 用自带
 *  UPLOAD_TIMEOUT_MS，80MB 慢链要远比 15s 宽）。 */
export const REQUEST_TIMEOUT_MS = 15_000;

/** /reader 首开的宽限——seqpos 缓存未命中时服务端懒算要重解析整本
 *  pypdf CMap（实测大稿 ~19s），默认 15s 必然 abort 成 "signal timed out"。 */
const READER_TIMEOUT_MS = 60_000;

/** 上传 xhr 超时——10min：80MB 上限在 ~150KB/s 慢链约 9min 传完 */
const UPLOAD_TIMEOUT_MS = 10 * 60_000;

/**
 * 错误体 → ApiError——request/xhrRequest 同一契约（{detail,code?,task_id?}，
 * 非对象体全缺席）。statusText 形参即 detail 兜底值，调用方各自定（fetch 直用，
 * xhr 空串时降 HTTP 状态码）。
 */
function toApiError(
    status: number,
    statusText: string,
    body: unknown,
): ApiError {
    let detail = statusText;
    let code: string | undefined;
    let taskId: string | undefined;
    if (body && typeof body === "object") {
        const b = body as Record<string, unknown>;
        if (typeof b.detail === "string") detail = b.detail;
        if (typeof b.code === "string") code = b.code;
        if (typeof b.task_id === "string") taskId = b.task_id;
    }
    return new ApiError(status, detail, code, taskId);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const res = await fetch(`${BASE}${path}`, {
        ...init,
        signal:
            init?.signal ?? AbortSignal.timeout?.(REQUEST_TIMEOUT_MS) ?? null,
    });
    if (!res.ok) {
        let body: unknown;
        try {
            body = await res.json();
        } catch {
            /* 非 JSON 错误体 */
        }
        throw toApiError(res.status, res.statusText, body);
    }
    if (res.status === 204) return undefined as T;
    const ct = res.headers.get("content-type") ?? "";
    return (ct.includes("json") ? res.json() : res.text()) as Promise<T>;
}

/**
 * XHR 版 request——fetch 无上传进度事件，带 onProgress 的 multipart
 * 提交走此路。响应解析口径与 request 一致（JSON 错误体 → ApiError，
 * 网络层失败/超时 → TypeError：createRequest 按「未决」留 idem key）。
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
            reject(
                toApiError(
                    xhr.status,
                    xhr.statusText || `HTTP ${xhr.status}`,
                    body,
                ),
            );
        };
        xhr.onerror = () => reject(new TypeError("failed to fetch"));
        xhr.onabort = () => reject(new TypeError("upload aborted"));
        // 上传裸挂（连接滞留）此前无超时——用户只能干等。TypeError 与
        // onerror 同类：createRequest 按「未决」留 idem key，重试复用不双建
        xhr.timeout = UPLOAD_TIMEOUT_MS;
        xhr.ontimeout = () => reject(new TypeError("upload timeout"));
        // init.signal 接 abort——上传路此前丢 signal，取消语义传不进 XHR
        const sig = init.signal;
        if (sig) {
            if (sig.aborted) {
                reject(new TypeError("upload aborted"));
                return;
            }
            sig.addEventListener("abort", () => xhr.abort(), { once: true });
        }
        xhr.send((init.body as XMLHttpRequestBodyInit | null) ?? null);
    });
}

function byokHeaders(byok?: ByokHeaders): Record<string, string> {
    const h: Record<string, string> = {};
    if (byok?.apiKey) h["X-Texlate-Key"] = byok.apiKey;
    if (byok?.baseUrl) h["X-Texlate-Base-URL"] = byok.baseUrl;
    if (byok?.model) h["X-Texlate-Model"] = byok.model;
    if (byok?.dialect) h["X-Texlate-Dialect"] = byok.dialect;
    if (byok?.idempotencyKey) h["Idempotency-Key"] = byok.idempotencyKey;
    return h;
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
    const key = intentKey(fp);
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
    /**
     * 任务列表全量拉取——服务端 ``limit`` 默认 100（上限 1000），裸调
     * 会静默截断长列表；按 ``{tasks,total}`` 信封 offset 翻页收全。
     */
    tasks: async (status?: string): Promise<TaskSnapshot[]> => {
        const PAGE = 1000;
        // 防御页数上限：无 total 且对端无视 offset（恒回满页）时防无限翻页
        const MAX_PAGES = 100;
        const out: TaskSnapshot[] = [];
        for (let i = 0; i < MAX_PAGES; i++) {
            const q = new URLSearchParams({
                limit: String(PAGE),
                offset: String(i * PAGE),
            });
            if (status) q.set("status", status);
            const res = await request<
                TaskSnapshot[] | { tasks: TaskSnapshot[]; total?: number }
            >(`/tasks?${q}`);
            // 裸数组无 {tasks,total} 分页契约——按全量一页收齐即停；
            // 继续 offset 对无视参数的对端只会重复累积或空转
            if (Array.isArray(res)) {
                out.push(...res);
                break;
            }
            const page = res.tasks ?? [];
            out.push(...page);
            if (
                page.length < PAGE ||
                (res.total != null && out.length >= res.total)
            )
                break;
        }
        return out;
    },

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
    /** 段落正文分页（进度页流式预览用；offset/limit 服务端夹取） */
    taskChunks(taskId: string, offset = 0, limit?: number) {
        const q = new URLSearchParams();
        if (offset > 0) q.set("offset", String(offset));
        if (limit != null) q.set("limit", String(limit));
        const qs = q.toString();
        return request<TaskChunksPage>(
            `/task/${taskId}/chunks${qs ? `?${qs}` : ""}`,
        );
    },
    /** 按 seq 集定点取块——增量轮询只拉脏 seq（chunkPoll；≤CHUNKS_PAGE_MAX 个） */
    taskChunksSeqs(taskId: string, seqs: number[]) {
        const q = new URLSearchParams({ seqs: seqs.join(",") });
        return request<TaskChunksPage>(`/task/${taskId}/chunks?${q}`);
    },
    cancel: (taskId: string) =>
        request(`/task/${taskId}/cancel`, { method: "POST" }),
    deleteTask: (taskId: string) =>
        request<void>(`/task/${taskId}`, { method: "DELETE" }),
    /** 批量瘦身：终态任务 workdir 清未登记字节——产物/记录全留，非破坏；
     *  dry=true 只算不删，给清理 UI 出「约可释放 X」预估 */
    slimTasks: (opts?: { dry?: boolean }) =>
        request<SlimReport>(`/tasks/slim${opts?.dry ? "?dry=1" : ""}`, {
            method: "POST",
        }),
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
    /** 单段重译（M8 用户侧入口）——202 入队 worker 重译 job，完成后前端轮询 chunks 刷新 */
    retranslateChunk: (taskId: string, seq: number, byok?: ByokHeaders) =>
        request<{ task_id: string; seq: number; status: string }>(
            `/task/${taskId}/chunk/${seq}/retranslate`,
            {
                method: "POST",
                headers: byokHeaders(byok),
            },
        ),

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

    reader: (taskId: string) =>
        request<ReaderInfo>(`/task/${taskId}/reader`, {
            signal: AbortSignal.timeout?.(READER_TIMEOUT_MS) ?? null,
        }),
    /**
     * keepalive=true 走 fetch keepalive——pagehide 冲刷期请求可在页面
     * 卸载后送达（载荷上限 64KB，阅读态远低）。M5 关 tab 兜底。
     */
    putPosition(
        taskId: string,
        keep: ReaderKeep,
        opts?: { keepalive?: boolean },
    ) {
        return request<void>(`/task/${taskId}/reader/position`, {
            method: "PUT",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(keep),
            keepalive: opts?.keepalive,
        });
    },

    // ---------- discover：alphaXiv 代理面（上游挂 → 502，调用方整块隐藏） ----------
    discoverFeed(opts?: {
        sort?: string;
        interval?: string;
        page?: number;
        pageSize?: number;
    }) {
        const q = new URLSearchParams();
        if (opts?.sort) q.set("sort", opts.sort);
        if (opts?.interval) q.set("interval", opts.interval);
        if (opts?.page != null) q.set("page", String(opts.page));
        if (opts?.pageSize != null) q.set("page_size", String(opts.pageSize));
        const qs = q.toString();
        return request<DiscoverFeed>(`/discover/feed${qs ? `?${qs}` : ""}`);
    },
    discoverSearch: (q: string) =>
        request<DiscoverHit[]>(`/discover/search?q=${encodeURIComponent(q)}`),
    discoverOverview: (arxivId: string) =>
        request<AxOverview>(
            `/discover/overview/${encodeURIComponent(arxivId)}`,
        ),
    /** OG 卡 PNG 直链（img src 用，不经 request——二进制非 JSON） */
    discoverOgUrl: (arxivId: string) =>
        `${BASE}/discover/og/${encodeURIComponent(arxivId)}`,

    // ---------- refs：引用悬浮卡 L2 远端增强（机会型；失败静默降级） ----------
    refsLookup: (refs: RefLookupItem[]) =>
        request<RefsLookupResponse>("/refs/lookup", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify({ refs }),
        }),

    // ---------- kept refs：文献收藏（M4 Phase B；refs.bib 的 keys 子集源） ----------
    /** 任务 kept 全集 {key: payload}——reader mount 时一次取回 */
    refsKept: (taskId: string) =>
        request<KeptRefsResponse>(`/task/${taskId}/refs/kept`),
    /**
     * kept 写——payload=null 即 unkeep。契约两形并行期兼容：先试
     * keyed path（PUT/DELETE /refs/kept/{key}），404/405 回退设计
     * 文档的 collection PUT（{key,payload}/{key,payload:null}）。
     */
    async refsKeepWrite(
        taskId: string,
        key: string,
        payload: KeptRef | null,
    ): Promise<void> {
        const keyed = `/task/${taskId}/refs/kept/${encodeURIComponent(key)}`;
        const json = (b: unknown): RequestInit => ({
            method: "PUT",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(b),
        });
        try {
            return await request<void>(
                keyed,
                payload === null
                    ? { method: "DELETE" }
                    : json({ key, payload }),
            );
        } catch (e) {
            if (
                !(e instanceof ApiError) ||
                (e.status !== 404 && e.status !== 405)
            )
                throw e;
        }
        return request<void>(
            `/task/${taskId}/refs/kept`,
            json({ key, payload }),
        );
    },
    /**
     * refs.bib 导出直链——keys 缺省=kept 全集（无 kept 则全可解 key），
     * all=1 恒全量；download=1 让服务端落 Content-Disposition。
     */
    refsBibUrl(
        taskId: string,
        opts?: { keys?: string[]; all?: boolean; download?: boolean },
    ): string {
        const q = new URLSearchParams();
        if (opts?.keys?.length) q.set("keys", opts.keys.join(","));
        if (opts?.all) q.set("all", "1");
        if (opts?.download) q.set("download", "1");
        const qs = q.toString();
        return `${BASE}/task/${taskId}/refs.bib${qs ? `?${qs}` : ""}`;
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
