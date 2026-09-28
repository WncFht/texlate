// LatexCard —— 公式源卡：点中渲染公式 → fixed 悬浮卡显 LaTeX 源。
// 定位骨架复刻 CiteCard（fixed、GAP=6、下不足翻上、Esc capture 先杀、
// 滚动 capture/卡外 pointerdown 关）——无 hover 关门（点击开卡非悬停，
// 卡片内容本就要求指针可移入/文本可选）。
//
// 不可信面：tex 一律 textContent 注入（载体源自 arXiv 产物，inert 但按
// 不可信处理）；不做「预览渲染」承诺——25% 源体 KaTeX 不可渲（cl-dialect）。
//
// openLatexCard() 是 features/copylatex.ts 的入口：命令层/委托监听都不
// 持有 Solid 组件树位，命令式 render 进 document.body 独立挂载点。

import { createSignal, onCleanup, onMount, Show } from "solid-js";
import { render } from "solid-js/web";

import { clText, copyText, type MathTex } from "./copylatex";

const CARD_W = 420;
const GAP = 6;

export interface LatexCardProps {
    /** 锚公式视口 rect（开卡时刻快照；多 rect 取首个） */
    rect: { left: number; top: number; right: number; bottom: number };
    /** 同步提取结果（alttext/annotation 臂）；缺省走 load() 懒载臂 */
    tex?: MathTex | null;
    /** 懒载臂（mathml-to-latex 兜底）——tex 缺席时开卡后调用补灌 */
    load?(): Promise<MathTex | null>;
    /** 行内式 → 脚行显示「带 $…$ 界符」开关（display 式恒纯体不显示） */
    inline?: boolean;
    onClose(): void;
    /** 复制成功回调（宿主 toast——字符数/approx 已算好） */
    onCopied?(chars: number, approx: boolean): void;
    /** 复制失败回调（宿主 toast——剪贴板双路皆败） */
    onCopyFail?(): void;
}

