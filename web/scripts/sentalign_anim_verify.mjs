// sent-align 动效臂端到端实测（A 连线 / B 涟漪+行擦入 / C PDF 悬停对位）。
// 链断言：
//   悬停 zh marked span → zh pane .sa-hot（锚叶染色）+ en pane .sa-peer
//     （en 无 TLXC 标 → pos 行带兜底染色）；移出窗格 → 双轨清零
//   悬停 en textLayer 文本 → containingSeq 兜底出 seq → en .sa-hot 行带
//     + zh .sa-peer（锚叶或行带）
//   点击 zh marked span → .sa-ripple 源点扩散（~420ms）+ .sa-arc-svg
//     跨栏连线 + .sa-wipe 行擦入（≤8 行）+ 1100ms 全自清
// 服务须挂新 dist（TEXLATE_SPA_DIR=web/dist）。
// 用法: TASK=t_xxx WEB_BASE=http://127.0.0.1:8899 \
//       node scripts/sentalign_anim_verify.mjs   (cwd=web/scripts)

import { join } from "node:path";
import { check, info, launch, results, SHOTS } from "./lib/pwkit.mjs";

const BASE = process.env.WEB_BASE ?? "http://127.0.0.1:8899";
const TASK = process.env.TASK ?? "t_65d2d6b1cca13638";

// 与 pdfseqpos.nearestSeq 同算法（en 悬停候选的期望 seq 推算）
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

const paneSide = { en: "original", zh: "translated" };

// 容器内找一枚可见 marked span（含非零 rect 子孙 + elementFromPoint 命中）
const pickMarked = (side, seqposJson) => `(() => {
    const map = ${JSON.stringify(seqposJson)};
    const vr = document
        .querySelector('.pane[data-side="${paneSide[side]}"] .pdfSlickContainer')
        ?.getBoundingClientRect();
    if (!vr) return null;
    for (const sp of document.querySelectorAll(
        '.pane[data-side="${paneSide[side]}"] .pdfSlickViewer ' +
            "span.markedContent[id]",
    )) {
        const m = /_mc(\\d+)$/.exec(sp.getAttribute("id") ?? "");
        if (!m) continue;
        const seq = Number(m[1]) - 50000;
        const ent = map[String(seq)];
        if (!ent?.o || !ent.t) continue;
        let hit = null;
        for (const c of sp.querySelectorAll("span")) {
            const r = c.getBoundingClientRect();
            if (r.width >= 2 && r.height >= 2) { hit = r; break; }
        }
        if (!hit) continue;
        const cx = hit.left + Math.min(hit.width / 2, 40);
        const cy = hit.top + hit.height / 2;
        if (cy < vr.top + 2 || cy > vr.bottom - 2 ||
            cx < vr.left + 2 || cx > vr.right - 2) continue;
        const at = document.elementFromPoint(cx, cy);
        if (!at || !sp.contains(at)) continue;
        return { seq, oPage: ent.o.page, tPage: ent.t.page, x: cx, y: cy };
    }
    return null;
})()`;

