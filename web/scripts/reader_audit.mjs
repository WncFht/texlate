// 阅读器全交互审计:面板开闭/主题/导航/进度页 + console 错误捕获
// 用法:node scripts/reader_audit.mjs

import { join } from "node:path";
import { launch, SHOTS } from "./lib/pwkit.mjs";

const BASE = process.env.WEB_BASE ?? "http://127.0.0.1:8765";
const DONE = "t_d7c669e8b3c92149";
const TRANSLATING = "t_25e3f4d173b4db4a";

const browser = await launch();
const ctx = await browser.newContext({
    viewport: { width: 1500, height: 950 },
});
const page = await ctx.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(`PAGEERROR: ${e.message}`));
page.on("console", (m) => {
    if (m.type() === "error") errors.push(`CONSOLE: ${m.text().slice(0, 220)}`);
});

const shot = (n) => page.screenshot({ path: join(SHOTS, `audit-${n}.png`) });
const log = (...a) => console.log(...a);

// ---------- 1. done 任务阅读器 ----------
await page.goto(`${BASE}/#/reader/${DONE}`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".pdfSlickViewer .page canvas", { timeout: 20000 });
await page.waitForTimeout(2500);
await shot("01-reader");

// 枚举 rail 按钮 + 工具栏按钮,逐个开→截图→关→验证消失
const railBtns = await page.evaluate(() =>
    [
        ...document.querySelectorAll(
            ".pane-rail button, .rail button, aside button",
        ),
    ].map((b, i) => ({
        i,
        label:
            b.getAttribute("aria-label") ||
            b.title ||
            b.textContent.trim().slice(0, 20),
        cls: b.className.slice(0, 40),
    })),
);
log("rail buttons:", JSON.stringify(railBtns));

const toolbarBtns = await page.evaluate(() =>
    [
        ...document.querySelectorAll(
            ".reader-toolbar button, .topbar button, header button",
        ),
    ].map(
        (b) =>
            b.getAttribute("aria-label") ||
            b.title ||
            b.textContent.trim().slice(0, 20),
    ),
);
log("toolbar buttons:", JSON.stringify(toolbarBtns));

// ---------- 2. FindBar 开闭 ----------
await page.keyboard.press("Control+f");
await page.waitForTimeout(500);
const findVisible = await page.evaluate(() => {
    const fb = document.querySelector(".findbar, [class*=find]");
    return fb
        ? {
              cls: fb.className,
              visible: fb.offsetParent !== null,
              html: fb.outerHTML.slice(0, 200),
          }
        : null;
});
log("after Ctrl+F:", JSON.stringify(findVisible));
await shot("02-findbar");
// Esc 关
await page.keyboard.press("Escape");
await page.waitForTimeout(400);
const findAfterEsc = await page.evaluate(() => {
    const fb = document.querySelector(".findbar, [class*=find]");
    return fb ? fb.offsetParent !== null : "gone";
});
log("findbar after Esc:", findAfterEsc);
// 关不掉的话试 X 按钮
if (findAfterEsc === true) {
    const x = await page.$(
        ".findbar button, [class*=find] button[aria-label*=关闭], [class*=find] .close",
    );
    if (x) {
        await x.click();
        await page.waitForTimeout(400);
    }
    const still = await page.evaluate(() => {
        const fb = document.querySelector(".findbar, [class*=find]");
        return fb ? fb.offsetParent !== null : "gone";
    });
    log("findbar after X click:", still);
}

// ---------- 3. DocInfo 面板开闭 ----------
const infoBtn = await page.evaluate(() =>
    [...document.querySelectorAll("button")].findIndex((b) =>
        /info|信息|属性|document/i.test(
            b.getAttribute("aria-label") || b.title || b.textContent,
        ),
    ),
);
log("info btn idx:", infoBtn);
// rail 按钮逐个试开/关（只点激活侧 rail——对照模式下非激活侧 display:none）
const RAIL_N = 7; // 缩略图/大纲/附件/查找/文档信息/高亮/带批注下载
for (let i = 0; i < RAIL_N; i++) {
    const sel = `.pane.active .pane-rail button:nth-of-type(${i + 1})`;
    const el = await page.$(sel);
    if (!el) {
        log(`rail[${i}] missing`);
        continue;
    }
    const label = await el.evaluate(
        (n) => n.getAttribute("aria-label") || n.title,
    );
    const dis = await el.evaluate((n) => n.disabled);
    if (dis) {
        log(`rail[${i}] "${label}" disabled, skip`);
        continue;
    }
    try {
        await el.click({ timeout: 3000 });
    } catch (e) {
        log(`rail[${i}] "${label}" click failed: ${e.message.split("\n")[0]}`);
        continue;
    }
    await page.waitForTimeout(500);
    const state = await page.evaluate(() => {
        const open = [
            ...document.querySelectorAll(
                ".pane.active aside:not([hidden]), .pane.active .findbar, .pane.active .docinfo",
            ),
        ]
            .filter((e) => e.offsetParent !== null)
            .map((e) => e.className.slice(0, 50));
        return open;
    });
    log(`click rail[${i}] "${label}":`, JSON.stringify(state));
    await shot(`03-rail-${i}`);
    // 关闭:查找条走 Esc,其余再点一次 toggle
    if (label === "查找") {
        await page.keyboard.press("Escape");
    } else {
        try {
            await el.click({ timeout: 3000 });
        } catch (e) {
            log(`  re-click failed: ${e.message.split("\n")[0]}`);
            continue;
        }
    }
    await page.waitForTimeout(400);
    const after = await page.evaluate(() => {
        const open = [
            ...document.querySelectorAll(
                ".pane.active aside:not([hidden]), .pane.active .docinfo",
            ),
        ]
            .filter((e) => e.offsetParent !== null)
            .map((e) => e.className.slice(0, 50));
        return open;
    });
    log(`  re-click close:`, JSON.stringify(after));
}

