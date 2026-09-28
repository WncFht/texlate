// host/modeSwitch —— 模式切换保位置（texglot planModeChange）。
// pendingJump（补偿跳）由本簇持有、根部 paneReady 消费——{cur} 箱形共享；
// guideReturn 回程票是 guide 隐藏期 scrollTop 读 0/写无效的实测定型语义
// （出 guide 须用这张票对齐，不能吃 capturePos 的 0 值）；
// guide 模式 saveNow 必须先于 setMode——进 guide 后双栏 display:none、
// paneVisible 全 false，positions 空表早退会让 pending 防抖存盘白清。

import type { Mode } from "../chrome/Toolbar";
import { other, type DocId, type Pos, type PosMap } from "../logic/alignment";
import { capturePos } from "../logic/sync";
import type { AnyHandle } from "../panes/PaneSlot";

export function createModeSwitch(deps: {
    mode(): Mode;
    setMode(m: Mode): void;
    active(): DocId;
    setActive(d: DocId): void;
    arxivId(): string | undefined;
    handles(): Partial<Record<DocId, AnyHandle>>;
    paneVisible(side: DocId): boolean;
    mapper(): PosMap;
    saveNow(): void;
    clearSaveTimer(): void;
    persistPosition(): void;
}) {
    const {
        mode,
        setMode,
        active,
        setActive,
        arxivId,
        handles,
        paneVisible,
        mapper,
        saveNow,
        clearSaveTimer,
        persistPosition,
    } = deps;

    const pendingJump: { cur: { from: DocId; pos: Pos } | null } = {
        cur: null,
    };
    /** 进 guide 时抓的活侧位置——隐藏期 scrollTop 读 0/写无效（实测 chromium），
        出 guide 须用这张回程票对齐，不能吃 capturePos 的 0 值 */
    let guideReturn: { from: DocId; pos: Pos } | null = null;

    const planModeChange = (next: Mode) => {
        if (next === mode()) return;
        if (next === "guide") {
            // 导读不是文档侧——不查 handles()[target]、不改 active；
            // pendingJump 也不留脏值（位置职责由 guideReturn 接管）
            if (!arxivId()) return;
            const src =
                handles()[active()] ??
                handles().original ??
                handles().translated;
            guideReturn =
                src && paneVisible(src.side)
                    ? { from: src.side, pos: capturePos(src) }
                    : null;
            pendingJump.cur = null;
            // saveNow 必须在 setMode 前——进 guide 后双栏 display:none、
            // paneVisible 全 false，positions 空表早退，pending 防抖存盘
            // 会被白清；guide 模式本身不落库（回程位置走 guideReturn）
            saveNow();
            clearSaveTimer();
            setMode(next);
            return;
        }
        // 出 guide 的回程票优先（隐藏期活侧 scrollTop 读 0——见 guideReturn 注释）
        const ticket = mode() === "guide" ? guideReturn : null;
        guideReturn = null;
        const src = ticket
            ? null
            : (handles()[active()] ??
              handles().original ??
              handles().translated);
        const from = ticket?.from ?? src?.side;
        const pos = ticket?.pos ?? (src ? capturePos(src) : null);
        if (from && pos) {
            // 目标侧：split → 当前隐藏的对侧；单栏 → next 对应侧
            const target: DocId = next === "split" ? other(from) : next;
            const dst = handles()[target];
            if (dst) {
                // 目标窗格仍在挂载态（U3 后单栏切换两侧俱在）——立即跳，
                // 不留 pendingJump 污染下次挂载
                const to = from === target ? pos : mapper()(pos, from);
                requestAnimationFrame(() => dst.jump(to));
            } else {
                pendingJump.cur = { from, pos };
            }
        }
        setMode(next);
        // 单栏下活动侧跟随可见侧——页码/翻页键/批注都对准可见窗格
        if (next !== "split") setActive(next as DocId);
        persistPosition();
    };

    return { pendingJump, planModeChange };
}
