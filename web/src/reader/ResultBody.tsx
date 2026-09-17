// ResultBody —— 终态面板主体：状态文案 + 任务错误 + 重试错误 + 警告 +
// 统计条 + 重试/换链动作行（needs_auth 附内联 Key 输入）。横幅与整页面板共用。
// 纯展示件：状态与回调全走 props；分享块以 share 槽注入（自门控）。

import { For, Show, type JSX } from "solid-js";
import type { TaskSnapshot } from "../api/client";
import type { ResultStats } from "../taskStats";
import { fmtElapsed } from "./timefmt";
import { t } from "../i18n/zh";

export interface RetryError {
    status: number;
    code?: string;
    message: string;
}

interface Props {
    /** 终态非 done 的状态键（fault/partial/cancelled/interrupted/needs_auth） */
    st: string;
    task: TaskSnapshot | null;
    retryError: RetryError | null;
    retrying: boolean;
    /** needs_auth 面板的内联 API Key（重试随 X-Texlate-Key 透传） */
    authKey: string;
    onAuthKey(v: string): void;
    onRetry(): void;
    /** F 桶取源失败 → arXiv HTML 链换链入口（canTryHtml 门控） */
    canTryHtml: boolean;
    htmlBusy: boolean;
    htmlErr: string;
    onTryHtml(): void;
    /** mergeResultStats 合成结果；null 时 stat-strip 整段缺席 */
    stats: ResultStats | null;
    /** partial/fault 的段落棋盘格（ProgressGrid 实例，自门控有数据才给） */
    grid?: JSX.Element;
    /** 分享块槽（ShareBlock 实例，自门控 canShare） */
    share?: JSX.Element;
}

const RESULT_TEXT: Record<string, string> = {
    fault: t.reader.resultFault,
    partial: t.reader.resultPartial,
    cancelled: t.reader.resultCancelled,
    interrupted: t.reader.resultInterrupted,
    needs_auth: t.reader.resultNeedsAuth,
};

export default function ResultBody(props: Props) {
    return (
        <>
            <h2 class="rp-status">{RESULT_TEXT[props.st] ?? t.status[props.st] ?? props.st}</h2>
            <Show when={props.task?.error}>
                {(e) => (
                    <p class="form-error">
                        [{e().code}] {e().message}
                        {e().retryable ? t.reader.retryable : ""}
                    </p>
                )}
            </Show>
            <Show when={props.retryError}>
                {(e) => (
                    <p class="form-error" role="alert">
                        [{e().code ?? "retry"}] {e().message}
                        <Show when={e().status === 401 || e().code === "auth_required"}>
                            {" "}
                            {t.reader.retryHintAuth}
                        </Show>
                    </p>
                )}
            </Show>
            <Show when={(props.task?.warnings?.length ?? 0) > 0}>
                <ul class="warn-list">
                    <For each={props.task!.warnings}>{(w) => <li>{w}</li>}</For>
                </ul>
            </Show>
            <Show when={props.stats}>
                {(s) => (
                    <dl class="stat-strip">
                        <Show when={s().tokens != null}>
                            <div class="stat">
                                <dt>{t.reader.statsTokens}</dt>
                                <dd class="stat-num">{s().tokens}</dd>
                            </div>
                        </Show>
                        <Show when={s().prompt != null}>
                            <div class="stat">
                                <dt>{t.reader.statsPrompt}</dt>
                                <dd class="stat-num">{s().prompt}</dd>
                            </div>
                        </Show>
                        <Show when={s().completion != null}>
                            <div class="stat">
                                <dt>{t.reader.statsCompletion}</dt>
                                <dd class="stat-num">{s().completion}</dd>
                            </div>
                        </Show>
                        <Show when={s().calls != null}>
                            <div class="stat">
                                <dt>{t.reader.statsCalls}</dt>
                                <dd class="stat-num">{s().calls}</dd>
                            </div>
                        </Show>
                        <Show when={s().latency != null}>
                            <div class="stat">
                                <dt>{t.reader.statsLatency}</dt>
                                <dd class="stat-num">{fmtElapsed(s().latency ?? 0)}</dd>
                            </div>
                        </Show>
                        <Show when={s().seconds != null}>
                            <div class="stat">
                                <dt>{t.reader.statsSeconds}</dt>
                                <dd class="stat-num">{fmtElapsed(s().seconds ?? 0)}</dd>
                            </div>
                        </Show>
                        <Show when={s().failed != null}>
                            <div class="stat">
                                <dt>{t.reader.statsFailed}</dt>
                                <dd class="stat-num">{s().failed}</dd>
                            </div>
                        </Show>
                    </dl>
                )}
            </Show>
            {props.grid}
            <div class="rp-actions">
                <Show when={props.st === "needs_auth"}>
                    <input
                        type="password"
                        class="auth-key-input"
                        placeholder={t.reader.authKeyPlaceholder}
                        aria-label={t.reader.authKeyPlaceholder}
                        value={props.authKey}
                        disabled={props.retrying}
                        onInput={(e) => props.onAuthKey(e.currentTarget.value)}
                    />
                </Show>
                <button
                    type="button"
                    class="tb-btn"
                    disabled={props.retrying}
                    onClick={() => props.onRetry()}
                >
                    {props.retrying ? t.reader.retrying : t.reader.retry}
                </button>
                <Show when={props.canTryHtml}>
                    <button
                        type="button"
                        class="tb-btn"
                        disabled={props.htmlBusy}
                        title={t.reader.tryHtmlHint}
                        onClick={() => props.onTryHtml()}
                    >
                        {props.htmlBusy ? t.reader.retrying : t.reader.tryHtml}
                    </button>
                </Show>
                <Show when={props.htmlErr}>
                    {(m) => (
                        <p class="form-error" role="alert">
                            {m()}
                        </p>
                    )}
                </Show>
                <Show when={props.st === "needs_auth"}>
                    <span class="muted">{t.reader.retryHintAuth}</span>
                </Show>
                {props.share}
            </div>
        </>
    );
}
