// @vitest-environment jsdom
// unmaskLatex：[[TYPE_n]] 掩码反查 + 未掩码 LaTeX 残件清理

import { describe, expect, it } from "vitest";
import { unmaskLatex } from "../reader/markdown";

// 用脱节点当宿主即可：createTreeWalker/closest/textContent 都支持 detached
const host = (html: string): HTMLElement => {
    const el = document.createElement("div");
    el.innerHTML = html;
    return el;
};

describe("unmaskLatex：掩码反查", () => {
    it("MATH：$…$/\\(…\\) 原样透传，裸环境体包 $$", () => {
        const el = host(
            `<p>inline [[MATH_1]] env [[MATH_2]] bare [[MATH_3]]</p>`,
        );
        unmaskLatex(el, {
            "[[MATH_1]]": "$e^{i\\pi}+1=0$",
            "[[MATH_2]]": "\\begin{equation}y=mx\\end{equation}",
            "[[MATH_3]]": "\\alpha+\\beta",
        });
        expect(el.textContent).toBe(
            "inline $e^{i\\pi}+1=0$ env " +
                "$$\\begin{equation}y=mx\\end{equation}$$ " +
                "bare \\(\\alpha+\\beta\\)",
        );
    });

    it("CITE/REF/BIB：剥壳成 [key] / (label)", () => {
        const el = host(
            `<p>see [[CITE_1]] cf [[REF_2]] entry [[BIB_3]]</p>`,
        );
        unmaskLatex(el, {
            "[[CITE_1]]": "\\cite{vaswani17,other}",
            "[[REF_2]]": "\\eqref{eq:attn}",
            "[[BIB_3]]": "\\bibitem{ba16}",
        });
        expect(el.textContent).toBe(
            "see [vaswani17,other] cf (eq:attn) entry [ba16]",
        );
    });

    it("URL/HREF/VERB：露可见文本", () => {
        const el = host(`<p>u [[URL_1]] h [[HREF_2]] v [[VERB_3]]</p>`);
        unmaskLatex(el, {
            "[[URL_1]]": "\\url{https://x.y}",
            "[[HREF_2]]": "\\href{https://x.y}{the site}",
            "[[VERB_3]]": "\\verb|a_b|",
        });
        expect(el.textContent).toBe("u https://x.y h the site v a_b");
    });

    it("CMD/MACRO：命令名隐去、参数文本保留；LABEL 隐去", () => {
        const el = host(`<p>[[CMD_1]] mid [[LABEL_2]] end</p>`);
        unmaskLatex(el, {
            "[[CMD_1]]": "\\textbf{Attention}",
            "[[LABEL_2]]": "\\label{sec:x}",
        });
        expect(el.textContent).toBe("Attention mid  end");
    });

    it("ph 缺席 → muted chip 露 kind 不露原形", () => {
        const el = host(`<p>f(x)=[[MATH_7]]</p>`);
        unmaskLatex(el, undefined);
        const chip = el.querySelector(".ph-tok");
        expect(chip?.textContent).toBe("math");
        expect(el.textContent).toContain("f(x)=");
    });

    it("宽容 token 形：[[MATH 1]] 也命中", () => {
        const el = host(`<p>v [[MATH 1]]</p>`);
        unmaskLatex(el, { "[[MATH_1]]": "$x$" });
        expect(el.textContent).toBe("v $x$");
    });
});

describe("unmaskLatex：残件清理", () => {
    it("\\newblock / ~ / {-} / 转义字符", () => {
        const el = host(
            `<p>Jimmy~Lei Ba \\newblock Layer norm. Minh{-}Thang 50\\% a\\_b</p>`,
        );
        unmaskLatex(el);
        expect(el.textContent).toBe(
            "Jimmy Lei Ba Layer norm. Minh-Thang 50% a_b",
        );
    });

    it("code/pre 内字面 LaTeX 不动", () => {
        const el = host(`<p>a~b</p><pre>x \\newblock y</pre>`);
        unmaskLatex(el);
        expect(el.querySelector("p")!.textContent).toBe("a b");
        expect(el.querySelector("pre")!.textContent).toBe(
            "x \\newblock y",
        );
    });

    it("带参格式命令剥壳（嵌套/双参）", () => {
        const el = host(
            `<p>\\textit{projected baseline length} ` +
                `\\textbf{a \\emph{b}} ` +
                `\\textcolor{red}{warn} ` +
                `\\texorpdfstring{vis}{pdf}</p>`,
        );
        unmaskLatex(el);
        expect(el.textContent).toBe(
            "projected baseline length a b warn vis",
        );
    });

    it("断行可选参与残余单反斜杠", () => {
        const el = host(
            `<p>Title \\\\[0.2in] next \\[1em] and\\\\ more</p>`,
        );
        unmaskLatex(el);
        expect(el.textContent).toBe("Title next and more");
    });
});
