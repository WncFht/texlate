// usages —— find-usages 反向索引：可引用目标 → 全部正文引用处。
// figIndex.ts（fu-popover-spike）泛化移植：figure-only → bib/figure/table/
// equation/theorem/section 六类。三数据源：
//   ① DOM 锚（dom 视图主源）：a[href^="#id"] 扫 pane DOM——0 dangling 实证；
//      TOC/nav chrome 必滤（sec 类 70% 入链在 TOC，不滤虚高 3.4×）；
//      子图锚 closest(figure) 归并宿主；锚落目标内（caption 自指）丢弃。
//   ② dual.json ph token（html 视图唯一源 + seq/语境归位键）：
//      [[CITE_n]] (seq,charOff) 即引用点，\cite{a,b} 逗号拆 key；
//      [[BIB_n]] → bibkey→{seq,charOff,enLen}。
//      存量档 ph 编号漂移实测存在（3/14）——构造期自检 token 序，
//      违例 keyReliable=false → 诚实降级「有句无键」。
//   ③ PDF named dests（v2 机会型）：cite.<bibkey> verbatim——
//      pdfCiteDests 只做存在性查询，反查索引在 PdfPane 侧。
// zh 配对（dom 臂）：双侧 pane 各建索引挂模块级注册表，开卡时按
//   (目标 id, 同 href 锚序 ord) 惰性配 zh 句——挂载序不敏感。

import type { DualChunk, DualJson } from "../api/types";
import { classifyLtxEl, type CiteKind } from "./cmd/hitctx";
import { PH_TOKEN_RX } from "./markdown";
import {
    BLOCK_RX,
    citeKeys,
    maskedSentenceAt,
    sentenceAround,
    zhTokenSentence,
} from "./uscontext";

// ------------------------------------------------------------------ 类型

export type UsageKind = Exclude<CiteKind, null>;

export interface UsageTarget {
    kind: UsageKind;
    /** 宿主元素（子图锚归并后的 figure / ltx_equation 容器 / …） */
    el: HTMLElement;
    id: string;
    label: string;
}

export interface UsageAnchor {
    /** dom 臂锚元素；dual 臂无 DOM 时为 undefined */
    el?: Element;
    /** 锚目标 id（href 片段已 decodeURIComponent） */
    id: string;
    /** 同 id 锚中的出现序（0 基）——跨 pane zh 配对键 */
    ord: number;
    /** 所属 [data-chunk] 枚举序（-1=不在块内）——镜像兜底载荷 */
    chunkOrd: number;
    /** 锚在所在块干净文本中的字符偏移 */
    charOff: number;
    /** dom=双 seq（chunk_id→seq 映射）；html=dual seq 直取 */
    seq: number | null;
}

export interface UsageSite {
    /** 语境句（en，已剥 annotation/掩码） */
    text: string;
    /** zh 配对句——开卡时惰性填 */
    zhText: string | null;
    anchors: UsageAnchor[];
    block: HTMLElement | null;
    /** 块在 root 内文档序（句排序键） */
    order: number;
    /** html 臂跳转页码（dual seq） */
    seq: number | null;
    /** html 臂跳转 fraction（charOff/enLen） */
    fraction?: number;
}

export interface UsageEntry {
    target: UsageTarget;
    sites: UsageSite[];
    /** zh 配对已尝试（一次性懒填闸） */
    paired?: boolean;
}

export interface UsageIndex {
    /** 元素（或其后代视角上爬）→ 目标条目；未索引返回 undefined */
    forEl(el: Element | null): UsageEntry | undefined;
    /** 目标 id → 条目（子图 id 也映到宿主 figure 条目） */
    forId(id: string): UsageEntry | undefined;
    entries: UsageEntry[];
    totalAnchors: number;
    totalSentences: number;
}

// ------------------------------------------------------------------ 工具

/** scope 内按 id 查元素——latexml id 含 .:（bib.bib13/S2.SS1），
    引号属性选择器绕开 CSS.escape（jsdom/老 webview 无），失败兜底全扫。
    与 hitctx.byId 同算法（本模块独立——hitctx 私有件不外借）。 */
