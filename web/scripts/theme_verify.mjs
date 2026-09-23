// 单轴合并实测:8 档色板 = 唯一外观轴,驱动整站 chrome + PDF 纸面。
// 活服 127.0.0.1:8765(须已 build)+ done 任务 t_d7c669e8b3c92149。
// OS 明暗走 playwright context colorScheme;色板经 addInitScript 预置
// texlate-paper-theme(首绘前落,含旧 texlate-theme 迁移场景)。
// 断言 data-theme 归类/documentElement computed token/meta theme-color/
// --page-bg-color/顶栏与非阅读面同色。
// /tmp tmpfs 与 chromium 坑同 cite_verify.mjs(TMPDIR 挪出 + --disable-gpu)。
// 用法:node scripts/theme_verify.mjs   (cwd=web/scripts)

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
    console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`);
};

// computed 可能是 rgb(0-255) 也可能是 color(srgb 0-1)——color-mix 的
// 结算形是后者,统一归一到 0-255 再做亮度/近似断言
const rgbOf = (s) => {
    const v = s.match(/-?\d+(\.\d+)?/g)?.map(Number).slice(0, 3) ?? [0, 0, 0];
    return v.every((x) => x <= 1) ? v.map((x) => x * 255) : v;
};
const lum = ([r, g, b]) => 0.2126 * r + 0.7152 * g + 0.0722 * b;
const near = (a, b, tol = 6) =>
    rgbOf(a).every((v, i) => Math.abs(v - b[i]) <= tol);

// 场景:[OS 明暗, 色板键(seed), 期望]。paper 经 texlate-paper-theme 预置;
// seed 为 null 时不写色板键(migration 场景写旧 texlate-theme)
const SCENARIOS = [
    {
        name: "OS亮 + auto → 原纸+亮chrome",
        os: "light",
        seed: ["texlate-paper-theme", "auto"],
        theme: "light",
        scheme: "light",
        meta: "#f5f1e8",
        toolbarNear: [253, 251, 245], // light --panel #fdfbf5
        containerNear: [237, 231, 217], // light --paper-2 #ede7d9
        pageVar: "",
    },
    {
        name: "OS暗 + auto → 暖黑对",
        os: "dark",
        seed: ["texlate-paper-theme", "auto"],
        theme: "dark",
        scheme: "dark",
        meta: "#17140f",
        toolbarNear: [38, 33, 26], // dark --panel #26211a
        containerNear: [31, 27, 21], // dark --paper-2 #1f1b15
        pageVar: "#17140f",
    },
    {
        name: "OS暗 + none → 逃生口:暗chrome+原页",
        os: "dark",
        seed: ["texlate-paper-theme", "none"],
        theme: "dark",
        scheme: "dark",
        meta: "#17140f",
        toolbarNear: [38, 33, 26],
        containerNear: [31, 27, 21],
        pageVar: "",
    },
    {
        name: "OS暗 + paper → 命名槽锁亮对(不听OS)",
        os: "dark",
        seed: ["texlate-paper-theme", "paper"],
        theme: "light",
        scheme: "light",
        meta: "#f5f1e8",
        toolbarNear: [253, 252, 250], // 派生 panel=20%#f5f1e8+80%白
        containerLumMin: 200,
        pageVar: "#f5f1e8",
    },
    {
        name: "OS亮 + black → 全深近黑",
        os: "light",
        seed: ["texlate-paper-theme", "black"],
        theme: "dark",
        scheme: "dark",
        meta: "#000000",
        toolbarLumMax: 60,
        containerLumMax: 30,
        pageVar: "#000000",
    },
    {
        name: "OS亮 + onedark → 蓝灰深整面",
        os: "light",
        seed: ["texlate-paper-theme", "onedark"],
        theme: "dark",
        scheme: "dark",
        meta: "#282c34",
        toolbarLumMax: 80,
        containerLumMax: 60,
        hueB: true, // b > r(冷色)
        pageVar: "#282c34",
    },
    {
        name: "OS亮 + sepia → 暖奶油整面",
        os: "light",
        seed: ["texlate-paper-theme", "sepia"],
        theme: "light",
        scheme: "light",
        meta: "#f4ecd8",
        toolbarLumMin: 220,
        containerLumMin: 200,
        pageVar: "#f4ecd8",
    },
    {
        name: "迁移:旧 theme=dark + 无纸面键 → 暖黑槽",
        os: "light",
        seed: ["texlate-theme", "dark"],
        theme: "dark",
        scheme: "dark",
        meta: "#17140f",
        toolbarNear: [38, 33, 26],
        containerNear: [31, 27, 21],
        pageVar: "#17140f",
    },
    {
        name: "迁移:旧 theme=light + 无纸面键 → 暖纸槽",
        os: "dark",
        seed: ["texlate-theme", "light"],
        theme: "light",
        scheme: "light",
        meta: "#f5f1e8",
        toolbarLumMin: 240, // 暗 OS 上锁定亮对——命名槽不听 OS
        pageVar: "#f5f1e8",
    },
];

async function run() {
    const errors = [];
    const browser = await chromium.launch({
        executablePath: EXE,
        args: ["--disable-gpu"],
        env: { ...process.env, TMPDIR: PW_TMP },
    });
    const url = `${BASE}/#/reader/${TASK}`;
    let lastProbe = null;

    for (const sc of SCENARIOS) {
        const ctx = await browser.newContext({ colorScheme: sc.os });
        await ctx.addInitScript(
            ([k, v]) => localStorage.setItem(k, v),
            sc.seed,
        );
        const page = await ctx.newPage();
        page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
        page.on("console", (m) => {
            if (m.type() === "error") errors.push(`console: ${m.text()}`);
        });
        await page.goto(url);
        await page.waitForSelector(".reader .reader-toolbar", {
            timeout: 20000,
        });
        await page.waitForSelector(".pdfSlickViewer .page", {
            timeout: 30000,
        });
        await page.waitForTimeout(400); // effect 落覆写一帧

        const s = await page.evaluate(() => {
            const cs = (sel) =>
                getComputedStyle(document.querySelector(sel));
            const el = document.documentElement;
            return {
                theme: el.dataset.theme ?? "",
                scheme: cs("html").colorScheme,
                meta:
                    document
                        .querySelector('meta[name="theme-color"]')
                        ?.getAttribute("content") ?? "",
                toolbarBg: cs(".reader-toolbar").backgroundColor,
                containerBg: cs(".pdfSlickContainer").backgroundColor,
                bodyBg: cs("body").backgroundColor,
                pageVar: cs(".pdfSlickViewer")
                    .getPropertyValue("--page-bg-color")
                    .trim(),
                topnavBtns: document.querySelectorAll(".topnav button")
                    .length,
                selAria: [
                    ...document.querySelectorAll(".reader-toolbar select"),
                ]
                    .map((x) => x.getAttribute("aria-label") ?? "")
                    .join(","),
            };
        });
        lastProbe = s;
        await page.screenshot({
            path: join(SHOTS, `merge-${sc.os}-${sc.seed[1]}.png`),
        });
        await ctx.close();

        const tLum = lum(rgbOf(s.toolbarBg));
        const cLum = lum(rgbOf(s.containerBg));
        const parts = [
            `theme=${s.theme}`,
            `toolbar=${s.toolbarBg}`,
            `gutter=${s.containerBg}`,
            `page=${s.pageVar || "(none)"}`,
        ];

        let ok = true;
        const why = [];
        if (s.theme !== sc.theme) {
            ok = false;
            why.push(`data-theme=${s.theme} 期望 ${sc.theme}`);
        }
        if (s.scheme !== sc.scheme) {
            ok = false;
            why.push(`color-scheme=${s.scheme}`);
        }
        if (s.meta !== sc.meta) {
            ok = false;
            why.push(`meta=${s.meta} 期望 ${sc.meta}`);
        }
        if (s.pageVar !== sc.pageVar) {
            ok = false;
            why.push(`pageVar=${s.pageVar || "(empty)"} 期望 ${sc.pageVar || "(empty)"}`);
        }
        if (sc.toolbarNear && !near(s.toolbarBg, sc.toolbarNear)) {
            ok = false;
            why.push(`toolbar 期望≈rgb(${sc.toolbarNear})`);
        }
        if (sc.containerNear && !near(s.containerBg, sc.containerNear)) {
            ok = false;
            why.push(`gutter 期望≈rgb(${sc.containerNear})`);
        }
        if (sc.toolbarLumMax !== undefined && tLum > sc.toolbarLumMax) {
            ok = false;
            why.push(`toolbar 亮度 ${tLum.toFixed(0)}>${sc.toolbarLumMax}`);
        }
        if (sc.containerLumMax !== undefined && cLum > sc.containerLumMax) {
            ok = false;
            why.push(`gutter 亮度 ${cLum.toFixed(0)}>${sc.containerLumMax}`);
        }
        if (sc.toolbarLumMin !== undefined && tLum < sc.toolbarLumMin) {
            ok = false;
            why.push(`toolbar 亮度 ${tLum.toFixed(0)}<${sc.toolbarLumMin}`);
        }
        if (sc.containerLumMin !== undefined && cLum < sc.containerLumMin) {
            ok = false;
            why.push(`gutter 亮度 ${cLum.toFixed(0)}<${sc.containerLumMin}`);
        }
        if (sc.hueB) {
            const [r, , b] = rgbOf(s.toolbarBg);
            if (b <= r) {
                ok = false;
                why.push(`toolbar 不冷 r=${r} b=${b}`);
            }
        }
        check(sc.name, ok, parts.join(" ") + (why.length ? ` | ${why.join(";")}` : ""));
    }

    // ---- 全局面:色板驱动非阅读页 chrome;控件面合一 ----
    const ctx = await browser.newContext({ colorScheme: "light" });
    await ctx.addInitScript(() =>
        localStorage.setItem("texlate-paper-theme", "onedark"),
    );
    const page = await ctx.newPage();
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
    page.on("console", (m) => {
        if (m.type() === "error") errors.push(`console: ${m.text()}`);
    });

    await page.goto(`${BASE}/#/tasks`);
    await page.waitForSelector(".topnav", { timeout: 20000 });
    await page.waitForTimeout(300);
    const g = await page.evaluate(() => ({
        navBg: getComputedStyle(document.querySelector(".topnav"))
            .backgroundColor,
        bodyBg: getComputedStyle(document.body).backgroundColor,
        theme: document.documentElement.dataset.theme ?? "",
    }));
    const nLum = lum(rgbOf(g.navBg));
    const [nr, , nb] = rgbOf(g.navBg);
    check(
        "非阅读面:onedark 板 → topnav 蓝灰深",
        g.theme === "dark" && nLum < 80 && nb > nr,
        `theme=${g.theme} nav=${g.navBg} body=${g.bodyBg}`,
    );

    await page.goto(`${BASE}/#/settings`);
    await page.waitForSelector(".settings", { timeout: 20000 });
    const st = await page.evaluate(() => {
        const labels = [...document.querySelectorAll(".settings label")];
        const ap = labels.find((l) => /外观|Appearance/.test(l.textContent));
        return {
            apOptions: ap?.querySelectorAll("select option").length ?? 0,
            apValue: ap?.querySelector("select")?.value ?? "",
            themeSeg: [...document.querySelectorAll(".segmented-item")].some(
                (x) => /浅色|深色|^Light$|^Dark$/.test(x.textContent ?? ""),
            ),
        };
    });
    check(
        "设置页:外观 select 8 档在位",
        st.apOptions === 8 && st.apValue === "onedark",
        `options=${st.apOptions} value=${st.apValue}`,
    );
    check(
        "设置页:无独立亮暗 Segmented",
        !st.themeSeg,
        st.themeSeg ? "仍有亮暗档控件" : "",
    );

    // 控件合一:topnav 无主题钮;阅读器顶栏外观 select 在位(最后一场景探针)
    check(
        "topnav 无主题钮",
        lastProbe?.topnavBtns === 0,
        `n=${lastProbe?.topnavBtns}`,
    );
    check(
        "阅读器外观 select 在位",
        /外观|appearance/i.test(lastProbe?.selAria ?? ""),
        `aria=${lastProbe?.selAria}`,
    );
    await ctx.close();

    check("零 console/pageerror", errors.length === 0, errors.join(" | "));
    await browser.close();

    const pass = results.filter((r) => r.ok).length;
    console.log(`\n${pass}/${results.length} PASS`);
    process.exit(pass === results.length ? 0 : 1);
}

await run();
