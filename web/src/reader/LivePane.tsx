// LivePane —— 翻译进行中的「边译边读」面板：api.taskChunks 轮询（2.5s
// 一拍，照 ChunkPreview 模式，组件卸载即停）累积段落到本地 map，已译段
// 走 HtmlPane 同一条 marked → DOMPurify → KaTeX 管线全渲染；未译段
// （status!=ok 或 zh 空）显原文 + 「未翻译」徽标。
//
// 增量 DOM 补丁：seq → <section> 映射 + 有序插入，每拍只重绘变化段，
// 滚动位置与已渲染公式不动。折叠容器恒挂载（display 自门控），
// 首段到达即自动可用；再大任务也限 CHUNKS_PAGE_MAX 窗内。

import { createSignal, onCleanup, onMount } from "solid-js";
import { api, type TaskChunksPage } from "../api/client";
import { chunkUntranslated, loadMdLibs, type MdLibs } from "./markdown";
import { escapeHtml } from "./sanitize";
import { t } from "../i18n/zh";

export interface LiveChunk {
    seq: number;
    kind?: string;
    status?: string;
    en?: string;
    zh?: string;
}

/**
 * 一页 chunks 合并进累积 map——新增/zh/status/en/kind 变动的行返回为
 * dirty（调用方只重绘这些）；非法 seq 丢弃。与轮询频率解耦，供 vitest 直测。
 */
export function mergeLive(
    acc: Map<number, LiveChunk>,
    rows: LiveChunk[],
): LiveChunk[] {
    const dirty: LiveChunk[] = [];
    for (const r of rows) {
        if (typeof r.seq !== "number" || !Number.isFinite(r.seq)) continue;
        const cur = acc.get(r.seq);
        if (
            cur &&
            cur.status === r.status &&
            cur.zh === r.zh &&
            cur.en === r.en &&
            cur.kind === r.kind
        )
            continue;
        acc.set(r.seq, {
            seq: r.seq,
            kind: r.kind,
            status: r.status,
            en: r.en,
            zh: r.zh,
        });
        dirty.push(r);
    }
    return dirty;
}

const POLL_MS = 2500;
/** 段窗上限——与 server CHUNKS_PAGE_MAX（500）同值，一页拉全量段 */
const WINDOW = 500;

interface Props {
    taskId: string;
}

export default function LivePane(props: Props) {
    let bodyEl!: HTMLDivElement;
    const acc = new Map<number, LiveChunk>();
    const els = new Map<number, HTMLElement>();
    /** 已渲染 seq 升序——迟到的洞插回正确位 */
    const order: number[] = [];
    const [total, setTotal] = createSignal(0);
    /** 已呈现段数（acc.size）与已译段数——summary 计数用 */
    const [shown, setShown] = createSignal(0);
    const [okN, setOkN] = createSignal(0);
    let libs: MdLibs | null = null;
    let alive = true;
    onCleanup(() => {
        alive = false;
    });

    /** 单段 → section 元素内 HTML（徽标 + 译文/原文渲染）；新建按 seq 序插入 */
    const paint = (c: LiveChunk) => {
        if (!libs) return;
        let el = els.get(c.seq);
        if (!el) {
            el = document.createElement("section");
            el.className = "chunk";
            el.dataset.chunk = String(c.seq);
            let i = order.length;
            while (i > 0 && order[i - 1] > c.seq) i--;
            order.splice(i, 0, c.seq);
            const ref =
                i < order.length - 1 ? (els.get(order[i + 1]) ?? null) : null;
            bodyEl.insertBefore(el, ref);
            els.set(c.seq, el);
        }
        const zh = (c.zh ?? "").trim();
        const badge = chunkUntranslated(c)
            ? `<span class="chunk-badge">${escapeHtml(t.live.untranslated)}</span>`
            : "";
        el.innerHTML = badge + libs.mdToHtml(zh ? c.zh! : (c.en ?? ""));
        libs.renderMath(el);
    };

    const tick = async () => {
        if (!alive) return;
        if (!libs) {
            try {
                libs = await loadMdLibs();
            } catch {
                return; // 库加载失败——下拍再试
            }
            if (!alive) return;
        }
        let page: TaskChunksPage;
        try {
            page = await api.taskChunks(props.taskId, 0, WINDOW);
        } catch {
            return; // 网络抖动/端点未就位——下拍再试
        }
        if (!alive) return;
        setTotal(page.total);
        for (const c of mergeLive(acc, page.chunks)) paint(c);
        setShown(acc.size);
        let ok = 0;
        for (const c of acc.values()) if (!chunkUntranslated(c)) ok++;
        setOkN(ok);
    };

    onMount(() => {
        void tick();
        const id = window.setInterval(() => void tick(), POLL_MS);
        onCleanup(() => window.clearInterval(id));
    });

    // details 恒挂（bodyEl 始终存在——Show 门控会让首拍 paint 落空）；
    // 首段到达前 display:none，内容出现即自动可用，用户可手动折叠
    return (
        <details
            class="live-pane"
            open
            style={{ display: shown() > 0 ? "" : "none" }}
        >
            <summary>
                {t.live.title} ·{" "}
                {t.live.progress
                    .replace("{n}", String(okN()))
                    .replace("{total}", String(total()))}
            </summary>
            <div ref={(el) => (bodyEl = el)} class="pane-html-body live-body" />
        </details>
    );
}
