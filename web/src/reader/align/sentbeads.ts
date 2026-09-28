// sentbeads —— 贪心对位叶（w4 自 sentalign.ts 拆出；全 lane 规格注释见
// sentalign.ts 头）：align-monotonic 贪心对位移植——rho=zh/en 逐 chunk
// 自适应，|log(zl/(el·rho))| 严格缩小才扩边，MAXG=4/侧，残句并末 bead。
// 零内部依赖纯叶：length 口径件 sentLen 在 sentseg.ts（属切句簇附属，
// 本叶不需要）。
//
// bead 协议：data-bead="{chunk}.{b}"（b=块内 bead 序位）——交互单位是 bead
// 不是句（句数不等 7.53% chunk 天然降级组高亮，绝不伪装 1:1）。
// 契约：bead → 元素集合——任何消费方一律 querySelectorAll，禁单元素假设。

/** bead = m:n 句组（半开句序位区间） */
export interface Bead {
    en0: number;
    en1: number;
    zh0: number;
    zh1: number;
}

const MAXG = 4; // bead 单侧最大句数（实测 87.6% 1:1）

const cost = (el: number, zl: number, rho: number): number =>
    el <= 0 || zl <= 0 || rho <= 0 ? 1e9 : Math.abs(Math.log(zl / (el * rho)));

/**
 * 贪心单调对位（align.py:align_greedy 移植）：逐 bead 双侧各取一句起，
 * 谁能让 |log(zl/(el·rho))| 严格变小就扩谁（小者先），否则闭合；单侧耗尽
 * 残句并入末 bead。rho 缺省 = Σzh/Σen（逐 chunk 自适应）。
 */
export function alignBeads(
    enLens: readonly number[],
    zhLens: readonly number[],
    rho?: number,
): Bead[] {
    const m = enLens.length;
    const n = zhLens.length;
    const r =
        rho ??
        (() => {
            const et = enLens.reduce((a, b) => a + b, 0);
            const zt = zhLens.reduce((a, b) => a + b, 0);
            return et > 0 ? zt / et : 1;
        })();
    const beads: Bead[] = [];
    let i = 0;
    let j = 0;
    while (i < m && j < n) {
        const en0 = i;
        const zh0 = j;
        i++;
        j++;
        let el = enLens[en0]!;
        let zl = zhLens[zh0]!;
        for (;;) {
            const cur = cost(el, zl, r);
            let best: [number, "en" | "zh"] | null = null;
            if (i < m && i - en0 < MAXG) {
                const c = cost(el + enLens[i]!, zl, r);
                if (c < cur - 1e-9 && (best === null || c < best[0]))
                    best = [c, "en"];
            }
            if (j < n && j - zh0 < MAXG) {
                const c = cost(el, zl + zhLens[j]!, r);
                if (c < cur - 1e-9 && (best === null || c < best[0]))
                    best = [c, "zh"];
            }
            if (best === null) break;
            if (best[1] === "en") {
                el += enLens[i]!;
                i++;
            } else {
                zl += zhLens[j]!;
                j++;
            }
        }
        beads.push({ en0, en1: i, zh0, zh1: j });
    }
    // 残句并入末 bead（双侧皆空才兜底独占）
    if (i < m || j < n) {
        if (beads.length) {
            const last = beads[beads.length - 1]!;
            last.en1 = m;
            last.zh1 = n;
        } else {
            beads.push({ en0: 0, en1: m, zh0: 0, zh1: n });
        }
    }
    return beads;
}
