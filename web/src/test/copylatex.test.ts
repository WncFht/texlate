// @vitest-environment jsdom
// copylatex —— 公式三径提取 / selChunks 闭区间+嵌套锚+anchor 截帽 /
// pdf 归一化 difflib 段级锚定 / clipboard 兜底链。

import { beforeEach, describe, expect, it, vi } from "vitest";
import {
    copyLatexMode,
    copyText,
    mathIsInline,
    mathTexFrom,
    mathTexSync,
    pdfSeqsForText,
    selChunks,
    setCopyLatexMode,
} from "../reader/cite/copylatex";

const q = <T extends Element = Element>(sel: string): T =>
    document.querySelector<T>(sel)!;

const FIXTURE = `
<div class="pane-html-body" id="body">
  <section class="chunk" data-chunk="1">
    <p>Alpha text one. <math class="ltx_Math" alttext="a_{1}+b" id="mAlt"><semantics>
      <annotation encoding="application/x-tex">WRONG-annotation</annotation>
    </semantics></math> tail one.</p>
  </section>
  <section class="chunk" data-chunk="2">
    <p>Beta text two.
      <span class="katex" id="k1"><math><semantics>
        <annotation encoding="application/x-tex">\\frac{x}{2}</annotation>
      </semantics></math><span class="katex-html">x/2</span></span>
      mid two.
      <math id="mBare"><mrow><mi>c</mi><mo>+</mo><mn>3</mn></mrow></math>
      end two.</p>
  </section>
  <figure class="ltx_figure" data-chunk="3" id="fig">
    <div class="ltx_para" data-chunk="4">Figure caption four.</div>
  </figure>
  <section class="chunk" data-chunk="b5">Bibitem no-seq five.</section>
  <section class="chunk" data-chunk="6"><p>Zeta text six.</p></section>
</div>`;

const rangeIn = (startSel: string, endSel: string, so = 0, eo = 0): Range => {
    const r = document.createRange();
    const sEl = q(startSel);
    const eEl = q(endSel);
    const sNode = sEl.firstChild ?? sEl;
    const eNode = eEl.firstChild ?? eEl;
    r.setStart(sNode, so);
    r.setEnd(eNode, eo);
    return r;
};

beforeEach(() => {
    document.body.innerHTML = FIXTURE;
});

// ---------------------------------------------------------------- 公式提取

describe("mathTexFrom 三级提取", () => {
    it("alttext 优先于 annotation（dom 链载体）", async () => {
        const r = await mathTexFrom(q("#mAlt"));
        expect(r).toEqual({ tex: "a_{1}+b", approx: false });
    });
    it(".katex 容器取 annotation[x-tex]（html/live 链）", async () => {
        const r = await mathTexFrom(q("#k1"));
        expect(r).toEqual({ tex: "\\frac{x}{2}", approx: false });
    });
    it("裸 MathML → convert 注入臂标 approx", async () => {
        const r = await mathTexFrom(q("#mBare"), {
            convert: (mml) => {
                expect(mml).toContain("<mrow>");
                return " c+3 ";
            },
        });
        expect(r).toEqual({ tex: "c+3", approx: true });
    });
    it("convert 抛错/空串 → null（调用面按无源）", async () => {
        await expect(
            mathTexFrom(q("#mBare"), {
                convert: () => {
                    throw new Error("boom");
                },
            }),
        ).resolves.toBeNull();
        await expect(
            mathTexFrom(q("#mBare"), { convert: () => "  " }),
        ).resolves.toBeNull();
    });
    it("mathTexSync 只走同步两臂", () => {
        expect(mathTexSync(q("#mAlt"))?.tex).toBe("a_{1}+b");
        expect(mathTexSync(q("#mBare"))).toBeNull();
        expect(mathTexSync(null)).toBeNull();
    });
    it("mathIsInline：display=block / .katex-display → false", () => {
        const inline = document.createElement("math");
        expect(mathIsInline(inline)).toBe(true);
        inline.setAttribute("display", "block");
        expect(mathIsInline(inline)).toBe(false);
        const wrap = document.createElement("div");
        wrap.className = "katex-display";
        const inner = document.createElement("math");
        wrap.append(inner);
        document.body.append(wrap);
        expect(mathIsInline(inner)).toBe(false);
        wrap.remove();
    });
});

// ---------------------------------------------------------------- selChunks

