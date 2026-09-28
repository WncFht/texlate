// hitctx —— 命中语境快照（sel-system Wave B）。
// 从 (selection, target, pane kind) 同步构造一份 HitCtx：菜单/键位/浮条
// 三入口共用同一快照时刻，谓词键由 flattenCtx 产出一一对应可查。
//
// 语境来源（全部仓内实证标记）：
//   sel    —— 原生 Selection + coveredChunks（reader/sel/coveredChunks.ts）；
//            跨 pane 选区对 deps.bodies 双侧各跑取并集。
//   cite   —— a.ltx_ref[href^='#']/.ltx_cite 容器/a.cite-ref[data-key]
//            （unmaskLatex 微插桩）；目标分类走宿主元素 class 词表
//            （ltx_bibitem/ltx_figure/ltx_table/ltx_equation/ltx_theorem/
//            ltx_section 系），未解析元素退 dest 名前缀词表（cite./equation./
//            figure./table./section*/theorem|lemma|bib. / latexml S\d.E/F/T）。
//   math   —— math.ltx_Math[alttext] + annotation[encoding=application/x-tex]
//            （latexml 真标记）；.katex/mjx-container 侧取内嵌 <math>。
//   chunk  —— closest('[data-chunk]')；intSeq 走 chunk_id→seq 映射
//            （chunks 端点已带 chunk_id，deps.seqOf 一次 Map）。
//   caps   —— 宿主能力面（assist 恒 false——无后端端点，见 menu-spec）。

import type { Ctx } from "./cmdreg";
import { extractRefIds } from "../citations";
import { MARKED_SPEC } from "../pdfmarks";
import { makeChunkResolver } from "../sel/coveredChunks";
import { selectionCopyText } from "../sel/selection";

// ------------------------------------------------------------------ 类型

export type PaneView = "dom" | "html" | "pdf" | "unknown";
export type PaneSide = "en" | "zh";

export type CiteKind =
    | "bib"
    | "figure"
    | "table"
    | "equation"
    | "theorem"
    | "section"
    | "other"
    | null;

export interface HitSel {
    /** 复制口径文本（range cloneContents().textContent，不折叠换行） */
    text: string;
    /** text.trim()——谓词/查询用 */
    trimmed: string;
    /** 选区两端点均落在 chunk 区内（copyPair 谓词真值源） */
    inChunk: boolean;
    /** covered data-chunk 键（文档序；跨 pane 双侧并集） */
    chunks: string[];
    /** 载荷：规范化 range（getRangeAt(0)） */
    range: Range | null;
}

export interface HitCite {
    targetKind: CiteKind;
    /** 锚目标可解析：dom=同 pane 内元素命中；pdf=dests() 含名 */
    targetExists: boolean;
    /** bibkey：href 片段（bib.bib13；cite.foo 去 cite. 前缀）或 data-key 首键 */
    bibkey: string | null;
    /** 条目正文：同 pane bibitem 文本 或 citeIndex 命中 */
    entryText: string | null;
    /** 卡片可填（bibkey 在手且有条目源）——cite.card 谓词用 */
    cardFillable: boolean;
    arxivId: string | null;
    doi: string | null;
    /** href 片段原文（跳转目标 id / pdf dest 名） */
    targetId: string | null;
    /** 解析到的目标元素（本 pane 内；pdf 侧恒 null） */
    targetEl: Element | null;
    /** 命中的锚元素 */
    anchorEl: Element | null;
}

export interface HitMath {
    /** TeX 源：alttext 优先，缺省取 annotation[x-tex] 文本 */
    tex: string | null;
    /** MathML 序列化（math 元素 outerHTML；katex 侧取内嵌 math） */
    mathml: string | null;
    el: Element | null;
}

export interface HitSent {
    /** sent-align 句锚 data-sid="{chunk}.{k}"（注入标引；未注入=null） */
    sid: string | null;
    /** bead 锚 data-bead="{chunk}.{b}"——sent.gotoPeer 谓词键 */
    bead: string | null;
}