function byId(scope: Element | Document, id: string): HTMLElement | null {
    const sel = `[id="${id.replace(/(["\\])/g, "\\$1")}"]`;
    try {
        const hit = scope.querySelector<HTMLElement>(sel);
        if (hit) return hit;
    } catch {
        /* 落兜底扫 */
    }
    for (const e of scope.querySelectorAll<HTMLElement>("[id]"))
        if (e.id === id) return e;
    return null;
}

/** TOC/导航 chrome——其内锚不算正文引用（sec 入链 70% 在此） */
const CHROME_SEL =
    "nav, .ltx_toclist, .ltx_NAV, [role='navigation'], .ltx_tabs";

/** 宿主归并选择器：目标元素或锚命中元素向上归并到这些容器。
    eq 行级无 id 时锚落 td/math 上——最近 .ltx_equation 容器收编；
    theorem 内段（p#Thm1.p1）归并宿主 theorem。 */
const HOST_SEL =
    "figure, .ltx_bibitem, .ltx_equation, .ltx_theorem, .ltx_float_algorithm";

/** 元素 → 引用宿主：命中 HOST_SEL 取最近祖先，否则元素自身（section/
    theorem 顶层 id 元素自为宿主）。 */
export function usageHostOf(el: Element | null): HTMLElement | null {
    if (!el) return null;
    const host = el.matches(HOST_SEL)
        ? (el as HTMLElement)
        : el.closest<HTMLElement>(HOST_SEL);
    return host ?? (el as HTMLElement);
}

/** 目标显示标签：figcaption/.ltx_tag 系优先，无则 id。 */
function targetLabel(host: HTMLElement, kind: UsageKind, id: string): string {
    const pick = (sel: string): string | null => {
        const el = host.querySelector<HTMLElement>(sel);
        const s = el?.textContent?.replace(/\s+/g, " ").trim();
        return s || null;
    };
    let label: string | null = null;
    switch (kind) {
        case "figure":
        case "table":
            label = pick("figcaption .ltx_tag, .ltx_tag_figure, .ltx_tag_table");
            break;
        case "bib":
            label = pick(".ltx_tag_bibitem");
            break;
        case "equation":
            label = pick(".ltx_tag_equation, .ltx_tag");
            break;
        case "theorem":
            label = pick(".ltx_title") ?? pick(".ltx_tag");
            break;
        case "section":
            label =
                pick(".ltx_title") ??
                (host.querySelector("h1,h2,h3,h4,h5,h6")?.textContent
                    ?.replace(/\s+/g, " ")
                    .trim() ||
                    null);
            break;
    }
    if (label && label.length > 80) label = `${label.slice(0, 80)}…`;
    return label || id || kind;
}

/** 元素 → {kind,宿主,id,label} 目标快照；不可引用类（other/无 id）null */
export function classifyTarget(el: Element | null): UsageTarget | null {
    const host = usageHostOf(el);
    if (!host) return null;
    const kind = classifyLtxEl(host);
    if (kind === "other") return null;
    const id = host.id || (el as HTMLElement)?.id || "";
    if (!id) return null;
    return { kind, el: host, id, label: targetLabel(host, kind, id) };
}

// ------------------------------------------------------ DOM 锚索引（dom 臂）

export interface BuildOpts {
    /** data-chunk key → dual seq（PaneSlot.chunks 的 chunk_id→seq 映射） */
    seqOf?(chunkKey: string): number | null;
}

/**
 * pane bodyEl → 全类目标反向索引。
 * ord 口径：同 id 锚中非 chrome + 可解析 + 非自指锚的出现序——zh 侧
 * 同口径计数，(id,ord) 对即跨 pane 配对键。
 */
