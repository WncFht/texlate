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
        expect(texts(t, splitZh(t))).toEqual([
            "版本 v2. 已发布。",
            "下一版。",
        ]);
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

const tick = (ms = 5): Promise<void> =>
    new Promise((r) => setTimeout(r, ms));

describe("SentAlignSession", () => {
    const EN = `<div data-chunk="c0"><p>Alpha one. Beta two gamma.</p></div>` +
        `<div data-chunk="c1"><p>Gamma tail.</p></div>`;
    const ZH = `<div data-chunk="c0"><p>甲一。乙二丙。</p></div>` +
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
        sp.dispatchEvent(
            new MouseEvent("pointerover", { bubbles: true }),
        );
        const hot = document.querySelectorAll(".sa-hot");
        expect(hot).toHaveLength(1);
        expect(hot[0]).toBe(sp);
        const peer = document.querySelectorAll(".sa-peer");
        expect(peer.length).toBeGreaterThan(0);
        for (const p of peer)
            expect(p.getAttribute("data-bead")).toBe("c0.0");
        // 离开到空白处 → 全清
        sp.dispatchEvent(
            new MouseEvent("pointerout", { bubbles: true }),
        );
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
});
