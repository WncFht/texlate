// Settings —— BYOK 表单：key 只写不回显（GET 只回 has_api_key）+ 测试按钮。

import { createSignal, onMount, Show, For } from "solid-js";
import { settingsStore } from "../stores/settings";
import { t } from "../i18n/zh";

export default function Settings() {
    const [apiKey, setApiKey] = createSignal("");
    const [baseUrl, setBaseUrl] = createSignal("");
    const [model, setModel] = createSignal("");
    const [targetLang, setTargetLang] = createSignal("zh-CN");
    const [glossary, setGlossary] = createSignal("");
    const [msg, setMsg] = createSignal("");
    const [testing, setTesting] = createSignal(false);

    onMount(async () => {
        await settingsStore.refresh();
        const s = settingsStore.settings();
        if (s) {
            setBaseUrl(s.base_url ?? "");
            setModel(s.model ?? "");
            setTargetLang(s.target_lang ?? "zh-CN");
            setGlossary(s.glossary ?? "");
        }
    });

    const save = async () => {
        setMsg("");
        const patch: Record<string, unknown> = {
            base_url: baseUrl(),
            model: model(),
            target_lang: targetLang(),
            glossary: glossary(),
        };
        if (apiKey()) patch.api_key = apiKey();
        await settingsStore.save(patch);
        setApiKey("");
        setMsg(t.settings.saved);
    };

    const test = async () => {
        setTesting(true);
        setMsg("");
        try {
            const r = await settingsStore.test();
            setMsg(r.ok ? t.settings.testOk : `${t.settings.testFail}：${r.detail ?? ""}`);
        } catch (e) {
            setMsg(`${t.settings.testFail}：${e instanceof Error ? e.message : String(e)}`);
        } finally {
            setTesting(false);
        }
    };

    const models = () => {
        const all = settingsStore.providers().flatMap((p) => p.models ?? []);
        return [...new Set(all)];
    };

    return (
        <main class="settings">
            <h1>{t.settings.title}</h1>
            <form
                class="settings-form"
                onSubmit={(e) => {
                    e.preventDefault();
                    void save();
                }}
            >
                <label>
                    <span>
                        {t.settings.apiKey}
                        <em class="muted">
                            {settingsStore.settings()?.has_api_key
                                ? t.settings.apiKeySet
                                : t.settings.apiKeyUnset}
                            · {t.settings.apiKeyHint}
                        </em>
                    </span>
                    <input
                        type="password"
                        autocomplete="off"
                        value={apiKey()}
                        onInput={(e) => setApiKey(e.currentTarget.value)}
                    />
                </label>
                <label>
                    <span>{t.settings.baseUrl}</span>
                    <input
                        type="url"
                        placeholder="https://…/v1"
                        value={baseUrl()}
                        onInput={(e) => setBaseUrl(e.currentTarget.value)}
                    />
                </label>
                <label>
                    <span>{t.settings.model}</span>
                    <input
                        list="provider-models"
                        value={model()}
                        onInput={(e) => setModel(e.currentTarget.value)}
                    />
                    <datalist id="provider-models">
                        <For each={models()}>{(m) => <option value={m} />}</For>
                    </datalist>
                </label>
                <label>
                    <span>{t.settings.targetLang}</span>
                    <input value={targetLang()} onInput={(e) => setTargetLang(e.currentTarget.value)} />
                </label>
                <label>
                    <span>
                        {t.settings.glossary}
                        <em class="muted">{t.settings.glossaryHint}</em>
                    </span>
                    <textarea
                        rows={6}
                        value={glossary()}
                        onInput={(e) => setGlossary(e.currentTarget.value)}
                    />
                </label>
                <div class="settings-actions">
                    <button type="submit" class="btn-primary">
                        {t.settings.save}
                    </button>
                    <button type="button" class="btn-ghost" disabled={testing()} onClick={() => void test()}>
                        {testing() ? t.settings.testing : t.settings.test}
                    </button>
                    <Show when={msg()}>
                        <span class="form-msg">{msg()}</span>
                    </Show>
                </div>
            </form>
        </main>
    );
}
