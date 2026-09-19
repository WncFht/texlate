// Discover —— alphaXiv 榜单/快搜全页面：sort × interval chips + 头版/索引行 + 加载更多。
// 版面：#1 头版卡（可读大预览）+ 余下索引行（rank + 小预览 + 单行密排）——
// 真序列榜单用编号立层级，别做均质卡墙；meta 独占右列不截断。
// 上游挂在独立页无处隐藏——首屏失败出页面级错误态带重试，翻页失败只出内联重试。
// 排序/窗口/已拉列表全挂模块级信号：hash 往返不丢滚动与页签选择，TTL 管新鲜度；
// loading/failed 是组件内信号（卸载不留卡死态），feedSeq 代次闸丢被顶替的响应。
// 第一页另走 sessionStorage SWR：命中即渲 + 后台 revalidate，reload 也不闪空。

import { createSignal, For, onCleanup, onMount, Show } from "solid-js";
import { api, type DiscoverHit, type DiscoverPaper } from "../api/client";
import { t } from "../i18n";

const PAGE_SIZE = 24;
/** 会话态保鲜窗——与服务端 feed 缓存（600s）同档，窗口内 hash 往返不重拉 */
const FEED_TTL_MS = 600_000;

const SORTS = [
    { value: "Hot", key: "hot" },
    { value: "Views", key: "views" },
    { value: "Likes", key: "likes" },
    { value: "GitHub", key: "github" },
    { value: "Comments", key: "comments" },
    { value: "Recent", key: "recent" },
] as const;

const INTERVALS = [
    { value: "3 Days", key: "d3" },
    { value: "7 Days", key: "d7" },
    { value: "30 Days", key: "d30" },
    { value: "90 Days", key: "d90" },
    { value: "All time", key: "all" },
] as const;

// ---- 会话级模块态：路由往返保留选择与已加载页（TTL 内不回流重拉） ----
const [sort, setSort] = createSignal<string>("Hot");
const [interval, setInterval] = createSignal<string>("7 Days");
const [papers, setPapers] = createSignal<DiscoverPaper[]>([]);
const [page, setPage] = createSignal(0);
const [endFeed, setEndFeed] = createSignal(false);
let lastFeedAt = 0;
/** feed 请求代次——每次 fetchPage 自增，落地时 seq 不一致即丢弃（切榜/翻页顶替） */
let feedSeq = 0;

// ---- 第一页 sessionStorage SWR：reload/超 TTL 先即渲缓存再后台纠偏 ----
const FEED_CACHE = "texlate.discover.feed";
const FEED_CACHE_TTL = 600_000;
const FEED_CACHE_MAX = 12;

const feedCacheKey = () => `${sort()}|${interval()}`;

const readFeedCache = (): DiscoverPaper[] | null => {
    try {
        const raw = sessionStorage.getItem(FEED_CACHE);
        if (!raw) return null;
        const map = JSON.parse(raw) as Record<
            string,
            { ts: number; rows: DiscoverPaper[] }
        >;
        const e = map[feedCacheKey()];
        if (!e || Date.now() - e.ts > FEED_CACHE_TTL) return null;
        return Array.isArray(e.rows) && e.rows.length ? e.rows : null;
    } catch {
        return null;
    }
};

const writeFeedCache = (rows: DiscoverPaper[]) => {
    try {
        const raw = sessionStorage.getItem(FEED_CACHE);
        const map = (
            raw ? JSON.parse(raw) : {}
        ) as Record<string, { ts: number; rows: DiscoverPaper[] }>;
        map[feedCacheKey()] = { ts: Date.now(), rows };
        const ks = Object.keys(map);
        // 超上限逐最旧（同一板面反复刷只换同键，容量挡的是多榜组合）
        for (const k of ks
            .sort((a, b) => map[a].ts - map[b].ts)
            .slice(0, Math.max(0, ks.length - FEED_CACHE_MAX))) {
            delete map[k];
        }
        sessionStorage.setItem(FEED_CACHE, JSON.stringify(map));
    } catch {
        /* quota/隐私模式——缓存只是提速 */
    }
};

/** 卡 id 取 universal_paper_id（arXiv id），缺席回 canonical_id */
const cardId = (p: DiscoverPaper) =>
    p.universal_paper_id || p.canonical_id || "";

const cardDesc = (p: DiscoverPaper) =>
    p.feed_description ||
    p.paper_summary?.feedDescription ||
    p.paper_summary?.summary ||
    "";

