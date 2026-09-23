// @vitest-environment jsdom
// find-usages 数据面测试：
//   A. buildUsageIndex —— 真实 arxiv_html_1706 fixture 全类索引
//     （枚举零引用目标 / 锚归并宿主 / chrome 滤除 / 自指丢弃 / 同句并站 /
//      forEl 后代命中）
//   B. 句界护栏——sentenceStarts（DOM 路）+ maskedSentenceStarts/At
//     （掩码路 batch.sentence_ends 移植）缩写/深度/转义/硬界
//   C. buildCiteUsageMap —— 多键拆/畸形 key 回退/漂移自检/无 ph 退化
//   D. zh 配对——fillPairZh 跨 pane (id,ord) 对
//   E. cardPlacement 纯函数夹取/翻转
//   F. classifyTarget / usageHostOf

import { beforeAll, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import {
    buildCiteUsageMap,
    buildUsageIndex,
    cardPlacement,
    classifyTarget,
    fillPairZh,
    pdfCiteDests,
    usageEntryFromCiteMap,
    usageHostOf,
} from "../reader/usages";
import {
    citeKeys,
    maskedSentenceAt,
    maskedSentenceStarts,
    sentenceAround,
    sentenceStarts,
    unmaskText,
    zhTokenSentence,
} from "../reader/uscontext";
import type { DualChunk } from "../api/types";

const HTML = readFileSync(
    `${process.cwd()}/src/test/fixtures/arxiv_html_1706.html`,
    "utf8",
);
const page = () => {
    const doc = new DOMParser().parseFromString(HTML, "text/html");
    return (doc.querySelector(".ltx_page_main") ?? doc.body) as HTMLElement;
};
const mini = (html: string) => {
    const doc = new DOMParser().parseFromString(
        `<div id="root">${html}</div>`,
        "text/html",
    );
    return doc.getElementById("root") as HTMLElement;
};
const byId = (root: HTMLElement, id: string) =>
    root.querySelector<HTMLElement>(`[id="${id}"]`);

// ---------------------------------------------------------------- A. 索引

describe("buildUsageIndex — 真实论文全类索引", () => {
    // 真论文 fixture 解析+索引 ~2s/次——一次建成全 describe 共享（只读消费）
    let root!: HTMLElement;
    let idx!: ReturnType<typeof buildUsageIndex>;
    beforeAll(() => {
        root = page();
        idx = buildUsageIndex(root);
    });
    it("枚举全类目标：零引用条目在场，锚点全收", () => {
        expect(idx.totalAnchors).toBe(93);
        expect(idx.totalSentences).toBe(93);
        expect(idx.entries).toHaveLength(153);
        const byKind: Record<string, number> = {};
        for (const e of idx.entries)
            byKind[e.target.kind] = (byKind[e.target.kind] ?? 0) + 1;
        expect(byKind).toEqual({
            section: 95,
            figure: 5,
            equation: 9,
            table: 4,
            bib: 40,
        });
    });
    it("站点数对拍 spike 已知值 + 标签", () => {
        const sites = (id: string) => idx.forId(id)?.sites.length;
        // 浮动体（spike buildFigIndex 同数）
        expect(sites("S3.F1")).toBe(1);
        expect(sites("S3.F2")).toBe(3);
        expect(sites("S4.T1")).toBe(1);
        expect(sites("S6.T2")).toBe(2);
        expect(sites("S6.T3")).toBe(6);
        expect(sites("S6.T4")).toBe(1);
        // 节（TOC chrome 已滤——7+12+3 个 section 类目标仅 3 条正文入链）
        expect(sites("S3.SS2")).toBe(1);
        expect(sites("S3.SS2.SSS2")).toBe(1);
        expect(sites("S5.SS4")).toBe(1);
        // 文献多站点
        expect(sites("bib.bib2")).toBe(5);
        expect(sites("bib.bib38")).toBe(8);
        expect(sites("bib.bib9")).toBe(8);
        // 标签
        expect(idx.forId("S3.F1")?.target.label).toBe("Figure 1:");
        expect(idx.forId("S3.SS2")?.target.label).toBe("3.2 Attention");
        expect(idx.forId("bib.bib38")?.target.label).toBe("[38]");
    });
    it("零引用目标有条目（空态一等公民）", () => {
        const f3 = idx.forId("Sx1.F3");
        expect(f3?.target.kind).toBe("figure");
        expect(f3?.target.label).toBe("Figure 3:");
        expect(f3?.sites).toHaveLength(0);
        const eq = idx.forId("S3.E1");
        expect(eq?.target.kind).toBe("equation");
        expect(eq?.target.label).toBe("(1)");
        expect(eq?.sites).toHaveLength(0);
    });
    it("forEl 上爬命中宿主条目；未索引元素 undefined", () => {
        const fig = byId(root, "S3.F2")!;
        const inner =
            fig.querySelector("figcaption, img, .ltx_graphics") ?? fig;
        expect(idx.forEl(inner)?.target.id).toBe("S3.F2");
        const bib = byId(root, "bib.bib38")!;
        const bibInner = bib.querySelector(".ltx_tag_bibitem") ?? bib;
        expect(idx.forEl(bibInner)?.target.id).toBe("bib.bib38");
        expect(idx.forEl(null)).toBeUndefined();
        expect(idx.forEl(document.createElement("div"))).toBeUndefined();
    });
    it("锚 ord 按文档序签发（跨 pane 配对键）", () => {
        const ords = idx
            .forId("bib.bib38")!
            .sites.flatMap((s) => s.anchors.map((a) => a.ord));
        expect(ords).toEqual([0, 1, 2, 3, 4, 5, 6, 7]);
    });
});

describe("buildUsageIndex — 合成边界", () => {
    it("chrome 滤除 + caption 自指丢弃 + 同句多锚并站", () => {
        const root = mini(`
            <nav><p><a href="#F1">toc link</a></p></nav>
            <figure id="F1" class="ltx_figure"><figcaption>Figure 1: cap
                <a href="#F1">self</a></figcaption></figure>
            <p>A <a href="#F1">one</a> and <a href="#F1">two</a> refs.
            B <a href="#F1">three</a> here.</p>
        `);
        const idx = buildUsageIndex(root);
        expect(idx.totalAnchors).toBe(3); // nav/self 不计
        const e = idx.forId("F1")!;
        expect(e.sites).toHaveLength(2);
        expect(e.sites[0].anchors.map((a) => a.ord)).toEqual([0, 1]);
        expect(e.sites[1].anchors.map((a) => a.ord)).toEqual([2]);
        expect(e.sites[0].text).toContain("one");
    });
    it("子图锚归并宿主 figure（非 figure 面板）；嵌套 figure 自立条目", () => {
        const root = mini(`
            <figure id="F9" class="ltx_figure"><div class="ltx_subfloat" id="F9.a"></div></figure>
            <p>See <a href="#F9.a">9a</a> panel.</p>
        `);
        const idx = buildUsageIndex(root);
        const e = idx.forId("F9")!;
        expect(e.sites).toHaveLength(1);
        expect(idx.forId("F9.a")).toBe(e); // 面板 id 映到宿主条目
        // 嵌套 <figure> 自身即宿主（spike 同口径：matches 优先于 closest）
        const root2 = mini(`
            <figure id="G1" class="ltx_figure"><figure class="ltx_subfloat" id="G1.a"></figure></figure>
            <p>x <a href="#G1.a">a</a>.</p>
        `);
        const idx2 = buildUsageIndex(root2);
        expect(idx2.forId("G1.a")!.sites).toHaveLength(1);
        expect(idx2.forId("G1")!.sites).toHaveLength(0);
    });
    it("悬空 href / 无 id 目标 / other 类元素不成条目", () => {
        const root = mini(`
            <p><a href="#NOPE">dangling</a> and <a href="#x">short</a>.</p>
            <p id="x">plain para with id but no ltx class</p>
        `);
        const idx = buildUsageIndex(root);
        expect(idx.totalAnchors).toBe(0);
        expect(idx.entries).toHaveLength(0);
    });
    it("seqOf 映射：data-chunk → dual seq 落到锚与站点", () => {
        const root = mini(`
            <div data-chunk="S1.p1"><p>See <a href="#F1">Fig 1</a>.</p></div>
            <figure id="F1" class="ltx_figure"></figure>
        `);
        const idx = buildUsageIndex(root, {
            seqOf: (k) => (k === "S1.p1" ? 42 : null),
        });
        const e = idx.forId("F1")!;
        expect(e.sites[0].seq).toBe(42);
        expect(e.sites[0].anchors[0].seq).toBe(42);
        expect(e.sites[0].anchors[0].charOff).toBeGreaterThanOrEqual(0);
    });
});

// ---------------------------------------------------------------- B. 句界

describe("句界护栏", () => {
    it("DOM 路：缩写/小数不切，文末不切，CJK 无空白切", () => {
        const t1 = "Fig. 2 shows x. It works.";
        expect(sentenceStarts(t1)).toEqual([0, 16]);
        expect(sentenceStarts("Value 3.5 stays. Yes.")).toEqual([0, 17]);
        const zh = "值不变。下句开始。";
        expect(sentenceStarts(zh)).toEqual([0, 4]);
        expect(sentenceStarts("no period")).toEqual([0]);
    });
    it("DOM 路 sentenceAround：含锚句 + anchorStart", () => {
        const root = mini(
            `<p>First <a href="#F1">ref</a> here. Second sentence.</p>`,
        );
        const p = root.querySelector("p")!;
        const a = root.querySelector("a")!;
        const s = sentenceAround(p, a)!;
        expect(s.text).toBe("First ref here.");
        expect(s.anchorStart).toBe(6);
        const stray = document.createElement("a");
        expect(sentenceAround(p, stray)).toBeNull();
    });
    it("掩码路：depth/转义/缩写/SL-PL 边界", () => {
        // depth>0 的 "." 不切；尾词 ≤3 字母按缩写豁免（batch.abbrev_cut）
        expect(maskedSentenceStarts("Done. Two {in.depth x. y} end."))
            .toEqual([0, 6]);
        const esc = "a \\\\ done. c"; // 源文 `a \\ done. c`
        expect(maskedSentenceStarts(esc)).toEqual([0, 11]);
        expect(maskedSentenceStarts("Fig. 2 works. Next.")).toEqual([0, 14]);
        expect(maskedSentenceStarts("Done.[[SL]]Next.")).toEqual([0, 11]);
        // 短词被 abbreviation 豁免——欠切不毁句
        expect(maskedSentenceStarts("A ok. B.")).toEqual([0]);
    });
    it("maskedSentenceAt：token 位所在句 unmask + 硬界", () => {
        const en = "First [[CITE_1]] here. Second one.";
        const ph = { "[[CITE_1]]": "\\cite{vaswani}" };
        const off = en.indexOf("[[CITE_1]]");
        const s = maskedSentenceAt(en, ph, off, off + 10)!;
        expect(s.text).toBe("First [vaswani] here.");
        const hard = "Para one.[[PL]]Para two [[CITE_1]] end.";
        const o2 = hard.indexOf("[[CITE_1]]");
        expect(maskedSentenceAt(hard, ph, o2, o2 + 10)!.text).toBe(
            "Para two [vaswani] end.",
        );
    });
    it("unmaskText：RESIDUE 清理 + token 替换", () => {
        expect(
            unmaskText("\\textbf{Bold} [[CITE_2]]~x", {
                "[[CITE_2]]": "\\cite{a,b}",
            }),
        ).toBe("Bold [a,b] x");
    });
    it("citeKeys：逗号拆 + 可选参 + 非 cite 体回退 brace 组", () => {
        expect(citeKeys("\\cite{a, b ,c}")).toEqual(["a", "b", "c"]);
        expect(citeKeys("\\citep[see][ch.2]{k1,k2}")).toEqual(["k1", "k2"]);
        expect(citeKeys("\\citealp{a}; \\citealp[opt]\n{b}")).toEqual(["a"]);
        expect(citeKeys("junk {a,b} tail")).toEqual(["a", "b"]);
        expect(citeKeys("plain")).toEqual([]);
    });
    it("zhTokenSentence：同名 token → zh 句；缺席 null", () => {
        const zh = "前句。见 [[CITE_1]] 所示。后句。";
        const ph = { "[[CITE_1]]": "\\cite{x}" };
        expect(zhTokenSentence(zh, ph, "[[CITE_1]]")).toBe("见 [x] 所示。");
        expect(zhTokenSentence("无 token。", ph, "[[CITE_1]]")).toBeNull();
        expect(zhTokenSentence(undefined, ph, "[[CITE_1]]")).toBeNull();
    });
});

// ---------------------------------------------------------------- C. dual 路

const chunk = (over: Partial<DualChunk>): DualChunk => ({
    seq: 1,
    src_file: "main.tex",
    ...over,
});

describe("buildCiteUsageMap", () => {
    it("多键 \\cite 拆 key 共享位 + BIB 落点 + zh 句配对", () => {
        const map = buildCiteUsageMap({
            chunks: [
                chunk({
                    seq: 1,
                    en: "Attention [[CITE_1]] works. Later [[CITE_2]] too.",
                    zh: "注意力 [[CITE_1]] 有效。稍后 [[CITE_2]] 也是。",
                    ph: {
                        "[[CITE_1]]": "\\cite{vaswani,bahdanau}",
                        "[[CITE_2]]": "\\cite{vaswani}",
                    },
                }),
                chunk({
                    seq: 2,
                    en: "[[BIB_1]]",
                    ph: { "[[BIB_1]]": "\\bibitem{Vaswani} vaswani et al." },
                }),
            ],
        });
        expect(map.hasTokens).toBe(true);
        expect(map.keyReliable).toBe(true);
        expect(map.byKey.get("vaswani")).toHaveLength(2);
        expect(map.byKey.get("bahdanau")).toHaveLength(1);
        expect(map.bibAt.get("Vaswani")?.seq).toBe(2);
        const occ = map.byKey.get("vaswani")![0];
        expect(occ.text).toBe("Attention [vaswani,bahdanau] works.");
        expect(occ.zhText).toBe("注意力 [vaswani,bahdanau] 有效。");
    });
    it("ph 编号漂移 → keyReliable=false", () => {
        const map = buildCiteUsageMap({
            chunks: [
                chunk({
                    seq: 1,
                    en: "a [[CITE_5]] b",
                    ph: { "[[CITE_5]]": "\\cite{x}" },
                }),
                chunk({
                    seq: 2,
                    en: "c [[CITE_2]] d", // 同桶内倒退=漂移
                    ph: { "[[CITE_2]]": "\\cite{y}" },
                }),
            ],
        });
        expect(map.keyReliable).toBe(false);
        // 跨 src_file 桶各自独立——不互相污染
        const ok = buildCiteUsageMap({
            chunks: [
                chunk({ seq: 1, en: "[[CITE_3]]", ph: { "[[CITE_3]]": "\\cite{x}" } }),
                chunk({
                    seq: 2,
                    src_file: "other.tex",
                    en: "[[CITE_1]]",
                    ph: { "[[CITE_1]]": "\\cite{y}" },
                }),
            ],
        });
        expect(ok.keyReliable).toBe(true);
    });
    it("无 ph / 无 token 旧档 → hasTokens=false 纯 DOM 路", () => {
        const map = buildCiteUsageMap({
            chunks: [chunk({ seq: 1, en: "no tokens" })],
        });
        expect(map.hasTokens).toBe(false);
        expect(map.byKey.size).toBe(0);
    });
    it("usageEntryFromCiteMap：同句多引用点并站 + fraction", () => {
        const map = buildCiteUsageMap({
            chunks: [
                chunk({
                    seq: 7,
                    en: "ab [[CITE_1]] cd [[CITE_2]] ef.",
                    ph: {
                        "[[CITE_1]]": "\\cite{k}",
                        "[[CITE_2]]": "\\cite{k}",
                    },
                }),
            ],
        });
        const e = usageEntryFromCiteMap(map, "k", "K. et al.");
        expect(e.target.kind).toBe("bib");
        expect(e.sites).toHaveLength(1); // 同 seq 同句并站
        expect(e.sites[0].anchors).toHaveLength(2);
        expect(e.sites[0].seq).toBe(7);
        expect(e.sites[0].fraction).toBeCloseTo(3 / 31, 5);
    });
    it("pdfCiteDests：cite.<key> verbatim 存在性", () => {
        const dests = new Set(["cite.vaswani", "sec.3"]);
        expect(pdfCiteDests(dests, "vaswani")).toEqual(["cite.vaswani"]);
        expect(pdfCiteDests(dests, "nope")).toEqual([]);
        expect(pdfCiteDests(undefined, "x")).toEqual([]);
    });
});

// ---------------------------------------------------------------- D. zh 配对

describe("fillPairZh — (id,ord) 跨 pane 对", () => {
    const side = (lang: string, word: string) =>
        mini(`
            <figure id="F1" class="ltx_figure"><figcaption>${word} caption</figcaption></figure>
            <p>${lang} <a href="#F1">r1</a> one. ${lang} <a href="#F1">r2</a> two.</p>
        `);
    it("同 id zh 条目按锚 ord 配对句", () => {
        const en = buildUsageIndex(side("en", "fig"));
        const zh = buildUsageIndex(side("中文", "图"));
        const e = en.forId("F1")!;
        fillPairZh(e, zh);
        expect(e.paired).toBe(true);
        expect(e.sites[0].zhText).toBe("中文 r1 one.");
        expect(e.sites[1].zhText).toBe("中文 r2 two.");
    });
    it("zh 侧缺条目/缺 ord → 该句 zhText 留 null；幂等", () => {
        const en = buildUsageIndex(side("en", "fig"));
        const zh = buildUsageIndex(
            mini(`<p>仅 <a href="#F1">一</a> 处。</p><figure id="F1" class="ltx_figure"></figure>`),
        );
        const e = en.forId("F1")!;
        fillPairZh(e, zh);
        expect(e.sites[0].zhText).toBe("仅 一 处。");
        expect(e.sites[1].zhText).toBeNull();
        fillPairZh(e, zh); // 二次调用不重复扫描
        fillPairZh(e, undefined);
        expect(e.sites[0].zhText).not.toBeNull();
    });
});

// ---------------------------------------------------------------- E/F. 工具

describe("cardPlacement / classifyTarget / usageHostOf", () => {
    const rect = (l: number, t: number, w = 10, h = 10) => ({
        left: l,
        top: t,
        right: l + w,
        bottom: t + h,
    });
    it("锚下方优先；下方不足且上方更宽则翻上", () => {
        const p1 = cardPlacement(rect(100, 100), 200, 1280, 800);
        expect(p1.flipped).toBe(false);
        expect(p1.top).toBe(116);
        const p2 = cardPlacement(rect(100, 700), 200, 1280, 800);
        expect(p2.flipped).toBe(true);
        expect(p2.top).toBe(494);
    });
    it("左右夹视口 + 宽度上限", () => {
        const p = cardPlacement(rect(1200, 100), 200, 1280, 800);
        expect(p.left).toBe(1280 - 380 - 8);
        expect(p.width).toBe(380);
        const narrow = cardPlacement(rect(5, 100), 200, 300, 800);
        expect(narrow.width).toBe(300 - 16);
    });
    it("classifyTarget：宿主归并 + kind + label；other → null", () => {
        const root = mini(`
            <figure id="F1" class="ltx_figure"><figcaption><span class="ltx_tag_figure">Figure 1:</span> cap</figcaption></figure>
            <section class="ltx_section" id="S1"><h2 class="ltx_title">Intro</h2></section>
            <p id="plain">text</p>
        `);
        const cap = root.querySelector("figcaption")!;
        const t = classifyTarget(cap)!;
        expect(t.kind).toBe("figure");
        expect(t.id).toBe("F1");
        expect(t.label).toBe("Figure 1:");
        const sec = root.querySelector("#S1")!;
        expect(classifyTarget(sec)?.id).toBe("S1");
        expect(classifyTarget(sec)?.label).toBe("Intro");
        // 无 id 元素不成目标（forEl 上爬路径兜底覆盖其后代视角）
        expect(classifyTarget(root.querySelector("h2"))).toBeNull();
        expect(classifyTarget(root.querySelector("#plain"))).toBeNull();
        expect(usageHostOf(root.querySelector(".ltx_tag_figure"))?.id).toBe(
            "F1",
        );
    });
});