export function buildUsageIndex(
    root: HTMLElement,
    opts: BuildOpts = {},
): UsageIndex {
    const blockOrder = new Map<HTMLElement, number>();
    let ord = 0;
    for (const b of root.querySelectorAll<HTMLElement>(BLOCK_RX))
        blockOrder.set(b, ord++);

    const chunkEls = [...root.querySelectorAll<HTMLElement>("[data-chunk]")];
    const chunkOrd = new Map<HTMLElement, number>();
    chunkEls.forEach((c, i) => chunkOrd.set(c, i));

    const byHost = new Map<HTMLElement, UsageEntry>();
    const byIdMap = new Map<string, UsageEntry>();
    const mkEntry = (host: HTMLElement, kind: UsageKind, id: string) => {
        const entry: UsageEntry = {
            target: {
                kind,
                el: host,
                id,
                label: targetLabel(host, kind, id),
            },
            sites: [],
        };
        byHost.set(host, entry);
        if (!byIdMap.has(id)) byIdMap.set(id, entry);
        return entry;
    };

    // ①先枚举「自身即宿主」的可索引元素——零引用目标（43% 浮动体从未被
    //   \ref）也要有条目，空态是一等设计而非异常。宿主内元素（figcaption/
    //   子图 panel/eq 行）usageHostOf≠自身 → 不独立成条目（锚归并宿主）。
    for (const el of root.querySelectorAll<HTMLElement>("[id]")) {
        if (!el.id || byHost.has(el)) continue;
        if (usageHostOf(el) !== el) continue;
        const kind = classifyLtxEl(el);
        if (kind === "other") continue;
        mkEntry(el, kind, el.id);
    }

    const ordSeq = new Map<string, number>(); // id → 已见可索引锚数
    let totalAnchors = 0;

    for (const a of root.querySelectorAll<HTMLAnchorElement>(
        "a[href^='#']",
    )) {
        if (a.closest(CHROME_SEL)) continue;
        const href = a.getAttribute("href") ?? "";
        if (href.length < 2) continue;
        let id = href.slice(1);
        try {
            id = decodeURIComponent(id);
        } catch {
            /* 保留原样 */
        }
        const target = byId(root, id);
        if (!target) continue;
        const host = usageHostOf(target);
        if (!host) continue;
        if (host.contains(a)) continue; // caption 自指不算引用
        const kind = classifyLtxEl(host);
        if (kind === "other") continue;
        totalAnchors++;
        const myOrd = ordSeq.get(id) ?? 0;
        ordSeq.set(id, myOrd + 1);

        let entry = byHost.get(host);
        if (!entry)
            // 非枚举宿主（罕见：无 id 的宿主元素被别的 id 锚指向——
            // usageHostOf 归并目标元素自身时才出现）
            entry = mkEntry(host, kind, host.id || id);
        // 目标 id（含子图 id）→ 宿主条目
        if (!byIdMap.has(id)) byIdMap.set(id, entry);
        if (host.id && !byIdMap.has(host.id)) byIdMap.set(host.id, entry);

        const chunkEl = a.closest<HTMLElement>("[data-chunk]");
        const anchor: UsageAnchor = {
            el: a,
            id,
            ord: myOrd,
            chunkOrd: chunkEl ? (chunkOrd.get(chunkEl) ?? -1) : -1,
            charOff: -1,
            seq: chunkEl
                ? (opts.seqOf?.(chunkEl.getAttribute("data-chunk") ?? "") ??
                    null)
                : null,
        };

        const block = a.closest<HTMLElement>(BLOCK_RX);
        if (!block) continue;
        const sent = sentenceAround(block, a);
        if (!sent) continue;
        anchor.charOff = sent.anchorStart;
        const hit = entry.sites.find(
            (s) => s.block === block && s.text === sent.text,
        );
        if (hit) {
            hit.anchors.push(anchor);
        } else {
            entry.sites.push({
                text: sent.text,
                zhText: null,
                anchors: [anchor],
                block,
                order: blockOrder.get(block) ?? Number.MAX_SAFE_INTEGER,
                seq: anchor.seq,
            });
        }
    }

    const entries = [...byHost.values()];
    let totalSentences = 0;
    for (const e of entries) {
        e.sites.sort((x, y) => x.order - y.order);
        totalSentences += e.sites.length;
    }
    return {
        entries,
        totalAnchors,
        totalSentences,
        forEl(el) {
            // 上爬首个带索引 id 的祖先——figure 内 img/caption、section 内
            // 段落都归到各自目标条目
            if (!el || !root.contains(el)) return undefined;
            for (let cur: Element | null = el; cur; cur = cur.parentElement) {
                const id = (cur as HTMLElement).id;
                if (id && byIdMap.has(id)) return byIdMap.get(id);
                if (cur === root) break;
            }
            return undefined;
        },
        forId(id) {
            return byIdMap.get(id);
        },
    };
}

// ------------------------------------------------------ zh 配对（dom 臂）

