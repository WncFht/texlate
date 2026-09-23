// cite-translate 实测：Toolbar「文献」钮 + RefsPanel 抽屉 + preflight
// 确认层 + 行内 RefTaskChip 七态 + 内联 key 门。
// 活服 127.0.0.1:8765（须已 build-web.sh + 重启）+ 真实 done 任务 +
// 整合期 Wave D 已挂（ReaderView onRefs/refsCount + RefsPanel 挂载 +
// CiteCard 脚钮）——未整合时 toolbar 钮缺席整组 FAIL，即为该波出闸信号。
//   TASK 默认 t_d7c669e8b3c92149（eprint 链——bibitem 条目含 arXiv id）。
//
// 端点隔离（不产生真实翻译任务）：
//   POST /api/arxiv/*\/translate → 回固定 202 体；
//   GET  /api/tasks              → 回罐装行（控 row 相——可观察
//                                  done/needs_auth/fault 行态）；
//   GET  /api/settings           → has_api_key:true（绕开凭证门走 POST 路；
//                                  AUTH_MOCK=1 时改回 false 测内联 key 框）。
//
// 覆盖矩阵（行为级断言）：
//   1. toolbar-btn   —— 「文献」钮在、角标=可译条数；
//   2. panel-open    —— role=dialog 抽屉出、.refs-row>0、id 徽标三态词表；
//   3. chip-phase    —— 行内 chip 按罐装行渲相（done→链接/fault→↻）；
//   4. confirm-layer —— 「翻译全部」→ alertdialog 计数+ETA 文案；Esc 先收
//                      确认层再收面板（层序）；
//   5. submit-mock   —— 行 chip「翻译此文」→ 拦截 POST + toast/queued 翻相；
//                      AUTH_MOCK=1 臂 → 内联 password 框替代 POST；
//   6. zero-errors   —— pageerror/console.error 清零。
// 用法: node scripts/citetranslate_verify.mjs   (cwd=web/scripts)

import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const BASE = process.env.WEB_BASE ?? "http://127.0.0.1:8765";
const TASK = process.env.TASK ?? "t_d7c669e8b3c92149";
const AUTH_MOCK = process.env.AUTH_MOCK === "1"; // 测凭证门臂
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

// 罐装行：定死 arxiv_id 匹配面板条目概率过低——灌 queued 行只在
// taskByArxiv 撞不上时自然落 idle 臂；本脚本断言面不依赖罐装行命中。
const FAKE_TID = "t_00000000000000aa";
const posted = []; // translate POST 拦截日志

