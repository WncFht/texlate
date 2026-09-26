// follow —— 跟手数学对拍：帧率无关性（同一输入 30/60/120fps 轨迹一致，
// §7.5「声称帧率无关就必须证明」）、lead 项稳态滞后抵消、critical 零
// 过冲、underdamped 过冲后收敛、WheelGuard 动量尾/反向重置/残留衰减。

import { describe, expect, it } from "vitest";
import { expFollow, Spring, WheelGuard } from "../follow";

const run = (dt: number, dur: number, step: (t: number) => void): void => {
    const n = Math.round(dur / dt);
    for (let i = 0; i < n; i++) step((i + 1) * dt);
};

describe("expFollow 一阶跟随", () => {
    it("静止目标收敛——离散形式对帧率划分是精确的", () => {
        const ends = [1 / 30, 1 / 60, 1 / 120].map((dt) => {
            let x = 0;
            run(dt, 1, () => {
                x = expFollow(x, 500, 6, dt);
            });
            return x;
        });
        // 残差每步乘 e^-k·dt——与 dt 如何划分无关，解析解 500(1-e^-6)≈498.76
        for (const e of ends) expect(e).toBeCloseTo(498.7612, 2);
        expect(Math.max(...ends) - Math.min(...ends)).toBeLessThan(0.001);
    });

    it("k 是 1/s 紧度——k 小落得慢", () => {
        let fast = 0;
        let slow = 0;
        run(1 / 60, 0.3, () => {
            fast = expFollow(fast, 100, 8, 1 / 60);
            slow = expFollow(slow, 100, 2, 1 / 60);
        });
        expect(fast).toBeGreaterThan(slow);
        expect(fast).toBeGreaterThan(90);
        expect(slow).toBeLessThan(50);
    });

    it("追匀速目标：无 lead 稳态滞后 ≈v/k（离散解 v·dt·e^-k·dt/(1-e^-k·dt)），带 lead 抵消到 ~0", () => {
        const v = 100;
        const k = 5;
        const dt = 1 / 60;
        let x = 0;
        let t = 0;
        run(dt, 3, () => {
            t += dt;
            x = expFollow(x, v * t, k, dt);
        });
        const lag = v * t - x;
        // 离散稳态：d_j = (d_{j-1}+v·dt)(1-α) → d* = v·dt(1-α)/α ≈ 19.18
        const a = 1 - Math.exp(-k * dt);
        const expected = (v * dt * (1 - a)) / a;
        expect(lag).toBeGreaterThan(expected * 0.95);
        expect(lag).toBeLessThan(expected * 1.05);
        expect(Math.abs(lag - v / k)).toBeLessThan(v / k * 0.1); // ≈v/k 连续极限

        x = 0;
        t = 0;
        run(dt, 3, () => {
            t += dt;
            x = expFollow(x, v * t, k, dt, v);
        });
        expect(Math.abs(v * t - x)).toBeLessThan(2); // 「跟手但总差一点」被 lead 消掉
    });
});

describe("Spring 阻尼弹簧", () => {
    it("ζ=1 临界：无过冲且 ~1s 落定（UI chrome/姿态档）", () => {
        const s = new Spring(0, 120, 1);
        let peak = 0;
        run(1 / 60, 1, () => {
            peak = Math.max(peak, s.step(100, 1 / 60));
        });
        expect(peak).toBeLessThanOrEqual(101); // 连续解零过冲，欧拉离散残余 <1%
        expect(s.value).toBeGreaterThan(99);
        expect(Math.abs(s.velocity)).toBeLessThan(5);
    });

    it("ζ<1 欠阻尼：过冲后回稳（落地有分量档）", () => {
        const s = new Spring(0, 120, 0.5);
        let peak = 0;
        run(1 / 60, 2, () => {
            peak = Math.max(peak, s.step(100, 1 / 60));
        });
        expect(peak).toBeGreaterThan(105); // ζ=0.5 连续解 ~16% 过冲
        expect(Math.abs(s.value - 100)).toBeLessThan(1);
    });

    it("帧率无关：30/60/120fps 同终点（半隐式欧拉残差随 dt 收敛）", () => {
        const ends = [1 / 30, 1 / 60, 1 / 120].map((dt) => {
            const s = new Spring(0, 120, 0.6);
            run(dt, 1.5, () => s.step(100, dt));
            return s.value;
        });
        for (const e of ends) expect(Math.abs(e - 100)).toBeLessThan(1);
        expect(Math.max(...ends) - Math.min(...ends)).toBeLessThan(2);
    });

    it("snap 瞬移清速——重绑目标不吃旧速度", () => {
        const s = new Spring(0, 120, 0.5);
        run(1 / 60, 0.2, () => s.step(100, 1 / 60));
        expect(s.velocity).not.toBe(0);
        s.snap(50);
        expect(s.value).toBe(50);
        expect(s.velocity).toBe(0);
    });
});

describe("WheelGuard 滚轮动量守卫", () => {
    it("累积达阈值触发一步，一次手势只走一步", () => {
        const g = new WheelGuard();
        expect(g.feed(50, 0)).toBe(0);
        expect(g.feed(50, 16)).toBe(1); // 100 ≥ 90
        // 锁定期内动量尾全吞
        expect(g.feed(80, 200)).toBe(0);
        expect(g.feed(200, 550)).toBe(0);
        // 锁定期过后手势重新计
        expect(g.feed(95, 650)).toBe(1);
    });

    it("反向 delta 清零重计——回滚不撞闸", () => {
        const g = new WheelGuard();
        expect(g.feed(60, 0)).toBe(0);
        expect(g.feed(-10, 50)).toBe(0); // 方向翻转 acc 归 -10
        expect(g.feed(-85, 100)).toBe(-1); // -95 达阈
    });

    it("tick 残留衰减——隔了几十帧的旧 delta 拼不出新步", () => {
        const g = new WheelGuard();
        expect(g.feed(85, 0)).toBe(0); // acc=85 未达阈
        for (let i = 0; i < 20; i++) g.tick(); // ×0.92^20 ≈ ×0.19 → ~16
        expect(g.feed(10, 400)).toBe(0); // 26 < 90（不衰减则 95 会触发）
        expect(g.feed(70, 450)).toBe(1); // 96 达阈
    });

    it("reset 全清", () => {
        const g = new WheelGuard();
        g.feed(85, 0);
        g.reset();
        expect(g.feed(10, 700)).toBe(0); // acc=10 而非 95
    });
});