describe("selChunks 闭区间 + anchor", () => {
    it("跨段选区 → seq 连续闭区间（含中间未命中段）", () => {
        // 起点在 chunk1 的 "Alpha"，终点落在 figure 内子块 4 的文本起点
        const p1 = q('[data-chunk="1"] p');
        const r = document.createRange();
        r.setStart(p1.firstChild!, 2);
        r.setEnd(q('[data-chunk="4"]').firstChild!, 0);
        const got = selChunks(q("#body"), r);
        expect(got.seqs).toEqual([1, 2, 3, 4]); // 嵌套锚 data-chunk=4 计入
        expect(got.head).toBeTruthy();
        expect(got.head!.startsWith("pha text one")).toBe(true);
    });
    it("嵌套锚：最内子块选区仍给出父+子 seq 闭区间", () => {
        const cap = q('[data-chunk="4"]');
        const r = document.createRange();
        r.selectNodeContents(cap);
        const got = selChunks(q("#body"), r);
        // figure(3) 是 4 的祖先——intersectsNode 双命中；闭区间 [3,4]
        expect(got.seqs).toEqual([3, 4]);
        expect(got.tail).toBe("Figure caption four.");
    });
    it("无 seq 锚（b5 bibitem）跳过不计区间", () => {
        const sec = q('[data-chunk="b5"]');
        const r = document.createRange();
        r.selectNodeContents(sec);
        const got = selChunks(q("#body"), r);
        expect(got.keys).toEqual(["b5"]);
        expect(got.seqs).toEqual([]); // 无 int seq → 空区间
        expect(got.head).toBe("Bibitem no-seq five.");
    });
    it("anchor 截帽：head 保首缘 400、tail 保尾缘 400", () => {
        const body = q("#body");
        // 造 >400 字符的首块文本
        const long = document.createElement("section");
        long.dataset.chunk = "7";
        const pad = "x".repeat(500);
        long.textContent = pad;
        body.append(long);
        const r = document.createRange();
        r.setStart(long.firstChild!, 10);
        r.setEnd(long.firstChild!, 490);
        const got = selChunks(body, r, { anchorCap: 100 });
        expect(got.head!.length).toBe(100);
        expect(got.head).toBe(pad.slice(10, 110)); // 首缘即切点侧
        expect(got.tail!.length).toBe(100);
        expect(got.tail).toBe(pad.slice(390, 490)); // 尾缘即切点侧
        long.remove();
    });
    it("seqOf 注入：dom 键经映射计入区间", () => {
        const r = rangeIn('[data-chunk="b5"]', '[data-chunk="b5"]');
        const got = selChunks(q("#body"), r, {
            seqOf: (k) => (k === "b5" ? 42 : null),
        });
        expect(got.seqs).toEqual([42]);
    });
});

// ---------------------------------------------------------------- pdf 锚定