/** meta 行：浏览数 · 发表日期 · GitHub stars（有啥出啥，拼一行） */
const cardMeta = (p: DiscoverPaper): string => {
    const parts: string[] = [];
    const v = p.metrics?.visits_count;
    const visits = v?.last_7_days ?? v?.all;
    if (visits != null) {
        parts.push(t.discover.views.replace("{n}", String(visits)));
    }
    const date = p.publication_date?.slice(0, 10);
    if (date) parts.push(date);
    if (p.github_stars) parts.push(`★ ${p.github_stars}`); // 0 star 不出徽
    return parts.join(" · ");
};

const dedup = (rows: DiscoverPaper[], seen: Set<string>) =>
    rows.filter((r) => {
        const k = cardId(r) || r.id;
        if (!k || seen.has(k)) return false;
        seen.add(k);
        return true;
    });

// ---- 密度控制：每行 2..6 张卡（默认 3——预览可读），sessionStorage 持久 ----
const DENSITY_KEY = "texlate.discover.cols";
const COL_MIN: Record<number, number> = {
    2: 430,
    3: 316,
    4: 232,
    5: 182,
    6: 148,
};

const readDensity = () => {
    try {
        const n = Number(sessionStorage.getItem(DENSITY_KEY));
        return n >= 2 && n <= 6 ? n : 3;
    } catch {
        return 3;
    }
};

const [density, setDensity] = createSignal(readDensity());

/** 骨架卡：与 .ax-card 解剖一致（16:9 图区 + 两行文本）防跳动 */
const SkelCards = (props: { n: number }) => (
    <For each={Array.from({ length: props.n })}>
        {() => (
            <article class="ax-card ax-skel" aria-hidden="true">
                <i class="sk-img" />
                <i class="sk-line" />
                <i class="sk-line short" />
            </article>
        )}
    </For>
);

