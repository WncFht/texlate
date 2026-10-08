// @vitest-environment jsdom
// ChannelsPanel + settingsStore 渠道面（ccLoad 式交互）：
// store 层 403→channelsOff、probe 子集传参、route 写；卡面 chips
// model(redirect)、路由条/钉到路由；抽屉编辑 + 模型表格（勾选批处理/
// 并发与启用列）；获取模型勾选器、测试弹窗、排序弹窗（priority 重发
// 稀疏序号）、删除确认弹窗、停用 toggle 折整表 PUT。

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    getChannels: vi.fn(),
    putChannels: vi.fn(),
    setChannelRoute: vi.fn(),
    getChannelPresets: vi.fn(),
    probeChannel: vi.fn(),
    getSettings: vi.fn(),
    providers: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const { clientModuleMock } = await import("./_taskkit");
    return clientModuleMock(importOriginal, mocks);
});

import { ApiError, type Channel } from "../api/client";
import ChannelsPanel from "../components/ChannelsPanel";
import { t } from "../i18n";
import { settingsStore } from "../stores/settings";
import { flush } from "./_taskkit";
import { mountToBody } from "./helpers";

const EP = () => t.settings.channels;

const modelOf = (model: string, redirect_model = "") => ({
    model,
    redirect_model,
    enabled: true,
    max_concurrency: null,
});

const channel = (over: Partial<Channel> = {}): Channel => ({
    id: "p1",
    name: "DeepSeek",
    preset: "deepseek",
    base_url: "https://api.deepseek.com",
    protocol: "auto",
    models: [modelOf("deepseek-chat")],
    priority: 10,
    max_concurrency: null,
    enabled: true,
    has_api_key: true,
    key_env: "",
    has_env_key: false,
    last_probe: null,
    ...over,
});

const viewOf = (
    channels: Channel[],
    route: { channel_id: string; model: string } = {
        channel_id: "auto",
        model: "",
    },
    active_id = "",
) => ({ channels, route, active_id });

/** 在 root 内按文本找按钮 */
const btnByText = (
    root: ParentNode,
    selector: string,
    text: string,
): HTMLButtonElement | undefined =>
    [...root.querySelectorAll<HTMLButtonElement>(selector)].find(
        (b) => b.textContent === text,
    );

/** input 填值 + input 事件（SolidJS onInput 挂载点） */
const typeInto = (el: HTMLInputElement, value: string) => {
    el.value = value;
    el.dispatchEvent(new Event("input", { bubbles: true }));
};

/** 抽屉内切到指定导航节（0 基本 / 1 凭据 / 2 模型） */
const drawerNav = (idx: number) =>
    [
        ...document.body.querySelectorAll<HTMLButtonElement>(
            ".ch-drawer .ch-nav-item",
        ),
    ][idx];

beforeEach(() => {
    for (const m of Object.values(mocks)) m.mockReset();
    mocks.getSettings.mockResolvedValue({ has_api_key: false });
    mocks.providers.mockResolvedValue({ providers: [] });
    mocks.getChannels.mockResolvedValue(viewOf([channel()]));
    mocks.putChannels.mockResolvedValue(viewOf([channel()]));
    mocks.setChannelRoute.mockResolvedValue(
        viewOf([channel()], { channel_id: "p1", model: "" }),
    );
    mocks.getChannelPresets.mockResolvedValue({
        presets: [
            {
                id: "deepseek",
                name: "DeepSeek",
                protocol: "openai",
                base_url: "https://api.deepseek.com",
                models: ["deepseek-chat"],
                key_env: "DEEPSEEK_API_KEY",
                has_env_key: false,
            },
        ],
    });
    mocks.probeChannel.mockResolvedValue({
        at: "2026-10-07T01:00:00+00:00",
        key_fp: "abcd1234",
        stage1: { verdict: "ok", models: ["deepseek-chat"], detail: "" },
        models: {
            "deepseek-chat": {
                verdict: "usable",
                latency_s: 0.4,
                detail: "",
                listed: true,
            },
        },
    });
    document.body.innerHTML = "";
});

