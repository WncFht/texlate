// 任务列表/活动任务 store —— solid store 承载 §2 快照 + SSE 增量。
// 拆分层（C3）：帧→live 归约在 liveFrames.ts（纯函数），观测通道编排
//（wanted/SSE 槽/轮询/探活）在 taskTransport.ts——本层是状态面与门面：
// tasks 行 reconcile/patch、TaskLive 写入、终态收敛、公开 API。

import { batch } from "solid-js";
import { createStore, produce, reconcile } from "solid-js/store";
import {
    api,
    ApiError,
    errText,
    forgetTaskEvents,
    isFailed,
    isTerminal,
    liveSeqWatermark,
    type ChunkItem,
    type TaskChannel,
    type TaskSnapshot,
    type TaskStatus,
} from "../api/client";
import {
    chunkCap,
    foldFixloop,
    mergeChunkItemsInto,
    normalizeLogfix,
    type TaskLive,
} from "./liveFrames";
import { createTransport } from "./taskTransport";
import { toast } from "./toastStore";
import { canonArxivKey } from "../arxidcanon";
import { currentLang, fmt, t, tPath } from "../i18n";

// 门面再导出：live 面类型与传输调参常量是 store 公开面的一部分——
// 消费方（TaskProgress/tests）从 tasks.ts 单点拿，不追内部文件布局
export type { TaskLive } from "./liveFrames";
export { MAX_SSE_TASKS, POLL_INTERVAL_MS } from "./taskTransport";
export { canonArxivKey };

interface TasksState {
    tasks: TaskSnapshot[];
    loaded: boolean;
    loadError?: string;
    live: Record<string, TaskLive>;
}

const [state, setState] = createStore<TasksState>({
    tasks: [],
    loaded: false,
    live: {},
});

const freshLive = (): TaskLive => ({
    stages: [],
    chunkItems: [],
    logs: [],
    warnings: [],
    transport: "connecting",
});

function ensureLive(taskId: string): void {
    setState("live", taskId, (l) => l ?? freshLive());
}

// ---------------------------------------------------------------------------
// B2 观测面：track/intents/taskByArxiv + 完成通知（cite-translate §D 挂法 A）
// ---------------------------------------------------------------------------

/** intents 竞态桥 TTL——POST 已回 task_id、列表行尚未物化的窗口期 */
const INTENT_TTL_MS = 60_000;

interface TaskIntent {
    taskId: string;
    /** 调用方给的原始 arxiv 形（合成占位行的 arxiv_id 展示用） */
    arxiv: string;
    at: number;
}

/**
 * arxivId(canon 键) → taskId 竞态桥：cite 卡/批译 POST 返回后列表行未
 * 物化前，taskByArxiv 仍能解析到任务。惰性过期（读时判+dropTask 反向清）。
 * 测试可经 taskStore.intents 读/清；业务面只走 track/taskByArxiv。
 */
const intents = new Map<string, TaskIntent>();

/** task_id 行定位一处口径（upsert/stage/done/patch/task 共用） */
function rowIndex(id: string): number {
    return state.tasks.findIndex((t) => t.task_id === id);
}

function rowOf(id: string): TaskSnapshot | undefined {
    return state.tasks.find((t) => t.task_id === id);
}

/**
 * 字段级写回行——行对象引用不变，TaskList 的 <For> 不整行重挂（M9）。
 * reconcile 对对象节点 in-place 合并：新增键落位、缺席键清 undefined
 * （快照语义——服务端不发即无此值）、等值叶不触写。
 */
function upsertTask(snap: TaskSnapshot) {
    const i = rowIndex(snap.task_id);
    if (i < 0) {
        setState("tasks", (list) => [snap, ...list]);
        return;
    }
    setState("tasks", i, reconcile(snap));
}

/**
 * /api/tasks 列表行是 TaskSnapshot 子集（缺 artifacts/warnings/usage/
 * queue_position/options/glossary）——reconcile 快照语义会把缺席键清
 * undefined，从现行行继承防清缺（refresh 与共享列表轮询共用）。
 */
