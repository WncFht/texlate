// host/navPosition —— 跳回栈 + 双栏镜像 + 位置持久化 + >500px 漂移跳回 +
// 滚动合帧页码回写 + 深链/回程票 + pagehide/回前台两路 DOM 挂载。
// nav↔position 互引（navBack 调 persistPosition、onUserScroll 查 navHolds）
// 合并一簇拆出——分两文件会产生循环 import。
//
// 实测定型语义（load-bearing，改序即回退 bug）：
//   - navMuteUntil 是 {at} 时间戳对象——引擎重建后新实例读同一截止点；
//   - pendingMirror 每侧一槽 last-wins，重试只认自己的 item；
//   - saveNow 空表早退——空 positions 会覆盖服务端已存位置；
//   - navPairSeq 是 {n} 号箱——sentalign recordJump 与 inspect mirror
//     经 deps 注入后在外簇 ++，与本簇 onDestJump 共用同一发号器。

import { createSignal, onCleanup, onMount } from "solid-js";
import {
    api,
    type DualJson,
    type ReaderInfo,
    type ReadingState,
} from "../../api/client";
import type { Mode } from "../chrome/Toolbar";
import { other, type DocId, type Pos, type PosMap } from "../logic/alignment";
import { capturePos, jumpTo, scrollTopFor } from "../logic/sync";
import { NavStack } from "../logic/navstack";
import type { AnyHandle } from "../panes/PaneSlot";
import { fromParamOf } from "../logic/tasknav";
import type { ReaderViewState } from "../logic/view";
import { taskStore } from "../../stores/tasks";

const JUMPBACK_PX = 500;
const SAVE_DEBOUNCE_MS = 1000;

