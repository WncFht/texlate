// HtmlPane —— 降级视图（upload_pdf MinerU markdown / 编译失败但译文在库）。
// marked 渲染 + KaTeX auto-render（管线与 LivePane 共用 reader/markdown.ts）；
// [data-chunk] 块当"页"用，chunk 对严格 1:1（seq 直映），同步复用
// SyncEngine —— 比 PDF 锚更准（§5.4）。
//
// 译文侧未译段（status!=ok，或旧 dual.json 无 status 但 zh 空）内联
// 「未翻译」徽标；done/partial 终态挂 hover「重译」钮 →
// api.retranslateChunk 入队后轮询该 seq 的 chunks 窗，zh 落地就地重绘。
//
// marked/katex（~300KB）只服务本视图——dynamic import 挪出 pdf/dom 常用路
// （P1）；css 同捆进本 chunk。拉取/解析期给 veil，不白屏。

import {
    createEffect,
    createSignal,
    onCleanup,
    onMount,
    Show,
    untrack,
} from "solid-js";

import type { DocId, Pos } from "./alignment";
import { escapeHtml } from "./sanitize";
import {
    chunkSideText,
    chunkUntranslated,
    loadMdLibs,
    type MdLibs,
} from "./markdown";
import { externalLinksBlank } from "./paneUtils";
import { CHUNK_WINDOW } from "./chunkPoll";
import {
    bindChunkGeom,
    capturePos,
    jumpTo,
    scrollTopFor,
    type PageGeom,
    type PaneLike,
} from "./sync";
import { api, ApiError, type DualChunk } from "../api/client";
import { t } from "../i18n";

/** 单段重译后等待新 zh 落地的轮询参数 */
const RETX_POLL_MS = 2000;
const RETX_TIMEOUT_MS = 60_000;
const RETX_TOAST_MS = 4500;

export interface HtmlPaneHandle extends PaneLike {
    gotoPage?(n: number): void;
    capture(): Pos;
    jump(pos: Pos): void;
    scrollTopFor(pos: Pos): number | null;
    /** html/dom 缩放落点：正文字号（px） */
    setFontSize?(px: number): void;
}

interface Props {
    side: DocId;
    chunks: DualChunk[];
    /** 单段重译通路：两者俱有才挂「重译」钮（终态 done/partial 由调用方判） */
    taskId?: string;
    canRetranslate?: boolean;
    active?: boolean;
    onReady?(h: HtmlPaneHandle): void;
    onDispose?(h: HtmlPaneHandle): void;
    onActivate?(): void;
    onScroll?(): void;
}

