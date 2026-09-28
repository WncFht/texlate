// @vitest-environment jsdom
// citeTranslate —— 引用文献翻译编排层测试面：
//   状态机全边（idle→queued→running→done|failed、failed→running 重试回边、
//   queued→failed 直跳、idle→done 直跳、终态→stage 新轮 runId 复位）；
//   refViewOf 行投影（4.3% 零事件帧兜底主路——无 live 帧行直读 status）；
//   translateBandPct 25-85 带 / ETA 区间与 fmtEta 文案形；
//   preflight 三桶（canon 双侧归一：钉版 vs 裸 id、URL 形 vs 存储 -- 形；
//   needs_auth→active；败终态→fresh）；
//   submit 分派（202 queued / 200 done / 200 needs_auth existing / 409 收编
//   taskId 双径 / 429 quota / 401 auth+retry 补 key / 凭证门不裸发）；
//   submitAll 批聚合 + 429 截断；ctText 双语兜底与计数模板；
//   canonRefId / extractRefIds 裸 DOI 臂；features 桥命令面。

import { describe, expect, it, vi } from "vitest";
import { ApiError, type TaskSnapshot } from "../api/client";
import { canonRefId, extractRefIds } from "../reader/cite/citations";
import {
    createCiteTranslate,
    createRefStatus,
    ctText,
    estimateEta,
    fmtEta,
    refViewOf,
    translateBandPct,
    type CiteTranslateDeps,
    type RefItem,
} from "../reader/cite/citeTranslate";
import { registerCiteTranslate } from "../reader/features/citetranslate";
import { Registry } from "../reader/cmd/cmdreg";
import type { CmdCtx } from "../reader/cmd/commands";
import RefTaskChip from "../reader/cards/RefTaskChip";
import { render } from "solid-js/web";
import { currentLang } from "../i18n";
import { snap } from "./fakes";

const tid = (n: number) => `t_${String(n).padStart(16, "0")}`;
const accepted = (n: number) => ({
    task_id: tid(n),
    status: "queued" as const,
    events_url: `/api/task/${tid(n)}/events`,
});

/** 默认依赖桶——全 spy，逐测试覆写需要项 */
const mkDeps = (over: Partial<CiteTranslateDeps> = {}) => {
    const post = vi.fn(async () => accepted(1));
    const list = vi.fn(async () => [] as TaskSnapshot[]);
    const track = vi.fn();
    const ok = vi.fn();
    const err = vi.fn();
    const deps: CiteTranslateDeps = {
        hasApiKey: () => true,
        postTranslate: post,
        listTasks: list,
        track,
        toastOk: ok,
        toastErr: err,
        ...over,
    };
    return { deps, post, list, track, ok, err };
};

// ---------------------------------------------------------------- canon

describe("canonRefId 双侧归一", () => {
    it.each([
        ["2401.00001", "2401.00001"],
        ["2401.00001v3", "2401.00001"], // 钉版剥 vN
        ["arXiv:2401.00001", "2401.00001"],
        ["https://arxiv.org/abs/2401.00001", "2401.00001"],
        ["https://arxiv.org/pdf/2401.00001v2.pdf", "2401.00001"],
        ["10.48550/arXiv.2401.00001", "2401.00001"],
        ["oai:arXiv.org:2401.00001", "2401.00001"],
        ["hep-th--9901001", "hep-th/9901001"], // safe_id 回流
        ["math.GT/0309136", "math/0309136"], // 旧式剥 class
        ["cs--9901001v2", "cs/9901001"],
        ["https://arxiv.org/abs/2401.00001?context=cs#x", "2401.00001"],
        ["  arXiv:2401.00001 [cs.CL] ", "2401.00001"], // 尾注+空白
    ])("%s → %s", (raw, want) => {
        expect(canonRefId(raw)).toBe(want);
    });
    it("空入参", () => {
        expect(canonRefId(undefined)).toBe("");
        expect(canonRefId(null)).toBe("");
        expect(canonRefId("   ")).toBe("");
    });
});

