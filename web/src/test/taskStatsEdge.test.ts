// mergeResultStats 补角：taskStats.test.ts 已盖优先级/兜底/空态主路径，本文件补——
// 逐字段独立兜底（非整体二选一）、?? 语义（0 不回退）、usage 零值/仅 model、
// done.stats 未知附加键不点亮、返回形状固定七键。

import { describe, expect, it } from "vitest";
import { mergeResultStats } from "../taskStats";

describe("mergeResultStats 边界", () => {
    it("逐字段兜底：stats.tokens 胜出，chunks_failed 缺席 → counters.failed 补位", () => {
        const r = mergeResultStats({ tokens: 100 }, { tokens: 999, failed: 7 });
        expect(r).toMatchObject({ tokens: 100, failed: 7 });
    });

    it("0 是有效值不触发兜底：chunks_failed=0 → failed=0（非 counters.failed）", () => {
        const r = mergeResultStats({ chunks_failed: 0 }, { failed: 5 });
        expect(r?.failed).toBe(0);
    });

    it("tokens=0 同理不回退 counters.tokens", () => {
        const r = mergeResultStats({ tokens: 0 }, { tokens: 9000 });
        expect(r?.tokens).toBe(0);
    });

    it("usage 零值字段照常点亮（calls=0/latency=0 不等于缺席）", () => {
        const r = mergeResultStats(undefined, undefined, {
            calls: 0,
            latency_s: 0,
        });
        expect(r).toMatchObject({ calls: 0, latency: 0 });
    });

    it("usage 仅 model（无计量字段）→ null（面板不渲染）", () => {
        expect(mergeResultStats(undefined, undefined, { model: "gpt-x" })).toBeNull();
    });

    it("done.stats 只有未识别附加键 → 不点亮（附加键不进 ResultStats）", () => {
        expect(mergeResultStats({ chunk_ms: 42, note: "x" })).toBeNull();
    });

    it("仅 seconds（done 帧缺 tokens）也点亮", () => {
        const r = mergeResultStats({ seconds: 61 });
        expect(r).toMatchObject({ seconds: 61, tokens: undefined });
    });

    it("返回形状固定七键：未中字段显式 undefined 而非缺键", () => {
        const r = mergeResultStats({ tokens: 1 }, { failed: 2 }, { calls: 3 });
        expect(r).toStrictEqual({
            tokens: 1,
            seconds: undefined,
            failed: 2,
            calls: 3,
            prompt: undefined,
            completion: undefined,
            latency: undefined,
        });
    });
});
