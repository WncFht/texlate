// taskActions —— Reader 终态编排动作：retry（终态 → 同 id 重入队，§3.3）
// 与 arXiv HTML 换链降级（F 桶取源失败 → 新任务）。自 pages/Reader.tsx
// 拆出：编排是「信号 + store + api」的纯逻辑层，页面只留装配与渲染。

import { createSignal } from "solid-js";
import {
    api,
    ApiError,
    apiErrText,
    landingHash,
    type TaskSnapshot,
    type TaskStatus,
} from "../api/client";
import { taskStore } from "../stores/tasks";
import type { RetryError } from "./ResultBody";

/**
 * 终态 → 同 id 重跑。onAccepted 在同 id 被服务端接受后回调——调用方
 * 清产物快照/阅读态/装载闸；随后本件补丁列表行（先于 resetLive——
 * 否则 SSE 生效前 effect 会用旧终态回盖页面 task）并重订阅。
 */
export function createTaskRetry(deps: {
    taskId(): string;
    nav(to: string): void;
    onAccepted(status: TaskStatus): void;
}) {
    const [retrying, setRetrying] = createSignal(false);
    const [retryError, setRetryError] = createSignal<RetryError | null>(null);
    // needs_auth 结果面板的内联 API Key 输入（重试随 X-Texlate-Key 透传）
    const [authKey, setAuthKey] = createSignal("");

    const run = async () => {
        if (retrying()) return;
        setRetrying(true);
        setRetryError(null);
        const taskId = deps.taskId();
        try {
            // needs_auth：重试必须重带 X-Texlate-Key（server 401 auth_required）
            const res = await api.retry(
                taskId,
                undefined,
                authKey() ? { apiKey: authKey() } : undefined,
            );
            if (res.task_id !== taskId) {
                deps.nav(`#/reader/${res.task_id}`);
                return;
            }
            deps.onAccepted(res.status);
            taskStore.patch(taskId, {
                status: res.status,
                stage: undefined,
                message: undefined,
                error: null,
                progress: 0,
            });
            taskStore.resetLive(taskId);
            setAuthKey(""); // 已用毕即弃，不留组件态
        } catch (e) {
            const ae = e instanceof ApiError ? e : null;
            setRetryError({
                status: ae?.status ?? 0,
                code: ae?.code,
                message: apiErrText(e),
            });
        } finally {
            setRetrying(false);
        }
    };

    return { retrying, retryError, authKey, setAuthKey, run };
}

// 取源段失败才可换链：编译/翻译段故障 html 链救不了，误示好过滥示。
// 新任务而非 retry：kind 是建行定死的列字段，retry 端点不换 kind——
// 换链必须新任务（kind 不同 cache_key 不同，不与原任务撞 dedup）
const HTML_FALLBACK_CODES: ReadonlySet<string> = new Set([
    "arxiv_fetch",
    "no_latex_source",
    "pdf_wrapper",
]);

/** arXiv HTML 通道降级：原任务 options/glossary 全量透传开新任务 */
export function createHtmlFallback(deps: {
    task(): TaskSnapshot | null;
    nav(to: string): void;
}) {
    const [htmlBusy, setHtmlBusy] = createSignal(false);
    const [htmlErr, setHtmlErr] = createSignal("");

    const can = () => {
        const s = deps.task();
        return (
            s?.kind === "arxiv" &&
            !!s.arxiv_id &&
            HTML_FALLBACK_CODES.has(s.error?.code ?? "")
        );
    };

    const run = async () => {
        const s = deps.task();
        if (!s?.arxiv_id || htmlBusy()) return;
        setHtmlBusy(true);
        setHtmlErr("");
        try {
            // M10：原任务 options/glossary 全量透传（glossary/concurrency/
            // guidance/prefer…），只改 source——idempotency_key 摘除（服务端
            // 按它 dedup，带过去会把新任务吞成旧任务命中）。
            const options: Record<string, unknown> = { ...(s.options ?? {}) };
            delete options.idempotency_key;
            options.source = "html";
            const res = await api.translate(s.arxiv_id, {
                model: s.model,
                target_lang: s.target_lang,
                glossary: s.glossary,
                options,
            });
            deps.nav(landingHash(res));
        } catch (e) {
            setHtmlErr(apiErrText(e));
        } finally {
            setHtmlBusy(false);
        }
    };

    return { htmlBusy, htmlErr, can, run };
}