describe("extractRefIds 裸 DOI 臂", () => {
    it("doi={}/\\doi{} 无前缀形捕获", () => {
        expect(
            extractRefIds("Author et al. doi={10.1145/1234.5678}, 2020.").doi,
        ).toBe("10.1145/1234.5678");
        expect(extractRefIds("\\doi{10.1000/xyz}").doi).toBe("10.1000/xyz");
    });
    it("doi.org/ 前缀形 + 条界残尾剥除", () => {
        expect(
            extractRefIds("see https://doi.org/10.5555/abc-def. Next").doi,
        ).toBe("10.5555/abc-def");
    });
    it("无 DOI 文本不产", () => {
        expect(extractRefIds("plain bib entry no ids").doi).toBeUndefined();
    });
    it("arXiv 臂不破——新式 id 仍出", () => {
        expect(extractRefIds("arXiv:2401.00001").arxivId).toBe("2401.00001");
    });
});

// ---------------------------------------------------------------- 状态机

describe("createRefStatus 状态机全边", () => {
    it("idle→queued→running→done 主链", () => {
        const r = createRefStatus();
        expect(r.view().phase).toBe("idle");
        r.feedSnapshot(snap(tid(1), { status: "queued", queue_position: 3 }));
        expect(r.view()).toMatchObject({
            phase: "queued",
            pct: 0,
            queuePosition: 3,
        });
        r.feedStage("translating", 40);
        r.feedChunk(3, 10, 1);
        expect(r.view()).toMatchObject({ phase: "running", pct: 43 });
        r.feedDone("done");
        expect(r.view()).toMatchObject({ phase: "done", pct: 100 });
    });

    it("idle→done 直跳（行快照收敛——零帧任务）", () => {
        const r = createRefStatus();
        r.feedSnapshot(snap(tid(2), { status: "done" }));
        expect(r.view()).toMatchObject({
            phase: "done",
            pct: 100,
            status: "done",
        });
    });

    it("queued→failed 直跳（服务端拒队）", () => {
        const r = createRefStatus();
        r.feedSnapshot(snap(tid(3), { status: "queued" }));
        r.feedDone("fault");
        expect(r.view().phase).toBe("failed");
        expect(r.view().status).toBe("fault");
    });

    it("failed→running 重试回边——终态后 stage 帧 runId+1 且计数复位", () => {
        const r = createRefStatus();
        r.feedStage("translating", 50);
        r.feedChunk(4, 8, 2);
        r.feedDone("fault");
        expect(r.view()).toMatchObject({ phase: "failed", runId: 0 });
        r.feedStage("fetching", 0); // retry 新轮（同 append-only 流）
        const v = r.view();
        expect(v.phase).toBe("running");
        expect(v.runId).toBe(1);
        expect(r.state.done).toBe(0); // 计数器随轮复位
        expect(r.state.total).toBe(0);
        expect(r.state.failed).toBe(0);
    });

    it("translating 内 chunk 帧驱动 band 插值（帧不带 progress）", () => {
        const r = createRefStatus();
        r.feedStage("translating", 30); // stage 帧 progress 是锚点
        expect(r.pct).toBe(25); // done=0 → 25
        r.feedChunk(5, 10, 0);
        expect(r.pct).toBe(55); // 25+30
        r.feedChunk(10, 10, 0);
        expect(r.pct).toBe(85); // cap
    });

    it("败终态冻结末值锚点（failed pct=anchor 不回 0）", () => {
        const r = createRefStatus();
        r.feedStage("translating", 62);
        r.feedDone("interrupted");
        expect(r.pct).toBe(62);
    });
});

// ---------------------------------------------------------------- 行投影

