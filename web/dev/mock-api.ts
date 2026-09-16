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
    created_at: number;
    updated_at: number;
    counters: { total: number; done: number; cached: number; failed: number; tokens: number };
    warnings: string[];
    error?: { code: string; message: string; retryable?: boolean } | null;
    events: MockEvent[];
    listeners: Set<ServerResponse>;
    timer?: ReturnType<typeof setInterval>;
    html?: boolean;
}

const tasks = new Map<string, MockTask>();
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

function mkId(): string {
    return `t_${(seqCounter++).toString(16).padStart(16, "0")}`;
}

function emit(task: MockTask, type: string, data: unknown) {
    const ev: MockEvent = { seq: task.events.length + 1, type, data };
    task.events.push(ev);
    task.updated_at = Date.now() / 1000;
    for (const res of task.listeners) {
        res.write(`id: ${ev.seq}\nevent: ${ev.type}\ndata: ${JSON.stringify(ev.data)}\n\n`);
    }
}

function snapshot(t: MockTask) {
    return {
        task_id: t.id,
        kind: t.kind,
        status: t.status,
        stage: t.stage,
        progress: t.progress,
        message: t.message,
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
        ...(isDone(t) ? { artifacts: artifactsOf(t) } : {}),
    };
}

function isDone(t: MockTask) {
    return ["done", "partial", "fault", "cancelled", "interrupted", "needs_auth"].includes(
        t.status,
    );
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

function artifactsOf(t: MockTask): Record<string, string> {
    // doc 管线（export_document 插译）：仅 src_tar + zh_docx/zh_epub，
    // 无 dual.json → reader 端点按真后端语义 404
    const kinds = isDoc(t)
        ? ["src_tar", `zh_${t.kind}`]
        : t.html
          ? ["dual_json", "md_zip", "compile_log"]
          : ["en_pdf", "zh_pdf", "dual_pdf", "dual_json", "zh_src_zip", "compile_log"];
    const out: Record<string, string> = {};
    for (const k of kinds) out[k] = `/api/files/${t.id}/${KIND_URL[k]}`;
    return out;
}

const TOTAL_CHUNKS = 24;

const WARN_POOL = [
    { code: "placeholder_repair", message: "占位符 ⟦MATH0003⟧ 译文缺失，已自动补回" },
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
            emit(t, "stage", { stage: "fetching", progress: 5, message: t.message, at: Date.now() / 1000 });
        } else if (tick === 3) {
            t.status = "parsing";
            t.stage = "parsing";
            t.progress = 16;
            t.message = "展平 LaTeX 源码";
            emit(t, "stage", { stage: "parsing", progress: 16, message: t.message, at: Date.now() / 1000 });
            emit(t, "log", { line: "[parse] main.tex flattened: 24 chunks" });
        } else if (tick >= 4 && seq < TOTAL_CHUNKS) {
            if (t.status !== "translating") {
                t.status = "translating";
                t.stage = "translating";
                emit(t, "stage", { stage: "translating", progress: 26, message: "翻译中", at: Date.now() / 1000 });
            }
            const items = [];
            for (let k = 0; k < 2 && seq < TOTAL_CHUNKS; k++, seq++) {
                const r = Math.random();
                items.push({
                    seq,
                    status: r < 0.82 ? "ok" : r < 0.95 ? "fallback_orig" : "failed",
                    ...(r >= 0.82 && r < 0.95 ? { error_code: "placeholder_mismatch" } : {}),
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
                const w = WARN_POOL[Math.floor(Math.random() * WARN_POOL.length)];
                emit(t, "warning", w);
                t.warnings.push(`[${w.code}] ${w.message}`);
            }
        } else if (seq >= TOTAL_CHUNKS && compileTicks < 3) {
            compileTicks++;
            if (t.stage !== "compiling") {
                t.status = "compiling";
                t.stage = "compiling";
                t.progress = 92;
                emit(t, "stage", { stage: "compiling", progress: 92, message: "编译中文 PDF", at: Date.now() / 1000 });
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
                stats: { tokens: t.counters.tokens, seconds: Math.round(tick * 0.35), chunks_failed: t.counters.failed },
            });
            for (const res of t.listeners) res.end();
            t.listeners.clear();
        }
    }, 350);
}

// ---------- 静态 mock 数据 ----------

