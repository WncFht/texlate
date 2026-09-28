// PdfPane ⌘-Inspect/本体反查命中面——destAtPoint 最近邻 + 分面容差
// inspectDestName + inspectAt/inspectDestAt/destHotAt，拆自 PdfPane.tsx。
// 纯查询工厂：deps 只进不出；openCard/openUsagesFor 以 getter 注入
// （cards 工厂后建——事件期调用时引用已就位，TDZ 安全）。

import type { PDFSlick } from "@pdfslick/core";
import { classifyDestName } from "../logic/citekind";
import { bandElsNear, citeAnchorOf, destOf, type PdfPageDivOf } from "./pdfDom";
import type { DestPointRow, DestPosRow, DestSite } from "./pdfDestScan";

export interface PdfInspectDeps {
    viewer(): PDFSlick["viewer"] | undefined;
    destPos: Map<number, DestPosRow[]>;
    destSites: Map<string, DestSite[]>;
    destPoint: Map<string, DestPointRow>;
    pageDiv: PdfPageDivOf;
    openCard(a: Element): void;
    openUsagesFor(
        target: Element | string | null,
        anchor: Element | null,
        at?: Pick<DOMRect, "left" | "right" | "top" | "bottom">,
    ): boolean;
}

export interface PdfInspect {
    destAtPoint(
        x: number,
        y: number,
        tol?: number,
        opts?: { kinds?: ReadonlySet<string>; maxDx?: number },
    ): string | null;
    inspectAt(x: number, y: number): boolean;
    inspectDestAt(x: number, y: number): { dest: unknown } | null;
    destHotAt(
        x: number,
        y: number,
    ): { dest: string; els: HTMLElement[] } | null;
}

