import { describe, expect, it } from "vitest";
import { mergeResultStats } from "../taskStats";

describe("mergeResultStats（done.stats 优先 + counters/usage 兜底）", () => {
    it("done.stats 优先：tokens/seconds/failed 取 done 帧", () => {
        const r = mergeResultStats(
            { tokens: 8000, seconds: 264, chunks_failed: 2 },
            { tokens: 5000, failed: 9 },
            undefined,
        );
        expect(r).toMatchObject({ tokens: 8000, seconds: 264, failed: 2 });
    });

    it("usage 细分透传：calls/prompt/completion/latency 各字段独立", () => {
        const r = mergeResultStats(undefined, { tokens: 9100 }, {
            calls: 24,
            prompt_tokens: 6100,
            completion_tokens: 3000,
            latency_s: 41.6,
        });
        expect(r).toMatchObject({
            tokens: 9100,
            calls: 24,
            prompt: 6100,
            completion: 3000,
            latency: 41.6,
        });
    });

    it("无 done 帧时 counters 兜底 tokens/failed", () => {
        const r = mergeResultStats(undefined, { tokens: 1200, failed: 3 }, undefined);
        expect(r).toMatchObject({ tokens: 1200, failed: 3, seconds: undefined });
    });

    it("三源全缺席 → null（stat-strip 不渲染）", () => {
        expect(mergeResultStats(undefined, undefined, undefined)).toBeNull();
        expect(mergeResultStats({}, {}, {})).toBeNull();
    });

    it("仅 usage 在场也渲染（老 done 帧缺 stats 的场景）", () => {
        const r = mergeResultStats(undefined, undefined, { calls: 7 });
        expect(r).toMatchObject({ calls: 7 });
    });

    it("usage 部分字段缺席 → 对应 stat 缺席，其余照常", () => {
        const r = mergeResultStats({ tokens: 500 }, undefined, {
            prompt_tokens: 300,
            completion_tokens: 200,
        });
        expect(r).toMatchObject({
            tokens: 500,
            prompt: 300,
            completion: 200,
            calls: undefined,
            latency: undefined,
        });
    });
});
