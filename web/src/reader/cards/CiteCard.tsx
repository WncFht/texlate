// CiteCard —— 引用悬浮卡：锚定链接位置的 fixed 弹层 + 条目内容。
// 时序/a11y（Wikipedia PagePreviews + WCAG 1.4.13）：
//   开卡 dwell 150ms / 关卡宽限 350ms 在宿主 pane 侧（它持有锚与卡片两侧
//   的指针态）；本组件管 Esc 可关、指针可移入（.cite-card 类是 pane 委托
//   pointerout 判 relatedTarget 的锚）、下方不足自动翻上。
// 滚动即关：pdf.js annotationLayer 会随 LRU 逐出/重排销毁，死锚卡比
// 跟随滚动更坑——宿主在 scroll/scalechanging/pagesdestroy 上统一收。

import { onCleanup, onMount, Show, type JSX } from "solid-js";

import type { BibEntry, RefMeta } from "../cite/citations";
import { usagesText } from "../cite/usages";
import RefTaskChip from "./RefTaskChip";
import type { TaskSnapshot } from "../../api/client";
import { t } from "../../i18n";

const CARD_W = 380;
const GAP = 6;

interface CardProps {
    /** 锚元素的视口 rect（开卡时刻快照；跨行链接取首个 clientRect） */
    rect: DOMRect;
    onClose(): void;
    /** 指针进出卡片——宿主用它续/启宽限关计时（hoverable 必需） */
    onCardEnter?(): void;
    onCardLeave?(): void;
    children: JSX.Element;
}

export default function CiteCard(props: CardProps) {
    let el!: HTMLDivElement;

    // 首渲按「锚下方」放，onMount 量高后不够再翻上——避免先量后渲的空帧
    const initLeft = () => {
        const w = Math.min(CARD_W, window.innerWidth - 16);
        return Math.min(
            Math.max(8, props.rect.left),
            window.innerWidth - w - 8,
        );
    };
    const initTop = () => props.rect.bottom + GAP;

    onMount(() => {
        const h = el.offsetHeight;
        const below = window.innerHeight - props.rect.bottom;
        if (
            below < h + GAP + 8 &&
            props.rect.top > below &&
            props.rect.top - h - GAP >= 8
        ) {
            el.style.top = `${props.rect.top - h - GAP}px`;
        } else {
            el.style.top = `${Math.min(initTop(), window.innerHeight - h - 8)}px`;
        }
    });

    onMount(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") {
                e.stopPropagation();
                props.onClose();
            }
        };
        // capture 先于 ReaderView 的全局 Esc（帮助层语义无碍——卡优先收）
        document.addEventListener("keydown", onKey, true);
        onCleanup(() => document.removeEventListener("keydown", onKey, true));
    });

    return (
        <div
            ref={(n) => (el = n)}
            class="cite-card"
            role="dialog"
            aria-label={t.cite.cardAria}
            style={{
                left: `${initLeft()}px`,
                top: `${initTop()}px`,
                width: `${Math.min(CARD_W, window.innerWidth - 16)}px`,
            }}
            onPointerEnter={() => props.onCardEnter?.()}
            onPointerLeave={() => props.onCardLeave?.()}
        >
            {props.children}
        </div>
    );
}

// ---------------------------------------------------------------- 条目内容

interface BodyProps {
    /** L0 本地条目（ph 索引 / lazy dest 抽取 / DOM 克隆三路任一给文本） */
    entry?: Pick<BibEntry, "label" | "text" | "arxivId" | "doi">;
    /** L2 远端元数据活访问器——回包晚于开卡，宿主按 entry.key 现查；
        全字段空的 meta 视同缺位（整块不显） */
    meta?: () => RefMeta | undefined;
    loading?: boolean;
    notFound?: boolean;
    /** 「跳到文献表」钮——走与点击链接相同的跳转路径（压栈+镜像） */
    onJump(): void;
    /** 「N 处引用 →」切换钮（find-usages lane）——onShowUsages 给了才渲染；
        count 是目标反向索引的引用句数（0 也显示——空态是一等设计） */
    onShowUsages?(): void;
    usagesCount?: number;
    /** kept_refs 收藏态（M4）——宿主按卡 key 现查 keptRefs 快照 */
    kept?: boolean;
    /** ☆/★ 切换——给了才渲染收藏钮（payload 由宿主闭包携带） */
    onToggleKeep?(): void;
    /** 「翻译此文」提交通道（cite-translate lane）——宿主 ct.submit
        包装；缺位时 chip 仅在条目已有任务行（非 idle 相）现身 */
    onTranslate?(): void | Promise<unknown>;
    /** needs_auth CTA 覆写（缺省跳 #/reader/{taskId} 内联 key 面板） */
    onTranslateAuth?(taskId: string): void;
    /** 文献任务行覆写查询（缺省 chip 内走 taskStore.taskByArxiv） */
    refTask?(arxivId: string): TaskSnapshot | undefined;
    /** 自定义主体（dom 视图塞克隆的 li.ltx_bibitem 节点） */
    children?: JSX.Element;
}

