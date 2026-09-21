// 语言选择：localStorage("texlate-lang") 存 "zh"|"en"|"auto"（缺省 auto）；
// auto 按 navigator.language 判——静态选型，setLang 写 storage 后 reload 生效。

import { t as zh } from "./zh";
import { t as en } from "./en";

export type LangChoice = "auto" | "zh" | "en";
export type Lang = "zh" | "en";
const LANG_KEY = "texlate-lang";

/** 存的选择（含 auto）——Settings 语言下拉回显用 */
export const langChoice = (): LangChoice => {
    try {
        const v = localStorage.getItem(LANG_KEY);
        if (v === "zh" || v === "en" || v === "auto") return v;
    } catch {
        /* localStorage 禁用/node 环境 */
    }
    return "auto";
};

export const currentLang = (): Lang => {
    const c = langChoice();
    if (c !== "auto") return c;
    return typeof navigator !== "undefined" &&
        navigator.language?.startsWith("zh")
        ? "zh"
        : "en";
};

export const setLang = (choice: LangChoice) => {
    try {
        localStorage.setItem(LANG_KEY, choice);
    } catch {
        /* 同上 */
    }
    if (typeof location !== "undefined") location.reload();
};

// 形状以 zh.ts 为准——en.ts 键级 parity 由这里的赋值把守
export const t: typeof zh = currentLang() === "zh" ? zh : en;

/** i18n 模板 {k} 插值——单源；各组件的本地 fmt 副本一律改从这里 import */
export const fmt = (tpl: string, vars: Record<string, string | number>): string =>
    tpl.replace(/\{(\w+)\}/g, (m, k: string) =>
        k in vars ? String(vars[k]) : m,
    );
