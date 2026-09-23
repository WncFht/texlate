// 引用 UX 实测:悬浮卡 / 点击跳文献表 / ↩↪ 跳回栈 / 双栏镜像 / 触屏 tap。
// 活服 127.0.0.1:8765(须已 build-web.sh + 重启)+ 真实 done 任务
// t_d7c669e8b3c92149(eprint 链,dual.json 65 BIB 条目,双 PDF cite.* 锚)。
// 断言全部是行为级:卡出现/内容非空、scrollTop 位移、chip 显隐。
//
// 本机 /tmp 是 16G tmpfs 常年 ~97%:playwright --disable-dev-shm-usage 把
// chromium 共享内存/profile 落 /tmp→写满即渲染进程 SIGTRAP(Target crashed
// 的随机性来自他会话挤占波动)。PW_TMP 把 TMPDIR 挪出 tmpfs 根治。
// --disable-gpu 走软渲染再省一道 NVRM 分配面。
// 用法:node scripts/cite_verify.mjs   (cwd=web/scripts)

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

// pane 内 pdf.js 滚动容器(viewer.container=#viewerContainer.pdfSlickContainer)
const SCROLLER = (side) => {
    const pane = document.querySelector(`.pane[data-side="${side}"]`);
    if (!pane) return null;
    const cand = [...pane.querySelectorAll("*")].filter(
        (e) =>
            e.scrollHeight > e.clientHeight + 80 &&
            /auto|scroll/.test(getComputedStyle(e).overflowY),
    );
    cand.sort((a, b) => b.scrollHeight - a.scrollHeight);
    const el = cand[0] ?? null;
    return el
        ? { top: el.scrollTop, h: el.scrollHeight, sel: el.className }
        : null;
};

