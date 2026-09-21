// Idempotency-Key：create 三路（translate/upload/shareImport）意图粒度
// 生成/复用/结案——对齐 server _create_and_enqueue 的 options.idempotency_key
// 去重契约（命中直返 202 cache:"idempotent"）。

import { afterEach, describe, expect, it, vi } from "vitest";
import { api } from "../api/client";
import { resp202, stubFetch, sentHeaders } from "./_fetchkit";

const netFail = () => Promise.reject(new TypeError("failed to fetch"));

afterEach(() => vi.unstubAllGlobals());

describe("Idempotency-Key（create 三路）", () => {
    it("translate 自动生成头发送；拿到响应后同参再提交→新 key（新意图）", async () => {
        const spy = stubFetch();
        await api.translate("2501.00001");
        const k1 = sentHeaders(spy)["Idempotency-Key"];
        expect(k1).toBeTruthy();
        expect(k1).toMatch(/^[0-9a-z-]{20,}$/);

        await api.translate("2501.00001");
        const k2 = sentHeaders(spy)["Idempotency-Key"];
        expect(k2).toBeTruthy();
        expect(k2).not.toBe(k1);
    });

    it("网络失败未决→同参重发复用同 key；拿到 HTTP 错误→结案、再发新 key", async () => {
        let spy = stubFetch(netFail);
        await expect(api.translate("2501.00002")).rejects.toThrow();
        const k1 = sentHeaders(spy)["Idempotency-Key"];
        expect(k1).toBeTruthy();

        // 同参重发：复用 k1；服务端回 400 → 意图结案
        spy = stubFetch(() =>
            Promise.resolve(
                new Response(JSON.stringify({ detail: "bad options" }), {
                    status: 400,
                    headers: { "content-type": "application/json" },
                }),
            ),
        );
        await expect(api.translate("2501.00002")).rejects.toThrow();
        expect(sentHeaders(spy)["Idempotency-Key"]).toBe(k1);

        spy = stubFetch();
        await api.translate("2501.00002");
        const k3 = sentHeaders(spy)["Idempotency-Key"];
        expect(k3).toBeTruthy();
        expect(k3).not.toBe(k1);
    });

    it("在飞并发同参（双击竞态）→ 两发同 key", async () => {
        const releases: Array<(r: Response) => void> = [];
        const spy = stubFetch(() => new Promise<Response>((r) => releases.push(r)));
        const p1 = api.translate("2501.00003");
        const p2 = api.translate("2501.00003");
        expect(spy).toHaveBeenCalledTimes(2);
        const k1 = sentHeaders(spy, 0)["Idempotency-Key"];
        const k2 = sentHeaders(spy, 1)["Idempotency-Key"];
        expect(k1).toBeTruthy();
        expect(k2).toBe(k1);
        for (const r of releases) r(resp202());
        await Promise.all([p1, p2]);
    });

    it("未决期间换参数→新 key；改回原参→仍复用旧 key（指纹绑定）", async () => {
        const spy = stubFetch(netFail);
        await expect(api.translate("2501.00006")).rejects.toThrow();
        const k1 = sentHeaders(spy)["Idempotency-Key"];

        await expect(api.translate("2501.00007")).rejects.toThrow();
        const k2 = sentHeaders(spy)["Idempotency-Key"];
        expect(k2).toBeTruthy();
        expect(k2).not.toBe(k1);

        await expect(api.translate("2501.00006")).rejects.toThrow();
        expect(sentHeaders(spy)["Idempotency-Key"]).toBe(k1);
    });

    it("upload 自动带头；未决同文件重发复用同 key", async () => {
        const file = new File(["x"], "up-idem.tex");
        const spy = stubFetch(netFail);
        await expect(api.upload(file)).rejects.toThrow();
        const k1 = sentHeaders(spy)["Idempotency-Key"];
        expect(k1).toBeTruthy();
        // multipart 不得手写 content-type（浏览器自产 boundary）——idem 头不破坏
        expect(sentHeaders(spy)).not.toHaveProperty("content-type");

        await expect(api.upload(file)).rejects.toThrow();
        expect(sentHeaders(spy)["Idempotency-Key"]).toBe(k1);

        // 另一文件 → 另一意图 → 新 key
        await expect(api.upload(new File(["y"], "up-idem-2.tex"))).rejects.toThrow();
        const k2 = sentHeaders(spy)["Idempotency-Key"];
        expect(k2).toBeTruthy();
        expect(k2).not.toBe(k1);
    });

    it("shareImport 自动带头；成功后同包再导入→新 key", async () => {
        const file = new File(["z"], "bundle-idem.share.zip");
        const spy = stubFetch();
        await api.shareImport(file);
        const k1 = sentHeaders(spy)["Idempotency-Key"];
        expect(k1).toBeTruthy();

        await api.shareImport(file);
        const k2 = sentHeaders(spy)["Idempotency-Key"];
        expect(k2).toBeTruthy();
        expect(k2).not.toBe(k1);
    });

    it("显式 byok.idempotencyKey → 原样透传、不占意图位", async () => {
        const spy = stubFetch();
        await api.translate("2501.00008", undefined, { idempotencyKey: "explicit-1" });
        expect(sentHeaders(spy)["Idempotency-Key"]).toBe("explicit-1");

        // 显式 key 不进 pending——同参自动提交走自己的生成路径
        await api.translate("2501.00008");
        const k = sentHeaders(spy)["Idempotency-Key"];
        expect(k).toBeTruthy();
        expect(k).not.toBe("explicit-1");
    });

    it("改 apiKey 重发同一提交→仍复用 idem key（凭证不是意图）", async () => {
        const spy = stubFetch(netFail);
        await expect(api.translate("2501.00009", undefined, { apiKey: "sk-a" })).rejects.toThrow();
        const k1 = sentHeaders(spy)["Idempotency-Key"];

        await expect(api.translate("2501.00009", undefined, { apiKey: "sk-b" })).rejects.toThrow();
        expect(sentHeaders(spy)["Idempotency-Key"]).toBe(k1);
        expect(sentHeaders(spy)["X-Texlate-Key"]).toBe("sk-b");
    });

    it("改 baseUrl/model 重发同一提交→新 idem key（端点是意图语义）", async () => {
        const spy = stubFetch(netFail);
        await expect(
            api.translate("2501.00010", undefined, { baseUrl: "https://a" }),
        ).rejects.toThrow();
        const k1 = sentHeaders(spy)["Idempotency-Key"];
        expect(k1).toBeTruthy();

        await expect(
            api.translate("2501.00010", undefined, { baseUrl: "https://b" }),
        ).rejects.toThrow();
        const k2 = sentHeaders(spy)["Idempotency-Key"];
        expect(k2).toBeTruthy();
        expect(k2).not.toBe(k1);

        // model 同入指纹——同端点换模型仍属另一意图
        await expect(
            api.translate("2501.00010", undefined, {
                baseUrl: "https://a",
                model: "m2",
            }),
        ).rejects.toThrow();
        const k3 = sentHeaders(spy)["Idempotency-Key"];
        expect(k3).toBeTruthy();
        expect(k3).not.toBe(k1);
        expect(k3).not.toBe(k2);
    });
});
