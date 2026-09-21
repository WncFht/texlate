// discover/feed —— Discover 页第一页 sessionStorage SWR 缓存与跨页去重的纯
// 函数核：storage/now 可注入（vitest node 环境无 sessionStorage，测试传内存
// fake），view.ts/taskFiles.ts/axsearch.ts 同例。

import type { DiscoverPaper } from "../api/client";

/** 会话态保鲜窗——与服务端 feed 缓存（600s）同档，窗口内 hash 往返不重拉 */
export const FEED_TTL_MS = 600_000;
/** SWR 存储窗——与 FEED_TTL_MS 同档共用单一口径：模块态与 sessionStorage
    两层缓存同步过期，别各写一份 600s 漂移 */
export const FEED_CACHE_TTL = FEED_TTL_MS;
export const FEED_CACHE = "texlate.discover.feed";
export const FEED_CACHE_MAX = 12;

type FeedCacheMap = Record<string, { ts: number; rows: DiscoverPaper[] }>;
/** 可注入存储——缺省走 sessionStorage（缺省引用在 try 内解，无 DOM 环境安返 null） */
type StorageLike = Pick<Storage, "getItem" | "setItem">;

/** 读当前 sort|interval 键的第一页缓存：超 TTL/坏 JSON/空表 → null */
export const readFeedCache = (
    key: string,
    storage?: StorageLike,
    now: number = Date.now(),
): DiscoverPaper[] | null => {
    try {
        const st = storage ?? sessionStorage;
        const raw = st.getItem(FEED_CACHE);
        if (!raw) return null;
        const map = JSON.parse(raw) as FeedCacheMap;
        const e = map[key];
        if (!e || now - e.ts > FEED_CACHE_TTL) return null;
        return Array.isArray(e.rows) && e.rows.length ? e.rows : null;
    } catch {
        return null;
    }
};

/** 写第一页缓存；超 FEED_CACHE_MAX 逐最旧键（同键刷新不占额，容量挡多榜组合） */
export const writeFeedCache = (
    key: string,
    rows: DiscoverPaper[],
    storage?: StorageLike,
    now: number = Date.now(),
) => {
    try {
        const st = storage ?? sessionStorage;
        const raw = st.getItem(FEED_CACHE);
        const map = (raw ? JSON.parse(raw) : {}) as FeedCacheMap;
        map[key] = { ts: now, rows };
        const ks = Object.keys(map);
        for (const k of ks
            .sort((a, b) => map[a].ts - map[b].ts)
            .slice(0, Math.max(0, ks.length - FEED_CACHE_MAX))) {
            delete map[k];
        }
        st.setItem(FEED_CACHE, JSON.stringify(map));
    } catch {
        /* quota/隐私模式——缓存只是提速 */
    }
};

/** 卡 id 取 universal_paper_id（arXiv id），缺席回 canonical_id */
export const cardId = (p: DiscoverPaper) =>
    p.universal_paper_id || p.canonical_id || "";

/** feed 行去重：卡 id 再缺席回行 id；seen 跨调用复用（翻页累计已见） */
export const dedup = (rows: DiscoverPaper[], seen: Set<string>) =>
    rows.filter((r) => {
        const k = cardId(r) || r.id;
        if (!k || seen.has(k)) return false;
        seen.add(k);
        return true;
    });
