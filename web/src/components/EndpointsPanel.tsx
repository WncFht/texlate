// EndpointsPanel —— BYOK 端点档案卡面（endpoints.json 的 UI 面）。
// server 形态整面 403：store.endpointsOff() 置位 → 整块不渲染。
// 写径整表替换（PUT profiles[]）——启用/删除/新建/编辑全折成全量写；
// 凭据写语义（api_key="" 承旧值、api_key|key_env 互斥）由服务端归一，
// 本面只造写行：读面不回 key，未触碰凭据的行凭据键缺席送出（=承旧值）。

import { createSignal, For, onMount, Show } from "solid-js";
import {
    api,
    apiErrText,
    type EndpointProfile,
    type EndpointProfileWrite,
    type ProbeReport,
} from "../api/client";
import { fmt, t } from "../i18n";
import { API_DIALECTS, segOptsWithCurrent } from "../options";
import { settingsStore } from "../stores/settings";
import Segmented from "./Segmented";

const MAX_MODELS = 8;

/** 编辑/新建草稿——models 是逗号/换行分隔原文，凭据两态互斥 */
interface Draft {
    /** 编辑时带原 id；新建为 ""（保存时由 base_url 造 slug） */
    id: string;
    label: string;
    base_url: string;
    dialect: string;
    models: string;
    enabled: boolean;
    cred: "key" | "env";
    api_key: string;
    key_env: string;
}

/** models 文本域 → 数组（逗号/换行分隔、trim 去空、去重保序、≤8） */
const parseModels = (text: string): string[] => {
    const seen = new Set<string>();
    const out: string[] = [];
    for (const m of text.split(/[,\n]/)) {
        const s = m.trim();
        if (s && !seen.has(s)) {
            seen.add(s);
            out.push(s);
        }
    }
    return out.slice(0, MAX_MODELS);
};

/** base_url → 新 profile slug id（后端 _slug_for 的 host-slug 简化版；撞名加 -N） */
const slugFor = (baseUrl: string, taken: Set<string>): string => {
    let host = "";
    try {
        host = new URL(baseUrl).hostname;
    } catch {
        /* 半成品 URL 也兜底 */
    }
    const base =
        (host || baseUrl)
            .toLowerCase()
            .replace(/[^a-z0-9]+/g, "-")
            .replace(/^-+|-+$/g, "")
            .slice(0, 24)
            .replace(/-+$/g, "") || "endpoint";
    let cand = base;
    let n = 2;
    while (taken.has(cand)) {
        cand = `${base}-${n}`;
        n += 1;
    }
    return cand;
};

/** 读面行 → 写面行（凭据键缺席 = 承旧值） */
const writeOf = (p: EndpointProfile): EndpointProfileWrite => ({
    id: p.id,
    label: p.label,
    base_url: p.base_url,
    dialect: p.dialect,
    models: p.models,
    enabled: p.enabled,
});

const draftOf = (p: EndpointProfile): Draft => ({
    id: p.id,
    label: p.label,
    base_url: p.base_url,
    dialect: p.dialect,
    models: p.models.join(", "),
    enabled: p.enabled,
    cred: p.key_env ? "env" : "key",
    api_key: "",
    key_env: p.key_env,
});

const blankDraft = (): Draft => ({
    id: "",
    label: "",
    base_url: "",
    dialect: "auto",
    models: "",
    enabled: true,
    cred: "key",
    api_key: "",
    key_env: "",
});

const draftToWrite = (d: Draft, taken: Set<string>): EndpointProfileWrite => ({
    id: d.id || slugFor(d.base_url, taken),
    label: d.label.trim(),
    base_url: d.base_url.trim(),
    dialect: d.dialect,
    models: parseModels(d.models),
    enabled: d.enabled,
    api_key: d.cred === "key" ? d.api_key.trim() : "",
    key_env: d.cred === "env" ? d.key_env.trim() : "",
});

