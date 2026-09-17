// PaneSlot —— 单侧窗格槽：dom → DomPane（序列化 DOM 产物）/ html → HtmlPane
// （chunks→marked）/ pdf → PdfPane 三层分发。dom 与 pdf 同按 doc.version
// keyed 重挂——重译后旧产物不留残影；document 缺侧（该侧无产物）→ 占位 veil。
// 同步关闭且漂移 >500px 时叠 jump-back 钮（ReaderView 判定，props.drift 驱动）。

import { Show } from "solid-js";
import PdfPane, { type PaneHandle } from "./PdfPane";
import HtmlPane, { type HtmlPaneHandle } from "./HtmlPane";
import DomPane, { type DomPaneHandle } from "./DomPane";
import type { DocId } from "./alignment";
import type { DualChunk } from "../api/client";
import type { ReaderViewState } from "./view";
import { t } from "../i18n/zh";

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
    /** 「下载带批注副本」文件名（仅 PdfPane 用） */
    annotName: string;
    active: boolean;
    /** 同步关闭漂移 >500px → 显示跳回钮 */
    drift?: boolean;
    onReady(h: AnyHandle): void;
    onDispose(h: AnyHandle): void;
    onPageChange(n: number): void;
    onActivate(): void;
    onScroll(): void;
    onJumpBack(): void;
}

export default function PaneSlot(props: Props) {
    return (
        <div class="pane-slot">
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
                                active={props.active}
                                onReady={(h) => props.onReady(h)}
                                onDispose={(h) => props.onDispose(h)}
                                onActivate={() => props.onActivate()}
                                onScroll={() => props.onScroll()}
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
                            active={props.active}
                            onReady={(h) => props.onReady(h)}
                            onDispose={(h) => props.onDispose(h)}
                            onActivate={() => props.onActivate()}
                            onScroll={() => props.onScroll()}
                        />
                    }
                >
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
                            <PdfPane
                                url={props.url}
                                side={props.side}
                                annotName={props.annotName}
                                active={props.active}
                                onReady={(h) => props.onReady(h)}
                                onDispose={(h) => props.onDispose(h)}
                                onPageChange={(p) => props.onPageChange(p)}
                                onActivate={() => props.onActivate()}
                                onScroll={() => props.onScroll()}
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
        </div>
    );
}
