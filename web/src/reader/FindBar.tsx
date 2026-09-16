// FindBar —— 窗格内查找浮条（pdf.js findbar 对等件）。
// pdfslick 只给 PDFFindController 实例、没有 UI 封装；协议是 eventBus 事件：
//   出："find"（type 缺省=新查询 / "again"=上下一个 / "highlightallchange"=高亮开关）
//      +"findbarclose"（清除高亮）
//   入："updatefindmatchescount"/"updatefindcontrolstate"（回填 n/m 与 FindState）
// textLayerMode 默认 ENABLE，命中高亮由 pdfjs text layer 自动画。

import { createEffect, createSignal, onCleanup, Show } from "solid-js";
import type { PDFSlick } from "@pdfslick/solid";
import { t } from "../i18n/zh";
import { FIND_STATE, findCountText, type FindCount } from "./paneUtils";

interface Props {
    slick(): PDFSlick | null;
    open: boolean;
    /** 暴露输入框给宿主做 openFind 后的焦点管理 */
    inputRef?(el: HTMLInputElement): void;
    onClose(): void;
}

export default function FindBar(props: Props) {
    const [query, setQuery] = createSignal("");
    const [count, setCount] = createSignal<FindCount | null>(null);
    const [state, setState] = createSignal<number | null>(null);
    const [hlAll, setHlAll] = createSignal(true);
    const [matchCase, setMatchCase] = createSignal(false);
    const [entireWord, setEntireWord] = createSignal(false);
    const [matchDiac, setMatchDiac] = createSignal(false);

    const emit = (type?: string, findPrevious = false) => {
        const s = props.slick();
        if (!s || !props.open) return;
        s.eventBus.dispatch("find", {
            type,
            query: query(),
            phraseSearch: true,
            caseSensitive: matchCase(),
            entireWord: entireWord(),
            highlightAll: hlAll(),
            matchDiacritics: matchDiac(),
            findPrevious,
        });
    };

    // 计数/状态回填；findbarclose 后 highlightMatches 清空、状态回 FOUND
    createEffect(() => {
        const s = props.slick();
        if (!s) return;
        const onCount = (e: object) =>
            setCount((e as { matchesCount: FindCount }).matchesCount);
        const onState = (e: object) => {
            const d = e as { state: number; matchesCount?: FindCount };
            setState(d.state);
            if (d.matchesCount) setCount(d.matchesCount);
        };
        s.eventBus.on("updatefindmatchescount", onCount);
        s.eventBus.on("updatefindcontrolstate", onState);
        onCleanup(() => {
            s.eventBus.off("updatefindmatchescount", onCount);
            s.eventBus.off("updatefindcontrolstate", onState);
        });
    });

    const close = () => {
        props.slick()?.eventBus.dispatch("findbarclose", {});
        setCount(null);
        setState(null);
        props.onClose();
    };

    // 关窗→重开且带词：重发新查询把高亮找回来（pdf.js findbar 同行为）
    let wasOpen = false;
    createEffect(() => {
        const now = props.open;
        if (now && !wasOpen && query()) emit();
        wasOpen = now;
    });

    const onKeyDown = (e: KeyboardEvent) => {
        if (e.key === "Enter") {
            e.preventDefault();
            emit("again", e.shiftKey);
        } else if (e.key === "Escape") {
            e.preventDefault();
            close();
        }
    };

    const notFound = () => state() === FIND_STATE.notFound && query() !== "";

    return (
        <Show when={props.open}>
            <div class="findbar" role="search">
                <div class="fb-row">
                    <input
                        ref={(el) => props.inputRef?.(el)}
                        type="text"
                        class="fb-input"
                        classList={{ notfound: notFound() }}
                        placeholder={t.pane.findPlaceholder}
                        aria-label={t.pane.find}
                        value={query()}
                        onInput={(e) => {
                            setQuery(e.currentTarget.value);
                            emit();
                        }}
                        onKeyDown={onKeyDown}
                    />
                    <button
                        type="button"
                        class="fb-btn"
                        title={t.pane.findPrev}
                        aria-label={t.pane.findPrev}
                        disabled={!query()}
                        onClick={() => emit("again", true)}
                    >
                        ↑
                    </button>
                    <button
                        type="button"
                        class="fb-btn"
                        title={t.pane.findNext}
                        aria-label={t.pane.findNext}
                        disabled={!query()}
                        onClick={() => emit("again")}
                    >
                        ↓
                    </button>
                    <span class="fb-count" aria-live="polite">
                        {findCountText(state(), count(), query() ? t.pane.findNone : "")}
                    </span>
                    <button
                        type="button"
                        class="fb-btn"
                        title={t.pane.findClose}
                        aria-label={t.pane.findClose}
                        onClick={close}
                    >
                        ✕
                    </button>
                </div>
                <div class="fb-opts">
                    <label>
                        <input
                            type="checkbox"
                            checked={hlAll()}
                            onChange={(e) => {
                                setHlAll(e.currentTarget.checked);
                                emit("highlightallchange");
                            }}
                        />
                        {t.pane.highlightAll}
                    </label>
                    <label>
                        <input
                            type="checkbox"
                            checked={matchCase()}
                            onChange={(e) => {
                                setMatchCase(e.currentTarget.checked);
                                emit();
                            }}
                        />
                        {t.pane.matchCase}
                    </label>
                    <label>
                        <input
                            type="checkbox"
                            checked={entireWord()}
                            onChange={(e) => {
                                setEntireWord(e.currentTarget.checked);
                                emit();
                            }}
                        />
                        {t.pane.entireWord}
                    </label>
                    <label>
                        <input
                            type="checkbox"
                            checked={matchDiac()}
                            onChange={(e) => {
                                setMatchDiac(e.currentTarget.checked);
                                emit();
                            }}
                        />
                        {t.pane.matchDiacritics}
                    </label>
                </div>
            </div>
        </Show>
    );
}
