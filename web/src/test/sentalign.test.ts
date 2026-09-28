// @vitest-environment jsdom
// sentalign —— 句级双语对位内核对拍（zhseg.py / align.py / wrap_sid.mjs
// 三 spike 移植语义）。
// 断言面：zh 正则臂切句表（Latin 缩写过切回归头案）、en Intl 扁平臂、
// bead 贪心对位（1:1/1:2/2:1/MAXG/降级残并）、注入幂等+textContent 恒等、
// sid 集合契约、悬停类名、点击跳+守卫、MO 增量重注、DOM→PDF 分位路径。

import { beforeEach, describe, expect, it, vi } from "vitest";
import {
    alignBeads,
    injectSentSpans,
    SentAlignSession,
    sentLen,
    splitEn,
    splitZh,
    stripSentSpans,
    type SaSide,
    type SentSpan,
} from "../reader/sentalign";
import type { Pos } from "../reader/alignment";

beforeEach(() => {
    document.body.innerHTML = "";
});

const texts = (t: string, spans: readonly SentSpan[]) =>
    spans.map(([s, e]) => t.slice(s, e));

// ================================================================= zh 切句

describe("splitZh zh 正则臂", () => {
    it("CJK 终止符切 + 闭引号 run 吸收", () => {
        const t = "甲。乙！丙？丁！戊?己…庚。";
        expect(texts(t, splitZh(t))).toEqual([
            "甲。",
            "乙！",
            "丙？",
            "丁！",
            "戊?",
            "己…",
            "庚。",
        ]);
    });

    it("闭引号/括号并入前句（」。』』）》）」 全套）", () => {
        const t = "他说「够了。」然后走。再见";
        expect(texts(t, splitZh(t))).toEqual([
            "他说「够了。」",
            "然后走。",
            "再见",
        ]);
    });

    it("行尾空白/换行吸收进前句", () => {
        const t = "甲。   \n乙。\n";
        const spans = splitZh(t);
        expect(texts(t, spans)).toEqual(["甲。   \n", "乙。\n"]);
    });

    it("ASCII '.' 跟空白才候选——'done. 下句' 切、'3.14' 不切", () => {
        const t = "这是 done. 下一句。";
        expect(texts(t, splitZh(t))).toEqual(["这是 done. ", "下一句。"]);
    });

    it("Latin 缩写过切回归：e.g. / et al. / Fig. 不切", () => {
        // Intl.Segmenter zh 在这些点上系统性过切——正则臂的头案
        const t = "使用 e.g. 的方法。它有效。";
        expect(texts(t, splitZh(t))).toEqual([
            "使用 e.g. 的方法。",
            "它有效。",
        ]);
        const t2 = "由 et al. 证明。见 Fig. 三。完。";
        expect(texts(t2, splitZh(t2))).toEqual([
            "由 et al. 证明。",
            "见 Fig. 三。",
            "完。",
        ]);
    });

    it("数字邻接 ASCII 点按缩写兜（v2. / 3.14. 后跟空白不切）", () => {
        const t = "版本 v2. 已发布。下一版。";
        expect(texts(t, splitZh(t))).toEqual(["版本 v2. 已发布。", "下一版。"]);
    });

    it("保护区：[[]] token / $..$ / URL 内的点不切", () => {
        const t = "公式 [[X_1]] 成立。式 $a.b$ 后。再。";
        expect(texts(t, splitZh(t))).toEqual([
            "公式 [[X_1]] 成立。",
            "式 $a.b$ 后。",
            "再。",
        ]);
        const u = "访问 https://example.com/a.b 后。再说。";
        expect(texts(u, splitZh(u))).toEqual([
            "访问 https://example.com/a.b 后。",
            "再说。",
        ]);
    });

    it("{} 深度>0 抑制切点；\\{ 转义双跳不抬深", () => {
        const t = "用{甲。乙}丙。丁。";
        expect(texts(t, splitZh(t))).toEqual(["用{甲。乙}丙。", "丁。"]);
        const e = "a\\{b。c}。"; // \{ 不抬深——句中 。 照切
        expect(texts(e, splitZh(e))).toEqual(["a\\{b。", "c}。"]);
    });

    it("空白/空文本 → 空表；纯空白句不产 span", () => {
        expect(splitZh("")).toEqual([]);
        expect(splitZh("   \n  ")).toEqual([]);
        expect(texts("甲。。乙", splitZh("甲。。乙"))).toEqual([
            "甲。。",
            "乙",
        ]);
    });
});

// ================================================================= en 切句

describe("splitEn en Intl 扁平臂", () => {
    it(". ! ? 常规切（句尾空白吸进前句 span——与 zh 臂同口径）", () => {
        const t = "First sentence. Second longer! Third next? Tail end.";
        expect(texts(t, splitEn(t))).toEqual([
            "First sentence. ",
            "Second longer! ",
            "Third next? ",
            "Tail end.",
        ]);
    });

    it("\\n 扁平化——RAW 变体的换行乱切免疫", () => {
        const t = "Line one continues\nacross a break. Second here.";
        const spans = splitEn(t);
        expect(texts(t, spans)).toEqual([
            "Line one continues\nacross a break. ",
            "Second here.",
        ]);
    });

    it("ws-only segment 剔除（连续空白不产句——ws 并入前句 span）", () => {
        const t = "One.   \n\n  Two.";
        expect(texts(t, splitEn(t))).toEqual(["One.   \n\n  ", "Two."]);
    });
});

// ================================================================= 对位

describe("alignBeads 贪心对位", () => {
    it("等长 → 逐对 1:1", () => {
        expect(alignBeads([10, 10, 10], [10, 10, 10], 1)).toEqual([
            { en0: 0, en1: 1, zh0: 0, zh1: 1 },
            { en0: 1, en1: 2, zh0: 1, zh1: 2 },
            { en0: 2, en1: 3, zh0: 2, zh1: 3 },
        ]);
    });

    it("en1:zh2 与 zh2:en1 合并", () => {
        expect(alignBeads([20], [10, 10], 1)).toEqual([
            { en0: 0, en1: 1, zh0: 0, zh1: 2 },
        ]);
        expect(alignBeads([10, 10], [20], 1)).toEqual([
            { en0: 0, en1: 2, zh0: 0, zh1: 1 },
        ]);
    });

    it("MAXG=4 封顶——扩到 4 句即闭 bead", () => {
        // en 六短 zh 一长一短：第一 bead 欲合 5 句被 MAXG 拦在 4
        const beads = alignBeads([5, 5, 5, 5, 5, 5], [25, 10], 1);
        expect(beads).toEqual([
            { en0: 0, en1: 4, zh0: 0, zh1: 1 },
            { en0: 4, en1: 6, zh0: 1, zh1: 2 },
        ]);
    });

    it("单侧残句并入末 bead（降级组——绝不伪装 1:1）", () => {
        // zh 少两句：末 bead 吞 en 残部
        expect(alignBeads([10, 10, 10], [10], 1)).toEqual([
            { en0: 0, en1: 3, zh0: 0, zh1: 1 },
        ]);
        expect(alignBeads([10], [10, 10], 1)).toEqual([
            { en0: 0, en1: 1, zh0: 0, zh1: 2 },
        ]);
    });

    it("rho 自适应缺省 = Σzh/Σen；空输入 → 空表", () => {
        // zh 普遍两倍长：rho=2 时 10 vs 20 恰好 1:1
        const beads = alignBeads([10, 10], [20, 20]);
        expect(beads).toEqual([
            { en0: 0, en1: 1, zh0: 0, zh1: 1 },
            { en0: 1, en1: 2, zh0: 1, zh1: 2 },
        ]);
        expect(alignBeads([], [])).toEqual([]);
        expect(alignBeads([10], [])).toEqual([
            { en0: 0, en1: 1, zh0: 0, zh1: 0 },
        ]);
    });
});

