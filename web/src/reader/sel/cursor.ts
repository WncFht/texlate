// cursor —— 键盘-only「选句→翻译→复制」句游标模态（exp/ss-a11y/cursor.js
// 移植，roving 为主形态；ad=aria-activedescendant 备选保留）。
//
// 契约（两形态共享同一键面，差异只在焦点载体）：
//   进入：pane 聚焦时按 v（Visual/游标模式）——现键面 1/2/3/4/s/[/]/?
//        /Backspace/Alt+←→/Ctrl+F 全不占 v/c/t/y/j/k/Enter/Esc。
//   移动：j/↓ 下一句；k/↑ 上一句；]/l 下一块首句；[/h 上一块首句；
//        Home/End 首/末句。端点停住并报「首/末句已达」（不环绕）。
//   选句：Enter 在 cursor ↔ selected 间翻转——真 Selection 落在句 Range
//        上（marker_i→marker_{i+1}），视觉 = 原生选区高亮，零样式债。
//   翻译：t = 取对侧窗格同 sid 对齐句 → payload 换 zh/en 并宣读。
//   复制：c（或 Ctrl+C）→ clipboard.writeText(payload)；无显式选择时
//        payload = 游标句原文——游标即隐含选择，Enter 只是确认/高亮。
//   退出：Esc → idle + 焦点回 pane（roving）；Tab → 不拦截自然走——出
//        模式落到文档序下一可停点（无键盘陷阱 WCAG 2.1.2）。
//   重入：记 last 游标——二次 v 回到上次句位。
// 模态内按键不透给全局键面（acted → preventDefault+stopImmediatePropagation：
// 全局键面同挂 document bubble，同节点后注册监听唯 sIP 能挡）。

import type { SentMark } from "./sentseg";

const INPUT_RE = /^(INPUT|TEXTAREA|SELECT)$/;

export interface CursorHooks {
    act?(kind: string, detail?: unknown): void;
    timing?(ms: number): void;
}

export interface CursorDeps {
    /** 本侧 .pane scrollEl（focus 宿主/AD 宿主） */
    pane: HTMLElement;
    /** 本侧 body（v 进门判定域） */
    body: Element;
    /** 本侧 SentMark[]（sentseg.segmentDoc 产物） */
    sents: SentMark[];
    /** 对侧 pane SentMark[]（translate 对齐查找） */
    otherSents?: SentMark[];
    /** aria-live 宣读元素（缺省静默） */
    live?: HTMLElement | null;
    hooks?: CursorHooks;
    /** 'roving'（真焦点漫游）| 'ad'（aria-activedescendant） */
    variant?: "roving" | "ad";
    /** 缺省 pane.ownerDocument */
    doc?: Document;
}

export interface CursorState {
    mode: "idle" | "cursor" | "selected";
    cur: number;
    payload: { text: string; side: string | null } | null;
    selected: number;
}

export interface Cursor {
    state: CursorState;
    /** 键位分发：'handled' | 'exit-tab' | null——挂 document bubble */
    onKey(e: KeyboardEvent): string | null;
    enter(): void;
    exit(refocus?: boolean): void;
    dispose(): void;
}

