// PdfPane idle 渐进扫描表——named-dest 预扫 + seqmap/usage 站集
// + dest 落点第二程，拆自 PdfPane.tsx。零 Solid 依赖纯 TS 工厂：
// abort() 由宿主组件 onCleanup 触发（五表随闭包随组件 GC）。

import {
    destPointOf,
    type PdfDocLike,
    type PdfPageLike,
} from "../cite/citations";
import { seqOfTextItem } from "./pdfmarks";

/** dest 名 → 指向它的 link annot 站（usages pdf 臂数据源）；
    frac/fx=锚位页内分位（卡站行语境抽取用） */
export interface DestSite {
    page: number;
    y: number;
    frac?: number;
    fx?: number;
}

/** 页内 dest 落点行——{name, 页内 top-down 分位, x 分位} */
export interface DestPosRow {
    name: string;
    frac: number;
    fx: number | null;
}

/** dest 名 → 落点（destPos 的反查面——落定闪/行带揭示的点名寻址） */
export interface DestPointRow {
    page: number;
    frac: number;
    fx: number | null;
}

/** seq → {page, 内容流 item 区间}（item 层 id 尾解码——DOM id
    撞名风险旁路主径；begin/end 供 seq→页内分位跳转） */
export interface SeqPageRow {
    page: number;
    begin: number;
    end: number;
}

export interface DestScan {
    /** named-dest 名集——dests() 预检面/labelAnchor 渲染播种共用
        同一实例（写入面必须留本实例上，勿换只读视图） */
    destNames: Set<string>;
    destSites: Map<string, DestSite[]>;
    /** 页 → dest 落点表——图/式本体右键反查 usages 的命台面；
        getDestinations 词表驱动、idle 渐进充填 */
    destPos: Map<number, DestPosRow[]>;
    destPoint: Map<string, DestPointRow>;
    seqPageMap: Map<number, SeqPageRow>;
    scanDests(doc: PdfDocLike, numPages: number): void;
    /** 卸载置旗即止（迟到回包 add 进闭包集合无害） */
    abort(): void;
}

