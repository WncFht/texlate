// copy-latex 实测：公式源卡（.latex-card）/ Alt+click 直复制 /
// 选区 → FloatBar「复制 LaTeX」→ POST /api/task/{id}/latex → toast。
// 活服 127.0.0.1:8765（须已 build-web.sh + 重启）+ 真实 done 任务 +
// registerCopyLatex 已挂 ReaderView（整合期 D）。
//
// 端点隔离：page.route 拦截 **/api/task/*/latex 回固定体——后端 lane 在
// 飞与否不影响本脚本（验的是前端链：选区→seqs→请求体→复制→toast）。
// 剪贴板：newContext permissions 授 clipboard-write；被拒走 execCommand
// 兜底臂，两路在真 chromium 下必居一。
//
// 覆盖矩阵（行为级断言）：
//   1. math-card   —— 点中 .pane-html-body 内 math/.katex → 卡出、
//                    .latex-src 非空、复制钮在；Esc 收卡；Alt+click 同元
//                    不开卡只出 toast（pdf-only 任务无 html 侧 → 记
//                    SKIP 不算 FAIL）；
//   2. sel-copy    —— 选区跨两块 → FloatBar 出 LaTeX 钮 → 点击 → 拦截
//                    到 seqs 非空 POST → .toast 出现；
//   3. zero-errors —— pageerror/console.error 清零。
// TASK 默认 t_d7c669e8b3c92149（eprint/pdf——只走 2/3）；html/dom 任务
// 经 TASK= 换入才覆盖 1。
// 用法: node scripts/copylatex_verify.mjs   (cwd=web/scripts)

import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const BASE = process.env.WEB_BASE ?? "http://127.0.0.1:8765";
const TASK = process.env.TASK ?? "t_d7c669e8b3c92149";
const root = join(homedir(), ".cache/ms-playwright");
const EXE =
    process.env.PW_EXE ??
    join(
        root,
        readdirSync(root)
            .filter((x) => x.startsWith("chromium-"))
            .sort()
            .reverse()[0],
        "chrome-linux64/chrome",
    );
if (!existsSync(EXE)) throw new Error(`no chromium at ${EXE}`);

const SHOTS = new URL("./shots/", import.meta.url).pathname;
mkdirSync(SHOTS, { recursive: true });
const PW_TMP = join(homedir(), ".cache/pw-tmp");
mkdirSync(PW_TMP, { recursive: true });

const results = [];
const check = (name, ok, detail = "") => {
    results.push({ name, ok, detail });
    console.log(
        `${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`,
    );
};
const info = (s) => console.log(`INFO  ${s}`);

// 浮条钮名：i18n 键未落地前标签可能是 menu.sel.copyTex 原文——三形态全收
const LATEX_BTN = /latex|tex|menu\.sel\.copytex/i;
const TOAST_OK = /复制|copied|latex|字符/i;

/** pane 内文本宿主：dom/html → .pane-html-body；pdf → .textLayer */
const HOST = (side) =>
    `.pane[data-side="${side}"] .pane-html-body, .pane[data-side="${side}"] .textLayer`;