describe("refViewOf 行投影（零帧兜底主路）", () => {
    it("无行 → idle", () => {
        expect(refViewOf(undefined)).toMatchObject({
            phase: "idle",
            pct: 0,
            taskId: undefined,
        });
    });
    it("queued 行 → queued + queuePos", () => {
        const v = refViewOf(
            snap(tid(1), { status: "queued", queue_position: 5 }),
        );
        expect(v).toMatchObject({ phase: "queued", pct: 0, queuePos: 5 });
    });
    it("在跑行直读 progress 列（无 live 帧也收敛）", () => {
        const v = refViewOf(
            snap(tid(2), { status: "translating", progress: 47 }),
        );
        expect(v).toMatchObject({ phase: "running", pct: 47 });
    });
    it("done/partial → done pct=100；partial 携 failedChunks", () => {
        expect(refViewOf(snap(tid(3), { status: "done" })).phase).toBe("done");
        const v = refViewOf(
            snap(tid(4), {
                status: "partial",
                counters: { done: 9, total: 10, failed: 2 } as never,
            }),
        );
        expect(v).toMatchObject({ phase: "done", pct: 100, failedChunks: 2 });
    });
    it("needs_auth → needsAuth（不交 failed 面）", () => {
        expect(refViewOf(snap(tid(5), { status: "needs_auth" })).phase).toBe(
            "needsAuth",
        );
    });
    it.each(["fault", "cancelled", "interrupted"] as const)(
        "败终态 %s → failed",
        (status) => {
            const v = refViewOf(snap(tid(6), { status, progress: 33 }));
            expect(v).toMatchObject({ phase: "failed", pct: 33 });
        },
    );
    it("live.chunk.failed 优先级高于行 counters", () => {
        const v = refViewOf(
            snap(tid(7), {
                status: "partial",
                counters: { failed: 1 } as never,
            }),
            {
                chunk: { done: 9, total: 10, cached: 0, failed: 4, items: [] },
                stages: [],
                chunkItems: [],
                logs: [],
                warnings: [],
                transport: "sse" as never,
            },
        );
        expect(v.failedChunks).toBe(4);
    });
});

// ---------------------------------------------------------------- band/ETA

describe("translateBandPct 与 ETA", () => {
    it("band: 25 起、60 分度、85 帽", () => {
        expect(translateBandPct(0, 10)).toBe(25);
        expect(translateBandPct(5, 10)).toBe(55);
        expect(translateBandPct(10, 10)).toBe(85);
        expect(translateBandPct(10, 5)).toBe(85); // 超帽钳
        expect(translateBandPct(0, 0)).toBe(25); // total=0 不 NaN
    });
    it("estimateEta 区间", () => {
        expect(estimateEta(1)).toEqual({ lo: 47, hi: 236 });
        expect(estimateEta(3)).toEqual({ lo: 141, hi: 708 });
    });
    it("fmtEta 文案形", () => {
        expect(fmtEta(47)).toBe("47s");
        expect(fmtEta(300)).toBe("5min");
        expect(fmtEta(3540)).toBe("1h");
        expect(fmtEta(5896)).toBe("1.6h");
        expect(fmtEta(14160)).toBe("3.9h");
    });
});

// ---------------------------------------------------------------- 提交分派

