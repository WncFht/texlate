// LivePane —— 翻译进行中的「边译边读」面板：chunkPoll 共享轮询（与
// ChunkPreview 同拍同请求）累积段落到本地 map，已译段走 HtmlPane 同一条
// marked → DOMPurify → KaTeX 管线全渲染；未译段（status!=ok 或 zh 空）
// 显原文 + 「未翻译」徽标。
//
// 增量 DOM 补丁：seq → <section> 映射 + 有序插入，每拍只重绘变化段，
// 滚动位置与已渲染公式不动。折叠容器恒挂载（display 自门控），
// 首段到达即自动可用；再大任务也限 CHUNKS_PAGE_MAX 窗内。
//
// frozen（compiling 段，chunks 已冻结）：补最后一拍抓齐末批写入后退订——
// 不挂着空轮询。

import {
    createEffect,
    createSignal,
    onCleanup,
    onMount,
} from "solid-js";
import type { TaskChunksPage } from "../api/client";
import { pollChunksOnce, subscribeChunks } from "./chunkPoll";
import { chunkUntranslated, loadMdLibs, type MdLibs } from "./markdown";
import { externalLinksBlank } from "./paneUtils";
import { escapeHtml } from "./sanitize";
import { t } from "../i18n";

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

interface Props {
    taskId: string;
    /** true=源数据已冻结（compiling 段）——补末拍后退订停轮询 */
    frozen?: boolean;
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
    let unsubscribe: (() => void) | undefined;
    let froze = false;
    onCleanup(() => {
        alive = false;
        unsubscribe?.();
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
        // marked 产物内的 http(s) 外链一律新窗——pane 内默认跳转会顶掉阅读器
        externalLinksBlank(el);
        libs.renderMath(el);
    };

    const recount = () => {
        setShown(acc.size);
        let ok = 0;
        for (const c of acc.values()) if (!chunkUntranslated(c)) ok++;
        setOkN(ok);
    };

    const onPage = (page: TaskChunksPage) => {
        if (!alive) return;
        setTotal(page.total);
        const dirty = mergeLive(acc, page.chunks);
        if (!libs) {
            // 库未就位时 acc 照积——每拍顺带重试加载（与旧 tick 路同节奏），
            // libs 落地后 backfill 补绘，页面不丢
            void ensureLibs();
            recount();
            return;
        }
        for (const c of dirty) paint(c);
        recount();
    };

    let libsLoading = false;
    const ensureLibs = async () => {
        if (libs || libsLoading) return;
        libsLoading = true;
        try {
            libs = await loadMdLibs();
        } catch {
            libsLoading = false;
            return;
        }
        libsLoading = false;
        if (!alive) return;
        // libs 晚于首拍到达：只补绘尚未建段的（els 内的皆已带公式渲染，
        // 重绘会让 auto-render 对已渲染 span 二次加工）
        for (const c of acc.values()) if (!els.has(c.seq)) paint(c);
        recount();
    };

    // compiling 冻结：translating→compiling 切换沿可能漏末批 chunk 写入——
    // 补一拍（在飞 tick 会归并等待，分发完成后）退订，共享轮询随归零自停
    const freeze = () => {
        if (froze || !unsubscribe) return;
        froze = true;
        void (async () => {
            await pollChunksOnce(props.taskId);
            unsubscribe?.();
            unsubscribe = undefined;
        })();
    };

    onMount(() => {
        void ensureLibs();
        unsubscribe = subscribeChunks(props.taskId, onPage);
        if (props.frozen) freeze(); // frozen 先于订阅到达的边角
    });

    createEffect(() => {
        if (props.frozen) freeze();
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
