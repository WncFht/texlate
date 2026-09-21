// BYOK 头透传：api 层打点——X-Texlate-Key 仅 byok.apiKey 非空时下发。

import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { sentHeaders, stubFetch } from "./_fetchkit";

afterEach(() => vi.unstubAllGlobals());

describe("BYOK X-Texlate-Key 透传（api 层）", () => {
    it("translate 带 apiKey → 头发送；不带 → 头缺席", async () => {
        let spy = stubFetch();
        await api.translate("2501.14787", undefined, { apiKey: "sk-temp" });
        expect(sentHeaders(spy)["X-Texlate-Key"]).toBe("sk-temp");

        spy = stubFetch();
        await api.translate("2501.14787");
        expect(sentHeaders(spy)).not.toHaveProperty("X-Texlate-Key");
    });

    it("translate byok 全字段：key/base_url/model/idempotency 四头齐发", async () => {
        const spy = stubFetch();
        await api.translate("2501.14787", undefined, {
            apiKey: "k",
            baseUrl: "https://x",
            model: "m",
            idempotencyKey: "i",
        });
        const h = sentHeaders(spy);
        expect(h["X-Texlate-Key"]).toBe("k");
        expect(h["X-Texlate-Base-URL"]).toBe("https://x");
        expect(h["X-Texlate-Model"]).toBe("m");
        expect(h["Idempotency-Key"]).toBe("i");
    });

    it("upload 带 apiKey → multipart 请求同样带头；不带 → 缺席", async () => {
        const file = new File(["x"], "a.tex");
        let spy = stubFetch();
        await api.upload(file, undefined, { apiKey: "sk-up" });
        expect(sentHeaders(spy)["X-Texlate-Key"]).toBe("sk-up");
        // multipart 不得手写 content-type（浏览器自产 boundary）
        expect(sentHeaders(spy)).not.toHaveProperty("content-type");

        spy = stubFetch();
        await api.upload(file);
        expect(sentHeaders(spy)).not.toHaveProperty("X-Texlate-Key");
    });

    it("shareImport 带 apiKey → 头发送；不带 → 缺席", async () => {
        const file = new File(["x"], "b.share.zip");
        let spy = stubFetch();
        await api.shareImport(file, undefined, { apiKey: "sk-sh" });
        expect(sentHeaders(spy)["X-Texlate-Key"]).toBe("sk-sh");

        spy = stubFetch();
        await api.shareImport(file);
        expect(sentHeaders(spy)).not.toHaveProperty("X-Texlate-Key");
    });

    it("retry 带 apiKey → 头发送（needs_auth 重试契约回归）", async () => {
        const spy = stubFetch();
        await api.retry("t_0000000000000f01", undefined, { apiKey: "sk-re" });
        expect(sentHeaders(spy)["X-Texlate-Key"]).toBe("sk-re");
    });
});