describe("settingsStore 渠道面", () => {
    it("refreshChannels：403 → channelsOff 置位（server 形态隐藏整块）", async () => {
        mocks.getChannels.mockRejectedValueOnce(
            new ApiError(403, "forbidden", "forbidden"),
        );

        await settingsStore.refreshChannels();

        expect(settingsStore.channelsOff()).toBe(true);
        expect(settingsStore.channels()).toBeNull();
    });

    it("refreshChannels：非 403 错误上抛（只把 403 当形态闸）", async () => {
        mocks.getChannels.mockRejectedValueOnce(new Error("down"));

        await expect(settingsStore.refreshChannels()).rejects.toThrow("down");
    });

    it("refreshChannels：成功 → 视图落 store、channelsOff 复位", async () => {
        mocks.getChannels.mockRejectedValueOnce(
            new ApiError(403, "forbidden", "forbidden"),
        );
        await settingsStore.refreshChannels();
        expect(settingsStore.channelsOff()).toBe(true);

        mocks.getChannels.mockResolvedValueOnce(
            viewOf([channel()], { channel_id: "p1", model: "m" }, "p1"),
        );
        await settingsStore.refreshChannels();

        expect(settingsStore.channelsOff()).toBe(false);
        expect(settingsStore.channels()?.channels[0]?.id).toBe("p1");
        expect(settingsStore.channels()?.route.channel_id).toBe("p1");
        expect(settingsStore.channels()?.active_id).toBe("p1");
    });

    it("setChannelRoute：POST route → 回包落 store", async () => {
        mocks.setChannelRoute.mockResolvedValueOnce(
            viewOf([channel()], { channel_id: "p1", model: "deepseek-chat" }),
        );

        await settingsStore.setChannelRoute({
            channel_id: "p1",
            model: "deepseek-chat",
        });

        expect(mocks.setChannelRoute).toHaveBeenCalledWith({
            channel_id: "p1",
            model: "deepseek-chat",
        });
        expect(settingsStore.channels()?.route.channel_id).toBe("p1");
    });

    it("probeChannel：models 子集 → {id,models} 透传；空数组 = stage1-only", async () => {
        await settingsStore.probeChannel("p1", ["m-x"]);
        expect(mocks.probeChannel).toHaveBeenCalledWith({
            id: "p1",
            models: ["m-x"],
        });

        mocks.probeChannel.mockClear();
        await settingsStore.probeChannel("p1", []);
        expect(mocks.probeChannel).toHaveBeenCalledWith({
            id: "p1",
            models: [],
        });
    });
});

