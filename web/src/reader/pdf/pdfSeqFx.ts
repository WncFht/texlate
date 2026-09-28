// PdfPane sent-align 落点闪/悬停染双轨 + 落定揭示闪——拆自 PdfPane.tsx。
// saFlash 闪轨（.sa-flash 单轨新闪清旧）与 saTint 染轨（sa-hot/sa-peer
// 单轨换轨摘旧）连同 saFlashAt 新度闸、saTintReq 在场请求整体搬迁——
// 半搬会双轨脑裂。工厂必须在组件 owner 内实例化（onCleanup 自注册
// saFlashTimer/saTintEls 清算）；handle.seqEls 前向引用以 deps 注入。

import { onCleanup } from "solid-js";
import type { PDFSlick } from "@pdfslick/core";
import type { Pos } from "../logic/alignment";
import { destPointOf, type PdfDocLike } from "../cite/citations";
import { MARKED_SEL, seqOfMarkedSpan } from "./pdfmarks";
import { bandElsAt, leafEls, type PdfPageDivOf } from "./pdfDom";
import type { DestPointRow } from "./pdfDestScan";
import type { PdfPageViewLike } from "./pdfHandle";

export interface SeqFxDeps {
    viewer(): PDFSlick["viewer"] | undefined;
    /** seq → 已渲染 markedContent span 集（handle.seqEls 同源实现，
        壳内单份——注入而非自写防两份查询面漂移） */
    seqEls(seq: number): HTMLElement[];
    pageDiv: PdfPageDivOf;
    /** dest 名 → 落点（flashDest named-dest 落点寻址；scan 表只读视图） */
    destPoint: Map<string, DestPointRow>;
    pdfDoc(): PdfDocLike | null;
}

export interface SeqFx {
    flashSeq(seq: number, pos: Pos | null): HTMLElement[];
    seqLeaves(seq: number): HTMLElement[];
    flashEls(els: HTMLElement[]): void;
    flashAtPos(pos: Pos): HTMLElement[];
    hoverSeq(seq: number | null, pos: Pos | null, cls: string): void;
    tintEls(els: HTMLElement[], cls: string): void;
    flashDest(dest: unknown): void;
    /** textlayerrendered 订户——存活悬停按 saTintReq 补染 */
    reapplyTint(): void;
}

