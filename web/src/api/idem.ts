// Idempotency-Key 生命周期——「提交意图」粒度。
//
// server `_create_and_enqueue` 按 options.idempotency_key 去重（同 tenant 命中
// 直返 202 {cache:"idempotent"}，不建行不入队；任务删除后 key 可复用）。
// key 绑定提交内容指纹：请求未决（网络层失败，服务端可能已收单）期间同参
// 重发/双击并发复用同 key；拿到任何 HTTP 响应（成功或错误）即结案，其后
// 同参提交视为新意图、生成新 key。byok.idempotencyKey 显式传入时透传，
// 不插手生命周期。

import type { ByokHeaders } from "./types";

const pendingCreate = new Map<string, string>();

function newKey(): string {
    const c = globalThis.crypto;
    if (c?.randomUUID) return c.randomUUID();
    // http://LAN 等非安全上下文无 randomUUID——getRandomValues 不受限
    if (c?.getRandomValues) {
        const b = c.getRandomValues(new Uint8Array(16));
        return Array.from(b, (x) => x.toString(16).padStart(2, "0")).join("");
    }
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
}

/** 取该意图在飞的 key；无则生成并登记 */
export function intentKey(fp: string): string {
    const key = pendingCreate.get(fp) ?? newKey();
    pendingCreate.set(fp, key);
    return key;
}

export function intentSettle(fp: string, key: string): void {
    // 守卫：同 fp 已被后续调用换新 key 时，旧在飞调用的结案不得误删新条目
    if (pendingCreate.get(fp) === key) pendingCreate.delete(fp);
}

/** 提交内容指纹——apiKey 是凭证不是意图，改 key 重试仍复用同一 idem key；
 *  dialect 与 baseUrl/model 同入指纹（同端点不同方言语义不同、非同参提交） */
export function createFp(
    kind: string,
    payload: unknown,
    byok?: ByokHeaders,
): string {
    const semantics = byok
        ? { baseUrl: byok.baseUrl, model: byok.model, dialect: byok.dialect }
        : null;
    return JSON.stringify([kind, payload, semantics]);
}

export function fileFp(file: File): string {
    return `${file.name}:${file.size}:${file.lastModified}`;
}
