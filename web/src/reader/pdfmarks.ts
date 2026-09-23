// pdfmarks —— zh.pdf seq 锚消费面（docs/dev/pdf-seq-anchors-impl-2026-09-23.md §3）。
// 后端 reconstruct 在 [[CHUNK_n]] 引用点注 \special{pdf:code /TLXC
// <</MCID 50000+seq>> BDC}…EMC；pdf.js includeMarkedContent 透出
// beginMarkedContentProps{tag:"TLXC<n>", id:"p<obj>_mc<50000+seq>"}——
// TextLayer 对 BDC+MCID 锚自动包 span.markedContent 并把 id 写进 DOM。
// 本模块收敛全部 pdf.js 私有面（id 尾解码 / markedContent 锚 spec /
// getTextContent item 层抽取）——升级 pdfjs 时单点排查。
//
// 双径分工：seqmap（item 层，seq→page 主径）走 getTextContent——DOM
//   无关、懒渲染页也可查；span 径（sel→seq / seq→rects 辅径）走
//   querySelectorAll——已渲染页即时可得。文档自有 MCID（≤~640 实证）
//   与 50000 基座无碰撞；他档 ≥50000 撞名仅影响 id 径，seqmap 层
//   还有 tag 前缀校验兜底。

export const MCID_BASE = 50000;

/** markedContent 锚选择器（BDC+MCID 才有 id——BMC/无 MCID 的 BDC 缺席） */
export const MARKED_SEL = "span.markedContent[id]";

/** TLXC item.tag 前缀（pdf.js 的 tag 字段=源 tag 名+内部计数拼接） */
const TLXC_TAG_RX = /^TLXC/;

const MC_TAIL_RX = /_mc(\d+)$/;

const mcidOf = (id: string): number | null => {
    const m = MC_TAIL_RX.exec(id);
    if (!m) return null;
    const n = Number(m[1]);
    return n >= MCID_BASE ? n - MCID_BASE : null;
};

/** span.markedContent → seq（id 尾 _mc<N> 且 N≥50000+seq；否则 null） */
export function seqOfMarkedSpan(el: Element | null): number | null {
    return mcidOf(el?.getAttribute?.("id") ?? "");
}

/** getTextContent item → seq：beginMarkedContentProps 且 tag 为 TLXC 族
    （id 尾解码同径——tag 校验挡掉同 id 撞名的文档自有锚） */
export function seqOfTextItem(item: unknown): number | null {
    const it = item as { id?: unknown; tag?: unknown; type?: unknown };
    if (typeof it?.id !== "string") return null;
    if (typeof it?.tag === "string" && !TLXC_TAG_RX.test(it.tag)) return null;
    return mcidOf(it.id);
}

/** markedContent 锚 spec——coveredChunks.makeChunkResolver 的 pdf 侧参数：
    selector 换锚族 + keyOf 出数值 seq 串（与 [data-chunk] 默认 spec 同契约） */
export const MARKED_SPEC = {
    selector: MARKED_SEL,
    keyOf(el: Element): string | null {
        const s = seqOfMarkedSpan(el);
        return s == null ? null : String(s);
    },
};