export function makeCursor(deps: CursorDeps): Cursor {
    const {
        pane,
        body,
        otherSents = [],
        sents,
        live = null,
        hooks,
        variant = "roving",
    } = deps;
    const doc = deps.doc ?? pane.ownerDocument!;

    const state: CursorState = {
        mode: "idle",
        cur: -1,
        payload: null,
        selected: -1,
    };

    const say = (msg: string) => {
        if (live) {
            live.textContent = "";
            live.textContent = msg;
        }
        hooks?.act?.("say", { msg });
    };
    const cur = () => sents[state.cur];

    const rangeOf = (idx: number): Range => {
        const m = sents[idx]!;
        const r = doc.createRange();
        r.setStartAfter(m.marker);
        const nx = sents[idx + 1];
        if (nx && nx.chunkEl === m.chunkEl) r.setEndBefore(nx.marker);
        else r.setEndAfter(m.chunkEl.lastChild ?? m.chunkEl);
        return r;
    };
    const textOf = (idx: number): string =>
        rangeOf(idx)
            .toString()
            .replace(/^\s+|\s+$/g, "");

    const paintCursor = () => {
        for (const s of sents) s.marker.classList.remove("cur", "sel");
        const m = cur();
        if (!m) return;
        m.marker.classList.add("cur");
        if (state.selected === state.cur) m.marker.classList.add("sel");
        if (variant === "ad") {
            pane.setAttribute("aria-activedescendant", m.marker.id);
            m.marker.setAttribute("aria-selected", "true");
        }
    };

    const place = (idx: number, announce = true) => {
        if (!sents.length) return;
        state.cur = Math.max(0, Math.min(sents.length - 1, idx));
        const m = cur()!;
        paintCursor();
        const t0 = performance.now();
        if (variant === "roving") {
            m.marker.focus({ preventScroll: false });
        } else {
            m.marker.scrollIntoView({ block: "nearest" });
        }
        hooks?.timing?.(performance.now() - t0);
        if (announce)
            say(
                `S${state.cur + 1}/${sents.length}: ${textOf(state.cur).slice(0, 80)}`,
            );
        state.payload = {
            text: textOf(state.cur),
            side: pane.getAttribute("data-side"),
        };
    };

    const firstVisible = (): number => {
        const top = pane.getBoundingClientRect().top;
        for (let i = 0; i < sents.length; i++) {
            if (sents[i]!.marker.getBoundingClientRect().bottom >= top)
                return i;
        }
        return 0;
    };

    const enter = () => {
        if (state.mode !== "idle" || !sents.length) return;
        state.mode = "cursor";
        pane.classList.add("cursor-on");
        const at = state.cur >= 0 ? state.cur : firstVisible();
        place(at);
        hooks?.act?.("mode", { mode: "cursor", at: state.cur });
    };
    const exit = (refocus = true) => {
        state.mode = "idle";
        state.selected = -1;
        pane.classList.remove("cursor-on");
        for (const s of sents) s.marker.classList.remove("cur", "sel");
        doc.getSelection?.()?.removeAllRanges();
        if (variant === "ad") pane.removeAttribute("aria-activedescendant");
        if (refocus && variant === "roving") pane.focus();
        hooks?.act?.("mode", { mode: "idle" });
    };

    // 块跳：chunkIdx 是枚举序但空句块（figure/table/空段）在 sents 里无
    // 项——精确匹配 chunkIdx===target 会 -1 越界。预建 chunkIdx→首句索引
    // 表，朝 d 方向扫最近有句块（163 块里实测有无句块——figure 即坑）。
    const chunkFirst = new Map<number, number>();
    sents.forEach((s, i) => {
        if (!chunkFirst.has(s.chunkIdx)) chunkFirst.set(s.chunkIdx, i);
    });
    const jumpChunk = (d: number) => {
        const ci = cur()?.chunkIdx ?? 0;
        const maxCi = sents.at(-1)?.chunkIdx ?? 0;
        for (let t = ci + d; t >= 0 && t <= 100000; t += d) {
            if (chunkFirst.has(t)) return place(chunkFirst.get(t)!);
            if (t > maxCi + 1) break;
        }
        return place(d > 0 ? sents.length - 1 : 0);
    };

    const select = () => {
        const sel = doc.getSelection?.();
        if (state.selected === state.cur) {
            // 翻转取消
            sel?.removeAllRanges();
            state.selected = -1;
            state.mode = "cursor";
            paintCursor();
            say("deselected");
            return;
        }
        const r = rangeOf(state.cur);
        sel?.setBaseAndExtent(
            r.startContainer,
            r.startOffset,
            r.endContainer,
            r.endOffset,
        );
        r.detach();
        state.selected = state.cur;
        state.mode = "selected";
        paintCursor();
        state.payload = {
            text: textOf(state.cur),
            side: pane.getAttribute("data-side"),
        };
        say(`selected: ${state.payload.text.slice(0, 80)}`);
        hooks?.act?.("select", { idx: state.cur });
    };

    const translate = () => {
        const m = cur();
        if (!m) return;
        const oi = otherSents.findIndex((s) => s.sid === m.sid);
        if (oi < 0) {
            say("no aligned sentence");
            return;
        }
        const hit = otherSents[oi]!;
        const r = doc.createRange();
        r.setStartAfter(hit.marker);
        const nx = otherSents[oi + 1];
        if (nx && nx.chunkEl === hit.chunkEl) r.setEndBefore(nx.marker);
        else r.setEndAfter(hit.chunkEl.lastChild ?? hit.chunkEl);
        const alt = r.toString().replace(/^\s+|\s+$/g, "");
        r.detach();
        state.payload = {
            text: alt,
            side: hit.marker.closest(".pane")?.getAttribute("data-side") ?? null,
        };
        say(`translation: ${alt.slice(0, 80)}`);
        hooks?.act?.("translate", { sid: m.sid, len: alt.length });
    };

    const copy = async () => {
        const p = state.payload ?? {
            text: textOf(state.cur),
            side: pane.getAttribute("data-side"),
        };
        let ok = true;
        try {
            await navigator.clipboard.writeText(p.text);
        } catch {
            ok = false; // 权限/上下文拒——hook 面仍记账供断言
        }
        say(`copied ${p.side}: ${p.text.slice(0, 60)}`);
        hooks?.act?.("copy", { side: p.side, len: p.text.length, ok });
    };

    /** 分发：'handled'|'exit-tab'|null。挂 document bubble（同 ReaderView）。 */
    const onKey = (e: KeyboardEvent): string | null => {
        const t0 = performance.now();
        const tgt = e.target as Element | null;
        const inInput =
            !!tgt &&
            (INPUT_RE.test(tgt.tagName) ||
                (tgt as HTMLElement).isContentEditable === true);
        // 模式外：只有本 pane 聚焦时的 v 进门
        if (state.mode === "idle") {
            if (
                (e.key === "v" || e.key === "V") &&
                !e.ctrlKey &&
                !e.metaKey &&
                !e.altKey &&
                (tgt === pane || body.contains(tgt))
            ) {
                e.preventDefault();
                enter();
                hooks?.timing?.(performance.now() - t0);
                return "handled";
            }
            return null;
        }
        // 模式内：Tab 不拦（自然出模式）；输入控件聚焦时全让路
        if (e.key === "Tab") {
            exit(false); // 焦点交给自然序——不 refocus
            return "exit-tab";
        }
        if (inInput) {
            exit(false);
            return null;
        }
        const k = e.key;
        let acted = true;
        if ((e.ctrlKey || e.metaKey) && k.toLowerCase() === "c") {
            void copy();
        } else if (e.ctrlKey || e.metaKey || e.altKey) {
            return null; // 修饰组合不抢（留给 Ctrl+F 等）
        } else
            switch (k) {
                case "j":
                case "ArrowDown":
                    place(state.cur + 1);
                    break;
                case "k":
                case "ArrowUp":
                    place(state.cur - 1);
                    break;
                case "]":
                case "l":
                    jumpChunk(+1);
                    break;
                case "[":
                case "h":
                    jumpChunk(-1);
                    break;
                case "Home":
                    place(0);
                    break;
                case "End":
                    place(sents.length - 1);
                    break;
                case "Enter":
                    select();
                    break;
                case "t":
                    translate();
                    break;
                case "c":
                case "y":
                    void copy();
                    break;
                case "Escape":
                    exit(true);
                    say("cursor off");
                    break;
                default:
                    acted = false;
            }
        if (acted) {
            e.preventDefault();
            // sIP 而非 stopPropagation——全局键面同挂 document bubble，
            // 同节点后注册监听只有 sIP 能挡（模态按键不透给全局键面）
            e.stopImmediatePropagation();
        }
        hooks?.timing?.(performance.now() - t0);
        return acted ? "handled" : null;
    };

    doc.addEventListener("keydown", onKey);
    return {
        state,
        onKey,
        enter,
        exit,
        dispose: () => doc.removeEventListener("keydown", onKey),
    };
}
