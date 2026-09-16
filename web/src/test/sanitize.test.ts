// @vitest-environment jsdom
// HtmlPane 注入管线回归：marked → DOMPurify → innerHTML → KaTeX auto-render。
// 要点：XSS 面被剥；MathML/KaTeX 相关标签保留；KaTeX 产物（sanitize 后现场
// 生成）完好。

import { describe, expect, it } from "vitest";
import { marked } from "marked";
import renderMathInElement from "katex/contrib/auto-render";
import { sanitizeHtml } from "../reader/sanitize";

const render = (md: string) =>
    sanitizeHtml(marked.parse(md, { async: false }) as string);

describe("sanitizeHtml（HtmlPane marked 输出消毒）", () => {
    it("script/事件处理器/javascript: 链接被剥", () => {
        const out = render(
            'text<script>alert(1)</script>\n\n<img src=x onerror=alert(2)>\n\n[click](javascript:alert(3))',
        );
        expect(out).not.toContain("<script");
        expect(out).not.toContain("onerror");
        expect(out).not.toContain("javascript:");
    });

    it("正常排版标签保留（h/p/code/table/a.href）", () => {
        const out = render(
            "# T\n\npara `code`\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n[x](https://example.org)",
        );
        expect(out).toContain("<h1");
        expect(out).toContain("<code");
        expect(out).toContain("<table");
        expect(out).toContain('href="https://example.org"');
    });

    it("MathML 呈现标签保留（math/mi）；semantics/annotation 属 mXSS 向量被剥", () => {
        const mathml =
            '<math><semantics><mi>x</mi><annotation encoding="application/x-tex">x</annotation></semantics></math>';
        const out = render(`inline ${mathml} tail`);
        expect(out).toContain("<math");
        expect(out).toContain("<mi>x</mi>");
        // DOMPurify 有意禁 semantics/annotation(-xml)——命名空间混淆 mXSS 向量；
        // KaTeX 渲染产物在 sanitize 之后生成，不受影响
        expect(out).not.toContain("<semantics");
        expect(out).not.toContain("<annotation");
    });

    it("sanitize 后 KaTeX auto-render 产物完好（.katex/.katex-html 就位）", () => {
        const host = document.createElement("div");
        host.innerHTML = render("损失函数为 $L = \\sum_i \\ell_i$ 且 $$E = mc^2$$。");
        renderMathInElement(host, {
            delimiters: [
                { left: "$$", right: "$$", display: true },
                { left: "$", right: "$", display: false },
            ],
            throwOnError: false,
        });
        const katex = host.querySelectorAll(".katex");
        expect(katex.length).toBe(2);
        expect(host.querySelector(".katex-html")).not.toBeNull();
        // KaTeX 产物自带 MathML 语义层（annotation/semantics）
        expect(host.querySelector("annotation")).not.toBeNull();
    });
});
