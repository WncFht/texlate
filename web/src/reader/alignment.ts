// 位置模型与映射 —— docs/research/product/2026-09-15-web-layer.md §5.3/§5.4。
// 坐标线性化：x = Σheights[0..page-1] + share * h[page]；pairs 带 x 时
// share=(col+fraction)/2——阅读序键 (page,col,fraction) 与坐标同构
// （xs 单调、插值不穿栏）；全无 x 退 fraction（旧数据逐位同旧）。
// pairs 是服务端已排序的单调链，二分插值；regions（图浮动）优先于
// pairs；无 pairs 退化为 kind:"pages" 同页码映射。
// 线形载荷（Pos/Alignment 族）是 API 契约——单一事实源在 api/types.ts，
// 本文件只做消费（createPositionMapper）与门面再导出（消费方沿旧路径拿）。

import type {
    Alignment,
    AlignmentPair,
    AlignmentRegion,
    Pos,
    RegionCoord,
} from "../api/types";

export type { Alignment, AlignmentPair, AlignmentRegion, Pos, RegionCoord };

export type DocId = "original" | "translated";
export type Side = DocId;

export type PosMap = (pos: Pos, from: Side) => Pos;

/** 对侧名——ReaderView 的 target/updateDrift/jumpBack 与 mapper 共用 */
export const other = (s: Side): Side =>
    s === "original" ? "translated" : "original";
const clamp = (v: number, lo: number, hi: number) =>
    Math.min(Math.max(v, lo), hi);

/** 双栏分界：x（页宽分位）≥ 此值 → 右栏。seqpos keyCmp、行带收窄、
    栏降级守卫共用口径——凭感觉改这值会让四处判定互相错位。 */
export const COL_X_SPLIT = 0.45;

/** 栏判定：x>=COL_X_SPLIT → 右栏；x 缺席（旧数据/滚动位无 x）→ 0 */
export const colOf = (p: Pos): number =>
    p.x != null && p.x >= COL_X_SPLIT ? 1 : 0;

/** 页内阅读序份额 (col+frac)/2——左栏压进 [0,.5)、右栏 [.5,1)，
    阅读序与坐标同构（toLinear share / sentalign roLin 同式） */
export const colShare = (p: Pos): number => (colOf(p) + p.fraction) / 2;

/** 「本页存在 col 栏地标」守卫——右半点击的栏降级判定共用
    （pdfseqpos containingSeq / sentalign fracInBlock）：本页无右栏锚
    时右半点击退 col0，防被 col1 floor 吸到页底锚。 */
export const pageHasCol = (
    lands: readonly { pos: Pos }[],
    page: number,
    col = 1,
): boolean => lands.some((l) => l.pos.page === page && colOf(l.pos) === col);

interface SideGeom {
    pages: number;
    h: (page: number) => number; // 1-based
    off: number[]; // off[i] = Σh[0..i-1]，长度 pages+1
}

function geom(
    side: Side,
    heights: Alignment["heights"],
    pages: number,
): SideGeom {
    const hs = heights?.[side];
    const h = (p: number) => hs?.[p - 1] ?? 1;
    const off = new Array<number>(pages + 1).fill(0);
    for (let i = 1; i <= pages; i++) off[i] = off[i - 1] + h(i);
    return { pages, h, off };
}

function toLinear(g: SideGeom, pos: Pos, colAware: boolean): number {
    const page = clamp(Math.round(pos.page), 1, g.pages);
    // col-aware：页内份额走 colShare 折栏（阅读序与坐标同构）；
    // 否则原 fraction 份额
    const share = colAware ? colShare(pos) : pos.fraction;
    return g.off[page - 1] + share * g.h(page);
}

function fromLinear(g: SideGeom, x: number, colAware: boolean): Pos {
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
    const rem = hh > 0 ? clamp((x - g.off[lo]) / hh, 0, 1) : 0;
    // 栏半页反解：≤0.5 属左栏（0.5 取页底 frac=1，防底→顶跳变），
    // >0.5 右栏；x 不回写——消费面只吃 page+fraction
    const fraction = colAware ? (rem <= 0.5 ? rem * 2 : (rem - 0.5) * 2) : rem;
    return { page: lo + 1, fraction };
}

/** 离群锚剔除：needle 误锚把分段插值拽出 V 形（实测单锚偏 ±20 页）。
    双向各查一遍——锚的 dst 线性位与前后邻插值期望差 >2 个 dst 均页高
    即剔（src 侧错位只在对侧序里现形）；端点无两邻不查。<3 锚无可剔。 */
