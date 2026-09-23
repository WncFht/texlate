// pdfTheme —— 全站外观轴与 Blender 的接线层。
//
// 主题模型(ADR-0020 二次追加·全面合并):8 档色板 = 唯一外观轴,
// 同时决定 PDF 纸面与整站 chrome。auto=OS 对(亮→原纸+亮 chrome,
// 暗→暖黑对);none=原纸+OS chrome(逃生口:暗 OS 下白纸+暗界面);
// 命名槽=锁定 {纸面,chrome} 对,不随 OS 漂移。
// chrome 不手调:paletteChromeVars 从色板 {background,foreground}
// 按 color-mix 固定比例派生全套界面 token——色相同源,脱配构造性
// 不可能(Apple Books 主题族模式);accent/阴影按明暗归类取
// base.css 已校准亮/暗套。
// 文档面独立于 chrome 派生:--page-bg-color(纸面)/--page-fg*(纸面墨色)
// --gutter(衬底=纸面压暗,永不比纸亮)同批内联落;null 主题移除后由
// base.css 兜底成「白纸+中性灰衬底 / 暗 chrome 时衬底归 --paper-2」。
//
// 免 fork 接入:不 patch 原型(PDFPageProxy 未导出、getContext 全局补丁
// 会把 pdf.js 内部 scratch canvas 也套住),而是按 pdfPage 实例拦
// render()——viewer._pages[].pdfPage 与缩略图共享同一 PDFPageProxy
// (document.getPage 缓存),一处补丁同时覆盖主页渲染与缩略图。
// 主题切换路径:setPaperTheme 换档 + pageView.reset() + viewer.update()
// 原位重渲,与 Zotero 的 page.reset()/pdfViewer.update() 同构。

import { createSignal, untrack } from "solid-js";
import type { PDFSlick } from "@pdfslick/core";
import { Blender, type PdfPageTheme } from "./blender";
import { settingsStore } from "../stores/settings";
import { t } from "../i18n";

// OS 明暗是唯一外部信号源——auto/none 伪槽的 chrome 归类与 auto 档
// 纸面都听它;命名槽锁定成对不听 OS
const osDarkQuery = () =>
    typeof window !== "undefined" && typeof window.matchMedia === "function"
        ? window.matchMedia("(prefers-color-scheme: dark)")
        : null;
const [osDark, setOsDark] = createSignal<boolean>(!!osDarkQuery()?.matches);
osDarkQuery()?.addEventListener?.("change", (e) => setOsDark(e.matches));
export { osDark };

// ---------- 纸面色板槽位表 ----------
// Zotero DEFAULT_THEMES 同构 + 自有槽;auto/none 不入表:
// auto 走 baseTokensFor 读 base.css 暗 token,none 恒 null 原样透传。
// 命名槽全硬编码——显式选板即锁定 {纸面,chrome} 对,不随 OS 漂移
export interface PaperSlot extends PdfPageTheme {
    /** 衬底覆写——默认派生 mix(bg,#000,92%);近黑板压无可压,钉提亮值保页缘 */
    gutter?: string;
}
export const PAPER_THEMES: Record<string, PaperSlot> = {
    dark: { background: "#17140f", foreground: "#e6ddcb" }, // 暖黑(=dark token)
    onedark: { background: "#282c34", foreground: "#abb2bf" }, // One Dark Pro
    black: {
        background: "#000000",
        foreground: "#ffffff",
        invertImages: true,
        gutter: "#0a0a0a",
    },
    snow: { background: "#eceff4", foreground: "#3b4252" },
    sepia: { background: "#f4ecd8", foreground: "#5b4636" },
    paper: { background: "#f5f1e8", foreground: "#211b12" }, // 暖纸(=light token)
};

/** 选板 ID 序列（auto/none 伪槽在前）——选择器选项序即此序 */
export const PAPER_THEME_IDS = [
    "auto",
    "none",
    "dark",
    "onedark",
    "black",
    "snow",
    "sepia",
    "paper",
] as const;

/** 槽位显示名——Toolbar/Settings 两处外观 select 共用 */
export const PAPER_LABEL: Record<string, string> = {
    auto: t.reader.paperAuto,
    none: t.reader.paperNone,
    dark: t.reader.paperDark,
    onedark: t.reader.paperOnedark,
    black: t.reader.paperBlack,
    snow: t.reader.paperSnow,
    sepia: t.reader.paperSepia,
    paper: t.reader.paperPaper,
};

export function currentPdfTheme(): PaperSlot | null {
    const choice = settingsStore.paperTheme();
    if (choice === "none") return null;
    if (choice !== "auto") return PAPER_THEMES[choice] ?? null;
    // auto=OS 对:暗→base.css 暗 token 现取(调色自动跟随),
    // 亮→null 原样透传(白底论文即本色)
    return osDark() ? baseTokensFor("dark") : null;
}

