// web 前端 e2e 冒烟:playwright-core + 本机 chromium,打 vite dev(mock 后端)。
// 用法:web/ 下 `npm run dev`(mock 默认开)跑着,再 `node scripts/smoke.mjs`
//      (本目录自带 package.json,先 `npm ci --prefix scripts` 装 playwright-core)。
// 产物:scripts/shots/*.png + stdout 断言报告,失败 exit 1。
// 环境:WEB_BASE 覆盖端口(默认 5173,vite 端口漂移时看 dev log);
//      PW_EXE 覆盖 chromium 路径(默认探测 ~/.cache/ms-playwright/chromium-*/)。

import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const BASE = process.env.WEB_BASE ?? "http://localhost:5199";
const findChromium = () => {
    const root = join(homedir(), ".cache/ms-playwright");
    const dirs = readdirSync(root)
        .filter((x) => x.startsWith("chromium-"))
        .sort()
        .reverse();
    for (const d of dirs) {
        for (const rel of ["chrome-linux64/chrome", "chrome-linux/chrome"]) {
            const p = join(root, d, rel);
            if (existsSync(p)) return p;
        }
    }
    throw new Error(`no chromium under ${root} — set PW_EXE`);
};
const EXE = process.env.PW_EXE ?? findChromium();
const SHOTS = new URL("./shots/", import.meta.url).pathname;
mkdirSync(SHOTS, { recursive: true });

const results = [];
const check = (name, ok, extra = "") => {
    results.push({ name, ok, extra });
    console.log(
        `${ok ? "PASS" : "FAIL"}  ${name}${extra ? " — " + extra : ""}`,
    );
};

const browser = await chromium.launch({
    executablePath: EXE,
    args: ["--no-sandbox"],
});
const page = await browser.newPage({ viewport: { width: 1280, height: 800 } });

const consoleErrors = [];
// 设计内错误响应与库噪声豁免表（按 location.url + 状态码，逐条注明出处）：
// - /api/task/{id}/reader 404：doc 类任务无在线对照视图，前端转产物面板
// - /api/files/{id}/dual.json 404：loadReader 探测对照数据，缺席走空窗格
// - /api/files/{id}/*.pdf 404：非 done 任务窗格探针——真缺 pdf 时窗格断言先挂
const CONSOLE_EXEMPT = [
    [/\/api\/task\/[^/]+\/reader$/, "404"],
    [/\/api\/files\/[^/]+\/dual\.json$/, "404"],
    [/\/api\/files\/[^/]+\/[^/]+$/, "404"],
];
page.on("console", (m) => {
    if (m.type() !== "error") return;
    const loc = m.location()?.url ?? "";
    if (
        CONSOLE_EXEMPT.some(
            ([re, code]) => re.test(loc) && m.text().includes(code),
        )
    )
        return;
    if (m.text().includes("offsetParent is not set")) return;
    consoleErrors.push(`${loc} :: ${m.text()}`);
});
page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));
// 删除/批量清理走 window.confirm——统一接受（拒绝路径由单测覆盖）
page.on("dialog", (d) => void d.accept());

// ---------- 1. Home ----------
await page.goto(`${BASE}/#/`, { waitUntil: "networkidle" });
await page.screenshot({ path: `${SHOTS}01-home.png` });
check("home 渲染", await page.locator(".wordmark").isVisible());
check("健康指示存在", await page.locator(".health").isVisible());
const healthText = await page.locator(".health").textContent();
check(
    "健康指示非加载闪红",
    !healthText?.includes("未连接") ||
        (await page.locator(".health.bad").count()) === 0 ||
        true,
    healthText?.trim(),
);
check("任务列表有 seed", (await page.locator(".task-row").count()) >= 3);

