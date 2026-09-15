// 阅读器顶栏：三模式 Segmented + 同步开关 + 缩放 + 页码 + 下载菜单 + 重试/取消。

import { createSignal, For, Show } from "solid-js";
import Segmented from "./Segmented";
import type { FileKind, TaskStatus } from "../api/client";
import { isTerminal } from "../api/client";
import { t } from "../i18n/zh";
import type { DocId } from "../reader/alignment";

export type Mode = "original" | "translated" | "split";

export interface DownloadItem {
    kind: FileKind;
    label: string;
    url: string;
}

interface Props {
    title: string;
    status?: TaskStatus;
    mode: Mode;
    syncing: boolean;
    zoom: string;
    page: number;
    numPages: number;
    active: DocId;
    swapped: boolean;
    downloads: DownloadItem[];
    onMode(m: Mode): void;
    onSync(on: boolean): void;
    onZoom(z: string): void;
    onGotoPage(n: number): void;
    onSwap(): void;
    onActiveSide(s: DocId): void;
    onRetry(): void;
    onCancel(): void;
    onBack(): void;
}

const ZOOMS = ["page-fit", "page-width", "auto", "50%", "75%", "100%", "125%", "150%", "200%"];
const ZOOM_LABEL: Record<string, string> = {
    "page-fit": t.reader.zoomFit,
    "page-width": t.reader.zoomWidth,
    auto: t.reader.zoomAuto,
};

export default function Toolbar(props: Props) {
    const [menuOpen, setMenuOpen] = createSignal(false);
    let pageInput!: HTMLInputElement;

    const submitPage = () => {
        const n = Number(pageInput?.value);
        if (Number.isInteger(n) && n >= 1) props.onGotoPage(n);
    };

    return (
        <header class="reader-toolbar">
            <button type="button" class="tb-btn" onClick={() => props.onBack()} title={t.reader.back}>
                ← {t.reader.back}
            </button>
            <span class="tb-title" title={props.title}>
                {props.title}
            </span>

            <Segmented
                ariaLabel="阅读模式"
                options={[
                    { value: "original", label: t.reader.original },
                    { value: "translated", label: t.reader.translated },
                    { value: "split", label: t.reader.split },
                ]}
                value={props.mode}
                onChange={(m) => props.onMode(m)}
            />

            <Show when={props.mode === "split"}>
                <button
                    type="button"
                    class="tb-btn"
                    classList={{ on: props.syncing }}
                    onClick={() => props.onSync(!props.syncing)}
                    title={t.reader.sync}
                >
                    ⇅ {t.reader.sync}
                </button>
                <button type="button" class="tb-btn" onClick={() => props.onSwap()} title={t.reader.swap}>
                    ⇄ {t.reader.swap}
                </button>
            </Show>

            <select
                class="tb-select"
                value={props.zoom}
                onChange={(e) => props.onZoom(e.currentTarget.value)}
                aria-label="缩放"
            >
                <For each={ZOOMS}>
                    {(z) => <option value={z}>{ZOOM_LABEL[z] ?? z}</option>}
                </For>
            </select>

            <span class="tb-page">
                <input
                    ref={(el) => (pageInput = el)}
                    type="number"
                    min={1}
                    max={props.numPages}
                    value={props.page}
                    onKeyDown={(e) => e.key === "Enter" && submitPage()}
                    onBlur={submitPage}
                    aria-label={t.reader.page}
                />
                / {props.numPages || "—"}
            </span>

            <span class="tb-spacer" />

            <Show when={props.status && !isTerminal(props.status)}>
                <button type="button" class="tb-btn" onClick={() => props.onCancel()}>
                    {t.reader.cancel}
                </button>
            </Show>
            <Show when={props.status && isTerminal(props.status) && props.status !== "done"}>
                <button type="button" class="tb-btn" onClick={() => props.onRetry()}>
                    {t.reader.retry}
                </button>
            </Show>

            <div class="tb-menu-wrap">
                <button type="button" class="tb-btn" onClick={() => setMenuOpen((v) => !v)}>
                    ⬇ {t.reader.download}
                </button>
                <Show when={menuOpen()}>
                    <div class="tb-menu" onClick={() => setMenuOpen(false)}>
                        <For each={props.downloads}>
                            {(d) => (
                                <a href={d.url} download="">
                                    {d.label}
                                </a>
                            )}
                        </For>
                    </div>
                </Show>
            </div>
        </header>
    );
}