// ---------- 4. 主题切换 ----------
for (const want of ["dark", "light"]) {
    await page.evaluate((t) => {
        localStorage.setItem("texlate-theme", t);
        document.documentElement.dataset.theme = t;
    }, want);
    await page.waitForTimeout(1500);
    const avg = await page.evaluate(() => {
        const cv = document.querySelector(".pdfSlickViewer .page canvas");
        if (!cv?.width) return null;
        const d = cv
            .getContext("2d")
            .getImageData(0, 0, cv.width, cv.height).data;
        let s = 0,
            n = 0;
        for (let i = 0; i < d.length; i += 4 * 97) {
            s += 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
            n++;
        }
        return +(s / n).toFixed(1);
    });
    log(`theme ${want}: canvas avg`, avg);
    await shot(`04-theme-${want}`);
}

// ---------- 5. 翻页/缩放 ----------
await page.keyboard.press("PageDown");
await page.waitForTimeout(800);
const pn = await page.evaluate(
    () =>
        document.querySelector("[class*=page-num], .reader-toolbar [type=text]")
            ?.textContent || document.title,
);
log("after PageDown:", pn);
await shot("05-pagedown");

// ---------- 6. partial 任务阅读页 + 横幅折叠 ----------
await page.goto(`${BASE}/#/reader/${TRANSLATING}`, {
    waitUntil: "domcontentloaded",
});
await page.waitForTimeout(3000);
const prog = await page.evaluate(() => ({
    title: document.title,
    bodyText: document.body.innerText.slice(0, 400),
    hasError: !!document.querySelector("[class*=error], .pane-error"),
}));
log("partial page:", JSON.stringify(prog, null, 1));
await shot("06-translating");

// 横幅折叠:全高 → 收起成细条 → 点击展开复原
const banner = await page.$(".result-banner");
if (banner) {
    const h0 = await page.evaluate(
        () => document.querySelector(".result-banner")?.offsetHeight,
    );
    const foldBtn = await page.$(".rb-fold");
    if (foldBtn) {
        await foldBtn.click();
        await page.waitForTimeout(500);
        const f = await page.evaluate(() => {
            const b = document.querySelector(".result-banner");
            return {
                h: b?.offsetHeight,
                folded: b?.classList.contains("folded"),
                text: b?.innerText.trim().slice(0, 60),
            };
        });
        log(`banner fold: ${h0}px →`, JSON.stringify(f));
        await shot("07-banner-folded");
        const line = await page.$(".rb-fold-line");
        if (line) {
            await line.click();
            await page.waitForTimeout(400);
            const h1 = await page.evaluate(
                () => document.querySelector(".result-banner")?.offsetHeight,
            );
            log("banner re-expand:", h1, "px");
        }
    } else {
        log("banner: no .rb-fold button!");
    }
} else {
    log("banner: no .result-banner (task done?)");
}

// ---------- 8. 工具栏全交互(done 任务) ----------
await page.goto(`${BASE}/#/reader/${DONE}`, { waitUntil: "domcontentloaded" });
await page.waitForSelector(".pdfSlickViewer .page canvas", { timeout: 20000 });
await page.waitForTimeout(2000);

// 模式 segmented:对照 → 译文 → 原文 → 导读 → 对照
for (const m of ["译文", "原文", "导读", "对照"]) {
    const btn = await page.evaluateHandle(
        (label) =>
            [...document.querySelectorAll("button")].find(
                (b) => b.textContent.trim() === label,
            ),
        m,
    );
    const el = btn.asElement();
    if (!el) {
        log(`mode "${m}" button missing`);
        continue;
    }
    await el.click();
    await page.waitForTimeout(900);
    const cls = await page.evaluate(
        () => document.querySelector(".panes")?.className,
    );
    log(`mode ${m}: .panes =`, cls);
}
await shot("08-mode-split");

