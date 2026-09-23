// keymap —— reader 单 document keydown 分发器（exp/ss-hotkeys/keymap.js
// installProposed 移植；legacy 形态退役不进仓）。
// 顺序（每格都是可测策略点，与 spike 逐行对应）：
//   1. Ctrl/Cmd+F → ui:find（先于 inInput——findbar 输入框里再按 Ctrl+F
//      也要能重新聚焦）
//   2. findbar 内任意控件上的 Esc → esc:find（含 checkbox/按钮——修 legacy
//      只挂文本框的盲区；stopImmediatePropagation 挡 window 级 pdf.js
//      unselect——findbar Esc 不杀高亮选中）
//   3. e.isComposing → 放过（IME 组合期不抢键）
//   4. inInput → 放过（Esc 落在输入控件里不塌任何层）
//   5. Esc → EscStack 层栈塌恰好一层：
//      editor(pdf.js 选中高亮) > cite > find > menu > info > help > sel。
//      editor 是 passive 记账层——不 preventDefault/sIP，事件穿透到
//      window 级 UIManager 自己做 unselectAll（真单塌一层）；其余层
//      消费时 sIP——document bubble 截停后 window 级监听收不到，一次
//      Esc 不双塌（连带保住高亮选中）。
//   6. help modal：'?' toggle 之外全灭 + sIP——modal 独占事件管道；
//      cite/find/menu 非模态不抑制（cite 卡开时 c 仍可复制选区）
//   7. Alt+←→（无 ctrl/meta）→ nav（pdf.js 不绑 alt 变体，无冲突）
//   8. 其余修饰键 → 放过（Ctrl+T 等浏览器键不能 preventDefault）
//   9. e.repeat → 仅 [/] 放行（翻页连发），动作键去重
//  10. pdf.js editor 选中态占有 Backspace/Delete——让位给 window 级监听
//      做删除，防 nav:back+删高亮双发（legacy 实测缺陷）
//  11. 键表：t=译选段 l=查选段 c=复制|cite开卡 s=sync 1-4=mode [/]=page
//      Backspace=nav.back ?=help
//
// EscStack 接线：opts.stack 传入即用其原面（层绑定由宿主自理）；缺省
// 内部建栈并把 7 层绑到 hooks（editor→pdfjs().selected passive；
// sel→hasSelection+collapseSelection；其余→isOpen/close）。
// 日志协议：hooks.act?.("dispatch", {key, ctx, action, ms})——测试据此
// 对拍 spike CELLS/STACKS 矩阵。

import { EscStack } from "./sel/escstack";
import { collapseSelection, hasLiveSelection } from "./sel/selection";

const INPUT_RE = /^(INPUT|TEXTAREA|SELECT)$/;
const REPEAT_OK = new Set(["[", "]"]);

const inInput = (t: EventTarget | null): boolean => {
    const el = t as Element | null;
    return (
        !!el &&
        (INPUT_RE.test(el.tagName) ||
            (el as HTMLElement).isContentEditable === true)
    );
};

export interface KeymapHooks {
    /** 语义动作出口（日志/断言；分发日志 kind="dispatch"） */
    act?(kind: string, detail?: unknown): void;
    /** 浮层开关查询：'cite'|'find'|'menu'|'info'|'help' */
    isOpen?(layer: string): boolean;
    /** 关某层（sel 缺省=collapseSelection） */
    close?(layer: string): void;
    /** target 是否落在 findbar DOM 内（缺省 .findbar closest） */
    inFindbar?(target: EventTarget | null): boolean;
    /** 原生选区非坍缩（缺省 hasLiveSelection(doc)） */
    hasSelection?(): boolean;
    /** target 是否引文锚内（缺省 cite 锚词表 closest） */
    onCite?(target: EventTarget | null): boolean;
    /** pdf.js 批注编辑器态——真身接线：slick.eventBus
        'editingstateschanged'.details.hasSelectedEditor +
        store.annotationEditorMode */
    pdfjs?(): { armed?: boolean; selected?: boolean };
    /** 每次分发耗时上报 */
    timing?(ms: number): void;
}

export interface KeymapOpts {
    /** 挂载文档（缺省全局 document） */
    doc?: Document;
    /** 外部 EscStack——传入即原面使用（宿主自绑层），缺省内部建栈 */
    stack?: EscStack;
}

export interface ReaderKeys {
    /** 分发器本体（挂 doc bubble；测试可直调免 dispatchEvent） */
    onKey(e: KeyboardEvent): void;
    /** 本键位层用的 EscStack（外部传入=同一引用；缺省=内部建） */
    stack: EscStack;
    dispose(): void;
}

/** 上下文名（dispatch 日志 ctx 字段——结果矩阵行标签） */
export function ctxName(t: EventTarget | null): string {
    const el = t as Element | null;
    if (!el || el.nodeType !== 1) return "body"; // document/window 目标归 body
    const doc = el.ownerDocument;
    if (el === doc?.body || el === doc?.documentElement) return "body";
    const he = el as HTMLElement;
    if (he.closest?.(".findbar"))
        return (he as HTMLInputElement).type === "checkbox"
            ? "fbCheck"
            : he.tagName === "INPUT"
              ? "fbInput"
              : "fbBtn";
    if (he.closest?.(".cite-card")) return "cardBtn";
    if (he.closest?.(".kbd-help, .help-ov")) return "helpOv";
    if (he.closest?.(".docinfo")) return "infoOv";
    if (he.isContentEditable) return "ce";
    if (he.tagName === "TEXTAREA") return "ta";
    if (he.tagName === "SELECT") return "sel";
    if (he.tagName === "INPUT") return "input";
    // 锚/按钮先于 .pane——pane 内 cite 链须标 citeA 而非 viewer
    if (he.closest?.("a[href^='#bib.'], a.cite-ref")) return "citeA";
    if (he.tagName === "A") return "link";
    if (he.tagName === "BUTTON") return "btn";
    if (he.closest?.(".pane")) return "viewer";
    return he.className
        ? String(he.className).split(" ")[0]!
        : he.tagName;
}

