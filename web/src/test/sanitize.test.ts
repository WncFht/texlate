// @vitest-environment jsdom
// HtmlPane 注入管线回归：marked → DOMPurify → innerHTML → KaTeX auto-render。
// 要点：XSS 面被剥；MathML/KaTeX 相关标签保留；KaTeX 产物（sanitize 后现场
// 生成）完好。

import { describe, expect, it } from "vitest";
import { marked } from "marked";
import renderMathInElement from "katex/contrib/auto-render";
import { sanitizeDomHtml, sanitizeHtml } from "../reader/sanitize";

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

    it("<style> 标签与行内 style 全剥（marked 译文无正当样式需求）", () => {
        const out = render(
            't<style>body{display:none}</style>\n\n<p style="position:fixed;inset:0;color:red">x</p>',
        );
        expect(out).not.toContain("<style");
        expect(out).not.toContain("display:none");
        expect(out).not.toContain("style=");
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

describe("sanitizeDomHtml（DomPane arxiv LaTeXML 产物消毒）", () => {
    it("script/事件处理器/iframe/object/embed/form/base/link/meta 被剥", () => {
        const out = sanitizeDomHtml(
            '<p onclick="x()">t</p><script>alert(1)</script>' +
                '<iframe src="//e"></iframe><object></object><embed>' +
                '<form></form><base href="//e"><link rel="x" href="//e"><meta name="x">',
        );
        expect(out).not.toContain("<script");
        expect(out).not.toContain("onclick");
        expect(out).not.toContain("<iframe");
        expect(out).not.toContain("<object");
        expect(out).not.toContain("<embed");
        expect(out).not.toContain("<form");
        expect(out).not.toContain("<base");
        expect(out).not.toContain("<link");
        expect(out).not.toContain("<meta");
        expect(out).toContain("<p>t</p>");
    });

    it("inline SVG 保留（ar5iv/LaTeXML 矢量图）——与 sanitizeHtml 的 svg:false 分野", () => {
        const svg = '<svg viewBox="0 0 1 1"><circle r="1"/></svg>';
        expect(sanitizeDomHtml(svg)).toContain("<svg");
        expect(sanitizeHtml(svg)).not.toContain("<svg");
    });

    it("<style> 保留但作用域到 .pane-html-body；危险声明与越权 at-规则剥除", () => {
        const out = sanitizeDomHtml(
            '<p class="ltx_p">x</p>' +
                "<style>body{display:none}.ltx_p{color:blue}" +
                "@media(min-width:1px){p{position:fixed;margin:0}}" +
                "@import url(//evil);p:hover{color:green}</style>",
        );
        const host = document.createElement("div");
        host.innerHTML = out;
        const css = host.querySelector("style")?.textContent ?? "";
        // body 选择器被前缀进作用域——失去对应用 chrome 的命中
        expect(css).toContain(".pane-html-body body");
        expect(css).not.toMatch(/(^|[}\n])\s*body\s*\{/);
        expect(css).toContain(".pane-html-body .ltx_p");
        // @import 丢；@media 内规则保留但 position:fixed 剥掉
        expect(css).not.toContain("evil");
        expect(css).toContain("@media");
        expect(css).not.toContain("position: fixed");
    });

    it("行内 style 剥 position:fixed/pointer-events，保留无害声明", () => {
        const out = sanitizeDomHtml(
            '<p style="position:fixed;pointer-events:none;width:10em">x</p>' +
                '<p style="position:relative;top:2px">y</p>',
        );
        const host = document.createElement("div");
        host.innerHTML = out;
        const ps = host.querySelectorAll("p");
        expect(ps[0].getAttribute("style")).not.toContain("position");
        expect(ps[0].getAttribute("style")).not.toContain("pointer-events");
        expect(ps[0].getAttribute("style")).toContain("width");
        // relative 不逃逸 .pane 裁剪——保留
        expect(ps[1].getAttribute("style")).toContain("relative");
    });

    it("data-chunk 锚与 MathML 保留；semantics/annotation 仍剥（mXSS 向量）", () => {
        const out = sanitizeDomHtml(
            '<section data-chunk="3"><math><semantics><mi>x</mi>' +
                '<annotation encoding="application/x-tex">x</annotation></semantics></math></section>',
        );
        expect(out).toContain('data-chunk="3"');
        expect(out).toContain("<math");
        expect(out).toContain("<mi>x</mi>");
        expect(out).not.toContain("<semantics");
        expect(out).not.toContain("<annotation");
    });
});
