import { describe, expect, it } from "vitest";
import {
    capturePos,
    jumpTo,
    scrollTopFor,
    SyncEngine,
    type PaneLike,
} from "../reader/sync";
import type { Pos } from "../reader/alignment";

/** 假滚动容器：scrollTop/clientHeight + EventTarget 语义的最小实现 */
class FakeEl {
    scrollTop = 0;
    clientHeight = 500;
    private listeners = new Set<() => void>();
    addEventListener(_t: string, l: () => void) {
        this.listeners.add(l);
    }
    removeEventListener(_t: string, l: () => void) {
        this.listeners.delete(l);
    }
    /** 模拟浏览器：写 scrollTop 后派发 scroll 事件（同步派发是测试替身
     *  简化——真实浏览器 scroll 事件异步，flush() 的 25ms 等待掩盖差异） */
    scrollTo(top: number) {
        this.scrollTop = top;
        for (const l of this.listeners) l();
    }
    dispatchScroll() {
        for (const l of this.listeners) l();
    }
}

function fakePane(
    side: "original" | "translated",
    pageTops: number[],
    pageH = 800,
): PaneLike & { fel: FakeEl } {
    const fel = new FakeEl();
    return {
        fel,
        side,
        get el() {
            return fel as unknown as HTMLElement;
        },
        pages: () =>
            pageTops.map((top, i) => ({ page: i + 1, top, height: pageH })),
    };
}

// rAF 在 node 里由 sync.ts 的 setTimeout 兜底 → 用 await 排空
const flush = () => new Promise((r) => setTimeout(r, 25));

describe("capturePos / jumpTo", () => {
    it("capture：焦点行 = scrollTop+20%vh，返回页码+fraction+viewport", () => {
        const p = fakePane("original", [0, 800, 1600]);
        p.fel.scrollTop = 900; // focus = 900 + 100 = 1000 → page2 (top 800), fraction 0.25
        const pos = capturePos(p);
        expect(pos.page).toBe(2);
        expect(pos.fraction).toBeCloseTo(0.25);
        expect(pos.viewport).toBeCloseTo(0.2); // (1000-900)/500
    });

    it("capture：focus 在页边界前取最后 top<=focus 的页", () => {
        const p = fakePane("original", [0, 800, 1600]);
        p.fel.scrollTop = 0;
        const pos = capturePos(p);
        expect(pos.page).toBe(1); // focus=100 在 page1 内
    });

    it("jump：scrollTop = top + fraction*h - viewport*vh；scrollTopFor 不动", () => {
        const p = fakePane("original", [0, 800, 1600]);
        const pos: Pos = { page: 2, fraction: 0.25, viewport: 0.2 };
        expect(scrollTopFor(p, pos)).toBe(800 + 200 - 100);
        jumpTo(p, pos);
        expect(p.fel.scrollTop).toBe(900);
    });

    it("capture：纯索引访问二分——pages 数组不可迭代也正常工作（不复制整表）", () => {
        const geoms = [
            { page: 1, top: 0, height: 800 },
            { page: 2, top: 800, height: 800 },
            { page: 3, top: 1600, height: 800 },
        ];
        // 迭代器炸掉——[...pages] 式复制会抛；索引遍历不受影响
        Object.defineProperty(geoms, Symbol.iterator, {
            value: () => {
                throw new Error("pages must not be iterated/copied");
            },
        });
        const fel = new FakeEl();
        fel.scrollTop = 900;
        const pane: PaneLike = {
            side: "original",
            get el() {
                return fel as unknown as HTMLElement;
            },
            pages: () => geoms,
        };
        const pos = capturePos(pane);
        expect(pos.page).toBe(2);
        expect(pos.fraction).toBeCloseTo(0.25);
    });
});

describe("SyncEngine", () => {
    const identity = (pos: Pos): Pos => pos;

    it("源滚动 → rAF 后把对侧跳到映射位置", async () => {
        const A = fakePane("original", [0, 800]);
        const B = fakePane("translated", [0, 800]);
        new SyncEngine(A, B, identity);
        A.fel.scrollTo(400);
        await flush();
        // A: focus=400+100=500 → p1 f0.625 viewport 0.2 → B: top = 0+500-100=400
        expect(B.fel.scrollTop).toBe(400);
    });

    it("程序跳转的回声被 ignoreTop 吞掉，不回环", async () => {
        const A = fakePane("original", [0, 800]);
        const B = fakePane("translated", [0, 800]);
        new SyncEngine(A, B, identity);
        A.fel.scrollTo(400);
        await flush();
        // B 已被程序跳到 400；模拟派发 scroll 回声
        B.fel.dispatchScroll();
        await flush();
        expect(A.fel.scrollTop).toBe(400); // A 未被回声推回
    });

    it("syncing=false 时不同步", async () => {
        const A = fakePane("original", [0, 800]);
        const B = fakePane("translated", [0, 800]);
        const e = new SyncEngine(A, B, identity);
        e.syncing = false;
        A.fel.scrollTo(700);
        await flush();
        expect(B.fel.scrollTop).toBe(0);
    });

    it("pendingSrc 覆盖：连续滚动只应用最后一帧", async () => {
        const A = fakePane("original", [0, 800, 1600]);
        const B = fakePane("translated", [0, 800, 1600]);
        new SyncEngine(A, B, identity);
        A.fel.scrollTo(100);
        A.fel.scrollTo(1200); // 第二次滚动覆盖 pendingSrc，第一帧不再生效
        await flush();
        expect(B.fel.scrollTop).toBe(1200);
    });

    it("滚动突发合帧：事件期零采样，rAF 内对最新位置采样一次", async () => {
        const A = fakePane("original", [0, 800, 1600]);
        const B = fakePane("translated", [0, 800, 1600]);
        let aCalls = 0;
        const origPages = A.pages;
        A.pages = () => {
            aCalls++;
            return origPages();
        };
        new SyncEngine(A, B, identity);
        A.fel.scrollTo(100);
        A.fel.scrollTo(1200);
        expect(aCalls).toBe(0); // 事件回调不读几何——全部推迟到 rAF
        await flush();
        expect(B.fel.scrollTop).toBe(1200);
        expect(aCalls).toBe(1); // 三次事件合并成一次 capturePos
    });

    it("dispose 移除监听", async () => {
        const A = fakePane("original", [0, 800]);
        const B = fakePane("translated", [0, 800]);
        const e = new SyncEngine(A, B, identity);
        e.dispose();
        A.fel.scrollTo(400);
        await flush();
        expect(B.fel.scrollTop).toBe(0);
    });
});
