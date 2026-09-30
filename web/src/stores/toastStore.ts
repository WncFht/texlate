// 全局 toast store —— 落地形态对齐 settings.ts/tasks.ts：
// 模块级 createSignal 承载、导出纯对象门面；文案由调用方给 t.* 成品串。
// 原型经 14 探针验证（2026-09-22 toast 预研），落地期按
// 契约收敛 API：push 改对象入参，action 支持 href 直跳；并修掉实测
// 抓到的死角（key 刷新时显式传入的新 action 现在会整体换新）。
//
// 与 HtmlPane 既有 .pane-toast 的关系：那是窗格内单槽 sticky 条（只覆盖
// 单段重译三态），本件是 app 级栈——SSE 断流、删除/清理回执、引用翻译
// 提交回执等无处落面的事件统一收口；窗格条保留原位（就近语义），不替换。

import { createSignal } from "solid-js";

export type ToastKind = "ok" | "err";

export interface ToastAction {
    label: string;
    /** 点按回调（host 渲染为按钮；act() 先收条再跑） */
    onClick?: () => void;
    /** 跳转目标（host 渲染为 <a>，hash 路由直跳；点击即收条） */
    href?: string;
}

export interface Toast {
    id: number;
    kind: ToastKind;
    text: string;
    /** 去重键——同 key 重推刷新原条文案+计时器而非叠新条 */
    key?: string;
    /** ms；Infinity/非正数=常驻条（需手动 dismiss） */
    ttl: number;
    createdAt: number;
    action?: ToastAction;
}

export interface ToastInput {
    kind: ToastKind;
    text: string;
    key?: string;
    ttl?: number;
    action?: ToastAction;
}

/** ok/err 便捷包装的可选参（kind/text 由包装自供） */
export type ToastOpts = Pick<ToastInput, "key" | "ttl" | "action">;

/** 栈上限——超出逐最旧，避免事件风暴把屏幕糊满 */
const MAX_TOASTS = 3;
/** 与既有 .pane-toast 同口径（HtmlPane RETX_TOAST_MS=4500） */
const DEFAULT_TTL_MS = 4500;
/** 错误条多留一倍——读错误比读成功费时 */
const ERR_TTL_MS = 9000;

const [toasts, setToasts] = createSignal<Toast[]>([]);
const timers = new Map<number, number>();
let nextId = 1;

const scheduleDismiss = (id: number, ttl: number): void => {
    if (!(ttl > 0) || !Number.isFinite(ttl)) return;
    timers.set(
        id,
        window.setTimeout(() => toast.dismiss(id), ttl),
    );
};

export const toast = {
    /** 当前栈（入栈序；渲染顺序交给 host） */
    toasts,

    /**
     * 入栈；同 key 已在栈=刷新文案+计时器，返回原 id。
     * 刷新时 ttl/action 缺省=保留旧面，
     * 显式传入则整体换新——新 push 的 action 不会被旧条吞掉。
     */
    push(input: ToastInput): number {
        if (input.key !== undefined) {
            const cur = toasts().find((x) => x.key === input.key);
            if (cur) {
                window.clearTimeout(timers.get(cur.id));
                const ttl = input.ttl ?? cur.ttl;
                setToasts((l) =>
                    l.map((x) =>
                        x.id === cur.id
                            ? {
                                  ...x,
                                  text: input.text,
                                  kind: input.kind,
                                  ttl,
                                  action:
                                      input.action !== undefined
                                          ? input.action
                                          : x.action,
                              }
                            : x,
                    ),
                );
                scheduleDismiss(cur.id, ttl);
                return cur.id;
            }
        }
        const ttl =
            input.ttl ?? (input.kind === "err" ? ERR_TTL_MS : DEFAULT_TTL_MS);
        const id = nextId++;
        setToasts((l) => [
            ...l,
            {
                id,
                kind: input.kind,
                text: input.text,
                key: input.key,
                ttl,
                createdAt: Date.now(),
                action: input.action,
            },
        ]);
        scheduleDismiss(id, ttl);
        // 超帽逐最旧（shift 端）——新条必落，避免丢最新错误
        while (toasts().length > MAX_TOASTS) toast.dismiss(toasts()[0].id);
        return id;
    },

    /** 便捷包装——调用点高频就两个形 */
    ok(text: string, opts: ToastOpts = {}): number {
        return toast.push({ ...opts, kind: "ok", text });
    },
    err(text: string, opts: ToastOpts = {}): number {
        return toast.push({ ...opts, kind: "err", text });
    },

    dismiss(id: number): void {
        window.clearTimeout(timers.get(id));
        timers.delete(id);
        setToasts((l) => l.filter((x) => x.id !== id));
    },

    /** 触条上行内 onClick 动作：先收条再跑；href 动作由 host <a> 直渲不走这 */
    act(id: number): void {
        const run = toasts().find((x) => x.id === id)?.action?.onClick;
        toast.dismiss(id);
        run?.();
    },

    /** 全清——页面切换/任务重开一局时用；测试隔离也走这里 */
    clear(): void {
        for (const t of toasts()) window.clearTimeout(timers.get(t.id));
        timers.clear();
        setToasts([]);
    },
};

// 代码库门面命名习惯（settingsStore/taskStore）——同一对象的别名，任选其一
export const toastStore = toast;