export default function LatexCard(props: LatexCardProps) {
    let el!: HTMLDivElement;
    // eslint-disable-next-line solid/reactivity -- 卡片按开卡时 tex 快照初始化
    const [src, setSrc] = createSignal<MathTex | null>(props.tex ?? null);
    const [loading, setLoading] = createSignal(
        // eslint-disable-next-line solid/reactivity -- 同上：tex/load 快照决定初始 loading 态
        props.tex == null && !!props.load,
    );
    const [withDelim, setWithDelim] = createSignal(false);
    const [copiedFlash, setCopiedFlash] = createSignal(false);
    let flashTimer = 0;

    onMount(() => {
        if (src() != null || !props.load) return;
        let alive = true;
        void props
            .load()
            .then((r) => {
                if (alive && r) setSrc(r);
            })
            .catch(() => undefined)
            .finally(() => {
                if (alive) setLoading(false);
            });
        onCleanup(() => {
            alive = false;
        });
    });

    /** 展示体 = 复制体——界符开关只作用行内式，display 恒纯体 */
    const body = (): string => {
        const tex = src()?.tex ?? "";
        if (!tex) return "";
        return props.inline && withDelim() ? `$${tex}$` : tex;
    };

    const doCopy = async () => {
        const tex = body();
        if (!tex) return;
        const ok = await copyText(tex);
        if (ok) {
            props.onCopied?.(tex.length, src()?.approx ?? false);
            setCopiedFlash(true);
            window.clearTimeout(flashTimer);
            flashTimer = window.setTimeout(() => setCopiedFlash(false), 1200);
        } else props.onCopyFail?.();
    };

    // ---- CiteCard 同款定位：首渲按「锚下方」，onMount 量高不够翻上 ----
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

    // ---- 关层三通道：Esc capture 先杀（ReaderView 全局 Esc 在 bubble 阶
    //      收不到）、滚动 capture、卡外 pointerdown ----
    onMount(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key !== "Escape") return;
            e.stopPropagation();
            props.onClose();
        };
        const onDown = (e: Event) => {
            if (!el.contains(e.target as Node)) props.onClose();
        };
        const onScroll = () => props.onClose();
        document.addEventListener("keydown", onKey, true);
        document.addEventListener("pointerdown", onDown);
        document.addEventListener("scroll", onScroll, {
            capture: true,
            passive: true,
        });
        onCleanup(() => {
            document.removeEventListener("keydown", onKey, true);
            document.removeEventListener("pointerdown", onDown);
            document.removeEventListener("scroll", onScroll, { capture: true });
            window.clearTimeout(flashTimer);
        });
    });

    return (
        <div
            ref={(n) => (el = n)}
            class="latex-card"
            role="dialog"
            aria-label={clText("reader.copyLatex.cardAria", "LaTeX 源码")}
            style={{
                left: `${initLeft()}px`,
                top: `${initTop()}px`,
                width: `${Math.min(CARD_W, window.innerWidth - 16)}px`,
            }}
        >
            <div class="latex-card-inner">
                <Show
                    when={src()}
                    fallback={
                        <div class="latex-empty muted">
                            {loading()
                                ? clText(
                                      "reader.copyLatex.loading",
                                      "提取源码中…",
                                  )
                                : clText(
                                      "reader.copyLatex.unavailable",
                                      "无 LaTeX 源",
                                  )}
                        </div>
                    }
                >
                    {(m) => (
                        <>
                            {/* textContent 注入——绝不 innerHTML */}
                            <pre
                                class="latex-src"
                                data-approx={m().approx || undefined}
                            >
                                {body()}
                            </pre>
                            <div class="latex-foot">
                                <button
                                    type="button"
                                    class="latex-copy"
                                    onClick={() => void doCopy()}
                                >
                                    {copiedFlash()
                                        ? clText(
                                              "reader.copyLatex.copied",
                                              "已复制",
                                          )
                                        : clText(
                                              "reader.copyLatex.copy",
                                              "复制",
                                          )}
                                </button>
                                <span class="latex-count muted">
                                    {body().length}{" "}
                                    {clText("reader.copyLatex.chars", "字符")}
                                </span>
                                <Show when={m().approx}>
                                    <span class="latex-approx">
                                        {clText(
                                            "reader.copyLatex.approx",
                                            "近似重构",
                                        )}
                                    </span>
                                </Show>
                                <Show when={props.inline}>
                                    <label class="latex-delim">
                                        <input
                                            type="checkbox"
                                            checked={withDelim()}
                                            onChange={(e) =>
                                                setWithDelim(
                                                    e.currentTarget.checked,
                                                )
                                            }
                                        />
                                        {clText(
                                            "reader.copyLatex.delim",
                                            "带 $…$ 界符",
                                        )}
                                    </label>
                                </Show>
                            </div>
                        </>
                    )}
                </Show>
            </div>
        </div>
    );
}

// ---------------------------------------------------------------- 命令式入口

export interface LatexCardHandle {
    /** 卡根元素（外部 contains 判定/dismiss 辅助用） */
    el: HTMLElement;
    close(): void;
    isOpen(): boolean;
}

/**
 * 在 document.body 下独立挂载点开卡——点击委托（features/copylatex.ts）
 * 不在 Solid 组件树内，拿不到 Portal 宿主位，用 render() 自管生命周期。
 * 同锚/异锚复开由调用方先 close 旧卡（features 层单卡模型）。
 */
export function openLatexCard(
    opts: Omit<LatexCardProps, "onClose"> & { onClose?(): void },
): LatexCardHandle {
    const host = document.createElement("div");
    host.className = "latex-card-host";
    document.body.appendChild(host);
    let open = true;
    const dispose = render(
        () => <LatexCard {...opts} onClose={() => handle.close()} />,
        host,
    );
    const handle: LatexCardHandle = {
        el: host,
        close() {
            if (!open) return;
            open = false;
            dispose();
            host.remove();
            opts.onClose?.();
        },
        isOpen: () => open,
    };
    return handle;
}
