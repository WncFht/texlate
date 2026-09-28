// pdfseqpos —— GET /reader 顶层 seqpos 字段的消费面。
// 服务端 seqpos.py 产出 {"seq": {"o": Pos, "t": Pos}}（o=en 原文、
// t=zh 译文）——zh 侧 TLXC 标直读、en 侧文本匹配，行级精度；Pos 带
// x（页宽分位，锚行左缘）时阅读序键升 (page,col,fraction)。本模块
// 收敛三件消费：
//   seqPos        seq+侧 → Pos——sent-align 点击/跳转的 seq 精度源
//   seqPairs      seqpos → AlignmentPair[]——并进 mapper 的 landmarks
//                 输入（createPositionMapper 内部独立排序，非单调值
//                 诚实成局部结——浮动体出序不伪装）；滚动同步同吃
//   seqLands      同侧阅读序地标表——picker floor 序列与 sentalign
//                 块内插值 S' 发现面共用同一份排序
//   containingSeq 点击位 Pos → 含点 seq——PDF 点击点不在 TLXC span
//                 上时的兜底锚定（en.pdf 无标记恒走这里）

import { colOf, pageHasCol, type AlignmentPair, type Pos } from "./alignment";

/** GET /reader ``seqpos`` 顶层字段形状（与 api/types ReaderInfo.seqpos 同构） */
export type SeqPosMap = Record<string, { o?: Pos; t?: Pos }>;

type SaSide = "en" | "zh";

const sideKey = (side: SaSide): "o" | "t" => (side === "en" ? "o" : "t");

/** 页线性位（page+fraction，seqpos.py 同款）——距离闸/插值口径 */
const linOf = (p: Pos): number => p.page + p.fraction;

/** 阅读序键比较：(page, col, fraction) 字典序 */
const keyCmp = (a: Pos, b: Pos): number =>
    a.page - b.page || colOf(a) - colOf(b) || a.fraction - b.fraction;

/** (page,fraction) 投影比较——pos 无 x 时的降级序（栏不可判） */
const projCmp = (a: Pos, b: Pos): number =>
    a.page - b.page || a.fraction - b.fraction;

/** 同行判定非对称窗：锚 fraction=行顶，点击落行内即锚下 ~半行高 →
    d∈[-0.004,+0.017]；点击低于下行顶（d<0）= 异行 */
export const ROW_UP = 0.004;
export const ROW_DOWN = 0.017;
/** 行幅面 x 容差（est_w 估宽噪声 + 点击未必贴字面缘） */
export const ROW_EPSX = 0.025;

/** seq + 侧 → Pos；无该 seq/该侧缺位 → null */
export function seqPos(map: SeqPosMap, seq: number, side: SaSide): Pos | null {
    return map[String(seq)]?.[sideKey(side)] ?? null;
}

/** seqpos → mapper  landmarks 输入（id="s{seq}"——与 dual 自带 pairs
    撞名隔离；两侧 Pos 齐全才出对） */
export function seqPairs(map: SeqPosMap): AlignmentPair[] {
    const out: AlignmentPair[] = [];
    for (const [k, v] of Object.entries(map)) {
        if (v.o && v.t)
            out.push({ id: `s${k}`, original: v.o, translated: v.t });
    }
    return out;
}

/** 同侧地标表：带 Pos 的 seq 按阅读序键 (page,col,fraction) 升序。 */
export function seqLands(
    map: SeqPosMap,
    side: SaSide,
): { seq: number; pos: Pos }[] {
    const k = sideKey(side);
    const out: { seq: number; pos: Pos }[] = [];
    for (const [key, v] of Object.entries(map)) {
        const p = v[k];
        if (p) out.push({ seq: Number(key), pos: p });
    }
    out.sort((a, b) => keyCmp(a.pos, b.pos));
    return out;
}

/** Pos → 含点 seq。先同行幅面 snap（点击 x 落在某锚行 [x0,x1] 内
    且同行 → 直命——宽行/TOC 的右半点击不被栏判错划）；否则阅读序
    地标表上取 floor（最后一个 ≤ pos 的锚——seq 锚记块首，点击落在
    块内即该块所辖）；pos 带 x 走 (page,col,fraction) 全键，无 x 退
    化纯 (page,fraction) 投影 floor（栏不可判时仍比最近邻诚实——最
    近邻会把右栏点击吸到左栏末块）。
    距离闸：floor 与 pos 线性距（page+fraction）>1.2 页 → null；
    pos 早于全部地标且与首锚差 >1 页 → null——稀疏 seqpos（老任务
    无 TLXC 标走文本匹配、覆盖参差）下宁 null 让调用方落比例旧路，
    不把点击吸到数页外的孤锚。 */
