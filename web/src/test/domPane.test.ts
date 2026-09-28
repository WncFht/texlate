// @vitest-environment jsdom
// DomPane 组件面：.ltx_page_main 本体抽取（文档头壳/nav/footer 丢弃）、
// 相对 URL 兜底 absolutize 到 arxiv.org、失败态错误 veil + 重试钮再拉。
// fetch 桩掉；sanitizeDomHtml/geom/raf 走真件（DOMPurify jsdom 可用）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render } from "solid-js/web";
import DomPane from "../reader/DomPane";

const PAGE = `<!doctype html><html><head><title>paper</title></head><body>
<nav class="site-nav">arxiv-nav-chrome</nav>
<div class="ltx_page_main"><section data-chunk="0"><p>body-text-one</p>
<a href="/abs/2401.00001">rel-link</a><img src="/img/x.png"></section></div>
<footer>page-footer</footer></body></html>`;

const fetchMock = vi.fn();
let dispose: (() => void) | undefined;

const okRes = (html: string) =>
    ({ ok: true, text: () => Promise.resolve(html) }) as Response;

beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
    dispose?.();
    dispose = undefined;
    document.body.innerHTML = "";
    vi.unstubAllGlobals();
});

describe("DomPane", () => {
    it("只取 .ltx_page_main 本体 + 相对 URL 兜底 arxiv.org", async () => {
        fetchMock.mockResolvedValue(okRes(PAGE));
        const onReady = vi.fn();
        dispose = render(
            () =>
                DomPane({
                    side: "translated",
                    url: "/api/files/t1/zh.html",
                    onReady,
                }),
            document.body,
        );
        await vi.waitFor(() => expect(onReady).toHaveBeenCalledTimes(1));
        const body = document.body.querySelector(".pane-html-body")!;
        expect(body.textContent).toContain("body-text-one");
        expect(body.textContent).not.toContain("arxiv-nav-chrome");
        expect(body.textContent).not.toContain("page-footer");
        expect(body.querySelector("a")!.getAttribute("href")).toBe(
            "https://arxiv.org/abs/2401.00001",
        );
        expect(body.querySelector("img")!.getAttribute("src")).toBe(
            "https://arxiv.org/img/x.png",
        );
    });

    it("拉取失败 → 错误 veil + 重试钮再拉成功", async () => {
        fetchMock.mockResolvedValueOnce({
            ok: false,
            status: 500,
        } as Response);
        dispose = render(
            () => DomPane({ side: "original", url: "/api/files/t1/en.html" }),
            document.body,
        );
        await vi.waitFor(() =>
            expect(document.body.querySelector(".pane-error")).not.toBeNull(),
        );

        fetchMock.mockResolvedValueOnce(okRes(PAGE));
        document.body
            .querySelector<HTMLButtonElement>(".pane-error .btn-ghost")!
            .click();
        await vi.waitFor(() =>
            expect(
                document.body.querySelector(".pane-html-body")!.textContent,
            ).toContain("body-text-one"),
        );
        expect(fetchMock).toHaveBeenCalledTimes(2);
        expect(fetchMock.mock.calls[1][0]).toBe("/api/files/t1/en.html");
    });
});
