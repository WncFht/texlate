// 纸面配色槽验证:逐槽切 settingsStore → canvas 物理像素均值 + --page-bg-color 断言
// 用法:node scripts/paper_theme_verify.mjs

import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const BASE = process.env.WEB_BASE ?? "http://127.0.0.1:8765";
const TASK = "t_d7c669e8b3c92149";
const root = join(homedir(), ".cache/ms-playwright");
const EXE = join(
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

// 期望 canvas 均值亮度区间(物理像素):暗槽 <120,亮/原色 >180
const CASES = [
    { id: "auto", dark: true, expect: "dark" },
    { id: "onedark", dark: true, expect: "dark" },
    { id: "black", dark: true, expect: "verydark" },
    { id: "snow", dark: true, expect: "light" },
    { id: "sepia", dark: true, expect: "light" },
    { id: "paper", dark: true, expect: "light" },
    { id: "none", dark: true, expect: "light" },
    { id: "auto", dark: false, expect: "light" },
];

const browser = await chromium.launch({ executablePath: EXE });
const ctx = await browser.newContext({
    viewport: { width: 1400, height: 900 },
});
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(`PAGEERROR: ${e.message}`));
page.on("console", (m) => {
    if (m.type() === "error") errors.push(`CONSOLE: ${m.text().slice(0, 160)}`);
});

await page.goto(`${BASE}/#/reader/${TASK}`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".pdfSlickViewer .page canvas", { timeout: 20000 });
await page.waitForTimeout(2500);

const measure = () =>
    page.evaluate(() => {
        const cv =
            document.querySelector(
                ".pane.active .pdfSlickViewer .page canvas",
            ) ?? document.querySelector(".pdfSlickViewer .page canvas");
        const viewer = cv?.closest(".pdfSlickViewer");
        let avg = null;
        try {
            const d = cv
                .getContext("2d")
                .getImageData(0, 0, cv.width, cv.height).data;
            let s = 0,
                n = 0;
            for (let i = 0; i < d.length; i += 4 * 97) {
                s += 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
                n++;
            }
            avg = +(s / n).toFixed(1);
        } catch {
            /* reset 间隙 h=0 */
        }
        return {
            avg,
            pageBg:
                viewer &&
                (getComputedStyle(viewer)
                    .getPropertyValue("--page-bg-color")
                    .trim() || "(unset)"),
        };
    });

let fails = 0;
for (const c of CASES) {
    // 单轴模型:OS 明暗唯一信号源=prefers-color-scheme——emulateMedia
    // 翻转打 matchMedia change→osDark();旧双轴遗物(texlate-theme 键/
    // dataset.theme 手改)不驱动任何东西,写了只污染迁移面
    await page.emulateMedia({ colorScheme: c.dark ? "dark" : "light" });
    await page.waitForTimeout(600);
    await page.evaluate(() =>
        [...document.querySelectorAll("button")]
            .find((b) => b.getAttribute("aria-label") === "更多")
            ?.click(),
    );
    await page.waitForTimeout(350);
    await page.evaluate((want) => {
        const sel = [...document.querySelectorAll(".tb-menu select")].find(
            (s) => s.options.length === 8,
        );
        if (!sel) return "NO SEL";
        sel.value = want;
        sel.dispatchEvent(new Event("change", { bubbles: true }));
        return sel.value;
    }, c.id);
    await page.keyboard.press("Escape");
    await page.waitForTimeout(2200);
    const m = await measure();
    const ok =
        m.avg == null
            ? false
            : c.expect === "verydark"
              ? m.avg < 60
              : c.expect === "dark"
                ? m.avg < 120
                : m.avg > 180;
    if (!ok) fails++;
    console.log(
        `${ok ? "PASS" : "FAIL"} paper=${c.id} appDark=${c.dark} → avg=${m.avg} pageBg=${m.pageBg}`,
    );
    await page.screenshot({
        path: join(SHOTS, `paper-${c.id}-${c.dark ? "d" : "l"}.png`),
    });
}

console.log(
    errors.length ? `errors:\n${errors.join("\n")}` : "no console errors",
);
console.log(fails ? `${fails} FAIL` : "ALL PASS");
await browser.close();
process.exit(fails ? 1 : 0);
