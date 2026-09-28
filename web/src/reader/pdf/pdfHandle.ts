// PdfPane 对外契约面——PaneHandle/Props/LinkServiceLike/PdfPageViewLike
// 纯类型声明（拆自 PdfPane.tsx，零运行时代码）。
// ReaderView 经 handles() 登记后以 ~20 处 h.xxx?.() 消费 PaneHandle；
// PaneSlot 按 Props 传参。sentalign/inspect/findusages 以接口形式声明
// 的桥面方法名与本 PaneHandle 一一对应。

import type { PDFSlick } from "@pdfslick/core";
import type { DocId, Pos } from "../logic/alignment";
import type { PaneLike } from "../logic/sync";
import type { BibEntry, CiteIndex, RefMeta } from "../cite/citations";
import type { KeptRef, TaskSnapshot } from "../../api/client";

export interface PaneHandle extends PaneLike {
    readonly slick: PDFSlick | null;
    numPages(): number;
    pageNumber(): number;
    gotoPage(n: number): void;
    setScaleValue(v: string): void;
    setScale(v: number): void;
    capture(): Pos;
    jump(pos: Pos): void;
    scrollTopFor(pos: Pos): number | null;
    /** 打开本窗格查找条（Ctrl+F 由上层路由到活动窗格）；
        query 注入输入框并发起查找（sel.find/pane.find 命令面） */
    openFind(query?: string): void;
    /** 镜像 named dest：走未包装的原始 goToDestination（不压本侧栈、
        不回传 nav 事件——ReaderView 拿到 pre/post 自记 dst 栈）；
        FitH/FitR 型 dest 临时免缩放重置。null=dst 无同名锚/未就绪 */
    mirrorDest?(dest: unknown): Promise<{ pre: Pos; post: Pos } | null>;
    /** Pos → 显式 dest 数组（sent-align DOM→PDF 路）：页0基 + XYZ
        锚点，y 为 bottom-up 点制 = (1-fraction)*页高；null=文档未就绪 */
    posDest?(pos: Pos): Promise<unknown[] | null>;
    /** 全页 Link annots 的 dest 名预扫产物（idle 切片渐进充填——返回
        当前已收子集，未扫完≠不存在）。M4 镜像/整合层的「本侧有无此
        dest」预检面 */
    dests?(): ReadonlySet<string>;
    /** sel-system Esc 栈查询/收面：'cite'=悬浮卡 'find'=查找条
        'info'=文档信息 */
    escOpen?(layer: string): boolean;
    escClose?(layer: string): void;
    /** pdf.js 批注编辑器态（keymap 占有判定）：armed=编辑模式开
        （高亮笔等 annotationEditorMode!=NONE）；selected=有选中批注
        （editingstateschanged.details.hasSelectedEditor 快照） */
    pdfjsState?(): { armed: boolean; selected: boolean };
    /** seq → 本窗格已渲染 span.markedContent 元素（跨页续段多枚；
        未渲染页缺席——调用方先 gotoPage/seqPage 定位） */
    seqEls?(seq: number): HTMLElement[];
    /** seq → 页码（idle seqmap 渐进充填——未扫到/无锚 null） */
    seqPage?(seq: number): number | null;
    /** 点击坐标 → Pos（sent-align PDF 源侧臂）：elementFromPoint 命中页 →
        {page, 页内 top-down 分位, x 页宽分位}；容器外/页间缝 null */
    posAtPoint?(x: number, y: number): Pos | null;
    /** 点击坐标 → seq（elementFromPoint 命中 markedContent span——
        TLXC 锚文档精确序；无锚命中/未渲染页 null，调用方按兜底语义走） */
    seqAtPoint?(x: number, y: number): number | null;
    /** Pos 落点闪示（sent-align PDF→PDF 臂）：命中页 textLayer 分位行带
        加 .sa-flash——单轨，新闪清旧闪。返回实际着闪元素集（anim 面） */
    flashAtPos?(pos: Pos): HTMLElement[];
    /** seq 锚闪示（sent-align seq 精度臂）：seqEls 命中则整组闪；
        无已渲染锚（懒渲染页/en.pdf 无标）→ pos 在场落回 flashAtPos。
        返回实际着闪元素集（anim 面） */
    flashSeq?(seq: number, pos: Pos | null): HTMLElement[];
    /** seq → markedContent 字形叶集（flashSeq 同源 leafEls 下钻）——
        sent-align 句级落点/闪示的原料面；未渲染页缺席 */
    seqLeaves?(seq: number): HTMLElement[];
    /** 任意字形叶集打闪（sent-align 句级叶集闪面——flashAtPos/flashSeq
        之外的第三闪；saFlash 单轨同口径） */
    flashEls?(els: HTMLElement[]): void;
    /** seq 悬停伴显（sent-align hover 臂）：cls=sa-hot|sa-peer 单轨染色
        ——锚叶集命中染锚；锚缺席（懒渲染页/无标文档）且 pos 在场落回
        行带；seq null 清轨。与 sa-flash 分轨互不清 */
    hoverSeq?(seq: number | null, pos: Pos | null, cls: string): void;
    /** 任意字形叶集染色（sent-align 句级悬停面——hoverSeq 的 els 版） */
    tintEls?(els: HTMLElement[], cls: string): void;
    /** dest（named/显式数组）→ 落点着陆闪：seq 命中闪锚叶，落回行带；
        goToDestination 落定/镜像落定/菜单跳的揭示共用面 */
    flashDest?(dest: unknown): void;
    /** ⌘-Inspect armed hover：非锚命中 → dest + 落点行带元素集（揭示
        染色原料）；锚命中走锚自身 .insp-hot 不入此路 */
    destHotAt?(
        x: number,
        y: number,
    ): { dest: string; els: HTMLElement[] } | null;
    /** 图/表/式/定理等本体坐标 → 落点 dest 名（destPos 反查——右键
        本体反查 usages 的命台面）；无候选/未扫完/other 类 null；
        tol=垂直分位容差（默认 0.4 右击档，⌘-Inspect 臂走紧档） */
    destAtPoint?(x: number, y: number, tol?: number): string | null;
    /** find-usages pdf 臂：cite.<key> dest 反查 link annot 站集开卡；
        at=显式卡锚矩形（右键本体路——锚元素缺席时卡落点击点） */
    openUsagesFor?(
        target: Element | string | null,
        anchor: Element | null,
        at?: Pick<DOMRect, "left" | "right" | "top" | "bottom">,
    ): boolean;
    /** ⌘-Inspect：坐标点 → 原地开检视卡（锚→目标卡/页内→UsagesCard）；
        handled=false 由闸按兜底语义走 */
    inspectAt?(x: number, y: number): boolean;
    /** ⌘-Inspect：坐标点 → 镜像载荷 {dest}；无可镜像物 null */
    inspectDestAt?(x: number, y: number): { dest: unknown } | null;
}