export function attachReaderKeys(
    hooks: KeymapHooks = {},
    opts: KeymapOpts = {},
): ReaderKeys {
    const doc = opts.doc ?? document;
    const inFindbar =
        hooks.inFindbar ??
        ((t: EventTarget | null) =>
            !!(t as Element | null)?.closest?.(".findbar"));
    const hasSelection =
        hooks.hasSelection ?? (() => hasLiveSelection(doc));
    const onCite =
        hooks.onCite ??
        ((t: EventTarget | null) =>
            !!(t as Element | null)?.closest?.(
                "a[href^='#bib.'], a.cite-ref, .ltx_cite",
            ));
    const pdfjs = hooks.pdfjs ?? (() => ({ armed: false, selected: false }));

    // EscStack：外部传入用原面；缺省内部建栈把 7 层绑到 hooks。
    const stack = opts.stack ?? new EscStack();
    if (!opts.stack) {
        stack.bind("editor", {
            isOpen: () => !!pdfjs().selected,
            passive: true, // 只记账——事件穿透给 window 级 UIManager
        });
        for (const layer of ["cite", "find", "menu", "info", "help"] as const)
            stack.bind(layer, {
                isOpen: () => hooks.isOpen?.(layer) ?? false,
                close: () => hooks.close?.(layer),
            });
        stack.bind("sel", {
            isOpen: () => hasSelection(),
            close: () => {
                if (hooks.close) hooks.close("sel");
                else collapseSelection(doc);
            },
        });
    }

    const onKey = (e: KeyboardEvent): void => {
        const t0 = performance.now();
        const ctx = ctxName(e.target);
        const done = (action: string) =>
            hooks.act?.("dispatch", {
                key: e.key,
                ctx,
                action,
                ms: performance.now() - t0,
            });
        const pass = () =>
            hooks.act?.("dispatch", {
                key: e.key,
                ctx,
                action: "pass",
                ms: performance.now() - t0,
            });

        // 1. Ctrl/Cmd+F
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "f") {
            e.preventDefault();
            done("ui:find");
            return;
        }
        // 2. findbar 内 Esc（含 checkbox/按钮——修 legacy 盲区；sIP 挡
        //    window 级 pdf.js unselect）
        if (e.key === "Escape" && inFindbar(e.target)) {
            e.preventDefault();
            e.stopImmediatePropagation();
            hooks.close?.("find");
            done("esc:find");
            return;
        }
        // 3. IME 组合期
        if (e.isComposing) {
            pass();
            return;
        }
        // 4. 输入控件
        if (inInput(e.target)) {
            pass();
            return;
        }
        // 5. Esc 层栈：一次恰好塌一层
        if (e.key === "Escape") {
            const col = stack.collapseTop();
            if (!col) {
                pass();
                return;
            }
            if (!col.consumed) {
                // passive（editor）：记账穿透——不动事件
                done(`esc:${col.layer}`);
                return;
            }
            e.preventDefault();
            e.stopImmediatePropagation(); // document bubble 截停——不双塌
            done(`esc:${col.layer}`);
            return;
        }
        // 6. help modal：'?' toggle 之外全灭 + sIP
        if (stack.isOpen("help")) {
            if (e.key === "?") {
                done("ui:help");
                return;
            }
            e.stopImmediatePropagation();
            pass();
            return;
        }
        // 7. Alt+←→
        if (e.altKey && !e.ctrlKey && !e.metaKey) {
            if (e.key === "ArrowLeft") {
                e.preventDefault();
                done("nav:back");
                return;
            }
            if (e.key === "ArrowRight") {
                e.preventDefault();
                done("nav:fwd");
                return;
            }
            pass();
            return;
        }
        // 8. 其余修饰键全放
        if (e.ctrlKey || e.metaKey || e.altKey) {
            pass();
            return;
        }
        // 9. 连发策略
        if (e.repeat && !REPEAT_OK.has(e.key)) {
            pass();
            return;
        }
        // 10. pdf.js 编辑器选中态占有 Backspace/Delete
        if (
            pdfjs().selected &&
            (e.key === "Backspace" || e.key === "Delete")
        ) {
            done("pdfjs:own");
            return;
        }
        // 11. 键表
        switch (e.key) {
            case "t":
            case "T":
                done(hasSelection() ? "sel:xlat" : "noop:sel");
                return;
            case "l":
            case "L":
                done(hasSelection() ? "sel:lookup" : "noop:sel");
                return;
            case "c":
            case "C":
                if (hasSelection()) {
                    done("sel:copy");
                    return;
                }
                if (onCite(e.target)) {
                    done("cite:open");
                    return;
                }
                done("noop:sel");
                return;
            case "s":
            case "S":
                done("ui:sync");
                return;
            case "1":
            case "2":
            case "3":
            case "4":
                done(`mode:${e.key}`);
                return;
            case "[":
                done("page:-1");
                return;
            case "]":
                done("page:+1");
                return;
            case "?":
                done("ui:help");
                return;
            case "Backspace":
                e.preventDefault();
                done("nav:back");
                return;
            default:
                pass();
        }
    };

    doc.addEventListener("keydown", onKey);
    return {
        onKey,
        stack,
        dispose: () => doc.removeEventListener("keydown", onKey),
    };
}
