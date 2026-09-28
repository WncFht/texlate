// Home —— 纯入口页：arXiv 输入 + 文件上传 + 选项（任务管理 #/tasks、
// alphaXiv 榜单 #/discover 已拆出；此处只留进行中提示行指路）。
// 结构（reader/chrome/taskActions 同例）：编排逻辑全在 home/ 簇工厂（options/
// search/upload/submit/health/dropzone），渲染片段在同簇组件——
// 本页只留表单态、布局 JSX 与装配。

import { createEffect, createSignal, onCleanup, onMount, Show } from "solid-js";
import { landingHash } from "../api/client";
import ActiveLine from "../home/ActiveLine";
import HealthLine from "../home/HealthLine";
import OptionsForm from "../home/OptionsForm";
import SuggestList from "../home/SuggestList";
import UploadBar from "../home/UploadBar";
import { createHomeDropzone } from "../home/dropzone";
import { createHomeHealth } from "../home/health";
import { createHomeOptions } from "../home/options";
import { createHomeSubmit } from "../home/submit";
import { createHomeSuggest } from "../home/search";
import { createHomeUpload, UPLOAD_EXTS } from "../home/upload";
import { t } from "../i18n";
import { settingsStore } from "../stores/settings";
import { taskStore } from "../stores/tasks";

// 门面再导出：parseArxivId 的本家在 home/search——消费方（tests）从
// pages/Home 单点拿的历史口径保留（stores/tasks.ts 同例）
export { parseArxivId } from "../home/search";

/** accept 属性与 precheckUpload 的 UPLOAD_EXT 校验正则同由 upload.ts 的
    UPLOAD_EXTS 派生（单一事实源）；i18n t.home.formats 展示文案（zh.ts）
    是剩余的手同步点 */
const UPLOAD_ACCEPT = UPLOAD_EXTS.map((e) => `.${e}`).join(",");

