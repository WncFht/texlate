// RefsPanel —— 文献表抽屉面板：全部可解析条目 + 顶部「翻译全部」批量 CTA。
// 规格 §B：行=label/截断正文/id 徽标（arXiv|DOI|无）/RefTaskChip/meta 标题；
// 「翻译全部」→ preflight 一拍分 done/active/new 三桶（双侧 canon）→ 确认
// 弹层（计数/ETA 区间/warn_big 警示逐字文案）→ 仅 new 臂串行灌队。
// done/active 行渲链接 #/reader/{task_id}；批任务不开独立 SSE——行状态骑
// taskStore 共享列表轮询 + intents 竞态桥（track 登记后行未物化也解得出）。
//
// 样式走内联（styles 表不在本 lane 权属——整合期可上提 cite.css）；
// z 层约定（selsys.css 注）：cite-card=30 < floatbar=35 < ctx-menu=40，
// 面板取 45（盖住菜单层，仍在 toast-host 之下）。

import {
    createSignal,
    For,
    onCleanup,
    onMount,
    Show,
} from "solid-js";
import {
    api,
    apiErrText,
    type TaskSnapshot,
} from "../api/client";
import { taskStore } from "../stores/tasks";
import { toast } from "../stores/toastStore";
import {
    ctText,
    estimateEta,
    fmtEta,
    REF_WARN_BIG,
    type CiteTranslate,
    type PreflightBuckets,
    type RefItem,
} from "./citeTranslate";
import { type BibEntry, type RefMeta } from "./citations";
import { readerHashWithFrom } from "./tasknav";
import RefTaskChip from "./RefTaskChip";

const PANEL_Z = 45;

interface Props {
    /** citeIndex.entries() + lazy-dest 已抽条目（宿主组装） */
    entries: BibEntry[];
    /** L2 元数据活访问器（回包晚到时行内补 meta 标题/arXiv 升级链） */
    meta?(key: string): RefMeta | undefined;
    /** 编排工厂实例（features/citetranslate.ts 创建注入） */
    ct: CiteTranslate;
    onClose(): void;
}

/** 条目可译 id——L1 抽取 arxivId 优先，L2 meta.externalIds.ArXiv 反补兜底
    （DOI-only 条目经 S2 反补后同样可译） */
const entryArxiv = (
    e: BibEntry,
    meta: Props["meta"],
): string | undefined => e.arxivId ?? meta?.(e.key)?.arxivId;