export interface HitChunk {
    /** data-chunk 键原文（dom=emit 块 key 如 S1.p4；html=seq 串） */
    key: string | null;
    /** 整数 seq（html=直解；dom=chunk_id→seq 映射；无行锚=null——约 31%） */
    intSeq: number | null;
    /** 宿主块分类（ltx_* 词表同 cite 分类；html pane 恒 'section'） */
    kind: CiteKind;
    el: Element | null;
    /** 对侧 pane 同 key 块可解析（copyPair 谓词） */
    counterpartAvail: boolean;
    /** seq ∈ 在飞重译集（retx 的 enableWhen 闸——disabled 不 hidden） */
    pending: boolean;
    /** 本侧块含非空文本 */
    hasText: boolean;
    /** en/zh 文本可取得（本侧文本 或 deps.chunkText 对侧解析） */
    hasEn: boolean;
    hasZh: boolean;
    /** zh 侧未译标记（.chunk-badge 或 deps.zhUntranslated） */
    zhUntranslated: boolean;
    /** 含 table/math/img/svg 等非文本件（空 textContent 容器块兜底） */
    hasNontext: boolean;
    /** 块内含 [data-ph] 掩码件 */
    hasPh: boolean;
}

export interface Caps {
    findInPane: boolean;
    /** 恒 false——assist 端点未上线（menu-spec sel.explain 不注册） */
    assist: boolean;
    retx: boolean;
    discover: boolean;
    navBack: boolean;
    navFwd: boolean;
    linkScheme: boolean;
}

export interface HitCtx {
    sel: HitSel;
    cite: HitCite;
    math: HitMath;
    sent: HitSent;
    chunk: HitChunk;
    view: PaneView;
    /** .pane[data-side] 归一：original→en translated→zh（直书 en/zh 也收） */
    paneSide: PaneSide | null;
    caps: Caps;
    target: Element | null;
}

// ------------------------------------------------------------------ deps

/** citeIndex 最小面（reader/citations.ts CiteIndex 的结构子集） */
export interface CiteLookup {
    lookup(
        keyOrDest: string,
    ): { text?: string; arxivId?: string; doi?: string } | undefined;
}

export interface HitDeps {
    /** pane 类（宿主传入；缺省按 target 所在 .pane 类名探） */
    view?: PaneView;
    /**
     * coveredChunks 的 pane body 集合——单 pane 传 [bodyEl]；跨 pane
     * 选区（commonAncestor=body）传双侧 [enBody, zhBody] 各跑取并集。
     * 缺省 = target 最近的 .pane-html-body/.textLayer 容器。
     */
    bodies?: readonly Element[];
    /** chunk_id→seq 映射（chunks 端点 chunk_id 字段建一次 Map） */
    seqOf?: ReadonlyMap<string, number> | ((key: string) => number | null);
    /** 在飞重译 seq 集（retx pending 闸） */
    pending?: ReadonlySet<number>;
    /** chunk 文本解析（本侧缺省时对侧 counter part 文本源） */
    chunkText?(key: string, lang: PaneSide): string | null;
    /** zh 未译外部判定（en 侧点击时无从看 badge——宿主按 chunks 行补） */
    zhUntranslated?(key: string): boolean;
    /** citeIndex（dual.json 路）——pdf/html 侧 entryText 与 arxiv/doi 源 */
    citeIndex?: CiteLookup;
    /** pdf.js named dest 已收集名集（PdfPane.handle.dests()） */
    dests?: ReadonlySet<string>;
    caps?: Partial<Caps>;
}

// ------------------------------------------------------------- 目标分类词表

/** ltx_* class → kind（宿主元素自身 class 词表，按优先级首个命中） */
const LTX_KIND: [RegExp, Exclude<CiteKind, null>][] = [
    [/^ltx_bibitem$|^ltx_bibblock$/, "bib"],
    [/^ltx_equation$|^ltx_eqn/, "equation"],
    [/^ltx_figure$|^ltx_flex_figure$|^ltx_subfloat$/, "figure"],
    [/^ltx_table$/, "table"],
    [/^ltx_theorem/, "theorem"],
    [
        /^ltx_(chapter|section|subsection|subsubsection|paragraph|subparagraph|abstract)/,
        "section",
    ],
];

/**
 * 元素 → kind：自身 class 词表优先；不识则爬到最近的 ltx_* 祖先重判
 * （嵌套内层如 ltx_caption/ltx_tbody 兜底到宿主 figure/table）。
 */
export function classifyLtxEl(el: Element | null): Exclude<CiteKind, null> {
    for (let cur = el; cur; cur = cur.parentElement) {
        const cls = cur.getAttribute("class") ?? "";
        if (!cls.includes("ltx_")) continue;
        const toks = cls.split(/\s+/);
        for (const [rx, kind] of LTX_KIND)
            if (toks.some((t) => rx.test(t))) return kind;
        if (cur !== el) return "other"; // 最近 ltx_ 祖先不识别 → 不再上爬
    }
    return "other";
}

