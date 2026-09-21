// 阅读器窗格侧件的纯函数层 —— 文件大小/查找计数/大纲颜色/页面尺寸文案。
// 与 pdfjs/pdfslick 解耦，供 vitest 直接断言。

import type { DocId } from "./alignment";

/** pdfjs PDFFindController 的 FindState 枚举（web/pdf_viewer.mjs 不导出，本地镜像） */
export const FIND_STATE = { found: 0, notFound: 1, wrapped: 2, pending: 3 } as const;

export interface FindCount {
    current: number;
    total: number;
}

/** 查找条右侧计数文案：有匹配 → "n/m"；查无 → noneLabel；未查/查询中 → "" */
export function findCountText(
    state: number | null,
    count: FindCount | null,
    noneLabel: string,
): string {
    if (state === FIND_STATE.notFound) return noneLabel;
    if (count && count.total > 0) return `${count.current}/${count.total}`;
    return "";
}

/** 附件/文档信息的字节数 → "1.2 MB" 风格短文案 */
export function fmtBytes(n: number | null | undefined): string {
    if (n == null || !Number.isFinite(n) || n < 0) return "—";
    if (n < 1024) return `${n} B`;
    const units = ["KB", "MB", "GB", "TB"];
    let v = n / 1024;
    let i = 0;
    while (v >= 1024 && i < units.length - 1) {
        v /= 1024;
        i++;
    }
    return `${v >= 100 ? Math.round(v) : v.toFixed(1)} ${units[i]}`;
}

/** 大纲条目的 color: Uint8ClampedArray → CSS rgb()；缺色 → undefined */
export function outlineColor(c: ArrayLike<number> | null | undefined): string | undefined {
    if (!c || c.length < 3) return undefined;
    return `rgb(${c[0]}, ${c[1]}, ${c[2]})`;
}

export interface PageSizeInfo {
    width: string;
    height: string;
    unit: string;
    name?: string;
    orientation?: string;
}

/** 文档信息"页面大小"行：name + w×h unit + 方向（pdfjs 的 orientation 是英文 fallback，这里映射） */
export function pageSizeText(
    ps: PageSizeInfo | null | undefined,
    orient: { portrait: string; landscape: string },
): string {
    if (!ps) return "—";
    const dims = `${ps.width} × ${ps.height} ${ps.unit}`;
    const o =
        ps.orientation === "portrait"
            ? orient.portrait
            : ps.orientation === "landscape"
              ? orient.landscape
              : "";
    return [ps.name, dims, o].filter(Boolean).join(" · ");
}

/** 日期字段（creationDate 等可为 null）→ 本地串或 "—" */
export function fmtDate(d: Date | null | undefined): string {
    return d instanceof Date && !Number.isNaN(d.getTime()) ? d.toLocaleString() : "—";
}

/** 「下载带批注副本」文件名：{task}-{en|zh}-annotated.pdf */
export function annotFileName(taskId: string, side: DocId): string {
    return `${taskId}-${side === "original" ? "en" : "zh"}-annotated.pdf`;
}

/**
 * 缩放选择值 → html/dom 窗格正文字号（px）。pdf 走 setScale 不经过这里。
 * "%" 值按比例进 0.6–2.0 区间线性映射 12–22px；命名值（page-width 等
 * pdf 语义档）对文本视图无意义 → 回基准 15px（= .pane-html-body 默认值）。
 */
export function zoomToFontPx(z: string): number {
    const m = z.match(/^(\d+(?:\.\d+)?)%$/);
    if (!m) return 15;
    const ratio = Math.min(2, Math.max(0.6, Number(m[1]) / 100));
    return Math.round((12 + ((ratio - 0.6) * 10) / 1.4) * 10) / 10;
}

/** 渲染产物里的 http(s)/协议相对外链一律新开标签页 + noopener——pane 内默认跳转会顶掉阅读器 */
export function externalLinksBlank(root: ParentNode): void {
    for (const a of root.querySelectorAll<HTMLAnchorElement>(
        'a[href^="http"], a[href^="//"]',
    )) {
        a.target = "_blank";
        a.rel = "noopener noreferrer";
    }
}