export interface LinkServiceLike {
    goToDestination(dest: unknown): Promise<void>;
    _ignoreDestinationZoom?: boolean;
}

export interface Props {
    url: string;
    side: DocId;
    /** 「下载带批注副本」文件名（Reader 按 taskId+side 拼好传入） */
    annotName?: string;
    active?: boolean;
    /** 引用索引（dual.json ph→bibMap）——缺位时卡片走 dest 懒抽取兜底 */
    citeIndex?: CiteIndex;
    /** L2 远端元数据回调——缺位卡片只出本地条目 */
    citeMeta?(key: string): RefMeta | undefined;
    /** kept_refs 收藏（M4）：卡 key = entry?.key ?? dest.slice(5) */
    citeKept?(key: string): boolean;
    onToggleKeep?(key: string, payload: KeptRef): void;
    /** 「翻译此文」提交（cite-translate lane）——宿主 ct.submit 包装；
        entry 恒非空（缺条目时合成 {key} 壳——懒抽取回包前也可点） */
    onTranslateRef?(entry: BibEntry): void | Promise<unknown>;
    /** 文献任务行覆写查询（缺省 RefTaskChip 内走 taskByArxiv） */
    refStatusOf?(arxivId: string): TaskSnapshot | undefined;
    onReady?(h: PaneHandle): void;
    onDispose?(h: PaneHandle): void;
    onPageChange?(page: number, numPages: number): void;
    onActivate?(): void;
    onScroll?(): void;
    /** 程序导航窗口开始（ReaderView 静音同步引擎+抑漂移） */
    onNavBegin?(): void;
    /** named-dest 跳转落定（pre/post 供跳回栈+镜像） */
    onDestJump?(dest: unknown, pre: Pos, post: Pos): void;
    /** PDF metadata Title 上报——Reader 层作顶栏/document.title 兜底 */
    onDocTitle?(title: string): void;
    /** 加载失败 veil 的重试——调用方换 key 整体重挂（url 不可在位换，§5.1） */
    onReload?(): void;
}

export interface PdfPageViewLike {
    div?: HTMLElement;
}