export function containingSeq(
    map: SeqPosMap,
    side: SaSide,
    pos: Pos,
): number | null {
    const lands = seqLands(map, side);
    const first = lands[0];
    if (!first) return null;

    if (pos.x != null) {
        // 同行幅面 snap：点击 x 落在某锚行 [x0,x1] 内且行带命中 → 直命。
        // 宽行（TOC/通栏标题/表头多格同行）点击 x 进右半时 raw-x 栏判会
        // 把行错划 col1，floor 进而吸到 col0 末锚（阅读序上合法但离点击
        // 行半页远）。多候选 = 同行多格（表头 cell）→ 取 x0≤点击的最右
        // 者（点击所在格段），全在右侧则取最近 x0，再按 d 打破。
        let rowSeq = -1;
        let rowKey: [number, number, number] | null = null;
        for (const l of lands) {
            const p = l.pos;
            if (p.page !== pos.page || p.x == null || p.x1 == null) continue;
            const d = pos.fraction - p.fraction;
            if (d < -ROW_UP || d > ROW_DOWN) continue;
            if (pos.x < p.x - ROW_EPSX || pos.x > p.x1 + ROW_EPSX) continue;
            const key: [number, number, number] =
                p.x <= pos.x ? [0, -p.x, Math.abs(d)] : [1, p.x, Math.abs(d)];
            if (
                !rowKey ||
                key[0] < rowKey[0] ||
                (key[0] === rowKey[0] &&
                    (key[1] < rowKey[1] ||
                        (key[1] === rowKey[1] && key[2] < rowKey[2])))
            ) {
                rowKey = key;
                rowSeq = l.seq;
            }
        }
        if (rowSeq >= 0) return rowSeq;
        // 本页无右栏地标（单栏页/右栏无锚/旧数据全 col0）→ 栏位降级，
        // 防右半点击被 col1 floor 吸到页底锚（对抗复核 N1 实证）
        const eff =
            colOf(pos) === 1 && !pageHasCol(lands, pos.page)
                ? { ...pos, x: 0 }
                : pos;
        // 全键 floor——栏序参与比较
        if (keyCmp(eff, first.pos) < 0)
            return linOf(first.pos) - linOf(eff) <= 1 ? first.seq : null;
        let lo = 0;
        let hi = lands.length - 1;
        let best = -1;
        while (lo <= hi) {
            const mid = (lo + hi) >> 1;
            if (keyCmp(lands[mid]!.pos, eff) <= 0) {
                best = mid;
                lo = mid + 1;
            } else hi = mid - 1;
        }
        if (best < 0) return null; // 防御：早于全部的上面已截
        // 同键并列（同页同栏同行首多 seq 锚，二分取到组内最末）→ 按 x
        // 取点击所辖格段：x0≤点击的最右者，全右则最小 x0——与 row-snap
        // 同规，否则点击落在前段时错吸到同排后锚（bd 普查实证）。
        {
            const bk = lands[best]!.pos;
            let g0 = best;
            while (g0 > 0 && keyCmp(lands[g0 - 1]!.pos, bk) === 0) g0--;
            let pk: [number, number] | null = null;
            for (let i = g0; i <= best; i++) {
                const px = lands[i]!.pos.x;
                if (px == null) continue;
                const k: [number, number] = px <= pos.x ? [0, -px] : [1, px];
                if (!pk || k[0] < pk[0] || (k[0] === pk[0] && k[1] < pk[1])) {
                    pk = k;
                    best = i;
                }
            }
        }
        return Math.abs(linOf(lands[best]!.pos) - linOf(eff)) <= 1.2
            ? lands[best]!.seq
            : null;
    }

    // 无 x 降级：投影 floor = (page,fraction) 最大的不超者；
    // 同步记投影最小锚给「早于全部」闸用
    let best = -1;
    let loIdx = 0;
    for (let i = 0; i < lands.length; i++) {
        const p = lands[i]!.pos;
        if (projCmp(p, lands[loIdx]!.pos) < 0) loIdx = i;
        if (projCmp(p, pos) > 0) continue;
        if (best < 0 || projCmp(p, lands[best]!.pos) >= 0) best = i;
    }
    if (best < 0) {
        const f = lands[loIdx]!.pos;
        return linOf(f) - linOf(pos) <= 1 ? lands[loIdx]!.seq : null;
    }
    return Math.abs(linOf(lands[best]!.pos) - linOf(pos)) <= 1.2
        ? lands[best]!.seq
        : null;
}