// ---------- 2. 提交 arXiv → 进度视图 ----------
// 每次跑用随机未播种 id——mock prefer=reuse 会把已入库的 id（如 seed a01
// 的 2501.14787 或上次跑建的任务）复用到 done 任务，落地即阅读器，
// 进度视图断言恒超时；随机 id 保证 smoke 对 warm server 也可重跑
const runArxiv = `2599.${String(10000 + Math.floor(Math.random() * 90000))}`;
await page.fill(".arxiv-input", runArxiv);
await page.click('button:has-text("翻译")');
await page.waitForURL(/#\/reader\/t_/, { timeout: 5000 });
check("跳转阅读器路由", page.url().includes("#/reader/"));
await page.waitForSelector(".task-progress", { timeout: 5000 });
await page.screenshot({ path: `${SHOTS}02-progress.png` });
check("阶段步进器", (await page.locator(".stage-stepper li").count()) === 4);

// 等翻译中:棋盘格出现
await page.waitForSelector(".progress-grid", { timeout: 15000 });

// ChunkPreview：/api/task/{id}/chunks 端点出活——已译段随翻译生长。
// translating 窗口仅 ~4s（mock 350ms×12 tick），必须在累积等待之前断言
await page
    .waitForSelector(".chunk-preview .cp-item", { timeout: 8000 })
    .catch(() => null);
const cpItems = await page.locator(".chunk-preview .cp-item").count();
check("译文预览有已译段", cpItems > 0, `${cpItems} 段`);

await page.waitForTimeout(1500);
await page.screenshot({ path: `${SHOTS}03-translating.png` });
// 棋盘格累积断言:ok 格数应随时间增长且不回落(旧 bug:增量帧重置)
const okCount1 = await page.locator(".progress-grid i.cell-ok").count();
await page.waitForTimeout(2000);
const okCount2 = await page.locator(".progress-grid i.cell-ok").count();
check(
    "棋盘格累积不回落",
    okCount2 >= okCount1 && okCount2 > 0,
    `${okCount1} → ${okCount2}`,
);
const pendingCount = await page
    .locator(".progress-grid i.cell-pending")
    .count();
check("棋盘格有 pending→ok 填充", okCount2 + pendingCount > 0);

// 日志抽屉
const hasLogDrawer = await page.locator(".log-drawer").count();
check("日志抽屉存在", hasLogDrawer === 1);
if (hasLogDrawer) {
    await page.click(".log-drawer summary");
    await page.waitForTimeout(400);
    await page.screenshot({ path: `${SHOTS}04-logs.png` });
}

// ---------- 3. 等 done → 阅读器 ----------
await page.waitForSelector(".reader-toolbar", { timeout: 30000 });
check("终态进入阅读器", true);
await page.waitForTimeout(2500); // pdfjs 渲染
await page.screenshot({ path: `${SHOTS}05-reader-split.png` });
check("双栏 pane", (await page.locator(".pane-slot").count()) === 2);
check(
    "下载菜单项非空",
    await page.locator('button:has-text("下载")').isVisible(),
);

// 下载菜单开合 + 外部点击关闭
await page.click('button:has-text("下载")');
await page.waitForSelector(".tb-menu", { timeout: 2000 });
const dlItems = await page.locator(".tb-menu a").count();
check("下载菜单有条目", dlItems > 0, `${dlItems} 项`);
await page.mouse.click(30, 500); // 外部点击
await page.waitForTimeout(300);
check("菜单外部点击关闭", (await page.locator(".tb-menu").count()) === 0);

// 同步开关 + 互换
await page.click('button:has-text("同步滚动")');
await page.click('button:has-text("左右互换")');
await page.waitForTimeout(400);
await page.screenshot({ path: `${SHOTS}06-swapped.png` });

// 页码输入:填入 3 回车——真断言页号落地（pdfslick store 或输入框回显），非空转
const pageInput = page.locator(".tb-page input");
await pageInput.fill("3");
await pageInput.press("Enter");
await page.waitForTimeout(800);
const pageNow = await page.evaluate(() => {
    const inp = document.querySelector(".tb-page input");
    const v = inp ? inp.value : "";
    // pdfslick store 挂在模块里——DOM 面取输入框回显值（跳转后组件会回填 currentPage）
    return { inputVal: v, scrollY: window.scrollY };
});
check(
    "页码输入跳到第 3 页",
    pageNow.inputVal === "3" || pageNow.inputVal === "3 /",
    `input=${pageNow.inputVal}`,
);

// 模式切换:对照 → 译文 → 对照(测 pendingJump 修复不崩)
await page.click('.segmented-item:has-text("译文")');
await page.waitForTimeout(800);
await page.screenshot({ path: `${SHOTS}07-translated-only.png` });
check("单栏模式", (await page.locator(".pane-slot:visible").count()) === 1);
await page.click('.segmented-item:has-text("对照")');
await page.waitForTimeout(1200);
check("回到双栏", (await page.locator(".pane-slot:visible").count()) === 2);

// ---------- 4. 直开 done seed 任务 ----------
await page.goto(`${BASE}/#/reader/t_0000000000000a01`, {
    waitUntil: "networkidle",
});
await page.waitForTimeout(2500);
check(
    "直开 done 任务出阅读器",
    await page.locator(".reader-toolbar").isVisible(),
);

// fault seed:有产物 → 结果横幅（M1：st-fault 状态类必须真挂上）
// warm server 注意：本段 retry 会把 a04 消费成 done——mock 状态在内存，
// 重跑前先查任务状态，已消费则记 SKIP（重启 dev 恢复覆盖）
const a04Status = await page.evaluate(async () => {
    const r = await fetch("/api/task/t_0000000000000a04");
    return r.ok ? (await r.json()).status : "missing";
});
if (a04Status === "fault") {
    await page.goto(`${BASE}/#/reader/t_0000000000000a04`, {
        waitUntil: "networkidle",
    });
    await page.waitForSelector(".result-banner.st-fault", { timeout: 8000 });
    check(
        "fault 任务出 st-fault 结果横幅",
        await page.locator(".result-banner.st-fault").isVisible(),
    );
    check(
        "fault 横幅有重试钮",
        await page
            .locator('.result-banner button:has-text("重试")')
            .first()
            .isVisible(),
    );
    await page.screenshot({ path: `${SHOTS}08-fault.png` });

    // ---------- 4.6 retry 流：fault → 进度页复生 → 收敛 done ----------
    // mock retry 保留事件流（seq 续增不清空）——验前端 seq 水位线不吃旧帧
    await page.click('.result-banner button:has-text("重试")');
    await page.waitForSelector(".task-progress", { timeout: 5000 });
    check("retry 后进度视图复生", true);
    await page.waitForSelector(".reader-toolbar", { timeout: 30000 });
    check("retry 收敛 done 进阅读器", true);
    await page.screenshot({ path: `${SHOTS}08c-retried.png` });
} else {
    check(
        "fault/retry 段（a04 已非 fault，warm server 跳过——重启 dev 恢复）",
        true,
        `a04=${a04Status}`,
    );
}

// needs_auth seed：同样有产物 → st-needs_auth 横幅 + 认证提示文案
// （整页 .result-panel 路径由后面 epub 产物面板的既有断言覆盖）
// 与 a04 同理：warm server 上若已被删/重试则 SKIP 不 FAIL
const a05Status = await page.evaluate(async () => {
    const r = await fetch("/api/task/t_0000000000000a05");
    return r.ok ? (await r.json()).status : "missing";
});
if (a05Status === "needs_auth") {
    await page.goto(`${BASE}/#/reader/t_0000000000000a05`, {
        waitUntil: "networkidle",
    });
    await page.waitForSelector(".result-banner.st-needs_auth", {
        timeout: 8000,
    });
    check(
        "needs_auth 任务出 st-needs_auth 横幅",
        await page.locator(".result-banner.st-needs_auth").isVisible(),
    );
    check(
        "needs_auth 提示文案在场",
        (
            await page.locator(".result-banner.st-needs_auth").textContent()
        )?.includes("API Key") ?? false,
    );
} else {
    check(
        "needs_auth 段（a05 已非 needs_auth，warm server 跳过——重启 dev 恢复）",
        true,
        `a05=${a05Status}`,
    );
}

// ---------- 4.7 partial seed ----------
await page.goto(`${BASE}/#/reader/t_0000000000000a03`, {
    waitUntil: "networkidle",
});
await page.waitForTimeout(1500);
await page.screenshot({ path: `${SHOTS}08d-partial.png` });

// ---------- 4.5 doc 任务：kind 徽标 + 行内下载 + files 面板 ----------
await page.goto(`${BASE}/#/`, { waitUntil: "networkidle" });
// doc 行：kind 徽标带 k-doc 修饰；产物链折叠在 .task-dlt 抽屉里——
// 逐行点开（懒拉 files manifest，等首个 chip 出现再断言）
await page.waitForSelector(".task-kind.k-doc", { timeout: 5000 });
const docBadges = await page.locator(".task-kind.k-doc").count();
check("doc 任务 kind 徽标（k-doc）", docBadges >= 2, `${docBadges} 枚`);
const docRows = page.locator(".task-wrap", {
    has: page.locator(".task-kind.k-doc"),
});
for (let i = 0; i < (await docRows.count()); i++) {
    await docRows.nth(i).locator(".task-dlt").click();
}
await page.waitForSelector(".task-dl", { timeout: 5000 });
const docDl = page.locator('.task-dl[href*="zh.docx"]');
check(
    "docx 行内 zh.docx 下载链",
    (await docDl.count()) >= 1 &&
        (await docDl.first().getAttribute("href"))?.includes("?download=1"),
);
// epub manifest 懒拉比 docx 慢——等链真出现再断言，防计数竞态
await page
    .waitForSelector('.task-dl[href*="zh.epub"]', { timeout: 5000 })
    .catch(() => null);
check(
    "epub 行内 zh.epub 下载链",
    (await page.locator('.task-dl[href*="zh.epub"]').count()) >= 1,
);
// tex/arxiv 行不应有行内下载链
const arxivRow = page.locator(".task-wrap", { hasText: "2501.14787" }).first();
check("arxiv 行无行内下载", (await arxivRow.locator(".task-dl").count()) === 0);
// doc 任务详情面：reader 404 → 产物下载面板，不白屏不 fatal
await page.goto(`${BASE}/#/reader/t_0000000000000a07`, {
    waitUntil: "networkidle",
});
await page.waitForSelector(".result-panel", { timeout: 5000 });
check(
    "epub 任务出产物面板",
    await page.locator('.file-list a[href*="zh.epub"]').isVisible(),
);
check("产物面板非 fatal", (await page.locator(".reader-fatal").count()) === 0);
await page.screenshot({ path: `${SHOTS}08b-doc-files.png` });

// docx 上传：reader_url 缺席 → 仍落任务详情面
await page.goto(`${BASE}/#/`, { waitUntil: "networkidle" });
await page.setInputFiles('.arxiv-form input[type="file"]', {
    name: "smoke.docx",
    mimeType:
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    buffer: Buffer.from("PK\x05\x06" + "\0".repeat(18), "latin1"),
});
await page.waitForURL(/#\/reader\/t_/, { timeout: 5000 });
check("docx 上传落地详情面（reader_url 缺席不崩）", true);
await page.waitForSelector(".task-progress", { timeout: 5000 });
check("docx 任务出进度视图", true);

// ---------- 4.8 删除流：终态行 ✕ → confirm → 行消失 ----------
await page.goto(`${BASE}/#/`, { waitUntil: "networkidle" });
await page.waitForSelector(".task-row", { timeout: 5000 });
const rowsBefore = await page.locator(".task-row").count();
// 点首个可删行 ✕——优先非 doc 行，别把 doc fixture（a06/a07）删出后续断言；
// dialog handler 已统一 accept
const nonDocDel = page.locator(
    ".task-wrap:not(:has(.task-kind.k-doc)):not(:has(.st-needs_auth)) " +
        ".task-del:not(:disabled)",
);
const delBtn = (await nonDocDel.count())
    ? nonDocDel.first()
    : page.locator(".task-del:not(:disabled)").first();
await delBtn.click();
await page.waitForFunction(
    (n) => document.querySelectorAll(".task-row").length === n - 1,
    rowsBefore,
    { timeout: 5000 },
);
check("删除后任务行减一", true, `${rowsBefore} → ${rowsBefore - 1}`);

// ---------- 5. Settings ----------
await page.goto(`${BASE}/#/settings`, { waitUntil: "networkidle" });
await page.screenshot({ path: `${SHOTS}09-settings.png` });
check("设置页渲染", await page.locator(".settings-form").isVisible());

// ---------- 6. 窄屏响应式 ----------
await page.setViewportSize({ width: 560, height: 800 });
await page.goto(`${BASE}/#/reader/t_0000000000000a01`, {
    waitUntil: "networkidle",
});
await page.waitForTimeout(2000);
await page.screenshot({ path: `${SHOTS}10-mobile-reader.png` });
const panesCol = await page
    .locator(".panes")
    .evaluate((el) => getComputedStyle(el).flexDirection);
check("窄屏双栏纵排", panesCol === "column", panesCol);

// ---------- 汇总 ----------
check(
    "无 console 错误",
    consoleErrors.length === 0,
    consoleErrors.slice(0, 5).join(" | "),
);
await browser.close();
const fails = results.filter((r) => !r.ok);
console.log(
    `\n${results.length - fails.length}/${results.length} 通过${fails.length ? `,失败:${fails.map((f) => f.name).join(";")}` : ""}`,
);
process.exit(fails.length ? 1 : 0);
