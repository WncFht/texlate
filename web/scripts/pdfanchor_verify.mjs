// pdf seq 锚（B 路 marked-content）端到端实测：
//   textLayer span.markedContent[id$="_mc<N>"] → 选区 → FloatBar「复制 LaTeX」
//   → POST /api/task/{id}/latex 请求体 seqs 断言。
//
// 两臂：
//   mock 臂（缺省）：page.route 全拦 t_mockseq 任务面 + 手工构造的 marked pdf
//     （两枚 /TLXC <</MCID 5000x>> BDC 锚 + 裸段），不依赖真任务/xelatex；
//   真任务臂（TASK=<id>）：活服任务厚臂——锚数、选区 seqs 同样断言；
//     老任务无锚时记 INFO 降级为 C 路模糊断言（选区 → seqs 非空即可）。
//
// 端点隔离：**/api/task/*/latex 拦截回包（验前端链：选区→seqs→请求体）。
// 活服 127.0.0.1:8765（须已 build-web.sh）——SPA 壳与静态资源走真服。
// 用法: node scripts/pdfanchor_verify.mjs        (cwd=web/scripts)
//       TASK=t_xxx node scripts/pdfanchor_verify.mjs

import { join } from "node:path";
import { check, info, launch, results, SHOTS } from "./lib/pwkit.mjs";

const BASE = process.env.WEB_BASE ?? "http://127.0.0.1:8765";
const TASK = process.env.TASK ?? "";
const MOCK_ID = "t_mockseq001";

// ---------------------------------------------------------------- marked pdf
// 手工构造最小合法 PDF：一页 Helvetica 三行——前两行各包一枚
// /TLXC <</MCID 5000x>> BDC…EMC marked-content 区（pdf.js textLayer 产
// span.markedContent[id$="_mc5000x"]），第三行裸段作锚外对照。
function buildMarkedPdf() {
    const content = [
        "q",
        "/TLXC <</MCID 50000>> BDC",
        "BT /F1 24 Tf 72 720 Td (Translated paragraph one.) Tj ET",
        "EMC",
        "/TLXC <</MCID 50001>> BDC",
        "BT /F1 24 Tf 72 640 Td (Translated paragraph two.) Tj ET",
        "EMC",
        "BT /F1 24 Tf 72 560 Td (Third plain paragraph tail.) Tj ET",
        "Q",
    ].join("\n");
    const objs = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792]" +
            " /Contents 4 0 R /Resources << /Font << /F1 5 0 R >>" +
            " /ProcSet [/PDF /Text] >> >>",
        `<< /Length ${content.length} >>\nstream\n${content}\nendstream`,
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ];
    let out = "%PDF-1.4\n";
    const offsets = [0];
    objs.forEach((body, i) => {
        offsets.push(out.length);
        out += `${i + 1} 0 obj\n${body}\nendobj\n`;
    });
    const xrefAt = out.length;
    out += `xref\n0 ${objs.length + 1}\n`;
    out += "0000000000 65535 f \n";
    for (let i = 1; i <= objs.length; i++)
        out += `${String(offsets[i]).padStart(10, "0")} 00000 n \n`;
    out +=
        `trailer\n<< /Size ${objs.length + 1} /Root 1 0 R >>\n` +
        `startxref\n${xrefAt}\n%%EOF\n`;
    return Buffer.from(out, "latin1");
}

const json = (body, status = 200) => ({
    status,
    contentType: "application/json",
    body: JSON.stringify(body),
});

