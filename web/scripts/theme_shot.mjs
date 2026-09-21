// 主题快切 + 暗色 PDF 反色截图验证（mock 后端，vite dev 已跑在 ::1:5199）
// 用法:node scripts/theme_shot.mjs;产物 scripts/shots/theme-*.png

import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const BASE = process.env.WEB_BASE ?? "http://[::1]:5199";
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

const browser = await chromium.launch({ executablePath: EXE });

async function shot(url, theme, name, waitMs = 1200) {
    const ctx = await browser.newContext({
        viewport: { width: 1400, height: 900 },
    });
    await ctx.addInitScript(
        (t) => localStorage.setItem("texlate-theme", t),
        theme,
    );
    const page = await ctx.newPage();
    await page.goto(`${BASE}${url}`, { waitUntil: "domcontentloaded" });
    await page
        .waitForSelector(".pdfSlickViewer .page canvas", { timeout: 15000 })
        .catch(() => {});
    await page.waitForTimeout(waitMs);
    await page.screenshot({ path: join(SHOTS, name) });
    await ctx.close();
    console.log("shot", name);
}

// dev server 跑在真后端模式——用真实 done 任务验证
const TASK = process.env.TASK ?? "t_d7c669e8b3c92149";

await shot("/#/", "dark", "theme-dark-home.png");
await shot("/#/settings", "auto", "theme-auto-settings.png");
await shot(`/#/reader/${TASK}`, "dark", "theme-dark-reader.png", 5000);
await shot(`/#/reader/${TASK}`, "light", "theme-light-reader.png", 5000);

// 切换行为:默认 auto,连点应循环 auto→light→dark→auto
{
    const ctx = await browser.newContext({
        viewport: { width: 1200, height: 800 },
    });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/#/`, { waitUntil: "domcontentloaded" });
    await page.waitForTimeout(800);
    const seq = [];
    for (let i = 0; i <= 3; i++) {
        seq.push(
            await page.evaluate(
                () =>
                    `${document.documentElement.dataset.theme}|${localStorage.getItem("texlate-theme")}`,
            ),
        );
        if (i < 3) {
            await page.click(".theme-toggle");
            await page.waitForTimeout(400);
        }
    }
    console.log("cycle:", JSON.stringify(seq));
    // 阅读器工具栏里的同款钮
    await page.goto(`${BASE}/#/reader/${TASK}`, {
        waitUntil: "domcontentloaded",
    });
    await page.waitForTimeout(3000);
    const tbBtns = await page.evaluate(() =>
        [...document.querySelectorAll(".reader-toolbar button")]
            .map((b) => b.getAttribute("aria-label") || b.textContent.trim())
            .filter(Boolean)
            .slice(0, 20),
    );
    console.log("toolbar-btns:", JSON.stringify(tbBtns));
    await ctx.close();
}

await browser.close();
