// API client —— 对齐 docs/research/product/web-layer.md §2。
// Base /api；错误一律 {detail, code?}；SSE 走原生 EventSource
// （浏览器自动带 Last-Event-ID 重放，§2.2 的重连语义天然满足）。
//
// 拆分门面粉：types=类型面 / rest=REST 端点 / sse=事件流 / idem=幂等键。
// 导入侧一律走本文件（mock/测试以本模块为缝）。

export * from "./types";
export { api, landingHash, REQUEST_TIMEOUT_MS } from "./rest";
export {
    forgetTaskEvents,
    openTaskEvents,
    type TaskChannel,
    type TaskEventHandlers,
    type TransportState,
} from "./sse";
