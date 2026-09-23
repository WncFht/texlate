// 图/表/公式引用查位置 v1 实测：滚动找 figure/table/equation 锚 → 悬停出 UsagesCard → 右键出 cite.usages
import { readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const BASE = process.env.WEB_BASE ?? "http://127.0.0.1:8765";
const TASK = process.env.TASK ?? "t_65d2d6b1cca13638";
const root = join(homedir(), ".cache/ms-playwright");
const EXE =
    process.env.PW_EXE ??
    join(
        root,
        readdirSync(root).filter((x) => x.startsWith("chromium-")).sort().at(-1),
        "chrome-linux64/chrome",
    );

const b = await chromium.launch({
    executablePath: EXE,
    args: ["--disable-dev-shm-usage", "--no-sandbox"],
});
const pg = await b.newPage({ viewport: { width: 1600, height: 900 } });
await pg.goto(`${BASE}/#/reader/${TASK}`, { waitUntil: "networkidle" });
await pg.waitForSelector("section.linkAnnotation a[href^='#']", { timeout: 20000 });
await pg.waitForTimeout(3000);

// 找 figure/table/equation 锚——不在视口就滚 zh 侧容器翻页找
const findTarget = () =>
    pg.evaluate(() => {
        for (const a of document.querySelectorAll("section.linkAnnotation a[href^='#']")) {
            const h = a.getAttribute("href") ?? "";
            if (!/^#(figure|table|equation)\./.test(h)) continue;
            const r = a.getBoundingClientRect();
            if (r.width && r.height && r.top > 80 && r.bottom < innerHeight - 60)
                return { href: h, x: r.left + r.width / 2, y: r.top + r.height / 2 };
        }
        return null;
    });

let target = await findTarget();
const scroller = await pg.$(".pane[data-side='translated'] .pdfSlickContainer, .pane[data-side='translated'] .pdfViewer, .pane[data-side='translated']");
for (let i = 0; i < 40 && !target; i++) {
    // 两个 pane 都滚——en 侧引用密度高
    for (const sel of [".pane[data-side='original']", ".pane[data-side='translated']"]) {
        await pg.evaluate((s) => {
            const p = document.querySelector(s);
            const c = p?.querySelector(".pdfSlickContainer") ?? p?.querySelector("[class*='viewer'], [class*='container']") ?? p;
            if (c) c.scrollTop += 1400;
        }, sel);
    }
    await pg.waitForTimeout(700);
    target = await findTarget();
}
console.log("hover target:", JSON.stringify(target));
if (!target) {
    const inv = await pg.evaluate(() => {
        const out = {};
        for (const a of document.querySelectorAll("section.linkAnnotation a[href^='#']")) {
            const fam = (a.getAttribute("href") ?? "").slice(1).split(".")[0];
            out[fam] = (out[fam] ?? 0) + 1;
        }
        return out;
    });
    console.log("anchor families after scroll:", JSON.stringify(inv));
    await b.close();
    process.exit(0);
}
await pg.mouse.move(target.x, target.y);
await pg.waitForTimeout(700);
const card = await pg.evaluate(() => {
    const c = document.querySelector(".usage-card");
    return c
        ? {
              label: c.querySelector(".usage-card-label")?.textContent,
              count: c.querySelector(".usage-card-count")?.textContent,
              items: c.querySelectorAll(".usage-card-item").length,
          }
        : null;
});
console.log("hover usages card:", JSON.stringify(card));
await pg.screenshot({ path: "reflook-hover.png" });
await pg.mouse.move(900, 300); // 挪走收卡
await pg.waitForTimeout(600);
await pg.mouse.click(target.x, target.y, { button: "right" });
await pg.waitForTimeout(500);
const menu = await pg.evaluate(() =>
    [...document.querySelectorAll("[class*='ctx'] button, [role='menuitem'], .menu button")].map((x) => x.textContent?.trim()).filter(Boolean),
);
console.log("ctxmenu items:", JSON.stringify(menu));
await pg.screenshot({ path: "reflook-ctx.png" });
await b.close();
