// dev/mock-api.ts —— Vite dev 中间件：无后端时起 demo（VITE_MOCK_API=0 关闭）。
// 对齐 §2 端点形状；任务进度由步进器驱动，SSE 帧格式与真后端一致。

import type { Connect, Plugin } from "vite";
import type { IncomingMessage, ServerResponse } from "node:http";
import { createReadStream, existsSync, statSync } from "node:fs";
import path from "node:path";

// ---------- 最小合法多页 PDF 生成器（ASCII 文本，demo 用） ----------

function escPdf(s: string): string {
    return s.replace(/[\\()]/g, (c) => `\\${c}`);
}

function miniPdf(title: string, pageTexts: string[]): Buffer {
    const bodies: string[] = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ];
    pageTexts.forEach((text, i) => {
        const contentObj = 5 + i * 2;
        const y = 700 - (i % 8) * 30;
        const stream = `BT /F1 22 Tf 72 ${y} Td (${escPdf(title)}) Tj 0 -40 Td (${escPdf(text)}) Tj ET`;
        bodies.push(
            `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] ` +
                `/Resources << /Font << /F1 3 0 R >> >> /Contents ${contentObj} 0 R >>`,
            `<< /Length ${Buffer.byteLength(stream, "latin1")} >>\nstream\n${stream}\nendstream`,
        );
    });
    const kids = pageTexts.map((_, i) => `${4 + i * 2} 0 R`).join(" ");
    bodies[1] = `<< /Type /Pages /Kids [${kids}] /Count ${pageTexts.length} >>`;

    let out = "%PDF-1.4\n";
    const offsets: number[] = [0];
    bodies.forEach((body, i) => {
        offsets.push(Buffer.byteLength(out, "latin1"));
        out += `${i + 1} 0 obj\n${body}\nendobj\n`;
    });
    const xrefPos = Buffer.byteLength(out, "latin1");
    out += `xref\n0 ${bodies.length + 1}\n0000000000 65535 f \n`;
    for (let i = 1; i <= bodies.length; i++) {
        out += `${offsets[i].toString(10).padStart(10, "0")} 00000 n \n`;
    }
    out += `trailer\n<< /Size ${bodies.length + 1} /Root 1 0 R >>\nstartxref\n${xrefPos}\n%%EOF\n`;
    return Buffer.from(out, "latin1");
}

// ---------- Mock 任务 ----------

type Status =
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

interface MockEvent {
    seq: number;
    type: string;
    data: unknown;
}

interface MockTask {
    id: string;
    kind: string;
    status: Status;
    stage?: string;
    progress: number;
    message?: string;
    title?: string;
    arxiv_id?: string;
    source_name?: string;
    /** cache_key 演示键：`{arxiv_id}|{ver}|{model}|{lang}`——dedup/reuse 判别用 */
    dedup?: string;
    created_at: number;
    updated_at: number;
    counters: {
        total: number;
        done: number;
        cached: number;
        failed: number;
        tokens: number;
    };
    warnings: string[];
    error?: { code: string; message: string; retryable?: boolean } | null;
    events: MockEvent[];
    listeners: Set<ServerResponse>;
    timer?: ReturnType<typeof setInterval>;
    html?: boolean;
    /** 演示 share/pack 422 分支："artifacts" 缺产物 / "failed" 打包失败 */
    share_fail?: "artifacts" | "failed";
    /** 已打过的 share_key——幂等直返（对齐真后端 index 命中） */
    share_key?: string;
}

const tasks = new Map<string, MockTask>();
// Idempotency-Key → taskId：对齐真后端 options.idempotency_key 去重
// （命中直返 202 cache:"idempotent"；任务删除后 key 可复用）
const idemTasks = new Map<string, string>();
let seqCounter = 1;

// 与 client.ts TERMINAL 同口径：终态可删，进行中 409
const TERMINAL: ReadonlySet<Status> = new Set([
    "done",
    "partial",
    "fault",
    "cancelled",
    "interrupted",
    "needs_auth",
]);

// store.RETRYABLE_FROM：retry 只许这些源态（done 不在内——409 invalid_transition）
const RETRYABLE: ReadonlySet<Status> = new Set([
    "fault",
    "partial",
    "cancelled",
    "interrupted",
    "needs_auth",
]);

function mkId(): string {
    return `t_${(seqCounter++).toString(16).padStart(16, "0")}`;
}

function emit(task: MockTask, type: string, data: unknown) {
    const ev: MockEvent = { seq: task.events.length + 1, type, data };
    task.events.push(ev);
    task.updated_at = Date.now() / 1000;
    for (const res of task.listeners) {
        res.write(
            `id: ${ev.seq}\nevent: ${ev.type}\ndata: ${JSON.stringify(ev.data)}\n\n`,
        );
    }
}

/** Idempotency-Key 去重命中——对齐 _create_and_enqueue：key 对应行还在即直返 */
function idemHit(req: Req): MockTask | null {
    const key = req.headers["idempotency-key"];
    if (typeof key !== "string" || !key) return null;
    const tid = idemTasks.get(key);
    return (tid && tasks.get(tid)) || null;
}

function idemRegister(req: Req, t: MockTask) {
    const key = req.headers["idempotency-key"];
    if (typeof key !== "string" || !key) return;
    idemTasks.set(key, t.id);
    emit(t, "log", { line: `[mock] Idempotency-Key ${key} registered` });
}

function snapshot(t: MockTask) {
    return {
        task_id: t.id,
        kind: t.kind,
        status: t.status,
        // snapshot 可选键缺席规则同 server（stage/title/arxiv_id 空值不发行）；
        // message 是 DB 列直发，null 也带键
        stage: t.stage,
        progress: t.progress,
        message: t.message ?? null,
        title: t.title,
        arxiv_id: t.arxiv_id,
        target_lang: "zh-CN",
        model: "mock-model",
        counters: t.counters,
        warnings: t.warnings,
        error: t.error ?? null,
        created_at: t.created_at,
        updated_at: t.updated_at,
        last_seq: t.events.length,
        // server snapshot 恒带 artifacts 键；进行中只有 src.tar 已登记（fetch 即落）
        artifacts: registeredArtifacts(t),
        ...(isDone(t)
            ? {
                  // task_usage 聚合行：从 counters 推演示值（prompt+completion=tokens）
                  usage: {
                      model: "mock-model",
                      calls: t.counters.done,
                      prompt_tokens: Math.round(t.counters.tokens * 0.72),
                      completion_tokens:
                          t.counters.tokens -
                          Math.round(t.counters.tokens * 0.72),
                      latency_s: Math.round(t.counters.done * 1.7),
                  },
              }
            : {}),
    };
}

