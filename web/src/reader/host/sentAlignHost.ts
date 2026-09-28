// host/sentAlignHost —— sent-align lane 桥接：saPanes 描述子构造 +
// attachSentAlign deps 全家注入 + saReg 命令面 + settings.sentAlign
// 翻转重扫 effect。deps 全部来自其他子系统（nav/mapper/derives/handles）——
// 依赖排序在 navPosition/derives 之后。根部 paneReady/paneDisposed/
// settings 翻转三处都调 sa.syncPanes()——bodyEl 同体免重挂，enabled 假
// 则全剥注入标引。

import { createEffect, onCleanup } from "solid-js";
import type { DocId, Pos, PosMap } from "../logic/alignment";
import { containingSeq, seqLands, seqPos } from "../pdf/pdfseqpos";
import type { SeqPosMap } from "../pdf/pdfseqpos";
import { capturePos } from "../logic/sync";
import type { AnyHandle } from "../panes/PaneSlot";
import type { ReaderViewState } from "../logic/view";
import type { Registry } from "../cmd/cmdreg";
import type { CmdCtx } from "../cmd/commands";
import type { NavStack } from "../logic/navstack";
import {
    attachSentAlign,
    registerSentAlign,
    type SentAlignPane,
} from "../features/sentalign";
import { settingsStore } from "../../stores/settings";
import {
    press as saPress,
    land as saLand,
    cancelLand as saCancelLand,
} from "../align/anim";