// ---------- 色板即全站主题:chrome 跟随纸面 ----------
// 界面 token 全部由纸面 {background,foreground} 按固定比例混出——
// 色相同源,脱配构造性不可能(Apple Books 主题族模式,HIG
// 「chrome recedes」)。暗板 elevated 往 fg 提亮、亮板往白提亮;
// accent/阴影不派生——按明暗归类取 base.css 已校准的亮/暗套。
// none 与 auto-亮档 currentPdfTheme()=null → 不落覆写,chrome 回退
// base.css [data-theme] 套(逃生口:暗 OS+白纸仍可显式到达)。

const CHROME_VAR_NAMES = [
    "--paper",
    "--paper-2",
    "--panel",
    "--ink",
    "--ink-2",
    "--ink-3",
    "--line",
    "--line-strong",
    "--cinnabar",
    "--cinnabar-deep",
    "--on-accent",
    "--pine",
    "--ochre",
    "--ochre-deep",
    "--ring",
    "--shadow",
    "--shadow-sm",
    "--shadow-pop",
    "--shadow-modal",
    // 文档面族——与 chrome 分族管理:null 主题移除后落回 base.css 原生纸默认
    "--page-bg-color",
    "--page-fg",
    "--page-fg-2",
    "--page-fg-3",
    "--gutter",
] as const;

// base.css 亮/暗两套语义色——accent 不随纸面色相漂移(对比度已校准),
// 只按色板明暗归类取套
const LIGHT_SEMANTIC: Record<string, string> = {
    "--cinnabar": "#b23a1f",
    "--cinnabar-deep": "#8c2d17",
    "--on-accent": "#fff",
    "--pine": "#2f6f4f",
    "--ochre": "#a67c00",
    "--ochre-deep": "#7d5f00",
    "--ring": "color-mix(in srgb, var(--cinnabar) 12%, transparent)",
    "--shadow": "0 1px 2px rgb(33 27 18 / 8%), 0 4px 16px rgb(33 27 18 / 7%)",
    "--shadow-sm": "0 1px 2px rgb(33 27 18 / 12%)",
    "--shadow-pop": "0 8px 28px rgb(0 0 0 / 18%)",
    "--shadow-modal": "0 12px 40px rgb(0 0 0 / 25%)",
};
const DARK_SEMANTIC: Record<string, string> = {
    "--cinnabar": "#d45b41",
    "--cinnabar-deep": "#ec8468",
    "--on-accent": "#170f08",
    "--pine": "#63a884",
    "--ochre": "#cfa226",
    "--ochre-deep": "#e0bc4d",
    "--ring": "color-mix(in srgb, var(--cinnabar) 16%, transparent)",
    "--shadow": "0 1px 2px rgb(0 0 0 / 35%), 0 4px 16px rgb(0 0 0 / 30%)",
    "--shadow-sm": "0 1px 2px rgb(0 0 0 / 40%)",
    "--shadow-pop": "0 8px 28px rgb(0 0 0 / 55%)",
    "--shadow-modal": "0 12px 40px rgb(0 0 0 / 60%)",
};

/** color-mix 串:a 占 pct%,b 占余量——色相严格取自色板两色 */
const mix = (a: string, b: string, pct: number): string =>
    `color-mix(in srgb, ${a} ${pct}%, ${b} ${100 - pct}%)`;

/** WCAG 相对亮度(0..1)——色板明暗归类阈值,现有板离 0.5 都远 */
function relLum(hex: string): number {
    const n = parseInt(hex.slice(1), 16);
    const lin = (v: number) => {
        const s = v / 255;
        return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    };
    return (
        0.2126 * lin((n >> 16) & 255) +
        0.7152 * lin((n >> 8) & 255) +
        0.0722 * lin(n & 255)
    );
}