/** dest 名/元素 id 前缀分类（pdf named dest + latexml id 词表双吃） */
export function classifyDestName(name: string): Exclude<CiteKind, null> {
    const n = name.toLowerCase();
    if (/^(cite|bib)\./.test(n) || /^bib$/.test(n)) return "bib";
    if (/^(equation|eq|eqn)[._-]/.test(n) || /(?:^|\.)e\d+$/.test(n))
        return "equation";
    if (
        /^(figure|fig|subfigure|subfig)[._-]/.test(n) ||
        /(?:^|\.)f\d+(?:\.\w+)?$/.test(n)
    )
        return "figure";
    if (/^(table|tab)[._-]/.test(n) || /(?:^|\.)t\d+(?:\.\d+)?$/.test(n))
        return "table";
    if (
        /^(theorem|thm|lemma|lem|prop|proposition|cor|corollary|def|definition|remark|rem)[._-]/.test(
            n,
        )
    )
        return "theorem";
    if (
        /^(chapter|part|section\*?|subsection|subsubsection|paragraph|appendix|abstract)[._-]/.test(
            n,
        ) ||
        /^s(?:x?\d+)(?:\.s{1,3}\d+)*$/.test(n)
    )
        return "section";
    return "other";
}

// ------------------------------------------------------------- 内部工具

const normSide = (raw: string | null): PaneSide | null =>
    raw === "original" || raw === "en"
        ? "en"
        : raw === "translated" || raw === "zh"
          ? "zh"
          : null;

const MATH_SEL = "math, .katex, mjx-container";
// 末项罩 pdf 批注层全部内链锚（figure./table./equation./section./cite.*）——
// 类由 classifyDestName 分桶，bib 谓词照常只接 cite.*
const CITE_SEL =
    "a.cite-ref, .ltx_cite, a.ltx_ref[href^='#'], a[href^='#bib.'], a[href^='#cite.'], section.linkAnnotation a[href^='#']";
const NONTEXT_SEL = "table, math, img, svg, figure, video, canvas, iframe";

function texOf(mathEl: Element): string | null {
    const alt = mathEl.getAttribute("alttext");
    if (alt) return alt;
    const ann = mathEl.querySelector(
        "annotation[encoding='application/x-tex']",
    );
    return ann?.textContent?.trim() || null;
}

function mathmlOf(mathEl: Element): string | null {
    const m =
        mathEl.tagName === "math" || mathEl.tagName === "MATH"
            ? mathEl
            : (mathEl.querySelector("math") ?? null);
    return m ? m.outerHTML : null;
}

interface CiteAnchor {
    /** 锚元素（a.ltx_ref/a.cite-ref/首个内层 a[href^='#']） */
    a: Element;
    /** 跳转目标名（href 片段或 pdf dest）；cite-ref 多键为首键 */
    targetId: string | null;
    bibkey: string | null;
    /** 多键列表（cite-ref data-key 逗号串） */
    keys: string[];
}

/** target → cite 锚解析；未命中 null */
function citeAnchorOf(target: Element | null): CiteAnchor | null {
    if (!target) return null;
    const hit = target.closest(CITE_SEL);
    if (!hit) return null;
    if (hit.matches("a.cite-ref")) {
        const keys = (hit.getAttribute("data-key") ?? "")
            .split(",")
            .map((k) => k.trim())
            .filter(Boolean);
        return {
            a: hit,
            targetId: keys[0] ?? null,
            bibkey: keys[0] ?? null,
            keys,
        };
    }
    // .ltx_cite 容器（点中括号/逗号非链面）→ 取内层首链
    const a = hit.matches("a[href^='#']")
        ? hit
        : hit.querySelector("a[href^='#']");
    if (!a) return null;
    const href = a.getAttribute("href") ?? "";
    if (!href.startsWith("#")) return null;
    let frag = href.slice(1);
    try {
        frag = decodeURIComponent(frag);
    } catch {
        /* 保留原样 */
    }
    return {
        a,
        targetId: frag,
        bibkey: frag.startsWith("cite.") ? frag.slice(5) : frag,
        keys: [frag],
    };
}

