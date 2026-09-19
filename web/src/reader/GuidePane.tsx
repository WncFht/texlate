// GuidePane —— 「导读」模式窗格：alphaXiv overview 的文档级版面。
// 取代旧 AxBlock 横幅：summary 六件套渲成字段卡、overview blog 全高排版 +
// 节锚 mini-TOC、citations 页脚——消灭 scroll-in-scroll 与字段浪费。
// available:false/错误/无 arxivId → empty 态（alphaXiv 外链仍在，不整块消失）。

import { createEffect, createSignal, For, onCleanup, Show } from "solid-js";
import { api, type AxOverview } from "../api/client";
import { t } from "../i18n";
import { loadMdLibs, type MdLibs } from "./markdown";

type State = "loading" | "empty" | "content";

type CardKey = "originalProblem" | "solution" | "keyInsights" | "results";

const CARDS: { key: CardKey; label: () => string }[] = [
    { key: "originalProblem", label: () => t.reader.guideProblem },
    { key: "solution", label: () => t.reader.guideSolution },
    { key: "keyInsights", label: () => t.reader.guideInsights },
    { key: "results", label: () => t.reader.guideResults },
];

export default function GuidePane(props: { arxivId?: string }) {
    const [ov, setOv] = createSignal<AxOverview | null>(null);
    const [state, setState] = createSignal<State>(
        props.arxivId ? "loading" : "empty",
    );
    const [libs, setLibs] = createSignal<MdLibs | null>(null);
    const [toc, setToc] = createSignal<{ el: HTMLElement; text: string }[]>([]);
    let bodyEl: HTMLElement | undefined;
    let alive = true;
    onCleanup(() => {
        alive = false;
    });

    createEffect(() => {
        const id = props.arxivId;
        if (!id) {
            setState("empty");
            return;
        }
        setState("loading");
        api.discoverOverview(id)
            .then((res) => {
                if (!alive) return;
                if (!res.available) {
                    setState("empty");
                    return;
                }
                setOv(res);
                setState("content");
                // overview markdown 在才付 marked+katex 懒加载成本
                if (res.overview) {
                    void loadMdLibs().then((l) => {
                        if (alive) setLibs(l);
                    });
                }
            })
            .catch(() => {
                if (alive) setState("empty");
            });
    });

    const axUrl = () =>
        ov()?.alphaxiv_url ?? `https://www.alphaxiv.org/abs/${props.arxivId}`;

    // overview md → 消毒 HTML + KaTeX；落地后抽 h2 建节锚 TOC（无 id 补位）
    createEffect(() => {
        const l = libs();
        const md = ov()?.overview;
        if (!l || !md || !bodyEl) return;
        bodyEl.innerHTML = l.mdToHtml(md);
        l.renderMath(bodyEl);
        setToc(
            [...bodyEl.querySelectorAll("h2")].map((h, i) => {
                if (!h.id) h.id = `guide-s${i}`;
                return { el: h, text: h.textContent ?? "" };
            }),
        );
    });

    const cardItems = (key: CardKey) => {
        const v = ov()?.summary?.[key];
        return (v ?? []).filter((x) => x?.trim());
    };

    return (
        <section class="guide" aria-label={t.reader.axDigest}>
            <div class="guide-scroll">
                <Show when={state() === "loading"}>
                    <div class="guide-skel" aria-hidden="true">
                        <i style={{ width: "34%" }} />
                        <i style={{ width: "88%" }} />
                        <i style={{ width: "76%" }} />
                        <i style={{ width: "62%" }} />
                    </div>
                </Show>

                <Show when={state() === "empty"}>
                    <div class="guide-empty">
                        <p>{t.reader.guideEmpty}</p>
                        <a
                            class="tb-btn"
                            href={axUrl()}
                            target="_blank"
                            rel="noreferrer"
                        >
                            {t.reader.guideOpen} ↗
                        </a>
                    </div>
                </Show>

                <Show when={state() === "content" && ov()}>
                    {(o) => (
                        <>
                            <header class="guide-head">
                                <span class="guide-badge">
                                    {t.reader.axDigest}
                                    <Show when={o().lang && o().lang !== "zh"}>
                                        {` · ${o().lang!.toUpperCase()}`}
                                    </Show>
                                </span>
                                <a
                                    class="guide-ax"
                                    href={axUrl()}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    {t.reader.guideOpen} ↗
                                </a>
                            </header>
                            <Show when={o().title}>
                                <h1 class="guide-title">{o().title}</h1>
                            </Show>
                            <Show when={o().summary?.feedDescription}>
                                <p class="guide-feed">
                                    {o().summary!.feedDescription}
                                </p>
                            </Show>
                            <div class="guide-cards">
                                <For each={CARDS}>
                                    {(c) => (
                                        <Show when={cardItems(c.key).length}>
                                            <section class="guide-card">
                                                <h2>{c.label()}</h2>
                                                <ul>
                                                    <For
                                                        each={cardItems(c.key)}
                                                    >
                                                        {(x) => <li>{x}</li>}
                                                    </For>
                                                </ul>
                                            </section>
                                        </Show>
                                    )}
                                </For>
                            </div>
                            <Show when={o().summary?.summary}>
                                <p class="guide-lead">{o().summary!.summary}</p>
                            </Show>
                            <div class="guide-cols">
                                <Show when={toc().length > 0}>
                                    <aside class="guide-toc">
                                        <h2>{t.reader.guideToc}</h2>
                                        <ul>
                                            <For each={toc()}>
                                                {(s) => (
                                                    <li>
                                                        <button
                                                            type="button"
                                                            onClick={() =>
                                                                s.el.scrollIntoView(
                                                                    {
                                                                        behavior:
                                                                            "smooth",
                                                                        block: "start",
                                                                    },
                                                                )
                                                            }
                                                        >
                                                            {s.text}
                                                        </button>
                                                    </li>
                                                )}
                                            </For>
                                        </ul>
                                    </aside>
                                </Show>
                                <article
                                    class="guide-body"
                                    ref={(el) => (bodyEl = el)}
                                />
                            </div>
                            <Show when={(o().citations?.length ?? 0) > 0}>
                                <footer class="guide-cites">
                                    <h2>{t.reader.guideCites}</h2>
                                    <ul>
                                        <For each={o().citations ?? []}>
                                            {(ci) => (
                                                <li>
                                                    <Show
                                                        when={ci.alphaxivLink}
                                                        fallback={
                                                            <span class="guide-cite-title">
                                                                {ci.title}
                                                            </span>
                                                        }
                                                    >
                                                        {(link) => (
                                                            <a
                                                                href={link()}
                                                                target="_blank"
                                                                rel="noreferrer"
                                                            >
                                                                {ci.title}
                                                            </a>
                                                        )}
                                                    </Show>
                                                    <Show
                                                        when={ci.justification}
                                                    >
                                                        <p>
                                                            {ci.justification}
                                                        </p>
                                                    </Show>
                                                </li>
                                            )}
                                        </For>
                                    </ul>
                                </footer>
                            </Show>
                        </>
                    )}
                </Show>
            </div>
        </section>
    );
}
