// commands —— sel-system 命令表（内核落地层）。
// 事实源 = menu-spec 21 项（ux-impl-2026-09-22 规格）；本表注册 **18 项**——
//   不注册（各功能 lane 自行 register，注册表本为此设计）：
//     sel.explain    —— 需 assist 后端端点（caps.assist 恒 false，本期无面）
//     sel.xlat       —— sel-translate lane（不在 menu-spec，键位 t 预留）
//     math.copyTex   —— copy-latex lane（ph 反代近似源属其管线）
//     chunk.copyTex  —— 同上
//     cite.usages    —— find-usages lane（不在 menu-spec）
//   仍注册但天然隐藏（谓词兜底，不会错触发）：
//     chunk.copyLink —— 需 caps.linkScheme（路由 ?seq=N 未落地）
//     chunk.retx     —— caps.retx 供给；seq∈pending 时 enableWhen 落禁用
//
// Command.title = i18n key（"menu.<id>"——整合期挂 zh.ts/en.ts 键面）；
// menu-spec 的双语串镜像在 MENU_LABELS。

import type { Command, Ctx, Registry } from "./cmdreg";
import { flattenCtx, type HitCtx, type PaneSide } from "./hitctx";

// ------------------------------------------------------------------ ctx

/** 命令上下文：扁平谓词键 + 结构化 hit + 依赖注入面 */
export interface CmdCtx extends Ctx {
    hit: HitCtx;
    deps: CmdDeps;
}

/** HitCtx → CmdCtx（扁平谓词键 + hit/deps 载荷） */
export function makeCmdCtx(hit: HitCtx, deps: CmdDeps): CmdCtx {
    return { ...flattenCtx(hit), hit, deps };
}

// ------------------------------------------------------------------ deps

/** 命令副作用注入面——全可选，缺席即对应命令被谓词自然隐藏/no-op。 */
export interface CmdDeps {
    /** 写剪贴板（缺省 navigator.clipboard.writeText） */
    writeText?(text: string): void | Promise<void>;
    /** 开外链（缺省 window.open noopener） */
    openUrl?(url: string): void;
    /** 窗格内查找（caps.findInPane 对应能力；query=选区文本） */
    openFind?(query?: string): void;
    navBack?(): void;
    navFwd?(): void;
    /** 引用卡（bibkey/锚/目标元素在 hit.cite 上） */
    citeCard?(cite: HitCtx["cite"]): void;
    /** 跳至锚目标（targetId/targetEl 在 hit.cite 上） */
    citeJump?(cite: HitCtx["cite"]): void;
    /** api.discoverOverview——未收录回包 {available:false} 走 toast 降级 */
    discoverOverview?(arxivId: string): Promise<unknown> | void;
    /** 单段重译通道（HtmlPane retranslate 同款：api.retranslateChunk+轮询） */
    retranslate?(seq: number): void;
    /** chunk 文本解析（hitctx 同款——谓词与载荷共用此源） */
    chunkText?(key: string, lang: PaneSide): string | null;
    /** 段链接构造（caps.linkScheme 真值源；返 null=不可造） */
    chunkLink?(chunk: HitCtx["chunk"]): string | null;
    toastOk?(msg: string): void;
    toastErr?(msg: string): void;
}

const writeText = (deps: CmdDeps, text: string) =>
    void (deps.writeText
        ? deps.writeText(text)
        : navigator.clipboard?.writeText(text));

const openUrl = (deps: CmdDeps, url: string): void => {
    if (deps.openUrl) deps.openUrl(url);
    else window.open(url, "_blank", "noopener");
};

const chunkTextOf = (ctx: CmdCtx, lang: PaneSide): string | null => {
    const c = ctx.hit.chunk;
    if (!c.key) return null;
    if (ctx.hit.paneSide === lang && c.el)
        return c.el.textContent?.trim() || null;
    return ctx.deps.chunkText?.(c.key, lang) ?? null;
};

const pairTextOf = (ctx: CmdCtx, key: string): string | null => {
    const en = ctx.deps.chunkText?.(key, "en") ?? null;
    const zh = ctx.deps.chunkText?.(key, "zh") ?? null;
    if (en == null && zh == null) return null;
    return [en, zh].filter((s) => s != null && s !== "").join("\n\n");
};

// ------------------------------------------------------------------ 命令表

/** 菜单分段序——入口按段间插分隔线 */
export const SECTION_ORDER = [
    "sel",
    "cite",
    "math",
    "sent",
    "chunk",
    "pane",
] as const;

