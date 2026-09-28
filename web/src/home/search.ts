// search —— Home arXiv 输入解析（parseArxivId）+ 输入即搜建议状态机：
// 300ms 防抖打 alphaxiv 快搜（只在输入「不像 arXiv id」时发起——能解析
// 成 id 的是待提交态不是检索态）、seq 代次闸丢被顶替的慢响应、下拉键盘
// 契约（↓↑ 环绕 / Enter 回填 / Esc 关）。自 pages/Home.tsx 拆出。

import { createSignal } from "solid-js";
import type { DiscoverHit } from "../api/client";
import { canonStrip } from "../arxidcanon";
import { createDebouncedAxSearch } from "../axsearch";

// 剥壳段在 arxidcanon.ts 单源（strict 臂——与服务端 arxiv/fetch.canon
// 同口径 canon spec §2 的 JS 镜像）。本层只叠提交校验：vN 合法性
// （v0 拒）、新旧形 id 判 + MM+era 白名单闸。锚定前缀剥（不 urlparse
// 任意 host）结构性拒端口/双斜杠/怪 scheme/寄生域名；仍比服务端窄是
// 刻意的——怪输入留给服务端 400 回来报错。

const ID_NEW_RX = /^(\d{2})(\d{2})\.(\d{4,5})$/;
const ID_OLD_RX = /^([a-z-]+)\/(\d{2})(\d{2})\d{3}$/;

/**
 * 用户输入 → canon arXiv id（`base` 或 `basevN`）；不可解析 → null。
 * era 闸：新形 YYMM∈[0704,当前YYMM]（9912=2099-12 未来态拒——spec
 * 「YYMM≥0704」的不可能 id 判例靠上界实现）；旧形 YYMM∈9107..9912∪
 * 0000..0703。v0/v1234 拒；v03→v3、V→v 归一。
 */
export function parseArxivId(raw: string): string | null {
    const { base: s, ver } = canonStrip(raw, true);
    if (ver !== null && ver < 1) return null; // v0 判非法（不静默去钉）

    const now = new Date();
    const curYYMM = (now.getFullYear() % 100) * 100 + (now.getMonth() + 1);
    const nm = ID_NEW_RX.exec(s);
    if (nm) {
        const mm = Number(nm[2]);
        const yymm = Number(nm[1]) * 100 + mm;
        if (mm < 1 || mm > 12) return null;
        if (yymm < 704 || yymm > curYYMM) return null;
    } else {
        const om = ID_OLD_RX.exec(s);
        if (!om) return null;
        const mm = Number(om[3]);
        const yymm = Number(om[2]) * 100 + mm;
        if (mm < 1 || mm > 12) return null;
        if (!(yymm >= 9107 || yymm <= 703)) return null;
    }
    return ver != null ? `${s}v${ver}` : s;
}

export function createHomeSuggest(deps: {
    /** 卸载闸——在飞请求不随卸载取消，但迟到响应不得再落地 */
    alive(): boolean;
    /** 建议命中回填输入框（用户确认后再提交）——契约含清格式错态
     *  （idBad/error）：下拉开着时也可提交落得 aria-invalid，回填的是
     *  合法 id，残留错态会让有效输入挂 invalid 标记 */
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
