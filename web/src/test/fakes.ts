// 共享 TaskSnapshot 工厂——各测试文件的 snap 手抄变体归一到此。
// status/progress 耦合保留：done → 100，其余 → 40（多数调用方依赖此形）。

import type { TaskSnapshot } from "../api/client";

export function snap(
    id: string,
    over: Partial<TaskSnapshot> = {},
): TaskSnapshot {
    const status = over.status ?? "done";
    return {
        task_id: id,
        kind: "arxiv",
        status,
        progress: over.progress ?? (status === "done" ? 100 : 40),
        created_at: 1_700_000_000,
        updated_at: 1_700_000_000,
        ...over,
    };
}