/** mock 臂全量路由——任务面 5 端点 + marked pdf + latex 捕获。 */
async function routeMock(page, pdf, cap) {
    const J = (body) => (route) => route.fulfill(json(body));
    await page.route(`**/api/task/${MOCK_ID}`, (route) => {
        if (route.request().method() !== "GET") return route.continue();
        return route.fulfill(
            json({
                task_id: MOCK_ID,
                kind: "arxiv",
                status: "done",
                progress: 100,
                created_at: 1,
                updated_at: 1,
                target_lang: "zh-CN",
                model: "mock",
            }),
        );
    });
    await page.route(`**/api/files/${MOCK_ID}`, J({ artifacts: {} }));
    await page.route(
        `**/api/files/${MOCK_ID}/dual.json**`,
        J({
            version: 1,
            documents: {
                original: { version: "v1", pages: 1 },
                translated: { version: "v1", pages: 1 },
            },
            chunks: [
                {
                    seq: 0,
                    en: "Translated paragraph one.",
                    zh: "第一段译文。",
                    kind: "text",
                },
                {
                    seq: 1,
                    en: "Translated paragraph two.",
                    zh: "第二段译文。",
                    kind: "text",
                },
                {
                    seq: 2,
                    en: "Third plain paragraph tail.",
                    zh: "第三段裸文。",
                    kind: "text",
                },
            ],
        }),
    );
    await page.route(`**/api/task/${MOCK_ID}/reader`, (route) => {
        if (route.request().method() !== "GET") return route.continue();
        return route.fulfill(
            json({
                view: "pdf",
                documents: {
                    original: {
                        version: "v1",
                        pages: 1,
                        url: "/mock-anchor.pdf",
                    },
                    translated: {
                        version: "v1",
                        pages: 1,
                        url: "/mock-anchor.pdf",
                    },
                },
                reading: null,
            }),
        );
    });
    await page.route(`**/api/task/${MOCK_ID}/reader/position`, (route) =>
        route.fulfill({ status: 200, body: "{}" }),
    );
    await page.route(`**/api/task/${MOCK_ID}/refs/kept`, J({ kept: {} }));
    await page.route("**/mock-anchor.pdf", (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/pdf",
            body: pdf,
        }),
    );
    await page.route("**/api/task/*/latex", async (route) => {
        try {
            cap.req = JSON.parse(route.request().postData() || "{}");
        } catch {
            cap.req = {};
        }
        await route.fulfill(
            json({
                latex: "% captured",
                chunks: cap.req?.seqs?.length ?? 1,
                files: ["main.tex"],
                mode_used: cap.req?.mode ?? "whole",
            }),
        );
    });
}

// -------------------------------------------------------------- 选择工具

/** 在 side 侧 textLayer 内造选区（evaluate 单参形：四元组解构）。
 * markedContent 锚内可能嵌套子 span——两端一律落到 Text 节点防 element
 * offset 语义炸 IndexSizeError。 */
const selectIn = ([side, spanSel, fromIdx, toIdx]) => {
    const tl = document.querySelector(`.pane[data-side="${side}"] .textLayer`);
    if (!tl) return false;
    const spans = [...tl.querySelectorAll(spanSel)].filter((e) =>
        (e.textContent || "").trim(),
    );
    if (spans.length <= Math.max(fromIdx, toIdx)) return false;
    const texts = (el) => {
        const w = el.ownerDocument.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        const ts = [];
        for (let n = w.nextNode(); n; n = w.nextNode())
            if (n.textContent.trim()) ts.push(n);
        return ts;
    };
    const a = texts(spans[fromIdx])[0];
    const bs = texts(spans[toIdx]);
    const b = bs[bs.length - 1];
    if (!a || !b) return false;
    getSelection().setBaseAndExtent(
        a,
        0,
        b,
        Math.min(12, b.textContent.length),
    );
    return getSelection().toString().trim().length > 0;
};

const LATEX_BTN = /latex|tex|menu\.sel\.copytex/i;

