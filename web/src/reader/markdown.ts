// markdown —— marked → DOMPurify → KaTeX 段渲染管线：HtmlPane（终态降级
// 视图）与 LivePane（翻译中边读）共用同一条渲染路径，徽标判定同源。
// marked/katex（~300KB）dynamic import 单例缓存：首调加载，其后即取，
// 只服务 html/live 视图，pdf/dom 常用路不付解析成本。

import { escapeHtml, sanitizeHtml } from "./sanitize";
import type { DocId } from "./alignment";

export interface MdLibs {
    /** 单段 markdown → 消毒后 HTML（marked 抛错降级转义原文——不炸整页） */
    mdToHtml(md: string): string;
    /** 容器内 KaTeX auto-render（整体失败留纯文本；.katex 跳过防重跑叠渲） */
    renderMath(el: HTMLElement): void;
}

let cached: Promise<MdLibs> | null = null;

export function loadMdLibs(): Promise<MdLibs> {
    if (!cached) {
        const p = Promise.all([
            import("marked"),
            import("katex/contrib/auto-render"),
            import("katex/dist/katex.min.css"),
        ]).then(([m, k]) => {
            const marked = m.marked;
            const autoRender = k.default;
            return {
                mdToHtml(md: string): string {
                    try {
                        // marked.parse 输出 string（无异步扩展）；LLM 译文内联
                        // HTML 原样透传——注入前过 DOMPurify
                        return sanitizeHtml(
                            marked.parse(md, { async: false }) as string,
                        );
                    } catch {
                        return `<p>${escapeHtml(md)}</p>`;
                    }
                },
                renderMath(el: HTMLElement): void {
                    try {
                        autoRender(el, {
                            delimiters: [
                                { left: "$$", right: "$$", display: true },
                                { left: "\\[", right: "\\]", display: true },
                                { left: "\\(", right: "\\)", display: false },
                                { left: "$", right: "$", display: false },
                            ],
                            // LivePane 增量补丁 / 单段重译就地更新会重复跑
                            // ——已渲染公式跳过（本版默认 ignoredClasses 为空）
                            ignoredClasses: ["katex"],
                            throwOnError: false, // 单公式失败原样显示源码，不炸整页
                        });
                    } catch {
                        /* KaTeX 整体失败时保留纯文本 */
                    }
                },
            };
        });
        cached = p;
        // 加载失败不留死缓存——下拍重试走新 import（弱网可自愈）
        p.catch(() => {
            if (cached === p) cached = null;
        });
    }
    return cached;
}

/** 单侧段文本：translated 优 zh 回退 en；original 优 en 回退 zh */
export function chunkSideText(
    c: { en?: string; zh?: string },
    side: DocId,
): string {
    return (side === "original" ? c.en : c.zh) ?? c.en ?? c.zh ?? "";
}

/**
 * 段是否「未翻译」（呈现原文）：status 在场以 !ok 为准
 * （fallback_orig/failed/pending 均视为未译）；status 缺席（旧 dual.json）
 * 或 zh 空 → 实际显示的就是原文 → 同样标记。
 */
export function chunkUntranslated(c: {
    status?: string;
    zh?: string;
}): boolean {
    return (
        (c.status !== undefined && c.status !== "ok") || !(c.zh ?? "").trim()
    );
}
