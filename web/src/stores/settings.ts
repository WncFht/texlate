// BYOK 设置 store —— GET 永不回 key 本体，只回 has_api_key（§2.5）。

import { createSignal } from "solid-js";
import { api, type Provider, type Settings } from "../api/client";

const [settings, setSettings] = createSignal<Settings | null>(null);
const [providers, setProviders] = createSignal<Provider[]>([]);
const [loaded, setLoaded] = createSignal(false);

// ---- 主题（U6）：auto=跟随 prefers-color-scheme；<html data-theme> 供 CSS 覆盖 ----
export type ThemeChoice = "auto" | "light" | "dark";
const THEME_KEY = "texlate-theme";

const readTheme = (): ThemeChoice => {
    try {
        const v = localStorage.getItem(THEME_KEY);
        if (v === "light" || v === "dark" || v === "auto") return v;
    } catch {
        /* localStorage 禁用/node 环境 */
    }
    return "auto";
};

const darkQuery = () =>
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-color-scheme: dark)")
        : null;

// 首绘 applyTheme 由 index.html 预置脚本先行——模块内第一次调用属复述,
// 不触发过渡;之后(用户切换/系统翻转)才挂 .theme-anim 做 200ms 同色过渡
let themeBooted = false;
let themeAnimTimer = 0;

const THEME_COLOR: Record<"light" | "dark", string> = {
    light: "#f5f1e8", // --paper
    dark: "#17140f",
};

function applyTheme(choice: ThemeChoice) {
    if (typeof document === "undefined") return;
    const dark =
        choice === "dark" || (choice === "auto" && !!darkQuery()?.matches);
    const resolved = dark ? "dark" : "light";
    const root = document.documentElement;
    if (themeBooted && root.dataset.theme !== resolved) {
        root.classList.add("theme-anim");
        window.clearTimeout(themeAnimTimer);
        themeAnimTimer = window.setTimeout(
            () => root.classList.remove("theme-anim"),
            240,
        );
    }
    themeBooted = true;
    root.dataset.theme = resolved;
    // 移动/PWA 浏览器外壳着色跟随实际主题而非系统媒体查询
    document
        .querySelector('meta[name="theme-color"]')
        ?.setAttribute("content", THEME_COLOR[resolved]);
}

const [theme, setThemeSig] = createSignal<ThemeChoice>(readTheme());
applyTheme(theme());
// auto 模式下跟随系统切换（监听一次，内部按当前 choice 判）
darkQuery()?.addEventListener?.("change", () => {
    if (theme() === "auto") applyTheme("auto");
});

export const settingsStore = {
    settings,
    providers,
    loaded,
    theme,

    setTheme(choice: ThemeChoice) {
        setThemeSig(choice);
        try {
            localStorage.setItem(THEME_KEY, choice);
        } catch {
            /* 同上 */
        }
        applyTheme(choice);
    },

    async refresh() {
        // getSettings 失败也要放 loaded——否则 Settings 页永远停在空表单
        try {
            const [s, p] = await Promise.all([
                api.getSettings(),
                api
                    .providers()
                    .catch(() => [] as Provider[] | { providers: Provider[] }),
            ]);
            setSettings(s);
            setProviders(Array.isArray(p) ? p : (p.providers ?? []));
        } catch {
            /* 页面层按 settings()==null 自行提示 */
        } finally {
            setLoaded(true);
        }
    },

    async save(patch: Settings) {
        const next = await api.putSettings(patch);
        // ignored 仅在有丢弃字段时才下发——浅合并会让上一轮的非空值挂留，
        // 显式归一到本轮回执
        setSettings((cur) => ({ ...cur, ...next, ignored: next.ignored ?? [] }));
        return next;
    },

    test: (s?: Settings) => api.testSettings(s),
};
