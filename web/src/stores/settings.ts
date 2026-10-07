// BYOK 设置 store —— GET 永不回 key 本体，只回 has_api_key（§2.5）。

import { createSignal } from "solid-js";
import {
    api,
    ApiError,
    type EndpointProfileWrite,
    type EndpointsView,
    type ProbeReport,
    type Provider,
    type Settings,
} from "../api/client";

const [settings, setSettings] = createSignal<Settings | null>(null);
const [providers, setProviders] = createSignal<Provider[]>([]);
const [loaded, setLoaded] = createSignal(false);

// ---- 端点档案（endpoints.json UI 面；local 形态限定）----
// server 形态整面 403：endpointsOff 置位后 Settings 页隐藏整块。
const [endpoints, setEndpoints] = createSignal<EndpointsView | null>(null);
const [endpointsOff, setEndpointsOff] = createSignal(false);

// ---- 外观（单轴合并，§ADR-0020 二次追加）----
// 8 档色板是全站唯一外观轴：纸面配色与 chrome 同源派生，不再存在独立
// 「界面主题」。auto=OS 对（亮→原纸+亮 chrome；暗→暖黑对）；
// none=原纸+OS chrome（逃生口：暗 OS 下仍可达白纸+暗界面）；
// 命名槽=锁定 {纸面,chrome} 对。OS 监听与 chrome 落点在 pdfTheme.ts。
export type PaperThemeChoice =
    "auto" | "none" | "dark" | "onedark" | "black" | "snow" | "sepia" | "paper";
const PAPER_KEY = "texlate-paper-theme";

const readPaperTheme = (): PaperThemeChoice => {
    try {
        const v = localStorage.getItem(PAPER_KEY);
        if (
            v === "auto" ||
            v === "none" ||
            v === "dark" ||
            v === "onedark" ||
            v === "black" ||
            v === "snow" ||
            v === "sepia" ||
            v === "paper"
        )
            return v;
        if (v === null) {
            // 单轴合并迁移：旧全局主题键折成语义等价的锁定色板档
            // （light→暖纸=旧亮 chrome 原值；dark→暖黑=旧暗 chrome+暗纸对）
            const t0 = localStorage.getItem("texlate-theme");
            if (t0 === "dark") return "dark";
            if (t0 === "light") return "paper";
        }
    } catch {
        /* localStorage 禁用/node 环境 */
    }
    return "auto";
};

const [paperTheme, setPaperThemeSig] =
    createSignal<PaperThemeChoice>(readPaperTheme());

// ---- 划词浮条（sel-system FloatBar 总开关，默认开）----
// localStorage "texlate-floatbar"：'0'/'off'/'false' → 关；缺省/其他 → 开。
const FLOATBAR_KEY = "texlate-floatbar";

const readFloatbar = (): boolean => {
    try {
        const v = localStorage.getItem(FLOATBAR_KEY);
        if (v === "0" || v === "off" || v === "false") return false;
    } catch {
        /* localStorage 禁用/node 环境 */
    }
    return true;
};

const [floatbar, setFloatbarSig] = createSignal<boolean>(readFloatbar());

// ---- 句级双语对位（sent-align 总开关，默认开）----
// localStorage "texlate-sent-align"：'0'/'off'/'false' → 关；缺省/其他 → 开。
// 关掉即全剥注入 span（features/sentalign 的 enabled() 源）。
const SENT_ALIGN_KEY = "texlate-sent-align";

const readSentAlign = (): boolean => {
    try {
        const v = localStorage.getItem(SENT_ALIGN_KEY);
        if (v === "0" || v === "off" || v === "false") return false;
    } catch {
        /* localStorage 禁用/node 环境 */
    }
    return true;
};

const [sentAlign, setSentAlignSig] = createSignal<boolean>(readSentAlign());

export const settingsStore = {
    settings,
    providers,
    loaded,
    paperTheme,
    floatbar,
    sentAlign,
    endpoints,
    endpointsOff,

    setPaperTheme(choice: PaperThemeChoice) {
        setPaperThemeSig(choice);
        try {
            localStorage.setItem(PAPER_KEY, choice);
        } catch {
            /* 同上 */
        }
    },

    setFloatbar(on: boolean) {
        setFloatbarSig(on);
        try {
            localStorage.setItem(FLOATBAR_KEY, on ? "1" : "0");
        } catch {
            /* 同上 */
        }
    },

    setSentAlign(on: boolean) {
        setSentAlignSig(on);
        try {
            localStorage.setItem(SENT_ALIGN_KEY, on ? "1" : "0");
        } catch {
            /* 同上 */
        }
    },

    async refresh() {
        // getSettings 失败也要放 loaded——否则 Settings 页永远停在空表单
        try {
            const [s, p] = await Promise.all([
                api.getSettings(),
                api
                    .providers()
                    .catch(() => [] as Provider[] | { providers: Provider[] }),
            ]);
            setSettings(s);
            setProviders(Array.isArray(p) ? p : (p.providers ?? []));
        } catch {
            /* 页面层按 settings()==null 自行提示 */
        } finally {
            setLoaded(true);
        }
    },

    async save(patch: Settings) {
        const next = await api.putSettings(patch);
        // ignored 仅在有丢弃字段时才下发——浅合并会让上一轮的非空值挂留，
        // 显式归一到本轮回执
        setSettings((cur) => ({
            ...cur,
            ...next,
            ignored: next.ignored ?? [],
        }));
        return next;
    },

    test: (s?: Settings) => api.testSettings(s),

    /** 端点档案表拉取：403（server 形态）→ endpointsOff 置位走隐藏，非 403 上抛 */
    async refreshEndpoints() {
        try {
            setEndpoints(await api.getEndpoints());
            setEndpointsOff(false);
        } catch (e) {
            if (e instanceof ApiError && e.status === 403) {
                setEndpointsOff(true);
                setEndpoints(null);
                return;
            }
            throw e;
        }
    },

    /** 整表替换写——回包即新视图直接落 store */
    async saveEndpoints(profiles: EndpointProfileWrite[]) {
        const v = await api.putEndpoints(profiles);
        setEndpoints(v);
        return v;
    },

    /**
     * 激活 profile：回包是 Settings 公共面——并进 settings（激活失败不上抛
     * 后半刷新失败也不算激活失败，故 refresh 吞错只留陈视图）。
     */
    async activateEndpoint(id: string) {
        const s = await api.activateEndpoint(id);
        setSettings((cur) => ({ ...cur, ...s }));
        await this.refreshEndpoints().catch(() => {
            /* active_id 刷新失败留陈视图——激活本身已成功 */
        });
        return s;
    },

    /** 探针（仅档案条目路：{id}——裸端点路是 exfil 闸内操作不走 store） */
    async probeEndpoint(id: string): Promise<ProbeReport> {
        const r = await api.probeEndpoint({ id });
        await this.refreshEndpoints().catch(() => {
            /* last_probe 已钉回档案；刷新失败由下次进入补齐 */
        });
        return r;
    },
};