export const createSeqFx = (deps: SeqFxDeps): SeqFx => {
    // sent-align 落点闪（单轨——连点两落点旧带当场清算，cite-flash 同款）
    let saFlashEls: HTMLElement[] = [];
    let saFlashTimer = 0;
    /** 最近打闪时刻——landingFlash 的新度闸：sentalign 句级闪与
        goToDestination 包装落定闪同轨，新闪在场时迟到的落定闪不补 */
    let saFlashAt = 0;
    const saFlash = (els: HTMLElement[]) => {
        for (const el of saFlashEls) el.classList.remove("sa-flash");
        window.clearTimeout(saFlashTimer);
        saFlashEls = els;
        if (els.length) saFlashAt = performance.now();
        for (const el of els) el.classList.add("sa-flash");
        saFlashTimer = window.setTimeout(() => {
            for (const el of els) el.classList.remove("sa-flash");
            saFlashEls = [];
        }, 1400);
    };
    // sent-align 悬停伴显轨（sa-hot/sa-peer 单轨——同窗格二态互斥，换轨
    // 先摘旧类；与 sa-flash 分轨互不清，闪动画跑着悬停照样染）
    let saTintEls: HTMLElement[] = [];
    let saTintCls = "";
    // 在场悬停请求——textLayer 懒渲染/重渲后按此补染（渲染把锚 span
    // 整棵换掉，不染则 peer 页现形后悬停色依旧缺席）
    let saTintReq: { seq: number; pos: Pos | null; cls: string } | null = null;
    const saTint = (els: HTMLElement[], cls: string) => {
        const old = saTintCls;
        for (const el of saTintEls) {
            if (old) el.classList.remove(old);
        }
        saTintEls = els;
        saTintCls = els.length ? cls : "";
        for (const el of els) el.classList.add(cls);
    };
    const reTint = (req: { seq: number; pos: Pos | null; cls: string }) => {
        const c = deps.viewer()?.container;
        const els = c
            ? [...c.querySelectorAll<HTMLElement>(MARKED_SEL)].filter(
                  (el) => seqOfMarkedSpan(el) === req.seq,
              )
            : [];
        const leaves = els.flatMap(leafEls);
        if (leaves.length) saTint(leaves, req.cls);
        else if (req.pos) saTint(bandElsAt(deps.pageDiv, req.pos), req.cls);
        else saTint([], req.cls);
    };

    /** 落点 Pos → 着陆闪：pos→client 点 seqAtPoint 多 x 采样（dest 落点
        常在块间白/栏缝/图区，单点易落空），有 seq 闪锚叶（句粒度跟着
        marked 叶走）；无 seq 落回行带。懒渲页 textLayer 未起时两路皆
        空——200ms 步最多重试两拍。
        新闪闸：mirrorDest 也过 goToDestination 包装——sentalign 句级闪
        与落定闪同轨互踩，400ms 内已有新闪则整场免打（迟到的整锚闪会
        把句闪回退成段闪） */
    const landingFlash = (pos: Pos | null, attempt = 0): void => {
        if (!pos) return;
        if (performance.now() - saFlashAt < 400) return;
        const views = (
            deps.viewer() as unknown as { _pages?: PdfPageViewLike[] }
        )?._pages;
        const div = views?.[pos.page - 1]?.div;
        if (!div) return;
        const r = div.getBoundingClientRect();
        if (r.height <= 0 || r.width <= 0) return;
        const c = deps.viewer()?.container;
        const cy = r.top + r.height * pos.fraction + 4;
        let seq: number | null = null;
        if (c)
            for (const xf of [pos.x ?? 0.3, pos.x ?? 0.7, 0.3, 0.7, 0.5]) {
                const sp = c.ownerDocument
                    .elementFromPoint(r.left + r.width * xf, cy)
                    ?.closest<HTMLElement>(MARKED_SEL);
                if (sp && c.contains(sp)) {
                    seq = seqOfMarkedSpan(sp);
                    if (seq != null) break;
                }
            }
        let els: HTMLElement[] = [];
        if (seq != null) els = deps.seqEls(seq).flatMap(leafEls);
        if (!els.length) els = bandElsAt(deps.pageDiv, pos);
        if (els.length) {
            saFlash(els);
            return;
        }
        if (attempt < 2)
            window.setTimeout(() => landingFlash(pos, attempt + 1), 200);
    };

    /** named/显式 dest → 落点 Pos → landingFlash（cite 锚/usages 站跳/
        镜像跳的落定揭示共用面）；词表缺席/解页失败静默无闪 */
    const flashDest = async (dest: unknown): Promise<void> => {
        let pos: Pos | null = null;
        if (typeof dest === "string") {
            const pt = deps.destPoint.get(dest);
            if (pt)
                pos = {
                    page: pt.page,
                    fraction: pt.frac,
                    x: pt.fx ?? undefined,
                };
        } else if (Array.isArray(dest)) {
            const pt = destPointOf(dest);
            const d = deps.pdfDoc();
            if (pt && d)
                try {
                    const pnum = (await d.getPageIndex(pt.ref)) + 1;
                    const pg = await d.getPage(pnum);
                    const view = (pg as unknown as { view?: number[] }).view;
                    const h =
                        view && view.length >= 4
                            ? view[3]! - view[1]!
                            : pg.getViewport({ scale: 1 }).height;
                    const w =
                        view && view.length >= 4
                            ? view[2]! - view[0]!
                            : pg.getViewport({ scale: 1 }).width;
                    if (h > 0)
                        pos = {
                            page: pnum,
                            fraction:
                                pt.y == null
                                    ? 0.5
                                    : Math.min(
                                          Math.max(
                                              1 - (pt.y - (view?.[1] ?? 0)) / h,
                                              0,
                                          ),
                                          1,
                                      ),
                            x:
                                pt.x == null || !(w > 0)
                                    ? undefined
                                    : Math.min(
                                          Math.max(
                                              (pt.x - (view?.[0] ?? 0)) / w,
                                              0,
                                          ),
                                          1,
                                      ),
                        };
                } catch {
                    /* 解页失败无闪 */
                }
        }
        // 首拍延 180ms——同轨上 sentalign 句级闪多在此窗内落定，届时
        // 新闪闸自然让行，纯 nav 跳的闪在滚动落定后才出反而更贴
        if (pos) window.setTimeout(() => landingFlash(pos), 180);
    };

    // ---- handle 切片（原 this.xxx 指整 handle 的自引用全部改 deps/局部
    // 直引——切片摊进 handle 后 this 不再指全量，见拆分风险②） ----
    const flashSeq = (seq: number, pos: Pos | null): HTMLElement[] => {
        const els = deps.seqEls(seq);
        // markedContent 容器是 display:contents 无盒——类打上也不
        // 渲染；逐层下钻到无元素子级的叶子（真字形 span）逐个打闪
        const leaves = els.flatMap(leafEls);
        if (leaves.length) {
            saFlash(leaves);
            return leaves;
        }
        if (pos) return flashAtPos(pos);
        return [];
    };
    const seqLeaves = (seq: number): HTMLElement[] => {
        const els = deps.seqEls(seq);
        return els.flatMap(leafEls);
    };
    const flashEls = (els: HTMLElement[]): void => {
        if (els.length) saFlash(els);
    };
    const flashAtPos = (pos: Pos): HTMLElement[] => {
        const els = bandElsAt(deps.pageDiv, pos);
        if (els.length) saFlash(els);
        return els;
    };
    const hoverSeq = (
        seq: number | null,
        pos: Pos | null,
        cls: string,
    ): void => {
        if (seq == null) {
            // 清轨按类名认账——对侧 clearHot 广播式双发 null，sa-peer
            // 清不踩本轨活着的 sa-hot（自身的 pointerleave 才发得动）
            if (saTintCls === "" || saTintCls === cls) {
                saTintReq = null;
                saTint([], cls);
            }
            return;
        }
        saTintReq = { seq, pos, cls };
        const els = deps.seqEls(seq);
        // 同 flashSeq：display:contents 容器染色看不见，染到字形叶
        const leaves = els.flatMap(leafEls);
        if (leaves.length) saTint(leaves, cls);
        else if (pos) saTint(bandElsAt(deps.pageDiv, pos), cls);
        else saTint([], cls);
    };
    const tintEls = (els: HTMLElement[], cls: string): void => {
        saTint(els, cls);
    };
    // textLayer 懒渲/重渲把锚 span 整棵换掉——存活悬停按 saTintReq
    // 补染（懒渲页现形后 peer 色不该缺席；saTint 内已滤零尺寸壳）
    const reapplyTint = () => {
        if (saTintReq) reTint(saTintReq);
    };

    onCleanup(() => window.clearTimeout(saFlashTimer));
    onCleanup(() => {
        for (const el of saTintEls)
            if (saTintCls) el.classList.remove(saTintCls);
        saTintEls = [];
    });

    return {
        flashSeq,
        seqLeaves,
        flashEls,
        flashAtPos,
        hoverSeq,
        tintEls,
        flashDest: (dest: unknown) => void flashDest(dest),
        reapplyTint,
    };
};