/** verdict → badge 色级：ok / warn / bad / ""（neutral） */
const VERDICT_CLASS: Record<string, string> = {
    ok: "ok",
    usable: "ok",
    placeholder_lost: "warn",
    no_cjk: "warn",
    empty: "warn",
    no_models_dir: "warn",
    skipped: "",
};
const verdictCls = (v: string): string => VERDICT_CLASS[v] ?? "bad";
const verdictText = (v: string): string => t.settings.endpoints.verdicts[v] ?? v;

/** 凭据三态展示行（读面只见 has_api_key / key_env 名 / has_env_key） */
const credText = (p: EndpointProfile): string => {
    const ep = t.settings.endpoints;
    if (p.has_api_key) return ep.credKeySet;
    if (p.key_env)
        return fmt(p.has_env_key ? ep.credEnvSet : ep.credEnvUnset, {
            name: p.key_env,
        });
    return ep.credNone;
};

/** 报告时效展示——ISO 截到分（秒级噪声无信息量） */
const probeAt = (r?: ProbeReport | null): string => {
    const at = r?.at ?? "";
    return at ? at.slice(0, 16).replace("T", " ") : "";
};

interface Props {
    /** 激活成功后的回调——Settings 主表单重拉字段（base_url/model 已换端点） */
    onActivated?: () => void;
}

