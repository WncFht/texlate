// sent-align 句级落点深度探针（实证「段落级 or 句子级」）。
// 方法：en 侧选一个高 marked 段，先击首行（u≈0）标定 zh 块顶视口位 A，
//       再击 65% 深处（u≈0.65）。若 frac 插值生效：zh 块顶应抬到
//       A - u_dst*H（u_meas=(A-T_deep)/H ≈ u_src）；段落级则 T_deep≈A。
//       顺带量 .sa-flash 覆盖面（整段闪 vs 句带闪）与 zh 锚叶存在性。
// 用法: TASK=t_xxx WEB_BASE=http://127.0.0.1:8765 \
//       node scripts/sentalign_depth_probe.mjs   (cwd=web/scripts)

import { join } from "node:path";
import { info, launch, SHOTS } from "./lib/pwkit.mjs";

const BASE = process.env.WEB_BASE ?? "http://127.0.0.1:8765";
const TASK = process.env.TASK ?? "t_1f616ca071d9ac97";
const DEPTH = Number(process.env.DEPTH ?? "0.65");

const MC = 50000;
const DIR = process.env.DIRECTION ?? "en2zh"; // zh2en = 反向臂
const SRC = DIR === "zh2en" ? "translated" : "original";
const DST = DIR === "zh2en" ? "original" : "translated";

// en 侧逐屏扫出首个「够高 marked 段」：返点击点（首行 + DEPTH 深处）与块几何
const pickTall = (seqposJson, depth) => `(async () => {
    const map = ${JSON.stringify(seqposJson)};
    const seqs = Object.keys(map).map(Number).sort((a, b) => a - b);
    const maxSeq = seqs[seqs.length - 1] ?? 0;
    const sc = document.querySelector(
        '.pane[data-side="${SRC}"] .pdfSlickContainer');
    if (!sc) return { err: "no scroller" };
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    for (let step = 0; step < 40; step++) {
        sc.scrollTop = step * (sc.clientHeight * 0.8);
        await sleep(450);
        const vr = sc.getBoundingClientRect();
        const groups = new Map();
        for (const sp of document.querySelectorAll(
            '.pane[data-side="${SRC}"] .pdfSlickViewer ' +
                "span.markedContent[id]",
        )) {
            const m = /_mc(\\d+)$/.exec(sp.getAttribute("id") ?? "");
            if (!m) continue;
            const seq = Number(m[1]) - ${MC};
            const ent = map[String(seq)];
            if (!ent?.o || !ent.t) continue;
            if (seq >= maxSeq - 2) continue; // 末锚 u 无分母
            const rs = [];
            for (const c of sp.querySelectorAll("span")) {
                const r = c.getBoundingClientRect();
                if (r.width >= 2 && r.height >= 2) rs.push(r);
            }
            if (!rs.length) continue;
            const top = Math.min(...rs.map((r) => r.top));
            const bot = Math.max(...rs.map((r) => r.bottom));
            if (!groups.has(seq) || bot - top > groups.get(seq).h)
                groups.set(seq, { seq, top, bot, h: bot - top, rs });
        }
        const cand = [...groups.values()]
            .filter((g) => g.h > vr.height * 0.18 && g.h > 140)
            .sort((a, b) => b.h - a.h)[0];
        if (!cand) continue;
        const rows = cand.rs
            .filter((r) => r.bottom > vr.top + 4 && r.top < vr.bottom - 4)
            .sort((a, b) => a.top - b.top);
        if (rows.length < 3) continue;
        const aimY = cand.top + cand.h * ${depth};
        const deep = rows.reduce((b, r) =>
            Math.abs(r.top + r.height / 2 - aimY) <
            Math.abs(b.top + b.height / 2 - aimY) ? r : b);
        const topRow = rows[0];
        const uSrc = (deep.top + deep.height / 2 - cand.top) / cand.h;
        return {
            seq: cand.seq,
            h: cand.h,
            rows: rows.length,
            uSrc,
            topClick: {
                x: topRow.left + Math.min(topRow.width / 2, 30),
                y: topRow.top + topRow.height / 2,
            },
            deepClick: {
                x: deep.left + Math.min(deep.width / 2, 30),
                y: deep.top + deep.height / 2,
            },
            oPage: map[String(cand.seq)].o.page,
            tPage: map[String(cand.seq)].t.page,
        };
    }
    return { err: "no tall chunk" };
})()`;

