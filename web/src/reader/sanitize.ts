// marked 输出消毒——管线产物非用户输入，但译文由 LLM 生成，可能携带
// 原样透传的 HTML/脚本片段（markdown 允许内联 HTML），注入 innerHTML
// 前必须过白名单。mathMl profile 保 MathML 呈现标签（math/mi/mrow…）；
// semantics/annotation(-xml) 是 DOMPurify 有意禁掉的 mXSS 向量，不重开——
// KaTeX 本体产物在注入后由 auto-render 现场生成，不经此函数。

import DOMPurify from "dompurify";

const PROFILE = {
    USE_PROFILES: { html: true, mathMl: true, svg: false },
};

export function sanitizeHtml(html: string): string {
    return DOMPurify.sanitize(html, PROFILE);
}

// 与 sanitizeHtml（md_zip 路 marked 产物）不同：arxiv DOM 是服务端
// LaTeXML 产物（worker emit 已剥过一层），但要保的东西更多——
// svg:true 因为 ar5iv/LaTeXML 的 tikz/矢量图走 inline SVG；
// FORBID 里补 iframe/object/embed/form/base（DOMPurify 默认不禁
// iframe 容器标签，同源嵌进 pane 是 UI redress 面）。
const DOM_PROFILE = {
    USE_PROFILES: { html: true, mathMl: true, svg: true, svgFilters: true },
    FORBID_TAGS: ["iframe", "object", "embed", "form", "base", "link", "meta"],
    // data-chunk 是 sync 几何锚——data-* DOMPurify 默认放行，显式声明防回归
    ADD_ATTR: ["data-chunk", "target"],
};

export function sanitizeDomHtml(html: string): string {
    return DOMPurify.sanitize(html, DOM_PROFILE);
}

/** marked 失败时把源 markdown 当纯文本兜底——只转义 HTML 特殊字符 */
export function escapeHtml(s: string): string {
    return s
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}
