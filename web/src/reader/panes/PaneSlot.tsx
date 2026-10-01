// PaneSlot —— 单侧窗格槽：dom → DomPane（序列化 DOM 产物）/ html → HtmlPane
// （chunks→marked）/ pdf → PdfPane 三层分发。dom 与 pdf 同按 doc.version
// keyed 重挂——重译后旧产物不留残影；document 缺侧（该侧无产物）→ 占位 veil。
// 同步关闭且漂移 >500px 时叠 jump-back 钮（ReaderView 判定，props.drift 驱动）。
//
// U3：切栏不再卸载隐藏侧——props.hidden → display:none 保活（pdf.js
// ResizeObserver 自愈重排），PdfPane 不再因 split↔单栏整份重载。
// PdfPane 错误重试经 onReload → nonce 换 key 整体重挂（url 不可在位换，§5.1）。

import { createSignal, Show } from "solid-js";
import PdfPane from "./PdfPane";
import type { PaneHandle } from "../pdf/pdfHandle";
import HtmlPane, { type HtmlPaneHandle } from "./HtmlPane";
import DomPane, { type DomPaneHandle } from "./DomPane";
import type { DocId, Pos } from "../logic/alignment";
import type { BibEntry, CiteIndex, RefMeta } from "../cite/citations";
import type { DualChunk, KeptRef, TaskSnapshot } from "../../api/client";
import type { ReaderViewState } from "../logic/view";
import { keptRefs } from "../../stores/keptRefs";
import { t } from "../../i18n";

/** 三种窗格上报的 handle 联合（同步引擎/持久化走 PaneLike 公共面） */
export type AnyHandle = PaneHandle | HtmlPaneHandle | DomPaneHandle;

interface Props {
    side: DocId;
    /** 当前阅读视图（调用方已保证 ∈ pdf/html/dom） */
    view: ReaderViewState;
    /** documents[side].version || undefined——keyed Show 的 when 不许 "" */
    version: string | undefined;
    /** docUrl 解析结果（dom=html 产物 / pdf=pdf 产物，含 version 校验） */
    url: string;
    /** dual.json chunks——仅 html 视图消费 */
    chunks: DualChunk[];
    /** 单段重译通路（仅 HtmlPane 用）：taskId + 终态可重译 */
    taskId?: string;
    canRetranslate?: boolean;
    /** 在飞重译 seq 集（sel-system：ReaderView 持有并喂 hitctx
        chunk.pending——与 HtmlPane 内部防抖同一份才实时） */
    retxPending?: Set<number>;
    /** 「下载带批注副本」文件名（仅 PdfPane 用） */
    annotName: string;
    active: boolean;
    /** true → 槽位 display:none 但保持挂载（切栏保活，U3） */
    hidden?: boolean;
    /** 分栏拖拽比例落点：flex-grow（仅 split 传入） */
    grow?: number;
    /** 同步关闭漂移 >500px → 显示跳回钮 */
    drift?: boolean;
    /** 引用索引（pdf 卡内容）+ 远端元数据回调 */
    citeIndex?: CiteIndex;
    citeMeta?(key: string): RefMeta | undefined;
    /** 文献「翻译此文」提交 + 任务行查询（cite-translate lane——
        目前仅 PdfPane 卡路接通；dom 侧卡宿主不在本批权属） */
    onTranslateRef?(entry: BibEntry): void | Promise<unknown>;
    refStatusOf?(arxivId: string): TaskSnapshot | undefined;
    /** 跳回栈深度（反应式）——nav chip 显隐 */
    navDepth?(): { back: boolean; fwd: boolean };
    onNavBack?(): void;
    onNavFwd?(): void;
    onReady(h: AnyHandle): void;
    onDispose(h: AnyHandle): void;
    onPageChange(n: number): void;
    onActivate(): void;
    onScroll(): void;
    onJumpBack(): void;
    /** 程序导航窗口开始 / named-dest 跳落定（pdf+dom 同口径回传） */
    onNavBegin?(): void;
    onDestJump?(dest: unknown, pre: Pos, post: Pos): void;
    /** PDF metadata Title 上报（仅 pdf 视图） */
    onDocTitle?(title: string): void;
}

