import { readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
const root = join(homedir(), ".cache/ms-playwright");
const EXE = join(root, readdirSync(root).filter(x => x.startsWith("chromium-")).sort().reverse()[0], "chrome-linux64/chrome");
const browser = await chromium.launch({ executablePath: EXE });
const ctx = await browser.newContext({ viewport: { width: 1200, height: 900 } });
await ctx.addInitScript(() => localStorage.setItem("texlate-theme", "dark"));
const page = await ctx.newPage();
page.on("console", m => console.log("[pg]", m.text().slice(0, 250)));
page.on("pageerror", e => console.log("[err]", e.message));
await page.goto("http://[::1]:5199/#/reader/t_d7c669e8b3c92149", { waitUntil: "domcontentloaded" });
await page.waitForSelector(".pdfSlickViewer .page canvas", { timeout: 20000 });
await page.waitForTimeout(2500);
const out = await page.evaluate(() => {
    const el = document.documentElement;
    const cs = getComputedStyle(el);
    // pdfSlick 实例不在全局——从 DOM 找 viewer 内部对象不可行;改查 store/DOM 线索
    const cv = document.querySelector(".pdfSlickViewer .page canvas");
    const thumb = document.querySelector(".pane-pdf canvas.thumbnailImage, .pdfSlickThumbnails canvas, [class*=thumbnail] canvas");
    return {
        dataTheme: el.dataset.theme,
        paper: cs.getPropertyValue("--paper").trim(),
        ink: cs.getPropertyValue("--ink").trim(),
        canvasSize: cv ? [cv.width, cv.height] : null,
        thumbFound: !!thumb,
        thumbClass: thumb?.className,
        allCanvases: [...document.querySelectorAll("canvas")].map(c => c.className || c.parentElement?.className).slice(0, 15),
    };
});
console.log(JSON.stringify(out, null, 1));
await browser.close();
