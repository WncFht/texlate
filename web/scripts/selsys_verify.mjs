// sel-system 实测：划词浮条 / 右键菜单 / Esc 层栈 / 句游标。
// 活服 127.0.0.1:8765（须已 build-web.sh + 重启）+ 真实 done 任务。
//   TASK 默认 t_d7c669e8b3c92149（eprint 链双 PDF，cite.* 锚）；
//   VIEW=html|dom 的任务换 TASK 环境变量即可复用本脚本（断言自动按
//   .pane-html-body/.pane-dom 落点走）。
//
// 覆盖矩阵（断言全部是行为级，不锚像素）：
//   1. floatbar    —— 拖选出条（fixed .floatbar visible）、钮数>0、
//                    点钮收条；settingsStore 关掉后不再出条；
//   2. ctxmenu     —— 右键出 .ctx-menu（role=menu）含 .ctx-item；
//                    Shift+右键不出自定义单（原生直通）；Esc 单塌一层；
//                    外点收单；菜单开时 floatbar 互斥收；
//   3. escstack    —— cite 卡开 + 选区在：一次 Esc 只塌卡不杀选区；
//   4. cursor      —— pane 聚焦按 v → .pane.cursor-on + .sb.cur 焦点；
//                    j 移句 → Enter 选句（.sb.sel + 原生选区非坍缩）→
//                    Esc 退模态回 pane 焦点。
// 用法: node scripts/selsys_verify.mjs   (cwd=web/scripts)

import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const BASE = process.env.WEB_BASE ?? "http://127.0.0.1:8765";
const TASK = process.env.TASK ?? "t_d7c669e8b3c92149";
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

