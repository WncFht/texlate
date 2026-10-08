// ChannelsPanel —— BYOK 渠道卡面（channels.json 的 UI 面，ccLoad 式渠道管理）：
// 路由条（auto/钉渠道 + 目标模型 datalist）+ 卡片 model(redirect) chips +
// 右侧抽屉编辑（基本/凭据/模型三节）+ 模型行式表格（勾选批处理/行内搜索/
// 重定向列/逐行并发与启用）+ 获取模型勾选器 + 逐模型测试弹窗 + 拖拽排序
// 弹窗 + 删除确认弹窗。
//
// server 形态整面 403：store.channelsOff() 置位 → 整块不渲染。
// 写径整表替换（PUT channels[] + 可选 route）——启用/删除/排序/编辑全折成
// 全量写；priority 由前端按展示序每次重发稀疏序号（(len-idx)*10，服务端
// 不重编号、按写入值路由）。凭据写语义（api_key="" 承旧值、api_key|key_env
// 互斥）由服务端归一，本面只造写行：读面不回 key，未触碰凭据的行凭据键
// 缺席送出（=承旧值）。路由选择走独立 POST /channels/route，不动渠道表。
//
// 模型条目 {model, redirect_model, enabled, max_concurrency}：model 是本地名
// （展示/探针报告键），redirect_model 是上游请求名（空串=本名直发），
// max_concurrency null=只受渠道/全局闸约束。子集探测按本地名发
// {id, models:[name]}，服务端按渠道 redirect 解析出上游名。

import {
    createEffect,
    createSignal,
    For,
    onCleanup,
    onMount,
    Show,
} from "solid-js";
import {
    apiErrText,
    type Channel,
    type ChannelModel,
    type ChannelPreset,
    type ChannelWrite,
    type ProbeReport,
} from "../api/client";
import { fmt, t } from "../i18n";
import { API_DIALECTS, segOptsWithCurrent } from "../options";
import { settingsStore } from "../stores/settings";
import Segmented from "./Segmented";

const MAX_MODELS = 8;
/** 卡片 chips 直显上限——超出折叠 +N */
const CHIP_MAX = 4;
/** 相邻渠道 priority 间距——写径按展示序重发稀疏序号（对齐服务端 PRIORITY_STEP） */
const PRIORITY_STEP = 10;
/** 渠道/模型并发上限域（与服务端 MAX_CONCURRENCY_CAP 同值） */
const MAX_CONC = 64;

