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
    unmaskLatex,
    type MdLibs,
} from "./markdown";
import { externalLinksBlank } from "./paneUtils";
import { CHUNK_WINDOW } from "./chunkPoll";
import {
    bindChunkGeom,
    forEachSliced,
    makeChunkPaneHandle,
    onPaneScroll,
    type ChunkPaneHandle,
} from "./sync";
import {
    attachUsages,
    type UsagesCtl,
    type UsagesOpen,
    type UsagesSource,
} from "./features/findusages";
import {
    buildCiteUsageMap,
    usageEntryFromCiteMap,
    type UsageEntry,
    type UsageSite,
} from "./usages";
import UsagesCard, { usagesText } from "./UsagesCard";
import { api, apiErrText, type DualChunk } from "../api/client";
import { t } from "../i18n";

/** 单段重译后等待新 zh 落地的轮询参数 */
const RETX_POLL_MS = 2000;
const RETX_TIMEOUT_MS = 60_000;
const RETX_TOAST_MS = 4500;

/** HtmlPane 把手——ChunkPaneHandle + sel-system 挂点：
    bodyEl()  文本宿主（hitctx bodies / sentseg 分段根 / cursor 域）
    openUsagesFor/mirrorDest/usageIndex/esc*  find-usages 臂
    （cite token 反向索引适配 UsagesSource，跳回协议同 DomPane 口径） */
export interface HtmlPaneHandle extends ChunkPaneHandle {
    bodyEl(): HTMLElement;
    /** 命令层开卡：目标元素或 bibkey/cite.key/bib.key 串 */
    openUsagesFor?(
        target: Element | string | null,
        anchor?: Element | null,
    ): boolean;
    /** 索引面出口（调试/测试——forEl/forId 同 UsagesSource 形） */
    usageIndex?(): UsagesSource | undefined;
    /** 镜像收端：{u:1,id,ord,chunkOrd} 复合 dest → seq+fraction Pos 跳；
        串 dest 剥 cite./bib. 前缀按 bibkey 落点解（bibAt） */
    mirrorDest?(dest: unknown): { pre: Pos; post: Pos } | null;
    escOpen?(layer: string): boolean;
    escClose?(layer: string): void;
    /** ⌘-Inspect：坐标点 → 原地开检视卡；handled=false 由闸按兜底语义走 */
    inspectAt?(x: number, y: number): boolean;
    /** ⌘-Inspect：坐标点 → 镜像载荷 {u:1,id}=bibkey；null=无可镜像物 */
    inspectDestAt?(x: number, y: number): { dest: unknown } | null;
}

interface Props {
    side: DocId;
    chunks: DualChunk[];
    /** 单段重译通路：两者俱有才挂「重译」钮（终态 done/partial 由调用方判） */
    taskId?: string;
    canRetranslate?: boolean;
    /** 在飞重译 seq 集外置共享（sel-system：hitctx chunk.pending 闸须与
        本 pane 的 pending 同一份——宿主经 PaneSlot 注入；缺省内部自建） */
    retxPending?: Set<number>;
    active?: boolean;
    onReady?(h: HtmlPaneHandle): void;
    onDispose?(h: HtmlPaneHandle): void;
    onActivate?(): void;
    onScroll?(): void;
    /** 程序导航窗口开始 / usages 跳落定（ReaderView 跳回栈+镜像入口，
        与 DomPane 同口径回传） */
    onNavBegin?(): void;
    onDestJump?(dest: unknown, pre: Pos, post: Pos): void;
}

/* —— finishChunk 仍是共享骨架的本地副本（forEachSliced/onPaneScroll 已随
 *   makeChunkPaneHandle hoist 进 sync.ts；本件与 LivePane.paint 的注入后
 *   渲染管线同口径，归宿 markdown.ts）—— */

/** 注入后渲染管线：外链新窗 → 掩码/残件反查 → KaTeX 重扫
 * （mount 分片 / 重译重绘 / LivePane.paint 三处同口径） */