describe("pdfSeqsForText 归一化段级锚定", () => {
    const dual = {
        chunks: [
            {
                seq: 1,
                en: "The quick brown fox jumps over the lazy dog.",
                zh: "敏捷的棕毛狐狸跳过懒狗。",
            },
            {
                seq: 2,
                en: "We prove that the bound is tight for all n greater than three.",
                zh: "我们证明该界对所有大于三的 n 是紧的。",
            },
            {
                seq: 3,
                en: "Figure 2 shows the resulting architecture diagram.",
                zh: "图 2 给出了最终的架构图。",
            },
        ],
    };
    it("en 侧选区命中相邻段 → 闭区间", () => {
        const sel =
            "the lazy dog.   We prove that the bound is tight for all n"; // 跨段+多空格
        expect(pdfSeqsForText(dual, sel, "en")).toEqual([1, 2]);
    });
    it("智能引号/破折号归一化", () => {
        const d2 = {
            chunks: [{ seq: 5, en: "a “quoted” thing—here", zh: "" }],
        };
        expect(pdfSeqsForText(d2, 'A "QUOTED" thing—here', "en")).toEqual([5]);
    });
    it("zh 侧选区对 zh 文本锚定", () => {
        expect(pdfSeqsForText(dual, "证明该界对所有大于三的", "zh")).toEqual([
            2,
        ]);
    });
    it("只命中边界段 → 单段区间；无命中 → 空", () => {
        expect(pdfSeqsForText(dual, "architecture diagram.", "en")).toEqual([
            3,
        ]);
        expect(pdfSeqsForText(dual, "totally unrelated prose", "en")).toEqual(
            [],
        );
    });
    it("空选区/无 chunks → 空", () => {
        expect(pdfSeqsForText(dual, "   ", "en")).toEqual([]);
        expect(pdfSeqsForText(null, "dog", "en")).toEqual([]);
        expect(pdfSeqsForText({ chunks: [] }, "dog", "en")).toEqual([]);
    });
    it("texStrip：latex 源残留段照常命中", () => {
        const d = {
            chunks: [
                {
                    seq: 7,
                    en: "We prove \\emph{that} the bound $O(n^2)$ is tight for all [[EQ_1]] values greater than \\textbf{three}.",
                },
                { seq: 8, en: "Totally unrelated conclusion follows here." },
            ],
        };
        // pdf 侧渲染态：命令/占位符已消失，数学只留零散字形
        const sel =
            "we prove that the bound is tight for all values greater than three";
        expect(pdfSeqsForText(d, sel, "en")).toEqual([7]);
    });
    it("gap 合并：选区被页眉噪声切碎仍整段命中", () => {
        const d = {
            chunks: [
                {
                    seq: 4,
                    en: "The second argument relies on a delicate induction over all finite subsets of the ambient space.",
                },
            ],
        };
        // pdf 抽取流中段插进页眉/页码（≤30 token 断口）——碎块覆盖应合并
        const sel =
            "the second argument relies on a delicate induction PROCEEDINGS OF THE AMS VOL 132 PAGE 441 over all finite subsets of the ambient space";
        expect(pdfSeqsForText(d, sel, "en")).toEqual([4]);
    });
    it("连通聚簇：散落重复命中不膨胀", () => {
        // seq 1 与 seq 40 同文（标题页+结论复述）——选区覆盖 40 并延入
        // 41 头（edgeTail 证据），簇 {40,41} 权重胜 {1}；旧闭区间会
        // 膨胀成 [1..41]
        const rep = "the zeta mechanism yields asymptotic stability";
        const d = {
            chunks: [
                { seq: 1, en: rep },
                { seq: 2, en: "unrelated body paragraph one" },
                { seq: 40, en: rep },
                { seq: 41, en: "unrelated body paragraph two" },
            ],
        };
        const sel = `${rep} unrelated body paragraph two`;
        expect(pdfSeqsForText(d, sel, "en")).toEqual([40, 41]);
    });
    it("NFKD：连字/全角折叠命中", () => {
        const d = {
            chunks: [
                { seq: 9, en: "The final figure shows a fish coefficient." },
            ],
        };
        // ﬁ=U+FB01/ﬀ=U+FB00 连字 + 全角数字 ２ ——pdf 字体常见形态
        expect(
            pdfSeqsForText(d, "the ﬁnal ﬁgure shows a ﬁsh coeﬃcient", "en"),
        ).toEqual([9]);
    });
});

// ---------------------------------------------------------------- 剪贴板

describe("copyText 兜底链", () => {
    it("clipboard.writeText 成功走主路", async () => {
        const write = vi.fn().mockResolvedValue(undefined);
        Object.defineProperty(navigator, "clipboard", {
            value: { writeText: write },
            configurable: true,
        });
        await expect(copyText("tex-body")).resolves.toBe(true);
        expect(write).toHaveBeenCalledWith("tex-body");
    });
    it("clipboard 缺席/拒绝 → textarea execCommand 兜底", async () => {
        Object.defineProperty(navigator, "clipboard", {
            value: {
                writeText: vi.fn().mockRejectedValue(new Error("denied")),
            },
            configurable: true,
        });
        // jsdom 无 execCommand——直接挂桩（spyOn 要求属性已存在）
        const exec = vi.fn().mockReturnValue(true);
        (document as unknown as { execCommand: unknown }).execCommand = exec;
        try {
            await expect(copyText("fb")).resolves.toBe(true);
            expect(exec).toHaveBeenCalledWith("copy");
        } finally {
            delete (document as unknown as { execCommand?: unknown })
                .execCommand;
        }
    });
    it("双路皆败 → false（不抛——调用面决定提示）", async () => {
        Object.defineProperty(navigator, "clipboard", {
            value: undefined,
            configurable: true,
        });
        const exec = vi.fn().mockImplementation(() => {
            throw new Error("no execCommand");
        });
        (document as unknown as { execCommand: unknown }).execCommand = exec;
        try {
            await expect(copyText("x")).resolves.toBe(false);
        } finally {
            delete (document as unknown as { execCommand?: unknown })
                .execCommand;
        }
    });
});

// ---------------------------------------------------------------- 档位

describe("copyLatexMode 档位存取", () => {
    it("缺省 sent；whole 往返", () => {
        const store = new Map<string, string>();
        const st = {
            getItem: (k: string) => store.get(k) ?? null,
            setItem: (k: string, v: string) => void store.set(k, v),
        };
        expect(copyLatexMode(st)).toBe("sent");
        setCopyLatexMode("whole", st);
        expect(copyLatexMode(st)).toBe("whole");
        setCopyLatexMode("sent", st);
        expect(copyLatexMode(st)).toBe("sent");
    });
});