export const createDestScan = (deps: {
    /** 当前视口页（viewer().currentPageNumber 桥——螺旋扫描中心） */
    currentPage(): number | undefined;
    pdfDoc(): PdfDocLike | null;
}): DestScan => {
    // named-dest 预扫（镜像「本侧有无此 dest」预检面）+ seqmap/usage 站集：
    // 文档就绪后 idle 逐页收 Link annots 的 dest 名/位置 + textContent
    // marked-content item。三表边扫边长——dests()/seqPage() 恒返回已收
    // 子集；卸载置 abort 旗即止（迟到回包 add 进闭包集合无害，组件随
    // 闭包 GC）。
    const destNames = new Set<string>();
    const destSites = new Map<string, DestSite[]>();
    const destPos = new Map<number, DestPosRow[]>();
    const destPoint = new Map<string, DestPointRow>();
    const seqPageMap = new Map<number, SeqPageRow>();
    let destScanAbort = false;
    const scanDests = (doc: PdfDocLike, numPages: number) => {
        const idle =
            window.requestIdleCallback ??
            ((f: () => void) => window.setTimeout(f, 20));
        // 视口页为中心螺旋外扫——annotations/seqmap 的可用性跟着用户
        // 视线走（原序扫时非首页读者的本体反查/句跳要干等全文档扫完）
        const cur = Math.min(
            Math.max(deps.currentPage() ?? 1, 1),
            Math.max(numPages, 1),
        );
        const order: number[] = [];
        for (let d = 0; d < numPages; d++) {
            if (cur + d <= numPages) order.push(cur + d);
            if (d > 0 && cur - d >= 1) order.push(cur - d);
        }
        let oi = 0;
        const step = async () => {
            if (destScanAbort || oi >= order.length) return;
            const page = order[oi++]!;
            try {
                const pg = await doc.getPage(page);
                const annots = await (
                    pg as PdfPageLike & {
                        getAnnotations?(o: {
                            intent: string;
                        }): Promise<{ dest?: unknown; rect?: number[] }[]>;
                    }
                ).getAnnotations?.({ intent: "display" });
                const pview = (pg as unknown as { view?: number[] }).view;
                const vw =
                    pview && pview.length >= 4 ? pview[2]! - pview[0]! : 0;
                const vh =
                    pview && pview.length >= 4 ? pview[3]! - pview[1]! : 0;
                // 只收字符串 named-dest（数组形 explicit dest 无键可查）
                for (const a of annots ?? [])
                    if (typeof a?.dest === "string") {
                        destNames.add(a.dest);
                        const arr =
                            destSites.get(a.dest) ??
                            destSites.set(a.dest, []).get(a.dest)!;
                        // annot.rect=[x1,y1,x2,y2] bottom-up——y2=锚顶
                        arr.push({
                            page,
                            y: Array.isArray(a.rect) ? (a.rect[3] ?? 0) : 0,
                            frac:
                                vh > 0 && Array.isArray(a.rect)
                                    ? Math.min(
                                          Math.max(
                                              1 -
                                                  (a.rect[3]! - pview![1]!) /
                                                      vh,
                                              0,
                                          ),
                                          1,
                                      )
                                    : undefined,
                            fx:
                                vw > 0 && Array.isArray(a.rect)
                                    ? Math.min(
                                          Math.max(
                                              (a.rect[0]! - pview![0]!) / vw,
                                              0,
                                          ),
                                          1,
                                      )
                                    : undefined,
                        });
                    }
                const tc = await (
                    pg as PdfPageLike & {
                        getTextContent?(o: {
                            includeMarkedContent: boolean;
                        }): Promise<{ items?: unknown[] }>;
                    }
                ).getTextContent?.({ includeMarkedContent: true });
                // MC 区域栈：文档自有 BMC/BDC 可与 TLXC 互嵌——begin 记
                // 区间起点，end 在配对 endMarkedContent 落定（未配平
                // 留 begin 值，页内分位仍是诚实下界）
                const mcStack: (number | null)[] = [];
                (tc?.items ?? []).forEach((it, i) => {
                    const ty = (it as { type?: unknown }).type;
                    if (
                        ty === "beginMarkedContent" ||
                        ty === "beginMarkedContentProps"
                    ) {
                        const s = seqOfTextItem(it);
                        if (s != null && !seqPageMap.has(s))
                            seqPageMap.set(s, { page, begin: i, end: i });
                        mcStack.push(s);
                    } else if (ty === "endMarkedContent") {
                        const s = mcStack.pop();
                        const rec = s != null ? seqPageMap.get(s) : undefined;
                        if (rec && rec.page === page) rec.end = i;
                    }
                });
            } catch {
                /* 单页注记/文本拉取失败不挡后续页 */
            }
            if (!destScanAbort && oi < order.length) idle(() => void step());
        };
        void step();
        // dest 落点解析与页扫并行——二者独立面，串行时 destAtPoint 要等
        // 全页扫完才活（本体反查/Inspect 命台面死窗 = 整个页扫时长）
        void resolveDestPoints();
    };

    /** 第二程：dest 词表 → 落点页内分位（本体反查命台面）。
        getDestinations 一把梭全词表，getPageIndex/getPage 逐名解——
        页对象按号缓存复用，idle 切片 24 名/帧不堵交互。无 y 的整页锚
        记 0.5（「页中」是最近邻口径下最诚实的落点——顶/底会偏吸页沿）。 */
    const resolveDestPoints = async () => {
        const d = deps.pdfDoc();
        if (!d?.getDestinations) return;
        // pdf.js≥4 返回 Map（词表含 name-tree 锚——LaTeX 引擎的 dest 全在
        // 那）；老版本/测试桩是 Record——两形都收，漏读 Map 是词表全空的
        // 静默塌方（posTotal=0 → destAtPoint 恒 null）
        let all: Map<string, unknown> | Record<string, unknown>;
        try {
            all = (await d.getDestinations()) ?? new Map();
        } catch {
            return;
        }
        const idle =
            window.requestIdleCallback ??
            ((f: () => void) => window.setTimeout(f, 20));
        const pageCache = new Map<number, Promise<PdfPageLike>>();
        const pageOf = (n: number) => {
            let p = pageCache.get(n);
            if (!p) {
                p = d.getPage(n);
                pageCache.set(n, p);
            }
            return p;
        };
        const entries =
            all instanceof Map ? [...all.entries()] : Object.entries(all);
        let i = 0;
        const step = async () => {
            if (destScanAbort || i >= entries.length) return;
            const slice = entries.slice(i, i + 24);
            i += 24;
            for (const [name, raw] of slice) {
                // 词表值应是 dest 数组；{D:…} 包装形防御摊平
                const pt = destPointOf(
                    Array.isArray(raw)
                        ? raw
                        : (raw as { D?: unknown } | null)?.D,
                );
                if (!pt) continue;
                try {
                    const pnum = (await d.getPageIndex(pt.ref)) + 1;
                    const pg = await pageOf(pnum);
                    const view = (pg as unknown as { view?: number[] }).view;
                    const vp = pg.getViewport({ scale: 1 });
                    const h =
                        view && view.length >= 4
                            ? view[3] - view[1]
                            : vp.height;
                    const w =
                        view && view.length >= 4 ? view[2] - view[0] : vp.width;
                    if (!(h > 0)) continue;
                    const x0 = view?.[0] ?? 0;
                    const y0 = view?.[1] ?? 0;
                    const frac =
                        pt.y == null
                            ? 0.5
                            : Math.min(Math.max(1 - (pt.y - y0) / h, 0), 1);
                    const fx =
                        pt.x == null || !(w > 0)
                            ? null
                            : Math.min(Math.max((pt.x - x0) / w, 0), 1);
                    const arr =
                        destPos.get(pnum) ?? destPos.set(pnum, []).get(pnum)!;
                    arr.push({ name, frac, fx });
                    destPoint.set(name, { page: pnum, frac, fx });
                } catch {
                    /* 单 dest 解页失败不挡后续名 */
                }
            }
            if (!destScanAbort && i < entries.length) idle(() => void step());
        };
        void step();
    };

    const abort = () => {
        destScanAbort = true;
    };

    return {
        destNames,
        destSites,
        destPos,
        destPoint,
        seqPageMap,
        scanDests,
        abort,
    };
};
