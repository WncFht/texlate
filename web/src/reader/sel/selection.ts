// selection —— 原生 Selection 工具层（sel-system Wave B）。
// 规格锚点（实现文档「选区语义」节）：
//   - 复制文本源 = range.toString() / cloneContents().textContent（不折叠
//     换行、不丢结构）；不用 sel.toString()（折叠换行，少 4 字符实证）。
//   - 反向拖拽判定 = compareDocumentPosition（anchorAfterFocus——双引擎
//     一致；sel.direction 字符串亦可但 node 级判定更稳）。
//   - 跨 pane 选区：对两侧 bodyEl 各跑一遍 coveredChunks 取并集。
//   - 坍缩/单 range 取值等零碎收口也在这里，供 keymap 层栈 sel 层与
//     hitctx/commands 共用。

import { makeChunkResolver } from "./coveredChunks";

type SelLike = Pick<Selection, "rangeCount" | "getRangeAt"> | null;

/** 复制口径文本：逐 range cloneContents().textContent（多 range 拼接）。 */
export function selectionCopyText(
    rangeOrSel: Range | SelLike,
): string {
    if (!rangeOrSel) return "";
    if ("getRangeAt" in rangeOrSel) {
        let out = "";
        for (let i = 0; i < rangeOrSel.rangeCount; i++)
            out += rangeOrSel.getRangeAt(i).cloneContents().textContent ?? "";
        return out;
    }
    return rangeOrSel.cloneContents().textContent ?? "";
}

/** range.toString() 口径（哨兵 <i class="sb"> 零宽不进文本） */
export function selectionText(sel: SelLike): string {
    if (!sel || sel.rangeCount === 0) return "";
    let out = "";
    for (let i = 0; i < sel.rangeCount; i++)
        out += sel.getRangeAt(i).toString();
    return out;
}

/**
 * 反向拖拽判定：anchor 在 focus 之后（文档序）即反向。
 * compareDocumentPosition 位掩码 DOCUMENT_POSITION_PRECEDING=2——
 * focusNode 在 anchorNode 之前 → 反向。容器端点退 Range.comparePoint
 * 路径（anchor/focus 两点构 range 不坍缩即正向）。
 */
export function anchorAfterFocus(
    sel: Pick<
        Selection,
        "anchorNode" | "anchorOffset" | "focusNode" | "focusOffset"
    >,
): boolean {
    const { anchorNode, anchorOffset, focusNode, focusOffset } = sel;
    if (!anchorNode || !focusNode) return false;
    if (anchorNode === focusNode) return anchorOffset > focusOffset;
    const pos = anchorNode.compareDocumentPosition(focusNode);
    if (pos & Node.DOCUMENT_POSITION_PRECEDING) return true;
    if (pos & Node.DOCUMENT_POSITION_FOLLOWING) return false;
    // CONTAINS/CONTAINED_BY：容器端点——构 focus→anchor range 测坍缩
    const doc = anchorNode.ownerDocument!;
    const r = doc.createRange();
    try {
        r.setStart(focusNode, focusOffset);
        r.setEnd(anchorNode, anchorOffset);
        return r.collapsed; // 坍缩=锚在焦前 → 反向
    } catch {
        return false;
    } finally {
        r.detach();
    }
}

/**
 * 跨 pane 双侧各跑：对 bodies 里每个 bodyEl 建 resolver 跑同一 range，
 * 键并集（文档序按 body 传入序）。返回 null 表示无选区。
 */
export function coveredChunksAcross(
    sel: SelLike,
    bodies: readonly Element[],
): string[] {
    if (!sel || sel.rangeCount === 0) return [];
    const range = sel.getRangeAt(0);
    const seen = new Set<string>();
    const out: string[] = [];
    for (const b of bodies)
        for (const k of makeChunkResolver(b)(range))
            if (!seen.has(k)) {
                seen.add(k);
                out.push(k);
            }
    return out;
}

/** 塌缩当前选区（Esc 层栈 sel 层的 close 动作） */
export function collapseSelection(doc?: Document | null): void {
    const d = doc ?? (typeof document !== "undefined" ? document : null);
    const sel = d?.getSelection?.() ?? d?.defaultView?.getSelection?.() ?? null;
    sel?.removeAllRanges();
}

/** 非坍缩判定（层栈 sel 层 isOpen / keymap hasSelection 缺省面） */
export function hasLiveSelection(doc?: Document | null): boolean {
    const d = doc ?? (typeof document !== "undefined" ? document : null);
    const sel = d?.getSelection?.() ?? d?.defaultView?.getSelection?.() ?? null;
    return !!sel && !sel.isCollapsed && sel.toString().length > 0;
}