function isDone(t: MockTask) {
    return [
        "done",
        "partial",
        "fault",
        "cancelled",
        "interrupted",
        "needs_auth",
    ].includes(t.status);
}

// db kind → URL kind，与 server KIND_URL 白名单一致；
// artifacts 键用 db kind，URL 仍走 url kind
const KIND_URL: Record<string, string> = {
    src_tar: "src.tar",
    en_pdf: "en.pdf",
    zh_pdf: "zh.pdf",
    dual_pdf: "dual.pdf",
    dual_json: "dual.json",
    zh_src_zip: "zh-src.zip",
    compile_log: "compile.log",
    md_zip: "md",
    zh_docx: "zh.docx",
    zh_epub: "zh.epub",
};

const isDoc = (t: MockTask) => t.kind === "docx" || t.kind === "epub";

// URL kind → db kind（server URL_KIND 反映射）
const URL_KIND: Record<string, string> = Object.fromEntries(
    Object.entries(KIND_URL).map(([db, u]) => [u, db]),
);

/** 该任务当前已登记产物集（db kind → url）——snapshot/files 下载共用 */
function registeredArtifacts(t: MockTask): Record<string, string> {
    if (isDone(t)) return artifactsOf(t);
    return t.status === "queued" ? {} : partialArtifacts(t);
}

function artifactsOf(t: MockTask): Record<string, string> {
    // doc 管线（export_document 插译）：仅 src_tar + zh_docx/zh_epub，
    // 无 dual.json → reader 端点按真后端语义 404
    const kinds = isDoc(t)
        ? ["src_tar", `zh_${t.kind}`]
        : t.html
          ? [
                "src_tar",
                "en_pdf",
                "zh_src_zip",
                "dual_json",
                "md_zip",
                "compile_log",
            ]
          : [
                "src_tar",
                "en_pdf",
                "zh_pdf",
                "dual_pdf",
                "dual_json",
                "zh_src_zip",
                "compile_log",
            ];
    const out: Record<string, string> = {};
    for (const k of kinds) out[k] = `/api/files/${t.id}/${KIND_URL[k]}`;
    return out;
}

/** 进行中任务已登记产物：fetch 一完成 src.tar 即在库（快照/cancel 事件共用） */
function partialArtifacts(t: MockTask): Record<string, string> {
    return { src_tar: `/api/files/${t.id}/src.tar` };
}

const TOTAL_CHUNKS = 24;

const WARN_POOL = [
    {
        code: "placeholder_repair",
        message: "占位符 ⟦MATH0003⟧ 译文缺失，已自动补回",
    },
    { code: "context_truncated", message: "段落过长，上下文窗口已截断" },
    { code: "glossary_miss", message: "术语表条目未命中：eigenpair" },
];

/** 步进器：每 tick 推一个阶段或一批 chunk，~7s 跑完整管线 */
function drive(t: MockTask) {
    let tick = 0;
    let seq = 0;
    let compileTicks = 0;
    // 演示用：translating 期间随机发 1~2 条 warning
    let warnLeft = 1 + Math.floor(Math.random() * 2);
    t.timer = setInterval(() => {
        tick++;
        if (tick === 1) {
            t.status = "fetching";
            t.stage = "fetching";
            t.progress = 5;
            t.message = "拉取 arXiv e-print";
            emit(t, "stage", {
                stage: "fetching",
                progress: 5,
                message: t.message,
                at: Date.now() / 1000,
            });
        } else if (tick === 3) {
            t.status = "parsing";
            t.stage = "parsing";
            t.progress = 16;
            t.message = "展平 LaTeX 源码";
            emit(t, "stage", {
                stage: "parsing",
                progress: 16,
                message: t.message,
                at: Date.now() / 1000,
            });
            emit(t, "log", { line: "[parse] main.tex flattened: 24 chunks" });
        } else if (tick >= 4 && seq < TOTAL_CHUNKS) {
            if (t.status !== "translating") {
                t.status = "translating";
                t.stage = "translating";
                emit(t, "stage", {
                    stage: "translating",
                    progress: 26,
                    message: "翻译中",
                    at: Date.now() / 1000,
                });
            }
            const items = [];
            for (let k = 0; k < 2 && seq < TOTAL_CHUNKS; k++, seq++) {
                const r = Math.random();
                items.push({
                    seq,
                    status:
                        r < 0.82 ? "ok" : r < 0.95 ? "fallback_orig" : "failed",
                    ...(r >= 0.82 && r < 0.95
                        ? { error_code: "placeholder_mismatch" }
                        : {}),
                });
            }
            t.counters = {
                total: TOTAL_CHUNKS,
                done: seq,
                cached: Math.floor(seq * 0.15),
                failed: items.filter((i) => i.status === "failed").length,
                tokens: seq * 380,
            };
            t.progress = 25 + Math.round((seq / TOTAL_CHUNKS) * 60);
            emit(t, "chunk", { ...t.counters, items });
            if (warnLeft > 0 && Math.random() < 0.2) {
                warnLeft--;
                const w =
                    WARN_POOL[Math.floor(Math.random() * WARN_POOL.length)];
                emit(t, "warning", w);
                t.warnings.push(`[${w.code}] ${w.message}`);
            }
        } else if (seq >= TOTAL_CHUNKS && compileTicks < 3) {
            compileTicks++;
            if (t.stage !== "compiling") {
                t.status = "compiling";
                t.stage = "compiling";
                t.progress = 92;
                emit(t, "stage", {
                    stage: "compiling",
                    progress: 92,
                    message: "编译中文 PDF",
                    at: Date.now() / 1000,
                });
                emit(t, "log", { line: "[compile] xelatex pass 1/2" });
            }
        } else if (seq >= TOTAL_CHUNKS) {
            clearInterval(t.timer);
            t.status = "done";
            t.stage = undefined;
            t.progress = 100;
            t.message = undefined;
            emit(t, "done", {
                status: "done",
                artifacts: artifactsOf(t),
                stats: {
                    tokens: t.counters.tokens,
                    seconds: Math.round(tick * 0.35),
                    chunks_failed: t.counters.failed,
                },
            });
            for (const res of t.listeners) res.end();
            t.listeners.clear();
        }
    }, 350);
}

// ---------- 静态 mock 数据 ----------

const EN_PAGES = 6;
const ZH_PAGES = 8;