/** 纸面色板 → chrome token 表;null 主题 → null(不落覆写) */
export function paletteChromeVars(
    th: PaperSlot | null,
): Record<string, string> | null {
    if (!th) return null;
    const { background: bg, foreground: fg } = th;
    const dark = relLum(bg) < 0.5;
    // 面:明暗两向——暗板 elevated 提亮(往 fg),亮板 elevated 提白
    const surfaces: Record<string, string> = dark
        ? {
              // 比例取自 base.css 暗 token 实测(bg#17140f→fg#e6ddcb):
              // paper-2≈4%fg / panel≈7%fg / line≈17%fg / line-strong≈26%fg /
              // ink-2=fg 70% / ink-3=fg 57%
              "--paper": bg,
              "--paper-2": mix(bg, fg, 96),
              "--panel": mix(bg, fg, 93),
              "--ink": fg,
              "--ink-2": mix(fg, bg, 70),
              "--ink-3": mix(fg, bg, 57),
              "--line": mix(bg, fg, 83),
              "--line-strong": mix(bg, fg, 74),
          }
        : {
              "--paper": bg,
              "--paper-2": mix(bg, fg, 95),
              "--panel": mix(bg, "#ffffff", 20),
              "--ink": fg,
              "--ink-2": mix(fg, bg, 66),
              "--ink-3": mix(fg, bg, 56),
              "--line": mix(bg, fg, 89),
              "--line-strong": mix(bg, fg, 79),
          };
    return {
        ...surfaces,
        // 文档面:纸面本色 + 纸面墨色阶梯(镜像 ink 同比例) + 衬底。
        // 衬底规则=纸面压暗(色相锚纸、永比纸暗——亮板暗 mat、暗板不再
        // 出现「亮框裱暗纸」);近黑板由槽位 gutter 钉死保页缘
        "--page-bg-color": bg,
        "--page-fg": fg,
        "--page-fg-2": mix(fg, bg, dark ? 70 : 66),
        "--page-fg-3": mix(fg, bg, dark ? 57 : 56),
        "--gutter": th.gutter ?? mix(bg, "#000000", 92),
        ...(dark ? DARK_SEMANTIC : LIGHT_SEMANTIC),
        "color-scheme": dark ? "dark" : "light",
    };
}

/** chrome 明暗归类:命名槽按自身纸面 WCAG 亮度,auto/none 听 OS——
    index.html 预置脚本内联同一口径(防 FOUC 先行落类) */
export function chromeClass(): "light" | "dark" {
    const p = settingsStore.paperTheme();
    const th = p === "auto" || p === "none" ? null : PAPER_THEMES[p];
    if (th) return relLum(th.background) < 0.5 ? "dark" : "light";
    return osDark() ? "dark" : "light";
}

// auto-暗档要读 base.css 暗 token 原值——但命名槽覆写可能正挂在
// documentElement 内联上,直接 computed 会读到脏值。同步
// 「摘覆写→翻 data-theme→读→还原」一趟拿真 base(同 task 内无绘制,
// 无闪烁);按类缓存——base token 会话内不变。
const baseTokenCache: Partial<Record<"light" | "dark", PdfPageTheme>> = {};
function baseTokensFor(cls: "light" | "dark"): PdfPageTheme {
    const hit = baseTokenCache[cls];
    if (hit) return hit;
    const el = document.documentElement;
    const stashed = CHROME_VAR_NAMES.map((n) => el.style.getPropertyValue(n));
    const prevScheme = el.style.colorScheme;
    const prevTheme = el.dataset.theme;
    for (const n of CHROME_VAR_NAMES) el.style.removeProperty(n);
    el.style.colorScheme = "";
    el.dataset.theme = cls;
    const cs = getComputedStyle(el);
    const th: PdfPageTheme = {
        background: cs.getPropertyValue("--paper").trim() || "#ffffff",
        foreground: cs.getPropertyValue("--ink").trim() || "#000000",
    };
    el.dataset.theme = prevTheme ?? "light";
    el.style.colorScheme = prevScheme;
    CHROME_VAR_NAMES.forEach((n, i) => {
        if (stashed[i]) el.style.setProperty(n, stashed[i]);
    });
    baseTokenCache[cls] = th;
    return th;
}

let chromeBooted = false;
let chromeAnimTimer = 0;
let prevChromeKey = "";

/** 全站 chrome 唯一写者——App 根 effect 内调用,paperTheme/osDark
    两路信号读即依赖,选板与系统翻转自动重放。落点:
    data-theme 明暗归类 + 色板派生 token 内联覆写 + meta theme-color。
    首绘由 index.html 预置先行,首次调用不挂过渡;之后键变才
    .theme-anim 200ms 同面过渡 */
export function applyPaletteChrome(el: HTMLElement): void {
    const cls = chromeClass();
    const th = currentPdfTheme();
    const key = `${cls}|${th?.background ?? ""}|${th?.foreground ?? ""}`;
    if (chromeBooted && key !== prevChromeKey) {
        el.classList.add("theme-anim");
        window.clearTimeout(chromeAnimTimer);
        chromeAnimTimer = window.setTimeout(
            () => el.classList.remove("theme-anim"),
            240,
        );
    }
    chromeBooted = true;
    prevChromeKey = key;
    el.dataset.theme = cls;
    const vars = paletteChromeVars(th);
    if (!vars) {
        for (const name of CHROME_VAR_NAMES) el.style.removeProperty(name);
        el.style.removeProperty("color-scheme");
    } else {
        for (const [name, value] of Object.entries(vars)) {
            if (name === "color-scheme") el.style.colorScheme = value;
            else el.style.setProperty(name, value);
        }
    }
    // 浏览器外壳着色:命名槽跟纸面本色,auto/none 跟归类 base 色
    const metaColor =
        th?.background ?? (cls === "dark" ? "#17140f" : "#f5f1e8");
    document
        .querySelector('meta[name="theme-color"]')
        ?.setAttribute("content", metaColor);
}