async function run() {
    const errors = [];
    const browser = await launch({
        args: ["--disable-gpu", "--disable-dev-shm-usage"],
        tmp: true,
    });
    const ctx = await browser.newContext({
        viewport: { width: 1500, height: 950 },
        permissions: ["clipboard-read", "clipboard-write"],
    });
    const page = await ctx.newPage();
    let crashed = false;
    page.on("crash", () => {
        crashed = true;
        console.log("!! renderer crashed — will retry");
    });
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
    page.on("console", (m) => {
        if (m.type() === "error")
            errors.push(`console.error: ${m.text().slice(0, 200)}`);
    });
    const bail = () => {
        if (crashed) throw new Error("renderer crashed");
    };

    const cap = { req: null };
    const mockMode = !TASK;
    if (mockMode) {
        await routeMock(page, buildMarkedPdf(), cap);
    } else {
        await page.route("**/api/task/*/latex", async (route) => {
            try {
                cap.req = JSON.parse(route.request().postData() || "{}");
            } catch {
                cap.req = {};
            }
            await route.fulfill(
                json({
                    latex: "% captured",
                    chunks: cap.req?.seqs?.length ?? 1,
                    files: ["main.tex"],
                    mode_used: cap.req?.mode ?? "whole",
                }),
            );
        });
    }

    /** FloatBar LaTeX 钮点击 → 捕获 seqs。 */
    const fireCopy = async () => {
        cap.req = null;
        const bar = page.locator(".floatbar");
        if (!(await bar.isVisible().catch(() => false))) return null;
        const btn = bar
            .locator("button")
            .filter({ hasText: LATEX_BTN })
            .first();
        if (!(await btn.isVisible().catch(() => false))) return null;
        await btn.click();
        await page.waitForTimeout(700);
        return cap.req;
    };

    try {
        await page.goto(`${BASE}/#/reader/${mockMode ? MOCK_ID : TASK}`, {
            waitUntil: "domcontentloaded",
        });
        await page.waitForSelector('.pane[data-side="translated"] .textLayer', {
            timeout: 30000,
        });
        await page.waitForTimeout(2000);
        bail();

        // ---- 1. 锚面：span.markedContent 计数 + id 形态 --------------------
        const markInfo = await page.evaluate(() => {
            const out = {};
            for (const side of ["original", "translated"]) {
                const spans = [
                    ...document.querySelectorAll(
                        `.pane[data-side="${side}"] span.markedContent[id]`,
                    ),
                ];
                out[side] = spans.map((s) => s.id);
            }
            return out;
        });
        info(`markedContent ids: ${JSON.stringify(markInfo)}`);
        const zhIds = markInfo.translated ?? [];
        if (mockMode) {
            check(
                "mock: translated pane has 2 marked spans",
                zhIds.length === 2,
                `${zhIds.length}`,
            );
            check(
                "mock: ids carry _mc5000{0,1} tail",
                zhIds.some((id) => /_mc50000$/.test(id)) &&
                    zhIds.some((id) => /_mc50001$/.test(id)),
                zhIds.join(","),
            );
        } else {
            check(
                "real: marked span count >= 0 (info only)",
                true,
                `${zhIds.length} anchors`,
            );
            if (!zhIds.length)
                info("task has no seq marks — C 路模糊断言 only");
        }

        // ---- 2. 选区→seqs --------------------------------------------------
        // 期望 seq 从实得锚 id 反推（_mc{50000+seq}）——真任务标记稀疏
        // （seq1 未注锚时两片是 [0,2]），硬编码 [0,1] 只适用密标 mock
        const seqOf = (id) => Number(/_mc(\d+)$/.exec(id)?.[1]) - 50000;
        const marked = zhIds.length;
        if (marked >= 1) {
            const want1 = seqOf(zhIds[0]);
            // 2a. 圈第一枚锚内文 → seqs=[其锚 seq]
            const ok1 = await page.evaluate(selectIn, [
                "translated",
                "span.markedContent",
                0,
                0,
            ]);
            check("select inside first marked span", ok1);
            if (ok1) {
                await page.waitForTimeout(450);
                const r1 = await fireCopy();
                check(
                    `seqs for first anchor == [${want1}]`,
                    !!r1 &&
                        Array.isArray(r1.seqs) &&
                        r1.seqs.length === 1 &&
                        r1.seqs[0] === want1,
                    r1 ? `seqs=${JSON.stringify(r1.seqs)}` : "no request",
                );
            }
        }
        if (marked >= 2) {
            const want2 = [seqOf(zhIds[0]), seqOf(zhIds[1])];
            // 2b. 跨两枚锚 → seqs=两锚 seq 对
            const ok2 = await page.evaluate(selectIn, [
                "translated",
                "span.markedContent",
                0,
                1,
            ]);
            check("select across two marked spans", ok2);
            if (ok2) {
                await page.waitForTimeout(450);
                const r2 = await fireCopy();
                check(
                    `seqs across anchors == [${want2}]`,
                    !!r2 &&
                        Array.isArray(r2.seqs) &&
                        r2.seqs.length === 2 &&
                        r2.seqs[0] === want2[0] &&
                        r2.seqs[1] === want2[1],
                    r2 ? `seqs=${JSON.stringify(r2.seqs)}` : "no request",
                );
            }
        }
        if (!marked) {
            // C 路兜底臂：任意文本选区 → seqs 非空（真任务老产物）
            const ok3 = await page.evaluate(selectIn, [
                "translated",
                "span",
                0,
                4,
            ]);
            check("plain textLayer selection made", ok3);
            if (ok3) {
                await page.waitForTimeout(450);
                const r3 = await fireCopy();
                check(
                    "fuzzy seqs non-empty",
                    !!r3 && Array.isArray(r3.seqs) && r3.seqs.length > 0,
                    r3 ? `seqs=${JSON.stringify(r3.seqs)}` : "no request",
                );
            }
        }

        await page
            .screenshot({ path: join(SHOTS, "pdfanchor.png") })
            .catch(() => {});
        bail();
        check(
            "zero console/page errors",
            errors.length === 0,
            errors.slice(0, 3).join(" | "),
        );
    } finally {
        await browser.close().catch(() => {});
    }
}

for (let attempt = 1; attempt <= 3; attempt++) {
    try {
        await run();
        break;
    } catch (e) {
        console.log(`attempt ${attempt} aborted: ${e.message}`);
        if (attempt === 3)
            check("run completes without crash", false, e.message);
    }
}

const fails = results.filter((r) => !r.ok);
console.log(
    `\n${results.length - fails.length}/${results.length} passed` +
        (fails.length
            ? ` — FAILED: ${fails.map((f) => f.name).join(", ")}`
            : ""),
);
process.exit(fails.length ? 1 : 0);