export default function RefsPanel(props: Props) {
    const [confirm, setConfirm] = createSignal<PreflightBuckets | null>(null);
    /** preflight/submit 在飞锁（防双击连发） */
    const [busy, setBusy] = createSignal<"preflight" | "submit" | null>(null);
    /** 内联 key 框——批内 401/凭证门宿主 + needs_auth 行「输 Key 重试」共用；
        run=key 收妥后的续跑回调（submit 续发 / api.retry 续跑） */
    const [authBox, setAuthBox] = createSignal<{
        key: string;
        run: (apiKey: string) => Promise<unknown>;
    } | null>(null);
    const [authBusy, setAuthBusy] = createSignal(false);
    let panelEl!: HTMLDivElement;

    // 挂载期自登记为工厂的 key 面板宿主——submit/submitAll 的 auth 分支
    // 走本面板内联框；卸载摘回（卡脚钮等其它入口回落工厂默认宿主）
    onMount(() => {
        props.ct.setAuthHost((retry) =>
            setAuthBox({ key: "", run: retry }),
        );
    });
    onCleanup(() => props.ct.setAuthHost(undefined));

    // Esc 序：确认层在 → 先收确认层；内联 key 框在 → 收 key 框；否则收面板。
    // capture + stopPropagation——不让 ReaderView 的全局 Esc 抢（卡优先收）。
    onMount(() => {
        const onKey = (e: KeyboardEvent) => {
            if (e.key !== "Escape") return;
            e.stopPropagation();
            if (confirm()) setConfirm(null);
            else if (authBox()) setAuthBox(null);
            else props.onClose();
        };
        document.addEventListener("keydown", onKey, true);
        onCleanup(() =>
            document.removeEventListener("keydown", onKey, true),
        );
    });
    onMount(() => queueMicrotask(() => panelEl?.focus()));

    /** 可译条目集（有 arXiv id 的行——DOI-only 无 id 行不灌队只列出） */
    const items = (): RefItem[] =>
        props.entries.flatMap((entry) => {
            const id = entryArxiv(entry, props.meta);
            return id ? [{ arxivId: id, entry }] : [];
        });

    const rowOf = (e: BibEntry): TaskSnapshot | undefined => {
        const id = entryArxiv(e, props.meta);
        return id ? taskStore.taskByArxiv(id) : undefined;
    };

    /** 「翻译全部」→ preflight 一拍三桶（~2ms；不可省——bare-id 重提钉版
        done 行会产幽灵 202 行） */
    const openConfirm = async () => {
        if (busy()) return;
        setBusy("preflight");
        try {
            setConfirm(await props.ct.preflight(items()));
        } catch (e) {
            toast.err(apiErrText(e));
        } finally {
            setBusy(null);
        }
    };

    /** 确认 CTA → 仅 new 臂串行灌队（409/200 收编照常——preflight 快照与
        服务端判定间的竞态由 dedup 兜底吸收） */
    const runBatch = async () => {
        const b = confirm();
        if (!b || busy()) return;
        setBusy("submit");
        try {
            const out = await props.ct.submitAll(b.fresh);
            for (const f of out.failed)
                toast.err(`${f.arxivId}: ${f.message}`);
            if (out.stoppedBy !== "auth") setConfirm(null);
        } finally {
            setBusy(null);
        }
    };

    /** needs_auth 行/401 续跑统一内联 key 框提交 */
    const submitAuth = async () => {
        const a = authBox();
        if (!a || authBusy() || !a.key.trim()) return;
        setAuthBusy(true);
        try {
            await a.run(a.key.trim());
            setAuthBox(null);
            // 批 401 续跑后确认层已没必要留（续跑在工厂内重入 submitAll）
            setConfirm(null);
        } catch (e) {
            toast.err(apiErrText(e));
        } finally {
            setAuthBusy(false);
        }
    };

    /** needs_auth 行内「输 Key 重试」——同 task_id retry 须重带
        X-Texlate-Key 头（settings 存 key 不解 header 源任务） */
    const rowAuth = (taskId: string) =>
        setAuthBox({
            key: "",
            run: async (apiKey) => {
                const res = await api.retry(
                    taskId,
                    undefined,
                    { apiKey },
                );
                taskStore.patch(taskId, {
                    status: res.status,
                    stage: undefined,
                    message: undefined,
                    error: null,
                    progress: 0,
                });
                taskStore.resetLive(taskId);
            },
        });

    const idBadge = (e: BibEntry): { kind: "arxiv" | "doi" | "none"; text: string } => {
        if (entryArxiv(e, props.meta)) return { kind: "arxiv", text: "arXiv" };
        if (e.doi ?? props.meta?.(e.key)?.doi)
            return { kind: "doi", text: "DOI" };
        return { kind: "none", text: ctText("idNone") };
    };

    const etaLine = (b: PreflightBuckets): string => {
        const { lo, hi } = estimateEta(b.counts.active + b.counts.fresh);
        return ctText("waitEta", { lo: fmtEta(lo), hi: fmtEta(hi) });
    };

    return (
        <div
            ref={(el) => (panelEl = el)}
            role="dialog"
            aria-modal="true"
            aria-label={ctText("panelTitle")}
            tabIndex={-1}
            style={{
                position: "fixed",
                top: 0,
                right: 0,
                bottom: 0,
                width: "min(460px, 94vw)",
                "z-index": PANEL_Z,
                display: "flex",
                "flex-direction": "column",
                background: "var(--chrome-bg, #fff)",
                "box-shadow": "-8px 0 28px rgba(0,0,0,.18)",
                "border-left": "1px solid var(--line,#d8d2c4)",
                outline: "none",
            }}
        >
            {/* 头：标题 + 翻译全部 CTA + 关 */}
            <div
                style={{
                    display: "flex",
                    "align-items": "center",
                    gap: "8px",
                    padding: "10px 14px",
                    "border-bottom": "1px solid var(--line,#d8d2c4)",
                }}
            >
                <strong style={{ flex: 1, "font-size": "14px" }}>
                    {ctText("panelTitle")}
                </strong>
                <button
                    type="button"
                    class="tb-btn"
                    disabled={busy() !== null || items().length === 0}
                    onClick={() => void openConfirm()}
                >
                    {busy() === "preflight"
                        ? ctText("preflightBusy")
                        : busy() === "submit"
                          ? ctText("submitBusy")
                          : ctText("translateAll")}
                </button>
                <button
                    type="button"
                    class="tb-btn"
                    aria-label={ctText("close")}
                    onClick={() => props.onClose()}
                >
                    ×
                </button>
            </div>

            {/* 确认弹层——三桶计数 + ETA 区间 + warn_big 警示（文案逐字 §B） */}
            <Show when={confirm()}>
                {(b) => (
                    <div
                        role="alertdialog"
                        aria-label={ctText("confirmTitle")}
                        style={{
                            margin: "10px 14px",
                            padding: "12px",
                            border: "1px solid var(--line,#d8d2c4)",
                            "border-radius": "8px",
                            background: "var(--paper,#fbf7ec)",
                        }}
                    >
                        <div style={{ "font-weight": 600, "margin-bottom": "6px" }}>
                            {ctText("confirmTitle")}
                        </div>
                        <div>
                            {ctText("counts", {
                                total: b().counts.total,
                                n_new: b().counts.fresh,
                                n_active: b().counts.active,
                                n_done: b().counts.done,
                            })}
                        </div>
                        <Show when={b().counts.fresh + b().counts.active > 0}>
                            <div class="muted">{etaLine(b())}</div>
                        </Show>
                        <div class="muted">{ctText("hint")}</div>
                        <Show when={b().counts.fresh > REF_WARN_BIG}>
                            <div
                                role="alert"
                                style={{
                                    "margin-top": "6px",
                                    padding: "6px 8px",
                                    "border-radius": "6px",
                                    background: "var(--warn-bg,#f7e6d0)",
                                    color: "var(--warn-fg,#7a4b12)",
                                }}
                            >
                                {ctText("warnBig", {
                                    n: b().counts.fresh,
                                    lo: fmtEta(
                                        estimateEta(
                                            b().counts.active + b().counts.fresh,
                                        ).lo,
                                    ),
                                    hi: fmtEta(
                                        estimateEta(
                                            b().counts.active + b().counts.fresh,
                                        ).hi,
                                    ),
                                })}
                            </div>
                        </Show>
                        <div style={{ "margin-top": "10px", display: "flex", gap: "8px" }}>
                            <button
                                type="button"
                                class="tb-btn"
                                disabled={
                                    b().counts.fresh === 0 || busy() === "submit"
                                }
                                onClick={() => void runBatch()}
                            >
                                {b().counts.fresh === 0
                                    ? ctText("ctaAllDone")
                                    : ctText("cta", { n: b().counts.fresh })}
                            </button>
                            <button
                                type="button"
                                class="tb-btn"
                                onClick={() => setConfirm(null)}
                            >
                                {ctText("authCancel")}
                            </button>
                        </div>
                    </div>
                )}
            </Show>

            {/* 内联 key 框——凭证门/401/needs_auth 三流合一 */}
            <Show when={authBox()}>
                {(a) => (
                    <div
                        style={{
                            margin: "10px 14px",
                            padding: "12px",
                            border: "1px solid var(--line,#d8d2c4)",
                            "border-radius": "8px",
                        }}
                    >
                        <div class="muted" style={{ "margin-bottom": "6px" }}>
                            {ctText("toastAuth")}
                        </div>
                        <input
                            type="password"
                            class="tx-select"
                            style={{ width: "100%", "box-sizing": "border-box" }}
                            placeholder={ctText("authPlaceholder")}
                            aria-label={ctText("authPlaceholder")}
                            value={a().key}
                            onInput={(e) =>
                                setAuthBox({
                                    key: e.currentTarget.value,
                                    run: a().run,
                                })
                            }
                            onKeyDown={(e) => {
                                if (e.key === "Enter") {
                                    e.preventDefault();
                                    void submitAuth();
                                }
                                e.stopPropagation();
                            }}
                        />
                        <div style={{ "margin-top": "8px", display: "flex", gap: "8px" }}>
                            <button
                                type="button"
                                class="tb-btn"
                                disabled={authBusy() || !a().key.trim()}
                                onClick={() => void submitAuth()}
                            >
                                {ctText("authSubmit")}
                            </button>
                            <button
                                type="button"
                                class="tb-btn"
                                onClick={() => setAuthBox(null)}
                            >
                                {ctText("authCancel")}
                            </button>
                        </div>
                    </div>
                )}
            </Show>

            {/* 条目行——label/截断正文/id 徽标/状态钮/meta 标题；
                done|active 行渲链接 #/reader/{task_id} */}
            <div style={{ flex: 1, "overflow-y": "auto", padding: "6px 14px 14px" }}>
                <For each={props.entries}>
                    {(e, i) => {
                        const aid = () => entryArxiv(e, props.meta);
                        const m = () => props.meta?.(e.key);
                        const row = () => rowOf(e);
                        const linkable = () => {
                            const r = row();
                            return r && !["fault", "cancelled", "interrupted"].includes(r.status)
                                ? r.task_id
                                : undefined;
                        };
                        const badge = () => idBadge(e);
                        return (
                            <div
                                class="refs-row"
                                style={{
                                    display: "flex",
                                    "align-items": "flex-start",
                                    gap: "8px",
                                    padding: "8px 0",
                                    "border-bottom":
                                        "1px solid var(--line,#ece6d8)",
                                }}
                            >
                                <span
                                    style={{
                                        flex: "none",
                                        "min-width": "2.4em",
                                        "font-weight": 600,
                                        color: "var(--muted,#8a8578)",
                                    }}
                                >
                                    {e.label || `[${e.order || i() + 1}]`}
                                </span>
                                <div style={{ flex: 1, "min-width": 0 }}>
                                    <Show
                                        when={linkable()}
                                        fallback={
                                            <div
                                                style={{
                                                    display: "-webkit-box",
                                                    "-webkit-line-clamp": "2",
                                                    "-webkit-box-orient": "vertical",
                                                    overflow: "hidden",
                                                }}
                                            >
                                                {e.text}
                                            </div>
                                        }
                                    >
                                        {(tid) => (
                                            <a
                                                href={readerHashWithFrom(tid())}
                                                style={{
                                                    display: "-webkit-box",
                                                    "-webkit-line-clamp": "2",
                                                    "-webkit-box-orient": "vertical",
                                                    overflow: "hidden",
                                                    color: "inherit",
                                                }}
                                            >
                                                {e.text}
                                            </a>
                                        )}
                                    </Show>
                                    <Show when={m()?.title}>
                                        <div class="muted" style={{ "font-size": "12px" }}>
                                            {m()?.title}
                                        </div>
                                    </Show>
                                </div>
                                <span
                                    class={`refs-id refs-id-${badge().kind}`}
                                    style={{
                                        flex: "none",
                                        "font-size": "11px",
                                        padding: "1px 6px",
                                        "border-radius": "999px",
                                        border: "1px solid var(--line,#d8d2c4)",
                                        color:
                                            badge().kind === "none"
                                                ? "var(--muted,#8a8578)"
                                                : "inherit",
                                    }}
                                    title={
                                        aid() ??
                                        e.doi ??
                                        props.meta?.(e.key)?.doi ??
                                        undefined
                                    }
                                >
                                    {badge().text}
                                </span>
                                <Show when={aid()}>
                                    {(id) => (
                                        <RefTaskChip
                                            arxivId={id()}
                                            onTranslate={() =>
                                                props.ct.submit(id(), {
                                                    quiet: false,
                                                })
                                            }
                                            onAuth={(tid) => rowAuth(tid)}
                                        />
                                    )}
                                </Show>
                            </div>
                        );
                    }}
                </For>
            </div>
        </div>
    );
}
