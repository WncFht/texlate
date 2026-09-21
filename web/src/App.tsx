// App —— 手写 hash 路由（5 页，不引 router 依赖）：#/  #/tasks  #/discover
// #/reader/:id  #/settings。Reader 是重页（pdfjs+katex+marked ~1MB）——lazy
// 路由级分包，首屏不付解析成本；落地后空闲预取，点进任务时基本即时。

import {
    createSignal,
    lazy,
    Match,
    onCleanup,
    onMount,
    Show,
    Suspense,
    Switch,
} from "solid-js";
import Home from "./pages/Home";
import Tasks from "./pages/Tasks";
import Discover from "./pages/Discover";
import Settings from "./pages/Settings";
import ThemeToggle from "./components/ThemeToggle";
import { isTerminal } from "./api/client";
import { taskStore } from "./stores/tasks";
import { t } from "./i18n";

const Reader = lazy(() => import("./pages/Reader"));

type Route =
    | { page: "home"; arxivId?: string }
    | { page: "tasks" }
    | { page: "discover" }
    | { page: "reader"; taskId: string }
    | { page: "settings" };

export function parseHash(hash: string): Route {
    const m = hash.match(/^#\/reader\/([A-Za-z0-9_-]+)/);
    if (m) return { page: "reader", taskId: m[1] };
    // #/arxiv/{id} 深链：预填首页输入框（Home 侧守卫，不自动提交）
    const a = hash.match(/^#\/arxiv\/([A-Za-z0-9][A-Za-z0-9._/-]*)/);
    if (a) {
        try {
            return { page: "home", arxivId: decodeURIComponent(a[1]) };
        } catch {
            return { page: "home", arxivId: a[1] };
        }
    }
    if (hash.startsWith("#/tasks")) return { page: "tasks" };
    if (hash.startsWith("#/discover")) return { page: "discover" };
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
        // 任务列表全局面：徽标/进行中提示/Tasks 页共享一份 store——
        // TTL 门内幂等，落地 #/reader 直开也顺手预热
        void taskStore.ensureFresh();
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
    /** 顶导航「任务」徽标：进行中（非终态）任务计数 */
    const activeCount = () =>
        taskStore.state.tasks.reduce(
            (n, x) => n + (isTerminal(x.status) ? 0 : 1),
            0,
        );

    return (
        <div class="app">
            <nav class="topnav" classList={{ hidden: isReader() }}>
                <a href="#/" class="brand">
                    {t.appName}
                </a>
                <a href="#/" classList={{ on: route().page === "home" }}>
                    {t.nav.translate}
                </a>
                <a
                    href="#/tasks"
                    classList={{ on: route().page === "tasks" }}
                >
                    {t.nav.tasks}
                    <Show when={activeCount() > 0}>
                        <span class="nav-badge">{activeCount()}</span>
                    </Show>
                </a>
                <a
                    href="#/discover"
                    classList={{ on: route().page === "discover" }}
                >
                    {t.nav.discover}
                </a>
                <a
                    href="#/settings"
                    classList={{ on: route().page === "settings" }}
                >
                    {t.nav.settings}
                </a>
                <ThemeToggle />
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
                    <Match when={route().page === "tasks"}>
                        <Tasks nav={nav} />
                    </Match>
                    <Match when={route().page === "discover"}>
                        <Discover nav={nav} />
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