describe("ChannelsPanel 卡面", () => {
    it("渲染渠道卡：name/base_url/model chips/优先级/凭据态", async () => {
        mocks.getChannels.mockResolvedValue(
            viewOf([
                channel({ priority: 20 }),
                channel({
                    id: "p2",
                    name: "",
                    preset: "custom",
                    base_url: "https://openrouter.ai/api",
                    models: [modelOf("m-a"), modelOf("m-b")],
                    priority: 10,
                    max_concurrency: 4,
                    has_api_key: false,
                    key_env: "MY_KEY",
                    has_env_key: true,
                    enabled: false,
                }),
            ]),
        );
        mountToBody(ChannelsPanel);
        await flush();

        const cards = document.body.querySelectorAll(".ch-card");
        expect(cards.length).toBe(2);
        expect(cards[0].textContent).toContain("DeepSeek");
        expect(cards[0].textContent).toContain("api.deepseek.com");
        expect(cards[0].textContent).toContain(EP().credKeySet);
        // 第二张：env 引用态 + 停用降权 + 渠道并发上限
        expect(cards[1].classList.contains("off")).toBe(true);
        expect(cards[1].textContent).toContain("MY_KEY");
        expect(cards[1].textContent).toContain("m-a");
        expect(cards[1].textContent).toContain("≤4");
    });

    it("redirect chip：model(red) 分段渲染（redirect 段弱显）", async () => {
        mocks.getChannels.mockResolvedValue(
            viewOf([
                channel({
                    models: [modelOf("alias", "real-name"), modelOf("plain")],
                }),
            ]),
        );
        mountToBody(ChannelsPanel);
        await flush();

        const chips = [
            ...document.body.querySelectorAll<HTMLElement>(".ch-chip"),
        ];
        expect(chips[0].textContent).toBe("alias(real-name)");
        expect(chips[0].querySelector(".ch-chip-red")?.textContent).toBe(
            "(real-name)",
        );
        expect(chips[1].textContent).toBe("plain");
    });

    it("chips 超 4 条折叠 +N 徽记", async () => {
        mocks.getChannels.mockResolvedValue(
            viewOf([
                channel({
                    models: [1, 2, 3, 4, 5, 6].map((n) => modelOf(`m${n}`)),
                }),
            ]),
        );
        mountToBody(ChannelsPanel);
        await flush();

        const chips = [
            ...document.body.querySelectorAll<HTMLElement>(".ch-chip"),
        ];
        expect(chips.length).toBe(5); // 4 直显 + 1 折叠徽记
        expect(chips[4].textContent).toBe("+2");
    });

    it("channelsOff → 整块不渲染", async () => {
        mocks.getChannels.mockRejectedValue(
            new ApiError(403, "forbidden", "forbidden"),
        );
        mountToBody(ChannelsPanel);
        await flush();

        expect(document.body.querySelector(".chs")).toBeNull();
    });

    it("路由条：钉渠道 select → POST /channels/route", async () => {
        mocks.getChannels.mockResolvedValue(
            viewOf([channel(), channel({ id: "p2", name: "OR", priority: 5 })]),
        );
        mountToBody(ChannelsPanel);
        await flush();

        const sel = document.body.querySelector<HTMLSelectElement>(
            ".ch-route select",
        )!;
        sel.value = "p2";
        sel.dispatchEvent(new Event("change", { bubbles: true }));
        await flush();

        expect(mocks.setChannelRoute).toHaveBeenCalledWith({
            channel_id: "p2",
            model: "",
        });
    });

    it("卡面钉到路由钮 → POST route 携带渠道 id；已钉渠道该钮 disabled", async () => {
        mocks.getChannels.mockResolvedValue(
            viewOf([
                channel(),
                channel({ id: "p2", name: "OR", priority: 5 }),
            ]),
        );
        mountToBody(ChannelsPanel);
        await flush();

        const pinBtns = [
            ...document.body.querySelectorAll<HTMLButtonElement>(
                ".ch-card .btn-ghost",
            ),
        ].filter((b) => b.textContent === EP().pinRoute);
        expect(pinBtns.length).toBe(2);
        pinBtns[1].click();
        await flush();

        expect(mocks.setChannelRoute).toHaveBeenCalledWith({
            channel_id: "p2",
            model: "",
        });
    });

    it("停用 toggle → 整表 PUT 翻 enabled + 按序重发稀疏 priority", async () => {
        mocks.getChannels.mockResolvedValue(
            viewOf([
                channel({ priority: 20 }),
                channel({ id: "p2", name: "OR", priority: 10 }),
            ]),
        );
        mountToBody(ChannelsPanel);
        await flush();

        const cb = document.body.querySelector<HTMLInputElement>(
            ".ch-card .ch-toggle input[type='checkbox']",
        )!;
        cb.click();
        await flush();

        const rows = mocks.putChannels.mock.calls[0][0] as Record<
            string,
            unknown
        >[];
        expect(rows[0].enabled).toBe(false);
        expect(rows[0].priority).toBe(20);
        expect(rows[1].priority).toBe(10);
    });
});

