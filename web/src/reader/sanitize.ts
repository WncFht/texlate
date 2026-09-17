// marked 输出消毒——管线产物非用户输入，但译文由 LLM 生成，可能携带
// 原样透传的 HTML/脚本片段（markdown 允许内联 HTML），注入 innerHTML
// 前必须过白名单。mathMl profile 保 MathML 呈现标签（math/mi/mrow…）；
// semantics/annotation(-xml) 是 DOMPurify 有意禁掉的 mXSS 向量，不重开——
// KaTeX 本体产物在注入后由 auto-render 现场生成，不经此函数。

import DOMPurify from "dompurify";

const PROFILE = {
    USE_PROFILES: { html: true, mathMl: true, svg: false },
    // marked 译文不需要样式：style 标签+行内 style 全剥——注入的
    // body{display:none}/position:fixed 是整个应用 chrome 的遮蔽面
    FORBID_TAGS: ["style"],
    FORBID_ATTR: ["style"],
};

export function sanitizeHtml(html: string): string {
    return DOMPurify.sanitize(html, PROFILE);
}

// 与 sanitizeHtml（md_zip 路 marked 产物）不同：arxiv DOM 是服务端
// LaTeXML 产物（worker emit 已剥过一层），但要保的东西更多——
// svg:true 因为 ar5iv/LaTeXML 的 tikz/矢量图走 inline SVG；
// FORBID 里补 iframe/object/embed/form/base（DOMPurify 默认不禁
// iframe 容器标签，同源嵌进 pane 是 UI redress 面）。
//
// <style>/style 不能直接剥——ltx_* 排版靠 arXiv 内嵌样式表。但样式表
// 内容半不可信（body{display:none} 全局生效、position:fixed 逃出
// overflow 裁剪），故 DOM_PROFILE 放行标签、sanitizeDomHtml 内做二次
// CSSOM 净化：所有规则选择器前缀到 .pane-html-body 作用域 + 剥除
// 定位逃逸声明；@import/@namespace/@page 等 at-规则白名单丢弃。
const DOM_PROFILE = {
    USE_PROFILES: { html: true, mathMl: true, svg: true, svgFilters: true },
    FORBID_TAGS: ["iframe", "object", "embed", "form", "base", "link", "meta"],
    // data-chunk 是 sync 几何锚——data-* DOMPurify 默认放行，显式声明防回归
    ADD_ATTR: ["data-chunk", "target"],
};

const PANE_SCOPE = ".pane-html-body";

/** 声明级剥除：fixed 是唯一逃出 .pane 裁剪的定位（.pane 有 position:relative，
 *  absolute/sticky 被 overflow:auto 圈住）；pointer-events 只服务于穿透覆盖层 */
function cleanDecls(style: CSSStyleDeclaration): void {
    if (style.getPropertyValue("position").trim() === "fixed")
        style.removeProperty("position");
    style.removeProperty("pointer-events");
}

/** 按顶层逗号切选择器列（:is()/:where() 内的逗号不切） */
function splitSelectors(sel: string): string[] {
    const out: string[] = [];
    let depth = 0;
    let quote = "";
    let cur = "";
    for (const ch of sel) {
        if (quote) {
            cur += ch;
            if (ch === quote) quote = "";
            continue;
        }
        if (ch === '"' || ch === "'") {
            quote = ch;
        } else if (ch === "(" || ch === "[") {
            depth++;
        } else if (ch === ")" || ch === "]") {
            depth = Math.max(0, depth - 1);
        } else if (ch === "," && depth === 0) {
            out.push(cur);
            cur = "";
            continue;
        }
        cur += ch;
    }
    if (cur.trim()) out.push(cur);
    return out;
}

function sanitizeRules(rules: CSSRuleList, out: string[]): void {
    for (const rule of rules) {
        if (rule instanceof CSSStyleRule) {
            cleanDecls(rule.style);
            if (!rule.style.length) continue;
            const sel = splitSelectors(rule.selectorText)
                .map((s) => `${PANE_SCOPE} ${s.trim()}`)
                .join(",");
            out.push(`${sel}{${rule.style.cssText}}`);
        } else if (
            rule instanceof CSSMediaRule ||
            rule instanceof CSSSupportsRule ||
            (typeof CSSLayerBlockRule === "function" && rule instanceof CSSLayerBlockRule) ||
            (typeof CSSContainerRule === "function" && rule instanceof CSSContainerRule) ||
            (typeof CSSScopeRule === "function" && rule instanceof CSSScopeRule)
        ) {
            const inner: string[] = [];
            sanitizeRules((rule as CSSGroupingRule).cssRules, inner);
            const head = rule.cssText.slice(0, rule.cssText.indexOf("{"));
            out.push(`${head}{${inner.join("")}}`);
        } else if (rule instanceof CSSKeyframesRule) {
            for (const kf of rule.cssRules) cleanDecls((kf as CSSKeyframeRule).style);
            out.push(rule.cssText);
        } else if (
            rule instanceof CSSFontFaceRule ||
            (typeof CSSCounterStyleRule === "function" && rule instanceof CSSCounterStyleRule)
        ) {
            out.push(rule.cssText);
        }
        // @import/@namespace/@page/@charset/未知规则：白名单外一律丢
    }
}

/** <style> 文本 → 作用域化 + 净化后的样式表；解析面失控时丢整表 */
function sanitizeCss(css: string): string {
    let sheet: CSSStyleSheet;
    try {
        sheet = new CSSStyleSheet();
        sheet.replaceSync(css);
    } catch {
        return "";
    }
    const out: string[] = [];
    sanitizeRules(sheet.cssRules, out);
    return out.join("\n");
}

function domElementHook(node: Node): void {
    const el = node as Element;
    if (el.localName === "style") {
        el.textContent = sanitizeCss(el.textContent ?? "");
        return;
    }
    const style = (el as HTMLElement).style;
    if (!style || typeof style.getPropertyValue !== "function") return;
    if (!el.hasAttribute("style")) return;
    cleanDecls(style);
    if (!style.length) el.removeAttribute("style");
}

let domHooked = false;

export function sanitizeDomHtml(html: string): string {
    if (!domHooked) {
        // hook 常驻默认实例：PROFILE 已禁 style 标签/属性，钩不到任何东西
        DOMPurify.addHook("afterSanitizeElements", domElementHook);
        domHooked = true;
    }
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
