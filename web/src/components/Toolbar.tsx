// 阅读器顶栏：三模式 Segmented + 同步开关 + 缩放 + 页码 + 下载菜单 + 重试/取消。

import { createEffect, createSignal, For, Show, untrack } from "solid-js";
import Segmented from "./Segmented";
import { settingsStore } from "../stores/settings";
import { taskStore } from "../stores/tasks";
import { PAPER_LABEL, PAPER_THEME_IDS } from "../reader/pdfTheme";
import { bindMenuDismiss, menuRoving, menuTriggerKey } from "./menuNav";
import type { FileKind, TaskStatus } from "../api/client";
import { isTerminal } from "../api/client";
import { t } from "../i18n";
import { ctText } from "../reader/citeTranslate";

export type Mode = "original" | "translated" | "split" | "guide";

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
    downloads: DownloadItem[];
    /** arXiv 任务 → 顶栏出 arxiv.org/abs 直达链 + Segmented 导读档 */
    arxivId?: string;
    /** 页码控件单位文案（html/dom 视图定位单位是段不是页） */
    pageUnit?: string;
    onMode(m: Mode): void;
    onSync(on: boolean): void;
    onZoom(z: string): void;
    onGotoPage(n: number): void;
    onSwap(): void;
    onRetry(): void;
    onCancel(): void;
    onBack(): void;
    /** 「?」快捷键帮助钮（ReaderView 开浮层） */
    onHelp?(): void;
    /** done 态分享钮——父层给 onShare 才出；弹层在 ReaderView（.tb-host 内） */
    onShare?(): void;
    shareOpen?: boolean;
    shareBtnRef?(el: HTMLButtonElement): void;
    /** 「文献」钮——onRefs 在且 refsTotal>0（citeIndex.size）才出；
        角标=refsCount 可译条数（0 不出角标）；≤640px 副本在 ⋯ 菜单 */
    onRefs?(): void;
    refsTotal?: number;
    refsCount?: number;
}