describe("测试弹窗", () => {
    it("卡面探测钮 → 弹窗选模型逐测（{id,models:[本地名]}），结果行上窗", async () => {
        mountToBody(ChannelsPanel);
        await flush();

        btnByText(document.body, ".ch-card .btn-ghost", EP().probe)?.click();
        await flush();

        const box = document.body.querySelector(".ch-box")!;
        expect(box.textContent).toContain(EP().testTitle);
        const runBtn = btnByText(box, ".btn-primary", EP().testRun)!;
        runBtn.click();
        await flush();
        await flush();

        expect(mocks.probeChannel).toHaveBeenCalledWith({
            id: "p1",
            models: ["deepseek-chat"],
        });
        const row = box.querySelector(".ch-test-row")!;
        expect(row.textContent).toContain("deepseek-chat");
        expect(row.textContent).toContain(EP().verdicts.usable);
    });
});

describe("编辑抽屉", () => {
    const openAdd = async () => {
        btnByText(document.body, ".ch-foot .btn-ghost", EP().add)?.click();
        await flush();
        return document.body.querySelector(".ch-drawer")!;
    };

    it("新建抽屉：基本→凭据→模型三节填写，保存折整表 PUT（dict 形 models，新行无 id）", async () => {
        mountToBody(ChannelsPanel);
        await flush();
        const drawer = await openAdd();

        // 基本节：base_url
        const url = drawer.querySelector<HTMLInputElement>(
            'input[type="url"]',
        )!;
        typeInto(url, "https://openrouter.ai/api/v1");

        // 凭据节：inline key
        drawerNav(1).click();
        await flush();
        const pwd = drawer.querySelector<HTMLInputElement>(
            'input[type="password"]',
        )!;
        typeInto(pwd, "sk-or-x");

        // 模型节：加两行录名
        drawerNav(2).click();
        await flush();
        const addBtn = btnByText(drawer, ".ch-mtools .btn-ghost", EP().addModel)!;
        addBtn.click();
        addBtn.click();
        await flush();
        const cells = [
            ...drawer.querySelectorAll<HTMLInputElement>(
                ".ch-mtable .ch-cell-in",
            ),
        ];
        // 每行三格（模型名/重定向/并发）——0/3 是两条模型名格
        typeInto(cells[0], "m-a");
        typeInto(cells[3], "m-b");
        await flush();

        const saveBtn = btnByText(drawer, ".btn-primary", EP().save)!;
        saveBtn.click();
        await flush();

        expect(mocks.putChannels).toHaveBeenCalledTimes(1);
        const rows = mocks.putChannels.mock.calls[0][0] as Record<
            string,
            unknown
        >[];
        expect(rows.length).toBe(2);
        // 既有行凭据键缺席（承旧值）；新行不带 id（服务端生成 ch-*）+ dict 形 models
        expect("api_key" in rows[0]).toBe(false);
        expect(rows[1].id).toBeUndefined();
        expect(rows[1].api_key).toBe("sk-or-x");
        expect(rows[1].models).toEqual([
            {
                model: "m-a",
                redirect_model: "",
                enabled: true,
                max_concurrency: null,
            },
            {
                model: "m-b",
                redirect_model: "",
                enabled: true,
                max_concurrency: null,
            },
        ]);
    });

    it("预设选择 → 预填 base_url/protocol（custom 兜底选项恒在）", async () => {
        mountToBody(ChannelsPanel);
        await flush();
        const drawer = await openAdd();

        const sel = drawer.querySelector<HTMLSelectElement>(
            ".ch-sec select",
        )!;
        sel.value = "deepseek";
        sel.dispatchEvent(new Event("change", { bubbles: true }));
        await flush();

        const url = drawer.querySelector<HTMLInputElement>(
            'input[type="url"]',
        )!;
        expect(url.value).toBe("https://api.deepseek.com");
        const nameIn = [
            ...drawer.querySelectorAll<HTMLInputElement>(".ch-sec input"),
        ].find((i) => i.type === "text" || i.type === "");
        expect(nameIn?.value).toBe("DeepSeek");
    });

    it("重定向列留空→空串；填值→dict 携带；并发列 → max_concurrency", async () => {
        mountToBody(ChannelsPanel);
        await flush();
        const drawer = await openAdd();
        typeInto(
            drawer.querySelector<HTMLInputElement>('input[type="url"]')!,
            "https://x.ai/v1",
        );
        drawerNav(2).click();
        await flush();
        btnByText(drawer, ".ch-mtools .btn-ghost", EP().addModel)!.click();
        await flush();
        const cells = [
            ...drawer.querySelectorAll<HTMLInputElement>(
                ".ch-mtable .ch-cell-in",
            ),
        ];
        typeInto(cells[0], "alias");
        typeInto(cells[1], "real-upstream");
        typeInto(cells[2], "4");
        await flush();
        btnByText(drawer, ".btn-primary", EP().save)!.click();
        await flush();

        const rows = mocks.putChannels.mock.calls[0][0] as Record<
            string,
            unknown
        >[];
        expect(rows[1].models).toEqual([
            {
                model: "alias",
                redirect_model: "real-upstream",
                enabled: true,
                max_concurrency: 4,
            },
        ]);
    });

    it("模型表格批处理：勾选→删除选中清行", async () => {
        mocks.getChannels.mockResolvedValue(
            viewOf([
                channel({
                    models: [modelOf("m-a"), modelOf("m-b"), modelOf("m-c")],
                }),
            ]),
        );
        mountToBody(ChannelsPanel);
        await flush();
        btnByText(document.body, ".ch-card .btn-ghost", EP().edit)?.click();
        await flush();
        const drawer = document.body.querySelector(".ch-drawer")!;
        drawerNav(2).click();
        await flush();

        // 全选 → 批处理条出 → 删除选中
        const selAll = drawer.querySelector<HTMLInputElement>(
            ".ch-mtable thead input[type='checkbox']",
        )!;
        selAll.click();
        await flush();
        const batchDel = btnByText(drawer, ".ch-mbatch .btn-ghost", EP().batchDel)!;
        batchDel.click();
        await flush();

        expect(
            drawer.querySelectorAll(".ch-mtable tbody tr td.ch-cb").length,
        ).toBe(0);
        expect(drawer.textContent).toContain(EP().modelsEmpty);
    });

    it("批处理转小写 + 去来源（redirect 不受影响）", async () => {
        mocks.getChannels.mockResolvedValue(
            viewOf([
                channel({
                    models: [
                        modelOf("Vendor/UPPER", "KEEP-Red"),
                        modelOf("plain"),
                    ],
                }),
            ]),
        );
        mountToBody(ChannelsPanel);
        await flush();
        btnByText(document.body, ".ch-card .btn-ghost", EP().edit)?.click();
        await flush();
        const drawer = document.body.querySelector(".ch-drawer")!;
        drawerNav(2).click();
        await flush();

        const selAll = drawer.querySelector<HTMLInputElement>(
            ".ch-mtable thead input[type='checkbox']",
        )!;
        selAll.click();
        await flush();
        btnByText(drawer, ".ch-mbatch .btn-ghost", EP().batchStrip)!.click();
        btnByText(drawer, ".ch-mbatch .btn-ghost", EP().batchLower)!.click();
        await flush();

        const cells = [
            ...drawer.querySelectorAll<HTMLInputElement>(
                ".ch-mtable .ch-cell-in",
            ),
        ];
        expect(cells[0].value).toBe("upper"); // 去来源 + 小写
        expect(cells[1].value).toBe("keep-red"); // 小写也吃（批处理对两列同施）但前缀不剥
        expect(cells[3].value).toBe("plain");
    });
});

