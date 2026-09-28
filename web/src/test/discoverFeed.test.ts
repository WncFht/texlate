import { describe, expect, it } from "vitest";
import type { DiscoverPaper } from "../api/client";
import {
    cardId,
    dedup,
    FEED_CACHE,
    FEED_CACHE_MAX,
    FEED_CACHE_TTL,
    readFeedCache,
    writeFeedCache,
} from "../discover/feed";

/** 内存 StorageLike——node 环境无 sessionStorage，注入 fake 直测 */
const memStorage = () => {
    const m = new Map<string, string>();
    return {
        map: m,
        getItem: (k: string) => m.get(k) ?? null,
        setItem: (k: string, v: string) => void m.set(k, v),
    };
};

const paper = (over: Partial<DiscoverPaper>): DiscoverPaper => ({
    title: "t",
    ...over,
});

describe("readFeedCache（第一页 SWR 缓存读）", () => {
    const rows = [paper({ universal_paper_id: "2501.00001" })];

    it("命中键 + TTL 内 → 返回缓存行", () => {
        const st = memStorage();
        writeFeedCache("Hot|7 Days", rows, st, 1000);
        expect(readFeedCache("Hot|7 Days", st, 2000)).toEqual(rows);
    });

    it("键不匹配（别的 sort|interval 组合）→ null", () => {
        const st = memStorage();
        writeFeedCache("Hot|7 Days", rows, st, 1000);
        expect(readFeedCache("Views|7 Days", st, 2000)).toBeNull();
    });

    it("TTL 边界：now-ts == TTL 仍命中，TTL+1 过期", () => {
        const st = memStorage();
        writeFeedCache("k", rows, st, 10_000);
        expect(readFeedCache("k", st, 10_000 + FEED_CACHE_TTL)).toEqual(rows);
        expect(readFeedCache("k", st, 10_000 + FEED_CACHE_TTL + 1)).toBeNull();
    });

    it("坏 JSON / 空表 / 无存储 → null（不抛）", () => {
        const st = memStorage();
        st.map.set(FEED_CACHE, "{oops");
        expect(readFeedCache("k", st)).toBeNull();
        writeFeedCache("k", [], st, 1);
        expect(readFeedCache("k", st, 2)).toBeNull(); // 空 rows 不当命中
        // storage 参数缺席且环境无 sessionStorage（node）→ 安返 null
        expect(readFeedCache("k")).toBeNull();
    });
});

describe("writeFeedCache（容量逐最旧）", () => {
    it("超 FEED_CACHE_MAX 逐最旧 sort|interval 键，同键刷新不占额", () => {
        const st = memStorage();
        // 填满 MAX 个不同键，ts 递增
        for (let i = 0; i < FEED_CACHE_MAX; i++) {
            writeFeedCache(`k${i}`, [paper({ id: `p${i}` })], st, i + 1);
        }
        // 同键重写不膨胀
        writeFeedCache("k0", [paper({ id: "p0b" })], st, 999);
        expect(Object.keys(JSON.parse(st.map.get(FEED_CACHE)!))).toHaveLength(
            FEED_CACHE_MAX,
        );
        // 第 MAX+1 个新键 → 最旧的 k1 出局（k0 ts 已刷新成最新）
        writeFeedCache("newest", [paper({ id: "pn" })], st, 1000);
        const map = JSON.parse(st.map.get(FEED_CACHE)!) as Record<
            string,
            { ts: number }
        >;
        expect(Object.keys(map)).toHaveLength(FEED_CACHE_MAX);
        expect(map.k1).toBeUndefined();
        expect(map.k0).toBeDefined();
        expect(map.newest).toBeDefined();
    });

    it("setItem 抛错（quota/隐私模式）→ 静默吞", () => {
        const st = {
            getItem: () => null,
            setItem: () => {
                throw new Error("quota");
            },
        };
        expect(() => writeFeedCache("k", [], st)).not.toThrow();
    });
});

describe("cardId/dedup（跨页去重稳定键）", () => {
    it('卡 id 回退链：universal_paper_id → canonical_id → ""', () => {
        expect(
            cardId(paper({ universal_paper_id: "u1", canonical_id: "c1" })),
        ).toBe("u1");
        expect(cardId(paper({ canonical_id: "c1" }))).toBe("c1");
        expect(cardId(paper({}))).toBe("");
    });

    it("dedup 回退链：卡 id 缺席再回行 id；无 id 行丢弃", () => {
        const seen = new Set<string>();
        const rows = [
            paper({ universal_paper_id: "u1" }),
            paper({ universal_paper_id: "u1", title: "dup" }),
            paper({ canonical_id: "c1" }),
            paper({ id: "row-id" }),
            paper({}),
        ];
        const out = dedup(rows, seen);
        expect(
            out.map((r) => r.universal_paper_id ?? r.canonical_id ?? r.id),
        ).toEqual(["u1", "c1", "row-id"]);
    });

    it("翻页：page>1 对累计 seen 集去重（榜单流动推回同篇）", () => {
        const seen = new Set<string>(["u1", "c1"]);
        const out = dedup(
            [
                paper({ universal_paper_id: "u1" }), // 已见 → 丢
                paper({ universal_paper_id: "u2" }), // 新 → 留
            ],
            seen,
        );
        expect(out).toHaveLength(1);
        expect(out[0].universal_paper_id).toBe("u2");
        expect(seen.has("u2")).toBe(true); // seen 被累计更新
    });
});