// ================================================================= 注入

const chunkEl = (inner: string, key = "S1"): HTMLElement => {
    const d = document.createElement("div");
    d.setAttribute("data-chunk", key);
    d.innerHTML = inner;
    document.body.appendChild(d);
    return d;
};

describe("injectSentSpans", () => {
    it("包裹文本为 span.ens[data-sid]；textContent 逐字节恒等", () => {
        const el = chunkEl("<p>First sentence. Second one.</p>");
        const t0 = el.textContent;
        const { sents } = injectSentSpans(el, "en");
        expect(el.textContent).toBe(t0);
        expect(sents.map((s) => s.sid)).toEqual(["S1.0", "S1.1"]);
        const spans = el.querySelectorAll("span.ens[data-sid]");
        expect(spans).toHaveLength(2);
        expect(spans[0]!.getAttribute("data-sid")).toBe("S1.0");
    });

    it("跨界句产多片同 sid——sid 集合契约（<em> 三分片）", () => {
        const el = chunkEl("<p>Alpha <em>beta</em> tail. Next.</p>");
        injectSentSpans(el, "en");
        const s0 = el.querySelectorAll('[data-sid="S1.0"]');
        expect(s0).toHaveLength(3); // "Alpha " + <em>beta</em> + " tail."
        expect(el.textContent).toBe("Alpha beta tail. Next.");
    });

    it("SKIP_TAGS/类/属性整树跳（math/code/katex/ph-tok/chunk-meta/data-ph）", () => {
        const el = chunkEl(
            `<p>A. B.</p><math>x. y.</math><code>c. d.</code>` +
                `<span class="katex">k. l.</span>` +
                `<span class="ph-tok">p. q.</span>` +
                `<span class="chunk-meta">m. n.</span>` +
                `<span data-ph="M">r. s.</span>`,
        );
        const { sents } = injectSentSpans(el, "en");
        expect(sents.map((s) => s.sid)).toEqual(["S1.0", "S1.1"]);
        expect(el.querySelectorAll("[data-sid]")).toHaveLength(2);
        // 跳过件内部零 span
        for (const sel of [
            "math",
            "code",
            ".katex",
            ".ph-tok",
            ".chunk-meta",
            "[data-ph]",
        ])
            expect(
                el.querySelector(sel)!.querySelectorAll("[data-sid]"),
            ).toHaveLength(0);
    });

    it("嵌套 [data-chunk] 是独立单元——外层句流不含其文本（footnote 闸）", () => {
        const el = chunkEl(
            `<p>Outer one. <span data-chunk="IN">Inner a. Inner b.</span> Outer two.</p>`,
        );
        const { sents } = injectSentSpans(el, "en");
        expect(sents.map((s) => s.sid)).toEqual(["S1.0", "S1.1"]);
        const inner = el.querySelector('[data-chunk="IN"]')!;
        expect(inner.querySelectorAll("[data-sid]")).toHaveLength(0);
    });

    it("RESTRICTED_SPAN_PARENTS 内留裸片（ul 直子文本不包 span）", () => {
        const el = chunkEl("<ul>Item one. Item two.</ul>");
        const { sents } = injectSentSpans(el, "en");
        expect(sents).toHaveLength(2); // 句仍登记（对位语料）
        expect(el.querySelectorAll("[data-sid]")).toHaveLength(0);
    });

    it("幂等：strip 归位 → 重注入同形；不 strip 双跑不双包", () => {
        const el = chunkEl("<p>One. Two.</p>");
        injectSentSpans(el, "en");
        const t0 = el.textContent;
        stripSentSpans(el);
        expect(el.textContent).toBe(t0);
        expect(el.querySelectorAll("[data-sid]")).toHaveLength(0);
        injectSentSpans(el, "en");
        expect(el.querySelectorAll("[data-sid]")).toHaveLength(2);
        expect(el.textContent).toBe(t0);
        // 不剥直接重注：已包文本跳过 → 零增量
        const again = injectSentSpans(el, "en");
        expect(again.sents).toHaveLength(0);
        expect(el.querySelectorAll("[data-sid]")).toHaveLength(2);
    });

    it("zh 侧产 span.zhs；sentLen 去掩码计长", () => {
        const el = chunkEl("<p>甲。乙丙丁。</p>");
        const { sents } = injectSentSpans(el, "zh");
        expect(sents).toHaveLength(2);
        expect(el.querySelectorAll("span.zhs")).toHaveLength(2);
        expect(sentLen("式 [[X_1]] 甲乙")).toBe(3); // token→空，甲乙=2+式=3
    });
});

// ================================================================= 会话

const paneBody = (inner: string): HTMLElement => {
    const b = document.createElement("div");
    b.className = "pane-body";
    b.innerHTML = inner;
    document.body.appendChild(b);
    return b;
};

const tick = (ms = 5): Promise<void> => new Promise((r) => setTimeout(r, ms));