describe("submit 七态分派", () => {
    it("202 miss → queued + track + toast", async () => {
        const { deps, post, track, ok } = mkDeps();
        const ct = createCiteTranslate(deps);
        const o = await ct.submit("2401.00001");
        expect(o).toEqual({ kind: "queued", taskId: tid(1) });
        expect(track).toHaveBeenCalledWith(tid(1), "2401.00001");
        expect(ok).toHaveBeenCalledOnce();
        expect(post).toHaveBeenCalledOnce();
    });

    it("200 reused done → done（可直读）", async () => {
        const { deps, track } = mkDeps({
            postTranslate: vi.fn(async () => ({
                ...accepted(2),
                status: "done" as const,
                reused: true,
                cache: "hit",
            })),
        });
        const o = await createCiteTranslate(deps).submit("2401.00002");
        expect(o).toEqual({ kind: "done", taskId: tid(2) });
        expect(track).toHaveBeenCalledWith(tid(2), "2401.00002");
    });

    it("200 reused needs_auth → existing（收编既有行，不重建）", async () => {
        const { deps } = mkDeps({
            postTranslate: vi.fn(async () => ({
                ...accepted(3),
                status: "needs_auth" as const,
                reused: true,
            })),
        });
        const o = await createCiteTranslate(deps).submit("2401.00003");
        expect(o).toMatchObject({ kind: "existing", taskId: tid(3) });
    });

    it("409 结构化 task_id → existing + track", async () => {
        const { deps, track } = mkDeps({
            postTranslate: vi.fn(async () => {
                throw new ApiError(
                    409,
                    "duplicate",
                    "duplicate_active",
                    tid(9),
                );
            }),
        });
        const o = await createCiteTranslate(deps).submit("2401.00009");
        expect(o).toEqual({ kind: "existing", taskId: tid(9) });
        expect(track).toHaveBeenCalledWith(tid(9), "2401.00009");
    });

    it("409 无 taskId → detail 正则兜回包 id", async () => {
        const { deps } = mkDeps({
            postTranslate: vi.fn(async () => {
                throw new ApiError(
                    409,
                    `active task ${tid(7)} exists`,
                    "duplicate_active",
                );
            }),
        });
        const o = await createCiteTranslate(deps).submit("2401.00007");
        expect(o).toEqual({ kind: "existing", taskId: tid(7) });
    });

    it("429 → quota + toastErr", async () => {
        const { deps, err } = mkDeps({
            postTranslate: vi.fn(async () => {
                throw new ApiError(429, "quota", "quota_exceeded");
            }),
        });
        const o = await createCiteTranslate(deps).submit("2401.00010");
        expect(o).toEqual({ kind: "quota" });
        expect(err).toHaveBeenCalledOnce();
    });

    it("401 → auth 回执 + onNeedAuth；retry 补 X-Texlate-Key 重发", async () => {
        const needAuth = vi.fn();
        const post = vi
            .fn()
            .mockRejectedValueOnce(new ApiError(401, "auth", "auth_required"))
            .mockResolvedValueOnce(accepted(11));
        const { deps } = mkDeps({ postTranslate: post, onNeedAuth: needAuth });
        const ct = createCiteTranslate(deps);
        const o = await ct.submit("2401.00011");
        expect(o.kind).toBe("auth");
        expect(needAuth).toHaveBeenCalledOnce();
        if (o.kind !== "auth") throw new Error("unreachable");
        const o2 = await o.retry("sk-test");
        expect(o2).toEqual({ kind: "queued", taskId: tid(11) });
        expect(post).toHaveBeenLastCalledWith(
            "2401.00011",
            expect.anything(),
            expect.objectContaining({ apiKey: "sk-test" }),
        );
        expect(ct.sessionKey()).toBe("sk-test");
    });

    it("凭证门：has_api_key===false 且不持 key → 不裸发 POST", async () => {
        const needAuth = vi.fn();
        const { deps, post } = mkDeps({
            hasApiKey: () => false,
            onNeedAuth: needAuth,
        });
        const o = await createCiteTranslate(deps).submit("2401.00012");
        expect(o.kind).toBe("auth");
        expect(post).not.toHaveBeenCalled();
        expect(needAuth).toHaveBeenCalledOnce();
    });

    it("门后收 key → sessionKey 记忆，后续提交免问", async () => {
        let hostRetry: ((k: string) => Promise<void>) | undefined;
        const { deps, post } = mkDeps({
            hasApiKey: () => false,
            onNeedAuth: (r) => {
                hostRetry = r;
            },
        });
        const ct = createCiteTranslate(deps);
        const o = await ct.submit("2401.00013");
        expect(o.kind).toBe("auth");
        await hostRetry!("sk-mem");
        expect(post).toHaveBeenCalledWith(
            "2401.00013",
            expect.anything(),
            expect.objectContaining({ apiKey: "sk-mem" }),
        );
        // 第二条提交不再过门（sessionKey 已立）
        await ct.submit("2401.00014");
        expect(post).toHaveBeenCalledTimes(2);
        expect(post).toHaveBeenLastCalledWith(
            "2401.00014",
            expect.anything(),
            expect.objectContaining({ apiKey: "sk-mem" }),
        );
    });

    it("401 但无宿主 → err toast 兜底（toastAuth 文案）", async () => {
        const { deps, err } = mkDeps({
            postTranslate: vi.fn(async () => {
                throw new ApiError(401, "auth", "auth_required");
            }),
        });
        const o = await createCiteTranslate(deps).submit("2401.00015");
        expect(o.kind).toBe("auth");
        expect(err).toHaveBeenCalledWith(ctText("toastAuth"));
    });

    it("400/网络错 → error 回执携 message", async () => {
        const { deps, err } = mkDeps({
            postTranslate: vi.fn(async () => {
                throw new ApiError(400, "bad arxiv id", "invalid");
            }),
        });
        const o = await createCiteTranslate(deps).submit("bogus");
        expect(o).toMatchObject({ kind: "error", message: "bad arxiv id" });
        expect(err).toHaveBeenCalledWith("bad arxiv id");
    });
});

