// UsagesCard —— find-usages 悬浮卡：目标 → 全部正文引用句。
// 时序/a11y 与 CiteCard 同口径（ADR-0021）：开卡 dwell/关卡宽限在宿主
// ctl（features/findusages.attachUsages）侧；本组件管 Esc capture 可关、
// 指针可移入、下方不足自动翻上、横向夹视口。
// 句列 <ol>：序号 + en 语境句主行 + zh 配对句次行（muted），截断 ~280
// 字符（fu-context p90=408/max=1620——截断兜底而非逐句预算）。
// 空态一等设计：43% 浮动体零 \ref 是常态，不渲染成异常。
// i18n：t.usages.* 键面在 i18n lane 落地前走本地 FALLBACK——
// (t as any).usages 缺席即取当前语言内置串，键落地后零改动生效。

import { onCleanup, onMount, For, Show } from "solid-js";

import { tLane } from "../i18n";
import { cardPlacement, type UsageEntry, type UsageSite } from "./usages";

const CARD_W = 380;
const GAP = 6;
/** 语境句展示上限——过伸句（displaymath 邻接最大类）截断兜底 */
const TRUNC = 280;

// i18n 键面未落地前的内置串——key: zh/en 双语（落地键见 lane 交付 notes）
const FALLBACK: Record<"zh" | "en", Record<string, string>> = {
    zh: {
        aria: "{label} 的全部引用处",
        count: "{n} 处引用",
        empty: "正文中没有找到引用句",
        jumpTo: "跳到目标本身",
        gotoUsages: "{n} 处引用 →",
        menuItem: "查找引用",
        degraded: "键映射不可靠——仅列句",
    },
    en: {
        aria: "All usages of {label}",
        count: "{n} usages",
        empty: "No citing sentences found in the text",
        jumpTo: "Jump to target",
        gotoUsages: "{n} usages →",
        menuItem: "Find usages",
        degraded: "key mapping unreliable — sentences only",
    },
};

/** usages.* 文本解析：i18n 键在场用键，缺席回落内置串（zh/en 随 currentLang） */
export function usagesText(
    key: string,
    vars?: Record<string, string | number>,
): string {
    return tLane("usages", key, FALLBACK, vars);
}

const trunc = (s: string): string =>
    s.length > TRUNC ? `${s.slice(0, TRUNC)}…` : s;

interface CardProps {
    /** 锚 rect（figcaption 优先 + 视口夹取已在 ctl 侧完成） */
    rect: Pick<DOMRect, "left" | "right" | "top" | "bottom">;
    entry: UsageEntry;
    /** Esc 通路——宿主 ctl.close(true)（还焦点+抑制旗） */
    onClose(): void;
    onCardEnter?(): void;
    onCardLeave?(): void;
    /** 句项点击 → 跳回引用锚 */
    onJump(s: UsageSite): void;
    /** foot「跳到目标本身」 */
    onJumpTarget(): void;
    /** 句数计数显示（缺省 sites.length——degraded 模式宿主可传锚数） */
    count?: number;
}

export default function UsagesCard(props: CardProps) {
    let el!: HTMLDivElement;

    const init = () =>
        cardPlacement(
            props.rect,
            240 /* 首渲估高，onMount 精修 */,
            window.innerWidth,
            window.innerHeight,
            CARD_W,
            GAP,
        );

    onMount(() => {
        const p = cardPlacement(
            props.rect,
            el.offsetHeight,
            window.innerWidth,
            window.innerHeight,
            CARD_W,
            GAP,
        );
        el.style.top = `${p.top}px`;
        el.style.left = `${p.left}px`;
        el.dataset.placement = p.flipped ? "top" : "bottom";
    });

    onMount(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") {
                e.stopPropagation();
                props.onClose();
            }
        };
        // capture 先于 ReaderView 全局 Esc——卡优先收（CiteCard 同款）
        document.addEventListener("keydown", onKey, true);
        onCleanup(() => document.removeEventListener("keydown", onKey, true));
    });

    const count = () => props.count ?? props.entry.sites.length;

    return (
        <div
            ref={(n) => (el = n)}
            class="usage-card"
            role="dialog"
            aria-label={usagesText("aria", {
                label: props.entry.target.label,
            })}
            style={{
                left: `${init().left}px`,
                top: `${init().top}px`,
                width: `${init().width}px`,
            }}
            onPointerEnter={() => props.onCardEnter?.()}
            onPointerLeave={() => props.onCardLeave?.()}
        >
            <div class="usage-card-head">
                <span class="usage-card-label">{props.entry.target.label}</span>
                <span class="usage-card-count">
                    {usagesText("count", { n: count() })}
                </span>
            </div>
            <Show
                when={props.entry.sites.length}
                fallback={
                    <div class="usage-card-empty">{usagesText("empty")}</div>
                }
            >
                <ol class="usage-card-list">
                    <For each={props.entry.sites}>
                        {(s, i) => (
                            <li>
                                <button
                                    type="button"
                                    class="usage-card-item"
                                    onClick={() => props.onJump(s)}
                                >
                                    <span class="usage-card-idx">
                                        {i() + 1}.
                                    </span>
                                    <span class="usage-card-sents">
                                        <span class="usage-card-sent">
                                            {trunc(s.text)}
                                        </span>
                                        <Show when={s.zhText}>
                                            <span class="usage-card-sent-zh">
                                                {trunc(s.zhText ?? "")}
                                            </span>
                                        </Show>
                                    </span>
                                </button>
                            </li>
                        )}
                    </For>
                </ol>
            </Show>
            <div class="usage-card-foot">
                <button
                    type="button"
                    class="usage-card-jump"
                    onClick={() => props.onJumpTarget()}
                >
                    {usagesText("jumpTo")}
                </button>
            </div>
        </div>
    );
}
