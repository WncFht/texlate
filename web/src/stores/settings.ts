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

function applyTheme(choice: ThemeChoice) {
    if (typeof document === "undefined") return;
    const dark = choice === "dark" || (choice === "auto" && !!darkQuery()?.matches);
    document.documentElement.dataset.theme = dark ? "dark" : "light";
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
        setSettings((cur) => ({ ...cur, ...next }));
        return next;
    },

    test: (s?: Settings) => api.testSettings(s),
};
