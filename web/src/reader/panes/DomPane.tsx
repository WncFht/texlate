// DomPane —— arxiv_html 链阅读窗格。
// 与 HtmlPane 同 PaneLike 契约：
//   pages() = [data-chunk] 元素 offsetTop/height —— 页面几何即 chunk 序，
//   seq 双侧 1:1（worker emit 在两侧 DOM 注入同一 data-chunk 标记），
//   SyncEngine/drift/position 持久化全部原样复用。
//
// 与 HtmlPane 的差异：渲染源是序列化 DOM 产物而非 dual.json chunks——
//   - 无 marked/KaTeX：MathML 浏览器原生渲染（arXiv 服务端 LaTeXML 产物直出）
//   - fetch 产物 → DOMPurify dom profile → innerHTML
//   - 服务端 emit 已 _sanitize_dom + absolutize，这里是第二道防线：
//     sanitize + 兜底把漏网的相对 URL 补到 arxiv.org origin
//   - 拉取期 veil + 失败态重试钮（不再与真空态同文案）

import {
    createEffect,
    createSignal,
    onCleanup,
    onMount,
    Show,
    untrack,
} from "solid-js";

import type { DocId, Pos } from "../logic/alignment";
import { sanitizeDomHtml } from "../logic/sanitize";
import { externalLinksBlank, otherSide, paneSide } from "../logic/paneUtils";
import {
    bindChunkGeom,
    forEachSliced,
    makeChunkPaneHandle,
    onPaneScroll,
    type ChunkPaneHandle,
} from "../logic/sync";
import CiteCard, { CiteCardBody } from "../cards/CiteCard";
import UsagesCard from "../cards/UsagesCard";
import { extractRefIds, type RefMeta } from "../cite/citations";
import {
    attachUsages,
    type UsagesCtl,
    type UsagesOpen,
} from "../features/findusages";
import {
    bindPaneIndex,
    buildUsageIndex,
    paneIndex,
    usageDestOf,
    type UsageDest,
    type UsageIndex,
    type UsageSite,
} from "../cite/usages";
import { errText, type DualChunk, type KeptRef } from "../../api/client";
import { t } from "../../i18n";

/** DomPane 把手——ChunkPaneHandle + sel-system 挂点：
    bodyEl()    文本宿主（hitctx bodies / sentseg 分段根 / cursor 域）
    jumpAnchor  页内锚跳 record=true 形（onNavBegin+onDestJump 全链——
                命令层 citeJump 走此，与点击内链同语义：压栈+镜像）
    escOpen/escClose  pane 内 Esc 层查询/收（'cite'=悬浮卡） */
export interface DomPaneHandle extends ChunkPaneHandle {
    bodyEl(): HTMLElement;
    jumpAnchor(id: string): { pre: Pos; post: Pos } | null;
    escOpen?(layer: string): boolean;
    escClose?(layer: string): void;
    /** find-usages：命令/外部开卡——目标元素或 id，anchor 给卡锚位 */
    openUsagesFor?(
        target: Element | string | null,
        anchor?: Element | null,
    ): boolean;
    /** 复合 dest 镜像：{u:1,id,ord,chunkOrd} usages 载荷优先，
        字符串退 gotoAnchor（ReaderView.mirrorTo 优先调本口） */
    mirrorDest?(dest: unknown): { pre: Pos; post: Pos } | null;
    /** 本侧 usage 索引（测试/调试面） */
    usageIndex?(): UsageIndex | undefined;
    /** ⌘-Inspect：坐标点 → 原地开检视卡；handled=false 由闸按兜底语义走 */
    inspectAt?(x: number, y: number): boolean;
    /** ⌘-Inspect：坐标点 → 镜像载荷 {dest}=目标元素 id；null=无可镜像物 */
    inspectDestAt?(x: number, y: number): { dest: unknown } | null;
}

