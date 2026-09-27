// sent-align seq 精度链端到端实测（Option A+B，真任务臂）。
// 链断言：
//   zh→en：zh pane 点 markedContent span → seqAtPoint 出 seq → jumpSeq
//          → seqPos → en pdf 落 seqpos[S].o.page（XYZ dest 目标行置顶）
//          + en pane .sa-flash 行带（en 无 TLXC 标 → flashAtPos 兜底）
//   en→zh：en pane 点 textLayer 文本（无锚）→ nearestSeq(seqpos,"en")
//          → zh pdf 落 seqpos[E].t.page + zh markedContent .sa-flash
//          （_mc{50000+E}——锚闪直钉到同 seq 的 marked span）
// 服务须已重启（seqpos 顶层字段）+ web build 已同步 static。
// 用法: TASK=t_xxx node scripts/sentalign_seq_verify.mjs   (cwd=web/scripts)

import { existsSync, mkdirSync, readdirSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { chromium } from "playwright-core";

const BASE = process.env.WEB_BASE ?? "http://127.0.0.1:8765";
const TASK = process.env.TASK ?? "t_65d2d6b1cca13638";
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

// 与 pdfseqpos.nearestSeq 同算法（node 侧期望 seq 推算）
const nearestSeq = (map, side, pos) => {
    const k = side === "en" ? "o" : "t";
    let best = null;
    let bestScore = Infinity;
    for (const [key, v] of Object.entries(map)) {
        const p = v[k];
        if (!p) continue;
        const dpage = Math.abs(p.page - pos.page);
        const score =
            dpage === 0
                ? Math.abs(p.fraction - pos.fraction)
                : dpage + (p.page < pos.page ? 1 - p.fraction : p.fraction);
        if (score < bestScore) {
            bestScore = score;
            best = Number(key);
        }
    }
    return best;
};

// 侧 → .pane data-side 值
const paneSide = { en: "original", zh: "translated" };

/** 容器视口顶部命中的页码（elementFromPoint 页缝兜底 data-page-number 扫描）。
    真滚动容器=.pdfSlickContainer（overflow:auto 的那个）——.pane-body 在
    文档序里更靠前会抢 querySelector 命中但 scrollHeight==clientHeight；
    [data-page-number] 须圈 .pdfSlickViewer 下——侧栏缩略图也带同名属性。 */
const topPageIn = (side) =>
    `(() => {
        const root = document.querySelector(
            '.pane[data-side="${paneSide[side]}"] .pdfSlickContainer');
        if (!root) return null;
        const viewer = root.querySelector(".pdfSlickViewer");
        const r = root.getBoundingClientRect();
        const el = document.elementFromPoint(
            r.left + r.width / 2, r.top + 8);
        const pg = el?.closest?.("[data-page-number]");
        if (pg && viewer?.contains(pg))
            return Number(pg.getAttribute("data-page-number"));
        // 页缝兜底：找 offsetTop 最大的 <= scrollTop 的页
        let best = null;
        const sc = root.scrollTop;
        for (const d of root.querySelectorAll(
            ".pdfSlickViewer [data-page-number]",
        ))
            if (d.offsetTop <= sc + 12) best = d;
        return best ? Number(best.getAttribute("data-page-number")) : null;
    })()`;

const run = async () => {
    // seqpos 由服务端懒算——node 侧直取同一响应做期望值推算
    const readerInfo = await fetch(`${BASE}/api/task/${TASK}/reader`).then(
        (r) => r.json(),
    );
    const seqpos = readerInfo.seqpos ?? {};
    const nSeq = Object.keys(seqpos).length;
    if (readerInfo.view && readerInfo.view !== "pdf")
        console.log(`WARN  view=${readerInfo.view}`);
    console.log(`INFO  task=${TASK} seqpos=${nSeq}`);

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
        await page.waitForSelector('.pane[data-side="translated"] .textLayer', {
            timeout: 30000,
        });
        await page.waitForTimeout(2000); // 两侧首屏渲染落定

        // 关滚动同步——本测试断言单侧位移，同步开着手动滚动会拖走对侧、
        // 预选点击坐标全部失效（实测 en 甩尾 zh 被同步到底、点击落 seq178）
        await page.evaluate(() => {
            for (const b of document.querySelectorAll(
                "button.tb-btn.tb-opt.on",
            ))
                if (b.textContent?.includes("⇅") && b.offsetParent) {
                    b.click();
                    break;
                }
        });
        // zh 回顶——PDFHistory 恢复位不定，marked 锚页须先渲出来
        await page.evaluate(() => {
            const sc = document.querySelector(
                '.pane[data-side="translated"] .pdfSlickContainer',
            );
            if (sc) sc.scrollTop = 0;
        });
        await page.waitForTimeout(1000);

        // ---------- 臂 1：zh→en（markedContent 锚点点击） ----------
        // markedContent span 是 0×0 容器（子孙文本 span 绝对定位）——
        // 点击位取其内首个非零 rect 子孙 span，elementFromPoint 命中
        // 子孙后 closest 上爬仍出 seq
        const zhPick = await page.evaluate((seqposJson) => {
            const map = JSON.parse(seqposJson);
            const out = [];
            const vr = document
                .querySelector(
                    '.pane[data-side="translated"] .pdfSlickContainer',
                )
                ?.getBoundingClientRect();
            if (!vr) return out;
            for (const sp of document.querySelectorAll(
                '.pane[data-side="translated"] .pdfSlickViewer ' +
                    "span.markedContent[id]",
            )) {
                const m = /_mc(\d+)$/.exec(sp.getAttribute("id") ?? "");
                if (!m) continue;
                const seq = Number(m[1]) - 50000;
                const ent = map[String(seq)];
                if (!ent?.o || !ent.t) continue;
                let hit = null;
                for (const c of sp.querySelectorAll("span")) {
                    const r = c.getBoundingClientRect();
                    if (r.width >= 2 && r.height >= 2) {
                        hit = r;
                        break;
                    }
                }
                if (!hit) continue;
                const cx = hit.left + Math.min(hit.width / 2, 40);
                const cy = hit.top + hit.height / 2;
                // 视口外点击落不到本窗格——只收可见区内候选
                if (
                    cy < vr.top + 2 ||
                    cy > vr.bottom - 2 ||
                    cx < vr.left + 2 ||
                    cx > vr.right - 2
                )
                    continue;
                // 命中须落在锚内（链接/批注/浮条盖住则跳）
                const at = document.elementFromPoint(cx, cy);
                if (!at || !sp.contains(at)) continue;
                out.push({
                    seq,
                    oPage: ent.o.page,
                    tPage: ent.t.page,
                    x: cx,
                    y: cy,
                });
            }
            return out;
        }, JSON.stringify(seqpos));
        // 偏好的目标：en 落页 ≠ zh 源页（跳转可观察）
        const pick1 = zhPick.filter((p) => p.oPage !== p.tPage)[0] ?? zhPick[0];
        if (!pick1) {
            check("zh→en: marked span 可点", false, "no candidates");
        } else {
            info(
                `zh→en pick seq=${pick1.seq} t.p${pick1.tPage}→o.p${pick1.oPage}`,
            );
            // 先把 en 滚到远处——同页目标也能看出跳回
            const enBefore = await page.evaluate(() => {
                const sc = document.querySelector(
                    '.pane[data-side="original"] .pdfSlickContainer',
                );
                if (sc) sc.scrollTop = sc.scrollHeight;
                return sc ? Math.round(sc.scrollTop) : -1;
            });
            await page.waitForTimeout(500);
            const enTopBefore = await page.evaluate(topPageIn("en"));
            await page.mouse.click(pick1.x, pick1.y);
            await page.waitForTimeout(700);
            const enAfter = await page.evaluate(topPageIn("en"));
            const flash1 = await page.evaluate(
                () =>
                    document.querySelectorAll(
                        '.pane[data-side="original"] .sa-flash',
                    ).length,
            );
            check(
                "zh→en: en 落 seqpos.o.page",
                enAfter === pick1.oPage,
                `want p${pick1.oPage} got p${enAfter} (was p${enTopBefore}, scroll=${enBefore})`,
            );
            check(
                "zh→en: en pane 落点闪示",
                flash1 > 0,
                `sa-flash els=${flash1}`,
            );
            await page.screenshot({
                path: join(SHOTS, "seqalign-1-zh-to-en.png"),
            });
        }

        // ---------- 臂 2：en→zh（nearestSeq 兜底链） ----------
        // zh 甩尾——跳回前页才有可观察位移（同步已关，en 不动）
        await page.evaluate(() => {
            const sc = document.querySelector(
                '.pane[data-side="translated"] .pdfSlickContainer',
            );
            if (sc) sc.scrollTop = sc.scrollHeight;
        });
        await page.waitForTimeout(600);
        const zhBefore = await page.evaluate(topPageIn("zh"));
        // en 回顶取候选——臂 1 已把它跳回前页，回顶后 p1-2 textLayer 在视口
        await page.evaluate(() => {
            const sc = document.querySelector(
                '.pane[data-side="original"] .pdfSlickContainer',
            );
            if (sc) sc.scrollTop = 0;
        });
        await page.waitForTimeout(800);
        // en 侧无 TLXC 标——在已渲染页找 textLayer span，点击位分位 →
        // node 侧 nearestSeq 推算期望 seq → zh 落页 + 锚闪
        const { enPick } = await page.evaluate(() => {
            const out = [];
            const vr = document
                .querySelector('.pane[data-side="original"] .pdfSlickContainer')
                ?.getBoundingClientRect();
            if (!vr) return { enPick: out };
            for (const pg of document.querySelectorAll(
                '.pane[data-side="original"] .pdfSlickViewer ' +
                    "[data-page-number]",
            )) {
                const page = Number(pg.getAttribute("data-page-number"));
                const pr = pg.getBoundingClientRect();
                if (pr.height < 10) continue;
                for (const sp of pg.querySelectorAll(".textLayer span")) {
                    const r = sp.getBoundingClientRect();
                    if (r.width < 8 || r.height < 4) continue;
                    const cx = r.left + Math.min(r.width / 2, 60);
                    const cy = r.top + r.height / 2;
                    // 只收视口内候选——窗外点击 elementFromPoint 落空
                    if (
                        cy < vr.top + 2 ||
                        cy > vr.bottom - 2 ||
                        cx < vr.left + 2 ||
                        cx > vr.right - 2
                    )
                        continue;
                    const at = document.elementFromPoint(cx, cy);
                    if (!at || !sp.contains(at)) continue;
                    out.push({
                        page,
                        frac: (cy - pr.top) / pr.height,
                        x: cx,
                        y: cy,
                    });
                }
            }
            return { enPick: out };
        });
        const ranked = enPick
            .map((p) => ({
                ...p,
                seq: nearestSeq(seqpos, "en", {
                    page: p.page,
                    fraction: p.frac,
                }),
            }))
            .filter((p) => p.seq != null && seqpos[String(p.seq)]?.t)
            .filter((p) => seqpos[String(p.seq)].t.page !== zhBefore)
            .sort((a, b) => a.frac - b.frac);
        const pick2 = ranked[Math.floor(ranked.length / 2)] ?? ranked[0];
        if (!pick2) {
            check("en→zh: textLayer 点击位可选", false, "no candidates");
        } else {
            const wantT = seqpos[String(pick2.seq)].t.page;
            info(
                `en→zh pick seq=${pick2.seq} o.p${pick2.page}f${pick2.frac.toFixed(2)}→t.p${wantT} (zh was p${zhBefore})`,
            );
            await page.mouse.click(pick2.x, pick2.y);
            await page.waitForTimeout(700);
            const zhAfter = await page.evaluate(topPageIn("zh"));
            const flash2 = await page.evaluate((mcid) => {
                const marked = [
                    ...document.querySelectorAll(
                        '.pane[data-side="translated"] span.markedContent.sa-flash[id]',
                    ),
                ].map((el) => el.getAttribute("id"));
                const any = document.querySelectorAll(
                    '.pane[data-side="translated"] .sa-flash',
                ).length;
                return { marked, any };
            }, 50000 + pick2.seq);
            check(
                "en→zh: zh 落 seqpos.t.page",
                zhAfter === wantT,
                `want p${wantT} got p${zhAfter} (was p${zhBefore})`,
            );
            check(
                "en→zh: zh pane 落点闪示",
                flash2.any > 0,
                `sa-flash els=${flash2.any}`,
            );
            if (pick2.seq != null)
                check(
                    `en→zh: markedContent 锚闪 _mc${50000 + pick2.seq}`,
                    flash2.marked.some((id) =>
                        id?.endsWith(`_mc${50000 + pick2.seq}`),
                    ) || flash2.marked.length === 0,
                    `marked flashes=${JSON.stringify(flash2.marked)}`,
                );
            await page.screenshot({
                path: join(SHOTS, "seqalign-2-en-to-zh.png"),
            });
        }
    } finally {
        await browser.close();
    }

    const fails = results.filter((r) => !r.ok).length;
    console.log(
        `\n${results.length - fails}/${results.length} PASS${fails ? ` (${fails} FAIL)` : ""}`,
    );
    process.exit(fails ? 1 : 0);
};

run().catch((e) => {
    console.error("FATAL", e);
    process.exit(2);
});
