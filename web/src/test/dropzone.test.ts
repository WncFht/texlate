// @vitest-environment jsdom
// home/dropzone 整页拖放：dragDepth 计数配平（子元素穿行不闪断）、
// 仅文件拖拽拦截、drop 的 busy 闸与失配 leave 钳位。

import { describe, expect, it, vi } from "vitest";

import { createHomeDropzone } from "../home/dropzone";

/** 假 DragEvent：dataTransfer.types/files 用数组即够（实现只展开读取） */
const dragEvent = (types: string[] = [], files: File[] = []) =>
    ({
        dataTransfer: { types, files },
        preventDefault: vi.fn(),
    }) as unknown as DragEvent;

const fileDrag = (files: File[] = [new File(["x"], "a.tex")]) =>
    dragEvent(["Files"], files);

const mk = (busy = false) => {
    const deps = {
        busy: () => busy,
        onBusyDrop: vi.fn(),
        onFiles: vi.fn(),
    };
    return { dz: createHomeDropzone(deps), deps };
};

describe("createHomeDropzone —— dragDepth 配平", () => {
    it("enter 进子元素再 leave 不闪断，配平归零才熄", () => {
        const { dz } = mk();
        expect(dz.dragOn()).toBe(false);
        dz.onDragEnter(fileDrag()); // 进入外层 depth=1
        expect(dz.dragOn()).toBe(true);
        dz.onDragEnter(fileDrag()); // 穿行进子元素 depth=2
        dz.onDragLeave(); // 离开子元素 depth=1 —— 仍亮
        expect(dz.dragOn()).toBe(true);
        dz.onDragLeave(); // 离开外层 depth=0 —— 熄
        expect(dz.dragOn()).toBe(false);
    });

    it("失配 leave 钳位 0：不吞掉后续 enter 的配平额度", () => {
        const { dz } = mk();
        dz.onDragLeave(); // 无 enter 先 leave —— 钳回 0 而非 -1
        expect(dz.dragOn()).toBe(false);
        dz.onDragEnter(fileDrag()); // depth=1
        dz.onDragEnter(fileDrag()); // depth=2（钳位生效：未欠账）
        dz.onDragLeave(); // depth=1 —— 仍亮
        expect(dz.dragOn()).toBe(true);
        dz.onDragLeave();
        expect(dz.dragOn()).toBe(false);
    });

    it("drop 归零计数并熄态", () => {
        const { dz, deps } = mk();
        dz.onDragEnter(fileDrag());
        dz.onDragEnter(fileDrag());
        dz.onDrop(fileDrag());
        expect(dz.dragOn()).toBe(false);
        expect(deps.onFiles).toHaveBeenCalledTimes(1);
        // 归零后一次 leave 不会复亮/欠账
        dz.onDragLeave();
        expect(dz.dragOn()).toBe(false);
    });
});

describe("createHomeDropzone —— 仅文件拖拽", () => {
    it("文本拖入不触发整页上传态、不 preventDefault", () => {
        const { dz } = mk();
        const e = dragEvent(["text/plain"]);
        dz.onDragEnter(e);
        expect(dz.dragOn()).toBe(false);
        expect(e.preventDefault).not.toHaveBeenCalled();
    });

    it("onDragOver：文件拖拽才 preventDefault（放行 drop）", () => {
        const { dz } = mk();
        const file = dragEvent(["Files"]);
        const text = dragEvent(["text/plain"]);
        dz.onDragOver(file);
        dz.onDragOver(text);
        expect(file.preventDefault).toHaveBeenCalledTimes(1);
        expect(text.preventDefault).not.toHaveBeenCalled();
    });

    it("无 Files 类型的 drop 直接忽略（不清态不回调）", () => {
        const { dz, deps } = mk();
        dz.onDragEnter(fileDrag());
        const e = dragEvent(["text/plain"]);
        dz.onDrop(e);
        expect(e.preventDefault).not.toHaveBeenCalled();
        expect(deps.onFiles).not.toHaveBeenCalled();
        expect(dz.dragOn()).toBe(true); // 文件拖拽仍在悬停
    });
});

describe("createHomeDropzone —— drop 闸", () => {
    it("busy 态落袋走 onBusyDrop 不透 onFiles", () => {
        const { dz, deps } = mk(true);
        dz.onDragEnter(fileDrag());
        const f = new File(["x"], "a.tex");
        dz.onDrop(fileDrag([f]));
        expect(deps.onBusyDrop).toHaveBeenCalledTimes(1);
        expect(deps.onFiles).not.toHaveBeenCalled();
        expect(dz.dragOn()).toBe(false); // drop 仍清拖拽态
    });

    it("空闲落袋透传 files 数组", () => {
        const { dz, deps } = mk();
        const fs = [new File(["a"], "a.tex"), new File(["b"], "b.tex")];
        dz.onDrop(fileDrag(fs));
        expect(deps.onFiles).toHaveBeenCalledWith(fs);
        expect(deps.onBusyDrop).not.toHaveBeenCalled();
    });

    it("空 files 落袋：清态但不回调（preventDefault 已做）", () => {
        const { dz, deps } = mk();
        const e = fileDrag([]);
        dz.onDrop(e);
        expect(e.preventDefault).toHaveBeenCalledTimes(1);
        expect(deps.onFiles).not.toHaveBeenCalled();
        expect(deps.onBusyDrop).not.toHaveBeenCalled();
    });
});
