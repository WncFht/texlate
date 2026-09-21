// submit —— Home arXiv 翻译提交编排：parseArxivId → collectOptions/byok
// → api.translate；409（同 cache_key 已有活动任务）直跳既有任务。busy
// 门防重入（输入框 Enter 隐式提交不走 disabled 钮）。自 pages/Home.tsx 拆出。

import {
    api,
    apiErrText,
    ApiError,
    type TranslateResponse,
} from "../api/client";
import { t } from "../i18n";
import type { HomeOptions } from "./options";
import { parseArxivId } from "./search";

export function createHomeSubmit(deps: {
    id(): string;
    busy(): boolean;
    setBusy(v: boolean): void;
    setError(v: string): void;
    /** id 解析失败——aria-invalid 只标格式错，服务端错误不占位 */
    markIdBad(): void;
    /** 卸载闸——在飞请求落地不得再动状态/劫持路由 */
    alive(): boolean;
    options: HomeOptions;
    /** 202 落地（reader_url 缺席回任务详情面） */
    onResult(res: TranslateResponse): void;
    /** 409 同 cache_key 活动任务 → 直接跳过去 */
    onExisting(taskId: string): void;
}) {
    const run = async () => {
        if (deps.busy()) return;
        const id = parseArxivId(deps.id());
        if (!id) {
            deps.setError(t.home.invalidId);
            deps.markIdBad();
            return;
        }
        deps.setError("");
        deps.setBusy(true);
        try {
            const res = await api.translate(
                id,
                deps.options.collectOptions(),
                deps.options.byok(),
            );
            if (!deps.alive()) return;
            deps.options.clearKey();
            deps.onResult(res);
        } catch (e) {
            if (!deps.alive()) return;
            // 409：同 cache_key 已有活动任务 → 直接跳过去
            if (e instanceof ApiError && e.status === 409) {
                const existing =
                    e.taskId ?? e.detail.match(/t_[0-9a-f]{16}/)?.[0];
                if (existing) {
                    deps.onExisting(existing);
                    return;
                }
            }
            deps.setError(apiErrText(e));
        } finally {
            deps.setBusy(false);
        }
    };

    return { run };
}

export type HomeSubmit = ReturnType<typeof createHomeSubmit>;
