// @vitest-environment jsdom
// EndpointsPanel + settingsStore 端点面：403 → endpointsOff 整块隐藏、
// 卡面渲染/激活/探测/新建草稿折整表 PUT、读面凭据三态展示。

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

const profile = (over: Partial<EndpointProfile> = {}): EndpointProfile => ({
    id: "p1",
    label: "DeepSeek",
    base_url: "https://api.deepseek.com",
    dialect: "auto",
    models: ["deepseek-chat"],
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

        mocks.getEndpoints.mockResolvedValueOnce(
            viewOf([profile()], "p1"),
        );
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
});

describe("EndpointsPanel 卡面", () => {
    it("渲染 profile 卡：label/base_url/models/活动徽章/凭据态", async () => {
        mocks.getEndpoints.mockResolvedValue(
            viewOf(
                [
                    profile(),
                    profile({
                        id: "p2",
                        label: "",
                        base_url: "https://openrouter.ai/api",
                        models: ["m-a", "m-b"],
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

        const btns = [
            ...document.body.querySelectorAll<HTMLButtonElement>(
                ".ep-card .btn-ghost",
            ),
        ];
        // 卡2 首个钮 = 设为当前（卡1 是活动 profile，其激活钮 disabled）
        const activateBtn = btns.find(
            (b) => b.textContent === EP().activate && !b.disabled,
        );
        activateBtn?.click();
        await flush();

        expect(mocks.activateEndpoint).toHaveBeenCalledWith("p2");
        expect(activated).toBe(1);
    });

    it("探测按钮 → probeEndpoint({id})，verdict 徽章上卡", async () => {
        mountToBody(() => EndpointsPanel({}));
        await flush();

        const probeBtn = [
            ...document.body.querySelectorAll<HTMLButtonElement>(
                ".ep-card .btn-ghost",
            ),
        ].find((b) => b.textContent === EP().probe);
        probeBtn?.click();
        await flush();
        await flush();

        expect(mocks.probeEndpoint).toHaveBeenCalledWith({ id: "p1" });
        const badge = [
            ...document.body.querySelectorAll<HTMLElement>(".ep-badge"),
        ].find((b) => b.textContent?.includes("deepseek-chat"));
        expect(badge?.textContent).toContain(
            EP().verdicts.usable,
        );
    });

    it("新建草稿 → 保存折整表 PUT（旧行凭据键缺席承旧值，新行带 slug+inline key）", async () => {
        mountToBody(() => EndpointsPanel({}));
        await flush();

        const addBtn = [
            ...document.body.querySelectorAll<HTMLButtonElement>(
                ".eps > .btn-ghost",
            ),
        ].find((b) => b.textContent === EP().add);
        addBtn?.click();
        await flush();

        const draft = document.body.querySelector(".ep-draft");
        expect(draft).not.toBeNull();
        const url = draft!.querySelector<HTMLInputElement>(
            'input[type="url"]',
        )!;
        url.value = "https://openrouter.ai/api/v1";
        url.dispatchEvent(new Event("input", { bubbles: true }));
        const pwd = draft!.querySelector<HTMLInputElement>(
            'input[type="password"]',
        )!;
        pwd.value = "sk-or-x";
        pwd.dispatchEvent(new Event("input", { bubbles: true }));
        const ta = draft!.querySelector<HTMLTextAreaElement>("textarea")!;
        ta.value = "m-a, m-b, m-a";
        ta.dispatchEvent(new Event("input", { bubbles: true }));
        await flush();

        const saveBtn = [
            ...draft!.querySelectorAll<HTMLButtonElement>(".btn-primary"),
        ].find((b) => b.textContent === EP().save);
        saveBtn?.click();
        await flush();

        expect(mocks.putEndpoints).toHaveBeenCalledTimes(1);
        const rows = mocks.putEndpoints.mock.calls[0][0] as Record<
            string,
            unknown
        >[];
        expect(rows.length).toBe(2);
        // 既有行凭据键缺席（承旧值）；新行带生成的 slug id + 去重后 models
        expect("api_key" in rows[0]).toBe(false);
        expect(rows[1].id).toBe("openrouter-ai");
        expect(rows[1].api_key).toBe("sk-or-x");
        expect(rows[1].models).toEqual(["m-a", "m-b"]);
    });

    it("停用 toggle → 整表 PUT 翻 enabled", async () => {
        mountToBody(() => EndpointsPanel({}));
        await flush();

        const cb = document.body.querySelector<HTMLInputElement>(
            ".ep-card input[type='checkbox']",
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
