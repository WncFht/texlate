// markdown —— marked → DOMPurify → KaTeX 段渲染管线：HtmlPane（终态降级
// 视图）与 LivePane（翻译中边读）共用同一条渲染路径，徽标判定同源。
// marked/katex（~300KB）dynamic import 单例缓存：首调加载，其后即取，
// 只服务 html/live 视图，pdf/dom 常用路不付解析成本。

import { escapeHtml, sanitizeHtml } from "./sanitize";
import { externalLinksBlank } from "./paneUtils";
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
                        // LaTeX 引号 `` `` ``/`` '' `` 先转弯引号——marked 会把
                        // 反引号当 code 定界，引文段变 <code> 还会把
                        // [[TYPE_n]] 掩码关进 unmask 跳过区
                        const pre = md.replace(/``/g, "“").replace(/''/g, "”");
                        // marked.parse 输出 string（无异步扩展）；LLM 译文内联
                        // HTML 原样透传——注入前过 DOMPurify
                        return sanitizeHtml(
                            marked.parse(pre, { async: false }) as string,
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

/** 单侧段文本：translated 优 zh 回退 en；original 优 en 回退 zh（空白串视同缺席） */
export function chunkSideText(
    c: { en?: string; zh?: string },
    side: DocId,
): string {
    const [v, alt] = side === "original" ? [c.en, c.zh] : [c.zh, c.en];
    return v?.trim() ? v : alt?.trim() ? alt : (v ?? alt ?? "");
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

// ---------------------------------------------------------------- LaTeX 适配

// eprint 链 chunk 文本带管线掩码 ``[[TYPE_n]]``（本体在 ph map，随
// dual.json 下发）——marked/DOMPurify 把它当纯文本原样放行，故注入后走
// DOM 文本节点反查替换：公式体补定界符交给下游 KaTeX auto-render，引用/
// 链接/抄录剥壳成可读文本，纯排版命令与内部标记静默隐去；ph 缺席
// （live 轮询行/旧产物）token 降级成 muted chip，不露掩码原形。
export const PH_TOKEN_RX = /\[\[\s*([A-Z]+)\s*_?(\d+)\s*\]\]/g;
const PH_PROBE = /\[\[\s*[A-Z]+\s*_?\d+\s*\]\]/;

// 未走掩码直接漏进文本的 LaTeX 残件——纯排版命令/断行/排版空白清掉，
// 带参格式命令剥壳留文本，转义字符回本字，`{-}`（显式连字符）→ `-`，
// `~`（排版 nbsp）→ 空格。剥壳类规则可生新残件（嵌套 `\textbf{a \emph{b}}`），
// pushText 侧做定点复扫。
export const RESIDUE_RULES: [RegExp, string][] = [
    // 断行可选参须先于 \\\\ 清理——`\\[0.2in]` 先吃 `\\` 会留 `[0.2in]`
    [/\\\\\s*\[[\d.]+[a-z]{2}\]/gi, " "],
    [/\\\[[\d.]+[a-z]{2}\]/gi, " "],
    // 双参命令先取可见参——`\textcolor{red}{t}`→t、`\texorpdfstring{t}{pdf}`→t
    [/\\texorpdfstring\s*\{([^{}]*)\}\{[^{}]*\}/g, "$1"],
    [/\\(?:textcolor|colorbox|fcolorbox)\s*\{[^{}]*\}\{([^{}]*)\}/g, "$1"],
    [
        /\\(?:newblock|newline|noindent|indent|hline|toprule|midrule|bottomrule|smallskip|medskip|bigskip|vfill|vfil|hfill|hfil|centering|raggedright|raggedleft|sloppy|fussy|pagebreak|clearpage|cleardoublepage|linebreak|nolinebreak|maketitle|tableofcontents|quad|qquad|em|bf|it|rm|sf|tt|sc|sl|boldmath|unboldmath|normalsize|small|footnotesize|scriptsize|tiny|large|Large|LARGE|huge|Huge|par)\b/g,
        "",
    ],
    // 单参格式/字体命令剥壳——`\textit{x}`→x（嵌套组靠复扫逐层剥）
    [
        /\\(?:textbf|textit|textsl|textsc|texttt|textrm|textsf|textmd|textup|emph|underline|uline|sout|st|hl|text|mathrm|mathbf|mathit|mathsf|mathtt|mathcal|mathbfit|boldsymbol|bm|MakeUppercase|MakeLowercase|uppercase|lowercase|mbox|fbox)\s*\{([^{}]*)\}/g,
        "$1",
    ],
    [/\\(?:vspace\*?|hspace\*?|cmidrule)\{[^}]*\}/g, ""],
    [/\\[,;:!]/g, " "],
    [/\\\\/g, " "],
    [/\\(?=\s)/g, ""], // 断行吃剩的单反斜杠（`\\\n` 尾）
    [/\{-\}/g, "-"],
    [/\\([%&#_])/g, "$1"],
    [/~/g, " "],
    [/ {2,}/g, " "],
];
// 探针直接由规则表合成——任一规则可命中即需进节点处理；手工镜像的命令
// 名单会随规则增删漂移（曾漏 `~`/` {2,}` 等规则，节点被探针误放过去）
const RESIDUE_PROBE = new RegExp(
    RESIDUE_RULES.map(([rx]) => rx.source).join("|"),
    "i",
);

/** 剥 body 顶层 `{...}` 组内容（组内花括号保留；`[...]` 可选参不进组） */
function braceGroups(body: string): string[] {
    const out: string[] = [];
    let depth = 0;
    let cur = "";
    for (const ch of body) {
        if (ch === "{") {
            depth++;
            if (depth > 1) cur += ch;
        } else if (ch === "}") {
            depth--;
            if (depth === 0) {
                out.push(cur);
                cur = "";
            } else {
                cur += ch;
            }
        } else if (depth > 0) {
            cur += ch;
        }
    }
    return out;
}

/** 单枚占位符 → 阅读文本；null = 静默隐去（内部标记类） */
export function phText(kind: string, body: string): string | null {
    const b = body.trim();
    switch (kind) {
        case "MATH": {
            // 裸环境体（\begin{equation}…）无定界符——auto-render 只认
            // 定界符，包 $$ 引它扫到；KaTeX 收 display 内 equation 系
            if (/^\\begin/.test(b)) return `$$${b}$$`;
            if (/^(?:\$\$?|\\\(|\\\[)/.test(b)) return b;
            return `\\(${b}\\)`;
        }
        case "CITE":
        case "BIB": {
            const g = braceGroups(b);
            return g.length ? `[${g[0]}]` : null;
        }
        case "REF": {
            const g = braceGroups(b);
            return g.length ? `(${g[0]})` : null;
        }
        case "URL": {
            const g = braceGroups(b);
            return g[0] ?? null;
        }
        case "HREF": {
            const g = braceGroups(b);
            return g[1] ?? g[0] ?? null;
        }
        case "VERB": {
            // \verb|x| / \verb*|x|——命令名后首字符即成对定界符
            const m = /^\\verb\*?(.)/.exec(b);
            if (!m) return null;
            const d = m[1];
            const j = b.indexOf(d, m[0].length);
            return j > m[0].length - 1 ? b.slice(m[0].length, j) : null;
        }
        case "CMD":
        case "MACRO":
        case "ENVTAG":
        case "EXPAND":
        case "AUTHOR":
        case "ENV": {
            // 命令名隐去、可见参数文本保留——`\textbf{Attention}` → `Attention`
            const g = braceGroups(b);
            return g.length ? g.join(" ") : null;
        }
        // LABEL/KEY/COMMENT/COND/GRAPHICS/……内部件一律隐去
        default:
            return null;
    }
}

/**
 * 掩码 + LaTeX 残件反查（sanitize 后、renderMath 前调）：dom 文本节点上
 * 做 ``[[TYPE_n]]`` → ph 体替换，顺带清未掩码的排版残件。code/pre 内的
 * 字面 LaTeX 是刻意展示——跳过不动。
 */
export function unmaskLatex(
    root: HTMLElement,
    ph?: Record<string, string>,
): void {
    const phm = ph ?? {};
    const nodes: Text[] = [];
    const w = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let n: Node | null;
    while ((n = w.nextNode())) {
        const t = n as Text;
        const p = t.parentElement;
        // [data-ph]/.cite-ref/.bib-anchor 是本函数产出的插桩包装——重跑
        //（重译重绘在同 el 上再进 finishChunk）时它们的正文绝不再扫
        if (
            !p ||
            p.closest("code,pre,.ph-tok,.katex,[data-ph],.cite-ref,.bib-anchor")
        )
            continue;
        if (PH_PROBE.test(t.data) || RESIDUE_PROBE.test(t.data))
            nodes.push(t);
    }
    for (const node of nodes) {
        const text = node.data;
        const frag = document.createDocumentFragment();
        let last = 0;
        let dirty = false;
        const pushText = (s: string) => {
            let cleaned = s;
            // 剥壳会生新残件（嵌套/双参尾部）——定点复扫，3 轮封顶防病态环
            for (let i = 0; i < 3; i++) {
                const prev = cleaned;
                for (const [rx, rep] of RESIDUE_RULES)
                    cleaned = cleaned.replace(rx, rep);
                if (cleaned === prev) break;
            }
            if (cleaned !== s) dirty = true;
            if (cleaned) frag.appendChild(document.createTextNode(cleaned));
        };
        PH_TOKEN_RX.lastIndex = 0;
        let m: RegExpExecArray | null;
        while ((m = PH_TOKEN_RX.exec(text))) {
            pushText(text.slice(last, m.index));
            last = m.index + m[0].length;
            dirty = true;
            const body = phm[`[[${m[1]}_${m[2]}]]`];
            const rep = body != null ? phText(m[1], body) : null;
            if (rep != null) {
                // §2.2 微插桩：MATH 替身包 span[data-ph]（值=原掩码键
                // verbatim——copy-latex 反查锚）；CITE 替身包
                // a.cite-ref[data-key]（cite 悬浮卡/收藏键面——多键
                // \cite{a,b} 保逗号串）。其余替身仍走裸文本节点。
                if (m[1] === "MATH") {
                    const sp = document.createElement("span");
                    sp.dataset.ph = `[[${m[1]}_${m[2]}]]`;
                    sp.textContent = rep;
                    frag.appendChild(sp);
                } else if (m[1] === "CITE") {
                    const a = document.createElement("a");
                    a.className = "cite-ref";
                    const km =
                        /\\cite\w*\*?\s*(?:\[[^\]]*\]\s*)*\{([^}]*)\}/.exec(
                            body,
                        );
                    if (km) a.dataset.key = km[1];
                    a.textContent = rep;
                    frag.appendChild(a);
                } else if (m[1] === "BIB") {
                    // bib 目标载体：html 臂 find-usages 的条目宿主锚
                    // （\bibitem[opt]{key}——bibAt/usageEntryFromCiteMap
                    // 的 data-bib-key 索引键与 usages.ts BIBITEM_KEY_RX 同口径）
                    const sp = document.createElement("span");
                    sp.className = "bib-anchor";
                    const km =
                        /\\bibitem\s*(?:\[[^\]]*\]\s*)?\{([^}]*)\}/.exec(body);
                    if (km) sp.dataset.bibKey = km[1];
                    sp.textContent = rep;
                    frag.appendChild(sp);
                } else {
                    frag.appendChild(document.createTextNode(rep));
                }
            } else if (body == null) {
                const chip = document.createElement("span");
                chip.className = "ph-tok";
                chip.textContent = m[1].toLowerCase();
                frag.appendChild(chip);
            }
        }
        pushText(text.slice(last));
        if (dirty) node.parentNode?.replaceChild(frag, node);
    }
}

/** 注入后渲染管线：外链新窗 → 掩码/残件反查 → KaTeX 重扫
 * （mount 分片 / 重译重绘 / LivePane.paint 三处同口径） */
export function finishChunk(
    el: HTMLElement,
    libs: MdLibs | null,
    ph?: Record<string, string>,
): void {
    externalLinksBlank(el);
    unmaskLatex(el, ph);
    libs?.renderMath(el);
}
