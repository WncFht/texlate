// axsearch —— alphaXiv 快搜的防抖搜索状态机：Discover 全页搜与 Home 输入
// 即搜共用（300ms 防抖 + seq 代次闸 + alive 卸载闸）。两侧差异收进三出口：
// onClear=空查询/被 gate 拦、onResult=命中落地、onError=失败映射。

import { api, type DiscoverHit } from "./api/client";

/**
 * 300ms 防抖打 alphaXiv 快搜：trim 后空串或 gate 判非检索输入即清场不发起；
 * seq 代次闸丢被顶替的慢响应，alive 闸挡卸载后落地。
 */
export const createDebouncedAxSearch = (deps: {
    /** 返回 true 视为非检索输入（同空查询——清结果不发起） */
    gate?(q: string): boolean;
    /** 迟到响应落地前的存活闸；缺省恒真（组件内态卸载即毁） */
    alive?(): boolean;
    onClear(): void;
    onResult(res: DiscoverHit[]): void;
    onError(): void;
}) => {
    let searchTimer = 0;
    // seq 防慢响应盖新查询（旧响应落地时输入早已变）：feed/cancel 同步换代，
    // 让防抖窗内未发请求的间隙里旧响应也立刻作废，不等到下个 timer 点火
    let searchSeq = 0;
    const feed = (v: string) => {
        window.clearTimeout(searchTimer);
        const seq = ++searchSeq;
        const q = v.trim();
        if (!q || deps.gate?.(q)) {
            deps.onClear();
            return;
        }
        searchTimer = window.setTimeout(() => {
            api.discoverSearch(q)
                .then((res) => {
                    if ((deps.alive?.() ?? true) && seq === searchSeq) {
                        deps.onResult(res);
                    }
                })
                .catch(() => {
                    if ((deps.alive?.() ?? true) && seq === searchSeq) {
                        deps.onError();
                    }
                });
        }, 300);
    };
    /** 卸载清防抖 timer + 换代——在飞 fetch 由 alive/seq 闸兜底 */
    const cancel = () => {
        window.clearTimeout(searchTimer);
        searchSeq++;
    };
    return { feed, cancel };
};