function inheritRich(
    s: TaskSnapshot,
    cur: TaskSnapshot | undefined,
): TaskSnapshot {
    if (!cur) return s;
    return {
        ...s,
        artifacts: s.artifacts ?? cur.artifacts,
        warnings: s.warnings ?? cur.warnings,
        usage: s.usage ?? cur.usage,
        // 仅排队中继承——离队后 queue_position 语义是「缺席」，
        // 照搬旧读会让已起跑/终态行永挂死位次
        queue_position:
            s.status === "queued"
                ? (s.queue_position ?? cur.queue_position)
                : undefined,
        options: s.options ?? cur.options,
        glossary: s.glossary ?? cur.glossary,
    };
}

/**
 * 列表行归并的水位守卫（refresh 与共享列表轮询共用口径）：SSE 已消费
 * 水位线或现行行 last_seq 领先于列表旧读 → 现行行顶替，旧读不回退；
 * 否则 inheritRich 补富字段后归并。stale 判定返回 cur 本身——调用方
 * 以 === 识别跳过（stale 行不写回、不进 convergeTerminal）。
 */
function mergeRow(
    incoming: TaskSnapshot,
    cur: TaskSnapshot | undefined,
): TaskSnapshot {
    if (
        cur !== undefined &&
        Math.max(liveSeqWatermark(incoming.task_id), cur.last_seq ?? 0) >
            (incoming.last_seq ?? 0)
    )
        return cur;
    return inheritRich(incoming, cur);
}

/** 终态收敛：释放 append-only 缓冲（logs/stages 会话内单调增长）；
 * done/chunk/chunkItems/warnings/error 留给终态面板与棋盘格；
 * fixloop/logfix 同属终态面板材料——不清 */
function settleLive(taskId: string) {
    if (!state.live[taskId]) return;
    setState("live", taskId, "logs", []);
    setState("live", taskId, "stages", []);
}

/**
 * 完成通知（cite-translate §D 挂法 A）：live.done 物化是唯一汇聚面——
 * 全部终态入径（SSE done 帧/snapshot 终态/共享列表轮询/refresh/独轮询
 * tick/探活/resync）收敛到 2 个写点：convergeTerminal 的 `!live.done`
 * 守卫内一发 + done handler 的 hadDone 快照后置守卫一发，每轮恰一次。
 * 天然免报：refresh/轮询首见终态的存量行（未 wanted 不 converge）、
 * deleted 帧；retry 新轮 resetLive 清 done rearm 后再报一次。
 */

/**
 * i18n 键 t.taskNotify.* 由 misc-frontend lane 合入——合入前经 tPath 安全
 * 取键拿模板/按钮文案，缺席回落拼装串（类型面不报错的运行期兜底）。
 */
function notifyTpl(): { done?: string; failed?: string; view: string } {
    return {
        done: tPath("taskNotify.done") ?? undefined,
        failed: tPath("taskNotify.failed") ?? undefined,
        view:
            tPath("taskNotify.view") ??
            (currentLang() === "zh" ? "查看" : "View"),
    };
}

function notifyDone(task: TaskSnapshot): void {
    // node 测试环境无通知面——store 状态路径不受影响
    if (typeof window === "undefined" || typeof document === "undefined")
        return;
    const keys = notifyTpl();
    const status = task.status;
    const title = task.title ?? task.arxiv_id ?? task.task_id;
    const tpl =
        (isFailed(status) ? keys.failed : keys.done) ?? "{title} · {status}";
    const text = fmt(tpl, {
        title,
        status: t.status[status] ?? status,
    });
    const key = `texlate-${task.task_id}`;
    // 显示门：页面藏起且已授权 → 系统通知（tag 幂等去重）；其余 in-app toast
    if (
        document.hidden &&
        typeof Notification !== "undefined" &&
        Notification.permission === "granted"
    ) {
        try {
            const n = new Notification(text, { tag: key });
            n.onclick = () => {
                window.focus();
                location.hash = `#/reader/${task.task_id}`;
            };
            return;
        } catch {
            /* 构造被拒（非安全上下文等）——回落 toast */
        }
    }
    const action = { label: keys.view, href: `#/reader/${task.task_id}` };
    if (isFailed(status)) toast.err(text, { key, action });
    else toast.ok(text, { key, action });
}

