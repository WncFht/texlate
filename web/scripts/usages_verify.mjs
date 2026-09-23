// find-usages 实测：悬浮卡三触发 / 站点跳回 / cite 卡互斥与切换 / 空态 /
// zh 配对行 / Esc 与 contextmenu 语义。
// 活服 127.0.0.1:8765（须已 build-web.sh）+ dom 视图任务：
//   TASK 默认 t_a1b2c3d4e5f60001——注入的 arxiv_html 链 fixture
//   （en.html/zh.html 均为 1706.03762 latexml 产物副本）。
//   换 TASK 即可复用到任何 dom 视图任务（断言按结构不锚像素）。
//
// 覆盖矩阵：
//   1. hover figure → dwell 后 .usage-card 出（Figure 2: 3 站）；
//      pointerout 后 350ms 宽限关卡；
//   2. tap/点击 figure → 即开卡；
//   3. 句项点击 → 跳回引用锚（scrollTop 变 + 卡收 + cite-flash）；
//   4. hover .ltx_bibitem → bib 卡（bib38 = 8 站）；
//   5. contextmenu section → 非 hoverable 类也直开；shift+右键放行；
//   6. 零引用 figure（Sx1.F3）→ 空态文案；
//   7. cite 卡脚部「N 处引用 →」→ usages 卡（卡族互斥 cite 卡收）；
//   8. zh 配对行 .usage-card-sent-zh 渲染（双侧索引在场时）；
//   9. Esc 关卡；
//  10. cite 锚右键 → ctxm 菜单「查找引用」→ usages 卡（registerFindUsages
//      → ReaderView open→openUsagesFor 链路）。
// 用法: node scripts/usages_verify.mjs   (cwd=web/scripts)

import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const BASE = process.env.WEB_BASE ?? "http://127.0.0.1:8765";
const TASK = process.env.TASK ?? "t_a1b2c3d4e5f60001";
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

