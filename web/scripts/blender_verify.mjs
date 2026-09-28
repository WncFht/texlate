// Blender 暗色管线实测:dev server(::1:5199,真后端)+ 真实 done 任务。
// 断言走 canvas 物理像素(getImageData)——CSS filter 是合成层效果不影响
// 读回,所以均值变暗 = Blender 在渲染期改写了像素,而非老 CSS 兜底。
// 用法:node scripts/blender_verify.mjs

import { join } from "node:path";
import { launch, SHOTS } from "./lib/pwkit.mjs";

const BASE = process.env.WEB_BASE ?? "http://[::1]:5199";
const TASK = process.env.TASK ?? "t_d7c669e8b3c92149";

// 主视区第一页 canvas 的平均亮度(步长采样) + 近 bg/fg 像素占比
const SAMPLE = `(() => { try {
    const cv = document.querySelector(".pdfSlickViewer .page canvas");
    if (!cv || !cv.width || !cv.height) return null;
    const x = cv.getContext("2d");
    if (!x) return null;
    const d = x.getImageData(0, 0, cv.width, cv.height).data;
    let sum = 0, n = 0, darkish = 0, lightish = 0;
    for (let i = 0; i < d.length; i += 4 * 97) {
        const l = 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
        sum += l; n++;
        if (l < 60) darkish++;
        if (l > 200) lightish++;
    }
    return { avg: +(sum / n).toFixed(1), darkPct: +(darkish / n * 100).toFixed(1), lightPct: +(lightish / n * 100).toFixed(1) };
    } catch { return null; } })()`;

const THUMB_SAMPLE = `(() => { try {
    const cv = document.querySelector(".pane-pdf .thumbnailImage") ||
               document.querySelector(".pdfSlickThumbnail canvas") ||
               document.querySelector(".thumbnailImage canvas") ||
               document.querySelector("a[class*=thumbnail] canvas") ||
               document.querySelector(".pdfSlickThumbnails canvas");
    if (!cv || !cv.width) {
        const c = [...document.querySelectorAll("canvas")].find(c => !c.closest(".pdfSlickViewer"));
        if (!c) return null;
        const x = c.getContext("2d");
        const d = x.getImageData(0, 0, c.width, c.height).data;
        let s = 0, n = 0;
        for (let i = 0; i < d.length; i += 4 * 13) { s += 0.2126*d[i]+0.7152*d[i+1]+0.0722*d[i+2]; n++; }
        return { avg: +(s/n).toFixed(1), sel: "fallback" };
    }
    const x = cv.getContext("2d");
    const d = x.getImageData(0, 0, cv.width, cv.height).data;
    let s = 0, n = 0;
    for (let i = 0; i < d.length; i += 4 * 13) { s += 0.2126*d[i]+0.7152*d[i+1]+0.0722*d[i+2]; n++; }
    return { avg: +(s/n).toFixed(1) };
    } catch { return null; } })()`;

const browser = await launch();
const ctx = await browser.newContext({
    viewport: { width: 1400, height: 950 },
});
// 先亮色开文档,拿到「白底」基线,再切暗验证重渲路径(reset+update)
await ctx.addInitScript(() => localStorage.setItem("texlate-theme", "light"));
const page = await ctx.newPage();
page.on("pageerror", (e) => console.log("[pageerror]", e.message));
page.on("console", (m) => {
    if (m.type() === "error")
        console.log("[console.error]", m.text().slice(0, 200));
});
await page.goto(`${BASE}/#/reader/${TASK}`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".pdfSlickViewer .page canvas", { timeout: 20000 });
await page.waitForTimeout(2500);

const light = await page.evaluate(SAMPLE);
console.log("light baseline:", JSON.stringify(light));

// 切到暗色:applyTheme 的落点就是 data-theme——直接写属性,MutationObserver
// 管线等价触发(toggle→store→applyTheme 链路此前已验)
await page.evaluate(() => {
    localStorage.setItem("texlate-theme", "dark");
    document.documentElement.dataset.theme = "dark";
});
await page.waitForTimeout(300);

// 等重渲:像素均值跌破阈为止(最多 8s;reset 会换新 canvas 故直接采样)
await page
    .waitForFunction(
        `(() => { const r = ${SAMPLE}; return r && r.avg < 120; })()`,
        { timeout: 8000 },
    )
    .catch(() => console.log("!! dark wait timeout"));
await page.waitForTimeout(400);
const dark = await page.evaluate(SAMPLE);
const thumbDark = await page.evaluate(THUMB_SAMPLE);
console.log(
    "dark render:",
    JSON.stringify(dark),
    "thumb:",
    JSON.stringify(thumbDark),
);
await page.screenshot({ path: join(SHOTS, "blender-dark-reader.png") });

// 切回亮色 → 应回白底
await page.evaluate(() => {
    localStorage.setItem("texlate-theme", "light");
    document.documentElement.dataset.theme = "light";
});
await page
    .waitForFunction(
        `(() => { const r = ${SAMPLE}; return r && r.avg > 180; })()`,
        { timeout: 8000 },
    )
    .catch(() => console.log("!! light wait timeout"));
await page.waitForTimeout(400);
const relight = await page.evaluate(SAMPLE);
console.log("relight render:", JSON.stringify(relight));
await page.screenshot({ path: join(SHOTS, "blender-light-reader.png") });

const ok =
    light &&
    light.avg > 180 &&
    dark &&
    dark.avg < 120 &&
    dark.darkPct > 50 &&
    relight &&
    relight.avg > 180;
console.log(ok ? "PASS" : "FAIL");
await browser.close();
process.exit(ok ? 0 : 1);