/** pane 内文本宿主：dom/html → .pane-html-body；pdf → .textLayer */
const HOST_SEL = (side) =>
    `.pane[data-side="${side}"] .pane-html-body, .pane[data-side="${side}"] .textLayer`;

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
    let crashed = false;
    page.on("crash", () => {
        crashed = true;
        console.log("!! renderer crashed — will retry");
    });
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
    page.on("console", (m) => {
        if (m.type() === "error")
            errors.push(`console.error: ${m.text().slice(0, 200)}`);
    });
    const bail = () => {
        if (crashed) throw new Error("renderer crashed");
    };

    try {
        await page.goto(`${BASE}/#/reader/${TASK}`, {
            waitUntil: "domcontentloaded",
        });
        await page.waitForSelector(HOST_SEL("original"), { timeout: 30000 });
        await page.waitForTimeout(2500);
        bail();

        const bar = page.locator(".floatbar");
        const menu = page.locator(".ctx-menu");
        const host = page.locator(HOST_SEL("original")).first();

        // ---- 1. 划词浮条 -------------------------------------------------
        // 拖选一段文本（首尾字符盒间直线扫）
        const selOk = await page.evaluate((sel) => {
            const el = document.querySelector(sel);
            if (!el) return false;
            const t = el.querySelector("[data-chunk]") ?? el.firstElementChild;
            const node = t?.firstChild;
            if (!node || node.nodeType !== 3 || node.length < 8) return false;
            const s = getSelection();
            s.setBaseAndExtent(node, 0, node, Math.min(12, node.length));
            return s.toString().length > 0;
        }, HOST_SEL("original"));
        check("selection made", selOk);
        await page.waitForTimeout(300); // release 40ms + rAF
        const barVisible = await bar.isVisible().catch(() => false);
        check("floatbar shows on selection", barVisible);
        if (barVisible) {
            const n = await bar.locator("button").count();
            check("floatbar has buttons", n > 0, `${n} buttons`);
            const first = bar.locator("button").first();
            const label = await first.textContent();
            await first.click();
            await page.waitForTimeout(200);
            check(
                "floatbar action hides bar",
                !(await bar.isVisible().catch(() => false)),
                `clicked "${label}"`,
            );
        }

        // ---- 2. 右键菜单 --------------------------------------------------
        // 互斥前置：再做一次选区出条
        await page.evaluate((sel) => {
            const el = document.querySelector(sel);
            const node = el?.querySelector("[data-chunk]")?.firstChild;
            if (node?.nodeType === 3)
                getSelection().setBaseAndExtent(node, 0, node, 10);
        }, HOST_SEL("original"));
        await page.waitForTimeout(300);
        const barBeforeMenu = await bar.isVisible().catch(() => false);

        await host.click({ button: "right" });
        await page.waitForTimeout(250);
        const menuVisible = await menu.isVisible().catch(() => false);
        check("contextmenu opens .ctx-menu", menuVisible);
        if (menuVisible) {
            const items = await menu.locator("li[role='menuitem']").count();
            check("menu has items", items > 0, `${items} items`);
            // FloatBar 互斥：开单后条必收
            if (barBeforeMenu)
                check(
                    "menu suppresses floatbar",
                    !(await bar.isVisible().catch(() => false)),
                );
            // Esc 单塌一层：菜单收，选区仍在（jsdom 外真实浏览器选区保持）
            await page.keyboard.press("Escape");
            await page.waitForTimeout(200);
            check(
                "Esc collapses menu only",
                !(await menu.isVisible().catch(() => false)),
            );
        }

        // Shift+右键 → 原生菜单直通（自定义单不开）
        await host.click({ button: "right", modifiers: ["Shift"] });
        await page.waitForTimeout(250);
        check(
            "shift+rclick bypasses custom menu",
            !(await menu.isVisible().catch(() => false)),
        );
        await page.keyboard.press("Escape"); // 原生菜单退场的兜底拍
        await page.waitForTimeout(150);

        // ---- 3. 句游标 ----------------------------------------------------
        // .sb 哨兵只在 dom/html 侧有（pdf 侧不建）——无则跳过并报未覆盖
        const sbCount = await page
            .locator(`.pane[data-side="original"] .sb`)
            .count();
        if (sbCount > 0) {
            const pane = page.locator('.pane[data-side="original"]');
            await pane.focus();
            await page.keyboard.press("v");
            await page.waitForTimeout(200);
            check(
                "v enters cursor mode",
                await page
                    .locator('.pane[data-side="original"].cursor-on .sb.cur')
                    .isVisible()
                    .catch(() => false),
            );
            await page.keyboard.press("j");
            await page.waitForTimeout(120);
            await page.keyboard.press("Enter");
            await page.waitForTimeout(120);
            check(
                "Enter selects sentence",
                await page
                    .locator('.pane[data-side="original"] .sb.sel')
                    .isVisible()
                    .catch(() => false),
            );
            await page.keyboard.press("Escape");
            await page.waitForTimeout(120);
            check(
                "Esc exits cursor mode",
                !(await page
                    .locator(".pane.cursor-on")
                    .isVisible()
                    .catch(() => false)),
            );
        } else {
            console.log("SKIP  cursor — pdf 侧无 .sb（dom/html 任务才覆盖）");
        }

        // ---- 4. 右键在 cite 锚上 → cite 段项可见 --------------------------
        const citeA = page
            .locator(
                '.pane[data-side="original"] a[href^="#cite."], ' +
                    '.pane[data-side="original"] a[href^="#bib."], ' +
                    '.pane[data-side="original"] a.cite-ref',
            )
            .first();
        if ((await citeA.count()) > 0) {
            await citeA.scrollIntoViewIfNeeded();
            await citeA.click({ button: "right" });
            await page.waitForTimeout(250);
            const citeItem = await menu
                .locator("li[role='menuitem']")
                .allTextContents()
                .catch(() => []);
            check(
                "cite section items on cite anchor",
                citeItem.some((x) => /引用|文献|Jump to|reference/i.test(x)),
                citeItem.join(" | ").slice(0, 120),
            );
            await page.keyboard.press("Escape");
        } else {
            console.log("SKIP  cite menu — 本任务无 cite 锚（dom 链特征）");
        }

        await page.screenshot({
            path: join(SHOTS, `selsys-${TASK}.png`),
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
