// Settings —— BYOK 表单：key 只写不回显（GET 只回 has_api_key）+ 测试按钮。

import { createSignal, onCleanup, onMount, Show, For } from "solid-js";
import { settingsStore } from "../stores/settings";
import { t } from "../i18n/zh";

export default function Settings() {
    const [apiKey, setApiKey] = createSignal("");
    const [baseUrl, setBaseUrl] = createSignal("");
    const [model, setModel] = createSignal("");
    const [targetLang, setTargetLang] = createSignal("zh-CN");
    const [glossary, setGlossary] = createSignal("");
    const [engine, setEngine] = createSignal("auto");
    const [concurrency, setConcurrency] = createSignal("3");
    const [guidance, setGuidance] = createSignal("on");
    const [msg, setMsg] = createSignal("");
    const [saving, setSaving] = createSignal(false);
    const [testing, setTesting] = createSignal(false);
    const [clearing, setClearing] = createSignal(false);
    let msgTimer = 0;

    onCleanup(() => window.clearTimeout(msgTimer));

    onMount(async () => {
        try {
            await settingsStore.refresh();
            const s = settingsStore.settings();
            if (s) {
                setBaseUrl(s.base_url ?? "");
                setModel(s.model ?? "");
                setTargetLang(s.target_lang ?? "zh-CN");
                setGlossary(s.glossary ?? "");
                setEngine(s.engine ?? "auto");
                setConcurrency(String(s.concurrency ?? 3));
                setGuidance(s.context_guidance === false ? "off" : "on");
            }
        } catch (e) {
            // 加载失败表单仍可用，仅提示
            setMsg(`${t.settings.loadFailed}：${e instanceof Error ? e.message : String(e)}`);
        }
    });

    /** 成功提示 3s 后自动清 */
    const flash = (text: string) => {
        setMsg(text);
        window.clearTimeout(msgTimer);
        msgTimer = window.setTimeout(() => setMsg(""), 3000);
    };

    const save = async () => {
        // Enter 隐式提交不走 disabled 按钮——saving 门防重入
        if (saving()) return;
        setSaving(true);
        setMsg("");
        const patch: Record<string, unknown> = {
            base_url: baseUrl().trim(),
            model: model().trim(),
            target_lang: targetLang().trim(),
            glossary: glossary(),
            engine: engine(),
            context_guidance: guidance() === "on",
        };
        // 空串不送——server 侧 int("") 直接 400；夹取口径同 Home 任务选项
        const conc = Number(concurrency());
        if (Number.isFinite(conc) && conc >= 1) {
            patch.concurrency = Math.max(1, Math.min(16, Math.floor(conc)));
        }
        if (apiKey().trim()) patch.api_key = apiKey().trim();
        try {
            await settingsStore.save(patch);
            setApiKey("");
            flash(t.settings.saved);
        } catch (e) {
            setMsg(`${t.settings.saveFailed}：${e instanceof Error ? e.message : String(e)}`);
        } finally {
            setSaving(false);
        }
    };

    /** 清除服务端已存 key：PUT {clear_api_key:true} → store 响应 has_api_key=false */
    const clearKey = async () => {
        if (clearing()) return;
        setClearing(true);
        setMsg("");
        try {
            await settingsStore.save({ clear_api_key: true });
            setApiKey("");
            flash(t.settings.keyCleared);
        } catch (e) {
            setMsg(`${t.settings.clearFailed}：${e instanceof Error ? e.message : String(e)}`);
        } finally {
            setClearing(false);
        }
    };

    const test = async () => {
        setTesting(true);
        setMsg("");
        try {
            // 测当前表单值而非已存配置
            const r = await settingsStore.test({
                base_url: baseUrl(),
                model: model(),
                ...(apiKey() ? { api_key: apiKey() } : {}),
            });
            setMsg(r.ok ? t.settings.testOk : `${t.settings.testFail}：${r.detail ?? ""}`);
        } catch (e) {
            setMsg(`${t.settings.testFail}：${e instanceof Error ? e.message : String(e)}`);
        } finally {
            setTesting(false);
        }
    };

    const models = () => {
        // provider preset 可能是 models[] 或单数 model
        const all = settingsStore
            .providers()
            .flatMap((p) => p.models ?? (typeof p.model === "string" ? [p.model] : []));
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
                <div class="key-row">
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
                    {/* 无存 key（needs_auth 语义）时禁用——无可清对象 */}
                    <button
                        type="button"
                        class="btn-ghost"
                        disabled={!settingsStore.settings()?.has_api_key || clearing()}
                        onClick={() => void clearKey()}
                    >
                        {clearing() ? t.settings.clearing : t.settings.clearKey}
                    </button>
                </div>
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
                    <span>{t.settings.engine}</span>
                    <select value={engine()} onChange={(e) => setEngine(e.currentTarget.value)}>
                        <option value="auto">{t.home.engineAuto}</option>
                        <option value="xelatex">xelatex</option>
                        <option value="tectonic">tectonic</option>
                    </select>
                </label>
                <label>
                    <span>
                        {t.settings.concurrency}
                        <em class="muted">{t.settings.concurrencyHint}</em>
                    </span>
                    <input
                        type="number"
                        min={1}
                        max={16}
                        value={concurrency()}
                        onInput={(e) => setConcurrency(e.currentTarget.value)}
                    />
                </label>
                <label>
                    <span>
                        {t.settings.contextGuidance}
                        <em class="muted">{t.settings.contextGuidanceHint}</em>
                    </span>
                    <select value={guidance()} onChange={(e) => setGuidance(e.currentTarget.value)}>
                        <option value="on">{t.home.optOn}</option>
                        <option value="off">{t.home.optOff}</option>
                    </select>
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
                    <button type="submit" class="btn-primary" disabled={saving()}>
                        {saving() ? t.settings.saving : t.settings.save}
                    </button>
                    <button type="button" class="btn-ghost" disabled={testing()} onClick={() => void test()}>
                        {testing() ? t.settings.testing : t.settings.test}
                    </button>
                    <Show when={msg()}>
                        <span class="form-msg" role="status">
                            {msg()}
                        </span>
                    </Show>
                </div>
            </form>
        </main>
    );
}