/** 双侧 pane 索引注册表：en/zh DomPane 各挂本侧（挂载序不敏感——
    配对在开卡时惰性求值，晚挂侧先出的卡 zhText=null 诚实缺省）。 */
const paneIndexes = new Map<"en" | "zh", UsageIndex>();

export function bindPaneIndex(side: "en" | "zh", idx: UsageIndex | null) {
    if (idx) paneIndexes.set(side, idx);
    else paneIndexes.delete(side);
}
export function paneIndex(side: "en" | "zh"): UsageIndex | undefined {
    return paneIndexes.get(side);
}

/** 用对侧索引惰性填 zhText：同目标 id 的 zh 条目里找同 ord 锚所在句。 */
export function fillPairZh(
    entry: UsageEntry,
    other: UsageIndex | undefined,
): void {
    if (!other || entry.paired) return;
    entry.paired = true;
    const oe = other.forId(entry.target.id);
    if (!oe) return;
    const zhByOrd = new Map<number, UsageSite>();
    for (const zs of oe.sites)
        for (const za of zs.anchors)
            if (!zhByOrd.has(za.ord)) zhByOrd.set(za.ord, zs);
    for (const s of entry.sites) {
        if (s.zhText != null) continue;
        for (const a of s.anchors) {
            const zs = zhByOrd.get(a.ord);
            if (zs) {
                s.zhText = zs.text;
                break;
            }
        }
    }
}

// ------------------------------------------------------ dual token 路（html 臂）

export interface CiteOccurrence {
    seq: number;
    /** [[CITE_n]] 在 masked en 中的偏移 */
    charOff: number;
    /** masked en 全长（fraction=charOff/enLen） */
    enLen: number;
    keys: string[];
    /** unmask 后语境句 */
    text: string | null;
    zhText: string | null;
    chunk: DualChunk;
}

export interface CiteUsageMap {
    /** bibkey → 引用点列表（多键 \cite{a,b} 逐 key 各记一条共享位） */
    byKey: Map<string, CiteOccurrence[]>;
    /** bibkey → bibitem 落点 */
    bibAt: Map<string, { seq: number; charOff: number; enLen: number }>;
    /** ph 编号序自检——false=漂移档（键映射不可信，降级有句无键） */
    keyReliable: boolean;
    /** 是否见到任何 CITE token（无 ph 旧档=false→纯 DOM 路） */
    hasTokens: boolean;
}

const BIBITEM_VAL_RX = /^\\bibitem\b/;
const BIBITEM_KEY_RX = /\\bibitem\s*(?:\[[^\]]*\]\s*)?\{([^}]*)\}/;

/**
 * dual.json chunks → bibkey 反向索引（fu-jump/click.mjs 路径产品化）。
 * ph 自检：每 src_file 桶内 CITE token 号按文档序须严格递增——ph 编号
 * 按文件内扫描序签发（rederive 实证），违例即漂移档。
 */
export function buildCiteUsageMap(
    dual: DualJson | { chunks?: DualChunk[] } | null | undefined,
): CiteUsageMap {
    const byKey = new Map<string, CiteOccurrence[]>();
    const bibAt = new Map<
        string,
        { seq: number; charOff: number; enLen: number }
    >();
    const buckets = new Map<string, number[]>();
    let hasTokens = false;

    for (const c of dual?.chunks ?? []) {
        const ph = c.ph ?? {};
        const en = c.en ?? "";
        const seq = Number(c.seq);
        const bucket = c.src_file ?? "";
        // matchAll 克隆 regex 迭代——环体里 maskedSentenceAt/zhTokenSentence
        // 还会用共享 PH_TOKEN_RX（exec/replace 都把 lastIndex 归零），
        // 直接 exec 循环会被内层重置打回起点造成死循环。
        for (const m of en.matchAll(PH_TOKEN_RX)) {
            const tokName = `[[${m[1]}_${m[2]}]]`;
            const body = ph[tokName];
            if (m[1] === "CITE") {
                hasTokens = true;
                (buckets.get(bucket) ?? buckets.set(bucket, []).get(bucket)!).push(
                    Number(m[2]),
                );
                const keys = body != null ? citeKeys(body) : [];
                const sent = maskedSentenceAt(
                    en,
                    ph,
                    m.index,
                    m.index + m[0].length,
                );
                const occ: CiteOccurrence = {
                    seq,
                    charOff: m.index,
                    enLen: en.length,
                    keys,
                    text: sent?.text ?? null,
                    zhText: zhTokenSentence(c.zh, ph, tokName),
                    chunk: c,
                };
                for (const k of keys) {
                    const arr = byKey.get(k) ?? [];
                    // 同 token 位在同 key 下只记一次
                    if (!arr.some((o) => o.seq === seq && o.charOff === m.index))
                        arr.push(occ);
                    byKey.set(k, arr);
                }
            } else if (m[1] === "BIB" && body != null) {
                if (!BIBITEM_VAL_RX.test(body.trim())) continue;
                const km = BIBITEM_KEY_RX.exec(body.trim());
                if (km)
                    bibAt.set(km[1].trim(), {
                        seq,
                        charOff: m.index,
                        enLen: en.length,
                    });
            }
        }
    }

    // 漂移自检：桶内编号序严格递增；空桶/单 token 天然通过
    let keyReliable = true;
    for (const ns of buckets.values()) {
        for (let i = 1; i < ns.length; i++) {
            if (ns[i] <= ns[i - 1]) {
                keyReliable = false;
                break;
            }
        }
        if (!keyReliable) break;
    }

    return { byKey, bibAt, keyReliable, hasTokens };
}