/** menu-spec.json 双语串镜像（title 的 i18n key 落地源） */
export const MENU_LABELS: Record<string, { zh: string; en: string }> = {
    "sel.copy": { zh: "复制", en: "Copy" },
    "sel.copyPair": { zh: "复制双语对照", en: "Copy en+zh pair" },
    "sel.find": { zh: "在文档中查找", en: "Find in document" },
    "sel.copyTex": { zh: "复制 LaTeX", en: "Copy LaTeX" },
    "cite.card": { zh: "查看引用条目", en: "Show reference card" },
    "cite.jump": { zh: "跳至引用目标", en: "Jump to referenced target" },
    "cite.copy": { zh: "复制文献条目", en: "Copy citation text" },
    "cite.arxiv": { zh: "打开 arXiv 页", en: "Open arXiv page" },
    "cite.doi": { zh: "打开 DOI", en: "Open DOI" },
    "cite.alphaxiv": { zh: "alphaXiv 导读", en: "alphaXiv overview" },
    "cite.usages": { zh: "查找引用", en: "Find usages" },
    "cite.translate": { zh: "翻译此文", en: "Translate" },
    "cite.refsAll": { zh: "全部文献", en: "All references" },
    "math.copyMathml": { zh: "复制 MathML", en: "Copy MathML" },
    "math.copyTex": { zh: "复制 TeX 源码", en: "Copy TeX source" },
    "sent.gotoPeer": { zh: "跳到对侧句", en: "Jump to peer sentence" },
    "chunk.copySrc": { zh: "复制原文", en: "Copy original" },
    "chunk.copyZh": { zh: "复制译文", en: "Copy translation" },
    "chunk.copyPair": { zh: "复制双语段", en: "Copy bilingual block" },
    "chunk.copyTex": { zh: "复制 LaTeX 源", en: "Copy LaTeX source" },
    "chunk.retx": { zh: "重译此段", en: "Retranslate block" },
    "chunk.copyLink": { zh: "复制段链接", en: "Copy link to block" },
    "pane.find": { zh: "窗格内查找…", en: "Find in pane…" },
    "pane.navBack": { zh: "跳回", en: "Jump back" },
    "pane.navFwd": { zh: "前进", en: "Jump forward" },
};

/**
 * 注册 menu-spec 命令集（18 项）。幂等——重复调用先 unregister 同名项。
 * @returns registry（链式）+ 实际注册 id 列表挂在返回值外不方便——用
 *          reg.all() 查。
 */