async function run() {
    const errors = [];
    const browser = await chromium.launch({
        executablePath: EXE,
        args: ["--disable-gpu"],
        env: { ...process.env, TMPDIR: PW_TMP },
    });
    const ctx = await browser.newContext({
        viewport: { width: 1500, height: 950 },
        hasTouch: true,
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
        await page.waitForSelector(
            ".pane[data-side] .pdfSlickViewer .page canvas",
            {
                timeout: 30000,
            },
        );
        await page.waitForTimeout(2500);
        bail();

        const scrollTop = (side) =>
            page.evaluate(SCROLLER, side).then((r) => r?.top ?? -1);
        const setScroll = (side, delta) =>
            page.evaluate(
                ([s, d]) => {
                    const pane = document.querySelector(
                        `.pane[data-side="${s}"]`,
                    );
                    const cand = [...pane.querySelectorAll("*")].filter(
                        (e) =>
                            e.scrollHeight > e.clientHeight + 80 &&
                            /auto|scroll/.test(getComputedStyle(e).overflowY),
                    );
                    cand.sort((a, b) => b.scrollHeight - a.scrollHeight);
                    cand[0].scrollTop += d;
                    return cand[0].scrollTop;
                },
                [side, delta],
            );

        // 滚到出现 cite.* 锚(linkAnnotation 随页渲染懒建)
        async function findCiteAnchor(side) {
            const sel = `.pane[data-side="${side}"] section.linkAnnotation a[href^="#cite."]`;
            for (let i = 0; i < 40; i++) {
                if (crashed) return null;
                const n = await page
                    .locator(sel)
                    .count()
                    .catch(() => 0);
                if (n > 0) return page.locator(sel).first();
                await setScroll(side, 700).catch(() => {});
                await page.waitForTimeout(280);
            }
            return null;
        }

        const card = page.locator(".cite-card");
        const chip = (side) =>
            page.locator(
                `.pane-slot:has(.pane[data-side="${side}"]) .nav-chip-btn`,
            );
        // back=↩ fwd=↪(按文本内容取——单向时只有一个按钮,nth 不可靠)
        const chipBtn = (side, dir) =>
            chip(side).filter({ hasText: dir === "back" ? "↩" : "↪" });

        // ---- 1. 找锚 + hover 出卡 ---------------------------------------
        const anchor = await findCiteAnchor("original");
        check("cite anchor found", !!anchor);
        if (!anchor) return;
        const href = await anchor.getAttribute("href");
        console.log(`INFO  anchor=${href}`);
        await anchor.scrollIntoViewIfNeeded();
        await page.waitForTimeout(300);

        await anchor.hover();
        await page.waitForTimeout(700);
        const cardVisible = await card.isVisible().catch(() => false);
        check("hover opens card", cardVisible);
        if (cardVisible) {
            const cardText = (await card.innerText()).trim();
            check(
                "card has content",
                cardText.length > 10,
                `${cardText.length} chars`,
            );
            await page
                .screenshot({ path: join(SHOTS, "cite-card.png") })
                .catch(() => {});
        }

        // ---- 2. Esc 关卡 --------------------------------------------------
        await page.keyboard.press("Escape");
        await page.waitForTimeout(300);
        check("Esc closes card", !(await card.isVisible().catch(() => false)));

        // ---- 3. click 跳文献表 + chip -------------------------------------
        // (Esc 后鼠标仍在锚上——先挪开再悬回,才会重发 pointerover)
        await page.mouse.move(40, 40);
        await page.waitForTimeout(400);
        await anchor.hover();
        await page.waitForTimeout(700);
        check(
            "re-hover reopens card",
            await card.isVisible().catch(() => false),
        );

        const preJump = await scrollTop("original");
        const preJumpDst = await scrollTop("translated");
        await page.keyboard.press("Escape");
        await page.waitForTimeout(200);
        await page.evaluate((h) => {
            const a = [
                ...document.querySelectorAll(
                    '.pane[data-side="original"] section.linkAnnotation a',
                ),
            ].find((x) => x.getAttribute("href") === h);
            a?.click();
        }, href);
        await page.waitForTimeout(900);
        bail();

        const postJump = await scrollTop("original");
        const postJumpDst = await scrollTop("translated");
        check(
            "click jumps (src scrollTop moved)",
            Math.abs(postJump - preJump) > 400,
            `${Math.round(preJump)} → ${Math.round(postJump)}`,
        );
        check(
            "split mirror (dst scrollTop moved)",
            Math.abs(postJumpDst - preJumpDst) > 400,
            `${Math.round(preJumpDst)} → ${Math.round(postJumpDst)}`,
        );
        await page.waitForTimeout(400);
        check(
            "nav chip back appears",
            await chipBtn("original", "back")
                .isVisible()
                .catch(() => false),
        );
        await page
            .screenshot({ path: join(SHOTS, "cite-jumped.png") })
            .catch(() => {});

        // ---- 4. ↩ 跳回 ----------------------------------------------------
        await chipBtn("original", "back").click();
        await page.waitForTimeout(900);
        const backPos = await scrollTop("original");
        check(
            "nav-back returns to pre-jump pos",
            Math.abs(backPos - preJump) < 400,
            `pre=${Math.round(preJump)} back=${Math.round(backPos)}`,
        );
        const fwdVisible = await chipBtn("original", "fwd")
            .isVisible()
            .catch(() => false);
        check("nav chip fwd appears", fwdVisible);
        if (fwdVisible) {
            await chipBtn("original", "fwd").click();
            await page.waitForTimeout(900);
            const fwdPos = await scrollTop("original");
            check(
                "nav-fwd returns to jumped pos",
                Math.abs(fwdPos - postJump) < 400,
                `post=${Math.round(postJump)} fwd=${Math.round(fwdPos)}`,
            );
            // 键盘回退:Backspace 弹栈(Alt+← 同路)
            await page.keyboard.press("Backspace");
            await page.waitForTimeout(900);
            const kbPos = await scrollTop("original");
            check(
                "Backspace pops nav stack",
                Math.abs(kbPos - preJump) < 400,
                `pre=${Math.round(preJump)} kb=${Math.round(kbPos)}`,
            );
        }

        // ---- 5. 触屏 tap=出卡不跳 ------------------------------------------
        const anchor2 = await findCiteAnchor("original");
        check("cite anchor re-found for touch", !!anchor2);
        if (anchor2) {
            await anchor2.scrollIntoViewIfNeeded();
            await page.waitForTimeout(400);
            const preTap = await scrollTop("original");
            const bb = await anchor2.boundingBox();
            if (bb) {
                await page.touchscreen.tap(
                    bb.x + bb.width / 2,
                    bb.y + bb.height / 2,
                );
                await page.waitForTimeout(800);
                check(
                    "touch tap opens card",
                    await card.isVisible().catch(() => false),
                );
                const postTap = await scrollTop("original");
                check(
                    "touch tap does NOT jump",
                    Math.abs(postTap - preTap) < 100,
                    `${Math.round(preTap)} → ${Math.round(postTap)}`,
                );
                await page
                    .screenshot({ path: join(SHOTS, "cite-touch.png") })
                    .catch(() => {});
                await page.keyboard.press("Escape");
            }
        }

        // ---- 6. L2 元数据(机会型——S2 可达才验) ------------------------------
        await page.waitForTimeout(4000);
        const anchor3 = await findCiteAnchor("original");
        if (anchor3) {
            await anchor3.scrollIntoViewIfNeeded();
            await anchor3.hover();
            await page.waitForTimeout(900);
            const meta = await page
                .locator(".cite-card-title, .cite-card-sub, .cite-card-tldr")
                .first()
                .isVisible()
                .catch(() => false);
            console.log(`INFO  L2 meta block present: ${meta}`);
            if (await card.isVisible().catch(() => false)) {
                await page
                    .screenshot({ path: join(SHOTS, "cite-card-meta.png") })
                    .catch(() => {});
                await page.keyboard.press("Escape");
            }
        }
        bail();
        check(
            "zero console/page errors",
            errors.length === 0,
            errors.slice(0, 3).join(" | "),
        );
    } finally {
        await browser.close().catch(() => {});
    }
}

for (let attempt = 1; attempt <= 3; attempt++) {
    try {
        await run();
        break;
    } catch (e) {
        console.log(`attempt ${attempt} aborted: ${e.message}`);
        if (attempt === 3)
            check("run completes without crash", false, e.message);
    }
}

const fails = results.filter((r) => !r.ok);
console.log(
    `\n${results.length - fails.length}/${results.length} passed` +
        (fails.length
            ? ` — FAILED: ${fails.map((f) => f.name).join(", ")}`
            : ""),
);
process.exit(fails.length ? 1 : 0);