const EN_PAGES = 6;
const ZH_PAGES = 8;

const enPdf = miniPdf("TeXlate mock — ORIGINAL", Array.from({ length: EN_PAGES }, (_, i) => `EN page ${i + 1} / ${EN_PAGES} — lorem ipsum source text`));
const zhPdf = miniPdf("TeXlate mock — ZH (placeholder text)", Array.from({ length: ZH_PAGES }, (_, i) => `ZH page ${i + 1} / ${ZH_PAGES} — translated text goes here`));
const dualPdf = miniPdf("TeXlate mock — DUAL", Array.from({ length: ZH_PAGES }, (_, i) => `dual page ${i + 1} / ${ZH_PAGES}`));

const mockChunks = [
    { seq: 0, src_file: "main.tex", kind: "text", en: "# Abstract\n\nWe study the problem of *cross-lingual* document translation.\n\nThe loss is $L = \\sum_i \\ell_i$.", zh: "# 摘要\n\n我们研究**跨语言**文档翻译问题。\n\n损失函数为 $L = \\sum_i \\ell_i$。" },
    { seq: 1, src_file: "main.tex", kind: "text", en: "## 1. Introduction\n\nMachine translation of scientific documents remains challenging due to formulas like $$E = mc^2$$ and structural markup.", zh: "## 1. 引言\n\n科技文献的机器翻译因 $$E = mc^2$$ 这类公式与结构化标记而仍然困难。" },
    { seq: 2, src_file: "main.tex", kind: "text", en: "Our pipeline preserves *all* LaTeX commands during translation, then recompiles with `ctex`.", zh: "我们的管线在翻译过程中保留*全部* LaTeX 命令，随后用 `ctex` 重编译。" },
    { seq: 3, src_file: "main.tex", kind: "text", en: "## 2. Method\n\nSegment-level translation with a sliding context window of three paragraphs.", zh: "## 2. 方法\n\n段落级翻译，滑窗为三段的上下文窗口。" },
    { seq: 4, src_file: "main.tex", kind: "text", en: "Results show placeholder integrity of 99.6% across the corpus.", zh: "结果显示全语料占位符完整性达 99.6%。" },
    { seq: 5, src_file: "main.tex", kind: "text", en: "## 3. Conclusion\n\nThe reader presents original and translation side by side, scroll-synchronized.", zh: "## 3. 结论\n\n阅读器以同步滚动的双栏对照呈现原文与译文。" },
];

