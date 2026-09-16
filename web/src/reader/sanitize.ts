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