const enPdf = miniPdf(
    "TeXlate mock — ORIGINAL",
    Array.from(
        { length: EN_PAGES },
        (_, i) => `EN page ${i + 1} / ${EN_PAGES} — lorem ipsum source text`,
    ),
);
const zhPdf = miniPdf(
    "TeXlate mock — ZH (placeholder text)",
    Array.from(
        { length: ZH_PAGES },
        (_, i) => `ZH page ${i + 1} / ${ZH_PAGES} — translated text goes here`,
    ),
);
const dualPdf = miniPdf(
    "TeXlate mock — DUAL",
    Array.from(
        { length: ZH_PAGES },
        (_, i) => `dual page ${i + 1} / ${ZH_PAGES}`,
    ),
);

const mockChunks = [
    {
        seq: 0,
        src_file: "main.tex",
        kind: "text",
        en: "# Abstract\n\nWe study the problem of *cross-lingual* document translation.\n\nThe loss is $L = \\sum_i \\ell_i$.",
        zh: "# 摘要\n\n我们研究**跨语言**文档翻译问题。\n\n损失函数为 $L = \\sum_i \\ell_i$。",
    },
    {
        seq: 1,
        src_file: "main.tex",
        kind: "text",
        en: "## 1. Introduction\n\nMachine translation of scientific documents remains challenging due to formulas like $$E = mc^2$$ and structural markup.",
        zh: "## 1. 引言\n\n科技文献的机器翻译因 $$E = mc^2$$ 这类公式与结构化标记而仍然困难。",
    },
    {
        seq: 2,
        src_file: "main.tex",
        kind: "text",
        en: "Our pipeline preserves *all* LaTeX commands during translation, then recompiles with `ctex`.",
        zh: "我们的管线在翻译过程中保留*全部* LaTeX 命令，随后用 `ctex` 重编译。",
    },
    {
        seq: 3,
        src_file: "main.tex",
        kind: "text",
        en: "## 2. Method\n\nSegment-level translation with a sliding context window of three paragraphs.",
        zh: "## 2. 方法\n\n段落级翻译，滑窗为三段的上下文窗口。",
    },
    {
        seq: 4,
        src_file: "main.tex",
        kind: "text",
        en: "Results show placeholder integrity of 99.6% across the corpus.",
        zh: "结果显示全语料占位符完整性达 99.6%。",
    },
    {
        seq: 5,
        src_file: "main.tex",
        kind: "text",
        en: "## 3. Conclusion\n\nThe reader presents original and translation side by side, scroll-synchronized.",
        zh: "## 3. 结论\n\n阅读器以同步滚动的双栏对照呈现原文与译文。",
    },
];

function mockDual() {
    return {
        version: 1,
        documents: {
            // version 恒 "mock"——与 files manifest sha256 / position 校验 /
            // ?version= 参数同一常量，三层口径一致（真后端是各文件 sha256）
            original: { version: "mock", pages: EN_PAGES },
            translated: { version: "mock", pages: ZH_PAGES },
        },
        alignment: {
            kind: "landmarks",
            heights: {
                original: Array(EN_PAGES).fill(1.414),
                translated: Array(ZH_PAGES).fill(1.414),
            },
            pairs: Array.from({ length: EN_PAGES }, (_, i) => ({
                id: `p.${i}`,
                original: { page: i + 1, fraction: 0 },
                translated: {
                    page: Math.min(
                        ZH_PAGES,
                        Math.floor((i * ZH_PAGES) / EN_PAGES) + 1,
                    ),
                    fraction: 0,
                },
            })),
            regions: [
                {
                    id: "figure.1",
                    original: { page: 3, start: 0.2, end: 0.5 },
                    translated: { page: 4, start: 0.1, end: 0.4 },
                },
            ],
        },
        chunks: mockChunks,
    };
}

function mockReader(task: MockTask) {
    return {
        view: task.html ? "html" : "pdf",
        // 哪侧无产物哪侧缺省（client.ts ReaderInfo 契约）：html 降级路无 zh.pdf
        // → translated 缺席；en.pdf 编译成功 → original 在场
        documents: task.html
            ? {
                  original: {
                      version: "mock",
                      pages: EN_PAGES,
                      url: `/api/files/${task.id}/en.pdf`,
                  },
              }
            : {
                  original: {
                      version: "mock",
                      pages: EN_PAGES,
                      url: `/api/files/${task.id}/en.pdf`,
                  },
                  translated: {
                      version: "mock",
                      pages: ZH_PAGES,
                      url: `/api/files/${task.id}/zh.pdf`,
                  },
              },
        alignment: mockDual().alignment,
        // server 恒返 dict（reading.json 缺席 → {}），不是 null
        reading: {},
    };
}

function seedTask(
    id: string,
    status: Status,
    opts?: Partial<MockTask>,
): MockTask {
    const t: MockTask = {
        id,
        kind: opts?.kind ?? "arxiv",
        status,
        progress: isDone({ status } as MockTask) ? 100 : 0,
        title: opts?.title,
        arxiv_id: opts?.arxiv_id,
        created_at: Date.now() / 1000 - 300,
        updated_at: Date.now() / 1000,
        counters: {
            total: TOTAL_CHUNKS,
            done: TOTAL_CHUNKS,
            cached: 4,
            failed: 1,
            tokens: 8123,
        },
        warnings: [],
        error: null,
        events: [],
        listeners: new Set(),
        ...opts,
    };
    t.source_name ??= t.arxiv_id ?? t.title;
    // arxiv/share kind 参与 dedup 寻址（对齐 cache_key 组分：id+ver+model+lang）
    if ((t.kind === "arxiv" || t.kind === "share") && t.arxiv_id) {
        t.dedup ??= `${t.arxiv_id}|latest|mock-model|zh-CN`;
    }
    tasks.set(id, t);
    return t;
}

seedTask("t_0000000000000a01", "done", {
    title: "Mock paper — PDF 对照演示",
    arxiv_id: "2501.14787",
});
seedTask("t_0000000000000a02", "done", {
    title: "Mock paper — HTML 降级演示",
    arxiv_id: "2409.01234",
    html: true,
});
seedTask("t_0000000000000a03", "partial", {
    title: "Mock paper — 部分失败样例",
    arxiv_id: "2401.00001",
});
seedTask("t_0000000000000a04", "fault", {
    title: "Mock paper — 编译失败样例",
    arxiv_id: "2407.05555",
    error: {
        code: "compile",
        message: "xelatex 编译失败(mock)",
        retryable: true,
    },
    warnings: ["⟦MATH0007⟧ 占位符在译文中缺失，已回退原文"],
});
seedTask("t_0000000000000a05", "needs_auth", {
    title: "Mock paper — 需要 API Key",
    arxiv_id: "2406.99999",
    error: {
        code: "auth_required",
        message: "未配置 API Key(mock)",
        retryable: true,
    },
});
// doc 管线演示：done 但 reader 404——产物下载面板的复现种子
seedTask("t_0000000000000a06", "done", {
    kind: "docx",
    title: "Mock doc — Word 产物演示（无对照视图）",
});
seedTask("t_0000000000000a07", "done", {
    kind: "epub",
    title: "Mock doc — EPUB 产物演示（无对照视图）",
});
// share/pack 演示：a08 走 422 artifacts 分支；a09 kind=share（UI 不显示按钮、点也 422）
seedTask("t_0000000000000a08", "done", {
    title: "Mock paper — share 打包缺产物演示",
    arxiv_id: "2408.07777",
    share_fail: "artifacts",
});
seedTask("t_0000000000000a09", "done", {
    kind: "share",
    title: "Mock share — 导入产物不自包演示",
    arxiv_id: "2501.14787",
});