const blenders = new WeakMap<CanvasRenderingContext2D, Blender>();
const PATCHED = Symbol("texlate-render-patched");

interface PdfPageLike {
    render(params: {
        canvasContext?: CanvasRenderingContext2D;
        canvas?: HTMLCanvasElement;
        viewport?: { width: number; height: number };
    }): unknown;
    [PATCHED]?: boolean;
}

// 实例级补丁:拦 pdfPage.render,把 canvasContext 套进 Blender。
// 每次渲染都按当前主题重建/换色——zoom、虚拟化滚动重渲自动吃到最新主题。
export function patchPdfPage(pg: PdfPageLike) {
    if (pg[PATCHED]) return;
    pg[PATCHED] = true;
    const orig = pg.render.bind(pg);
    pg.render = (params) => {
        // pdf.js 命令式调用,非 tracked scope——untrack 显式取当下主题
        const theme = untrack(currentPdfTheme);
        // pdf.js 6.x:params.canvas 为主路(内部 getContext 自取),
        // canvasContext 为旧签名——两者同源,getContext 返回同一实例
        const ctx =
            params?.canvasContext ??
            params?.canvas?.getContext?.("2d") ??
            null;
        if (
            theme &&
            ctx &&
            !(ctx as CanvasRenderingContext2D & { skipBlender?: boolean })
                .skipBlender
        ) {
            let b = blenders.get(ctx);
            if (!b) {
                b = new Blender(ctx, theme);
                blenders.set(ctx, b);
            } else {
                b.setTheme(theme);
            }
            const vp = params.viewport;
            b.pageWidth = vp?.width ?? ctx.canvas.width;
            b.pageHeight = vp?.height ?? ctx.canvas.height;
        }
        return orig(params);
    };
}

// document.getPage 是 PDFPageProxy 的唯一产线(viewer/缩略图/后续懒取
// 都走它,且内部按页码缓存)——在文档级拦截根除「pdfPage 懒赋值晚于
// _pages 扫描」的时序洞;已取出的实例由下方 _pages 补扫兜底
const DOC_PATCHED = Symbol("texlate-getpage-patched");
interface PdfDocumentLike {
    getPage(n: number): Promise<PdfPageLike>;
    [DOC_PATCHED]?: boolean;
}
export function patchPdfDocument(doc: PdfDocumentLike | null | undefined) {
    if (!doc || doc[DOC_PATCHED]) return;
    doc[DOC_PATCHED] = true;
    const origGetPage = doc.getPage.bind(doc);
    doc.getPage = async (n: number) => {
        const pg = await origGetPage(n);
        patchPdfPage(pg);
        return pg;
    };
}

interface PageViewLike {
    pdfPage?: PdfPageLike;
    reset(opts?: Record<string, boolean>): void;
}
interface ThumbViewLike {
    pdfPage?: PdfPageLike;
    reset(): void;
}
interface ViewerLike {
    _pages?: PageViewLike[];
    update(): void;
}
interface ThumbViewerLike {
    _thumbnails?: ThumbViewLike[];
    forceRendering(): boolean;
}

// 主题切换:全页 reset(INITIAL) + viewer.update() 重渲可见页;
// 缩略图 reset 保留旧图(pdfslick 的 reset 不清 img)直到新渲覆盖,
// forceRendering 逐次排队——每调一次只取一个最高优先级
export function applyPdfTheme(slick: PDFSlick | null | undefined) {
    patchPdfDocument(slick?.document as PdfDocumentLike | null | undefined);
    const viewer = slick?.viewer as unknown as ViewerLike | undefined;
    if (!viewer?._pages) return;
    for (const pv of viewer._pages) {
        if (pv?.pdfPage) patchPdfPage(pv.pdfPage);
        pv?.reset?.({ keepTextLayer: true });
    }
    const tv = slick?.thumbnailViewer as unknown as ThumbViewerLike | undefined;
    for (const t of tv?._thumbnails ?? []) {
        if (t?.pdfPage) patchPdfPage(t.pdfPage);
        t?.reset?.();
    }
    viewer.update();
    if (tv) while (tv.forceRendering()) {
        /* 逐次排队可见缩略图,直到没有可渲的 */
    }
}
