// App —— 手写 hash 路由（3 页，不引 router 依赖）：#/  #/reader/:id  #/settings
// Reader 是重页（pdfjs+katex+marked ~1MB）——lazy 路由级分包，首屏不付解析
// 成本；落地后空闲预取，点进任务时基本即时。

import {
    createSignal,
    lazy,
    Match,
    onCleanup,
    onMount,
    Suspense,
    Switch,
} from "solid-js";
import Home from "./pages/Home";
import Settings from "./pages/Settings";
import { t } from "./i18n";

const Reader = lazy(() => import("./pages/Reader"));

type Route =
    | { page: "home"; arxivId?: string }
    | { page: "reader"; taskId: string }
    | { page: "settings" };

export function parseHash(hash: string): Route {
    const m = hash.match(/^#\/reader\/([A-Za-z0-9_-]+)/);
    if (m) return { page: "reader", taskId: m[1] };
    // #/arxiv/{id} 深链：预填首页输入框 + 自动提交一次（Home 侧守卫）
    const a = hash.match(/^#\/arxiv\/([A-Za-z0-9][A-Za-z0-9._/-]*)/);
    if (a) {
        try {
            return { page: "home", arxivId: decodeURIComponent(a[1]) };
        } catch {
            return { page: "home", arxivId: a[1] };
        }
    }
    if (hash.startsWith("#/settings")) return { page: "settings" };
    return { page: "home" };
}

export function nav(to: string) {
    window.location.hash = to;
}

export default function App() {
    const [route, setRoute] = createSignal<Route>(
        parseHash(window.location.hash),
    );
    const onHash = () => setRoute(parseHash(window.location.hash));
    onMount(() => {
        window.addEventListener("hashchange", onHash);
        const ric =
            window.requestIdleCallback ??
            ((f: () => void) => window.setTimeout(f, 1500));
        ric(() => void import("./pages/Reader"));
    });
    onCleanup(() => window.removeEventListener("hashchange", onHash));

    const isReader = () => route().page === "reader";
    /** 深链参数只喂 Home——其余页不携带，narrow 后取 arxivId */
    const homeArxivId = () => {
        const r = route();
        return r.page === "home" ? r.arxivId : undefined;
    };

    return (
        <div class="app">
            <nav class="topnav" classList={{ hidden: isReader() }}>
                <a href="#/" class="brand">
                    {t.appName}
                </a>
                <a href="#/" classList={{ on: route().page === "home" }}>
                    {t.nav.tasks}
                </a>
                <a
                    href="#/settings"
                    classList={{ on: route().page === "settings" }}
                >
                    {t.nav.settings}
                </a>
            </nav>
            <Suspense
                fallback={
                    <div class="route-loading">
                        <span class="spinner" />
                        <span class="muted">{t.reader.loading}</span>
                    </div>
                }
            >
                <Switch>
                    {/* keyed：#/reader/A → #/reader/B 整树重挂，不残留上个任务的状态 */}
                    <Match
                        when={
                            route().page === "reader" &&
                            (route() as { taskId: string }).taskId
                        }
                        keyed
                    >
                        {(taskId) => <Reader taskId={taskId} nav={nav} />}
                    </Match>
                    <Match when={route().page === "settings"}>
                        <Settings />
                    </Match>
                    <Match when={true}>
                        <Home nav={nav} arxivId={homeArxivId()} />
                    </Match>
                </Switch>
            </Suspense>
        </div>
    );
}