export default function PaneSlot(props: Props) {
    // PdfPane 错误重试：nonce 并进 keyed key——重挂即重取（版本未变也强制）
    const [pdfNonce, bumpPdfNonce] = createSignal(0);
    const pdfKey = () =>
        props.version ? `${props.version}#${pdfNonce()}` : undefined;

    // kept refs（M4）：模块单例直读——ReaderView 不透传这两个回调，
    // taskId 是本槽既有 prop。toggle 在 store 内乐观+串行落库。
    const citeKept = (key: string) => keptRefs.isKept(key);
    const onToggleKeep = (key: string, payload: KeptRef) => {
        const id = props.taskId;
        if (id) keptRefs.toggle(id, key, payload);
    };

    return (
        <div
            class="pane-slot"
            style={{
                display: props.hidden ? "none" : "",
                "flex-grow": props.grow != null ? String(props.grow) : "",
            }}
        >
            <Show
                when={props.view !== "dom"}
                fallback={
                    <Show
                        when={props.version}
                        keyed
                        fallback={
                            <div class="pane-veil pane-empty">
                                <p class="muted">{t.reader.docMissing}</p>
                            </div>
                        }
                    >
                        {(_v) => (
                            <DomPane
                                side={props.side}
                                url={props.url}
                                chunks={props.chunks}
                                active={props.active}
                                citeMeta={props.citeMeta}
                                citeKept={citeKept}
                                onToggleKeep={onToggleKeep}
                                onReady={(h) => props.onReady(h)}
                                onDispose={(h) => props.onDispose(h)}
                                onActivate={() => props.onActivate()}
                                onScroll={() => props.onScroll()}
                                onNavBegin={() => props.onNavBegin?.()}
                                onDestJump={(d, pre, post) =>
                                    props.onDestJump?.(d, pre, post)
                                }
                            />
                        )}
                    </Show>
                }
            >
                <Show
                    when={props.view !== "html"}
                    fallback={
                        <HtmlPane
                            side={props.side}
                            chunks={props.chunks}
                            taskId={props.taskId}
                            canRetranslate={props.canRetranslate}
                            retxPending={props.retxPending}
                            active={props.active}
                            onReady={(h) => props.onReady(h)}
                            onDispose={(h) => props.onDispose(h)}
                            onActivate={() => props.onActivate()}
                            onScroll={() => props.onScroll()}
                            onNavBegin={() => props.onNavBegin?.()}
                            onDestJump={(d, pre, post) =>
                                props.onDestJump?.(d, pre, post)
                            }
                        />
                    }
                >
                    <Show
                        when={pdfKey()}
                        keyed
                        fallback={
                            <div class="pane-veil pane-empty">
                                <p class="muted">{t.reader.docMissing}</p>
                            </div>
                        }
                    >
                        {(_v) => (
                            <PdfPane
                                url={props.url}
                                side={props.side}
                                annotName={props.annotName}
                                active={props.active}
                                citeIndex={props.citeIndex}
                                citeMeta={props.citeMeta}
                                citeKept={citeKept}
                                onToggleKeep={onToggleKeep}
                                onTranslateRef={props.onTranslateRef}
                                refStatusOf={props.refStatusOf}
                                onReady={(h) => props.onReady(h)}
                                onDispose={(h) => props.onDispose(h)}
                                onPageChange={(p) => props.onPageChange(p)}
                                onActivate={() => props.onActivate()}
                                onScroll={() => props.onScroll()}
                                onNavBegin={() => props.onNavBegin?.()}
                                onDestJump={(d, pre, post) =>
                                    props.onDestJump?.(d, pre, post)
                                }
                                onDocTitle={(ti) => props.onDocTitle?.(ti)}
                                onReload={() => bumpPdfNonce((n) => n + 1)}
                            />
                        )}
                    </Show>
                </Show>
            </Show>
            <Show when={props.drift}>
                <button
                    type="button"
                    class="jump-back"
                    onClick={() => props.onJumpBack()}
                >
                    ⌖ {t.reader.jumpBack}
                </button>
            </Show>
            {/* 导航栈 chip——压栈过才显；与 drift 钮共存时导航栈语义优先
                （程序跳转窗口内 ReaderView 已抑 drift 重算） */}
            <Show
                when={
                    props.navDepth &&
                    (props.navDepth().back || props.navDepth().fwd)
                }
            >
                <div class="nav-chip">
                    <Show when={props.navDepth?.().back}>
                        <button
                            type="button"
                            class="nav-chip-btn"
                            onClick={() => props.onNavBack?.()}
                        >
                            ↩ {t.cite.navBack}
                        </button>
                    </Show>
                    <Show when={props.navDepth?.().fwd}>
                        <button
                            type="button"
                            class="nav-chip-btn"
                            onClick={() => props.onNavFwd?.()}
                        >
                            ↪ {t.cite.navFwd}
                        </button>
                    </Show>
                </div>
            </Show>
        </div>
    );
}
