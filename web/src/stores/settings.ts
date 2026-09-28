// BYOK 设置 store —— GET 永不回 key 本体，只回 has_api_key（§2.5）。

import { createSignal } from "solid-js";
import { api, type Provider, type Settings } from "../api/client";

const [settings, setSettings] = createSignal<Settings | null>(null);
const [providers, setProviders] = createSignal<Provider[]>([]);
const [loaded, setLoaded] = createSignal(false);

// ---- 外观（单轴合并，§ADR-0020 二次追加）----
// 8 档色板是全站唯一外观轴：纸面配色与 chrome 同源派生，不再存在独立
// 「界面主题」。auto=OS 对（亮→原纸+亮 chrome；暗→暖黑对）；
// none=原纸+OS chrome（逃生口：暗 OS 下仍可达白纸+暗界面）；
// 命名槽=锁定 {纸面,chrome} 对。OS 监听与 chrome 落点在 pdfTheme.ts。
export type PaperThemeChoice =
    "auto" | "none" | "dark" | "onedark" | "black" | "snow" | "sepia" | "paper";
const PAPER_KEY = "texlate-paper-theme";

const readPaperTheme = (): PaperThemeChoice => {
    try {
        const v = localStorage.getItem(PAPER_KEY);
        if (
            v === "auto" ||
            v === "none" ||
            v === "dark" ||
            v === "onedark" ||
            v === "black" ||
            v === "snow" ||
            v === "sepia" ||
            v === "paper"
        )
            return v;
        if (v === null) {
            // 单轴合并迁移：旧全局主题键折成语义等价的锁定色板档
            // （light→暖纸=旧亮 chrome 原值；dark→暖黑=旧暗 chrome+暗纸对）
            const t0 = localStorage.getItem("texlate-theme");
            if (t0 === "dark") return "dark";
            if (t0 === "light") return "paper";
        }
    } catch {
        /* localStorage 禁用/node 环境 */
    }
    return "auto";
};

const [paperTheme, setPaperThemeSig] =
    createSignal<PaperThemeChoice>(readPaperTheme());

// ---- 划词浮条（sel-system FloatBar 总开关，默认开）----
// localStorage "texlate-floatbar"：'0'/'off'/'false' → 关；缺省/其他 → 开。
const FLOATBAR_KEY = "texlate-floatbar";

const readFloatbar = (): boolean => {
    try {
        const v = localStorage.getItem(FLOATBAR_KEY);
        if (v === "0" || v === "off" || v === "false") return false;
    } catch {
        /* localStorage 禁用/node 环境 */
    }
    return true;
};

const [floatbar, setFloatbarSig] = createSignal<boolean>(readFloatbar());

// ---- 句级双语对位（sent-align 总开关，默认开）----
// localStorage "texlate-sent-align"：'0'/'off'/'false' → 关；缺省/其他 → 开。
// 关掉即全剥注入 span（features/sentalign 的 enabled() 源）。
const SENT_ALIGN_KEY = "texlate-sent-align";

const readSentAlign = (): boolean => {
    try {
        const v = localStorage.getItem(SENT_ALIGN_KEY);
        if (v === "0" || v === "off" || v === "false") return false;
    } catch {
        /* localStorage 禁用/node 环境 */
    }
    return true;
};

const [sentAlign, setSentAlignSig] = createSignal<boolean>(readSentAlign());

export const settingsStore = {
    settings,
    providers,
    loaded,
    paperTheme,
    floatbar,
    sentAlign,

    setPaperTheme(choice: PaperThemeChoice) {
        setPaperThemeSig(choice);
        try {
            localStorage.setItem(PAPER_KEY, choice);
        } catch {
            /* 同上 */
        }
    },

    setFloatbar(on: boolean) {
        setFloatbarSig(on);
        try {
            localStorage.setItem(FLOATBAR_KEY, on ? "1" : "0");
        } catch {
            /* 同上 */
        }
    },

    setSentAlign(on: boolean) {
        setSentAlignSig(on);
        try {
            localStorage.setItem(SENT_ALIGN_KEY, on ? "1" : "0");
        } catch {
            /* 同上 */
        }
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
        setSettings((cur) => ({
            ...cur,
            ...next,
            ignored: next.ignored ?? [],
        }));
        return next;
    },

    test: (s?: Settings) => api.testSettings(s),
};