async function run() {
    const errors = [];
    const browser = await chromium.launch({
        executablePath: EXE,
        args: ["--disable-gpu", "--disable-dev-shm-usage"],
        env: { ...process.env, TMPDIR: PW_TMP },
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

    // ---- 端点 mock：回包记录请求体，latex 体固定可断言 -------------------
    let latexReq = null;
    await page.route("**/api/task/*/latex", async (route) => {
        try {
            latexReq = JSON.parse(route.request().postData() || "{}");
        } catch {
            latexReq = {};
        }
        await route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({
                latex: "\\alpha+\\beta=\\gamma",
                chunks: latexReq?.seqs?.length ?? 1,
                files: ["main.tex"],
                mode_used: latexReq?.mode ?? "sent",
            }),
        });
    });

    try {
        await page.goto(`${BASE}/#/reader/${TASK}`, {
            waitUntil: "domcontentloaded",
        });
        await page.waitForSelector(HOST("original"), { timeout: 30000 });
        await page.waitForTimeout(2500);
        bail();

        const htmlHost = page.locator(
            '.pane[data-side="original"] .pane-html-body',
        );
        const hasHtml = (await htmlHost.count()) > 0;
        const bar = page.locator(".floatbar");
        const card = page.locator(".latex-card");
        const toastBox = page.locator(".toast");

        // ---- 1. 公式源卡（html/dom 侧才考） -------------------------------
        const mathSel =
            '.pane[data-side="original"] .pane-html-body math[alttext], ' +
            '.pane[data-side="original"] .pane-html-body .katex, ' +
            '.pane[data-side="original"] .pane-html-body math';
        const mathEl = page.locator(mathSel).first();
        const hasMath = (await mathEl.count()) > 0;
        if (!hasHtml || !hasMath) {
            info("no html-side math host — card checks skipped (pdf-only task)");
        } else {
            await mathEl.scrollIntoViewIfNeeded().catch(() => {});
            await page.waitForTimeout(300);
            await mathEl.click();
            await page.waitForTimeout(400);
            const cardVisible = await card.isVisible().catch(() => false);
            check("click math opens latex card", cardVisible);
            if (cardVisible) {
                const src = (
                    await card.locator(".latex-src").textContent()
                ).trim();
                check("card has tex source", src.length > 0, `${src.length} chars`);
                check(
                    "card has copy button",
                    await card.locator(".latex-copy").isVisible().catch(() => false),
                );
                await page
                    .screenshot({ path: join(SHOTS, "latex-card.png") })
                    .catch(() => {});
                await card.locator(".latex-copy").click();
                await page.waitForTimeout(500);
                check(
                    "card copy fires toast",
                    await toastBox
                        .filter({ hasText: TOAST_OK })
                        .first()
                        .isVisible()
                        .catch(() => false),
                );
            }
            await page.keyboard.press("Escape");
            await page.waitForTimeout(300);
            check(
                "Esc closes latex card",
                !(await card.isVisible().catch(() => false)),
            );

            // Alt+click：跳过卡直复制 + toast
            await mathEl.click({ modifiers: ["Alt"] });
            await page.waitForTimeout(500);
            check(
                "alt+click skips card",
                !(await card.isVisible().catch(() => false)),
            );
            check(
                "alt+click copies (toast)",
                await toastBox
                    .filter({ hasText: TOAST_OK })
                    .first()
                    .isVisible()
                    .catch(() => false),
            );
        }

        // ---- 2. 选区 → FloatBar LaTeX 钮 → POST --------------------------
        // 选区跨两个顶层 [data-chunk]（html）或两个 textLayer span（pdf）
        latexReq = null;
        const selOk = await page.evaluate(() => {
            const pick = (root, sel, minLen) =>
                [...root.querySelectorAll(sel)].filter(
                    (e) => (e.textContent || "").trim().length >= minLen,
                );
            const firstText = (el) => {
                const w = el.ownerDocument.createTreeWalker(
                    el,
                    NodeFilter.SHOW_TEXT,
                );
                let n;
                while ((n = w.nextNode()))
                    if (n.textContent.trim()) return n;
                return null;
            };
            const html = document.querySelector(
                '.pane[data-side="original"] .pane-html-body',
            );
            if (html) {
                const chunks = pick(html, "[data-chunk]", 40).filter(
                    (c) => !c.parentElement.closest("[data-chunk]"),
                );
                if (chunks.length < 2) return false;
                const n1 = firstText(chunks[0]);
                const n2 = firstText(chunks[1]);
                if (!n1 || !n2) return false;
                getSelection().setBaseAndExtent(
                    n1,
                    0,
                    n2,
                    Math.min(20, n2.textContent.length),
                );
                return getSelection().toString().length > 10;
            }
            const tl = document.querySelector(
                '.pane[data-side="original"] .textLayer',
            );
            if (!tl) return false;
            const spans = pick(tl, "span", 6);
            if (spans.length < 6) return false;
            const a = spans[0].firstChild;
            const b = spans[Math.min(5, spans.length - 1)].firstChild;
            if (!a || !b) return false;
            getSelection().setBaseAndExtent(
                a,
                0,
                b,
                Math.min(10, b.textContent.length),
            );
            return getSelection().toString().length > 4;
        });
        check("cross-chunk selection made", selOk);
        if (selOk) {
            await page.waitForTimeout(400); // release + rAF + flattenCtx
            const barVisible = await bar.isVisible().catch(() => false);
            check("floatbar shows on selection", barVisible);
            if (barVisible) {
                const btn = bar
                    .locator("button")
                    .filter({ hasText: LATEX_BTN })
                    .first();
                const btnOk = await btn.isVisible().catch(() => false);
                check("floatbar has copy-latex button", btnOk);
                if (btnOk) {
                    await btn.click();
                    await page.waitForTimeout(700);
                    check(
                        "POST /latex fired with seqs",
                        !!latexReq && Array.isArray(latexReq.seqs) && latexReq.seqs.length > 0,
                        latexReq ? `seqs=${JSON.stringify(latexReq.seqs)} mode=${latexReq.mode}` : "no request",
                    );
                    check(
                        "sel copy fires toast",
                        await toastBox
                            .filter({ hasText: TOAST_OK })
                            .first()
                            .isVisible()
                            .catch(() => false),
                    );
                }
            }
        }

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
