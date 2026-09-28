// @vitest-environment jsdom
// 上传进度 client 层：fetch 无上传进度事件——带 onProgress 的 multipart 提交
// 走 XHR（xhr.upload.onprogress → loaded/total）。覆盖：
//   progress 回调触发、Idempotency-Key/BYOK 头经 setRequestHeader、
//   未决重发复用同 key（XHR 路 idem 语义不变）、
//   xhr.timeout=UPLOAD_TIMEOUT_MS(10min) + ontimeout/onabort → TypeError
//   （同 onerror 属「未决」——留 idem key，重试复用不双建）、
//   HTTP 错误 → ApiError、网络失败 → TypeError（未决留 key）。

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RESP } from "./_homekit";

/** 最小 XHR 桩：记录 open/setRequestHeader/send，测试手动驱动 onprogress/onload */
class FakeXHR {
    static instances: FakeXHR[] = [];
    upload = {
        onprogress: null as
            | ((e: {
                  loaded: number;
                  total: number;
                  lengthComputable: boolean;
              }) => void)
            | null,
    };
    headers: Record<string, string> = {};
    method = "";
    url = "";
    status = 0;
    statusText = "";
    responseText = "";
    sentBody: unknown = null;
    onload: (() => void) | null = null;
    onerror: (() => void) | null = null;
    onabort: (() => void) | null = null;
    ontimeout: (() => void) | null = null;
    timeout = 0;

    constructor() {
        FakeXHR.instances.push(this);
    }
    open(method: string, url: string) {
        this.method = method;
        this.url = url;
    }
    setRequestHeader(k: string, v: string) {
        this.headers[k] = v;
    }
    getResponseHeader(k: string) {
        return k.toLowerCase() === "content-type" ? "application/json" : null;
    }
    send(body?: unknown) {
        this.sentBody = body;
    }
    abort() {
        // 真 XHR abort() 触发 abort 事件 → onabort（init.signal 臂亦落此）
        this.onabort?.();
    }
    progress(loaded: number, total: number, computable = true) {
        this.upload.onprogress?.({
            loaded,
            total,
            lengthComputable: computable,
        });
    }
    respond(status: number, body: unknown) {
        this.status = status;
        this.responseText =
            typeof body === "string" ? body : JSON.stringify(body);
        this.onload?.();
    }
}

function stubXhr() {
    FakeXHR.instances = [];
    vi.stubGlobal("XMLHttpRequest", FakeXHR);
    return FakeXHR;
}

const lastXhr = () => {
    const xhr = FakeXHR.instances.at(-1);
    if (!xhr) throw new Error("no XHR instance");
    return xhr;
};

const fetchSpy = vi.fn<typeof fetch>();

beforeEach(() => {
    stubXhr();
    fetchSpy.mockReset();
    vi.stubGlobal("fetch", fetchSpy);
});

afterEach(() => vi.unstubAllGlobals());

import { api, ApiError } from "../api/client";

