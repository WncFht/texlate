// @vitest-environment jsdom
// GuidePane 回归：
//  - available:false → empty 态出 alphaXiv 外链（不整块消失）
//  - available:true → 标题 + 字段四卡（空数组不出卡）+ 导语 + TOC（h2 抽节）+ citations
//  - overview 缺席时仍出卡片/引用（TOC 缺席不炸）

import { afterEach, describe, expect, it, vi } from "vitest";
import { render } from "solid-js/web";

const mocks = vi.hoisted(() => ({
    discoverOverview: vi.fn(),
    mdToHtml: vi.fn((md: string) => md),
    renderMath: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: { ...mod.api, discoverOverview: mocks.discoverOverview },
    };
});

vi.mock("../reader/markdown", () => ({
    loadMdLibs: () =>
        Promise.resolve({
            mdToHtml: mocks.mdToHtml,
            renderMath: mocks.renderMath,
        }),
}));

import GuidePane from "../reader/GuidePane";

const OV = {
    available: true,
    lang: "zh",
    alphaxiv_url: "https://www.alphaxiv.org/abs/1706.03762",
    title: "测试标题",
    summary: {
        summary: "导语一段",
        feedDescription: "feed 一句",
        originalProblem: ["问题一", "问题二"],
        solution: [],
        keyInsights: ["洞察一"],
        results: ["结果一"],
    },
    overview: "## 第一节\n\n正文\n\n## 第二节\n\n正文二",
    citations: [
        {
            title: "相关论文 A",
            justification: "为什么相关 A",
            alphaxivLink: "https://alphaxiv.org/abs/1",
        },
        { title: "无链论文 B" },
    ],
};

describe("GuidePane", () => {
    let dispose: (() => void) | undefined;
    let host: HTMLDivElement;
    afterEach(() => {
        dispose?.();
        dispose = undefined;
        host?.remove();
        vi.clearAllMocks();
    });

    const mount = (arxivId?: string) => {
        host = document.createElement("div");
        document.body.appendChild(host);
        dispose = render(() => GuidePane({ arxivId }), host);
        return host;
    };

    it("available:false → empty 态含 alphaXiv 外链", async () => {
        mocks.discoverOverview.mockResolvedValue({ available: false });
        const el = mount("1706.03762v7");
        await vi.waitFor(() =>
            expect(el.querySelector(".guide-empty")).toBeTruthy(),
        );
        const a = el.querySelector<HTMLAnchorElement>(".guide-empty a");
        expect(a?.href).toContain("alphaxiv.org/abs/1706.03762v7");
    });

    it("无 arxivId → 直接 empty，不发请求", async () => {
        const el = mount(undefined);
        await vi.waitFor(() =>
            expect(el.querySelector(".guide-empty")).toBeTruthy(),
        );
        expect(mocks.discoverOverview).not.toHaveBeenCalled();
    });

    it("content 态：标题/feed/卡片/导语/TOC/citations 全渲，空数组卡缺席", async () => {
        mocks.discoverOverview.mockResolvedValue(OV);
        mocks.mdToHtml.mockReturnValue(
            "<h2>第一节</h2><p>x</p><h2>第二节</h2>",
        );
        const el = mount("1706.03762v7");
        await vi.waitFor(() =>
            expect(el.querySelectorAll(".guide-body h2").length).toBe(2),
        );
        expect(el.querySelector(".guide-title")?.textContent).toBe("测试标题");
        expect(el.querySelector(".guide-feed")?.textContent).toBe("feed 一句");
        // solution 空数组 → 方案卡不出（4 缺 1）
        const cards = [...el.querySelectorAll(".guide-card h2")].map(
            (h) => h.textContent,
        );
        expect(cards.length).toBe(3);
        expect(el.querySelector(".guide-lead")?.textContent).toBe("导语一段");
        const toc = [...el.querySelectorAll(".guide-toc button")].map(
            (b) => b.textContent,
        );
        expect(toc).toEqual(["第一节", "第二节"]);
        // 无 id 的 h2 补 guide-s{i} 锚
        expect(el.querySelector(".guide-body h2")?.id).toBe("guide-s0");
        expect(el.querySelectorAll(".guide-cites li").length).toBe(2);
        expect(
            el.querySelector<HTMLAnchorElement>(".guide-cites a")?.href,
        ).toContain("alphaxiv.org/abs/1");
        // 无 alphaxivLink 的引用 → 退 span 不是死链
        expect(el.querySelector(".guide-cite-title")?.textContent).toBe(
            "无链论文 B",
        );
    });

    it("overview 缺席：卡片/引用仍出，TOC 缺席不炸", async () => {
        mocks.discoverOverview.mockResolvedValue({ ...OV, overview: null });
        const el = mount("1706.03762v7");
        await vi.waitFor(() =>
            expect(el.querySelectorAll(".guide-card").length).toBe(3),
        );
        expect(el.querySelector(".guide-toc")).toBeNull();
        expect(el.querySelectorAll(".guide-cites li").length).toBe(2);
    });

    it("请求失败 → empty 态", async () => {
        mocks.discoverOverview.mockRejectedValue(new Error("upstream"));
        const el = mount("1706.03762v7");
        await vi.waitFor(() =>
            expect(el.querySelector(".guide-empty")).toBeTruthy(),
        );
    });
});