// ---------------------------------------------------------------- 批量

describe("submitAll 批聚合", () => {
    const items = (...ids: string[]): RefItem[] =>
        ids.map((arxivId) => ({ arxivId }));

    it("202/200done/409 混桶 → submitted/absorbed 分计", async () => {
        const post = vi
            .fn()
            .mockResolvedValueOnce(accepted(1)) // 新入队
            .mockResolvedValueOnce({
                ...accepted(2),
                status: "done" as const,
                reused: true,
            }) // 已有译文
            .mockRejectedValueOnce(
                new ApiError(409, "dup", "duplicate_active", tid(3)),
            ); // 在跑收编
        const { deps } = mkDeps({ postTranslate: post });
        const out = await createCiteTranslate(deps).submitAll(
            items("2401.1", "2401.2", "2401.3"),
        );
        expect(out).toMatchObject({ submitted: 1, absorbed: 2 });
        expect(out.failed).toEqual([]);
        expect(out.stoppedBy).toBeUndefined();
    });

    it("429 即停——已提交计数进 toastBatchQuota {k,n}", async () => {
        const post = vi
            .fn()
            .mockResolvedValueOnce(accepted(1))
            .mockRejectedValueOnce(new ApiError(429, "quota", "quota_exceeded"))
            .mockResolvedValueOnce(accepted(4));
        const { deps, err } = mkDeps({ postTranslate: post });
        const out = await createCiteTranslate(deps).submitAll(
            items("a", "b", "c"),
        );
        expect(out).toMatchObject({
            submitted: 1,
            stoppedBy: "quota",
        });
        expect(post).toHaveBeenCalledTimes(2); // 第三条不发
        expect(err).toHaveBeenCalledWith(
            ctText("toastBatchQuota", { k: 1, n: 3 }),
        );
    });

    it("凭证门 → stoppedBy=auth，收 key 后续跑剩余臂", async () => {
        let hostRetry: ((k: string) => Promise<void>) | undefined;
        const post = vi.fn(async () => accepted(5));
        const { deps } = mkDeps({
            hasApiKey: () => false,
            postTranslate: post,
            onNeedAuth: (r) => {
                hostRetry = r;
            },
        });
        const ct = createCiteTranslate(deps);
        const out = await ct.submitAll(items("a", "b"));
        expect(out).toMatchObject({ submitted: 0, stoppedBy: "auth" });
        await hostRetry!("sk-batch");
        // 续跑整批（断点 slice 原 items 全量——门在首条前）
        expect(post).toHaveBeenCalledTimes(2);
        expect(post).toHaveBeenLastCalledWith(
            "b",
            expect.anything(),
            expect.objectContaining({ apiKey: "sk-batch" }),
        );
    });

    it("批内 401 半途 → 断点续跑（已发不重发）", async () => {
        let hostRetry: ((k: string) => Promise<void>) | undefined;
        const post = vi
            .fn()
            .mockResolvedValueOnce(accepted(1))
            .mockRejectedValueOnce(new ApiError(401, "auth", "auth_required"))
            .mockResolvedValue(accepted(6));
        const { deps } = mkDeps({
            postTranslate: post,
            onNeedAuth: (r) => {
                hostRetry = r;
            },
        });
        const out = await createCiteTranslate(deps).submitAll(
            items("a", "b", "c"),
        );
        expect(out).toMatchObject({ submitted: 1, stoppedBy: "auth" });
        await hostRetry!("sk-mid");
        // a / b(401) / b(续) / c(续) —— 已发的 a 不重发，断点 b 起续
        expect(post).toHaveBeenCalledTimes(4);
        expect(post.mock.calls[2][0]).toBe("b");
        expect(post.mock.calls[3][0]).toBe("c");
    });

    it("错误条目收 failed 明细不中断后续", async () => {
        const post = vi
            .fn()
            .mockRejectedValueOnce(new ApiError(400, "bad id", "invalid"))
            .mockResolvedValueOnce(accepted(8));
        const { deps } = mkDeps({ postTranslate: post });
        const out = await createCiteTranslate(deps).submitAll(items("x", "y"));
        expect(out.submitted).toBe(1);
        expect(out.failed).toEqual([{ arxivId: "x", message: "bad id" }]);
    });
});

