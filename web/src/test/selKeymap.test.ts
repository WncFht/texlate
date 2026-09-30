// @vitest-environment jsdom
// selKeymap —— attachReaderKeys 对拍 2026-09-22 键位预研 CELLS(proposed 列)
// + STACKS 层叠剧本。pdf.js UIManager 的 window 级监听用 mimic 复刻：
//   - Esc 无 checker：选中态 Esc 即 unselect（输入框里也一样——其自身契约）
//   - Backspace/Delete 选中态删 editor（armed+editorExists 就记账，eff 区分）
//   - 未选中 + 容器内 Enter/Space → newEditor；选中态裸方向键 → translate
// dispatcher 在 document bubble；mimic 在 window——sIP 拦截面如实验证。
// jsdom 无默认打字/链接导航默认动作——input/clicks 断言只取动作面。

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { attachReaderKeys, ctxName } from "../reader/chrome/keymap";

// ------------------------------------------------------------- fixture

const FIXTURE = `
<div class="tb"><button id="tbBtn" type="button">b</button></div>
<div class="findbar" id="findbar">
  <input id="fbInput" type="text"><input id="fbHl" type="checkbox">
  <button id="fbBtn" type="button">×</button></div>
<div id="scEn" class="pane" tabindex="0" data-side="original">
  <div class="pane-html-body"><div data-chunk="S1">en body text
    <a id="citeA" href="#bib.bib1">[1]</a></div>
    <div id="ed1" tabindex="-1"></div></div></div>
<div id="scZh" class="pane" tabindex="0" data-side="translated">
  <div class="pane-html-body"><div data-chunk="S1" id="zhChunk">译文文本内容</div></div></div>
<input id="setInput" type="text">
<textarea id="ta"></textarea>
<select id="selEl"><option>1</option></select>
<div id="ce" contenteditable="true" tabindex="-1">editable</div>
<div class="cite-card"><button id="cardClose" type="button">x</button></div>
<div class="kbd-help"><button type="button">h</button></div>`;

type LayerName = "cite" | "find" | "menu" | "info" | "help";
interface St {
    armed: boolean;
    selected: boolean;
    editorExists: boolean;
}
let layers: Record<LayerName, boolean>;
let st: St;
let log: { kind: string; [k: string]: unknown }[] = [];
let keys!: ReturnType<typeof attachReaderKeys>;

const q = (sel: string) => document.querySelector<HTMLElement>(sel)!;

const selectZh = () => {
    const t = q("#zhChunk").firstChild as Text;
    document.getSelection()!.setBaseAndExtent(t, 0, t, 4);
};
const selLen = () => document.getSelection()!.toString().length;

const resetLayers = () => {
    for (const k of Object.keys(layers) as LayerName[]) layers[k] = false;
    st.armed = false;
    st.selected = false;
    st.editorExists = false;
    document.getSelection()!.removeAllRanges();
};

beforeEach(() => {
    document.body.innerHTML = FIXTURE;
    // jsdom 无 contentEditable 支持（isContentEditable undefined）——
    // 真浏览器反射 contenteditable 属性；测试面补等价属性
    Object.defineProperty(q("#ce"), "isContentEditable", {
        configurable: true,
        value: true,
    });
    layers = {
        cite: false,
        find: false,
        menu: false,
        info: false,
        help: false,
    };
    st = { armed: false, selected: false, editorExists: false };
    log = [];
    keys = attachReaderKeys({
        act: (kind, d) => log.push({ kind, ...(d as object) }),
        isOpen: (l) => layers[l as LayerName] === true,
        close: (l) => {
            if (l === "sel") document.getSelection()!.removeAllRanges();
            else layers[l as LayerName] = false;
        },
        inFindbar: (t) =>
            layers.find && !!(t as Element | null)?.closest?.(".findbar"),
        hasSelection: () => {
            const s = document.getSelection()!;
            return !s.isCollapsed && s.toString().length > 0;
        },
        onCite: (t) =>
            !!(t as Element | null)?.closest?.(
                "a[href^='#bib.'], a.cite-ref, .ltx_cite",
            ),
        pdfjs: () => st,
    });
    // FindBar 组件级 Enter → find:again（分发器让路后由输入框自己处理）
    q("#fbInput").addEventListener("keydown", (e) => {
        if (e.key === "Enter")
            log.push({ kind: "dispatch", action: "find:again" });
    });
    // pdf.js UIManager window 级监听 mimic（真实契约：textInputChecker 豁免
    // delete/backspace/字母，但 Esc 无 checker——输入框里 Esc 连带解选）
    window.addEventListener("keydown", pdfjsMimic);
});
afterEach(() => {
    keys.dispose();
    window.removeEventListener("keydown", pdfjsMimic);
    document.body.innerHTML = "";
});

