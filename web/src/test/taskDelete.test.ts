import { beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
    tasks: vi.fn(),
    deleteTask: vi.fn(),
    openTaskEvents: vi.fn(),
}));

vi.mock("../api/client", async (importOriginal) => {
    const mod = await importOriginal<typeof import("../api/client")>();
    return {
        ...mod,
        api: { ...mod.api, tasks: mocks.tasks, deleteTask: mocks.deleteTask },
        openTaskEvents: mocks.openTaskEvents,
    };
});

import { ApiError, type TaskSnapshot } from "../api/client";
import { taskStore } from "../stores/tasks";
import { snap as fakeSnap } from "./fakes";

// (id, status="done") 签名保留——缺省面与 fakes.snap 全同形
const snap = (
    id: string,
    status: TaskSnapshot["status"] = "done",
): TaskSnapshot => fakeSnap(id, { status });

beforeEach(() => {
    mocks.tasks.mockReset();
    mocks.deleteTask.mockReset().mockResolvedValue(undefined);
    mocks.openTaskEvents.mockReset().mockReturnValue({ close: vi.fn(), closed: false });
});

describe("taskStore.remove（DELETE /task/{id} + 本地移除）", () => {
    it("终态任务删除：调用 deleteTask 并从列表移除", async () => {
        mocks.tasks.mockResolvedValue([snap("t_a"), snap("t_b")]);
        await taskStore.refresh();

        await taskStore.remove("t_a");

        expect(mocks.deleteTask).toHaveBeenCalledTimes(1);
        expect(mocks.deleteTask).toHaveBeenCalledWith("t_a");
        expect(taskStore.task("t_a")).toBeUndefined();
        expect(taskStore.state.tasks.map((t) => t.task_id)).toEqual(["t_b"]);
    });

    it("在途任务删除：同时断开 SSE channel 并清 live 条目", async () => {
        mocks.tasks.mockResolvedValue([snap("t_live", "translating")]);
        await taskStore.refresh();
        expect(mocks.openTaskEvents).toHaveBeenCalledWith("t_live", expect.anything());
        expect(taskStore.live("t_live")).toBeDefined();

        await taskStore.remove("t_live");

        const ch = mocks.openTaskEvents.mock.results[0].value;
        expect(ch.close).toHaveBeenCalled();
        expect(taskStore.live("t_live")).toBeUndefined();
        expect(taskStore.task("t_live")).toBeUndefined();
    });

    it("后端 404 视为已删：不抛错，本地照常移除", async () => {
        mocks.tasks.mockResolvedValue([snap("t_gone")]);
        await taskStore.refresh();
        mocks.deleteTask.mockRejectedValueOnce(new ApiError(404, "task not found"));

        await expect(taskStore.remove("t_gone")).resolves.toBeUndefined();
        expect(taskStore.task("t_gone")).toBeUndefined();
    });

    it("其他错误（如 500）：向上抛出且本地保留", async () => {
        mocks.tasks.mockResolvedValue([snap("t_err")]);
        await taskStore.refresh();
        mocks.deleteTask.mockRejectedValueOnce(new ApiError(500, "boom"));

        await expect(taskStore.remove("t_err")).rejects.toThrow("boom");
        expect(taskStore.task("t_err")).toBeDefined();
    });
});
