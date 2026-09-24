// PdfPane 图/表/式本体右键反查 usages 端到端实测（destPos 命台链路）。
// 链断言：
//   1. 全文档滚一遍逼 annotationLayer 懒渲染 → 找 figure/table/equation
//      类 link 锚 → 点击跳目标页
//   2. 目标页顶文本片（dest 落点≈视口顶）上右键 → destAtPoint 命中
//      → .usage-card 出（preventDefault+stopPropagation——ctxm 菜单不弹）
//   3. 卡渲染非空；
//   4. Esc 关卡；
//   5. shift+右键同位 → 不开卡（原生菜单放行）。
// 服务须已重启 + web build 已同步 static。
// 用法: TASK=t_xxx SIDE=translated node scripts/pdf_dest_usages_verify.mjs

import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const BASE = process.env.WEB_BASE ?? "http://127.0.0.1:8765";
const TASK = process.env.TASK ?? "t_65d2d6b1cca13638";
const SIDE = process.env.SIDE ?? "translated";
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
const info = (s) => console.log(`INFO  ${s}`);

const USAGE_RX =
    /^(cite|bib)\.|^(equation|eq|eqn)[._-]|(?:^|\.)e\d+$|^(figure|fig|subfigure|subfig)[._-]|(?:^|\.)f\d+(?:\.\w+)?$|^(table|tab)[._-]|(?:^|\.)t\d+(?:\.\d+)?$|^(theorem|thm|lemma|lem|prop|proposition|cor|corollary|def|definition|remark|rem)[._-]/i;
const FIG_RX =
    /^(figure|fig|subfigure|subfig)[._-]|^(equation|eq|eqn)[._-]|^(table|tab)[._-]/i;