export function createSentAlignHost(deps: {
    reg: Registry<CmdCtx>;
    handles(): Partial<Record<DocId, AnyHandle>>;
    liveBodyEl(): HTMLElement | null;
    view(): ReaderViewState;
    seqposMap(): SeqPosMap;
    seqOf(): Map<string, number>;
    seqLenOf(): Map<number, { en: number; zh: number }>;
    mapper(): PosMap;
    navStacks: Record<DocId, NavStack>;
    navPairSeq: { n: number };
    onNavBegin(): void;
    samePos(a: Pos, b: Pos): boolean;
}) {
    const {
        reg,
        handles,
        liveBodyEl,
        view,
        seqposMap,
        seqOf,
        seqLenOf,
        mapper,
        navStacks,
        navPairSeq,
        onNavBegin,
        samePos,
    } = deps;

    // sent-align lane：会话 attach + sent.gotoPeer 命令注册。
    // paneReady/paneDisposed/settings.sentAlign 翻转三处都调
    // sa.syncPanes()——bodyEl 同体免重挂，enabled 假则全剥注入标引
    const saPanes = (): SentAlignPane[] => {
        const out: SentAlignPane[] = [];
        // live-pane 列头——attach 内 want 同侧后写胜，真 zh pane 在场时
        // live 只作候补（live 独占 zh 侧时才实际挂载）
        const live = liveBodyEl();
        if (live) out.push({ kind: "live", side: "zh", bodyEl: live });
        for (const side of ["original", "translated"] as const) {
            const h = handles()[side];
            if (!h) continue;
            const saSide = side === "translated" ? "zh" : "en";
            if ("bodyEl" in h && typeof h.bodyEl === "function") {
                out.push({
                    kind: view(),
                    side: saSide,
                    bodyEl: h.bodyEl(),
                    scroller: h.el,
                    capture: () => capturePos(h),
                });
            } else {
                // pdf 窗格无 DOM 体——DOM→PDF 跳转目标 + PDF 点击源
                // （seqAtPoint：TLXC 锚命中优先，未命中 containingSeq
                // 兜底——含点块 floor 语义）
                out.push({
                    kind: "pdf",
                    side: saSide,
                    clickEl: (() => {
                        try {
                            return h.el;
                        } catch {
                            return undefined;
                        }
                    })(),
                    posAtPoint: (x, y) =>
                        "posAtPoint" in h
                            ? (h.posAtPoint?.(x, y) ?? null)
                            : null,
                    seqAtPoint: (x, y) => {
                        if ("seqAtPoint" in h) {
                            const s = h.seqAtPoint?.(x, y);
                            if (s != null) return s;
                        }
                        const p =
                            "posAtPoint" in h ? h.posAtPoint?.(x, y) : null;
                        // 距离闸内置于 containingSeq（floor>1.2 页/
                        // 早于首锚>1 页 → null）——稀疏 seqpos 下落回
                        // jumpPosToPdf 比例旧路
                        return p ? containingSeq(seqposMap(), saSide, p) : null;
                    },
                });
            }
        }
        return out;
    };
    const sa = attachSentAlign({
        panes: saPanes,
        enabled: () => settingsStore.sentAlign(),
        deps: {
            navBegin: () => onNavBegin(),
            recordJump: (dst, pre, post) => {
                if (!pre || !post || samePos(pre, post)) return;
                navStacks[dst === "zh" ? "translated" : "original"].recordJump(
                    pre,
                    post,
                    ++navPairSeq.n,
                );
            },
            mapPos: (pos, from) =>
                mapper()(pos, from === "zh" ? "translated" : "original"),
            pdfDest: (dst, pos) => {
                const h = handles()[dst === "zh" ? "translated" : "original"];
                return h && "posDest" in h
                    ? (h.posDest?.(pos) ?? Promise.resolve(null))
                    : Promise.resolve(null);
            },
            pdfJump: (dst, dest) => {
                const h = handles()[dst === "zh" ? "translated" : "original"];
                return Promise.resolve(
                    h && "mirrorDest" in h
                        ? (h.mirrorDest?.(dest) ?? null)
                        : null,
                );
            },
            pdfFlash: (dst, pos) => {
                const h = handles()[dst === "zh" ? "translated" : "original"];
                return h && "flashAtPos" in h ? h.flashAtPos?.(pos) : undefined;
            },
            // seq 臂：seqpos 直锚（Option B 服务端注入的消费口）
            seqPos: (seq, side) => seqPos(seqposMap(), seq, side),
            // 块内插值地标表——点击块内偏移 u 推进 S→S' 区间
            seqLands: (side) => seqLands(seqposMap(), side),
            seqOfChunk: (key) => seqOf().get(key) ?? null,
            chunkLen: (seq, side) => seqLenOf().get(seq)?.[side] ?? 0,
            pdfFlashSeq: (dst, seq, pos) => {
                const h = handles()[dst === "zh" ? "translated" : "original"];
                if (h && "flashSeq" in h) return h.flashSeq?.(seq, pos);
                if (h && "flashAtPos" in h && pos) return h.flashAtPos?.(pos);
                return undefined;
            },
            // 句级落点原料：marked 字形叶（PdfPane.seqLeaves 桥）
            pdfSeqLeaves: (dst, seq) => {
                const h = handles()[dst === "zh" ? "translated" : "original"];
                return h && "seqLeaves" in h ? h.seqLeaves?.(seq) : undefined;
            },
            pdfFlashEls: (dst, els) => {
                const h = handles()[dst === "zh" ? "translated" : "original"];
                if (h && "flashEls" in h) h.flashEls?.(els);
            },
            // 悬停伴显桥：pdf 侧经 hoverSeq 锚/带染色（dom 侧无此面，
            // sentalign 内 DOM 对侧自己染 [data-sid] span）
            pdfHover: (dst, seq, pos, cls) => {
                const h = handles()[dst === "zh" ? "translated" : "original"];
                if (h && "hoverSeq" in h) h.hoverSeq?.(seq, pos, cls);
            },
            // 句级悬停色桥：pdf 侧逐叶 saTint（sentalign 句级揭示面）
            pdfTintEls: (dst, els, cls) => {
                const h = handles()[dst === "zh" ? "translated" : "original"];
                if (h && "tintEls" in h) h.tintEls?.(els, cls);
            },
            // 动效三件套：点击涟漪/落句连线+行擦入（anim.ts 全 fixed
            // 零重排面；reduced-motion 自带降级）
            anim: {
                press: (x, y) => saPress(x, y),
                land: (from, els) => saLand(from, els),
            },
        },
    });
    const saReg = registerSentAlign(reg, { session: sa.session });
    // 开关翻转 → 差异重扫（关=剥光 .ens/.zhs 标引，开=重注入）
    createEffect(() => {
        settingsStore.sentAlign();
        sa.syncPanes();
    });

    onCleanup(() => {
        sa.dispose();
        saReg.dispose();
        saCancelLand(); // 在飞连线/擦入盖层随视图一起摘
    });

    return { sa };
}
