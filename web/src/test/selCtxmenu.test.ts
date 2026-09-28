// @vitest-environment jsdom
// selCtxmenu —— placeMenu/placeSubmenu 不变量 fuzz + useContextMenu
// 开/关单三通道（Esc/外点/选取）+ snapshot veto/bypass + menuItemsFor
// cmdreg 桥（SECTION_ORDER 分段/分隔线/disabled/label 解析/动作出口）
// + 两处已修缺陷回归：
//   (a) 本层处理过的 nav 键 stopPropagation——子菜单内 ArrowDown 不
//       被根级 ul 委托重排；
//   (b) 垂直换轨（ArrowUp/Down/Home/End）同步 setSubIdx(-1)——键盘
//       移到兄弟项即收本层子菜单。
// jsdom 无 layout：MenuLevel onMount 实测 offsetWidth/Height=0 → place
// 全钳左上，断言只走 DOM 存在性与焦点面，不锚坐标。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "solid-js/web";
import {
    cmdLabel,
    menuItemsFor,
    placeMenu,
    placeSubmenu,
    useContextMenu,
    type CtxItem,
    type CtxMenuOpts,
    type CtxOpen,
} from "../reader/ContextMenu";
import { Registry, type Command } from "../reader/cmd/cmdreg";
import { MENU_LABELS, type CmdCtx } from "../reader/cmd/commands";
import { currentLang, t } from "../i18n";

// ------------------------------------------------------------ 纯函数

describe("placeMenu", () => {
    it("右下默认展开；出界翻边并硬钳视口", () => {
        // 光标旁够放 → 不翻
        const p = placeMenu(100, 100, 200, 150, 1024, 768);
        expect(p.left).toBe(100);
        expect(p.top).toBe(100);
        expect(p.flipX).toBe(false);
        expect(p.flipY).toBe(false);
        // 右溢出 → 翻光标左侧
        const q = placeMenu(1000, 100, 200, 150, 1024, 768);
        expect(q.flipX).toBe(true);
        expect(q.left).toBe(800);
        // 下溢出 → 翻上
        const r = placeMenu(100, 750, 200, 150, 1024, 768);
        expect(r.flipY).toBe(true);
        expect(r.top).toBe(600);
    });

    it("fuzz 3000：w+2m<=vw 且 h+2m<=vh → 必落视口内", () => {
        let seed = 0x1234abcd;
        const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff);
        for (let i = 0; i < 3000; i++) {
            const vw = 240 + (rnd() % 1400);
            const vh = 200 + (rnd() % 1000);
            const w = 40 + (rnd() % 300);
            const h = 30 + (rnd() % 300);
            if (w + 8 > vw || h + 8 > vh) continue;
            const p = placeMenu(rnd() % vw, rnd() % vh, w, h, vw, vh);
            expect(p.left).toBeGreaterThanOrEqual(4);
            expect(p.top).toBeGreaterThanOrEqual(4);
            expect(p.left + w).toBeLessThanOrEqual(vw - 4);
            expect(p.top + h).toBeLessThanOrEqual(vh - 4);
        }
    });
});

describe("placeSubmenu", () => {
    const a = { left: 100, top: 200, right: 300, bottom: 228 };
    it("贴父项右缘默认；右溢出翻左", () => {
        const p = placeSubmenu(a, 180, 120, 1024, 768);
        expect(p.left).toBe(298); // a.right - 2
        expect(p.flipX).toBe(false);
        const q = placeSubmenu(
            { left: 900, top: 200, right: 1010, bottom: 228 },
            180,
            120,
            1024,
            768,
        );
        expect(q.flipX).toBe(true);
        expect(q.left).toBe(722); // a.left - w + 2
    });
    it("fuzz 3000：落点视口内", () => {
        let seed = 0xfeed1234;
        const rnd = () => (seed = (seed * 1103515245 + 12345) & 0x7fffffff);
        for (let i = 0; i < 3000; i++) {
            const vw = 300 + (rnd() % 1400);
            const vh = 200 + (rnd() % 1000);
            const w = 40 + (rnd() % 280);
            const h = 30 + (rnd() % 300);
            if (w + 8 > vw || h + 8 > vh) continue;
            const ax = rnd() % vw;
            const ay = rnd() % vh;
            const p = placeSubmenu(
                {
                    left: ax,
                    top: ay,
                    right: ax + 30 + (rnd() % 100),
                    bottom: ay + 28,
                },
                w,
                h,
                vw,
                vh,
            );
            expect(p.left).toBeGreaterThanOrEqual(4);
            expect(p.top).toBeGreaterThanOrEqual(4);
            expect(p.left + w).toBeLessThanOrEqual(vw - 4);
            expect(p.top + h).toBeLessThanOrEqual(vh - 4);
        }
    });
});