const BODY = (side) => `.pane[data-side="${side}"] .pane-html-body`;

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
    // 资源 404 走 response 面（带 URL 可白名单）；console 的
    // "Failed to load resource" 无 URL，跳过改由 response 覆盖
    const INHERENT_404 =
        /\/Figures\/|\/api\/task\/[^/]+\/refs\/kept/;
    page.on("response", (r) => {
        if (r.status() >= 400 && !INHERENT_404.test(r.url()))
            errors.push(`http ${r.status()}: ${r.url()}`);
    });
    page.on("console", (m) => {
        if (m.type() === "error" && !/Failed to load resource/.test(m.text()))
            errors.push(`console.error: ${m.text().slice(0, 200)}`);
    });
    const bail = () => {
        if (crashed) throw new Error("renderer crashed");
    };

    const card = page.locator(".usage-card");
    const cardVisible = () => card.isVisible().catch(() => false);
    const scrollTop = () =>
        page.evaluate(
            (sel) => document.querySelector(sel)?.scrollTop ?? -1,
            '.pane[data-side="original"]',
        );

    try {
        await page.goto(`${BASE}/#/reader/${TASK}`, {
            waitUntil: "domcontentloaded",
        });
        const bodyOk = await page
            .waitForSelector(BODY("original"), { timeout: 30000 })
            .then(() => true)
            .catch(() => false);
        if (!bodyOk) {
            console.log(
                "SKIP  非 dom 视图任务（本 lane 需 arxiv_html 链）——全部断言跳过",
            );
            process.exit(0);
        }
        await page.waitForSelector(`${BODY("original")} figure`, {
            timeout: 20000,
        });
        await page.waitForTimeout(2500); // 分片落地+索引构建宽限
        bail();

        // ---- 1. hover figure → 卡 --------------------------------------
        const fig2 = page.locator(`${BODY("original")} [id="S3.F2"]`);
        const figOk = (await fig2.count()) > 0;
        check("fixture figure S3.F2 present", figOk);
        if (figOk) {
            await fig2.scrollIntoViewIfNeeded();
            await fig2.hover();
            await page.waitForTimeout(400); // dwell 150 + 渲染
            check("hover figure opens usages card", await cardVisible());
            if (await cardVisible()) {
                const label = await card
                    .locator(".usage-card-label")
                    .textContent();
                check(
                    "card label = Figure 2",
                    /Figure 2/.test(label ?? ""),
                    label ?? "",
                );
                const items = await card
                    .locator(".usage-card-item")
                    .count();
                check("Figure 2 has 3 sites", items === 3, `${items}`);
                // zh 配对行（对侧索引在场）
                const zhRows = await card
                    .locator(".usage-card-sent-zh")
                    .count();
                check("zh pair rows render", zhRows > 0, `${zhRows}`);
            }
            // pointerout → 350ms 宽限关卡
            await page.mouse.move(40, 40);
            await page.waitForTimeout(200);
            check("card survives brief leave (<350ms)", await cardVisible());
            await page.waitForTimeout(400);
            check("card closes after grace", !(await cardVisible()));
        }

        // ---- 2. tap/点击即开 ---------------------------------------------
        if (figOk) {
            await fig2.click({ position: { x: 8, y: 8 } });
            await page.waitForTimeout(150);
            check("tap opens card immediately", await cardVisible());
        }

        // ---- 3. 句项跳回 ---------------------------------------------------
        if (await cardVisible()) {
            const before = await scrollTop();
            await card.locator(".usage-card-item").first().click();
            await page.waitForTimeout(400);
            const after = await scrollTop();
            check(
                "site click jumps to citing anchor",
                before !== after || before < 0,
                `scrollTop ${before}→${after}`,
            );
            check("jump closes card", !(await cardVisible()));
            const flashed = await page
                .locator(`${BODY("original")} .cite-flash`)
                .count();
            check("anchor flash mark", flashed > 0, `${flashed}`);
        }

        // ---- 4. hover bibitem → bib 卡 ------------------------------------
        const bib38 = page.locator(`${BODY("original")} [id="bib.bib38"]`);
        if ((await bib38.count()) > 0) {
            await bib38.scrollIntoViewIfNeeded();
            await bib38.hover();
            await page.waitForTimeout(400);
            check("hover bibitem opens card", await cardVisible());
            if (await cardVisible()) {
                const items = await card
                    .locator(".usage-card-item")
                    .count();
                check("bib38 has 8 sites", items === 8, `${items}`);
            }
            await page.keyboard.press("Escape");
            await page.waitForTimeout(150);
            check("Esc closes card", !(await cardVisible()));
        } else {
            console.log("SKIP  bib.bib38 — fixture 无此条");
        }

        // ---- 5. contextmenu 全类 + shift 放行 ------------------------------
        const cmOk = await page.evaluate((sel) => {
            const sec = document.querySelector(`${sel} [id="S5.SS4"]`);
            if (!sec) return false;
            sec.dispatchEvent(
                new MouseEvent("contextmenu", {
                    bubbles: true,
                    cancelable: true,
                }),
            );
            return true;
        }, BODY("original"));
        if (cmOk) {
            await page.waitForTimeout(200);
            check(
                "contextmenu on section opens card",
                await cardVisible(),
            );
            check(
                "custom ctx menu suppressed",
                !(await page
                    .locator(".ctx-menu")
                    .isVisible()
                    .catch(() => false)),
            );
            await page.keyboard.press("Escape");
            await page.waitForTimeout(150);
        } else {
            console.log("SKIP  S5.SS4 section — fixture 缺");
        }
        const shiftOk = await page.evaluate((sel) => {
            const sec = document.querySelector(`${sel} [id="S5.SS4"]`);
            if (!sec) return false;
            sec.dispatchEvent(
                new MouseEvent("contextmenu", {
                    bubbles: true,
                    cancelable: true,
                    shiftKey: true,
                }),
            );
            return true;
        }, BODY("original"));
        if (shiftOk) {
            await page.waitForTimeout(200);
            check(
                "shift+contextmenu bypasses card",
                !(await cardVisible()),
            );
            await page.keyboard.press("Escape");
            await page.waitForTimeout(120);
        }

        // ---- 6. 零引用 figure 空态 ----------------------------------------
        const f3 = page.locator(`${BODY("original")} [id="Sx1.F3"]`);
        if ((await f3.count()) > 0) {
            await f3.scrollIntoViewIfNeeded();
            await f3.hover();
            await page.waitForTimeout(400);
            check("unreferenced figure opens card", await cardVisible());
            const empty = await card
                .locator(".usage-card-empty")
                .isVisible()
                .catch(() => false);
            check("empty state renders", empty);
            await page.keyboard.press("Escape");
            await page.waitForTimeout(150);
        } else {
            console.log("SKIP  Sx1.F3 — fixture 缺");
        }

        // ---- 7. cite 卡 → usages 切换 --------------------------------------
        const citeA = page
            .locator(`${BODY("original")} a[href="#bib.bib38"]`)
            .first();
        if ((await citeA.count()) > 0) {
            await citeA.scrollIntoViewIfNeeded();
            await citeA.hover();
            await page.waitForTimeout(400);
            const citeCard = page.locator(".cite-card");
            const citeUp = await citeCard.isVisible().catch(() => false);
            check("cite anchor hover opens cite card", citeUp);
            const btn = citeCard.locator(".cite-card-usages");
            if (await btn.isVisible().catch(() => false)) {
                await btn.click();
                await page.waitForTimeout(250);
                check("usages button switches to usage card",
                    await cardVisible());
                check(
                    "cite card closed (mutex)",
                    !(await citeCard.isVisible().catch(() => false)),
                );
            } else {
                check("cite card usages button present", false);
            }
            await page.keyboard.press("Escape");
        } else {
            console.log("SKIP  cite anchor — fixture 无 #bib.bib38 锚");
        }

        // ---- 8. ctxm 菜单 cite.usages 命令路 -------------------------------
        // cite 锚让行（attachUsages 不拦）→ .panes 委托开菜单 →
        // 「查找引用」→ openUsagesFor(bib38) → 卡直开
        const citeA2 = page
            .locator(`${BODY("original")} a[href="#bib.bib38"]`)
            .first();
        if ((await citeA2.count()) > 0) {
            await citeA2.scrollIntoViewIfNeeded();
            // 带锚点坐标的合成 contextmenu——菜单落在锚旁（坐标 0,0 会把
            // fixed 菜单项渲出视口，click 永远等不到稳定）
            await page.evaluate((sel) => {
                const a = document.querySelector(
                    `${sel} a[href="#bib.bib38"]`,
                );
                if (!a) return;
                const r = a.getBoundingClientRect();
                a.dispatchEvent(
                    new MouseEvent("contextmenu", {
                        bubbles: true,
                        cancelable: true,
                        clientX: r.left + 4,
                        clientY: r.top + 4,
                    }),
                );
            }, BODY("original"));
            await page.waitForTimeout(300);
            const menu = page.locator(".ctx-menu");
            const menuUp = await menu.isVisible().catch(() => false);
            check("cite anchor ctxm opens custom menu", menuUp);
            const item = page.locator(
                '.ctx-item[data-id="cite.usages"]',
            );
            const itemUp = await item.isVisible().catch(() => false);
            check("cite.usages menu item present", itemUp);
            if (itemUp) {
                await item.click();
                await page.waitForTimeout(300);
                check(
                    "menu item opens usages card",
                    await cardVisible(),
                );
                check(
                    "ctx menu closed after pick",
                    !(await menu.isVisible().catch(() => false)),
                );
                if (await cardVisible()) {
                    const n = await card
                        .locator(".usage-card-item")
                        .count();
                    check("menu-opened card = bib38 sites", n === 8, `${n}`);
                }
            }
            await page.keyboard.press("Escape");
            await page.waitForTimeout(150);
        } else {
            console.log("SKIP  menu path — fixture 无 #bib.bib38 锚");
        }

        await page.screenshot({
            path: join(SHOTS, `usages-${TASK}.png`),
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
