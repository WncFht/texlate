// Home —— arXiv 输入 + 文件上传 + 任务列表（活动任务进度走 SSE）。

import { createSignal, For, onMount, Show } from "solid-js";
import {
    api,
    ApiError,
    landingHash,
    type Health,
    type TranslateOptions,
} from "../api/client";
import { taskStore } from "../stores/tasks";
import { settingsStore } from "../stores/settings";
import TaskList from "../components/TaskList";
import { t } from "../i18n/zh";

const ARXIV_RE =
    /^(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?\/\d{7}(?:v\d+)?)$/i;

const TARGET_LANGS = ["zh-CN", "zh-TW", "en"];
const ENGINES = ["auto", "xelatex", "tectonic"];

function parseArxivId(raw: string): string | null {
    const s = raw.trim();
    if (ARXIV_RE.test(s)) return s;
    const m = s.match(/arxiv\.org\/(?:abs|pdf)\/([^\s?#/]+?)(?:\.pdf)?(?:[?#].*)?$/i);
    return m && ARXIV_RE.test(m[1]) ? m[1] : null;
}

export default function Home(props: { nav(to: string): void }) {
    const [arxivId, setArxivId] = createSignal("");
    const [busy, setBusy] = createSignal(false);
    const [error, setError] = createSignal("");
    const [health, setHealth] = createSignal<Health | null>(null);
    const [healthPending, setHealthPending] = createSignal(true);
    // 任务选项（默认收起；空值 = 跟随 settings 默认）
    const [optModel, setOptModel] = createSignal("");
    const [optLang, setOptLang] = createSignal("");
    const [optGlossary, setOptGlossary] = createSignal("");
    const [optGuidance, setOptGuidance] = createSignal("");
    const [optConcurrency, setOptConcurrency] = createSignal("");
    const [optEngine, setOptEngine] = createSignal("");
    const [optPrefer, setOptPrefer] = createSignal("");
    const [optShare, setOptShare] = createSignal("");
    const [optMain, setOptMain] = createSignal("");
    // per-request BYOK：仅存组件 state，提交成功即清，不落 settings
    const [optKey, setOptKey] = createSignal("");
    let fileInput!: HTMLInputElement;

    onMount(() => {
        void taskStore.refresh();
        if (!settingsStore.loaded()) void settingsStore.refresh();
        api.health()
            .then(setHealth)
            .catch(() => setHealth(null))
            .finally(() => setHealthPending(false));
    });

    /** health.compilers 可用数/总数（值 truthy 视为可用） */
    const compilersStat = () => {
        const c = health()?.compilers;
        if (!c) return "";
        const keys = Object.keys(c);
        return `${keys.filter((k) => c[k]).length}/${keys.length}`;
    };

    const open = (taskId: string) => props.nav(`#/reader/${taskId}`);
    // 202 落地：reader_url 仅产 dual.json 的 kind 下发，缺席（docx/epub）
    // 回 task_id——#/reader/:id 即任务详情面，终态自动落产物下载面板
    const openRes = (res: Parameters<typeof landingHash>[0]) => props.nav(landingHash(res));

    /** 非空字段收成 TranslateOptions；全空返回 undefined（不附带 body 字段） */
    const collectOptions = (): TranslateOptions | undefined => {
        const o: TranslateOptions = {};
        const opts: NonNullable<TranslateOptions["options"]> = {};
        if (optModel().trim()) o.model = optModel().trim();
        if (optLang()) o.target_lang = optLang();
        if (optGlossary().trim()) o.glossary = optGlossary().trim();
        if (optGuidance()) opts.context_guidance = optGuidance() === "on";
        const conc = Number(optConcurrency());
        if (optConcurrency() && Number.isFinite(conc)) {
            opts.concurrency = Math.max(1, Math.min(16, Math.floor(conc)));
        }
        if (optEngine()) opts.engine = optEngine();
        if (optShare()) opts.share_pack = optShare() === "on";
        const pref = optPrefer();
        if (pref === "reuse" || pref === "fresh") opts.prefer = pref;
        if (Object.keys(opts).length) o.options = opts;
        return o.model || o.target_lang || o.glossary || o.options ? o : undefined;
    };

    /** 临时 key → X-Texlate-Key 头（空 → undefined，纯 per-request 透传） */
    const byok = () => (optKey().trim() ? { apiKey: optKey().trim() } : undefined);

    const submit = async () => {
        const id = parseArxivId(arxivId());
        if (!id) {
            setError(t.home.invalidId);
            return;
        }
        setError("");
        setBusy(true);
        try {
            const res = await api.translate(id, collectOptions(), byok());
            setOptKey("");
            openRes(res);
        } catch (e) {
            // 409：同 cache_key 已有活动任务 → 直接跳过去
            if (e instanceof ApiError && e.status === 409) {
                const existing = e.taskId ?? e.detail.match(/t_[0-9a-f]{16}/)?.[0];
                if (existing) {
                    open(existing);
                    return;
                }
            }
            setError(e instanceof Error ? e.message : String(e));
        } finally {
            setBusy(false);
        }
    };

    const upload = async (file: File) => {
        setError("");
        setBusy(true);
        try {
            // upload 的 options 走 multipart JSON 字段；prefer 仅对 arxiv 缓存有意义
            // （server 上传路恒 prefer=fresh），glossary 在 options 内传递
            const o = collectOptions();
            const upOpts: Record<string, unknown> = { ...o?.options };
            delete upOpts.prefer;
            if (o?.glossary) upOpts.glossary = o.glossary;
            // .share.zip 是社区缓存包——走 share/import（包内 manifest 自描述）
            if (file.name.toLowerCase().endsWith(".share.zip")) {
                const res = await api.shareImport(
                    file,
                    Object.keys(upOpts).length ? upOpts : undefined,
                    byok(),
                );
                setOptKey("");
                openRes(res);
                return;
            }
            const main = optMain().trim();
            const fields =
                o || main
                    ? {
                          model: o?.model,
                          target_lang: o?.target_lang,
                          main: main || undefined,
                          options: upOpts,
                      }
                    : undefined;
            const res = await api.upload(file, fields, byok());
            setOptKey("");
            openRes(res);
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        } finally {
            setBusy(false);
        }
    };

    /** settings 默认值做占位文案（未加载时给通用占位） */
    const def = (k: "model" | "target_lang" | "engine" | "concurrency") => {
        const v = settingsStore.settings()?.[k];
        return v === undefined || v === "" ? "…" : String(v);
    };

    return (
        <main class="home">
            <section class="hero">
                <h1 class="wordmark">
                    {t.appName} <span class="tagline">{t.tagline}</span>
                </h1>
                <form
                    class="arxiv-form"
                    onSubmit={(e) => {
                        e.preventDefault();
                        void submit();
                    }}
                >
                    <input
                        class="arxiv-input"
                        placeholder={t.home.arxivPlaceholder}
                        value={arxivId()}
                        onInput={(e) => setArxivId(e.currentTarget.value)}
                        spellcheck={false}
                    />
                    <button type="submit" class="btn-primary" disabled={busy()}>
                        {t.home.translate}
                    </button>
                    <button
                        type="button"
                        class="btn-ghost"
                        disabled={busy()}
                        onClick={() => fileInput?.click()}
                    >
                        {busy() ? t.home.uploading : t.home.upload}
                    </button>
                    <input
                        ref={(el) => (fileInput = el)}
                        type="file"
                        hidden
                        accept=".pdf,.tex,.tar,.gz,.tgz,.zip,.docx,.epub"
                        onChange={(e) => {
                            const f = e.currentTarget.files?.[0];
                            if (f) void upload(f);
                            e.currentTarget.value = "";
                        }}
                    />
                </form>
                <p class="muted upload-formats">{t.home.formats}</p>
                <details class="task-opts">
                    <summary>{t.home.options}</summary>
                    <div class="opts-grid">
                        <label>
                            <span>{t.home.optModel}</span>
                            <input
                                value={optModel()}
                                placeholder={def("model")}
                                onInput={(e) => setOptModel(e.currentTarget.value)}
                            />
                        </label>
                        <label>
                            <span>{t.home.optLang}</span>
                            <select
                                value={optLang()}
                                onChange={(e) => setOptLang(e.currentTarget.value)}
                            >
                                <option value="">
                                    {t.home.optDefault}（{def("target_lang")}）
                                </option>
                                <For each={TARGET_LANGS}>
                                    {(l) => <option value={l}>{l}</option>}
                                </For>
                            </select>
                        </label>
                        <label>
                            <span>{t.home.optEngine}</span>
                            <select
                                value={optEngine()}
                                onChange={(e) => setOptEngine(e.currentTarget.value)}
                            >
                                <option value="">
                                    {t.home.optDefault}（{def("engine")}）
                                </option>
                                <For each={ENGINES}>
                                    {(en) => (
                                        <option value={en}>
                                            {en === "auto" ? t.home.engineAuto : en}
                                        </option>
                                    )}
                                </For>
                            </select>
                        </label>
                        <label>
                            <span>{t.home.optConcurrency}</span>
                            <input
                                type="number"
                                min={1}
                                max={16}
                                value={optConcurrency()}
                                placeholder={def("concurrency")}
                                onInput={(e) => setOptConcurrency(e.currentTarget.value)}
                            />
                        </label>
                        <label>
                            <span>{t.home.optGuidance}</span>
                            <select
                                value={optGuidance()}
                                onChange={(e) => setOptGuidance(e.currentTarget.value)}
                            >
                                <option value="">{t.home.optDefault}</option>
                                <option value="on">{t.home.optOn}</option>
                                <option value="off">{t.home.optOff}</option>
                            </select>
                        </label>
                        <label>
                            <span>{t.home.optPrefer}</span>
                            <select
                                value={optPrefer()}
                                onChange={(e) => setOptPrefer(e.currentTarget.value)}
                            >
                                <option value="">{t.home.optDefault}</option>
                                <option value="reuse">{t.home.preferReuse}</option>
                                <option value="fresh">{t.home.preferFresh}</option>
                            </select>
                        </label>
                        <label>
                            <span>
                                {t.home.optShare}
                                <em class="muted">{t.home.optShareHint}</em>
                            </span>
                            <select
                                value={optShare()}
                                onChange={(e) => setOptShare(e.currentTarget.value)}
                            >
                                <option value="">{t.home.optDefault}</option>
                                <option value="on">{t.home.optOn}</option>
                                <option value="off">{t.home.optOff}</option>
                            </select>
                        </label>
                        <label>
                            <span>
                                {t.home.optMain}
                                <em class="muted">{t.home.optMainHint}</em>
                            </span>
                            <input
                                value={optMain()}
                                placeholder="main.tex"
                                onInput={(e) => setOptMain(e.currentTarget.value)}
                            />
                        </label>
                        <label class="span2">
                            <span>
                                {t.home.optGlossary}
                                <em class="muted">{t.home.optGlossaryHint}</em>
                            </span>
                            <textarea
                                rows={3}
                                value={optGlossary()}
                                onInput={(e) => setOptGlossary(e.currentTarget.value)}
                            />
                        </label>
                        <label class="span2">
                            <span>
                                {t.home.optKey}
                                <em class="muted">{t.home.optKeyHint}</em>
                            </span>
                            <input
                                type="password"
                                autocomplete="off"
                                value={optKey()}
                                onInput={(e) => setOptKey(e.currentTarget.value)}
                            />
                        </label>
                    </div>
                </details>
                <Show when={error()}>
                    <p class="form-error">{error()}</p>
                </Show>
                <p
                    class="health"
                    classList={{ checking: healthPending(), bad: !healthPending() && !health()?.ok }}
                >
                    <i class="dot" />
                    {healthPending()
                        ? t.home.healthChecking
                        : health()?.ok
                          ? t.home.healthOk
                          : t.home.healthBad}
                    <Show when={!healthPending() && health()?.ok}>
                        <span class="muted">
                            v{health()!.version ?? "?"} · {t.home.compilers} {compilersStat()}
                        </span>
                    </Show>
                </p>
            </section>

            <section class="home-tasks">
                <h2>{t.home.tasks}</h2>
                <Show when={taskStore.state.loadError}>
                    {(err) => (
                        <p class="form-error">
                            {t.home.loadFailed}：{err()}{" "}
                            <button
                                type="button"
                                class="btn-ghost"
                                onClick={() => void taskStore.refresh()}
                            >
                                {t.home.retry}
                            </button>
                        </p>
                    )}
                </Show>
                <Show when={taskStore.state.loaded} fallback={<p class="muted">…</p>}>
                    <TaskList tasks={taskStore.state.tasks} onOpen={open} />
                </Show>
            </section>
        </main>
    );
}