export default function HtmlPane(props: Props) {
    let scrollEl!: HTMLDivElement;
    let bodyEl!: HTMLDivElement;
    const [ready, setReady] = createSignal(false);
    const geom = bindChunkGeom(
        () => scrollEl,
        () => bodyEl,
    );

    // 渲染库就位后留在组件态——重译就地重绘同一管线
    let libs: MdLibs | null = null;
    /** 重译更新的段覆盖层（props.chunks 是不可变快照，zh 落地写这里） */
    const overrides = new Map<number, DualChunk>();
    /** 在飞重译 seq——按钮防抖 + 卸载断 poll */
    const pending = new Set<number>();
    const [note, setNote] = createSignal("");
    let noteTimer = 0;

    const handle: HtmlPaneHandle = {
        side: untrack(() => props.side),
        get el() {
            return scrollEl;
        },
        pages(): PageGeom[] {
            return geom.pages();
        },
        capture() {
            return capturePos(this);
        },
        // 页码 = chunk 序：跳到第 n 段顶
        gotoPage(n) {
            jumpTo(this, { page: n, fraction: 0, viewport: 0 });
        },
        jump(pos) {
            jumpTo(this, pos);
        },
        scrollTopFor(pos) {
            return scrollTopFor(this, pos);
        },
        setFontSize(px) {
            bodyEl.style.fontSize = `${px}px`;
        },
    };

    const toast = (msg: string) => {
        setNote(msg);
        window.clearTimeout(noteTimer);
        noteTimer = window.setTimeout(() => setNote(""), RETX_TOAST_MS);
    };

    const seqAttr = (seq: number): string =>
        Number.isInteger(seq) ? String(seq) : escapeHtml(String(seq));

    /** 段 → <section class="chunk"> 串：译文侧未译段带徽标，可重译挂 hover 钮 */
    const sectionHtml = (c: DualChunk): string => {
        const cur = overrides.get(c.seq) ?? c;
        const md = chunkSideText(cur, props.side);
        const inner = libs ? libs.mdToHtml(md) : `<p>${escapeHtml(md)}</p>`;
        let s = `<section class="chunk" data-chunk="${seqAttr(c.seq)}">`;
        // 「未翻译」只标译文侧——原文侧显原文是本职，徽标反成噪声
        if (props.side === "translated" && chunkUntranslated(cur))
            s += `<span class="chunk-badge">${t.live.untranslated}</span>`;
        if (props.canRetranslate && props.taskId && Number.isInteger(c.seq))
            s += `<button type="button" class="chunk-retx" data-retx="${seqAttr(c.seq)}" title="${t.live.retranslate}">${t.live.retranslate}</button>`;
        return `${s}${inner}</section>`;
    };

    /** 重译落地：overrides 已写 → 该段整节重建 + KaTeX 重扫（按钮重新生成） */
    const repaint = (seq: number) => {
        const sec = bodyEl.querySelector(`section[data-chunk="${seq}"]`);
        const c = overrides.get(seq);
        if (!sec || !c) return;
        const tmp = document.createElement("div");
        tmp.innerHTML = sectionHtml(c);
        const fresh = tmp.firstElementChild as HTMLElement | null;
        if (!fresh) return;
        sec.replaceWith(fresh);
        // 重绘段含新外链——初始渲染挂过，就地重绘也要挂（与 mount 路径同口径）
        externalLinksBlank(fresh);
        libs?.renderMath(fresh);
        geom.rebind();
    };

    /** 202 入队 → 轮询该 seq 所在 chunks 窗（offset=seq 直取），zh 变化即就地更新 */
    const retranslate = async (seq: number, btn: HTMLButtonElement) => {
        const taskId = props.taskId;
        if (!taskId || pending.has(seq)) return;
        pending.add(seq);
        btn.disabled = true;
        btn.textContent = t.live.retranslating;
        try {
            await api.retranslateChunk(taskId, seq);
        } catch (e) {
            toast(
                `${t.live.retxFail}：${e instanceof ApiError ? e.detail : e instanceof Error ? e.message : String(e)}`,
            );
            pending.delete(seq);
            btn.disabled = false;
            btn.textContent = t.live.retranslate;
            return;
        }
        const before =
            overrides.get(seq)?.zh ??
            props.chunks.find((c) => c.seq === seq)?.zh ??
            "";
        const deadline = Date.now() + RETX_TIMEOUT_MS;
        while (!disposed && Date.now() < deadline) {
            await new Promise((r) => window.setTimeout(r, RETX_POLL_MS));
            if (disposed) break;
            try {
                // 快径 offset=seq 直取一行（chunks 页按 seq 升序、seq 0 基
                // 连续的服务端契约）；未命中退整窗扫描——offset 语义漂移
                // （稀疏 seq/行序变化）时仍找得到
                let row = (
                    await api.taskChunks(taskId, seq, 1)
                ).chunks.find((r) => r.seq === seq);
                if (!row) {
                    row = (
                        await api.taskChunks(taskId, 0, CHUNK_WINDOW)
                    ).chunks.find((r) => r.seq === seq);
                }
                if (row && row.zh !== before) {
                    const base =
                        overrides.get(seq) ??
                        props.chunks.find((c) => c.seq === seq);
                    overrides.set(seq, {
                        ...(base ?? { seq }),
                        zh: row.zh,
                        status: row.status,
                    });
                    repaint(seq);
                    toast(t.live.retxDone);
                    pending.delete(seq);
                    return;
                }
            } catch {
                /* 轮询抖动——继续等到超时 */
            }
        }
        if (!disposed) {
            toast(t.live.retxTimeout);
            pending.delete(seq);
            btn.disabled = false;
            btn.textContent = t.live.retranslate;
        }
    };

    const onBodyClick = (e: MouseEvent) => {
        const btn = (e.target as HTMLElement).closest<HTMLButtonElement>(
            ".chunk-retx",
        );
        if (!btn || btn.disabled) return;
        const seq = Number(btn.dataset.retx);
        if (!Number.isInteger(seq)) return;
        void retranslate(seq, btn);
    };

    let disposed = false;
    onMount(async () => {
        libs = await loadMdLibs().catch(() => null);
        if (disposed) return;
        // 库加载失败仍出转义原文——比永远停在 veil  spinner 强
        bodyEl.innerHTML =
            props.chunks.map(sectionHtml).join("") ||
            `<p class="chunk-empty">${t.reader.chunkEmpty}</p>`;
        externalLinksBlank(bodyEl);
        libs?.renderMath(bodyEl);
        bodyEl.addEventListener("click", onBodyClick);
        geom.rebind();
        setReady(true);
        props.onReady?.(handle);
    });
    onCleanup(() => {
        disposed = true;
        window.clearTimeout(noteTimer);
        bodyEl.removeEventListener("click", onBodyClick);
        geom.dispose();
        props.onDispose?.(handle);
    });

    createEffect(() => {
        const el = scrollEl;
        const l = () => props.onScroll?.();
        el.addEventListener("scroll", l, { passive: true });
        onCleanup(() => el.removeEventListener("scroll", l));
    });

    return (
        <div
            ref={(el) => (scrollEl = el)}
            class="pane pane-html"
            tabindex="0"
            classList={{ active: !!props.active }}
            data-side={props.side}
            onPointerDown={() => props.onActivate?.()}
        >
            <div ref={(el) => (bodyEl = el)} class="pane-html-body" />
            <div
                class="pane-toast"
                classList={{ show: !!note() }}
                role="status"
            >
                {note()}
            </div>
            <Show when={!ready()}>
                <div class="pane-veil">
                    <div
                        class="spinner"
                        role="status"
                        aria-label={t.pane.loading}
                    />
                </div>
            </Show>
        </div>
    );
}