describe("api.upload/shareImport 上传进度（XHR 路）", () => {
    it("onProgress → xhr.upload.onprogress 触发回调（loaded/total），202 解析 JSON", async () => {
        const prog = vi.fn();
        const p = api.upload(
            new File(["src"], "paper.tex"),
            undefined,
            undefined,
            prog,
        );
        const xhr = lastXhr();

        expect(xhr.method).toBe("POST");
        expect(xhr.url).toBe("/api/upload");
        expect(xhr.sentBody).toBeInstanceOf(FormData);
        // fetch 不被调用——上传进度路恒走 XHR
        expect(fetchSpy).not.toHaveBeenCalled();

        xhr.progress(512, 1024);
        xhr.progress(1024, 1024);
        xhr.respond(202, RESP);

        await expect(p).resolves.toMatchObject({ task_id: RESP.task_id });
        expect(prog).toHaveBeenNthCalledWith(1, 512, 1024);
        expect(prog).toHaveBeenNthCalledWith(2, 1024, 1024);
    });

    it("lengthComputable=false / total=0 事件不触发回调", async () => {
        const prog = vi.fn();
        const p = api.upload(
            new File(["x"], "a.tex"),
            undefined,
            undefined,
            prog,
        );
        const xhr = lastXhr();
        xhr.progress(100, 0, false);
        xhr.progress(100, 0);
        xhr.respond(202, RESP);
        await p;
        expect(prog).not.toHaveBeenCalled();
    });

    it("shareImport 同样回报进度", async () => {
        const prog = vi.fn();
        const p = api.shareImport(
            new File(["z"], "b.share.zip"),
            undefined,
            undefined,
            prog,
        );
        const xhr = lastXhr();
        expect(xhr.url).toBe("/api/share/import");
        xhr.progress(300, 600);
        xhr.respond(202, RESP);
        await p;
        expect(prog).toHaveBeenCalledWith(300, 600);
    });

    it("Idempotency-Key 自动生成 + BYOK 头经 setRequestHeader 发送", async () => {
        const p = api.upload(
            new File(["x"], "idem-up.tex"),
            undefined,
            { apiKey: "sk-xhr" },
            vi.fn(),
        );
        const xhr = lastXhr();
        expect(xhr.headers["Idempotency-Key"]).toMatch(/^[0-9a-z-]{20,}$/);
        expect(xhr.headers["X-Texlate-Key"]).toBe("sk-xhr");
        // multipart content-type 不手写（浏览器自产 boundary）
        expect(xhr.headers).not.toHaveProperty("content-type");
        xhr.respond(202, RESP);
        await p;
    });

    it("未决同文件重发复用同 key（XHR 路 idem 语义不变）", async () => {
        const file = new File(["x"], "idem-re.tex");
        const p1 = api.upload(file, undefined, undefined, vi.fn());
        const k1 = lastXhr().headers["Idempotency-Key"];
        lastXhr().onerror?.();
        await expect(p1).rejects.toThrow(TypeError);

        const p2 = api.upload(file, undefined, undefined, vi.fn());
        const k2 = lastXhr().headers["Idempotency-Key"];
        expect(k2).toBe(k1);
        lastXhr().respond(202, RESP);
        await p2;
    });

    it("xhr.timeout=UPLOAD_TIMEOUT_MS(10min)；ontimeout → TypeError，重发复用 key", async () => {
        const file = new File(["x"], "slow.tex");
        const p1 = api.upload(file, undefined, undefined, vi.fn());
        const xhr = lastXhr();
        // 10min：80MB 上限在 ~150KB/s 慢链约 9min 传完（rest.ts UPLOAD_TIMEOUT_MS）
        expect(xhr.timeout).toBe(600_000);
        const k1 = xhr.headers["Idempotency-Key"];

        xhr.ontimeout?.();
        await expect(p1).rejects.toThrow(TypeError);
        await expect(p1).rejects.toThrow("upload timeout");

        // TypeError 属「未决」——同文件重发复用同 key
        const p2 = api.upload(file, undefined, undefined, vi.fn());
        expect(lastXhr().headers["Idempotency-Key"]).toBe(k1);
        lastXhr().respond(202, RESP);
        await p2;
    });

    it('abort → TypeError("upload aborted")，同文件重发复用 key', async () => {
        const file = new File(["x"], "abort.tex");
        const p1 = api.upload(file, undefined, undefined, vi.fn());
        const k1 = lastXhr().headers["Idempotency-Key"];

        lastXhr().abort();
        await expect(p1).rejects.toThrow(TypeError);
        await expect(p1).rejects.toThrow("upload aborted");

        const p2 = api.upload(file, undefined, undefined, vi.fn());
        expect(lastXhr().headers["Idempotency-Key"]).toBe(k1);
        lastXhr().respond(202, RESP);
        await p2;
    });

    it("HTTP 错误 → ApiError（detail/code 解析口径同 fetch 路）", async () => {
        const p = api.upload(
            new File(["x"], "bad.tex"),
            undefined,
            undefined,
            vi.fn(),
        );
        lastXhr().respond(422, {
            detail: "unsupported_format",
            code: "unsupported_format",
        });
        await expect(p).rejects.toSatisfy(
            (e) =>
                e instanceof ApiError &&
                e.status === 422 &&
                e.detail === "unsupported_format" &&
                e.code === "unsupported_format",
        );
    });

    it("无 onProgress → 仍走 fetch（既有契约：XHR 仅在需要进度时启用）", async () => {
        fetchSpy.mockResolvedValue(
            new Response(JSON.stringify(RESP), {
                status: 202,
                headers: { "content-type": "application/json" },
            }),
        );
        await api.upload(new File(["x"], "nofetch.tex"));
        expect(fetchSpy).toHaveBeenCalledOnce();
        expect(FakeXHR.instances).toHaveLength(0);
    });
});