function pdfjsMimic(e: KeyboardEvent) {
    if (!st.armed) return;
    const t = e.target as Element;
    const inInp =
        /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName) ||
        (t as HTMLElement).isContentEditable === true;
    if (e.key === "Escape" && st.selected) {
        // Esc 无 checker——input 里也解选
        st.selected = false;
        log.push({ kind: "pdfjs", action: "unselect", eff: true });
        return;
    }
    if (inInp) return; // textInputChecker 豁免其余键
    if (st.selected) {
        if (e.key === "Backspace" || e.key === "Delete") {
            st.editorExists = false;
            st.selected = false;
            log.push({ kind: "pdfjs", action: "delete", eff: true });
        } else if (
            /^Arrow/.test(e.key) &&
            !e.altKey &&
            !e.ctrlKey &&
            !e.metaKey
        ) {
            log.push({ kind: "pdfjs", action: "translate", eff: true });
        }
        return;
    }
    if (st.editorExists && (e.key === "Backspace" || e.key === "Delete")) {
        log.push({ kind: "pdfjs", action: "delete", eff: false }); // 空转
        return;
    }
    if ((e.key === "Enter" || e.key === " ") && t.closest?.(".pane") != null) {
        st.editorExists = true;
        st.selected = true;
        log.push({ kind: "pdfjs", action: "newEditor", eff: true });
    }
}

// ------------------------------------------------------------- ctx 摆位

type Setup = () => Element | Document;
const CTX: Record<string, Setup> = {
    body: () => document.body,
    selZh: () => {
        selectZh();
        return q("#scZh");
    },
    selZhBtn: () => {
        selectZh();
        return q("#tbBtn");
    },
    viewer: () => q("#scEn"),
    fbInput: () => {
        layers.find = true;
        return q("#fbInput");
    },
    fbCheck: () => {
        layers.find = true;
        return q("#fbHl");
    },
    setInput: () => q("#setInput"),
    ta: () => q("#ta"),
    sel: () => q("#selEl"),
    ce: () => q("#ce"),
    btn: () => q("#tbBtn"),
    citeA: () => q("#citeA"),
    card: () => {
        layers.cite = true;
        return q("#cardClose");
    },
    help: () => {
        layers.help = true;
        return document.body;
    },
    menu: () => {
        layers.menu = true;
        return document.body;
    },
    edSel: () => {
        st.armed = true;
        st.editorExists = true;
        st.selected = true;
        return q("#ed1");
    },
    edOn: () => {
        st.armed = true;
        st.editorExists = true;
        return q("#scEn");
    },
    citeAnnot: () => {
        st.armed = true;
        st.editorExists = true;
        return q("#citeA");
    },
    fbInputEd: () => {
        st.armed = true;
        st.editorExists = true;
        st.selected = true;
        layers.find = true;
        return q("#fbInput");
    },
    setInputEd: () => {
        st.armed = true;
        st.editorExists = true;
        st.selected = true;
        return q("#setInput");
    },
};

interface Cell {
    ctx: string;
    key: string;
    P: string;
    opts?: KeyboardEventInit;
    closed?: LayerName[];
    selGone?: boolean;
    prevented?: boolean;
    pdfjs?: string | null;
}