export const createPdfInspect = (deps: PdfInspectDeps): PdfInspect => {
    /** 本体坐标 → 落点 dest 名：posAtPoint 同法解页+分位（多取 x 分位做
        双栏并列消歧），同页 destPos 候选过「other 类拒收 + |Δfy|≤tol 闸 +
        Δfy+0.25Δfx 最近邻」；有引用站（destSites 非空）的候选优先——同距
        时「真被引过」的才是用户要答的。opts.kinds 收窄类型白名单、
        opts.maxDx 栏距闸（超距拒收——跨栏同高误吸用） */
    const destAtPoint = (
        x: number,
        y: number,
        tol = 0.4,
        opts?: { kinds?: ReadonlySet<string>; maxDx?: number },
    ): string | null => {
        const c = deps.viewer()?.container;
        if (!c) return null;
        const pg = c.ownerDocument
            .elementFromPoint(x, y)
            ?.closest<HTMLElement>("[data-page-number]");
        if (!pg || !c.contains(pg)) return null;
        const page = Number(pg.getAttribute("data-page-number"));
        if (!Number.isFinite(page)) return null;
        const r = pg.getBoundingClientRect();
        if (r.height <= 0 || r.width <= 0) return null;
        const fy = (y - r.top) / r.height;
        const fx = (x - r.left) / r.width;
        let bestAny: { score: number; name: string } | null = null;
        let bestHit: { score: number; name: string } | null = null;
        for (const d of deps.destPos.get(page) ?? []) {
            const kind = classifyDestName(d.name);
            if (kind === "other") continue;
            if (opts?.kinds && !opts.kinds.has(kind)) continue;
            const dy = Math.abs(d.frac - fy);
            if (dy > tol) continue;
            if (
                opts?.maxDx != null &&
                d.fx != null &&
                Math.abs(d.fx - fx) > opts.maxDx
            )
                continue;
            const score =
                dy +
                (d.fx != null ? Math.min(Math.abs(d.fx - fx), 1) * 0.25 : 0);
            if (!bestAny || score < bestAny.score)
                bestAny = { score, name: d.name };
            if (deps.destSites.get(d.name)?.length)
                if (!bestHit || score < bestHit.score)
                    bestHit = { score, name: d.name };
        }
        return (bestHit ?? bestAny)?.name ?? null;
    };

    // ⌘-Inspect 命中分面容差：落在 textLayer 字形上=行级紧收（±~2%页≈一行
    // 高，原 0.1 页分位会把上下五六行正文全吸进最近 dest）；紧窗落空且
    // 目标是浮动体（式号右置锚在左/多行式跨数行）→ 半窗补一刀不挂栏
    // 闸。空白/图形区=浮动体中窗（±9%页）+栏距闸 0.45——图面本体无字
    // 可点，适度窗是「点在图上」语义；0.45≈一栏宽，异栏同高不收而单栏
    // 锚在左、点在图心不冤
    const INSPECT_TEXT_TOL = 0.02;
    const INSPECT_TEXT_FLOAT_TOL = 0.045;
    const INSPECT_FLOAT_TOL = 0.09;
    const INSPECT_FLOAT_KINDS = new Set(["figure", "table", "equation"]);
    const inspectDestName = (
        x: number,
        y: number,
        t: Element | null,
    ): string | null => {
        const onText = t?.closest?.(".textLayer span") != null;
        if (onText)
            return (
                destAtPoint(x, y, INSPECT_TEXT_TOL) ??
                destAtPoint(x, y, INSPECT_TEXT_FLOAT_TOL, {
                    kinds: INSPECT_FLOAT_KINDS,
                })
            );
        return destAtPoint(x, y, INSPECT_FLOAT_TOL, {
            kinds: INSPECT_FLOAT_KINDS,
            maxDx: 0.45,
        });
    };

    // ⌘-Inspect：锚→bib 开 CiteCard/他开 UsagesCard；页内非锚命中
    // （分面容差 inspectDestName——文字行级紧收/空白浮动体中窗）→
    // 卡落点击矩形；other 类 dest 不出卡
    const inspectAt = (x: number, y: number): boolean => {
        const c = deps.viewer()?.container;
        if (!c) return false;
        const t = c.ownerDocument.elementFromPoint(x, y);
        const a = citeAnchorOf(t);
        if (a) {
            const dest = destOf(a);
            if (!dest) return false;
            if (classifyDestName(dest) === "other") return false;
            if (dest.startsWith("cite.")) {
                deps.openCard(a);
                return true;
            }
            return deps.openUsagesFor(dest, a);
        }
        const dest = inspectDestName(x, y, t);
        if (!dest) return false;
        const span =
            (t as Element | null)?.closest?.(".textLayer span") ?? null;
        return deps.openUsagesFor(dest, span, {
            left: x - 1,
            right: x + 1,
            top: y - 1,
            bottom: y + 1,
        });
    };

    const inspectDestAt = (x: number, y: number): { dest: unknown } | null => {
        const c = deps.viewer()?.container;
        if (!c) return null;
        const t = c.ownerDocument.elementFromPoint(x, y);
        const a = citeAnchorOf(t);
        if (a) {
            const dest = destOf(a);
            return dest && classifyDestName(dest) !== "other" ? { dest } : null;
        }
        const dest = inspectDestName(x, y, t);
        return dest ? { dest } : null;
    };

    // ⌘-Inspect armed hover 强化：非锚命中 → dest + 落点行带元素
    // （揭示染色面）；锚命中无需此路——锚自身 .insp-hot 已标
    const destHotAt = (
        x: number,
        y: number,
    ): { dest: string; els: HTMLElement[] } | null => {
        const c = deps.viewer()?.container;
        if (!c) return null;
        const t = c.ownerDocument.elementFromPoint(x, y);
        const dest = inspectDestName(x, y, t);
        if (!dest) return null;
        const pt = deps.destPoint.get(dest);
        const els = pt
            ? bandElsNear(deps.pageDiv, pt.page, pt.frac, pt.fx ?? undefined)
            : [];
        return { dest, els };
    };

    return { destAtPoint, inspectAt, inspectDestAt, destHotAt };
};
