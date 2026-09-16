// 阅读器顶栏：三模式 Segmented + 同步开关 + 缩放 + 页码 + 下载菜单 + 重试/取消。

import { createEffect, createSignal, For, onCleanup, onMount, Show, untrack } from "solid-js";
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
    /** false（HTML 视图）时禁用页码跳转 */
    canGotoPage?: boolean;
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
    // 页码输入走本地 draft：编辑中不被滚动回写的 props.page 打断
    const [draft, setDraft] = createSignal(untrack(() => String(props.page)));
    const [editing, setEditing] = createSignal(false);
    let menuWrap!: HTMLDivElement;

    createEffect(() => {
        const p = props.page;
        if (!editing()) setDraft(String(p));
    });

    // 合法值（1..numPages）才提交；非法输入回退当前页
    const commitPage = () => {
        const n = Number(draft());
        if (Number.isInteger(n) && n >= 1 && (!props.numPages || n <= props.numPages)) {
            if (n !== props.page) props.onGotoPage(n);
        } else {
            setDraft(String(props.page));
        }
    };

    // 下载菜单：外部点击 / Escape 关闭
    onMount(() => {
        const onDown = (e: PointerEvent) => {
            if (menuOpen() && !menuWrap.contains(e.target as Node)) setMenuOpen(false);
        };
        const onKey = (e: KeyboardEvent) => {
            if (e.key === "Escape") setMenuOpen(false);
        };
        document.addEventListener("pointerdown", onDown);
        document.addEventListener("keydown", onKey);
        onCleanup(() => {
            document.removeEventListener("pointerdown", onDown);
            document.removeEventListener("keydown", onKey);
        });
    });

    const noGoto = () => props.canGotoPage === false;

    return (
        <header class="reader-toolbar">
            <button type="button" class="tb-btn" onClick={() => props.onBack()} title={t.reader.back}>
                ← {t.reader.back}
            </button>
            <span class="tb-title" title={props.title}>
                {props.title}
            </span>

            <Segmented
                ariaLabel={t.reader.mode}
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
                aria-label={t.reader.zoom}
            >
                <For each={ZOOMS}>
                    {(z) => <option value={z}>{ZOOM_LABEL[z] ?? z}</option>}
                </For>
            </select>

            <span class="tb-page">
                <input
                    type="number"
                    min={1}
                    max={props.numPages}
                    value={draft()}
                    disabled={noGoto()}
                    title={noGoto() ? t.reader.noPageJump : undefined}
                    onInput={(e) => setDraft(e.currentTarget.value)}
                    onFocus={() => setEditing(true)}
                    onKeyDown={(e) => {
                        if (e.key === "Enter") {
                            commitPage();
                            e.currentTarget.blur();
                        } else if (e.key === "Escape") {
                            setDraft(String(props.page));
                            e.currentTarget.blur();
                        }
                    }}
                    onBlur={() => {
                        commitPage();
                        setEditing(false);
                    }}
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

            <div class="tb-menu-wrap" ref={(el) => (menuWrap = el)}>
                <button
                    type="button"
                    class="tb-btn"
                    aria-haspopup="menu"
                    aria-expanded={menuOpen()}
                    disabled={props.downloads.length === 0}
                    onClick={() => setMenuOpen((v) => !v)}
                >
                    ⬇ {t.reader.download}
                </button>
                <Show when={menuOpen()}>
                    <div class="tb-menu" role="menu" onClick={() => setMenuOpen(false)}>
                        <For each={props.downloads}>
                            {(d) => (
                                <a href={d.url} download="" role="menuitem">
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
