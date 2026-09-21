// 位置模型与映射 —— docs/research/product/web-layer.md §5.3/§5.4。
// 坐标线性化：x = Σheights[0..page-1] + fraction * h[page]，pairs 是服务端
// 已排序的单调链，二分插值；regions（图浮动）优先于 pairs；无 pairs 退化为
// kind:"pages" 同页码映射。
// 线形载荷（Pos/Alignment 族）是 API 契约——单一事实源在 api/types.ts，
// 本文件只做消费（createPositionMapper）与门面再导出（消费方沿旧路径拿）。

import type {
    Alignment,
    AlignmentPair,
    AlignmentRegion,
    Pos,
    RegionCoord,
} from "../api/types";

export type {
    Alignment,
    AlignmentPair,
    AlignmentRegion,
    Pos,
    RegionCoord,
};

export type DocId = "original" | "translated";
export type Side = DocId;

export type PosMap = (pos: Pos, from: Side) => Pos;

/** 对侧名——ReaderView 的 target/updateDrift/jumpBack 与 mapper 共用 */
export const other = (s: Side): Side =>
    s === "original" ? "translated" : "original";
const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), hi);

interface SideGeom {
    pages: number;
    h: (page: number) => number; // 1-based
    off: number[]; // off[i] = Σh[0..i-1]，长度 pages+1
}

function geom(side: Side, heights: Alignment["heights"], pages: number): SideGeom {
    const hs = heights?.[side];
    const h = (p: number) => hs?.[p - 1] ?? 1;
    const off = new Array<number>(pages + 1).fill(0);
    for (let i = 1; i <= pages; i++) off[i] = off[i - 1] + h(i);
    return { pages, h, off };
}

function toLinear(g: SideGeom, pos: Pos): number {
    const page = clamp(Math.round(pos.page), 1, g.pages);
    return g.off[page - 1] + pos.fraction * g.h(page);
}

function fromLinear(g: SideGeom, x: number): Pos {
    const total = g.off[g.pages];
    if (x <= 0) return { page: 1, fraction: 0 };
    if (x >= total) return { page: g.pages, fraction: 1 };
    // 二分：最大 i 使 off[i] <= x，i ∈ [0, pages-1]
    let lo = 0,
        hi = g.pages;
    while (lo + 1 < hi) {
        const mid = (lo + hi) >> 1;
        if (g.off[mid] <= x) lo = mid;
        else hi = mid;
    }
    const hh = g.h(lo + 1);
    return { page: lo + 1, fraction: hh > 0 ? clamp((x - g.off[lo]) / hh, 0, 1) : 0 };
}

/**
 * 构造双栏位置映射。pages = 两侧页数（reader info / dual.json documents）。
 * 返回的映射保留 viewport 字段。
 */
export function createPositionMapper(
    alignment: Alignment | undefined,
    pages: { original: number; translated: number },
): PosMap {
    const geoms: Record<Side, SideGeom> = {
        original: geom("original", alignment?.heights, Math.max(1, pages.original)),
        translated: geom("translated", alignment?.heights, Math.max(1, pages.translated)),
    };

    // regions → 源侧线性区间表（升序）
    const regions = (alignment?.regions ?? [])
        .map((r) => {
            const so = toLinear(geoms.original, { page: r.original.page, fraction: r.original.start });
            const eo = toLinear(geoms.original, { page: r.original.page, fraction: r.original.end });
            const st = toLinear(geoms.translated, { page: r.translated.page, fraction: r.translated.start });
            const et = toLinear(geoms.translated, { page: r.translated.page, fraction: r.translated.end });
            // 两侧区间同口径 min/max 归一——start>end 的反向 region 在
            // 命中插值时 y 会倒序映射（ds>de 折返），先归一保单调
            return {
                o: [Math.min(so, eo), Math.max(so, eo)] as const,
                t: [Math.min(st, et), Math.max(st, et)] as const,
            };
        })
        .sort((a, b) => a.o[0] - b.o[0]);

    // pairs → 两个方向的单调折线
    const rawPairs = alignment?.pairs ?? [];
    const byOrig = [...rawPairs].sort(
        (a, b) => toLinear(geoms.original, a.original) - toLinear(geoms.original, b.original),
    );
    const byTrans = [...rawPairs].sort(
        (a, b) => toLinear(geoms.translated, a.translated) - toLinear(geoms.translated, b.translated),
    );

    const xsO = byOrig.map((p) => toLinear(geoms.original, p.original));
    const ysO = byOrig.map((p) => toLinear(geoms.translated, p.translated));
    const xsT = byTrans.map((p) => toLinear(geoms.translated, p.translated));
    const ysT = byTrans.map((p) => toLinear(geoms.original, p.original));

    const interp = (x: number, xs: number[], ys: number[]): number => {
        if (xs.length === 0) return x;
        if (x <= xs[0]) return ys[0];
        if (x >= xs[xs.length - 1]) return ys[ys.length - 1];
        let lo = 0,
            hi = xs.length - 1;
        while (lo + 1 < hi) {
            const mid = (lo + hi) >> 1;
            if (xs[mid] <= x) lo = mid;
            else hi = mid;
        }
        const span = xs[lo + 1] - xs[lo];
        const t = span > 0 ? (x - xs[lo]) / span : 0;
        return ys[lo] + t * (ys[lo + 1] - ys[lo]);
    };

    const useLandmarks = alignment?.kind !== "pages" && rawPairs.length > 0;

    return (pos, from) => {
        const to = other(from);
        const src = geoms[from];
        const dst = geoms[to];
        const x = toLinear(src, pos);

        let y: number;
        if (useLandmarks) {
            // regions 优先：图浮动块内部按归一化位置映射
            let hit: (typeof regions)[number] | undefined;
            for (const r of regions) {
                const [s, e] = from === "original" ? r.o : r.t;
                if (x >= s && x <= e) {
                    hit = r;
                    break;
                }
            }
            if (hit) {
                const [s, e] = from === "original" ? hit.o : hit.t;
                const [ds, de] = from === "original" ? hit.t : hit.o;
                const t = e > s ? (x - s) / (e - s) : 0;
                y = ds + t * (de - ds);
            } else {
                const xs = from === "original" ? xsO : xsT;
                const ys = from === "original" ? ysO : ysT;
                y = interp(x, xs, ys);
            }
            const out = fromLinear(dst, y);
            return { ...out, viewport: pos.viewport };
        }
        // kind:"pages" 退化：同页码 + 同 fraction，目标页数不足则截断
        return {
            page: clamp(Math.round(pos.page), 1, dst.pages),
            fraction: pos.fraction,
            viewport: pos.viewport,
        };
    };
}
