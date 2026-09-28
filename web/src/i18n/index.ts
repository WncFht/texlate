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
export const fmt = (
    tpl: string,
    vars: Record<string, string | number>,
): string =>
    tpl.replace(/\{(\w+)\}/g, (m, k: string) =>
        k in vars ? String(vars[k]) : m,
    );

/** t-path 解析（"menu.sel.copy" → t.menu.sel.copy）；缺键/命中非串 → null。
    整合期未落地的 lane 键靠本件探测——缺席即 null 让调用方回落。 */
export const tPath = (path: string): string | null => {
    let cur: unknown = t;
    for (const k of path.split(".")) {
        if (cur == null || typeof cur !== "object") return null;
        cur = (cur as Record<string, unknown>)[k];
    }
    return typeof cur === "string" ? cur : null;
};

/** lane 文案取键：t.<section>[key] → 未落地回落 fb[currentLang()][key] →
    key 兜底；vars 在场走 fmt 插值。cite/citeTran/usages 各 lane 同构。 */
export const tLane = (
    section: string,
    key: string,
    fb: Record<Lang, Record<string, string>>,
    vars?: Record<string, string | number>,
): string => {
    const dict = (
        t as unknown as Record<string, Record<string, string> | undefined>
    )[section];
    const tpl = dict?.[key] ?? fb[currentLang()][key] ?? key;
    return vars ? fmt(tpl, vars) : tpl;
};