export default function Discover(props: { nav(to: string): void }) {
    const [query, setQuery] = createSignal("");
    // hits=null=未发起/已清空；[]=搜过无匹配——两态驱动结果区显隐
    const [hits, setHits] = createSignal<DiscoverHit[] | null>(null);
    // 组件内瞬态——卸载中飞不残留卡死（旧版挂模块级，fetch finally 被 alive
    // 闸跳过后 loading 永真、chips 全瘫）
    const [loading, setLoading] = createSignal(false);
    const [failed, setFailed] = createSignal(false);
    let searchTimer = 0;
    let searchSeq = 0;
    onCleanup(() => {
        window.clearTimeout(searchTimer);
    });

    const fetchPage = async (p: number) => {
        const seq = ++feedSeq;
        setLoading(true);
        try {
            const res = await api.discoverFeed({
                sort: sort(),
                interval: interval(),
                page: p,
                pageSize: PAGE_SIZE,
            });
            // 被顶替的响应整包丢弃——数据/状态/lastFeedAt 都不落
            if (seq !== feedSeq) return;
            const rows = res.papers ?? [];
            if (p === 1) {
                // 整页替换：缓存命中残留/旧榜单不混入；缓存写展示口径
                const seen = new Set<string>();
                const fresh = dedup(rows, seen);
                setPapers(fresh);
                writeFeedCache(fresh);
            } else {
                // 跨页去重（榜单流动可能把同篇推回后页）——按卡 id 稳定键
                setPapers((prev) => [
                    ...prev,
                    ...dedup(
                        rows,
                        new Set(
                            prev
                                .map((x) => cardId(x) || x.id)
                                .filter((k): k is string => !!k),
                        ),
                    ),
                ]);
            }
            setPage(p);
            if (rows.length < PAGE_SIZE) setEndFeed(true);
            setFailed(false);
            lastFeedAt = Date.now();
        } catch {
            if (seq === feedSeq) setFailed(true);
        } finally {
            if (seq === feedSeq) setLoading(false);
        }
    };

    /** 切榜/切窗口/失败重试同一出口：缓存命中即渲（后台纠偏），否则骨架 */
    const resetFeed = () => {
        setPage(0);
        setEndFeed(false);
        setFailed(false);
        setPapers(readFeedCache() ?? []);
        void fetchPage(1);
    };

    // chips 不设 loading 闸——切换即时生效，被顶替的请求靠 feedSeq 丢
    const pickSort = (v: string) => {
        if (v === sort()) return;
        setSort(v);
        resetFeed();
    };
    const pickInterval = (v: string) => {
        if (v === interval()) return;
        setInterval(v);
        resetFeed();
    };

    onMount(() => {
        // 会话态残留：TTL 内原样呈现（含滚动深度），超时回第一页（有缓存先垫）
        if (!papers().length || Date.now() - lastFeedAt > FEED_TTL_MS) {
            resetFeed();
        }
    });

    /** 300ms 防抖快搜；清空查询即回榜单（seq 防慢响应盖新查询） */
    const onSearchInput = (v: string) => {
        setQuery(v);
        window.clearTimeout(searchTimer);
        const q = v.trim();
        if (!q) {
            searchSeq++;
            setHits(null);
            return;
        }
        searchTimer = window.setTimeout(() => {
            const seq = ++searchSeq;
            api.discoverSearch(q)
                .then((res) => {
                    if (seq === searchSeq) setHits(res);
                })
                .catch(() => {
                    // 搜索失败当无结果——留空态文案，不炸页面
                    if (seq === searchSeq) setHits([]);
                });
        }, 300);
    };

    const searching = () => query().trim().length > 0;

    return (
        <main class="page discover">
            <h1 class="page-title">
                {t.discover.title}
                <span class="ax-via">{t.discover.via}</span>
            </h1>
            <div class="disc-controls">
                <div class="task-chips" role="group" aria-label="sort">
                    <For each={SORTS}>
                        {(s) => (
                            <button
                                type="button"
                                class="task-chip"
                                classList={{ on: sort() === s.value }}
                                aria-pressed={sort() === s.value}
                                onClick={() => pickSort(s.value)}
                            >
                                {t.discover.sorts[s.key]}
                            </button>
                        )}
                    </For>
                </div>
                <div class="task-chips" role="group" aria-label="interval">
                    <For each={INTERVALS}>
                        {(i) => (
                            <button
                                type="button"
                                class="task-chip"
                                classList={{ on: interval() === i.value }}
                                aria-pressed={interval() === i.value}
                                onClick={() => pickInterval(i.value)}
                            >
                                {t.discover.intervals[i.key]}
                            </button>
                        )}
                    </For>
                </div>
                {/* 密度步进：每行 2..6 张——调大读字、调小扫榜；auto-fill
                    在窄屏自动降列 */}
                <div
                    class="ax-density"
                    role="group"
                    aria-label={t.discover.density}
                    title={t.discover.density}
                >
                    <button
                        type="button"
                        class="ax-den-btn"
                        disabled={density() <= 2}
                        aria-label="−"
                        onClick={() => {
                            setDensity((d) => Math.max(2, d - 1));
                            try {
                                sessionStorage.setItem(
                                    DENSITY_KEY,
                                    String(density()),
                                );
                            } catch {
                                /* 忽略 */
                            }
                        }}
                    >
                        −
                    </button>
                    <span class="ax-den-n">{density()}</span>
                    <button
                        type="button"
                        class="ax-den-btn"
                        disabled={density() >= 6}
                        aria-label="+"
                        onClick={() => {
                            setDensity((d) => Math.min(6, d + 1));
                            try {
                                sessionStorage.setItem(
                                    DENSITY_KEY,
                                    String(density()),
                                );
                            } catch {
                                /* 忽略 */
                            }
                        }}
                    >
                        +
                    </button>
                </div>
                <input
                    class="disc-search"
                    type="search"
                    placeholder={t.discover.searchPlaceholder}
                    aria-label={t.discover.searchLabel}
                    value={query()}
                    onInput={(e) => onSearchInput(e.currentTarget.value)}
                />
            </div>

            <Show
                when={!searching()}
                fallback={
                    <div class="disc-hits">
                        <Show when={hits() === null}>
                            <For each={[0, 1, 2]}>
                                {() => <div class="disc-hit skel" />}
                            </For>
                        </Show>
                        <Show when={hits() !== null && !hits()!.length}>
                            <p class="disc-empty muted">
                                {t.discover.searchEmpty}
                            </p>
                        </Show>
                        <For each={hits() ?? []}>
                            {(h) => (
                                <div class="disc-hit">
                                    <div class="disc-hit-body">
                                        <span class="disc-hit-title">
                                            {h.title ?? h.paperId}
                                        </span>
                                        <Show when={h.snippet}>
                                            <span class="disc-hit-snippet">
                                                {h.snippet}
                                            </span>
                                        </Show>
                                    </div>
                                    <Show when={h.paperId}>
                                        <button
                                            type="button"
                                            class="btn-ghost ax-go"
                                            onClick={() =>
                                                props.nav(
                                                    `#/arxiv/${h.paperId}`,
                                                )
                                            }
                                        >
                                            {t.home.translate}
                                        </button>
                                    </Show>
                                </div>
                            )}
                        </For>
                    </div>
                }
            >
                <Show when={failed() && !papers().length && !loading()}>
                    <div class="disc-fail">
                        <p class="form-error">{t.discover.failed}</p>
                        <button
                            type="button"
                            class="btn-ghost"
                            onClick={resetFeed}
                        >
                            {t.discover.retry}
                        </button>
                    </div>
                </Show>
                <div
                    class="ax-grid"
                    aria-busy={loading()}
                    style={{ "--ax-min": `${COL_MIN[density()]}px` }}
                >
                    <For each={papers()}>
                        {(p, i) => {
                            const id = cardId(p);
                            const meta = cardMeta(p);
                            return (
                                <article class="ax-card">
                                    {/* 卡体 → arXiv 摘要页（新标签看英文原文）；
                                        翻译入口在卡底「翻译」按钮 */}
                                    <a
                                        class="ax-card-top"
                                        href={
                                            id
                                                ? `https://arxiv.org/abs/${id}`
                                                : undefined
                                        }
                                        target="_blank"
                                        rel="noreferrer"
                                    >
                                        <Show when={p.image_url}>
                                            <img
                                                class="ax-thumb"
                                                src={p.image_url}
                                                alt=""
                                                loading="lazy"
                                                onLoad={(e) => {
                                                    e.currentTarget.style.opacity =
                                                        "1";
                                                }}
                                                onError={(e) => {
                                                    e.currentTarget.style.display =
                                                        "none";
                                                }}
                                            />
                                        </Show>
                                        <div class="ax-card-head">
                                            <span class="ax-rank">
                                                {String(i() + 1).padStart(
                                                    2,
                                                    "0",
                                                )}
                                            </span>
                                            <h3 class="ax-card-title">
                                                {p.title}
                                            </h3>
                                        </div>
                                        <Show when={cardDesc(p)}>
                                            <p class="ax-card-desc">
                                                {cardDesc(p)}
                                            </p>
                                        </Show>
                                    </a>
                                    <div class="ax-card-foot">
                                        <span class="muted ax-meta">{meta}</span>
                                        <Show when={id}>
                                            <span class="ax-foot-actions">
                                                <button
                                                    type="button"
                                                    class="btn-ghost ax-go"
                                                    onClick={() =>
                                                        props.nav(
                                                            `#/arxiv/${id}`,
                                                        )
                                                    }
                                                >
                                                    {t.home.translate}
                                                </button>
                                                <a
                                                    class="ax-link"
                                                    href={`https://www.alphaxiv.org/abs/${id}`}
                                                    target="_blank"
                                                    rel="noreferrer"
                                                >
                                                    alphaXiv ↗
                                                </a>
                                            </span>
                                        </Show>
                                    </div>
                                </article>
                            );
                        }}
                    </For>
                    {/* 首屏满格骨架 / 翻页尾部骨架——空态文案让位骨架防双闪 */}
                    <Show when={loading() && !papers().length}>
                        <SkelCards n={9} />
                    </Show>
                    <Show when={loading() && papers().length > 0}>
                        <SkelCards n={6} />
                    </Show>
                </div>
                <Show when={!papers().length && !loading() && !failed()}>
                    <p class="disc-empty muted">{t.discover.empty}</p>
                </Show>
                <div class="disc-more">
                    <Show when={papers().length > 0 && failed() && !loading()}>
                        <button
                            type="button"
                            class="btn-ghost"
                            onClick={() => void fetchPage(page() + 1)}
                        >
                            {t.discover.retry}
                        </button>
                    </Show>
                    <Show
                        when={
                            !failed() &&
                            !endFeed() &&
                            papers().length > 0 &&
                            !loading()
                        }
                    >
                        <button
                            type="button"
                            class="btn-ghost"
                            onClick={() => void fetchPage(page() + 1)}
                        >
                            {t.discover.loadMore}
                        </button>
                    </Show>
                </div>
            </Show>
        </main>
    );
}
