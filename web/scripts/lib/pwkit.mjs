// verify/shot 脚本公共 bootstrap：chromium 探测 + launch + shots 目录 +
// PASS/FAIL 计数。各脚本差异收敛为 launch({args, tmp}) 两个开关。

import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

export const findChromium = () => {
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

export const EXE = process.env.PW_EXE ?? findChromium();

// 本机 /tmp 是 16G tmpfs 常年近满——tmp:true 把 chromium 的 shm/profile
// 经 TMPDIR 挪出 tmpfs，否则渲染进程随机 SIGTRAP（Target crashed）。
export const PW_TMP = join(homedir(), ".cache/pw-tmp");
export const SHOTS = new URL("../shots/", import.meta.url).pathname;
mkdirSync(PW_TMP, { recursive: true });
mkdirSync(SHOTS, { recursive: true });

export const launch = ({ args = [], tmp = false, ...rest } = {}) =>
    chromium.launch({
        executablePath: EXE,
        args,
        ...(tmp ? { env: { ...process.env, TMPDIR: PW_TMP } } : {}),
        ...rest,
    });

// 仅适合 goto 前无需挂 handler/route/initScript 的直通脚本——先跳后挂会
// 漏捕首载 console 错误，verify 类脚本一律走 launch() 本地展开。
export const openPage = async (
    url,
    { viewport, waitUntil = "domcontentloaded", launchOpts, contextOpts } = {},
) => {
    const browser = await launch(launchOpts);
    const ctx = await browser.newContext({ viewport, ...contextOpts });
    const page = await ctx.newPage();
    await page.goto(url, { waitUntil });
    return { browser, ctx, page };
};

export const results = [];
export const check = (name, ok, detail = "") => {
    results.push({ name, ok });
    console.log(
        `${ok ? "PASS" : "FAIL"}  ${name}${detail ? `  — ${detail}` : ""}`,
    );
};
export const info = (s) => console.log(`INFO  ${s}`);
