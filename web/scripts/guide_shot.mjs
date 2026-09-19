import { readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
const root = join(homedir(), ".cache/ms-playwright");
const exe = join(root, readdirSync(root).filter(x => x.startsWith("chromium-")).sort().reverse()[0], "chrome-linux64/chrome");
const browser = await chromium.launch({ executablePath: exe });
const page = await browser.newPage({ viewport: { width: 1200, height: 1500 } });
const task = process.env.TASK ?? "t_a096368649765da9";
await page.goto(`http://127.0.0.1:8765/#/reader/${task}`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3500);
// 模式选择器——找含「导读/guide」的选项
const clicked = await page.evaluate(() => {
    const els = [...document.querySelectorAll("button,select,[role=button],option")];
    const hit = els.find(e => /导读|guide/i.test(e.textContent ?? "") || /guide/i.test(e.value ?? ""));
    if (!hit) return els.map(e => (e.textContent ?? e.value ?? "").trim()).filter(Boolean).slice(0, 30);
    if (hit.tagName === "OPTION") { hit.selected = true; hit.parentElement.dispatchEvent(new Event("change", { bubbles: true })); }
    else hit.click();
    return "clicked:" + (hit.textContent ?? hit.value).trim();
});
console.log("mode-click:", JSON.stringify(clicked));
await page.waitForTimeout(4500);
const stats = await page.evaluate(() => {
    const g = document.querySelector(".guide-body");
    return {
        hasGuide: !!g,
        guideText: (g?.innerText ?? "").slice(0, 300),
        katex: document.querySelectorAll(".guide .katex").length,
        katexErr: document.querySelectorAll(".guide .katex-error").length,
        dollarLeft: (document.querySelector(".guide")?.innerText.match(/\$[^$\n]+\$/g) ?? []).slice(0, 5),
        imgs: document.querySelectorAll(".guide img").length,
        imgsBroken: [...document.querySelectorAll(".guide img")].filter(i => !i.complete || i.naturalWidth === 0).length,
    };
});
console.log(JSON.stringify(stats, null, 1));
await page.screenshot({ path: "guide.png", fullPage: true });
await browser.close();