function finishChunk(
    el: HTMLElement,
    libs: MdLibs | null,
    ph?: Record<string, string>,
): void {
    externalLinksBlank(el);
    unmaskLatex(el, ph);
    libs?.renderMath(el);
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
    /** 在飞重译 seq——按钮防抖 + 卸载断 poll；宿主注入则共享
        （hitctx chunk.pending 读同一份 → 菜单 chunk.retx disabled 实时） */
    // eslint-disable-next-line solid/reactivity -- 宿主共享的 Set 引用，挂载拍快照是有意的
    const pending = props.retxPending ?? new Set<number>();
    const [note, setNote] = createSignal("");
    let noteTimer = 0;

    const handle = makeChunkPaneHandle({
        side: untrack(() => props.side),
        scroller: () => scrollEl,
        body: () => bodyEl,
        geom,
    }) as HtmlPaneHandle; // sel-system 挂点（bodyEl）下方挂上
    handle.bodyEl = () => bodyEl;

    // ---------------- find-usages 臂（html 链）----------------
    // dual.json [[CITE_n]]/[[BIB_n]] token → bibkey 反向索引；卡面经
    // UsagesCard 呈现，跳转走 Pos（seq→文档序页 + charOff/enLen 分位）。
    // keyReliable=false（ph 编号漂移档）时条目仍出、label 尾缀 degraded
    // 注记——「有句无键」语义由索引层数据保持，表面只做诚实信号。
    const [ucard, setUcard] = createSignal<UsagesOpen | null>(null);
    let usagesCtl: UsagesCtl | null = null;
    /** props.chunks 是 dual 快照（en/ph 稳态——重译只改 zh，卡内 zhText
        滞后一拍可接受）；索引不随响应式重建 */
    const citeMap = buildCiteUsageMap({ chunks: untrack(() => props.chunks) });
    /** seq → [data-chunk] 文档序（Pos.page-1）——mount 段落后建 */
    const seqIndex = new Map<number, number>();

    /** bibkey 剥装饰前缀——html 臂键域=dual 里的裸 bibkey */
    const bareKey = (id: string): string => id.replace(/^(?:cite|bib)\./, "");
    /** [data-bib-key] 内联查——key 含引号/反斜杠按 hitctx byId 同口径转义 */
    const bibAnchorEl = (key: string): HTMLElement | null =>
        bodyEl.querySelector<HTMLElement>(
            `[data-bib-key="${key.replace(/(["\\])/g, "\\$1")}"]`,
        );

    /** 键 → UsageEntry：byKey/bibAt 双表任一在手才算「可索引目标」；
        target.el 补上 bib-anchor（usageEntryFromCiteMap 产 null 壳——
        委托 hover/tap/contextmenu 触发链要求宿主元素非空） */
    const usageEntryFor = (
        key: string,
        anchor: HTMLElement | null,
    ): UsageEntry | undefined => {
        if (!citeMap.byKey.has(key) && !citeMap.bibAt.has(key))
            return undefined;
        const base = (anchor?.textContent ?? "").trim() || key;
        const label = citeMap.keyReliable
            ? base
            : `${base} · ${usagesText("degraded")}`;
        const e = usageEntryFromCiteMap(citeMap, key, label);
        if (anchor) e.target.el = anchor;
        return e;
    };

    const usageSrc: UsagesSource = {
        forEl(el) {
            const anchor = el?.closest?.("[data-bib-key]") ?? null;
            if (!(anchor instanceof HTMLElement)) return undefined;
            const key = anchor.getAttribute("data-bib-key") ?? "";
            if (!key) return undefined;
            return usageEntryFor(key, anchor);
        },
        forId(id) {
            const key = bareKey(id);
            return usageEntryFor(key, bibAnchorEl(key));
        },
    };

    /** seq+fraction → Pos 跳（seqIndex 缺席/未命中 → null 不跳） */
    const jumpSeq = (
        seq: number | null,
        fraction: number,
    ): { pre: Pos; post: Pos } | null => {
        const idx = seq != null ? seqIndex.get(seq) : undefined;
        if (idx == null) return null;
        const pre = handle.capture();
        handle.jump({ page: idx + 1, fraction });
        return { pre, post: handle.capture() };
    };

    /** usages 句项 → 该引用点在正文的 seq 分位（dest 载荷同 DomPane 口径） */
    const jumpToUsage = (site: UsageSite) => {
        const a = site.anchors[0];
        const seq = site.seq ?? a?.seq ?? null;
        if (seq == null || !seqIndex.has(seq)) return;
        const pre = handle.capture();
        props.onNavBegin?.();
        usagesCtl?.close();
        handle.jump({
            page: (seqIndex.get(seq) ?? 0) + 1,
            fraction: site.fraction ?? 0,
        });
        const post = handle.capture();
        props.onDestJump?.(
            {
                u: 1,
                id: a?.id ?? "",
                ord: a?.ord ?? 0,
                chunkOrd: a?.chunkOrd ?? -1,
            },
            pre,
            post,
        );
    };

    /** 跳到 bib-anchor 目标本体——优先元素滚位（DomPane jumpToEl 同款） */
    const jumpToTarget = () => {
        const u = ucard();
        const el = u?.entry.target.el;
        if (!u || !(el instanceof HTMLElement) || !el.isConnected) return;
        const pre = handle.capture();
        props.onNavBegin?.();
        usagesCtl?.close();
        const sr = scrollEl.getBoundingClientRect();
        scrollEl.scrollTop += el.getBoundingClientRect().top - sr.top - 12;
        const post = handle.capture();
        props.onDestJump?.(u.entry.target.id, pre, post);
    };

    // sel-system 挂点：cite 层 Esc 归并（与 menuCard 同层）、命令开卡、
    // 镜像收端——ReaderView 经 AnyHandle 联合调这几个可选槽
    // eslint-disable-next-line solid/reactivity -- 命令式 handle 槽：ucard() 在调用期读是有意的
    handle.escOpen = (l) => l === "cite" && ucard() != null;
    handle.escClose = (l) => {
        if (l === "cite") usagesCtl?.close();
    };
    handle.openUsagesFor = (target, anchor) =>
        usagesCtl?.openFor(target, anchor) ?? false;
    handle.usageIndex = () => (citeMap.hasTokens ? usageSrc : undefined);
    handle.mirrorDest = (dest) => {
        const d = dest as
            | { u?: number; id?: string; ord?: number; chunkOrd?: number }
            | string;
        if (typeof d === "string") {
            // 串 dest 兜底：bibkey（可带 cite./bib. 前缀）→ 条目落点
            const at = citeMap.bibAt.get(bareKey(d));
            return at
                ? jumpSeq(at.seq, at.enLen > 0 ? at.charOff / at.enLen : 0)
                : null;
        }
        if (d && d.u === 1 && typeof d.id === "string") {
            const key = bareKey(d.id);
            const occs = citeMap.byKey.get(key) ?? [];
            const occ = occs[d.ord ?? 0] ?? occs[0];
            if (occ)
                return jumpSeq(
                    occ.seq,
                    occ.enLen > 0 ? occ.charOff / occ.enLen : 0,
                );
            // 句点落空退条目落点（bibAt 兜底臂——DomPane chunkOrd 兜底同位）
            const at = citeMap.bibAt.get(key);
            if (at)
                return jumpSeq(
                    at.seq,
                    at.enLen > 0 ? at.charOff / at.enLen : 0,
                );
        }
        return null;
    };

    // ⌘-Inspect 挂点：a.cite-ref[data-key] 与 [data-bib-key] 双轨——
    // cite 替身无 href（闸的外链放行不替它判），多键逗号串取首键开
    // usages 卡（html 臂无 cite 单卡形——卡面与 hover 卡同一份）
    handle.inspectAt = (x, y) => {
        const el = bodyEl.ownerDocument.elementFromPoint(x, y);
        if (!el || !bodyEl.contains(el)) return false;
        const cr = el.closest<HTMLElement>(".cite-ref");
        if (cr) {
            const key = (cr.getAttribute("data-key") ?? "")
                .split(",")[0]
                ?.trim();
            return key ? (usagesCtl?.openFor(key, cr) ?? false) : false;
        }
        if (el.closest("[data-bib-key]"))
            return usagesCtl?.openFor(el, el) ?? false;
        return false;
    };
    handle.inspectDestAt = (x, y) => {
        const el = bodyEl.ownerDocument.elementFromPoint(x, y);
        if (!el || !bodyEl.contains(el)) return null;
        const cr = el.closest<HTMLElement>(".cite-ref, [data-bib-key]");
        if (!cr) return null;
        const key = (
            cr.getAttribute("data-key") ??
            cr.getAttribute("data-bib-key") ??
            ""
        )
            .split(",")[0]
            ?.trim();
        // {u:1,id}=bibkey 复合载荷：pdf 收端 pdfCiteDests 解 cite.<key>，
        // dom 收端 forId 落空诚实 null
        return key ? { dest: { u: 1, id: key } } : null;
    };

    /** 卡/触发面 arming：usagesCtl 的 figure/table/bibitem tabindex 补 +
        html 臂自产 .bib-anchor 同待遇（focus 触发要它可聚焦 + insp-t 预标） */
    const armUsageTargets = (root: HTMLElement) => {
        usagesCtl?.armTargets(root);
        for (const el of root.querySelectorAll<HTMLElement>(".bib-anchor")) {
            if (el.tabIndex < 0) el.tabIndex = 0;
            el.classList.add("insp-t");
        }
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
            s += `<span class="chunk-badge">${escapeHtml(t.live.untranslated)}</span>`;
        if (props.canRetranslate && props.taskId && Number.isInteger(c.seq))
            s += `<button type="button" class="chunk-retx" data-retx="${seqAttr(c.seq)}" title="${escapeHtml(t.live.retranslate)}">${escapeHtml(t.live.retranslate)}</button>`;
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
        finishChunk(fresh, libs, c.ph);
        // 重绘段的 .bib-anchor 是新元素——tabindex 重新武装
        armUsageTargets(fresh);
        // childList 变化已排 MO 整绑——同步再绑一遍是纯重复，只清缓存
        geom.invalidate();
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
            toast(`${t.live.retxFail}：${apiErrText(e)}`);
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
                let row = (await api.taskChunks(taskId, seq, 1)).chunks.find(
                    (r) => r.seq === seq,
                );
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
        // usages 委托先挂——citeMap 在 hasTokens=0 时 source()=undefined
        // 天然静默；zhText 已由 dual 携带，跨 pane 配对索引不缺
        usagesCtl = attachUsages(
            { el: scrollEl, bodyEl: () => bodyEl },
            {
                source: () => (citeMap.hasTokens ? usageSrc : undefined),
                pairIndex: () => undefined, // 站点自带 zhText——无需对侧索引
                open: (p) => setUcard(p),
                close: () => setUcard(null),
            },
        );
        libs = await loadMdLibs().catch(() => null);
        if (disposed) return;
        if (!props.chunks.length) {
            // 库加载失败仍出转义原文——比永远停在 veil spinner 强
            bodyEl.innerHTML = `<p class="chunk-empty">${t.reader.chunkEmpty}</p>`;
        } else {
            // 几百段一次 innerHTML + 全文 KaTeX 会连卡主线程数秒——按时间盒
            // 分片挂载、片间 rAF 让帧；onReady 仍待全部落 DOM，保证同步几何完整
            const tmp = document.createElement("div");
            await forEachSliced(
                props.chunks,
                (c) => {
                    tmp.innerHTML = sectionHtml(c);
                    const sec = tmp.firstElementChild as HTMLElement | null;
                    if (sec) {
                        finishChunk(sec, libs, c.ph);
                        bodyEl.append(sec);
                    }
                },
                () => disposed,
            );
            if (disposed) return;
        }
        bodyEl.addEventListener("click", onBodyClick);
        // seq→文档序索引（Pos.page-1）——bib 落点/引用句的 Pos 跳都查它
        seqIndex.clear();
        bodyEl
            .querySelectorAll<HTMLElement>("[data-chunk]")
            .forEach((el, i) => {
                const n = Number(el.getAttribute("data-chunk"));
                if (Number.isInteger(n)) seqIndex.set(n, i);
            });
        armUsageTargets(bodyEl);
        geom.rebind();
        setReady(true);
        props.onReady?.(handle);
    });
    onCleanup(() => {
        disposed = true;
        window.clearTimeout(noteTimer);
        bodyEl.removeEventListener("click", onBodyClick);
        usagesCtl?.dispose();
        usagesCtl = null;
        geom.dispose();
        props.onDispose?.(handle);
    });

    createEffect(() => {
        onPaneScroll(scrollEl, () => props.onScroll?.());
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
            {/* find-usages 悬浮卡（html 臂——cite token 索引驱动） */}
            <Show when={ucard()} keyed>
                {(u) => (
                    <UsagesCard
                        rect={u.rect}
                        entry={u.entry}
                        onClose={() => usagesCtl?.close(true)}
                        onCardEnter={() => usagesCtl?.cardEnter()}
                        onCardLeave={() => usagesCtl?.cardLeave()}
                        onJump={(s) => jumpToUsage(s)}
                        onJumpTarget={jumpToTarget}
                    />
                )}
            </Show>
        </div>
    );
}
