// pdfseqpos —— GET /reader 顶层 seqpos 字段的消费面。
// 服务端 seqpos.py 产出 {"seq": {"o": Pos, "t": Pos}}（o=en 原文、
// t=zh 译文）——zh 侧 TLXC 标直读、en 侧文本匹配，行级精度。本模块
// 收敛三件消费：
//   seqPos     seq+侧 → Pos——sent-align 点击/跳转的 seq 精度源
//   seqPairs   seqpos → AlignmentPair[]——并进 mapper 的 landmarks
//              输入（createPositionMapper 内部独立排序，非单调值
//              诚实成局部结——浮动体出序不伪装）；滚动同步同吃
//   nearestSeq 点击位 Pos → 最近 seq——PDF 点击点不在 TLXC span 上
//              时的兜底锚定（en.pdf 无标记恒走这里）

import type { AlignmentPair, Pos } from "./alignment";

/** GET /reader ``seqpos`` 顶层字段形状（与 api/types ReaderInfo.seqpos 同构） */
export type SeqPosMap = Record<string, { o?: Pos; t?: Pos }>;

type SaSide = "en" | "zh";

const sideKey = (side: SaSide): "o" | "t" => (side === "en" ? "o" : "t");

/** seq + 侧 → Pos；无该 seq/该侧缺位 → null */
export function seqPos(
    map: SeqPosMap,
    seq: number,
    side: SaSide,
): Pos | null {
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

/** Pos → 最近 seq。同页比分位差（恒 <1 优先）；跨页按页差 + 到页沿
    距离粗排——点击落在无 seq 覆盖区（页眉/参考文献间缝）时给的是
    诚实最近邻，不是精确命中（调用方按「兜底」语义消费）。 */
export function nearestSeq(
    map: SeqPosMap,
    side: SaSide,
    pos: Pos,
): number | null {
    const k = sideKey(side);
    let best: number | null = null;
    let bestScore = Number.POSITIVE_INFINITY;
    for (const [key, v] of Object.entries(map)) {
        const p = v[k];
        if (!p) continue;
        const dpage = Math.abs(p.page - pos.page);
        const score =
            dpage === 0
                ? Math.abs(p.fraction - pos.fraction)
                : dpage + (p.page < pos.page ? 1 - p.fraction : p.fraction);
        if (score < bestScore) {
            bestScore = score;
            best = Number(key);
        }
    }
    return best;
}
