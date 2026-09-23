// 纸面×背景协同审计:逐色板截图 + 关键面(gutter/page/pane/panel)实际取色。
// 用法:node scripts/theme_pair_audit.mjs;产物 scripts/shots/pair-*.png
import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const BASE = process.env.WEB_BASE ?? "http://[::1]:5199";
const TASK = process.env.TASK ?? "t_0000000000000a01";
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

const THEMES = ["auto", "none", "dark", "onedark", "black", "snow", "sepia", "paper"];
const OS_DARK = process.env.OS_DARK !== "0"; // 默认模拟暗 OS(auto/none 才有戏)

const PROBE = `(() => {
    const cs = (el, p) => el ? getComputedStyle(el)[p] : null;
    const pick = (sel, prop = "backgroundColor") =>
        cs(document.querySelector(sel), prop);
    const root = document.documentElement;
    const vars = {};
    for (const v of ["--paper","--paper-2","--panel","--ink","--line"])
        vars[v] = getComputedStyle(root).getPropertyValue(v).trim();
    return {
        theme: localStorage.getItem("texlate-paper-theme"),
        dataTheme: root.dataset.theme,
        vars,
        body: pick("body"),
        panes: pick(".panes"),
        slickContainer: pick(".pdfSlickContainer"),
        page: pick(".pdfSlickViewer .page"),
        pageInlineVar: document.querySelector(".pdfSlickViewer")?.style.getPropertyValue("--page-bg-color") || null,
        canvas: (() => {
            const cv = document.querySelector(".pdfSlickViewer .page canvas");
            if (!cv?.width) return null;
            const d = cv.getContext("2d").getImageData(0,0,cv.width,cv.height).data;
            let s=0,n=0;
            for (let i=0;i<d.length;i+=4*97){s+=0.2126*d[i]+0.7152*d[i+1]+0.0722*d[i+2];n++}
            return +(s/n).toFixed(1);
        })(),
        htmlPane: pick(".pane-html"),
        toolbar: pick(".reader-toolbar"),
        rail: pick(".pane-rail"),
    };
})()`;

const browser = await chromium.launch({ executablePath: EXE });
for (const t of THEMES) {
    const ctx = await browser.newContext({
        viewport: { width: 1440, height: 900 },
        colorScheme: OS_DARK ? "dark" : "light",
    });
    await ctx.addInitScript(
        (v) => localStorage.setItem("texlate-paper-theme", v),
        t,
    );
    const page = await ctx.newPage();
    page.on("pageerror", (e) => console.log(`[${t} pageerror]`, e.message));
    await page.goto(`${BASE}/#/reader/${TASK}`, {
        waitUntil: "domcontentloaded",
    });
    await page
        .waitForSelector(".pdfSlickViewer .page canvas", { timeout: 15000 })
        .catch(() => console.log(`[${t}] no canvas`));
    await page.waitForTimeout(2500);
    const probe = await page.evaluate(PROBE);
    console.log(`\n=== ${t} (osDark=${OS_DARK}) ===`);
    console.log(JSON.stringify(probe, null, 1));
    await page.screenshot({
        path: join(SHOTS, `pair-${t}${OS_DARK ? "-darkos" : "-lightos"}.png`),
    });
    await ctx.close();
}
await browser.close();
