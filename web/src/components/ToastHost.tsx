// ToastHost —— toast store 的最小宿主：App.tsx 顶层挂一处。
// 视觉沿用 .pane-toast 的 pill 口径（toast.css 落 fixed 视口底中 + For 栈）；
// role 分档沿用既有约定：err→alert，其余→status（Home/Settings form-msg
// 同口径）。action 双形：href 渲 <a>（hash 路由直跳），否则渲钮走 act()。

import { For, Show } from "solid-js";
import { toast } from "../stores/toastStore";

export default function ToastHost() {
    return (
        <div class="toast-host" aria-live="polite">
            <For each={toast.toasts()}>
                {(x) => (
                    <div
                        class={`toast t-${x.kind}`}
                        role={x.kind === "err" ? "alert" : "status"}
                        onClick={() => toast.dismiss(x.id)}
                    >
                        <span class="toast-msg">{x.text}</span>
                        <Show when={x.action}>
                            {(a) =>
                                a().href !== undefined ? (
                                    <a
                                        class="toast-act"
                                        href={a().href}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            toast.dismiss(x.id);
                                        }}
                                    >
                                        {a().label}
                                    </a>
                                ) : (
                                    <button
                                        type="button"
                                        class="toast-act"
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            toast.act(x.id);
                                        }}
                                    >
                                        {a().label}
                                    </button>
                                )
                            }
                        </Show>
                    </div>
                )}
            </For>
        </div>
    );
}
