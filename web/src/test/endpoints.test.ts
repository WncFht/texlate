// @vitest-environment jsdom
// EndpointsPanel + settingsStore 端点面（ccLoad 式交互后）：
// store 层 403→endpointsOff、probe 子集传参；卡面 chips model(redirect)、
// 激活；抽屉编辑 + 模型表格（勾选批处理）；获取模型勾选器、测试弹窗、
// 排序弹窗、删除确认弹窗、停用 toggle 折整表 PUT。

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    getEndpoints: vi.fn(),
    putEndpoints: vi.fn(),
    activateEndpoint: vi.fn(),
    probeEndpoint: vi.fn(),
    getSettings: vi.fn(),
    providers: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const { clientModuleMock } = await import("./_taskkit");
    return clientModuleMock(importOriginal, mocks);
});

import { ApiError, type EndpointProfile } from "../api/client";
import EndpointsPanel from "../components/EndpointsPanel";
import { t } from "../i18n";
import { settingsStore } from "../stores/settings";
import { flush } from "./_taskkit";
import { mountToBody } from "./helpers";

const EP = () => t.settings.endpoints;

const modelOf = (model: string, redirect_model = "") => ({
    model,
    redirect_model,
});

const profile = (over: Partial<EndpointProfile> = {}): EndpointProfile => ({
    id: "p1",
    label: "DeepSeek",
    base_url: "https://api.deepseek.com",
    dialect: "auto",
    models: [modelOf("deepseek-chat")],
    enabled: true,
    has_api_key: true,
    key_env: "",
    has_env_key: false,
    last_probe: null,
    ...over,
});

const viewOf = (profiles: EndpointProfile[], active_id = "") => ({
    profiles,
    active_id,
});

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
            ".ep-drawer .ep-nav-item",
        ),
    ][idx];

