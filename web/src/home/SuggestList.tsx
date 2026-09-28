// SuggestList —— Home 快搜建议下拉：listbox 行（标题 + snippet）+「翻译」
// 直达深链钮。mousedown 抢在 blur 前保 click（blur 本身管「点外面关」）。
// 状态机（hits/activeHit/pickHit/键盘契约）在同簇 search.ts。

import { For, Show } from "solid-js";
import { t } from "../i18n";
import type { HomeSuggest } from "./search";

export default function SuggestList(props: {
    sg: HomeSuggest;
    nav(to: string): void;
}) {
    return (
        <Show when={props.sg.hits() !== null}>
            <ul class="ax-suggest" id="ax-suggest" role="listbox">
                <Show
                    when={props.sg.hits()!.length}
                    fallback={
                        <li class="ax-suggest-empty" role="presentation">
                            {t.home.axSearchEmpty}
                        </li>
                    }
                >
                    <For each={props.sg.hits()!}>
                        {(h, i) => (
                            <li role="presentation">
                                {/* mousedown 抢在 blur 前——阻止焦点转移
                                    保住 click；blur 本身管「点外面关」 */}
                                <button
                                    type="button"
                                    id={`ax-sug-${i()}`}
                                    role="option"
                                    aria-selected={props.sg.activeHit() === i()}
                                    class="ax-suggest-item"
                                    classList={{
                                        on: props.sg.activeHit() === i(),
                                    }}
                                    onPointerEnter={() =>
                                        props.sg.setActiveHit(i())
                                    }
                                    onMouseDown={(e) => e.preventDefault()}
                                    onClick={() => props.sg.pickHit(h)}
                                >
                                    <span class="ax-suggest-title">
                                        {h.title ?? h.paperId}
                                    </span>
                                    <Show when={h.snippet}>
                                        <span class="ax-suggest-snippet">
                                            {h.snippet}
                                        </span>
                                    </Show>
                                </button>
                                <button
                                    type="button"
                                    class="btn-ghost ax-suggest-go"
                                    onMouseDown={(e) => e.preventDefault()}
                                    onClick={() =>
                                        props.nav(`#/arxiv/${h.paperId}`)
                                    }
                                >
                                    {t.home.translate}
                                </button>
                            </li>
                        )}
                    </For>
                </Show>
            </ul>
        </Show>
    );
}