export default function Home(props: {
    nav(to: string): void;
    /** #/arxiv/{id} 深链——预填输入框 + 聚焦翻译钮，不自动提交 */
    arxivId?: string;
}) {
    // 表单共享态：busy 是 submit/upload 互斥门，error/idBad 是输入行反馈；
    // authErr 是 401/auth_required 的结构化错误面（内联 key 输入 + 设置链）
    const [arxivId, setArxivId] = createSignal("");
    const [busy, setBusy] = createSignal(false);
    const [error, setError] = createSignal("");
    const [authErr, setAuthErr] = createSignal<string | null>(null);
    // id 解析失败态：aria-invalid 只标格式错，服务端错误不占位
    const [idBad, setIdBad] = createSignal(false);
    let fileInput!: HTMLInputElement;
    // 在飞请求不随卸载取消（幂等键保证服务端只收一单）——但落地后不得再
    // openRes 劫持用户已切走的路由；alive 守一切提交后副作用
    let alive = true;
    onCleanup(() => {
        alive = false;
    });

    const opts = createHomeOptions();
    const sg = createHomeSuggest({
        alive: () => alive,
        // 回填的是合法 id——残留格式错态随回填即消（同 onIdInput 口径），
        // 否则有效输入仍挂 aria-invalid + 旧错文案
        fillId: (v) => {
            setArxivId(v);
            if (idBad()) {
                setIdBad(false);
                setError("");
            }
        },
    });
    const open = (taskId: string) => props.nav(`#/reader/${taskId}`);
    // 202 落地：reader_url 仅产 dual.json 的 kind 下发，缺席（docx/epub）
    // 回 task_id——#/reader/:id 即任务详情面，终态自动落产物下载面板
    const openRes = (res: Parameters<typeof landingHash>[0]) =>
        props.nav(landingHash(res));
    const sub = createHomeSubmit({
        id: arxivId,
        busy,
        setBusy,
        setError,
        setAuthErr,
        markIdBad: () => setIdBad(true),
        alive: () => alive,
        options: opts,
        onResult: openRes,
        onExisting: open,
    });
    const up = createHomeUpload({
        busy,
        setBusy,
        setError,
        alive: () => alive,
        options: opts,
        onResult: openRes,
        onBatchDone: () => void taskStore.refresh(),
    });
    const hh = createHomeHealth();
    const dz = createHomeDropzone({
        busy,
        onBusyDrop: () => setError(t.home.dropBusy),
        onFiles: (files) => void up.uploadBatch(files),
    });

    const onIdInput = (v: string) => {
        setArxivId(v);
        // 格式错提示随编辑即消——用户在改，错误就不该挂着
        if (idBad()) {
            setIdBad(false);
            setError("");
        }
        sg.feed(v);
    };

    onMount(() => {
        void taskStore.ensureFresh();
        if (!settingsStore.loaded()) void settingsStore.refresh();
        hh.ensure();
    });
    onCleanup(() => {
        hh.dispose();
        sg.cancel();
    });

    // #/arxiv/{id} 深链：预填输入框 + 聚焦翻译钮待用户拍板——分享链接落到
    // 别人浏览器不该白烧任务。lastDeep 记已消费的值防同值重聚焦；
    // 清空（离开深链）复位，回到同 id 可再预填
    let submitBtn!: HTMLButtonElement;
    let lastDeep: string | undefined;
    createEffect(() => {
        const a = props.arxivId;
        if (!a) {
            lastDeep = undefined;
            return;
        }
        if (a === lastDeep) return;
        lastDeep = a;
        setArxivId(a);
        submitBtn?.focus();
    });

    return (
        <main
            class="home"
            classList={{ "drop-on": dz.dragOn() }}
            onDragEnter={dz.onDragEnter}
            onDragOver={dz.onDragOver}
            onDragLeave={dz.onDragLeave}
            onDrop={dz.onDrop}
        >
            <section class="hero">
                <h1 class="wordmark">
                    {t.appName} <span class="tagline">{t.tagline}</span>
                </h1>
                <form
                    class="arxiv-form"
                    onSubmit={(e) => {
                        e.preventDefault();
                        void sub.run();
                    }}
                >
                    <div class="arxiv-field">
                        <input
                            class="arxiv-input"
                            placeholder={t.home.arxivPlaceholder}
                            aria-label={t.home.arxivLabel}
                            aria-invalid={idBad()}
                            role="combobox"
                            aria-autocomplete="list"
                            aria-expanded={sg.hits() !== null}
                            aria-controls="ax-suggest"
                            aria-activedescendant={
                                sg.activeHit() >= 0
                                    ? `ax-sug-${sg.activeHit()}`
                                    : undefined
                            }
                            autocapitalize="off"
                            value={arxivId()}
                            onInput={(e) => onIdInput(e.currentTarget.value)}
                            onBlur={sg.close}
                            onKeyDown={sg.onSuggestKey}
                            spellcheck={false}
                        />
                        <SuggestList sg={sg} nav={props.nav} />
                    </div>
                    <button
                        type="submit"
                        class="btn-primary"
                        disabled={busy()}
                        ref={(el) => (submitBtn = el)}
                    >
                        {busy() && !up.uploading()
                            ? t.home.submitting
                            : t.home.translate}
                    </button>
                    <button
                        type="button"
                        class="btn-ghost"
                        disabled={busy()}
                        onClick={() => fileInput?.click()}
                    >
                        {up.uploading() ? t.home.uploading : t.home.upload}
                    </button>
                    <input
                        ref={(el) => (fileInput = el)}
                        type="file"
                        hidden
                        multiple
                        accept={UPLOAD_ACCEPT}
                        onChange={(e) => {
                            const files = [...(e.currentTarget.files ?? [])];
                            if (files.length) void up.uploadBatch(files);
                            e.currentTarget.value = "";
                        }}
                    />
                </form>
                <Show when={error()}>
                    <p class="form-error" role="alert">
                        {error()}
                    </p>
                </Show>
                {/* 401/auth_required：内联 key 输入（写 opts.optKey，下次
                    提交随 byok 透传）+ 设置页链——复用 ResultBody 模式（M1） */}
                <Show when={authErr()}>
                    {(msg) => (
                        <div class="form-error" role="alert">
                            <p>{msg()}</p>
                            <input
                                type="password"
                                class="auth-key-input"
                                placeholder={t.reader.authKeyPlaceholder}
                                aria-label={t.reader.authKeyPlaceholder}
                                value={opts.optKey()}
                                onInput={(e) =>
                                    opts.setOptKey(e.currentTarget.value)
                                }
                            />
                            <a href="#/settings">{t.home.goSettings}</a>
                        </div>
                    )}
                </Show>
                {/* 服务端无 key 且用户未填 BYOK 时的软提示（M1）——不禁钮：
                    keyless 通道仍可能直过，auth 失败才落上面的富错误面 */}
                <Show
                    when={
                        settingsStore.settings()?.has_api_key === false &&
                        !opts.optKey().trim() &&
                        !authErr()
                    }
                >
                    <p class="muted">
                        <a href="#/settings">{t.home.noKeyHint}</a>
                    </p>
                </Show>
                <UploadBar uploading={up.uploading} upPct={up.upPct} />
                <p class="muted upload-formats">
                    {t.home.formats}
                    <span class="drop-hint">{t.home.dropHint}</span>
                </p>
                <OptionsForm opts={opts} />
                <HealthLine hh={hh} />
            </section>
            <ActiveLine />
        </main>
    );
}