/** scope 内按 id 查元素：latexml id 含 .:（bib.bib13/S2.SS1）——
    引号属性选择器绕开 CSS.escape（jsdom/老 webview 无），失败兜底全扫。 */
function byId(scope: Element | Document, id: string): Element | null {
    const sel = `[id="${id.replace(/(["\\])/g, "\\$1")}"]`;
    try {
        const hit = scope.querySelector(sel);
        if (hit) return hit;
    } catch {
        /* 落兜底扫 */
    }
    for (const e of scope.querySelectorAll("[id]")) if (e.id === id) return e;
    return null;
}

/** 端点是否在 chunk 区：在锚内、本身是锚、或含锚元素（body 全选端点）。
    pdf 侧 span.markedContent[id] 同位计入（marked-content seq 锚） */
const endpointInChunk = (n: Node): boolean => {
    const el = n.nodeType === 3 ? n.parentElement : (n as Element);
    return (
        el?.closest?.("[data-chunk], span.markedContent[id]") != null ||
        (el?.querySelectorAll?.("[data-chunk]").length ?? 0) > 0
    );
};

// ------------------------------------------------------------------ 快照

/**
 * 事件时刻快照。sel 可注入（测试桩 getSelection 用）；缺省取
 * target.ownerDocument.getSelection()——无 window 环境安全。
 */