/**
 * 终态收敛统一入口：合成 done 兜底 + settleLive + unwant。
 *
 * 非 done 帧探到终态时真实 done 帧可能永不到达——SSE snapshot(seq=0)
 * 恒先于重放段的 done 上电线，client 收终态即 close()，done 被丢在
 * 线路上；轮询/探活路径本就没有 done 帧。live.done 缺席 → Reader 的
 * `done && !info()` → loadReader 永不触发 → 终态任务永卡 loading。
 * snapshot.artifacts 与 done.artifacts 同源（server `_artifacts`）；
 * stats 缺键由 counters/usage 兜底（taskStats.mergeResultStats）。
 */
function convergeTerminal(taskId: string, s: TaskSnapshot) {
    ensureLive(taskId);
    if (!state.live[taskId]?.done) {
        setState("live", taskId, "done", {
            status: s.status,
            // 拷一份再入 store——s.artifacts 与 reconcile 后的行 artifacts
            // 共用底层节点，直接写入会让后续 reconcile 改穿到 live.done
            artifacts: { ...(s.artifacts ?? {}) },
            stats: {},
        });
        // 守卫内发一次——迟到的真实 done 帧见 live.done 已在即不重发
        notifyDone(s);
    }
    settleLive(taskId);
    tp.unwant(taskId);
}

/** 任务行已删（本地 remove / 服务端 deleted 帧 / 轮询 404 / SSE 探活 404）——观测+状态+水位线全清 */
function dropTask(taskId: string) {
    tp.drop(taskId);
    forgetTaskEvents(taskId);
    // 竞态桥里指向已删任务的登记一并清——否则 taskByArxiv 在 TTL 内
    // 继续合成「幽灵 queued 占位行」
    for (const [k, it] of intents) if (it.taskId === taskId) intents.delete(k);
    setState("tasks", (list) => list.filter((t) => t.task_id !== taskId));
    setState(
        "live",
        produce((l) => {
            delete l[taskId];
        }),
    );
}

