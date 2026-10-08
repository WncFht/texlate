// 设置 store —— settings.json 只剩任务策略/外观键；端点凭据唯一事实源
// 是 channels.json（channels 段即其 UI 面）。

import { createSignal } from "solid-js";
import {
    api,
    ApiError,
    type ChannelModel,
    type ChannelPreset,
    type ChannelRoute,
    type ChannelsView,
    type ChannelWrite,
    type ProbeReport,
    type Settings,
} from "../api/client";

const [settings, setSettings] = createSignal<Settings | null>(null);
const [loaded, setLoaded] = createSignal(false);

// ---- 渠道（channels.json UI 面；local 形态限定）----
// server 形态整面 403：channelsOff 置位后 Settings 页隐藏整块。
const [channels, setChannels] = createSignal<ChannelsView | null>(null);
const [channelsOff, setChannelsOff] = createSignal(false);
// 服务商预设目录——新建渠道预填面；拉过一次即驻留（静态目录）
const [channelPresets, setChannelPresets] = createSignal<ChannelPreset[]>([]);

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
    loaded,
    paperTheme,
    floatbar,
    sentAlign,
    channels,
    channelsOff,
    channelPresets,

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
        // getSettings 失败也要放 loaded——否则 Settings 页永远停在空表单；
        // channels 同帧尽力拉（凭证门/模型占位都吃它），非 403 失败留空不阻塞
        try {
            const [s] = await Promise.all([
                api.getSettings(),
                this.refreshChannels().catch(() => {}),
            ]);
            setSettings(s);
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

    /** 渠道路由对下一请求决议出的上游线名（未加载/无决议 → ""） */
    routedModel() {
        return channels()?.active_model ?? "";
    },

    /**
     * 凭证门判据（cite-translate/Home 软提示共用）——`false` 才闸：
     * channels 未加载或 403（server 形态）→ undefined 放行，交给
     * 401/needs_auth 回执面；active_id 空 = 无可路由渠道 → false。
     */
    hasCredential(): boolean | undefined {
        if (channelsOff()) return undefined;
        const v = channels();
        if (!v) return undefined;
        return v.active_id !== "";
    },

    /** 渠道表拉取：403（server 形态）→ channelsOff 置位走隐藏，非 403 上抛 */
    async refreshChannels() {
        try {
            setChannels(await api.getChannels());
            setChannelsOff(false);
        } catch (e) {
            if (e instanceof ApiError && e.status === 403) {
                setChannelsOff(true);
                setChannels(null);
                return;
            }
            throw e;
        }
    },

    /** 整表替换写——回包即新视图直接落 store；route 缺省承旧 */
    async saveChannels(rows: ChannelWrite[], route?: ChannelRoute) {
        const v = await api.putChannels(rows, route);
        setChannels(v);
        return v;
    },

    /** 路由选择写（POST /channels/route）——渠道表不动，回包落 store */
    async setChannelRoute(route: ChannelRoute) {
        const v = await api.setChannelRoute(route);
        setChannels(v);
        return v;
    },

    /** 服务商预设目录——幂等懒拉（目录静态，失败留空不阻塞表单） */
    async refreshChannelPresets() {
        if (channelPresets().length) return;
        try {
            const r = await api.getChannelPresets();
            setChannelPresets(r.presets);
        } catch {
            /* 预设拉取失败 → 面板回落纯手工表单 */
        }
    },

    /**
     * 探针（渠道条目路：{id}——裸端点路是 exfil 闸内操作走 probeChannelBare）。
     * ``models`` 给本地名子集 → 逐模型测（服务端 merge 语义，未探保留旧 verdict）。
     */
    async probeChannel(id: string, models?: string[]): Promise<ProbeReport> {
        const r = await api.probeChannel(
            models === undefined ? { id } : { id, models },
        );
        await this.refreshChannels().catch(() => {
            /* last_probe 已钉回渠道；刷新失败由下次进入补齐 */
        });
        return r;
    },

    /** 裸端点探测：草稿态按表单现值测（必须显式 api_key——exfil 闸），不钉渠道 */
    async probeChannelBare(req: {
        base_url: string;
        api_key: string;
        protocol?: string;
        models?: ChannelModel[];
    }): Promise<ProbeReport> {
        return api.probeChannel(req);
    },
};