describe("SentAlignSession", () => {
    const EN =
        `<div data-chunk="c0"><p>Alpha one. Beta two gamma.</p></div>` +
        `<div data-chunk="c1"><p>Gamma tail.</p></div>`;
    const ZH =
        `<div data-chunk="c0"><p>甲一。乙二丙。</p></div>` +
        `<div data-chunk="c1"><p>丙尾。</p></div>`;

    it("双侧 mount → data-bead 双侧标引（{chunk}.{b} 形）", async () => {
        const en = paneBody(EN);
        const zh = paneBody(ZH);
        const s = new SentAlignSession();
        await s.mountSide("en", en);
        await s.mountSide("zh", zh);
        const beads = new Set<string>();
        for (const sp of document.querySelectorAll("[data-bead]"))
            beads.add(sp.getAttribute("data-bead")!);
        expect(beads).toEqual(new Set(["c0.0", "c0.1", "c1.0"]));
        s.destroy();
    });

    it("悬停：同 sid 全集 .sa-hot + 对侧 bead 全集 .sa-peer；leave 清零", async () => {
        const en = paneBody(EN);
        const zh = paneBody(ZH);
        const s = new SentAlignSession();
        await s.mountSide("en", en);
        await s.mountSide("zh", zh);
        const sp = en.querySelector('[data-sid="c0.0"]')!;
        sp.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
        const hot = document.querySelectorAll(".sa-hot");
        expect(hot).toHaveLength(1);
        expect(hot[0]).toBe(sp);
        const peer = document.querySelectorAll(".sa-peer");
        expect(peer.length).toBeGreaterThan(0);
        for (const p of peer) expect(p.getAttribute("data-bead")).toBe("c0.0");
        // 离开到空白处 → 全清
        sp.dispatchEvent(new MouseEvent("pointerout", { bubbles: true }));
        expect(document.querySelectorAll(".sa-hot,.sa-peer")).toHaveLength(0);
        s.destroy();
    });

    it("无 bead 句悬停只本侧 hot（对侧无伴显）", async () => {
        const en = paneBody(EN);
        const s = new SentAlignSession();
        await s.mountSide("en", en); // 只挂一侧 → 无对位 → 无 bead
        const sp = en.querySelector('[data-sid="c0.0"]')!;
        expect(sp.getAttribute("data-bead")).toBeNull();
        sp.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
        expect(document.querySelectorAll(".sa-hot")).toHaveLength(1);
        expect(document.querySelectorAll(".sa-peer")).toHaveLength(0);
        s.destroy();
    });

    it("点击 → 对侧 bead 首元素 flash + recordJump(pre,post)", async () => {
        const en = paneBody(EN);
        const zh = paneBody(ZH);
        const pos: Pos = { page: 1, fraction: 0 };
        const recordJump = vi.fn();
        const navBegin = vi.fn();
        const s = new SentAlignSession({ recordJump, navBegin });
        await s.mountSide("en", en);
        await s.mountSide("zh", zh, { capture: () => pos });
        const sp = en.querySelector('[data-sid="c0.0"]')!;
        sp.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        expect(navBegin).toHaveBeenCalledTimes(1);
        expect(recordJump).toHaveBeenCalledWith("zh", pos, pos);
        // 落点 .sa-flash 标记在 zh 侧 bead 元素上
        const flashed = document.querySelectorAll(".sa-flash");
        expect(flashed.length).toBeGreaterThan(0);
        for (const f of flashed)
            expect(f.getAttribute("data-bead")).toBe("c0.0");
        s.destroy();
    });

    it("点击守卫：a/button/[data-ph] 内点击不跳", async () => {
        const en = paneBody(
            `<div data-chunk="c0"><p>See <a href="#x">link one</a> here. Tail.</p></div>`,
        );
        const zh = paneBody(`<div data-chunk="c0"><p>甲。尾。</p></div>`);
        const recordJump = vi.fn();
        const s = new SentAlignSession({ recordJump });
        await s.mountSide("en", en);
        await s.mountSide("zh", zh);
        const a = en.querySelector("a")!;
        // 链接文本被句 span 包住（span 是 a 的子级）——点 a 应被守卫拦
        expect(a.querySelector("[data-sid]")).not.toBeNull();
        a.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        expect(recordJump).not.toHaveBeenCalled();
        s.destroy();
    });

    it("MO 增量：新 chunk 自动注入；块内重绘自动重注", async () => {
        const en = paneBody(EN);
        const s = new SentAlignSession({ debounceMs: 0 });
        await s.mountSide("en", en);
        // 新增块
        const d = document.createElement("div");
        d.setAttribute("data-chunk", "c9");
        d.innerHTML = "<p>New one. New two.</p>";
        en.appendChild(d);
        await tick();
        expect(d.querySelectorAll("[data-sid]")).toHaveLength(2);
        // 块内重绘（repaint 形：整段 innerHTML 换掉）
        const c0 = en.querySelector('[data-chunk="c0"]')!;
        c0.innerHTML = "<p>Repaint alpha. Repaint beta.</p>";
        await tick();
        expect(c0.querySelectorAll("[data-sid]")).toHaveLength(2);
        expect(c0.textContent).toBe("Repaint alpha. Repaint beta.");
        s.destroy();
    });

    it("unmount 剥光注入 span（开关关闭零残留）+ 对侧 bead 标清", async () => {
        const en = paneBody(EN);
        const zh = paneBody(ZH);
        const s = new SentAlignSession();
        await s.mountSide("en", en);
        await s.mountSide("zh", zh);
        s.unmountSide("en");
        expect(en.querySelectorAll("[data-sid]")).toHaveLength(0);
        expect(zh.querySelectorAll("[data-bead]")).toHaveLength(0);
        expect(zh.querySelectorAll("[data-sid]").length).toBeGreaterThan(0);
        s.destroy();
    });

    it("DOM→PDF：sid 分位 → mapPos → pdfDest → pdfJump → recordJump", async () => {
        const en = paneBody(
            `<div data-chunk="c0"><p>First half. Second half.</p></div>`,
        );
        const calls: string[] = [];
        const pdfPos: Pos = { page: 3, fraction: 0.5 };
        const s = new SentAlignSession({
            mapPos: (pos) => {
                calls.push(`mapPos:${pos.page}:${pos.fraction.toFixed(2)}`);
                return pdfPos;
            },
            pdfDest: (_d, pos) => {
                calls.push(`pdfDest:${pos.page}`);
                return [pos.page - 1, { name: "XYZ" }, 0, 100, null];
            },
            pdfJump: (_d, dest) => {
                calls.push(`pdfJump:${(dest as unknown[])[0]}`);
                return Promise.resolve({
                    pre: { page: 1, fraction: 0 },
                    post: pdfPos,
                });
            },
            recordJump: (d, pre, post) =>
                calls.push(`recordJump:${d}:${pre?.page}->${post?.page}`),
        });
        await s.mountSide("en", en);
        s.mountPdfSide("zh");
        const sp = en.querySelector('[data-sid="c0.1"]')!;
        sp.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        await tick();
        // 第二句起点 / 拼接长 = 0.5 分位；pdfDest 收到映射后 pos
        expect(calls).toEqual([
            "mapPos:1:0.50",
            "pdfDest:3",
            "pdfJump:2",
            "recordJump:zh:1->3",
        ]);
        s.destroy();
    });

    it("PDF→PDF：pdf 源侧 click → posAtPoint → mapPos/pdfDest/pdfJump → recordJump+pdfFlash", async () => {
        const pdf = paneBody(
            `<div class="textLayer"><span>line one.</span></div>`,
        );
        const calls: string[] = [];
        const s = new SentAlignSession({
            navBegin: () => calls.push("navBegin"),
            mapPos: (pos) => {
                calls.push(`mapPos:${pos.page}:${pos.fraction.toFixed(2)}`);
                return { page: 4, fraction: 0.25 };
            },
            pdfDest: (_d, pos) => {
                calls.push(`pdfDest:${pos.page}`);
                return [pos.page - 1, { name: "XYZ" }, 0, 100, null];
            },
            pdfJump: (_d, dest) => {
                calls.push(`pdfJump:${(dest as unknown[])[0]}`);
                return Promise.resolve({
                    pre: { page: 1, fraction: 0 },
                    post: { page: 4, fraction: 0.25 },
                });
            },
            recordJump: (d, pre, post) =>
                calls.push(`recordJump:${d}:${pre?.page}->${post?.page}`),
            pdfFlash: (d, pos) => {
                calls.push(`pdfFlash:${d}:${pos.page}`);
                return undefined;
            },
        });
        s.mountPdfSide("zh");
        s.mountPdfClickSource("en", pdf, (x, y) => {
            calls.push(`posAtPoint:${x},${y}`);
            return { page: 2, fraction: 0.5 };
        });
        const sp = pdf.querySelector("span")!;
        sp.dispatchEvent(
            new MouseEvent("click", {
                bubbles: true,
                clientX: 10,
                clientY: 20,
            }),
        );
        await tick();
        expect(calls).toEqual([
            "posAtPoint:10,20",
            "navBegin",
            "mapPos:2:0.50",
            "pdfDest:4",
            "pdfJump:3",
            "recordJump:zh:1->4",
            "pdfFlash:zh:4",
        ]);
        // posAtPoint null（页间缝/容器外）→ 不跳
        calls.length = 0;
        s.mountPdfClickSource("en", pdf, () => null);
        sp.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        await tick();
        expect(calls).toEqual([]);
        // unmountSide 摘监听——点击源随侧卸载
        s.unmountSide("en");
        s.mountPdfClickSource("en", pdf, () => ({ page: 2, fraction: 0 }));
        s.unmountSide("en");
        sp.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        await tick();
        expect(calls).toEqual([]);
        s.destroy();
    });

    it("PDF→PDF seq 快路：seqAtPoint 命中 → seqPos/pdfDest/pdfJump → recordJump+pdfFlashSeq（posAtPoint/mapPos 不碰）", async () => {
        const pdf = paneBody(
            `<div class="textLayer"><span>line one.</span></div>`,
        );
        const calls: string[] = [];
        const s = new SentAlignSession({
            navBegin: () => calls.push("navBegin"),
            seqPos: (seq, side) => {
                calls.push(`seqPos:${seq}:${side}`);
                return { page: 6, fraction: 0.3 };
            },
            pdfDest: (_d, pos) => {
                calls.push(`pdfDest:${pos.page}`);
                return [pos.page - 1, { name: "XYZ" }, 0, 100, null];
            },
            pdfJump: (_d, dest) => {
                calls.push(`pdfJump:${(dest as unknown[])[0]}`);
                return Promise.resolve({
                    pre: { page: 1, fraction: 0 },
                    post: { page: 6, fraction: 0.3 },
                });
            },
            recordJump: (d, pre, post) =>
                calls.push(`recordJump:${d}:${pre?.page}->${post?.page}`),
            pdfFlash: (d, pos) => {
                calls.push(`pdfFlash:${d}:${pos.page}`);
                return undefined;
            },
            pdfFlashSeq: (d, seq, pos) => {
                calls.push(`pdfFlashSeq:${d}:${seq}:${pos?.page}`);
                return undefined;
            },
            mapPos: () => {
                calls.push("mapPos");
                return { page: 0, fraction: 0 };
            },
        });
        s.mountPdfSide("zh");
        s.mountPdfClickSource(
            "en",
            pdf,
            (x, y) => {
                calls.push(`posAtPoint:${x},${y}`);
                return { page: 2, fraction: 0.5 };
            },
            (x, y) => {
                calls.push(`seqAtPoint:${x},${y}`);
                return 42;
            },
        );
        const sp = pdf.querySelector("span")!;
        sp.dispatchEvent(
            new MouseEvent("click", {
                bubbles: true,
                clientX: 10,
                clientY: 20,
            }),
        );
        await tick();
        // seq 快路全程不碰 posAtPoint/mapPos——seqPos 直锚 + 锚闪
        // （navBegin 在 seqPos 落定后——不可落地不静音导航）
        expect(calls).toEqual([
            "seqAtPoint:10,20",
            "seqPos:42:zh",
            "navBegin",
            "pdfDest:6",
            "pdfJump:5",
            "recordJump:zh:1->6",
            "pdfFlashSeq:zh:42:6",
        ]);
        s.destroy();
    });

    // ---- 句级落点臂（pdfSentAt + pdfFlashEls）----
    const rectOf = (top: number, left = 0, width = 100, height = 12) =>
        ({
            top,
            left,
            width,
            height,
            right: left + width,
            bottom: top + height,
            x: left,
            y: top,
            toJSON: () => ({}),
        }) as DOMRect;
    /** 假 zh marked 叶组：page div + markedContent + 三句各 4 字 */
    const fakeZhLeaves = (mcid = 50042, page = 3) => {
        const pg = document.createElement("div");
        pg.setAttribute("data-page-number", String(page));
        pg.innerHTML =
            `<span class="markedContent" id="_mc${mcid}">` +
            `<span>甲句一。</span><span>乙句二。</span><span>丙句三。</span>` +
            `</span>`;
        document.body.appendChild(pg);
        pg.getBoundingClientRect = () => rectOf(0, 0, 400, 800);
        const leaves = [
            ...pg.querySelector<HTMLElement>(".markedContent")!.children,
        ] as HTMLElement[];
        leaves[0]!.getBoundingClientRect = () => rectOf(100, 10, 200);
        leaves[1]!.getBoundingClientRect = () => rectOf(112, 10, 200);
        leaves[2]!.getBoundingClientRect = () => rectOf(300, 10, 200);
        return leaves;
    };
    const LANDS = (side: SaSide) =>
        side === "en"
            ? [
                  {
                      seq: 42,
                      pos: { page: 2, fraction: 0.1, x: 0, x1: 0.4 },
                  },
                  {
                      seq: 43,
                      pos: { page: 2, fraction: 0.9, x: 0, x1: 0.4 },
                  },
              ]
            : [
                  {
                      seq: 42,
                      pos: { page: 3, fraction: 0.1, x: 0, x1: 0.4 },
                  },
                  {
                      seq: 43,
                      pos: { page: 3, fraction: 0.9, x: 0, x1: 0.4 },
                  },
              ];

    it("PDF→PDF 句级落点：u 在场+dst 叶在场 → 句首叶 Pos + pdfFlashEls 句域闪（不碰整段闪）", async () => {
        const pdf = paneBody(`<div class="textLayer"><span>line.</span></div>`);
        const leaves = fakeZhLeaves();
        const calls: string[] = [];
        const s = new SentAlignSession({
            navBegin: () => calls.push("navBegin"),
            seqPos: () => ({ page: 3, fraction: 0.1 }),
            seqLands: LANDS,
            pdfSeqLeaves: () => leaves,
            pdfFlashEls: (_d, els) => calls.push(`pdfFlashEls:${els.length}`),
            pdfDest: (_d, pos) => {
                calls.push(`pdfDest:${pos.page}@${pos.fraction.toFixed(2)}`);
                return [pos.page - 1, { name: "XYZ" }, 0, 0, null];
            },
            pdfJump: () =>
                Promise.resolve({
                    pre: { page: 1, fraction: 0 },
                    post: { page: 3, fraction: 0.375 },
                }),
            recordJump: (d) => calls.push(`recordJump:${d}`),
            pdfFlashSeq: () => {
                calls.push("pdfFlashSeq");
                return undefined;
            },
        });
        s.mountPdfSide("zh");
        s.mountPdfClickSource(
            "en",
            pdf,
            () => ({ page: 2, fraction: 0.66, x: 0.1 }),
            () => 42,
        );
        pdf.querySelector("span")!.dispatchEvent(
            new MouseEvent("click", {
                bubbles: true,
                clientX: 5,
                clientY: 5,
            }),
        );
        await tick();
        // u=(2.33-2.05)/0.4=0.7 → target 8.4 → 第三句 [8,12)
        // → 句首叶 fraction=300/800=0.375
        expect(calls).toContain("pdfDest:3@0.38");
        expect(calls).toContain("pdfFlashEls:1");
        expect(calls).not.toContain("pdfFlashSeq");
        s.destroy();
    });

    it("句级臂叶缺席 → 锚区间插值落点 + pdfFlash 行带→整段殿后", async () => {
        const pdf = paneBody(`<div class="textLayer"><span>line.</span></div>`);
        const calls: string[] = [];
        const s = new SentAlignSession({
            seqPos: () => ({ page: 3, fraction: 0.1 }),
            seqLands: LANDS,
            pdfSeqLeaves: () => [],
            pdfFlashEls: () => calls.push("pdfFlashEls"),
            pdfDest: (_d, pos) => {
                calls.push(`pdfDest:${pos.page}@${pos.fraction.toFixed(2)}`);
                return [pos.page - 1, { name: "XYZ" }, 0, 0, null];
            },
            pdfJump: () =>
                Promise.resolve({
                    pre: { page: 1, fraction: 0 },
                    post: { page: 3, fraction: 0.66 },
                }),
            recordJump: () => {},
            pdfFlash: (_d, pos) => {
                calls.push(`pdfFlash:${pos.page}`);
                return [];
            },
            pdfFlashSeq: (_d, seq) => {
                calls.push(`pdfFlashSeq:${seq}`);
                return undefined;
            },
        });
        s.mountPdfSide("zh");
        s.mountPdfClickSource(
            "en",
            pdf,
            () => ({ page: 2, fraction: 0.66, x: 0.1 }),
            () => 42,
        );
        pdf.querySelector("span")!.dispatchEvent(
            new MouseEvent("click", { bubbles: true, clientX: 1, clientY: 1 }),
        );
        await tick();
        // 叶缺席 → interpDst：zh 区间 3.05→3.45，u=0.7 → y=3.33
        // → {page:3, fraction:0.66}
        expect(calls).toContain("pdfDest:3@0.66");
        expect(calls).toContain("pdfFlash:3");
        expect(calls).toContain("pdfFlashSeq:42");
        expect(calls).not.toContain("pdfFlashEls");
        s.destroy();
    });

    it("marked 双出现（TOC 重放+真标）→ 按锚页择真标组", async () => {
        const pdf = paneBody(`<div class="textLayer"><span>line.</span></div>`);
        // 同 seq 两枚 marked：p1 TOC 残件 + p3 正文真标
        const tocPg = document.createElement("div");
        tocPg.setAttribute("data-page-number", "1");
        tocPg.innerHTML =
            `<span class="markedContent" id="_mc50042">` +
            `<span>目录残。</span></span>`;
        document.body.appendChild(tocPg);
        tocPg.getBoundingClientRect = () => rectOf(0, 0, 400, 800);
        const tocLeaf = tocPg.querySelector<HTMLElement>(
            ".markedContent span",
        )!;
        tocLeaf.getBoundingClientRect = () => rectOf(50, 10, 200);
        const leaves = fakeZhLeaves();
        const calls: string[] = [];
        const s = new SentAlignSession({
            seqPos: () => ({ page: 3, fraction: 0.1 }), // 锚在 p3
            seqLands: LANDS,
            pdfSeqLeaves: () => [tocLeaf, ...leaves],
            pdfFlashEls: (_d, els) =>
                calls.push(
                    `pdfFlashEls:${els.map((e) => e.textContent).join(",")}`,
                ),
            pdfDest: (_d, pos) => {
                calls.push(`pdfDest:${pos.page}@${pos.fraction.toFixed(2)}`);
                return [pos.page - 1, { name: "XYZ" }, 0, 0, null];
            },
            pdfJump: () =>
                Promise.resolve({
                    pre: { page: 1, fraction: 0 },
                    post: { page: 3, fraction: 0.375 },
                }),
            recordJump: () => {},
        });
        s.mountPdfSide("zh");
        s.mountPdfClickSource(
            "en",
            pdf,
            () => ({ page: 2, fraction: 0.66, x: 0.1 }),
            () => 42,
        );
        pdf.querySelector("span")!.dispatchEvent(
            new MouseEvent("click", { bubbles: true, clientX: 1, clientY: 1 }),
        );
        await tick();
        // 真标组被选中 → 落点在 p3 句首叶而非 TOC 残件
        expect(calls).toContain("pdfDest:3@0.38");
        expect(calls).toContain("pdfFlashEls:丙句三。");
        s.destroy();
    });

    it("DOM→PDF 句级落点：sid 点击 → pdfSentAt 句首 Pos + 句域闪", async () => {
        const en = paneBody(
            `<div data-chunk="c0"><p>First half. Second half.</p></div>`,
        );
        const leaves = fakeZhLeaves();
        const calls: string[] = [];
        const s = new SentAlignSession({
            seqOfChunk: (k) => (k === "c0" ? 42 : null),
            seqPos: () => ({ page: 3, fraction: 0.1 }),
            seqLands: LANDS,
            pdfSeqLeaves: () => leaves,
            pdfFlashEls: (_d, els) => calls.push(`pdfFlashEls:${els.length}`),
            pdfDest: (_d, pos) => {
                calls.push(`pdfDest:${pos.page}@${pos.fraction.toFixed(2)}`);
                return [pos.page - 1, { name: "XYZ" }, 0, 0, null];
            },
            pdfJump: () =>
                Promise.resolve({
                    pre: { page: 1, fraction: 0 },
                    post: { page: 3, fraction: 0.14 },
                }),
            recordJump: () => {},
            pdfFlashSeq: () => {
                calls.push("pdfFlashSeq");
                return undefined;
            },
        });
        await s.mountSide("en", en);
        s.mountPdfSide("zh");
        en.querySelector('[data-sid="c0.1"]')!.dispatchEvent(
            new MouseEvent("click", { bubbles: true, clientX: 1, clientY: 1 }),
        );
        await tick();
        // u=Second半句起点/24≈0.5 → target 6 → 第二句 [4,8) → 叶1
        // fraction=112/800=0.14
        expect(calls).toContain("pdfDest:3@0.14");
        expect(calls).toContain("pdfFlashEls:1");
        expect(calls).not.toContain("pdfFlashSeq");
        s.destroy();
    });

    it("seq 快路不可落地（seqPos null）→ 落回 posAtPoint 兜底臂", async () => {
        const pdf = paneBody(`<div class="textLayer"><span>x.</span></div>`);
        const calls: string[] = [];
        const press = vi.fn();
        const s = new SentAlignSession({
            seqPos: () => null,
            mapPos: () => ({ page: 3, fraction: 0.5 }),
            pdfDest: (_d, pos) => [pos.page - 1, { name: "XYZ" }, 0, 0, null],
            pdfJump: () =>
                Promise.resolve({
                    pre: { page: 1, fraction: 0 },
                    post: { page: 3, fraction: 0.5 },
                }),
            recordJump: (d) => calls.push(`recordJump:${d}`),
            anim: { press },
        });
        s.mountPdfSide("zh");
        s.mountPdfClickSource(
            "en",
            pdf,
            () => {
                calls.push("posAtPoint");
                return { page: 2, fraction: 0.4 };
            },
            () => {
                calls.push("seqAtPoint");
                return 7;
            },
        );
        pdf.querySelector("span")!.dispatchEvent(
            new MouseEvent("click", { bubbles: true, clientX: 1, clientY: 1 }),
        );
        await tick();
        // seqAtPoint 给了 seq 但 seqPos 查不到 → jumpSeq false → 兜底
        expect(calls).toEqual(["seqAtPoint", "posAtPoint", "recordJump:zh"]);
        // seq 臂涟漪与兜底臂共一次点击——press 恰一次不双击
        expect(press).toHaveBeenCalledTimes(1);
        s.destroy();
    });

    it("PDF→DOM：seq 命中对侧 DOM → 块滚位 + sa-flash + recordJump", async () => {
        const pdf = paneBody(`<div class="textLayer"><span>x.</span></div>`);
        const zh = paneBody(
            `<div data-chunk="S1.p1"><p>甲。</p></div>` +
                `<div data-chunk="S1.p2"><p>乙二。</p></div>`,
        );
        const calls: string[] = [];
        const pos: Pos = { page: 1, fraction: 0 };
        const s = new SentAlignSession({
            navBegin: () => calls.push("navBegin"),
            seqOfChunk: (k) => (k === "S1.p2" ? 7 : null),
            recordJump: (d, pre, post) =>
                calls.push(`recordJump:${d}:${pre?.page}->${post?.page}`),
        });
        await s.mountSide("zh", zh, { capture: () => pos });
        s.mountPdfClickSource(
            "en",
            pdf,
            () => {
                calls.push("posAtPoint");
                return { page: 2, fraction: 0.4 };
            },
            () => 7,
        );
        pdf.querySelector("span")!.dispatchEvent(
            new MouseEvent("click", { bubbles: true, clientX: 5, clientY: 5 }),
        );
        await tick();
        expect(calls).toEqual(["navBegin", "recordJump:zh:1->1"]);
        // 落点闪示打在 seq 对应的 chunk 块上
        const flashed = zh.querySelectorAll(".sa-flash");
        expect(flashed).toHaveLength(1);
        expect(flashed[0]!.getAttribute("data-chunk")).toBe("S1.p2");
        s.destroy();
    });

    it("DOM→PDF seq 快路：sid 点击 → seqOfChunk+seqPos 直锚（mapPos 不碰）+ pdfFlashSeq", async () => {
        const en = paneBody(
            `<div data-chunk="c0"><p>First half. Second half.</p></div>`,
        );
        const calls: string[] = [];
        const s = new SentAlignSession({
            seqOfChunk: (k) => (k === "c0" ? 11 : null),
            seqPos: (seq, side) => {
                calls.push(`seqPos:${seq}:${side}`);
                return { page: 8, fraction: 0.2 };
            },
            pdfDest: (_d, pos) => {
                calls.push(`pdfDest:${pos.page}`);
                return [pos.page - 1, { name: "XYZ" }, 0, 50, null];
            },
            pdfJump: (_d, dest) => {
                calls.push(`pdfJump:${(dest as unknown[])[0]}`);
                return Promise.resolve({
                    pre: { page: 1, fraction: 0 },
                    post: { page: 8, fraction: 0.2 },
                });
            },
            recordJump: (d, pre, post) =>
                calls.push(`recordJump:${d}:${pre?.page}->${post?.page}`),
            pdfFlashSeq: (d, seq, pos) => {
                calls.push(`pdfFlashSeq:${d}:${seq}:${pos?.page}`);
                return undefined;
            },
            mapPos: () => {
                calls.push("mapPos");
                return { page: 0, fraction: 0 };
            },
        });
        await s.mountSide("en", en);
        s.mountPdfSide("zh");
        const sp = en.querySelector('[data-sid="c0.1"]')!;
        sp.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        await tick();
        expect(calls).toEqual([
            "seqPos:11:zh",
            "pdfDest:8",
            "pdfJump:7",
            "recordJump:zh:1->8",
            "pdfFlashSeq:zh:11:8",
        ]);
        s.destroy();
    });
});