// 帧→状态归约 handlers（transport/resync 两键是传输自留地，不在此表）。
// 需 unwant/rebalance 的帧（snapshot/done 终态沿、deleted 帧）经 tp 回调——
// tp 在此对象字面量求值后才赋值，handler 体执行时已在位（惰性闭包）。
const tp = createTransport({
    tasks: () => state.tasks,
    ensureLive,
    setTransport: (taskId, s) => setState("live", taskId, "transport", s),
    upsertTask,
    onTerminal: convergeTerminal,
    onDrop: dropTask,
    // 非 pin 观测面共享列表轮询：一拍 /api/tasks 整表归并——与 refresh
    // 同水位口径（现行行更新则列表旧读不回退）。整表而非只 wanted ids：
    // 响应本含全表，顺带归并外来行让徽标/Tasks 页对「别处新开的任务」
    // 也精确（修 reader 停留期盲区）；新非终态行自动 wanted(pin:false)、
    // 消失行收敛为已删（pin 行除外——其 404 生命周期由自有通道探活管，
    // 列表可能因翻页/竞态短暂缺席，不能一帧缺席就拆 reader 的聚焦）。
    pollListWanted: async () => {
        const list = await api.tasks();
        const byId = new Map(state.tasks.map((r) => [r.task_id, r]));
        const ids = new Set<string>();
        let dirty = false;
        for (const s of list) {
            if (!ids.add(s.task_id)) continue; // 翻页重复行兜底（refresh 同口径）
            const cur = byId.get(s.task_id);
            const m = mergeRow(s, cur);
            if (m !== cur) {
                upsertTask(m);
                if (isTerminal(m.status) && tp.wanted.has(s.task_id)) {
                    // 收敛喂归并后行——原始列表行缺 artifacts，直喂会把
                    // live.done 的 artifacts 合成成 {}（refresh 路同口径）
                    convergeTerminal(s.task_id, m);
                    dirty = true;
                }
            }
            if (!isTerminal(m.status) && !tp.wanted.has(s.task_id)) {
                // 外来在跑行——登记非 pin 观测（下拍起在归并面内）
                tp.wanted.set(s.task_id, { pin: false });
                dirty = true;
            }
        }
        // 列表里消失的行 = 已删：pin 行留着（reader 聚焦面的 404 由
        // settleSnapshot/探活精确收敛），其余整行清
        for (const row of [...state.tasks]) {
            if (ids.has(row.task_id)) continue;
            if (tp.wanted.get(row.task_id)?.pin) continue;
            dropTask(row.task_id);
            dirty = true;
        }
        if (dirty) tp.rebalance();
    },
    clearChunkLive: (taskId) => {
        setState("live", taskId, "chunk", undefined);
        setState("live", taskId, "chunkItems", []);
    },
    frameHandlers: (taskId) => ({
        snapshot: (s) => {
            upsertTask(s);
            if (isTerminal(s.status)) {
                convergeTerminal(taskId, s);
                tp.rebalance();
            }
        },
        stage: (e) => {
            batch(() => {
                setState("live", taskId, "stage", e);
                setState("live", taskId, "stages", (ss) => [...ss, e]);
                // 字段级补丁——行引用不变，<For> 不整行重挂（M9）
                const i = rowIndex(taskId);
                if (i >= 0) {
                    setState("tasks", i, "status", e.stage);
                    setState("tasks", i, "stage", e.stage);
                    setState("tasks", i, "progress", e.progress);
                    setState("tasks", i, "message", e.message);
                }
            });
        },
        chunk: (e) => {
            batch(() => {
                setState("live", taskId, "chunk", e);
                // 一帧一次 produce：空洞补齐+落位先在 draft 上算完再统一
                // 落盘——跳到 seq=N 时逐格 setState 是 N 笔写（seq 上限
                // 100k 即病态放大）；produce 仍只触达被写 index 的订阅，
                // ProgressGrid 按格订阅的 P2 语义不破
                const cap = chunkCap(e.total);
                setState(
                    "live",
                    taskId,
                    "chunkItems",
                    produce((items: ChunkItem[]) =>
                        mergeChunkItemsInto(items, e.items, cap),
                    ),
                );
            });
        },
        log: (e) => {
            // 追加写不拷全表（编译爆发期逐条派发，slice(-499) 每条 O(500)
            // 分配+For 全表 diff）；满 600 才一次性截回 500，摊薄截断成本
            const len = state.live[taskId]?.logs.length ?? 0;
            if (len >= 600) {
                setState("live", taskId, "logs", (ls) => [
                    ...ls.slice(-499),
                    e,
                ]);
            } else {
                setState("live", taskId, "logs", len, e);
            }
        },
        warning: (e) =>
            setState("live", taskId, "warnings", (ws) => [...ws, e]),
        error: (e) => setState("live", taskId, "error", e),
        fixloop: (e) => {
            const next = foldFixloop(state.live[taskId]?.fixloop, e);
            if (next !== null) setState("live", taskId, "fixloop", next);
        },
        logfix: (e) => setState("live", taskId, "logfix", normalizeLogfix(e)),
        done: (e) => {
            // DELETE 端点的收尾帧——本任务行已删，别回填成 "deleted" 僵尸行
            if (e.status === "deleted") {
                dropTask(taskId);
                tp.rebalance();
                return;
            }
            const status = e.status; // 窄化在闭包外——batch 内不继承 narrowing
            // 通知守卫快照须抢在 batch 前——done 落地后 live.done 必在场，
            // 拍晚了守卫恒真（恰一次语义毁于时序而非逻辑）
            const hadDone = state.live[taskId]?.done !== undefined;
            batch(() => {
                setState("live", taskId, "done", e);
                const i = rowIndex(taskId);
                if (i >= 0) {
                    setState("tasks", i, "status", status);
                    setState("tasks", i, "progress", 100);
                    // 拷一份——e.artifacts 已随 live.done 入 store，同对象入
                    // 第二路径会共用节点，后续 reconcile 会改穿 live.done
                    setState("tasks", i, "artifacts", { ...e.artifacts });
                }
                settleLive(taskId);
            });
            tp.unwant(taskId);
            tp.rebalance();
            // snapshot 终态已先行合成 live.done（convergeTerminal 已报）的
            // 迟到 done 帧不重发；首见 done 才报（行不在册则无从跳转，不报）
            if (!hadDone) {
                const row = rowOf(taskId);
                if (row) notifyDone(row);
            }
        },
    }),
});

let lastFreshAt = 0;