// zh 侧量测：同 seq marked 叶并集视口几何 + scrollTop + .sa-flash 覆盖
const measureZh = (seq) => `(() => {
    const sc = document.querySelector(
        '.pane[data-side="${DST}"] .pdfSlickContainer');
    if (!sc) return null;
    const vr = sc.getBoundingClientRect();
    const leaves = [];
    for (const sp of document.querySelectorAll(
        '.pane[data-side="${DST}"] .pdfSlickViewer ' +
            "span.markedContent[id]",
    )) {
        const m = /_mc(\\d+)$/.exec(sp.getAttribute("id") ?? "");
        if (!m || Number(m[1]) - ${MC} !== ${seq}) continue;
        for (const c of sp.querySelectorAll("span")) {
            const r = c.getBoundingClientRect();
            if (r.width >= 2 && r.height >= 2) leaves.push(r);
        }
    }
    const union = leaves.length
        ? {
              top: Math.min(...leaves.map((r) => r.top)),
              bot: Math.max(...leaves.map((r) => r.bottom)),
              h: Math.max(...leaves.map((r) => r.bottom)) -
                  Math.min(...leaves.map((r) => r.top)),
          }
        : null;
    const fl = [...document.querySelectorAll(
        '.pane[data-side="${DST}"] .sa-flash',
    )]
        .map((e) => e.getBoundingClientRect())
        .filter((r) => r.width >= 2 && r.height >= 2);
    const flUnion = fl.length
        ? {
              n: fl.length,
              top: Math.min(...fl.map((r) => r.top)),
              h: Math.max(...fl.map((r) => r.bottom)) -
                  Math.min(...fl.map((r) => r.top)),
          }
        : null;
    const wipes = [...document.querySelectorAll(
        '.pane[data-side="translated"] .sa-wipe',
    )].map((e) => {
        const r = e.getBoundingClientRect();
        return { top: r.top, h: r.height };
    });
    return {
        scrollTop: sc.scrollTop,
        visH: vr.height,
        union,
        flash: flUnion,
        wipes,
        marked: leaves.length,
    };
})()`;

const run = async () => {
    const readerInfo = await fetch(`${BASE}/api/task/${TASK}/reader`).then(
        (r) => r.json(),
    );
    const seqpos = readerInfo.seqpos ?? {};
    info(`task=${TASK} seqpos=${Object.keys(seqpos).length}`);

    const browser = await launch({
        args: ["--disable-dev-shm-usage", "--no-sandbox"],
        tmp: true,
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
        await page.waitForTimeout(2000);
        await page.evaluate(() => {
            for (const b of document.querySelectorAll(
                "button.tb-btn.tb-opt.on",
            ))
                if (b.textContent?.includes("⇅") && b.offsetParent) {
                    b.click();
                    break;
                }
        });
        await page.evaluate(() => {
            for (const side of ["original", "translated"]) {
                const sc = document.querySelector(
                    `.pane[data-side="${side}"] .pdfSlickContainer`,
                );
                if (sc) sc.scrollTop = 0;
            }
        });
        await page.waitForTimeout(1200);

        const pick = await page.evaluate(pickTall(seqpos, DEPTH));
        if (pick.err) {
            console.log(`FATAL ${pick.err}`);
            return;
        }
        info(
            `pick seq=${pick.seq} o.p${pick.oPage}→t.p${pick.tPage} ` +
                `chunkH=${pick.h.toFixed(0)}px rows=${pick.rows} ` +
                `uSrc=${pick.uSrc.toFixed(2)}`,
        );

        // ---- click 1: 首行（u≈0）→ 标定 A ----
        await page.mouse.click(pick.topClick.x, pick.topClick.y);
        await page.waitForTimeout(600);
        const mTop = await page.evaluate(measureZh(pick.seq));
        if (!mTop?.union) {
            console.log(
                `RESULT seq=${pick.seq} zh-marked=absent ` +
                    `scrollTop=${mTop?.scrollTop?.toFixed(0)} ` +
                    `flash=${JSON.stringify(mTop?.flash)}`,
            );
        } else {
            const A = mTop.union.top;
            info(
                `top click → zhUnionTop=${A.toFixed(0)} ` +
                    `H=${mTop.union.h.toFixed(0)} ` +
                    `scrollTop=${mTop.scrollTop.toFixed(0)} ` +
                    `flash=${mTop.flash ? `n=${mTop.flash.n} h=${mTop.flash.h.toFixed(0)}` : "none"} ` +
                    `wipes=${mTop.wipes.length}`,
            );

            // ---- click 2: 深处（u≈uSrc）----
            await page.mouse.click(pick.deepClick.x, pick.deepClick.y);
            await page.waitForTimeout(600);
            const mDeep = await page.evaluate(measureZh(pick.seq));
            const T = mDeep?.union?.top;
            const uMeas =
                T != null && mDeep.union.h > 0 ? (A - T) / mDeep.union.h : null;
            info(
                `deep click → zhUnionTop=${T?.toFixed(0)} ` +
                    `scrollTop=${mDeep?.scrollTop?.toFixed(0)} ` +
                    `flash=${mDeep?.flash ? `n=${mDeep.flash.n} h=${mDeep.flash.h.toFixed(0)}` : "none"} ` +
                    `wipes=${mDeep?.wipes?.length}`,
            );
            console.log(
                `RESULT seq=${pick.seq} uSrc=${pick.uSrc.toFixed(2)} ` +
                    `uMeas=${uMeas == null ? "n/a" : uMeas.toFixed(2)} ` +
                    `A=${A.toFixed(0)} T=${T?.toFixed(0)} ` +
                    `Hzh=${mDeep?.union?.h?.toFixed(0)} ` +
                    `flashCover=${mDeep?.flash && mDeep.union ? (mDeep.flash.h / mDeep.union.h).toFixed(2) : "n/a"}`,
            );
        }
        await page.screenshot({
            path: join(SHOTS, "depth-probe.png"),
        });
    } finally {
        await browser.close();
    }
};

await run();
