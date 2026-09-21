// _fetchkit —— fetch 桩脚手架（REST/api 层测试共享）：resp202 回执、
// stubFetch 全局桩、sentHeaders 头读取——byok/idempotency 等文件的手抄
// 三件套归一到此（_* 前缀 = 测试内件，vite include 只收 *.test.ts）。
// RESP/flush 单一事实源在 _homekit.ts——本件再导出，收养方一处 import。
// 同 _homekit/_taskkit 约定：不得静态 import 任何经 ../api/client 的
// 应用模块（本件会在 vi.mock 工厂内被 await，静态引成环、被测面绑真 api）。

import { vi } from "vitest";
import { flush, RESP } from "./_homekit";

export { flush, RESP };

/** 202 queued 回执 Response——translate/upload/shareImport 同形 */
export function resp202() {
    return new Response(JSON.stringify(RESP), {
        status: 202,
        headers: { "content-type": "application/json" },
    });
}

/** vi.stubGlobal("fetch") 一体桩：缺省 impl 回 resp202，可传自定义 fetch */
export function stubFetch(impl?: typeof fetch) {
    const spy = vi.fn<typeof fetch>(impl ?? (() => Promise.resolve(resp202())));
    vi.stubGlobal("fetch", spy);
    return spy;
}

/** 第 i 次（默认最后一次）fetch 调用的 headers（RequestInit.headers 平面对象） */
export function sentHeaders(
    spy: ReturnType<typeof stubFetch>,
    i = -1,
): Record<string, string> {
    const init = spy.mock.calls.at(i)?.[1];
    return (init?.headers ?? {}) as Record<string, string>;
}