export const taskStore = {
    state,

    /**
     * TTL 门下的 refresh：多页（Home 进行中提示/Tasks 列表/App 徽标）
     * 挂载时都调——同一资源一处 TTL，路由往返不再各页各拉一份。
     * 时间戳先落再 await：并发挂载只放一马；refresh 失败同样记时防连打。
     */
    async ensureFresh(ttlMs = 30_000) {
        if (Date.now() - lastFreshAt < ttlMs) return;
        lastFreshAt = Date.now();
        await taskStore.refresh();
    },

    async refresh() {
        try {
            const list = await api.tasks();
            const byId = new Map(state.tasks.map((r) => [r.task_id, r]));
            // 列表行是请求发起时刻的旧读——在飞 SSE 事件已推进的行会被
            // reconcile 回退；行 last_seq 落后于已消费 seq（SSE 水位线∪
            // 行内 last_seq）→ store 现行行顶替。offset 翻页在并发插入
            // 下可能重复见行——task_id 去重兜底
            const seen = new Set<string>();
            const merged: TaskSnapshot[] = [];
            for (const t of list) {
                if (seen.has(t.task_id)) continue;
                seen.add(t.task_id);
                merged.push(mergeRow(t, byId.get(t.task_id)));
            }
            // reconcile 按 task_id 匹配：在册行字段级合并（引用不变，
            // <For> 行不重挂）；新行插入、消失行移除——一次原子替换
            setState("tasks", reconcile(merged, { key: "task_id" }));
            // reconcile 收缩路径可产稀疏数组洞——下游 find/forEach 遇洞
            // 拿 undefined 行即 TypeError（sparse 实证；retention_loop
            // 周期性删终态行后首次 refresh 就触发）。一次 filter 压紧：
            // 元素引用原样保留，<For> 不整行重挂
            setState("tasks", (l) => l.filter((x) => x != null));
            setState("loaded", true);
            setState("loadError", undefined);
            const ids = new Set(merged.map((t) => t.task_id));
            for (const t of merged) {
                if (!isTerminal(t.status)) {
                    if (!tp.wanted.has(t.task_id))
                        tp.wanted.set(t.task_id, { pin: false });
                } else if (tp.wanted.has(t.task_id)) {
                    // 列表回终态（done 帧可能未到/已丢）——收敛并摘除
                    convergeTerminal(t.task_id, t);
                }
            }
            // 列表里消失的非 pin 任务（别处已删）——停止观测；pin 的留着
            // （reader 可能在 retry 间隙，新快照未到）
            for (const [id, w] of [...tp.wanted]) {
                if (!ids.has(id) && !w.pin) tp.unwant(id);
            }
            tp.rebalance();
        } catch (e) {
            setState({
                loaded: true,
                loadError: errText(e),
            });
        }
    },

    /**
     * 订阅任务（pin=聚焦优先占 SSE 槽；幂等——重复调用复用同一句柄）。
     * 句柄 close() 恒等于 unwatch：SSE 与轮询双轨同一 detach 语义（M2）。
     */
    watch(taskId: string): TaskChannel {
        return tp.watch(taskId);
    },

    /** 摘除观测（幂等公开）：close() 句柄与显式调用等价 */
    unwatch(taskId: string) {
        tp.unwatch(taskId);
    },

    /** 本地补丁任务行（retry 后乐观更新；SSE snapshot 随后来覆盖为准）。
     *  逐字段写——行引用保持（M9）；undefined 值跳过（patch 只带要改的键） */
    patch(taskId: string, p: Partial<TaskSnapshot>) {
        const i = rowIndex(taskId);
        if (i < 0) return;
        for (const [k, v] of Object.entries(p)) {
            if (v === undefined) continue;
            (setState as (...a: unknown[]) => void)("tasks", i, k, v);
        }
    },

    /** 删除任务：先 DELETE 后端（404 视为已删同样本地移除），再清 SSE/列表/live */
    async remove(taskId: string) {
        try {
            await api.deleteTask(taskId);
        } catch (e) {
            if (!(e instanceof ApiError && e.status === 404)) throw e;
        }
        dropTask(taskId);
        tp.rebalance();
    },

    /** retry 复用同一 task_id：清掉上一轮 SSE 痕迹再重新订阅（seq 水位线保留——旧轮重放帧照丢） */
    resetLive(taskId: string) {
        tp.revive(taskId); // 新轮给 SSE 一次复活机会
        tp.unwant(taskId); // watchHandles 保留——watch() 复用同一句柄
        setState("live", taskId, freshLive());
        // merge 语义不清缺席键——上一轮散叶残件显式清：陈旧 live.done
        // 泄进新轮会让 Reader 拿旧 artifacts、完成通知守卫恒真不再 rearm
        for (const k of [
            "stage",
            "chunk",
            "done",
            "error",
            "fixloop",
            "logfix",
        ] as const)
            (setState as (...a: unknown[]) => void)(
                "live",
                taskId,
                k,
                undefined,
            );
        taskStore.watch(taskId);
    },

    live(taskId: string): TaskLive | undefined {
        return state.live[taskId];
    },

    task(taskId: string): TaskSnapshot | undefined {
        return rowOf(taskId);
    },

    /**
     * 非 pin 登记（cite 卡/批译等外部提交桥的观测入口）：入 wanted
     * (pin:false)——槽空按 updated_at 序可占 SSE 槽，槽满降级共享列表
     * 轮询；已有 wanted 登记的行不动既有 pin 标记（幂等）。
     * 带 arxivId 时记 intents 竞态桥（TTL 60s）——POST 已回 task_id、
     * 列表行未物化的窗口内 taskByArxiv 仍能解到。
     * 注意：只登记在跑任务；pin 槽是 reader 聚焦专属，卡/徽标面一律
     * 走本件而非 watch()。
     */
    track(taskId: string, opts: { arxivId?: string } = {}) {
        if (!tp.wanted.has(taskId)) tp.wanted.set(taskId, { pin: false });
        if (opts.arxivId) {
            const key = canonArxivKey(opts.arxivId);
            if (key)
                intents.set(key, {
                    taskId,
                    arxiv: opts.arxivId,
                    at: Date.now(),
                });
        }
        tp.rebalance();
    },

    /** 竞态桥本体（facade 只读面；测试清桶 cast 回 Map）；业务面只经 track/taskByArxiv 读写 */
    intents: intents as ReadonlyMap<string, TaskIntent>,

    /**
     * arxivId → 任务行派生选择器（双侧 canon 归一后匹配）：
     * 行内多命中按 可读终态(done|partial) > 在跑 > 败终态 取档，
     * 同档取 updated_at 最新；行内无命中回退 intents 竞态桥——TTL 内
     * 合成 queued 占位行（task_id 保真，卡片可先跳「排队中」态）。
     */
    taskByArxiv(arxivId: string): TaskSnapshot | undefined {
        const key = canonArxivKey(arxivId);
        if (!key) return undefined;
        let best: TaskSnapshot | undefined;
        let bestRank = -1;
        for (const row of state.tasks) {
            if (!row.arxiv_id) continue;
            if (canonArxivKey(row.arxiv_id) !== key) continue;
            const rank =
                row.status === "done" || row.status === "partial"
                    ? 2
                    : isTerminal(row.status)
                      ? 0
                      : 1;
            if (
                rank > bestRank ||
                (rank === bestRank &&
                    (row.updated_at ?? 0) > (best?.updated_at ?? 0))
            ) {
                best = row;
                bestRank = rank;
            }
        }
        if (best) return best;
        const it = intents.get(key);
        if (!it) return undefined;
        if (Date.now() - it.at > INTENT_TTL_MS) {
            intents.delete(key);
            return undefined;
        }
        const row = rowOf(it.taskId);
        if (row) return row;
        return {
            task_id: it.taskId,
            kind: "arxiv",
            status: "queued",
            progress: 0,
            created_at: Math.floor(it.at / 1000),
            updated_at: Math.floor(it.at / 1000),
            arxiv_id: it.arxiv,
        };
    },

    /** taskByArxiv 的状态投影——卡钮/徽标只问相时的便捷形 */
    taskStatusOf(arxivId: string): TaskStatus | undefined {
        return taskStore.taskByArxiv(arxivId)?.status;
    },

    /**
     * 进行中（非终态）任务计数——App.tsx 顶导航徽标同口径单源化：
     * active=queued/fetching/parsing/translating/compiling 五态，
     * interrupted 属 UI 终态不计。细粒度订阅只跟 status 叶。
     */
    activeCount(): number {
        return state.tasks.reduce(
            (n, x) => n + (isTerminal(x.status) ? 0 : 1),
            0,
        );
    },
};