export function CiteCardBody(props: BodyProps) {
    const e = () => props.entry;
    const meta = () => props.meta?.();
    // 全空 meta（S2 回 {} 或只剩 doi/arxivId）渲染成「· 分隔的空串行」
    // ——有任一展示字段才算有元数据块；外链判定仍走 meta() 原值
    const metaShown = () => {
        const m = meta();
        if (!m) return undefined;
        if (
            !m.title &&
            !m.tldr &&
            m.citationCount == null &&
            !m.venue &&
            !m.year &&
            !m.authors?.length
        )
            return undefined;
        return m;
    };
    return (
        <div class="cite-card-inner">
            <Show when={e()?.label}>
                <div class="cite-card-label">{e()?.label}</div>
            </Show>
            <Show when={metaShown()}>
                {(m) => (
                    <div class="cite-card-meta">
                        <Show when={m().title}>
                            <div class="cite-card-title">{m().title}</div>
                        </Show>
                        <div class="cite-card-sub">
                            {[
                                (m().authors ?? []).slice(0, 3).join(", ") +
                                    ((m().authors?.length ?? 0) > 3
                                        ? " et al."
                                        : ""),
                                m().venue,
                                m().year ? String(m().year) : "",
                                m().citationCount != null
                                    ? t.cite.citedBy.replace(
                                          "{n}",
                                          String(m().citationCount),
                                      )
                                    : "",
                            ]
                                .filter(Boolean)
                                .join(" · ")}
                        </div>
                        <Show when={m().tldr}>
                            <div class="cite-card-tldr">{m().tldr}</div>
                        </Show>
                    </div>
                )}
            </Show>
            <Show when={props.children}>
                <div class="cite-card-clone">{props.children}</div>
            </Show>
            <Show when={!props.children && e()?.text}>
                <div class="cite-card-text">{e()?.text}</div>
            </Show>
            <Show when={props.loading}>
                <div class="cite-card-text muted">{t.cite.loading}</div>
            </Show>
            <Show when={props.notFound}>
                <div class="cite-card-text muted">{t.cite.notFound}</div>
            </Show>
            <div class="cite-card-foot">
                <button
                    type="button"
                    class="cite-card-jump"
                    onClick={() => props.onJump()}
                >
                    {t.cite.jumpToBib}
                </button>
                <Show when={props.onShowUsages}>
                    <button
                        type="button"
                        class="cite-card-usages"
                        onClick={() => props.onShowUsages?.()}
                    >
                        {usagesText("gotoUsages", {
                            n: props.usagesCount ?? 0,
                        })}
                    </button>
                </Show>
                <Show when={meta()?.arxivId ?? e()?.arxivId}>
                    {(id) => (
                        <a
                            class="cite-card-ext"
                            href={`https://arxiv.org/abs/${id()}`}
                            target="_blank"
                            rel="noreferrer"
                        >
                            arXiv ↗
                        </a>
                    )}
                </Show>
                <Show when={meta()?.doi ?? e()?.doi}>
                    {(d) => (
                        <a
                            class="cite-card-ext"
                            href={`https://doi.org/${d()}`}
                            target="_blank"
                            rel="noreferrer"
                        >
                            DOI ↗
                        </a>
                    )}
                </Show>
                <Show when={props.onToggleKeep}>
                    <button
                        type="button"
                        class={`cite-card-keep${props.kept ? " on" : ""}`}
                        aria-pressed={props.kept ?? false}
                        title={props.kept ? t.cite.keepRemove : t.cite.keep}
                        aria-label={
                            props.kept ? t.cite.keepRemove : t.cite.keep
                        }
                        onClick={() => props.onToggleKeep?.()}
                    >
                        {props.kept ? "★" : "☆"}{" "}
                        {props.kept ? t.cite.kept : t.cite.keep}
                    </button>
                </Show>
                {/* 文献翻译 chip：无 arxivId 自隐；idle 相仅在宿主给
                    onTranslate 时出钮（RefTaskChip 内守） */}
                <Show when={meta()?.arxivId ?? e()?.arxivId}>
                    {(id) => (
                        <RefTaskChip
                            arxivId={id()}
                            task={
                                props.refTask
                                    ? () => props.refTask?.(id())
                                    : undefined
                            }
                            onTranslate={props.onTranslate}
                            onAuth={props.onTranslateAuth}
                        />
                    )}
                </Show>
            </div>
        </div>
    );
}