const run = async () => {
    const readerInfo = await fetch(`${BASE}/api/task/${TASK}/reader`).then(
        (r) => r.json(),
    );
    const seqpos = readerInfo.seqpos ?? {};
    if (readerInfo.view && readerInfo.view !== "pdf")
        console.log(`WARN  view=${readerInfo.view}`);
    console.log(`INFO  task=${TASK} seqpos=${Object.keys(seqpos).length}`);

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
        // 关滚动同步——单侧位移断言不被同步拖走
        await page.evaluate(() => {
            for (const b of document.querySelectorAll(
                "button.tb-btn.tb-opt.on",
            ))
                if (b.textContent?.includes("⇅") && b.offsetParent) {
                    b.click();
                    break;
                }
        });
        // 双侧回顶——marked 锚页/密集锚区先渲出来
        await page.evaluate(() => {
            for (const side of ["original", "translated"]) {
                const sc = document.querySelector(
                    `.pane[data-side="${side}"] .pdfSlickContainer`,
                );
                if (sc) sc.scrollTop = 0;
            }
        });
        await page.waitForTimeout(1200);

        // ---------- 臂 C1：zh→en 悬停对位 ----------
        const pick1 = await page.evaluate(pickMarked("zh", seqpos));
        if (!pick1) {
            check("C1 zh悬停: marked span 可悬", false, "no candidates");
        } else {
            info(
                `C1 pick seq=${pick1.seq} t.p${pick1.tPage}→o.p${pick1.oPage}`,
            );
            await page.mouse.move(pick1.x, pick1.y);
            await page.waitForTimeout(400);
            const hov1 = await page.evaluate(() => ({
                hot: document.querySelectorAll(
                    '.pane[data-side="translated"] .sa-hot',
                ).length,
                peer: document.querySelectorAll(
                    '.pane[data-side="original"] .sa-peer',
                ).length,
            }));
            check(
                "C1 zh悬停: zh pane .sa-hot 锚染色",
                hov1.hot > 0,
                `hot els=${hov1.hot}`,
            );
            check(
                "C1 zh悬停: en pane .sa-peer 对位染色",
                hov1.peer > 0,
                `peer els=${hov1.peer}`,
            );
            await page.screenshot({
                path: join(SHOTS, "anim-1-hover-zh.png"),
            });
            // 移出窗格 → 双轨清零
            await page.mouse.move(5, 5);
            await page.waitForTimeout(400);
            const clr1 = await page.evaluate(() => ({
                hot: document.querySelectorAll(
                    '.pane[data-side="translated"] .sa-hot',
                ).length,
                peer: document.querySelectorAll(
                    '.pane[data-side="original"] .sa-peer',
                ).length,
            }));
            check(
                "C1 移出: hot+peer 全清零",
                clr1.hot === 0 && clr1.peer === 0,
                `hot=${clr1.hot} peer=${clr1.peer}`,
            );
        }

        // ---------- 臂 C2：en→zh 悬停（containingSeq 兜底臂） ----------
        // en 页首文本区找一枚 span → node 侧 nearestSeq 算期望 seq
        const enPick = await page.evaluate(() => {
            const vr = document
                .querySelector('.pane[data-side="original"] .pdfSlickContainer')
                ?.getBoundingClientRect();
            if (!vr) return null;
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
                    if (
                        cy < vr.top + 2 ||
                        cy > vr.bottom - 2 ||
                        cx < vr.left + 2 ||
                        cx > vr.right - 2
                    )
                        continue;
                    const at = document.elementFromPoint(cx, cy);
                    if (!at || !sp.contains(at)) continue;
                    return {
                        page,
                        frac: (cy - pr.top) / pr.height,
                        x: cx,
                        y: cy,
                    };
                }
            }
            return null;
        });
        const seq2 = enPick
            ? nearestSeq(seqpos, "en", {
                  page: enPick.page,
                  fraction: enPick.frac,
              })
            : null;
        if (!enPick || seq2 == null || !seqpos[String(seq2)]?.t) {
            check(
                "C2 en悬停: textLayer 悬停位可选",
                false,
                `enPick=${!!enPick} seq=${seq2}`,
            );
        } else {
            info(
                `C2 pick seq=${seq2} o.p${enPick.page}f${enPick.frac.toFixed(2)}→t.p${seqpos[String(seq2)].t.page}`,
            );
            await page.mouse.move(enPick.x, enPick.y);
            await page.waitForTimeout(500);
            const hov2 = await page.evaluate(() => ({
                hot: document.querySelectorAll(
                    '.pane[data-side="original"] .sa-hot',
                ).length,
                peer: document.querySelectorAll(
                    '.pane[data-side="translated"] .sa-peer',
                ).length,
                peerMarked: document.querySelectorAll(
                    '.pane[data-side="translated"] .markedContent .sa-peer,' +
                        '.pane[data-side="translated"] .markedContent.sa-peer',
                ).length,
            }));
            check(
                "C2 en悬停: en pane .sa-hot 行带染色",
                hov2.hot > 0,
                `hot els=${hov2.hot}`,
            );
            check(
                "C2 en悬停: zh pane .sa-peer 对位染色",
                hov2.peer > 0,
                `peer els=${hov2.peer} (marked=${hov2.peerMarked})`,
            );
            await page.screenshot({
                path: join(SHOTS, "anim-2-hover-en.png"),
            });
            await page.mouse.move(5, 5);
            await page.waitForTimeout(300);
        }

        // ---------- 臂 A+B：zh→en 点击 → 涟漪+连线+行擦入 ----------
        if (!pick1) {
            check("AB 点击: marked span 可点", false, "no candidates");
        } else {
            await page.mouse.click(pick1.x, pick1.y);
            // 涟漪同步落 DOM（点击 handler 同帧）——420ms 内必在
            const ripple = await page.evaluate(
                () => document.querySelectorAll(".sa-ripple").length,
            );
            check(
                "AB 点击: .sa-ripple 源点扩散",
                ripple > 0,
                `ripples=${ripple}`,
            );
            // 连线+擦入在 pdfJump resolve 后落——轮询等
            let arc = null;
            try {
                arc = await page.waitForSelector(".sa-arc-svg", {
                    timeout: 5000,
                });
            } catch {}
            check("AB 点击: .sa-arc-svg 跨栏连线", !!arc);
            const wipes = await page.evaluate(
                () => document.querySelectorAll(".sa-wipe").length,
            );
            check(
                "AB 点击: .sa-wipe 行擦入 (1..8)",
                wipes >= 1 && wipes <= 8,
                `wipes=${wipes}`,
            );
            const flash = await page.evaluate(
                () =>
                    document.querySelectorAll(
                        '.pane[data-side="original"] .sa-flash',
                    ).length,
            );
            check(
                "AB 点击: en 落点 sa-flash（回归）",
                flash > 0,
                `flash els=${flash}`,
            );
            await page.screenshot({
                path: join(SHOTS, "anim-3-click-arc.png"),
            });
            // 全自清——1100ms 后盖层摘光
            await page.waitForTimeout(1400);
            const gone = await page.evaluate(
                () =>
                    document.querySelectorAll(".sa-ripple,.sa-wipe,.sa-arc-svg")
                        .length,
            );
            check("AB 自清: 动效盖层全摘", gone === 0, `left=${gone}`);
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
