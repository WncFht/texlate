// keptRefs —— 文献收藏（kept_refs）store：reader 页单任务单例。
// 模块级（settingsStore/taskStore 同例）——深层 pane（PdfPane/DomPane
// 经 PaneSlot）直接消费，不经 ReaderView props 穿线。
//
// kept = {key → payload} 快照即真相：text/meta 是收藏时刻看到的版本，
// key 漂移（dom 链 bib.bibN 序数随 arXiv 版本变）不影响已收条目导出。
// toggle = 乐观写 + 失败回滚 + 全局写链串行——连点竞态下 PUT/DELETE
// 必须按序到服务端，且回滚只认「本拍仍是最新意图」（keySeq 代次闸）。
// load 带任务代次闸——切任务/重跑的迟到响应不落旧任务数据。

import { createSignal } from "solid-js";
import { api, type KeptRef } from "../api/client";

const [kept, setKept] = createSignal<Record<string, KeptRef>>({});
let curTask: string | null = null;
let loadSeq = 0;
const keySeq = new Map<string, number>();
let tail: Promise<unknown> = Promise.resolve();

export const keptRefs = {
    /** key → payload 快照表（响应式——isKept 在渲染上下文里读即订阅） */
    kept,
    count: () => Object.keys(kept()).length,
    isKept: (key: string): boolean => kept()[key] !== undefined,

    /** 全量取回——Reader mount 调一次；任务切换重调即重绑（先清后取，
        迟到响应按代次丢弃）。端点缺席/网络失败 → 静默空表（收藏面降级
        为「写了会回滚」——端点上线路由后即正常）。 */
    async load(taskId: string): Promise<void> {
        curTask = taskId;
        const my = ++loadSeq;
        setKept({});
        try {
            const res = await api.refsKept(taskId);
            if (curTask !== taskId || my !== loadSeq) return;
            setKept(res.kept ?? {});
        } catch {
            /* 端点缺席/拉取失败——kept 面留空，不挡阅读器 */
        }
    },

    /**
     * 乐观切换：kept 态立即翻转，后台 PUT/DELETE 落库；失败回滚。
     * 同 key 连点由 keySeq 代次闸保证「只有最后一拍的失败才回滚」；
     * 全局 tail 链串行保证服务端收到操作的次序 = 用户点击次序。
     */
    toggle(taskId: string, key: string, payload: KeptRef): void {
        const prev = kept()[key];
        const had = prev !== undefined;
        const my = (keySeq.get(key) ?? 0) + 1;
        keySeq.set(key, my);
        setKept((m) => {
            const n = { ...m };
            if (had) delete n[key];
            else n[key] = payload;
            return n;
        });
        const job = () =>
            api.refsKeepWrite(taskId, key, had ? null : payload);
        tail = tail.then(job).catch(() => {
            // 其后同 key 又有 toggle → 本拍意图已被顶替，不回灌
            if (keySeq.get(key) !== my) return;
            setKept((m) => {
                const n = { ...m };
                if (had) n[key] = prev;
                else delete n[key];
                return n;
            });
        });
    },
};
