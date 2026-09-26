// floor_verify —— web 前端「验收地板」（motion-web verify_case.py 移植，
// 剪裁到 app UI）。腿腿分立 PASS/WARN/FAIL，不合成分数——复合质量分
// 会把「不喜欢」变成「测试通过」，比没测更糟（verification-harness §0）。
//
// 轻路由腿（#/ #/tasks #/discover #/settings，每条编码一个具体投诉）：
//   errors    加载+驻留期 pageerror/console.error → FAIL
//   overflow  320/375/414/768/1440 任一档横向溢出 → FAIL
//   tokens    样式表 var(--x) 无 fallback 引用但 --x 无定义 → FAIL
//             （stray */ 吞掉 :root 块、clamp + 缺空格丢声明同款死法）
//   ground    html/body 计算底色全透明 → WARN（app 可在 wrapper 上画）
//   landmark  main/[role=main] 缺失或 h1 ≠ 1 → WARN
//   live      真 wheel 无可滚区 + 真 hover 首个可交互件无响应 → WARN
// reader 模式（--reader [taskId]，默认 mock 种子 t_0000000000000a01）追加：
//   probe     window.__saAnim 探针缺席 → FAIL
//   anim      demo() 走真 land → hold 中间帧 dashoffset 介于两端 +
//             两帧截图像素不同 → release 后自清。
//             全链 FAIL 即「动效是硬切」——终态断言抓不到这种死法。
//
// 用法（web/scripts/ 下）：
//   npm run dev 起 mock（端口 5199），再 node scripts/floor_verify.mjs
//   node scripts/floor_verify.mjs --reader              # + mock 种子 reader 腿
//   WEB_BASE=http://127.0.0.1:8765 node scripts/floor_verify.mjs --reader t_xxx
//   PW_EXE 覆盖 chromium（默认探测 ~/.cache/ms-playwright/chromium-*/）。

import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const BASE = process.env.WEB_BASE ?? "http://localhost:5199";
const ridx = process.argv.indexOf("--reader");
const READER =
    ridx < 0
        ? null
        : (process.argv[ridx + 1] ?? "t_0000000000000a01");

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

let fails = 0;
const leg = (route, name, state, detail = "") => {
    if (state === "FAIL") fails++;
    console.log(
        `${state.padEnd(4)}  ${route.padEnd(9)} ${name.padEnd(9)} ${detail}`,
    );
};

const ROUTES = [
    ["home", "#/"],
    ["tasks", "#/tasks"],
    ["discover", "#/discover"],
    ["settings", "#/settings"],
];
const WIDTHS = [320, 375, 414, 768, 1440];

