// rail 双常驻验证：split 下两 pane 各 34px rail，激活切换后位置不变。
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
        readdirSync(root)
            .filter((x) => x.startsWith("chromium-"))
            .sort()
            .at(-1),
        "chrome-linux64/chrome",
    );

const b = await chromium.launch({
    executablePath: EXE,
    args: ["--disable-dev-shm-usage", "--no-sandbox"],
});
const pg = await b.newPage({ viewport: { width: 1600, height: 900 } });
await pg.goto(`${BASE}/#/reader/${TASK}`, { waitUntil: "networkidle" });
await pg.waitForSelector(".pane-rail", { timeout: 15000 }).catch(() => {});
await pg.waitForTimeout(2500);
const snap = () =>
    pg.evaluate(() => ({
        panesCls: document.querySelector(".panes")?.className,
        panes: [...document.querySelectorAll(".pane")].map((p) => ({
            side: p.dataset.side,
            active: p.classList.contains("active"),
        })),
        rails: [...document.querySelectorAll(".pane-rail")].map((r) => {
            const cs = getComputedStyle(r);
            const rect = r.getBoundingClientRect();
            return {
                display: cs.display,
                x: Math.round(rect.x),
                w: Math.round(rect.width),
            };
        }),
    }));
const before = await snap();
const panes = await pg.$$(".pane");
if (panes[1]) {
    await panes[1].click({ position: { x: 200, y: 400 } });
    await pg.waitForTimeout(400);
}
const after = await snap();
console.log(JSON.stringify({ before, after }, null, 1));
await pg.screenshot({ path: "rail-check.png" });
await b.close();
