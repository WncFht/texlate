// search —— Home arXiv 输入解析（parseArxivId）+ 输入即搜建议状态机：
// 300ms 防抖打 alphaxiv 快搜（只在输入「不像 arXiv id」时发起——能解析
// 成 id 的是待提交态不是检索态）、seq 代次闸丢被顶替的慢响应、下拉键盘
// 契约（↓↑ 环绕 / Enter 回填 / Esc 关）。自 pages/Home.tsx 拆出。

import { createSignal } from "solid-js";
import type { DiscoverHit } from "../api/client";
import { createDebouncedAxSearch } from "../axsearch";

const ARXIV_RE =
    /^(?:\d{4}\.\d{4,5}(?:v\d+)?|[a-z-]+(?:\.[A-Z][a-zA-Z]+)?\/\d{7}(?:v\d+)?)$/i;

// 服务端 normalize_arxiv_id 的轻量版：剥 arXiv: 前缀、各路径段 URL、
// 尾部斜杠与 .pdf，再按新/旧 id 形白名单判
export function parseArxivId(raw: string): string | null {
    const s = raw.trim().replace(/^arxiv\s*:\s*/i, "");
    const bare = s.replace(/\.pdf$/i, "");
    if (ARXIV_RE.test(bare)) return bare;
    const m = s.match(
        /arxiv\.org\/(?:abs|pdf|html|src|e-print|format)\/+([^\s?#]+?)\/*?(?:\.pdf)?(?:[?#].*)?$/i,
    );
    return m && ARXIV_RE.test(m[1]) ? m[1] : null;
}

export function createHomeSuggest(deps: {
    /** 卸载闸——在飞请求不随卸载取消，但迟到响应不得再落地 */
    alive(): boolean;
    /** 建议命中回填输入框（用户确认后再提交） */
    fillId(id: string): void;
}) {
    // 输入框快搜建议（alphaXiv）：hits=null=未发起/已关；[]=搜过无匹配
    const [hits, setHits] = createSignal<DiscoverHit[] | null>(null);
    // 键盘导航 active 项（-1=无；↓↑ 与悬停同写一份，鼠标键盘不分裂）
    const [activeHit, setActiveHit] = createSignal(-1);
    /** 下拉开/关唯一出口——hits 变即复位 active */
    const setSuggest = (v: DiscoverHit[] | null) => {
        setHits(v);
        setActiveHit(-1);
    };

    /**
     * 输入即搜喂入口：调用方先写输入信号/清格式错，再交本件判发起。
     * 300ms 防抖打 alphaxiv 快搜（axsearch.ts 共享工厂）——能解析成 id
     * 的输入不发起（待提交态）；失败同空查询处理（关下拉）。
     */
    const axSearch = createDebouncedAxSearch({
        alive: deps.alive,
        gate: (q) => parseArxivId(q) !== null,
        onClear: () => setSuggest(null),
        onResult: setSuggest,
        onError: () => setSuggest(null),
    });
    const feed = axSearch.feed;

    /** 建议行点击/Enter 选中 → 回填输入框（用户确认后再提交） */
    const pickHit = (h: DiscoverHit) => {
        if (h.paperId) deps.fillId(h.paperId);
        setSuggest(null);
    };

    /**
     * 建议下拉键盘契约：↓↑ 在选项间环绕移动 active 项，Enter 选中回填，
     * Esc 关下拉。列表合上或未出条时全键放行（Enter 走表单提交）。
     */
    const onSuggestKey = (e: KeyboardEvent) => {
        const list = hits();
        if (e.key === "Escape") {
            if (list !== null) {
                e.preventDefault();
                setSuggest(null);
            }
            return;
        }
        if (!list?.length) return;
        if (e.key === "ArrowDown" || e.key === "ArrowUp") {
            e.preventDefault();
            const n = list.length;
            const next =
                e.key === "ArrowDown"
                    ? (activeHit() + 1) % n
                    : (activeHit() - 1 + n) % n;
            setActiveHit(next);
            document
                .getElementById(`ax-sug-${next}`)
                ?.scrollIntoView({ block: "nearest" });
            return;
        }
        if (e.key === "Enter" && activeHit() >= 0) {
            e.preventDefault();
            pickHit(list[activeHit()]);
        }
    };

    /** blur/点外面关下拉（合上的唯一出口仍是 setSuggest——active 复位） */
    const close = () => setSuggest(null);

    /** 卸载清防抖 timer——在飞 fetch 由 alive 闸兜底 */
    const cancel = axSearch.cancel;

    return {
        hits,
        activeHit,
        setActiveHit,
        feed,
        pickHit,
        onSuggestKey,
        close,
        cancel,
    };
}

export type HomeSuggest = ReturnType<typeof createHomeSuggest>;