function dropOutliers(
    pairs: AlignmentPair[],
    geoms: Record<Side, SideGeom>,
    colAware: boolean,
): AlignmentPair[] {
    if (pairs.length < 3) return pairs;
    const drop = new Set<number>();
    for (const [src, dst] of [
        ["original", "translated"],
        ["translated", "original"],
    ] as const) {
        const unit =
            geoms[dst].off[geoms[dst].pages] / Math.max(geoms[dst].pages, 1);
        const order = pairs
            .map((_, i) => i)
            .sort(
                (a, b) =>
                    toLinear(geoms[src], pairs[a]![src], colAware) -
                    toLinear(geoms[src], pairs[b]![src], colAware),
            );
        const xs = order.map((i) =>
            toLinear(geoms[src], pairs[i]![src], colAware),
        );
        const ys = order.map((i) =>
            toLinear(geoms[dst], pairs[i]![dst], colAware),
        );
        for (let k = 1; k + 1 < order.length; k++) {
            const span = xs[k + 1]! - xs[k - 1]!;
            if (span <= 0) continue;
            const exp =
                ys[k - 1]! +
                (ys[k + 1]! - ys[k - 1]!) * ((xs[k]! - xs[k - 1]!) / span);
            if (Math.abs(ys[k]! - exp) > 2 * unit) drop.add(order[k]!);
        }
    }
    return drop.size ? pairs.filter((_, i) => !drop.has(i)) : pairs;
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
        original: geom(
            "original",
            alignment?.heights,
            Math.max(1, pages.original),
        ),
        translated: geom(
            "translated",
            alignment?.heights,
            Math.max(1, pages.translated),
        ),
    };

    // pairs 任一侧带 x → 双栏阅读序线性化（toLinear 的 share 口径）；
    // 全无 x 的旧数据保持原 page+frac——结果与旧版逐位一致
    const rawPairs = alignment?.pairs ?? [];
    const colAware = rawPairs.some(
        (p) => p.original.x != null || p.translated.x != null,
    );
    // 建 interp 前先剔离群锚——needle 假锚会把同步拽出 V 形
    const pairs = dropOutliers(rawPairs, geoms, colAware);

    // regions → 源侧线性区间表（升序）
    const regions = (alignment?.regions ?? [])
        .map((r) => {
            const so = toLinear(
                geoms.original,
                { page: r.original.page, fraction: r.original.start },
                colAware,
            );
            const eo = toLinear(
                geoms.original,
                { page: r.original.page, fraction: r.original.end },
                colAware,
            );
            const st = toLinear(
                geoms.translated,
                { page: r.translated.page, fraction: r.translated.start },
                colAware,
            );
            const et = toLinear(
                geoms.translated,
                { page: r.translated.page, fraction: r.translated.end },
                colAware,
            );
            // 两侧区间同口径 min/max 归一——start>end 的反向 region 在
            // 命中插值时 y 会倒序映射（ds>de 折返），先归一保单调
            return {
                o: [Math.min(so, eo), Math.max(so, eo)] as const,
                t: [Math.min(st, et), Math.max(st, et)] as const,
            };
        })
        .sort((a, b) => a.o[0] - b.o[0]);

    // pairs → 两个方向的单调折线（线性化已含 col——按值排序即
    // 阅读序 (page,col,fraction) 排序）
    const byOrig = [...pairs].sort(
        (a, b) =>
            toLinear(geoms.original, a.original, colAware) -
            toLinear(geoms.original, b.original, colAware),
    );
    const byTrans = [...pairs].sort(
        (a, b) =>
            toLinear(geoms.translated, a.translated, colAware) -
            toLinear(geoms.translated, b.translated, colAware),
    );

    const xsO = byOrig.map((p) =>
        toLinear(geoms.original, p.original, colAware),
    );
    const ysO = byOrig.map((p) =>
        toLinear(geoms.translated, p.translated, colAware),
    );
    const xsT = byTrans.map((p) =>
        toLinear(geoms.translated, p.translated, colAware),
    );
    const ysT = byTrans.map((p) =>
        toLinear(geoms.original, p.original, colAware),
    );

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

    const useLandmarks = alignment?.kind !== "pages" && pairs.length > 0;

    return (pos, from) => {
        const to = other(from);
        const src = geoms[from];
        const dst = geoms[to];
        const x = toLinear(src, pos, colAware);

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
            const out = fromLinear(dst, y, colAware);
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
