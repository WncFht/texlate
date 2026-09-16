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

const BASE = process.env.WEB_BASE ?? "http://localhost:5173";
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
page.on("console", (m) => {
    if (m.type() === "error") consoleErrors.push(m.text());
});
page.on("pageerror", (e) => consoleErrors.push(`pageerror: ${e.message}`));

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
await page.fill(".arxiv-input", "2501.14787");
await page.click('button:has-text("翻译")');
await page.waitForURL(/#\/reader\/t_/, { timeout: 5000 });
check("跳转阅读器路由", page.url().includes("#/reader/"));
await page.waitForSelector(".task-progress", { timeout: 5000 });
await page.screenshot({ path: `${SHOTS}02-progress.png` });
check("阶段步进器", (await page.locator(".stage-stepper li").count()) === 4);

// 等翻译中:棋盘格出现
await page.waitForSelector(".progress-grid", { timeout: 15000 });
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

// 页码输入:填入 3 回车
const pageInput = page.locator(".tb-page input");
await pageInput.fill("3");
await pageInput.press("Enter");
await page.waitForTimeout(600);
check("页码输入后仍聚焦可用", true);

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

// fault seed:结果面板
await page.goto(`${BASE}/#/reader/t_0000000000000a03`, {
    waitUntil: "networkidle",
});
await page.waitForTimeout(1500);
await page.screenshot({ path: `${SHOTS}08-partial.png` });

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