// errors 豁免表——设计内错误响应，逐条注明出处（与 smoke.mjs:48-56 同源）：
// - /api/task/{id}/reader 404：doc 类任务无在线对照视图，前端转产物面板
// - /api/files/{id}/dual.json 404：loadReader 探测对照数据，缺席走空窗格
// - /api/files/{id}/*.pdf 404：非 done 任务窗格探针
// - /api/discover/* 404：mock 不覆盖 alphaXiv 代理面——机会型增强缺席整块隐藏
// - /api/task/{id}/refs/kept 404：mock 未覆盖 kept 收藏面——前端容错空集
const EXEMPT_RESPONSES = [
    [/\/api\/task\/[^/]+\/reader$/, "404"],
    [/\/api\/files\/[^/]+\/dual\.json$/, "404"],
    [/\/api\/files\/[^/]+\/[^/]+$/, "404"],
    [/\/api\/discover\//, "404"],
    [/\/api\/task\/[^/]+\/refs\/kept$/, "404"],
];
const exempt = (url, status) =>
    EXEMPT_RESPONSES.some(([re, st]) => re.test(url) && String(status) === st);

// tokens 归属判定——var(--x) 无 fallback 引用且 --x 无定义时，若引用全部
// 来自 vendored 样式表（data-vite-dev-id/href 含 node_modules/pdf_viewer），
// 是上游主题钩子（pdfslick dist 不船 :root 块、宿主负责）→ WARN 豁免；
// 只要有一处来自 app 样式 → FAIL（stray */ 吞 :root / clamp 缺空格丢声明）。
const VENDOR_ORIGIN = /node_modules|pdf_viewer|pdfslick/;

const browser = await chromium.launch({
    executablePath: EXE,
    args: ["--no-sandbox"],
});

/** pageerror/console 真错 + 非豁免 4xx/5xx 响应收集（response 按 URL
    归因——console 的「Failed to load resource」不带 URL，跳过）。 */
const watchErrors = (page, errs) => {
    page.on("pageerror", (e) => errs.push(`pageerror: ${e.message}`));
    page.on("console", (m) => {
        if (
            m.type() === "error" &&
            !/Failed to load resource/.test(m.text())
        )
            errs.push(m.text());
    });
    page.on("response", (r) => {
        const s = r.status();
        if (s >= 400 && !exempt(r.url(), s))
            errs.push(`${s} ${r.url()}`);
    });
};

/** 每路由共享的页面级腿。 */
async function floorLegs(route, hash) {
    const page = await browser.newPage({
        viewport: { width: 1280, height: 800 },
    });
    const errs = [];
    watchErrors(page, errs);
    try {
        await page.goto(`${BASE}/${hash}`, {
            waitUntil: "domcontentloaded",
            timeout: 15000,
        });
        await page.waitForTimeout(1500);
    } catch (e) {
        leg(route, "load", "FAIL", `goto ${hash}: ${e.message}`);
        await page.close();
        return;
    }

    leg(
        route,
        "errors",
        errs.length ? "FAIL" : "PASS",
        errs.slice(0, 3).join(" | ") || "clean",
    );

    // overflow——逐档宽度，documentElement/body 双测防 overflow-x:hidden 遮丑
    const badW = [];
    for (const w of WIDTHS) {
        await page.setViewportSize({ width: w, height: 800 });
        await page.waitForTimeout(300);
        const ov = await page.evaluate(
            () =>
                Math.max(
                    document.documentElement.scrollWidth,
                    document.body?.scrollWidth ?? 0,
                ) - innerWidth,
        );
        if (ov > 1) badW.push(`${w}px +${ov}`);
    }
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.waitForTimeout(200);
    leg(
        route,
        "overflow",
        badW.length ? "FAIL" : "PASS",
        badW.length ? badW.join(" ") : `${WIDTHS.length} 档无横溢`,
    );

    // tokens——无 fallback 的 var() 引用按样式表归属：
    // dev 下 vite 给 <style> 打 data-vite-dev-id 源路径；build 产物用 href。
    const tk = await page.evaluate((vendorRe) => {
        const vend = new RegExp(vendorRe);
        const origin = (s) =>
            s.ownerNode?.dataset?.viteDevId ??
            s.href ??
            "(inline)";
        const usedBy = new Map(); // var → Set<origin>
        const defined = new Set();
        const walk = (rs, org) => {
            for (const r of rs) {
                if (r.cssRules?.length) walk(r.cssRules, org);
                const css = r.cssText ?? "";
                for (const m of css.matchAll(
                    /var\(\s*(--[\w-]+)\s*(\)|,)/g,
                )) {
                    if (m[2] === ")") {
                        if (!usedBy.has(m[1])) usedBy.set(m[1], new Set());
                        usedBy.get(m[1]).add(org);
                    }
                }
                for (const m of css.matchAll(/(--[\w-]+)\s*:/g)) {
                    defined.add(m[1]);
                }
            }
        };
        for (const s of document.styleSheets) {
            const org = origin(s);
            try {
                walk(s.cssRules, org);
            } catch {
                /* 跨域样式表跳过 */
            }
        }
        const missing = [];
        const vendored = [];
        for (const [v, orgs] of usedBy) {
            if (defined.has(v)) continue;
            ([...orgs].every((o) => vend.test(o)) ? vendored : missing)
                .push(v);
        }
        return {
            missing,
            vendored,
            used: usedBy.size,
            defined: defined.size,
        };
    }, VENDOR_ORIGIN.source);
    leg(
        route,
        "tokens",
        tk.missing.length ? "FAIL" : "PASS",
        tk.missing.length
            ? `未定义引用 ${tk.missing.slice(0, 5).join(" ")}`
            : `${tk.used} 引用 / ${tk.defined} 定义` +
                  (tk.vendored.length
                      ? `（vendored 钩子豁免 ${tk.vendored.length}）`
                      : ""),
    );

    const g = await page.evaluate(() => {
        const bg = (el) => getComputedStyle(el).backgroundColor;
        const t = (c) =>
            c === "transparent" || c === "rgba(0, 0, 0, 0)";
        return {
            html: bg(document.documentElement),
            body: bg(document.body),
            clear: t(bg(document.documentElement)) &&
                t(bg(document.body)),
        };
    });
    leg(
        route,
        "ground",
        g.clear ? "WARN" : "PASS",
        g.clear
            ? "html/body 全透明——底色得有人画"
            : `body ${g.body}`,
    );

    const lm = await page.evaluate(() => ({
        main: document.querySelectorAll('main, [role="main"]').length,
        h1: document.querySelectorAll("h1").length,
    }));
    leg(
        route,
        "landmark",
        lm.main === 0 || lm.h1 !== 1 ? "WARN" : "PASS",
        `main×${lm.main} h1×${lm.h1}`,
    );

    // live——真滚轮必须滚得动某个区；真 hover 首个可交互件须有样式响应
    const scrollable = await page.evaluate(() => {
        const cands = [
            document.scrollingElement,
            ...document.querySelectorAll(
                ".scroll, [class*='scroll'], .pane, main, .list, " +
                    "[style*='overflow']",
            ),
        ];
        for (const el of cands) {
            if (
                el instanceof HTMLElement &&
                el.scrollHeight > el.clientHeight + 10
            ) {
                const r = el.getBoundingClientRect();
                if (r.width && r.height)
                    return {
                        x: r.x + r.width / 2,
                        y: r.y + r.height / 2,
                    };
            }
        }
        return null;
    });
    let wheelOk = false;
    if (scrollable) {
        const before = await page.evaluate(() => ({
            y: scrollY,
            tops: [
                ...document.querySelectorAll(
                    ".scroll, [class*='scroll'], .pane, main",
                ),
            ]
                .filter((e) => e.scrollHeight > e.clientHeight + 10)
                .map((e) => e.scrollTop)
                .join(","),
        }));
        await page.mouse.move(scrollable.x, scrollable.y);
        await page.mouse.wheel(0, 360);
        await page.waitForTimeout(350);
        const after = await page.evaluate(() => ({
            y: scrollY,
            tops: [
                ...document.querySelectorAll(
                    ".scroll, [class*='scroll'], .pane, main",
                ),
            ]
                .filter((e) => e.scrollHeight > e.clientHeight + 10)
                .map((e) => e.scrollTop)
                .join(","),
        }));
        wheelOk = before.y !== after.y || before.tops !== after.tops;
    }
    const hovH = await page.evaluateHandle(() => {
        const el = document.querySelector(
            'button:not([disabled]),a[href],[role="button"],' +
                "input,select,textarea",
        );
        return el instanceof HTMLElement && el.getBoundingClientRect().width
            ? el
            : null;
    });
    const hovEl = hovH.asElement();
    let hoverOk = false;
    let hovDetail = "无可交互件";
    if (hovEl) {
        const box = await hovEl.boundingBox();
        const snapOf = (h) =>
            h.evaluate((el) => {
                const cs = getComputedStyle(el);
                return `${cs.cursor}|${cs.color}|${cs.backgroundColor}|` +
                    `${cs.textDecorationLine}|${cs.outlineStyle}`;
            });
        const s1 = await snapOf(hovEl);
        await page.mouse.move(
            box.x + box.width / 2,
            box.y + box.height / 2,
        );
        await page.waitForTimeout(250);
        const s2 = await snapOf(hovEl);
        const cursor = await page.evaluate(
            (p) => {
                const el = document.elementFromPoint(p.x, p.y);
                const it = el?.closest(
                    'button,a,[role="button"],input,select,textarea',
                );
                return it ? getComputedStyle(it).cursor : "";
            },
            { x: box.x + box.width / 2, y: box.y + box.height / 2 },
        );
        // 样式响应，或命中件 pointer cursor——设计好的 affordance 也算响应
        hoverOk = s1 !== s2 || cursor === "pointer";
        hovDetail = s1 !== s2 ? "样式有应" : `cursor=${cursor}`;
    }
    await hovH.dispose();
    leg(
        route,
        "live",
        wheelOk || hoverOk ? "PASS" : "WARN",
        `wheel ${scrollable ? (wheelOk ? "ok" : "无响应") : "无可滚区"} ` +
            `hover ${hoverOk ? "ok" : hovDetail}`,
    );

    await page.close();
}

for (const [route, hash] of ROUTES) await floorLegs(route, hash);

// ---------- reader 模式：探针面 + 真动效中间帧 ----------
if (READER) {
    const route = "reader";
    const page = await browser.newPage({
        viewport: { width: 1280, height: 800 },
    });
    const errs = [];
    watchErrors(page, errs);
    try {
        await page.goto(`${BASE}/#/reader/${READER}`, {
            waitUntil: "domcontentloaded",
            timeout: 20000,
        });
        await page.waitForSelector(".pane", { timeout: 15000 });
        await page.waitForTimeout(1200);
    } catch (e) {
        leg(route, "load", "FAIL", `reader/${READER}: ${e.message}`);
        await page.close();
        await browser.close();
        process.exit(1);
    }
    leg(
        route,
        "errors",
        errs.length ? "FAIL" : "PASS",
        errs.slice(0, 3).join(" | ") || "clean",
    );

    const hasProbe = await page.evaluate(
        () => typeof window.__saAnim === "object",
    );
    leg(route, "probe", hasProbe ? "PASS" : "FAIL", "__saAnim");

    if (hasProbe) {
        // landTimer 1100ms 实钟自清——本条腿必须在该窗内打完
        const st = await page.evaluate(() => {
            window.__saAnim.demo(120, innerHeight * 0.55);
            return new Promise((res) =>
                setTimeout(() => res(window.__saAnim.state()), 30),
            );
        });
        if (!st.arc || !st.wipes) {
            leg(
                route,
                "anim",
                "FAIL",
                `demo 未产件 state=${JSON.stringify(st)}`,
            );
        } else {
            const dashAt = (t) =>
                page.evaluate(async (t) => {
                    window.__saAnim.hold(t);
                    await new Promise((r) => requestAnimationFrame(r));
                    return getComputedStyle(
                        document.querySelector(".sa-arc-path"),
                    ).strokeDashoffset;
                }, t);
            const shotAt = async (t) => {
                await page.evaluate((t) => window.__saAnim.hold(t), t);
                return page.screenshot({
                    clip: {
                        x: 0,
                        y: 0,
                        width: 360,
                        height: 800,
                    },
                });
            };
            const dEarly = parseFloat(await dashAt(120));
            const shotA = await shotAt(120);
            const dLate = parseFloat(await dashAt(500));
            const shotB = await shotAt(500);
            const st2 = await page.evaluate(() =>
                window.__saAnim.state(),
            );
            const dashMoved = dEarly > 0.05 && dLate < 0.02 &&
                dEarly > dLate;
            const pixMoved = !shotA.equals(shotB);
            leg(
                route,
                "anim",
                dashMoved && pixMoved && st2.arc ? "PASS" : "FAIL",
                `dashoffset 120ms=${dEarly} 500ms=${dLate} ` +
                    `像素${pixMoved ? "有差" : "无差（硬切嫌疑）"}`,
            );
            await page.evaluate(() => window.__saAnim.release());
            await page.waitForTimeout(1300);
            const st3 = await page.evaluate(() =>
                window.__saAnim.state(),
            );
            leg(
                route,
                "cleanup",
                !st3.arc && !st3.wipes && !st3.ripple
                    ? "PASS"
                    : "FAIL",
                JSON.stringify(st3),
            );
        }
    }
    await page.close();
}

await browser.close();
console.log(
    `\n${fails ? `${fails} 条 FAIL` : "全过"}${
        READER ? "" : "（--reader 可加 anim/probe 腿）"
    }`,
);
process.exit(fails ? 1 : 0);
