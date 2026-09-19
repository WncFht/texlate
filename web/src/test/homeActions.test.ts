// @vitest-environment jsdom
// home/ 簇抽出件的纯逻辑面：parseArxivId 新本家（穷举口径在
// parseArxivId.test.ts——经 pages/Home 门面仍指向同一实现）、
// precheckUpload 预检、createHomeOptions 的 collectOptions/uploadFields/
// byok 快照口径、createHomeSuggest 防抖 + seq 闸 + 键盘契约。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    discoverSearch: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: { ...mod.api, discoverSearch: mocks.discoverSearch },
    };
});

import { createHomeOptions } from "../home/options";
import { createHomeSuggest, parseArxivId } from "../home/search";
import { MAX_UPLOAD_BYTES, precheckUpload } from "../home/upload";
import { parseArxivId as parseArxivIdViaPage } from "../pages/Home";

beforeEach(() => {
    mocks.discoverSearch.mockReset().mockResolvedValue([]);
});

afterEach(() => {
    vi.useRealTimers();
});

describe("parseArxivId —— 本家 home/search，pages/Home 门面同源", () => {
    it("门面再导出指向同一实现", () => {
        expect(parseArxivIdViaPage).toBe(parseArxivId);
    });
    it("裸 id / URL / 拒绝冒烟", () => {
        expect(parseArxivId("2501.14787")).toBe("2501.14787");
        expect(parseArxivId("https://arxiv.org/abs/hep-th/9901001")).toBe(
            "hep-th/9901001",
        );
        expect(parseArxivId("not-an-id")).toBeNull();
    });
});

describe("precheckUpload —— 客户端预检（U14）", () => {
    it("扩展名白名单放行（.share.zip 走 .zip 白名单）", () => {
        for (const name of [
            "a.tex",
            "a.pdf",
            "a.docx",
            "a.epub",
            "a.zip",
            "a.tgz",
            "a.tar.gz",
            "b.share.zip",
        ]) {
            expect(precheckUpload(new File(["x"], name))).toBeNull();
        }
    });

    it("白名单外扩展名报错", () => {
        expect(precheckUpload(new File(["x"], "a.txt"))).toBeTruthy();
        expect(precheckUpload(new File(["x"], "a.exe"))).toBeTruthy();
    });

    it("超 80MB 报过大（size 覆写免真分配）", () => {
        const big = new File(["x"], "a.tex");
        Object.defineProperty(big, "size", { value: MAX_UPLOAD_BYTES + 1 });
        expect(precheckUpload(big)).toBeTruthy();
        const edge = new File(["x"], "a.tex");
        Object.defineProperty(edge, "size", { value: MAX_UPLOAD_BYTES });
        expect(precheckUpload(edge)).toBeNull();
    });
});

describe("createHomeOptions —— collectOptions/byok/uploadFields", () => {
    it("全默认 → 恒写 front_matter（UI 态即意图）", () => {
        const o = createHomeOptions();
        expect(o.collectOptions()).toEqual({
            options: {
                front_matter: { abstract: true, title: true, author: false },
            },
        });
    });

    it("字段收集：trim、并发夹取 1..16、prefer/source 透传", () => {
        const o = createHomeOptions();
        o.setOptModel("  m1  ");
        o.setOptLang("zh-TW");
        o.setOptConcurrency("99");
        o.setOptGuidance("on");
        o.setOptEngine("tectonic");
        o.setOptPrefer("fresh");
        o.setOptSource("html");
        o.setOptShare("on");
        o.setOptFmAuthor("on");
        expect(o.collectOptions()).toEqual({
            model: "m1",
            target_lang: "zh-TW",
            options: {
                context_guidance: true,
                concurrency: 16,
                engine: "tectonic",
                prefer: "fresh",
                source: "html",
                share_pack: true,
                front_matter: { abstract: true, title: true, author: true },
            },
        });
    });

    it("source=eprint 不写字段（服务端缺省同义）", () => {
        const o = createHomeOptions();
        const r = o.collectOptions();
        expect(r?.options?.source).toBeUndefined();
    });

    it("uploadFields：prefer/source 剔除 + glossary 上提", () => {
        const o = createHomeOptions();
        o.setOptPrefer("reuse");
        o.setOptSource("html");
        o.setOptGlossary("a = b");
        const { o: tr, upOpts } = o.uploadFields();
        expect(upOpts.prefer).toBeUndefined();
        expect(upOpts.source).toBeUndefined();
        expect(upOpts.glossary).toBe("a = b");
        expect(tr?.glossary).toBe("a = b");
    });

    it("byok：空白不透传；填写后 clearKey 归零", () => {
        const o = createHomeOptions();
        expect(o.byok()).toBeUndefined();
        o.setOptKey("  ");
        expect(o.byok()).toBeUndefined();
        o.setOptKey(" sk-t ");
        expect(o.byok()).toEqual({ apiKey: "sk-t" });
        o.clearKey();
        expect(o.byok()).toBeUndefined();
    });
});