export function registerCommands(
    reg: Registry<CmdCtx>,
    _deps: CmdDeps = {},
): Registry<CmdCtx> {
    const cmds: Command<CmdCtx>[] = [
        // ------------------------------------------------ sel 段（划词族）
        {
            id: "sel.copy",
            title: "menu.sel.copy",
            sec: "sel",
            bar: true,
            when: "sel.text",
            run: (c) => writeText(c.deps, c.hit.sel.text),
        },
        {
            id: "sel.copyPair",
            title: "menu.sel.copyPair",
            sec: "sel",
            bar: true,
            when: "sel.text && sel.inChunk && chunk.counterpartAvail",
            run: (c) => {
                // 覆盖块逐块取双语对；段落级对位（句级）属 sent-align lane
                const parts = c.hit.sel.chunks
                    .map((k) => pairTextOf(c, k))
                    .filter((s): s is string => s != null && s !== "");
                writeText(
                    c.deps,
                    parts.length ? parts.join("\n\n") : c.hit.sel.text,
                );
            },
        },
        {
            id: "sel.find",
            title: "menu.sel.find",
            sec: "sel",
            bar: true,
            when: "sel.text && caps.findInPane",
            run: (c) => c.deps.openFind?.(c.hit.sel.trimmed),
        },
        // ------------------------------------------------ cite 段（引用锚）
        {
            id: "cite.card",
            title: "menu.cite.card",
            sec: "cite",
            when: "cite.targetKind == 'bib' && (cite.entryText || cite.cardFillable)",
            run: (c) => c.deps.citeCard?.(c.hit.cite),
        },
        {
            id: "cite.jump",
            title: "menu.cite.jump",
            sec: "cite",
            when: "cite.targetExists",
            run: (c) => c.deps.citeJump?.(c.hit.cite),
        },
        {
            id: "cite.copy",
            title: "menu.cite.copy",
            sec: "cite",
            when: "cite.targetKind == 'bib' && cite.entryText",
            run: (c) => writeText(c.deps, c.hit.cite.entryText ?? ""),
        },
        {
            id: "cite.arxiv",
            title: "menu.cite.arxiv",
            sec: "cite",
            when: "cite.targetKind == 'bib' && cite.arxivId",
            run: (c) =>
                openUrl(c.deps, `https://arxiv.org/abs/${c.hit.cite.arxivId}`),
        },
        {
            id: "cite.doi",
            title: "menu.cite.doi",
            sec: "cite",
            when: "cite.targetKind == 'bib' && cite.doi",
            run: (c) => openUrl(c.deps, `https://doi.org/${c.hit.cite.doi}`),
        },
        {
            id: "cite.alphaxiv",
            title: "menu.cite.alphaxiv",
            sec: "cite",
            when: "cite.targetKind == 'bib' && cite.arxivId && caps.discover",
            run: async (c) => {
                const res = await c.deps.discoverOverview?.(
                    c.hit.cite.arxivId ?? "",
                );
                // 未收录回包 {available:false} → toast 降级（menu-spec 注）
                if (
                    res != null &&
                    typeof res === "object" &&
                    (res as { available?: boolean }).available === false
                )
                    c.deps.toastErr?.("alphaxiv: not indexed");
            },
        },
        // ------------------------------------------------ math 段（公式）
        {
            id: "math.copyMathml",
            title: "menu.math.copyMathml",
            sec: "math",
            when: "math.mathml",
            run: (c) => writeText(c.deps, c.hit.math.mathml ?? ""),
        },
        // ------------------------------------------------ chunk 段（块）
        {
            id: "chunk.copySrc",
            title: "menu.chunk.copySrc",
            sec: "chunk",
            // hasNontext 兜底：1/163 空 textContent 容器块（menu-spec 注）
            when: "chunk.hasEn || chunk.hasNontext",
            run: (c) => {
                const t =
                    chunkTextOf(c, "en") ?? c.hit.chunk.el?.textContent ?? "";
                writeText(c.deps, t);
            },
        },
        {
            id: "chunk.copyZh",
            title: "menu.chunk.copyZh",
            sec: "chunk",
            when: "chunk.hasZh && !chunk.zhUntranslated",
            run: (c) => {
                const t =
                    chunkTextOf(c, "zh") ?? c.hit.chunk.el?.textContent ?? "";
                writeText(c.deps, t);
            },
        },
        {
            id: "chunk.copyPair",
            title: "menu.chunk.copyPair",
            sec: "chunk",
            when: "chunk.hasEn && chunk.hasZh && !chunk.zhUntranslated && chunk.counterpartAvail",
            run: (c) => {
                const t = c.hit.chunk.key
                    ? pairTextOf(c, c.hit.chunk.key)
                    : null;
                if (t != null) writeText(c.deps, t);
            },
        },
        {
            id: "chunk.retx",
            title: "menu.chunk.retx",
            sec: "chunk",
            // seq∈pending → disabled 不 hidden（enableWhen 而非 when）
            when: "caps.retx && chunk.intSeq",
            enableWhen: "!chunk.pending",
            run: (c) => {
                if (c.hit.chunk.intSeq != null)
                    c.deps.retranslate?.(c.hit.chunk.intSeq);
            },
        },
        {
            id: "chunk.copyLink",
            title: "menu.chunk.copyLink",
            sec: "chunk",
            when: "chunk.seq && caps.linkScheme",
            run: (c) => {
                const url = c.deps.chunkLink?.(c.hit.chunk);
                if (url) writeText(c.deps, url);
            },
        },
        // ------------------------------------------------ pane 段（窗格）
        {
            id: "pane.find",
            title: "menu.pane.find",
            sec: "pane",
            when: "caps.findInPane",
            run: (c) => c.deps.openFind?.(),
        },
        {
            id: "pane.navBack",
            title: "menu.pane.navBack",
            sec: "pane",
            when: "caps.navBack",
            run: (c) => c.deps.navBack?.(),
        },
        {
            id: "pane.navFwd",
            title: "menu.pane.navFwd",
            sec: "pane",
            when: "caps.navFwd",
            run: (c) => c.deps.navFwd?.(),
        },
    ];
    for (const cmd of cmds) {
        if (reg.get(cmd.id)) reg.unregister(cmd.id); // 幂等重挂
        reg.register(cmd);
    }
    return reg;
}