// 键位预研 CELLS 的 proposed 列（input 插入/clicks 面 jsdom 无默认动作，
// 略；全 66 格动作面保留）
const CELLS: Cell[] = [
    { ctx: "body", key: "t", P: "noop:sel" },
    { ctx: "body", key: "l", P: "noop:sel" },
    { ctx: "body", key: "c", P: "noop:sel" },
    { ctx: "body", key: "[", P: "page:-1" },
    { ctx: "body", key: "]", P: "page:+1" },
    { ctx: "body", key: "Escape", P: "pass" },
    { ctx: "selZh", key: "t", P: "sel:xlat" },
    { ctx: "selZh", key: "l", P: "sel:lookup" },
    { ctx: "selZh", key: "c", P: "sel:copy" },
    { ctx: "selZh", key: "T", P: "sel:xlat" },
    { ctx: "selZh", key: "[", P: "page:-1" },
    { ctx: "selZh", key: "Escape", P: "esc:sel", selGone: true },
    { ctx: "selZhBtn", key: "t", P: "sel:xlat" },
    { ctx: "selZhBtn", key: "c", P: "sel:copy" },
    { ctx: "fbInput", key: "t", P: "pass" },
    { ctx: "fbInput", key: "c", P: "pass" },
    { ctx: "fbInput", key: "[", P: "pass" },
    { ctx: "fbInput", key: "Enter", P: "find:again" },
    { ctx: "fbInput", key: "Escape", P: "esc:find", closed: ["find"] },
    { ctx: "fbCheck", key: "t", P: "pass" },
    { ctx: "fbCheck", key: "Escape", P: "esc:find", closed: ["find"] },
    { ctx: "body", key: "Escape", P: "esc:find", closed: ["find"] },
    { ctx: "setInput", key: "t", P: "pass" },
    { ctx: "ta", key: "l", P: "pass" },
    { ctx: "sel", key: "t", P: "pass" },
    { ctx: "ce", key: "t", P: "pass" },
    { ctx: "ce", key: "Escape", P: "pass" },
    { ctx: "setInput", key: "Escape", P: "pass" },
    { ctx: "btn", key: "t", P: "noop:sel" },
    { ctx: "btn", key: "[", P: "page:-1" },
    { ctx: "btn", key: "Escape", P: "pass" },
    { ctx: "citeA", key: "c", P: "cite:open" },
    { ctx: "citeA", key: "t", P: "noop:sel" },
    { ctx: "viewer", key: "t", P: "noop:sel" },
    { ctx: "viewer", key: "[", P: "page:-1" },
    { ctx: "card", key: "Escape", P: "esc:cite", closed: ["cite"] },
    { ctx: "card", key: "c", P: "noop:sel" },
    { ctx: "help", key: "Escape", P: "esc:help", closed: ["help"] },
    { ctx: "help", key: "[", P: "pass" },
    { ctx: "help", key: "t", P: "pass" },
    { ctx: "menu", key: "Escape", P: "esc:menu", closed: ["menu"] },
    {
        ctx: "body",
        key: "t",
        P: "pass",
        opts: { ctrlKey: true },
        prevented: false,
    },
    {
        ctx: "selZh",
        key: "t",
        P: "pass",
        opts: { ctrlKey: true },
        prevented: false,
    },
    { ctx: "setInput", key: "f", P: "ui:find", opts: { ctrlKey: true } },
    { ctx: "selZh", key: "t", P: "pass", opts: { repeat: true } },
    { ctx: "viewer", key: "[", P: "page:-1", opts: { repeat: true } },
    { ctx: "selZh", key: "t", P: "pass", opts: { isComposing: true } },
    { ctx: "body", key: "ArrowLeft", P: "nav:back", opts: { altKey: true } },
    { ctx: "body", key: "Backspace", P: "pass", opts: { repeat: true } },
    { ctx: "edSel", key: "Backspace", P: "pdfjs:own", pdfjs: "delete" },
    { ctx: "edSel", key: "Delete", P: "pdfjs:own", pdfjs: "delete" },
    { ctx: "edSel", key: "Escape", P: "esc:editor", pdfjs: "unselect" },
    { ctx: "edOn", key: "Backspace", P: "nav:back", pdfjs: "delete" },
    { ctx: "edSel", key: "[", P: "page:-1", pdfjs: null },
    { ctx: "edSel", key: "t", P: "noop:sel", pdfjs: null },
    { ctx: "edSel", key: "l", P: "noop:sel", pdfjs: null },
    { ctx: "edSel", key: "ArrowLeft", P: "pass", pdfjs: "translate" },
    {
        ctx: "edSel",
        key: "ArrowLeft",
        P: "nav:back",
        opts: { altKey: true },
        pdfjs: null,
    },
    { ctx: "edOn", key: "Enter", P: "pass", pdfjs: "newEditor" },
    { ctx: "edOn", key: " ", P: "pass", pdfjs: "newEditor" },
    { ctx: "citeAnnot", key: "Enter", P: "pass", pdfjs: "newEditor" },
    { ctx: "citeA", key: "Enter", P: "pass" },
    { ctx: "fbInputEd", key: "Backspace", P: "pass", pdfjs: null },
    {
        ctx: "fbInputEd",
        key: "Escape",
        P: "esc:find",
        pdfjs: null,
        closed: ["find"],
    },
    { ctx: "setInputEd", key: "Escape", P: "pass", pdfjs: "unselect" },
    { ctx: "setInputEd", key: "t", P: "pass", pdfjs: null },
];