const ZOOMS = [
    "page-fit",
    "page-width",
    "auto",
    "50%",
    "75%",
    "100%",
    "125%",
    "150%",
    "200%",
];
const ZOOM_LABEL: Record<string, string> = {
    "page-fit": t.reader.zoomFit,
    "page-width": t.reader.zoomWidth,
    auto: t.reader.zoomAuto,
};
export default function Toolbar(props: Props) {
    const [menuOpen, setMenuOpen] = createSignal(false);
    const [moreOpen, setMoreOpen] = createSignal(false);
    // 页码输入走本地 draft：编辑中不被滚动回写的 props.page 打断
    const [draft, setDraft] = createSignal(untrack(() => String(props.page)));
    const [editing, setEditing] = createSignal(false);
    let menuWrap!: HTMLDivElement;
    let menuBtn: HTMLButtonElement | undefined;
    let moreWrap!: HTMLDivElement;
    let moreBtn: HTMLButtonElement | undefined;

    createEffect(() => {
        const p = props.page;
        if (!editing()) setDraft(String(p));
    });

    // 合法值（1..numPages）才提交；非法输入回退当前页
    const commitPage = () => {
        const n = Number(draft());
        if (
            Number.isInteger(n) &&
            n >= 1 &&
            (!props.numPages || n <= props.numPages)
        ) {
            if (n !== props.page) props.onGotoPage(n);
        } else {
            setDraft(String(props.page));
        }
    };

    // 下载菜单 dismiss：外部点击收 / Escape 收+焦点回触发钮（menuNav 共享件）
    bindMenuDismiss({
        open: menuOpen,
        close: () => setMenuOpen(false),
        wrap: () => menuWrap,
        trigger: () => menuBtn,
    });
    bindMenuDismiss({
        open: moreOpen,
        close: () => setMoreOpen(false),
        wrap: () => moreWrap,
        trigger: () => moreBtn,
    });

    // 导读档仅 arXiv 任务出（upload/doc 任务无 alphaXiv 导读）
    const segOpts = (): { value: Mode; label: string }[] => {
        const o: { value: Mode; label: string }[] = [
            { value: "original", label: t.reader.original },
            { value: "translated", label: t.reader.translated },
            { value: "split", label: t.reader.split },
        ];
        if (props.arxivId) o.push({ value: "guide", label: t.reader.guide });
        return o;
    };

    return (
        <header class="reader-toolbar">
            <button
                type="button"
                class="tb-btn"
                onClick={() => props.onBack()}
                title={t.reader.back}
            >
                ← {t.reader.back}
            </button>
            {/* 任务观测 chip——reader 页 .topnav 隐藏留下的真空洞由它补：
                点击→#/tasks；计数与 App.tsx 徽标同口径（非终态数，
                interrupted 属终态不计）。桌面常显——绝不能挂 .tb-opt
                （≤640px 会被连带藏掉）；窄屏副本在 ⋯ 菜单首项 */}
            <a class="tb-btn" href="#/tasks" title={t.nav.tasks}>
                {t.nav.tasks}
                <Show when={taskStore.activeCount() > 0}>
                    <span class="nav-badge">{taskStore.activeCount()}</span>
                </Show>
            </a>
            {/* 「文献」钮——refsTotal>0 才出（父层 citeIndex.size 闸）；
                角标=可译条数。窄屏 .tb-opt 藏，副本在 ⋯ 菜单 */}
            <Show when={props.onRefs && (props.refsTotal ?? 0) > 0}>
                <button
                    type="button"
                    class="tb-btn tb-opt"
                    onClick={() => props.onRefs?.()}
                    title={ctText("panelTitle")}
                >
                    {ctText("refs")}
                    <Show when={(props.refsCount ?? 0) > 0}>
                        <span class="nav-badge">{props.refsCount}</span>
                    </Show>
                </button>
            </Show>
            <span class="tb-title" title={props.title}>
                {props.title}
            </span>

            {/* ⋯ 溢出菜单——≤640px 由 responsive.css 翻出，收纳 .tb-opt 控件。
                DOM 位置紧贴 title：移动端与返回同行居右上，桌面 display:none 无布局影响 */}
            <div
                class="tb-menu-wrap tb-more-wrap"
                ref={(el) => (moreWrap = el)}
            >
                <button
                    type="button"
                    class="tb-btn"
                    ref={(el) => (moreBtn = el)}
                    aria-haspopup="menu"
                    aria-expanded={moreOpen()}
                    aria-label={t.reader.more}
                    title={t.reader.more}
                    onClick={() => setMoreOpen((v) => !v)}
                    onKeyDown={(e) =>
                        menuTriggerKey(
                            e,
                            () => setMoreOpen(true),
                            () => moreWrap,
                        )
                    }
                >
                    ⋯
                </button>
                <Show when={moreOpen()}>
                    <div
                        class="tb-menu"
                        role="menu"
                        onKeyDown={(e) =>
                            menuRoving(e, () => setMoreOpen(false))
                        }
                    >
                        {/* 任务入口副本（≤640px ⋯ 菜单才翻出）——role=menuitem
                            才入 menuRoving 漫游圈；hash 跳走顺手收菜单 */}
                        <a
                            role="menuitem"
                            tabIndex={-1}
                            href="#/tasks"
                            onClick={() => setMoreOpen(false)}
                        >
                            {t.nav.tasks}
                            <Show when={taskStore.activeCount() > 0}>
                                <span class="nav-badge">
                                    {taskStore.activeCount()}
                                </span>
                            </Show>
                        </a>
                        {/* 「文献」窄屏副本——同显隐闸；role=menuitem 入
                            menuRoving 漫游圈 */}
                        <Show when={props.onRefs && (props.refsTotal ?? 0) > 0}>
                            <button
                                type="button"
                                role="menuitem"
                                tabIndex={-1}
                                onClick={() => {
                                    props.onRefs?.();
                                    setMoreOpen(false);
                                }}
                            >
                                {ctText("refs")}
                                <Show when={(props.refsCount ?? 0) > 0}>
                                    <span class="nav-badge">
                                        {props.refsCount}
                                    </span>
                                </Show>
                            </button>
                        </Show>
                        <div class="tb-menu-sep" />
                        <Show when={props.mode === "split"}>
                            <button
                                type="button"
                                role="menuitem"
                                tabIndex={-1}
                                classList={{ on: props.syncing }}
                                onClick={() => {
                                    props.onSync(!props.syncing);
                                    setMoreOpen(false);
                                }}
                            >
                                ⇅ {t.reader.sync}
                            </button>
                            <button
                                type="button"
                                role="menuitem"
                                tabIndex={-1}
                                onClick={() => {
                                    props.onSwap();
                                    setMoreOpen(false);
                                }}
                            >
                                ⇄ {t.reader.swap}
                            </button>
                        </Show>
                        <label class="tb-menu-row">
                            {t.reader.appearance}
                            <select
                                class="tb-select tx-select"
                                role="menuitem"
                                tabIndex={-1}
                                value={settingsStore.paperTheme()}
                                onChange={(e) =>
                                    settingsStore.setPaperTheme(
                                        e.currentTarget.value as Parameters<
                                            typeof settingsStore.setPaperTheme
                                        >[0],
                                    )
                                }
                                onKeyDown={(e) => {
                                    if (
                                        e.key === "ArrowDown" ||
                                        e.key === "ArrowUp" ||
                                        e.key === "ArrowLeft" ||
                                        e.key === "ArrowRight" ||
                                        e.key === "Home" ||
                                        e.key === "End"
                                    ) {
                                        e.stopPropagation();
                                    }
                                }}
                            >
                                <For each={PAPER_THEME_IDS}>
                                    {(id) => (
                                        <option value={id}>
                                            {PAPER_LABEL[id]}
                                        </option>
                                    )}
                                </For>
                            </select>
                        </label>
                        <label class="tb-menu-row">
                            {t.reader.zoom}
                            {/* role=menuitem 收进 menuRoving 漫游圈（≤640px 时
                                此处是唯一缩放控件）；方向键/Home/End 留给 select
                                原生改值不上冒（否则被 roving 抢走焦点），
                                Tab/Escape 照常上冒收菜单 */}
                            <select
                                class="tb-select tx-select"
                                role="menuitem"
                                tabIndex={-1}
                                value={props.zoom}
                                onChange={(e) =>
                                    props.onZoom(e.currentTarget.value)
                                }
                                onKeyDown={(e) => {
                                    if (
                                        e.key === "ArrowDown" ||
                                        e.key === "ArrowUp" ||
                                        e.key === "ArrowLeft" ||
                                        e.key === "ArrowRight" ||
                                        e.key === "Home" ||
                                        e.key === "End"
                                    ) {
                                        e.stopPropagation();
                                    }
                                }}
                            >
                                <For each={ZOOMS}>
                                    {(z) => (
                                        <option value={z}>
                                            {ZOOM_LABEL[z] ?? z}
                                        </option>
                                    )}
                                </For>
                            </select>
                        </label>
                        <Show when={props.arxivId}>
                            {(id) => (
                                <a
                                    role="menuitem"
                                    tabIndex={-1}
                                    href={`https://arxiv.org/abs/${id()}`}
                                    target="_blank"
                                    rel="noopener noreferrer"
                                    onClick={() => setMoreOpen(false)}
                                >
                                    arXiv ↗
                                </a>
                            )}
                        </Show>
                        <Show when={props.onShare}>
                            <button
                                type="button"
                                role="menuitem"
                                tabIndex={-1}
                                onClick={() => {
                                    props.onShare?.();
                                    setMoreOpen(false);
                                }}
                            >
                                ⇧ {t.reader.share}
                            </button>
                        </Show>
                        <Show when={props.downloads.length > 0}>
                            <div class="tb-menu-sep" />
                            <For each={props.downloads}>
                                {(d) => (
                                    <a
                                        href={d.url}
                                        download=""
                                        role="menuitem"
                                        tabIndex={-1}
                                        onClick={() => setMoreOpen(false)}
                                    >
                                        {d.label}
                                    </a>
                                )}
                            </For>
                        </Show>
                        <div class="tb-menu-sep" />
                        <button
                            type="button"
                            role="menuitem"
                            tabIndex={-1}
                            onClick={() => {
                                props.onHelp?.();
                                setMoreOpen(false);
                            }}
                        >
                            ? {t.reader.helpTitle}
                        </button>
                    </div>
                </Show>
            </div>
            <Show when={props.arxivId}>
                {(id) => (
                    <a
                        class="tb-btn tb-opt"
                        href={`https://arxiv.org/abs/${id()}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        title={t.reader.arxivLink}
                        aria-label={t.reader.arxivLink}
                    >
                        arXiv ↗
                    </a>
                )}
            </Show>

            <Segmented
                ariaLabel={t.reader.mode}
                options={segOpts()}
                value={props.mode}
                onChange={(m) => props.onMode(m)}
            />

            <Show when={props.mode === "split"}>
                <button
                    type="button"
                    class="tb-btn tb-opt"
                    classList={{ on: props.syncing }}
                    onClick={() => props.onSync(!props.syncing)}
                    title={t.reader.sync}
                >
                    ⇅ {t.reader.sync}
                </button>
                <button
                    type="button"
                    class="tb-btn tb-opt"
                    onClick={() => props.onSwap()}
                    title={t.reader.swap}
                >
                    ⇄ {t.reader.swap}
                </button>
            </Show>

            <select
                class="tb-select tb-opt tx-select"
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
                    aria-label={props.pageUnit ?? t.reader.page}
                />
                / {props.numPages || "—"}
            </span>

            <span class="tb-spacer" />

            <Show when={props.status && !isTerminal(props.status)}>
                <button
                    type="button"
                    class="tb-btn"
                    onClick={() => props.onCancel()}
                >
                    {t.reader.cancel}
                </button>
            </Show>
            <Show
                when={
                    props.status &&
                    isTerminal(props.status) &&
                    props.status !== "done"
                }
            >
                <button
                    type="button"
                    class="tb-btn"
                    onClick={() => props.onRetry()}
                >
                    {t.reader.retry}
                </button>
            </Show>

            <Show when={props.onShare}>
                <button
                    type="button"
                    class="tb-btn tb-opt tb-share"
                    ref={(el) => props.shareBtnRef?.(el)}
                    aria-haspopup="dialog"
                    aria-expanded={!!props.shareOpen}
                    title={t.reader.shareBtnTip}
                    onClick={() => props.onShare?.()}
                >
                    ⇧ {t.reader.share}
                </button>
            </Show>

            {/* 外观（纸面色板即阅读主题,chrome 跟随派生）——阅读器内唯一
                主题控件;窄屏收进 ⋯ 菜单里的同款 select */}
            <select
                class="tb-select tb-opt tx-select"
                value={settingsStore.paperTheme()}
                onChange={(e) =>
                    settingsStore.setPaperTheme(
                        e.currentTarget.value as Parameters<
                            typeof settingsStore.setPaperTheme
                        >[0],
                    )
                }
                aria-label={t.reader.appearance}
                title={t.reader.appearance}
            >
                <For each={PAPER_THEME_IDS}>
                    {(id) => <option value={id}>{PAPER_LABEL[id]}</option>}
                </For>
            </select>

            <button
                type="button"
                class="tb-btn tb-opt"
                title={t.reader.helpTitle}
                aria-label={t.reader.helpTitle}
                onClick={() => props.onHelp?.()}
            >
                ?
            </button>

            <div class="tb-menu-wrap tb-opt" ref={(el) => (menuWrap = el)}>
                <button
                    type="button"
                    class="tb-btn"
                    ref={(el) => (menuBtn = el)}
                    aria-haspopup="menu"
                    aria-expanded={menuOpen()}
                    disabled={props.downloads.length === 0}
                    onClick={() => setMenuOpen((v) => !v)}
                    onKeyDown={(e) =>
                        menuTriggerKey(
                            e,
                            () => setMenuOpen(true),
                            () => menuWrap,
                        )
                    }
                >
                    ⬇ {t.reader.download}
                </button>
                <Show when={menuOpen()}>
                    <div
                        class="tb-menu"
                        role="menu"
                        onClick={() => setMenuOpen(false)}
                        onKeyDown={(e) =>
                            menuRoving(e, () => setMenuOpen(false))
                        }
                    >
                        <For each={props.downloads}>
                            {(d) => (
                                <a
                                    href={d.url}
                                    download=""
                                    role="menuitem"
                                    tabIndex={-1}
                                >
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