// -------------------------------------------------------- useContextMenu

let dispose: (() => void) | undefined;

const ITEMS: CtxItem[] = [
    { id: "copy", label: "Copy" },
    { id: "sep", sep: true },
    {
        id: "jump",
        label: "Jump",
        children: [
            { id: "sub1", label: "Sub A" },
            { id: "sub2", label: "Sub B" },
        ],
    },
    { id: "off", label: "Disabled", disabled: true },
];

const open = (
    ctx: ReturnType<typeof useContextMenu>,
    x = 120,
    y = 140,
    target?: Element,
) => {
    const e = new MouseEvent("contextmenu", {
        bubbles: true,
        clientX: x,
        clientY: y,
    });
    if (target) target.dispatchEvent(e);
    ctx.onContextMenu(e);
};

const menuEl = () => document.querySelector<HTMLElement>(".ctx-menu");
const rows = (scope?: ParentNode) => [
    ...(scope ?? document).querySelectorAll<HTMLElement>(
        ".ctx-menu li[role='menuitem']",
    ),
];
const tick = () => new Promise((r) => setTimeout(r, 0));

beforeEach(() => {
    document.body.innerHTML = `<button id="prev">prev</button>
<div id="host"><div class="pane" data-side="original"><div class="pane-html-body"><div data-chunk="0" id="c0">text body</div></div></div></div>`;
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
});

describe("useContextMenu", () => {
    it("开单渲染 items + 快照 hit/cmd 挂入 CtxOpen；isOpen 翻真", async () => {
        const seen: CtxOpen[] = [];
        let ctx!: ReturnType<typeof useContextMenu>;
        dispose = render(() => {
            ctx = useContextMenu(
                (o) => {
                    seen.push(o);
                    return ITEMS;
                },
                {
                    snapshot: (_e, base) => ({
                        ...base,
                        hit: { marker: 1 } as unknown as CtxOpen["hit"],
                        cmd: { tag: "ctx" } as unknown as CtxOpen["cmd"],
                    }),
                },
            );
            return ctx.menu();
        }, document.body);
        open(ctx, 120, 140);
        await tick();
        expect(ctx.isOpen()).toBe(true);
        const m = menuEl();
        expect(m).not.toBeNull();
        expect(rows().map((r) => r.dataset.id)).toEqual([
            "copy",
            "jump",
            "off",
        ]);
        // sep 渲染为分隔行
        expect(document.querySelectorAll(".ctx-sep").length).toBe(1);
        // snapshot 扩展挂入
        expect((seen[0] as unknown as Record<string, unknown>).cmd).toEqual({
            tag: "ctx",
        });
        expect(seen[0]!.x).toBe(120);
        expect(seen[0]!.y).toBe(140);
    });

    it("snapshot=null veto 与 bypass 都不拦默认、不开单", async () => {
        let ctx!: ReturnType<typeof useContextMenu>;
        const opts: CtxMenuOpts = {
            snapshot: () => null,
            bypass: (e) => e.shiftKey,
        };
        dispose = render(() => {
            ctx = useContextMenu(() => ITEMS, opts);
            return ctx.menu();
        }, document.body);
        // veto：snapshot 返 null → 原生菜单照常（未 preventDefault）
        const e = new MouseEvent("contextmenu", { bubbles: true });
        ctx.onContextMenu(e);
        await tick();
        expect(ctx.isOpen()).toBe(false);
        expect(menuEl()).toBeNull();
        // bypass：shiftKey → 直接放行（snapshot 都不会被调）
        const spy = vi.fn((_e: MouseEvent) => null as null);
        dispose?.();
        dispose = render(() => {
            ctx = useContextMenu(() => ITEMS, {
                bypass: (e) => e.shiftKey,
                snapshot: (e, b) => {
                    spy(e);
                    return b;
                },
            });
            return ctx.menu();
        }, document.body);
        ctx.onContextMenu(
            new MouseEvent("contextmenu", { bubbles: true, shiftKey: true }),
        );
        await tick();
        expect(spy).not.toHaveBeenCalled();
        expect(ctx.isOpen()).toBe(false);
    });

    it("关单三通道：Esc / 外点 pointerdown / 点选——回焦开单前焦点", async () => {
        const onClose = vi.fn();
        const action = vi.fn();
        let ctx!: ReturnType<typeof useContextMenu>;
        dispose = render(() => {
            ctx = useContextMenu(
                () => [
                    { id: "a", label: "A", action },
                    { id: "b", label: "B" },
                ],
                { onClose },
            );
            return ctx.menu();
        }, document.body);
        const prev = document.getElementById("prev")!;
        prev.focus();
        // Esc 关
        open(ctx);
        await tick();
        document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
        await tick();
        expect(ctx.isOpen()).toBe(false);
        expect(onClose).toHaveBeenCalledTimes(1);
        expect(document.activeElement).toBe(prev); // 回焦
        // 外点关
        open(ctx);
        await tick();
        document.body.dispatchEvent(
            new MouseEvent("pointerdown", { bubbles: true }),
        );
        await tick();
        expect(ctx.isOpen()).toBe(false);
        // 点选关 + action 出口
        open(ctx);
        await tick();
        rows()[0]!.click();
        await tick();
        expect(action).toHaveBeenCalledTimes(1);
        expect(ctx.isOpen()).toBe(false);
    });

    it("幂等 close：重复关单不重复回调/回焦", async () => {
        const onClose = vi.fn();
        let ctx!: ReturnType<typeof useContextMenu>;
        dispose = render(() => {
            ctx = useContextMenu(() => ITEMS, { onClose });
            return ctx.menu();
        }, document.body);
        ctx.close(); // 未开单——空转
        expect(onClose).not.toHaveBeenCalled();
        open(ctx);
        await tick();
        ctx.close();
        ctx.close();
        expect(onClose).toHaveBeenCalledTimes(1);
    });
});