export function createNavPosition(deps: {
    handles(): Partial<Record<DocId, AnyHandle>>;
    paneVisible(side: DocId): boolean;
    mapper(): PosMap;
    info(): ReaderInfo | null;
    dual(): DualJson | null | undefined;
    view(): ReaderViewState;
    taskId(): string;
    mode(): Mode;
    active(): DocId;
    syncing(): boolean;
    zoom(): string;
    swapped(): boolean;
}) {
    const {
        handles,
        paneVisible,
        mapper,
        info,
        dual,
        view,
        taskId,
        mode,
        active,
        syncing,
        zoom,
        swapped,
    } = deps;

    const [pageNums, setPageNums] = createSignal<Record<DocId, number>>({
        original: 1,
        translated: 1,
    });
    const [drift, setDrift] = createSignal<Partial<Record<DocId, boolean>>>({});

    /** 程序导航静音计数——引用跳转/镜像/栈回放窗口内抑 drift 重算；
        navMuteUntil 是同窗口给 SyncEngine 的时间戳（对象持有——
        引擎重建后新实例读同一截止点） */
    let navHolds = 0;
    const navMuteUntil = { at: 0 };
    /** dst 侧 handle 缺席时的待镜像 {dest,pair}——paneReady/重试补投
        （每侧一槽，新镜像覆盖旧的，last-wins） */
    const pendingMirror = new Map<DocId, { dest: unknown; pair: number }>();
    /** 镜像跳配对号——cite 跳每发一次 +1，双侧栈同号入栈；↩/↪ 命中
        pair 项时对侧栈顶同号即联动（见 navBack/navFwd）。
        {n} 号箱形：sentalign recordJump / inspect mirror 经 deps
        在外簇 ++——须持同一引用跨簇发号 */
    const navPairSeq = { n: 0 };
    /** 每侧一栈：named-dest 跳转压栈（滚动永不入栈）；sioyek 回写语义 */
    const navStacks: Record<DocId, NavStack> = {
        original: new NavStack(),
        translated: new NavStack(),
    };
    let saveTimer = 0;
    let driftRaf = 0;

    /** 程序导航窗口开始：drift 计数与引擎时间戳各起一拍，
        600ms 自释放——回声窗口覆盖「跳转+镜像+rAF 合帧」全程 */
    const onNavBegin = () => {
        navHolds++;
        navMuteUntil.at = performance.now() + 600;
        window.setTimeout(() => {
            navHolds--;
        }, 600);
    };

    /** 跳前≈跳后判同——dest 已在视口内的点击不产生栈项（幻影 entry 会
        截断前进栈）。fraction/viewport 双阈值容 capture 像素抖动 */
    const samePos = (a: Pos, b: Pos): boolean =>
        a.page === b.page &&
        Math.abs(a.fraction - b.fraction) < 0.002 &&
        Math.abs((a.viewport ?? 0) - (b.viewport ?? 0)) < 0.01;

    /** 镜像到 dst 侧：handle 缺席挂 pendingMirror（paneReady 补投）；
        失败且仍 split 时留 1200ms 重试——dst 重挂窗口期丢镜像比
        晚到镜像更伤。成功且有位移才记 dst 栈（同 pair 入栈供联动回跳） */
    const mirrorTo = (
        dstSide: DocId,
        dest: unknown,
        tries: number,
        pair: number,
    ): void => {
        const dh = handles()[dstSide];
        if (!dh) {
            pendingMirror.set(dstSide, { dest, pair });
            return;
        }
        onNavBegin(); // dst 滚动回声窗
        void (async () => {
            let r: { pre: Pos; post: Pos } | null | undefined;
            try {
                if ("mirrorDest" in dh && dh.mirrorDest) {
                    r = await dh.mirrorDest(dest);
                } else if (
                    "gotoAnchor" in dh &&
                    dh.gotoAnchor &&
                    typeof dest === "string"
                ) {
                    r = dh.gotoAnchor(dest);
                }
            } catch {
                r = null;
            }
            if (r) {
                pendingMirror.delete(dstSide);
                if (!samePos(r.pre, r.post))
                    navStacks[dstSide].recordJump(r.pre, r.post, pair);
                // 镜像落定闪——dst 侧刚跳到的 seq 锚/行带出闪（裸 mirrorDest
                // 不经 goToDestination 包装，落定闪要在这里补）
                if ("flashDest" in dh) dh.flashDest?.(dest);
                // 镜像落定后的余波回声（图像/字体晚载的二次滚）再补一拍
                navMuteUntil.at = performance.now() + 250;
                return;
            }
            if (mode() === "split" && tries > 0) {
                const item = { dest, pair };
                pendingMirror.set(dstSide, item);
                window.setTimeout(() => {
                    // 槽位已被新镜像/paneReady 覆盖即放弃——只重试自己的项
                    if (pendingMirror.get(dstSide) !== item) return;
                    pendingMirror.delete(dstSide);
                    mirrorTo(dstSide, dest, tries - 1, pair);
                }, 1200);
            }
        })();
    };

    /** named-dest 跳落定：本侧压栈（pre≈post 幻影跳不记）；split 下同侧
        镜像对侧（dst 栈也记，两侧各自的 ↩ 都能回到自己跳前的位置）。
        镜像条件只管 split——syncing 无关（cite 跳是刻意导航不是滚动传播）；
        同步引擎的回声已由 navMuteUntil 窗口吞掉，syncing off 时引擎本就短路 */
    const onDestJump = (side: DocId, dest: unknown, pre: Pos, post: Pos) => {
        const pair = ++navPairSeq.n;
        if (!samePos(pre, post)) navStacks[side].recordJump(pre, post, pair);
        if (mode() !== "split") return;
        mirrorTo(other(side), dest, 2, pair);
    };

    const navBack = (side: DocId) => {
        const h = handles()[side];
        if (!h) return;
        onNavBegin();
        const r = navStacks[side].back(capturePos(h));
        if (!r && fromTask) {
            returnToSrc();
            return;
        }
        if (r) h.jump(r.pos);
        // 成对回跳：对侧栈顶是同一镜像跳 → 一起回（各自回自己跳前位）
        if (r?.pair !== undefined && mode() === "split") {
            const bs = other(side);
            const bh = handles()[bs];
            if (bh && navStacks[bs].topPair() === r.pair) {
                const rb = navStacks[bs].back(capturePos(bh));
                if (rb) bh.jump(rb.pos);
            }
        }
        persistPosition();
    };
    const navFwd = (side: DocId) => {
        const h = handles()[side];
        if (!h) return;
        onNavBegin();
        const r = navStacks[side].fwd(capturePos(h));
        if (r) h.jump(r.pos);
        // 成对前跳：对侧前进票是同一镜像跳 → 一起前
        if (r?.pair !== undefined && mode() === "split") {
            const bs = other(side);
            const bh = handles()[bs];
            if (bh && navStacks[bs].nextPair() === r.pair) {
                const rb = navStacks[bs].fwd(capturePos(bh));
                if (rb) bh.jump(rb.pos);
            }
        }
        persistPosition();
    };

    /** 深链 seq（chunk.copyLink 产物回本阅读器 #/reader/{id}?seq=N）——
        hash 一次性快照；pdf 视图 chunk 序≠页序不落（deepSeqTarget 判空） */
    const deepSeq = (() => {
        const m = /[?&]seq=(\d+)/.exec(window.location.hash);
        return m ? Number(m[1]) : null;
    })();
    /** seq → chunk 序 Pos（[data-chunk] 文档序页 + 顶分位 0）；
        晚到 dual（info 先渲）/seq 不在档 → null 落回 saved 恢复 */
    const deepSeqTarget = (): Pos | null => {
        if (deepSeq == null || view() === "pdf") return null;
        const chunks = dual()?.chunks ?? [];
        const i = chunks.findIndex((c) => c.seq === deepSeq);
        return i >= 0 ? { page: i + 1, fraction: 0 } : null;
    };

    /** 跨任务回程票：#/reader/{id}?from={src}——chip 跳带来的源任务 id */
    const fromTask = (() => {
        const f = fromParamOf(window.location.hash);
        // keyed Match 按 taskId 整树重挂，挂载拍快照是有意的
        return f && f !== taskId() ? f : null;
    })();
    const returnToSrc = () => {
        if (fromTask) location.hash = `#/reader/${fromTask}`;
    };

    // ---------- 位置持久化 + >500px 跳回 ----------

    const saveNow = (opts?: { keepalive?: boolean }) => {
        const positions: Partial<Record<DocId, Pos>> = {};
        for (const side of ["original", "translated"] as const) {
            const h = handles()[side];
            if (!h || !paneVisible(side)) continue;
            try {
                positions[side] = capturePos(h);
            } catch {
                /* 拆解期 slick 已空——跳过该侧 */
            }
        }
        // 无可写位置（窗格未挂/已卸）不发——空表会覆盖服务端已存位置
        if (Object.keys(positions).length === 0) return;
        const state: ReadingState = {
            positions,
            active: active(),
            mode: mode(),
            zoom: zoom(),
            sync: syncing(),
            swapped: swapped(),
            document_version: info()?.documents.translated?.version,
        };
        void api.putPosition(taskId(), state, opts).catch(() => undefined);
    };

    const persistPosition = () => {
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(saveNow, SAVE_DEBOUNCE_MS);
    };

    /** 防抖存盘计时器清零——planModeChange 进 guide 前白清（pending
        防抖存盘会在 positions 空表期白跑） */
    const clearSaveTimer = () => {
        window.clearTimeout(saveTimer);
        saveTimer = 0;
    };

    /** 卸载冲刷：防抖窗口内离开（重试回进度视图/返回列表/切任务）
        不丢最后一段阅读位置——根部 onCleanup 调 */
    const flushSave = () => {
        if (saveTimer) {
            window.clearTimeout(saveTimer);
            saveTimer = 0;
            saveNow();
        }
    };

    /** 同步关闭时：任一侧与"对侧映射来的期望位置"漂移 >500px → 显示跳回按钮 */
    const updateDrift = () => {
        if (mode() !== "split" || syncing()) {
            setDrift({});
            return;
        }
        const next: Partial<Record<DocId, boolean>> = {};
        for (const side of ["original", "translated"] as const) {
            const me = handles()[side];
            const otherSide = other(side);
            const src = handles()[otherSide];
            if (!me || !src) continue;
            const expected = scrollTopFor(
                me,
                mapper()(capturePos(src), otherSide),
            );
            next[side] =
                expected !== null &&
                Math.abs(me.el.scrollTop - expected) > JUMPBACK_PX;
        }
        setDrift(next);
    };

    const jumpBack = (side: DocId) => {
        const me = handles()[side];
        const otherSide = other(side);
        const src = handles()[otherSide];
        if (!me || !src) return;
        jumpTo(me, mapper()(capturePos(src), otherSide));
        setDrift((d) => ({ ...d, [side]: false }));
        persistPosition();
    };

    // 滚动侧记集合，rAF 里一次采样——同帧双侧都滚（同步回声带 user scroll
    // 语义时）两侧页码都回写，不是只留最后进事件的一侧
    const scrolledSides = new Set<DocId>();

    const onUserScroll = (side: DocId) => {
        persistPosition();
        scrolledSides.add(side);
        // 双侧滚动+程序化回声每事件都进来——合帧到一次几何采样
        if (driftRaf) return;
        driftRaf = window.requestAnimationFrame(() => {
            driftRaf = 0;
            const sides = [...scrolledSides];
            scrolledSides.clear();
            // 滚动侧页码回写（dom/html 无 pdfjs pagechanging 事件，走 capturePos；
            // 几何缓存已在，成本近零；pdf 侧与 onPageChange 同源一致）
            for (const s of sides) {
                const h = handles()[s];
                if (!h) continue;
                try {
                    const p = capturePos(h).page;
                    if (p !== pageNums()[s])
                        setPageNums((prev) => ({ ...prev, [s]: p }));
                } catch {
                    /* 拆解期 slick 已空 */
                }
            }
            // 程序导航窗口内不重算 drift——cite 跳双侧同动，跳后 drift
            // 必是程序位移的假象（导航栈语义优先于漂移钮，§8-Q5 裁决）
            if (navHolds === 0) updateDrift();
        });
    };

    // pagehide 冲刷：关 tab/退导航时防抖窗口内的最后位置，
    // keepalive 让请求活到发出为止（普通 fetch 随页面销毁被掐）
    onMount(() => {
        const onHide = () => saveNow({ keepalive: true });
        window.addEventListener("pagehide", onHide);
        onCleanup(() => window.removeEventListener("pagehide", onHide));
    });

    // 后台回前台补一拍任务面：reader 停留期间槽外任务只靠共享列表
    // 轮询（无轮询集时整面停摆），回前台即刻校准徽标/任务行——
    // ttl=0 恒刷（lastFreshAt 门在 ensureFresh 内，节拍天然去重）
    onMount(() => {
        const onVis = () => {
            if (!document.hidden) void taskStore.ensureFresh(0);
        };
        document.addEventListener("visibilitychange", onVis);
        onCleanup(() =>
            document.removeEventListener("visibilitychange", onVis),
        );
    });

    onCleanup(() => {
        if (driftRaf) window.cancelAnimationFrame(driftRaf);
    });

    return {
        pageNums,
        setPageNums,
        drift,
        navStacks,
        navMuteUntil,
        navPairSeq,
        pendingMirror,
        onNavBegin,
        samePos,
        mirrorTo,
        onDestJump,
        navBack,
        navFwd,
        deepSeqTarget,
        fromTask,
        returnToSrc,
        saveNow,
        persistPosition,
        clearSaveTimer,
        flushSave,
        updateDrift,
        jumpBack,
        onUserScroll,
    };
}