// 同步滚动 / 左右互换
for (const label of ["⇅ 同步滚动", "⇄ 左右互换"]) {
    const el = await page.evaluateHandle(
        (l) =>
            [...document.querySelectorAll("button")].find((b) =>
                b.textContent.trim().includes(l.slice(2)),
            ),
        label,
    );
    const b = el.asElement();
    if (!b) {
        log(`toolbar "${label}" missing`);
        continue;
    }
    await b.click();
    await page.waitForTimeout(500);
}
const swapState = await page.evaluate(
    () => document.querySelector(".panes")?.className,
);
log("after sync toggle + swap:", swapState);
await shot("09-swapped");
// 复位
await page.evaluate(() =>
    [...document.querySelectorAll("button")]
        .find((b) => b.textContent.trim().includes("左右互换"))
        ?.click(),
);
await page.evaluate(() =>
    [...document.querySelectorAll("button")]
        .find((b) => b.textContent.trim().includes("同步滚动"))
        ?.click(),
);
await page.waitForTimeout(300);

// 缩放 select
const zoomOk = await page.evaluate(() => {
    const sel = [...document.querySelectorAll("select")].find(
        (s) => s.options.length > 2,
    );
    if (!sel) return "no select";
    sel.value = "page-fit";
    sel.dispatchEvent(new Event("change", { bubbles: true }));
    return sel.value;
});
await page.waitForTimeout(1200);
log("zoom set:", zoomOk);

// 页码输入跳页
await page.evaluate(() => {
    const inp = document.querySelector(".tb-page input");
    if (inp) {
        inp.value = "3";
        inp.dispatchEvent(new Event("input", { bubbles: true }));
        inp.dispatchEvent(
            new KeyboardEvent("keydown", { key: "Enter", bubbles: true }),
        );
    }
});
await page.waitForTimeout(1200);
const pageNow = await page.evaluate(
    () => document.querySelector(".tb-page input")?.value,
);
log("goto page 3 →", pageNow);
await shot("10-page3");

// 更多菜单:开 → Esc 关
await page.evaluate(() =>
    [...document.querySelectorAll("button")]
        .find((b) => b.getAttribute("aria-label") === "更多")
        ?.click(),
);
await page.waitForTimeout(400);
const menuOpen = await page.evaluate(
    () => !!document.querySelector(".tb-menu"),
);
await shot("11-more-menu");
await page.keyboard.press("Escape");
await page.waitForTimeout(300);
const menuAfter = await page.evaluate(
    () => !!document.querySelector(".tb-menu"),
);
log("more menu:", menuOpen, "→ Esc:", menuAfter);

// 帮助弹层:开 → Esc 关
await page.evaluate(() =>
    [...document.querySelectorAll("button")]
        .find((b) => b.textContent.trim() === "?")
        ?.click(),
);
await page.waitForTimeout(400);
const helpOpen = await page.evaluate(
    () => !!document.querySelector(".kbd-help"),
);
await shot("12-help");
await page.keyboard.press("Escape");
await page.waitForTimeout(300);
const helpAfter = await page.evaluate(
    () => !!document.querySelector(".kbd-help"),
);
log("help dialog:", helpOpen, "→ Esc:", helpAfter);

// 分享弹层(done + arxiv 源):开 → 外部点击关
const shareBtn = await page.evaluateHandle(() =>
    [...document.querySelectorAll("button")].find((b) =>
        b.textContent.trim().startsWith("⇧"),
    ),
);
const sb = shareBtn.asElement();
if (sb) {
    await sb.click();
    await page.waitForTimeout(500);
    const pop = await page.evaluate(
        () => !!document.querySelector(".share-pop"),
    );
    await shot("13-share-pop");
    await page.mouse.click(750, 600);
    await page.waitForTimeout(400);
    const popAfter = await page.evaluate(
        () => !!document.querySelector(".share-pop"),
    );
    log("share pop:", pop, "→ outside click:", popAfter);
} else {
    log("share button missing");
}

// 下载菜单:开 → Esc 关
const dlBtn = await page.evaluateHandle(() =>
    [...document.querySelectorAll("button")].find((b) =>
        b.textContent.trim().includes("下载"),
    ),
);
const db = dlBtn.asElement();
if (db) {
    await db.click();
    await page.waitForTimeout(400);
    const dlOpen = await page.evaluate(
        () => !!document.querySelector(".tb-menu"),
    );
    await shot("14-dl-menu");
    await page.keyboard.press("Escape");
    await page.waitForTimeout(300);
    const dlAfter = await page.evaluate(
        () => !!document.querySelector(".tb-menu"),
    );
    log("download menu:", dlOpen, "→ Esc:", dlAfter);
} else {
    log("download button missing");
}

log("\n=== console/page errors ===");
errors.forEach((e) => log(e));
log(errors.length ? `${errors.length} errors` : "no errors");
await browser.close();