// --------------------------------------------------------- 两处已修缺陷

describe("已修缺陷回归", () => {
    const withSub: CtxItem[] = [
        { id: "a", label: "A" },
        {
            id: "j",
            label: "J",
            children: [
                { id: "s1", label: "S1" },
                { id: "s2", label: "S2" },
                { id: "s3", label: "S3" },
            ],
        },
        { id: "b", label: "B" },
    ];

    const openMenu = async () => {
        let ctx!: ReturnType<typeof useContextMenu>;
        dispose = render(() => {
            ctx = useContextMenu(() => withSub);
            return ctx.menu();
        }, document.body);
        open(ctx);
        await tick();
        // autofocus → 首项
        await tick();
        return ctx;
    };

    const key = (el: Element | Document, k: string) =>
        el.dispatchEvent(
            new KeyboardEvent("keydown", { key: k, bubbles: true }),
        );

    it("(b) 垂直换轨同步收子菜单：ArrowRight 开后 ArrowUp → .ctx-sub 消失", async () => {
        await openMenu();
        const li = rows()[1]!; // J（带子菜单）
        li.focus();
        key(li, "ArrowRight");
        await tick();
        expect(document.querySelector(".ctx-sub")).not.toBeNull();
        // 垂直换轨发生在「本层」行上——子菜单打开后 ArrowRight 已把焦点
        // 移交子菜单；换轨键须落根行才触发根的 setSubIdx(-1)
        const liB = rows().find((r) => r.dataset.id === "b")!;
        liB.focus();
        key(liB, "ArrowUp");
        await tick();
        expect(document.querySelector(".ctx-sub")).toBeNull();
    });

    it("(a) 子菜单内 ArrowDown stopPropagation——根级不重排焦点", async () => {
        await openMenu();
        const li = rows()[1]!;
        li.focus();
        key(li, "ArrowRight");
        await tick();
        await tick(); // 子菜单 autofocus microtask
        const sub = document.querySelector<HTMLElement>(".ctx-sub");
        expect(sub).not.toBeNull();
        // 子菜单首行聚焦后 ArrowDown → 移到 s2；事件不冒到根 ul 委托
        const subRows = [
            ...sub!.querySelectorAll<HTMLElement>("li[role='menuitem']"),
        ];
        subRows[0]!.focus();
        key(subRows[0]!, "ArrowDown");
        await tick();
        const active = document.activeElement as HTMLElement;
        expect(active.closest(".ctx-sub")).toBe(sub); // 焦点留在子菜单内
        expect(subRows.indexOf(active)).toBe(1); // 子菜单内下移一行
        // 根级若重处理会把焦点挪回根项——sub 树内无 .ctx-item 根行
        expect(active.dataset.id).toBe("s2");
    });
});