interface Props {
    side: DocId;
    /** /api/files/{taskId}/{en|zh}.html（带 ?version=sha256 校验，docUrl 拼） */
    url: string;
    active?: boolean;
    onReady?(h: DomPaneHandle): void;
    onDispose?(h: DomPaneHandle): void;
    onActivate?(): void;
    onScroll?(): void;
    /** 程序导航窗口开始（ReaderView 静音同步引擎+抑漂移） */
    onNavBegin?(): void;
    /** 页内锚跳落定（string=id 走对侧 gotoAnchor；{u:1,id,ord,chunkOrd}
        usages 载荷走 mirrorDest 复合解；pre/post 供跳回栈） */
    onDestJump?(dest: unknown, pre: Pos, post: Pos): void;
    /** dual chunks——data-chunk key→seq 映射源（usages 锚 seq 归位） */
    chunks?: DualChunk[];
    /** 远端元数据活访问器（卡面展示 + kept payload 快照；dom 链无
        citeIndex 也能收——meta 常缺位） */
    citeMeta?(key: string): RefMeta | undefined;
    /** kept_refs 收藏（M4）：卡 key = 锚目标元素 id（bib.bibN） */
    citeKept?(key: string): boolean;
    onToggleKeep?(key: string, payload: KeptRef): void;
}

/** 服务端 absolutize 的漏网兜底——相对路径一律归 arxiv.org origin。 */
const ARXIV_ORIGIN = "https://arxiv.org";

function fixupRelativeUrls(root: HTMLElement): void {
    for (const el of root.querySelectorAll<HTMLElement>(
        "[src^='/'], [href^='/']",
    )) {
        for (const attr of ["src", "href"] as const) {
            const v = el.getAttribute(attr);
            if (v?.startsWith("/"))
                el.setAttribute(attr, `${ARXIV_ORIGIN}${v}`);
        }
    }
}