/** 编辑/新建草稿——models 是可编行表，凭据两态互斥 */
interface Draft {
    /** 编辑时带原 id；新建为 ""（保存时服务端生成 ch-<8hex>） */
    id: string;
    name: string;
    preset: string;
    base_url: string;
    protocol: string;
    models: ChannelModel[];
    enabled: boolean;
    /** 沿用现值；保存时按展示序重发 */
    priority: number;
    /** null = 不限 */
    max_concurrency: number | null;
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

/** 并发输入格 → number|null（空/非正 → null=不限；>0 clamp 1..64） */
const concOf = (raw: string): number | null => {
    const n = Number.parseInt(raw, 10);
    if (!Number.isFinite(n) || n <= 0) return null;
    return Math.min(MAX_CONC, n);
};

/** 读面行 → 写面行（凭据键缺席 = 承旧值） */
const writeOf = (c: Channel): ChannelWrite => ({
    id: c.id,
    name: c.name,
    preset: c.preset,
    base_url: c.base_url,
    protocol: c.protocol,
    models: c.models.map((m) => ({ ...m })),
    priority: c.priority,
    max_concurrency: c.max_concurrency,
    enabled: c.enabled,
});

const draftOf = (c: Channel): Draft => ({
    id: c.id,
    name: c.name,
    preset: c.preset,
    base_url: c.base_url,
    protocol: c.protocol,
    models: c.models.map((m) => ({ ...m })),
    enabled: c.enabled,
    priority: c.priority,
    max_concurrency: c.max_concurrency,
    cred: c.key_env ? "env" : "key",
    api_key: "",
    key_env: c.key_env,
});

const blankDraft = (): Draft => ({
    id: "",
    name: "",
    preset: "custom",
    base_url: "",
    protocol: "auto",
    models: [],
    enabled: true,
    priority: 0,
    max_concurrency: null,
    cred: "key",
    api_key: "",
    key_env: "",
});

/** 草稿 → 写行：空名行丢弃、按本地名去重保序、≤8 截断（服务端兜底再验） */
const draftToWrite = (d: Draft): ChannelWrite => {
    const seen = new Set<string>();
    const models: ChannelModel[] = [];
    for (const m of d.models) {
        const name = m.model.trim();
        const red = m.redirect_model.trim();
        if (!name || seen.has(name)) continue;
        seen.add(name);
        models.push({
            model: name,
            redirect_model: red === name ? "" : red,
            enabled: m.enabled,
            max_concurrency: m.max_concurrency,
        });
    }
    return {
        id: d.id || undefined,
        name: d.name.trim(),
        preset: d.preset,
        base_url: d.base_url.trim(),
        protocol: d.protocol,
        models: models.slice(0, MAX_MODELS),
        priority: d.priority,
        max_concurrency: d.max_concurrency,
        enabled: d.enabled,
        api_key: d.cred === "key" ? d.api_key.trim() : "",
        key_env: d.cred === "env" ? d.key_env.trim() : "",
    };
};

/** 展示名：name(red)；无 redirect 只显名 */
const chipText = (m: ChannelModel): string =>
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
const verdictText = (v: string): string => t.settings.channels.verdicts[v] ?? v;

/** 凭据三态展示行（读面只见 has_api_key / key_env 名 / has_env_key） */
const credText = (c: Channel): string => {
    const ep = t.settings.channels;
    if (c.has_api_key) return ep.credKeySet;
    if (c.key_env)
        return fmt(c.has_env_key ? ep.credEnvSet : ep.credEnvUnset, {
            name: c.key_env,
        });
    return ep.credNone;
};

/** 报告时效展示——ISO 截到分（秒级噪声无信息量） */
const probeAt = (r?: ProbeReport | null): string => {
    const at = r?.at ?? "";
    return at ? at.slice(0, 16).replace("T", " ") : "";
};

export default function ChannelsPanel() {
    const [draft, setDraft] = createSignal<Draft | null>(null);
    const [sec, setSec] = createSignal<DrawerSec>("basic");
    const [busy, setBusy] = createSignal(""); // channel id | "draft" | "sort"
    const [probing, setProbing] = createSignal("");
    /** 本地探测回执（{id} 路服务端已钉 last_probe，本图兜刷新失败的即时显示） */
    const [probeOut, setProbeOut] = createSignal<Record<string, ProbeReport>>(
        {},
    );
    const [msg, setMsg] = createSignal("");
    const [msgErr, setMsgErr] = createSignal(false);
    // ---- 路由条态 ----
    const [routeCh, setRouteCh] = createSignal("auto");
    const [routeModel, setRouteModel] = createSignal("");
    /** 用户已动路由控件但尚未保存成功——回包/刷新不回灌盖掉在编辑的值 */
    let routeDirty = false;
    // ---- 模型表格态（草稿内）----
    const [modelSel, setModelSel] = createSignal<Set<number>>(new Set());
    const [modelFilter, setModelFilter] = createSignal("");
    // ---- 弹窗态 ----
    const [fetchSt, setFetchSt] = createSignal<FetchState | null>(null);
    const [testId, setTestId] = createSignal("");
    const [testModel, setTestModel] = createSignal("");
    const [testRows, setTestRows] = createSignal<TestRow[]>([]);
    const [sortIds, setSortIds] = createSignal<string[] | null>(null);
    const [delTarget, setDelTarget] = createSignal<Channel | null>(null);
    let sortDragIdx = -1;

    onMount(() => {
        void settingsStore.refreshChannels().catch(() => {});
        void settingsStore.refreshChannelPresets();
    });

    const ep = () => t.settings.channels;
    const view = () => settingsStore.channels();
    /** 展示序 = priority 降序（路由求值同序——上者优先） */
    const channels = () =>
        [...(view()?.channels ?? [])].sort((a, b) => b.priority - a.priority);
    const presets = () => settingsStore.channelPresets();
    const reportOf = (c: Channel) => probeOut()[c.id] ?? c.last_probe ?? null;
    const presetOf = (id: string): ChannelPreset | undefined =>
        presets().find((p) => p.id === id);
    const presetName = (id: string): string =>
        presetOf(id)?.name ?? (id === "custom" ? "" : id);
    /** 当前生效渠道展示名——按 active_id 反查渠道名，查不到回显裸 id */
    const activeName = (): string => {
        const id = view()?.active_id ?? "";
        return channels().find((c) => c.id === id)?.name || id;
    };

    // 服务端 route → 本地控件值回灌（用户编辑中不盖）
    createEffect(() => {
        const r = view()?.route;
        if (!r || routeDirty) return;
        setRouteCh(r.channel_id || "auto");
        setRouteModel(r.model || "");
    });

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

    /** 全量写公共臂：rows 已是展示序——按位次重发稀疏 priority 后 PUT */
    const saveTable = async (rows: ChannelWrite[]) => {
        const numbered = rows.map((r, i) => ({
            ...r,
            priority: (rows.length - i) * PRIORITY_STEP,
        }));
        await settingsStore.saveChannels(numbered);
    };

    // ------------------------------------------------------------ 路由条

    /** 目标模型 datalist 候选：钉渠道 → 该渠道本地名；auto → 全启用渠道并集 */
    const routeModelOpts = (): string[] => {
        const cid = routeCh();
        const pool =
            cid === "auto"
                ? channels().filter((c) => c.enabled)
                : channels().filter((c) => c.id === cid);
        const out: string[] = [];
        for (const c of pool)
            for (const m of c.models)
                if (!out.includes(m.model)) out.push(m.model);
        return out;
    };

    const saveRoute = async (channel_id: string, model: string) => {
        if (busy()) return;
        setBusy("route");
        setMsg("");
        try {
            await settingsStore.setChannelRoute({
                channel_id,
                model: model.trim(),
            });
            routeDirty = false;
            ok(ep().routeSaved);
        } catch (e) {
            fail(`${ep().routeFailed}：${apiErrText(e)}`);
        } finally {
            setBusy("");
        }
    };

    const pinRoute = (c: Channel) => {
        routeDirty = true;
        setRouteCh(c.id);
        void saveRoute(c.id, routeModel());
    };

    // ------------------------------------------------------------ 卡片操作

    const toggleEnabled = async (c: Channel) => {
        if (busy()) return;
        setBusy(c.id);
        setMsg("");
        try {
            await saveTable(
                channels().map((x) => ({
                    ...writeOf(x),
                    enabled: x.id === c.id ? !x.enabled : x.enabled,
                })),
            );
        } catch (e) {
            fail(`${ep().saveFailed}：${apiErrText(e)}`);
        } finally {
            setBusy("");
        }
    };

    const confirmDelete = async () => {
        const c = delTarget();
        if (!c || busy()) return;
        setBusy(c.id);
        setMsg("");
        try {
            await saveTable(
                channels()
                    .filter((x) => x.id !== c.id)
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

    /** 选预设 → 预填 name/base_url/protocol/key_env：只填空槽或仍挂着旧预设值的槽，不盖用户手改 */
    const applyPreset = (presetId: string) => {
        const d = draft();
        const next = presetOf(presetId);
        if (!d || !next) {
            up({ preset: presetId });
            return;
        }
        const prev = presetOf(d.preset);
        const patch: Partial<Draft> = { preset: presetId };
        if (!d.base_url.trim() || d.base_url === prev?.base_url)
            patch.base_url = next.base_url;
        if (!d.name.trim() || d.name === prev?.name) patch.name = next.name;
        if (!d.protocol || d.protocol === prev?.protocol)
            patch.protocol = next.protocol;
        if (d.cred === "env" && (!d.key_env.trim() || d.key_env === prev?.key_env))
            patch.key_env = next.key_env;
        up(patch);
    };

    const saveDraft = async () => {
        const d = draft();
        if (!d || busy()) return;
        setBusy("draft");
        setMsg("");
        try {
            const cur = channels();
            const rows = cur.map(writeOf);
            const w = draftToWrite(d);
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

    /** 行字段更新（按数组下标，For 渲染行不动） */
    const setModel = (i: number, patch: Partial<ChannelModel>) =>
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

    const blankModel = (): ChannelModel => ({
        model: "",
        redirect_model: "",
        enabled: true,
        max_concurrency: null,
    });

    const addModel = () => {
        const d = draft();
        if (!d || d.models.length >= MAX_MODELS) return;
        up({ models: [...d.models, blankModel()] });
    };

    /** 批处理：对勾选下标跑 f(entry)→entry（保留勾选） */
    const batchMap = (f: (m: ChannelModel) => ChannelModel) => {
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
            enabled: m.enabled,
            max_concurrency: m.max_concurrency,
        }));

    const batchStrip = () =>
        batchMap((m) => ({ ...m, model: stripPrefix(m.model) }));

    const batchEnable = (on: boolean) =>
        batchMap((m) => ({ ...m, enabled: on }));

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
        const c = channels().find((x) => x.id === d.id);
        const rep = c ? reportOf(c) : null;
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
            const saved = channels().find((x) => x.id === d.id);
            const urlSame =
                !!saved &&
                d.base_url.trim().replace(/\/+$/, "") ===
                    saved.base_url.replace(/\/+$/, "");
            if (d.cred === "key" && d.api_key.trim()) {
                r = await settingsStore.probeChannelBare({
                    base_url: d.base_url.trim(),
                    api_key: d.api_key.trim(),
                    protocol: d.protocol,
                    models: [],
                });
            } else if (d.id && urlSame) {
                r = await settingsStore.probeChannel(d.id, []);
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
            .map((n) => ({ ...blankModel(), model: n }));
        up({ models: [...d.models, ...add].slice(0, MAX_MODELS) });
        setFetchSt(null);
    };

    // ------------------------------------------------------------ 测试弹窗

    const openTest = (c: Channel) => {
        setTestId(c.id);
        setTestModel(c.models[0]?.model ?? "");
        setTestRows([]);
    };

    const runTest = async () => {
        const cid = testId();
        const name = testModel();
        if (!cid || !name || probing()) return;
        setProbing(cid);
        setMsg("");
        try {
            const r = await settingsStore.probeChannel(cid, [name]);
            setProbeOut((m) => ({ ...m, [cid]: r }));
            const rows: TestRow[] = Object.entries(r.models ?? {}).map(
                ([uid, mr]) => ({
                    name: uid,
                    verdict: mr.verdict,
                    latency_s: mr.latency_s,
                    detail: mr.detail,
                    listed: mr.listed,
                }),
            );
            // 没出模型行时 stage1 本身就是结果（渠道死全段 skipped/空）
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

    const openSort = () => setSortIds(channels().map((c) => c.id));

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
        const byId = new Map(channels().map((c) => [c.id, c]));
        const rows = ids
            .map((id) => byId.get(id))
            .filter((c): c is Channel => !!c)
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
        <Show when={!settingsStore.channelsOff()}>
            <section class="chs" aria-label={ep().title}>
                <h2>
                    {ep().title}
                    <em class="muted">{ep().hint}</em>
                </h2>
                <Show
                    when={view()}
                    fallback={<p class="muted">{t.pane.loading}</p>}
                >
                    {/* ============ 路由条 ============ */}
                    <div class="ch-route">
                        <span class="ch-route-label">{ep().route}</span>
                        <select
                            value={routeCh()}
                            disabled={!!busy()}
                            onChange={(e) => {
                                routeDirty = true;
                                setRouteCh(e.currentTarget.value);
                                void saveRoute(
                                    e.currentTarget.value,
                                    routeModel(),
                                );
                            }}
                        >
                            <option value="auto">{ep().routeAuto}</option>
                            <For each={channels()}>
                                {(c) => (
                                    <option value={c.id}>
                                        {c.name || c.id}
                                        {c.enabled
                                            ? ""
                                            : `（${ep().disabledTag}）`}
                                    </option>
                                )}
                            </For>
                        </select>
                        <input
                            id="ch-route-model"
                            list="ch-route-models"
                            placeholder={ep().routeModelPh}
                            value={routeModel()}
                            disabled={!!busy()}
                            onInput={(e) => {
                                routeDirty = true;
                                setRouteModel(e.currentTarget.value);
                            }}
                            onChange={(e) =>
                                void saveRoute(
                                    routeCh(),
                                    e.currentTarget.value,
                                )
                            }
                        />
                        <datalist id="ch-route-models">
                            <For each={routeModelOpts()}>
                                {(name) => <option value={name} />}
                            </For>
                        </datalist>
                        <em class="muted ch-route-hint">{ep().routeHint}</em>
                    </div>
                    {/* 路由的下一请求真实决议（active_id/active_model）——与
                        钉选态分开显示：pin 只改 route.channel_id，生效看决议 */}
                    <p class="ch-active muted">
                        {ep().activeNow}：
                        {view()?.active_id
                            ? `${activeName()} · ${view()?.active_model}`
                            : ep().activeNone}
                    </p>
                    <Show
                        when={channels().length > 0}
                        fallback={
                            <p class="muted">
                                {ep().empty}{" "}
                                <button
                                    type="button"
                                    class="btn-primary"
                                    onClick={() => openDraft(blankDraft())}
                                >
                                    {ep().addTitle}
                                </button>
                            </p>
                        }
                    >
                        <ul class="ch-list">
                            <For each={channels()}>
                                {(c) => {
                                    const rep = () => reportOf(c);
                                    return (
                                        <li
                                            class="ch-card"
                                            classList={{ off: !c.enabled }}
                                        >
                                            <div class="ch-head">
                                                <strong>{c.name || c.id}</strong>
                                                <Show when={presetName(c.preset)}>
                                                    <span class="ch-preset">
                                                        {presetName(c.preset)}
                                                    </span>
                                                </Show>
                                                {/* 生效标 = 路由决议命中
                                                    （active_id）——非钉选态；
                                                    钉选看路由条 select 现值 */}
                                                <Show
                                                    when={
                                                        view()?.active_id ===
                                                        c.id
                                                    }
                                                >
                                                    <span class="ch-badge ok">
                                                        {ep().routedBadge}
                                                    </span>
                                                </Show>
                                                <span class="ch-spacer" />
                                                <label class="ch-toggle">
                                                    <input
                                                        type="checkbox"
                                                        checked={c.enabled}
                                                        disabled={!!busy()}
                                                        onChange={() =>
                                                            void toggleEnabled(
                                                                c,
                                                            )
                                                        }
                                                    />
                                                    {ep().enabledTip}
                                                </label>
                                            </div>
                                            <div class="ch-url">{c.base_url}</div>
                                            <Show when={c.models.length > 0}>
                                                <div class="ch-models">
                                                    <For
                                                        each={c.models.slice(
                                                            0,
                                                            CHIP_MAX,
                                                        )}
                                                    >
                                                        {(m) => (
                                                            <code
                                                                class="ch-chip"
                                                                classList={{
                                                                    off: !m.enabled,
                                                                }}
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
                                                                    <i class="ch-chip-red">
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
                                                            c.models.length >
                                                            CHIP_MAX
                                                        }
                                                    >
                                                        <code class="ch-chip ch-more">
                                                            {fmt(ep().moreN, {
                                                                n:
                                                                    c.models
                                                                        .length -
                                                                    CHIP_MAX,
                                                            })}
                                                        </code>
                                                    </Show>
                                                </div>
                                            </Show>
                                            <div class="ch-meta">
                                                <span>{credText(c)}</span>
                                                <span class="muted">
                                                    {fmt(ep().priorityN, {
                                                        n: c.priority,
                                                    })}
                                                </span>
                                                <Show when={c.max_concurrency}>
                                                    <span class="muted">
                                                        {fmt(ep().concN, {
                                                            n:
                                                                c.max_concurrency ??
                                                                0,
                                                        })}
                                                    </span>
                                                </Show>
                                                <Show when={rep()}>
                                                    {(r) => (
                                                        <span class="ch-probe">
                                                            {fmt(ep().at, {
                                                                at: probeAt(
                                                                    r(),
                                                                ),
                                                            })}
                                                            <i
                                                                class={`ch-badge ${verdictCls(
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
                                            <div class="ch-actions">
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    disabled={
                                                        !!busy() ||
                                                        view()?.route
                                                            .channel_id ===
                                                            c.id
                                                    }
                                                    onClick={() => pinRoute(c)}
                                                >
                                                    {ep().pinRoute}
                                                </button>
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    disabled={!!probing()}
                                                    onClick={() => openTest(c)}
                                                >
                                                    {ep().probe}
                                                </button>
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    onClick={() =>
                                                        openDraft(draftOf(c))
                                                    }
                                                >
                                                    {ep().edit}
                                                </button>
                                                <button
                                                    type="button"
                                                    class="btn-ghost"
                                                    disabled={!!busy()}
                                                    onClick={() =>
                                                        setDelTarget(c)
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
                    <div class="ch-foot">
                        <button
                            type="button"
                            class="btn-ghost"
                            onClick={() => openDraft(blankDraft())}
                        >
                            {ep().add}
                        </button>
                        <Show when={channels().length > 1}>
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
                            class="ch-veil"
                            onClick={(e) => veilClick(e, () => setDraft(null))}
                        >
                            <div
                                class="ch-drawer"
                                role="dialog"
                                aria-modal="true"
                                aria-label={
                                    d().id ? ep().editTitle : ep().addTitle
                                }
                            >
                                <header class="ch-drawer-head">
                                    <h3>
                                        {d().id ? ep().editTitle : ep().addTitle}
                                    </h3>
                                    <button
                                        type="button"
                                        class="ch-x"
                                        aria-label={ep().close}
                                        onClick={() => setDraft(null)}
                                    >
                                        ×
                                    </button>
                                </header>
                                <div class="ch-drawer-body">
                                    <nav class="ch-nav">
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
                                                    class="ch-nav-item"
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
                                    <div class="ch-sec">
                                        {/* ---- 基本 ---- */}
                                        <Show when={sec() === "basic"}>
                                            <label>
                                                <span>{ep().preset}</span>
                                                <select
                                                    value={d().preset}
                                                    onChange={(e) =>
                                                        applyPreset(
                                                            e.currentTarget
                                                                .value,
                                                        )
                                                    }
                                                >
                                                    <Show
                                                        when={
                                                            !presetOf(
                                                                d().preset,
                                                            )
                                                        }
                                                    >
                                                        <option
                                                            value={d().preset}
                                                        >
                                                            {d().preset}
                                                        </option>
                                                    </Show>
                                                    <For
                                                        each={[
                                                            ...presets(),
                                                            ...(presetOf(
                                                                "custom",
                                                            )
                                                                ? []
                                                                : [
                                                                      {
                                                                          id: "custom",
                                                                          name: "Custom",
                                                                          protocol:
                                                                              "auto",
                                                                          base_url:
                                                                              "",
                                                                          models: [],
                                                                          key_env:
                                                                              "",
                                                                          has_env_key:
                                                                              false,
                                                                      } satisfies ChannelPreset,
                                                                  ]),
                                                        ]}
                                                    >
                                                        {(p) => (
                                                            <option
                                                                value={p.id}
                                                            >
                                                                {p.name}
                                                            </option>
                                                        )}
                                                    </For>
                                                </select>
                                            </label>
                                            <label>
                                                <span>{ep().name}</span>
                                                <input
                                                    value={d().name}
                                                    placeholder={ep().namePh}
                                                    onInput={(e) =>
                                                        up({
                                                            name: e
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
                                                        d().protocol,
                                                        (x) =>
                                                            x === "auto"
                                                                ? t.settings
                                                                      .dialectAuto
                                                                : x,
                                                    )}
                                                    value={d().protocol}
                                                    onChange={(v) =>
                                                        up({ protocol: v })
                                                    }
                                                    ariaLabel={
                                                        t.settings.dialect
                                                    }
                                                />
                                            </div>
                                            <label>
                                                <span>{ep().maxConc}</span>
                                                <input
                                                    type="number"
                                                    min={1}
                                                    max={MAX_CONC}
                                                    placeholder={
                                                        ep().maxConcPh
                                                    }
                                                    value={
                                                        d().max_concurrency ??
                                                        ""
                                                    }
                                                    onInput={(e) =>
                                                        up({
                                                            max_concurrency:
                                                                concOf(
                                                                    e
                                                                        .currentTarget
                                                                        .value,
                                                                ),
                                                        })
                                                    }
                                                />
                                            </label>
                                            <label class="ch-toggle">
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
                                                            channels().find(
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
                                            <div class="ch-mtools">
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
                                                <span class="ch-spacer" />
                                                <span class="muted">
                                                    {fmt(ep().modelsCount, {
                                                        n: d().models.length,
                                                    })}
                                                </span>
                                            </div>
                                            <Show when={modelSel().size > 0}>
                                                <div class="ch-mbatch">
                                                    <span>
                                                        {fmt(ep().selN, {
                                                            n: modelSel().size,
                                                        })}
                                                    </span>
                                                    <button
                                                        type="button"
                                                        class="btn-ghost"
                                                        onClick={() =>
                                                            batchEnable(true)
                                                        }
                                                    >
                                                        {ep().batchEnable}
                                                    </button>
                                                    <button
                                                        type="button"
                                                        class="btn-ghost"
                                                        onClick={() =>
                                                            batchEnable(false)
                                                        }
                                                    >
                                                        {ep().batchDisable}
                                                    </button>
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
                                            <table class="ch-mtable">
                                                <thead>
                                                    <tr>
                                                        <th class="ch-cb">
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
                                                        <th class="ch-idx">
                                                            #
                                                        </th>
                                                        <th>
                                                            {ep().colName}
                                                            <input
                                                                class="ch-th-search"
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
                                                        <th class="ch-conc">
                                                            {ep().colConc}
                                                        </th>
                                                        <th class="ch-on">
                                                            {ep().colEnabled}
                                                        </th>
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
                                                                    colspan={8}
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
                                                                <tr
                                                                    classList={{
                                                                        off: !d()
                                                                            .models[
                                                                            i
                                                                        ]
                                                                            .enabled,
                                                                    }}
                                                                >
                                                                    <td class="ch-cb">
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
                                                                    <td class="ch-idx">
                                                                        {i + 1}
                                                                    </td>
                                                                    <td>
                                                                        <input
                                                                            class="ch-cell-in"
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
                                                                            class="ch-cell-in"
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
                                                                    <td class="ch-conc">
                                                                        <input
                                                                            type="number"
                                                                            min={1}
                                                                            max={
                                                                                MAX_CONC
                                                                            }
                                                                            class="ch-cell-in"
                                                                            placeholder="∞"
                                                                            value={
                                                                                d()
                                                                                    .models[
                                                                                    i
                                                                                ]
                                                                                    .max_concurrency ??
                                                                                ""
                                                                            }
                                                                            onInput={(
                                                                                e,
                                                                            ) =>
                                                                                setModel(
                                                                                    i,
                                                                                    {
                                                                                        max_concurrency:
                                                                                            concOf(
                                                                                                e
                                                                                                    .currentTarget
                                                                                                    .value,
                                                                                            ),
                                                                                    },
                                                                                )
                                                                            }
                                                                        />
                                                                    </td>
                                                                    <td class="ch-on">
                                                                        <input
                                                                            type="checkbox"
                                                                            checked={
                                                                                d()
                                                                                    .models[
                                                                                    i
                                                                                ]
                                                                                    .enabled
                                                                            }
                                                                            onChange={(
                                                                                e,
                                                                            ) =>
                                                                                setModel(
                                                                                    i,
                                                                                    {
                                                                                        enabled:
                                                                                            e
                                                                                                .currentTarget
                                                                                                .checked,
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
                                                                                    class={`ch-badge ${verdictCls(
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
                                                                    <td class="ch-rowops">
                                                                        <button
                                                                            type="button"
                                                                            class="ch-op"
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
                                                                            class="ch-op"
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
                                                                            class="ch-op"
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
                                <footer class="ch-drawer-foot">
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
                            class="ch-veil ch-veil-top"
                            onClick={(e) => veilClick(e, () => setFetchSt(null))}
                        >
                            <div
                                class="ch-box"
                                role="dialog"
                                aria-modal="true"
                                aria-label={ep().fetchTitle}
                            >
                                <h3 class="ch-box-title">{ep().fetchTitle}</h3>
                                <Show
                                    when={fetchList()}
                                    fallback={
                                        <>
                                            <p class="muted">
                                                {st().kind === "loading"
                                                    ? ep().fetchLoading
                                                    : fetchErrText()}
                                            </p>
                                            <div class="ch-box-foot">
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
                                            <div class="ch-pick">
                                                <For each={ls().models}>
                                                    {(name) => (
                                                        <label class="ch-pick-item">
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
                                            <div class="ch-box-foot">
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
                    {(cid) => {
                        const c = () =>
                            channels().find((x) => x.id === cid());
                        return (
                            <div
                                class="ch-veil ch-veil-top"
                                onClick={(e) =>
                                    veilClick(e, () => setTestId(""))
                                }
                            >
                                <div
                                    class="ch-box"
                                    role="dialog"
                                    aria-modal="true"
                                    aria-label={ep().testTitle}
                                >
                                    <h3 class="ch-box-title">
                                        {ep().testTitle}——
                                        {c()?.name || cid()}
                                    </h3>
                                    <div class="ch-test-bar">
                                        <select
                                            value={testModel()}
                                            onChange={(e) =>
                                                setTestModel(
                                                    e.currentTarget.value,
                                                )
                                            }
                                        >
                                            <For each={c()?.models ?? []}>
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
                                    <div class="ch-test-rows">
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
                                                    <div class="ch-test-row">
                                                        <code>{row.name}</code>
                                                        <i
                                                            class={`ch-badge ${verdictCls(
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
                                                                class="muted ch-test-detail"
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
                                    <div class="ch-box-foot">
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
                            class="ch-veil ch-veil-top"
                            onClick={(e) => veilClick(e, () => setSortIds(null))}
                        >
                            <div
                                class="ch-box"
                                role="dialog"
                                aria-modal="true"
                                aria-label={ep().sortTitle}
                            >
                                <h3 class="ch-box-title">{ep().sortTitle}</h3>
                                <p class="muted">{ep().sortHint}</p>
                                <ul class="ch-sort">
                                    <For each={ids()}>
                                        {(id, i) => {
                                            const c = () =>
                                                channels().find(
                                                    (x) => x.id === id,
                                                );
                                            return (
                                                <li
                                                    class="ch-sort-item"
                                                    draggable
                                                    onDragStart={() => {
                                                        sortDragIdx = i();
                                                    }}
                                                    onDragOver={(e) =>
                                                        e.preventDefault()
                                                    }
                                                    onDrop={() => sortDrop(i())}
                                                >
                                                    <span class="ch-grip">
                                                        ⋮⋮
                                                    </span>
                                                    <span>
                                                        {c()?.name || id}
                                                    </span>
                                                    <span class="muted ch-sort-url">
                                                        {c()?.base_url}
                                                    </span>
                                                </li>
                                            );
                                        }}
                                    </For>
                                </ul>
                                <div class="ch-box-foot">
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
                    {(c) => (
                        <div
                            class="ch-veil ch-veil-top"
                            onClick={(e) =>
                                veilClick(e, () => setDelTarget(null))
                            }
                        >
                            <div
                                class="ch-box"
                                role="alertdialog"
                                aria-modal="true"
                                aria-label={ep().delTitle}
                            >
                                <h3 class="ch-box-title">{ep().delTitle}</h3>
                                <p>
                                    {fmt(ep().delConfirm, {
                                        label: c().name || c().id,
                                    })}
                                </p>
                                <div class="ch-box-foot">
                                    <button
                                        type="button"
                                        class="btn-ghost"
                                        onClick={() => setDelTarget(null)}
                                    >
                                        {ep().cancel}
                                    </button>
                                    <button
                                        type="button"
                                        class="btn-primary ch-danger"
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
