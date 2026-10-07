// EndpointsPanel —— BYOK 端点档案卡面（endpoints.json 的 UI 面，ccLoad 式
// 渠道管理交互）：卡片 model(redirect) chips + 右侧抽屉编辑（基本/凭据/模型
// 三节）+ 模型行式表格（勾选批处理/行内搜索/重定向列）+ 获取模型勾选器 +
// 逐模型测试弹窗 + 拖拽排序弹窗 + 删除确认弹窗。
//
// server 形态整面 403：store.endpointsOff() 置位 → 整块不渲染。
// 写径整表替换（PUT profiles[]）——启用/删除/排序/编辑全折成全量写；
// 凭据写语义（api_key="" 承旧值、api_key|key_env 互斥）由服务端归一，
// 本面只造写行：读面不回 key，未触碰凭据的行凭据键缺席送出（=承旧值）。
//
// 模型条目 {model, redirect_model}：model 是本地名（展示/探针报告键），
// redirect_model 是线上请求名（空串=本名直发）。子集探测按本地名发
// {id, models:[name]}，服务端按档案 redirect 解析出线名。

import { createSignal, For, onCleanup, onMount, Show } from "solid-js";
import {
    apiErrText,
    type EndpointModel,
    type EndpointProfile,
    type EndpointProfileWrite,
    type ProbeReport,
} from "../api/client";
import { fmt, t } from "../i18n";
import { API_DIALECTS, segOptsWithCurrent } from "../options";
import { settingsStore } from "../stores/settings";
import Segmented from "./Segmented";

const MAX_MODELS = 8;
/** 卡片 chips 直显上限——超出折叠 +N */
const CHIP_MAX = 4;

/** 编辑/新建草稿——models 是可编行表，凭据两态互斥 */
interface Draft {
    /** 编辑时带原 id；新建为 ""（保存时由 base_url 造 slug） */
    id: string;
    label: string;
    base_url: string;
    dialect: string;
    models: EndpointModel[];
    enabled: boolean;
    cred: "key" | "env";
    api_key: string;
    key_env: string;
}

type DrawerSec = "basic" | "cred" | "models";

/** 获取模型弹窗态 */
type FetchState =
    | { kind: "loading" }
    | { kind: "error"; text: string }
    | { kind: "list"; models: string[]; checked: Set<string> };

/** 测试弹窗结果行 */
interface TestRow {
    name: string;
    verdict: string;
    latency_s?: number;
    detail?: string;
    listed?: boolean | null;
}

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
    models: p.models.map((m) => ({ ...m })),
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
    models: [],
    enabled: true,
    cred: "key",
    api_key: "",
    key_env: "",
});

/** 草稿 → 写行：空名行丢弃、按本地名去重保序、≤8 截断（服务端兜底再验） */
const draftToWrite = (d: Draft, taken: Set<string>): EndpointProfileWrite => {
    const seen = new Set<string>();
    const models: EndpointModel[] = [];
    for (const m of d.models) {
        const name = m.model.trim();
        const red = m.redirect_model.trim();
        if (!name || seen.has(name)) continue;
        seen.add(name);
        models.push({ model: name, redirect_model: red });
    }
    return {
        id: d.id || slugFor(d.base_url, taken),
        label: d.label.trim(),
        base_url: d.base_url.trim(),
        dialect: d.dialect,
        models: models.slice(0, MAX_MODELS),
        enabled: d.enabled,
        api_key: d.cred === "key" ? d.api_key.trim() : "",
        key_env: d.cred === "env" ? d.key_env.trim() : "",
    };
};

/** 展示名：name(red)；无 redirect 只显名 */
const chipText = (m: EndpointModel): string =>
    m.redirect_model ? `${m.model}(${m.redirect_model})` : m.model;