function mockDual(taskId: string) {
    return {
        version: 1,
        documents: {
            original: { version: `mock-en-${taskId}`, pages: EN_PAGES },
            translated: { version: `mock-zh-${taskId}`, pages: ZH_PAGES },
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
                translated: { page: Math.min(ZH_PAGES, Math.floor((i * ZH_PAGES) / EN_PAGES) + 1), fraction: 0 },
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
        documents: {
            original: {
                version: `mock-en-${task.id}`,
                pages: task.html ? mockChunks.length : EN_PAGES,
                url: `/api/files/${task.id}/en.pdf`,
            },
            translated: {
                version: `mock-zh-${task.id}`,
                pages: task.html ? mockChunks.length : ZH_PAGES,
                url: `/api/files/${task.id}/zh.pdf`,
            },
        },
        alignment: mockDual(task.id).alignment,
        reading: null,
    };
}

function seedTask(id: string, status: Status, opts?: Partial<MockTask>): MockTask {
    const t: MockTask = {
        id,
        kind: opts?.kind ?? "arxiv",
        status,
        progress: isDone({ status } as MockTask) ? 100 : 0,
        title: opts?.title,
        arxiv_id: opts?.arxiv_id,
        created_at: Date.now() / 1000 - 300,
        updated_at: Date.now() / 1000,
        counters: { total: TOTAL_CHUNKS, done: TOTAL_CHUNKS, cached: 4, failed: 1, tokens: 8123 },
        warnings: [],
        error: null,
        events: [],
        listeners: new Set(),
        ...opts,
    };
    tasks.set(id, t);
    return t;
}

seedTask("t_0000000000000a01", "done", { title: "Mock paper — PDF 对照演示", arxiv_id: "2501.14787" });
seedTask("t_0000000000000a02", "done", { title: "Mock paper — HTML 降级演示", arxiv_id: "2409.01234", html: true });
seedTask("t_0000000000000a03", "partial", { title: "Mock paper — 部分失败样例", arxiv_id: "2401.00001" });
seedTask("t_0000000000000a04", "fault", {
    title: "Mock paper — 编译失败样例",
    arxiv_id: "2407.05555",
    error: { code: "compile", message: "xelatex 编译失败(mock)", retryable: true },
    warnings: ["⟦MATH0007⟧ 占位符在译文中缺失，已回退原文"],
});
seedTask("t_0000000000000a05", "needs_auth", {
    title: "Mock paper — 需要 API Key",
    arxiv_id: "2406.99999",
    error: { code: "auth_required", message: "未配置 API Key(mock)", retryable: true },
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

function serveSse(req: Req, res: Res, task: MockTask) {
    res.writeHead(200, {
        "content-type": "text/event-stream",
        "cache-control": "no-store",
        connection: "keep-alive",
    });
    res.write(`id: 0\nevent: snapshot\ndata: ${JSON.stringify(snapshot(task))}\n\n`);
    const lastId = Number(req.headers["last-event-id"] ?? 0) || 0;
    for (const ev of task.events) {
        if (ev.seq > lastId) res.write(`id: ${ev.seq}\nevent: ${ev.type}\ndata: ${JSON.stringify(ev.data)}\n\n`);
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

const FILE_BODY: Record<string, (taskId: string) => { body: Buffer | string; type: string }> = {
    "en.pdf": () => ({ body: enPdf, type: "application/pdf" }),
    "zh.pdf": () => ({ body: zhPdf, type: "application/pdf" }),
    "dual.pdf": () => ({ body: dualPdf, type: "application/pdf" }),
    "dual.json": (id) => ({ body: JSON.stringify(mockDual(id)), type: "application/json" }),
    "compile.log": () => ({ body: "[mock] xelatex: no errors\n", type: "text/plain" }),
    "src.tar": () => ({ body: Buffer.from("mock tar\n"), type: "application/gzip" }),
    "zh-src.zip": () => ({ body: Buffer.from("PK\x05\x06" + "\0".repeat(18), "latin1"), type: "application/zip" }),
    md: () => ({ body: Buffer.from("PK\x05\x06" + "\0".repeat(18), "latin1"), type: "application/zip" }),
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
        // 对齐真后端 provider_presets：单数 model + base_url + key_env
        json(res, 200, {
            providers: [
                {
                    id: "gateway",
                    name: "Local Gateway",
                    base_url: "http://127.0.0.1:3003/v1",
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
            ],
        });
        return true;
    }
    if (req.method === "GET" && p === "/api/tasks") {
        // 对齐真后端：列表行不附 artifacts（懒拉 /api/files/{id} 补）
        const rows = [...tasks.values()].map((t) => {
            const s = snapshot(t);
            delete s.artifacts;
            return s;
        });
        json(res, 200, { tasks: rows });
        return true;
    }
    if ((mm = m(/^\/api\/arxiv\/([^/]+)\/translate$/)) && req.method === "POST") {
        const id = decodeURIComponent(mm[1]);
        const t = seedTask(mkId(), "queued", {
            title: `arXiv ${id}`,
            arxiv_id: id,
            counters: { total: 0, done: 0, cached: 0, failed: 0, tokens: 0 },
        });
        drive(t);
        json(res, 202, {
            task_id: t.id,
            status: "queued",
            cache: "miss",
            events_url: `/api/task/${t.id}`,
            reader_url: `/api/task/${t.id}/reader`,
        });
        return true;
    }
    if (req.method === "POST" && p === "/api/upload") {
        // 按扩展名演示 doc 管线（真后端走魔数嗅探，mock 只看文件名）
        let body = "";
        req.on("data", (c: Buffer) => (body += c.toString("latin1")));
        req.on("end", () => {
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
                counters: { total: 0, done: 0, cached: 0, failed: 0, tokens: 0 },
            });
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
    if ((mm = m(/^\/api\/task\/([^/]+)$/)) && req.method === "GET") {
        const t = tasks.get(mm[1]);
        if (!t) return notFound(res), true;
        const accept = req.headers.accept ?? "";
        if (accept.includes("text/event-stream")) serveSse(req, res, t);
        else json(res, 200, snapshot(t));
        return true;
    }
    if ((mm = m(/^\/api\/task\/([^/]+)$/)) && req.method === "DELETE") {
        const t = tasks.get(mm[1]);
        if (!t) return notFound(res), true;
        if (!TERMINAL.has(t.status)) {
            json(res, 409, { detail: "task is active; cancel first" });
            return true;
        }
        if (t.timer) clearInterval(t.timer);
        for (const l of t.listeners) l.end();
        tasks.delete(t.id);
        res.writeHead(204).end();
        return true;
    }
    if ((mm = m(/^\/api\/task\/([^/]+)\/cancel$/)) && req.method === "POST") {
        const t = tasks.get(mm[1]);
        if (!t) return notFound(res), true;
        if (t.timer) clearInterval(t.timer);
        t.status = "cancelled";
        emit(t, "done", { status: "cancelled", artifacts: {}, stats: {} });
        json(res, 200, { ok: true });
        return true;
    }
    if ((mm = m(/^\/api\/task\/([^/]+)\/retry$/)) && req.method === "POST") {
        const t = tasks.get(mm[1]);
        if (!t) return notFound(res), true;
        t.status = "queued";
        t.progress = 0;
        t.counters = { total: 0, done: 0, cached: 0, failed: 0, tokens: 0 };
        drive(t);
        json(res, 200, { ok: true });
        return true;
    }
    if ((mm = m(/^\/api\/task\/([^/]+)\/reader$/)) && req.method === "GET") {
        const t = tasks.get(mm[1]);
        if (!t) return notFound(res), true;
        // doc 任务无 dual.json——对齐真后端 404（"dual.json 未产出"）
        if (isDoc(t)) return notFound(res, "dual.json 未产出"), true;
        json(res, 200, mockReader(t));
        return true;
    }
    if (m(/^\/api\/task\/[^/]+\/reader\/position$/) && req.method === "PUT") {
        json(res, 200, { ok: true });
        return true;
    }
    if ((mm = m(/^\/api\/files\/([^/]+)$/)) && req.method === "GET") {
        const t = tasks.get(mm[1]);
        if (!t) return notFound(res), true;
        // manifest：db kind → {bytes, sha256, created_at, url}
        const arts: Record<
            string,
            { bytes: number; sha256: string; created_at: number; url: string }
        > = {};
        for (const [kind, url] of Object.entries(artifactsOf(t))) {
            arts[kind] = { bytes: 1024, sha256: "mock", created_at: t.updated_at, url };
        }
        json(res, 200, { artifacts: arts });
        return true;
    }
    if ((mm = m(/^\/api\/files\/([^/]+)\/(.+)$/)) && req.method === "GET") {
        const t = tasks.get(mm[1]);
        const kind = decodeURIComponent(mm[2]);
        const entry = FILE_BODY[kind];
        if (!t || !entry) return notFound(res), true;
        const { body, type } = entry(t.id);
        res.writeHead(200, { "content-type": type, "cache-control": "no-store" });
        res.end(body);
        return true;
    }
    if (p === "/api/settings" && req.method === "GET") {
        json(res, 200, {
            has_api_key: true,
            base_url: "http://127.0.0.1:3003/v1",
            model: "swe-2-medium",
            target_lang: "zh-CN",
            glossary: "",
        });
        return true;
    }
    if (p === "/api/settings" && req.method === "PUT") {
        let body = "";
        req.on("data", (c) => (body += c));
        req.on("end", () => json(res, 200, { ok: true, ...JSON.parse(body || "{}") }));
        return true;
    }
    if (p === "/api/settings/test" && req.method === "POST") {
        // 对齐真后端 {ok, models, model}，回显 body 里的 model
        let body = "";
        req.on("data", (c) => (body += c));
        req.on("end", () => {
            const b = JSON.parse(body || "{}") as { model?: string };
            json(res, 200, {
                ok: true,
                models: ["swe-2-medium", "deepseek-flash", "gpt-4o-mini"],
                model: b.model ?? "mock-model",
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
export function pdfjsAssetsMiddleware(pdfjsDir: string): Connect.NextHandleFunction {
    return (req, res, next) => {
        const mm = req.url?.match(/^\/pdfjs\/(cmaps|standard_fonts|wasm)\/(.+)$/);
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
