// PdfPane 导航面——goToDestination 单点劫持 + 串行导航队列 + mirrorDest
// 镜像跳，拆自 PdfPane.tsx。use*/create* 工厂契约：必须在组件 owner
// 顶层同步调用（createEffect 注册要 owner）。
// handle 前向引用一律 getHandle() 惰性取——原 capturePos(this) 的 this
// 指整 handle（几何采样靠它），漏改即 pre/post 全错。

import { createEffect } from "solid-js";
import type { PDFSlick } from "@pdfslick/core";
import type { Pos } from "../logic/alignment";
import { capturePos } from "../logic/sync";
import { pdfCiteDests } from "../cite/usages";
import type { PdfDocLike } from "../cite/citations";
import type { LinkServiceLike, PaneHandle } from "./pdfHandle";

export interface PdfNavDeps {
    pdfSlick(): PDFSlick | null;
    isDocumentLoaded(): boolean;
    pdfDoc(): PdfDocLike | null;
    /** 整 handle 惰性引用——劫持回调/mirrorDest 执行期才取（此时
        壳内 handle 字面量已就位），替代原 this 语义 */
    getHandle(): PaneHandle;
    /** find-usages {u:1} 载荷翻译的实时子集——同 scan 实例 */
    destNames: ReadonlySet<string>;
    closeAll(): void;
    onNavBegin(): void;
    onDestJump(dest: unknown, pre: Pos, post: Pos): void;
    flashDest(dest: unknown): void;
}

export interface PdfNav {
    mirrorDest(dest: unknown): Promise<{ pre: Pos; post: Pos } | null>;
}

export const createPdfNav = (deps: PdfNavDeps): PdfNav => {
    // goToDestination 包装持有的原始引用——mirrorDest 走它绕开压栈/回传
    let origGoTo: ((dest: unknown) => Promise<void>) | null = null;
    let wrappedLs: LinkServiceLike | null = null;
    // 导航串行队列：wrapped 跳转与镜像都经它——pdf.js 内部多个 worker
    // 往返乱序落定会把窗格拽回旧意图；排队执行保证落定序=点击序，
    // 且 pre 在任务体里现捕（排队期位置可能已被上一跳改写）
    let navChain: Promise<void> = Promise.resolve();
    let navSeq = 0;
    let mirrorSeq = 0;
    const enqueueNav = (task: () => Promise<void>) => {
        navChain = navChain.then(task, task);
        return navChain;
    };

    const mirrorDest = async (
        dest: unknown,
    ): Promise<{ pre: Pos; post: Pos } | null> => {
        const s = deps.pdfSlick();
        const orig = origGoTo;
        if (!s || !orig) return null;
        // find-usages 镜像载荷 {u:1,id,ord,chunkOrd}——机会型
        // named-dest 翻译：cite.<key> 在本侧 dest 集内才接（无
        // dest 族文档诚实 null 由对侧降级）；dom 臂 id 带 bib.
        // 前缀时剥一层重试
        if (
            dest != null &&
            typeof dest === "object" &&
            (dest as { u?: unknown }).u === 1
        ) {
            const raw = String((dest as { id?: unknown }).id ?? "");
            const cand =
                pdfCiteDests(deps.destNames, raw)[0] ??
                (raw.startsWith("bib.")
                    ? pdfCiteDests(deps.destNames, raw.slice(4))[0]
                    : undefined);
            if (!cand) return null;
            dest = cand;
        }
        // dst 无同名锚即放弃——不显式验会让 pdf.js 内部抛/跳错页
        if (typeof dest === "string") {
            try {
                const d = await deps.pdfDoc()?.getDestination(dest);
                if (!d) return null;
            } catch {
                return null;
            }
        }
        // 与用户导航同队串行——镜像落定序=意图序；有更新的镜像
        // 排队时旧的作废（src 连点两 cite，dst 不该先落 A 再落 B）
        const my = ++mirrorSeq;
        let r: { pre: Pos; post: Pos } | null = null;
        await enqueueNav(async () => {
            if (my !== mirrorSeq) return;
            const pre = capturePos(deps.getHandle());
            try {
                await orig(dest);
            } catch {
                return;
            }
            r = { pre, post: capturePos(deps.getHandle()) };
        });
        return r;
    };

    // linkService.goToDestination 单点劫持——所有内链（cite 锚/大纲/named
    // dest）唯一漏斗；preventDefault/stopPropagation 拦不住 onclick 属性
    // 处理器，包装是唯一能「跳前压栈」的拦截点。navChain 串行化执行：
    // orig 内含多个 worker 往返，裸并发会乱序落定+栈失真；末次入队者
    // 胜出（旧任务轮到执行时 navSeq 已变→直接作废），pre 在执行时现捕。
    // _ignoreDestinationZoom 常置——缩放是双侧统一信号，dest 自带缩放
    // （FitH/FitR）会让两窗格发散且 store 无回写。
    createEffect(() => {
        const s = deps.pdfSlick();
        if (!s || !deps.isDocumentLoaded()) return;
        const ls = s.linkService as unknown as LinkServiceLike;
        if (wrappedLs === ls) return;
        wrappedLs = ls;
        ls._ignoreDestinationZoom = true;
        const orig = ls.goToDestination.bind(ls);
        origGoTo = orig;
        ls.goToDestination = (dest: unknown) => {
            const my = ++navSeq;
            // 排队回调执行期读 deps getter（props/信号桥）是有意的
            return enqueueNav(async () => {
                if (my !== navSeq) return; // 更新的导航已排队——作废本跳
                deps.onNavBegin();
                deps.closeAll();
                // 死链预检：pdf.js 对缺失 dest 只 console.error 不抛——
                // 不预检会记 post≈pre 幻影栈项并截断前进栈
                if (typeof dest === "string") {
                    try {
                        if (!(await deps.pdfDoc()?.getDestination(dest)))
                            return;
                    } catch {
                        return;
                    }
                }
                const pre = capturePos(deps.getHandle());
                try {
                    await orig(dest);
                } catch {
                    return;
                }
                deps.onDestJump(dest, pre, capturePos(deps.getHandle()));
                // 落定揭示：dest→落点 seq/行带闪（cite 锚/usages 站跳
                // 共用；sentalign 跳走 mirrorDest 原路不入此漏斗）
                deps.flashDest(dest);
            });
        };
    });

    return { mirrorDest };
};
