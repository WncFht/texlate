// selCmdreg —— cmdreg 谓词求值器 + Registry + commands 表审计。
// 对拍 exp/ss-cmdreg 同款语义：真值表/坏语法/缓存/whenKeys 静态审计；
// 落地扩展：enableWhen（disabled 不 hidden）、unregister 幂等、
// registerCommands 18 项全集 ⊆ CTX_KEYS（拼写漂移审计）。

import { describe, expect, it } from "vitest";
import {
    auditWhenKeys,
    compileWhen,
    evalWhen,
    Registry,
    whenCacheSize,
    whenKeys,
    type Command,
} from "../reader/cmd/cmdreg";
import {
    makeCmdCtx,
    MENU_LABELS,
    registerCommands,
    SECTION_ORDER,
    type CmdCtx,
} from "../reader/cmd/commands";
import { CTX_KEYS, snapshotHit } from "../reader/cmd/hitctx";

// ============================================================ when 求值器

describe("when evaluator truth table", () => {
    const cases: [string, Record<string, unknown>, boolean][] = [
        ["sel.text", { "sel.text": "abc" }, true],
        ["sel.text", {}, false],
        ["sel.text", { "sel.text": "" }, false], // 空串 falsy
        ["!inInput", { inInput: true }, false],
        ["!inInput", {}, true], // 缺键 = falsy
        ["a && b", { a: 1, b: 1 }, true],
        ["a && b", { a: 1 }, false],
        ["a || b", { b: "x" }, true],
        ["a || b", {}, false],
        ["a && !b", { a: true }, true],
        ["(a || b) && !c", { b: true }, true],
        ["(a || b) && !c", { b: true, c: 1 }, false],
        ["!(a && b)", { a: true }, true],
        ["cite.targetKind == 'bib'", { "cite.targetKind": "bib" }, true],
        ["cite.targetKind == 'bib'", { "cite.targetKind": "figure" }, false],
        ["cite.targetKind != 'bib'", { "cite.targetKind": "figure" }, true],
        ["cite.targetKind != 'bib'", {}, true], // 缺键 != literal → true
        ["paneSide == 'zh'", { paneSide: "zh" }, true],
        ['view == "dom"', { view: "dom" }, true], // 双引号字面量
        ["a == true", { a: true }, true],
        ["a == false", { a: false }, true],
        ["a == false", {}, false], // 缺键 undefined !== false
        ["a.b-c_d", { "a.b-c_d": 7 }, true], // 键含 . - _
    ];
    for (const [src, ctx, want] of cases)
        it(`${src} → ${want}`, () => {
            expect(evalWhen(src, ctx)).toBe(want);
        });
});

describe("when syntax errors (compile-time throw)", () => {
    const bad = [
        "a &&",
        "(a",
        "a == 42", // 数字字面量不支持
        "a b",
        "a ==",
        "&& a",
        "a ||| b",
        "'unclosed",
        "a === 'x'", // 三等于非法
        "",
    ];
    for (const src of bad)
        it(`rejects ${JSON.stringify(src)}`, () => {
            expect(() => compileWhen(src)).toThrow();
        });
    it("register() also throws on bad when", () => {
        const r = new Registry();
        expect(() =>
            r.register({ id: "x", title: "x", when: "a &&", run: () => {} }),
        ).toThrow();
        expect(r.size).toBe(0); // 半注册态不留
    });
});

describe("when cache + whenKeys", () => {
    it("compiles once per source", () => {
        const src = "sel.text && !caps.assist && chunk.intSeq";
        const n0 = whenCacheSize();
        compileWhen(src);
        expect(whenCacheSize()).toBe(n0 + 1);
        compileWhen(src);
        expect(whenCacheSize()).toBe(n0 + 1);
    });
    it("whenKeys extracts all referenced keys", () => {
        expect(
            whenKeys("cite.targetKind == 'bib' && (cite.entryText || cite.cardFillable)").sort(),
        ).toEqual(["cite.cardFillable", "cite.entryText", "cite.targetKind"]);
        expect(whenKeys("!a && !(b || c)")).toEqual(["a", "b", "c"]);
        expect(whenKeys("view == 'dom'")).toEqual(["view"]);
    });
});

// ============================================================ Registry 语义

const mk = (
    id: string,
    over: Partial<Command> = {},
): Command => ({ id, title: `menu.${id}`, run: () => {}, ...over });