// ------------------------------------------------------------ cmdreg 桥

describe("menuItemsFor", () => {
    const ctxOf = (flat: Record<string, unknown> = {}) =>
        ({ hit: {}, deps: {}, ...flat }) as unknown as CmdCtx;

    const reg = () => {
        const r = new Registry<CmdCtx>();
        return r;
    };

    it("SECTION_ORDER 分段 + 段间插 sep；注册乱序仍按段序", () => {
        const r = reg();
        const mk = (id: string, sec: string): Command<CmdCtx> => ({
            id,
            title: `menu.${id}`,
            sec,
            run: () => {},
        });
        // 乱序注册：chunk 在前 sel 在后——菜单仍按 SECTION_ORDER
        r.register(mk("chunk.copySrc", "chunk"));
        r.register(mk("pane.find", "pane"));
        r.register(mk("sel.copy", "sel"));
        const items = menuItemsFor(r, ctxOf());
        const order = items.filter((i) => !i.sep).map((i) => i.id);
        expect(order).toEqual(["sel.copy", "chunk.copySrc", "pane.find"]);
        expect(items.filter((i) => i.sep).length).toBe(2); // 三段两缝
    });

    it("enableWhen 不过 → disabled 不 hidden；click 不执行", () => {
        const r = reg();
        const run = vi.fn();
        r.register({
            id: "chunk.retx",
            title: "menu.chunk.retx",
            sec: "chunk",
            enableWhen: "chunk.intSeq", // ctx 缺该键 → disabled
            run,
        });
        const items = menuItemsFor(r, ctxOf());
        expect(items.length).toBe(1);
        expect(items[0]!.disabled).toBe(true);
        items[0]!.action?.({} as CtxOpen);
        // action 走 runUnchecked——disabled 语义由菜单层承担（原生菜单同义：
        // aria-disabled 项不可点，见 ContextMenu li onClick 早退）
        expect(run).toHaveBeenCalledTimes(1); // runUnchecked 不查 enableWhen
    });

    it("label 覆写优先，cmdLabel 解析 t-path→MENU_LABELS→id 兜底", () => {
        const r = reg();
        r.register({
            id: "cite.jump",
            title: "menu.cite.jump",
            sec: "cite",
            run: () => {},
        });
        r.register({
            id: "x.y",
            title: "no.such.key",
            sec: "z",
            run: () => {},
        });
        const items = menuItemsFor(r, ctxOf(), {
            label: (c) => (c.id === "cite.jump" ? "跳至文献条目" : undefined),
        });
        expect(items[0]!.label).toBe("跳至文献条目");
        // 未覆写项：title 不是 t 键 → MENU_LABELS 无此 id → id 兜底
        // （items[1] 是 cite/z 段间 sep——过滤再取）
        expect(items.filter((i) => !i.sep)[1]!.label).toBe("x.y");
    });

    it("cmdLabel：t-path 命中 / MENU_LABELS 镜像 / id 兜底", () => {
        // t-path 命中 = i18n 当前语言串（测试环境 en——与菜单实渲染同源）
        expect(cmdLabel({ id: "sel.copy", title: "menu.sel.copy" })).toBe(
            t.menu.sel.copy,
        );
        expect(cmdLabel({ id: "sel.copy", title: "no.such.path" })).toBe(
            MENU_LABELS["sel.copy"]![currentLang()],
        ); // MENU_LABELS 镜像
        expect(cmdLabel({ id: "nope.x", title: "nope.y" })).toBe("nope.x");
    });

    it("action → runUnchecked + onError 兜底（rejection 不外溢）", async () => {
        const r = reg();
        r.register({
            id: "boom",
            title: "menu.boom",
            run: () => Promise.reject(new Error("kaput")),
        });
        const onError = vi.fn();
        const items = menuItemsFor(r, ctxOf(), { onError });
        items[0]!.action?.({} as CtxOpen);
        await new Promise((r2) => setTimeout(r2, 0));
        expect(onError).toHaveBeenCalledTimes(1);
    });
});
