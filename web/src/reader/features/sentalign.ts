// features/sentalign —— sent-align lane 的挂载面（Wave C 落地契约，
// 实施文档 docs/dev/ux-impl-2026-09-22/sent-align…实施文档.md）。
//
// attachSentAlign(opts) —— 持有 SentAlignSession，按 opts.panes() 现扫
//   把各 DOM 窗格挂成一侧：bodyEl 变化才重挂（pane 重渲零成本），
//   kind=='pdf' 或无 bodyEl 的 pane 登记为 DOM→PDF 跳转目标侧——
//   clickEl+posAtPoint 在场时同侧另挂 PDF→PDF 点击源（位置映射跳，
//   行带级落点闪；句级 quad 高亮属 v2 句锚面）；
//   opts.enabled() 假 → 全侧卸载（开关关闭零残留——注入 span 全剥）。
//   整合调用点：paneReady/paneDisposed/视图换型后 syncPanes()；组件卸载
//   dispose()。enabled 挂 settingsStore.sentAlign 时建议另起 effect 在
//   信号翻转处也调 syncPanes（或把调用塞进既有 pane-watcher 链尾）。
//
// registerSentAlign(reg, opts) —— 右键菜单命令面（v1 一项）：
//   sent.gotoPeer   when="sent.bead" —— 命中带 bead 的句 → 跳对侧 bead。
//                   谓词键 sent.bead 由 hitctx flattenCtx 供给（INTEGRATION：
//                   hitctx.ts 增 sent.{sid,bead} 三键 + CTX_KEYS 登记 +
//                   snapshotHit 里 closest('[data-sid]') 快照）——键未落地
//                   前谓词恒假天然隐藏，注册面零依赖先行。
//   命令不重复实现跳转——run 直调 session.jumpToPeer。
//
// i18n：menu.sent.gotoPeer 键整合期进 zh.ts/en.ts——注册 title 即该键，
//   MENU_LABELS 镜像串 "跳到对侧句 / Jump to peer sentence"。

import type { Pos } from "../alignment";
import type { Command, Registry } from "../cmd/cmdreg";
import type { CmdCtx } from "../cmd/commands";
import {
    SentAlignSession,
    type SaSide,
    type SentAlignDeps,
} from "../sentalign";

// ------------------------------------------------------------------ 契约面

/** 宿主 pane 的描述子——只用词表字段，不绑具体 Pane 类。 */
export interface SentAlignPane {
    /** pane 类：'dom'|'html'|'live'|'pdf'|…（宿主自定词表） */
    kind: string;
    /** 'en'|'original' → en 侧；'zh'|'translated' → zh 侧；缺省按 en */
    side?: string;
    /** 句料容器（dom=section 宿主，html/live=正文体；pdf 侧缺省） */
    bodyEl?: HTMLElement;
    /** 滚动容器（缺省=bodyEl——DomPane 的 .pane-html-scroll 之类） */
    scroller?: HTMLElement;
    /** Pos 快照（recordJump 记账的 pre/post 源——handle.capture 绑定形） */
    capture?(): Pos;
    /** pdf 源侧点击挂点（PDF→PDF/PDF→DOM 臂——viewer 容器；dom 侧不给） */
    clickEl?: HTMLElement;
    /** 点击坐标 → Pos（PdfPane.posAtPoint 桥） */
    posAtPoint?(x: number, y: number): Pos | null;
    /** 点击坐标 → seq（PdfPane.seqAtPoint 桥 + 宿主 nearestSeq 兜底——
        在场时点击走 seq 精度快路，Pos 臂降为兜底） */
    seqAtPoint?(x: number, y: number): number | null;
}

export interface SentAlignAttachOpts {
    panes(): readonly SentAlignPane[];
    /** 总开关（settingsStore.sentAlign）——缺省恒 true */
    enabled?(): boolean;
    /** 会话依赖（navBegin/recordJump/mapPos/pdfDest/pdfJump） */
    deps?: SentAlignDeps;
}

export interface SentAlignHandle {
    /** paneReady/paneDisposed/换 view 后调用——现扫 panes() 差异重挂；
        enabled() 翻转也走这里（关→全剥，开→全注）。 */
    syncPanes(): void;
    /** 会话本体（jumpToPeer/注入单测/状态面直读） */
    readonly session: SentAlignSession;
    dispose(): void;
}

// ------------------------------------------------------------------ attach

const paneSide = (p: SentAlignPane): SaSide =>
    p.side === "zh" || p.side === "translated" ? "zh" : "en";

export function attachSentAlign(opts: SentAlignAttachOpts): SentAlignHandle {
    const session = new SentAlignSession(opts.deps ?? {});
    const enabled = opts.enabled ?? (() => true);
    /** 侧 → 当前挂的 bodyEl——只在换了宿主元素时才重挂 */
    const mounted = new Map<SaSide, HTMLElement>();

    const syncPanes = (): void => {
        const panes = opts.panes();
        const want = new Map<SaSide, SentAlignPane>();
        for (const p of panes) want.set(paneSide(p), p); // 同侧多 pane 尾者胜
        for (const side of ["en", "zh"] as const) {
            const p = want.get(side);
            const body = p?.bodyEl ?? null;
            if (!enabled() || !p) {
                // 关总开关或侧消失——卸（pdf 目标登记也一并清）
                session.unmountSide(side);
                mounted.delete(side);
                continue;
            }
            if (body) {
                if (mounted.get(side) === body) continue; // 同体免重挂
                mounted.set(side, body);
                void session.mountSide(side, body, {
                    scroller: p.scroller,
                    kind: p.kind,
                    capture: p.capture,
                });
            } else {
                // 无 body 的侧（pdf 窗格）——DOM→PDF 目标登记；
                // clickEl+posAtPoint 在场同侧挂 PDF 点击源（seqAtPoint
                // 可选项——给了点击先走 seq 快路，缺席纯 Pos 臂）
                mounted.delete(side);
                session.unmountSide(side);
                session.mountPdfSide(side);
                if (p.clickEl && p.posAtPoint)
                    session.mountPdfClickSource(
                        side,
                        p.clickEl,
                        p.posAtPoint,
                        p.seqAtPoint,
                    );
            }
        }
    };

    return {
        syncPanes,
        session,
        dispose() {
            session.destroy();
            mounted.clear();
        },
    };
}

// ------------------------------------------------------------------ 命令面

export interface SentAlignRegOpts {
    /** 会话源——缺省内部另起（整合面传 attach 的那份共享状态） */
    session?: SentAlignSession;
}

/** 注册 sent.gotoPeer——hitctx sent.* 键落地前谓词恒假天然隐藏。 */
export function registerSentAlign(
    reg: Registry<CmdCtx>,
    opts: SentAlignRegOpts = {},
): { dispose(): void } {
    const session = opts.session ?? new SentAlignSession();
    const cmds: Command<CmdCtx>[] = [
        {
            id: "sent.gotoPeer",
            title: "menu.sent.gotoPeer",
            sec: "sent",
            bar: true,
            when: "sent.bead",
            run: (c) => {
                const bead = c["sent.bead"];
                const side = c.hit.paneSide === "zh" ? "zh" : "en";
                if (typeof bead === "string" && bead)
                    session.jumpToPeer(bead, side);
            },
        },
    ];
    for (const cmd of cmds) {
        if (reg.get(cmd.id)) reg.unregister(cmd.id); // 幂等重挂
        reg.register(cmd);
    }
    return {
        dispose() {
            for (const cmd of cmds) reg.unregister(cmd.id);
        },
    };
}
