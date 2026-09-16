// App —— 手写 hash 路由（3 页，不引 router 依赖）：#/  #/reader/:id  #/settings

import { createSignal, Match, onCleanup, onMount, Switch } from "solid-js";
import Home from "./pages/Home";
import Reader from "./pages/Reader";
import Settings from "./pages/Settings";
import { t } from "./i18n/zh";

type Route = { page: "home" } | { page: "reader"; taskId: string } | { page: "settings" };

function parseHash(hash: string): Route {
    const m = hash.match(/^#\/reader\/([A-Za-z0-9_-]+)/);
    if (m) return { page: "reader", taskId: m[1] };
    if (hash.startsWith("#/settings")) return { page: "settings" };
    return { page: "home" };
}

export function nav(to: string) {
    window.location.hash = to;
}

export default function App() {
    const [route, setRoute] = createSignal<Route>(parseHash(window.location.hash));
    const onHash = () => setRoute(parseHash(window.location.hash));
    onMount(() => window.addEventListener("hashchange", onHash));
    onCleanup(() => window.removeEventListener("hashchange", onHash));

    const isReader = () => route().page === "reader";

    return (
        <div class="app">
            <nav class="topnav" classList={{ hidden: isReader() }}>
                <a href="#/" class="brand">
                    {t.appName}
                </a>
                <a href="#/" classList={{ on: route().page === "home" }}>
                    {t.nav.tasks}
                </a>
                <a href="#/settings" classList={{ on: route().page === "settings" }}>
                    {t.nav.settings}
                </a>
            </nav>
            <Switch>
                {/* keyed：#/reader/A → #/reader/B 整树重挂，不残留上个任务的状态 */}
                <Match
                    when={route().page === "reader" && (route() as { taskId: string }).taskId}
                    keyed
                >
                    {(taskId) => <Reader taskId={taskId} nav={nav} />}
                </Match>
                <Match when={route().page === "settings"}>
                    <Settings />
                </Match>
                <Match when={true}>
                    <Home nav={nav} />
                </Match>
            </Switch>
        </div>
    );
}