// ================================================================= 动效臂

describe("句对位动效（press/land/pdfHover 接线）", () => {
    const EN =
        `<div data-chunk="c0"><p>Alpha one. Beta two gamma.</p></div>` +
        `<div data-chunk="c1"><p>Gamma tail.</p></div>`;
    const ZH =
        `<div data-chunk="c0"><p>甲一。乙二丙。</p></div>` +
        `<div data-chunk="c1"><p>丙尾。</p></div>`;

    it("DOM 点击 → anim.press(点击点) + jump 落定后 anim.land(源点, bead els)", async () => {
        const en = paneBody(
            `<div data-chunk="c0"><p>Alpha one. Beta two.</p></div>`,
        );
        const zh = paneBody(`<div data-chunk="c0"><p>甲一。乙二。</p></div>`);
        const pos: Pos = { page: 1, fraction: 0 };
        const press = vi.fn();
        const land = vi.fn();
        const s = new SentAlignSession({ anim: { press, land } });
        await s.mountSide("en", en);
        await s.mountSide("zh", zh, { capture: () => pos });
        en.querySelector('[data-sid="c0.0"]')!.dispatchEvent(
            new MouseEvent("click", {
                bubbles: true,
                clientX: 33,
                clientY: 44,
            }),
        );
        await tick();
        expect(press).toHaveBeenCalledWith(33, 44);
        expect(land).toHaveBeenCalledTimes(1);
        const [from, els] = land.mock.calls[0]! as [
            { x: number; y: number },
            Element[],
        ];
        expect(from).toMatchObject({ x: 33, y: 44 });
        expect(els.length).toBeGreaterThan(0);
        for (const el of els) expect(el.getAttribute("data-bead")).toBe("c0.0");
        s.destroy();
    });

    it("PDF 点击 → press + pdfFlashSeq 元素集喂给 land", async () => {
        const pdf = paneBody(`<div class="textLayer"><span>x.</span></div>`);
        const flashEl = document.createElement("span");
        const press = vi.fn();
        const land = vi.fn();
        const s = new SentAlignSession({
            anim: { press, land },
            seqPos: () => ({ page: 6, fraction: 0.3 }),
            pdfDest: (_d, pos) => [pos.page - 1, { name: "XYZ" }, 0, 100, null],
            pdfJump: () =>
                Promise.resolve({
                    pre: { page: 1, fraction: 0 },
                    post: { page: 6, fraction: 0.3 },
                }),
            pdfFlashSeq: () => [flashEl],
        });
        s.mountPdfSide("zh");
        s.mountPdfClickSource(
            "en",
            pdf,
            () => ({ page: 2, fraction: 0.5 }),
            () => 42,
        );
        pdf.querySelector("span")!.dispatchEvent(
            new MouseEvent("click", {
                bubbles: true,
                clientX: 9,
                clientY: 8,
            }),
        );
        await tick();
        expect(press).toHaveBeenCalledWith(9, 8);
        expect(land).toHaveBeenCalledTimes(1);
        expect(land.mock.calls[0]![1]).toEqual([flashEl]);
        s.destroy();
    });

    it("mountPdfHoverSource：move → 本侧 sa-hot + 对侧 sa-peer；同 seq 随 pos 重补（dedup 在写层）；leave/链接 清轨", async () => {
        const pdf = paneBody(
            `<div class="textLayer"><a href="#">l</a><span>x.</span></div>`,
        );
        const calls: string[] = [];
        const s = new SentAlignSession({
            seqPos: () => ({ page: 7, fraction: 0.5 }),
            pdfHover: (side, seq, pos, cls) =>
                calls.push(
                    `h:${side}:${seq}:${cls}${pos ? ":" + pos.page : ""}`,
                ),
        });
        s.mountPdfSide("zh");
        s.mountPdfHoverSource(
            "en",
            pdf,
            () => 5,
            () => ({ page: 1, fraction: 0.2 }),
        );
        const sp = pdf.querySelector("span")!;
        // 拖选守卫——buttons!=0 不跟手
        sp.dispatchEvent(
            new MouseEvent("pointermove", { bubbles: true, buttons: 1 }),
        );
        expect(calls).toEqual([]);
        // 正常跟手——本侧 hot（pos 随行）+ 对侧 peer（seqPos 落点）
        sp.dispatchEvent(
            new MouseEvent("pointermove", {
                bubbles: true,
                clientX: 1,
                clientY: 1,
            }),
        );
        expect(calls).toEqual(["h:en:5:sa-hot:1", "h:zh:5:sa-peer:7"]);
        // 同 seq 再动（过节流）——hot/peer 都随 pos 重算（句级跟手；
        // 无 seqLands 句料 u=null → 对侧退整锚重发，dedup 在元素写层）
        calls.length = 0;
        await tick(70);
        sp.dispatchEvent(
            new MouseEvent("pointermove", {
                bubbles: true,
                clientX: 2,
                clientY: 2,
            }),
        );
        expect(calls).toEqual(["h:en:5:sa-hot:1", "h:zh:5:sa-peer:7"]);
        // 移上链接 → 双轨清
        calls.length = 0;
        await tick(70);
        pdf.querySelector("a")!.dispatchEvent(
            new MouseEvent("pointermove", { bubbles: true }),
        );
        expect(calls).toEqual(["h:en:null:sa-hot", "h:zh:null:sa-peer"]);
        // leave → 再清一轮双轨（armPdfPeer(null) 对侧也剥）
        calls.length = 0;
        pdf.dispatchEvent(new MouseEvent("pointerleave", { bubbles: true }));
        expect(calls).toEqual(["h:en:null:sa-hot", "h:zh:null:sa-peer"]);
        s.destroy();
    });

    it("DOM→PDF 悬停：sid pointerover → pdfHover(对侧,seq,seqPos,sa-peer)；离开清 pdf 轨", async () => {
        const en = paneBody(
            `<div data-chunk="c0"><p>Alpha one. Beta two.</p></div>`,
        );
        const calls: string[] = [];
        const s = new SentAlignSession({
            seqOfChunk: (k) => (k === "c0" ? 23 : null),
            seqPos: () => ({ page: 7, fraction: 0.6 }),
            pdfHover: (side, seq, pos, cls) =>
                calls.push(
                    `h:${side}:${seq}:${cls}${pos ? ":" + pos.page : ""}`,
                ),
        });
        await s.mountSide("en", en);
        s.mountPdfSide("zh");
        const sp = en.querySelector('[data-sid="c0.0"]')!;
        sp.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
        // bead 是 DOM↔DOM 概念——pdf 对侧无 bead 也有 seq 对位；
        // 先两发 clearHot 剥轨再上新 peer
        expect(calls).toEqual([
            "h:en:null:sa-peer",
            "h:zh:null:sa-peer",
            "h:zh:23:sa-peer:7",
        ]);
        expect(en.querySelectorAll(".sa-hot")).toHaveLength(1);
        calls.length = 0;
        sp.dispatchEvent(new MouseEvent("pointerout", { bubbles: true }));
        // clearHot 两侧 pdf 轨一并剥
        expect(calls).toEqual(["h:en:null:sa-peer", "h:zh:null:sa-peer"]);
        s.destroy();
    });

    it("pdf hover + DOM 对侧：seq↔chunk 1:1 peer 走会话 peerEls——leave/clearHot 同源扫", async () => {
        const pdf = paneBody(`<div class="textLayer"><span>x.</span></div>`);
        const zh = paneBody(`<div data-chunk="c9"><p>甲一。乙二。</p></div>`);
        const calls: string[] = [];
        const s = new SentAlignSession({
            seqOfChunk: (k) => (k === "c9" ? 31 : null),
            pdfHover: (side, seq, _pos, cls) =>
                calls.push(`${side}:${seq}:${cls}`),
        });
        await s.mountSide("zh", zh);
        s.mountPdfHoverSource(
            "en",
            pdf,
            () => 31,
            () => ({ page: 1, fraction: 0.5 }),
        );
        pdf.querySelector("span")!.dispatchEvent(
            new MouseEvent("pointermove", { bubbles: true }),
        );
        // 本侧 sa-hot 走桥；DOM 对侧不涉 pdfHover——块内 sid 全挂 peer
        expect(calls).toEqual(["en:31:sa-hot"]);
        expect(zh.querySelectorAll(".sa-peer").length).toBeGreaterThan(0);
        await tick(70);
        // pdf 悬停仍在场时 DOM 侧 pointerover——clearHot 须把 pdf 臂
        // 养在 peerEls 里的 sa-peer 一并扫走再武装新 DOM 悬停
        const zhSp = zh.querySelector('[data-sid="c9.0"]')!;
        zhSp.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
        expect(zh.querySelectorAll(".sa-peer")).toHaveLength(0);
        expect(zh.querySelectorAll(".sa-hot").length).toBeGreaterThan(0);
        zhSp.dispatchEvent(new MouseEvent("pointerout", { bubbles: true }));
        // 重新 pdf 悬停后再走 leave——peer 清零
        calls.length = 0;
        pdf.querySelector("span")!.dispatchEvent(
            new MouseEvent("pointermove", { bubbles: true }),
        );
        expect(zh.querySelectorAll(".sa-peer").length).toBeGreaterThan(0);
        pdf.dispatchEvent(new MouseEvent("pointerleave", { bubbles: true }));
        expect(zh.querySelectorAll(".sa-peer")).toHaveLength(0);
        s.destroy();
    });

    it("跨侧 1:1 同 sid 直移不撞 dedup key——en→zh 悬停正常换轨", async () => {
        const en = paneBody(EN);
        const zh = paneBody(ZH);
        const s = new SentAlignSession();
        await s.mountSide("en", en);
        await s.mountSide("zh", zh);
        const enSp = en.querySelector('[data-sid="c0.0"]')!;
        const zhSp = zh.querySelector('[data-sid="c0.0"]')!;
        // 双侧 c0.0 同字——dedup 键不带侧名时 out/over 双双被吞
        enSp.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
        expect(en.querySelectorAll(".sa-hot")).toHaveLength(1);
        // 直移到 zh 同字 span：out(relatedTarget=zhSp)+over
        enSp.dispatchEvent(
            new MouseEvent("pointerout", {
                bubbles: true,
                relatedTarget: zhSp,
            }),
        );
        zhSp.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
        expect(en.querySelectorAll(".sa-hot")).toHaveLength(0);
        expect(zh.querySelectorAll(".sa-hot")).toHaveLength(1);
        // zh 悬停 en 侧 bead 伴显照常
        expect(en.querySelectorAll(".sa-peer").length).toBeGreaterThan(0);
        s.destroy();
    });

    it("重注保命：悬停块被 injectChunk 重切后按原 sid 补臂", async () => {
        const en = paneBody(EN);
        const zh = paneBody(ZH);
        const s = new SentAlignSession();
        await s.mountSide("en", en);
        await s.mountSide("zh", zh);
        const sp = en.querySelector('[data-sid="c0.0"]')!;
        sp.dispatchEvent(new MouseEvent("pointerover", { bubbles: true }));
        expect(en.querySelectorAll(".sa-hot")).toHaveLength(1);
        expect(zh.querySelectorAll(".sa-peer").length).toBeGreaterThan(0);
        // 模拟 MO 重注（repaint 路径）——悬停中的 chunk 被剥重包
        s.injectChunk("en", en.querySelector('[data-chunk="c0"]')!);
        const nsp = en.querySelector('[data-sid="c0.0"]')!;
        expect(nsp).not.toBe(sp); // span 确已换新
        expect(nsp.classList.contains("sa-hot")).toBe(true);
        expect(zh.querySelectorAll(".sa-peer").length).toBeGreaterThan(0);
        s.destroy();
    });

    it("重注保命：pdf 悬停臂的 DOM peer 块被重切后按存活 seq 补染", async () => {
        const pdf = paneBody(`<div class="textLayer"><span>x.</span></div>`);
        const zh = paneBody(ZH);
        const s = new SentAlignSession({
            seqOfChunk: (k) => (k === "c0" ? 31 : null),
        });
        await s.mountSide("zh", zh);
        s.mountPdfHoverSource(
            "en",
            pdf,
            () => 31,
            () => ({ page: 1, fraction: 0.5 }),
        );
        pdf.querySelector("span")!.dispatchEvent(
            new MouseEvent("pointermove", { bubbles: true }),
        );
        expect(zh.querySelectorAll(".sa-peer").length).toBeGreaterThan(0);
        const old = zh.querySelector(".sa-peer")!;
        s.injectChunk("zh", zh.querySelector('[data-chunk="c0"]')!);
        const peers = zh.querySelectorAll(".sa-peer");
        expect(peers.length).toBeGreaterThan(0);
        expect(peers[0]).not.toBe(old); // 新 span 新染——不是亡件残留
        s.destroy();
    });

    it("悬停节流带尾沿——窗内末笔移动补评不丢 seq", async () => {
        const pdf = paneBody(`<div class="textLayer"><span>x.</span></div>`);
        const calls: string[] = [];
        const s = new SentAlignSession({
            seqPos: () => ({ page: 7, fraction: 0.5 }),
            pdfHover: (side, seq, _pos, cls) =>
                calls.push(`${side}:${seq}:${cls}`),
        });
        s.mountPdfSide("zh");
        s.mountPdfHoverSource(
            "en",
            pdf,
            (x) => (x >= 2 ? 6 : 5),
            () => ({ page: 1, fraction: 0.2 }),
        );
        const sp = pdf.querySelector("span")!;
        sp.dispatchEvent(
            new MouseEvent("pointermove", {
                bubbles: true,
                clientX: 1,
                clientY: 1,
            }),
        );
        // 窗内第二笔（x=2→seq6）被节流压住，但尾沿须补评——
        // 指针停句上后悬停不许留在 seq5
        sp.dispatchEvent(
            new MouseEvent("pointermove", {
                bubbles: true,
                clientX: 2,
                clientY: 2,
            }),
        );
        expect(calls).toEqual(["en:5:sa-hot", "zh:5:sa-peer"]);
        calls.length = 0;
        await tick(80);
        expect(calls).toEqual(["en:6:sa-hot", "zh:6:sa-peer"]);
        s.destroy();
    });

    it("窗格滚动扫悬停——pdf 臂 scroll 即清轨（scroll 不冒泡走 capture）", async () => {
        const pdf = paneBody(`<div class="textLayer"><span>x.</span></div>`);
        const calls: string[] = [];
        const s = new SentAlignSession({
            seqPos: () => ({ page: 7, fraction: 0.5 }),
            pdfHover: (side, seq, _pos, cls) =>
                calls.push(`${side}:${seq}:${cls}`),
        });
        s.mountPdfSide("zh");
        s.mountPdfHoverSource(
            "en",
            pdf,
            () => 5,
            () => ({ page: 1, fraction: 0.2 }),
        );
        pdf.querySelector("span")!.dispatchEvent(
            new MouseEvent("pointermove", { bubbles: true }),
        );
        expect(calls).toEqual(["en:5:sa-hot", "zh:5:sa-peer"]);
        calls.length = 0;
        pdf.dispatchEvent(new Event("scroll"));
        expect(calls).toEqual(["en:null:sa-hot", "zh:null:sa-peer"]);
        s.destroy();
    });

    it("DOM 侧滚动扫悬停——scroller scroll → clearHot", async () => {
        const en = paneBody(EN);
        const zh = paneBody(ZH);
        const s = new SentAlignSession();
        await s.mountSide("en", en);
        await s.mountSide("zh", zh);
        en.querySelector('[data-sid="c0.0"]')!.dispatchEvent(
            new MouseEvent("pointerover", { bubbles: true }),
        );
        expect(en.querySelectorAll(".sa-hot")).toHaveLength(1);
        en.dispatchEvent(new Event("scroll")); // scroller 缺省=body
        expect(document.querySelectorAll(".sa-hot,.sa-peer")).toHaveLength(0);
        s.destroy();
    });

    it("pdfFlash 行带兜底臂的元素集也喂 land（无 pdfFlashSeq 时）", async () => {
        const pdf = paneBody(`<div class="textLayer"><span>x.</span></div>`);
        const bandEl = document.createElement("span");
        const land = vi.fn();
        const s = new SentAlignSession({
            anim: { land },
            mapPos: () => ({ page: 3, fraction: 0.5 }),
            pdfDest: (_d, pos) => [pos.page - 1, { name: "XYZ" }, 0, 0, null],
            pdfJump: () =>
                Promise.resolve({
                    pre: { page: 1, fraction: 0 },
                    post: { page: 3, fraction: 0.5 },
                }),
            pdfFlash: () => [bandEl],
        });
        s.mountPdfSide("zh");
        s.mountPdfClickSource(
            "en",
            pdf,
            () => ({ page: 2, fraction: 0.4 }),
            () => null,
        );
        pdf.querySelector("span")!.dispatchEvent(
            new MouseEvent("click", { bubbles: true, clientX: 4, clientY: 4 }),
        );
        await tick();
        expect(land).toHaveBeenCalledTimes(1);
        expect(land.mock.calls[0]![0]).toMatchObject({ x: 4, y: 4 });
        expect(land.mock.calls[0]![1]).toEqual([bandEl]);
        s.destroy();
    });

    it("gotoPeer 非点击跳——land from=null 只擦入不连线", async () => {
        const en = paneBody(EN);
        const zh = paneBody(ZH);
        const land = vi.fn();
        const s = new SentAlignSession({ anim: { land } });
        await s.mountSide("en", en);
        // 先一次落空点击（zh 未挂、无 pdf deps——旧单槽制会滞留源点）
        en.querySelector('[data-sid="c0.0"]')!.dispatchEvent(
            new MouseEvent("click", { bubbles: true }),
        );
        await s.mountSide("zh", zh);
        // 参数透传制下残点无从泄漏——命令跳 land 只收 null
        s.jumpToPeer("c0.1", "en");
        expect(land).toHaveBeenCalledTimes(1);
        expect(land.mock.calls[0]![0]).toBeNull();
        expect((land.mock.calls[0]![1] as Element[]).length).toBeGreaterThan(0);
        s.destroy();
    });
});
