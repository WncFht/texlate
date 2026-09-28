import { describe, expect, it } from "vitest";
import { DB_TO_URL_KIND } from "../api/client";
import { t } from "../i18n";
import { t as tZh } from "../i18n/zh";
import { t as tEn } from "../i18n/en";

// zh.ts 是 Record 段（status/kind/files）的唯一事实源——服务端词表扩张时
// 这些断言先于 UI 空白处报警。词表以 server/store.py 与 client.ts 类型为准。

/** 深度遍历叶子：visit(path, value)；非对象的值都算叶（string/number/…） */
const walkLeaves = (
    o: Record<string, unknown>,
    path: string,
    visit: (path: string, value: unknown) => void,
): void => {
    for (const [k, v] of Object.entries(o)) {
        const p = path ? `${path}.${k}` : k;
        if (v && typeof v === "object") {
            walkLeaves(v as Record<string, unknown>, p, visit);
        } else {
            visit(p, v);
        }
    }
};

const keySet = (o: Record<string, unknown>): string[] => {
    const keys: string[] = [];
    walkLeaves(o, "", (p) => keys.push(p));
    return keys;
};

const expectNonEmptyLeaves = (o: Record<string, unknown>) =>
    walkLeaves(o, "", (p, v) => {
        if (typeof v === "string")
            expect(v.trim().length, p).toBeGreaterThan(0);
    });

describe("en/zh —— 键级 parity（Record 段 typeof 守不到，靠这里）", () => {
    it("en.ts 与 zh.ts 叶子键集合完全一致", () => {
        expect(
            keySet(tEn as unknown as Record<string, unknown>).sort(),
        ).toEqual(keySet(tZh as unknown as Record<string, unknown>).sort());
    });
    it("en.ts 无空文案叶", () => {
        expectNonEmptyLeaves(tEn as unknown as Record<string, unknown>);
    });
});

describe("t.status —— 服务端状态/阶段词表全覆盖", () => {
    it("pipeline 阶段 + 终态 + needs_auth 全部有文案", () => {
        const vocab = [
            "queued",
            "fetching",
            "parsing",
            "translating",
            "compiling",
            "done",
            "partial",
            "fault",
            "cancelled",
            "interrupted",
            "needs_auth",
        ];
        for (const k of vocab) expect(t.status[k], k).toBeTruthy();
    });
});

describe("t.kind —— 任务类型词表全覆盖", () => {
    it("TaskKind 联合 + share 包全部有文案", () => {
        const vocab = [
            "arxiv",
            "arxiv_html",
            "upload_tex",
            "upload_pdf",
            "docx",
            "epub",
            "share",
        ];
        for (const k of vocab) expect(t.kind[k], k).toBeTruthy();
    });
});

describe("t.files —— FileKind 全覆盖", () => {
    it("DB_TO_URL_KIND 每个 url kind 都有标签", () => {
        for (const urlKind of Object.values(DB_TO_URL_KIND)) {
            expect(t.files[urlKind], urlKind).toBeTruthy();
        }
    });
});

describe("t —— 无空文案叶（防占位键混进 UI）", () => {
    it("所有叶子值非空且非纯空白", () => {
        expectNonEmptyLeaves(t as unknown as Record<string, unknown>);
    });
});
