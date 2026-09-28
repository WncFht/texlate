// navstack —— 引用跳转的「跳回栈」（sioyek 历史语义精简版）。
// 模型：entries[i] 是可导航位置，idx 指向「当前位置」槽。跳转时把跳前
// 活态写进 entries[idx]（用户可能在落点后又滚过——写回的是真值），再
// 把落点作为新当前项入栈。回跳瞬间同样把当前活态回写 idx 槽——返回点
// 精确到「按返回那刻的位置」，不是跳前那一刻。
// 只记跳转类动作（named dest / 页内锚），滚动永不入栈。

import { createSignal } from "solid-js";

import type { Pos } from "./alignment";

/** 栈项：pos 之外带 pair 标记——split 镜像跳在两侧栈各产一条同 pair
    项，一侧 ↩/↪ 命中 pair 项时对侧栈顶同 pair 即联动回/前（未成对的
    历史各自独立不受影响） */
interface NavEntry {
    pos: Pos;
    pair?: number;
}

export class NavStack {
    private entries: NavEntry[] = [];
    private idx = -1;
    private stamp: () => number;
    private bump: () => void;

    constructor() {
        const [stamp, setStamp] = createSignal(0);
        this.stamp = stamp;
        this.bump = () => setStamp((n) => n + 1);
    }

    /** 一次跳转：pre=跳前活态、post=落点活态；截断前进项后入栈。
        pair=镜像配对号（ReaderView 每次 cite 跳发一号，双侧同号入栈） */
    recordJump(pre: Pos, post: Pos, pair?: number): void {
        this.entries.length = this.idx + 1;
        if (this.idx >= 0) {
            // 回写跳前活态但保留 pair——该槽是它所属那次镜像跳的票据
            this.entries[this.idx] = { ...this.entries[this.idx], pos: pre };
        } else {
            this.entries.push({ pos: pre });
        }
        this.entries.push({ pos: post, pair });
        this.idx = this.entries.length - 1;
        this.bump();
    }

    canBack(): boolean {
        this.stamp();
        return this.idx > 0;
    }

    canFwd(): boolean {
        this.stamp();
        return this.idx + 1 < this.entries.length;
    }

    /** 栈顶（当前位）pair——回跳联动判定用 */
    topPair(): number | undefined {
        this.stamp();
        return this.entries[this.idx]?.pair;
    }

    /** 前进票（下一槽）pair——前跳联动判定用 */
    nextPair(): number | undefined {
        this.stamp();
        return this.entries[this.idx + 1]?.pair;
    }

    /** 回跳：cur=此刻活态（回写为前进票），返目标位置+离开槽的 pair */
    back(cur: Pos): { pos: Pos; pair?: number } | null {
        if (this.idx <= 0) return null;
        const pair = this.entries[this.idx].pair;
        this.entries[this.idx] = { ...this.entries[this.idx], pos: cur };
        this.idx--;
        this.bump();
        return { pos: this.entries[this.idx].pos, pair };
    }

    /** 前跳：cur=此刻活态（回写为回退票），返目标位置+落进槽的 pair */
    fwd(cur: Pos): { pos: Pos; pair?: number } | null {
        if (this.idx + 1 >= this.entries.length) return null;
        const pair = this.entries[this.idx + 1].pair;
        this.entries[this.idx] = { ...this.entries[this.idx], pos: cur };
        this.idx++;
        this.bump();
        return { pos: this.entries[this.idx].pos, pair };
    }
}