describe("createHomeSuggest —— 防抖 + seq 闸 + 键盘契约", () => {
    const key = (k: string) =>
        ({ key: k, preventDefault: vi.fn() }) as unknown as KeyboardEvent;

    it("300ms 防抖：连续输入只发最后一查", async () => {
        vi.useFakeTimers();
        const sg = createHomeSuggest({
            alive: () => true,
            fillId: () => {},
        });
        sg.feed("first query");
        sg.feed("second query");
        await vi.advanceTimersByTimeAsync(300);
        expect(mocks.discoverSearch).toHaveBeenCalledTimes(1);
        expect(mocks.discoverSearch).toHaveBeenCalledWith("second query");
    });

    it("能解析成 arXiv id 的输入不发起搜索（待提交态）", async () => {
        vi.useFakeTimers();
        const sg = createHomeSuggest({
            alive: () => true,
            fillId: () => {},
        });
        sg.feed("2501.14787");
        await vi.advanceTimersByTimeAsync(500);
        expect(mocks.discoverSearch).not.toHaveBeenCalled();
        expect(sg.hits()).toBeNull();
    });

    it("seq 闸：慢响应落地不盖新查询", async () => {
        vi.useFakeTimers();
        const sg = createHomeSuggest({
            alive: () => true,
            fillId: () => {},
        });
        let resolveFirst: ((v: unknown) => void) | undefined;
        let resolveSecond: ((v: unknown) => void) | undefined;
        mocks.discoverSearch
            .mockImplementationOnce(
                () => new Promise((r) => (resolveFirst = r)),
            )
            .mockImplementationOnce(
                () => new Promise((r) => (resolveSecond = r)),
            );
        sg.feed("query one");
        await vi.advanceTimersByTimeAsync(300); // search1 在飞（seq=1）
        sg.feed("query two");
        await vi.advanceTimersByTimeAsync(300); // search2 在飞（seq=2）
        resolveFirst?.([{ paperId: "2501.00001", title: "stale" }]);
        await vi.advanceTimersByTimeAsync(0);
        // 旧响应被 seq 闸丢——hits 仍空等 search2
        expect(sg.hits()).toBeNull();
        resolveSecond?.([{ paperId: "2501.00002", title: "new" }]);
        await vi.advanceTimersByTimeAsync(0);
        expect(sg.hits()).toEqual([{ paperId: "2501.00002", title: "new" }]);
    });

    it("↓↑ 环绕、Enter 回填、Esc 关下拉", async () => {
        vi.useFakeTimers();
        const fills: string[] = [];
        const sg = createHomeSuggest({
            alive: () => true,
            fillId: (id) => fills.push(id),
        });
        mocks.discoverSearch.mockResolvedValue([
            { paperId: "2501.00001" },
            { paperId: "2501.00002" },
        ]);
        sg.feed("some query");
        await vi.advanceTimersByTimeAsync(300);
        await vi.advanceTimersByTimeAsync(0);
        expect(sg.hits()?.length).toBe(2);

        sg.onSuggestKey(key("ArrowDown"));
        expect(sg.activeHit()).toBe(0);
        sg.onSuggestKey(key("ArrowDown"));
        expect(sg.activeHit()).toBe(1);
        sg.onSuggestKey(key("ArrowDown")); // 环绕回头
        expect(sg.activeHit()).toBe(0);
        sg.onSuggestKey(key("ArrowUp")); // 反向环绕到尾
        expect(sg.activeHit()).toBe(1);

        sg.onSuggestKey(key("Enter"));
        expect(fills).toEqual(["2501.00002"]);
        expect(sg.hits()).toBeNull();
        expect(sg.activeHit()).toBe(-1);
    });

    it("pickHit：回填输入框 + 关下拉", async () => {
        const fills: string[] = [];
        const sg = createHomeSuggest({
            alive: () => true,
            fillId: (id) => fills.push(id),
        });
        sg.pickHit({ paperId: "cs/0501001" });
        expect(fills).toEqual(["cs/0501001"]);
        expect(sg.hits()).toBeNull();
    });
});