// settings 演示态：GET 出参即真后端 public() 形状（api_key 剥壳成 has_api_key，
// 字段面 = SettingsStore.FIELDS 全量）
const mockSettings: Record<string, unknown> = {
    has_api_key: true,
    base_url: "http://127.0.0.1:3033/v1",
    model: "swe-2-medium",
    target_lang: "zh-CN",
    glossary: "",
    glossary_dir: "",
    concurrency: 3,
    engine: "auto",
    context_guidance: true,
    cors_origins: [],
    quota_max_tasks: 0,
    quota_max_bytes: 0,
};

// server PUT /api/settings 键白名单 = SettingsStore.FIELDS + 两个伪字段
const SETTINGS_KEYS = new Set([
    "base_url",
    "model",
    "api_key",
    "target_lang",
    "glossary",
    "glossary_dir",
    "concurrency",
    "engine",
    "context_guidance",
    "cors_origins",
    "quota_max_tasks",
    "quota_max_bytes",
    "clear_api_key",
    "has_api_key",
]);

// ---------- 路由 ----------

type Req = IncomingMessage;
type Res = ServerResponse;

function json(res: Res, status: number, body: unknown) {
    res.writeHead(status, {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
    });
    res.end(JSON.stringify(body));
}

function notFound(res: Res, detail = "not found") {
    json(res, 404, { detail });
}

const str = (v: unknown) => (typeof v === "string" ? v : "");

// settings.TARGET_LANGS 同口径
const TARGET_LANGS: ReadonlySet<string> = new Set(["zh-CN", "zh-TW", "en"]);

// fetch.normalize_arxiv_id + _valid_id 的 mock 口径：
// 剥 URL/arXiv: 前缀、.pdf、vN 后缀，再按新/旧 id 形白名单判
const NEW_ID_RE = /^\d{4}\.\d{4,5}$/;
const OLD_ID_RE = /^[a-zA-Z-]+(?:\.[A-Z][a-zA-Z]+)?\/\d{7}$/;
const ID_URL_RE =
    /^(?:(?:https?:\/\/)?(?:[\w.-]+\.)?arxiv\.org\/(?:abs|pdf|src|e-print|html|format)\/+|arxiv\s*:\s*)/i;
const VER_RE = /^(.+?)[vV](\d{1,3})$/;

function normalizeArxiv(
    raw: string,
): { base: string; ver: number | null } | null {
    let s = raw.trim().replace(ID_URL_RE, "");
    s = s
        .split("?")[0]
        .split("#")[0]
        .replace(/^\/+|\/+$/g, "");
    s = s.replace(/\.pdf$/i, "");
    const vm = VER_RE.exec(s);
    if (vm && (NEW_ID_RE.test(vm[1]) || OLD_ID_RE.test(vm[1]))) {
        return { base: vm[1], ver: Number(vm[2]) };
    }
    if (NEW_ID_RE.test(s) || OLD_ID_RE.test(s)) return { base: s, ver: null };
    return null;
}

// settings.validate_base_url 的 mock 口径：http(s) 裸服务根，无 userinfo/query/
// fragment；http 仅 localhost/tailnet（100.64/10、*.ts.net）可放行
function validateBaseUrl(v: string): string | null {
    let u: URL;
    try {
        u = new URL(v.trim().replace(/\/+$/, ""));
    } catch {
        return "invalid base_url（不含 userinfo/query/fragment 的裸服务根）";
    }
    if (
        (u.protocol !== "https:" && u.protocol !== "http:") ||
        !u.hostname ||
        u.username ||
        u.password ||
        u.search ||
        u.hash
    ) {
        return "invalid base_url（不含 userinfo/query/fragment 的裸服务根）";
    }
    if (u.protocol === "http:") {
        const h = u.hostname.toLowerCase();
        const local =
            h === "localhost" ||
            h === "::1" ||
            h.startsWith("127.") ||
            h.endsWith(".ts.net") ||
            /^100\.(6[4-9]|[7-9]\d|1[01]\d|12[0-7])\./.test(h);
        if (!local)
            return "远程 API 强制 HTTPS；仅 localhost 或 tailnet 可用 HTTP";
    }
    return null;
}

function serveSse(req: Req, res: Res, task: MockTask) {
    res.writeHead(200, {
        "content-type": "text/event-stream",
        "cache-control": "no-store",
        connection: "keep-alive",
    });
    res.write(
        `id: 0\nevent: snapshot\ndata: ${JSON.stringify(snapshot(task))}\n\n`,
    );
    const lastId = Number(req.headers["last-event-id"] ?? 0) || 0;
    for (const ev of task.events) {
        if (ev.seq > lastId)
            res.write(
                `id: ${ev.seq}\nevent: ${ev.type}\ndata: ${JSON.stringify(ev.data)}\n\n`,
            );
    }
    if (isDone(task)) {
        res.end();
        return;
    }
    task.listeners.add(res);
    const ping = setInterval(() => res.write(": ping\n\n"), 15000);
    req.on("close", () => {
        clearInterval(ping);
        task.listeners.delete(res);
    });
}

const FILE_BODY: Record<
    string,
    (taskId: string) => { body: Buffer | string; type: string }
> = {
    "en.pdf": () => ({ body: enPdf, type: "application/pdf" }),
    "zh.pdf": () => ({ body: zhPdf, type: "application/pdf" }),
    "dual.pdf": () => ({ body: dualPdf, type: "application/pdf" }),
    "dual.json": () => ({
        body: JSON.stringify(mockDual()),
        type: "application/json",
    }),
    "compile.log": () => ({
        body: "[mock] xelatex: no errors\n",
        type: "text/plain",
    }),
    "src.tar": () => ({
        body: Buffer.from("mock tar\n"),
        type: "application/gzip",
    }),
    "zh-src.zip": () => ({
        body: Buffer.from("PK\x05\x06" + "\0".repeat(18), "latin1"),
        type: "application/zip",
    }),
    md: () => ({
        body: Buffer.from("PK\x05\x06" + "\0".repeat(18), "latin1"),
        type: "application/zip",
    }),
    "zh.docx": () => ({
        body: Buffer.from("PK\x05\x06" + "\0".repeat(18), "latin1"),
        type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    }),
    "zh.epub": () => ({
        body: Buffer.from("PK\x05\x06" + "\0".repeat(18), "latin1"),
        type: "application/epub+zip",
    }),
};

