// coveredChunks —— [data-chunk] 选区命中（预研版移植，对拍验证语义保持）。
// 与 range.intersectsNode 全扫一致（800+ fuzz + directed 全等），复杂度
// O(命中锚数) 而非 O(总锚数)：jsdom 实测 ~25µs vs ~43ms（163 锚）。
//
// 契约：bodyEl = pane 挂载根（.pane-html-body）；range = sel.getRangeAt(0)
//   （必须先 getRangeAt 规范化——anchor/focus 可能反向）。
// 返回 data-chunk 值数组（文档序）。seq 映射另需 chunk_id→seq 表
//   （chunks 端点 chunk_id；~31% 锚无行：bibitem/figure/authors → null 兜底）。
//
// 已知边界：
//   - 选区终点恰在下一锚首文本 offset0 → 该锚以白字相交计入（trim>0 滤）
//   - 端点落在无锚区（license 行/页眉残渣）→ 向文档序收拢到最近锚
//   - 跨 pane 选区：对两侧 bodyEl 各跑一遍（单 document，commonAncestor=body）

const childEl = (
    node: Node,
    offset: number,
    side: "start" | "end",
): Element | null => {
    if (node.nodeType === 3) return node.parentElement;
    if (node.nodeType === 1) {
        // Range offset 计 childNodes（含文本/注释），不是 children
        const el = node as Element;
        const t =
            side === "start"
                ? el.childNodes[offset]
                : el.childNodes[offset - 1];
        if (!t) return el;
        return t.nodeType === 3
            ? t.parentElement
            : t.nodeType === 1
              ? (t as Element)
              : el;
    }
    return null;
};

/** 最外层锚（嵌套锚归并到宿主锚） */
const outermost = (el: Element | null, sel: string): Element | null => {
    let cur = el?.closest?.(sel) ?? null;
    while (cur?.parentElement?.closest?.(sel))
        cur = cur.parentElement.closest(sel);
    return cur;
};

/** 最内层锚（closest 即最内） */
const innermost = (el: Element | null, sel: string): Element | null =>
    el?.closest?.(sel) ?? null;

export type CoveredChunks = (range: Range) => string[];

/** 锚族规格——[data-chunk]（dom/html 侧）或 span.markedContent[id]
    （pdf textLayer 侧，pdfmarks.MARKED_SPEC）。keyOf null=非本族锚跳过 */
export interface ChunkAnchorSpec {
    selector: string;
    keyOf(el: Element): string | null;
}

const DATA_SPEC: ChunkAnchorSpec = {
    selector: "[data-chunk]",
    keyOf: (el) => el.getAttribute("data-chunk"),
};

/**
 * 建 resolver：快照 bodyEl 下全部锚元素（构建期一次 querySelectorAll
 * + Map 索引）。DOM 变化后须重建——pane 重渲/分片落地完成后调方重建。
 * RangeCtor 可注入（jsdom/跨 realm 测试用）；spec 缺省 [data-chunk]。
 */
export function makeChunkResolver(
    bodyEl: Element,
    RangeCtor?: typeof Range,
    spec: ChunkAnchorSpec = DATA_SPEC,
): CoveredChunks {
    const R = RangeCtor ?? bodyEl.ownerDocument!.defaultView!.Range;
    const sel = spec.selector;
    const chunkEls = [...bodyEl.querySelectorAll<Element>(sel)] as Element[];
    const idxOf = new Map<Element, number>(chunkEls.map((e, i) => [e, i]));
    const er = bodyEl.ownerDocument!.createRange();
    const endsAfterStart = (el: Element, selR: Range): boolean => {
        er.selectNodeContents(el);
        return er.compareBoundaryPoints(R.START_TO_END, selR) > 0;
    };
    const startsBeforeEnd = (el: Element, selR: Range): boolean => {
        er.selectNodeContents(el);
        return er.compareBoundaryPoints(R.END_TO_START, selR) < 0;
    };

    /** @returns 文档序锚 keys（spec.keyOf 非 null 者） */
    return function coveredChunks(range: Range): string[] {
        const sEl = childEl(range.startContainer, range.startOffset, "start");
        const eEl = childEl(range.endContainer, range.endOffset, "end");
        const outS = outermost(sEl, sel);
        const outE = outermost(eEl, sel);
        const innerE = innermost(eEl, sel);
        let lo = outS ? idxOf.get(outS) : undefined;
        let hi = innerE ? idxOf.get(innerE) : undefined;
        if (lo === undefined)
            for (let i = 0; i < chunkEls.length && lo === undefined; i++)
                if (endsAfterStart(chunkEls[i]!, range)) lo = i;
        if (hi === undefined)
            for (let i = chunkEls.length - 1; i >= 0 && hi === undefined; i--)
                if (startsBeforeEnd(chunkEls[i]!, range)) hi = i;
        if (lo === undefined || hi === undefined || lo > hi) return [];
        const innerStartEl = innermost(sEl, sel);
        const innerStartIdx = innerStartEl
            ? idxOf.get(innerStartEl)
            : undefined;
        if (innerStartIdx !== undefined && innerStartIdx > hi)
            hi = innerStartIdx;
        if (outE)
            for (const d of outE.querySelectorAll(sel)) {
                const di = idxOf.get(d);
                if (di !== undefined && di > hi && startsBeforeEnd(d, range))
                    hi = di;
            }
        const dead = new Set<Element>();
        if (outS)
            for (const d of outS.querySelectorAll(sel))
                if (!endsAfterStart(d, range)) dead.add(d);
        const keys: string[] = [];
        for (let i = lo; i <= hi; i++)
            if (!dead.has(chunkEls[i]!)) {
                const k = spec.keyOf(chunkEls[i]!);
                if (k != null) keys.push(k);
            }
        return keys;
    };
}