describe("Registry", () => {
    it("duplicate id rejected at register time", () => {
        const r = new Registry().register(mk("a"));
        expect(() => r.register(mk("a"))).toThrow(/duplicate/);
    });
    it("unregister removes + is idempotent-false on second call", () => {
        const r = new Registry().register(mk("a"));
        expect(r.unregister("a")).toBe(true);
        expect(r.unregister("a")).toBe(false);
        expect(r.size).toBe(0);
    });
    it("visible = when pass; enabled = when + enableWhen", () => {
        const r = new Registry()
            .register(mk("v1", { when: "a" }))
            .register(mk("v2", { when: "b" }))
            .register(mk("v3", { when: "a", enableWhen: "en" }));
        const ctx = { a: 1 };
        expect(r.visible(ctx).map((c) => c.id)).toEqual(["v1", "v3"]);
        expect(r.enabled(ctx).map((c) => c.id)).toEqual(["v1"]);
        // enableWhen 满足后启用——visible 集不变（disabled 不 hidden）
        expect(
            r.enabled({ a: 1, en: 1 }).map((c) => c.id),
        ).toEqual(["v1", "v3"]);
        // eval() = 可见集别名
        expect(r.eval(ctx).map((c) => c.id)).toEqual(["v1", "v3"]);
    });
    it("run() refuses invisible/disabled; runUnchecked bypasses gates", async () => {
        const log: string[] = [];
        const r = new Registry()
            .register({ ...mk("a", { when: "x" }), run: () => void log.push("a") })
            .register({ ...mk("b", { enableWhen: "en" }), run: () => void log.push("b") });
        expect(await r.run("a", {})).toBe(false);
        expect(await r.run("b", {})).toBe(false); // enableWhen 未满足
        expect(log).toEqual([]);
        expect(await r.run("b", { en: 1 })).toBe(true);
        expect(await r.runUnchecked("a", {})).toBe(true);
        expect(await r.run("missing", {})).toBe(false);
        expect(log).toEqual(["b", "a"]);
    });
    it("byKey dispatches first when+enabled match in register order", async () => {
        const log: string[] = [];
        const r = new Registry()
            .register({ ...mk("a", { keys: ["s"], when: "x" }), run: () => void log.push("a") })
            .register({ ...mk("b", { keys: ["s"] }), run: () => void log.push("b") });
        const hit = r.byKey("s", {});
        expect(hit?.id).toBe("b"); // a 的 when 不过 → 落到 b
        const hit2 = r.byKey("s", { x: 1 });
        expect(hit2?.id).toBe("a"); // 注册序优先
        expect(r.byKey("q", {})).toBeUndefined();
    });
});

// ============================================================ commands 表审计

describe("registerCommands (menu-spec 18)", () => {
    const reg = () => registerCommands(new Registry<CmdCtx>());

    it("registers exactly the 18 spec items, not the excluded five", () => {
        const ids = reg()
            .all()
            .map((c) => c.id);
        expect(ids.sort()).toEqual(
            [
                "sel.copy",
                "sel.copyPair",
                "sel.find",
                "cite.card",
                "cite.jump",
                "cite.copy",
                "cite.arxiv",
                "cite.doi",
                "cite.alphaxiv",
                "math.copyMathml",
                "chunk.copySrc",
                "chunk.copyZh",
                "chunk.copyPair",
                "chunk.retx",
                "chunk.copyLink",
                "pane.find",
                "pane.navBack",
                "pane.navFwd",
            ].sort(),
        );
        for (const excluded of [
            "sel.explain",
            "sel.xlat",
            "math.copyTex",
            "chunk.copyTex",
            "cite.usages",
        ])
            expect(reg().get(excluded)).toBeUndefined();
    });
    it("is idempotent — second call replaces, no dup-throw", () => {
        const r = reg();
        registerCommands(r);
        registerCommands(r);
        expect(r.size).toBe(18);
    });
    it("every when/enableWhen key ⊆ CTX_KEYS (spelling-drift audit)", () => {
        expect(auditWhenKeys([...reg().all()], CTX_KEYS)).toEqual([]);
    });
    it("every id has MENU_LABELS zh+en and a known sec", () => {
        const secs = new Set<string>(SECTION_ORDER);
        for (const c of reg().all()) {
            expect(MENU_LABELS[c.id], c.id).toBeTruthy();
            expect(MENU_LABELS[c.id]!.zh).toBeTruthy();
            expect(MENU_LABELS[c.id]!.en).toBeTruthy();
            expect(secs.has(c.sec!), `${c.id}.sec`).toBe(true);
            expect(c.title).toBe(`menu.${c.id}`);
        }
    });
    it("chunk.retx: pending → visible-but-disabled (enableWhen 语义)", () => {
        // node 环境无 DOM——手工造最小 HitCtx 形状（snapshotHit 在 jsdom 测试
        // 里另有覆盖；此处只喂谓词层关心的字段）
        const hit = {
            sel: { text: "", trimmed: "", inChunk: false, chunks: [], range: null },
            cite: {
                targetKind: null,
                targetExists: false,
                bibkey: null,
                entryText: null,
                cardFillable: false,
                arxivId: null,
                doi: null,
                targetId: null,
                targetEl: null,
                anchorEl: null,
            },
            math: { tex: null, mathml: null, el: null },
            chunk: {
                key: "S1.p4",
                intSeq: 7,
                kind: "section",
                el: null,
                counterpartAvail: false,
                pending: true,
                hasText: true,
                hasEn: true,
                hasZh: false,
                zhUntranslated: false,
                hasNontext: false,
                hasPh: false,
            },
            view: "dom",
            paneSide: "en",
            caps: {
                findInPane: false,
                assist: false,
                retx: true,
                discover: false,
                navBack: false,
                navFwd: false,
                linkScheme: false,
            },
            target: null,
        } as unknown as ReturnType<typeof snapshotHit>;
        const ctx = makeCmdCtx(hit, {});
        const r = reg();
        const ids = (list: Command<CmdCtx>[]) => list.map((c) => c.id);
        expect(ids(r.visible(ctx))).toContain("chunk.retx"); // pending 仍可见
        expect(ids(r.enabled(ctx))).not.toContain("chunk.retx"); // 但禁用
        // chunk.intSeq 布尔化谓词键可直读
        expect(evalWhen("chunk.intSeq", ctx)).toBe(true);
        expect(evalWhen("chunk.pending", ctx)).toBe(true);
    });
    it("assist 恒 false——caps.assist 谓词键存在且为假", () => {
        expect(CTX_KEYS).toContain("caps.assist");
        expect(CTX_KEYS).toContain("caps.findInPane");
    });
});