// ---------------------------------------------------------------- preflight

describe("preflight 三桶（canon 双侧）", () => {
    it("钉版 item 撞裸 id 行 / URL 形撞存储 -- 形", async () => {
        const rows = [
            snap(tid(1), { status: "done", arxiv_id: "2401.00001" }), // 裸 id 行
            snap(tid(2), {
                status: "translating",
                arxiv_id: "hep-th--9901001",
            }), // 存储形行
        ];
        const { deps } = mkDeps({ listTasks: vi.fn(async () => rows) });
        const b = await createCiteTranslate(deps).preflight([
            { arxivId: "2401.00001v2" }, // 钉版 → done 桶
            { arxivId: "https://arxiv.org/abs/hep-th/9901001" }, // URL → active
            { arxivId: "2401.00002" }, // 无行 → fresh
        ]);
        expect(b.done.map((r) => r.item.arxivId)).toEqual(["2401.00001v2"]);
        expect(b.active.map((r) => r.item.arxivId)).toEqual([
            "https://arxiv.org/abs/hep-th/9901001",
        ]);
        expect(b.fresh.map((i) => i.arxivId)).toEqual(["2401.00002"]);
        expect(b.counts).toEqual({ total: 3, done: 1, active: 1, fresh: 1 });
    });

    it("needs_auth 行归 active（重提收编，补 key 走 retry）", async () => {
        const rows = [snap(tid(1), { status: "needs_auth", arxiv_id: "x1" })];
        const { deps } = mkDeps({ listTasks: vi.fn(async () => rows) });
        const b = await createCiteTranslate(deps).preflight([
            { arxivId: "x1" },
        ]);
        expect(b.active).toHaveLength(1);
        expect(b.fresh).toHaveLength(0);
    });

    it("败终态行归 fresh（重提真建行）", async () => {
        for (const status of ["fault", "cancelled", "interrupted"] as const) {
            const { deps } = mkDeps({
                listTasks: vi.fn(async () => [
                    snap(tid(1), { status, arxiv_id: "x9" }),
                ]),
            });
            const b = await createCiteTranslate(deps).preflight([
                { arxivId: "x9" },
            ]);
            expect(b.fresh).toHaveLength(1);
            expect(b.done).toHaveLength(0);
        }
    });

    it("同 id 多行取档序：可读终态 > 在跑 > 败终态（同档 updated_at 新先）", async () => {
        const rows = [
            snap(tid(1), {
                status: "fault",
                arxiv_id: "x5",
                updated_at: 100,
            }),
            snap(tid(2), {
                status: "partial",
                arxiv_id: "x5",
                updated_at: 50, // 更早但档高
            }),
        ];
        const { deps } = mkDeps({ listTasks: vi.fn(async () => rows) });
        const b = await createCiteTranslate(deps).preflight([
            { arxivId: "x5" },
        ]);
        expect(b.done[0]?.row.task_id).toBe(tid(2));
    });
});

// ---------------------------------------------------------------- 文案

describe("ctText 双语兜底与计数模板", () => {
    const zh = currentLang() === "zh"; // jsdom navigator=en-US → en 兜底
    it("cite 扩展键（未合入走内置兜底）", () => {
        expect(ctText("cite.translate")).toBe(zh ? "翻译此文" : "Translate");
        expect(ctText("cite.openZh")).toBe(
            zh ? "打开译文" : "Open translation",
        );
    });
    it("counts 模板计数插值", () => {
        const s = ctText("counts", {
            total: 7,
            n_new: 4,
            n_active: 2,
            n_done: 1,
        });
        expect(s).toContain("7");
        expect(s).toContain("4");
        expect(s).toContain("2");
        expect(s).toContain("1");
        expect(s).not.toContain("{");
    });
    it("warnBig / cta / waitEta 模板", () => {
        expect(ctText("cta", { n: 5 })).toBe(zh ? "翻译 5 篇" : "Translate 5");
        expect(ctText("waitEta", { lo: "47s", hi: "4min" })).toContain("47s");
        expect(ctText("warnBig", { n: 20, lo: "15min", hi: "1.3h" })).toContain(
            "20",
        );
    });
});

