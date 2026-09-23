// LivePane —— 翻译进行中的「边译边读」面板：chunkPoll 共享轮询累积段落到
// 本地 map，已译段走 HtmlPane 同一条 marked → DOMPurify → KaTeX 管线全渲染；
// 未译段（status!=ok 或 zh 空）显原文 + 「未翻译」徽标。每段头带 #seq/kind
// 元信息（原 ChunkPreview 的段定位价值并入此处）。
//
// 增量 DOM 补丁：seq → <section> 映射 + 有序插入，每拍只重绘变化段，
// 滚动位置与已渲染公式不动。折叠容器恒挂载（display 自门控），
// 首段到达即自动可用。acc/els/order 累积全部已下发 seq——delta 轮询
// 每拍限 CHUNK_WINDOW（= 服务端 CHUNKS_PAGE_MAX 500）拉取但跨拍全量
// 送达，渲染 DOM 并无 500 窗上限；注意整页兜底路径
// （api.taskChunks 首页拉取）只覆盖 seq<500，>500 段任务在降级态截尾。
//
// 折叠免绘制：details 合上期间 onPage 只把脏 seq 记进 pendingSeqs，
// marked+KaTeX 不做；重新展开时按 acc 最新快照 backfill 补渲。
//
// frozen（compiling 段，chunks 已冻结）：补最后一拍抓齐末批写入后退订——
// 不挂着空轮询。

import { createEffect, createSignal, onCleanup, onMount } from "solid-js";
import type { TaskChunksPage } from "../api/client";
import { pollChunksOnce, subscribeChunks } from "./chunkPoll";
import {
    chunkSideText,
    chunkUntranslated,
    loadMdLibs,
    unmaskLatex,
    type MdLibs,
} from "./markdown";
import { externalLinksBlank } from "./paneUtils";
import { escapeHtml } from "./sanitize";
import { raf } from "./sync";
import { t } from "../i18n";

export interface LiveChunk {
    seq: number;
    kind?: string;
    status?: string;
    en?: string;
    zh?: string;
    /** 掩码反查表（dual.json 起携带；DB 轮询行暂缺→token 降级 chip） */
    ph?: Record<string, string>;
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
        // ph 缺席的行继承旧表——合并结果进 dirty，重绘才能拿到保留的掩码表
        const merged: LiveChunk = {
            seq: r.seq,
            kind: r.kind,
            status: r.status,
            en: r.en,
            zh: r.zh,
            ph: r.ph ?? cur?.ph,
        };
        if (
            cur &&
            cur.status === merged.status &&
            cur.zh === merged.zh &&
            cur.en === merged.en &&
            cur.kind === merged.kind &&
            cur.ph === merged.ph
        )
            continue;
        acc.set(r.seq, merged);
        dirty.push(merged);
    }
    return dirty;
}

interface Props {
    taskId: string;
    /** true=源数据已冻结（compiling 段）——补末拍后退订停轮询 */
    frozen?: boolean;
    /** sel-system 挂点：body 元素出口（live 在 .panes 容器外，宿主经此
        拿文本宿主——hitctx bodies / 未来 sentseg/cursor 挂点）；
        挂载回调元素、卸载回调 null */
    bodyRef?(el: HTMLDivElement | null): void;
}

/** 重绘时间盒——一拍几十段全 marked+KaTeX 会卡帧，切片跨帧让出主线程 */
const PAINT_SLICE_MS = 40;

export default function LivePane(props: Props) {
    let detEl!: HTMLDetailsElement;
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
    onCleanup(() => props.bodyRef?.(null));
    /** 面板开合态（初值对应 JSX 的 open 属性），toggle 事件同步 */
    let isOpen = true;
    /** 折叠期间积下的脏 seq——重开时按 acc 快照补渲（paint 内逐 seq 摘除） */
    const pendingSeqs = new Set<number>();
    onCleanup(() => {
        alive = false;
        unsubscribe?.();
    });

    /** 单段 → section 元素内 HTML（seq/kind 元信息 + 徽标 + 译文/原文渲染） */
    const paint = (c: LiveChunk) => {
        if (!libs) return;
        pendingSeqs.delete(c.seq);
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
        const meta =
            `<div class="chunk-meta muted">` +
            `<span class="chunk-seq">#${c.seq + 1}</span>` +
            (c.kind ? `<i class="chunk-kind">${escapeHtml(c.kind)}</i>` : "") +
            `</div>`;
        const badge = chunkUntranslated(c)
            ? `<span class="chunk-badge">${escapeHtml(t.live.untranslated)}</span>`
            : "";
        // 与 HtmlPane 同一单侧取文：zh 空白回退 en
        el.innerHTML =
            meta + badge + libs.mdToHtml(chunkSideText(c, "translated"));
        // marked 产物内的 http(s) 外链一律新窗——pane 内默认跳转会顶掉阅读器
        externalLinksBlank(el);
        unmaskLatex(el, c.ph);
        libs.renderMath(el);
    };

    const recount = () => {
        setShown(acc.size);
        let ok = 0;
        for (const c of acc.values()) if (!chunkUntranslated(c)) ok++;
        setOkN(ok);
    };

    /** 待绘队列——onPage 只入队，rAF 分片刷出（首拍几百段不再单帧全渲） */
    const paintQueue: LiveChunk[] = [];
    let paintScheduled = false;
    const flushPaints = () => {
        paintScheduled = false;
        if (!alive) {
            paintQueue.length = 0;
            return;
        }
        // 合上的瞬间：未绘部分转 pending，不白做 marked+KaTeX
        if (!isOpen) {
            for (const c of paintQueue) pendingSeqs.add(c.seq);
            paintQueue.length = 0;
            return;
        }
        const deadline = performance.now() + PAINT_SLICE_MS;
        while (paintQueue.length && performance.now() < deadline) {
            paint(paintQueue.shift()!);
        }
        if (paintQueue.length) {
            paintScheduled = true;
            raf(flushPaints);
        }
    };
    const enqueuePaints = (rows: LiveChunk[]) => {
        if (!rows.length) return;
        paintQueue.push(...rows);
        if (!paintScheduled) {
            paintScheduled = true;
            raf(flushPaints);
        }
    };
    /** 开则入队即绘；合则记 seq 等 backfill */
    const queueOrDefer = (rows: LiveChunk[]) => {
        if (isOpen) enqueuePaints(rows);
        else for (const c of rows) pendingSeqs.add(c.seq);
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
        queueOrDefer(dirty);
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
        const missed: LiveChunk[] = [];
        for (const c of acc.values()) if (!els.has(c.seq)) missed.push(c);
        queueOrDefer(missed);
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
            ref={(el) => (detEl = el)}
            on:toggle={() => {
                isOpen = detEl.open;
                // 展开 backfill：pendingSeqs 按 acc 最新快照补渲，
                // paint() 内逐 seq 摘除；libs 未到则由 ensureLibs 的
                // missed 补绘兜底（acc 未建段的都在其中）
                if (!isOpen || !libs || pendingSeqs.size === 0) return;
                const rows: LiveChunk[] = [];
                for (const s of pendingSeqs) {
                    const c = acc.get(s);
                    if (c) rows.push(c);
                }
                enqueuePaints(rows);
            }}
            style={{ display: shown() > 0 ? "" : "none" }}
        >
            <summary>
                {t.live.title} ·{" "}
                {t.live.progress
                    .replace("{n}", String(okN()))
                    .replace("{total}", String(total()))}
            </summary>
            <div
                ref={(el) => {
                    bodyEl = el;
                    props.bodyRef?.(el);
                }}
                class="pane-html-body live-body"
            />
        </details>
    );
}
