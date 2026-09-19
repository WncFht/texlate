import { readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";
const root = join(homedir(), ".cache/ms-playwright");
const exe = join(root, readdirSync(root).filter(x => x.startsWith("chromium-")).sort().reverse()[0], "chrome-linux64/chrome");
const browser = await chromium.launch({ executablePath: exe });
const page = await browser.newPage({ viewport: { width: 1200, height: 1500 } });
await page.goto(`http://127.0.0.1:8765/#/reader/t_a096368649765da9`, { waitUntil: "domcontentloaded" });
await page.waitForTimeout(3000);
await page.evaluate(() => {
    const els = [...document.querySelectorAll("button,select,[role=button]")];
    const hit = els.find(e => /导读|guide/i.test(e.textContent ?? ""));
    hit?.click();
});
await page.waitForTimeout(4000);
const r = await page.evaluate(() => {
    const lead = document.querySelector(".guide-lead");
    const feed = document.querySelector(".guide-feed");
    const cards = [...document.querySelectorAll(".guide-card li")].map(li => li.innerText.slice(0, 60));
    return {
        leadHTML: lead?.innerHTML.slice(0, 400),
        leadHasKatex: !!lead?.querySelector(".katex"),
        feedText: feed?.innerText.slice(0, 200),
        cardKatex: document.querySelectorAll(".guide-card .katex").length,
        rawDollar: (document.querySelector(".guide")?.innerText.match(/\$/g) ?? []).length,
        cards,
    };
});
console.log(JSON.stringify(r, null, 1));
await page.screenshot({ path: "guide2.png", fullPage: true });
await browser.close();
