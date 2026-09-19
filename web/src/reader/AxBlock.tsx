// AxBlock —— alphaXiv 机会型增强横幅（OG 分享卡 + AI 导读折叠）。
// 服务端 /api/discover/* 代理 alphaxiv 公共面（其 CORS 不放行浏览器直连）；
// OG 卡对任意论文实时渲染、overview 仅爆款有产物——未收录/未生成/上游挂
// 一律静默不渲染，纯增强零打扰。

import { createEffect, createSignal, onCleanup, Show } from "solid-js";
import { api, type AxOverview } from "../api/client";
import { t } from "../i18n";
import { loadMdLibs, type MdLibs } from "./markdown";

export default function AxBlock(props: { arxivId?: string }) {
    const [ov, setOv] = createSignal<AxOverview | null>(null);
    const [ogOk, setOgOk] = createSignal(true);
    const [libs, setLibs] = createSignal<MdLibs | null>(null);
    let bodyEl: HTMLDivElement | undefined;
    let alive = true;
    onCleanup(() => {
        alive = false;
    });

    createEffect(() => {
        const id = props.arxivId;
        if (!id) return;
        api.discoverOverview(id)
            .then((res) => {
                if (!alive || !res.available) return;
                setOv(res);
                // overview markdown 在才付 marked+katex 的懒加载成本
                if (res.overview) {
                    void loadMdLibs().then((l) => {
                        if (alive) setLibs(l);
                    });
                }
            })
            .catch(() => {
                /* 机会型——静默 */
            });
    });

    const axUrl = () =>
        ov()?.alphaxiv_url ?? `https://www.alphaxiv.org/abs/${props.arxivId}`;

    // overview md → 消毒 HTML + KaTeX：bodyEl 经 ref 先就位，libs 异步
    // 到位后本 effect 重跑完成渲染（details 折叠态 innerHTML 照样生效）
    createEffect(() => {
        const l = libs();
        const md = ov()?.overview;
        if (!l || !md || !bodyEl) return;
        bodyEl.innerHTML = l.mdToHtml(md);
        l.renderMath(bodyEl);
    });

    return (
        <Show when={props.arxivId && (ogOk() || ov() !== null)}>
            <section class="ax-block">
                <Show when={ogOk()}>
                    <a
                        class="ax-og"
                        href={axUrl()}
                        target="_blank"
                        rel="noreferrer"
                    >
                        <img
                            src={api.discoverOgUrl(props.arxivId!)}
                            alt={t.reader.axDigest}
                            loading="lazy"
                            onError={() => setOgOk(false)}
                        />
                    </a>
                </Show>
                <Show when={ov()}>
                    {(o) => (
                        <div class="ax-ov">
                            <div class="ax-ov-head">
                                <span class="ax-badge">
                                    {t.reader.axDigest}
                                    <Show when={o().lang === "en"}>
                                        {" · EN"}
                                    </Show>
                                </span>
                                <a
                                    class="ax-link"
                                    href={o().alphaxiv_url ?? axUrl()}
                                    target="_blank"
                                    rel="noreferrer"
                                >
                                    {t.reader.axOpen} ↗
                                </a>
                            </div>
                            <Show when={o().title}>
                                <h4 class="ax-ov-title">{o().title}</h4>
                            </Show>
                            <Show when={o().summary?.summary}>
                                <p class="ax-ov-sum">{o().summary!.summary}</p>
                            </Show>
                            <Show when={o().overview}>
                                <details class="ax-ov-full">
                                    <summary>{t.reader.axFull}</summary>
                                    <div
                                        class="ax-ov-body"
                                        ref={(el) => (bodyEl = el)}
                                    />
                                </details>
                            </Show>
                        </div>
                    )}
                </Show>
            </section>
        </Show>
    );
}