export default function EndpointsPanel(props: Props) {
    const [draft, setDraft] = createSignal<Draft | null>(null);
    const [busy, setBusy] = createSignal(""); // profile id | "draft"
    const [probing, setProbing] = createSignal("");
    /** 本地探测回执（{id} 路服务端已钉 last_probe，本图兜刷新失败的即时显示） */
    const [probeOut, setProbeOut] = createSignal<Record<string, ProbeReport>>(
        {},
    );
    const [msg, setMsg] = createSignal("");
    const [msgErr, setMsgErr] = createSignal(false);

    onMount(() => void settingsStore.refreshEndpoints().catch(() => {}));

    const ep = () => t.settings.endpoints;
    const view = () => settingsStore.endpoints();
    const profiles = () => view()?.profiles ?? [];
    const reportOf = (p: EndpointProfile) =>
        probeOut()[p.id] ?? p.last_probe ?? null;

    const fail = (text: string) => {
        setMsgErr(true);
        setMsg(text);
    };

    /** 全量写公共臂：rows 由调用方按现表变换 */
    const saveTable = async (rows: EndpointProfileWrite[]) => {
        await settingsStore.saveEndpoints(rows);
    };

    const toggleEnabled = async (p: EndpointProfile) => {
        if (busy()) return;
        setBusy(p.id);
        setMsg("");
        try {
            await saveTable(
                profiles().map((x) => ({
                    ...writeOf(x),
                    enabled: x.id === p.id ? !x.enabled : x.enabled,
                })),
            );
        } catch (e) {
            fail(`${ep().saveFailed}：${apiErrText(e)}`);
        } finally {
            setBusy("");
        }
    };

    const remove = async (p: EndpointProfile) => {
        if (busy()) return;
        if (
            !window.confirm(
                fmt(ep().delConfirm, { label: p.label || p.id }),
            )
        )
            return;
        setBusy(p.id);
        setMsg("");
        try {
            await saveTable(
                profiles()
                    .filter((x) => x.id !== p.id)
                    .map(writeOf),
            );
        } catch (e) {
            fail(`${ep().saveFailed}：${apiErrText(e)}`);
        } finally {
            setBusy("");
        }
    };

    const activate = async (p: EndpointProfile) => {
        if (busy()) return;
        setBusy(p.id);
        setMsg("");
        try {
            await settingsStore.activateEndpoint(p.id);
            props.onActivated?.();
            setMsgErr(false);
            setMsg(fmt(ep().activated, { label: p.label || p.id }));
        } catch (e) {
            fail(`${ep().activateFailed}：${apiErrText(e)}`);
        } finally {
            setBusy("");
        }
    };

    const probe = async (p: EndpointProfile) => {
        if (probing()) return;
        setProbing(p.id);
        setMsg("");
        try {
            const r = await settingsStore.probeEndpoint(p.id);
            setProbeOut((m) => ({ ...m, [p.id]: r }));
        } catch (e) {
            fail(`${ep().probeFailed}：${apiErrText(e)}`);
        } finally {
            setProbing("");
        }
    };

    /** 草稿探测：输入了新 key → 裸端点路（探草稿现值）；否则既有 id → {id} 档案路 */
    const probeDraft = async () => {
        const d = draft();
        if (!d || probing()) return;
        const key = `draft:${d.id || "new"}`;
        setProbing(key);
        setMsg("");
        try {
            const r =
                d.cred === "key" && d.api_key.trim()
                    ? await api.probeEndpoint({
                          base_url: d.base_url.trim(),
                          api_key: d.api_key.trim(),
                          dialect: d.dialect,
                          models: parseModels(d.models),
                      })
                    : await settingsStore.probeEndpoint(d.id);
            setProbeOut((m) => ({ ...m, [key]: r }));
        } catch (e) {
            fail(`${ep().probeFailed}：${apiErrText(e)}`);
        } finally {
            setProbing("");
        }
    };

    const saveDraft = async () => {
        const d = draft();
        if (!d || busy()) return;
        setBusy("draft");
        setMsg("");
        try {
            const cur = profiles();
            const rows = cur.map(writeOf);
            const w = draftToWrite(d, new Set(cur.map((x) => x.id)));
            const idx = rows.findIndex((x) => x.id === d.id);
            if (idx >= 0) rows[idx] = w;
            else rows.push(w);
            await saveTable(rows);
            setDraft(null);
        } catch (e) {
            fail(`${ep().saveFailed}：${apiErrText(e)}`);
        } finally {
            setBusy("");
        }
    };

    /** 草稿字段更新（signal 内对象浅改） */
    const up = (patch: Partial<Draft>) =>
        setDraft((d) => (d ? { ...d, ...patch } : d));

    const draftReport = () => {
        const d = draft();
        return d ? (probeOut()[`draft:${d.id || "new"}`] ?? null) : null;
    };

    return (
        <Show when={!settingsStore.endpointsOff()}>
            <section class="eps" aria-label={t.settings.endpoints.title}>
                <h2>
                    {ep().title}
                    <em class="muted">{ep().hint}</em>
                </h2>
                <Show
                    when={view()}
                    fallback={<p class="muted">{t.pane.loading}</p>}
                >
                    <Show
                        when={profiles().length > 0}
                        fallback={<p class="muted">{ep().empty}</p>}
                    >
                        <ul class="ep-list">
                            <For each={profiles()}>
                                {(p) => {
                                    const rep = () => reportOf(p);
                                    return (
                                        <li
                                            class="ep-card"
                                            classList={{ off: !p.enabled }}
                                        >
                                            <div class="ep-head">
                                                <strong>{p.label || p.id}</strong>
                                                <Show
                                                    when={
                                                        view()?.active_id ===
                                                        p.id
                                                    }
                                                >
                                                    <span class="ep-badge ok">
                                                        {ep().activeBadge}
                                                    </span>
                                                </Show>
                                                <span class="ep-spacer" />
                                                <label class="ep-toggle">
                                                    <input
                                                        type="checkbox"
                                                        checked={p.enabled}
                                                        disabled={!!busy()}
                                                        onChange={() =>
                                                            void toggleEnabled(
                                                                p,
                                                            )
                                                        }
                                                    />
                                                    {ep().enabledTip}
                                                </label>
                                            </div>
                                            <div class="ep-url">{p.base_url}</div>
                                            <Show when={p.models.length > 0}>
                                                <div class="ep-models">
                                                    <For each={p.models}>
                                                        {(m) => (
                                                            <code>{m}</code>
                                                        )}
                                                    </For>
                                                </div>
                                            </Show>
                                            <div class="ep-meta">
                                                <span>{credText(p)}</span>
                                                <Show when={rep()}>
                                                    {(r) => (
                                                        <span class="ep-probe">
                                                            {fmt(ep().at, {
                                                                at: probeAt(
                                                                    r(),
                                                                ),
                                                            })}
                                                            <i
                                                                class={`ep-badge ${verdictCls(
                                                                    r().stage1
                                                                        ?.verdict ??
                                                                        "",
                                                                )}`}
                                                            >
                                                                {verdictText(
                                                                    r().stage1
                                                                        ?.verdict ??
                                                                        "",
                                                                )}
                                                            </i>
                                                            <For
                                                                each={Object.entries(
                                                                    r().models ??
                                                                        {},
                                                                )}
                                                            >
                                                                {([
                                                                    uid,
                                                                    mr,
                                                                ]) => (
                                                                    <i
                                                                        class={`ep-badge ${verdictCls(
                                                                            mr.verdict,
                                                                        )}`}
                                                                        title={
                                                                            mr.detail ||
                                                                            uid
                                                                        }
                                                                    >
                                                                        {uid}:{" "}
                                                                        {verdictText(
                                                                            mr.verdict,
                                                                        )}
                                                                        {mr.latency_s
                                                                            ? ` ${mr.latency_s}s`
                                                                            : ""}
                                                                    </i>
                                                                )}
                                                            </For>
                                                        </span>
                                                    )}
                                                </Show>
                                            </div>
                                            <div class="ep-actions">
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    disabled={
                                                        !!busy() ||
                                                        view()?.active_id ===
                                                            p.id
                                                    }
                                                    onClick={() =>
                                                        void activate(p)
                                                    }
                                                >
                                                    {busy() === p.id
                                                        ? t.settings.saving
                                                        : ep().activate}
                                                </button>
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    disabled={!!probing()}
                                                    onClick={() =>
                                                        void probe(p)
                                                    }
                                                >
                                                    {probing() === p.id
                                                        ? ep().probing
                                                        : ep().probe}
                                                </button>
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    onClick={() =>
                                                        setDraft(draftOf(p))
                                                    }
                                                >
                                                    {ep().edit}
                                                </button>
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    disabled={!!busy()}
                                                    onClick={() =>
                                                        void remove(p)
                                                    }
                                                >
                                                    {ep().del}
                                                </button>
                                            </div>
                                        </li>
                                    );
                                }}
                            </For>
                        </ul>
                    </Show>
                    <Show
                        when={draft()}
                        fallback={
                            <button
                                type="button"
                                class="btn-ghost"
                                onClick={() => setDraft(blankDraft())}
                            >
                                {ep().add}
                            </button>
                        }
                    >
                        {(d) => (
                            <div class="ep-draft">
                                <h3>
                                    {d().id ? ep().editTitle : ep().addTitle}
                                </h3>
                                <label>
                                    <span>{ep().label}</span>
                                    <input
                                        value={d().label}
                                        placeholder={ep().labelPh}
                                        onInput={(e) =>
                                            up({
                                                label: e.currentTarget.value,
                                            })
                                        }
                                    />
                                </label>
                                <label>
                                    <span>{t.settings.baseUrl}</span>
                                    <input
                                        type="url"
                                        placeholder="https://…/v1"
                                        value={d().base_url}
                                        onInput={(e) =>
                                            up({
                                                base_url:
                                                    e.currentTarget.value,
                                            })
                                        }
                                    />
                                </label>
                                <div class="settings-field">
                                    <span>{t.settings.dialect}</span>
                                    <Segmented
                                        options={segOptsWithCurrent(
                                            API_DIALECTS,
                                            d().dialect,
                                            (x) =>
                                                x === "auto"
                                                    ? t.settings.dialectAuto
                                                    : x,
                                        )}
                                        value={d().dialect}
                                        onChange={(v) => up({ dialect: v })}
                                        ariaLabel={t.settings.dialect}
                                    />
                                </div>
                                <label>
                                    <span>
                                        {ep().models}
                                        <em class="muted">{ep().modelsPh}</em>
                                    </span>
                                    <textarea
                                        rows={2}
                                        value={d().models}
                                        onInput={(e) =>
                                            up({
                                                models: e.currentTarget.value,
                                            })
                                        }
                                    />
                                </label>
                                <div class="settings-field">
                                    <span>
                                        {ep().cred}
                                        <em class="muted">{ep().credHint}</em>
                                    </span>
                                    <Segmented
                                        options={[
                                            {
                                                value: "key",
                                                label: ep().credKey,
                                            },
                                            {
                                                value: "env",
                                                label: ep().credEnv,
                                            },
                                        ]}
                                        value={d().cred}
                                        onChange={(v) =>
                                            up({ cred: v as Draft["cred"] })
                                        }
                                        ariaLabel={ep().cred}
                                    />
                                    <Show
                                        when={d().cred === "key"}
                                        fallback={
                                            <input
                                                value={d().key_env}
                                                placeholder={ep().envPh}
                                                onInput={(e) =>
                                                    up({
                                                        key_env:
                                                            e.currentTarget
                                                                .value,
                                                    })
                                                }
                                            />
                                        }
                                    >
                                        <input
                                            type="password"
                                            autocomplete="off"
                                            value={d().api_key}
                                            placeholder={
                                                profiles().find(
                                                    (x) => x.id === d().id,
                                                )?.has_api_key
                                                    ? ep().keyPh
                                                    : t.settings.apiKey
                                            }
                                            onInput={(e) =>
                                                up({
                                                    api_key:
                                                        e.currentTarget.value,
                                                })
                                            }
                                        />
                                    </Show>
                                </div>
                                <Show when={draftReport()}>
                                    {(r) => (
                                        <div class="ep-probe">
                                            <i
                                                class={`ep-badge ${verdictCls(
                                                    r().stage1?.verdict ?? "",
                                                )}`}
                                            >
                                                {verdictText(
                                                    r().stage1?.verdict ?? "",
                                                )}
                                            </i>
                                            <For
                                                each={Object.entries(
                                                    r().models ?? {},
                                                )}
                                            >
                                                {([uid, mr]) => (
                                                    <i
                                                        class={`ep-badge ${verdictCls(
                                                            mr.verdict,
                                                        )}`}
                                                        title={mr.detail || uid}
                                                    >
                                                        {uid}:{" "}
                                                        {verdictText(
                                                            mr.verdict,
                                                        )}
                                                        {mr.latency_s
                                                            ? ` ${mr.latency_s}s`
                                                            : ""}
                                                    </i>
                                                )}
                                            </For>
                                        </div>
                                    )}
                                </Show>
                                <div class="ep-actions">
                                    <button
                                        type="button"
                                        class="btn-primary"
                                        disabled={!!busy() || !d().base_url.trim()}
                                        onClick={() => void saveDraft()}
                                    >
                                        {busy() === "draft"
                                            ? t.settings.saving
                                            : ep().save}
                                    </button>
                                    <Show
                                        when={
                                            d().id ||
                                            (d().cred === "key" &&
                                                d().api_key.trim())
                                        }
                                    >
                                        <button
                                            type="button"
                                            class="btn-ghost"
                                            disabled={
                                                !!probing() ||
                                                !d().base_url.trim()
                                            }
                                            onClick={() => void probeDraft()}
                                        >
                                            {probing() ===
                                            `draft:${d().id || "new"}`
                                                ? ep().probing
                                                : ep().probe}
                                        </button>
                                    </Show>
                                    <button
                                        type="button"
                                        class="btn-ghost"
                                        onClick={() => setDraft(null)}
                                    >
                                        {ep().cancel}
                                    </button>
                                </div>
                            </div>
                        )}
                    </Show>
                </Show>
                <Show when={msg()}>
                    <p
                        class="form-msg"
                        classList={{ err: msgErr() }}
                        role={msgErr() ? "alert" : "status"}
                    >
                        {msg()}
                    </p>
                </Show>
            </section>
        </Show>
    );
}
