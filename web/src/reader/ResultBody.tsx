// ResultBody —— 终态面板主体：状态文案 + 任务错误 + 重试错误 + 警告 +
// 统计条 + 重试/换链动作行（needs_auth 附内联 Key 输入）。横幅与整页面板共用。
// 纯展示件：状态与回调全走 props；分享块以 share 槽注入（自门控）。

import { For, Show, type JSX } from "solid-js";
import type { TaskSnapshot } from "../api/client";
import type { ResultStats } from "../taskStats";
import { fmtElapsed } from "./timefmt";
import { t } from "../i18n";

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

// 折叠态细条复用同一份文案（Reader 横幅槽）
export const RESULT_TEXT: Record<string, string> = {
    fault: t.reader.resultFault,
    partial: t.reader.resultPartial,
    cancelled: t.reader.resultCancelled,
    interrupted: t.reader.resultInterrupted,
    needs_auth: t.reader.resultNeedsAuth,
    // done 仅作「完成但带 warnings」横幅态由 Reader 闸注入——非 done
    // 常态不渲染本件
    done: t.reader.resultDone,
};

/** done.stats.stage_seconds 短键 → 阶段名（t.status 键） */
const STAGE_LABEL: Record<string, string> = {
    fetch: t.status.fetching,
    parse: t.status.parsing,
    translate: t.status.translating,
    compile: t.status.compiling,
};

export default function ResultBody(props: Props) {
    // warnings 是 "[code] message" 串——mock_translator 命中即「keyless
    // 走了 mock 翻译」信号，done 态给重试 + key 输入（M1 止血）
    const mockWarn = () =>
        (props.task?.warnings ?? []).some((w) => w.includes("mock_translator"));
    return (
        <>
            <h2 class="rp-status">
                {RESULT_TEXT[props.st] ?? t.status[props.st] ?? props.st}
            </h2>
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
                        <Show
                            when={
                                e().status === 401 ||
                                e().code === "auth_required"
                            }
                        >
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
                                <dd class="stat-num">
                                    {fmtElapsed(s().latency ?? 0)}
                                </dd>
                            </div>
                        </Show>
                        <Show when={s().seconds != null}>
                            <div class="stat">
                                <dt>{t.reader.statsSeconds}</dt>
                                <dd class="stat-num">
                                    {fmtElapsed(s().seconds ?? 0)}
                                </dd>
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
            {/* done.stats 细分件：分阶段耗时 / fixloop 判定 / L2 摘要——
                各块独立缺席（老任务/未跑段的 payload 无此键） */}
            <Show when={props.stats?.stageSeconds}>
                {(ss) => (
                    <p class="stage-secs muted">
                        <span class="ss-label">{t.reader.statsStage}</span>
                        <For each={Object.entries(ss())}>
                            {([k, v]) => (
                                <span class="ss-item">
                                    {STAGE_LABEL[k] ?? k} {fmtElapsed(v)}
                                </span>
                            )}
                        </For>
                    </p>
                )}
            </Show>
            <Show when={props.stats?.fixloop}>
                {(v) => (
                    <p class="stage-secs muted">
                        <span class="ss-label">{t.reader.statsFixloop}</span>
                        <span class="fx-badge">{v()}</span>
                    </p>
                )}
            </Show>
            <Show when={props.stats?.l2}>
                {(l) => (
                    <p class="stage-secs muted">
                        <span class="ss-label">{t.reader.statsL2}</span>
                        <Show when={l().enabled === false}>
                            <span class="ss-item">{t.reader.statsL2Off}</span>
                        </Show>
                        <Show when={l().enabled !== false}>
                            <span class="ss-item">
                                {t.progress.l2Errors} {l().errors ?? 0}
                            </span>
                            <span class="ss-item">
                                {t.progress.l2Retranslated}{" "}
                                {l().retranslated ?? 0}
                            </span>
                            <span class="ss-item">
                                {t.progress.l2Fallback} {l().fallback ?? 0}
                            </span>
                        </Show>
                    </p>
                )}
            </Show>
            {props.grid}
            <div class="rp-actions">
                {/* needs_auth 恒给 key 输入；done+mock 也给——keyless mock
                    落地产物要重译成真翻译（M1） */}
                <Show
                    when={
                        props.st === "needs_auth" ||
                        (props.st === "done" && mockWarn())
                    }
                >
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
                {/* done 常态不渲染重试（done 无 warnings 时本件根本不挂）；
                    done+mock 恢复重试入口 */}
                <Show when={props.st !== "done" || mockWarn()}>
                    <button
                        type="button"
                        class="tb-btn"
                        disabled={props.retrying}
                        onClick={() => props.onRetry()}
                    >
                        {props.retrying ? t.reader.retrying : t.reader.retry}
                    </button>
                </Show>
                <Show when={props.st === "done" && mockWarn()}>
                    <span class="muted">{t.reader.mockNotice}</span>
                </Show>
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
                {/* retryError 已内联 retryHintAuth（L72-75）时不再重复——
                    仅首访/非 auth 错误时补操作提示 */}
                <Show
                    when={
                        props.st === "needs_auth" &&
                        !(
                            props.retryError?.status === 401 ||
                            props.retryError?.code === "auth_required"
                        )
                    }
                >
                    <span class="muted">{t.reader.retryHintAuth}</span>
                </Show>
                {props.share}
            </div>
        </>
    );
}