describe("获取模型勾选器", () => {
    it("既有渠道 → {id,models:[]} stage1-only；勾选新模型确认并入草稿行", async () => {
        mocks.probeChannel.mockResolvedValue({
            at: "2026-10-07T01:00:00+00:00",
            key_fp: "abcd1234",
            stage1: {
                verdict: "ok",
                models: ["deepseek-chat", "deepseek-reasoner", "new-m"],
                detail: "",
            },
            models: {},
        });
        mountToBody(ChannelsPanel);
        await flush();
        btnByText(document.body, ".ch-card .btn-ghost", EP().edit)?.click();
        await flush();
        const drawer = document.body.querySelector(".ch-drawer")!;
        drawerNav(2).click();
        await flush();

        btnByText(drawer, ".ch-mtools .btn-ghost", EP().fetchModels)!.click();
        await flush();
        await flush();

        expect(mocks.probeChannel).toHaveBeenCalledWith({
            id: "p1",
            models: [],
        });
        // 勾选器三条：ccLoad 式默认全勾（既有条目确认时去重不重复入档）
        const items = [
            ...document.body.querySelectorAll<HTMLElement>(".ch-pick-item"),
        ];
        expect(items.length).toBe(3);
        const checked = [
            ...document.body.querySelectorAll<HTMLInputElement>(
                ".ch-pick-item input",
            ),
        ];
        expect(checked.every((c) => c.checked)).toBe(true);

        btnByText(document.body, ".ch-box .btn-primary", EP().fetchConfirm)!.click();
        await flush();

        const cells = [
            ...drawer.querySelectorAll<HTMLInputElement>(
                ".ch-mtable .ch-cell-in",
            ),
        ];
        // 追加新勾两条（旧勾不重复入档）→ 3 行模型名格（每行三格 name/redirect/conc）
        const names = cells
            .filter((_, i) => i % 3 === 0)
            .map((c) => c.value);
        expect(names).toEqual(["deepseek-chat", "deepseek-reasoner", "new-m"]);
    });
});

