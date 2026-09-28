// host/derives —— info/dual → 派生 memos：seqpos 映射、chunk↔seq 索引、
// 块文本长、页数、位置映射器、引用索引。sync/nav/sentalign/cite 各簇
// 共用的单一事实源（须随 info/dual 晚到自动重算）。

import { createMemo } from "solid-js";
import type { DualJson, ReaderInfo } from "../../api/client";
import { createPositionMapper, type Alignment } from "../logic/alignment";
import { seqPairs } from "../pdf/pdfseqpos";
import { buildCiteIndex } from "../cite/citations";

export function createDerives(deps: {
    info(): ReaderInfo | null;
    dual(): DualJson | null | undefined;
}) {
    const { info, dual } = deps;

    /** GET /reader 顶层 seqpos——seq 级双侧 Pos（服务端懒算缓存）。
        mapper landmarks 合流与 sent-align seq 臂共用此源 */
    const seqposMap = createMemo(() => info()?.seqpos ?? {});

    /** chunk_id→seq 映射（dom 键）+ seq 串直解（html 键）双登记 */
    const seqOf = createMemo(() => {
        const m = new Map<string, number>();
        for (const c of dual()?.chunks ?? []) {
            if (c.chunk_id) m.set(c.chunk_id, c.seq);
            m.set(String(c.seq), c.seq);
        }
        return m;
    });

    /** seq→双侧块文本长（ph 剥净）——sentalign interpDst 的 dst
        幅面夹取原料（浮动撑大的块区间 ≠ 文本幅面） */
    const seqLenOf = createMemo(() => {
        const m = new Map<number, { en: number; zh: number }>();
        for (const c of dual()?.chunks ?? []) {
            if (typeof c.seq !== "number") continue;
            const strip = (s?: string) =>
                (s ?? "").replace(/\[\[[A-Z]+_\d+\]\]/g, "").length;
            m.set(c.seq, { en: strip(c.en), zh: strip(c.zh) });
        }
        return m;
    });

    const pageCounts = createMemo(() => {
        const i = info();
        const d = dual();
        if (!i) return { original: 1, translated: 1 };
        if (i.view === "html") {
            const n = Math.max(d?.chunks?.length ?? 1, 1);
            return { original: n, translated: n };
        }
        // dom 与 pdf 同路：dom 的 "pages" = 锚定 chunk 数（worker 写进
        // documents.*.pages），不进 dual.chunks 分支
        return {
            original: i.documents.original?.pages ?? 1,
            translated: i.documents.translated?.pages ?? 1,
        };
    });

    const mapper = createMemo(() => {
        const al = dual()?.alignment ?? info()?.alignment;
        const sp = seqPairs(seqposMap());
        if (!sp.length) return createPositionMapper(al, pageCounts());
        // seq pairs 合流 landmarks——kind:"pages"（或无 alignment）需
        // 翻牌才生效（createPositionMapper 的 useLandmarks 闸）；旧
        // pairs 保留，mapper 内部按两侧各自排序（浮动体出序诚实成结）
        const merged: Alignment = {
            kind: al?.kind === "pages" || !al ? "landmarks" : al.kind,
            heights: al?.heights,
            regions: al?.regions,
            pairs: [...(al?.pairs ?? []), ...sp],
        };
        return createPositionMapper(merged, pageCounts());
    });

    /** dual.json ph → bibkey 索引；无 ph 时 size=0（卡片走 dest 懒抽取） */
    const citeIndex = createMemo(() => buildCiteIndex(dual()));

    return { seqposMap, seqOf, seqLenOf, pageCounts, mapper, citeIndex };
}