function handleApi(req: Req, res: Res, url: URL): boolean {
    const p = url.pathname;
    const m = (re: RegExp) => p.match(re);

    let mm: RegExpMatchArray | null;

    if (req.method === "GET" && p === "/api/health") {
        json(res, 200, {
            ok: true,
            version: "mock",
            compilers: { tectonic: true, xelatex: true, babeldoc: true },
            data_dir: "/tmp/texlate-mock",
        });
        return true;
    }
    if (req.method === "GET" && p === "/api/providers") {
        // 对齐真后端 provider_presets：全量预设 + active（按当前 base_url）+ has_env_key
        const presets = [
            {
                id: "gateway",
                name: "Local Gateway",
                base_url: "http://127.0.0.1:3033/v1",
                model: "swe-2-medium",
                key_env: "MOCK_GATEWAY_KEY",
            },
            {
                id: "deepseek",
                name: "DeepSeek",
                base_url: "https://api.deepseek.com",
                model: "deepseek-chat",
                key_env: "DEEPSEEK_API_KEY",
            },
            {
                id: "openai",
                name: "OpenAI",
                base_url: "https://api.openai.com",
                model: "gpt-4o-mini",
                key_env: "OPENAI_API_KEY",
            },
            {
                id: "anthropic",
                name: "Anthropic",
                base_url: "https://api.anthropic.com",
                model: "claude-haiku-4-5",
                key_env: "ANTHROPIC_API_KEY",
            },
            {
                id: "qwen",
                name: "Alibaba Qwen",
                base_url: "https://dashscope.aliyuncs.com/compatible-mode",
                model: "qwen-flash",
                key_env: "DASHSCOPE_API_KEY",
            },
            {
                id: "custom",
                name: "Custom (OpenAI 兼容)",
                base_url: "",
                model: "",
                key_env: "TEXLATE_API_KEY",
            },
        ];
        for (const pr of presets) {
            (pr as Record<string, unknown>).active =
                pr.base_url !== "" && pr.base_url === mockSettings.base_url;
            (pr as Record<string, unknown>).has_env_key = false;
        }
        json(res, 200, { providers: presets });
        return true;
    }
    if (req.method === "GET" && p === "/api/tasks") {
        // 对齐真后端列表行：无 artifacts/warnings/last_seq/usage（懒拉补齐），
        // 含 source_name；?status= 过滤
        const want = url.searchParams.get("status") ?? "";
        const rows = [...tasks.values()]
            .filter((t) => !want || t.status === want)
            .map((t) => ({
                task_id: t.id,
                kind: t.kind,
                status: t.status,
                // 真后端 DB 列 NULL 也发 null——不丢键（snapshot 规则不同：可选键缺席）
                stage: t.stage ?? null,
                progress: t.progress,
                message: t.message ?? null,
                title: t.title ?? null,
                arxiv_id: t.arxiv_id ?? null,
                source_name: t.source_name ?? null,
                target_lang: "zh-CN",
                model: "mock-model",
                created_at: t.created_at,
                updated_at: t.updated_at,
                counters: t.counters,
                error: t.error ?? null,
            }));
        json(res, 200, { tasks: rows });
        return true;
    }
    // arxiv_id 走 `:path`（旧式 archive/NNNNNNN 含斜杠），body JSON 需读——
    // 校验/prefer/dedup 都要看字段
    if ((mm = m(/^\/api\/arxiv\/(.+)\/translate$/)) && req.method === "POST") {
        const id = decodeURIComponent(mm[1]);
        let body = "";
        req.on("data", (c: Buffer) => (body += c.toString("latin1")));
        req.on("end", () => {
            const hit = idemHit(req);
            if (hit) {
                json(res, 202, {
                    task_id: hit.id,
                    status: hit.status,
                    cache: "idempotent",
                    events_url: `/api/task/${hit.id}`,
                    reader_url: `/api/task/${hit.id}/reader`,
                });
                return;
            }
            const norm = normalizeArxiv(id);
            if (!norm) {
                json(res, 400, { detail: `invalid arxiv id: '${id}'` });
                return;
            }
            let b: Record<string, unknown>;
            try {
                b = body ? (JSON.parse(body) as Record<string, unknown>) : {};
            } catch {
                json(res, 400, { detail: "bad json" });
                return;
            }
            const model = str(b.model) || "mock-model";
            const lang = str(b.target_lang) || "zh-CN";
            if (!TARGET_LANGS.has(lang)) {
                json(res, 400, {
                    detail: `target_lang ∈ ${[...TARGET_LANGS].sort()}`,
                });
                return;
            }
            const opts = (b.options ?? {}) as Record<string, unknown>;
            const prefer = str(opts.prefer) || "reuse";
            if (prefer !== "reuse" && prefer !== "fresh") {
                json(res, 400, { detail: "options.prefer ∈ reuse|fresh" });
                return;
            }
            const key = `${norm.base}|${norm.ver ?? "latest"}|${model}|${lang}`;
            if (prefer === "reuse") {
                // find_active_by_cache_key：ACTIVE+interrupted → 409 带 task_id
                const active = [...tasks.values()].find(
                    (t) =>
                        t.dedup === key &&
                        (!TERMINAL.has(t.status) || t.status === "interrupted"),
                );
                if (active) {
                    json(res, 409, {
                        detail: `active task ${active.id} exists`,
                        task_id: active.id,
                        code: "duplicate_active",
                    });
                    return;
                }
                // find_reusable：done/partial → 200 reused（不建行不入队）
                const done = [...tasks.values()].find(
                    (t) =>
                        t.dedup === key &&
                        (t.status === "done" || t.status === "partial"),
                );
                if (done) {
                    json(res, 200, {
                        task_id: done.id,
                        status: done.status,
                        reused: true,
                        events_url: `/api/task/${done.id}`,
                        ...(isDoc(done)
                            ? {}
                            : { reader_url: `/api/task/${done.id}/reader` }),
                    });
                    return;
                }
            }
            const t = seedTask(mkId(), "queued", {
                title: `arXiv ${norm.base}`,
                arxiv_id: norm.base,
                dedup: key,
                counters: {
                    total: 0,
                    done: 0,
                    cached: 0,
                    failed: 0,
                    tokens: 0,
                },
            });
            idemRegister(req, t);
            if (req.headers["x-texlate-key"]) {
                emit(t, "log", {
                    line: "[mock] X-Texlate-Key received (per-request BYOK)",
                });
            }
            drive(t);
            json(res, 202, {
                task_id: t.id,
                status: "queued",
                cache: "miss",
                events_url: `/api/task/${t.id}`,
                reader_url: `/api/task/${t.id}/reader`,
            });
        });
        return true;
    }
    if (req.method === "POST" && p === "/api/upload") {
        // 按扩展名演示 doc 管线（真后端走魔数嗅探，mock 只看文件名）
        let body = "";
        req.on("data", (c: Buffer) => (body += c.toString("latin1")));
        req.on("end", () => {
            const hit = idemHit(req);
            if (hit) {
                json(res, 202, {
                    task_id: hit.id,
                    status: hit.status,
                    cache: "idempotent",
                    events_url: `/api/task/${hit.id}`,
                    ...(isDoc(hit)
                        ? {}
                        : { reader_url: `/api/task/${hit.id}/reader` }),
                });
                return;
            }
            const fname = /filename="([^"]+)"/.exec(body)?.[1] ?? "upload.tex";
            const ext = fname.toLowerCase().split(".").pop() ?? "";
            const kind =
                ext === "docx" || ext === "epub"
                    ? ext
                    : ext === "pdf"
                      ? "upload_pdf"
                      : "upload_tex";
            const t = seedTask(mkId(), "queued", {
                kind,
                title: fname,
                counters: {
                    total: 0,
                    done: 0,
                    cached: 0,
                    failed: 0,
                    tokens: 0,
                },
            });
            idemRegister(req, t);
            if (req.headers["x-texlate-key"]) {
                emit(t, "log", {
                    line: "[mock] X-Texlate-Key received (per-request BYOK)",
                });
            }
            drive(t);
            json(res, 202, {
                task_id: t.id,
                status: "queued",
                events_url: `/api/task/${t.id}`,
                // 对齐后端新契约：reader_url 仅产 dual.json 的 kind 下发
                ...(isDoc(t) ? {} : { reader_url: `/api/task/${t.id}/reader` }),
            });
        });
        return true;
    }
    if (req.method === "POST" && p === "/api/share/import") {
        // share 包导入演示：kind=share 走完整管线（真后端 fetch/parse/compile 重跑）。
        // 与真后端同口径：manifest key_parts 重算 cache_key → prefer=reuse dedup
        // （同 id+model+lang 的 done 任务在场 → 200 reused，消费侧共享缓存命中路径）。
        // 用独立 id——避开 a01 seed 的 done 命中，让首次导入跑管线、重导演示 reused
        let body = "";
        req.on("data", (c: Buffer) => (body += c.toString("latin1")));
        req.on("end", () => {
            const hit = idemHit(req);
            if (hit) {
                json(res, 202, {
                    task_id: hit.id,
                    status: hit.status,
                    cache: "idempotent",
                    events_url: `/api/task/${hit.id}`,
                    reader_url: `/api/task/${hit.id}/reader`,
                });
                return;
            }
            const key = "2501.99999|latest|mock-model|zh-CN";
            const active = [...tasks.values()].find(
                (t) =>
                    t.dedup === key &&
                    (!TERMINAL.has(t.status) || t.status === "interrupted"),
            );
            if (active) {
                json(res, 409, {
                    detail: `active task ${active.id} exists`,
                    task_id: active.id,
                    code: "duplicate_active",
                });
                return;
            }
            const done = [...tasks.values()].find(
                (t) =>
                    t.dedup === key &&
                    (t.status === "done" || t.status === "partial"),
            );
            if (done) {
                json(res, 200, {
                    task_id: done.id,
                    status: done.status,
                    reused: true,
                    events_url: `/api/task/${done.id}`,
                    reader_url: `/api/task/${done.id}/reader`,
                });
                return;
            }
            const fname =
                /filename="([^"]+)"/.exec(body)?.[1] ?? "bundle.share.zip";
            const t = seedTask(mkId(), "queued", {
                kind: "share",
                title: fname,
                arxiv_id: "2501.99999",
                dedup: key,
                counters: {
                    total: 0,
                    done: 0,
                    cached: 0,
                    failed: 0,
                    tokens: 0,
                },
            });
            idemRegister(req, t);
            if (req.headers["x-texlate-key"]) {
                emit(t, "log", {
                    line: "[mock] X-Texlate-Key received (per-request BYOK)",
                });
            }
            drive(t);
            json(res, 202, {
                task_id: t.id,
                status: "queued",
                events_url: `/api/task/${t.id}`,
                reader_url: `/api/task/${t.id}/reader`,
            });
        });
        return true;
    }
    if ((mm = m(/^\/api\/task\/([^/]+)$/)) && req.method === "GET") {
        const t = tasks.get(mm[1]);
        if (!t) return (notFound(res), true);
        const accept = req.headers.accept ?? "";
        if (accept.includes("text/event-stream")) serveSse(req, res, t);
        else json(res, 200, snapshot(t));
        return true;
    }
    if ((mm = m(/^\/api\/task\/([^/]+)$/)) && req.method === "DELETE") {
        const t = tasks.get(mm[1]);
        if (!t) return (notFound(res), true);
        // 真后端 ACTIVE → 409 invalid_transition；删前补 done{status:"deleted"} 帧收尾
        if (!TERMINAL.has(t.status)) {
            json(res, 409, {
                detail: `task ${t.id} is ${t.status}: cancel first`,
                code: "invalid_transition",
            });
            return true;
        }
        if (t.timer) clearInterval(t.timer);
        emit(t, "done", { status: "deleted", artifacts: {}, stats: {} });
        for (const l of t.listeners) l.end();
        tasks.delete(t.id);
        // 行删则 idempotency_key 释放（server find_by_idempotency 查行，行无则 key 可复用）
        for (const [k, v] of idemTasks) if (v === t.id) idemTasks.delete(k);
        json(res, 200, { task_id: t.id, status: "deleted" });
        return true;
    }
    if ((mm = m(/^\/api\/task\/([^/]+)\/cancel$/)) && req.method === "POST") {
        const t = tasks.get(mm[1]);
        if (!t) return (notFound(res), true);
        // 真后端仅 ACTIVE → cancelled；终态重复 cancel → 409 invalid_transition
        if (TERMINAL.has(t.status)) {
            json(res, 409, {
                detail: `${t.id}: ${t.status} -> cancelled rejected`,
                code: "invalid_transition",
            });
            return true;
        }
        if (t.timer) clearInterval(t.timer);
        t.status = "cancelled";
        emit(t, "done", {
            status: "cancelled",
            artifacts: partialArtifacts(t),
            stats: {
                tokens: t.counters.tokens,
                seconds: Math.round(Date.now() / 1000 - t.created_at),
                chunks_failed: t.counters.failed,
            },
        });
        json(res, 200, { task_id: t.id, status: "cancelled" });
        return true;
    }
    if ((mm = m(/^\/api\/task\/([^/]+)\/retry$/)) && req.method === "POST") {
        const t = tasks.get(mm[1]);
        if (!t) return (notFound(res), true);
        let body = "";
        req.on("data", (c: Buffer) => (body += c.toString("latin1")));
        req.on("end", () => {
            // 守卫阶梯对齐真后端：非 RETRYABLE_FROM → 409（先守卫后读 body 语义；
            // mock 为取 bad_keys 先读体但响应口径不变）
            if (!RETRYABLE.has(t.status)) {
                json(res, 409, {
                    detail: `${t.id}: ${t.status} -> queued rejected`,
                    code: "invalid_transition",
                });
                return;
            }
            if (t.status === "needs_auth" && !req.headers["x-texlate-key"]) {
                json(res, 401, {
                    detail: "auth_source=header：重试必须重带 X-Texlate-Key",
                    code: "auth_required",
                });
                return;
            }
            let b: Record<string, unknown>;
            try {
                b = body ? (JSON.parse(body) as Record<string, unknown>) : {};
            } catch {
                json(res, 400, { detail: "bad json" });
                return;
            }
            const bad = Object.keys(b)
                .filter((k) => k !== "main" && k !== "options")
                .sort();
            if (bad.length) {
                json(res, 400, {
                    detail: `retry body 仅支持 main/options，不识别: ${JSON.stringify(bad)}`,
                    code: "invalid_request",
                });
                return;
            }
            if (
                "options" in b &&
                (typeof b.options !== "object" || b.options === null)
            ) {
                json(res, 400, {
                    detail: "retry options 须为 object",
                    code: "invalid_request",
                });
                return;
            }
            t.status = "queued";
            t.stage = undefined;
            t.progress = 0;
            t.error = null;
            t.counters = { total: 0, done: 0, cached: 0, failed: 0, tokens: 0 };
            if (req.headers["x-texlate-key"]) {
                emit(t, "log", {
                    line: "[mock] X-Texlate-Key received (per-request BYOK)",
                });
            }
            drive(t);
            // 真后端 202 _accepted 形状：{task_id,status,events_url,cache:"retry",reader_url?}
            json(res, 202, {
                task_id: t.id,
                status: "queued",
                cache: "retry",
                events_url: `/api/task/${t.id}`,
                ...(isDoc(t) ? {} : { reader_url: `/api/task/${t.id}/reader` }),
            });
        });
        return true;
    }
    if (
        (mm = m(/^\/api\/task\/([^/]+)\/share\/pack$/)) &&
        req.method === "POST"
    ) {
        const t = tasks.get(mm[1]);
        if (!t) return (notFound(res), true);
        // 对齐真后端守卫阶梯：kind=share → 422；非 done/partial → 409；无 arxiv_id → 422
        if (t.kind === "share") {
            json(res, 422, {
                detail: "kind=share 任务不打共享包（导入产物不自包）",
                code: "share_pack_rejected",
            });
            return true;
        }
        if (t.status !== "done" && t.status !== "partial") {
            json(res, 409, {
                detail: `任务状态 ${t.status}：仅 done/partial 终态可打包`,
                code: "invalid_state",
            });
            return true;
        }
        if (!t.arxiv_id) {
            json(res, 422, {
                detail: "任务无 arxiv_id（不参与共享寻址）",
                code: "share_pack_rejected",
            });
            return true;
        }
        if (t.share_fail === "artifacts") {
            json(res, 422, {
                detail: "缺必需产物: ['zh-src.zip'](mock)",
                code: "share_pack_artifacts",
            });
            return true;
        }
        if (t.share_fail === "failed") {
            json(res, 422, {
                detail: "share 打包失败(mock)",
                code: "share_pack_failed",
            });
            return true;
        }
        // 幂等：已打过 → 同 share_key 直返不重打
        t.share_key ??= `s-${t.arxiv_id.replace(/[^a-z0-9]/gi, "").toLowerCase()}-zh-${t.id.slice(-4)}`;
        json(res, 200, {
            share_key: t.share_key,
            url: `${t.share_key}.share.zip`,
            bytes: 20480,
        });
        return true;
    }
    if ((mm = m(/^\/api\/task\/([^/]+)\/reader$/)) && req.method === "GET") {
        const t = tasks.get(mm[1]);
        if (!t) return (notFound(res), true);
        // doc 任务无 dual.json——对齐真后端 404（"dual.json 未产出"）
        if (isDoc(t)) return (notFound(res, "dual.json 未产出"), true);
        json(res, 200, mockReader(t));
        return true;
    }
    if (
        (mm = m(/^\/api\/task\/([^/]+)\/reader\/position$/)) &&
        req.method === "PUT"
    ) {
        const t = tasks.get(mm[1]);
        if (!t) return (notFound(res), true);
        let body = "";
        req.on("data", (c: Buffer) => (body += c.toString("latin1")));
        req.on("end", () => {
            let b: Record<string, unknown>;
            try {
                b = body ? (JSON.parse(body) as Record<string, unknown>) : {};
            } catch {
                json(res, 400, { detail: "bad json" });
                return;
            }
            // document_version 对 zh.pdf sha256——mock sha 恒 "mock"，不符即 409
            const want = str(b.document_version);
            const rec =
                FILE_BODY["zh.pdf"] && artifactsOf(t).zh_pdf ? "mock" : "";
            if (want && rec && want !== rec) {
                json(res, 409, {
                    detail: "document_version mismatch",
                    code: "version_mismatch",
                });
                return;
            }
            json(res, 200, { ok: true });
        });
        return true;
    }
    if (
        (mm = m(/^\/api\/task\/([^/]+)\/chunks$/)) &&
        req.method === "GET"
    ) {
        const t = tasks.get(mm[1]);
        if (!t) return (notFound(res), true);
        const total = t.counters.total || TOTAL_CHUNKS;
        // 已译段数跟 counters.done（drive() 逐拍推进）；done 终态视作全量
        const doneN = t.status === "done" ? total : t.counters.done;
        const off = Math.max(
            0,
            Number(url.searchParams.get("offset") ?? 0) || 0,
        );
        const lim = Number(url.searchParams.get("limit") ?? 0) || 60;
        const rows = [];
        for (let i = off; i < Math.min(total, off + lim); i++) {
            const src = mockChunks[i] ?? {
                kind: "text",
                en: `[mock] paragraph ${i + 1} source text.`,
                zh: `[mock] 第 ${i + 1} 段译文。`,
            };
            rows.push({
                seq: i,
                kind: src.kind,
                // 未译到段 zh 留空——ChunkPreview 按 zh 非空过滤，预览随推进生长
                status: i < doneN ? "ok" : "pending",
                en: src.en,
                zh: i < doneN ? src.zh : "",
            });
        }
        json(res, 200, { chunks: rows, total });
        return true;
    }
    if ((mm = m(/^\/api\/files\/([^/]+)$/)) && req.method === "GET") {
        const t = tasks.get(mm[1]);
        if (!t) return (notFound(res), true);
        // manifest：db kind → {bytes, sha256, created_at, url}（只列已登记的）
        const arts: Record<
            string,
            { bytes: number; sha256: string; created_at: number; url: string }
        > = {};
        for (const [kind, url] of Object.entries(registeredArtifacts(t))) {
            arts[kind] = {
                bytes: 1024,
                sha256: "mock",
                created_at: t.updated_at,
                url,
            };
        }
        json(res, 200, { artifacts: arts });
        return true;
    }
    if (
        (mm = m(/^\/api\/files\/([^/]+)\/(.+)$/)) &&
        (req.method === "GET" || req.method === "HEAD")
    ) {
        const t = tasks.get(mm[1]);
        const kind = decodeURIComponent(mm[2]);
        if (!t) return (notFound(res), true);
        const dbKind = URL_KIND[kind];
        const entry = FILE_BODY[kind];
        if (!dbKind || !entry)
            return (notFound(res, `unknown kind '${kind}'`), true);
        // 真后端按 files 表登记判 404——任务没产这个 kind 就是 404，不是白名单有就给
        if (!(dbKind in registeredArtifacts(t))) {
            return (notFound(res, `no artifact ${kind}`), true);
        }
        const ver = url.searchParams.get("version") ?? "";
        if (ver && ver !== "mock") {
            json(res, 409, {
                detail: "version mismatch: have mock",
                code: "version_mismatch",
            });
            return true;
        }
        const { body, type } = entry(t.id);
        const headers: Record<string, string> = {
            "content-type": type,
            "cache-control": "no-store",
        };
        // server 按 int 解析 download——非零才发 Content-Disposition
        if (Number(url.searchParams.get("download") ?? 0)) {
            const stem = (t.arxiv_id ?? t.id).replace(/[^A-Za-z0-9_.+-]/g, "_");
            headers["content-disposition"] =
                `attachment; filename="texlate-${stem}-${kind}"`;
        }
        res.writeHead(200, headers);
        res.end(req.method === "HEAD" ? undefined : body);
        return true;
    }
    if (p === "/api/settings" && req.method === "GET") {
        json(res, 200, { ...mockSettings });
        return true;
    }
    if (p === "/api/settings" && req.method === "PUT") {
        let body = "";
        req.on("data", (c) => (body += c));
        req.on("end", () => {
            let b: Record<string, unknown>;
            try {
                b = body ? (JSON.parse(body) as Record<string, unknown>) : {};
            } catch {
                json(res, 400, { detail: "bad json" });
                return;
            }
            // 真后端白名单外键直接 400（防 settings.json 攒垃圾键）
            const bad = Object.keys(b)
                .filter((k) => !SETTINGS_KEYS.has(k))
                .sort();
            if (bad.length) {
                json(res, 400, {
                    detail: `settings 未知字段: ${JSON.stringify(bad)}`,
                });
                return;
            }
            if (
                typeof b.target_lang === "string" &&
                b.target_lang &&
                !TARGET_LANGS.has(b.target_lang)
            ) {
                json(res, 400, {
                    detail: `target_lang ∈ ${[...TARGET_LANGS].sort()}`,
                });
                return;
            }
            // 对齐真后端：clear_api_key 伪字段清 key；api_key 非空才置位
            if (b.clear_api_key) mockSettings.has_api_key = false;
            if (typeof b.api_key === "string" && b.api_key)
                mockSettings.has_api_key = true;
            for (const k of SETTINGS_KEYS) {
                if (
                    k in b &&
                    k !== "api_key" &&
                    k !== "clear_api_key" &&
                    k !== "has_api_key"
                ) {
                    mockSettings[k] = b[k];
                }
            }
            json(res, 200, { ...mockSettings });
        });
        return true;
    }
    if (p === "/api/settings/test" && req.method === "POST") {
        // 对齐真后端：base_url 非法 → 400；探活失败 → {ok:false,detail}；
        // 成功 → {ok,models,model} 回显 body 里的 model
        let body = "";
        req.on("data", (c) => (body += c));
        req.on("end", () => {
            let b: Record<string, unknown>;
            try {
                b = body ? (JSON.parse(body) as Record<string, unknown>) : {};
            } catch {
                json(res, 400, { detail: "bad json" });
                return;
            }
            const baseUrl = str(b.base_url) || str(mockSettings.base_url);
            const err = validateBaseUrl(baseUrl);
            if (err) {
                json(res, 400, { detail: err });
                return;
            }
            if (str(b.api_key) === "bad" || str(b.api_key) === "invalid") {
                json(res, 200, {
                    ok: false,
                    detail: "mock: 探活失败（401 Unauthorized）",
                });
                return;
            }
            json(res, 200, {
                ok: true,
                models: ["swe-2-medium", "deepseek-flash", "gpt-4o-mini"],
                model: str(b.model) || "mock-model",
            });
        });
        return true;
    }
    return false;
}

export function mockApiPlugin(): Plugin {
    return {
        name: "texlate-mock-api",
        apply: "serve",
        configureServer(server) {
            server.middlewares.use((req, res, next) => {
                if (!req.url?.startsWith("/api/")) return next();
                const url = new URL(req.url, "http://localhost");
                if (!handleApi(req, res, url)) notFound(res);
            });
        },
    };
}

/** dev 下把 /pdfjs/{cmaps,standard_fonts,wasm} 映射到 node_modules/pdfjs-dist */
export function pdfjsAssetsMiddleware(
    pdfjsDir: string,
): Connect.NextHandleFunction {
    return (req, res, next) => {
        const mm = req.url?.match(
            /^\/pdfjs\/(cmaps|standard_fonts|wasm)\/(.+)$/,
        );
        if (!mm) return next();
        const file = path.join(pdfjsDir, mm[1], path.basename(mm[2]));
        if (!existsSync(file) || !statSync(file).isFile()) {
            res.writeHead(404);
            res.end();
            return;
        }
        res.writeHead(200, { "content-type": "application/octet-stream" });
        createReadStream(file).pipe(res);
    };
}