// ---------------------------------------------------------------- features 桥

describe("registerCiteTranslate 桥", () => {
    const mkIndex = (entries: { key: string; arxivId?: string }[]) => ({
        size: entries.length,
        entries: () =>
            entries.map(
                (e, i) =>
                    ({
                        key: e.key,
                        order: i + 1,
                        label: `[${i + 1}]`,
                        text: `text ${e.key}`,
                        arxivId: e.arxivId,
                    }) as never,
            ),
        lookup: () => undefined,
    });

    it("注册 2 命令 + dispose 幂等摘除", () => {
        const reg = new Registry<CmdCtx>();
        const f = registerCiteTranslate(reg, {
            citeIndex: () => mkIndex([{ key: "a", arxivId: "2401.1" }]),
            postTranslate: vi.fn(async () => accepted(1)),
        });
        expect(reg.get("cite.translate")).toBeTruthy();
        expect(reg.get("cite.refsAll")).toBeTruthy();
        f.dispose();
        expect(reg.get("cite.translate")).toBeUndefined();
        expect(reg.get("cite.refsAll")).toBeUndefined();
    });

    it("refsCount=L1+L2 反补并集（DOI-only 经 meta.arxivId 计入）", () => {
        const idx = mkIndex([
            { key: "a", arxivId: "2401.1" },
            { key: "b" }, // DOI-only——L2 meta 反补
            { key: "c" }, // 无 id 不计
        ]);
        const f = registerCiteTranslate(new Registry<CmdCtx>(), {
            citeIndex: () => idx,
            citeMeta: (k) =>
                k === "b" ? ({ arxivId: "2401.2" } as never) : undefined,
        });
        expect(f.refsTotal()).toBe(3);
        expect(f.refsCount()).toBe(2);
        expect(f.translatable().map((i) => i.arxivId)).toEqual([
            "2401.1",
            "2401.2",
        ]);
    });

    it("cite.translate 命令 run → ct.submit(hit.cite.arxivId)", async () => {
        const post = vi.fn(async () => accepted(3));
        const reg = new Registry<CmdCtx>();
        registerCiteTranslate(reg, {
            citeIndex: () => mkIndex([]),
            postTranslate: post,
        });
        const ctx = {
            hit: { cite: { arxivId: "2401.00001" } },
            deps: {},
        } as unknown as CmdCtx;
        await reg.get("cite.translate")!.run(ctx);
        expect(post).toHaveBeenCalledWith(
            "2401.00001",
            expect.anything(),
            undefined,
        );
    });

    it("cite.refsAll → openRefsPanel 信号", () => {
        const open = vi.fn();
        const reg = new Registry<CmdCtx>();
        registerCiteTranslate(reg, {
            citeIndex: () => mkIndex([]),
            openRefsPanel: open,
        });
        reg.get("cite.refsAll")!.run({} as CmdCtx);
        expect(open).toHaveBeenCalledOnce();
    });

    it("task() 行透传翻译体（model/lang/glossary/options）", async () => {
        const post = vi.fn(async () => accepted(4));
        const f = registerCiteTranslate(new Registry<CmdCtx>(), {
            citeIndex: () => mkIndex([{ key: "a", arxivId: "2401.9" }]),
            task: () =>
                snap(tid(0), {
                    model: "m-x",
                    target_lang: "zh",
                    glossary: "g.tex",
                    options: { concurrency: 2, idempotency_key: "STRIP" },
                }),
            postTranslate: post,
        });
        await f.translateEntry({ arxivId: "2401.9" });
        expect(post).toHaveBeenCalledWith(
            "2401.9",
            {
                model: "m-x",
                target_lang: "zh",
                glossary: "g.tex",
                options: { concurrency: 2 }, // idempotency_key 已摘
            },
            undefined,
        );
    });

    it("translateEntry 无 id 条目 → undefined 不发帖", async () => {
        const post = vi.fn(async () => accepted(5));
        const f = registerCiteTranslate(new Registry<CmdCtx>(), {
            citeIndex: () => mkIndex([]),
            postTranslate: post,
        });
        expect(await f.translateEntry({ key: "noid" })).toBeUndefined();
        expect(post).not.toHaveBeenCalled();
    });
});

