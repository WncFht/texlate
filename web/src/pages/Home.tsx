// Home —— arXiv 输入 + 文件上传 + 任务列表（活动任务进度走 SSE）。

import { createSignal, onMount, Show } from "solid-js";
import { api, ApiError, type Health } from "../api/client";
import { taskStore } from "../stores/tasks";
import TaskList from "../components/TaskList";
import { t } from "../i18n/zh";

const ARXIV_RE =
    /^(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z]{2})?\/\d{7}(?:v\d+)?)$/i;

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
    let fileInput!: HTMLInputElement;

    onMount(() => {
        taskStore.refresh();
        api.health()
            .then(setHealth)
            .catch(() => setHealth(null));
    });

    const open = (taskId: string) => props.nav(`#/reader/${taskId}`);

    const submit = async () => {
        const id = parseArxivId(arxivId());
        if (!id) {
            setError(t.home.invalidId);
            return;
        }
        setError("");
        setBusy(true);
        try {
            const res = await api.translate(id);
            open(res.task_id);
        } catch (e) {
            // 409：同 cache_key 已有活动任务 → 直接跳过去
            if (e instanceof ApiError && e.status === 409) {
                const m = e.detail.match(/t_[0-9a-f]{16}/);
                if (m) {
                    open(m[0]);
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
            const res = await api.upload(file);
            open(res.task_id);
        } catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        } finally {
            setBusy(false);
        }
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
                        accept=".pdf,.tex,.tar,.gz,.tgz,.zip"
                        onChange={(e) => {
                            const f = e.currentTarget.files?.[0];
                            if (f) void upload(f);
                            e.currentTarget.value = "";
                        }}
                    />
                </form>
                <Show when={error()}>
                    <p class="form-error">{error()}</p>
                </Show>
                <p class="health" classList={{ bad: !health()?.ok }}>
                  <i class="dot" /> {health()?.ok ? t.home.healthOk : t.home.healthBad}
                </p>
            </section>

            <section class="home-tasks">
                <h2>{t.home.tasks}</h2>
                <Show when={taskStore.state.loaded} fallback={<p class="muted">…</p>}>
                    <TaskList tasks={taskStore.state.tasks} onOpen={open} />
                </Show>
            </section>
        </main>
    );
}