export function snapshotHit(
    target: Element | null,
    sel?: Pick<Selection, "rangeCount" | "getRangeAt"> | null,
    deps: HitDeps = {},
): HitCtx {
    const doc = target?.ownerDocument ?? deps.bodies?.[0]?.ownerDocument;
    const liveSel =
        sel === undefined
            ? ((doc?.defaultView ?? doc)?.getSelection?.() ?? null)
            : sel;

    const pane = target?.closest(".pane") ?? null;
    const paneSide = normSide(pane?.getAttribute("data-side") ?? null);
    const view: PaneView =
        deps.view ??
        (pane?.classList.contains("pane-dom")
            ? "dom"
            : pane?.classList.contains("pane-html")
              ? "html"
              : pane?.classList.contains("pane-pdf")
                ? "pdf"
                : "unknown");

    // ------------------------------------------------------------ sel
    const bodies =
        deps.bodies ??
        ([
            target?.closest(".pane-html-body, .textLayer, .pane-body") ??
                pane ??
                null,
        ].filter(Boolean) as Element[]);
    let range: Range | null = null;
    const chunks: string[] = [];
    let selText = "";
    if (liveSel && liveSel.rangeCount > 0) {
        range = liveSel.getRangeAt(0);
        selText = selectionCopyText(range);
        const seen = new Set<string>();
        for (const b of bodies) {
            // .textLayer body → markedContent seq 锚（pdf B 路）；其余
            // body 维持 [data-chunk]（dom/html 锚族）
            const spec = b.classList.contains("textLayer")
                ? MARKED_SPEC
                : undefined;
            for (const k of makeChunkResolver(b, undefined, spec)(range)) {
                if (!seen.has(k)) {
                    seen.add(k);
                    chunks.push(k);
                }
            }
        }
    }
    const inChunk =
        chunks.length > 0 &&
        !!range &&
        endpointInChunk(range.startContainer) &&
        endpointInChunk(range.endContainer);

    // ------------------------------------------------------------ cite
    const ca = citeAnchorOf(target);
    let targetEl: Element | null = null;
    let targetExists = false;
    if (ca?.targetId) {
        // 本 pane 内解析（dup-id 防对侧命中——DomPane.anchorTarget 同口径）
        const scope =
            ca.a.closest(".pane")?.querySelector(".pane-html-body") ??
            ca.a.closest(".pane") ??
            // live-pane 等无 .pane 壳宿主：锚自身所在文本容器优先于
            // bodies[0]（后者恒为首侧 pane——会误解析到别的窗格）
            ca.a.closest(".pane-html-body, .textLayer, .pane-body") ??
            bodies[0] ??
            ca.a.ownerDocument;
        targetEl = byId(scope, ca.targetId);
        if (!targetEl) {
            // html 臂 bib 宿主：unmaskLatex 产 .bib-anchor[data-bib-key]
            // （span 无 id）——a.cite-ref 的裸 bibkey 落在这里才解析得到
            // 目标，否则 cite.* 整段命令面在 html 视图全灭
            const q = ca.targetId.replace(/(["\\])/g, "\\$1");
            try {
                targetEl =
                    scope.querySelector?.(`[data-bib-key="${q}"]`) ?? null;
            } catch {
                targetEl = null;
            }
        }
        if (targetEl) targetExists = true;
        else if (deps.dests?.has(ca.targetId)) targetExists = true;
    }
    const targetKind: CiteKind = !ca
        ? null
        : targetEl
          ? targetEl.matches?.(".bib-anchor,[data-bib-key]")
              ? "bib"
              : classifyLtxEl(targetEl)
          : ca.targetId
            ? classifyDestName(ca.targetId)
            : "other";
    const citeIndexHit = (() => {
        if (!ca?.bibkey || !deps.citeIndex) return undefined;
        return (
            deps.citeIndex.lookup(ca.bibkey) ??
            deps.citeIndex.lookup(ca.bibkey.replace(/^bib\./, "")) ??
            deps.citeIndex.lookup(`cite.${ca.bibkey}`)
        );
    })();
    // .bib-anchor 只含 "[key]" 标号（条目正文在 chunk 尾部）——裸锚命中时
    // entryText 让给 citeIndex 富文，锚文本仅作最终兜底
    const bareAnchor = !!targetEl?.matches?.(".bib-anchor,[data-bib-key]");
    const entryText =
        targetEl && targetKind === "bib" && !bareAnchor
            ? targetEl.textContent?.replace(/\s+/g, " ").trim() || null
            : (citeIndexHit?.text ??
              (bareAnchor
                  ? targetEl?.textContent?.replace(/\s+/g, " ").trim() || null
                  : null));
    const ids = extractRefIds(entryText ?? "");
    const cite: HitCite = {
        targetKind,
        targetExists,
        bibkey: ca?.bibkey ?? null,
        entryText,
        cardFillable:
            targetKind === "bib" &&
            !!ca?.bibkey &&
            (entryText != null || citeIndexHit != null),
        arxivId: citeIndexHit?.arxivId ?? ids.arxivId ?? null,
        doi: citeIndexHit?.doi ?? ids.doi ?? null,
        targetId: ca?.targetId ?? null,
        targetEl,
        anchorEl: ca?.a ?? null,
    };

    // ------------------------------------------------------------ math
    const mathEl = target?.closest(MATH_SEL) ?? null;
    const math: HitMath = {
        tex: mathEl ? texOf(mathEl) : null,
        mathml: mathEl ? mathmlOf(mathEl) : null,
        el: mathEl,
    };

    // ------------------------------------------------------------ sent
    // sent-align 注入的句标引（span.ens|zhs[data-sid][data-bead]）——
    // sent.gotoPeer 的谓词源；未注入/已剥时恒 null
    const sentEl = target?.closest?.("[data-sid]") ?? null;
    const sent: HitSent = {
        sid: sentEl?.getAttribute("data-sid") ?? null,
        bead: sentEl?.getAttribute("data-bead") ?? null,
    };

    // ------------------------------------------------------------ chunk
    const chunkEl = target?.closest("[data-chunk]") ?? null;
    const chunkKey = chunkEl?.getAttribute("data-chunk") ?? null;
    const intSeq = (() => {
        if (chunkKey == null) return null;
        if (/^\d+$/.test(chunkKey)) return Number(chunkKey); // html 侧恒等
        const m = deps.seqOf;
        if (!m) return null;
        return typeof m === "function"
            ? m(chunkKey)
            : (m.get(chunkKey) ?? null);
    })();
    const hasText = !!chunkEl?.textContent?.trim();
    const ownText = hasText ? (chunkEl?.textContent ?? "") : null;
    const otherSide: PaneSide = paneSide === "zh" ? "en" : "zh";
    const enText =
        paneSide === "en"
            ? ownText
            : (chunkKey != null && deps.chunkText?.(chunkKey, "en")) || null;
    const zhText =
        paneSide === "zh"
            ? ownText
            : (chunkKey != null && deps.chunkText?.(chunkKey, "zh")) || null;
    const chunk: HitChunk = {
        key: chunkKey,
        intSeq,
        kind: chunkEl
            ? view === "html"
                ? "section"
                : classifyLtxEl(chunkEl)
            : null,
        el: chunkEl,
        counterpartAvail:
            chunkKey != null &&
            deps.chunkText != null &&
            deps.chunkText(chunkKey, otherSide) != null,
        pending: intSeq != null && (deps.pending?.has(intSeq) ?? false),
        hasText,
        hasEn: enText != null && enText.trim() !== "",
        hasZh: zhText != null && zhText.trim() !== "",
        zhUntranslated:
            (paneSide === "zh" && !!chunkEl?.querySelector(".chunk-badge")) ||
            (chunkKey != null && (deps.zhUntranslated?.(chunkKey) ?? false)),
        hasNontext: !!chunkEl?.querySelector(NONTEXT_SEL),
        hasPh: !!chunkEl?.querySelector("[data-ph]"),
    };

    // ------------------------------------------------------------ caps
    const caps: Caps = {
        findInPane: false,
        assist: false, // 无后端端点——menu-spec sel.explain 不注册
        retx: false,
        discover: false,
        navBack: false,
        navFwd: false,
        linkScheme: false,
        ...deps.caps,
    };

    return {
        sel: {
            text: selText,
            trimmed: selText.trim(),
            inChunk,
            chunks,
            range,
        },
        cite,
        math,
        sent,
        chunk,
        view,
        paneSide,
        caps,
        target,
    };
}

// ---------------------------------------------------------------- 谓词面

/**
 * HitCtx → 扁平谓词袋（when 子句读的键）。
 * 语义注意：
 *   - sel.text     值为 trimmed 文本——「trim 非空」谓词直读
 *   - chunk.intSeq 折叠为「intSeq !== null」布尔——seq=0 恒真值坑免疫
 *   - 其余 null/串/布尔直出（JS truthy 判定）
 */
export function flattenCtx(hit: HitCtx): Ctx {
    return {
        "sel.text": hit.sel.trimmed,
        "sel.inChunk": hit.sel.inChunk,
        "sel.chunks": hit.sel.chunks.length > 0,
        "cite.targetKind": hit.cite.targetKind,
        "cite.targetExists": hit.cite.targetExists,
        "cite.bibkey": hit.cite.bibkey,
        "cite.entryText": hit.cite.entryText,
        "cite.cardFillable": hit.cite.cardFillable,
        "cite.arxivId": hit.cite.arxivId,
        "cite.doi": hit.cite.doi,
        "math.tex": hit.math.tex,
        "math.mathml": hit.math.mathml,
        // 可选链：手写 hit 夹具/旧快照可缺 sent 臂——键仍出、值 null
        "sent.sid": hit.sent?.sid ?? null,
        "sent.bead": hit.sent?.bead ?? null,
        "chunk.seq": hit.chunk.key,
        "chunk.intSeq": hit.chunk.intSeq !== null,
        "chunk.kind": hit.chunk.kind,
        "chunk.counterpartAvail": hit.chunk.counterpartAvail,
        "chunk.pending": hit.chunk.pending,
        "chunk.hasEn": hit.chunk.hasEn,
        "chunk.hasZh": hit.chunk.hasZh,
        "chunk.zhUntranslated": hit.chunk.zhUntranslated,
        "chunk.hasNontext": hit.chunk.hasNontext,
        "chunk.hasPh": hit.chunk.hasPh,
        view: hit.view,
        paneSide: hit.paneSide,
        "caps.findInPane": hit.caps.findInPane,
        "caps.assist": hit.caps.assist,
        "caps.retx": hit.caps.retx,
        "caps.discover": hit.caps.discover,
        "caps.navBack": hit.caps.navBack,
        "caps.navFwd": hit.caps.navFwd,
        "caps.linkScheme": hit.caps.linkScheme,
    };
}

/** 谓词键全集——auditWhenKeys 的 ctxKeys 源（拼写漂移审计基准）。 */
export const CTX_KEYS: readonly string[] = [
    "sel.text",
    "sel.inChunk",
    "sel.chunks",
    "cite.targetKind",
    "cite.targetExists",
    "cite.bibkey",
    "cite.entryText",
    "cite.cardFillable",
    "cite.arxivId",
    "cite.doi",
    "math.tex",
    "math.mathml",
    "sent.sid",
    "sent.bead",
    "chunk.seq",
    "chunk.intSeq",
    "chunk.kind",
    "chunk.counterpartAvail",
    "chunk.pending",
    "chunk.hasEn",
    "chunk.hasZh",
    "chunk.zhUntranslated",
    "chunk.hasNontext",
    "chunk.hasPh",
    "view",
    "paneSide",
    "caps.findInPane",
    "caps.assist",
    "caps.retx",
    "caps.discover",
    "caps.navBack",
    "caps.navFwd",
    "caps.linkScheme",
];