/** CiteUsageMap → UsageEntry 适配（html 臂卡面数据源——无 DOM 锚，
    site.seq+fraction 走 Pos 跳，degraded 时键仍出但标 keyReliable）。 */
export function usageEntryFromCiteMap(
    map: CiteUsageMap,
    key: string,
    label: string,
): UsageEntry {
    const occs = map.byKey.get(key) ?? [];
    // 同句多引用点合并（seq+text 去重，anchors 收齐）
    const sites: UsageSite[] = [];
    occs.forEach((o, i) => {
        const anchor: UsageAnchor = {
            id: key,
            ord: i,
            chunkOrd: -1,
            charOff: o.charOff,
            seq: o.seq,
        };
        const fraction = o.enLen > 0 ? o.charOff / o.enLen : 0;
        const hit = sites.find(
            (s) => s.seq === o.seq && s.text === (o.text ?? ""),
        );
        if (hit) hit.anchors.push(anchor);
        else
            sites.push({
                text: o.text ?? "",
                zhText: o.zhText,
                anchors: [anchor],
                block: null,
                order: i,
                seq: o.seq,
                fraction,
            });
    });
    return {
        target: {
            kind: "bib",
            el: null as unknown as HTMLElement,
            id: key,
            label,
        },
        sites,
    };
}

// ------------------------------------------------------------------ pdf 臂

/** pdf named dest 机会型查询：cite.<bibkey> verbatim（dest-vocab 实测
    59.6% 文档有；无 dests 集或缺名 → 空列表诚实降级）。 */
export function pdfCiteDests(
    dests: ReadonlySet<string> | undefined,
    key: string,
): string[] {
    if (!dests) return [];
    const d = `cite.${key}`;
    return dests.has(d) ? [d] : [];
}

// ------------------------------------------------------------------ 定位

export interface CardPlacement {
    left: number;
    top: number;
    flipped: boolean;
    width: number;
}

/** 锚 rect → 卡几何：锚下方优先，不足且上方更宽则翻上；左右夹视口。
    与 CiteCard 同口径（CARD_W=380, GAP=6, 边距 8）——spike 纯函数直搬。 */
export function cardPlacement(
    rect: Pick<DOMRect, "left" | "right" | "top" | "bottom">,
    cardH: number,
    vw: number,
    vh: number,
    cardW = 380,
    gap = 6,
): CardPlacement {
    const width = Math.min(cardW, vw - 16);
    const left = Math.min(Math.max(8, rect.left), vw - width - 8);
    const below = vh - rect.bottom;
    let top = rect.bottom + gap;
    let flipped = false;
    if (
        below < cardH + gap + 8 &&
        rect.top > below &&
        rect.top - cardH - gap >= 8
    ) {
        top = rect.top - cardH - gap;
        flipped = true;
    } else {
        top = Math.min(top, vh - cardH - 8);
    }
    return { left, top, flipped, width };
}
