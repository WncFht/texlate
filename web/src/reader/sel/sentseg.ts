// sentseg —— DOM 内句边界标定（exp/ss-a11y/sentseg.js 移植）。
// sentence_ends（xlat/batch.py:327）语义的 DOM 移植：
//   产出不是包裹 span，而是零宽 <i class="sb"> 哨兵元素钉在句首——句界可
//   跨内联 <a>/<math>/<b>，任何「包元素」方案都会在跨界句上折断；哨兵点
//   标定 + Range(marker_i → marker_{i+1}|blockEnd) 复原句串是唯一不毁
//   DOM 的路。哨兵 tabindex=-1 + role=mark → roving-focus 游标落点，
//   零新增 tab 停点。
//   id 带侧名（sb-{side}-{seq}-{k}）——双 pane 克隆下裸 id 双侧撞车，
//   aria-activedescendant 会指到对侧元素（实测 zh 侧 AD 引 EN 节点）。
// 句读规则：en .!?+缩写豁免（尾词含.或≤3字母不切）；zh 。！？；+后随空白闸；
// SKIP_TAGS 整树跳 MATH/SCRIPT/SVG。
// 实测 missed_cuts=0、chunkIdx 单调。

const SKIP_TAGS = new Set([
    "MATH",
    "ANNOTATION",
    "SCRIPT",
    "STYLE",
    "NOSCRIPT",
    "TEMPLATE",
    "TEXTAREA",
    "SELECT",
    "IFRAME",
    "OBJECT",
    "SVG",
    "HEAD",
]);

// 与 _ABBREV_TAIL_RX/_ABBREV_MAX_WORD 同款：尾词含 '.'（e.g./al.）或 ≤3
// 字母（Fig/Sec/Dr/vs）→ 缩写位不切。?.! 恒切。
const ABBREV_TAIL_RX = /([A-Za-z][A-Za-z.]*)$/;
const ABBREV_MAX_WORD = 3;
function abbrevCut(text: string, i: number): boolean {
    const m = ABBREV_TAIL_RX.exec(text.slice(0, i));
    if (!m) return false;
    const w = m[1]!;
    return w.includes(".") || w.length <= ABBREV_MAX_WORD;
}
// CJK 句读——zh 侧用同一套哨兵（。！？；后随空白或文本尾）
const CJK_STOP = /[。！？；]/;

// SKIP_SEL：SKIP_TAGS 的选择器形——sentenceText 的 cloneContents 剥离用
// （Range.toString 会带上 math/script 子树文本——spike 同款 latent bug）
const SKIP_SEL = [...SKIP_TAGS].join(",").toLowerCase();

export type SegSide = "en" | "zh";

export interface SentMark {
    /** `${seq}:${k}`——chunk 序 + 块内句序（双 pane 对齐靠管线 sid 对应） */
    sid: string;
    /** 哨兵元素（tabindex=-1 role=mark id=sb-{side}-{seq}-{k}） */
    marker: HTMLElement;
    /** 所属 [data-chunk] 块 */
    block: Element;
    chunkEl: Element;
    /** data-chunk 枚举序（块跳查表用——空句块在 sents 里无项） */
    chunkIdx: number;
}

/** 收集 block 内全部可见文本节点（SKIP_TAGS 子树整体跳过）。
    手工 childNodes 递归而非 TreeWalker——jsdom 的 createTreeWalker 静默
    忽略 {acceptNode} 对象形 filter（实测 math/script 文本漏进 stream）；
    手工走对宿主 webview 零依赖，且 SKIP_TAGS 判在元素上天然整树跳
    （<math><mi>…</mi></math> 文本父是 mi 非 math——递归不进入即免查祖先链）。 */
function textNodes(block: Element): Text[] {
    const out: Text[] = [];
    const walk = (el: Element) => {
        for (const n of el.childNodes) {
            if (n.nodeType === 3) {
                if (n.nodeValue && n.nodeValue.trim()) out.push(n as Text);
            } else if (n.nodeType === 1) {
                const e = n as Element;
                if (!SKIP_TAGS.has(e.tagName.toUpperCase())) walk(e);
            }
        }
    };
    walk(block);
    return out;
}

/**
 * 在 block 内逐句钉哨兵。返回 SentMark[]（未挂 chunkEl/chunkIdx——
 * segmentDoc 统一补）。
 * @param seq chunk 序（sid = `${seq}:${k}`；传 data-chunk 键）
 * @param side 'en'|'zh' 决定句读集合与哨兵 id 侧名
 */