export default function DomPane(props: Props) {
    let scrollEl!: HTMLDivElement;
    let bodyEl!: HTMLDivElement;
    const [phase, setPhase] = createSignal<"loading" | "ready" | "error">(
        "loading",
    );
    const [errMsg, setErrMsg] = createSignal("");
    const geom = bindChunkGeom(
        () => scrollEl,
        () => bodyEl,
    );

    const handle = makeChunkPaneHandle({
        side: untrack(() => props.side),
        scroller: () => scrollEl,
        body: () => bodyEl,
        geom,
    }) as DomPaneHandle; // sel-system 挂点在下方逐项挂上（bodyEl/jumpAnchor/esc*）

    // ---------- 页内锚代理 + 文献悬浮卡（同锚双语义：hover=卡 / click=跳+压栈） ----------
    interface DomCardState {
        rect: DOMRect;
        id: string;
        target: HTMLElement;
        clone: HTMLElement;
        seq: number;
    }
    const [card, setCard] = createSignal<DomCardState | null>(null);
    let openTimer = 0;
    let closeTimer = 0;
    let cardSeq = 0;
    let curAnchor: Element | null = null;
    let lastTouch = false;
    // 开卡后短暂滚动宽限——tap/键盘 focus 半可见锚时浏览器 focus-scroll
    // 会把锚挪进视口（程序滚非用户滚），不宽限则开卡即被 scroll→close 杀
    let scrollGraceUntil = 0;
    const OPEN_DELAY = 150;
    const CLOSE_DELAY = 350;

    // ---------- find-usages 悬浮卡（第二卡族——与同锚 cite 卡互斥） ----------
    const [ucard, setUcard] = createSignal<UsagesOpen | null>(null);
    let usageIndex: UsageIndex | null = null;
    let usagesCtl: UsagesCtl | null = null;
    /** data-chunk key → dual seq（chunks 端点 chunk_id 投影） */
    const seqOf = (() => {
        let map: Map<string, number> | null = null;
        return (key: string): number | null => {
            if (!map) {
                map = new Map();
                for (const c of props.chunks ?? []) {
                    if (c.chunk_id != null) map.set(c.chunk_id, Number(c.seq));
                }
            }
            return map.get(key) ?? null;
        };
    })();

    const clearCardTimers = () => {
        window.clearTimeout(openTimer);
        window.clearTimeout(closeTimer);
        openTimer = closeTimer = 0;
    };
    const closeCard = () => {
        clearCardTimers();
        curAnchor = null;
        setCard(null);
    };

    /** kept payload（M4）：快照即真相——label 取 .ltx_tag_bibitem（[n]
        编号），text 全文本，arxivId/doi 从文本抽；meta 收此刻远端值 */
    const keepPayload = (c: DomCardState): KeptRef => {
        const text = c.clone.textContent?.trim() || undefined;
        return {
            label:
                c.clone
                    .querySelector(".ltx_tag_bibitem")
                    ?.textContent?.trim() || undefined,
            text,
            ...extractRefIds(text ?? ""),
            meta: props.citeMeta?.(c.id),
        };
    };

    /** a[href^="#"] → 本 pane 内的目标元素；不在本 pane 视同无（跨 pane
        的 #bib.bibN dup-id 永不会命中——querySelector 以 bodyEl 为根） */
    const anchorTarget = (
        a: Element,
    ): { id: string; el: HTMLElement } | null => {
        const href = a.getAttribute("href") ?? "";
        if (!href.startsWith("#")) return null;
        let id = href.slice(1);
        try {
            id = decodeURIComponent(id);
        } catch {
            /* 保留原样 */
        }
        const el = bodyEl.querySelector<HTMLElement>(`#${CSS.escape(id)}`);
        return el ? { id, el } : null;
    };
    const bibOf = (el: HTMLElement): HTMLElement | null =>
        el.matches("li.ltx_bibitem, .ltx_bibitem")
            ? el
            : el.closest<HTMLElement>("li.ltx_bibitem, .ltx_bibitem");
    const anchorOf = (t: EventTarget | null): Element | null =>
        (t as Element | null)?.closest?.("a[href^='#']") ?? null;

    // cite-flash 单轨——连续跳两个目标时旧元素的类/定时器要当场清算，
    // 否则旧定时器到点摘的是新元素头上的类（闪记提前熄灭）
    let flashEl: HTMLElement | null = null;
    let flashTimer = 0;
    const flash = (el: HTMLElement) => {
        if (flashEl && flashEl !== el) flashEl.classList.remove("cite-flash");
        window.clearTimeout(flashTimer);
        flashEl = el;
        el.classList.add("cite-flash");
        flashTimer = window.setTimeout(() => {
            el.classList.remove("cite-flash");
            if (flashEl === el) flashEl = null;
        }, 1400);
    };

    /** 锚跳统一路径：scrollTop 写位 + 目标闪记 + （可选）压栈回传。
        record=false 是镜像通路——ReaderView 拿到 pre/post 自记 dst 栈 */
    const jumpToEl = (
        id: string,
        el: HTMLElement,
        record: boolean,
    ): { pre: Pos; post: Pos } => {
        const pre = handle.capture();
        if (record) props.onNavBegin?.();
        closeCard();
        usagesCtl?.close();
        const sr = scrollEl.getBoundingClientRect();
        scrollEl.scrollTop += el.getBoundingClientRect().top - sr.top - 12;
        flash(el);
        const post = handle.capture();
        if (record) props.onDestJump?.(id, pre, post);
        return { pre, post };
    };
    // eslint-disable-next-line solid/reactivity -- 命令式 handle 槽：props/信号在调用期读是有意的
    handle.gotoAnchor = (id) => {
        const el = bodyEl.querySelector<HTMLElement>(`#${CSS.escape(id)}`);
        if (!el) return null;
        return jumpToEl(id, el, false);
    };
    // sel-system 挂点：命令层 citeJump 走 record=true 全链（压栈+镜像）
    handle.bodyEl = () => bodyEl;
    // eslint-disable-next-line solid/reactivity -- 命令式 handle 槽：props/信号在调用期读是有意的
    handle.jumpAnchor = (id) => {
        const el = bodyEl.querySelector<HTMLElement>(`#${CSS.escape(id)}`);
        if (!el) return null;
        return jumpToEl(id, el, true);
    };
    // eslint-disable-next-line solid/reactivity -- 命令式 handle 槽：card()/ucard() 在调用期读是有意的
    handle.escOpen = (l) => l === "cite" && (card() != null || ucard() != null);
    handle.escClose = (l) => {
        if (l === "cite") {
            closeCard();
            usagesCtl?.close();
        }
    };

    // find-usages 挂点：命令层经 openUsagesFor 开卡；镜像层经 mirrorDest
    // 收 {u:1,id,ord,chunkOrd} 复合 dest（zh 侧 id 落空退 chunkOrd 块跳）
    handle.openUsagesFor = (target, anchor) =>
        usagesCtl?.openFor(target, anchor) ?? false;
    handle.usageIndex = () => usageIndex ?? undefined;
    handle.mirrorDest = (dest) => {
        const d = dest as UsageDest | string;
        if (typeof d === "string") return handle.gotoAnchor?.(d) ?? null;
        if (d && d.u === 1 && typeof d.id === "string") {
            // 同 id 第 ord 个可索引锚——dst 侧索引同口径计数（非 chrome +
            // 可解析 + 非自指），ord 跨 pane 一致
            const el = (() => {
                const e = usageIndex?.forId(d.id!);
                if (!e) return null;
                const flat = e.sites
                    .flatMap((s) => s.anchors)
                    .filter((a) => a.el)
                    .sort((a, b) => a.ord - b.ord);
                return (
                    (flat[d.ord ?? 0]?.el as HTMLElement | undefined) ?? null
                );
            })();
            if (el) {
                const pre = handle.capture();
                const sr = scrollEl.getBoundingClientRect();
                scrollEl.scrollTop +=
                    el.getBoundingClientRect().top - sr.top - 12;
                flash(el);
                return { pre, post: handle.capture() };
            }
            // zh 落空退同 data-chunk 枚举序（zh id 存活 92% 的兜底臂）
            if (typeof d.chunkOrd === "number" && d.chunkOrd >= 0) {
                const c =
                    bodyEl.querySelectorAll<HTMLElement>("[data-chunk]")[
                        d.chunkOrd
                    ];
                if (c) {
                    const pre = handle.capture();
                    const sr = scrollEl.getBoundingClientRect();
                    scrollEl.scrollTop +=
                        c.getBoundingClientRect().top - sr.top - 12;
                    return { pre, post: handle.capture() };
                }
            }
        }
        return null;
    };

    // ⌘-Inspect 挂点：锚→bib 开克隆卡/他开 usages；本体宿主→usages 卡。
    // section 宿主是全节容器——forEl 祖先爬升会把节内任意段落解析成节
    // 卡，只有真击中节标题才算 handled（段落内 ⌘+click 走闸的吞语义）
    const sectionTitleHit = (host: Element, el: Element) => {
        const t = el.closest(".ltx_title, h1, h2, h3, h4, h5, h6");
        return t != null && host.contains(t);
    };
    handle.inspectAt = (x, y) => {
        const el = bodyEl.ownerDocument.elementFromPoint(x, y);
        if (!el || !bodyEl.contains(el)) return false;
        const a = anchorOf(el);
        if (a) {
            const hit = anchorTarget(a);
            if (!hit) return false;
            const bib = bibOf(hit.el);
            if (bib) {
                openDomCard(a, hit.id, bib);
                return true;
            }
            return usagesCtl?.openFor(hit.el, a) ?? false;
        }
        const entry = usageIndex?.forEl(el);
        const host = entry?.target.el ?? null;
        if (!entry || !host) return false;
        if (entry.target.kind === "section" && !sectionTitleHit(host, el))
            return false;
        return usagesCtl?.openFor(el, el) ?? false;
    };
    handle.inspectDestAt = (x, y) => {
        const el = bodyEl.ownerDocument.elementFromPoint(x, y);
        if (!el || !bodyEl.contains(el)) return null;
        const a = anchorOf(el);
        if (a) {
            const hit = anchorTarget(a);
            return hit ? { dest: hit.id } : null;
        }
        const entry = usageIndex?.forEl(el);
        const host = entry?.target.el ?? null;
        if (!entry || !host) return null;
        if (entry.target.kind === "section" && !sectionTitleHit(host, el))
            return null;
        return { dest: entry.target.id };
    };

    /** usages 句项 → 跳回引用锚：scrollTop 写位+闪记+压栈回传；
        dest 载荷 {u,id,ord,chunkOrd}——对侧 mirrorDest 解 */
    const jumpToUsage = (site: UsageSite) => {
        const a = site.anchors[0];
        const el = a?.el as HTMLElement | undefined;
        if (!a || !el?.isConnected) return;
        const pre = handle.capture();
        props.onNavBegin?.();
        closeCard();
        usagesCtl?.close();
        const sr = scrollEl.getBoundingClientRect();
        scrollEl.scrollTop += el.getBoundingClientRect().top - sr.top - 12;
        flash(el);
        const post = handle.capture();
        props.onDestJump?.(usageDestOf(site), pre, post);
    };

    const openDomCard = (a: Element, id: string, bibEl: HTMLElement) => {
        usagesCtl?.close(); // 卡族互斥：cite 卡开时 usages 卡收
        // 克隆 bibitem——零解析格式全保真；剥 id/href 防 dup-id 与卡内误跳
        const clone = bibEl.cloneNode(true) as HTMLElement;
        clone.removeAttribute("id");
        for (const n of clone.querySelectorAll("[id]")) n.removeAttribute("id");
        for (const n of clone.querySelectorAll("a")) n.removeAttribute("href");
        const seq = ++cardSeq;
        curAnchor = a;
        scrollGraceUntil = performance.now() + 600;
        setCard({
            // 多 rect 锚（跨行引用串）取首个——贴指针入口而非整串包裹框
            rect: a.getClientRects()[0] ?? a.getBoundingClientRect(),
            id,
            target: bibEl,
            clone,
            seq,
        });
    };

    let disposed = false;
    let ac: AbortController | null = null;

    const load = async () => {
        ac?.abort();
        const ctl = (ac = new AbortController());
        setPhase("loading");
        setErrMsg("");
        try {
            const res = await fetch(props.url, { signal: ctl.signal });
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const raw = await res.text();
            // 产物是完整 HTML 文档——只取 <body> 内文进 pane，头壳（arxiv
            // 的 nav/meta/link）丢弃。ltx_page 主容器及以下才是论文本体。
            const doc = new DOMParser().parseFromString(raw, "text/html");
            const page = doc.querySelector(".ltx_page_main") ?? doc.body;
            if (disposed) return;
            const tmp = document.createElement("div");
            tmp.innerHTML = sanitizeDomHtml(page.innerHTML);
            // 修复管道在 detached tmp 上整跑一遍——querySelectorAll 不覆盖
            // 根自身，改到落地后逐片跑会漏顶层节点
            fixupRelativeUrls(tmp);
            externalLinksBlank(tmp);
            // 分片落地：1-3MB 产物一次 innerHTML 冻结主线程数百 ms——顶层
            // 节点按时间盒分批 append，首片落地撤 veil，余下后台续渲，
            // 全部落完才 rebind（锚集合此时才完整）
            const nodes = [...tmp.childNodes];
            bodyEl.replaceChildren();
            await forEachSliced(
                nodes,
                (n) => {
                    bodyEl.append(n);
                    setPhase("ready"); // 首片落地即撤 veil
                },
                () => disposed || ctl.signal.aborted,
            );
            if (disposed || ctl.signal.aborted) return;
            geom.rebind();
            // find-usages 索引：锚面全量后建（86ms/170-chunk 冷建可同步）；
            // 模块级 pane 注册表供对侧 zh 配对（挂载序不敏感）
            usageIndex = buildUsageIndex(bodyEl, { seqOf });
            bindPaneIndex(paneSide(props), usageIndex);
            usagesCtl?.armTargets(bodyEl);
            setPhase("ready");
        } catch (e) {
            // 重试先 abort 在途——旧请求的回包不再落盘
            if (
                disposed ||
                (e instanceof DOMException && e.name === "AbortError")
            )
                return;
            setErrMsg(errText(e));
            setPhase("error");
        }
    };

    onMount(async () => {
        // usages 委托先挂——load 未完成时 source()=undefined 天然静默
        usagesCtl = attachUsages(
            { el: scrollEl, bodyEl: () => bodyEl },
            {
                source: () => usageIndex ?? undefined,
                pairIndex: () => paneIndex(otherSide(props)),
                onWillOpen: () => closeCard(), // 卡族互斥反向臂
                open: (p) => setUcard(p),
                close: () => setUcard(null),
            },
        );
        await load();
        if (!disposed) props.onReady?.(handle);
    });
    onCleanup(() => {
        disposed = true;
        ac?.abort();
        usagesCtl?.dispose();
        usagesCtl = null;
        bindPaneIndex(paneSide(props), null);
        usageIndex = null;
        geom.dispose();
        props.onDispose?.(handle);
    });

    createEffect(() => {
        onPaneScroll(scrollEl, () => {
            if (performance.now() >= scrollGraceUntil) closeCard();
            props.onScroll?.();
        });
    });

    // 内链代理：a[href^="#"] 一律 preventDefault——hash 路由兜底会把它
    // 读成路由（App.tsx 活 bug）；跳转走 jumpToEl 手写 scrollTop+压栈。
    // hover/focus 只对 bibitem 锚出卡（克隆 li.ltx_bibitem，格式全保真）；
    // 触屏 tap=卡（卡内「跳到文献表」走同一 jumpToEl）。focusin/out 与
    // Tab 重导挂 scrollEl——卡在 bodyEl 外，焦点三段路要全程可见。
    onMount(() => {
        const scheduleOpen = (fn: () => void) => {
            window.clearTimeout(openTimer);
            openTimer = window.setTimeout(() => {
                openTimer = 0; // 发后即清零——同锚复悬才能再排程
                fn();
            }, OPEN_DELAY);
        };
        const scheduleClose = () => {
            window.clearTimeout(closeTimer); // 重入必须撤旧定时器
            closeTimer = window.setTimeout(closeCard, CLOSE_DELAY);
        };

        const onClick = (e: MouseEvent) => {
            const a = anchorOf(e.target);
            if (!a) {
                if (card()) closeCard(); // 点正文空白即收卡
                return;
            }
            e.preventDefault(); // 无条件拦——hash 绝不出 location
            const hit = anchorTarget(a);
            if (!hit) {
                if (card()) closeCard();
                return;
            }
            const bib = bibOf(hit.el);
            // detail=0 是键盘/AT 合成的 click——保持跳转语义不截卡
            if (lastTouch && e.detail !== 0 && bib) {
                clearCardTimers();
                openDomCard(a, hit.id, bib);
                return;
            }
            jumpToEl(hit.id, hit.el, true);
        };
        const onOver = (e: PointerEvent) => {
            if (e.pointerType === "touch") return;
            const a = anchorOf(e.target);
            if (!a) return;
            const hit = anchorTarget(a);
            if (!hit) return;
            const bibEl = bibOf(hit.el);
            if (!bibEl) return; // 非文献锚不进门——不占 curAnchor
            if (a === curAnchor) {
                // 同锚复悬只续不关；卡未开且定时器已逝要补武装
                window.clearTimeout(closeTimer);
                if (!card() && !openTimer)
                    scheduleOpen(() => openDomCard(a, hit.id, bibEl));
                return;
            }
            clearCardTimers();
            curAnchor = a;
            scheduleOpen(() => openDomCard(a, hit.id, bibEl));
        };
        const onOut = (e: PointerEvent) => {
            const rel = e.relatedTarget as Element | null;
            if (rel?.closest?.(".cite-card")) return;
            if (rel === curAnchor) return;
            if (anchorOf(e.target) || card()) {
                window.clearTimeout(openTimer);
                scheduleClose();
            }
        };
        const onFocusIn = (e: FocusEvent) => {
            const a = anchorOf(e.target);
            if (!a) return;
            // 指针点击引发的 focus 不出卡（:focus-visible 只对键盘成立）
            if (!(a instanceof HTMLElement) || !a.matches(":focus-visible"))
                return;
            const hit = anchorTarget(a);
            const bibEl = hit ? bibOf(hit.el) : null;
            if (!hit || !bibEl) return;
            clearCardTimers();
            openDomCard(a, hit.id, bibEl);
        };
        const onFocusOut = (e: FocusEvent) => {
            const rel = e.relatedTarget as Element | null;
            if (rel?.closest?.(".cite-card")) return;
            if (!anchorOf(e.target) && !card()) return;
            scheduleClose();
        };
        // 卡 DOM 序远离锚——锚上 Tab 直接把焦点送进卡内首个可焦点件
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key !== "Tab" || e.shiftKey) return;
            if (!card() || document.activeElement !== curAnchor) return;
            const el = scrollEl.querySelector<HTMLElement>(
                ".cite-card button, .cite-card a[href]",
            );
            if (!el) return;
            e.preventDefault();
            el.focus();
        };
        const onPointerDown = (e: PointerEvent) => {
            lastTouch = e.pointerType === "touch";
        };
        bodyEl.addEventListener("click", onClick);
        bodyEl.addEventListener("pointerover", onOver);
        bodyEl.addEventListener("pointerout", onOut);
        bodyEl.addEventListener("pointerdown", onPointerDown, true);
        scrollEl.addEventListener("focusin", onFocusIn);
        scrollEl.addEventListener("focusout", onFocusOut);
        scrollEl.addEventListener("keydown", onKeyDown);
        onCleanup(() => {
            bodyEl.removeEventListener("click", onClick);
            bodyEl.removeEventListener("pointerover", onOver);
            bodyEl.removeEventListener("pointerout", onOut);
            bodyEl.removeEventListener("pointerdown", onPointerDown, true);
            scrollEl.removeEventListener("focusin", onFocusIn);
            scrollEl.removeEventListener("focusout", onFocusOut);
            scrollEl.removeEventListener("keydown", onKeyDown);
            clearCardTimers();
            window.clearTimeout(flashTimer);
            flashEl?.classList.remove("cite-flash");
            flashEl = null;
        });
    });

    return (
        <div
            ref={(el) => (scrollEl = el)}
            class="pane pane-html pane-dom"
            tabindex="0"
            classList={{ active: !!props.active }}
            data-side={props.side}
            onPointerDown={() => props.onActivate?.()}
        >
            {/* pane-html-body 复用 HtmlPane 排版样式；ltx_* 类样式由 worker
                emit 时内联固化进产物 <style>，产物自足 */}
            <div ref={(el) => (bodyEl = el)} class="pane-html-body" />
            <Show when={card()}>
                {(c) => (
                    <CiteCard
                        rect={c().rect}
                        onClose={closeCard}
                        onCardEnter={() => window.clearTimeout(closeTimer)}
                        onCardLeave={() => {
                            window.clearTimeout(closeTimer);
                            closeTimer = window.setTimeout(
                                closeCard,
                                CLOSE_DELAY,
                            );
                        }}
                    >
                        <CiteCardBody
                            meta={() => props.citeMeta?.(c().id)}
                            kept={props.citeKept?.(c().id)}
                            onShowUsages={
                                usageIndex?.forEl(c().target)
                                    ? () => usagesCtl?.openFor(c().target)
                                    : undefined
                            }
                            usagesCount={
                                usageIndex?.forEl(c().target)?.sites.length
                            }
                            onToggleKeep={
                                props.onToggleKeep
                                    ? () =>
                                          props.onToggleKeep?.(
                                              c().id,
                                              keepPayload(c()),
                                          )
                                    : undefined
                            }
                            onJump={() => {
                                jumpToEl(c().id, c().target, true);
                            }}
                        >
                            {c().clone}
                        </CiteCardBody>
                    </CiteCard>
                )}
            </Show>
            <Show when={ucard()}>
                {(u) => (
                    <UsagesCard
                        rect={u().rect}
                        entry={u().entry}
                        onClose={() => usagesCtl?.close(true)}
                        onCardEnter={() => usagesCtl?.cardEnter()}
                        onCardLeave={() => usagesCtl?.cardLeave()}
                        onJump={(s) => jumpToUsage(s)}
                        onJumpTarget={() => {
                            const tg = u().entry.target;
                            if (tg.el?.isConnected)
                                jumpToEl(tg.id, tg.el, true);
                        }}
                    />
                )}
            </Show>
            <Show when={phase() === "loading"}>
                <div class="pane-veil">
                    <div
                        class="spinner"
                        role="status"
                        aria-label={t.pane.loading}
                    />
                </div>
            </Show>
            <Show when={phase() === "error"}>
                <div
                    class="pane-veil pane-error"
                    style={{ "flex-direction": "column", gap: "8px" }}
                >
                    <span>
                        {t.pane.loadFailed}：{errMsg()}
                    </span>
                    <button
                        type="button"
                        class="btn-ghost"
                        onClick={() => void load()}
                    >
                        {t.reader.retry}
                    </button>
                </div>
            </Show>
        </div>
    );
}