// ---------------------------------------------------------------- chip 渲染

describe("RefTaskChip 行投影渲染", () => {
    const mount = (props: Parameters<typeof RefTaskChip>[0]) => {
        const dispose = render(() => RefTaskChip(props), document.body);
        return dispose;
    };
    const chipEl = () =>
        document.body.querySelector<HTMLElement>(".ref-task-chip");

    it("idle 无 onTranslate → 不渲 chip", () => {
        const d = mount({ arxivId: "x-none", task: () => undefined });
        expect(chipEl()).toBeNull();
        d();
    });

    it("idle + onTranslate → 「翻译此文」钮，点击回调", () => {
        const onT = vi.fn();
        const d = mount({
            arxivId: "x-idle",
            task: () => undefined,
            onTranslate: onT,
        });
        const el = chipEl()!;
        expect(el.tagName).toBe("BUTTON");
        expect(el.textContent).toContain(ctText("cite.translate"));
        el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        expect(onT).toHaveBeenCalledOnce();
        d();
    });

    it("done 行 → <a href=#/reader/{tid}>「打开译文」", () => {
        const d = mount({
            arxivId: "x-done",
            task: () => snap(tid(4), { status: "done" }),
            live: () => undefined,
        });
        const el = chipEl()!;
        expect(el.tagName).toBe("A");
        expect(el.getAttribute("href")).toBe(`#/reader/${tid(4)}`);
        expect(el.textContent).toContain(ctText("cite.openZh"));
        d();
    });

    it("partial 行 → done 相 + failedChunks 角标", () => {
        const d = mount({
            arxivId: "x-partial",
            task: () =>
                snap(tid(5), {
                    status: "partial",
                    counters: { done: 8, total: 10, failed: 3 } as never,
                }),
            live: () => undefined,
        });
        const el = chipEl()!;
        expect(el.classList.contains("is-done")).toBe(true);
        const badge = el.querySelector(".ref-chip-badge")!;
        expect(badge.textContent).toContain("3");
        d();
    });

    it("needs_auth 行 → 输 Key CTA（默认跳 reader 页）", () => {
        const d = mount({
            arxivId: "x-auth",
            task: () => snap(tid(6), { status: "needs_auth" }),
            live: () => undefined,
        });
        const el = chipEl()!;
        expect(el.textContent).toContain(ctText("authKeyCta"));
        const onAuth = vi.fn();
        d();
        const d2 = mount({
            arxivId: "x-auth",
            task: () => snap(tid(6), { status: "needs_auth" }),
            live: () => undefined,
            onAuth,
        });
        chipEl()!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        expect(onAuth).toHaveBeenCalledWith(tid(6));
        d2();
    });

    it("fault 行 → ↻ 重试（默认 retry 通道）", () => {
        const d = mount({
            arxivId: "x-fault",
            task: () => snap(tid(7), { status: "fault", progress: 55 }),
            live: () => undefined,
        });
        const el = chipEl()!;
        expect(el.classList.contains("is-failed")).toBe(true);
        expect(el.textContent).toContain(ctText("cite.retryRef"));
        d();
    });

    it("queued 行 → 禁用态 chip（不入点击路）", () => {
        const onT = vi.fn();
        const d = mount({
            arxivId: "x-q",
            task: () => snap(tid(8), { status: "queued", queue_position: 2 }),
            live: () => undefined,
            onTranslate: onT,
        });
        const el = chipEl() as HTMLButtonElement;
        expect(el.disabled).toBe(true);
        expect(el.textContent).toContain(ctText("cite.queued"));
        el.dispatchEvent(new MouseEvent("click", { bubbles: true }));
        expect(onT).not.toHaveBeenCalled();
        d();
    });
});