/** 去来源前缀：`vendor/name` → `name`（批处理臂——本地名瘦身，redirect 不动） */
const stripPrefix = (name: string): string => {
    const i = name.lastIndexOf("/");
    return i >= 0 ? name.slice(i + 1) : name;
};

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
    const [sec, setSec] = createSignal<DrawerSec>("basic");
    const [busy, setBusy] = createSignal(""); // profile id | "draft"
    const [probing, setProbing] = createSignal("");
    /** 本地探测回执（{id} 路服务端已钉 last_probe，本图兜刷新失败的即时显示） */
    const [probeOut, setProbeOut] = createSignal<Record<string, ProbeReport>>(
        {},
    );
    const [msg, setMsg] = createSignal("");
    const [msgErr, setMsgErr] = createSignal(false);
    // ---- 模型表格态（草稿内）----
    const [modelSel, setModelSel] = createSignal<Set<number>>(new Set());
    const [modelFilter, setModelFilter] = createSignal("");
    // ---- 弹窗态 ----
    const [fetchSt, setFetchSt] = createSignal<FetchState | null>(null);
    const [testId, setTestId] = createSignal("");
    const [testModel, setTestModel] = createSignal("");
    const [testRows, setTestRows] = createSignal<TestRow[]>([]);
    const [sortIds, setSortIds] = createSignal<string[] | null>(null);
    const [delTarget, setDelTarget] = createSignal<EndpointProfile | null>(null);
    let sortDragIdx = -1;

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

    /** 弹窗内窄化访问器——Show when 不认 kind 判别，手动取 list/error 分支 */
    const fetchList = () => {
        const s = fetchSt();
        return s?.kind === "list" ? s : null;
    };
    const fetchErrText = () => {
        const s = fetchSt();
        return s?.kind === "error" ? s.text : "";
    };
    const ok = (text: string) => {
        setMsgErr(false);
        setMsg(text);
    };

    /** 全量写公共臂：rows 由调用方按现表变换 */
    const saveTable = async (rows: EndpointProfileWrite[]) => {
        await settingsStore.saveEndpoints(rows);
    };

    // ------------------------------------------------------------ 卡片操作

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

    const activate = async (p: EndpointProfile) => {
        if (busy()) return;
        setBusy(p.id);
        setMsg("");
        try {
            await settingsStore.activateEndpoint(p.id);
            props.onActivated?.();
            ok(fmt(ep().activated, { label: p.label || p.id }));
        } catch (e) {
            fail(`${ep().activateFailed}：${apiErrText(e)}`);
        } finally {
            setBusy("");
        }
    };

    const confirmDelete = async () => {
        const p = delTarget();
        if (!p || busy()) return;
        setBusy(p.id);
        setMsg("");
        try {
            await saveTable(
                profiles()
                    .filter((x) => x.id !== p.id)
                    .map(writeOf),
            );
            setDelTarget(null);
        } catch (e) {
            fail(`${ep().saveFailed}：${apiErrText(e)}`);
        } finally {
            setBusy("");
        }
    };

    // ------------------------------------------------------------ 抽屉

    const openDraft = (d: Draft) => {
        setDraft(d);
        setSec("basic");
        setModelSel(new Set<number>());
        setModelFilter("");
    };

    /** 草稿字段更新（signal 内对象浅改） */
    const up = (patch: Partial<Draft>) =>
        setDraft((d) => (d ? { ...d, ...patch } : d));

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

    // ------------------------------------------------------------ 模型表格

    /** 行字段更新（按数组下标，Index 渲染行不动） */
    const setModel = (i: number, patch: Partial<EndpointModel>) =>
        up({
            models: draft()!.models.map((m, j) =>
                j === i ? { ...m, ...patch } : m,
            ),
        });

    const moveModel = (i: number, dir: -1 | 1) => {
        const d = draft();
        if (!d) return;
        const j = i + dir;
        if (j < 0 || j >= d.models.length) return;
        const next = [...d.models];
        [next[i], next[j]] = [next[j], next[i]];
        setModelSel(new Set<number>()); // 下标语义随重排失效——清空
        up({ models: next });
    };

    const removeModels = (idxs: ReadonlySet<number>) => {
        const d = draft();
        if (!d) return;
        up({ models: d.models.filter((_, i) => !idxs.has(i)) });
        setModelSel(new Set<number>());
    };

    const addModel = () => {
        const d = draft();
        if (!d || d.models.length >= MAX_MODELS) return;
        up({ models: [...d.models, { model: "", redirect_model: "" }] });
    };

    /** 批处理：对勾选下标跑 f(entry)→entry（保留勾选） */
    const batchMap = (f: (m: EndpointModel) => EndpointModel) => {
        const d = draft();
        if (!d) return;
        const sel = modelSel();
        up({
            models: d.models.map((m, i) => (sel.has(i) ? f(m) : m)),
        });
    };

    const batchLower = () =>
        batchMap((m) => ({
            model: m.model.toLowerCase(),
            redirect_model: m.redirect_model.toLowerCase(),
        }));

    const batchStrip = () =>
        batchMap((m) => ({ ...m, model: stripPrefix(m.model) }));

    /** 过滤后的可见下标（搜索只遮显示，批处理仍按全表下标语义） */
    const visibleIdx = (): number[] => {
        const d = draft();
        if (!d) return [];
        const q = modelFilter().trim().toLowerCase();
        return d.models
            .map((m, i) => ({ m, i }))
            .filter(
                ({ m }) =>
                    !q ||
                    m.model.toLowerCase().includes(q) ||
                    m.redirect_model.toLowerCase().includes(q),
            )
            .map(({ i }) => i);
    };

    const selAllChecked = () => {
        const vis = visibleIdx();
        return vis.length > 0 && vis.every((i) => modelSel().has(i));
    };

    const toggleSelAll = (on: boolean) => {
        const sel = new Set(modelSel());
        for (const i of visibleIdx()) {
            if (on) sel.add(i);
            else sel.delete(i);
        }
        setModelSel(sel);
    };

    const toggleSel = (i: number, on: boolean) => {
        const sel = new Set(modelSel());
        if (on) sel.add(i);
        else sel.delete(i);
        setModelSel(sel);
    };

    /** 行状态徽章：last_probe.models[本地名] 取最新 verdict */
    const modelStatus = (name: string) => {
        const d = draft();
        if (!d?.id) return null;
        const p = profiles().find((x) => x.id === d.id);
        const rep = p ? reportOf(p) : null;
        return rep?.models?.[name] ?? null;
    };

    // ------------------------------------------------------------ 获取模型

    /**
     * 获取模型径：草稿有 inline key → 裸探（现值）；既有 id 且 base_url 未改
     * → {id, models:[]}（服务端 stage1-only + merge 保留 stage2 verdict）；
     * env 凭据新草稿 → 不可用（凭据不在前端手里）。
     */
    const fetchModels = async () => {
        const d = draft();
        if (!d || fetchSt()?.kind === "loading") return;
        setFetchSt({ kind: "loading" });
        try {
            let r: ProbeReport;
            const saved = profiles().find((x) => x.id === d.id);
            const urlSame =
                !!saved &&
                d.base_url.trim().replace(/\/+$/, "") ===
                    saved.base_url.replace(/\/+$/, "");
            if (d.cred === "key" && d.api_key.trim()) {
                r = await settingsStore.probeEndpointBare({
                    base_url: d.base_url.trim(),
                    api_key: d.api_key.trim(),
                    dialect: d.dialect,
                    models: [],
                });
            } else if (d.id && urlSame) {
                r = await settingsStore.probeEndpoint(d.id, []);
            } else {
                setFetchSt({ kind: "error", text: ep().fetchNeedSave });
                return;
            }
            const list = r.stage1?.models ?? [];
            if (!list.length) {
                setFetchSt({
                    kind: "error",
                    text: fmt(ep().fetchError, {
                        detail: r.stage1?.detail || r.stage1?.verdict || "",
                    }),
                });
                return;
            }
            setFetchSt({
                kind: "list",
                models: list,
                // ccLoad 同款：默认全勾——确认只并新名，既有条目天然去重
                checked: new Set(list),
            });
        } catch (e) {
            setFetchSt({ kind: "error", text: apiErrText(e) });
        }
    };

    const fetchToggle = (name: string, on: boolean) => {
        const st = fetchSt();
        if (st?.kind !== "list") return;
        const checked = new Set(st.checked);
        if (on) checked.add(name);
        else checked.delete(name);
        setFetchSt({ ...st, checked });
    };

    const fetchConfirm = () => {
        const st = fetchSt();
        const d = draft();
        if (st?.kind !== "list" || !d) return;
        const have = new Set(d.models.map((m) => m.model));
        const add = [...st.checked]
            .filter((n) => !have.has(n))
            .map((n) => ({ model: n, redirect_model: "" }));
        up({ models: [...d.models, ...add].slice(0, MAX_MODELS) });
        setFetchSt(null);
    };

    // ------------------------------------------------------------ 测试弹窗

    const openTest = (p: EndpointProfile) => {
        setTestId(p.id);
        setTestModel(p.models[0]?.model ?? "");
        setTestRows([]);
    };

    const runTest = async () => {
        const pid = testId();
        const name = testModel();
        if (!pid || !name || probing()) return;
        setProbing(pid);
        setMsg("");
        try {
            const r = await settingsStore.probeEndpoint(pid, [name]);
            setProbeOut((m) => ({ ...m, [pid]: r }));
            const rows: TestRow[] = Object.entries(r.models ?? {}).map(
                ([uid, mr]) => ({
                    name: uid,
                    verdict: mr.verdict,
                    latency_s: mr.latency_s,
                    detail: mr.detail,
                    listed: mr.listed,
                }),
            );
            // 没出模型行时 stage1 本身就是结果（端点死全段 skipped/空）
            if (!rows.length && r.stage1) {
                rows.push({
                    name: `stage1`,
                    verdict: r.stage1.verdict,
                    detail: r.stage1.detail,
                });
            }
            setTestRows((cur) => [...rows, ...cur]);
        } catch (e) {
            fail(`${ep().probeFailed}：${apiErrText(e)}`);
        } finally {
            setProbing("");
        }
    };

    // ------------------------------------------------------------ 排序弹窗

    const openSort = () => setSortIds(profiles().map((p) => p.id));

    const sortDrop = (at: number) => {
        const ids = sortIds();
        if (!ids || sortDragIdx < 0 || sortDragIdx === at) return;
        const next = [...ids];
        const [moved] = next.splice(sortDragIdx, 1);
        next.splice(at, 0, moved);
        setSortIds(next);
    };

    const saveSort = async () => {
        const ids = sortIds();
        if (!ids || busy()) return;
        const byId = new Map(profiles().map((p) => [p.id, p]));
        const rows = ids
            .map((id) => byId.get(id))
            .filter((p): p is EndpointProfile => !!p)
            .map(writeOf);
        setBusy("sort");
        try {
            await saveTable(rows);
            setSortIds(null);
        } catch (e) {
            fail(`${ep().saveFailed}：${apiErrText(e)}`);
        } finally {
            setBusy("");
        }
    };

    // ------------------------------------------------------------ 导出

    /** 导出模型清单：`model` 每行一条，redirect 条目写成 `model,redirect`（可复制回 ccLoad 文本导入） */
    const exportModels = async () => {
        const d = draft();
        if (!d) return;
        const lines = d.models
            .filter((m) => m.model.trim())
            .map((m) =>
                m.redirect_model.trim()
                    ? `${m.model.trim()},${m.redirect_model.trim()}`
                    : m.model.trim(),
            )
            .join("\n");
        try {
            await navigator.clipboard.writeText(lines);
            ok(fmt(ep().exported, { n: lines.split("\n").length }));
        } catch {
            // clipboard 失败降级：临时 textarea 选区拷贝（老权限形态兜底）
            const ta = document.createElement("textarea");
            ta.value = lines;
            document.body.appendChild(ta);
            ta.select();
            const copied = document.execCommand("copy");
            ta.remove();
            if (copied)
                ok(fmt(ep().exported, { n: lines.split("\n").length }));
            else fail(ep().exportFail);
        }
    };

    // ------------------------------------------------------------ 弹窗外壳

    /** Esc 关最上层弹窗（drawer > fetch > test > sort > delete） */
    const closeTop = () => {
        if (fetchSt()) setFetchSt(null);
        else if (testId()) setTestId("");
        else if (sortIds()) setSortIds(null);
        else if (delTarget()) setDelTarget(null);
        else if (draft()) setDraft(null);
    };
    onMount(() => {
        const esc = (e: KeyboardEvent) => {
            if (e.key === "Escape" && !busy() && !probing()) closeTop();
        };
        document.addEventListener("keydown", esc);
        onCleanup(() => document.removeEventListener("keydown", esc));
    });

    const veilClick = (e: MouseEvent, close: () => void) => {
        if (e.target === e.currentTarget && !busy() && !probing()) close();
    };

    // ------------------------------------------------------------ 渲染

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
                                                    <For
                                                        each={p.models.slice(
                                                            0,
                                                            CHIP_MAX,
                                                        )}
                                                    >
                                                        {(m) => (
                                                            <code
                                                                class="ep-chip"
                                                                title={chipText(
                                                                    m,
                                                                )}
                                                            >
                                                                {m.model}
                                                                <Show
                                                                    when={
                                                                        m.redirect_model
                                                                    }
                                                                >
                                                                    <i class="ep-chip-red">
                                                                        (
                                                                        {
                                                                            m.redirect_model
                                                                        }
                                                                        )
                                                                    </i>
                                                                </Show>
                                                            </code>
                                                        )}
                                                    </For>
                                                    <Show
                                                        when={
                                                            p.models.length >
                                                            CHIP_MAX
                                                        }
                                                    >
                                                        <code class="ep-chip ep-more">
                                                            {fmt(ep().moreN, {
                                                                n:
                                                                    p.models
                                                                        .length -
                                                                    CHIP_MAX,
                                                            })}
                                                        </code>
                                                    </Show>
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
                                                    onClick={() => openTest(p)}
                                                >
                                                    {ep().probe}
                                                </button>
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    onClick={() =>
                                                        openDraft(draftOf(p))
                                                    }
                                                >
                                                    {ep().edit}
                                                </button>
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    disabled={!!busy()}
                                                    onClick={() =>
                                                        setDelTarget(p)
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
                    <div class="ep-foot">
                        <button
                            type="button"
                            class="btn-ghost"
                            onClick={() => openDraft(blankDraft())}
                        >
                            {ep().add}
                        </button>
                        <Show when={profiles().length > 1}>
                            <button
                                type="button"
                                class="btn-ghost"
                                onClick={openSort}
                            >
                                {ep().sort}
                            </button>
                        </Show>
                    </div>
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

                {/* ============ 编辑抽屉 ============ */}
                <Show when={draft()}>
                    {(d) => (
                        <div
                            class="ep-veil"
                            onClick={(e) => veilClick(e, () => setDraft(null))}
                        >
                            <div
                                class="ep-drawer"
                                role="dialog"
                                aria-modal="true"
                                aria-label={
                                    d().id ? ep().editTitle : ep().addTitle
                                }
                            >
                                <header class="ep-drawer-head">
                                    <h3>
                                        {d().id ? ep().editTitle : ep().addTitle}
                                    </h3>
                                    <button
                                        type="button"
                                        class="ep-x"
                                        aria-label={ep().close}
                                        onClick={() => setDraft(null)}
                                    >
                                        ×
                                    </button>
                                </header>
                                <div class="ep-drawer-body">
                                    <nav class="ep-nav">
                                        <For
                                            each={
                                                [
                                                    ["basic", ep().secBasic],
                                                    ["cred", ep().secCred],
                                                    ["models", ep().secModels],
                                                ] as [DrawerSec, string][]
                                            }
                                        >
                                            {([key, label]) => (
                                                <button
                                                    type="button"
                                                    class="ep-nav-item"
                                                    classList={{
                                                        on: sec() === key,
                                                    }}
                                                    onClick={() => setSec(key)}
                                                >
                                                    {label}
                                                </button>
                                            )}
                                        </For>
                                    </nav>
                                    <div class="ep-sec">
                                        {/* ---- 基本 ---- */}
                                        <Show when={sec() === "basic"}>
                                            <label>
                                                <span>{ep().label}</span>
                                                <input
                                                    value={d().label}
                                                    placeholder={ep().labelPh}
                                                    onInput={(e) =>
                                                        up({
                                                            label: e
                                                                .currentTarget
                                                                .value,
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
                                                                e.currentTarget
                                                                    .value,
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
                                                                ? t.settings
                                                                      .dialectAuto
                                                                : x,
                                                    )}
                                                    value={d().dialect}
                                                    onChange={(v) =>
                                                        up({ dialect: v })
                                                    }
                                                    ariaLabel={
                                                        t.settings.dialect
                                                    }
                                                />
                                            </div>
                                            <label class="ep-toggle">
                                                <input
                                                    type="checkbox"
                                                    checked={d().enabled}
                                                    onChange={(e) =>
                                                        up({
                                                            enabled:
                                                                e.currentTarget
                                                                    .checked,
                                                        })
                                                    }
                                                />
                                                {ep().enabledTip}
                                            </label>
                                        </Show>
                                        {/* ---- 凭据 ---- */}
                                        <Show when={sec() === "cred"}>
                                            <div class="settings-field">
                                                <span>
                                                    {ep().cred}
                                                    <em class="muted">
                                                        {ep().credHint}
                                                    </em>
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
                                                        up({
                                                            cred: v as Draft["cred"],
                                                        })
                                                    }
                                                    ariaLabel={ep().cred}
                                                />
                                                <Show
                                                    when={d().cred === "key"}
                                                    fallback={
                                                        <input
                                                            value={d().key_env}
                                                            placeholder={
                                                                ep().envPh
                                                            }
                                                            onInput={(e) =>
                                                                up({
                                                                    key_env:
                                                                        e
                                                                            .currentTarget
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
                                                                (x) =>
                                                                    x.id ===
                                                                    d().id,
                                                            )?.has_api_key
                                                                ? ep().keyPh
                                                                : t.settings
                                                                      .apiKey
                                                        }
                                                        onInput={(e) =>
                                                            up({
                                                                api_key:
                                                                    e
                                                                        .currentTarget
                                                                        .value,
                                                            })
                                                        }
                                                    />
                                                </Show>
                                            </div>
                                        </Show>
                                        {/* ---- 模型 ---- */}
                                        <Show when={sec() === "models"}>
                                            <div class="ep-mtools">
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    disabled={
                                                        !d().base_url.trim() ||
                                                        fetchSt()?.kind ===
                                                            "loading"
                                                    }
                                                    onClick={() =>
                                                        void fetchModels()
                                                    }
                                                >
                                                    {fetchSt()?.kind ===
                                                    "loading"
                                                        ? ep().fetchLoading
                                                        : ep().fetchModels}
                                                </button>
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    disabled={
                                                        d().models.length >=
                                                        MAX_MODELS
                                                    }
                                                    onClick={addModel}
                                                >
                                                    {ep().addModel}
                                                </button>
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    disabled={
                                                        !d().models.length
                                                    }
                                                    title={ep().exportTip}
                                                    onClick={() =>
                                                        void exportModels()
                                                    }
                                                >
                                                    {ep().exportModels}
                                                </button>
                                                <span class="ep-spacer" />
                                                <span class="muted">
                                                    {fmt(ep().modelsCount, {
                                                        n: d().models.length,
                                                    })}
                                                </span>
                                            </div>
                                            <Show when={modelSel().size > 0}>
                                                <div class="ep-mbatch">
                                                    <span>
                                                        {fmt(ep().selN, {
                                                            n: modelSel().size,
                                                        })}
                                                    </span>
                                                    <button
                                                        type="button"
                                                        class="btn-ghost"
                                                        onClick={batchLower}
                                                    >
                                                        {ep().batchLower}
                                                    </button>
                                                    <button
                                                        type="button"
                                                        class="btn-ghost"
                                                        onClick={batchStrip}
                                                    >
                                                        {ep().batchStrip}
                                                    </button>
                                                    <button
                                                        type="button"
                                                        class="btn-ghost"
                                                        onClick={() =>
                                                            removeModels(
                                                                modelSel(),
                                                            )
                                                        }
                                                    >
                                                        {ep().batchDel}
                                                    </button>
                                                </div>
                                            </Show>
                                            <table class="ep-mtable">
                                                <thead>
                                                    <tr>
                                                        <th class="ep-cb">
                                                            <input
                                                                type="checkbox"
                                                                checked={selAllChecked()}
                                                                onChange={(e) =>
                                                                    toggleSelAll(
                                                                        e
                                                                            .currentTarget
                                                                            .checked,
                                                                    )
                                                                }
                                                            />
                                                        </th>
                                                        <th class="ep-idx">
                                                            #
                                                        </th>
                                                        <th>
                                                            {ep().colName}
                                                            <input
                                                                class="ep-th-search"
                                                                placeholder={
                                                                    ep()
                                                                        .searchPh
                                                                }
                                                                value={modelFilter()}
                                                                onInput={(e) =>
                                                                    setModelFilter(
                                                                        e
                                                                            .currentTarget
                                                                            .value,
                                                                    )
                                                                }
                                                            />
                                                        </th>
                                                        <th>{ep().colRedirect}</th>
                                                        <th>{ep().colStatus}</th>
                                                        <th />
                                                    </tr>
                                                </thead>
                                                <tbody>
                                                    <Show
                                                        when={
                                                            visibleIdx()
                                                                .length > 0
                                                        }
                                                        fallback={
                                                            <tr>
                                                                <td
                                                                    colspan={6}
                                                                    class="muted"
                                                                >
                                                                    {
                                                                        ep()
                                                                            .modelsEmpty
                                                                    }
                                                                </td>
                                                            </tr>
                                                        }
                                                    >
                                                        <For
                                                            each={visibleIdx()}
                                                        >
                                                            {(i) => (
                                                                <tr>
                                                                    <td class="ep-cb">
                                                                        <input
                                                                            type="checkbox"
                                                                            checked={modelSel().has(
                                                                                i,
                                                                            )}
                                                                            onChange={(
                                                                                e,
                                                                            ) =>
                                                                                toggleSel(
                                                                                    i,
                                                                                    e
                                                                                        .currentTarget
                                                                                        .checked,
                                                                                )
                                                                            }
                                                                        />
                                                                    </td>
                                                                    <td class="ep-idx">
                                                                        {i + 1}
                                                                    </td>
                                                                    <td>
                                                                        <input
                                                                            class="ep-cell-in"
                                                                            value={
                                                                                d()
                                                                                    .models[
                                                                                    i
                                                                                ]
                                                                                    .model
                                                                            }
                                                                            onInput={(
                                                                                e,
                                                                            ) =>
                                                                                setModel(
                                                                                    i,
                                                                                    {
                                                                                        model: e
                                                                                            .currentTarget
                                                                                            .value,
                                                                                    },
                                                                                )
                                                                            }
                                                                        />
                                                                    </td>
                                                                    <td>
                                                                        <input
                                                                            class="ep-cell-in"
                                                                            placeholder={
                                                                                ep()
                                                                                    .redirectPh
                                                                            }
                                                                            value={
                                                                                d()
                                                                                    .models[
                                                                                    i
                                                                                ]
                                                                                    .redirect_model
                                                                            }
                                                                            onInput={(
                                                                                e,
                                                                            ) =>
                                                                                setModel(
                                                                                    i,
                                                                                    {
                                                                                        redirect_model:
                                                                                            e
                                                                                                .currentTarget
                                                                                                .value,
                                                                                    },
                                                                                )
                                                                            }
                                                                        />
                                                                    </td>
                                                                    <td>
                                                                        <Show
                                                                            when={modelStatus(
                                                                                d()
                                                                                    .models[
                                                                                    i
                                                                                ]
                                                                                    .model,
                                                                            )}
                                                                        >
                                                                            {(
                                                                                mr,
                                                                            ) => (
                                                                                <i
                                                                                    class={`ep-badge ${verdictCls(
                                                                                        mr()
                                                                                            .verdict,
                                                                                    )}`}
                                                                                    title={
                                                                                        mr()
                                                                                            .detail ||
                                                                                        ""
                                                                                    }
                                                                                >
                                                                                    {verdictText(
                                                                                        mr()
                                                                                            .verdict,
                                                                                    )}
                                                                                    {mr()
                                                                                        .latency_s
                                                                                        ? ` ${mr().latency_s}s`
                                                                                        : ""}
                                                                                </i>
                                                                            )}
                                                                        </Show>
                                                                    </td>
                                                                    <td class="ep-rowops">
                                                                        <button
                                                                            type="button"
                                                                            class="ep-op"
                                                                            title={
                                                                                ep()
                                                                                    .rowMoveUp
                                                                            }
                                                                            disabled={
                                                                                i ===
                                                                                0
                                                                            }
                                                                            onClick={() =>
                                                                                moveModel(
                                                                                    i,
                                                                                    -1,
                                                                                )
                                                                            }
                                                                        >
                                                                            ↑
                                                                        </button>
                                                                        <button
                                                                            type="button"
                                                                            class="ep-op"
                                                                            title={
                                                                                ep()
                                                                                    .rowMoveDown
                                                                            }
                                                                            disabled={
                                                                                i ===
                                                                                d()
                                                                                    .models
                                                                                    .length -
                                                                                    1
                                                                            }
                                                                            onClick={() =>
                                                                                moveModel(
                                                                                    i,
                                                                                    1,
                                                                                )
                                                                            }
                                                                        >
                                                                            ↓
                                                                        </button>
                                                                        <button
                                                                            type="button"
                                                                            class="ep-op"
                                                                            title={
                                                                                ep()
                                                                                    .rowDel
                                                                            }
                                                                            onClick={() =>
                                                                                removeModels(
                                                                                    new Set(
                                                                                        [
                                                                                            i,
                                                                                        ],
                                                                                    ),
                                                                                )
                                                                            }
                                                                        >
                                                                            ×
                                                                        </button>
                                                                    </td>
                                                                </tr>
                                                            )}
                                                        </For>
                                                    </Show>
                                                </tbody>
                                            </table>
                                        </Show>
                                    </div>
                                </div>
                                <footer class="ep-drawer-foot">
                                    <button
                                        type="button"
                                        class="btn-primary"
                                        disabled={
                                            !!busy() || !d().base_url.trim()
                                        }
                                        onClick={() => void saveDraft()}
                                    >
                                        {busy() === "draft"
                                            ? t.settings.saving
                                            : ep().save}
                                    </button>
                                    <button
                                        type="button"
                                        class="btn-ghost"
                                        onClick={() => setDraft(null)}
                                    >
                                        {ep().cancel}
                                    </button>
                                </footer>
                            </div>
                        </div>
                    )}
                </Show>

                {/* ============ 获取模型勾选器 ============ */}
                <Show when={fetchSt()}>
                    {(st) => (
                        <div
                            class="ep-veil ep-veil-top"
                            onClick={(e) => veilClick(e, () => setFetchSt(null))}
                        >
                            <div
                                class="ep-box"
                                role="dialog"
                                aria-modal="true"
                                aria-label={ep().fetchTitle}
                            >
                                <h3 class="ep-box-title">{ep().fetchTitle}</h3>
                                <Show
                                    when={fetchList()}
                                    fallback={
                                        <>
                                            <p class="muted">
                                                {st().kind === "loading"
                                                    ? ep().fetchLoading
                                                    : fetchErrText()}
                                            </p>
                                            <div class="ep-box-foot">
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    onClick={() =>
                                                        setFetchSt(null)
                                                    }
                                                >
                                                    {ep().cancel}
                                                </button>
                                            </div>
                                        </>
                                    }
                                >
                                    {(ls) => (
                                        <>
                                            <div class="ep-pick">
                                                <For each={ls().models}>
                                                    {(name) => (
                                                        <label class="ep-pick-item">
                                                            <input
                                                                type="checkbox"
                                                                checked={ls().checked.has(
                                                                    name,
                                                                )}
                                                                onChange={(
                                                                    e,
                                                                ) =>
                                                                    fetchToggle(
                                                                        name,
                                                                        e
                                                                            .currentTarget
                                                                            .checked,
                                                                    )
                                                                }
                                                            />
                                                            <code>{name}</code>
                                                        </label>
                                                    )}
                                                </For>
                                            </div>
                                            <p class="muted">
                                                {fmt(ep().pickCount, {
                                                    n: ls().checked.size,
                                                })}
                                            </p>
                                            <div class="ep-box-foot">
                                                <button
                                                    type="button"
                                                    class="btn-primary"
                                                    onClick={fetchConfirm}
                                                >
                                                    {ep().fetchConfirm}
                                                </button>
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    onClick={() =>
                                                        setFetchSt(null)
                                                    }
                                                >
                                                    {ep().cancel}
                                                </button>
                                            </div>
                                        </>
                                    )}
                                </Show>
                            </div>
                        </div>
                    )}
                </Show>

                {/* ============ 测试弹窗 ============ */}
                <Show when={testId()}>
                    {(pid) => {
                        const p = () =>
                            profiles().find((x) => x.id === pid());
                        return (
                            <div
                                class="ep-veil ep-veil-top"
                                onClick={(e) =>
                                    veilClick(e, () => setTestId(""))
                                }
                            >
                                <div
                                    class="ep-box"
                                    role="dialog"
                                    aria-modal="true"
                                    aria-label={ep().testTitle}
                                >
                                    <h3 class="ep-box-title">
                                        {ep().testTitle}——
                                        {p()?.label || pid()}
                                    </h3>
                                    <div class="ep-test-bar">
                                        <select
                                            value={testModel()}
                                            onChange={(e) =>
                                                setTestModel(
                                                    e.currentTarget.value,
                                                )
                                            }
                                        >
                                            <For each={p()?.models ?? []}>
                                                {(m) => (
                                                    <option value={m.model}>
                                                        {chipText(m)}
                                                    </option>
                                                )}
                                            </For>
                                        </select>
                                        <button
                                            type="button"
                                            class="btn-primary"
                                            disabled={
                                                !!probing() || !testModel()
                                            }
                                            onClick={() => void runTest()}
                                        >
                                            {probing()
                                                ? ep().testRunning
                                                : ep().testRun}
                                        </button>
                                    </div>
                                    <div class="ep-test-rows">
                                        <Show
                                            when={testRows().length > 0}
                                            fallback={
                                                <p class="muted">
                                                    {ep().testEmpty}
                                                </p>
                                            }
                                        >
                                            <For each={testRows()}>
                                                {(row) => (
                                                    <div class="ep-test-row">
                                                        <code>{row.name}</code>
                                                        <i
                                                            class={`ep-badge ${verdictCls(
                                                                row.verdict,
                                                            )}`}
                                                        >
                                                            {verdictText(
                                                                row.verdict,
                                                            )}
                                                            {row.latency_s
                                                                ? ` ${row.latency_s}s`
                                                                : ""}
                                                        </i>
                                                        <Show
                                                            when={
                                                                row.listed ===
                                                                false
                                                            }
                                                        >
                                                            <span class="muted">
                                                                {
                                                                    ep()
                                                                        .unlisted
                                                                }
                                                            </span>
                                                        </Show>
                                                        <Show when={row.detail}>
                                                            <span
                                                                class="muted ep-test-detail"
                                                                title={
                                                                    row.detail
                                                                }
                                                            >
                                                                {row.detail}
                                                            </span>
                                                        </Show>
                                                    </div>
                                                )}
                                            </For>
                                        </Show>
                                    </div>
                                    <div class="ep-box-foot">
                                        <button
                                            type="button"
                                            class="btn-ghost"
                                            onClick={() => setTestId("")}
                                        >
                                            {ep().close}
                                        </button>
                                    </div>
                                </div>
                            </div>
                        );
                    }}
                </Show>

                {/* ============ 排序弹窗 ============ */}
                <Show when={sortIds()}>
                    {(ids) => (
                        <div
                            class="ep-veil ep-veil-top"
                            onClick={(e) => veilClick(e, () => setSortIds(null))}
                        >
                            <div
                                class="ep-box"
                                role="dialog"
                                aria-modal="true"
                                aria-label={ep().sortTitle}
                            >
                                <h3 class="ep-box-title">{ep().sortTitle}</h3>
                                <p class="muted">{ep().sortHint}</p>
                                <ul class="ep-sort">
                                    <For each={ids()}>
                                        {(id, i) => {
                                            const p = () =>
                                                profiles().find(
                                                    (x) => x.id === id,
                                                );
                                            return (
                                                <li
                                                    class="ep-sort-item"
                                                    draggable
                                                    onDragStart={() => {
                                                        sortDragIdx = i();
                                                    }}
                                                    onDragOver={(e) =>
                                                        e.preventDefault()
                                                    }
                                                    onDrop={() => sortDrop(i())}
                                                >
                                                    <span class="ep-grip">
                                                        ⋮⋮
                                                    </span>
                                                    <span>
                                                        {p()?.label || id}
                                                    </span>
                                                    <span class="muted ep-sort-url">
                                                        {p()?.base_url}
                                                    </span>
                                                </li>
                                            );
                                        }}
                                    </For>
                                </ul>
                                <div class="ep-box-foot">
                                    <button
                                        type="button"
                                        class="btn-primary"
                                        disabled={!!busy()}
                                        onClick={() => void saveSort()}
                                    >
                                        {busy() === "sort"
                                            ? t.settings.saving
                                            : ep().save}
                                    </button>
                                    <button
                                        type="button"
                                        class="btn-ghost"
                                        onClick={() => setSortIds(null)}
                                    >
                                        {ep().cancel}
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}
                </Show>

                {/* ============ 删除确认 ============ */}
                <Show when={delTarget()}>
                    {(p) => (
                        <div
                            class="ep-veil ep-veil-top"
                            onClick={(e) =>
                                veilClick(e, () => setDelTarget(null))
                            }
                        >
                            <div
                                class="ep-box"
                                role="alertdialog"
                                aria-modal="true"
                                aria-label={ep().delTitle}
                            >
                                <h3 class="ep-box-title">{ep().delTitle}</h3>
                                <p>
                                    {fmt(ep().delConfirm, {
                                        label: p().label || p().id,
                                    })}
                                </p>
                                <div class="ep-box-foot">
                                    <button
                                        type="button"
                                        class="btn-ghost"
                                        onClick={() => setDelTarget(null)}
                                    >
                                        {ep().cancel}
                                    </button>
                                    <button
                                        type="button"
                                        class="btn-primary ep-danger"
                                        disabled={!!busy()}
                                        onClick={() => void confirmDelete()}
                                    >
                                        {ep().del}
                                    </button>
                                </div>
                            </div>
                        </div>
                    )}
                </Show>
            </section>
        </Show>
    );
}