beforeEach(() => {
    for (const m of Object.values(mocks)) m.mockReset();
    mocks.getSettings.mockResolvedValue({ has_api_key: false });
    mocks.providers.mockResolvedValue({ providers: [] });
    mocks.getEndpoints.mockResolvedValue(viewOf([profile()], "p1"));
    mocks.putEndpoints.mockResolvedValue(viewOf([profile()], "p1"));
    mocks.activateEndpoint.mockResolvedValue({ has_api_key: true });
    mocks.probeEndpoint.mockResolvedValue({
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

describe("settingsStore 端点面", () => {
    it("refreshEndpoints：403 → endpointsOff 置位（server 形态隐藏整块）", async () => {
        mocks.getEndpoints.mockRejectedValueOnce(
            new ApiError(403, "forbidden", "forbidden"),
        );

        await settingsStore.refreshEndpoints();

        expect(settingsStore.endpointsOff()).toBe(true);
        expect(settingsStore.endpoints()).toBeNull();
    });

    it("refreshEndpoints：非 403 错误上抛（只把 403 当形态闸）", async () => {
        mocks.getEndpoints.mockRejectedValueOnce(new Error("down"));

        await expect(settingsStore.refreshEndpoints()).rejects.toThrow("down");
    });

    it("refreshEndpoints：成功 → 视图落 store、endpointsOff 复位", async () => {
        mocks.getEndpoints.mockRejectedValueOnce(
            new ApiError(403, "forbidden", "forbidden"),
        );
        await settingsStore.refreshEndpoints();
        expect(settingsStore.endpointsOff()).toBe(true);

        mocks.getEndpoints.mockResolvedValueOnce(viewOf([profile()], "p1"));
        await settingsStore.refreshEndpoints();

        expect(settingsStore.endpointsOff()).toBe(false);
        expect(settingsStore.endpoints()?.profiles[0]?.id).toBe("p1");
        expect(settingsStore.endpoints()?.active_id).toBe("p1");
    });

    it("activateEndpoint：Settings 回执并入 settings + 端点视图重拉", async () => {
        mocks.activateEndpoint.mockResolvedValueOnce({
            base_url: "https://api.deepseek.com",
            model: "deepseek-chat",
            has_api_key: true,
        });

        await settingsStore.activateEndpoint("p1");

        expect(mocks.activateEndpoint).toHaveBeenCalledWith("p1");
        expect(settingsStore.settings()?.base_url).toBe(
            "https://api.deepseek.com",
        );
        expect(mocks.getEndpoints).toHaveBeenCalled();
    });

    it("probeEndpoint：models 子集 → {id,models} 透传；空数组 = stage1-only", async () => {
        await settingsStore.probeEndpoint("p1", ["m-x"]);
        expect(mocks.probeEndpoint).toHaveBeenCalledWith({
            id: "p1",
            models: ["m-x"],
        });

        mocks.probeEndpoint.mockClear();
        await settingsStore.probeEndpoint("p1", []);
        expect(mocks.probeEndpoint).toHaveBeenCalledWith({
            id: "p1",
            models: [],
        });
    });
});

describe("EndpointsPanel 卡面", () => {
    it("渲染 profile 卡：label/base_url/model chips/活动徽章/凭据态", async () => {
        mocks.getEndpoints.mockResolvedValue(
            viewOf(
                [
                    profile(),
                    profile({
                        id: "p2",
                        label: "",
                        base_url: "https://openrouter.ai/api",
                        models: [modelOf("m-a"), modelOf("m-b")],
                        has_api_key: false,
                        key_env: "MY_KEY",
                        has_env_key: true,
                        enabled: false,
                    }),
                ],
                "p1",
            ),
        );
        mountToBody(() => EndpointsPanel({}));
        await flush();

        const cards = document.body.querySelectorAll(".ep-card");
        expect(cards.length).toBe(2);
        expect(cards[0].textContent).toContain("DeepSeek");
        expect(cards[0].textContent).toContain("api.deepseek.com");
        expect(cards[0].querySelector(".ep-badge")?.textContent).toBe(
            EP().activeBadge,
        );
        expect(cards[0].textContent).toContain(EP().credKeySet);
        // 第二张：env 引用态 + 停用降权
        expect(cards[1].classList.contains("off")).toBe(true);
        expect(cards[1].textContent).toContain("MY_KEY");
        expect(cards[1].textContent).toContain("m-a");
    });

    it("redirect chip：model(red) 分段渲染（redirect 段弱显）", async () => {
        mocks.getEndpoints.mockResolvedValue(
            viewOf([
                profile({
                    models: [modelOf("alias", "real-name"), modelOf("plain")],
                }),
            ]),
        );
        mountToBody(() => EndpointsPanel({}));
        await flush();

        const chips = [
            ...document.body.querySelectorAll<HTMLElement>(".ep-chip"),
        ];
        expect(chips[0].textContent).toBe("alias(real-name)");
        expect(chips[0].querySelector(".ep-chip-red")?.textContent).toBe(
            "(real-name)",
        );
        expect(chips[1].textContent).toBe("plain");
    });

    it("chips 超 4 条折叠 +N 徽记", async () => {
        mocks.getEndpoints.mockResolvedValue(
            viewOf([
                profile({
                    models: [1, 2, 3, 4, 5, 6].map((n) => modelOf(`m${n}`)),
                }),
            ]),
        );
        mountToBody(() => EndpointsPanel({}));
        await flush();

        const chips = [
            ...document.body.querySelectorAll<HTMLElement>(".ep-chip"),
        ];
        expect(chips.length).toBe(5); // 4 直显 + 1 折叠徽记
        expect(chips[4].textContent).toBe("+2");
    });

    it("endpointsOff → 整块不渲染", async () => {
        mocks.getEndpoints.mockRejectedValue(
            new ApiError(403, "forbidden", "forbidden"),
        );
        mountToBody(() => EndpointsPanel({}));
        await flush();

        expect(document.body.querySelector(".eps")).toBeNull();
    });

    it("激活按钮 → activateEndpoint + onActivated 回调", async () => {
        mocks.getEndpoints.mockResolvedValue(
            viewOf(
                [
                    profile(),
                    profile({ id: "p2", label: "OR", has_api_key: true }),
                ],
                "p1",
            ),
        );
        let activated = 0;
        mountToBody(() => EndpointsPanel({ onActivated: () => activated++ }));
        await flush();

        // 卡1 是活动 profile，其激活钮 disabled——挑可用那颗（卡2）
        const activateBtn = [
            ...document.body.querySelectorAll<HTMLButtonElement>(
                ".ep-card .btn-ghost",
            ),
        ].find((b) => b.textContent === EP().activate && !b.disabled);
        activateBtn?.click();
        await flush();

        expect(mocks.activateEndpoint).toHaveBeenCalledWith("p2");
        expect(activated).toBe(1);
    });

    it("停用 toggle → 整表 PUT 翻 enabled", async () => {
        mountToBody(() => EndpointsPanel({}));
        await flush();

        const cb = document.body.querySelector<HTMLInputElement>(
            ".ep-card .ep-toggle input[type='checkbox']",
        )!;
        cb.click();
        await flush();

        const rows = mocks.putEndpoints.mock.calls[0][0] as Record<
            string,
            unknown
        >[];
        expect(rows[0].enabled).toBe(false);
    });
});

describe("测试弹窗", () => {
    it("卡面探测钮 → 弹窗选模型逐测（{id,models:[本地名]}），结果行上窗", async () => {
        mountToBody(() => EndpointsPanel({}));
        await flush();

        btnByText(document.body, ".ep-card .btn-ghost", EP().probe)?.click();
        await flush();

        const box = document.body.querySelector(".ep-box")!;
        expect(box.textContent).toContain(EP().testTitle);
        const runBtn = btnByText(box, ".btn-primary", EP().testRun)!;
        runBtn.click();
        await flush();
        await flush();

        expect(mocks.probeEndpoint).toHaveBeenCalledWith({
            id: "p1",
            models: ["deepseek-chat"],
        });
        const row = box.querySelector(".ep-test-row")!;
        expect(row.textContent).toContain("deepseek-chat");
        expect(row.textContent).toContain(EP().verdicts.usable);
    });
});

describe("编辑抽屉", () => {
    const openAdd = async () => {
        btnByText(document.body, ".ep-foot .btn-ghost", EP().add)?.click();
        await flush();
        return document.body.querySelector(".ep-drawer")!;
    };

    it("新建抽屉：基本→凭据→模型三节填写，保存折整表 PUT（dict 形 models）", async () => {
        mountToBody(() => EndpointsPanel({}));
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
        const addBtn = btnByText(drawer, ".ep-mtools .btn-ghost", EP().addModel)!;
        addBtn.click();
        addBtn.click();
        await flush();
        const cells = [
            ...drawer.querySelectorAll<HTMLInputElement>(
                ".ep-mtable .ep-cell-in",
            ),
        ];
        // 每行两格（模型名/重定向）——0/2 是两条模型名格
        typeInto(cells[0], "m-a");
        typeInto(cells[2], "m-b");
        await flush();

        const saveBtn = btnByText(drawer, ".btn-primary", EP().save)!;
        saveBtn.click();
        await flush();

        expect(mocks.putEndpoints).toHaveBeenCalledTimes(1);
        const rows = mocks.putEndpoints.mock.calls[0][0] as Record<
            string,
            unknown
        >[];
        expect(rows.length).toBe(2);
        // 既有行凭据键缺席（承旧值）；新行带生成 slug + dict 形 models
        expect("api_key" in rows[0]).toBe(false);
        expect(rows[1].id).toBe("openrouter-ai");
        expect(rows[1].api_key).toBe("sk-or-x");
        expect(rows[1].models).toEqual([
            { model: "m-a", redirect_model: "" },
            { model: "m-b", redirect_model: "" },
        ]);
    });

    it("重定向列留空→空串；填值→dict 携带", async () => {
        mountToBody(() => EndpointsPanel({}));
        await flush();
        const drawer = await openAdd();
        typeInto(
            drawer.querySelector<HTMLInputElement>('input[type="url"]')!,
            "https://x.ai/v1",
        );
        drawerNav(2).click();
        await flush();
        btnByText(drawer, ".ep-mtools .btn-ghost", EP().addModel)!.click();
        await flush();
        const cells = [
            ...drawer.querySelectorAll<HTMLInputElement>(
                ".ep-mtable .ep-cell-in",
            ),
        ];
        typeInto(cells[0], "alias");
        typeInto(cells[1], "real-upstream");
        await flush();
        btnByText(drawer, ".btn-primary", EP().save)!.click();
        await flush();

        const rows = mocks.putEndpoints.mock.calls[0][0] as Record<
            string,
            unknown
        >[];
        expect(rows[1].models).toEqual([
            { model: "alias", redirect_model: "real-upstream" },
        ]);
    });

    it("模型表格批处理：勾选→删除选中清行", async () => {
        mocks.getEndpoints.mockResolvedValue(
            viewOf([
                profile({
                    models: [modelOf("m-a"), modelOf("m-b"), modelOf("m-c")],
                }),
            ]),
        );
        mountToBody(() => EndpointsPanel({}));
        await flush();
        btnByText(document.body, ".ep-card .btn-ghost", EP().edit)?.click();
        await flush();
        const drawer = document.body.querySelector(".ep-drawer")!;
        drawerNav(2).click();
        await flush();

        // 全选 → 批处理条出 → 删除选中
        const selAll = drawer.querySelector<HTMLInputElement>(
            ".ep-mtable thead input[type='checkbox']",
        )!;
        selAll.click();
        await flush();
        const batchDel = btnByText(drawer, ".ep-mbatch .btn-ghost", EP().batchDel)!;
        batchDel.click();
        await flush();

        expect(
            drawer.querySelectorAll(".ep-mtable tbody tr td.ep-cb").length,
        ).toBe(0);
        expect(drawer.textContent).toContain(EP().modelsEmpty);
    });

    it("批处理转小写 + 去来源（redirect 不受影响）", async () => {
        mocks.getEndpoints.mockResolvedValue(
            viewOf([
                profile({
                    models: [
                        modelOf("Vendor/UPPER", "KEEP-Red"),
                        modelOf("plain"),
                    ],
                }),
            ]),
        );
        mountToBody(() => EndpointsPanel({}));
        await flush();
        btnByText(document.body, ".ep-card .btn-ghost", EP().edit)?.click();
        await flush();
        const drawer = document.body.querySelector(".ep-drawer")!;
        drawerNav(2).click();
        await flush();

        const selAll = drawer.querySelector<HTMLInputElement>(
            ".ep-mtable thead input[type='checkbox']",
        )!;
        selAll.click();
        await flush();
        btnByText(drawer, ".ep-mbatch .btn-ghost", EP().batchStrip)!.click();
        btnByText(drawer, ".ep-mbatch .btn-ghost", EP().batchLower)!.click();
        await flush();

        const cells = [
            ...drawer.querySelectorAll<HTMLInputElement>(
                ".ep-mtable .ep-cell-in",
            ),
        ];
        expect(cells[0].value).toBe("upper"); // 去来源 + 小写
        expect(cells[1].value).toBe("keep-red"); // 小写也吃（批处理对两列同施）但前缀不剥
        expect(cells[2].value).toBe("plain");
    });
});

describe("获取模型勾选器", () => {
    it("既有档案 → {id,models:[]} stage1-only；勾选新模型确认并入草稿行", async () => {
        mocks.probeEndpoint.mockResolvedValue({
            at: "2026-10-07T01:00:00+00:00",
            key_fp: "abcd1234",
            stage1: {
                verdict: "ok",
                models: ["deepseek-chat", "deepseek-reasoner", "new-m"],
                detail: "",
            },
            models: {},
        });
        mountToBody(() => EndpointsPanel({}));
        await flush();
        btnByText(document.body, ".ep-card .btn-ghost", EP().edit)?.click();
        await flush();
        const drawer = document.body.querySelector(".ep-drawer")!;
        drawerNav(2).click();
        await flush();

        btnByText(drawer, ".ep-mtools .btn-ghost", EP().fetchModels)!.click();
        await flush();
        await flush();

        expect(mocks.probeEndpoint).toHaveBeenCalledWith({
            id: "p1",
            models: [],
        });
        // 勾选器三条：ccLoad 式默认全勾（既有条目确认时去重不重复入档）
        const items = [
            ...document.body.querySelectorAll<HTMLElement>(".ep-pick-item"),
        ];
        expect(items.length).toBe(3);
        const checked = [
            ...document.body.querySelectorAll<HTMLInputElement>(
                ".ep-pick-item input",
            ),
        ];
        expect(checked.every((c) => c.checked)).toBe(true);

        btnByText(document.body, ".ep-box .btn-primary", EP().fetchConfirm)!.click();
        await flush();

        const cells = [
            ...drawer.querySelectorAll<HTMLInputElement>(
                ".ep-mtable .ep-cell-in",
            ),
        ];
        // 追加新勾两条（旧勾不重复入档）→ 3 行模型名格
        const names = cells
            .filter((_, i) => i % 2 === 0)
            .map((c) => c.value);
        expect(names).toEqual(["deepseek-chat", "deepseek-reasoner", "new-m"]);
    });
});

describe("排序/删除弹窗", () => {
    it("排序弹窗列档案、保存 PUT 顺序", async () => {
        mocks.getEndpoints.mockResolvedValue(
            viewOf([
                profile(),
                profile({ id: "p2", label: "OR", base_url: "https://or.ai" }),
            ]),
        );
        mountToBody(() => EndpointsPanel({}));
        await flush();

        btnByText(document.body, ".ep-foot .btn-ghost", EP().sort)?.click();
        await flush();

        const items = document.body.querySelectorAll(".ep-sort-item");
        expect(items.length).toBe(2);
        expect(items[0].textContent).toContain("DeepSeek");

        btnByText(document.body, ".ep-box .btn-primary", EP().save)?.click();
        await flush();
        const rows = mocks.putEndpoints.mock.calls[0][0] as Record<
            string,
            unknown
        >[];
        expect(rows.map((r) => r.id)).toEqual(["p1", "p2"]);
    });

    it("删除确认弹窗 → PUT 移除该行", async () => {
        mocks.getEndpoints.mockResolvedValue(
            viewOf([
                profile(),
                profile({ id: "p2", label: "OR" }),
            ]),
        );
        mountToBody(() => EndpointsPanel({}));
        await flush();

        const cards = document.body.querySelectorAll(".ep-card");
        btnByText(cards[1], ".btn-ghost", EP().del)?.click();
        await flush();

        const box = document.body.querySelector(".ep-box")!;
        expect(box.textContent).toContain(EP().delTitle);
        btnByText(box, ".btn-primary", EP().del)?.click();
        await flush();

        const rows = mocks.putEndpoints.mock.calls[0][0] as Record<
            string,
            unknown
        >[];
        expect(rows.length).toBe(1);
        expect(rows[0].id).toBe("p1");
    });
});