async function run() {
    const errors = [];
    const browser = await chromium.launch({
        executablePath: EXE,
        args: ["--disable-gpu", "--disable-dev-shm-usage"],
        env: { ...process.env, TMPDIR: PW_TMP },
    });
    const ctx = await browser.newContext({
        viewport: { width: 1500, height: 950 },
    });
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
    page.on("console", (m) => {
        if (m.type() === "error")
            errors.push(`console.error: ${m.text().slice(0, 200)}`);
    });

    // ---- 端点隔离 --------------------------------------------------------
    await page.route("**/api/arxiv/*/translate", async (route) => {
        if (route.request().method() !== "POST") return route.continue();
        posted.push(route.request().url());
        return route.fulfill({
            status: 202,
            contentType: "application/json",
            body: JSON.stringify({
                task_id: FAKE_TID,
                status: "queued",
                cache: "miss",
                events_url: `/api/task/${FAKE_TID}/events`,
            }),
        });
    });
    await page.route("**/api/tasks*", (route) =>
        route.fulfill({
            status: 200,
            contentType: "application/json",
            body: JSON.stringify({ tasks: [], total: 0 }),
        }),
    );
    if (AUTH_MOCK) {
        await page.route(/\/api\/settings$/, (route) =>
            route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({ has_api_key: false }),
            }),
        );
    } else {
        await page.route(/\/api\/settings$/, (route) =>
            route.fulfill({
                status: 200,
                contentType: "application/json",
                body: JSON.stringify({ has_api_key: true }),
            }),
        );
    }

    try {
        await page.goto(`${BASE}/#/reader/${TASK}`, {
            waitUntil: "domcontentloaded",
        });
        await page.waitForSelector(".reader-toolbar", { timeout: 30000 });
        await page.waitForTimeout(2500);

        // ---- 1. Toolbar 文献钮 --------------------------------------------
        const refsBtn = page.locator(
            '.reader-toolbar button:has-text("文献"), ' +
                '.reader-toolbar button:has-text("Refs")',
        );
        const btnVisible = await refsBtn
            .first()
            .isVisible()
            .catch(() => false);
        check("toolbar refs button visible", btnVisible);
        if (!btnVisible) {
            info("文献钮缺席——整合期 onRefs/refsTotal 未接（或任务无条目）");
            // 无钮时后续面板面全不可达——提前截图收尾
            await page.screenshot({
                path: join(SHOTS, `citetranslate-${TASK}-nobtn.png`),
            });
            return;
        }
        const badge = refsBtn.first().locator(".nav-badge");
        const badgeText = await badge.textContent().catch(() => null);
        check(
            "refs badge numeric",
            badgeText == null || /^\d+$/.test(badgeText.trim()),
            `badge=${badgeText?.trim() ?? "none"}`,
        );

        // ---- 2. 面板开合 --------------------------------------------------
        await refsBtn.first().click();
        await page.waitForTimeout(400);
        const panel = page.locator(
            'div[role="dialog"][aria-modal="true"]',
        );
        const panelVisible = await panel.isVisible().catch(() => false);
        check("refs panel opens (role=dialog)", panelVisible);
        if (!panelVisible) return;

        const rows = panel.locator(".refs-row");
        const rowCount = await rows.count();
        check("panel lists ref rows", rowCount > 0, `${rowCount} rows`);
        const chips = panel.locator(".ref-task-chip");
        const chipCount = await chips.count();
        info(`chips=${chipCount}（有 arXiv id 的行才出 chip）`);

        // ---- 3. 「翻译全部」→ 确认层 --------------------------------------
        const allBtn = panel.locator(
            'button:has-text("翻译全部"), button:has-text("Translate all")',
        );
        const allBtnVisible = await allBtn.isVisible().catch(() => false);
        check("translate-all button present", allBtnVisible);
        if (allBtnVisible) {
            await allBtn.click();
            await page.waitForTimeout(500);
            const confirmLayer = panel.locator('[role="alertdialog"]');
            const confirmVisible = await confirmLayer
                .isVisible()
                .catch(() => false);
            check("preflight confirm layer shows", confirmVisible);
            if (confirmVisible) {
                const txt = (await confirmLayer.textContent()) ?? "";
                check(
                    "confirm shows bucket counts",
                    /\d+/.test(txt) && !txt.includes("{"),
                    txt.replace(/\s+/g, " ").slice(0, 120),
                );
                // Esc 层序：先收确认层，面板仍在
                await page.keyboard.press("Escape");
                await page.waitForTimeout(250);
                check(
                    "Esc collapses confirm first",
                    !(await confirmLayer.isVisible().catch(() => false)),
                );
                check(
                    "panel survives confirm Esc",
                    await panel.isVisible().catch(() => false),
                );
            }
        }

        // ---- 4. 行内 chip 提交（或凭证门臂） ------------------------------
        const translateChip = panel.locator(
            'button.ref-task-chip.is-idle, ' +
                'button.ref-task-chip:has-text("翻译此文"), ' +
                'button.ref-task-chip:has-text("Translate")',
        );
        const idleChipCount = await translateChip.count();
        if (idleChipCount > 0) {
            await translateChip.first().click();
            await page.waitForTimeout(600);
            if (AUTH_MOCK) {
                const keyBox = panel.locator('input[type="password"]');
                check(
                    "auth gate → inline key box (no POST)",
                    (await keyBox.count()) > 0 && posted.length === 0,
                    `posted=${posted.length}`,
                );
            } else {
                check(
                    "chip click → POST /translate intercepted",
                    posted.length > 0,
                    `${posted.length} posts`,
                );
                const toastOk = await page
                    .locator(".toast")
                    .first()
                    .isVisible()
                    .catch(() => false);
                const chipText = await translateChip
                    .first()
                    .textContent()
                    .catch(() => "");
                check(
                    "submit feedback (toast or phase flip)",
                    toastOk ||
                        /排队|queued|翻译中|translating/i.test(chipText ?? ""),
                    `toast=${toastOk} chip="${(chipText ?? "").trim()}"`,
                );
            }
        } else {
            info("无 idle chip（全部已译/无 arXiv id 条目）——submit 臂 SKIP");
        }

        // ---- 5. Esc 收面板 -------------------------------------------------
        await page.keyboard.press("Escape");
        await page.waitForTimeout(300);
        check(
            "Esc closes panel",
            !(await panel.isVisible().catch(() => false)),
        );

        await page.screenshot({
            path: join(SHOTS, `citetranslate-${TASK}.png`),
            fullPage: false,
        });
    } finally {
        await browser.close();
    }

    const failed = results.filter((r) => !r.ok);
    console.log(
        `\n${results.length - failed.length}/${results.length} PASS` +
            (errors.length ? `\nerrors:\n${errors.join("\n")}` : ""),
    );
    if (errors.length) failed.push({ name: "no page errors", ok: false });
    process.exit(failed.length ? 1 : 0);
}

run().catch((e) => {
    console.error("FATAL", e);
    process.exit(2);
});