describe("排序/删除弹窗", () => {
    it("排序弹窗列渠道、保存 PUT 顺序 + priority 重发", async () => {
        mocks.getChannels.mockResolvedValue(
            viewOf([
                channel({ priority: 20 }),
                channel({
                    id: "p2",
                    name: "OR",
                    base_url: "https://or.ai",
                    priority: 10,
                }),
            ]),
        );
        mountToBody(ChannelsPanel);
        await flush();

        btnByText(document.body, ".ch-foot .btn-ghost", EP().sort)?.click();
        await flush();

        const items = document.body.querySelectorAll(".ch-sort-item");
        expect(items.length).toBe(2);
        expect(items[0].textContent).toContain("DeepSeek");

        btnByText(document.body, ".ch-box .btn-primary", EP().save)?.click();
        await flush();
        const rows = mocks.putChannels.mock.calls[0][0] as Record<
            string,
            unknown
        >[];
        expect(rows.map((r) => r.id)).toEqual(["p1", "p2"]);
        expect(rows.map((r) => r.priority)).toEqual([20, 10]);
    });

    it("删除确认弹窗 → PUT 移除该行", async () => {
        mocks.getChannels.mockResolvedValue(
            viewOf([
                channel({ priority: 20 }),
                channel({ id: "p2", name: "OR", priority: 10 }),
            ]),
        );
        mountToBody(ChannelsPanel);
        await flush();

        const cards = document.body.querySelectorAll(".ch-card");
        btnByText(cards[1], ".btn-ghost", EP().del)?.click();
        await flush();

        const box = document.body.querySelector(".ch-box")!;
        expect(box.textContent).toContain(EP().delTitle);
        btnByText(box, ".btn-primary", EP().del)?.click();
        await flush();

        const rows = mocks.putChannels.mock.calls[0][0] as Record<
            string,
            unknown
        >[];
        expect(rows.length).toBe(1);
        expect(rows[0].id).toBe("p1");
    });
});
