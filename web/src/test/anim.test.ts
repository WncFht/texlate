// @vitest-environment jsdom
// anim —— 句对位动效层对拍：press 涟漪 / land 连线+行擦入 / cancelLand
// 清场 / lineRects 去重滤壳 / reduced-motion 全静默 / 单轨清算。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cancelLand, land, lineRects, press } from "../reader/anim";

const rect = (top: number, left = 0, width = 100, height = 12): DOMRect =>
    ({
        top,
        left,
        width,
        height,
        right: left + width,
        bottom: top + height,
        x: left,
        y: top,
        toJSON: () => ({}),
    }) as DOMRect;

// jsdom 无布局——getClientRects 注入假矩形组测纯几何面
const elWithRects = (rs: DOMRect[]): HTMLElement => {
    const el = document.createElement("span");
    el.getClientRects = () => rs as unknown as DOMRectList;
    document.body.append(el);
    return el;
};

beforeEach(() => {
    document.body.innerHTML = "";
    vi.useFakeTimers();
});
afterEach(() => {
    cancelLand();
    vi.unstubAllGlobals();
    vi.useRealTimers();
});

describe("anim 句对位动效层", () => {
    it("press → .sa-ripple 定点落 + ~420ms 自清", () => {
        press(33, 44);
        const d = document.querySelector<HTMLElement>(".sa-ripple")!;
        expect(d).toBeTruthy();
        expect(d.style.left).toBe("33px");
        expect(d.style.top).toBe("44px");
        vi.advanceTimersByTime(430);
        expect(document.querySelector(".sa-ripple")).toBeNull();
    });

    it("lineRects——同行碎片并集（em/a 切片的句不被截尾）+ 零尺寸壳滤除 + 排序", () => {
        const a = elWithRects([rect(100, 50), rect(100, 60, 40)]); // 同行双片→并集
        const b = elWithRects([rect(50, 10), rect(0, 0, 0, 0)]); // 零尺寸滤
        const rs = lineRects([a, b]);
        expect(rs).toHaveLength(2);
        expect(rs[0]!.top).toBe(50);
        expect(rs[1]!.top).toBe(100);
        expect(rs[1]!.left).toBe(50); // 并集左缘=min
        expect(rs[1]!.width).toBe(100); // 50..150 覆盖两片全幅
    });

    it("land → 逐行 .sa-wipe（40ms stagger）+ 贝塞尔连线（源点→首行左缘中）", () => {
        land({ x: 10, y: 20 }, [elWithRects([rect(200, 300), rect(220, 300)])]);
        const wipes = document.querySelectorAll<HTMLElement>(".sa-wipe");
        expect(wipes).toHaveLength(2);
        expect(wipes[0]!.style.left).toBe("300px");
        expect(wipes[0]!.style.top).toBe("200px");
        expect(wipes[0]!.style.animationDelay).toBe("0ms");
        expect(wipes[1]!.style.animationDelay).toBe("40ms");
        const path = document.querySelector(".sa-arc-svg path")!;
        const d = path.getAttribute("d")!;
        expect(d.startsWith("M 10 20 C ")).toBe(true);
        expect(d.endsWith(", 300 206")).toBe(true); // 200+12/2
        vi.advanceTimersByTime(1150);
        expect(
            document.querySelectorAll(".sa-wipe,.sa-arc-svg"),
        ).toHaveLength(0);
    });

    it("land 行数封顶 8——九行落句只擦前八", () => {
        const els = [
            elWithRects([
                rect(0),
                rect(10),
                rect(20),
                rect(30),
                rect(40),
                rect(50),
                rect(60),
                rect(70),
                rect(80),
            ]),
        ];
        land({ x: 1, y: 1 }, els);
        expect(document.querySelectorAll(".sa-wipe")).toHaveLength(8);
    });

    it("land 单轨——在飞连线/擦入被新 land 当场清算", () => {
        land({ x: 1, y: 1 }, [elWithRects([rect(100)])]);
        expect(
            document.querySelectorAll(".sa-wipe,.sa-arc-svg"),
        ).toHaveLength(2);
        land({ x: 2, y: 2 }, [elWithRects([rect(300), rect(320)])]);
        const wipes = document.querySelectorAll<HTMLElement>(".sa-wipe");
        expect(wipes).toHaveLength(2); // 新两行；旧一行已摘
        expect(wipes[0]!.style.top).toBe("300px");
        expect(document.querySelectorAll(".sa-arc-svg")).toHaveLength(1);
    });

    it("land 空 els/全壳零矩形 → 什么都不产", () => {
        land({ x: 1, y: 1 }, []);
        land({ x: 1, y: 1 }, [elWithRects([])]);
        expect(
            document.querySelectorAll(".sa-wipe,.sa-arc-svg"),
        ).toHaveLength(0);
    });

    it("land 不杀在飞涟漪——press ack 与连线并存（同帧 press→land）", () => {
        press(9, 9);
        land({ x: 1, y: 1 }, [elWithRects([rect(100)])]);
        expect(document.querySelector(".sa-ripple")).toBeTruthy();
        vi.advanceTimersByTime(430); // 涟漪自钟到点自清
        expect(document.querySelector(".sa-ripple")).toBeNull();
        expect(document.querySelectorAll(".sa-wipe")).toHaveLength(1);
    });

    it("land 自清钟只摘连线/擦入——别帧新涟漪不被误杀", () => {
        land({ x: 1, y: 1 }, [elWithRects([rect(100)])]);
        vi.advanceTimersByTime(900); // 还在 1100ms 窗内
        press(5, 5); // 新按下（其 land 未决——涟漪归 press 管）
        vi.advanceTimersByTime(210); // A 自清钟到点
        expect(document.querySelectorAll(".sa-wipe,.sa-arc-svg")).toHaveLength(0);
        expect(document.querySelector(".sa-ripple")).toBeTruthy();
    });

    it("land from=null（gotoPeer 非点击跳）→ 只擦入不连线", () => {
        land(null, [elWithRects([rect(100), rect(120)])]);
        expect(document.querySelectorAll(".sa-wipe")).toHaveLength(2);
        expect(document.querySelectorAll(".sa-arc-svg")).toHaveLength(0);
        vi.advanceTimersByTime(1150);
        expect(document.querySelectorAll(".sa-wipe")).toHaveLength(0);
    });

    it("land 连线终点取首个视口内行——跨页 seq 不连画外点", () => {
        // jsdom innerHeight=768：首行 top=-40 画外，次行 100 画内
        land({ x: 1, y: 1 }, [
            elWithRects([rect(-40, 30), rect(100, 30)]),
        ]);
        const d = document
            .querySelector(".sa-arc-svg path")!
            .getAttribute("d")!;
        expect(d.endsWith(", 30 106")).toBe(true); // 100+12/2 非 -40+6
    });

    it("cancelLand 摘光在飞件（涟漪在内）——旧 timer 不再复活", () => {
        press(9, 9);
        land({ x: 1, y: 1 }, [elWithRects([rect(100)])]);
        cancelLand();
        expect(
            document.querySelectorAll(".sa-wipe,.sa-arc-svg,.sa-ripple"),
        ).toHaveLength(0);
        vi.advanceTimersByTime(2000);
        expect(
            document.querySelectorAll(".sa-wipe,.sa-arc-svg,.sa-ripple"),
        ).toHaveLength(0);
    });

    it("reduced-motion → press/land 全静默（静态落点由 sa-flash 承担）", () => {
        vi.stubGlobal("matchMedia", () => ({ matches: true }));
        press(1, 2);
        land({ x: 1, y: 1 }, [elWithRects([rect(100)])]);
        expect(
            document.querySelectorAll(".sa-ripple,.sa-wipe,.sa-arc-svg"),
        ).toHaveLength(0);
    });

    it("saAnimProbe——state 报在飞件、hold/release 不炸、__saAnim 已挂窗", () => {
        const probe = (
            window as unknown as {
                __saAnim: {
                    hold(t: number): number;
                    release(): void;
                    state(): {
                        ripple: boolean;
                        arc: boolean;
                        wipes: number;
                    };
                };
            }
        ).__saAnim;
        expect(probe).toBeTruthy();
        expect(probe.state()).toEqual({
            ripple: false,
            arc: false,
            wipes: 0,
        });
        land({ x: 1, y: 1 }, [elWithRects([rect(100), rect(120)])]);
        const st = probe.state();
        expect(st.arc).toBe(true);
        expect(st.wipes).toBe(2);
        // jsdom 不跑 WAAPI——hold 钉 0 条但不许炸；真冻结断言在
        // scripts/floor_verify.mjs --reader 的 anim 腿
        expect(probe.hold(300)).toBe(0);
        probe.release();
        cancelLand();
        expect(probe.state()).toEqual({
            ripple: false,
            arc: false,
            wipes: 0,
        });
    });
});
