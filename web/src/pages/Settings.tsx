// Settings —— BYOK 表单：key 只写不回显（GET 只回 has_api_key）+ 测试按钮。

import { createSignal, onCleanup, onMount, Show, For } from "solid-js";
import { settingsStore } from "../stores/settings";
import Segmented from "../components/Segmented";
import { errText, type Provider } from "../api/client";
import {
    API_DIALECTS,
    ENGINES,
    segOptsWithCurrent,
    TARGET_LANGS,
} from "../options";
import { t, langChoice, setLang, type LangChoice } from "../i18n";
import { PAPER_LABEL, PAPER_THEME_IDS } from "../reader/pdf/pdfTheme";

/** 并发夹取 1..16——与 Home 任务选项（home/options.ts）同一口径 */
const clampConcurrency = (v: number) =>
    Math.max(1, Math.min(16, Math.floor(v)));

/** 预设的模型清单：models[] 或单数 model；自定义/无模型预设 → 空表走自由输入 */
const providerModels = (p?: Provider): string[] =>
    p?.models ?? (p?.model ? [p.model] : []);

export default function Settings() {
    const [apiKey, setApiKey] = createSignal("");
    const [baseUrl, setBaseUrl] = createSignal("");
    const [model, setModel] = createSignal("");
    const [dialect, setDialect] = createSignal("auto");
    const [targetLang, setTargetLang] = createSignal("zh-CN");
    const [glossary, setGlossary] = createSignal("");
    const [engine, setEngine] = createSignal("auto");
    const [concurrency, setConcurrency] = createSignal("3");
    const [guidance, setGuidance] = createSignal("on");
    const [msg, setMsg] = createSignal("");
    const [msgErr, setMsgErr] = createSignal(false);
    const [saving, setSaving] = createSignal(false);
    const [testing, setTesting] = createSignal(false);
    const [clearing, setClearing] = createSignal(false);
    // 服务商预设（U14）："" = 自定义；选定即回填 base_url + 首选 model
    const [provider, setProvider] = createSignal("");
    // store.refresh 内部吞错——settings() 仍 null 即加载失败（与"还没配置"区分）
    const [loadErr, setLoadErr] = createSignal(false);
    // 任务完成通知权限态（localStorage 无关——浏览器 Notification 权限；
    // 非 default 态按钮即禁，「开启」只在用户手势里 requestPermission）
    const [notifyPerm, setNotifyPerm] = createSignal<string>(
        typeof Notification === "undefined"
            ? "unsupported"
            : Notification.permission,
    );
    let msgTimer = 0;

    onCleanup(() => window.clearTimeout(msgTimer));

    const load = async () => {
        setLoadErr(false);
        await settingsStore.refresh();
        const s = settingsStore.settings();
        if (!s) {
            setLoadErr(true);
            return;
        }
        setBaseUrl(s.base_url ?? "");
        setModel(s.model ?? "");
        setDialect(s.dialect ?? "auto");
        // 回填后反查预设：base_url 命中即归位，否则落「自定义」；
        // s.base_url 缺席时不查——免得撞上同样缺 base_url 的预设误归位
        setProvider(
            s.base_url
                ? (settingsStore
                      .providers()
                      .find((p) => p.base_url === s.base_url)?.id ?? "")
                : "",
        );
        setTargetLang(s.target_lang ?? "zh-CN");
        setGlossary(s.glossary ?? "");
        setEngine(s.engine ?? "auto");
        setConcurrency(String(s.concurrency ?? 3));
        setGuidance(s.context_guidance === false ? "off" : "on");
    };
    onMount(() => void load());

    /** 成功提示 3s 后自动清 */
    const flash = (text: string) => {
        setMsgErr(false);
        setMsg(text);
        window.clearTimeout(msgTimer);
        msgTimer = window.setTimeout(() => setMsg(""), 3000);
    };

    /** 失败提示常驻到下次操作——错误不该自己溜走 */
    const fail = (text: string) => {
        window.clearTimeout(msgTimer);
        setMsgErr(true);
        setMsg(text);
    };

    const save = async () => {
        // Enter 隐式提交不走 disabled 按钮——saving 门防重入
        if (saving()) return;
        setSaving(true);
        setMsg("");
        const patch: Record<string, unknown> = {
            base_url: baseUrl().trim(),
            model: model().trim(),
            dialect: dialect(),
            target_lang: targetLang().trim(),
            glossary: glossary(),
            engine: engine(),
            context_guidance: guidance() === "on",
        };
        // 空串不送——server 侧 int("") 直接 400；夹取口径同 Home 任务选项
        const conc = Number(concurrency());
        if (Number.isFinite(conc) && conc >= 1) {
            patch.concurrency = clampConcurrency(conc);
        }
        if (apiKey().trim()) patch.api_key = apiKey().trim();
        try {
            await settingsStore.save(patch);
            setApiKey("");
            flash(t.settings.saved);
        } catch (e) {
            fail(`${t.settings.saveFailed}：${errText(e)}`);
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
            fail(`${t.settings.clearFailed}：${errText(e)}`);
        } finally {
            setClearing(false);
        }
    };

    /** 通知权限请求——须落在点击手势内；旧实现不返 Promise 的走 catch 兜底 */
    const requestNotify = async () => {
        if (typeof Notification === "undefined") {
            setNotifyPerm("unsupported");
            return;
        }
        try {
            setNotifyPerm(await Notification.requestPermission());
        } catch {
            setNotifyPerm(Notification.permission);
        }
    };

    const test = async () => {
        setTesting(true);
        setMsg("");
        try {
            // 测当前表单值而非已存配置——trim 归一化口径与 save() 一致
            const r = await settingsStore.test({
                base_url: baseUrl().trim(),
                model: model().trim(),
                dialect: dialect(),
                ...(apiKey().trim() ? { api_key: apiKey().trim() } : {}),
            });
            if (r.ok) flash(t.settings.testOk);
            else fail(`${t.settings.testFail}：${r.detail ?? ""}`);
        } catch (e) {
            fail(`${t.settings.testFail}：${errText(e)}`);
        } finally {
            setTesting(false);
        }
    };

    /** 当前选中预设（undefined = 自定义） */
    const curProvider = () =>
        settingsStore.providers().find((p) => p.id === provider());

    /** 当前预设的模型清单——空表时走自由输入框 */
    const provModels = () => providerModels(curProvider());

    /** 预设选择即回填 base_url + 首选 model——model 留空值时用户再挑 */
    const pickProvider = (id: string) => {
        setProvider(id);
        const p = settingsStore.providers().find((x) => x.id === id);
        if (!p) return;
        setBaseUrl(p.base_url ?? "");
        const ms = providerModels(p);
        if (ms.length && !ms.includes(model())) setModel(ms[0]);
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
                <Show when={loadErr()}>
                    <p class="form-error" role="alert">
                        {t.settings.loadFailed}{" "}
                        <button
                            type="button"
                            class="btn-ghost"
                            onClick={() => void load()}
                        >
                            {t.home.retry}
                        </button>
                    </p>
                </Show>
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
                            name="api_key"
                            autocomplete="off"
                            value={apiKey()}
                            onInput={(e) => setApiKey(e.currentTarget.value)}
                        />
                    </label>
                    {/* 无存 key（needs_auth 语义）时禁用——无可清对象 */}
                    <button
                        type="button"
                        class="btn-ghost"
                        disabled={
                            !settingsStore.settings()?.has_api_key || clearing()
                        }
                        onClick={() => void clearKey()}
                    >
                        {clearing() ? t.settings.clearing : t.settings.clearKey}
                    </button>
                </div>
                {/* 后端回执 ignored：白名单外字段被静默丢弃——明示防「存了没生效」 */}
                <Show when={settingsStore.settings()?.ignored?.length}>
                    <p class="form-warn" role="status">
                        {t.settings.ignoredWarn.replace(
                            "{names}",
                            (settingsStore.settings()?.ignored ?? []).join(
                                "、",
                            ),
                        )}
                    </p>
                </Show>
                <Show when={settingsStore.providers().length > 0}>
                    <label>
                        <span>{t.settings.provider}</span>
                        <select
                            class="tx-select"
                            value={provider()}
                            onChange={(e) =>
                                pickProvider(e.currentTarget.value)
                            }
                        >
                            <option value="">
                                {t.settings.providerCustom}
                            </option>
                            <For each={settingsStore.providers()}>
                                {(p) => (
                                    <option value={p.id}>
                                        {p.name ?? p.id}
                                    </option>
                                )}
                            </For>
                        </select>
                    </label>
                </Show>
                <label>
                    <span>{t.settings.baseUrl}</span>
                    <input
                        type="url"
                        name="base_url"
                        placeholder="https://…/v1"
                        value={baseUrl()}
                        onInput={(e) => {
                            setBaseUrl(e.currentTarget.value);
                            // 手改 URL 即脱离预设——否则预设名下挂着别人的地址
                            if (provider()) setProvider("");
                        }}
                    />
                </label>
                <label>
                    <span>{t.settings.model}</span>
                    {/* 预设带 models → select；自定义/无 models → 自由输入（BYOK 任意端点） */}
                    <Show
                        when={provModels().length > 0}
                        fallback={
                            <input
                                name="model"
                                value={model()}
                                onInput={(e) => setModel(e.currentTarget.value)}
                            />
                        }
                    >
                        <select
                            class="tx-select"
                            name="model"
                            value={model()}
                            onChange={(e) => setModel(e.currentTarget.value)}
                        >
                            {/* 现值不在预设清单（旧配置）也保留为可选，防静默改值 */}
                            <Show
                                when={
                                    model() && !provModels().includes(model())
                                }
                            >
                                <option value={model()}>{model()}</option>
                            </Show>
                            <For each={provModels()}>
                                {(m) => <option value={m}>{m}</option>}
                            </For>
                        </select>
                    </Show>
                </label>
                <div class="settings-field">
                    <span>
                        {t.settings.dialect}
                        <em class="muted">{t.settings.dialectHint}</em>
                    </span>
                    <Segmented
                        options={segOptsWithCurrent(
                            API_DIALECTS,
                            dialect(),
                            (d) => (d === "auto" ? t.settings.dialectAuto : d),
                        )}
                        value={dialect()}
                        onChange={setDialect}
                        ariaLabel={t.settings.dialect}
                    />
                </div>
                <div class="settings-field">
                    <span>{t.settings.targetLang}</span>
                    <Segmented
                        options={segOptsWithCurrent(TARGET_LANGS, targetLang())}
                        value={targetLang()}
                        onChange={setTargetLang}
                        ariaLabel={t.settings.targetLang}
                    />
                </div>
                <div class="settings-field">
                    <span>{t.settings.engine}</span>
                    <Segmented
                        options={segOptsWithCurrent(ENGINES, engine(), (en) =>
                            en === "auto" ? t.home.engineAuto : en,
                        )}
                        value={engine()}
                        onChange={setEngine}
                        ariaLabel={t.settings.engine}
                    />
                </div>
                <label>
                    <span>
                        {t.settings.concurrency}
                        <em class="muted">{t.settings.concurrencyHint}</em>
                    </span>
                    <input
                        type="number"
                        name="concurrency"
                        min={1}
                        max={16}
                        value={concurrency()}
                        onInput={(e) => setConcurrency(e.currentTarget.value)}
                    />
                </label>
                <div class="settings-field">
                    <span>
                        {t.settings.contextGuidance}
                        <em class="muted">{t.settings.contextGuidanceHint}</em>
                    </span>
                    <Segmented
                        options={[
                            { value: "on", label: t.home.optOn },
                            { value: "off", label: t.home.optOff },
                        ]}
                        value={guidance()}
                        onChange={setGuidance}
                        ariaLabel={t.settings.contextGuidance}
                    />
                </div>
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
                {/* 外观=色板即全站主题(ADR-0020 二次追加):纸面+chrome 同源
                    配对,唯一外观轴——不再存在独立的界面亮暗选择 */}
                <label>
                    <span>
                        {t.settings.appearance}
                        <em class="muted">{t.settings.appearanceHint}</em>
                    </span>
                    <select
                        class="tx-select"
                        value={settingsStore.paperTheme()}
                        onChange={(e) =>
                            settingsStore.setPaperTheme(
                                e.currentTarget.value as Parameters<
                                    typeof settingsStore.setPaperTheme
                                >[0],
                            )
                        }
                    >
                        <For each={PAPER_THEME_IDS}>
                            {(id) => (
                                <option value={id}>{PAPER_LABEL[id]}</option>
                            )}
                        </For>
                    </select>
                </label>
                {/* 划词浮条 + 句游标提示（sel-system——localStorage 即时生效，
                    不走后端 settings 通道） */}
                <div class="settings-field">
                    <span>
                        {t.settings.floatbar}
                        <em class="muted">{t.settings.floatbarHint}</em>
                    </span>
                    <Segmented
                        options={[
                            { value: "on", label: t.home.optOn },
                            { value: "off", label: t.home.optOff },
                        ]}
                        value={settingsStore.floatbar() ? "on" : "off"}
                        onChange={(v) => settingsStore.setFloatbar(v === "on")}
                        ariaLabel={t.settings.floatbar}
                    />
                    <em class="muted">{t.settings.cursorHint}</em>
                </div>
                {/* 句级双语对位（sent-align——localStorage 即时生效） */}
                <div class="settings-field">
                    <span>
                        {t.settings.sentAlign}
                        <em class="muted">{t.settings.sentAlignHint}</em>
                    </span>
                    <Segmented
                        options={[
                            { value: "on", label: t.home.optOn },
                            { value: "off", label: t.home.optOff },
                        ]}
                        value={settingsStore.sentAlign() ? "on" : "off"}
                        onChange={(v) => settingsStore.setSentAlign(v === "on")}
                        ariaLabel={t.settings.sentAlign}
                    />
                </div>
                {/* 任务完成通知（notifyDone 闸=document.hidden+permission===
                    granted——本页只做权限请求入口与态显示，无独立开关） */}
                <div class="settings-field">
                    <span>
                        {t.settings.notify}
                        <em class="muted">{t.settings.notifyHint}</em>
                    </span>
                    <button
                        type="button"
                        class="btn-ghost"
                        disabled={notifyPerm() !== "default"}
                        onClick={() => void requestNotify()}
                    >
                        {notifyPerm() === "granted"
                            ? t.settings.notifyOn
                            : notifyPerm() === "default"
                              ? t.settings.notifyEnable
                              : t.settings.notifyDenied}
                    </button>
                </div>
                <div class="settings-field">
                    <span>{t.settings.lang}</span>
                    <Segmented
                        options={[
                            { value: "auto", label: t.settings.langAuto },
                            { value: "zh", label: t.settings.langZh },
                            { value: "en", label: t.settings.langEn },
                        ]}
                        value={langChoice()}
                        onChange={(v) => setLang(v as LangChoice)}
                        ariaLabel={t.settings.lang}
                    />
                </div>
                <div class="settings-actions">
                    <button
                        type="submit"
                        class="btn-primary"
                        disabled={saving()}
                    >
                        {saving() ? t.settings.saving : t.settings.save}
                    </button>
                    <button
                        type="button"
                        class="btn-ghost"
                        disabled={testing()}
                        onClick={() => void test()}
                    >
                        {testing() ? t.settings.testing : t.settings.test}
                    </button>
                    <Show when={msg()}>
                        <span
                            class="form-msg"
                            classList={{ err: msgErr() }}
                            role={msgErr() ? "alert" : "status"}
                        >
                            {msg()}
                        </span>
                    </Show>
                </div>
            </form>
        </main>
    );
}