export function segmentBlock(
    block: Element,
    seq: string | number,
    side: SegSide = "en",
): SentMark[] {
    const doc = block.ownerDocument!;
    const nodes = textNodes(block);
    // 拼逻辑流 + 每节点偏移表
    let stream = "";
    const spans: { node: Text; g0: number; g1: number }[] = [];
    for (const n of nodes) {
        spans.push({
            node: n,
            g0: stream.length,
            g1: stream.length + n.nodeValue!.length,
        });
        stream += n.nodeValue;
    }
    // 切点收集：句首恒 0；其余 = 句读 + 后随空白（DOM 无 {} 深度，只保留
    // 缩写豁免 + 空白闸——pipeline 的 \\/{ 语义在已渲染文本上无对应物）
    const cuts = new Set<number>([0]);
    const isStop = (c: string) =>
        side === "zh" ? CJK_STOP.test(c) : ".!?".includes(c);
    for (let i = 0; i + 1 < stream.length; i++) {
        const c = stream[i]!;
        if (!isStop(c)) continue;
        const nxt = stream[i + 1]!;
        if (nxt !== " " && nxt !== "\n" && nxt !== "　") continue;
        if (side !== "zh" && abbrevCut(stream, i)) continue;
        cuts.add(i + 1);
    }
    // 映射 cut → (node, localOffset)，splitText + 插哨兵。
    // 逆序处理——前插不扰后插的节点偏移。
    const locate = (g: number) => {
        for (const s of spans)
            if (g >= s.g0 && g <= s.g1) return { node: s.node, off: g - s.g0 };
        return null;
    };
    const sideName = block.closest(".pane")?.getAttribute("data-side") ?? "d";
    const sorted = [...cuts].sort((a, b) => b - a);
    const marks: SentMark[] = [];
    let k = sorted.length;
    for (const g of sorted) {
        k--;
        const at = locate(g);
        if (!at) continue;
        const m = doc.createElement("i");
        m.className = "sb";
        m.dataset.sid = `${seq}:${k}`;
        // id 须带侧名——双 pane 同构克隆下裸 `sb-seq-k` 双侧撞车
        m.id = `sb-${sideName}-${seq}-${k}`;
        m.tabIndex = -1;
        m.setAttribute("role", "mark");
        m.setAttribute("aria-label", `sentence ${k + 1}`);
        const parent = at.node.parentNode!;
        if (at.off === 0) {
            parent.insertBefore(m, at.node);
        } else if (at.off >= at.node.nodeValue!.length) {
            parent.insertBefore(m, at.node.nextSibling);
        } else {
            at.node.splitText(at.off);
            parent.insertBefore(m, at.node.nextSibling);
        }
        marks.push({
            sid: m.dataset.sid,
            marker: m,
            block,
            chunkEl: block,
            chunkIdx: -1,
        });
    }
    marks.reverse();
    return marks;
}

/** 整文档分句：root 下全部 [data-chunk]（返回带 chunkIdx 的 SentMark[]）。 */
export function segmentDoc(
    root: Element | Document,
    side: SegSide = "en",
): SentMark[] {
    const blocks = [
        ...(root as Element).querySelectorAll<Element>("[data-chunk]"),
    ];
    const out: SentMark[] = [];
    let ci = 0;
    for (const b of blocks) {
        const seq = b.getAttribute("data-chunk") ?? String(ci);
        for (const m of segmentBlock(b, seq, side)) {
            m.chunkEl = b;
            m.chunkIdx = ci;
            out.push(m);
        }
        ci++;
    }
    return out;
}

/** 哨兵 → 句 Range：marker_i → 同块下一哨兵，无则块尾。 */
export function sentenceRange(
    doc: Document,
    all: SentMark[],
    idx: number,
): Range {
    const m = all[idx]!;
    const range = doc.createRange();
    range.setStartAfter(m.marker);
    const next = idx + 1 < all.length ? all[idx + 1]! : null;
    if (next && next.chunkEl === m.chunkEl) {
        range.setEndBefore(next.marker); // 哨兵归入下一句——句间空白随后句前
    } else {
        range.setEndAfter(m.chunkEl.lastChild ?? m.chunkEl);
    }
    return range;
}

/** 句文本（Range 口径——哨兵零宽元素不进）。
    cloneContents + 剥离 SKIP_TAGS 子树：Range.toString 会把界内
    math/script 的全部后代文本一并串连（"x.y" 假句读进译文），
    必须剔除后与 textNodes 的 stream 口径一致。 */
export function sentenceText(
    doc: Document,
    all: SentMark[],
    idx: number,
): string {
    const r = sentenceRange(doc, all, idx);
    const frag = r.cloneContents();
    for (const el of frag.querySelectorAll(SKIP_SEL)) el.remove();
    const t = frag.textContent ?? "";
    r.detach();
    return t.replace(/^\s+/, "").replace(/\s+$/, "");
}