describe("CELLS matrix (proposed column)", () => {
    for (const c of CELLS) {
        it(`${c.ctx} + ${JSON.stringify(c.key)} → ${c.P}`, () => {
            resetLayers();
            log = [];
            // pre:'find' 格：body+Escape 但 findbar 先开着
            if (c.ctx === "body" && c.key === "Escape" && c.closed)
                layers.find = true;
            const target = CTX[c.ctx]!();
            const e = new KeyboardEvent("keydown", {
                key: c.key,
                bubbles: true,
                cancelable: true,
                ...c.opts,
            });
            target.dispatchEvent(e);
            const acts = log
                .filter((x) => x.kind === "dispatch")
                .map((x) => x.action);
            const sig = acts.filter((a) => a !== "pass");
            if (c.P === "pass") expect(sig).toEqual([]);
            else expect(sig).toEqual([c.P]);
            if (c.closed)
                for (const l of c.closed) expect(layers[l]).toBe(false);
            if (c.selGone) expect(selLen()).toBe(0);
            if (c.prevented === false) expect(e.defaultPrevented).toBe(false);
            if (c.pdfjs !== undefined) {
                const pact = log
                    .filter((x) => x.kind === "pdfjs")
                    .map((x) => x.action);
                if (c.pdfjs === null) expect(pact).toEqual([]);
                else expect(pact).toContain(c.pdfjs);
            }
        });
    }
});

// ------------------------------------------------------------- STACKS

describe("STACKS — Esc 层叠剧本（每 Esc 恰塌一层）", () => {
    const escSeq = (
        open: LayerName[],
        opts: { edSel?: boolean; focusBody?: boolean } = {},
    ) => {
        resetLayers();
        log = [];
        if (opts.edSel) {
            st.armed = true;
            st.editorExists = true;
            st.selected = true;
        }
        for (const l of open) layers[l] = true;
        // editor+find 剧本焦点在 fbInput：第一发 findbar-Esc（find 关）后
        // 焦点仍滞留框内——第二发 inFindbar 假（层已关）→ inInput 让路 →
        // window 级 pdf.js unselect 记 'editor'（Esc 无 checker 契约）
        const target = opts.focusBody ? document.body : q("#fbInput");
        const seq: string[][] = [];
        let consumed = 0;
        for (let i = 0; i < 2; i++) {
            target.dispatchEvent(
                new KeyboardEvent("keydown", {
                    key: "Escape",
                    bubbles: true,
                    cancelable: true,
                }),
            );
            const evs = log
                .filter(
                    (x) =>
                        (x.kind === "dispatch" &&
                            x.key === "Escape" &&
                            String(x.action).startsWith("esc:")) ||
                        (x.kind === "pdfjs" && x.action === "unselect"),
                )
                .map((x) =>
                    x.kind === "pdfjs" ? "editor" : String(x.action).slice(4),
                );
            seq.push([...new Set(evs.slice(consumed))]);
            consumed = evs.length;
        }
        return seq;
    };

    it("cite+help → [[cite],[help]]", () => {
        expect(escSeq(["cite", "help"], { focusBody: true })).toEqual([
            ["cite"],
            ["help"],
        ]);
    });
    it("menu+help → [[menu],[help]]（legacy 双塌修复点）", () => {
        expect(escSeq(["menu", "help"], { focusBody: true })).toEqual([
            ["menu"],
            ["help"],
        ]);
    });
    it("info+menu → [[menu],[info]]", () => {
        expect(escSeq(["info", "menu"], { focusBody: true })).toEqual([
            ["menu"],
            ["info"],
        ]);
    });
    it("cite+find(focus body) → [[cite],[find]]", () => {
        expect(escSeq(["cite", "find"], { focusBody: true })).toEqual([
            ["cite"],
            ["find"],
        ]);
    });
    it("editor+cite → [[editor],[cite]]（editor 最内层先塌）", () => {
        expect(escSeq(["cite"], { edSel: true, focusBody: true })).toEqual([
            ["editor"],
            ["cite"],
        ]);
    });
    it("editor+find(focus fb) → [[find],[editor]]（findbar Esc 先行）", () => {
        expect(escSeq(["find"], { edSel: true })).toEqual([
            ["find"],
            ["editor"],
        ]);
    });
});

// ------------------------------------------------------------- ctxName

describe("ctxName", () => {
    it("maps repo class vocab to ctx labels", () => {
        expect(ctxName(document.body)).toBe("body");
        expect(ctxName(q("#fbInput"))).toBe("fbInput");
        expect(ctxName(q("#fbHl"))).toBe("fbCheck");
        expect(ctxName(q("#fbBtn"))).toBe("fbBtn");
        expect(ctxName(q("#cardClose"))).toBe("cardBtn");
        expect(ctxName(q(".kbd-help button"))).toBe("helpOv");
        expect(ctxName(q("#ce"))).toBe("ce");
        expect(ctxName(q("#ta"))).toBe("ta");
        expect(ctxName(q("#selEl"))).toBe("sel");
        expect(ctxName(q("#setInput"))).toBe("input");
        expect(ctxName(q("#scEn"))).toBe("viewer");
        expect(ctxName(q("#citeA"))).toBe("citeA");
        expect(ctxName(q("#tbBtn"))).toBe("btn");
    });
});
