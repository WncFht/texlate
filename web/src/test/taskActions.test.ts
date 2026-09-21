// taskActions 回归（createHtmlFallback 为主）：
//  - can() 闸：kind==="arxiv" + arxiv_id + 取源段错误码三枚才放行
//  - run()：options 全量透传但摘 idempotency_key、改 source:"html"，
//    model/target_lang/glossary 随行；nav 落 reader hash
//  - 失败面：htmlErr 走 apiErrText（ApiError→detail，其余→message）

import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    translate: vi.fn(),
    retry: vi.fn(),
}));

// vi.mock 提升限制——工厂体内再引 _homekit（顶层 import 进不了 hoisted 作用域）
vi.mock("../api/client", async (importOriginal) =>
    (await import("./_homekit")).buildApiModule(
        await importOriginal<typeof import("../api/client")>(),
        mocks,
    ),
);

import { ApiError, type TaskSnapshot } from "../api/client";
import { createHtmlFallback, createTaskRetry } from "../reader/taskActions";
import { resetHomeMocks } from "./_homekit";
import { snap as fakeSnap } from "./fakes";

// fault 源任务夹具——缺省面走 fakes.snap，本件只钉 fallback 相关字段
const snap = (over: Partial<TaskSnapshot> = {}): TaskSnapshot =>
    fakeSnap("t_src", {
        status: "fault",
        progress: 30,
        updated_at: 1_700_000_001,
        arxiv_id: "2501.00001",
        model: "swe-2-medium",
        target_lang: "zh",
        glossary: "gloss.tex",
        options: {
            concurrency: 4,
            prefer: "fresh",
            idempotency_key: "idem-123",
        },
        error: { code: "arxiv_fetch", message: "fetch boom" },
        ...over,
    });

const RESP = {
    task_id: "t_new",
    status: "queued",
    events_url: "/api/task/t_new",
    reader_url: "/api/task/t_new/reader",
};

beforeEach(() => {
    resetHomeMocks(mocks);
    // 本件 RESP 是新任务回执（t_new）——非 _homekit RESP 的 t_…0f01 形，自留
    mocks.translate.mockResolvedValue(RESP);
});

describe("createHtmlFallback.can()", () => {
    it("放行：arxiv kind + arxiv_id + 取源段错误码", () => {
        for (const code of ["arxiv_fetch", "no_latex_source", "pdf_wrapper"]) {
            const a = createHtmlFallback({
                task: () => snap({ error: { code, message: "x" } }),
                nav: vi.fn(),
            });
            expect(a.can()).toBe(true);
        }
    });

    it("拦截：无任务 / 非 arxiv kind / 无 arxiv_id / 非取源段错误码 / 无错误", () => {
        const nav = vi.fn();
        expect(
            createHtmlFallback({ task: () => null, nav }).can(),
        ).toBe(false);
        for (const over of [
            { kind: "upload_tex" },
            { arxiv_id: null },
            { error: { code: "compile", message: "x" } },
            { error: null },
        ] as Partial<TaskSnapshot>[]) {
            const a = createHtmlFallback({ task: () => snap(over), nav });
            expect(a.can()).toBe(false);
        }
    });
});

describe("createHtmlFallback.run()", () => {
    it("options 透传 + 摘 idempotency_key + source:html；nav 落新任务 reader", async () => {
        const nav = vi.fn();
        const a = createHtmlFallback({ task: () => snap(), nav });
        await a.run();

        expect(mocks.translate).toHaveBeenCalledTimes(1);
        const [arxivId, body] = mocks.translate.mock.calls[0];
        expect(arxivId).toBe("2501.00001");
        expect(body).toMatchObject({
            model: "swe-2-medium",
            target_lang: "zh",
            glossary: "gloss.tex",
        });
        const options = body?.options as Record<string, unknown>;
        expect(options.source).toBe("html");
        expect(options.concurrency).toBe(4);
        expect(options.prefer).toBe("fresh");
        expect("idempotency_key" in options).toBe(false);
        // 原任务 options 不被就地改写
        expect(snap().options?.idempotency_key).toBe("idem-123");
        expect(nav).toHaveBeenCalledWith("#/reader/t_new");
    });

    it("options 缺席 → 仅注入 source；无 arxiv_id → 不发请求", async () => {
        const a = createHtmlFallback({
            task: () => snap({ options: undefined }),
            nav: vi.fn(),
        });
        await a.run();
        const options = mocks.translate.mock.calls[0][1]
            ?.options as Record<string, unknown>;
        expect(options).toEqual({ source: "html" });

        mocks.translate.mockClear();
        const b = createHtmlFallback({
            task: () => snap({ arxiv_id: undefined }),
            nav: vi.fn(),
        });
        await b.run();
        expect(mocks.translate).not.toHaveBeenCalled();
    });

    it("失败：ApiError → detail；普通 Error → message（无 \"Error: \" 前缀）", async () => {
        mocks.translate.mockRejectedValueOnce(
            new ApiError(502, "网关 502", "fetch_failed"),
        );
        const a = createHtmlFallback({ task: () => snap(), nav: vi.fn() });
        await a.run();
        expect(a.htmlErr()).toBe("网关 502");
        expect(a.htmlBusy()).toBe(false);

        mocks.translate.mockRejectedValueOnce(new Error("net down"));
        await a.run();
        expect(a.htmlErr()).toBe("net down");
    });
});

describe("createTaskRetry（apiErrText 落点）", () => {
    it("ApiError → status/code/detail 全带；普通 Error → message", async () => {
        const onAccepted = vi.fn();
        mocks.retry.mockRejectedValueOnce(
            new ApiError(401, "需要 API Key", "auth_required"),
        );
        const r = createTaskRetry({
            taskId: () => "t_src",
            nav: vi.fn(),
            onAccepted,
        });
        await r.run();
        expect(r.retryError()).toEqual({
            status: 401,
            code: "auth_required",
            message: "需要 API Key",
        });
        expect(onAccepted).not.toHaveBeenCalled();

        mocks.retry.mockRejectedValueOnce(new Error("boom"));
        await r.run();
        expect(r.retryError()?.message).toBe("boom");
    });
});