const run = async () => {
    const browser = await chromium.launch({
        executablePath: EXE,
        args: ["--disable-dev-shm-usage", "--no-sandbox"],
        env: { ...process.env, TMPDIR: PW_TMP },
    });
    const page = await browser.newPage({
        viewport: { width: 1680, height: 1000 },
    });
    try {
        await page.goto(`${BASE}/#/reader/${TASK}`, {
            waitUntil: "domcontentloaded",
        });
        await page.waitForSelector(
            `.pane[data-side="${SIDE}"] .pdfSlickContainer`,
            { timeout: 60000 },
        );
        // annotationLayer 按页懒渲；快滚会被 pdf.js 取消渲染请求（页滚出
        // 视口即弃渲），慢滚+每步扫已渲 annot（已渲的持久留 DOM）才可
        // 靠发现 fig/eq/tab 锚。命中立即停步——页仍在视口，点击可达。
        const scanAnchors = ({ side, wantSrc }) => {
            const want = new RegExp(wantSrc, "i");
            const links = [
                ...document.querySelectorAll(
                    `.pane[data-side="${side}"] section.linkAnnotation a[href^='#']`,
                ),
            ];
            const dec = (a) => {
                const h = (a.getAttribute("href") ?? "").slice(1);
                try {
                    return decodeURIComponent(h);
                } catch {
                    try {
                        return unescape(h);
                    } catch {
                        return h;
                    }
                }
            };
            const all = links
                .map((a) => ({ dest: dec(a), a }))
                .filter((x) => x.dest);
            const pick = all.find((x) => want.test(x.dest));
            if (!pick) return null;
            const r = pick.a.getBoundingClientRect();
            return {
                dest: pick.dest,
                x: r.left + r.width / 2,
                y: r.top + r.height / 2,
                inView: r.bottom > 0 && r.top < innerHeight,
            };
        };
        const anchorInfo = await (async () => {
            // 首页 annot 渲完要数秒——先落定再起步扫（probe 实证 top=0
            //  dwell 后页 1 即见 equation.4.16/4.19 锚）
            await page.waitForTimeout(6000);
            const dims = await page.evaluate((side) => {
                const c = document.querySelector(
                    `.pane[data-side="${side}"] .pdfSlickContainer`,
                );
                return c
                    ? { h: c.clientHeight, total: c.scrollHeight }
                    : null;
            }, SIDE);
            if (!dims) return null;
            for (let y = 0; y <= dims.total; y += Math.floor(dims.h * 0.9)) {
                await page.evaluate(
                    ({ side, top }) => {
                        const c = document.querySelector(
                            `.pane[data-side="${side}"] .pdfSlickContainer`,
                        );
                        if (c) c.scrollTop = top;
                    },
                    { side: SIDE, top: y },
                );
                await page.waitForTimeout(900);
                const found = await page.evaluate(scanAnchors, {
                    side: SIDE,
                    wantSrc: FIG_RX.source,
                });
                // 锚须在视口内——滚过头的命中页可能已被逐出渲染窗
                if (found?.inView) return found;
            }
            return null;
        })();
        await page.waitForTimeout(12000); // destPos idle 充填兜底
        if (!anchorInfo) {
            check("找到图/表/式引用锚", false, "无 link annot");
            return;
        }
        info(`锚 dest=${anchorInfo.dest}`);
        check(
            "找到图/表/式引用锚",
            USAGE_RX.test(anchorInfo.dest),
            anchorInfo.dest,
        );

        // 点锚跳目标页——落定后 dest 行在视口顶附近
        await page.waitForTimeout(400);
        await page.mouse.click(anchorInfo.x, anchorInfo.y);
        await page.waitForTimeout(1500);

        // 视口顶页 + 靠顶文本片（dest 落点带）
        const target = await page.evaluate((side) => {
            const root = document.querySelector(
                `.pane[data-side="${side}"] .pdfSlickContainer`,
            );
            if (!root) return null;
            const r = root.getBoundingClientRect();
            const el = document.elementFromPoint(
                r.left + r.width / 2,
                r.top + 8,
            );
            const pageDiv = el?.closest?.("[data-page-number]") ?? null;
            if (!pageDiv) return null;
            const spans = [
                ...pageDiv.querySelectorAll(".textLayer span"),
            ].map((s) => ({ s, sr: s.getBoundingClientRect() }));
            const near = spans
                .filter(
                    ({ s, sr }) =>
                        sr.top >= r.top - 40 &&
                        sr.top <= r.top + r.height * 0.5 &&
                        sr.height > 0 &&
                        (s.textContent ?? "").trim().length > 0,
                )
                .sort((a, b) => a.sr.top - b.sr.top)[0];
            if (near) {
                return {
                    page: Number(
                        pageDiv.getAttribute("data-page-number"),
                    ),
                    x: near.sr.left + Math.min(near.sr.width / 2, 60),
                    y: near.sr.top + near.sr.height / 2,
                    text: (near.s.textContent ?? "").slice(0, 40),
                };
            }
            const pr = pageDiv.getBoundingClientRect();
            return {
                page: Number(pageDiv.getAttribute("data-page-number")),
                x: pr.left + pr.width / 2,
                y: pr.top + pr.height * 0.25,
                text: "(blank-area)",
            };
        }, SIDE);
        if (!target) {
            check("目标页定位", false, "视口顶无页");
            return;
        }
        info(
            `落点 p${target.page} (${Math.round(target.x)},${Math.round(target.y)}) "${target.text}"`,
        );

        // 右键本体 → usages 卡
        let opened = false;
        for (let i = 0; i < 4 && !opened; i++) {
            await page.mouse.click(target.x, target.y, {
                button: "right",
            });
            await page.waitForTimeout(900);
            opened = (await page.$(".usage-card")) != null;
            if (!opened) {
                const ctxm = await page.$(".ctx-menu");
                info(
                    `第${i + 1}次右键未开卡${ctxm ? "（ctxm 菜单弹出——destAtPoint 未命中）" : "（无菜单无卡）"}`,
                );
                await page.keyboard.press("Escape");
                await page.waitForTimeout(1200);
            }
        }
        check("本体右键 → .usage-card 出", opened);

        if (opened) {
            const card = await page.evaluate(() => {
                const c = document.querySelector(".usage-card");
                if (!c) return null;
                return {
                    label:
                        c.querySelector(".usage-card-label")
                            ?.textContent ?? "",
                    count:
                        c.querySelector(".usage-card-count")
                            ?.textContent ?? "",
                    items: c.querySelectorAll(".usage-card-item").length,
                    empty: !!c.querySelector(".usage-card-empty"),
                    text: c.textContent.slice(0, 160),
                };
            });
            info(
                `卡内容 label="${card?.label}" count="${card?.count}" items=${card?.items} empty=${card?.empty}`,
            );
            check("卡渲染非空", !!card && !!card.label);
            await page.screenshot({
                path: join(SHOTS, `pdf-dest-usages-${TASK}.png`),
            });
        }

        // Esc 关卡
        await page.keyboard.press("Escape");
        await page.waitForTimeout(400);
        check("Esc 关卡", (await page.$(".usage-card")) == null);

        // shift+右键 → 原生菜单放行（卡不重开）。mouse.click 不吃
        // modifiers 选项（那是 page.click 的）——须 keyboard.down 真按
        await page.keyboard.down("Shift");
        await page.mouse.click(target.x, target.y, { button: "right" });
        await page.keyboard.up("Shift");
        await page.waitForTimeout(500);
        check(
            "shift+右键放行（不开卡）",
            (await page.$(".usage-card")) == null,
        );
    } finally {
        await browser.close();
    }
    const fails = results.filter((r) => !r.ok);
    console.log(
        `\n${results.length - fails.length}/${results.length} PASS${fails.length ? ` — FAIL: ${fails.map((f) => f.name).join(", ")}` : ""}`,
    );
    process.exit(fails.length ? 1 : 0);
};

run();
